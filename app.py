import pandas as pd
import streamlit as st

from components import exibir_logo, kpis, grafico_linha, grafico_barras_h, tabela
from data import carregar_dados

st.set_page_config(
    page_title="Google Ads — Buriti",
    page_icon="📊",
    layout="wide",
)

exibir_logo()
st.title("Google Ads — Buriti")

df = carregar_dados()

if df.empty:
    st.warning("Nenhum dado encontrado.")
    st.stop()

df["date"] = pd.to_datetime(df["date"])

# ── Filtros ───────────────────────────────────────────────────────────────────

st.sidebar.header("Filtros")

dmin, dmax = df["date"].min().date(), df["date"].max().date()
periodo = st.sidebar.date_input("Período", value=(dmin, dmax), min_value=dmin, max_value=dmax)
if isinstance(periodo, tuple) and len(periodo) == 2:
    df = df[(df["date"].dt.date >= periodo[0]) & (df["date"].dt.date <= periodo[1])]

campanhas = sorted(df["campaign_name"].dropna().unique())
sel = st.sidebar.multiselect("Campanhas", campanhas, default=campanhas)
df = df[df["campaign_name"].isin(sel)]

if df.empty:
    st.warning("Nenhum dado para os filtros selecionados.")
    st.stop()

# ── KPIs ──────────────────────────────────────────────────────────────────────

custo  = df["cost"].sum()
cliques = int(df["clicks"].sum())
conv   = df["conversions"].sum()
valor  = df["conversions_value"].sum()
roas   = (valor / custo) if custo else 0
cpa    = (custo / conv) if conv else 0

kpis({
    "Custo":       f"R$ {custo:,.2f}",
    "Cliques":     f"{cliques:,}",
    "Conversões":  f"{conv:,.1f}",
    "ROAS":        f"{roas:,.2f}x",
    "CPA":         f"R$ {cpa:,.2f}",
})

st.divider()

# ── Abas ──────────────────────────────────────────────────────────────────────

aba1, aba2, aba3 = st.tabs(["📈 Evolução", "🏆 Campanhas", "📋 Tabela"])

with aba1:
    diario = df.groupby("date", as_index=False)[["cost", "clicks", "conversions"]].sum()
    grafico_linha(diario, x="date", y="cost", titulo="Custo diário")
    grafico_linha(diario, x="date", y="conversions", titulo="Conversões diárias")

with aba2:
    por_camp = df.groupby("campaign_name", as_index=False)[["cost"]].sum()
    grafico_barras_h(por_camp, x="cost", y="campaign_name", titulo="Custo por campanha")

with aba3:
    tabela(df.sort_values("date", ascending=False))
