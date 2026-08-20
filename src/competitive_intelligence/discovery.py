from __future__ import annotations

import gzip
import json
import logging
import random
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote, quote_plus, urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup

from .collectors import GenericProductCollector
from .collectors.base import CollectionError
from .config import (
    COLLECTION_TIMEOUT_SECONDS,
    DISCOVERY_CACHE_TTL_HOURS,
    DISCOVERY_DELAY_SECONDS,
    DISCOVERY_MAX_CANDIDATES,
    DISCOVERY_MIN_SOURCES,
    DISCOVERY_SITEMAP_MAX_FILES,
    DISCOVERY_SITEMAP_MAX_URLS,
    DISCOVERY_TARGET_PRODUCTS,
    PRODUCTS_CONFIG,
    ROOT,
    USER_AGENT,
    USE_PLAYWRIGHT_FALLBACK,
)

LOGGER = logging.getLogger(__name__)

SOURCE_ORIGINS = {
    "kabum": "https://www.kabum.com.br",
    "pichau": "https://www.pichau.com.br",
    "terabyte": "https://www.terabyteshop.com.br",
}

# Fallbacks mirror the Sitemap directives currently published by each store's robots.txt.
# robots.txt is still fetched dynamically first so the project adapts if a store changes them.
DEFAULT_SITEMAPS = {
    "kabum": ["https://www.kabum.com.br/sitemap.xml"],
    "pichau": ["https://www.pichau.com.br/media/sitemap.xml"],
    "terabyte": [
        "https://www.terabyteshop.com.br/sitemap.xml",
        "https://www.terabyteshop.com.br/sitemap-manus.xml",
    ],
}

# Search pages are only a fallback. Primary discovery is sitemap-to-sitemap matching.
SEARCH_TEMPLATES = {
    "kabum": "https://www.kabum.com.br/busca/{path_query}",
    "pichau": "https://www.pichau.com.br/search?q={query}",
}

# Public, query-free catalog areas used only when a sitemap is temporarily unavailable.
# The crawler still asks the project's robots policy before every page fetch.
PUBLIC_CATALOG_SEEDS = {
    "kabum": [
        "https://www.kabum.com.br/hardware",
        "https://www.kabum.com.br/perifericos",
        "https://www.kabum.com.br/monitores",
    ],
    "pichau": [
        "https://www.pichau.com.br/hardware",
        "https://www.pichau.com.br/perifericos",
        "https://www.pichau.com.br/computadores",
        "https://www.pichau.com.br/monitores",
    ],
    "terabyte": [
        "https://www.terabyteshop.com.br/hardware",
        "https://www.terabyteshop.com.br/perifericos",
        "https://www.terabyteshop.com.br/monitores",
    ],
}

STOPWORDS = {
    "de", "da", "do", "das", "dos", "e", "com", "para", "por", "sem", "gamer",
    "preto", "branco", "azul", "rgb", "usb", "wireless", "fio", "the", "and",
    "produto", "oferta", "hardware", "perifericos", "periféricos",
}

CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("SSD", ("ssd", "nvme", "solid state")),
    ("Mouse", ("mouse",)),
    ("Teclado", ("teclado", "keyboard")),
    ("Headset", ("headset", "fone gamer", "headphone")),
    ("Memória RAM", ("memoria ddr", "memória ddr", "memory ddr", "ram ")),
    ("Monitor", ("monitor",)),
    ("Processador", ("processador", "ryzen", "core i3", "core i5", "core i7", "core i9")),
    ("Placa de vídeo", ("placa de video", "placa de vídeo", "geforce", "radeon", "rtx ", "rx ")),
    ("Placa-mãe", ("placa mae", "placa-mãe", "motherboard")),
    ("Fonte", ("fonte ", "power supply", " psu")),
    ("Cooler", ("cooler", "water cooler", "air cooler")),
]

KNOWN_BRANDS = [
    "Logitech", "Kingston", "Western Digital", "WD", "Crucial", "Samsung", "Corsair",
    "Adata", "ADATA", "SanDisk", "Seagate", "AMD", "Intel", "Asus", "ASUS", "MSI",
    "Gigabyte", "ASRock", "DeepCool", "Thermaltake", "Cooler Master", "HyperX", "Redragon",
    "Razer", "AOC", "LG", "Dell", "Acer", "BenQ", "ViewSonic", "XPG", "Patriot",
]

