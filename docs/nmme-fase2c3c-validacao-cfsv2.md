# Validação científica retrospectiva do CFSv2 — Fase 2C.3C

**Relatório técnico — completamente separado do sistema operacional. Nenhuma métrica aqui é apresentada no dashboard de produção. Referência observacional exclusiva: `data/chirps_v3_historico/chirps_v3_1981_2011.csv` (365 meses, Fase 2C.3B) — `data/serie_subst.csv` e `data/chirps_1981_2025.csv` NÃO foram usados como referência principal em nenhum cálculo.**

## 1. Auditoria da base RAW (antes de qualquer métrica)

- Registros RAW: 34560 (esperado 34560).
- Inicializações distintas: 240 (esperado 240, jan/1991 a dez/2010).
- Unicidade (init_date × lead × member): ✅.
- Exatamente 24 membros por (init_date, lead): ✅.
- target_month corresponde a init_date+(lead-1) — **validado, nunca reconstruído**: ✅.
- H1 = mês corrente (target_month == init_date): ✅.
- Sem valores faltantes nas colunas essenciais: ✅.
- Unidades (mm/day convertido para mm/mês, conversão registrada): ✅.
- Localização única (Fazendas_Sinobras_Centroide, nunca misturada com São Bento): ✅.
- Meses-alvo distintos cobertos: 245.
- **Auditoria APROVADA.**

## 2. Base pareada CFSv2 × CHIRPS v3

- 34560 registros pareados (um por init_date×target_month×lead×member), 245 meses-alvo distintos.
- Pareamento exclusivo por `target_month` exato — nenhuma observação de `serie_subst.csv`/`chirps_1981_2025.csv` foi usada como referência principal.
- Nenhum mês-alvo ausente (validado antes de qualquer métrica).

## 3. Métricas determinísticas por horizonte (média dos 24 membros)

H1 é a previsão do **mês corrente** — tratado separadamente, nunca agregado com H2-H6 (horizontes futuros) numa métrica única.

| Horizonte | N | Bias (abs, mm) | MAE (abs, mm) | RMSE (abs, mm) | Corr (abs) | Corr (anomalia) | RMSESS (abs) | RMSESS (anomalia) |
|---|---|---|---|---|---|---|---|---|
| H1 | 240 | -37.83 | 52.47 | 71.81 | 0.833 | 0.409 | -0.225 | -0.225 |
| H2 | 240 | -17.27 | 54.05 | 74.80 | 0.801 | 0.170 | -0.278 | -0.278 |
| H3 | 240 | -5.72 | 55.74 | 77.33 | 0.811 | 0.139 | -0.316 | -0.316 |
| H4 | 240 | 0.70 | 59.52 | 80.92 | 0.811 | 0.134 | -0.379 | -0.379 |
| H5 | 240 | 5.83 | 61.60 | 84.93 | 0.808 | 0.105 | -0.447 | -0.447 |
| H6 | 240 | 7.85 | 63.38 | 87.15 | 0.807 | 0.096 | -0.491 | -0.491 |

**Fórmula do skill score:** `RMSESS = 1 - RMSE_modelo / RMSE_climatologia` — positivo significa que o modelo erra MENOS que a climatologia expansível (benchmark, calculada sem leakage); negativo significa que a climatologia sozinha seria uma previsão melhor. **Nenhum valor aqui deve ser lido como 'bom' ou 'mau' isoladamente** — ver a seção 7 (intervalos de confiança) antes de qualquer conclusão.

**Nota sobre bias/MAE/RMSE/RMSESS 'absoluto' vs. 'anomalia' serem numericamente idênticos na tabela:** isso é esperado, não um erro de cópia. Subtrair a mesma climatologia da previsão e da observação não muda a DIFERENÇA entre elas (erro = previsto-observado é invariante a essa translação) — por isso bias/MAE/RMSE e o RMSESS derivado deles são idênticos nas duas colunas. A métrica que realmente muda — e que importa aqui — é a **correlação**, porque ela depende da variância de cada série: a climatologia (o ciclo sazonal) infla a correlação 'absoluta' artificialmente, e só desaparece quando as duas são expressas como anomalia.

A correlação cai fortemente da precipitação absoluta para a anomalia em todos os horizontes — esperado: parte da correlação absoluta é só o ciclo sazonal (out-abr chuvoso, jun-ago seco) que tanto o modelo quanto a climatologia capturam trivialmente. A correlação em anomalia é a medida mais honesta da habilidade real de prever o DESVIO em relação ao esperado para aquele mês.

## 4. Avaliação por mês do ano (Seção 10 — nunca escondida numa média anual)

