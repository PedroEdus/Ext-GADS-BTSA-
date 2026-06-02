import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from google.cloud import bigquery
from google.oauth2 import service_account

load_dotenv()  # carrega GOOGLE_APPLICATION_CREDENTIALS em execução local

PROJECT_ID = "buriti-marketing-analytics"
DATASET    = "buriti_marketing_silver"
TABELA     = "google_ads"


def _criar_client() -> bigquery.Client:
    # Em produção (Streamlit Cloud) usa st.secrets; local cai no
    # GOOGLE_APPLICATION_CREDENTIALS. Acessar st.secrets sem secrets.toml
    # levanta StreamlitSecretNotFoundError, então protegemos com try/except.
    try:
        if "gcp_service_account" in st.secrets:
            credentials = service_account.Credentials.from_service_account_info(
                st.secrets["gcp_service_account"]
            )
            return bigquery.Client(credentials=credentials, project=PROJECT_ID)
    except Exception:
        pass
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
                       PARTITION BY date, customer_id, campaign_id
                       ORDER BY _loaded_at DESC
                   ) AS rn
            FROM `{PROJECT_ID}.{DATASET}.{TABELA}`
        )
        WHERE rn = 1
    """
    return client.query(query).to_dataframe()
