from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CollectedProduct:
    title: str | None
    price: float | None
    currency: str = "BRL"
    available: bool | None = None
    seller: str | None = None
    source: str = "http"
    extraction_method: str | None = None
    http_status: int | None = None


class CollectionError(RuntimeError):
    pass
