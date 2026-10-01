# Reconstrução histórica CHIRPS v3.0 — relatório consolidado final (Fase 2C.3B)

**Relatório técnico — não substitui dados operacionais, não calcula
skill do CFSv2, não altera SARIMAX/XGBoost/dashboard/previsões
históricas do CFSv2.**

## 1. Resultado final

**Os 16 lotes (0 a 15) estão APROVADOS. A série completa de
1981-01 a 2011-05 (365 meses) está APROVADA com cobertura temporal
completa: 365/365 meses com valor científico válido (`ok`/`zero_real`).**

| Lote | Período | Meses | Status |
|---|---|---|---|
| 0 | 1981-01 a 1982-12 | 24 | ✅ APROVADO (já estava, preservado — não repetido) |
| 1 | 1983-01 a 1984-12 | 24 | ✅ APROVADO — 24/24 válidos |
| 2 | 1985-01 a 1986-12 | 24 | ✅ APROVADO — 24/24 válidos |
| 3 | 1987-01 a 1988-12 | 24 | ✅ APROVADO — 24/24 válidos |
| 4 | 1989-01 a 1990-12 | 24 | ✅ APROVADO — 24/24 válidos |
| 5 | 1991-01 a 1992-12 | 24 | ✅ APROVADO — 24/24 válidos |
| 6 | 1993-01 a 1994-12 | 24 | ✅ APROVADO — 24/24 válidos |
| 7 | 1995-01 a 1996-12 | 24 | ✅ APROVADO — 24/24 válidos |
| 8 | 1997-01 a 1998-12 | 24 | ✅ APROVADO — 24/24 válidos |
| 9 | 1999-01 a 2000-12 | 24 | ✅ APROVADO — 24/24 válidos |
| 10 | 2001-01 a 2002-12 | 24 | ✅ APROVADO — 24/24 válidos (ver histórico da falha, seção 2) |
| 11 | 2003-01 a 2004-12 | 24 | ✅ APROVADO — 24/24 válidos |
| 12 | 2005-01 a 2006-12 | 24 | ✅ APROVADO — 24/24 válidos |
| 13 | 2007-01 a 2008-12 | 24 | ✅ APROVADO — 24/24 válidos |
| 14 | 2009-01 a 2010-12 | 24 | ✅ APROVADO — 24/24 válidos |
| 15 | 2011-01 a 2011-05 | 5 | ✅ APROVADO — 5/5 válidos |
| **Total** | **1981-01 a 2011-05** | **365** | **✅ 365/365 válidos** |

## 2. Histórico da falha original de 2001-08 e sua resolução

Numa execução anterior desta mesma atividade, o lote 10 (2001-01 a
2002-12) foi avaliado com **23/24 meses válidos** — o mês **2001-08**
teve status `erro_verificacao_disponibilidade`, motivo `erro_rede:
<urlopen error [Errno 104] Connection reset by peer>`, já após 3
tentativas internas esgotadas
(`identificacao_arquivo__tentativas_esgotadas=3`). Classificação:
falha de rede transitória (classe 3 da classificação exaustiva de
`scripts/chirps_v3_piloto.py`) — **não** `mes_ausente`, **não**
NoData, **não** problema metodológico. A execução foi interrompida
imediatamente (STOP-ON-FAILURE), os lotes 11-15 não foram iniciados, e
nenhuma ação corretiva automática foi tomada.

Após revisão e autorização explícita, a **retomada NORMAL** do lote 10
foi executada (não `reprocessar_ausentes_ou_nodata()` — essa falha não
é do tipo que esse mecanismo trata). Antes da retentativa, confirmado
programaticamente que `meses_pendentes_lote(10)` continha
exclusivamente `[(2001, 8)]` — os outros 23 meses já válidos do lote
10 **não** foram reextraídos. A retentativa resolveu o mês:

| | Antes | Depois |
|---|---|---|
| status | `erro_verificacao_disponibilidade` | `ok` |
| valor_mm | — (nenhum) | 7,2041 mm |
| motivo do erro | `erro_rede: Connection reset by peer` | — (nenhum) |
| tentativas HTTP esgotadas | 3 | — (não se aplica, sucesso) |

O mês 2001-08 obteve um valor científico válido (7,20 mm — agosto é
mês seco na região, valor plausível) na primeira nova tentativa. A
falha original foi confirmada como **transitória do lado do servidor
CHC** — não recorreu, não mudou de natureza, não indicou nenhum
problema com a metodologia, o pixel de referência ou a versão do
CHIRPS.

