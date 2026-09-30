# Reconstrução histórica CHIRPS v3.0 — estado acumulado (Fase 2C.3B)

**Relatório de status — STOP-ON-FAILURE no lote 10. Não substitui dados
operacionais, não calcula skill, não altera SARIMAX/XGBoost/dashboard/
previsões históricas do CFSv2.**

## 1. Objetivo desta atividade

Concluir a reconstrução histórica CHIRPS v3.0 Final de jan/1981 a
mai/2011 (365 meses, 16 lotes de 24 meses, o último com 5), executando
sequencialmente os lotes 1 a 15 — o lote 0 (1981-01 a 1982-12) já
estava aprovado e **não foi repetido**. Cada lote é uma barreira
independente: só o lote seguinte é iniciado quando o anterior tem
cobertura temporal completa (24/24 meses com valor científico válido,
`ok`/`zero_real`, nenhum ausente/NoData/falha/valor inválido).

## 2. Resultado desta execução

**Lotes 1 a 9: APROVADOS, 24/24 meses válidos cada — 216 meses.**
Somados aos 24 meses do lote 0 (preservados, não repetidos), o arquivo
acumulado tem **240/365 meses com valor científico válido** (1981-01 a
2000-12, contínuo, sem lacunas).

**Lote 10 (2001-01 a 2002-12): REPROVADO — STOP-ON-FAILURE acionado.**
A execução foi interrompida imediatamente após a avaliação do lote 10;
**os lotes 11 a 15 NÃO foram iniciados**, conforme a regra.

| Lote | Período | Meses | Status |
|---|---|---|---|
| 0 | 1981-01 a 1982-12 | 24 | ✅ APROVADO (já estava, preservado) |
| 1 | 1983-01 a 1984-12 | 24 | ✅ APROVADO — 24/24 válidos |
| 2 | 1985-01 a 1986-12 | 24 | ✅ APROVADO — 24/24 válidos |
| 3 | 1987-01 a 1988-12 | 24 | ✅ APROVADO — 24/24 válidos |
| 4 | 1989-01 a 1990-12 | 24 | ✅ APROVADO — 24/24 válidos |
| 5 | 1991-01 a 1992-12 | 24 | ✅ APROVADO — 24/24 válidos |
| 6 | 1993-01 a 1994-12 | 24 | ✅ APROVADO — 24/24 válidos |
| 7 | 1995-01 a 1996-12 | 24 | ✅ APROVADO — 24/24 válidos |
| 8 | 1997-01 a 1998-12 | 24 | ✅ APROVADO — 24/24 válidos |
| 9 | 1999-01 a 2000-12 | 24 | ✅ APROVADO — 24/24 válidos |
| **10** | **2001-01 a 2002-12** | **24** | **❌ REPROVADO — 23/24 válidos, 1 falha** |
| 11–15 | 2003-01 a 2011-05 | 125 | ⏸ NÃO INICIADOS (STOP-ON-FAILURE) |

## 3. Diagnóstico da falha — lote 10

- **Mês responsável: 2001-08.**
- **Status:** `erro_verificacao_disponibilidade` — falha na checagem
  HTTP de disponibilidade do arquivo no servidor do CHC, ANTES de
  qualquer tentativa de leitura do raster.
- **Motivo registrado:** `erro_rede: <urlopen error [Errno 104]
  Connection reset by peer>` — reset de conexão TCP durante a
  requisição, já depois de 3 tentativas internas esgotadas
  (`identificacao_arquivo__tentativas_esgotadas=3`,
  `scripts/_chirps_v3.py::verificar_disponibilidade_http`).
- **Classificação:** falha de rede transitória (classe 3 da
  classificação exaustiva de `scripts/chirps_v3_piloto.py` —
  `STATUS_FALHA_OU_INVALIDO_CONHECIDOS`) — **não** é `mes_ausente`,
  **não** é NoData (`nodata_sentinela`/`nodata_nan`), **não** é valor
  implausível. É uma falha real de comunicação com o servidor.
