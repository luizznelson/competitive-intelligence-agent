from __future__ import annotations

import logging
import os
import time

from src.competitive_intelligence.service import collect_all

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
LOGGER = logging.getLogger("scheduler")

hours = float(os.getenv("COLLECTION_INTERVAL_HOURS", "12"))
interval = max(hours * 3600, 3600)  # never more frequent than hourly by default

while True:
    try:
        result = collect_all()
        LOGGER.info("Collection finished: %s", result)
    except Exception:
        LOGGER.exception("Collection run failed")
    LOGGER.info("Sleeping %.1f hours", interval / 3600)
    time.sleep(interval)
