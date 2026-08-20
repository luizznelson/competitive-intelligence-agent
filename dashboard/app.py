from __future__ import annotations

import html
import logging
import math
import os
import time
from pathlib import Path
import sys

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.competitive_intelligence.agent import (
    AgentBudgetError,
    AgentRateLimitError,
    AgentTemporaryError,
    ask_agent_sync,
)
from src.competitive_intelligence.ai_guardrails import QuestionValidationError, normalize_question
from src.competitive_intelligence.analytics import (
    collection_health,
    history_maturity,
    latest_observations,
    market_snapshot,
    monitored_products,
    observations_frame,
    overview_metrics,
    price_history,
    product_comparison,
    product_listing_status,
    recent_changes,
    source_summary,
    success_bool_mask,
)
from src.competitive_intelligence.db import init_db, seed_catalog
from src.competitive_intelligence.config import (
    AI_CACHE_TTL_SECONDS,
    AI_MAX_COMPLETION_TOKENS,
    AI_MAX_QUESTION_CHARS,
    AI_MAX_SESSION_MESSAGES,
    AI_MIN_REQUEST_INTERVAL_SECONDS,
    DEMO_MODE,
)
from src.competitive_intelligence.reporting import build_weekly_brief


# =============================================================================
# PAGE
# =============================================================================
st.set_page_config(
    page_title="Competitive Intelligence",
    page_icon="CI",
    layout="wide",
    initial_sidebar_state="expanded",
)

logger = logging.getLogger(__name__)


@st.cache_data(
    ttl=AI_CACHE_TTL_SECONDS,
    max_entries=128,
    show_spinner=False,
)
def cached_agent_answer(question: str, data_version: str) -> str:
    """Cache identical analyses while automatically invalidating on new market data."""
    _ = data_version  # Included in Streamlit cache key to invalidate after a new collection.
    return ask_agent_sync(question)


