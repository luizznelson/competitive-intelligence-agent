from __future__ import annotations

import json

from mcp.server import MCPServer

from .analytics import (
    collection_health,
    history_maturity,
    market_snapshot,
    price_history,
    product_comparison,
    recent_changes,
    source_summary,
)
from .db import init_db, seed_catalog

mcp = MCPServer("competitive-intelligence")


def _records(df, limit: int = 50) -> list[dict]:
    if df.empty:
        return []
    frame = df.head(limit).copy()
    for col in frame.columns:
        if "date" in col.lower() or "time" in col.lower() or col == "collected_at":
            try:
                frame[col] = frame[col].astype(str)
            except Exception:
                pass
    return json.loads(frame.to_json(orient="records", date_format="iso"))


@mcp.tool()
def compare_market() -> list[dict]:
    """Compare latest valid prices across monitored competitors for all products."""
    init_db()
    seed_catalog()
    return _records(market_snapshot())


@mcp.tool()
def compare_product(canonical_id: str) -> list[dict]:
    """Compare latest valid prices for one canonical product across competitors.

    Args:
        canonical_id: Product id from the monitored catalog.
    """
    return _records(product_comparison(canonical_id))


@mcp.tool()
def get_price_history(canonical_id: str, days: int = 30) -> list[dict]:
    """Get persisted real price observations for a product.

    Args:
        canonical_id: Canonical product id.
        days: History window in days.
    """
    return _records(price_history(canonical_id, days), limit=300)


@mcp.tool()
def get_recent_changes(threshold_pct: float = 3.0) -> list[dict]:
    """Get latest price movements above an absolute percentage threshold.

    Args:
        threshold_pct: Minimum absolute percentage change to return.
    """
    return _records(recent_changes(threshold_pct))


@mcp.tool()
def get_source_summary() -> list[dict]:
    """Summarize each source by collection coverage, availability, price leadership and gap to the lowest offer."""
    return _records(source_summary())


@mcp.tool()
def get_history_maturity() -> dict:
    """Return how much of the active catalog has enough repeated observations to support movement analysis."""
    return history_maturity()


@mcp.tool()
def get_collection_health(limit: int = 10) -> list[dict]:
    """Get collection-run health metrics, including successes and failures."""
    return _records(collection_health(limit))


if __name__ == "__main__":
    mcp.run(transport="stdio")