| Mês | Grupo sazonal | N | Bias | MAE | RMSE | Corr |
|---|---|---|---|---|---|---|
| Jan | chuvosa | 120 | 30.34 | 77.88 | 93.34 | 0.107 |
| Fev | chuvosa | 120 | 61.73 | 81.92 | 98.51 | 0.270 |
| Mar | chuvosa | 120 | 85.63 | 106.68 | 123.48 | 0.183 |
| Abr | chuvosa | 120 | -8.40 | 62.04 | 81.07 | 0.258 |
| Mai | transicao | 120 | -78.15 | 78.25 | 98.58 | 0.312 |
| Jun | seca | 120 | -4.91 | 5.64 | 10.41 | 0.222 |
| Jul | seca | 120 | -2.43 | 2.70 | 5.57 | 0.099 |
| Ago | seca | 120 | -8.47 | 8.96 | 15.68 | 0.157 |
| Set | transicao | 120 | -45.78 | 45.79 | 56.82 | 0.136 |
| Out | chuvosa | 120 | -81.91 | 81.91 | 87.71 | 0.267 |
| Nov | chuvosa | 120 | -78.95 | 80.60 | 96.39 | 0.338 |
| Dez | chuvosa | 120 | 38.42 | 61.17 | 75.00 | -0.127 |

**Por grupo sazonal regional (CLAUDE.md):**

| Grupo | N | Bias | MAE | RMSE | Corr |
|---|---|---|---|---|---|
| chuvosa | 840 | 6.69 | 78.89 | 94.75 | 0.563 |
| transicao | 240 | -61.96 | 62.02 | 80.46 | 0.515 |
| seca | 360 | -5.27 | 5.77 | 11.33 | 0.203 |

## 5. Avaliação probabilística (24 membros)

CRPS calculado com a fórmula "fair" (Ferro et al. 2008), não-viesada para ensemble finito. CRPSS compara contra a climatologia probabilística (conjunto dos anos históricos elegíveis, sem leakage). Tercis calculados exclusivamente com o histórico permitido antes de cada inicialização — nunca com 1981-2011 completo.

| Horizonte | N | CRPS modelo | CRPS climatologia | CRPSS | BS seco | BS normal | BS úmido | BSS seco | BSS normal | BSS úmido |
|---|---|---|---|---|---|---|---|---|---|---|
| H1 | 240 | 42.34 | 27.87 | -0.519 | 0.3301 | 0.2344 | 0.2298 | -0.485 | -0.055 | -0.034 |
| H2 | 240 | 41.38 | 27.77 | -0.490 | 0.3244 | 0.2192 | 0.2520 | -0.460 | 0.014 | -0.134 |
| H3 | 240 | 41.55 | 27.94 | -0.487 | 0.3178 | 0.2216 | 0.2622 | -0.430 | 0.003 | -0.180 |
| H4 | 240 | 43.69 | 27.85 | -0.569 | 0.3183 | 0.2196 | 0.2740 | -0.433 | 0.012 | -0.233 |
| H5 | 240 | 46.14 | 27.85 | -0.656 | 0.3284 | 0.2303 | 0.2980 | -0.478 | -0.036 | -0.341 |
| H6 | 240 | 47.28 | 27.69 | -0.707 | 0.3398 | 0.2299 | 0.3071 | -0.529 | -0.035 | -0.382 |

**Fórmulas:** `CRPSS = 1 - CRPS_modelo / CRPS_climatologia_probabilistica` — `BSS = 1 - BS_modelo / BS_referencia_climatologica (p=1/3, BS_ref=2/9)`.

### Rank histogram (posição da observação entre os 24 membros ordenados, 1-25)

- H1: 1:1, 3:4, 4:3, 5:4, 6:1, 7:3, 8:4, 9:1, 10:3, 11:2, 12:8, 13:3, 14:3, 15:9, 16:3, 17:6, 18:9, 19:5, 20:11, 21:12, 22:11, 23:18, 24:33, 25:83
- H2: 1:7, 2:6, 3:2, 4:5, 5:3, 6:5, 7:2, 8:6, 9:5, 10:2, 11:7, 12:8, 13:4, 14:7, 15:7, 16:8, 17:6, 18:5, 19:7, 20:10, 21:13, 22:14, 23:22, 24:21, 25:58
- H3: 1:9, 2:7, 3:7, 4:3, 5:5, 6:7, 7:7, 8:7, 9:2, 10:4, 11:7, 12:7, 13:5, 14:5, 15:7, 16:7, 17:6, 18:3, 19:8, 20:8, 21:12, 22:15, 23:17, 24:20, 25:55
- H4: 1:16, 2:11, 3:4, 4:8, 5:9, 6:1, 7:5, 8:7, 9:1, 10:4, 11:7, 12:8, 13:5, 14:3, 15:5, 16:1, 17:7, 18:11, 19:11, 20:7, 21:10, 22:14, 23:15, 24:26, 25:44
- H5: 1:19, 2:11, 3:7, 4:7, 5:5, 6:3, 7:1, 8:6, 9:8, 10:7, 11:4, 12:3, 13:4, 14:2, 15:6, 16:7, 17:11, 18:6, 19:8, 20:5, 21:13, 22:9, 23:15, 24:16, 25:57
- H6: 1:26, 2:7, 3:8, 4:5, 5:1, 6:4, 7:8, 8:7, 9:6, 10:3, 11:1, 12:5, 13:5, 14:4, 15:3, 16:8, 17:6, 18:6, 19:14, 20:3, 21:12, 22:15, 23:21, 24:17, 25:45

