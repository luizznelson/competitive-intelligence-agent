from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import text

from .db import engine, init_db


def _read_sql(query: str, params: dict | None = None) -> pd.DataFrame:
    init_db()
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn, params=params or {})


def observations_frame() -> pd.DataFrame:
    return _read_sql(
        """
        SELECT
            o.id AS observation_id,
            o.collected_at,
            o.price,
            o.currency,
            o.available,
            o.seller,
            o.title AS observed_title,
            o.source,
            o.extraction_method,
            o.http_status,
            o.success,
            o.error,
            l.id AS listing_id,
            l.url,
            l.active AS listing_active,
            p.canonical_id,
            p.canonical_name,
            p.brand,
            p.model,
            p.mpn,
            p.category,
            c.slug AS competitor_slug,
            c.name AS competitor
        FROM price_observations o
        JOIN listings l ON l.id = o.listing_id
        JOIN products p ON p.id = l.product_id
        JOIN competitors c ON c.id = l.competitor_id
        ORDER BY o.collected_at ASC, o.id ASC
        """
    )


def catalog_overview() -> dict:
    """Return configured catalog counts, independently of whether a collection has run."""
    frame = _read_sql(
        """
        SELECT
            COUNT(DISTINCT CASE WHEN l.active THEN p.id END) AS products,
            COUNT(DISTINCT CASE WHEN l.active THEN c.id END) AS competitors,
            COUNT(CASE WHEN l.active THEN 1 END) AS active_listings
        FROM listings l
        JOIN products p ON p.id = l.product_id
        JOIN competitors c ON c.id = l.competitor_id
        """
    )
    if frame.empty:
        return {"products": 0, "competitors": 0, "active_listings": 0}
    row = frame.iloc[0]
    return {
        "products": int(row["products"] or 0),
        "competitors": int(row["competitors"] or 0),
        "active_listings": int(row["active_listings"] or 0),
    }


def monitored_products() -> pd.DataFrame:
    """Products with at least one active configured listing, regardless of collection state."""
    return _read_sql(
        """
        SELECT
            p.canonical_id,
            p.canonical_name,
            p.brand,
            p.model,
            p.mpn,
            p.category,
            COUNT(l.id) AS active_listings
        FROM products p
        JOIN listings l ON l.product_id = p.id AND l.active = TRUE
        GROUP BY p.id, p.canonical_id, p.canonical_name, p.brand, p.model, p.mpn, p.category
        ORDER BY p.canonical_name
        """
    )


def product_listing_status(canonical_id: str) -> pd.DataFrame:
    """Latest state of every active listing for a product, including never-collected and failed listings."""
    return _read_sql(
        """
        SELECT
            p.canonical_id,
            p.canonical_name,
            l.id AS listing_id,
            l.url,
            c.slug AS competitor_slug,
            c.name AS competitor,
            o.id AS observation_id,
            o.collected_at,
            o.price,
            o.currency,
            o.available,
            o.seller,
            o.source,
            o.extraction_method,
            o.http_status,
            o.success,
            o.error
        FROM listings l
        JOIN products p ON p.id = l.product_id
        JOIN competitors c ON c.id = l.competitor_id
        LEFT JOIN price_observations o ON o.id = (
            SELECT po.id
            FROM price_observations po
            WHERE po.listing_id = l.id
            ORDER BY po.collected_at DESC, po.id DESC
            LIMIT 1
        )
        WHERE l.active = TRUE
          AND p.canonical_id = :canonical_id
        ORDER BY c.name
        """,
        {"canonical_id": canonical_id},
    )


