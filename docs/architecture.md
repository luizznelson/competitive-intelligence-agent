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

### PostgreSQL

Separa:

- produto;
- fonte;
- listing;
- observação;
- execução da coleta.

`source` e `seller` são armazenados separadamente.

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