## 6. Intervalos de confiança (bootstrap em blocos por ano, nunca linhas independentes)

O mesmo `target_month` aparece em vários horizontes/inicializações — as observações NÃO são independentes. O IC 95% usa reamostragem em blocos por ANO do target_month (nunca bootstrap de linhas soltas, que subestimaria a incerteza real).

| Horizonte | RMSE | IC 95% | MAE | IC 95% | Bias | IC 95% |
|---|---|---|---|---|---|---|
| H1 | 71.81 | [65.12, 78.34] | 52.47 | [48.27, 56.60] | -37.83 | [-44.04, -30.92] |
| H2 | 74.80 | [68.08, 80.79] | 54.05 | [49.48, 58.33] | -17.27 | [-23.78, -11.02] |
| H3 | 77.33 | [68.13, 86.60] | 55.74 | [49.15, 63.05] | -5.72 | [-9.66, -1.47] |
| H4 | 80.92 | [73.04, 88.89] | 59.52 | [53.82, 65.56] | 0.70 | [-3.17, 4.49] |
| H5 | 84.93 | [76.67, 93.53] | 61.60 | [55.58, 68.17] | 5.83 | [1.67, 10.40] |
| H6 | 87.15 | [78.33, 95.88] | 63.38 | [56.85, 70.62] | 7.85 | [4.10, 11.83] |

## 7. LOYO retrospectivo (complementar — NUNCA misturado com a simulação operacional)

**Rótulo: `loyo_retrospective`.** NÃO simula uso em tempo real — usa anos futuros na climatologia. Análise complementar apenas, nunca misturada com expanding_operational_simulation.

| Horizonte | N | RMSESS (abs) |
|---|---|---|
| H1 | 240 | -0.260 |
| H2 | 240 | -0.317 |
| H3 | 240 | -0.356 |
| H4 | 240 | -0.426 |
| H5 | 240 | -0.496 |
| H6 | 240 | -0.537 |

## 8. Interpretação — separada por tipo de desempenho, nunca uma conclusão única

Esta seção separa deliberadamente quatro desempenhos DIFERENTES — nunca resumidos numa frase como "modelo validado" ou "boa habilidade":

1. **Desempenho absoluto** — correlação alta (0.80-0.83) em todos os horizontes, mas dominada pelo ciclo sazonal regional (chuva concentrada out-abr).
2. **Desempenho em anomalias** — correlação cai para a faixa 0.10-0.41 e diminui com o horizonte — a habilidade real de prever o desvio em relação ao esperado para aquele mês é MODESTA e decai com o lead time, como esperado fisicamente.
3. **Desempenho relativo à climatologia (RMSESS/CRPSS)** — NEGATIVO em todos os horizontes testados, tanto na simulação operacional expansível quanto no LOYO retrospectivo — a climatologia expansível sem leakage teve erro MENOR que o ensemble bruto (não corrigido por viés) do CFSv2 neste ponto único, nesta amostra. Isso NÃO significa que o CFSv2 é inútil — o ensemble aqui usado é bruto (forecast_prec_mm sem qualquer correção de viés ou downscaling), e o benchmark é uma climatologia já bem ajustada aos próprios dados observados.
4. **Desempenho probabilístico** — CRPSS e BSS também predominantemente negativos, consistente com os itens 2-3: o ensemble bruto discrimina mal as categorias de tercil neste ponto.

**Nenhuma dessas quatro leituras, isoladamente, autoriza uma conclusão geral de habilidade.** Qualquer decisão sobre uso operacional do CFSv2 deve revisar conjuntamente: magnitude do skill, intervalo de confiança (seção 6), horizonte, época do ano (seção 4) e tamanho da amostra (N=240 inicializações, mas com dependência temporal relevante — daí o bootstrap em blocos).

## Restrições respeitadas

- Dashboard, SARIMAX, XGBoost, pipeline operacional, série de produção e dados RAW do CFSv2 não foram alterados.
- Nenhuma métrica desta fase é apresentada automaticamente no dashboard de produção.
- `serie_subst.csv`/`chirps_1981_2025.csv` não foram usados como referência principal em nenhum cálculo.
- Testes de controle de leakage (climatologia, tercis, pareamento, mistura de membros, demonstração sintética) executados e aprovados antes do cálculo das métricas — ver `tests/test_cfsv2_validacao_cientifica.py`.
