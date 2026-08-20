from pathlib import Path

from src.competitive_intelligence.collectors.generic import extract_product, parse_brl

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_brl():
    assert parse_brl("R$ 1.299,90") == 1299.90
    assert parse_brl("219.90") == 219.90


def test_extract_jsonld_product():
    html = (FIXTURES / "product_jsonld.html").read_text(encoding="utf-8")
    item = extract_product(html)
    assert item.title == "Logitech G305 LIGHTSPEED"
    assert item.price == 219.90
    assert item.available is True
    assert item.seller == "Loja Teste"
    assert item.extraction_method == "json-ld"


def test_extract_text_heuristic_uses_best_advertised_price():
    html = (FIXTURES / "product_text.html").read_text(encoding="utf-8")
    item = extract_product(html)
    assert item.price == 499.99
    assert item.available is True
    assert "Loja Exemplo" in (item.seller or "")
    assert item.extraction_method == "text-heuristic"


def test_extract_terabyte_like_html_ignores_placeholder_and_reads_availability():
    html = (FIXTURES / "terabyte_like.html").read_text(encoding="utf-8")
    item = extract_product(html)
    assert item.price == 728.90
    assert item.available is True
    assert item.seller == "TerabyteShop"
    assert item.extraction_method == "text-heuristic"