def latest_observations(active_only: bool = True) -> pd.DataFrame:
    df = observations_frame()
    if df.empty:
        return df
    if active_only and "listing_active" in df.columns:
        df = df[df["listing_active"] == True].copy()  # noqa: E712
    if df.empty:
        return df
    df["collected_at"] = pd.to_datetime(df["collected_at"])
    return (
        df.sort_values(["listing_id", "collected_at", "observation_id"])
        .groupby("listing_id", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )


def previous_and_latest() -> pd.DataFrame:
    df = observations_frame()
    if df.empty:
        return pd.DataFrame()
    if "listing_active" in df.columns:
        df = df[df["listing_active"] == True].copy()  # noqa: E712
    df = df[df["success"] == True].copy()  # noqa: E712
    df = df[df["price"].notna()].copy()
    if df.empty:
        return pd.DataFrame()
    df["collected_at"] = pd.to_datetime(df["collected_at"])
    df = df.sort_values(["listing_id", "collected_at", "observation_id"])
    df["previous_price"] = df.groupby("listing_id")["price"].shift(1)
    latest = df.groupby("listing_id", as_index=False).tail(1).copy()
    latest["change_abs"] = latest["price"] - latest["previous_price"]
    latest["change_pct"] = np.where(
        latest["previous_price"].notna() & (latest["previous_price"] != 0),
        (latest["change_abs"] / latest["previous_price"]) * 100,
        np.nan,
    )
    return latest.reset_index(drop=True)


def _market_eligible(latest: pd.DataFrame) -> pd.DataFrame:
    """Offers eligible for current price comparison: success + price + not explicitly unavailable."""
    if latest.empty:
        return latest
    eligible = latest[(latest["success"] == True) & latest["price"].notna()].copy()  # noqa: E712
    if "available" in eligible.columns:
        eligible = eligible[eligible["available"] != False].copy()  # noqa: E712
    return eligible


def market_snapshot() -> pd.DataFrame:
    latest = _market_eligible(latest_observations())
    if latest.empty:
        return pd.DataFrame()

    rows: list[dict] = []
    for (canonical_id, canonical_name), group in latest.groupby(["canonical_id", "canonical_name"]):
        prices = group["price"].astype(float)
        median = float(prices.median())
        min_idx = group["price"].astype(float).idxmin()
        max_idx = group["price"].astype(float).idxmax()
        min_row = group.loc[min_idx]
        max_row = group.loc[max_idx]
        min_price = float(min_row["price"])
        max_price = float(max_row["price"])
        spread_pct = ((max_price - min_price) / min_price * 100) if min_price and len(group) >= 2 else np.nan
        rows.append(
            {
                "canonical_id": canonical_id,
                "product": canonical_name,
                "competitors_with_price": int(len(group)),
                "min_price": min_price,
                "min_competitor": min_row["competitor"],
                "median_price": median,
                "max_price": max_price,
                "max_competitor": max_row["competitor"],
                "spread_pct": spread_pct,
                "available_count": int((group["available"] == True).sum()) if "available" in group else 0,  # noqa: E712
            }
        )
    return pd.DataFrame(rows).sort_values("spread_pct", ascending=False, na_position="last").reset_index(drop=True)


def price_history(canonical_id: str | None = None, days: int = 30) -> pd.DataFrame:
    df = observations_frame()
    if df.empty:
        return df
    if "listing_active" in df.columns:
        df = df[df["listing_active"] == True].copy()  # noqa: E712
    df = df[(df["success"] == True) & df["price"].notna()].copy()  # noqa: E712
    df["collected_at"] = pd.to_datetime(df["collected_at"])
    cutoff = pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=days)
    df = df[df["collected_at"] >= cutoff]
    if canonical_id:
        df = df[df["canonical_id"] == canonical_id]
    return df.sort_values("collected_at")


def recent_changes(threshold_pct: float = 3.0) -> pd.DataFrame:
    df = previous_and_latest()
    if df.empty:
        return df
    df = df[df["change_pct"].notna()].copy()
    df = df[df["change_pct"].abs() >= threshold_pct]
    return df.sort_values("change_pct", key=lambda s: s.abs(), ascending=False).reset_index(drop=True)


