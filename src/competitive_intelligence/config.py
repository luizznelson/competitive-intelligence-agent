from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

try:
    # On Streamlit Cloud, values set under Settings -> Secrets live in
    # st.secrets. Streamlit normally mirrors top-level secrets into
    # os.environ automatically, but that mirroring only happens on a full
    # process start - an incremental "hot" app update can leave a process
    # running without it. Mirroring here too, with setdefault so an
    # explicitly-set env var always wins, makes secrets take effect without
    # depending on that timing. Wrapped in try/except because st.secrets
    # raises when no secrets file exists (plain CLI/local runs) and because
    # config.py must stay importable without a Streamlit runtime.
    import streamlit as st

    for _key, _value in st.secrets.items():
        os.environ.setdefault(_key, str(_value))
except Exception:
    pass

_explicit_database_url = os.getenv("DATABASE_URL")
DEMO_DATABASE_PATH = ROOT / "data" / "demo" / "competitive_intelligence_demo.db"
RUNTIME_DATABASE_PATH = ROOT / "data" / "competitive_intelligence.db"

# Local/Docker execution normally provides DATABASE_URL explicitly.
# A public Streamlit deployment can run without secrets: when the committed
# demo snapshot exists, the app automatically opens it in read-only/demo mode.
if _explicit_database_url:
    DATABASE_URL = _explicit_database_url
    DEMO_MODE = False
elif DEMO_DATABASE_PATH.exists():
    DATABASE_URL = f"sqlite:///{DEMO_DATABASE_PATH}"
    DEMO_MODE = True
else:
    DATABASE_URL = f"sqlite:///{RUNTIME_DATABASE_PATH}"
    DEMO_MODE = False
COLLECTION_TIMEOUT_SECONDS = int(os.getenv("COLLECTION_TIMEOUT_SECONDS", "25"))
COLLECTION_DELAY_SECONDS = float(os.getenv("COLLECTION_DELAY_SECONDS", "2"))
USE_PLAYWRIGHT_FALLBACK = os.getenv("USE_PLAYWRIGHT_FALLBACK", "true").lower() in {"1", "true", "yes"}
ROBOTS_POLICY = os.getenv("ROBOTS_POLICY", "warn").lower()  # strict | warn | off
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (compatible; CompetitiveIntelligenceAgent/1.0; portfolio research)",
)
PRODUCTS_CONFIG = Path(os.getenv("PRODUCTS_CONFIG", ROOT / "config" / "products.yml"))
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

# Public AI analyst safeguards
AI_MAX_QUESTION_CHARS = max(100, int(os.getenv("AI_MAX_QUESTION_CHARS", "500")))
AI_MAX_COMPLETION_TOKENS = max(128, min(2048, int(os.getenv("AI_MAX_COMPLETION_TOKENS", "700"))))
AI_MAX_STEPS = max(1, min(4, int(os.getenv("AI_MAX_STEPS", "3"))))
AI_MAX_TOOL_CALLS = max(1, min(8, int(os.getenv("AI_MAX_TOOL_CALLS", "5"))))
AI_MAX_TOOL_RESULT_CHARS = max(2000, min(30000, int(os.getenv("AI_MAX_TOOL_RESULT_CHARS", "10000"))))
AI_CACHE_TTL_SECONDS = max(60, int(os.getenv("AI_CACHE_TTL_SECONDS", "3600")))
AI_MIN_REQUEST_INTERVAL_SECONDS = max(0.0, float(os.getenv("AI_MIN_REQUEST_INTERVAL_SECONDS", "8")))
AI_MAX_SESSION_MESSAGES = max(2, min(20, int(os.getenv("AI_MAX_SESSION_MESSAGES", "12"))))
AI_GROQ_TIMEOUT_SECONDS = max(5.0, float(os.getenv("AI_GROQ_TIMEOUT_SECONDS", "25")))

# Resilience / retry policy
# MAX_ATTEMPTS includes the first attempt. Example: 3 = 1 initial request + up to 2 retries.
HTTP_MAX_ATTEMPTS = max(1, int(os.getenv("HTTP_MAX_ATTEMPTS", "3")))
PLAYWRIGHT_MAX_ATTEMPTS = max(1, int(os.getenv("PLAYWRIGHT_MAX_ATTEMPTS", "2")))
RETRY_BACKOFF_BASE_SECONDS = max(0.0, float(os.getenv("RETRY_BACKOFF_BASE_SECONDS", "1.5")))
RETRY_BACKOFF_MAX_SECONDS = max(0.0, float(os.getenv("RETRY_BACKOFF_MAX_SECONDS", "12")))
RETRY_JITTER_SECONDS = max(0.0, float(os.getenv("RETRY_JITTER_SECONDS", "0.5")))

# Catalog discovery / scale-up
DISCOVERY_TARGET_PRODUCTS = max(1, int(os.getenv("DISCOVERY_TARGET_PRODUCTS", "100")))
DISCOVERY_MIN_SOURCES = max(1, int(os.getenv("DISCOVERY_MIN_SOURCES", "2")))
DISCOVERY_MAX_CANDIDATES = max(DISCOVERY_TARGET_PRODUCTS, int(os.getenv("DISCOVERY_MAX_CANDIDATES", "650")))
DISCOVERY_DELAY_SECONDS = max(0.0, float(os.getenv("DISCOVERY_DELAY_SECONDS", "1.0")))

DISCOVERY_CACHE_TTL_HOURS = max(1.0, float(os.getenv("DISCOVERY_CACHE_TTL_HOURS", "24")))
DISCOVERY_SITEMAP_MAX_FILES = max(1, int(os.getenv("DISCOVERY_SITEMAP_MAX_FILES", "120")))
DISCOVERY_SITEMAP_MAX_URLS = max(1000, int(os.getenv("DISCOVERY_SITEMAP_MAX_URLS", "80000")))
