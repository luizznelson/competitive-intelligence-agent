from pathlib import Path

import yaml


CATALOG_PATH = Path(__file__).resolve().parents[1] / "config" / "products.yml"
PRIMARY_SOURCES = {"kabum", "pichau", "terabyte"}


def _load_products():
    data = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    return data["products"]


def test_catalog_has_expected_scale_and_primary_sources():
    products = _load_products()

    # O projeto foi expandido para pelo menos 100 produtos.
    # Não usar == 100 para permitir crescimento futuro do catálogo.
    assert len(products) >= 100

    active_sources = {
        listing["competitor"]
        for product in products
        for listing in product["listings"]
        if listing.get("active", True)
    }

    # As fontes competitivas ativas principais devem continuar sendo estas.
    assert PRIMARY_SOURCES.issubset(active_sources)

    # Magazine Luiza pode permanecer modelado historicamente,
    # mas não deve aparecer como fonte ativa principal.
    assert "magalu" not in active_sources


def test_catalog_has_unique_product_ids_and_listing_urls():
    products = _load_products()

    canonical_ids = [product["canonical_id"] for product in products]
    assert len(canonical_ids) == len(set(canonical_ids))

    urls = [
        listing["url"]
        for product in products
        for listing in product["listings"]
    ]
    assert len(urls) == len(set(urls))


def test_every_product_has_at_least_two_active_sources_and_identity():
    products = _load_products()

    for product in products:
        active_sources = {
            listing["competitor"]
            for listing in product["listings"]
            if listing.get("active", True)
        }

        assert len(active_sources) >= 2, product["canonical_id"]

        assert product.get("canonical_id"), product
        assert product.get("canonical_name"), product["canonical_id"]
        assert product.get("brand"), product["canonical_id"]

        # Discovery pode identificar o SKU por MPN quando disponível
        # ou por modelo normalizado quando o varejista não publica MPN.
        assert (
            product.get("mpn") or product.get("model")
        ), f"Produto sem identidade suficiente: {product['canonical_id']}"