Com o lote 10 aprovado (24/24) e a integridade do arquivo acumulado
verificada, a execução **continuou automaticamente** pelos lotes 11 a
15, cada um como barreira independente (só avançava para o próximo
quando o anterior tinha cobertura temporal completa) — todos aprovados
sem nenhuma outra falha.

## 3. Validação da série completa (365 meses)

Verificado programaticamente sobre
`data/chirps_v3_historico/chirps_v3_1981_2011.csv`:

- **365 registros únicos** (1 por par ano-mês, sem duplicatas).
- **Sequência mensal contínua**, sem lacunas — cobre exatamente
  1981-01 a 2011-05, nenhum mês fora do período esperado.
- **Primeiro registro: janeiro/1981.** **Último registro: maio/2011.**
- **Nenhum mês ausente, nenhum NoData, nenhum status inválido** — o
  conjunto de status distintos na série inteira é exatamente
  `{ok, zero_real}`.
- **Grade e localização espacial consistentes em toda a série**: o
  mesmo pixel (`row=1355, col=2640`), a mesma resolução real usada
  (`0,05°` em lon e lat) e `verificacao_grade__grade_ok=True` em
  todas as 365 linhas.
- **Lotes 0-9 (240 meses, 1981-01 a 2000-12) verificados coluna a
  coluna contra o commit anterior (`6255738`): zero diferenças
  semânticas** — nenhum valor já aprovado foi alterado pela execução
  dos lotes posteriores.

`avaliar_qualidade_reconstrucao()` (reusa
`scripts/chirps_v3_piloto.py::avaliar_qualidade_piloto`) sobre o
período completo confirma: `aprovado=True`,
`cobertura_temporal_completa=True`, 365/365 meses com valor válido, 0
ausentes, 0 NoData, 0 falhas.

## 4. Estatísticas descritivas de QC (controle de qualidade da
   referência observacional — NÃO skill do CFSv2)

**Estatísticas gerais (365 meses, mm/mês):**

| Estatística | Valor |
|---|---|
| Mínimo | 0,0 mm (mai/1983) |
| Máximo | 525,61 mm (jan/1985) |
| Média | 138,71 mm |
| Mediana | 140,50 mm |
| Desvio-padrão | 113,36 mm |

**Média por mês do ano (climatologia observacional 1981-2011, todos os
meses completos, n=30 ou 31):**

| Mês | Média (mm) | Mês | Média (mm) |
|---|---|---|---|
| Jan | 269,51 | Jul | 4,53 |
| Fev | 227,12 | Ago | 12,16 |
| Mar | 266,44 | Set | 58,72 |
| Abr | 205,99 | Out | 126,41 |
| Mai | 86,04 | Nov | 190,56 |
| Jun | 7,39 | Dez | 197,57 |

Padrão sazonal coerente com a climatologia de referência do projeto
(CLAUDE.md, `CLIM_JAN_DEZ`): chuva concentrada out-abr, estação seca
bem marcada jun-ago. Soma das médias mensais: **1.652,4 mm/ano**.

**Totais anuais, anos completos (1981-2010, jan-dez):** variam de
1.242,4 mm (2010) a 2.552,1 mm (1985) — valores individuais completos
disponíveis em `data/chirps_v3_historico/chirps_v3_1981_2011.csv`.
2011 é parcial (só jan-mai, 1.154,1 mm) — **não** é comparável a um
ano completo.

## 5. Comparação descritiva (opcional — executada, 365/365 aprovados)

Comparação **estritamente descritiva** com as duas referências
existentes, para o período comum (365 meses, 1981-01 a 2011-05).
**`data/chirps_1981_2025.csv` NÃO é identificado como "CHIRPS v2
confirmado"** — a versão do CHIRPS usada por aquele pipeline nunca foi
registrada. Nenhuma métrica de habilidade preditiva do CFSv2 foi
calculada nesta seção.

### 5.1 CHIRPS v3 (novo) vs. CHIRPS histórico existente (`data/chirps_1981_2025.csv`)

| Métrica | Valor |
|---|---|
| Diferença média COM SINAL (v3 − existente) | −5,56 mm |
| Diferença ABSOLUTA média (MAE) | 15,78 mm |
| Correlação (Pearson) | 0,9832 |

Diferença média por mês do ano (sinal / absoluta, mm):

