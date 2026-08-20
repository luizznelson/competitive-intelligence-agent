from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from html import unescape
from urllib.parse import urlparse
from ..robots import RobotsParser

import requests
from bs4 import BeautifulSoup

from ..config import (
    COLLECTION_DELAY_SECONDS,
    COLLECTION_TIMEOUT_SECONDS,
    HTTP_MAX_ATTEMPTS,
    PLAYWRIGHT_MAX_ATTEMPTS,
    RETRY_BACKOFF_BASE_SECONDS,
    RETRY_BACKOFF_MAX_SECONDS,
    RETRY_JITTER_SECONDS,
    ROBOTS_POLICY,
    USER_AGENT,
    USE_PLAYWRIGHT_FALLBACK,
)
from .base import CollectedProduct, CollectionError

LOGGER = logging.getLogger(__name__)

PRICE_RE = re.compile(r"R\$\s*([0-9][0-9\.,]*[\.,][0-9]{2})")


def parse_brl(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (float, int)):
        return float(value)
    text = str(value).strip().replace("R$", "").replace(" ", "")
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(Decimal(text))
    except (InvalidOperation, ValueError):
        return None


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _product_from_jsonld(soup: BeautifulSoup) -> CollectedProduct | None:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        for node in _walk(data):
            node_type = node.get("@type")
            types = node_type if isinstance(node_type, list) else [node_type]
            if "Product" not in types:
                continue

            offers = node.get("offers")
            if isinstance(offers, list):
                # Prefer an offer that actually contains a price.
                priced = [offer for offer in offers if isinstance(offer, dict) and offer.get("price") is not None]
                offers = priced[0] if priced else (offers[0] if offers else None)

            price = None
            currency = "BRL"
            available = None
            seller = None

            if isinstance(offers, dict):
                price_spec = offers.get("priceSpecification")
                if not isinstance(price_spec, dict):
                    price_spec = {}
                price = parse_brl(
                    offers.get("price")
                    or offers.get("lowPrice")
                    or price_spec.get("price")
                )
                currency = offers.get("priceCurrency") or currency
                availability = str(offers.get("availability") or "").lower()
                if availability:
                    available = not any(
                        token in availability
                        for token in ["outofstock", "soldout", "discontinued", "preorder"]
                    )
                seller_data = offers.get("seller") or offers.get("offeredBy")
                if isinstance(seller_data, dict):
                    seller = seller_data.get("name")
                elif seller_data:
                    seller = str(seller_data)

            if price is not None or offers is not None:
                return CollectedProduct(
                    title=node.get("name"),
                    price=price,
                    currency=currency,
                    available=available,
                    seller=seller,
                    extraction_method="json-ld",
                )
    return None


def _from_meta(soup: BeautifulSoup) -> CollectedProduct | None:
    title = None
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title:
        title = og_title.get("content")
    if not title and soup.title:
        title = soup.title.get_text(strip=True)

    candidates = [
        soup.find("meta", attrs={"property": "product:price:amount"}),
        soup.find("meta", attrs={"property": "og:price:amount"}),
        soup.find(attrs={"itemprop": "price"}),
    ]
    price = None
    for el in candidates:
        if not el:
            continue
        price = parse_brl(el.get("content") or el.get("value") or el.get_text(" ", strip=True))
        if price is not None:
            break

    if price is None:
        return None

    return CollectedProduct(title=title, price=price, extraction_method="meta")


def _availability_from_text(text: str) -> bool | None:
    normalized = re.sub(r"\s+", " ", text.lower())

    negative_tokens = [
        "produto indisponível",
        "produto indisponivel",
        "esgotado",
        "fora de estoque",
        "todos vendidos",
        "avise quando o produto chegar",
    ]
    positive_tokens = [
        "produto disponível",
        "produto disponivel",
        "pronta entrega",
        "comprar agora",
        "adicionar ao carrinho",
        "em estoque",
        "restam ",
    ]

    if any(token in normalized for token in negative_tokens):
        return False
    if any(token in normalized for token in positive_tokens):
        return True
    return None


