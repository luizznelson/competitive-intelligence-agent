# Catalog Discovery v2 — sitemap-first

A descoberta de catálogo usa os `Sitemap:` publicados no `robots.txt` de cada loja como fonte principal de URLs.

Fluxo:

1. Ler `robots.txt` de KaBuM!, Pichau e TerabyteShop.
2. Carregar e percorrer recursivamente sitemap indexes/URL sets.
3. Manter somente URLs com formato provável de página de produto.
4. Construir um índice local por URL/MPN/modelo.
5. Selecionar candidatos em round-robin entre as fontes disponíveis.
6. Extrair identidade (JSON-LD/H1) da página candidata.
7. Procurar o mesmo MPN/modelo nos índices das outras lojas.
8. Validar a página correspondente antes de gravar no catálogo.
9. Aceitar somente produtos com o número mínimo de fontes configurado.

## Por que não usar `/search?q=` na Pichau?

O discovery não depende dessa rota. A política publicada pela própria loja bloqueia URLs com parâmetros de query para crawlers. A Pichau passa a ser descoberta pelo sitemap e por páginas públicas query-free quando o sitemap estiver temporariamente indisponível.

## 403 de sitemap

Um HTTP 403 não é contornado. O sistema tenta outros sitemaps explicitamente publicados pela loja, depois cache local previamente obtido e, em último caso, um crawl limitado de páginas públicas permitidas pela política do projeto. Isso diferencia indisponibilidade temporária da fonte de uma regra `robots.txt`.

## Cache

Os índices de URLs são persistidos em `data/discovery_cache/` por padrão por 24 horas. Isso reduz tráfego e evita baixar dezenas de milhares de URLs a cada execução.

## Diagnóstico

```bash
python -m src.competitive_intelligence.cli sources --refresh
```

Exibe, por fonte, a estratégia usada (`sitemap`, `fresh-cache`, `stale-cache`, `public-catalog-fallback` ou `unavailable`) e quantas URLs de produto ficaram disponíveis.
