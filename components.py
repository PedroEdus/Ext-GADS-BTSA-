import base64
import os

import pandas as pd
import plotly.express as px
import streamlit as st

_ASSETS     = os.path.join(os.path.dirname(__file__), "assets")
LOGO_CLARA  = os.path.join(_ASSETS, "logo_preta.png")
LOGO_ESCURA = os.path.join(_ASSETS, "logo_branca.png")


def _imagem_base64(caminho: str) -> str:
    with open(caminho, "rb") as f:
        return base64.b64encode(f.read()).decode()


def exibir_logo() -> None:
    existe_clara  = os.path.exists(LOGO_CLARA)
    existe_escura = os.path.exists(LOGO_ESCURA)
    if not existe_clara and not existe_escura:
        return
    caminho_claro  = LOGO_CLARA  if existe_clara  else LOGO_ESCURA
    caminho_escuro = LOGO_ESCURA if existe_escura else LOGO_CLARA
    clara_b64  = _imagem_base64(caminho_claro)
    escura_b64 = _imagem_base64(caminho_escuro)
    st.markdown(
        f"""
        <style>
            .logo-container {{
                display: flex; justify-content: flex-start; margin-bottom: 0.75rem;
            }}
            .logo-container img {{ width: min(260px, 60vw); height: auto; }}
            .logo-dark {{ display: none; }}
            @media (prefers-color-scheme: dark) {{
                .logo-light {{ display: none; }}
                .logo-dark  {{ display: block; }}
            }}
        </style>
        <div class="logo-container">
            <img class="logo-light" src="data:image/png;base64,{clara_b64}">
            <img class="logo-dark"  src="data:image/png;base64,{escura_b64}">
        </div>
        """,
        unsafe_allow_html=True,
    )


def _tema() -> str:
    return "plotly_dark" if st.get_option("theme.base") == "dark" else "plotly_white"


def _layout(fig, altura: int = 500):
    fig.update_layout(
        height=altura,
        template=_tema(),
        margin=dict(l=20, r=60, t=60, b=20),
    )
    return fig


def kpis(metricas: dict) -> None:
    """metricas = {"Label": "valor formatado", ...}"""
    cols = st.columns(len(metricas))
    for col, (label, valor) in zip(cols, metricas.items()):
        col.metric(label, valor)


def grafico_linha(df: pd.DataFrame, x: str, y, titulo: str) -> None:
    fig = px.line(df, x=x, y=y, title=titulo, markers=True)
    fig = _layout(fig)
    st.plotly_chart(fig, width="stretch")


def grafico_barras_h(
    df: pd.DataFrame,
    x: str,
    y: str,
    titulo: str,
    color: str | None = None,
    color_map: dict | None = None,
) -> None:
    fig = px.bar(
        df.sort_values(x, ascending=False),
        x=x,
        y=y,
        color=color,
        orientation="h",
        title=titulo,
        color_discrete_map=color_map,
        height=max(420, len(df) * 32),
    )
    fig.update_traces(textposition="outside", cliponaxis=False, textfont_size=11)
    fig.update_layout(
        yaxis={"categoryorder": "total ascending"},
        template=_tema(),
        margin=dict(l=20, r=80, t=60, b=20),
    )
    st.plotly_chart(fig, width="stretch")


def grafico_rosca(
    df: pd.DataFrame,
    names: str,
    values: str,
    titulo: str,
    color_map: dict | None = None,
) -> None:
    fig = px.pie(
        df,
        names=names,
        values=values,
        title=titulo,
        color=names,
        color_discrete_map=color_map,
        hole=0.4,
    )
    fig.update_traces(textinfo="label+percent+value")
    fig = _layout(fig, altura=420)
    st.plotly_chart(fig, width="stretch")


def tabela(df: pd.DataFrame) -> None:
    st.dataframe(df, hide_index=True, width="stretch")
