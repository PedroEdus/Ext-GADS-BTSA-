"""Extração massiva Google Ads -> BigQuery, com SAVEPOINTS + THREADS.

Espelha o padrão do projeto GA4 (Extração Massiva Analytics.py):
- 1 checkpoint CSV por conta em gads_checkpoints/
- retoma de onde parou (pula dias já extraídos) — savepoint
- salva o checkpoint imediatamente a cada dia
- ThreadPoolExecutor paraleliza entre as contas
- retry com backoff em rate limit / erros transitórios
- ao fim: merge dos checkpoints -> RAW (WRITE_TRUNCATE) + registro da carga

    python etl/extracao_massiva.py
    python etl/extracao_massiva.py --inicio 2025-01-01 --fim 2026-05-31 --workers 5
    python etl/extracao_massiva.py --sem-bq        # só extrai p/ CSV, não carrega no BQ
"""

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from dotenv import load_dotenv
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.cloud import bigquery

load_dotenv()

PROJECT_ID     = "buriti-marketing-analytics"
DATASET_RAW    = "buriti_marketing_raw"
DATASET_SILV   = "buriti_marketing_silver"
TABLE_RAW      = f"{PROJECT_ID}.{DATASET_RAW}.google_ads_raw"
TABLE_AUDIT    = f"{PROJECT_ID}.{DATASET_SILV}.controle_cargas_google_ads"

ARQUIVO_CONTAS = "contas.json"
CHECKPOINT_DIR = "gads_checkpoints"
OUT_DIR        = "gads_out"
API_VERSION    = "v20"

DEDUP_KEYS = ["customer_id", "date", "campaign_id"]

NUM_INT   = ["customer_id", "campaign_id", "impressions", "clicks"]
NUM_FLOAT = ["cost", "conversions", "conversions_value"]

GAQL = """
    SELECT
        segments.date,
        customer.id,
        customer.descriptive_name,
        campaign.id,
        campaign.name,
        campaign.status,
        campaign.advertising_channel_type,
        metrics.impressions,
        metrics.clicks,
        metrics.cost_micros,
        metrics.conversions,
        metrics.conversions_value
    FROM campaign
    WHERE segments.date = '{dia}'
"""

os.makedirs(CHECKPOINT_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)


# ============================================================
# CHECKPOINT HELPERS (savepoint por conta)
# ============================================================
def checkpoint_path(cid: str) -> str:
    return os.path.join(CHECKPOINT_DIR, f"{cid}.csv")


def load_checkpoint_dates(cid: str) -> set:
    """Datas já extraídas para essa conta."""
    path = checkpoint_path(cid)
    if os.path.exists(path):
        df = pd.read_csv(path, dtype=str)
        if "date" in df.columns:
            return set(df["date"].unique())
    return set()


def save_checkpoint(cid: str, df_new: pd.DataFrame) -> None:
    """Append incremental no checkpoint da conta, deduplicando."""
    path = checkpoint_path(cid)
    if os.path.exists(path):
        df_old = pd.read_csv(path, dtype=str)
        df_all = pd.concat([df_old, df_new.astype(str)], ignore_index=True)
        df_all = df_all.drop_duplicates(subset=DEDUP_KEYS, keep="last")
    else:
        df_all = df_new.astype(str)
    df_all.to_csv(path, index=False, encoding="utf-8")


def marcar_dia_vazio(cid: str, dia: str, nome: str) -> None:
    """Registra um dia sem dados para não re-consultar (savepoint de dia vazio)."""
    df = pd.DataFrame([{
        "date": dia, "customer_id": cid, "customer_name": nome,
        "campaign_id": "", "campaign_name": "", "campaign_status": "",
        "advertising_channel_type": "", "impressions": "0", "clicks": "0",
        "cost": "0", "conversions": "0", "conversions_value": "0",
    }])
    save_checkpoint(cid, df)


# ============================================================
# EXTRAÇÃO (1 dia, com retry)
# ============================================================
def extrair_dia(client: GoogleAdsClient, cid: str, nome: str, dia: str, retries: int = 5) -> pd.DataFrame:
    ga_service = client.get_service("GoogleAdsService")
    query = GAQL.format(dia=dia)

    for attempt in range(retries):
        try:
            stream = ga_service.search_stream(customer_id=cid, query=query)
            linhas = []
            for batch in stream:
                for r in batch.results:
                    linhas.append({
                        "date":                     r.segments.date,
                        "customer_id":              r.customer.id,
                        "customer_name":            r.customer.descriptive_name,
                        "campaign_id":              r.campaign.id,
                        "campaign_name":            r.campaign.name,
                        "campaign_status":          r.campaign.status.name,
                        "advertising_channel_type": r.campaign.advertising_channel_type.name,
                        "impressions":              r.metrics.impressions,
                        "clicks":                   r.metrics.clicks,
                        "cost":                     r.metrics.cost_micros / 1_000_000,
                        "conversions":              r.metrics.conversions,
                        "conversions_value":        r.metrics.conversions_value,
                    })
            return pd.DataFrame(linhas)
        except GoogleAdsException as ex:
            msg = ex.failure.errors[0].message if ex.failure.errors else str(ex)
            transitorio = any(k in msg.upper() for k in ("RESOURCE_EXHAUSTED", "INTERNAL", "DEADLINE"))
            if transitorio and attempt < retries - 1:
                wait = 10 * (attempt + 1)
                print(f"    [retry {attempt+1}] {cid} {dia} — {wait}s ({msg[:50]})")
                time.sleep(wait)
            else:
                raise