| Mês | Sinal | Absoluta | Mês | Sinal | Absoluta |
|---|---|---|---|---|---|
| Jan | +5,79 | 12,40 | Jul | +2,76 | 3,44 |
| Fev | −22,96 | 25,37 | Ago | +3,34 | 4,65 |
| Mar | −5,95 | 20,83 | Set | +8,46 | 10,84 |
| Abr | −10,64 | 15,96 | Out | −13,72 | 15,54 |
| Mai | +15,78 | 17,20 | Nov | +3,49 | 8,32 |
| Jun | −5,74 | 6,69 | Dez | −47,70 | 47,70 |

Por período: 1981-1995 (sinal −5,25 mm, MAE 18,55 mm, corr. 0,9786,
n=180); 1996-2011 (sinal −5,87 mm, MAE 13,09 mm, corr. 0,9884, n=185).
Dezembro concentra o maior viés absoluto — coerente com CLAUDE.md
armadilha 7 (viés de fonte mais forte em out-nov-dez nesta região).

### 5.2 CHIRPS v3 (novo) vs. série de produção (`data/serie_subst.csv`)

| Métrica | Valor |
|---|---|
| Diferença média COM SINAL (v3 − produção) | −5,88 mm |
| Diferença ABSOLUTA média (MAE) | 30,66 mm |
| Correlação (Pearson) | 0,9272 |

Diferença média por mês do ano (sinal / absoluta, mm):

| Mês | Sinal | Absoluta | Mês | Sinal | Absoluta |
|---|---|---|---|---|---|
| Jan | +4,71 | 44,94 | Jul | −2,83 | 4,89 |
| Fev | −46,26 | 56,50 | Ago | +0,02 | 6,73 |
| Mar | −37,70 | 60,93 | Set | +10,82 | 19,16 |
| Abr | −17,49 | 37,49 | Out | +4,42 | 24,48 |
| Mai | −0,89 | 22,61 | Nov | +35,64 | 43,98 |
| Jun | −9,14 | 9,41 | Dez | −9,62 | 34,52 |

Por período: 1981-1995 (sinal −0,67 mm, MAE 25,48 mm, corr. 0,9517,
n=180); 1996-2011 (sinal −10,95 mm, MAE 35,70 mm, corr. 0,9147, n=185).
Correlação e MAE piores que contra o CHIRPS existente — esperado, já
que `serie_subst.csv` combina procedência pré-1996 não comprovada com
estimativas CHIRPS ZONAIS por fazenda pós-1996 (metodologia zonal vs.
ponto, diferente por desenho).

**Esta comparação é puramente descritiva — não valida nem invalida o
CFSv2, não calcula skill, e não trata nenhuma das duas referências
existentes como "verdade absoluta".**

## 6. Metodologia e integridade — confirmação

- CHIRPS v3.0 Final mensal, ponto único no pixel de referência
  `CHIRPS_v3_ponto_centroide` (`row=1355, col=2640`, resolução real
  0,05°) — idêntico em toda a série de 365 meses.
- `scripts/_chirps_v3.py` **não foi alterado** em nenhum momento desta
  atividade (nem na execução original dos lotes 1-9, nem no
  STOP-ON-FAILURE do lote 10, nem na retomada).
- Mesma separação entre zero real e ausência
  (`classificar_valor`), mesmas verificações de CRS/resolução/
  origem/dimensões (`verificar_grade`) em todos os 365 meses.
- A análise de sensibilidade espacial **não foi repetida** —
  permanece a do piloto de 17 meses
  (`docs/nmme-fase2c3b-sensibilidade-espacial.md`).
- **Nenhum indicador de habilidade preditiva do CFSv2 foi calculado**
  em nenhuma etapa desta atividade — nem na validação do QC, nem na
  comparação descritiva da seção 5.

## Restrições respeitadas

- Os lotes 0-9 não foram repetidos — só o mês pendente do lote 10
  (2001-08) foi reextraído, via retomada normal.
- Nenhuma ausência foi substituída por zero; nenhuma interpolação;
  nenhuma outra versão do CHIRPS usada; pixel de referência
  inalterado; nenhum valor modificado manualmente.
- `reprocessar_ausentes_ou_nodata()` não foi acionado em nenhum
  momento — a falha de 2001-08 nunca foi `mes_ausente`/NoData.
- Nenhum indicador de habilidade preditiva do CFSv2 foi calculado.
- SARIMAX, XGBoost, dashboard e dados operacionais não foram tocados.
