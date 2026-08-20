# Arquitetura — Competitive Intelligence Agent

## Visão geral

```text
                 config/products.yml
                         │
                         ▼
                    Catalog Sync
                         │
                         ▼
           ┌──────── Active Listings ────────┐
           │                                 │
           ▼                                 ▼
      robots.txt                         Collection Run
   Requests + Protego                         │
           │                                  ▼
           └──────────────► HTTP collector + retry/backoff
                                              │
                                     extraction succeeded?
                                       │              │
                                      yes            no
                                       │              ▼
                                       │        Playwright fallback
                                       │              │
                                       └───────┬──────┘
                                               ▼
                                      Price Observation
                                               │
                                               ▼
                                           PostgreSQL
                                               │
                    ┌──────────────────────────┼──────────────────────────┐
                    ▼                          ▼                          ▼
                 Analytics                  MCP Server               Reporting
                    │                          │                          │
                    ▼                          ▼                          ▼
                Streamlit                  AI Agent                Executive Brief
```

## Responsabilidades por camada

### Catálogo

Define o produto canônico e as URLs monitoradas por fonte.

A comparação é baseada em MPN/SKU sempre que possível. O objetivo é reduzir falsos matches entre variantes visualmente semelhantes.

### Policy / `robots.txt`

Antes da coleta, o sistema verifica a política pública da origem.

A implementação diferencia:

- `Disallow` explícito;
- arquivo não encontrado / indisponível;
- erro transitório do servidor;
- página permitida.

Isso evita transformar erro de transporte em suposto bloqueio de crawling.

### HTTP collector

Primeira estratégia de coleta.

Responsável por:

- timeout;
- retry seletivo;
- exponential backoff;
- jitter;
- status HTTP;
- extração estruturada.

### Playwright fallback

Usado somente quando a estratégia HTTP não fornece conteúdo suficiente.

Isso reduz custo e fragilidade em comparação com uma arquitetura browser-first.

### Extração

Prioridade:

1. JSON-LD / Schema.org;
2. metadados;
3. heurísticas HTML/texto.

A extração persiste também o método utilizado, permitindo auditar como cada observação foi obtida.

### PostgreSQL / SQLite

Separa:

- produto;
- fonte;
- listing;
- observação;
- execução da coleta.

`source` e `seller` são armazenados separadamente.

O pipeline completo roda sobre PostgreSQL. O deploy público (Streamlit Cloud ou qualquer ambiente sem `DATABASE_URL` configurada) sobe automaticamente sobre um snapshot SQLite real, exportado do banco operacional (`cli export-demo`) e versionado em `data/demo/`. Esse modo é somente leitura: `seed_catalog()` não roda e não existe nenhum caminho de coleta no dashboard. Ver `DEMO_MODE` em `config.py`.

### Analytics

É deliberadamente determinístico.

Calcula:

- snapshot de mercado;
- menor/mediana/maior preço;
- dispersão percentual;
- disponibilidade;
- movimentos consecutivos;
- cobertura por fonte;
- liderança de menor preço;
- maturidade do histórico;
- saúde da coleta.

### MCP

Expõe a camada analítica como tools independentes do agente.

O agente não acessa tabelas arbitrariamente; ele consome capacidades definidas pelo sistema.

O servidor MCP (`src/competitive_intelligence/mcp_server.py`) roda via stdio. Existe também um `mcp_server.py` na raiz do repositório — um entrypoint fino (`from src.competitive_intelligence.mcp_server import mcp`) usado apenas para conectar hosts MCP externos (ex.: MCP Inspector, clientes desktop) sem precisar apontar para dentro de `src/`.

### AI Market Analyst

Responsável por:

- interpretar uma pergunta;
- escolher tools;
- recuperar evidências;
- produzir síntese executiva;
- explicitar limitações de histórico.

O agente não é responsável por calcular indicadores-base.

---

# Decisões principais

## 1. URLs explícitas, não crawling aberto

O projeto monitora apenas listings definidos no catálogo.

Benefícios:

- menor carga nas fontes;
- matching auditável;
- controle do escopo;
- manutenção previsível.

## 2. HTTP antes de browser automation

Browser automation é mais pesada e mais sensível a alterações visuais.

Portanto:

```text
HTTP
 ↓
retry/backoff
 ↓
extração falhou?
 ↓
Playwright
```

## 3. Fonte e seller são conceitos separados

Evita interpretar o mesmo vendedor em dois canais como dois concorrentes diferentes.

## 4. IA não é fonte dos números

Remover a API de LLM não interrompe:

- coleta;
- persistência;
- histórico;
- analytics;
- relatório determinístico;
- dashboard.

## 5. Fotografia e tendência são conceitos separados

O sistema mede explicitamente a maturidade do histórico.

Uma oferta só entra em análise de movimento depois de possuir duas observações válidas.

## 6. Falha de coleta não é sinal de mercado

A área de Operação & Qualidade existe justamente para separar:

```text
mudança no mercado
        ≠
falha técnica do collector
```

## 7. Listings antigos são desativados, não apagados

Uma alteração no catálogo não destrói evidências históricas.

## 8. Indisponibilidade é um resultado, não ausência de dado

`success=true` com `available=false` significa que a página foi coletada com sucesso e a oferta foi identificada como indisponível — não é uma falha de coleta. Essa observação continua no histórico e nas tabelas de observações, mas não entra no cálculo de menor, mediana ou maior preço, porque não representa uma oferta comprável no momento. `success=false` (erro de transporte/extração), `available=false` (oferta esgotada) e `available=true` (oferta válida) são três estados diferentes e nunca são tratados como equivalentes pelo analytics.
