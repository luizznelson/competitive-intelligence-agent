import pytest

from src.competitive_intelligence.collectors.base import CollectionError
from src.competitive_intelligence.collectors.generic import GenericProductCollector


class DummyResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text
        self.headers = {}


def test_product_page_allowed_when_robots_explicitly_allows(monkeypatch):
    collector = GenericProductCollector()
    robots = """User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /checkout/\n"""
    monkeypatch.setattr(collector.session, "get", lambda *a, **k: DummyResponse(200, robots))

    assert collector._robots_allowed("https://www.pichau.com.br/produto-exemplo") is True


def test_explicit_disallow_is_respected(monkeypatch):
    collector = GenericProductCollector()
    robots = """User-agent: *\nAllow: /\nDisallow: /api/\n"""
    monkeypatch.setattr(collector.session, "get", lambda *a, **k: DummyResponse(200, robots))

    with pytest.raises(CollectionError, match="ROBOTS_DISALLOW"):
        collector._robots_allowed("https://www.pichau.com.br/api/private")


def test_warn_policy_does_not_mislabel_robots_fetch_403_as_explicit_disallow(monkeypatch):
    collector = GenericProductCollector()
    monkeypatch.setattr(collector.session, "get", lambda *a, **k: DummyResponse(403, ""))

    # Default project policy is warn: inability to retrieve robots is different
    # from a parsed Disallow rule and must not be reported as such.
    assert collector._robots_allowed("https://www.example.com/product/1") is True


def test_server_error_on_robots_is_conservative(monkeypatch):
    collector = GenericProductCollector()
    monkeypatch.setattr(collector.session, "get", lambda *a, **k: DummyResponse(503, ""))

    with pytest.raises(CollectionError, match="ROBOTS_UNAVAILABLE"):
        collector._robots_allowed("https://www.example.com/product/1")


def test_pichau_query_string_rule_is_respected(monkeypatch):
    collector = GenericProductCollector()
    robots = """User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /*?*\n"""
    monkeypatch.setattr(collector.session, "get", lambda *a, **k: DummyResponse(200, robots))

    with pytest.raises(CollectionError, match="ROBOTS_DISALLOW"):
        collector._robots_allowed("https://www.pichau.com.br/produto-exemplo?utm_source=test")


def test_magalu_normal_product_path_is_allowed(monkeypatch):
    collector = GenericProductCollector()
    robots = """User-agent: *\nDisallow: /Includes/\nDisallow: /compra/\nDisallow: /nota-fiscal/\nDisallow: /boleto/\n"""
    monkeypatch.setattr(collector.session, "get", lambda *a, **k: DummyResponse(200, robots))

    assert collector._robots_allowed(
        "https://www.magazineluiza.com.br/produto-exemplo/p/abc123/in/ssdi/"
    ) is True


def test_terabyte_explicit_product_allow_and_search_disallow(monkeypatch):
    collector = GenericProductCollector()
    robots = """User-agent: *\nAllow: /produto/\nAllow: /hardware/\nDisallow: /busca\nDisallow: /*?p=\n"""
    monkeypatch.setattr(collector.session, "get", lambda *a, **k: DummyResponse(200, robots))

    assert collector._robots_allowed(
        "https://www.terabyteshop.com.br/produto/31563/ssd-kingston-nv3"
    ) is True

    with pytest.raises(CollectionError, match="ROBOTS_DISALLOW"):
        collector._robots_allowed("https://www.terabyteshop.com.br/busca?q=ssd")
