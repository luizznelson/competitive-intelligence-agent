from pathlib import Path

import yaml


def test_catalog_has_twenty_products_and_three_primary_sources():
    path = Path(__file__).resolve().parents[1] / "config" / "products.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    products = data["products"]
    active = []
    inactive = []
    for product in products:
        for listing in product["listings"]:
            row = (product["canonical_id"], listing["competitor"], listing.get("active", True))
            (active if row[2] else inactive).append(row)

    assert len(products) == 20
    assert len(active) == 57
    assert {competitor for _, competitor, _ in active} == {"kabum", "pichau", "terabyte"}
    assert any(competitor == "magalu" for _, competitor, _ in inactive)


def test_catalog_has_unique_canonical_ids_and_urls():
    path = Path(__file__).resolve().parents[1] / "config" / "products.yml"
    products = yaml.safe_load(path.read_text(encoding="utf-8"))["products"]

    canonical_ids = [p["canonical_id"] for p in products]
    urls = [listing["url"] for p in products for listing in p["listings"]]

    assert len(canonical_ids) == len(set(canonical_ids))
    assert len(urls) == len(set(urls))


def test_every_product_has_at_least_two_active_sources_and_mpn():
    path = Path(__file__).resolve().parents[1] / "config" / "products.yml"
    products = yaml.safe_load(path.read_text(encoding="utf-8"))["products"]

    for product in products:
        active_sources = {x["competitor"] for x in product["listings"] if x.get("active", True)}
        assert len(active_sources) >= 2, product["canonical_id"]
        assert product.get("mpn"), product["canonical_id"]