PICHAU_RESERVED_ROOTS = {
    "api", "account", "checkout", "checkout-app", "manager", "customer", "success",
    "loginascustomer", "preview", "search", "hardware", "perifericos", "computadores",
    "monitores", "marcas", "marca", "departamentos", "atendimento", "quem-somos",
    "carrinho", "blog", "institucional", "contato", "login", "cadastro",
}


@dataclass(slots=True)
class ProductIdentity:
    title: str
    brand: str | None
    model: str | None
    mpn: str | None
    category: str


@dataclass(slots=True)
class SearchMatch:
    competitor: str
    url: str
    score: float
    title: str | None


@dataclass(slots=True)
class SourceCatalog:
    source: str
    urls: list[str]
    strategy: str
    sitemap_urls: list[str]
    errors: list[str]


@dataclass(slots=True)
class IndexedUrl:
    url: str
    normalized: str
    compact: str
    tokens: frozenset[str]


def _ascii(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    text = _ascii(text).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [tok for tok in text.split() if tok not in STOPWORDS and len(tok) > 1]
    return " ".join(tokens)


def compact_text(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", _ascii(text or "").lower())


def slugify(text: str) -> str:
    value = normalize_text(text).replace(" ", "-")
    return re.sub(r"-+", "-", value).strip("-")[:110]


def token_similarity(left: str, right: str) -> float:
    a = normalize_text(left)
    b = normalize_text(right)
    if not a or not b:
        return 0.0
    at = set(a.split())
    bt = set(b.split())
    jaccard = len(at & bt) / max(len(at | bt), 1)
    sequence = SequenceMatcher(None, a, b).ratio()
    return 0.65 * jaccard + 0.35 * sequence


def infer_category(title: str) -> str:
    normalized = _ascii(title).lower()
    for category, needles in CATEGORY_RULES:
        if any(needle in normalized for needle in needles):
            return category
    return "Hardware"


def infer_brand(title: str, raw_brand: str | None = None) -> str | None:
    if raw_brand:
        return str(raw_brand).strip()
    normalized = _ascii(title).lower()
    for brand in KNOWN_BRANDS:
        if _ascii(brand).lower() in normalized:
            return brand
    first = title.split()[0].strip(" ,-|/") if title.split() else None
    return first if first and len(first) > 1 else None


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _candidate_code_from_title(title: str) -> str | None:
    candidates = re.findall(r"\b[A-Z0-9][A-Z0-9._/-]{4,}\b", title.upper())
    ranked = []
    for token in candidates:
        has_alpha = bool(re.search(r"[A-Z]", token))
        has_digit = bool(re.search(r"\d", token))
        separator = bool(re.search(r"[-_/]", token))
        if has_alpha and has_digit:
            ranked.append((int(separator), len(token), token))
    if not ranked:
        return None
    ranked.sort(reverse=True)
    return ranked[0][2]


def extract_identity(html: str, url: str) -> ProductIdentity | None:
    soup = BeautifulSoup(html, "html.parser")
    title: str | None = None
    brand: str | None = None
    model: str | None = None
    mpn: str | None = None

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        for node in _walk(data):
            node_type = node.get("@type") if isinstance(node, dict) else None
            types = node_type if isinstance(node_type, list) else [node_type]
            if "Product" not in types:
                continue
            title = title or node.get("name")
            mpn = mpn or node.get("mpn")
            model = model or node.get("model")
            sku = node.get("sku")
            if not mpn and sku and not str(sku).isdigit():
                mpn = str(sku)
            raw_brand = node.get("brand")
            if isinstance(raw_brand, dict):
                brand = brand or raw_brand.get("name")
            elif raw_brand:
                brand = brand or str(raw_brand)

    h1 = soup.find("h1")
    if not title and h1:
        title = h1.get_text(" ", strip=True)
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)
    if not title:
        return None

    title = re.sub(r"\s+", " ", title).strip()
    mpn = str(mpn).strip() if mpn else _candidate_code_from_title(title)
    brand = infer_brand(title, brand)
    model = str(model).strip() if model else (mpn or title[:120])
    return ProductIdentity(
        title=title,
        brand=brand,
        model=model,
        mpn=mpn,
        category=infer_category(title),
    )


def build_search_url(competitor: str, query: str) -> str:
    if competitor == "kabum":
        path_query = slugify(query)
        return SEARCH_TEMPLATES[competitor].format(path_query=quote(path_query, safe="-"))
    if competitor == "pichau":
        return SEARCH_TEMPLATES[competitor].format(query=quote_plus(query))
    raise ValueError(f"Fonte de busca não suportada: {competitor}")


def _normalized_host(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


def _same_origin(url: str, base: str) -> bool:
    return _normalized_host(url) == _normalized_host(base)


def _canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(query="", fragment="").geturl().rstrip("/")


def _source_from_url(url: str) -> str | None:
    host = urlparse(url).netloc.lower()
    if "kabum.com.br" in host:
        return "kabum"
    if "pichau.com.br" in host:
        return "pichau"
    if "terabyteshop.com.br" in host:
        return "terabyte"
    return None


def _is_probable_product_url(source: str, url: str) -> bool:
    parsed = urlparse(url)
    if _normalized_host(url) != _normalized_host(SOURCE_ORIGINS[source]):
        return False
    if parsed.query:
        return False
    path = parsed.path.rstrip("/")
    lower = path.lower()
    if source in {"kabum", "terabyte"}:
        return "/produto/" in lower
    if source == "pichau":
        segments = [segment for segment in path.split("/") if segment]
        if len(segments) != 1:
            return False
        root = segments[0].lower()
        return root not in PICHAU_RESERVED_ROOTS and "-" in root and len(root) > 12
    return False


def _is_probable_catalog_url(source: str, url: str) -> bool:
    parsed = urlparse(url)
    if _normalized_host(url) != _normalized_host(SOURCE_ORIGINS[source]):
        return False
    if parsed.query:
        return False
    path = parsed.path.lower().rstrip("/")
    if not path:
        return False
    if source == "pichau":
        return path.startswith(("/hardware", "/perifericos", "/computadores", "/monitores", "/marca/"))
    if source == "terabyte":
        return path.startswith(("/hardware", "/perifericos", "/monitores", "/notebooks", "/refrigeracao"))
    if source == "kabum":
        return path.startswith(("/hardware", "/perifericos", "/monitores", "/marcas/"))
    return False


def extract_search_links(html: str, competitor: str, search_url: str, identity: ProductIdentity) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    scored: list[tuple[float, str]] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = _canonicalize_url(urljoin(search_url, anchor.get("href")))
        if href in seen or not _same_origin(href, search_url):
            continue
        path = urlparse(href).path.lower()
        if competitor == "kabum" and "/produto/" not in path:
            continue
        if competitor == "pichau" and not _is_probable_product_url("pichau", href):
            continue

        text = anchor.get_text(" ", strip=True) or anchor.get("title") or href
        score = token_similarity(identity.title, text)
        if identity.mpn and compact_text(identity.mpn) in compact_text(text + " " + href):
            score = max(score, 0.98)
        if score < 0.18:
            continue
        seen.add(href)
        scored.append((score, href))

    scored.sort(reverse=True)
    return [url for _, url in scored[:8]]


def _variant_tokens(text: str) -> set[str]:
    normalized = _ascii(text).lower().replace(",", ".")
    patterns = [
        r"\b\d+(?:\.\d+)?\s?(?:tb|gb|mb)\b",
        r"\b(?:ddr[345]|pcie\s?[345](?:\.0)?|nvme|sata\s?(?:ii|iii|3))\b",
        r"\b\d{3,4}\s?mhz\b",
    ]
    values: set[str] = set()
    for pattern in patterns:
        for match in re.findall(pattern, normalized, flags=re.IGNORECASE):
            values.add(compact_text(match))
    return values


def identity_match_score(reference: ProductIdentity, candidate: ProductIdentity) -> float:
    ref_mpn = compact_text(reference.mpn)
    cand_mpn = compact_text(candidate.mpn)
    if ref_mpn and cand_mpn:
        if ref_mpn == cand_mpn:
            return 1.0
        # Different explicit manufacturer codes are a hard rejection.
        return 0.0

    ref_brand = normalize_text(reference.brand)
    cand_brand = normalize_text(candidate.brand)
    if ref_brand and cand_brand and ref_brand != cand_brand:
        return 0.0

    ref_variants = _variant_tokens(reference.title)
    cand_variants = _variant_tokens(candidate.title)
    if ref_variants and cand_variants and ref_variants.isdisjoint(cand_variants):
        return 0.0

    score = token_similarity(reference.title, candidate.title)
    ref_model = compact_text(reference.model)
    cand_model = compact_text(candidate.model)
    if ref_model and cand_model and len(ref_model) >= 5 and ref_model == cand_model:
        score = max(score, 0.93)
    if ref_mpn and ref_mpn in compact_text(candidate.title):
        score = max(score, 0.98)
    if cand_mpn and cand_mpn in compact_text(reference.title):
        score = max(score, 0.98)
    return score


class SitemapUrlIndex:
    def __init__(self, source: str, urls: list[str]):
        self.source = source
        self.entries: list[IndexedUrl] = []
        self.token_map: dict[str, set[int]] = defaultdict(set)
        for url in urls:
            normalized = normalize_text(urlparse(url).path)
            compact = compact_text(urlparse(url).path)
            tokens = frozenset(token for token in normalized.split() if len(token) >= 3)
            idx = len(self.entries)
            self.entries.append(IndexedUrl(url=url, normalized=normalized, compact=compact, tokens=tokens))
            for token in tokens:
                self.token_map[token].add(idx)

    def find(self, identity: ProductIdentity, limit: int = 8) -> list[str]:
        if not self.entries:
            return []

        exact_code = compact_text(identity.mpn)
        if exact_code and len(exact_code) >= 5:
            exact = [entry.url for entry in self.entries if exact_code in entry.compact]
            if exact:
                return exact[:limit]

        query = normalize_text(" ".join(filter(None, [identity.brand, identity.model, identity.title])))
        tokens = [token for token in query.split() if len(token) >= 3]
        candidate_ids: set[int] = set()
        # Alphanumeric model-like tokens are usually more discriminative than generic words.
        ranked_tokens = sorted(
            tokens,
            key=lambda token: (bool(re.search(r"[a-z]", token) and re.search(r"\d", token)), len(token)),
            reverse=True,
        )[:8]
        for token in ranked_tokens:
            candidate_ids.update(self.token_map.get(token, set()))

        if not candidate_ids:
            return []

        scored: list[tuple[float, str]] = []
        for idx in candidate_ids:
            entry = self.entries[idx]
            overlap = len(set(tokens) & set(entry.tokens)) / max(len(set(tokens)), 1)
            sequence = SequenceMatcher(None, normalize_text(identity.title), entry.normalized).ratio()
            score = 0.75 * overlap + 0.25 * sequence
            scored.append((score, entry.url))
        scored.sort(reverse=True)
        return [url for score, url in scored[:limit] if score >= 0.20]


class CatalogDiscovery:
    def __init__(self):
        self.collector = GenericProductCollector()
        self.session = self.collector.session
        self.cache_dir = ROOT / "data" / "discovery_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._catalogs: dict[str, SourceCatalog] = {}
        self._indexes: dict[str, SitemapUrlIndex] = {}

    def _fetch_html(self, url: str, *, respect_robots: bool = True) -> str:
        if respect_robots:
            self.collector._robots_allowed(url)
        time.sleep(max(DISCOVERY_DELAY_SECONDS, 0))
        response = self.session.get(url, timeout=COLLECTION_TIMEOUT_SECONDS, allow_redirects=True)
        response.raise_for_status()
        html = response.text
        if len(html) > 5000:
            return html
        if not USE_PLAYWRIGHT_FALLBACK:
            return html

        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return html
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=USER_AGENT, locale="pt-BR")
                page.goto(url, wait_until="domcontentloaded", timeout=COLLECTION_TIMEOUT_SECONDS * 1000)
                page.wait_for_timeout(1200)
                return page.content()
            finally:
                browser.close()

    def _robots_sitemaps(self, source: str) -> list[str]:
        origin = SOURCE_ORIGINS[source]
        robots_url = f"{origin}/robots.txt"
        try:
            response = self.session.get(robots_url, timeout=COLLECTION_TIMEOUT_SECONDS, allow_redirects=True)
            if response.status_code == 200:
                values = []
                for line in response.text.splitlines():
                    match = re.match(r"^\s*Sitemap\s*:\s*(\S+)\s*$", line, flags=re.IGNORECASE)
                    if match:
                        values.append(match.group(1).strip())
                if values:
                    return list(dict.fromkeys(values))
        except requests.RequestException as exc:
            LOGGER.warning("Não foi possível ler Sitemap directives de %s: %s", source, exc)
        return DEFAULT_SITEMAPS[source]

    @staticmethod
    def _decode_xml(content: bytes) -> bytes:
        if content[:2] == b"\x1f\x8b":
            return gzip.decompress(content)
        return content

    def _fetch_sitemap_document(self, url: str) -> tuple[list[str], list[str]]:
        """Return (child_sitemaps, page_urls) from one XML sitemap document.

        A 403 is not bypassed. The caller can try another sitemap explicitly published by the site
        or fall back to a previously cached URL index/public catalog crawl.
        """
        self.collector._robots_allowed(url)
        response = self.session.get(
            url,
            timeout=COLLECTION_TIMEOUT_SECONDS,
            allow_redirects=True,
            headers={"Accept": "application/xml,text/xml;q=0.9,*/*;q=0.5"},
        )
        response.raise_for_status()
        root = ET.fromstring(self._decode_xml(response.content))
        root_name = root.tag.rsplit("}", 1)[-1].lower()
        locs = [
            (node.text or "").strip()
            for node in root.iter()
            if node.tag.rsplit("}", 1)[-1].lower() == "loc" and (node.text or "").strip()
        ]
        if root_name == "sitemapindex":
            return locs, []
        return [], locs

    def _crawl_sitemaps(self, source: str, roots: list[str]) -> tuple[list[str], list[str]]:
        queue: deque[str] = deque(dict.fromkeys(roots))
        seen_sitemaps: set[str] = set()
        pages: list[str] = []
        errors: list[str] = []

        while queue and len(seen_sitemaps) < DISCOVERY_SITEMAP_MAX_FILES and len(pages) < DISCOVERY_SITEMAP_MAX_URLS:
            sitemap_url = queue.popleft()
            if sitemap_url in seen_sitemaps:
                continue
            seen_sitemaps.add(sitemap_url)
            try:
                children, urls = self._fetch_sitemap_document(sitemap_url)
            except Exception as exc:
                message = f"{sitemap_url}: {exc}"
                errors.append(message)
                LOGGER.warning("Sitemap %s indisponível para %s: %s", sitemap_url, source, exc)
                continue
            for child in children:
                if child not in seen_sitemaps:
                    queue.append(child)
            for url in urls:
                canonical = _canonicalize_url(url)
                if _is_probable_product_url(source, canonical):
                    pages.append(canonical)
                    if len(pages) >= DISCOVERY_SITEMAP_MAX_URLS:
                        break

        return list(dict.fromkeys(pages)), errors

    def _cache_path(self, source: str) -> Path:
        return self.cache_dir / f"{source}_catalog_urls.json"

    def _read_cache(self, source: str, *, allow_stale: bool = False) -> list[str]:
        path = self._cache_path(source)
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = float(payload.get("fetched_at", 0))
            age_hours = max(0.0, (time.time() - fetched_at) / 3600.0)
            if not allow_stale and age_hours > DISCOVERY_CACHE_TTL_HOURS:
                return []
            urls = [str(url) for url in payload.get("urls", []) if _is_probable_product_url(source, str(url))]
            return list(dict.fromkeys(urls))
        except Exception as exc:
            LOGGER.warning("Cache de discovery inválido para %s: %s", source, exc)
            return []

    def _write_cache(self, source: str, urls: list[str]) -> None:
        path = self._cache_path(source)
        payload = {"source": source, "fetched_at": time.time(), "urls": urls}
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp.replace(path)

    def _crawl_public_catalog(self, source: str, max_pages: int = 24, max_products: int = 1800) -> tuple[list[str], list[str]]:
        """Respectful degraded-mode crawl of query-free public catalog pages.

        This does not attempt to defeat HTTP blocks and never visits a URL that the project's
        robots policy rejects. It exists only as a temporary fallback when XML sitemaps cannot
        be obtained from the current network path.
        """
        queue: deque[str] = deque(PUBLIC_CATALOG_SEEDS[source])
        seen_pages: set[str] = set()
        products: list[str] = []
        errors: list[str] = []

        while queue and len(seen_pages) < max_pages and len(products) < max_products:
            page_url = queue.popleft()
            if page_url in seen_pages:
                continue
            seen_pages.add(page_url)
            try:
                html = self._fetch_html(page_url, respect_robots=True)
            except Exception as exc:
                errors.append(f"{page_url}: {exc}")
                continue
            soup = BeautifulSoup(html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                absolute = _canonicalize_url(urljoin(page_url, anchor.get("href")))
                if not _same_origin(absolute, SOURCE_ORIGINS[source]):
                    continue
                if _is_probable_product_url(source, absolute):
                    products.append(absolute)
                    if len(products) >= max_products:
                        break
                elif _is_probable_catalog_url(source, absolute) and absolute not in seen_pages:
                    queue.append(absolute)

        return list(dict.fromkeys(products)), errors

    def load_source_catalog(self, source: str, *, force_refresh: bool = False) -> SourceCatalog:
        if source in self._catalogs and not force_refresh:
            return self._catalogs[source]

        if not force_refresh:
            cached = self._read_cache(source)
            if cached:
                catalog = SourceCatalog(source, cached, "fresh-cache", self._robots_sitemaps(source), [])
                self._catalogs[source] = catalog
                LOGGER.info("Catálogo %s carregado do cache: %s URLs", source, len(cached))
                return catalog

        sitemap_roots = self._robots_sitemaps(source)
        urls, errors = self._crawl_sitemaps(source, sitemap_roots)
        if urls:
            self._write_cache(source, urls)
            catalog = SourceCatalog(source, urls, "sitemap", sitemap_roots, errors)
            self._catalogs[source] = catalog
            LOGGER.info("Catálogo %s via sitemap: %s URLs de produto", source, len(urls))
            return catalog

        stale = self._read_cache(source, allow_stale=True)
        if stale:
            catalog = SourceCatalog(source, stale, "stale-cache", sitemap_roots, errors)
            self._catalogs[source] = catalog
            LOGGER.warning("Sitemaps de %s indisponíveis; usando cache anterior com %s URLs", source, len(stale))
            return catalog

        crawl_urls, crawl_errors = self._crawl_public_catalog(source)
        errors.extend(crawl_errors)
        if crawl_urls:
            self._write_cache(source, crawl_urls)
            catalog = SourceCatalog(source, crawl_urls, "public-catalog-fallback", sitemap_roots, errors)
            self._catalogs[source] = catalog
            LOGGER.warning("%s sem sitemap acessível; fallback público encontrou %s URLs", source, len(crawl_urls))
            return catalog

        catalog = SourceCatalog(source, [], "unavailable", sitemap_roots, errors)
        self._catalogs[source] = catalog
        LOGGER.warning("Fonte %s sem catálogo disponível nesta execução", source)
        return catalog

    def load_all_catalogs(self, *, force_refresh: bool = False) -> dict[str, SourceCatalog]:
        catalogs = {source: self.load_source_catalog(source, force_refresh=force_refresh) for source in SOURCE_ORIGINS}
        for source, catalog in catalogs.items():
            self._indexes[source] = SitemapUrlIndex(source, catalog.urls)
        LOGGER.info(
            "Fontes de discovery: %s",
            " | ".join(f"{name}={len(cat.urls)} ({cat.strategy})" for name, cat in catalogs.items()),
        )
        return catalogs

    def candidate_urls(self, max_candidates: int) -> list[str]:
        catalogs = self.load_all_catalogs()
        buckets: list[list[str]] = []
        for offset, source in enumerate(("terabyte", "kabum", "pichau")):
            urls = list(catalogs[source].urls)
            if not urls:
                continue
            rnd = random.Random(4200 + offset)
            rnd.shuffle(urls)
            buckets.append(urls)

        merged: list[str] = []
        idx = 0
        while len(merged) < max_candidates and buckets:
            progressed = False
            for bucket in buckets:
                if idx < len(bucket):
                    merged.append(bucket[idx])
                    progressed = True
                    if len(merged) >= max_candidates:
                        break
            if not progressed:
                break
            idx += 1
        return list(dict.fromkeys(merged))[:max_candidates]

    def _validate_match(self, source: str, url: str, identity: ProductIdentity) -> SearchMatch | None:
        try:
            html = self._fetch_html(url, respect_robots=True)
            candidate_identity = extract_identity(html, url)
        except Exception as exc:
            LOGGER.debug("Validação falhou para %s: %s", url, exc)
            return None
        if not candidate_identity:
            return None
        score = identity_match_score(identity, candidate_identity)
        if score < 0.60:
            return None
        return SearchMatch(competitor=source, url=url, score=score, title=candidate_identity.title)

    def match_from_catalog(self, source: str, identity: ProductIdentity) -> SearchMatch | None:
        index = self._indexes.get(source)
        if index is None:
            catalog = self.load_source_catalog(source)
            index = SitemapUrlIndex(source, catalog.urls)
            self._indexes[source] = index
        for url in index.find(identity, limit=8):
            match = self._validate_match(source, url, identity)
            if match:
                return match
        return None

    def search_source(self, competitor: str, identity: ProductIdentity) -> SearchMatch | None:
        """Legacy fallback for a robots-allowed search route.

        Pichau's current query-string search route is blocked by its published robots policy,
        so sitemap matching should normally handle that store instead.
        """
        query = identity.mpn or f"{identity.brand or ''} {identity.model or identity.title}".strip()
        search_url = build_search_url(competitor, query)
        try:
            html = self._fetch_html(search_url, respect_robots=True)
        except CollectionError as exc:
            LOGGER.debug("Busca %s não permitida: %s", competitor, exc)
            return None
        except Exception as exc:
            LOGGER.debug("Busca %s falhou para %s: %s", competitor, query, exc)
            return None

        links = extract_search_links(html, competitor, search_url, identity)
        for link in links[:5]:
            match = self._validate_match(competitor, link, identity)
            if match:
                return match
        return None

    def find_cross_store_matches(self, source: str, identity: ProductIdentity) -> list[SearchMatch]:
        matches: list[SearchMatch] = []
        for other in SOURCE_ORIGINS:
            if other == source:
                continue
            match = self.match_from_catalog(other, identity)
            if match:
                matches.append(match)
                continue
            # Only KaBuM currently has a useful query-free search route that can be tried
            # without conflicting with the published query-parameter restrictions.
            if other == "kabum":
                fallback = self.search_source("kabum", identity)
                if fallback:
                    matches.append(fallback)
        return matches

    def diagnose_sources(self, *, force_refresh: bool = False) -> dict:
        catalogs = self.load_all_catalogs(force_refresh=force_refresh)
        return {
            source: {
                "strategy": catalog.strategy,
                "product_urls": len(catalog.urls),
                "sitemaps": catalog.sitemap_urls,
                "errors": catalog.errors[:5],
            }
            for source, catalog in catalogs.items()
        }


def _load_catalog(path: Path) -> dict:
    if not path.exists():
        return {"products": []}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {"products": []}


def _catalog_keys(payload: dict) -> tuple[set[str], set[str]]:
    mpns: set[str] = set()
    names: set[str] = set()
    for product in payload.get("products", []):
        if product.get("mpn"):
            mpns.add(compact_text(str(product["mpn"])))
        names.add(normalize_text(str(product.get("canonical_name", ""))))
    return mpns, names


def _unique_canonical_id(identity: ProductIdentity, existing_ids: set[str]) -> str:
    base = slugify(f"{identity.brand or ''}-{identity.model or identity.mpn or identity.title}") or "product"
    candidate = base
    suffix = 2
    while candidate in existing_ids:
        candidate = f"{base[:100]}-{suffix}"
        suffix += 1
    return candidate


def expand_catalog(
    *,
    target: int = DISCOVERY_TARGET_PRODUCTS,
    min_sources: int = DISCOVERY_MIN_SOURCES,
    max_candidates: int = DISCOVERY_MAX_CANDIDATES,
    config_path: Path | str = PRODUCTS_CONFIG,
) -> dict:
    """Expand the monitored catalog using cross-store sitemap matching.

    Primary strategy:
      1. Read the Sitemap directives published in each store's robots.txt.
      2. Build local URL indexes for KaBuM!, Pichau and TerabyteShop.
      3. Round-robin candidate products from available indexes.
      4. Extract product identity from JSON-LD/H1.
      5. Match the same MPN/model against the other stores' sitemap indexes.
      6. Validate the actual matched page before persisting it.

    A product is added only when at least `min_sources` independent stores validate.
    Existing products/history are preserved and YAML progress is written atomically.
    """
    path = Path(config_path)
    payload = _load_catalog(path)
    products = payload.setdefault("products", [])
    existing_ids = {str(p.get("canonical_id")) for p in products}
    existing_mpns, existing_names = _catalog_keys(payload)
    start_count = len(products)
    if start_count >= target:
        return {
            "target": target,
            "initial_products": start_count,
            "products_added": 0,
            "final_products": start_count,
            "candidates_checked": 0,
            "message": "Catálogo já atingiu o alvo.",
        }

    discovery = CatalogDiscovery()
    candidates = discovery.candidate_urls(max_candidates)
    catalogs = discovery._catalogs
    added = 0
    checked = 0
    rejected_single_source = 0
    rejected_duplicate = 0
    rejected_identity = 0
    source_hits = {source: 0 for source in SOURCE_ORIGINS}
    category_counts: dict[str, int] = defaultdict(int)

    for candidate_url in candidates:
        if len(products) >= target:
            break
        checked += 1
        source = _source_from_url(candidate_url)
        if source is None:
            continue
        try:
            html = discovery._fetch_html(candidate_url, respect_robots=True)
            identity = extract_identity(html, candidate_url)
        except Exception as exc:
            LOGGER.debug("Candidato inválido %s: %s", candidate_url, exc)
            rejected_identity += 1
            continue
        if not identity:
            rejected_identity += 1
            continue

        normalized_mpn = compact_text(identity.mpn) if identity.mpn else ""
        normalized_name = normalize_text(identity.title)
        if (normalized_mpn and normalized_mpn in existing_mpns) or normalized_name in existing_names:
            rejected_duplicate += 1
            continue

        if category_counts[identity.category] >= 24:
            continue

        listings = [{"competitor": source, "active": True, "url": candidate_url}]
        source_hits[source] += 1
        for match in discovery.find_cross_store_matches(source, identity):
            if match.competitor not in {row["competitor"] for row in listings}:
                listings.append({"competitor": match.competitor, "active": True, "url": match.url})
                source_hits[match.competitor] += 1

        if len(listings) < min_sources:
            rejected_single_source += 1
            if checked % 25 == 0:
                LOGGER.info(
                    "Progresso discovery: %s/%s candidatos | catálogo %s/%s | novos %s | matches insuficientes %s",
                    checked, len(candidates), len(products), target, added, rejected_single_source,
                )
            continue

        canonical_id = _unique_canonical_id(identity, existing_ids)
        product = {
            "canonical_id": canonical_id,
            "canonical_name": identity.title,
            "brand": identity.brand,
            "model": identity.model,
            "mpn": identity.mpn,
            "category": identity.category,
            "listings": listings,
        }
        products.append(product)
        existing_ids.add(canonical_id)
        existing_names.add(normalized_name)
        if normalized_mpn:
            existing_mpns.add(normalized_mpn)
        category_counts[identity.category] += 1
        added += 1
        LOGGER.info(
            "Produto descoberto %s/%s: %s | fontes=%s",
            len(products), target, identity.title, ",".join(row["competitor"] for row in listings),
        )

        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
        temp.replace(path)

    final_count = len(products)
    report = {
        "target": target,
        "initial_products": start_count,
        "products_added": added,
        "final_products": final_count,
        "candidates_checked": checked,
        "rejected_duplicates": rejected_duplicate,
        "rejected_identity": rejected_identity,
        "rejected_single_source": rejected_single_source,
        "validated_source_hits": source_hits,
        "source_catalogs": {
            source: {"urls": len(catalog.urls), "strategy": catalog.strategy}
            for source, catalog in catalogs.items()
        },
        "target_reached": final_count >= target,
    }
    report_path = ROOT / "data" / "discovery_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