# =============================================================================
# DESIGN SYSTEM
# Psychology of color:
# - Navy: trust, reliability, executive decision-making
# - Blue: clarity, data, technology
# - Teal: positive opportunity / healthy status
# - Amber: attention without alarm
# - Red: risk / deterioration
# =============================================================================
st.html(
    """
<style>
:root {
  --ink:#172033;
  --ink-2:#344054;
  --muted:#667085;
  --muted-2:#98A2B3;
  --line:#E4E7EC;
  --line-soft:#EEF1F5;
  --surface:#FFFFFF;
  --surface-soft:#F8FAFC;
  --page:#F5F7FA;
  --navy:#17324D;
  --navy-2:#254A6B;
  --blue:#2F6FED;
  --blue-soft:#EEF4FF;
  --teal:#238577;
  --teal-soft:#ECF8F5;
  --amber:#B7791F;
  --amber-soft:#FFF8E8;
  --red:#C24141;
  --red-soft:#FFF1F1;
}

html, body, [class*="css"] {
  font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

[data-testid="stAppViewContainer"] {
  background: var(--page);
}

[data-testid="stHeader"] {
  background: rgba(245,247,250,.94);
  border-bottom: 1px solid var(--line-soft);
}

[data-testid="stSidebar"] {
  background: #FBFCFD;
  border-right: 1px solid var(--line);
}

[data-testid="stSidebar"] > div:first-child {
  padding-top: 1.3rem;
}

.block-container {
  max-width: 1450px;
  padding-top: 1.15rem;
  padding-bottom: 3.5rem;
}

/* Header: intentionally restrained. The data should be the visual focus. */
.ci-hero {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 24px 26px 22px;
  margin-bottom: 16px;
  box-shadow: 0 1px 2px rgba(16,24,40,.025);
}

.ci-hero::after,
.ci-hero-grid { display:none; }

.ci-hero-content {
  max-width: 980px;
}

.ci-eyebrow {
  display:flex;
  align-items:center;
  gap:8px;
  margin-bottom:7px;
  color:var(--navy-2);
  font-size:.72rem;
  font-weight:650;
  letter-spacing:.02em;
  text-transform:none;
}

.ci-eyebrow-dot {
  width:7px;
  height:7px;
  border-radius:50%;
  background:var(--teal);
}

.ci-title {
  color:var(--ink);
  font-size:clamp(1.75rem, 2.7vw, 2.35rem);
  line-height:1.1;
  letter-spacing:-.035em;
  font-weight:720;
}

.ci-subtitle {
  color:var(--muted);
  max-width:860px;
  margin-top:8px;
  font-size:.9rem;
  line-height:1.62;
}

.ci-hero-status {
  display:flex;
  flex-wrap:wrap;
  gap:7px;
  margin-top:15px;
}

.ci-chip-dark {
  display:inline-flex;
  align-items:center;
  gap:6px;
  padding:5px 9px;
  border-radius:7px;
  border:1px solid var(--line);
  background:var(--surface-soft);
  color:var(--ink-2);
  font-size:.67rem;
  font-weight:560;
}

/* KPI cards: no decorative stripes. Small status dot carries semantic color. */
.ci-kpi {
  position:relative;
  min-height:108px;
  background:var(--surface);
  border:1px solid var(--line);
  border-radius:12px;
  padding:15px 16px 13px;
  box-shadow:0 1px 2px rgba(16,24,40,.02);
}

.ci-kpi::before {
  content:"";
  display:block;
  width:7px;
  height:7px;
  border-radius:50%;
  background:var(--kpi-accent, var(--blue));
  margin-bottom:10px;
}

.ci-kpi-label {
  color:var(--muted);
  font-size:.68rem;
  font-weight:630;
  letter-spacing:.02em;
  text-transform:none;
}

.ci-kpi-value {
  color:var(--ink);
  font-size:1.55rem;
  line-height:1.1;
  letter-spacing:-.03em;
  font-weight:710;
  margin-top:5px;
}

.ci-kpi-note {
  color:var(--muted-2);
  font-size:.66rem;
  line-height:1.4;
  margin-top:6px;
}

/* Sections */
.ci-section-head { margin:8px 0 15px; }
.ci-section-kicker {
  color:var(--muted-2);
  font-size:.68rem;
  font-weight:620;
  letter-spacing:.01em;
  text-transform:none;
  margin-bottom:4px;
}
.ci-section-title {
  color:var(--ink);
  font-size:1.08rem;
  font-weight:690;
  letter-spacing:-.015em;
}
.ci-section-subtitle {
  color:var(--muted);
  font-size:.78rem;
  line-height:1.55;
  margin-top:3px;
}

.ci-panel {
  background:var(--surface);
  border:1px solid var(--line);
  border-radius:12px;
  padding:15px 16px;
  box-shadow:none;
}

/* Executive summary */
.ci-summary { display:grid; grid-template-columns:1fr; gap:8px; }
.ci-summary-item {
  background:var(--surface);
  border:1px solid var(--line);
  border-radius:10px;
  padding:12px 13px;
}
.ci-summary-item.attention { border-left:3px solid var(--amber); }
.ci-summary-item.positive  { border-left:3px solid var(--teal); }
.ci-summary-item.neutral   { border-left:3px solid var(--navy-2); }
.ci-summary-item.risk      { border-left:3px solid var(--red); }
.ci-summary-label {
  font-size:.66rem;
  font-weight:620;
  letter-spacing:.01em;
  text-transform:none;
  color:var(--muted-2);
}
.ci-summary-text {
  margin-top:5px;
  color:var(--ink-2);
  font-size:.78rem;
  line-height:1.55;
}
.ci-summary-text strong { color:var(--ink); }

/* Market signals */
.ci-signal {
  border-bottom:1px solid var(--line-soft);
  padding:11px 2px;
}
.ci-signal:last-child { border-bottom:none; }
.ci-signal-top {
  display:flex;
  align-items:flex-start;
  justify-content:space-between;
  gap:12px;
}
.ci-signal-product {
  color:var(--ink-2);
  font-size:.78rem;
  font-weight:620;
  line-height:1.4;
}
.ci-signal-source {
  color:var(--muted-2);
  font-size:.66rem;
  margin-top:3px;
}
.ci-change {
  display:inline-flex;
  align-items:center;
  justify-content:center;
  min-width:56px;
  padding:3px 7px;
  border-radius:6px;
  font-size:.68rem;
  font-weight:650;
  white-space:nowrap;
}
.ci-change.up { color:var(--red); background:var(--red-soft); }
.ci-change.down { color:var(--teal); background:var(--teal-soft); }

/* Product metrics */
.ci-product-metric {
  min-height:86px;
  background:var(--surface);
  border:1px solid var(--line);
  border-radius:11px;
  padding:13px 14px;
}
.ci-product-metric-label {
  color:var(--muted);
  font-size:.67rem;
  font-weight:620;
}
.ci-product-metric-value {
  color:var(--ink);
  font-size:1.2rem;
  font-weight:700;
  letter-spacing:-.02em;
  margin-top:4px;
}
.ci-product-metric-note {
  color:var(--muted-2);
  font-size:.64rem;
  margin-top:3px;
}

.ci-empty {
  background:var(--surface);
  border:1px dashed #CDD3DC;
  border-radius:11px;
  padding:18px;
  color:var(--muted);
  font-size:.77rem;
  line-height:1.6;
}

.ci-callout {
  background:#F5F8FC;
  border:1px solid #DCE5EF;
  border-left:3px solid var(--navy-2);
  border-radius:10px;
  padding:12px 14px;
  color:var(--ink-2);
  font-size:.76rem;
  line-height:1.58;
}

.ci-method-note {
  background:var(--surface-soft);
  border:1px solid var(--line);
  border-radius:9px;
  padding:10px 12px;
  color:var(--muted);
  font-size:.7rem;
  line-height:1.5;
}


/* Storytelling / decision-oriented overview */
.ci-question-box {
  background:#F7FAFC;
  border:1px solid #DCE5EF;
  border-left:4px solid var(--navy-2);
  border-radius:12px;
  padding:15px 17px;
  margin:2px 0 16px;
}
.ci-question-label {
  color:var(--muted-2);
  font-size:.66rem;
  font-weight:650;
  margin-bottom:5px;
}
.ci-question-text {
  color:var(--ink);
  font-size:.98rem;
  line-height:1.5;
  font-weight:640;
}
.ci-question-note {
  color:var(--muted);
  font-size:.72rem;
  line-height:1.5;
  margin-top:5px;
}
.ci-decision-card {
  min-height:126px;
  background:var(--surface);
  border:1px solid var(--line);
  border-radius:12px;
  padding:14px 15px;
}
.ci-decision-kicker {
  color:var(--muted-2);
  font-size:.64rem;
  font-weight:650;
  margin-bottom:7px;
}
.ci-decision-value {
  color:var(--ink);
  font-size:1.05rem;
  line-height:1.35;
  font-weight:700;
}
.ci-decision-note {
  color:var(--muted);
  font-size:.69rem;
  line-height:1.5;
  margin-top:6px;
}
.ci-story-step {
  color:var(--navy-2);
  font-size:.68rem;
  font-weight:700;
  margin-bottom:4px;
}

/* Decision rationale / engineering story */
.ci-context-strip {
  display:grid;
  grid-template-columns:repeat(4, minmax(0,1fr));
  gap:10px;
  margin:2px 0 18px;
}
.ci-context-step {
  background:var(--surface);
  border:1px solid var(--line);
  border-radius:10px;
  padding:11px 12px;
  min-height:84px;
}
.ci-context-num {
  color:var(--muted-2);
  font-size:.62rem;
  font-weight:700;
  margin-bottom:5px;
}
.ci-context-title {
  color:var(--ink);
  font-size:.78rem;
  font-weight:660;
  margin-bottom:3px;
}
.ci-context-text {
  color:var(--muted);
  font-size:.68rem;
  line-height:1.45;
}
.ci-insight-box {
  background:var(--surface);
  border:1px solid var(--line);
  border-radius:12px;
  padding:15px 16px;
  margin-top:10px;
}
.ci-insight-title {
  color:var(--ink);
  font-size:.8rem;
  font-weight:680;
  margin-bottom:8px;
}
.ci-insight-list {
  display:grid;
  gap:7px;
}
.ci-insight-row {
  display:flex;
  gap:8px;
  align-items:flex-start;
  color:var(--ink-2);
  font-size:.74rem;
  line-height:1.5;
}
.ci-insight-bullet {
  width:7px;
  height:7px;
  border-radius:50%;
  background:var(--navy-2);
  margin-top:5px;
  flex:0 0 auto;
}
.ci-tech-decision {
  background:var(--surface);
  border:1px solid var(--line);
  border-radius:12px;
  padding:14px 15px;
  min-height:138px;
}
.ci-tech-decision h4 {
  margin:0 0 6px;
  color:var(--ink);
  font-size:.82rem;
}
.ci-tech-decision p {
  margin:0;
  color:var(--muted);
  font-size:.71rem;
  line-height:1.55;
}
.ci-tech-tag {
  display:inline-block;
  margin-bottom:8px;
  padding:3px 7px;
  border-radius:6px;
  background:var(--surface-soft);
  color:var(--navy-2);
  border:1px solid var(--line);
  font-size:.62rem;
  font-weight:650;
}

/* Native components */
[data-testid="stDataFrame"] {
  border:1px solid var(--line);
  border-radius:10px;
  overflow:hidden;
  background:var(--surface);
}

[data-baseweb="tab-list"] {
  gap:24px;
  border-bottom:1px solid var(--line);
}
[data-baseweb="tab"] {
  height:44px;
  padding-left:1px;
  padding-right:1px;
  font-size:.79rem;
  color:var(--muted) !important;
  font-weight:520;
}
[data-baseweb="tab"][aria-selected="true"] {
  color:var(--navy) !important;
  font-weight:650;
}
[data-baseweb="tab-highlight"] {
  background-color:var(--navy-2) !important;
}

[data-testid="stChatMessage"] {
  background:var(--surface);
  border:1px solid var(--line);
  border-radius:11px;
  padding:4px 8px;
}

/* Sidebar */
[data-testid="stSidebar"] .stButton > button {
  min-height:2.5rem;
  border-radius:9px;
  background:#F0F5FA !important;
  border:1px solid #C8D7E5 !important;
  color:var(--navy) !important;
  font-weight:620 !important;
  box-shadow:none !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
  background:#E7EFF7 !important;
  border-color:#AFC4D8 !important;
  color:#102A43 !important;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
  color:var(--muted);
}

/* Sliders: neutral blue instead of default red */
[data-testid="stSlider"] [role="slider"],
[data-testid="stSelectSlider"] [role="slider"] {
  background-color:var(--navy-2) !important;
  border-color:var(--navy-2) !important;
}

hr { border-color:var(--line) !important; }

@media (max-width:900px) {
  .ci-context-strip { grid-template-columns:1fr 1fr; }
  .ci-hero { padding:20px; }
  .ci-title { font-size:1.7rem; }
  .ci-subtitle { font-size:.84rem; }
}
</style>
"""
)


# =============================================================================
# HELPERS
# =============================================================================
def brl(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value):
        return "—"
    return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(value, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):.{digits}f}%"


def dt_label(value) -> str:
    if value is None or pd.isna(value):
        return "Sem coleta"
    ts = pd.to_datetime(value)
    return ts.strftime("%d/%m/%Y %H:%M")


def style_fig(fig, height: int = 380, title: str | None = None):
    fig.update_layout(
        height=height,
        margin=dict(l=16, r=16, t=44 if title else 18, b=16),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#FFFFFF",
        font=dict(family="Inter, Segoe UI, Arial", color="#667085", size=11),
        title=(
            dict(text=title, font=dict(size=13, color="#0F172A"), x=0.01, xanchor="left")
            if title
            else dict(text="")
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=10),
            title_text="",
        ),
        hoverlabel=dict(font_size=11, bgcolor="#172033", font_color="#FFFFFF"),
    )
    fig.update_xaxes(showgrid=False, linecolor="#E4E7EC", tickfont=dict(color="#667085"))
    fig.update_yaxes(gridcolor="#F2F4F7", zeroline=False, tickfont=dict(color="#667085"))
    return fig


