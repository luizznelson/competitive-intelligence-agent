# Automatic Catalog Discovery

The project can expand the manually validated seed catalog to a larger real-world catalog without maintaining hundreds of URLs by hand.

## Goal

The default target is **100 canonical products**, with at least **2 validated stores per product**.

## How it works

1. Reads public TerabyteShop product sitemaps as a source of real candidate product pages.
2. Extracts product identity from Product JSON-LD / page metadata (title, brand, model and MPN when published).
3. Searches the same MPN/model in KaBuM! and Pichau only when the project's robots policy allows the search URL.
4. Opens candidate product pages and validates the match using exact MPN when available and conservative title similarity otherwise.
5. Adds a product only when the configured minimum number of independent sources has been validated.
6. Writes progress to `config/products.yml` after every accepted product, so interrupted discovery runs can be resumed.
7. Calls the normal catalog synchronizer, preserving all historical observations already stored in PostgreSQL.

## Command

```bash
python -m src.competitive_intelligence.cli discover --target 100
```

The operation is intentionally slower than a normal collection because it validates candidate pages rather than blindly adding search results.

## Safety / reliability

- Existing manually curated products are preserved.
- Duplicate MPNs and strongly duplicate titles are ignored.
- At least two validated sources are required by default.
- Explicit `robots.txt` disallow rules remain respected by the existing collection policy.
- Search failures do not fabricate listings; the candidate is simply skipped.
- A run summary is written to `data/discovery_report.json`.

After discovery, normal collection is unchanged:

```bash
python -m src.competitive_intelligence.cli collect
```
