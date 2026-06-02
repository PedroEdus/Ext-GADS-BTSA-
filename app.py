import pandas as pd
import streamlit as st

from components import (
    exibir_logo, injetar_css_global, kpis, grafico_evolucao,
    grafico_tipo_lancamento, grafico_canal, grafico_cpc_grupo,
    grafico_barras_campanha, tabela_resumo,
)
from data import carregar_dados

st.set_page_config(page_title="Google Ads — Buriti", page_icon="📊", layout="wide")

injetar_css_global()
exibir_logo()
st.title("Google Ads — Buriti")

df = carregar_dados()
if df.empty:
    st.warning("Nenhum dado encontrado.")
    st.stop()

df["date"] = pd.to_datetime(df["date"])

# ── Filtros ───────────────────────────────────────────────────────────────────
st.sidebar.header("Filtros")

df_orig = df.copy()  # referência original para calcular opções dos filtros independentes

# Período
dmin, dmax = df["date"].min().date(), df["date"].max().date()
periodo = st.sidebar.date_input("Período", value=(dmin, dmax), min_value=dmin, max_value=dmax)
if isinstance(periodo, tuple) and len(periodo) == 2:
    df = df[(df["date"].dt.date >= periodo[0]) & (df["date"].dt.date <= periodo[1])]

# Tipo de campanha — vazio = todos
tipos_opts = ["Lançamento", "Estoque", "Outros"]
sel_tipo = st.sidebar.multiselect("Tipo de campanha", tipos_opts)
if sel_tipo:
    df = df[df["Tipo_Lancamento"].isin(sel_tipo)]

# Conta — vazio = todas
contas_opts = sorted(df_orig["customer_name"].dropna().unique())
sel_conta = st.sidebar.multiselect("Conta", contas_opts)
if sel_conta:
    df = df[df["customer_name"].isin(sel_conta)]

# UF — vazio = todas
ufs_opts = sorted(df_orig["UF"].dropna().unique())
sel_uf = st.sidebar.multiselect("UF", ufs_opts)
if sel_uf:
    df = df[df["UF"].isin(sel_uf) | df["UF"].isna()]

# Cidade — cascateia após UF; vazio = todas
df_para_cidade = df_orig[df_orig["UF"].isin(sel_uf)] if sel_uf else df_orig
cidades_opts = sorted(
    df_para_cidade["Cidade"].dropna()
    .loc[lambda s: s != "Não identificado"].unique()
)
sel_cidade = st.sidebar.multiselect("Cidade", cidades_opts)
if sel_cidade:
    df = df[df["Cidade"].isin(sel_cidade) | (df["Cidade"] == "Não identificado") | df["Cidade"].isna()]

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
        grafico_canal(df, "cost", "Investimento por canal")
    grafico_barras_campanha(df, "cost", "Investimento por campanha (R$)", "bar_cost")

with aba_cliques:
    grafico_evolucao(df, "clicks")
    c1, c2 = st.columns([1, 1])
    with c1:
        grafico_tipo_lancamento(df, "clicks", "Cliques por tipo")
    with c2:
        grafico_canal(df, "clicks", "Cliques por canal")
    grafico_barras_campanha(df, "clicks", "Cliques por campanha", "bar_clicks")

with aba_cpc:
    grafico_evolucao(df, "cpc")
    c1, c2 = st.columns(2)
    with c1:
        grafico_cpc_grupo(df, "Tipo_Lancamento", "CPC médio por tipo")
    with c2:
        grafico_cpc_grupo(df, "advertising_channel_type", "CPC médio por canal")
    grafico_barras_campanha(df, "cpc", "Custo por clique por campanha (R$)", "bar_cpc")

with aba_tabela:
    st.subheader("Detalhe por campanha")
    csv = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        label="⬇️ Baixar dados (CSV)",
        data=csv,
        file_name="google_ads_filtrado.csv",
        mime="text/csv",
    )
    tabela_resumo(df)