def kpi(label: str, value: str, note: str, accent: str = "#2563EB"):
    st.html(
        f"""
<div class="ci-kpi" style="--kpi-accent:{html.escape(accent)}">
  <div class="ci-kpi-label">{html.escape(str(label))}</div>
  <div class="ci-kpi-value">{html.escape(str(value))}</div>
  <div class="ci-kpi-note">{html.escape(str(note))}</div>
</div>
"""
    )


def section_header(kicker: str, title: str, subtitle: str):
    st.html(
        f"""
<div class="ci-section-head">
  <div class="ci-section-kicker">{html.escape(kicker)}</div>
  <div class="ci-section-title">{html.escape(title)}</div>
  <div class="ci-section-subtitle">{html.escape(subtitle)}</div>
</div>
"""
    )


def product_metric(label: str, value: str, note: str = ""):
    st.html(
        f"""
<div class="ci-product-metric">
  <div class="ci-product-metric-label">{html.escape(label)}</div>
  <div class="ci-product-metric-value">{html.escape(value)}</div>
  <div class="ci-product-metric-note">{html.escape(note)}</div>
</div>
"""
    )


def summary_item(label: str, text: str, tone: str = "neutral"):
    st.html(
        f"""
<div class="ci-summary-item {html.escape(tone)}">
  <div class="ci-summary-label">{html.escape(label)}</div>
  <div class="ci-summary-text">{text}</div>
</div>
"""
    )


def compact_name(value, max_len: int = 46) -> str:
    value = str(value)
    return value if len(value) <= max_len else value[: max_len - 1].rstrip() + "…"


def decision_card(kicker: str, value: str, note: str):
    st.html(
        f"""
<div class="ci-decision-card">
  <div class="ci-decision-kicker">{html.escape(kicker)}</div>
  <div class="ci-decision-value">{html.escape(value)}</div>
  <div class="ci-decision-note">{html.escape(note)}</div>
</div>
"""
    )


# =============================================================================
# DATA
# =============================================================================
init_db()
if not DEMO_MODE:
    seed_catalog()

metrics = overview_metrics()
latest = latest_observations()
snapshot = market_snapshot()
health = collection_health(20)
sources = source_summary()
maturity = history_maturity()

last_update = None
if not latest.empty:
    last_update = pd.to_datetime(latest["collected_at"]).max()


# =============================================================================
# SIDEBAR
# =============================================================================
with st.sidebar:
    st.markdown("### Competitive Intelligence")
    st.caption("Operação, filtros e integrações")
    st.divider()

    st.markdown("**Dados de mercado**")
    if last_update is not None:
        st.caption(f"Última observação: {dt_label(last_update)}")
    if DEMO_MODE:
        st.caption("Versão pública em modo demonstrativo, baseada em snapshot de dados reais coletados pelo pipeline.")
    else:
        st.caption("Coletas são executadas pelo CLI; o dashboard permanece somente leitura.")

    st.divider()
    st.markdown("**Parâmetros analíticos**")
    threshold = st.slider(
        "Movimento relevante",
        min_value=1.0,
        max_value=20.0,
        value=3.0,
        step=0.5,
        format="%.1f%%",
        help="Variação mínima absoluta entre as duas últimas observações para gerar um sinal.",
    )
    history_days = st.select_slider(
        "Janela histórica",
        options=[7, 14, 30, 60, 90],
        value=30,
        help="Período exibido nos gráficos de histórico de preço.",
    )

    st.divider()
    st.markdown("**Integrações**")
    if os.getenv("GROQ_API_KEY"):
        st.success("Groq configurada")
    else:
        st.info("Groq não configurada")
    st.caption("MCP disponibiliza as ferramentas analíticas ao agente de IA.")

changes = recent_changes(threshold)


# =============================================================================
# HERO
# =============================================================================
source_count = int(metrics.get("competitors", 0))
last_collection_rate = metrics.get("last_collection_success_rate")
healthy = pd.notna(last_collection_rate) and float(last_collection_rate) >= 80
status_label = "Coleta saudável" if healthy else "Coleta a verificar"
status_dot = "#14B8A6" if healthy else "#F59E0B"

st.html(
    f"""
<div class="ci-hero">
  <div class="ci-hero-grid"></div>
  <div class="ci-hero-content">
    <div class="ci-eyebrow"><span class="ci-eyebrow-dot"></span> Inteligência competitiva</div>
    <div class="ci-title">Competitive Intelligence</div>
    <div class="ci-subtitle">
      Substitui o acompanhamento manual de concorrentes por uma rotina rastreável de coleta, comparação e histórico — transformando preços e disponibilidade em sinais que orientam onde investigar primeiro.
    </div>
    <div class="ci-hero-status">
      <span class="ci-chip-dark">{metrics.get('products', 0)} SKUs monitorados</span>
      <span class="ci-chip-dark">{metrics.get('configured_listings', 0)} ofertas configuradas</span>
      <span class="ci-chip-dark">{source_count} fontes</span>
      <span class="ci-chip-dark">Atualizado · {html.escape(dt_label(last_update))}</span>
      <span class="ci-chip-dark"><span style="width:6px;height:6px;border-radius:50%;background:{status_dot};display:inline-block"></span>{html.escape(status_label)}</span>
    </div>
  </div>
</div>
"""
)


# =============================================================================
# KPIs
# =============================================================================
comparable_products = int(
    len(snapshot[snapshot["spread_pct"].notna() & (snapshot["competitors_with_price"] >= 2)])
) if not snapshot.empty else 0

c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    kpi("Produtos monitorados", str(metrics["products"]), "catálogo ativo", "#17324D")
with c2:
    kpi("Ofertas configuradas", str(metrics.get("configured_listings", 0)), "URLs monitoradas", "#2F6FED")
with c3:
    kpi("Produtos comparáveis", str(comparable_products), "2+ ofertas válidas", "#238577")
with c4:
    kpi("Movimentos relevantes", str(len(changes)), f"|Δ| ≥ {threshold:.1f}%", "#B7791F")
with c5:
    health_accent = "#238577" if healthy else ("#B7791F" if pd.notna(last_collection_rate) and float(last_collection_rate) >= 50 else "#C24141")
    kpi("Cobertura da coleta", pct(last_collection_rate), "última execução", health_accent)

if latest.empty:
    st.html(
        """
<div class="ci-empty" style="margin-top:16px">
  O catálogo está configurado, mas ainda não há observações no banco selecionado. Em ambiente local, execute a coleta pelo CLI para iniciar o histórico real do mercado.
</div>
"""
    )


# =============================================================================
# NAVIGATION
# =============================================================================
overview_tab, market_tab, agent_tab, quality_tab, method_tab = st.tabs(
    ["Visão executiva", "Mercado & preços", "Analista de IA", "Operação & qualidade", "Método & decisões"]
)


