"""ETL Google Ads -> BigQuery (RAW) — multi-conta, incremental e responsivo.

Antes de extrair, o script lê a última data já presente no BigQuery e só
coleta o que falta até ontem (D-1):

- Última data no BQ >= D-1  -> nada a fazer (dados já em dia).
- Última data no BQ <  D-1  -> extrai de (última data + 1) até D-1.
- Tabela vazia / inexistente -> faz a carga inicial a partir de INICIO_PADRAO.

Modos:
    # Incremental automático (padrão, usado pelo GitHub Action diário):
    python etl/load_google_ads.py

    # Forçar um intervalo específico (sobrescreve a lógica incremental):
    python etl/load_google_ads.py --inicio 2025-01-01 --fim 2026-06-01

Regras da stack Buriti:
- WRITE_APPEND no RAW, dedup fica na query (ROW_NUMBER), nunca no ETL
- _loaded_at timestamp em todo load
- registra cada carga em controle_cargas_google_ads
"""

import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from dotenv import load_dotenv
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.cloud import bigquery

load_dotenv()

PROJECT_ID   = "buriti-marketing-analytics"
DATASET_RAW  = "buriti_marketing_raw"
DATASET_SILV = "buriti_marketing_silver"
TABLE_RAW    = f"{PROJECT_ID}.{DATASET_RAW}.google_ads_raw"
TABLE_AUDIT  = f"{PROJECT_ID}.{DATASET_SILV}.controle_cargas_google_ads"

ARQUIVO_CONTAS = "contas.json"
INICIO_PADRAO  = "2025-01-01"   # usado só quando o RAW está vazio (carga inicial)

# Métricas diárias por campanha. Ajuste as colunas conforme a necessidade.
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


def _ads_client() -> GoogleAdsClient:
    return GoogleAdsClient.load_from_storage("google-ads.yaml")


def _carregar_contas() -> list[dict]:
    if not os.path.exists(ARQUIVO_CONTAS):
        raise FileNotFoundError(
            f"{ARQUIVO_CONTAS} não encontrado. Rode primeiro: python etl/descobrir_contas.py"
        )
    with open(ARQUIVO_CONTAS, encoding="utf-8") as f:
        return json.load(f)


def extrair_conta(client: GoogleAdsClient, customer_id: str, inicio: str, fim: str) -> list[dict]:
    ga_service = client.get_service("GoogleAdsService")
    query = GAQL.format(inicio=inicio, fim=fim)
    stream = ga_service.search_stream(customer_id=customer_id, query=query)

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
    return linhas


def ultima_data_bq(client: bigquery.Client) -> date | None:
    """Lê a última (maior) data já presente no RAW. None se vazio/inexistente."""
    try:
        query = f"SELECT MAX(date) AS ultima FROM `{TABLE_RAW}`"
        for row in client.query(query).result():
            if row.ultima is None:
                return None
            # date pode vir como string ISO ('2026-05-31') ou date
            if isinstance(row.ultima, str):
                return datetime.strptime(row.ultima[:10], "%Y-%m-%d").date()
            return row.ultima
    except Exception as e:
        print(f"[aviso] não foi possível ler a última data do BQ ({str(e)[:60]}). "
              f"Tratando como carga inicial.")
        return None


def resolver_periodo(client: bigquery.Client) -> tuple[str, str] | None:
    """Define [inicio, fim] incremental. Retorna None se já está em dia."""
    d1 = date.today() - timedelta(days=1)
    ultima = ultima_data_bq(client)

    if ultima is None:
        inicio = datetime.strptime(INICIO_PADRAO, "%Y-%m-%d").date()
        print(f"[incremental] RAW vazio — carga inicial a partir de {inicio}.")
    elif ultima >= d1:
        print(f"[incremental] Dados já em dia (última data no BQ: {ultima}, D-1: {d1}). "
              f"Nada a extrair.")
        return None
    else:
        inicio = ultima + timedelta(days=1)
        print(f"[incremental] Última data no BQ: {ultima} | D-1: {d1} | "
              f"extraindo {inicio} -> {d1}.")

    return inicio.isoformat(), d1.isoformat()


