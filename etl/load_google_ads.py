"""ETL Google Ads -> BigQuery (RAW).

Modos:
    # Incremental D-1 (padrão, usado pelo GitHub Action diário):
    python etl/load_google_ads.py

    # Carga histórica de um intervalo:
    python etl/load_google_ads.py --inicio 2025-01-01 --fim 2025-06-01

Segue as regras da stack Buriti:
- WRITE_APPEND no RAW, dedup fica na query (ROW_NUMBER), nunca no ETL
- _loaded_at timestamp em todo load
- registra cada carga em controle_cargas_google_ads
"""

import argparse
import os
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from dotenv import load_dotenv
from google.ads.googleads.client import GoogleAdsClient
from google.cloud import bigquery

load_dotenv()

PROJECT_ID   = "buriti-marketing-analytics"
DATASET_RAW  = "buriti_marketing_raw"
DATASET_SILV = "buriti_marketing_silver"
TABLE_RAW    = f"{PROJECT_ID}.{DATASET_RAW}.google_ads_raw"
TABLE_AUDIT  = f"{PROJECT_ID}.{DATASET_SILV}.controle_cargas_google_ads"

CUSTOMER_ID  = os.getenv("GOOGLE_ADS_CUSTOMER_ID", "").replace("-", "")

# Métricas diárias por campanha. Ajuste as colunas conforme a necessidade.
GAQL = """
    SELECT
        segments.date,
        customer.id,
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
    return GoogleAdsClient.load_from_storage("google-ads.yaml", version="v18")


def extrair(inicio: str, fim: str) -> pd.DataFrame:
    client = _ads_client()
    ga_service = client.get_service("GoogleAdsService")
    query = GAQL.format(inicio=inicio, fim=fim)
    stream = ga_service.search_stream(customer_id=CUSTOMER_ID, query=query)

    linhas = []
    for batch in stream:
        for r in batch.results:
            linhas.append({
                "date":                     r.segments.date,
                "customer_id":              r.customer.id,
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


def carregar_raw(df: pd.DataFrame, client: bigquery.Client) -> int:
    if df.empty:
        return 0
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
    parser.add_argument("--inicio", help="YYYY-MM-DD (default: D-1)")
    parser.add_argument("--fim", help="YYYY-MM-DD (default: D-1)")
    args = parser.parse_args()

    d1 = (date.today() - timedelta(days=1)).isoformat()
    inicio = args.inicio or d1
    fim = args.fim or d1

    client = bigquery.Client(project=PROJECT_ID)
    try:
        df = extrair(inicio, fim)
        rows = carregar_raw(df, client)
        registrar_carga(client, rows, "OK", inicio, fim)
        print(f"[OK] {rows} linhas carregadas em {TABLE_RAW} ({inicio} a {fim})")
    except Exception as e:
        registrar_carga(client, 0, f"ERRO: {e}", inicio, fim)
        raise


if __name__ == "__main__":
    main()