# =============================================================================
# EXECUTIVE OVERVIEW — STORY FIRST
# =============================================================================
with overview_tab:
    st.write("")

    section_header(
        "Visão executiva",
        "O que merece atenção no mercado agora?",
        "A visão executiva prioriza decisões: onde há maior divergência de preço, quem aparece com menor oferta e onde existem sinais de disponibilidade ou mudança.",
    )

    st.html(
        """
<div class="ci-question-box">
  <div class="ci-question-label">Pergunta de negócio</div>
  <div class="ci-question-text">Quais produtos e fontes apresentam sinais competitivos que justificam investigação ou ação comercial?</div>
  <div class="ci-question-note">O panorama transforma preços e disponibilidade em uma sequência de leitura: prioridade → evidência → tendência.</div>
</div>
"""
    )

    st.html(
        """
<div class="ci-context-strip">
  <div class="ci-context-step"><div class="ci-context-num">01</div><div class="ci-context-title">Coletar</div><div class="ci-context-text">Capturar preço e disponibilidade das páginas monitoradas.</div></div>
  <div class="ci-context-step"><div class="ci-context-num">02</div><div class="ci-context-title">Estruturar</div><div class="ci-context-text">Normalizar produto, fonte, seller e histórico em uma base comum.</div></div>
  <div class="ci-context-step"><div class="ci-context-num">03</div><div class="ci-context-title">Comparar</div><div class="ci-context-text">Calcular dispersão, liderança de preço, disponibilidade e movimentos.</div></div>
  <div class="ci-context-step"><div class="ci-context-num">04</div><div class="ci-context-title">Priorizar</div><div class="ci-context-text">Destacar onde os dados justificam investigação comercial.</div></div>
</div>
"""
    )

    if snapshot.empty:
        st.html('<div class="ci-empty">Ainda não há observações disponíveis para gerar a primeira fotografia competitiva do mercado.</div>')
    else:
        comparable_snapshot = snapshot[
            snapshot["spread_pct"].notna() & (snapshot["competitors_with_price"] >= 2)
        ].copy()

        # ---------------------------------------------------------------------
        # Decision cards — answer the business question before showing charts.
        # ---------------------------------------------------------------------
        top_spread_row = None
        if not comparable_snapshot.empty:
            top_spread_row = comparable_snapshot.sort_values("spread_pct", ascending=False).iloc[0]

        price_leader = None
        price_leader_count = 0
        comparable_count = int(len(comparable_snapshot))
        if comparable_count:
            leader_counts = comparable_snapshot["min_competitor"].dropna().value_counts()
            if not leader_counts.empty:
                price_leader = str(leader_counts.index[0])
                price_leader_count = int(leader_counts.iloc[0])

        availability_by_source = pd.DataFrame()
        known_availability = latest[
            (latest["success"] == True) & latest["available"].notna()  # noqa: E712
        ].copy() if not latest.empty else pd.DataFrame()
        if not known_availability.empty:
            availability_by_source = (
                known_availability.groupby("competitor", as_index=False)
                .agg(
                    offers=("listing_id", "count"),
                    available_offers=("available", lambda s: int(s.astype(bool).sum())),
                )
            )
            availability_by_source["availability_rate"] = (
                availability_by_source["available_offers"] / availability_by_source["offers"] * 100
            )

        lowest_availability = None
        if not availability_by_source.empty:
            lowest_availability = availability_by_source.sort_values("availability_rate").iloc[0]

        d1, d2, d3 = st.columns(3, gap="medium")
        with d1:
            if top_spread_row is not None:
                decision_card(
                    "Maior divergência de preço",
                    f"{top_spread_row['spread_pct']:.1f}%",
                    f"{compact_name(top_spread_row['product'], 38)} · {top_spread_row['min_competitor']} → {top_spread_row['max_competitor']}",
                )
            else:
                decision_card(
                    "Maior divergência de preço",
                    "Em formação",
                    "São necessárias duas ou mais ofertas válidas do mesmo SKU.",
                )
        with d2:
            if price_leader:
                decision_card(
                    "Fonte que mais lidera em preço",
                    price_leader,
                    f"Menor oferta em {price_leader_count} de {comparable_count} produtos comparáveis.",
                )
            else:
                decision_card(
                    "Fonte que mais lidera em preço",
                    "Em formação",
                    "Ainda não há produtos comparáveis suficientes.",
                )
        with d3:
            if lowest_availability is not None:
                decision_card(
                    "Maior atenção em disponibilidade",
                    str(lowest_availability["competitor"]),
                    f"{lowest_availability['availability_rate']:.1f}% das ofertas com status conhecido estão disponíveis.",
                )
            else:
                decision_card(
                    "Maior atenção em disponibilidade",
                    "Sem leitura",
                    "As fontes ainda não retornaram status de disponibilidade suficiente.",
                )

        insight_rows = []
        if top_spread_row is not None:
            insight_rows.append(
                f"<strong>{html.escape(compact_name(top_spread_row['product'], 58))}</strong> concentra a maior divergência atual: "
                f"{top_spread_row['spread_pct']:.1f}% entre {html.escape(str(top_spread_row['min_competitor']))} e {html.escape(str(top_spread_row['max_competitor']))}."
            )
        if price_leader:
            insight_rows.append(
                f"<strong>{html.escape(price_leader)}</strong> aparece como menor preço em {price_leader_count} de {comparable_count} SKUs comparáveis; isso indica presença competitiva, não recomendação automática de repricing."
            )
        if lowest_availability is not None:
            insight_rows.append(
                f"<strong>{html.escape(str(lowest_availability['competitor']))}</strong> apresenta a menor disponibilidade observada entre as fontes com status conhecido ({lowest_availability['availability_rate']:.1f}%)."
            )
        insight_rows.append(
            f"O histórico já permite medir movimento em <strong>{maturity['with_history']} de {maturity['configured_listings']}</strong> ofertas ativas ({maturity['history_coverage_pct']:.1f}%)."
        )
        rendered_insights = "".join(
            f'<div class="ci-insight-row"><span class="ci-insight-bullet"></span><span>{row}</span></div>'
            for row in insight_rows
        )
        st.html(
            f'<div class="ci-insight-box"><div class="ci-insight-title">Leitura do conjunto</div><div class="ci-insight-list">{rendered_insights}</div></div>'
        )

        st.write("")

        # ---------------------------------------------------------------------
        # Step 1 — Which products deserve attention?
        # Use relative spread, not absolute R$, so mice, SSDs and headsets can
        # be compared without an expensive product distorting the axis.
        # ---------------------------------------------------------------------
        st.html('<div class="ci-story-step">1 · PRIORIDADE</div>')
        section_header(
            "",
            "Onde há maior diferença entre as lojas?",
            "Produtos ordenados pela dispersão percentual entre a menor e a maior oferta disponível. A escala percentual permite comparar categorias com preços muito diferentes.",
        )

        if comparable_snapshot.empty:
            st.html('<div class="ci-empty">Ainda não existem produtos com pelo menos duas ofertas válidas e disponíveis.</div>')
        else:
            top_n = comparable_snapshot.sort_values("spread_pct", ascending=False).head(8).copy()
            top_n["label"] = top_n["product"].map(lambda x: compact_name(x, 44))
            top_n = top_n.sort_values("spread_pct", ascending=True)

            fig_spread = go.Figure()
            fig_spread.add_trace(
                go.Bar(
                    x=top_n["spread_pct"],
                    y=top_n["label"],
                    orientation="h",
                    marker=dict(color="#2F6FED"),
                    text=top_n["spread_pct"].map(lambda x: f"{x:.1f}%"),
                    textposition="outside",
                    customdata=top_n[["min_price", "min_competitor", "max_price", "max_competitor"]].values,
                    hovertemplate=(
                        "<b>%{y}</b><br>"
                        "Dispersão: %{x:.1f}%<br>"
                        "Menor: R$ %{customdata[0]:,.2f} · %{customdata[1]}<br>"
                        "Maior: R$ %{customdata[2]:,.2f} · %{customdata[3]}"
                        "<extra></extra>"
                    ),
                )
            )
            fig_spread.update_xaxes(title="Diferença entre menor e maior oferta (%)", rangemode="tozero")
            fig_spread.update_yaxes(title="", automargin=True)
            fig_spread.update_layout(showlegend=False)
            st.plotly_chart(style_fig(fig_spread, 390), width="stretch", config={"displayModeBar": False})
            st.caption("Mostrados os 8 produtos com maior dispersão entre ofertas válidas. Os preços absolutos ficam na aba Mercado & preços.")

        # ---------------------------------------------------------------------
        # Step 2 — Which retailer is applying price pressure / availability?
        # ---------------------------------------------------------------------
        st.write("")
        st.html('<div class="ci-story-step">2 · FONTES</div>')
        section_header(
            "",
            "Quem está pressionando preço e onde há ruptura?",
            "A liderança de menor preço mostra presença competitiva; disponibilidade mostra capacidade de sustentar a oferta.",
        )

        source_left, source_right = st.columns(2, gap="large")

        with source_left:
            if comparable_count:
                wins = (
                    comparable_snapshot["min_competitor"]
                    .dropna()
                    .value_counts()
                    .rename_axis("Fonte")
                    .reset_index(name="Produtos")
                    .sort_values("Produtos", ascending=True)
                )
                fig_wins = go.Figure(
                    go.Bar(
                        x=wins["Produtos"],
                        y=wins["Fonte"],
                        orientation="h",
                        marker=dict(color="#17324D"),
                        text=wins["Produtos"],
                        textposition="outside",
                        hovertemplate="<b>%{y}</b><br>Menor preço em %{x} SKU(s)<extra></extra>",
                    )
                )
                fig_wins.update_xaxes(title="Quantidade de SKUs com menor preço", dtick=1, rangemode="tozero")
                fig_wins.update_yaxes(title="")
                fig_wins.update_layout(showlegend=False)
                st.plotly_chart(style_fig(fig_wins, 290, "Liderança de menor preço"), width="stretch", config={"displayModeBar": False})
            else:
                st.html('<div class="ci-empty">A liderança por preço será calculada quando houver SKUs comparáveis.</div>')

        with source_right:
            if not availability_by_source.empty:
                avail = availability_by_source.sort_values("availability_rate", ascending=True).copy()
                fig_avail = go.Figure(
                    go.Bar(
                        x=avail["availability_rate"],
                        y=avail["competitor"],
                        orientation="h",
                        marker=dict(color="#238577"),
                        text=avail["availability_rate"].map(lambda x: f"{x:.0f}%"),
                        textposition="outside",
                        customdata=avail[["available_offers", "offers"]].values,
                        hovertemplate=(
                            "<b>%{y}</b><br>Disponibilidade: %{x:.1f}%<br>"
                            "%{customdata[0]} de %{customdata[1]} ofertas disponíveis<extra></extra>"
                        ),
                    )
                )
                fig_avail.update_xaxes(title="Ofertas disponíveis (%)", range=[0, 105])
                fig_avail.update_yaxes(title="")
                fig_avail.update_layout(showlegend=False)
                st.plotly_chart(style_fig(fig_avail, 290, "Disponibilidade por fonte"), width="stretch", config={"displayModeBar": False})
            else:
                st.html('<div class="ci-empty">Ainda não há status de disponibilidade suficiente para comparar as fontes.</div>')

        # ---------------------------------------------------------------------
        # Step 3 — What changed? If history is insufficient, make that explicit.
        # ---------------------------------------------------------------------
        st.write("")
        st.html('<div class="ci-story-step">3 · MOVIMENTO</div>')
        section_header(
            "",
            "O que mudou desde a coleta anterior?",
            f"Movimentos absolutos iguais ou superiores a {threshold:.1f}% entre as duas últimas observações válidas da mesma oferta.",
        )

        if changes.empty:
            successful_history = observations_frame()
            valid_history = successful_history[
                (successful_history["success"] == True) & successful_history["price"].notna()  # noqa: E712
            ].copy() if not successful_history.empty else pd.DataFrame()
            obs_per_listing = valid_history.groupby("listing_id").size() if not valid_history.empty else pd.Series(dtype=int)
            listings_with_history = int((obs_per_listing >= 2).sum()) if not obs_per_listing.empty else 0

            st.html(
                f"""
<div class="ci-callout">
  <strong>Histórico em formação.</strong> A fotografia atual já permite comparar preços e disponibilidade, mas variação exige pelo menos duas observações válidas da mesma oferta. Neste momento, <strong>{listings_with_history}</strong> listing(s) já possuem histórico suficiente para medir mudança. As próximas coletas transformam a fotografia em tendência.
</div>
"""
            )
        else:
            change_view = changes.head(8).copy()
            change_view["Produto"] = change_view["canonical_name"].map(lambda x: compact_name(x, 50))
            change_view["Fonte"] = change_view["competitor"]
            change_view["Preço atual"] = change_view["price"].map(brl)
            change_view["Preço anterior"] = change_view["previous_price"].map(brl)
            change_view["Variação"] = change_view["change_pct"].map(lambda x: f"{x:+.1f}%")
            st.dataframe(
                change_view[["Produto", "Fonte", "Preço anterior", "Preço atual", "Variação"]],
                width="stretch",
                hide_index=True,
            )

        # ---------------------------------------------------------------------
        # Evidence table — compact, not the main story.
        # ---------------------------------------------------------------------
        st.write("")
        section_header(
            "Evidências",
            "Produtos que mais merecem investigação",
            "Resumo das maiores dispersões atuais. A exploração completa permanece na aba Mercado & preços.",
        )

        evidence = comparable_snapshot.sort_values("spread_pct", ascending=False).head(10).copy()
        if evidence.empty:
            st.html('<div class="ci-empty">Ainda não há evidências comparáveis suficientes.</div>')
        else:
            evidence["Produto"] = evidence["product"].map(lambda x: compact_name(x, 52))
            evidence["Menor"] = evidence.apply(lambda r: f"{brl(r['min_price'])} · {r['min_competitor']}", axis=1)
            evidence["Mediana"] = evidence["median_price"].map(brl)
            evidence["Maior"] = evidence.apply(lambda r: f"{brl(r['max_price'])} · {r['max_competitor']}", axis=1)
            evidence["Dispersão"] = evidence["spread_pct"].map(lambda x: f"{x:.1f}%")
            evidence["Fontes"] = evidence["competitors_with_price"].astype(int)
            st.dataframe(
                evidence[["Produto", "Menor", "Mediana", "Maior", "Dispersão", "Fontes"]],
                width="stretch",
                hide_index=True,
            )