def extrair(inicio: str, fim: str) -> pd.DataFrame:
    client = _ads_client()
    contas = _carregar_contas()
    todas = []
    for c in contas:
        cid = c["id"]
        try:
            linhas = extrair_conta(client, cid, inicio, fim)
            todas.extend(linhas)
            print(f"   [{cid}] {c.get('nome', '')}: {len(linhas)} linhas")
        except GoogleAdsException as ex:
            print(f"   [{cid}] {c.get('nome', '')}: ERRO — {ex.failure.errors[0].message}")
    return pd.DataFrame(todas)


def _apagar_periodo(client: bigquery.Client, inicio: str, fim: str) -> None:
    """Remove do RAW as linhas do período antes de reinserir (idempotência).

    Garante que reprocessar o mesmo intervalo não gere duplicatas e que
    métricas que consolidam retroativamente sejam substituídas pelas mais
    recentes. Ignora silenciosamente se a tabela ainda não existe.
    """
    try:
        query = f"""
            DELETE FROM `{TABLE_RAW}`
            WHERE date BETWEEN @inicio AND @fim
        """
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("inicio", "STRING", inicio),
            bigquery.ScalarQueryParameter("fim", "STRING", fim),
        ])
        job = client.query(query, job_config=job_config)
        job.result()
        removidas = job.num_dml_affected_rows or 0
        if removidas:
            print(f"[dedup] {removidas} linhas antigas de {inicio} a {fim} removidas antes do append.")
    except Exception as e:
        # Tabela inexistente na primeira carga -> nada a apagar.
        print(f"[dedup] sem remoção prévia ({str(e)[:60]}).")


def carregar_raw(df: pd.DataFrame, client: bigquery.Client, inicio: str, fim: str) -> int:
    if df.empty:
        return 0
    # Idempotência: apaga o período antes de reinserir (anti-duplicatas).
    _apagar_periodo(client, inicio, fim)
    df["_loaded_at"] = datetime.now(timezone.utc)
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    client.load_table_from_dataframe(df, TABLE_RAW, job_config=job_config).result()
    return len(df)


def registrar_carga(client: bigquery.Client, rows: int, status: str,
                    inicio: str, fim: str) -> None:
    audit = pd.DataFrame([{
        "fonte":        "google_ads",
        "periodo_ini":  inicio,
        "periodo_fim":  fim,
        "qtd_linhas":   rows,
        "carregado_em": datetime.now(timezone.utc),
        "status":       status,
    }])
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    client.load_table_from_dataframe(audit, TABLE_AUDIT, job_config=job_config).result()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inicio", help="YYYY-MM-DD (sobrescreve a lógica incremental)")
    parser.add_argument("--fim", help="YYYY-MM-DD (sobrescreve a lógica incremental)")
    args = parser.parse_args()

    client = bigquery.Client(project=PROJECT_ID)

    # Intervalo manual tem prioridade; senão, resolve incrementalmente pelo BQ.
    if args.inicio or args.fim:
        d1 = (date.today() - timedelta(days=1)).isoformat()
        inicio = args.inicio or d1
        fim = args.fim or d1
    else:
        periodo = resolver_periodo(client)
        if periodo is None:
            return  # já está em dia, nada a fazer
        inicio, fim = periodo

    try:
        print(f"Extraindo período {inicio} a {fim}:")
        df = extrair(inicio, fim)
        rows = carregar_raw(df, client, inicio, fim)
        registrar_carga(client, rows, "OK", inicio, fim)
        print(f"\n[OK] {rows} linhas carregadas em {TABLE_RAW} ({inicio} a {fim})")
    except Exception as e:
        registrar_carga(client, 0, f"ERRO: {e}", inicio, fim)
        raise


if __name__ == "__main__":
    main()
