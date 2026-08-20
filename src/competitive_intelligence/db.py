from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import yaml
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from .config import DATABASE_URL, PRODUCTS_CONFIG
from .models import Base, Competitor, Listing, Product


def _prepare_sqlite_path(database_url: str) -> None:
    if database_url.startswith("sqlite:///"):
        raw = database_url.replace("sqlite:///", "", 1)
        path = Path(raw)
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)


_prepare_sqlite_path(DATABASE_URL)

engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    Base.metadata.create_all(engine)


def seed_catalog(config_path: Path | str = PRODUCTS_CONFIG) -> dict[str, int]:
    """
    Upsert the YAML catalog and synchronize active flags.

    Existing historical listings are preserved, but any listing omitted from the
    current config is deactivated. This prevents stale sources (for example an old
    marketplace URL) from continuing to be collected after the catalog changes.
    """
    init_db()
    payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    products = payload.get("products", [])

    competitor_display = {
        "kabum": "KaBuM!",
        "pichau": "Pichau",
        "terabyte": "TerabyteShop",
        "magalu": "Magazine Luiza",
    }

    product_count = 0
    listing_count = 0
    active_count = 0

    with session_scope() as session:
        # Preserve history but disable anything no longer declared by the catalog.
        session.execute(update(Listing).values(active=False))

        for item in products:
            product = session.scalar(select(Product).where(Product.canonical_id == item["canonical_id"]))
            if product is None:
                product = Product(
                    canonical_id=item["canonical_id"],
                    canonical_name=item["canonical_name"],
                    brand=item.get("brand"),
                    model=item.get("model"),
                    mpn=item.get("mpn"),
                    category=item.get("category"),
                )
                session.add(product)
                session.flush()
                product_count += 1
            else:
                product.canonical_name = item["canonical_name"]
                product.brand = item.get("brand")
                product.model = item.get("model")
                product.mpn = item.get("mpn")
                product.category = item.get("category")

            for listing_cfg in item.get("listings", []):
                slug = listing_cfg["competitor"]
                is_active = bool(listing_cfg.get("active", True))
                competitor = session.scalar(select(Competitor).where(Competitor.slug == slug))
                if competitor is None:
                    competitor = Competitor(slug=slug, name=competitor_display.get(slug, slug.title()))
                    session.add(competitor)
                    session.flush()
                else:
                    competitor.name = competitor_display.get(slug, competitor.name)

                listing = session.scalar(
                    select(Listing).where(
                        Listing.product_id == product.id,
                        Listing.competitor_id == competitor.id,
                    )
                )
                if listing is None:
                    listing = Listing(
                        product_id=product.id,
                        competitor_id=competitor.id,
                        url=listing_cfg["url"],
                        active=is_active,
                    )
                    session.add(listing)
                    listing_count += 1
                else:
                    listing.url = listing_cfg["url"]
                    listing.active = is_active

                active_count += int(is_active)

    return {
        "products_created": product_count,
        "listings_created": listing_count,
        "active_listings": active_count,
    }