# =============================================================================
# MARKET & PRODUCTS
# =============================================================================
with market_tab:
    st.write("")
    section_header(
        "Exploração",
        "Mercado & preços",
        "Análise detalhada das ofertas atuais, disponibilidade e histórico acumulado para cada produto.",
    )

    catalog_products = monitored_products()
    if catalog_products.empty:
        st.html('<div class="ci-empty">O catálogo ainda não possui produtos ativos para monitoramento.</div>')
    else:
        labels = dict(zip(catalog_products["canonical_name"], catalog_products["canonical_id"]))
        selected_name = st.selectbox("Produto monitorado", list(labels.keys()))
        selected_id = labels[selected_name]

        listing_status = product_listing_status(selected_id)
        comparison = product_comparison(selected_id)
        history = price_history(selected_id, history_days)

        observed = listing_status[
            (listing_status["success"] == True) & listing_status["price"].notna()  # noqa: E712
        ].copy() if not listing_status.empty else pd.DataFrame()

        total_sources = int(len(listing_status))
        available_sources = (
            int((listing_status["available"] == True).sum())  # noqa: E712
            if not listing_status.empty and "available" in listing_status.columns
            else 0
        )

        valid_prices = comparison["price"].dropna().astype(float) if not comparison.empty else pd.Series(dtype=float)
        low = valid_prices.min() if not valid_prices.empty else None
        median = valid_prices.median() if not valid_prices.empty else None
        high = valid_prices.max() if not valid_prices.empty else None

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            product_metric("Menor preço disponível", brl(low), "entre ofertas elegíveis")
        with m2:
            product_metric("Mediana disponível", brl(median), "entre ofertas elegíveis")
        with m3:
            product_metric("Maior preço disponível", brl(high), "entre ofertas elegíveis")
        with m4:
            product_metric("Disponibilidade", f"{available_sources}/{total_sources}", "fontes com estoque agora")

        never_collected = int(listing_status["observation_id"].isna().sum()) if not listing_status.empty else 0
        failed_latest = (
            int(((listing_status["observation_id"].notna()) & (listing_status["success"] != True)).sum())  # noqa: E712
            if not listing_status.empty
            else 0
        )

        if total_sources and never_collected == total_sources:
            st.html(
                '<div class="ci-empty" style="margin-top:16px"><strong>Aguardando primeira coleta.</strong> '
                'O produto está no catálogo, mas ainda não possui observações nas fontes configuradas.</div>'
            )
        elif not observed.empty and available_sources == 0:
            st.html(
                '<div class="ci-callout" style="margin-top:16px"><strong>Sem oferta disponível no momento.</strong> '
                'As fontes foram coletadas e possuem preços observados, porém nenhuma confirmou estoque. '
                'Esses valores permanecem como referência e histórico, mas não entram no comparativo de preço disponível.</div>'
            )
        elif failed_latest > 0:
            st.html(
                f'<div class="ci-callout" style="margin-top:16px"><strong>Cobertura parcial da fotografia atual.</strong> '
                f'{failed_latest} de {total_sources} fonte(s) apresentou(aram) falha na observação mais recente. '
                'As métricas usam somente ofertas elegíveis.</div>'
            )

        if not listing_status.empty:
            st.write("")
            left, right = st.columns([1, 1.45], gap="large")

            with left:
                section_header(
                    "Detalhe",
                    "Situação das fontes",
                    "Última observação de cada listing ativo, incluindo indisponibilidade e falhas de coleta.",
                )
                table = listing_status[[
                    "competitor", "price", "available", "seller", "success", "observation_id"
                ]].copy()

                def _listing_state(row):
                    if pd.isna(row["observation_id"]):
                        return "Aguardando coleta"
                    if row["success"] is not True and row["success"] != True:
                        return "Falha na coleta"
                    if row["available"] is False or row["available"] == False:  # noqa: E712
                        return "Sem estoque"
                    if row["available"] is True or row["available"] == True:  # noqa: E712
                        return "Disponível"
                    return "Disponibilidade não confirmada"

                table["Situação"] = table.apply(_listing_state, axis=1)
                table["Entra na comparação"] = table.apply(
                    lambda row: "Sim"
                    if (
                        pd.notna(row["observation_id"])
                        and row["success"] == True  # noqa: E712
                        and pd.notna(row["price"])
                        and row["available"] != False  # noqa: E712
                    )
                    else "Não",
                    axis=1,
                )
                table["price"] = table["price"].map(lambda x: brl(x) if pd.notna(x) else "—")
                table["seller"] = table["seller"].fillna("—")
                table = table[["competitor", "price", "Situação", "seller", "Entra na comparação"]]
                table.columns = ["Fonte", "Preço observado", "Situação", "Seller", "Entra na comparação"]
                st.dataframe(table, width="stretch", hide_index=True)

            with right:
                section_header(
                    "Comparação",
                    "Preços observados por fonte",
                    "Ofertas sem estoque continuam visíveis como evidência, mas não entram no comparativo de preço disponível.",
                )
                if not observed.empty:
                    plot_df = observed.copy()
                    plot_df["Situação"] = plot_df["available"].map(
                        lambda x: "Disponível" if x is True or x == True else ("Sem estoque" if x is False or x == False else "Não confirmada")
                    )
                    current_fig = px.bar(
                        plot_df.sort_values("price", ascending=True),
                        x="price",
                        y="competitor",
                        color="Situação",
                        orientation="h",
                        labels={"price": "Preço", "competitor": "Fonte"},
                        color_discrete_map={
                            "Disponível": "#2563EB",
                            "Sem estoque": "#98A2B3",
                            "Não confirmada": "#F59E0B",
                        },
                    )
                    current_fig.update_traces(hovertemplate="%{y}<br>R$ %{x:,.2f}<extra></extra>")
                    current_fig.update_xaxes(tickprefix="R$ ")
                    current_fig.update_layout(legend_title_text="")
                    st.plotly_chart(style_fig(current_fig, 315), width="stretch")
                else:
                    st.html('<div class="ci-empty">Ainda não há preço observado válido para este produto.</div>')

        if not history.empty:
            st.write("")
            section_header(
                "Tendência",
                "Histórico de preço",
                f"Preços observados com sucesso nos últimos {history_days} dias, inclusive quando a oferta estava sem estoque.",
            )
            hist_fig = px.line(
                history,
                x="collected_at",
                y="price",
                color="competitor",
                markers=True,
                labels={"collected_at": "Data", "price": "Preço", "competitor": "Fonte"},
                color_discrete_sequence=["#2563EB", "#0F766E", "#F59E0B", "#7C3AED", "#64748B"],
            )
            hist_fig.update_yaxes(tickprefix="R$ ")
            hist_fig.update_traces(line=dict(width=2.4), marker=dict(size=6))
            st.plotly_chart(style_fig(hist_fig, 410), width="stretch")
            st.html(
                '<div class="ci-method-note">O histórico começa na primeira execução do pipeline. '
                'O projeto não cria backfill artificial de preços anteriores. Preço observado sem estoque é mantido '
                'como evidência histórica, mas não é tratado como oferta disponível.</div>'
            )
        elif never_collected == 0:
            st.write("")
            st.html('<div class="ci-empty">Ainda não há histórico de preço válido para este produto na janela selecionada.</div>')