def collection_health(limit: int = 20) -> pd.DataFrame:
    return _read_sql(
        """
        SELECT id, started_at, finished_at, total_listings, successful, failed
        FROM collection_runs
        ORDER BY started_at DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )


def history_maturity() -> dict:
    """Measure how much of the active catalog can already support change analysis."""
    catalog = catalog_overview()
    frame = _read_sql(
        """
        SELECT
            l.id AS listing_id,
            COUNT(o.id) AS valid_observations
        FROM listings l
        LEFT JOIN price_observations o
          ON o.listing_id = l.id
         AND o.success = true
         AND o.price IS NOT NULL
        WHERE l.active = true
        GROUP BY l.id
        """
    )
    if frame.empty:
        return {
            "configured_listings": catalog["active_listings"],
            "with_observation": 0,
            "with_history": 0,
            "history_coverage_pct": 0.0,
        }
    with_observation = int((frame["valid_observations"] >= 1).sum())
    with_history = int((frame["valid_observations"] >= 2).sum())
    total = int(catalog["active_listings"])
    return {
        "configured_listings": total,
        "with_observation": with_observation,
        "with_history": with_history,
        "history_coverage_pct": float(with_history / total * 100) if total else 0.0,
    }


def source_summary() -> pd.DataFrame:
    """Summarize coverage, availability and price leadership by monitored source."""
    configured = _read_sql(
        """
        SELECT c.name AS competitor, COUNT(l.id) AS configured_offers
        FROM listings l
        JOIN competitors c ON c.id = l.competitor_id
        WHERE l.active = true
        GROUP BY c.name
        ORDER BY c.name
        """
    )
    if configured.empty:
        return configured

    latest = latest_observations()
    rows = configured.copy()

    if latest.empty:
        rows["observed_offers"] = 0
        rows["successful_offers"] = 0
        rows["valid_price_offers"] = 0
        rows["available_offers"] = 0
        rows["availability_rate"] = np.nan
        rows["collection_coverage_pct"] = 0.0
        rows["price_leader_wins"] = 0
        rows["avg_gap_to_lowest_pct"] = np.nan
        return rows

    latest_counts = (
        latest.groupby("competitor", as_index=False)
        .agg(
            observed_offers=("listing_id", "count"),
            successful_offers=("success", lambda s: int((s == True).sum())),  # noqa: E712
            valid_price_offers=("price", lambda s: int(s.notna().sum())),
        )
    )
    rows = rows.merge(latest_counts, on="competitor", how="left")

    known = latest[(latest["success"] == True) & latest["available"].notna()].copy()  # noqa: E712
    if known.empty:
        avail = pd.DataFrame(columns=["competitor", "known_availability", "available_offers", "availability_rate"])
    else:
        avail = (
            known.groupby("competitor", as_index=False)
            .agg(
                known_availability=("listing_id", "count"),
                available_offers=("available", lambda s: int(s.astype(bool).sum())),
            )
        )
        avail["availability_rate"] = avail["available_offers"] / avail["known_availability"] * 100
    rows = rows.merge(avail, on="competitor", how="left")

    snapshot = market_snapshot()
    comparable = snapshot[snapshot["spread_pct"].notna() & (snapshot["competitors_with_price"] >= 2)].copy() if not snapshot.empty else pd.DataFrame()
    if comparable.empty:
        wins = pd.DataFrame(columns=["competitor", "price_leader_wins"])
    else:
        wins = comparable["min_competitor"].value_counts().rename_axis("competitor").reset_index(name="price_leader_wins")
    rows = rows.merge(wins, on="competitor", how="left")

    eligible = _market_eligible(latest)
    if eligible.empty:
        avg_gap = pd.DataFrame(columns=["competitor", "avg_gap_to_lowest_pct"])
    else:
        eligible = eligible.copy()
        eligible["product_min"] = eligible.groupby("canonical_id")["price"].transform("min")
        eligible["gap_to_lowest_pct"] = np.where(
            eligible["product_min"] > 0,
            (eligible["price"] - eligible["product_min"]) / eligible["product_min"] * 100,
            np.nan,
        )
        avg_gap = (
            eligible.groupby("competitor", as_index=False)["gap_to_lowest_pct"]
            .mean()
            .rename(columns={"gap_to_lowest_pct": "avg_gap_to_lowest_pct"})
        )
    rows = rows.merge(avg_gap, on="competitor", how="left")

    for col in ["observed_offers", "successful_offers", "valid_price_offers", "available_offers", "price_leader_wins"]:
        rows[col] = rows[col].fillna(0).astype(int)
    rows["collection_coverage_pct"] = np.where(
        rows["configured_offers"] > 0,
        rows["successful_offers"] / rows["configured_offers"] * 100,
        np.nan,
    )
    return rows.sort_values(["price_leader_wins", "collection_coverage_pct"], ascending=[False, False]).reset_index(drop=True)


def overview_metrics() -> dict:
    catalog = catalog_overview()
    latest = latest_observations()
    snapshot = market_snapshot()
    changes = recent_changes(3.0)
    health = collection_health(1)
    eligible = _market_eligible(latest)
    maturity = history_maturity()

    return {
        "products": int(catalog["products"]),
        "competitors": int(catalog["competitors"]),
        "active_listings": int(len(eligible)) if not eligible.empty else 0,
        "configured_listings": int(catalog["active_listings"]),
        "observed_listings": int(len(latest)) if not latest.empty else 0,
        "relevant_changes": int(len(changes)) if not changes.empty else 0,
        "average_market_spread_pct": float(snapshot["spread_pct"].mean()) if not snapshot.empty else np.nan,
        "last_collection_success_rate": (
            float(health.iloc[0]["successful"] / health.iloc[0]["total_listings"] * 100)
            if not health.empty and health.iloc[0]["total_listings"]
            else np.nan
        ),
        "history_coverage_pct": maturity["history_coverage_pct"],
        "listings_with_history": maturity["with_history"],
    }


def product_comparison(canonical_id: str) -> pd.DataFrame:
    latest = _market_eligible(latest_observations())
    if latest.empty:
        return latest
    df = latest[latest["canonical_id"] == canonical_id].copy()
    if df.empty:
        return df
    median = float(df["price"].median())
    df["price_index_vs_median"] = np.where(median, df["price"] / median * 100, np.nan)
    df["gap_vs_median_pct"] = np.where(median, (df["price"] - median) / median * 100, np.nan)
    return df.sort_values("price").reset_index(drop=True)