- **Nenhuma ação corretiva foi tomada nesta atividade**, por desenho:
  - o valor não foi substituído por zero, nem interpolado;
  - nenhuma outra versão do CHIRPS foi usada;
  - o pixel de referência (`CHIRPS_v3_ponto_centroide`) não foi
    alterado;
  - o valor problemático não foi modificado manualmente;
  - `scripts/chirps_v3_piloto.py::reprocessar_ausentes_ou_nodata()`
    **não** foi acionado (esse mecanismo é reservado a
    `mes_ausente`/`nodata_sentinela`/`nodata_nan`, nenhum dos quais
    ocorreu aqui — não seria a ferramenta certa mesmo se fosse
    aplicável).
  - Falhas transitórias de rede/arquivo (diferente de
    `mes_ausente`/NoData) permanecem elegíveis à **retomada normal já
    implementada** (`meses_pendentes`/`executar_lote`, porque o status
    não está em `STATUS_RESOLVIDOS`) — uma nova chamada a
    `executar_lote(10)` tentaria novamente, automaticamente, só o mês
    2001-08 (os outros 23 já resolvidos não seriam retocados). Essa
    nova tentativa **não foi disparada nesta atividade** — decisão
    explícita de quem revisar este relatório.

## 4. Integridade do arquivo acumulado

`data/chirps_v3_historico/chirps_v3_1981_2011.csv` após esta execução:

- **264 registros** (24 do lote 0 + 216 dos lotes 1-9 + 24 do lote 10,
  sendo 23 válidos e 1 com falha registrada).
- Nenhum registro duplicado (1 linha por par ano-mês, verificado
  programaticamente).
- Ordenação cronológica mantida (1981-01 → 2002-12).
- Nenhum mês de lote anteriormente aprovado foi perdido.
- **Lote 0 verificado byte-a-byte nos campos de dado** (comparação
  coluna a coluna contra o commit anterior): as 24 linhas originais
  continuam com os mesmos valores em todas as colunas em comum — a
  única diferença no `git diff` bruto é cosmética (duas colunas novas
  de diagnóstico de falha, `identificacao_arquivo__motivo` e
  `identificacao_arquivo__tentativas_esgotadas`, introduzidas pelo
  lote 10 e gravadas como vazias/NaN nas linhas do lote 0, que nunca
  tiveram falha) — nenhum valor real foi alterado.
- Metadados de proveniência (URL, formato, versão CHIRPS, timestamp de
  extração, identificação do arquivo, classificação do pixel) mantidos
  em todas as linhas.

## 5. Metodologia preservada

- CHIRPS v3.0 Final mensal, ponto único no pixel de referência
  `CHIRPS_v3_ponto_centroide` — mesma convenção de seleção de pixel,
  mesmas verificações de CRS/resolução/origem/dimensões
  (`scripts/_chirps_v3.py::verificar_grade`), mesma separação entre
  zero real e ausência (`classificar_valor`).
- **`scripts/_chirps_v3.py` não foi alterado nesta atividade** — nenhum
  erro real impediu a execução a ponto de justificar mudança de
  comportamento (a falha de 2001-08 é externa, do lado do servidor).
- A análise de sensibilidade espacial **não foi repetida** —
  permanece a do piloto de 17 meses, `docs/nmme-fase2c3b-sensibilidade-espacial.md`.
- Nenhum indicador de habilidade preditiva do CFSv2 foi calculado.

## 6. Próximos passos (não executados nesta atividade)

1. Decidir explicitamente se `executar_lote(10)` deve ser chamado de
   novo — a retomada normal já tentaria automaticamente só 2001-08,
   sem necessidade de nenhuma outra intervenção manual.
2. Se o lote 10 for aprovado numa nova tentativa, retomar a sequência
   a partir do lote 11 (2003-01 a 2004-12), mantendo a mesma barreira
   por lote.
3. Só depois de todos os 16 lotes aprovados: validação final dos 365
   meses, estatísticas descritivas de QC, comparação descritiva
   opcional com `data/chirps_1981_2025.csv`/`data/serie_subst.csv`, e
   o relatório consolidado final.

## Restrições respeitadas

- Nenhum dado histórico anterior foi alterado ou perdido (lotes 0-9
  intactos e verificados).
- Nenhuma ausência foi substituída por zero; nenhuma interpolação;
  nenhuma outra versão do CHIRPS usada; pixel de referência inalterado;
  nenhum valor modificado manualmente.
- `reprocessar_ausentes_ou_nodata()` não foi acionado automaticamente.
- Os lotes 11 a 15 não foram iniciados.
- Nenhum indicador de habilidade preditiva do CFSv2 foi calculado.
- SARIMAX, XGBoost, dashboard e dados operacionais não foram tocados.
