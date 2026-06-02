import re

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from google.cloud import bigquery
from google.oauth2 import service_account

load_dotenv()  # carrega GOOGLE_APPLICATION_CREDENTIALS em execução local

PROJECT_ID = "buriti-marketing-analytics"
DATASET    = "buriti_marketing_silver"
TABELA     = "google_ads"

_NUM_COLS = ["impressions", "clicks", "cost", "conversions", "conversions_value"]

_UF_BR = {
    "AC","AL","AP","AM","BA","CE","DF","ES","GO","MA",
    "MT","MS","MG","PA","PB","PR","PE","PI","RJ","RN",
    "RS","RO","RR","SC","SP","SE","TO",
}

# Ancora em Cidade/UF: nome pode ter acento, espaço, ponto
_RE_CUF = re.compile(r'([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s\.]+?)\s*/\s*([A-Z]{2})(?:\b|$)')


def _tipo_lancamento(nome: str) -> str:
    """Classifica a campanha pelo nome: Estoque / Lançamento / Outros."""
    n = str(nome)
    if re.search(r"estoque", n, re.IGNORECASE):
        return "Estoque"
    if re.search(r"lan[cç]amento", n, re.IGNORECASE):
        return "Lançamento"
    return "Outros"


def _extrair_cidade_uf(nome: str) -> tuple:
    """Extrai (Cidade, UF) do nome da campanha usando 3 padrões.

    Padrão 1 — Estoque | Cidade/UF  ou  Lançamento | Cidade/UF
    Padrão 2 — Campanha de ... - Cidade/UF
    Padrão 3 — Cidade/UF - ... (primeiro campo antes do traço)
    Demais   — ("Não identificado", None)
    """
    n = str(nome).strip()

    # Padrão 1
    if re.match(r'^(?:Estoque|Lan[cç]amento)\s*\|', n, re.IGNORECASE):
        apos = re.sub(r'^(?:Estoque|Lan[cç]amento)\s*\|\s*', '', n, flags=re.IGNORECASE)
        m = _RE_CUF.match(apos)
        if m and m.group(2) in _UF_BR:
            return m.group(1).strip(), m.group(2)
        return "Não identificado", None

    # Padrão 2
    if re.match(r'^Campanha\b', n, re.IGNORECASE):
        partes = n.split(' - ', 1)
        if len(partes) > 1:
            m = _RE_CUF.match(partes[1].strip())
            if m and m.group(2) in _UF_BR:
                return m.group(1).strip(), m.group(2)
        return "Não identificado", None

    # Padrão 3
    m = _RE_CUF.match(n)
    if m and m.group(2) in _UF_BR:
        return m.group(1).strip(), m.group(2)

    # Padrão 4 (catch-all) — varre o nome inteiro buscando qualquer Cidade/UF
    m = _RE_CUF.search(n)
    if m and m.group(2) in _UF_BR:
        return m.group(1).strip(), m.group(2)

    return "Não identificado", None


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
    df = client.query(query).to_dataframe()
    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"])
    for c in _NUM_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    # Remove campanhas de teste [TS]
    df = df[~df["campaign_name"].str.match(r"^\[TS\]", na=False)]

    # Classificação Estoque / Lançamento / Outros
    df["Tipo_Lancamento"] = df["campaign_name"].map(_tipo_lancamento)

    # Extração de Cidade e UF via regex (3 padrões)
    cidade_uf = df["campaign_name"].map(_extrair_cidade_uf)
    df["Cidade"] = cidade_uf.map(lambda x: x[0])
    df["UF"]     = cidade_uf.map(lambda x: x[1])

    return df
