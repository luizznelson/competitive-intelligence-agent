from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from .collectors import GenericProductCollector
from .db import init_db, seed_catalog, session_scope
from .models import CollectionRun, Listing, PriceObservation

LOGGER = logging.getLogger(__name__)


def collect_all() -> dict:
    init_db()
    seed_catalog()
    collector = GenericProductCollector()

    with session_scope() as session:
        listings = list(
            session.scalars(
                select(Listing)
                .options(joinedload(Listing.product), joinedload(Listing.competitor))
                .where(Listing.active.is_(True))
                .order_by(Listing.id)
            ).unique()
        )
        run = CollectionRun(started_at=datetime.utcnow(), total_listings=len(listings))
        session.add(run)
        session.flush()
        run_id = run.id

    successful = 0
    failed = 0
    rows: list[dict] = []

    for listing in listings:
        try:
            item = collector.collect(listing.url)
            success = item.price is not None
            error = None if success else "Coleta concluída sem preço."
            successful += int(success)
            failed += int(not success)
        except Exception as exc:
            LOGGER.exception("Falha ao coletar %s", listing.url)
            item = None
            success = False
            error = str(exc)
            failed += 1

        with session_scope() as session:
            observation = PriceObservation(
                listing_id=listing.id,
                run_id=run_id,
                collected_at=datetime.utcnow(),
                price=item.price if item else None,
                currency=item.currency if item else "BRL",
                available=item.available if item else None,
                seller=(item.seller or listing.competitor.name) if item else None,
                title=item.title if item else None,
                source=item.source if item else "error",
                extraction_method=item.extraction_method if item else None,
                http_status=item.http_status if item else None,
                success=success,
                error=error,
            )
            session.add(observation)

        rows.append(
            {
                "product": listing.product.canonical_name,
                "competitor": listing.competitor.name,
                "price": item.price if item else None,
                "available": item.available if item else None,
                "source": item.source if item else "error",
                "success": success,
                "error": error,
            }
        )

    with session_scope() as session:
        run = session.get(CollectionRun, run_id)
        run.finished_at = datetime.utcnow()
        run.successful = successful
        run.failed = failed

    return {
        "run_id": run_id,
        "total": len(listings),
        "successful": successful,
        "failed": failed,
        "observations": rows,
    }
