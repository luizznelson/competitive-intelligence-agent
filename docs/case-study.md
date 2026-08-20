# Case Study — Competitive Intelligence Agent

## Contexto

Uma rotina simples de inteligência competitiva pode exigir que alguém abra repetidamente diversas páginas de concorrentes para registrar preço e disponibilidade.

Essa abordagem funciona em baixa escala, mas começa a falhar quando a quantidade de SKUs e fontes cresce:

- o trabalho é repetitivo;
- mudanças podem passar despercebidas;
- não existe histórico confiável;
- comparar títulos de produto manualmente é sujeito a erro;
- falhas de coleta podem ser confundidas com mudanças reais do mercado;
- cada relatório exige reconstruir a análise.

## Pergunta

> Como substituir o monitoramento manual de concorrentes por uma rotina contínua e rastreável que indique onde existe informação relevante para decisão?

## Critério de sucesso

O sistema deveria conseguir:

1. monitorar páginas públicas previamente selecionadas;
2. associar listings ao mesmo produto canônico;
3. registrar preço, disponibilidade, seller e horário;
4. manter histórico;
5. calcular sinais de forma determinística;
6. mostrar qualidade e falhas da própria coleta;
7. permitir investigação em linguagem natural sem entregar os cálculos ao LLM.

---

# Como a solução foi pensada

## Primeiro: definir o que era dado de mercado

Uma página publicada não significa automaticamente uma oferta comparável.

O sistema diferencia:

- preço extraído;
- disponibilidade;
- seller;
- canal;
- sucesso da coleta;
- método de extração.

Isso permite dizer não apenas “qual preço foi encontrado”, mas “qual o nível de confiança operacional nessa observação”.

## Segundo: tratar produto como entidade, não como texto

O mesmo SKU pode receber títulos diferentes em cada varejista.

A comparação parte de um produto canônico e prioriza MPN/SKU.

## Terceiro: separar coleta de análise

A coleta precisa ser confiável antes de qualquer conclusão.

Por isso o projeto separa:

```text
Collection Health
Market Analytics
AI Interpretation
```

## Quarto: usar IA somente onde existe incerteza interpretativa

Cálculos objetivos permanecem determinísticos.

O agente é utilizado para:

- decidir quais tools consultar;
- combinar diferentes evidências;
- explicar o que merece atenção;
- reconhecer quando o histórico é insuficiente.

---

# Desafios que apareceram de verdade

## `robots.txt` classificado incorretamente

Na primeira implementação, uma falha ao buscar o arquivo poderia ser interpretada como bloqueio total.

A correção separou erro de transporte de `Disallow` explícito e introduziu parsing com Protego.

## Sites com renderização diferente

Algumas fontes expõem JSON-LD diretamente; outras exigem navegador.

A solução tornou a coleta adaptativa:

```text
HTTP → retry/backoff → Playwright fallback
```

## Marketplace duplicando concorrente

Uma oferta publicada em marketplace pode ter como seller uma loja já monitorada diretamente.

A modelagem passou a distinguir `source` de `seller`.

## Histórico insuficiente

Um dashboard pode induzir conclusões erradas se tratar uma única coleta como tendência.

O projeto introduziu uma métrica de maturidade do histórico e comunica explicitamente quando os dados só permitem uma fotografia atual.

---

# Como apresentar este case em entrevista

Uma versão curta:

> “Eu parti de um problema de monitoramento competitivo manual. Modelei um catálogo de produtos canônicos, construí uma camada de coleta com HTTP, retry/backoff e fallback para Playwright, persisti histórico em PostgreSQL e separei indicadores determinísticos da interpretação por IA. Durante o desenvolvimento encontrei problemas reais com robots.txt, páginas dinâmicas e marketplaces, e ajustei a arquitetura para manter rastreabilidade. O agente acessa apenas tools MCP e não calcula preços ou indicadores por conta própria.”

## O que o case demonstra

- diagnóstico de problema;
- arquitetura antes da implementação;
- automação;
- web data collection;
- tratamento de erros;
- modelagem relacional;
- analytics;
- qualidade de dados;
- storytelling executivo;
- MCP;
- agentes de IA;
- Docker;
- testes;
- documentação.

---

# Prints recomendados para o portfólio

## 1. Visão executiva

Mostrar:

- pergunta de negócio;
- maior divergência;
- liderança por preço;
- disponibilidade;
- gráfico de dispersão.

Esse print responde **o que o sistema descobriu**.

## 2. Mercado & preços

Selecionar um SKU com três fontes válidas e boa dispersão.

Mostrar:

- menor/mediana/maior;
- tabela de fontes;
- gráfico de preços;
- histórico quando já houver observações suficientes.

Esse print mostra **a evidência**.

## 3. Operação & qualidade

Mostrar:

- taxa de sucesso;
- cobertura por fonte;
- métodos de coleta;
- maturidade do histórico;
- rastreabilidade.

Esse print mostra **que a análise não depende de dados tratados como caixa-preta**.

---

# O que evitar ao apresentar

Evitar descrever o projeto como:

> “scraper com IA”

ou:

> “dashboard usando Streamlit, MCP e Groq”

A tecnologia deve vir depois do problema.

A descrição preferida é:

> **Sistema automatizado de inteligência competitiva que coleta e historiza observações públicas de mercado, calcula sinais de preço e disponibilidade e disponibiliza evidências para análise executiva e investigação assistida por IA.**
