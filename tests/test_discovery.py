from src.competitive_intelligence.discovery import (
    ProductIdentity,
    SitemapUrlIndex,
    _is_probable_product_url,
    build_search_url,
    compact_text,
    extract_identity,
    extract_search_links,
    identity_match_score,
    infer_category,
    normalize_text,
    token_similarity,
)


def test_identity_from_jsonld():
    html = '''
    <html><head><script type="application/ld+json">
    {"@type":"Product","name":"Mouse Logitech G203 LIGHTSYNC 910-005793",
     "mpn":"910-005793","model":"G203 LIGHTSYNC","brand":{"name":"Logitech"}}
    </script></head></html>
    '''
    identity = extract_identity(html, "https://example.com/produto/1")
    assert identity is not None
    assert identity.mpn == "910-005793"
    assert identity.brand == "Logitech"
    assert identity.category == "Mouse"


def test_similarity_rewards_same_model():
    same = token_similarity(
        "SSD Kingston NV3 1TB SNV3S/1000G",
        "SSD Kingston NV3 1 TB M.2 NVMe SNV3S-1000G",
    )
    different = token_similarity(
        "SSD Kingston NV3 1TB SNV3S/1000G",
        "Mouse Logitech G203 910-005793",
    )
    assert same > different
    assert same > 0.45


def test_search_urls_are_expected():
    kabum = build_search_url("kabum", "910-005793")
    pichau = build_search_url("pichau", "910-005793")
    assert kabum == "https://www.kabum.com.br/busca/910-005793"
    assert pichau == "https://www.pichau.com.br/search?q=910-005793"


def test_kabum_search_links_prioritize_product_paths():
    identity = ProductIdentity(
        title="Mouse Logitech G203 LIGHTSYNC 910-005793",
        brand="Logitech",
        model="G203",
        mpn="910-005793",
        category="Mouse",
    )
    html = '''
    <a href="/hardware">Hardware</a>
    <a href="/produto/112948/mouse-logitech-g203-910-005793">Mouse Logitech G203 910-005793</a>
    <a href="/produto/9/outro-produto">Outro Produto</a>
    '''
    links = extract_search_links(html, "kabum", "https://www.kabum.com.br/busca/910-005793", identity)
    assert links[0].endswith("/produto/112948/mouse-logitech-g203-910-005793")


def test_category_inference():
    assert infer_category("Monitor Gamer LG UltraGear 27") == "Monitor"
    assert infer_category("Processador AMD Ryzen 7 7700X") == "Processador"
    assert infer_category("SSD Kingston NV3 1TB") == "SSD"
    assert normalize_text("Memória DDR5 16GB") == "memoria ddr5 16gb"


def test_compact_mpn_equivalence():
    assert compact_text("SNV3S/1000G") == compact_text("SNV3S-1000G")


def test_identity_match_accepts_same_mpn_with_different_separator():
    a = ProductIdentity("SSD Kingston NV3 1TB SNV3S/1000G", "Kingston", "NV3", "SNV3S/1000G", "SSD")
    b = ProductIdentity("SSD Kingston NV3 1TB SNV3S-1000G", "Kingston", "NV3", "SNV3S-1000G", "SSD")
    assert identity_match_score(a, b) == 1.0


def test_identity_match_rejects_different_explicit_mpn():
    a = ProductIdentity("SSD Kingston NV3 1TB", "Kingston", "NV3", "SNV3S/1000G", "SSD")
    b = ProductIdentity("SSD Kingston NV3 500GB", "Kingston", "NV3", "SNV3S/500G", "SSD")
    assert identity_match_score(a, b) == 0.0


def test_source_product_url_rules_cover_current_store_shapes():
    assert _is_probable_product_url(
        "kabum",
        "https://www.kabum.com.br/produto/621162/ssd-kingston-nv3-snv3s-1000g",
    )
    assert _is_probable_product_url(
        "terabyte",
        "https://www.terabyteshop.com.br/produto/31564/ssd-kingston-nv3-snv3s1000g",
    )
    assert _is_probable_product_url(
        "pichau",
        "https://www.pichau.com.br/ssd-kingston-nv3-1tb-snv3s-1000g",
    )
    assert not _is_probable_product_url("pichau", "https://www.pichau.com.br/hardware/ssd")
    assert not _is_probable_product_url("pichau", "https://www.pichau.com.br/search?q=nv3")


def test_sitemap_index_finds_mpn_across_url_separator_differences():
    urls = [
        "https://www.pichau.com.br/ssd-kingston-nv3-1tb-snv3s-1000g",
        "https://www.pichau.com.br/mouse-logitech-g203-910-005793",
    ]
    index = SitemapUrlIndex("pichau", urls)
    identity = ProductIdentity(
        "SSD Kingston NV3 1TB SNV3S/1000G", "Kingston", "NV3", "SNV3S/1000G", "SSD"
    )
    found = index.find(identity)
    assert found
    assert "snv3s-1000g" in found[0]
