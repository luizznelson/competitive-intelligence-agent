# Competitive Intelligence Agent

### Monitoramento automatizado de concorrentes para transformar preços públicos em sinais de mercado

Sistema de inteligência competitiva para eletrônicos que coleta **preço e disponibilidade em fontes públicas**, mantém histórico real, calcula indicadores determinísticos e disponibiliza os dados em um dashboard executivo e para um **agente de IA conectado por MCP**.

> **Pergunta de negócio:** como substituir o monitoramento manual de concorrentes por uma rotina contínua, rastreável e orientada por dados — sem depender de análise manual a cada ciclo?

`Python` · `Playwright` · `PostgreSQL` · `SQL` · `Pandas` · `Streamlit` · `Plotly` · `MCP` · `LangChain/LangGraph-ready` · `Groq` · `Docker` · `Pytest`

---

## O problema

Monitorar concorrentes manualmente parece simples quando existem poucos produtos. O problema aparece quando a operação precisa repetir, todos os dias:

1. abrir diferentes lojas;
2. localizar o mesmo SKU em cada fonte;
3. registrar preço e disponibilidade;
4. identificar mudanças relevantes;
5. separar um movimento de mercado de um problema de coleta;
6. transformar tudo em informação útil para decisão.

O custo não está apenas no tempo de consulta. Sem histórico estruturado, cada análise recomeça praticamente do zero.

O projeto foi construído para responder:

> **Quais produtos e fontes apresentam sinais competitivos que justificam investigação ou ação comercial?**

---

## A solução

```text
Catálogo de SKUs
      ↓
Política robots.txt
      ↓
HTTP + retry/backoff
      ↓ (fallback quando necessário)
Playwright
      ↓
Extração + normalização
      ↓
PostgreSQL + histórico
      ↓
Analytics determinístico
      ↓
Dashboard + relatório
      ↓
MCP tools
      ↓
AI Market Analyst
```

A IA não é o sistema inteiro. A coleta, o banco, o histórico, os indicadores e o dashboard funcionam sem LLM.

---

## Como a análise conta uma história

A visão executiva foi desenhada para responder perguntas em sequência, e não apenas mostrar gráficos:

### 1. Prioridade

**Onde existe maior divergência de preço?**

Os SKUs são ordenados pela dispersão percentual entre a menor e a maior oferta válida. O uso de percentual permite comparar categorias com faixas de preço diferentes.

### 2. Fontes

**Quem aparece com menor preço e onde existem sinais de ruptura?**

O sistema acompanha:

- quantidade de SKUs em que cada fonte possui a menor oferta;
- disponibilidade por fonte;
- cobertura da coleta;
- gap médio para o menor preço observado do SKU.

### 3. Movimento

**O que mudou desde a coleta anterior?**

A variação é calculada somente quando a mesma oferta possui pelo menos duas observações válidas.

> Uma coleta produz uma **fotografia**. Tendência exige histórico.

### 4. Evidência

A análise executiva sempre permite chegar ao dado de origem: produto, fonte, seller, preço, disponibilidade, URL, horário, método de extração e eventual falha.

---

## Dados reais

A versão atual monitora um catálogo de **20 produtos canônicos** e **57 URLs ativas** em três fontes principais:

- **KaBuM!**
- **Pichau**
- **TerabyteShop**

O matching prioriza **MPN/SKU**, evitando comparar produtos parecidos que são, na prática, variantes diferentes.

O Magazine Luiza permanece modelado como canal complementar, mas não é usado como concorrente principal nos casos em que a oferta é vendida pela própria KaBuM!.

> O projeto não gera preços históricos artificiais. O histórico começa na primeira execução real do collector.

---

# Decisões de engenharia

## HTTP antes de browser automation

`requests` é a primeira estratégia porque é mais leve, previsível e barata.

O Playwright entra como fallback quando:

- o HTML entregue por HTTP não contém informação suficiente;
- a página depende de renderização no navegador;
- a extração estruturada falha após as tentativas HTTP.

Antes do fallback, erros transitórios passam por **retry seletivo + exponential backoff + jitter**.

---

## Produto canônico antes de comparar preço

Um mesmo produto pode aparecer como:

```text
SSD Kingston NV3 1TB M.2 NVMe
Kingston NV3 1 TB PCIe 4.0
SSD NV3 SNV3S/1000G Kingston
```

Comparar apenas o título é frágil.

Por isso, o catálogo mantém uma identidade canônica e utiliza MPN/SKU como principal referência.

---

## Fonte não é a mesma coisa que seller

Em marketplaces:

