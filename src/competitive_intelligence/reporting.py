from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from .analytics import (
    collection_health,
    history_maturity,
    market_snapshot,
    overview_metrics,
    recent_changes,
    source_summary,
)
from .config import ROOT


def brl(value) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def build_weekly_brief(threshold_pct: float = 3.0) -> str:
    """Build a deterministic executive brief from persisted observations."""
    metrics = overview_metrics()
    snapshot = market_snapshot()
    changes = recent_changes(threshold_pct)
    health = collection_health(1)
    sources = source_summary()
    maturity = history_maturity()

    comparable = (
        snapshot[snapshot["spread_pct"].notna() & (snapshot["competitors_with_price"] >= 2)].copy()
        if not snapshot.empty
        else pd.DataFrame()
    )

    lines = [
        "# Competitive Intelligence Brief",
        "",
        f"**Gerado em:** {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        "",
        "## Pergunta de negócio",
        "",
        "> Quais produtos e fontes apresentam sinais competitivos que justificam investigação ou ação comercial?",
        "",
        "## Resposta executiva",
        "",
        f"- Catálogo: **{metrics['products']} produtos**, **{metrics['competitors']} fontes** e **{metrics['configured_listings']} URLs ativas**.",
        f"- Ofertas válidas para comparação de preço agora: **{metrics['active_listings']}**.",
    ]

    success_rate = metrics.get("last_collection_success_rate")
    if success_rate == success_rate:
        lines.append(f"- Saúde da última coleta: **{success_rate:.1f}%** de sucesso.")

    if comparable.empty:
        lines.append("- Ainda não há SKUs com duas ou mais ofertas válidas suficientes para medir dispersão competitiva.")
    else:
        top = comparable.sort_values("spread_pct", ascending=False).iloc[0]
        lines.append(
            f"- Maior divergência atual: **{top['product']}**, com spread de **{top['spread_pct']:.1f}%** "
            f"entre {top['min_competitor']} ({brl(top['min_price'])}) e {top['max_competitor']} ({brl(top['max_price'])})."
        )

        leader_counts = comparable["min_competitor"].dropna().value_counts()
        if not leader_counts.empty:
            leader = str(leader_counts.index[0])
            wins = int(leader_counts.iloc[0])
            lines.append(
                f"- Fonte com maior presença como menor preço: **{leader}**, liderando **{wins} de {len(comparable)}** SKUs comparáveis."
            )

    if not sources.empty and sources["availability_rate"].notna().any():
        low_avail = sources.dropna(subset=["availability_rate"]).sort_values("availability_rate").iloc[0]
        lines.append(
            f"- Maior atenção em disponibilidade: **{low_avail['competitor']}**, com **{low_avail['availability_rate']:.1f}%** "
            "das ofertas com status conhecido disponíveis."
        )

    lines += [
        "",
        "## Prioridades por preço",
        "",
    ]
    if comparable.empty:
        lines.append("Ainda não há produtos comparáveis suficientes.")
    else:
        for _, row in comparable.sort_values("spread_pct", ascending=False).head(10).iterrows():
            lines.append(
                f"- **{row['product']}** — spread **{row['spread_pct']:.1f}%**; "
                f"menor {brl(row['min_price'])} em {row['min_competitor']}; "
                f"mediana {brl(row['median_price'])}; maior {brl(row['max_price'])} em {row['max_competitor']}."
            )

    lines += ["", "## Leitura por fonte", ""]
    if sources.empty:
        lines.append("Sem dados de fonte suficientes.")
    else:
        for _, row in sources.iterrows():
            availability = (
                f"{row['availability_rate']:.1f}% disponível"
                if pd.notna(row["availability_rate"])
                else "disponibilidade não determinada"
            )
            avg_gap = (
                f"gap médio de {row['avg_gap_to_lowest_pct']:.1f}% para o menor preço do SKU"
                if pd.notna(row["avg_gap_to_lowest_pct"])
                else "gap médio ainda não calculável"
            )
            lines.append(
                f"- **{row['competitor']}** — {int(row['price_leader_wins'])} liderança(s) de menor preço; "
                f"{availability}; cobertura de coleta {row['collection_coverage_pct']:.1f}%; {avg_gap}."
            )

    lines += ["", "## Movimentações relevantes", ""]
    if changes.empty:
        lines.append(
            f"Nenhuma variação absoluta >= {threshold_pct:.1f}% foi identificada entre as duas últimas observações válidas da mesma oferta."
        )
    else:
        for _, row in changes.head(15).iterrows():
            direction = "queda" if row["change_pct"] < 0 else "alta"
            lines.append(
                f"- **{row['canonical_name']} — {row['competitor']}**: {direction} de "
                f"**{abs(row['change_pct']):.1f}%**, de {brl(row['previous_price'])} para {brl(row['price'])}."
            )

    lines += [
        "",
        "## Maturidade do histórico",
        "",
        f"- Listings com pelo menos uma observação válida: **{maturity['with_observation']} de {maturity['configured_listings']}**.",
        f"- Listings com duas ou mais observações válidas: **{maturity['with_history']} de {maturity['configured_listings']}**.",
        f"- Cobertura para análise de movimento: **{maturity['history_coverage_pct']:.1f}%**.",
        "",
        "A fotografia atual permite comparar preços e disponibilidade. Conclusões de tendência exigem histórico repetido da mesma oferta.",
        "",
        "## Observação metodológica",
        "",
        "Os indicadores de preço, disponibilidade, dispersão e variação são calculados deterministicamente a partir das observações persistidas. "
        "A camada de IA, quando habilitada, seleciona ferramentas MCP e interpreta esses resultados, mas não substitui os cálculos do pipeline.",
    ]

    if not health.empty:
        row = health.iloc[0]
        lines += [
            "",
            "## Rastreabilidade da última execução",
            "",
            f"- Ofertas previstas: **{int(row['total_listings'])}**",
            f"- Sucessos: **{int(row['successful'])}**",
            f"- Falhas: **{int(row['failed'])}**",
        ]

    return "\n".join(lines)


def save_weekly_brief(path: str | Path | None = None) -> Path:
    target = Path(path) if path else ROOT / "reports" / "competitive_intelligence_brief.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_weekly_brief(), encoding="utf-8")
    return target
