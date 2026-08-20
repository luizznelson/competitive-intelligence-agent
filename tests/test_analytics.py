from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.competitive_intelligence.analytics import success_bool_mask
from src.competitive_intelligence.models import Base, Competitor, Listing, PriceObservation, Product


def test_price_change_math():
    old = 200.0
    new = 180.0
    pct = (new - old) / old * 100
    assert pct == pytest.approx(-10.0)


def test_success_bool_mask_handles_native_booleans():
    success = pd.Series([True, False, None])
    mask = success_bool_mask(success)
    assert mask.tolist() == [True, False, False]
    failures = pd.DataFrame({"success": success}).loc[~mask]
    assert failures["success"].tolist() == [False, None]


def test_success_bool_mask_handles_sqlite_int64_encoding():
    # The SQLite demo snapshot surfaces boolean columns to pandas as int64 0/1,
    # not native bool. A bare `~series.fillna(False)` bitwise-inverts the ints
    # (0 -> -1, 1 -> -2) instead of negating them, which breaks `.loc[]`
    # indexing with a KeyError on labels like -1/-2 (see dashboard/app.py's
    # failures table). success_bool_mask must coerce to bool first.
    success = pd.Series([1, 0, 1], dtype="int64")
    mask = success_bool_mask(success)
    assert mask.dtype == bool
    assert mask.tolist() == [True, False, True]

    failures = pd.DataFrame({"id": [1, 2, 3], "success": success}).loc[~mask]
    assert failures["id"].tolist() == [2]


def test_relational_model_accepts_history():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        competitor = Competitor(slug="test", name="Test Store")
        product = Product(canonical_id="p1", canonical_name="Product 1")
        session.add_all([competitor, product])
        session.flush()
        listing = Listing(product_id=product.id, competitor_id=competitor.id, url="https://example.com/p1")
        session.add(listing)
        session.flush()
        session.add_all(
            [
                PriceObservation(listing_id=listing.id, price=100.0, collected_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)),
                PriceObservation(listing_id=listing.id, price=90.0, collected_at=datetime.now(timezone.utc).replace(tzinfo=None)),
            ]
        )
        session.commit()
        assert session.query(PriceObservation).count() == 2