def _seller_from_text(text: str) -> str | None:
    patterns = [
        r"Vendido\s+e\s+entregue\s+por\s*:\s*([^\n|]{2,80})",
        r"Vendido\s+por\s*:\s*([^\n|]{2,80})",
        r"Vendido\s+por\s+([^\n|]{2,80})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            seller = re.sub(r"\s+", " ", match.group(1)).strip(" .:-")
            # Stop common UI fragments accidentally captured after the seller.
            seller = re.split(
                r"\b(?:e entregue por|avaliações|avaliações dos clientes|de r\$|por r\$|preço r\$)\b",
                seller,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip(" .:-")
            return seller or None
    return None


def _heuristic_from_text(soup: BeautifulSoup) -> CollectedProduct | None:
    text = unescape(soup.get_text("\n", strip=True))

    # Prefer cash/Pix contexts and explicitly avoid installment amounts.
    preferred_patterns = [
        re.compile(r"à\s+vista\s*R\$\s*([0-9][0-9\.,]*[\.,][0-9]{2})", re.IGNORECASE | re.DOTALL),
        re.compile(r"R\$\s*([0-9][0-9\.,]*[\.,][0-9]{2})\s*(?:no\s+PIX|à\s+vista)", re.IGNORECASE | re.DOTALL),
        re.compile(r"por\s*:\s*R\$\s*([0-9][0-9\.,]*[\.,][0-9]{2})", re.IGNORECASE | re.DOTALL),
    ]
    price = None
    for pattern in preferred_patterns:
        for match in pattern.finditer(text):
            candidate = parse_brl(match.group(1))
            # Ignore placeholder values such as R$ 000,00 present in some share widgets.
            if candidate is not None and candidate > 1:
                price = candidate
                break
        if price is not None:
            break

    if price is None:
        candidates = []
        for match in PRICE_RE.finditer(text):
            context_before = text[max(0, match.start() - 32):match.start()].lower()
            if re.search(r"\d{1,2}x\s+de\s*$", context_before):
                continue
            value = parse_brl(match.group(1))
            if value is not None and value > 1:
                candidates.append(value)
        if not candidates:
            return None
        price = min(candidates)

    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else None
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)

    return CollectedProduct(
        title=title,
        price=price,
        available=_availability_from_text(text),
        seller=_seller_from_text(text),
        extraction_method="text-heuristic",
    )


def extract_product(html: str) -> CollectedProduct:
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text("\n", strip=True)

    structured = _product_from_jsonld(soup)
    if structured and structured.price is not None:
        if structured.available is None:
            structured.available = _availability_from_text(page_text)
        if structured.seller is None:
            structured.seller = _seller_from_text(page_text)
        return structured

    meta = _from_meta(soup)
    if meta:
        meta.available = _availability_from_text(page_text)
        meta.seller = _seller_from_text(page_text)
        return meta

    heuristic = _heuristic_from_text(soup)
    if heuristic:
        return heuristic

    raise CollectionError("Nenhum preço confiável foi encontrado no HTML.")


class GenericProductCollector:
    """Structured-data-first collector with respectful robots handling and retry/backoff."""

    RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        # Cache parsed robots files for the lifetime of one collection run.
        self._robots_cache: dict[str, RobotsParser | None] = {}

    def _robots_allowed(self, url: str) -> bool:
        """
        Check robots.txt using the same HTTP session/user-agent as the collector.

        The public robots.txt is fetched with the same Requests session/user-agent
        as the collector and parsed with Protego. This avoids conflating a failure to
        retrieve robots.txt with an explicit Disallow rule, and supports modern
        wildcard/precedence conventions used by retail sites.

        Policy:
          - off: skip robots checks.
          - warn: explicit Disallow is respected; a transport/4xx fetch problem is
            logged and collection may continue. 5xx is treated conservatively.
          - strict: inability to obtain/evaluate robots.txt blocks collection.
        """
        if ROBOTS_POLICY == "off":
            return True

        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        robots_url = f"{origin}/robots.txt"

        if origin not in self._robots_cache:
            parser: RobotsParser | None = None
            try:
                response = self.session.get(
                    robots_url,
                    timeout=COLLECTION_TIMEOUT_SECONDS,
                    allow_redirects=True,
                )

                if response.status_code == 200:
                    parser = RobotsParser.parse(response.text)
                    self._robots_cache[origin] = parser
                elif response.status_code in {404, 410}:
                    # No robots file published at this origin.
                    LOGGER.info("robots.txt ausente em %s (HTTP %s).", origin, response.status_code)
                    self._robots_cache[origin] = None
                    return True
                elif 500 <= response.status_code < 600:
                    # Conservative behavior for server errors.
                    message = f"robots.txt temporariamente indisponível em {origin} (HTTP {response.status_code})"
                    raise CollectionError(f"ROBOTS_UNAVAILABLE: {message}")
                else:
                    message = (
                        f"não foi possível obter robots.txt de {origin} "
                        f"(HTTP {response.status_code})"
                    )
                    if ROBOTS_POLICY == "strict":
                        raise CollectionError(f"ROBOTS_UNAVAILABLE_STRICT: {message}")
                    LOGGER.warning("%s; ROBOTS_POLICY=warn, prosseguindo sem inferir bloqueio.", message)
                    self._robots_cache[origin] = None
                    return True

            except CollectionError:
                raise
            except requests.RequestException as exc:
                message = f"falha de transporte ao obter robots.txt de {origin}: {exc}"
                if ROBOTS_POLICY == "strict":
                    raise CollectionError(f"ROBOTS_UNAVAILABLE_STRICT: {message}") from exc
                LOGGER.warning("%s; ROBOTS_POLICY=warn, prosseguindo sem inferir bloqueio.", message)
                self._robots_cache[origin] = None
                return True

        parser = self._robots_cache.get(origin)
        if parser is None:
            return True

        allowed = parser.can_fetch(url, USER_AGENT)
        if not allowed:
            raise CollectionError(
                f"ROBOTS_DISALLOW: URL explicitamente bloqueada pelas regras publicadas em {robots_url}: {url}"
            )
        return True

    @staticmethod
    def _retry_after_seconds(response: requests.Response | None) -> float | None:
        if response is None:
            return None
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            return max(0.0, float(value.strip()))
        except ValueError:
            return None

    @staticmethod
    def _is_retryable_http_exception(exc: Exception) -> bool:
        if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
            return True
        if isinstance(exc, requests.exceptions.HTTPError):
            response = exc.response
            return bool(response is not None and response.status_code in GenericProductCollector.RETRYABLE_HTTP_STATUS)
        return False

    @staticmethod
    def _backoff_seconds(attempt: int, retry_after: float | None = None) -> float:
        if retry_after is not None:
            base_wait = min(retry_after, RETRY_BACKOFF_MAX_SECONDS)
        else:
            base_wait = min(
                RETRY_BACKOFF_BASE_SECONDS * (2 ** max(attempt - 1, 0)),
                RETRY_BACKOFF_MAX_SECONDS,
            )
        return base_wait + random.uniform(0.0, RETRY_JITTER_SECONDS)

    def _wait_before_retry(
        self,
        *,
        source: str,
        url: str,
        attempt: int,
        max_attempts: int,
        error: Exception,
        retry_after: float | None = None,
    ) -> None:
        wait = self._backoff_seconds(attempt, retry_after)
        LOGGER.warning(
            "%s falhou para %s (tentativa %s/%s): %s. Nova tentativa em %.2fs.",
            source,
            url,
            attempt,
            max_attempts,
            error,
            wait,
        )
        time.sleep(wait)

    def _collect_http(self, url: str) -> CollectedProduct:
        last_error: Exception | None = None

        for attempt in range(1, HTTP_MAX_ATTEMPTS + 1):
            response: requests.Response | None = None
            try:
                response = self.session.get(
                    url,
                    timeout=COLLECTION_TIMEOUT_SECONDS,
                    allow_redirects=True,
                )
                status = response.status_code

                if status in self.RETRYABLE_HTTP_STATUS:
                    raise requests.exceptions.HTTPError(
                        f"HTTP {status} recebido de {url}",
                        response=response,
                    )

                response.raise_for_status()
                item = extract_product(response.text)
                item.source = "http"
                item.http_status = status
                return item

            except Exception as exc:
                last_error = exc
                retryable = self._is_retryable_http_exception(exc)

                if retryable and attempt < HTTP_MAX_ATTEMPTS:
                    self._wait_before_retry(
                        source="HTTP",
                        url=url,
                        attempt=attempt,
                        max_attempts=HTTP_MAX_ATTEMPTS,
                        error=exc,
                        retry_after=self._retry_after_seconds(response),
                    )
                    continue

                raise exc

        raise CollectionError(f"HTTP collector falhou: {last_error}")

    def collect(self, url: str) -> CollectedProduct:
        self._robots_allowed(url)
        time.sleep(max(COLLECTION_DELAY_SECONDS, 0))

        try:
            return self._collect_http(url)
        except Exception as http_exc:
            if not USE_PLAYWRIGHT_FALLBACK:
                raise CollectionError(f"HTTP collector falhou: {http_exc}") from http_exc

            LOGGER.info(
                "HTTP esgotou as tentativas ou não conseguiu extrair %s; tentando Playwright: %s",
                url,
                http_exc,
            )
            return self._collect_playwright(url, http_exc)

    def _collect_playwright(self, url: str, original_error: Exception) -> CollectedProduct:
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise CollectionError(
                "Playwright não está disponível. Execute `python -m playwright install chromium`."
            ) from exc

        last_error: Exception | None = None

        for attempt in range(1, PLAYWRIGHT_MAX_ATTEMPTS + 1):
            browser = None
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page(user_agent=USER_AGENT, locale="pt-BR")
                    response = page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=COLLECTION_TIMEOUT_SECONDS * 1000,
                    )
                    page.wait_for_timeout(1800)
                    html = page.content()
                    status = response.status if response else None

                    if status in self.RETRYABLE_HTTP_STATUS:
                        raise CollectionError(f"Playwright recebeu HTTP {status} de {url}")

                    item = extract_product(html)
                    item.source = "playwright"
                    item.http_status = status
                    return item

            except Exception as exc:
                last_error = exc
                retryable = (
                    isinstance(exc, PlaywrightTimeoutError)
                    or any(
                        token in str(exc).lower()
                        for token in [
                            "timeout",
                            "net::err_",
                            "http 408",
                            "http 425",
                            "http 429",
                            "http 500",
                            "http 502",
                            "http 503",
                            "http 504",
                        ]
                    )
                )

                if retryable and attempt < PLAYWRIGHT_MAX_ATTEMPTS:
                    self._wait_before_retry(
                        source="Playwright",
                        url=url,
                        attempt=attempt,
                        max_attempts=PLAYWRIGHT_MAX_ATTEMPTS,
                        error=exc,
                    )
                    continue
                break
            finally:
                if browser is not None:
                    try:
                        browser.close()
                    except Exception:
                        pass

        raise CollectionError(
            f"HTTP e Playwright falharam. HTTP={original_error}; Playwright={last_error}"
        ) from last_error

    @staticmethod
    def debug_dict(item: CollectedProduct) -> dict:
        return asdict(item)