```text
source/channel = Magazine Luiza
seller         = KaBuM!
```

Sem essa separação, o sistema poderia interpretar o mesmo vendedor como dois concorrentes independentes.

`source` e `seller` são persistidos separadamente.

---

## Indicadores não são calculados pelo LLM

São determinísticos:

- menor preço;
- mediana;
- maior preço;
- spread percentual;
- disponibilidade;
- variação entre observações;
- liderança de menor preço;
- cobertura da coleta;
- saúde do pipeline.

A IA recebe esses resultados através de tools e atua na **investigação e síntese**, não na criação dos números.

---

## Sem backfill fictício

O sistema diferencia explicitamente:

```text
1 observação  → fotografia atual
2+ observações → possibilidade de medir movimento
histórico maior → análise de tendência
```

Isso impede o dashboard de sugerir tendências que os dados ainda não sustentam.

---

# Desafios reais encontrados

## 1. `robots.txt`

A primeira implementação confundia falha ao obter o arquivo `robots.txt` com um `Disallow` explícito.

Consequência: páginas permitidas eram classificadas incorretamente como bloqueadas.

A solução foi redesenhada para:

- buscar o arquivo usando a mesma sessão HTTP do collector;
- interpretar as regras com **Protego**;
- distinguir `Disallow` real de indisponibilidade/falha de transporte;
- persistir o motivo correto quando uma coleta não ocorre.

Esse problema foi identificado durante a execução com fontes reais, não criado artificialmente para demonstração.

## 2. HTML variável entre fontes

Cada varejista expõe preço e disponibilidade de forma diferente.

A estratégia de extração prioriza:

1. JSON-LD / Schema.org;
2. metadados estruturados;
3. heurísticas de HTML/texto;
4. Playwright como fallback.

## 3. Preço visível não significa oferta válida

O collector precisa evitar valores como:

- parcelas;
- placeholders;
- produtos esgotados tratados como preço corrente;
- valores não associados à oferta principal.

Uma oferta indisponível continua sendo persistida como **sinal de mercado**, mas não entra no cálculo de menor/mediana/maior preço atual.

## 4. Coleta e inteligência são problemas diferentes

Uma falha do scraper não deve ser interpretada como mudança do mercado.

Por isso, o projeto possui uma área específica de **Operação & Qualidade**, separando saúde do pipeline dos sinais competitivos.

---

# Dashboard

O Streamlit possui cinco perspectivas.

### Visão executiva

Responde primeiro **o que merece atenção**, e só depois mostra as evidências.

- maior divergência de preço;
- liderança por menor preço;
- disponibilidade;
- dispersão percentual;
- movimentos recentes;
- maturidade do histórico.

### Mercado & preços

Exploração detalhada de um SKU:

- menor preço;
- mediana;
- maior preço;
- ofertas por fonte;
- seller;
- disponibilidade;
- histórico acumulado.

### Analista de IA

Interface em linguagem natural que consulta tools MCP.

Exemplos:

```text
Quais produtos merecem atenção agora?
Qual fonte lidera mais SKUs em preço?
Compare as ofertas do Kingston NV3 1TB.
O histórico já é suficiente para falar em tendência?
Como está a saúde da coleta?
```

### Operação & qualidade

Mostra se a informação é confiável antes de interpretá-la:

- taxa de sucesso;
- cobertura por fonte;
- método HTTP/Playwright;
- método de extração;
- falhas recentes;
- rastreabilidade;
- maturidade do histórico.

### Método & decisões

Documenta dentro do próprio produto:

- por que HTTP vem antes do Playwright;
- como produto canônico é definido;
- por que seller e source são separados;
- por que os indicadores são determinísticos;
- onde MCP e IA entram;
- quais problemas reais apareceram durante o desenvolvimento.

---

# MCP + AI Market Analyst

O servidor MCP expõe ferramentas como:

```text
compare_market()
compare_product(canonical_id)
get_price_history(canonical_id, days)
get_recent_changes(threshold_pct)
get_source_summary()
get_history_maturity()
get_collection_health(limit)
```

O agente escolhe as ferramentas necessárias para responder à pergunta.

Fluxo:

```text
Pergunta do usuário
      ↓
AI Market Analyst
      ↓
MCP tools
      ↓
Analytics / PostgreSQL
      ↓
Evidências reais
      ↓
Síntese executiva
```

O prompt do agente exige separar **achado, evidência e limitação**, além de explicitar quando o histórico ainda é insuficiente.

---

# Modelo de dados

Principais entidades:

```text
products
competitors
listings
price_observations
collection_runs
```

Cada observação preserva:

