# Catalog Discovery — sitemap-first

O objetivo é expandir o catálogo curado manualmente para um catálogo maior e real, sem manter centenas de URLs à mão. O alvo padrão é **100 produtos canônicos**, com pelo menos **2 fontes validadas** por produto.

## Estratégia

A descoberta usa os `Sitemap:` publicados no `robots.txt` de cada loja como fonte principal de URLs — não crawling aberto, não busca por palavra-chave como estratégia primária.

Fluxo:

1. Ler `robots.txt` de KaBuM!, Pichau e TerabyteShop dinamicamente, a cada execução — o projeto se adapta se uma loja alterar suas regras.
2. Carregar e percorrer recursivamente os sitemap indexes / URL sets publicados.
3. Manter apenas URLs com formato provável de página de produto.
4. Construir um índice local por URL/MPN/modelo.
5. Selecionar candidatos em round-robin entre as fontes disponíveis.
6. Extrair identidade (JSON-LD / H1) da página candidata.
7. Procurar o mesmo MPN/modelo nos índices das outras lojas.
8. Validar a página correspondente (MPN exato quando disponível, similaridade conservadora de título como alternativa).
9. Aceitar o produto no catálogo somente quando o número mínimo de fontes configurado for atingido.

Progresso é gravado em `config/products.yml` após cada produto aceito, permitindo retomar uma execução interrompida sem perder o que já foi validado.

## Por que não usar `/search?q=` na Pichau

O discovery não depende dessa rota como estratégia principal: a política publicada no `robots.txt` da Pichau bloqueia URLs com parâmetro de query para crawlers. Em vez de contornar essa regra, a Pichau é descoberta via sitemap e, quando o sitemap está temporariamente indisponível, via páginas públicas *query-free*. Uma rota de busca legada permanece no código apenas como fallback documentado — hoje só KaBuM! usa uma rota de busca sem parâmetro de query como complemento ao sitemap.

## Indisponibilidade de sitemap

Um HTTP 403 ou similar não é contornado. O sistema tenta outros sitemaps explicitamente publicados pela loja, depois cache local previamente obtido e, em último caso, um crawl limitado de páginas públicas permitidas pela política do projeto. Isso diferencia indisponibilidade temporária da fonte de uma regra `robots.txt` — o mesmo cuidado usado na coleta normal (ver [`docs/architecture.md`](architecture.md)).

## Cache

Os índices de URLs de cada sitemap são persistidos em `data/discovery_cache/` por 24 horas por padrão, reduzindo tráfego e evitando baixar dezenas de milhares de URLs a cada execução.

## Comandos

```bash
python -m src.competitive_intelligence.cli discover --target 100
python -m src.competitive_intelligence.cli sources --refresh
```

`sources --refresh` diagnostica, por fonte, a estratégia usada (`sitemap`, `fresh-cache`, `stale-cache`, `public-catalog-fallback` ou `unavailable`) e quantas URLs de produto ficaram disponíveis, ignorando o cache local.

Depois do discovery, a coleta normal segue igual:

```bash
python -m src.competitive_intelligence.cli collect
```

## Evidência da execução real que levou o catálogo a 100 produtos

Registrada em `data/discovery_report.json`:

| Métrica | Valor |
|---|---|
| Produtos iniciais | 36 |
| Candidatos avaliados | 462 |
| Produtos aceitos | 64 |
| Rejeitados por duplicidade | 15 |
| Rejeitados por identidade inconsistente | 9 |
| Rejeitados por fonte única (mínimo não atingido) | 374 |
| Catálogo final | 100 |

A maior parte dos candidatos avaliados (374 de 462) foi descartada por não atingir o mínimo de 2 fontes independentes validadas — o discovery é deliberadamente conservador: um candidato sem confirmação cruzada não vira produto no catálogo.

## Segurança e confiabilidade

- produtos curados manualmente são preservados;
- MPNs duplicados e títulos fortemente duplicados são ignorados;
- regras explícitas de `Disallow` em `robots.txt` continuam respeitadas pela mesma política de coleta usada no pipeline normal;
- falha de busca não fabrica listing — o candidato é simplesmente descartado.