# =============================================================================
# AI ANALYST
# =============================================================================
with agent_tab:
    st.write("")
    section_header(
        "Inteligência assistida",
        "Analista de IA",
        "A IA consulta ferramentas MCP sobre os dados persistidos. Nenhum cálculo de preço ou disponibilidade é delegado ao modelo.",
    )

    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = []
    if "agent_question_draft" not in st.session_state:
        st.session_state.agent_question_draft = ""

    st.html(
        """
<div class="ci-callout">
  <strong>Uso controlado.</strong> A análise só é executada após uma ação explícita em <strong>Analisar</strong>. Perguntas idênticas podem reutilizar uma resposta em cache, e cada execução possui limites de tamanho, etapas, ferramentas e resposta.
</div>
"""
    )
    st.write("")

    q1, q2, q3 = st.columns(3)
    suggestions = [
        "Quais produtos merecem atenção agora?",
        "Qual produto tem maior dispersão de preços?",
        "Como está a saúde da coleta?",
    ]
    for col, suggestion in zip([q1, q2, q3], suggestions):
        with col:
            if st.button(suggestion, width="stretch", key=f"suggest_{suggestion}"):
                # Suggestions only populate the draft. They never call the API.
                st.session_state.agent_question_draft = suggestion
                st.rerun()

    groq_configured = bool(os.getenv("GROQ_API_KEY"))
    with st.form("agent_analysis_form", clear_on_submit=False):
        st.text_area(
            "Pergunta",
            key="agent_question_draft",
            max_chars=AI_MAX_QUESTION_CHARS,
            height=96,
            placeholder="Ex.: quais produtos têm maior diferença de preço entre as fontes disponíveis?",
            help=f"Máximo de {AI_MAX_QUESTION_CHARS} caracteres.",
        )
        submitted = st.form_submit_button(
            "Analisar",
            type="primary",
            disabled=not groq_configured,
            use_container_width=False,
        )

    cache_minutes = max(1, int(AI_CACHE_TTL_SECONDS / 60))
    cache_text = f"cache de até {cache_minutes} min para perguntas idênticas"
    st.caption(
        f"Proteções: {AI_MAX_QUESTION_CHARS} caracteres por pergunta · "
        f"até {AI_MAX_COMPLETION_TOKENS} tokens de resposta por etapa · {cache_text}."
    )

    if not groq_configured:
        st.info(
            "Analista de IA indisponível neste ambiente. No Streamlit Cloud, configure `GROQ_API_KEY` em Settings → Secrets."
        )

    if submitted:
        try:
            question = normalize_question(
                st.session_state.agent_question_draft,
                AI_MAX_QUESTION_CHARS,
            )
        except QuestionValidationError as exc:
            st.warning(str(exc))
        else:
            now = time.monotonic()
            last_request = float(st.session_state.get("agent_last_request_monotonic", 0.0))
            remaining = AI_MIN_REQUEST_INTERVAL_SECONDS - (now - last_request)

            if remaining > 0:
                st.warning(
                    f"Aguarde {math.ceil(remaining)} s antes de iniciar outra análise nesta sessão."
                )
            else:
                st.session_state.agent_last_request_monotonic = now
                st.session_state.agent_messages.append({"role": "user", "content": question})
                st.session_state.agent_messages = st.session_state.agent_messages[-AI_MAX_SESSION_MESSAGES:]

                data_version = (
                    pd.to_datetime(last_update).isoformat()
                    if last_update is not None
                    else "no-observations"
                )

                with st.spinner("Consultando as evidências e sintetizando a análise..."):
                    try:
                        answer = cached_agent_answer(question, data_version)
                    except AgentRateLimitError as exc:
                        wait_hint = ""
                        if exc.retry_after_seconds:
                            wait_hint = f" A API sugeriu aguardar cerca de {exc.retry_after_seconds} s."
                        answer = (
                            "O limite temporário de uso do Analista de IA foi atingido. "
                            "Os indicadores e gráficos do dashboard continuam disponíveis normalmente."
                            + wait_hint
                        )
                    except AgentBudgetError as exc:
                        answer = str(exc)
                    except AgentTemporaryError:
                        answer = (
                            "O serviço de IA está temporariamente indisponível. "
                            "Tente novamente mais tarde; os dados determinísticos do dashboard não são afetados."
                        )
                    except Exception:
                        logger.exception("Falha inesperada no Analista de IA")
                        answer = (
                            "Não foi possível concluir a análise agora. "
                            "Tente novamente mais tarde ou reformule a pergunta."
                        )

                st.session_state.agent_messages.append({"role": "assistant", "content": answer})
                st.session_state.agent_messages = st.session_state.agent_messages[-AI_MAX_SESSION_MESSAGES:]
                st.rerun()

    if st.session_state.agent_messages:
        st.write("")
        section_header(
            "Sessão",
            "Análises desta visita",
            "O histórico abaixo é apenas de interface; cada nova análise é independente e só ocorre mediante envio manual.",
        )
        for message in st.session_state.agent_messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if st.button("Limpar histórico da sessão", key="clear_agent_history"):
            st.session_state.agent_messages = []
            st.session_state.agent_question_draft = ""
            st.rerun()

    st.write("")
    st.html(
        """
<div class="ci-method-note">
  Princípio do projeto: preços, variações, disponibilidade e indicadores são calculados fora do LLM. O modelo recebe apenas resultados das ferramentas MCP, possui orçamento limitado de execução e não deve inventar observações ausentes.
</div>
"""
    )