```text
produto canônico
fonte
seller
preço
moeda
disponibilidade
URL
timestamp
origem da coleta
método de extração
HTTP status
sucesso/falha
erro
```

Listings removidos do YAML são marcados como `active=false` em vez de apagados, preservando rastreabilidade.

---

# Relatório executivo

O projeto gera um brief em Markdown com:

- pergunta de negócio;
- resposta executiva;
- maiores dispersões;
- leitura por fonte;
- movimentos relevantes;
- maturidade do histórico;
- saúde da última execução;
- nota metodológica.

```powershell
docker compose exec dashboard python -m src.competitive_intelligence.cli report
```

---

# Estrutura

```text
competitive-intelligence-agent/
├── .streamlit/
│   └── config.toml
├── config/
│   └── products.yml
├── dashboard/
│   └── app.py
├── docs/
│   ├── architecture.md
│   └── case-study.md
├── reports/
├── scripts/
│   └── run_scheduler.py
├── src/
│   └── competitive_intelligence/
│       ├── collectors/
│       │   ├── base.py
│       │   └── generic.py
│       ├── agent.py
│       ├── analytics.py
│       ├── cli.py
│       ├── config.py
│       ├── db.py
│       ├── mcp_server.py
│       ├── models.py
│       ├── reporting.py
│       ├── robots.py
│       └── service.py
├── tests/
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── requirements.txt
```

---

# Executando com Docker

## 1. Ambiente

```powershell
Copy-Item .env.example .env
```

A IA é opcional. Para habilitar o agente:

```text
GROQ_API_KEY=sua_chave
```

Nunca versione o `.env`.

## 2. Suba banco e dashboard

```powershell
docker compose up --build -d db dashboard
```

Acesse:

```text
http://localhost:8501
```

## 3. Sincronize o catálogo

```powershell
docker compose exec dashboard python -m src.competitive_intelligence.cli init
```

## 4. Execute uma coleta

Pelo dashboard: **Executar coleta**.

Ou:

```powershell
docker compose exec dashboard python -m src.competitive_intelligence.cli collect
```

## 5. Testes

```powershell
docker compose exec dashboard pytest -q
```

## 6. Scheduler opcional

```powershell
docker compose --profile scheduler up -d scheduler
```

---

# O que este projeto demonstra

Mais do que uma stack, o case mostra uma sequência de raciocínio:

```text
Problema operacional
        ↓
Definição do que precisa ser medido
        ↓
Escolha das fontes
        ↓
Arquitetura de coleta
        ↓
Tratamento de falhas reais
        ↓
Modelagem e histórico
        ↓
Analytics determinístico
        ↓
Comunicação executiva
        ↓
IA como camada de investigação
```

A intenção não é construir “um scraper com IA”.

É construir um **sistema de inteligência competitiva** em que coleta, qualidade, análise e interpretação possuem responsabilidades separadas.

---

# Limitações e próximos passos

- páginas públicas podem mudar de estrutura;
- preço observado não inclui necessariamente frete, cupom ou condição personalizada;
- disponibilidade publicada pode não refletir estoque físico em tempo real;
- ampliar o catálogo aumenta a necessidade de manutenção dos adapters;
- tendência confiável depende da acumulação contínua de histórico;
- regras de coleta e termos das fontes devem ser reavaliados periodicamente.

Evoluções possíveis:

- matching semiautomático de novos produtos;
- alertas por e-mail/Slack;
- scheduler gerenciado;
- API para consumo externo;
- relatório em PDF;
- detecção de anomalias de coleta;
- avaliação formal das respostas do agente;
- deployment contínuo.

---

## Uso responsável

Projeto educacional/de portfólio. A coleta é restrita a páginas públicas explicitamente configuradas e deve respeitar políticas das fontes, `robots.txt`, limites de requisição e legislação aplicável. O sistema não implementa bypass de autenticação, CAPTCHA ou mecanismos de bloqueio.

---

## Escala do catálogo: descoberta automática

Para evitar manter manualmente centenas de URLs, o projeto possui uma etapa separada de **Product Discovery**. Ela usa páginas públicas reais, identifica produtos, procura o mesmo item nas demais fontes e só adiciona matches validados ao catálogo.

O alvo padrão é **100 produtos canônicos**, exigindo pelo menos **2 fontes independentes** por produto.

```bash
python -m src.competitive_intelligence.cli discover --target 100
```

Depois da descoberta, os novos produtos são sincronizados no banco e passam a fazer parte das próximas coletas normalmente.

Detalhes: [`docs/catalog-discovery.md`](docs/catalog-discovery.md).
