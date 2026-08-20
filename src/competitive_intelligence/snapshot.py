from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, func, insert, select

from .config import DEMO_DATABASE_PATH
from .db import engine as source_engine
from .models import Base, CollectionRun, Competitor, Listing, PriceObservation, Product


_TABLES = [
    Competitor.__table__,
    Product.__table__,
    Listing.__table__,
    CollectionRun.__table__,
    PriceObservation.__table__,
]


def export_demo_snapshot(target: Path | None = None, overwrite: bool = False) -> dict:
    """Export the current configured database to a portable SQLite snapshot.

    The snapshot contains only application data (catalog, listings, collection
    runs and observations). Credentials and environment variables are never
    copied.
    """
    target = Path(target or DEMO_DATABASE_PATH).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    source_url = str(source_engine.url)
    target_url = f"sqlite:///{target}"
    if source_url == target_url:
        raise RuntimeError("A origem já é o banco de demonstração; exporte a partir do banco local/PostgreSQL.")

    if target.exists():
        if not overwrite:
            raise FileExistsError(
                f"Snapshot já existe em {target}. Use --overwrite para substituí-lo."
            )
        target.unlink()

    target_engine = create_engine(target_url, future=True)
    Base.metadata.create_all(target_engine)

    counts: dict[str, int] = {}
    with source_engine.connect() as source_conn, target_engine.begin() as target_conn:
        for table in _TABLES:
            rows = [dict(row._mapping) for row in source_conn.execute(select(table))]
            if rows:
                target_conn.execute(insert(table), rows)
            counts[table.name] = len(rows)

        latest_observation = source_conn.scalar(select(func.max(PriceObservation.collected_at)))
        latest_run = source_conn.scalar(select(func.max(CollectionRun.finished_at)))

    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "last_observation_at": latest_observation.isoformat() if latest_observation else None,
        "last_collection_finished_at": latest_run.isoformat() if latest_run else None,
        "tables": counts,
        "snapshot_file": target.name,
        "note": "Snapshot real exportado do banco operacional para demonstração somente leitura.",
    }
    metadata_path = target.parent / "snapshot_metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "snapshot": str(target),
        "metadata": str(metadata_path),
        "tables": counts,
        "last_observation_at": metadata["last_observation_at"],
        "size_mb": round(target.stat().st_size / (1024 * 1024), 2),
    }