# =============================================================================
# OPERATIONS & DATA QUALITY
# =============================================================================
with quality_tab:
    st.write("")
    section_header(
        "Confiabilidade",
        "Operação & qualidade",
        "Taxa de sucesso, métodos de extração, rastreabilidade das observações e relatório executivo.",
    )

    if health.empty:
        st.html('<div class="ci-empty">Ainda não existem execuções registradas.</div>')
    else:
        health_display = health.copy()
        health_display["success_rate"] = health_display.apply(
            lambda r: (r["successful"] / r["total_listings"] * 100) if r["total_listings"] else 0,
            axis=1,
        )
        health_display["started_at"] = pd.to_datetime(health_display["started_at"])

        last_run = health_display.iloc[0]
        q1, q2, q3, q4 = st.columns(4)
        with q1:
            product_metric("Última execução", dt_label(last_run["started_at"]), "início da coleta")
        with q2:
            product_metric(
                "Taxa de sucesso",
                pct(last_run["success_rate"]),
                f"{int(last_run['successful'])}/{int(last_run['total_listings'])} ofertas",
            )
        with q3:
            product_metric("Falhas", str(int(last_run["failed"])), "última execução")
        with q4:
            product_metric("Execuções", str(len(health_display)), "janela carregada")

        st.write("")
        left, right = st.columns([1.45, 1], gap="large")

        with left:
            section_header("Histórico", "Saúde das execuções", "Taxa de sucesso das coletas registradas.")
            health_fig = px.area(
                health_display.sort_values("started_at"),
                x="started_at",
                y="success_rate",
                labels={"started_at": "Execução", "success_rate": "Taxa de sucesso"},
            )
            health_fig.update_traces(line_color="#2563EB", fillcolor="rgba(37,99,235,.10)", name="Taxa de sucesso", showlegend=False)
            health_fig.update_layout(title_text="")
            health_fig.update_yaxes(range=[0, 105], ticksuffix="%")
            st.plotly_chart(style_fig(health_fig, 300), width="stretch")

        obs = observations_frame()
        if not obs.empty and "listing_active" in obs.columns:
            obs = obs[obs["listing_active"] == True].copy()  # noqa: E712

        with right:
            section_header("Extração", "Métodos utilizados", "Distribuição dos métodos nas observações persistidas.")
            if not obs.empty and "extraction_method" in obs.columns:
                method_counts = (
                    obs["extraction_method"]
                    .fillna("Não identificado")
                    .replace({"": "Não identificado", "json-ld": "JSON-LD", "text-heuristic": "Heurística HTML", "meta": "Meta tags"})
                    .value_counts()
                    .reset_index()
                )
                method_counts.columns = ["Método", "Observações"]
                donut = px.pie(
                    method_counts,
                    names="Método",
                    values="Observações",
                    hole=.68,
                    color_discrete_sequence=["#2563EB", "#0F766E", "#F59E0B", "#94A3B8"],
                )
                donut.update_traces(textposition="outside", textinfo="percent+label")
                donut.update_layout(showlegend=False, title_text="")
                st.plotly_chart(style_fig(donut, 300), width="stretch")
            else:
                st.html('<div class="ci-empty">Ainda não há dados de método de extração.</div>')

        st.write("")
        section_header(
            "Cobertura",
            "Fontes monitoradas",
            "Cobertura de coleta, disponibilidade e presença como menor preço. Esses indicadores ajudam a separar sinal de mercado de problema operacional do collector.",
        )
        if sources.empty:
            st.html('<div class="ci-empty">Ainda não há resumo das fontes.</div>')
        else:
            source_view = sources.copy()
            source_view["Cobertura"] = source_view["collection_coverage_pct"].map(lambda x: f"{x:.1f}%")
            source_view["Disponibilidade"] = source_view["availability_rate"].map(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
            source_view["Gap médio p/ menor"] = source_view["avg_gap_to_lowest_pct"].map(lambda x: f"{x:.1f}%" if pd.notna(x) else "—")
            source_view = source_view.rename(
                columns={
                    "competitor": "Fonte",
                    "configured_offers": "URLs",
                    "successful_offers": "Sucessos",
                    "price_leader_wins": "Menor preço em",
                }
            )
            st.dataframe(
                source_view[["Fonte", "URLs", "Sucessos", "Cobertura", "Disponibilidade", "Menor preço em", "Gap médio p/ menor"]],
                width="stretch",
                hide_index=True,
            )

        st.write("")
        maturity_text = (
            f"<div class='ci-callout'><strong>Maturidade do histórico:</strong> "
            f"{maturity['with_history']} de {maturity['configured_listings']} ofertas ativas já possuem pelo menos duas observações válidas "
            f"({maturity['history_coverage_pct']:.1f}%). Comparação atual e tendência são tratados separadamente para evitar conclusões que o histórico ainda não sustenta.</div>"
        )
        st.html(maturity_text)

    obs = observations_frame()
    if not obs.empty and "listing_active" in obs.columns:
        obs = obs[obs["listing_active"] == True].copy()  # noqa: E712
    if not obs.empty:
        st.write("")
        section_header(
            "Rastreabilidade",
            "Últimas observações",
            "Amostra dos registros persistidos com status, método e eventual motivo de falha.",
        )

        cols = [
            "collected_at",
            "canonical_name",
            "competitor",
            "price",
            "available",
            "source",
            "extraction_method",
            "success",
            "error",
        ]
        obs_display = obs.sort_values("collected_at", ascending=False)[cols].head(50).copy()
        obs_display["price"] = obs_display["price"].map(brl)
        obs_display["available"] = obs_display["available"].map(lambda x: "Sim" if x is True else ("Não" if x is False else "Não identificado"))
        obs_display["success"] = obs_display["success"].map(lambda x: "OK" if bool(x) else "Falha")
        obs_display["source"] = obs_display["source"].replace({"http": "HTTP", "playwright": "Navegador", "error": "Falha"})
        obs_display["extraction_method"] = obs_display["extraction_method"].fillna("Não identificado").replace({"json-ld": "JSON-LD", "text-heuristic": "Heurística HTML", "meta": "Meta tags"})
        obs_display["error"] = obs_display["error"].fillna("—").map(lambda x: (str(x)[:117] + "...") if len(str(x)) > 120 else str(x))
        obs_display.columns = [
            "Coletado em",
            "Produto",
            "Fonte",
            "Preço",
            "Disponível",
            "Origem",
            "Método",
            "Status",
            "Erro",
        ]
        st.dataframe(obs_display, width="stretch", hide_index=True)

        if "success" in obs.columns:
            success_mask = success_bool_mask(obs["success"])
            failures = obs.loc[~success_mask].copy()
        else:
            failures = pd.DataFrame()
        if not failures.empty:
            st.write("")
            section_header(
                "Diagnóstico",
                "Falhas recentes",
                "Erros persistidos para apoiar manutenção dos collectors.",
            )
            failure_cols = ["collected_at", "canonical_name", "competitor", "http_status", "error"]
            existing = [c for c in failure_cols if c in failures.columns]
            failure_display = failures.sort_values("collected_at", ascending=False)[existing].head(20).copy()
            failure_display = failure_display.rename(
                columns={
                    "collected_at": "Coletado em",
                    "canonical_name": "Produto",
                    "competitor": "Fonte",
                    "http_status": "HTTP",
                    "error": "Erro",
                }
            )
            st.dataframe(failure_display, width="stretch", hide_index=True)

    st.write("")
    section_header(
        "Reporting",
        "Relatório executivo",
        "Brief periódico gerado a partir dos indicadores calculados pelo sistema.",
    )

    brief = build_weekly_brief()
    col_a, col_b = st.columns([1, 3])
    with col_a:
        st.download_button(
            "Baixar relatório (.md)",
            data=brief,
            file_name="competitive_intelligence_brief.md",
            mime="text/markdown",
            width="stretch",
        )
    with col_b:
        st.html(
            '<div class="ci-method-note">O relatório usa números calculados deterministicamente. A camada de IA pode ser adicionada à narrativa sem alterar os indicadores-base.</div>'
        )

    with st.expander("Pré-visualizar relatório"):
        st.markdown(brief)


# =============================================================================
# METHOD & ENGINEERING DECISIONS
# =============================================================================
with method_tab:
    st.write("")
    section_header(
        "Raciocínio de engenharia",
        "Por que o sistema foi construído desta forma?",
        "Esta seção documenta decisões que tornam o projeto auditável e defensável: a tecnologia aparece como resposta ao problema, não como objetivo em si.",
    )

    st.html(
        '''
<div class="ci-question-box">
  <div class="ci-question-label">Problema original</div>
  <div class="ci-question-text">Monitorar preços e disponibilidade manualmente exige abrir várias lojas, registrar mudanças e reconstruir a análise a cada ciclo.</div>
  <div class="ci-question-note">A solução automatiza a coleta e organiza o histórico, mas mantém a decisão comercial com uma pessoa. O sistema aponta onde investigar; não altera preços sozinho.</div>
</div>
'''
    )

    a, b, c = st.columns(3, gap="medium")
    with a:
        st.html('''<div class="ci-tech-decision"><span class="ci-tech-tag">COLETA</span><h4>HTTP antes de navegador</h4><p>Requests é mais leve, previsível e barato. Playwright entra somente quando a página exige renderização ou a extração HTTP não é suficiente. Retry/backoff trata falhas transitórias antes do fallback.</p></div>''')
    with b:
        st.html('''<div class="ci-tech-decision"><span class="ci-tech-tag">DADOS</span><h4>Produto canônico antes de comparar</h4><p>O mesmo SKU pode ter títulos diferentes em cada loja. O catálogo usa MPN/SKU para ligar listings a um produto canônico e evitar comparar variantes diferentes.</p></div>''')
    with c:
        st.html('''<div class="ci-tech-decision"><span class="ci-tech-tag">MARKETPLACE</span><h4>Fonte e seller são separados</h4><p>Uma oferta publicada em marketplace pode ser vendida por uma loja já monitorada diretamente. Canal e seller são persistidos separadamente para reduzir dupla contagem conceitual.</p></div>''')

    st.write("")
    d, e, f = st.columns(3, gap="medium")
    with d:
        st.html('''<div class="ci-tech-decision"><span class="ci-tech-tag">ANALYTICS</span><h4>Indicadores determinísticos</h4><p>Menor preço, mediana, dispersão, disponibilidade e variação são calculados em SQL/Pandas. O LLM não recebe liberdade para inventar números nem substituir regras objetivas.</p></div>''')
    with e:
        st.html('''<div class="ci-tech-decision"><span class="ci-tech-tag">IA + MCP</span><h4>Agente sobre uma base funcional</h4><p>O produto funciona sem IA. MCP expõe ferramentas analíticas ao agente; o modelo escolhe consultas e sintetiza evidências. Isso desacopla interpretação da camada de dados.</p></div>''')
    with f:
        st.html('''<div class="ci-tech-decision"><span class="ci-tech-tag">HISTÓRICO</span><h4>Sem backfill fictício</h4><p>O histórico começa na primeira coleta real. Enquanto uma oferta não possui duas observações válidas, o sistema trata o dado como fotografia atual e não como tendência.</p></div>''')

    st.write("")
    section_header(
        "Desafios reais",
        "O que precisou ser corrigido durante o desenvolvimento",
        "Os problemas encontrados fazem parte da demonstração de engenharia: coletar dados públicos continuamente exige lidar com políticas, HTML variável e semântica comercial.",
    )

    st.markdown(
        '''
- **`robots.txt`** — a primeira implementação confundia falha ao obter a política com `Disallow` explícito. A checagem foi redesenhada para separar indisponibilidade do arquivo de bloqueio real.
- **Páginas dinâmicas** — algumas fontes não entregam conteúdo suficiente por HTTP; Playwright foi mantido como fallback, não como padrão.
- **Preço publicado x oferta comparável** — valores de parcelas, placeholders e ofertas indisponíveis não podem contaminar o snapshot competitivo.
- **Marketplace x concorrente** — o mesmo seller pode aparecer em canais diferentes; por isso `source` e `seller` são entidades semânticas distintas.
- **Fotografia x tendência** — uma coleta permite comparação transversal; mudança de preço exige observação repetida da mesma URL.
        '''
    )

    st.write("")
    section_header(
        "Arquitetura",
        "Da página pública à decisão",
        "Cada camada tem responsabilidade própria para que coleta, analytics e IA possam evoluir separadamente.",
    )
    st.code(
        '''Catálogo de SKUs
      ↓
robots.txt / policy
      ↓
HTTP + retry/backoff
      ↓ (fallback)
Playwright
      ↓
Extração + normalização
      ↓
PostgreSQL + histórico
      ↓
Analytics determinístico
      ↓
Dashboard / relatório
      ↓
MCP tools
      ↓
AI Market Analyst''',
        language="text",
    )

    st.html('<div class="ci-method-note">Critério de projeto: uma tecnologia só permanece se resolver uma responsabilidade concreta. Remover o LLM não interrompe a coleta, o histórico, os cálculos nem o dashboard.</div>')


# =============================================================================
# FOOTER
# =============================================================================
st.write("")
st.caption(
    "Competitive Intelligence · Real market observations · Historical analytics · MCP tools · AI-assisted interpretation"
)