def extrair_conta(cid: str, nome: str, dias: list[str]) -> int:
    """Extrai todos os dias pendentes de uma conta. Roda em uma thread."""
    client = GoogleAdsClient.load_from_storage("google-ads.yaml", version=API_VERSION)

    done = load_checkpoint_dates(cid)
    pendentes = [d for d in dias if d not in done]
    if not pendentes:
        return 0

    novos = 0
    for dia in pendentes:
        try:
            df = extrair_dia(client, cid, nome, dia)
            if df is not None and not df.empty:
                save_checkpoint(cid, df)
                novos += len(df)
            else:
                marcar_dia_vazio(cid, dia, nome)
        except Exception as e:
            print(f"  [{cid}] ERRO {dia} — {str(e)[:80]}")
            # não quebra a thread — segue pro próximo dia
        time.sleep(0.05)
    return novos


# ============================================================
# MERGE + CARGA NO BIGQUERY
# ============================================================
def merge_checkpoints() -> pd.DataFrame:
    frames = []
    for f in os.listdir(CHECKPOINT_DIR):
        if f.endswith(".csv"):
            df = pd.read_csv(os.path.join(CHECKPOINT_DIR, f), dtype=str)
            if not df.empty:
                frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    # remove linhas-marcador de dia vazio (sem campanha)
    df = df[df["campaign_id"].astype(str) != ""]
    return df


def _tipar(df: pd.DataFrame) -> pd.DataFrame:
    for c in NUM_INT:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype("int64")
    for c in NUM_FLOAT:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype(float)
    return df


def carregar_bq(df: pd.DataFrame, inicio: str, fim: str) -> None:
    client = bigquery.Client(project=PROJECT_ID)
    df = _tipar(df)
    df["_loaded_at"] = datetime.now(timezone.utc)

    job = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    client.load_table_from_dataframe(df, TABLE_RAW, job_config=job).result()

    audit = pd.DataFrame([{
        "fonte": "google_ads", "periodo_ini": inicio, "periodo_fim": fim,
        "qtd_linhas": len(df), "carregado_em": datetime.now(timezone.utc),
        "status": "OK (massiva)",
    }])
    client.load_table_from_dataframe(
        audit, TABLE_AUDIT, job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    ).result()
    print(f"[OK] {len(df)} linhas carregadas (WRITE_TRUNCATE) em {TABLE_RAW}")


# ============================================================
# MAIN
# ============================================================
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inicio", default="2025-01-01")
    parser.add_argument("--fim", default=(date.today() - timedelta(days=1)).isoformat())
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--sem-bq", action="store_true", help="só extrai CSV, não carrega no BQ")
    args = parser.parse_args()

    contas = json.load(open(ARQUIVO_CONTAS, encoding="utf-8"))
    dias = pd.date_range(args.inicio, args.fim).strftime("%Y-%m-%d").tolist()

    print(f"Contas: {len(contas)} | Período: {args.inicio} -> {args.fim} | "
          f"Dias: {len(dias)} | Workers: {args.workers}\n")

    completed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(extrair_conta, c["id"], c.get("nome", ""), dias): c
            for c in contas
        }
        for fut in as_completed(futures):
            c = futures[fut]
            try:
                novos = fut.result()
                completed += 1
                print(f"[{completed}/{len(contas)}] {c['id']} {c.get('nome','')} — {novos} linhas novas")
            except Exception as e:
                print(f"[ERRO FATAL] {c['id']} — {str(e)[:80]}")

    print("\nMergindo checkpoints...")
    df = merge_checkpoints()
    out_csv = os.path.join(OUT_DIR, f"google_ads_{args.inicio}_a_{args.fim}.csv")
    df.to_csv(out_csv, index=False, encoding="utf-8")
    print(f"[OK] {len(df)} linhas no CSV consolidado: {out_csv}")

    if args.sem_bq:
        print("[--sem-bq] pulei a carga no BigQuery.")
        return
    if df.empty:
        print("Nada para carregar no BQ.")
        return
    carregar_bq(df, args.inicio, args.fim)


if __name__ == "__main__":
    main()
