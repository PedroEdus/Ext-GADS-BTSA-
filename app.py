import pandas as pd
import streamlit as st

from components import (
    exibir_logo, kpis, grafico_evolucao, grafico_tipo_lancamento,
    grafico_barras_campanha, tabela_resumo,
)
from data import carregar_dados

st.set_page_config(page_title="Google Ads — Buriti", page_icon="📊", layout="wide")

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

tipos = ["Lançamento", "Estoque", "Outros"]
tipos_disp = [t for t in tipos if t in df["Tipo_Lancamento"].unique()]
sel_tipo = st.sidebar.multiselect("Tipo de campanha", tipos_disp, default=tipos_disp)
df = df[df["Tipo_Lancamento"].isin(sel_tipo)]

contas = sorted(df["customer_name"].dropna().unique())
sel_conta = st.sidebar.multiselect("Conta (cidade)", contas, default=contas)
df = df[df["customer_name"].isin(sel_conta)]

if df.empty:
    st.warning("Nenhum dado para os filtros selecionados.")
    st.stop()

# ── KPIs ──────────────────────────────────────────────────────────────────────
kpis(df)
st.divider()

# ── Abas ──────────────────────────────────────────────────────────────────────
aba_gasto, aba_cliques, aba_cpc, aba_tabela = st.tabs(
    ["💰 Valor Gasto", "🖱️ Cliques", "💵 Custo por Clique", "📋 Tabela"]
)

with aba_gasto:
    grafico_evolucao(df, "cost")
    c1, c2 = st.columns([1, 1])
    with c1:
        grafico_tipo_lancamento(df, "cost", "Investimento por tipo")
    with c2:
        st.write("")
    grafico_barras_campanha(df, "cost", "Investimento por campanha (R$)", "bar_cost")

with aba_cliques:
    grafico_evolucao(df, "clicks")
    c1, c2 = st.columns([1, 1])
    with c1:
        grafico_tipo_lancamento(df, "clicks", "Cliques por tipo")
    with c2:
        st.write("")
    grafico_barras_campanha(df, "clicks", "Cliques por campanha", "bar_clicks")

with aba_cpc:
    grafico_evolucao(df, "cpc")
    grafico_barras_campanha(df, "cpc", "Custo por clique por campanha (R$)", "bar_cpc")

with aba_tabela:
    tabela_resumo(df)
