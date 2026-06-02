import base64
import os

import pandas as pd
import plotly.express as px
import streamlit as st

# ── Logos ───────────────────────────────────────────────────────────────────
_ASSETS     = os.path.join(os.path.dirname(__file__), "assets")
LOGO_CLARA  = os.path.join(_ASSETS, "logo_preta.png")
LOGO_ESCURA = os.path.join(_ASSETS, "logo_branca.png")

# Estoque / Lançamento / Outros — paleta verde da marca (mesma do Meta Ads)
_LANCAMENTO_COLOR_MAP = {
    "Lançamento": "#008140",
    "Estoque":    "#00b359",
    "Outros":     "#888888",
}

POR_PAGINA = 20

# ── CSS compartilhado (design system Buriti) ──────────────────────────────────
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

.pub-card { background:#1c1c1c; border-radius:8px; padding:18px 20px 14px; margin-bottom:4px; }
.pub-card-title { font-family:'Manrope',sans-serif; font-size:15px; font-weight:600; color:#fff; margin-bottom:16px; }

.pub-bar-list { display:flex; flex-direction:column; gap:9px; }
.pub-bar-row { display:grid; grid-template-columns:240px 1fr 130px; align-items:center; gap:12px; }
.pub-bar-name { font-family:'Manrope',sans-serif; font-size:12px; color:#fff; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.pub-bar-track { height:16px; background:#262626; border-radius:3px; overflow:hidden; }
.pub-bar-value { font-family:'JetBrains Mono',monospace; font-size:12px; color:rgba(255,255,255,0.72); text-align:right; font-variant-numeric:tabular-nums; }
.pub-bar-legend { display:flex; gap:14px; margin-top:14px; padding-top:12px; border-top:1px solid #2a2a2a; flex-wrap:wrap; }
.pub-legend-item { display:inline-flex; align-items:center; gap:6px; font-family:'Manrope',sans-serif; font-size:12px; color:rgba(255,255,255,0.72); }
.pub-legend-dot { width:8px; height:8px; border-radius:50%; display:inline-block; flex-shrink:0; }

.pub-table-wrap { overflow-x:auto; }
.pub-table { width:100%; border-collapse:collapse; font-family:'Manrope',sans-serif; font-size:13px; }
.pub-table th { padding:9px 12px; text-align:left; border-bottom:1px solid #2a2a2a; color:rgba(255,255,255,0.50); font-size:12px; font-weight:500; white-space:nowrap; }
.pub-table td { padding:9px 12px; border-bottom:1px solid #1f1f1f; color:#fff; white-space:nowrap; }
.pub-table th.num, .pub-table td.num { text-align:right; font-family:'JetBrains Mono',monospace; font-variant-numeric:tabular-nums; font-size:12px; }
.pub-table tbody tr:hover td { background:rgba(255,255,255,0.025); }
.pub-table tr.total td { border-top:1px solid #3a3a3a; border-bottom:none; font-weight:700; background:rgba(0,129,64,0.07); }
</style>
"""

# CSS global injetado uma vez no app — substitui vermelho do Streamlit por verde Buriti
_GLOBAL_CSS = """
<style>
/* Tags do multiselect: fundo verde Buriti */
span[data-baseweb="tag"] {
    background-color: #008140 !important;
}
/* X de remoção da tag */
span[data-baseweb="tag"] span[role="img"] svg path {
    fill: rgba(255,255,255,0.8) !important;
}
/* Radio button selecionado: verde */
input[type="radio"]:checked + div {
    color: #008140 !important;
}
div[data-baseweb="radio"] input:checked ~ div:first-of-type div {
    background-color: #008140 !important;
    border-color: #008140 !important;
}
/* Tabs sublinhado ativo: verde */
button[data-baseweb="tab"][aria-selected="true"] {
    color: #008140 !important;
}
button[data-baseweb="tab"][aria-selected="true"]::after {
    background-color: #008140 !important;
}
</style>
"""


def injetar_css_global() -> None:
    st.markdown(_GLOBAL_CSS, unsafe_allow_html=True)


def _html(content: str) -> None:
    if hasattr(st, "html"):
        st.html(_CSS + content)
    else:
        st.markdown(_CSS + content, unsafe_allow_html=True)


# ── Logo ──────────────────────────────────────────────────────────────────────
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
            .logo-container {{ display:flex; justify-content:flex-start; margin-bottom:0.75rem; }}
            .logo-container img {{ width:min(220px,55vw); height:auto; }}
            .logo-dark {{ display:none; }}
            @media (prefers-color-scheme:dark) {{
                .logo-light {{ display:none; }}
                .logo-dark  {{ display:block; }}
            }}
        </style>
        <div class="logo-container">
            <img class="logo-light" src="data:image/png;base64,{clara_b64}">
            <img class="logo-dark"  src="data:image/png;base64,{escura_b64}">
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────
def _tema() -> str:
    return "plotly_dark" if st.get_option("theme.base") == "dark" else "plotly_white"


def _br(valor, decimais: int = 0, prefixo: str = "") -> str:
    """Formatação numérica brasileira: 1.234,56."""
    try:
        fmt = f"{float(valor):,.{decimais}f}"
    except Exception:
        return "—"
    fmt = fmt.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{prefixo}{fmt}"


def _font_color_para_fundo(hex_color: str) -> str:
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "black" if lum > 0.55 else "white"


def _rgba(hex_color: str, alpha: float) -> str:
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _legenda_html(df: pd.DataFrame) -> str:
    if "Tipo_Lancamento" not in df.columns:
        return ""
    tipos = df["Tipo_Lancamento"].dropna().unique()
    return "".join(
        f'<span class="pub-legend-item">'
        f'<span class="pub-legend-dot" style="background:{_LANCAMENTO_COLOR_MAP.get(t,"#888")}"></span>{t}</span>'
        for t in _LANCAMENTO_COLOR_MAP if t in tipos
    )


# ── KPIs (sem conversão / ROAS) ───────────────────────────────────────────────
def kpis(df: pd.DataFrame) -> None:
    custo = df["cost"].sum()        if "cost"        in df.columns else 0
    clk   = df["clicks"].sum()      if "clicks"      in df.columns else 0
    imp   = df["impressions"].sum() if "impressions" in df.columns else 0
    ctr   = (clk / imp * 100) if imp else 0
    cpc   = (custo / clk)     if clk else 0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Investimento", _br(custo, 2, "R$ "))
    c2.metric("Cliques",      _br(clk))
    c3.metric("Impressões",   _br(imp))
    c4.metric("CTR médio",    _br(ctr, 2) + "%")
    c5.metric("CPC médio",    _br(cpc, 2, "R$ "))


# ── Evolução temporal (diária / mensal) ───────────────────────────────────────
def _agg_periodo(df: pd.DataFrame, granularidade: str) -> pd.DataFrame:
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    if granularidade == "Mensal":
        d["periodo"] = d["date"].dt.to_period("M").dt.to_timestamp()
    else:
        d["periodo"] = d["date"].dt.normalize()
    agg = d.groupby("periodo", as_index=False)[["cost", "clicks", "impressions"]].sum()
    agg["cpc"] = (agg["cost"] / agg["clicks"].replace(0, pd.NA)).fillna(0)
    return agg


_EVO_FMT = {
    "cost":   ("Investimento (R$)", "#008140", lambda v: _br(v, 2, "R$ ")),
    "clicks": ("Cliques",           "#00b359", lambda v: _br(v)),
    "cpc":    ("Custo por clique (R$)", "#33aa77", lambda v: _br(v, 2, "R$ ")),
}


_LAYOUT_BASE = dict(
    plot_bgcolor="#1c1c1c",
    paper_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Manrope, sans-serif", color="#ffffff"),
    margin=dict(l=20, r=20, t=50, b=20),
    xaxis=dict(title=None, gridcolor="#2a2a2a", linecolor="#2a2a2a"),
    yaxis=dict(title=None, gridcolor="#2a2a2a"),
    separators=",.",
)


def _titulo_layout(titulo: str) -> dict:
    return dict(font=dict(family="Manrope, sans-serif", size=15, color="#ffffff"),
                x=0, xanchor="left", pad=dict(l=4), text=titulo)


def grafico_evolucao(df: pd.DataFrame, coluna: str, key_suffix: str = "") -> None:
    titulo, cor, fmt = _EVO_FMT[coluna]

    gran = st.radio(
        "Visualização", ["Diário", "Mensal"], horizontal=True,
        key=f"gran_{coluna}_{key_suffix}", label_visibility="collapsed",
    )

    agg = _agg_periodo(df, gran)
    if agg.empty:
        st.info("Sem dados no período.")
        return

    sufixo = "(mês)" if gran == "Mensal" else "(dia)"
    titulo_full = f"{titulo} {sufixo}"

    if gran == "Mensal":
        agg_plot = agg.copy()
        agg_plot["periodo_str"] = agg_plot["periodo"].dt.strftime("%b/%Y")
        y_max = float(agg_plot[coluna].max()) if not agg_plot.empty else 1
        fig = px.bar(agg_plot, x="periodo_str", y=coluna)
        text_br = [fmt(v) for v in agg_plot[coluna]]
        fig.update_traces(
            marker_color=cor,
            text=text_br, texttemplate="%{text}",
            textposition="outside",
            textfont=dict(size=10, color="rgba(255,255,255,0.7)"),
            cliponaxis=False,
        )
        fig.update_layout(
            **_LAYOUT_BASE, height=400, bargap=0.28,
            xaxis=dict(title=None, type="category", gridcolor="#2a2a2a"),
            yaxis=dict(title=None, gridcolor="#2a2a2a", range=[0, y_max * 1.22]),
            title=_titulo_layout(titulo_full),
        )
    else:
        fig = px.area(agg, x="periodo", y=coluna, color_discrete_sequence=[cor])
        fig.update_traces(
            line=dict(width=2, color=cor),
            fillcolor=_rgba(cor, 0.13),
        )
        fig.update_layout(
            **_LAYOUT_BASE, height=380,
            title=_titulo_layout(titulo_full),
        )

    st.plotly_chart(fig, use_container_width=True)


# ── Donut por Tipo de campanha ────────────────────────────────────────────────
def grafico_tipo_lancamento(df: pd.DataFrame, coluna: str = "cost", titulo: str | None = None) -> None:
    if "Tipo_Lancamento" not in df.columns or coluna not in df.columns:
        return
    label = {"cost": "Investimento", "clicks": "Cliques"}.get(coluna, coluna)
    titulo = titulo or f"Distribuição por tipo — {label}"
    fmt = (lambda v: _br(v, 2, "R$ ")) if coluna == "cost" else (lambda v: _br(v))

    resumo = df.groupby("Tipo_Lancamento", as_index=False)[coluna].sum()
    total  = resumo[coluna].sum()
    resumo["_pct"]  = (resumo[coluna] / total * 100).round(1) if total else 0
    resumo["_text"] = resumo.apply(
        lambda r: f"{fmt(r[coluna])}<br>{r['_pct']:.1f}%" if r["_pct"] >= 5 else "", axis=1)
    font_colors = [_font_color_para_fundo(_LANCAMENTO_COLOR_MAP.get(t, "#888"))
                   for t in resumo["Tipo_Lancamento"]]

    fig = px.pie(resumo, names="Tipo_Lancamento", values=coluna,
                 color="Tipo_Lancamento", color_discrete_map=_LANCAMENTO_COLOR_MAP,
                 hole=0.58, title=titulo)
    fig.update_traces(
        text=resumo["_text"].tolist(), textposition="inside", textinfo="text",
        insidetextfont=dict(family="JetBrains Mono, monospace", size=11, color=font_colors),
        hovertemplate="%{label}: %{value:,.0f} (%{percent})",
        domain=dict(x=[0, 0.62], y=[0, 1]),
    )
    fig.update_layout(
        plot_bgcolor="#1c1c1c", paper_bgcolor="rgba(0,0,0,0)",
        separators=",.", height=320,
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(
            orientation="v", x=0.65, y=0.5, xanchor="left", yanchor="middle",
            font=dict(family="Manrope, sans-serif", size=12, color="rgba(255,255,255,0.8)"),
        ),
        font=dict(family="Manrope, sans-serif", color="#ffffff"),
        title=_titulo_layout(titulo),
    )
    st.plotly_chart(fig, use_container_width=True)


# ── Barras por campanha (paginado, colorido por Tipo) ─────────────────────────
def grafico_barras_campanha(df: pd.DataFrame, coluna: str, titulo: str, key: str) -> None:
    fmt = (lambda v: _br(v, 2, "R$ ")) if coluna in ("cost", "cpc") else (lambda v: _br(v))

    if coluna == "cpc":
        base = df.groupby("campaign_name").agg(cost=("cost", "sum"), clicks=("clicks", "sum"))
        base["cpc"] = base["cost"] / base["clicks"].replace(0, pd.NA)
        totais = base["cpc"].fillna(0).sort_values(ascending=False)
    else:
        totais = df.groupby("campaign_name")[coluna].sum().sort_values(ascending=False)

    tipo_por_camp = df.groupby("campaign_name")["Tipo_Lancamento"].first() \
        if "Tipo_Lancamento" in df.columns else {}

    campanhas_ord = totais.index.tolist()
    n_total = len(campanhas_ord)
    n_pages = max(1, -(-n_total // POR_PAGINA))
    if key not in st.session_state:
        st.session_state[key] = 0
    page = min(st.session_state[key], n_pages - 1)
    st.session_state[key] = page

    campanhas_pag = campanhas_ord[page * POR_PAGINA:(page + 1) * POR_PAGINA]
    max_val = totais.max() or 1

    rows_html = ""
    for camp in campanhas_pag:
        val   = totais[camp]
        tipo  = tipo_por_camp.get(camp, "Outros") if hasattr(tipo_por_camp, "get") else "Outros"
        color = _LANCAMENTO_COLOR_MAP.get(tipo, "#888888")
        bar_w = (val / max_val * 100) if max_val else 0
        name_tr = (camp[:42] + "…") if len(str(camp)) > 42 else camp
        rows_html += (
            f'<div class="pub-bar-row">'
            f'<div class="pub-bar-name" title="{camp}">{name_tr}</div>'
            f'<div class="pub-bar-track">'
            f'<div style="width:{bar_w:.2f}%;height:100%;background:{color};border-radius:3px;"></div>'
            f'</div>'
            f'<div class="pub-bar-value">{fmt(val)}</div>'
            f'</div>'
        )

    _html(f"""
        <div class="pub-card">
            <div class="pub-card-title">{titulo}</div>
            <div class="pub-bar-list">{rows_html}</div>
            <div class="pub-bar-legend">{_legenda_html(df)}</div>
        </div>
    """)

    if n_pages > 1:
        c1, c2, c3 = st.columns([1, 5, 1])
        with c1:
            if st.button("← Ant.", key=f"prev_{key}", disabled=page == 0):
                st.session_state[key] -= 1
                st.rerun()
        with c2:
            st.caption(f"Página {page + 1} de {n_pages}  ·  {n_total} campanhas")
        with c3:
            if st.button("Próx. →", key=f"next_{key}", disabled=page >= n_pages - 1):
                st.session_state[key] += 1
                st.rerun()


# ── Tabela resumo por conta (cidade) ──────────────────────────────────────────
def tabela_resumo(df: pd.DataFrame) -> None:
    grupo = "customer_name" if "customer_name" in df.columns else "campaign_name"
    resumo = df.groupby(grupo, as_index=False).agg(
        Campanhas=("campaign_name", "nunique"),
        Impressoes=("impressions", "sum"),
        Cliques=("clicks", "sum"),
        Investimento=("cost", "sum"),
    )
    resumo = resumo.sort_values("Investimento", ascending=False)
    imp = resumo["Impressoes"].replace(0, pd.NA)
    clk = resumo["Cliques"].replace(0, pd.NA)
    resumo["CTR"] = (resumo["Cliques"] / imp * 100).round(2)
    resumo["CPC"] = (resumo["Investimento"] / clk).round(2)

    total = resumo[["Campanhas", "Impressoes", "Cliques", "Investimento"]].sum()
    total_ctr = (total["Cliques"] / total["Impressoes"] * 100) if total["Impressoes"] else 0
    total_cpc = (total["Investimento"] / total["Cliques"]) if total["Cliques"] else 0

    header = ("<tr><th>Conta</th><th class='num'>Campanhas</th><th class='num'>Impressões</th>"
              "<th class='num'>Cliques</th><th class='num'>CTR (%)</th>"
              "<th class='num'>Investimento (R$)</th><th class='num'>CPC (R$)</th></tr>")

    rows = ""
    for _, r in resumo.iterrows():
        rows += (
            f'<tr><td>{r[grupo]}</td>'
            f'<td class="num">{_br(r["Campanhas"])}</td>'
            f'<td class="num">{_br(r["Impressoes"])}</td>'
            f'<td class="num">{_br(r["Cliques"])}</td>'
            f'<td class="num">{_br(r["CTR"], 2)}</td>'
            f'<td class="num">{_br(r["Investimento"], 2, "R$ ")}</td>'
            f'<td class="num">{_br(r["CPC"], 2, "R$ ")}</td></tr>'
        )
    rows += (
        f'<tr class="total"><td>TOTAL</td>'
        f'<td class="num">{_br(total["Campanhas"])}</td>'
        f'<td class="num">{_br(total["Impressoes"])}</td>'
        f'<td class="num">{_br(total["Cliques"])}</td>'
        f'<td class="num">{_br(total_ctr, 2)}</td>'
        f'<td class="num">{_br(total["Investimento"], 2, "R$ ")}</td>'
        f'<td class="num">{_br(total_cpc, 2, "R$ ")}</td></tr>'
    )

    _html(f"""
        <div class="pub-card">
            <div class="pub-table-wrap">
                <table class="pub-table"><thead>{header}</thead><tbody>{rows}</tbody></table>
            </div>
        </div>
    """)
