"""Extração massiva Google Ads -> BigQuery, com SAVEPOINTS + THREADS.

Inspirado no padrão do GA4 (Extração Massiva Analytics.py), mas com chunk
MENSAL em vez de diário — a Google Ads API tem limite diário de operações
rígido, e dia-a-dia (26 contas x ~516 dias) estoura a quota. Mês-a-mês a
API retorna as linhas diárias numa única query (~17 chunks x 26 contas).

- 1 checkpoint CSV por conta em gads_checkpoints/{cid}.csv  (dados)
- 1 controle de chunks por conta em gads_checkpoints/{cid}.done.json (savepoint)
- retoma de onde parou (pula meses já extraídos, inclusive os vazios)
- ThreadPoolExecutor paraleliza entre as contas
- retry com backoff em rate limit / erros transitórios
- ao fim: merge dos checkpoints -> RAW (WRITE_TRUNCATE) + registro da carga

    python etl/extracao_massiva.py
    python etl/extracao_massiva.py --inicio 2025-01-01 --fim 2026-05-31 --workers 3
    python etl/extracao_massiva.py --sem-bq        # só extrai p/ CSV, não carrega no BQ
    python etl/extracao_massiva.py --reset         # apaga checkpoints e recomeça
"""

import argparse
import json
import os
import shutil
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
NUM_INT    = ["customer_id", "campaign_id", "impressions", "clicks"]
NUM_FLOAT  = ["cost", "conversions", "conversions_value"]

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
    WHERE segments.date BETWEEN '{inicio}' AND '{fim}'
"""

os.makedirs(CHECKPOINT_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)


# ============================================================
# CHUNKS MENSAIS
# ============================================================
def meses(inicio: str, fim: str) -> list[tuple[str, str, str]]:
    """Lista (chave 'YYYY-MM', primeiro_dia, ultimo_dia) cobrindo [inicio, fim]."""
    di = datetime.strptime(inicio, "%Y-%m-%d").date()
    df_ = datetime.strptime(fim, "%Y-%m-%d").date()
    out = []
    cur = di.replace(day=1)
    while cur <= df_:
        prox = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        ini_chunk = max(cur, di)
        fim_chunk = min(prox - timedelta(days=1), df_)
        out.append((cur.strftime("%Y-%m"), ini_chunk.isoformat(), fim_chunk.isoformat()))
        cur = prox
    return out


# ============================================================
# SAVEPOINT HELPERS (por conta)
# ============================================================
def csv_path(cid: str) -> str:
    return os.path.join(CHECKPOINT_DIR, f"{cid}.csv")


def done_path(cid: str) -> str:
    return os.path.join(CHECKPOINT_DIR, f"{cid}.done.json")


def load_done_chunks(cid: str) -> set:
    p = done_path(cid)
    if os.path.exists(p):
        return set(json.load(open(p, encoding="utf-8")))
    return set()


def mark_chunk_done(cid: str, chunk_key: str) -> None:
    done = load_done_chunks(cid)
    done.add(chunk_key)
    json.dump(sorted(done), open(done_path(cid), "w", encoding="utf-8"))


def append_csv(cid: str, df_new: pd.DataFrame) -> None:
    p = csv_path(cid)
    if os.path.exists(p):
        df_old = pd.read_csv(p, dtype=str)
        df_all = pd.concat([df_old, df_new.astype(str)], ignore_index=True)
        df_all = df_all.drop_duplicates(subset=DEDUP_KEYS, keep="last")
    else:
        df_all = df_new.astype(str)
    df_all.to_csv(p, index=False, encoding="utf-8")


# ============================================================
# EXTRAÇÃO (1 chunk mensal, com retry)
# ============================================================
def extrair_chunk(client, cid, ini, fim, retries=6) -> pd.DataFrame:
    ga = client.get_service("GoogleAdsService")
    query = GAQL.format(inicio=ini, fim=fim)
    for attempt in range(retries):
        try:
            stream = ga.search_stream(customer_id=cid, query=query)
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
            up = msg.upper()
            transitorio = any(k in up for k in ("EXHAUST", "QUOTA", "INTERNAL", "DEADLINE", "UNAVAILABLE"))
            if transitorio and attempt < retries - 1:
                wait = min(60, 15 * (attempt + 1))
                print(f"    [retry {attempt+1}/{retries}] {cid} {ini[:7]} — {wait}s ({msg[:40]})")
                time.sleep(wait)
            else:
                raise


def extrair_conta(cid: str, nome: str, chunks: list[tuple[str, str, str]]) -> int:
    """Processa todos os chunks pendentes de uma conta. Roda em uma thread."""
    client = GoogleAdsClient.load_from_storage("google-ads.yaml", version=API_VERSION)
    done = load_done_chunks(cid)
    novos = 0
    for chave, ini, fim in chunks:
        if chave in done:
            continue
        try:
            df = extrair_chunk(client, cid, ini, fim)
            if df is not None and not df.empty:
                append_csv(cid, df)
                novos += len(df)
            mark_chunk_done(cid, chave)   # savepoint (mesmo se vazio)
        except Exception as e:
            print(f"  [{cid}] ERRO {chave} — {str(e)[:80]}")
        time.sleep(0.2)
    return novos


# ============================================================
# MERGE + CARGA NO BIGQUERY
# ============================================================
def merge_csvs() -> pd.DataFrame:
    frames = []
    for f in os.listdir(CHECKPOINT_DIR):
        if f.endswith(".csv"):
            df = pd.read_csv(os.path.join(CHECKPOINT_DIR, f), dtype=str)
            if not df.empty:
                frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


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
    client.load_table_from_dataframe(
        df, TABLE_RAW, job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    ).result()
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
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--sem-bq", action="store_true")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    if args.reset and os.path.isdir(CHECKPOINT_DIR):
        shutil.rmtree(CHECKPOINT_DIR)
        os.makedirs(CHECKPOINT_DIR, exist_ok=True)
        print("[reset] checkpoints apagados.\n")

    contas = json.load(open(ARQUIVO_CONTAS, encoding="utf-8"))
    chunks = meses(args.inicio, args.fim)
    print(f"Contas: {len(contas)} | Período: {args.inicio} -> {args.fim} | "
          f"Chunks/conta: {len(chunks)} (mensal) | Workers: {args.workers}\n")

    completed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(extrair_conta, c["id"], c.get("nome", ""), chunks): c
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
    df = merge_csvs()
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
