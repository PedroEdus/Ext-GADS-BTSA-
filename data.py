import pandas as pd
import streamlit as st
from google.cloud import bigquery
from google.oauth2 import service_account

PROJECT_ID = "buriti-marketing-analytics"
DATASET    = "buriti_marketing_silver"
TABELA     = "google_ads"


def _criar_client() -> bigquery.Client:
    if "gcp_service_account" in st.secrets:
        credentials = service_account.Credentials.from_service_account_info(
            st.secrets["gcp_service_account"]
        )
        return bigquery.Client(credentials=credentials, project=PROJECT_ID)
    return bigquery.Client(project=PROJECT_ID)


@st.cache_data(ttl=3600)
def carregar_dados() -> pd.DataFrame:
    client = _criar_client()
    # Dedup via ROW_NUMBER — chave única = data + campanha.
    query = f"""
        SELECT * EXCEPT(rn)
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY date, campaign_id
                       ORDER BY _loaded_at DESC
                   ) AS rn
            FROM `{PROJECT_ID}.{DATASET}.{TABELA}`
        )
        WHERE rn = 1
    """
    return client.query(query).to_dataframe()
