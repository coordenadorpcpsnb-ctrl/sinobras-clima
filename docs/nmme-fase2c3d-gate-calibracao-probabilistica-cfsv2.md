# Gate diagnóstico de calibração probabilística — Fase 2C.3D (Método 3.5)

**GATE DIAGNÓSTICO, não implementação. Nenhum EMOS foi ajustado, nenhum membro foi recalibrado, nenhum dressing foi aplicado, nenhum quantile mapping probabilístico foi executado, nenhuma probabilidade operacional nem o dashboard foram alterados. O único objetivo deste documento é responder, com os fatos primeiro, se a dispersão dos 24 membros do CFSv2 contém informação útil sobre a incerteza/erro da previsão — e classificar essa resposta por horizonte, nunca declarar o Método 3.5 aprovado.**

**Revisão sazonal (pós-commit `ad6caf5`):** a revisão independente confirmou auditoria de 24 membros, CRPS/CRPSS, Brier/BSS, bootstrap anual, rank histogram e cobertura, mas apontou que a classificação original (baseada na correlação spread×erro POOLED, todos os meses juntos) podia estar confundida pelo ciclo sazonal forte da precipitação — meses chuvosos têm spread E erro absolutos maiores que meses secos por pura sazonalidade, o que por si só já gera correlação positiva entre spread e erro, mesmo sem nenhuma informação caso a caso. A partir desta revisão, a classificação PRINCIPAL do gate (seção 10) usa a correlação spread×erro CONTROLADA POR MÊS (seção 3.1); a versão pooled é mantida só como referência (seção 3 e 10.1), nunca decisória.

Protegidos e não alterados nesta atividade: CFSv2 RAW, CHIRPS v3 histórico, base pareada da 2C.3C, dashboard, SARIMAX/XGBoost, pipeline operacional, `serie_subst.csv`, e os artefatos já aprovados dos Métodos 3.1/3.2/3.4 e do gate do Método 3.3 — todos só lidos, nunca alterados.

## 1. Unidade de análise e auditoria de 24 membros

1 linha por `(init_date, lead)`; os 24 membros são usados SÓ para estatísticas internas do ensemble (`ensemble_mean`, `ensemble_median`, `ensemble_std` (`ddof=1`), `ensemble_variance`, `ensemble_iqr`, `ensemble_min/max/range`) — NUNCA tratados como 24 anos/observações históricas independentes em nenhum bootstrap deste módulo (todo bootstrap resample `target_ano`, em blocos, nunca membros).

Auditoria de contagem de membros: ✅ todas as linhas têm exatamente 24 membros.

## 2. Spread médio por horizonte e spread-error ratio (itens 1, 2 e 4 do pedido original)

`erro_abs = |ensemble_mean - obs|`, `erro_quadratico = (ensemble_mean - obs)²`, `erro_assinado = ensemble_mean - obs` — SEM qualquer correção de bias (diagnóstico do ensemble RAW). `spread_error_ratio = mean(ensemble_std) / RMSE(ensemble_mean, obs)` — leitura SEMPRE só diagnóstica, nunca prova isolada de calibração. Esses sinais (junto com o rank histogram, seção 4) alimentam o julgamento de "calibração de magnitude" usado na classificação (seção 10).

| Horizonte | N | Spread médio (`ensemble_std`) | RMSE(`ensemble_mean`, obs) | spread_error_ratio | Leitura diagnóstica |
|---|---|---|---|---|---|
| H1 | 240 | 40.12 | 71.81 | 0.559 | muito abaixo de 1 — ensemble potencialmente UNDERdispersive |
| H2 | 240 | 48.94 | 74.80 | 0.654 | muito abaixo de 1 — ensemble potencialmente UNDERdispersive |
| H3 | 240 | 48.74 | 77.33 | 0.630 | muito abaixo de 1 — ensemble potencialmente UNDERdispersive |
| H4 | 240 | 48.59 | 80.92 | 0.601 | muito abaixo de 1 — ensemble potencialmente UNDERdispersive |
| H5 | 240 | 47.86 | 84.93 | 0.564 | muito abaixo de 1 — ensemble potencialmente UNDERdispersive |
| H6 | 240 | 47.21 | 87.15 | 0.542 | muito abaixo de 1 — ensemble potencialmente UNDERdispersive |

## 3. Spread-skill RAW POOLED — diagnóstico bruto, mantido só como referência

`spread_skill_raw_pooled`: Pearson e Spearman entre `ensemble_std` e `erro_abs` (e Pearson entre `ensemble_variance` e `erro_quadratico`), SEM separar por mês — todos os casos de todos os meses juntos. Bootstrap em blocos por `target_ano` (`v.bootstrap_blocos_por_ano`, reaproveitado sem modificação). **Mantido integralmente (mesmos números de sempre), mas NÃO é mais usado para decidir a classificação do gate** — pode estar confundido pelo ciclo sazonal (ver seção 3.1).

| Horizonte | N | Pearson(std, erro_abs) | IC 95% | Spearman(std, erro_abs) | IC 95% | Pearson(variance, erro_quad.) | IC 95% |
|---|---|---|---|---|---|---|---|
| H1 | 240 | 0.290 | [0.166, 0.407] | 0.454 | [0.350, 0.544] | 0.101 | [-0.008, 0.235] |
| H2 | 240 | 0.375 | [0.280, 0.467] | 0.528 | [0.456, 0.592] | 0.212 | [0.084, 0.351] |
| H3 | 240 | 0.436 | [0.360, 0.513] | 0.571 | [0.505, 0.636] | 0.271 | [0.202, 0.373] |
| H4 | 240 | 0.453 | [0.388, 0.528] | 0.578 | [0.511, 0.635] | 0.245 | [0.158, 0.357] |
| H5 | 240 | 0.445 | [0.362, 0.530] | 0.562 | [0.493, 0.634] | 0.290 | [0.154, 0.410] |
| H6 | 240 | 0.484 | [0.407, 0.558] | 0.597 | [0.525, 0.666] | 0.315 | [0.212, 0.412] |

## 3.1. Spread-skill CONTROLADO POR MÊS — análise PRINCIPAL (revisão sazonal, itens 2/3)

`spread_skill_month_controlled_retrospective` — RETROSPECTIVA/DESCRITIVA (a centralização usa a amostra completa de hindcast, nunca operacional). Para cada `lead × target_mes` (as ~20 observações daquele mês), calcula `spread_resid = ensemble_std - média_do_mês`, `erro_abs_resid = erro_abs - média_do_mês`, e equivalente para `ensemble_variance`/`erro_quadratico` — depois correlaciona os RESÍDUOS. Testa se o spread tem informação ALÉM do ciclo sazonal. Bootstrap em blocos por `target_ano`, recalculando as médias mensais DENTRO de cada reamostra (preferência explícita da revisão — reflete toda a transformação, não só a correlação final).

| Horizonte | N | Pearson resid(std, erro_abs) | IC 95% | Classificação | Spearman resid | IC 95% | Classificação |
|---|---|---|---|---|---|---|---|
| H1 | 240 | -0.023 | [-0.204, 0.152] | IC 95% inclui zero (indeterminado) | 0.056 | [-0.147, 0.221] | IC 95% inclui zero (indeterminado) |
| H2 | 240 | 0.155 | [0.043, 0.256] | IC 95% totalmente ACIMA de zero | 0.180 | [0.036, 0.291] | IC 95% totalmente ACIMA de zero |
| H3 | 240 | 0.115 | [-0.037, 0.262] | IC 95% inclui zero (indeterminado) | 0.148 | [-0.018, 0.287] | IC 95% inclui zero (indeterminado) |
| H4 | 240 | 0.011 | [-0.124, 0.149] | IC 95% inclui zero (indeterminado) | 0.031 | [-0.099, 0.182] | IC 95% inclui zero (indeterminado) |
| H5 | 240 | -0.069 | [-0.247, 0.087] | IC 95% inclui zero (indeterminado) | -0.081 | [-0.238, 0.072] | IC 95% inclui zero (indeterminado) |
| H6 | 240 | -0.046 | [-0.188, 0.106] | IC 95% inclui zero (indeterminado) | -0.021 | [-0.192, 0.148] | IC 95% inclui zero (indeterminado) |

### 3.2. Quanto a correlação caiu após o controle sazonal

| Horizonte | Pearson RAW pooled | Pearson residual (controlado por mês) | Queda |
|---|---|---|---|
| H1 | 0.290 | -0.023 | 0.314 |
| H2 | 0.375 | 0.155 | 0.220 |
| H3 | 0.436 | 0.115 | 0.321 |
| H4 | 0.453 | 0.011 | 0.441 |
| H5 | 0.445 | -0.069 | 0.514 |
| H6 | 0.484 | -0.046 | 0.530 |

Queda grande e consistente em quase todos os horizontes confirma que boa parte (ou toda) a correlação pooled vinha do ciclo sazonal comum entre spread e erro, não de informação caso a caso — exatamente a confusão que a revisão apontou como risco.

### 3.3. Coerência mês × lead (revisão sazonal, item 5) — descritivo, nunca 72 testes de significância

Pearson(`ensemble_std`, `erro_abs`) por célula `target_mes × lead`, N≈20 por célula, SEM centralização dentro da própria célula (um único mês não tem o que centralizar). Objetivo: ver se o sinal raw pooled é coerente em muitos meses ou concentrado na diferença seca/chuvosa.

| Mês \ Lead | H1 | H2 | H3 | H4 | H5 | H6 |
|---|---|---|---|---|---|---|
| Jan | -0.32 | -0.24 | 0.43 | 0.31 | -0.34 | 0.14 |
| Fev | -0.05 | 0.23 | 0.56 | -0.33 | 0.10 | -0.18 |
| Mar | 0.43 | 0.49 | -0.11 | 0.10 | 0.25 | 0.02 |
| Abr | -0.14 | 0.25 | 0.25 | -0.15 | -0.19 | -0.23 |
| Mai | 0.62 | 0.13 | 0.15 | 0.10 | -0.13 | -0.23 |
| Jun | 0.07 | 0.08 | 0.64 | -0.09 | -0.14 | 0.06 |
| Jul | 0.22 | -0.10 | -0.16 | 0.50 | 0.24 | -0.12 |
| Ago | 0.21 | -0.06 | 0.40 | 0.18 | -0.08 | 0.30 |
| Set | 0.23 | 0.06 | -0.16 | -0.17 | -0.08 | -0.01 |
| Out | 0.18 | 0.02 | 0.13 | 0.04 | -0.03 | -0.14 |
| Nov | -0.17 | 0.08 | -0.39 | -0.30 | -0.55 | 0.02 |
| Dez | -0.08 | -0.01 | 0.02 | 0.30 | 0.06 | 0.06 |

Sinais de magnitude e direção variáveis mês a mês (ver tabela) — consistente com a interpretação de que o sinal pooled é inflado pela diferença entre meses, não um padrão caso a caso uniformemente presente dentro de cada mês.

## 4. Rank histogram (item 5 do pedido original)

Posição (1..25) da observação entre os 24 membros ordenados. Tie-break **explícito e determinístico** (`_rank_observacao_determinístico`, próprio deste módulo — ver nota de implementação abaixo), nunca o sorteio seedado de `v.rank_observacao` usado em outros pontos da 2C.3C. Diagnóstico derivado, nunca um teste de hipótese formal como critério único: frequência nos ranks extremos (1 e 25 — formato em U sugere underdispersion), frequência central (terço central — concentração sugere overdispersion), e desvio de uniformidade.

> **Nota de implementação (desvio deliberado do reuso literal):** o item 5 do pedido original exige tie-break "explícito e determinístico"; `v.rank_observacao` (2C.3C) resolve empates por sorteio seedado — reprodutível, mas não determinístico no sentido de regra fixa. Por isso este módulo define sua própria `_rank_observacao_determinístico`: sem empate, mesma posição de sempre; com empate, sempre o PONTO MÉDIO do intervalo de posições válidas, arredondado meio-para-cima em caso de 0,5 exato. `crps_amostral` e `categoria_tercil` continuam reaproveitados sem modificação.

| Horizonte | N | Freq. ranks extremos (1 e 25) | Freq. central (terço central) | Desvio de uniformidade | Esperado por rank sob uniformidade |
|---|---|---|---|---|---|
| H1 | 240 | 0.350 | 0.133 | 0.920 | 9.60 |
| H2 | 240 | 0.271 | 0.200 | 0.670 | 9.60 |
| H3 | 240 | 0.267 | 0.183 | 0.592 | 9.60 |
| H4 | 240 | 0.250 | 0.142 | 0.597 | 9.60 |
| H5 | 240 | 0.317 | 0.171 | 0.623 | 9.60 |
| H6 | 240 | 0.296 | 0.146 | 0.690 | 9.60 |

Esperado sob uniformidade perfeita: 2/25 = 0,080 nos ranks extremos combinados. Frequências nos ranks extremos consistentemente acima disso em todos os horizontes (ver tabela) são consistentes com um ensemble RAW **underdispersive** — a observação cai fora da faixa dos 24 membros com frequência maior do que uma dispersão bem calibrada permitiria.

### 4.1. Rank 1 vs. rank 25 separados — bias vs. underdispersion (revisão sazonal, item 9)

O uso conjunto dos ranks extremos (seção 4) detecta falta de cobertura mas não distingue dispersão insuficiente (extremos altos e aproximadamente simétricos) de bias sistemático (forte assimetria entre rank 1 e rank 25) — os dois podem coexistir. `diferenca = freq_rank25 - freq_rank1`.

| Horizonte | Freq. rank 1 | Freq. rank 25 | Diferença (rank25 − rank1) |
|---|---|---|---|
| H1 | 0.004 | 0.346 | 0.342 |
| H2 | 0.029 | 0.242 | 0.212 |
| H3 | 0.037 | 0.229 | 0.192 |
| H4 | 0.067 | 0.183 | 0.117 |
| H5 | 0.079 | 0.237 | 0.158 |
| H6 | 0.108 | 0.188 | 0.079 |

**Forte assimetria em todos os horizontes: freq. rank 25 >> freq. rank 1** (ver tabela) — a observação cai ACIMA de todos os 24 membros com frequência muito maior do que cai abaixo de todos eles. Isso é evidência de um componente de BIAS SISTEMÁTICO (o ensemble RAW subestima a precipitação com mais frequência do que sobrestima), não apenas underdispersion simétrica — os dois componentes coexistem aqui, e a seção 4 isolada não deixava isso visível.

## 5. Cobertura de intervalos empíricos 50/80/90% (item 6 do pedido original)

Intervalos EMPÍRICOS (percentis dos 24 membros RAW, nunca uma distribuição assumida). `coverage_error = cobertura_observada - cobertura_nominal`. **Nenhuma calibração de intervalo aplicada nesta etapa — só diagnóstico.**

| Horizonte | N | Cobertura 50% (nominal 0,50) | erro | Cobertura 80% (nominal 0,80) | erro | Cobertura 90% (nominal 0,90) | erro |
|---|---|---|---|---|---|---|---|
| H1 | 240 | 0.217 | -0.283 | 0.404 | -0.396 | 0.504 | -0.396 |
| H2 | 240 | 0.283 | -0.217 | 0.492 | -0.308 | 0.592 | -0.308 |
| H3 | 240 | 0.263 | -0.237 | 0.492 | -0.308 | 0.617 | -0.283 |
| H4 | 240 | 0.263 | -0.237 | 0.483 | -0.317 | 0.588 | -0.312 |
| H5 | 240 | 0.271 | -0.229 | 0.458 | -0.342 | 0.558 | -0.342 |
| H6 | 240 | 0.258 | -0.242 | 0.450 | -0.350 | 0.596 | -0.304 |

Coverage_error consistentemente NEGATIVO (cobertura observada abaixo da nominal) em todos os horizontes é o mesmo sinal de dispersão insuficiente já visto no spread_error_ratio (seção 2) e no rank histogram (seção 4).

**Nota metodológica (revisão sazonal, item 10):** Cobertura baixa dos membros RAW pode refletir simultaneamente localização/média viesada (bias determinístico, já documentado nos Métodos 3.1/3.2/3.4) e spread insuficiente (underdispersion). Cobertura isolada não identifica qual componente de um eventual EMOS (média ou variância) precisaria ser corrigido — revisão sazonal, item 10.

## 6. CRPS RAW (item 7 do pedido original — NÃO alterado nesta revisão)

Fórmula "fair" (Ferro et al. 2008) reaproveitada sem modificação (`v.crps_amostral`) — nunca uma segunda fórmula paralela. `crps_medio_climatologia` usa a mesma climatologia causal observada já aprovada na 2C.3C como referência DIRETAMENTE comparável. **Valores idênticos ao commit `ad6caf5` — confirmado em teste de regressão automatizado (`tests/test_cfsv2_gate_calibracao_probabilistica.py`).**

| Horizonte | N | CRPS médio (modelo RAW) | CRPS médio (climatologia causal) | CRPSS |
|---|---|---|---|---|
| H1 | 240 | 42.34 | 27.87 | -0.519 |
| H2 | 240 | 41.38 | 27.77 | -0.490 |
| H3 | 240 | 41.55 | 27.94 | -0.487 |
| H4 | 240 | 43.69 | 27.85 | -0.569 |
| H5 | 240 | 46.14 | 27.85 | -0.656 |
| H6 | 240 | 47.28 | 27.69 | -0.707 |

CRPSS negativo em todos os horizontes indica que o ensemble RAW do CFSv2, sem qualquer correção, tem CRPS pior que a climatologia causal observada — achado consistente com o skill interanual determinístico fraco já documentado nos Métodos 3.1/3.2/3.4.

## 7. Brier Score e BSS por tercil (item 8 do pedido original — NÃO alterado nesta revisão)

Categorias de tercil (seco/normal/úmido) e `BS_ref_nominal = mean((1/3 - o_i)^2)` reaproveitados EXATAMENTE da 2C.3C (`v.categoria_tercil`), nunca redefinidos. Probabilidades RAW = fração dos 24 membros em cada categoria. **Valores idênticos ao commit `ad6caf5` — confirmado em teste de regressão.**

| Horizonte | BS seco | BS normal | BS úmido | BSS seco | BSS normal | BSS úmido |
|---|---|---|---|---|---|---|
| H1 | 0.330 | 0.234 | 0.230 | -0.320 | -0.140 | -0.089 |
| H2 | 0.324 | 0.219 | 0.252 | -0.298 | -0.059 | -0.202 |
| H3 | 0.318 | 0.222 | 0.262 | -0.271 | -0.078 | -0.242 |
| H4 | 0.318 | 0.220 | 0.274 | -0.273 | -0.061 | -0.307 |
| H5 | 0.328 | 0.230 | 0.298 | -0.314 | -0.113 | -0.421 |
| H6 | 0.340 | 0.230 | 0.307 | -0.359 | -0.111 | -0.465 |

BSS calculado sempre contra a referência nominal `mean((1/3-o_i)^2)` já corrigida na 2C.3C — nunca a constante 2/9.

## 8. Dependência/diversidade entre membros — raw vs. anomalia mensal (revisão sazonal, itens 7/8)

Correlação de Pearson par-a-par média entre as 24 séries temporais de membro (fora da diagonal). `correlacao_membros_raw` (sobre precipitação bruta) é fortemente contaminada pelo mesmo ciclo sazonal comum a todos os membros — meses chuvosos elevam TODOS os membros juntos. `correlacao_membros_anomalia_mensal` (PRINCIPAL) remove isso: para cada membro, subtrai sua própria média histórica por `target_mes` antes de montar a matriz de correlação.

| Horizonte | N inicializações | N membros | Correlação RAW | Correlação anomalia mensal (principal) | ESS aprox. (raw) | ESS aprox. (principal) |
|---|---|---|---|---|---|---|
| H1 | 240 | 24 | 0.783 | 0.286 | 1.26 | 3.17 |
| H2 | 240 | 24 | 0.773 | 0.100 | 1.28 | 7.29 |
| H3 | 240 | 24 | 0.811 | 0.064 | 1.22 | 9.75 |
| H4 | 240 | 24 | 0.829 | 0.062 | 1.20 | 9.86 |
| H5 | 240 | 24 | 0.840 | 0.070 | 1.18 | 9.22 |
| H6 | 240 | 24 | 0.850 | 0.081 | 1.17 | 8.38 |

**A correlação RAW (~0,77–0,85) cai substancialmente para a anomalia mensal (~0,06–0,29) em todos os horizontes** — confirma que boa parte da aparente "redundância" entre membros era só o ciclo sazonal comum, não falta de diversidade real. O Effective Ensemble Size aproximado sobe de ~1,2 (raw, quase "1 membro efetivo") para valores bem mais plausíveis (3 a 10, dependendo do horizonte) na versão por anomalia mensal.

**Leitura heurística correta (nunca literal):** "a correlação média entre anomalias dos membros implica redundância moderada/baixa segundo esta aproximação" — nunca "o ensemble possui apenas N membros independentes". Nunca usado para expandir a amostra histórica de 240 inicializações.

## 9. Sazonalidade — mês × lead e grupo sazonal × lead, atenção à estação seca (item 10 do pedido original)

Diagnóstico DESCRITIVO (CRPS/CRPSS, não alterados) — nunca 72 testes de significância independentes nem um critério de aprovação célula a célula. Ver seção 3.3 para a matriz equivalente de spread-skill.

### 9.1. N elegível por célula (mês × lead)

| Mês \ Lead | H1 | H2 | H3 | H4 | H5 | H6 |
|---|---|---|---|---|---|---|
| Jan | 20 | 20 | 20 | 20 | 20 | 20 |
| Fev | 20 | 20 | 20 | 20 | 20 | 20 |
| Mar | 20 | 20 | 20 | 20 | 20 | 20 |
| Abr | 20 | 20 | 20 | 20 | 20 | 20 |
| Mai | 20 | 20 | 20 | 20 | 20 | 20 |
| Jun | 20 | 20 | 20 | 20 | 20 | 20 |
| Jul | 20 | 20 | 20 | 20 | 20 | 20 |
| Ago | 20 | 20 | 20 | 20 | 20 | 20 |
| Set | 20 | 20 | 20 | 20 | 20 | 20 |
| Out | 20 | 20 | 20 | 20 | 20 | 20 |
| Nov | 20 | 20 | 20 | 20 | 20 | 20 |
| Dez | 20 | 20 | 20 | 20 | 20 | 20 |

### 9.2. CRPS médio (modelo RAW) por célula (mês × lead)

| Mês \ Lead | H1 | H2 | H3 | H4 | H5 | H6 |
|---|---|---|---|---|---|---|
| Jan | 60.65 | 46.67 | 48.23 | 48.05 | 54.92 | 55.91 |
| Fev | 37.28 | 38.58 | 48.03 | 64.39 | 64.45 | 73.96 |
| Mar | 31.95 | 56.50 | 63.13 | 81.84 | 96.92 | 97.23 |
| Abr | 50.64 | 43.72 | 44.33 | 42.00 | 41.50 | 41.17 |
| Mai | 61.45 | 70.14 | 70.65 | 71.04 | 71.13 | 72.16 |
| Jun | 4.37 | 4.86 | 5.12 | 5.26 | 5.43 | 5.40 |
| Jul | 2.97 | 2.69 | 2.60 | 2.29 | 2.50 | 2.65 |
| Ago | 9.58 | 8.88 | 8.28 | 8.23 | 7.62 | 7.88 |
| Set | 46.59 | 42.45 | 41.86 | 43.84 | 43.00 | 41.32 |
| Out | 80.71 | 74.29 | 67.09 | 68.78 | 70.13 | 69.95 |
| Nov | 81.93 | 69.42 | 61.01 | 55.50 | 52.31 | 49.11 |
| Dez | 39.96 | 38.34 | 38.29 | 33.09 | 43.75 | 50.57 |

### 9.3. Grupos sazonais (chuvosa/transição/seca) × lead

| Grupo | Métrica | H1 | H2 | H3 | H4 | H5 | H6 |
|---|---|---|---|---|---|---|---|
| chuvosa | N | 140 | 140 | 140 | 140 | 140 | 140 |
| chuvosa | CRPS médio (modelo) | 54.73 | 52.50 | 52.87 | 56.24 | 60.57 | 62.56 |
| chuvosa | CRPSS | -0.466 | -0.413 | -0.412 | -0.508 | -0.624 | -0.677 |
| transicao | N | 40 | 40 | 40 | 40 | 40 | 40 |
| transicao | CRPS médio (modelo) | 54.02 | 56.29 | 56.25 | 57.44 | 57.06 | 56.74 |
| transicao | CRPSS | -0.800 | -0.876 | -0.875 | -0.914 | -0.902 | -0.953 |
| seca | N | 60 | 60 | 60 | 60 | 60 | 60 |
| seca | CRPS médio (modelo) | 5.64 | 5.48 | 5.33 | 5.26 | 5.18 | 5.31 |
| seca | CRPSS | -0.287 | -0.250 | -0.217 | -0.201 | -0.183 | -0.212 |

**Atenção especial à estação seca (jun-ago, ver seção 9.3)** — os Métodos 3.2/3.4 já mostraram baixa variabilidade de sinal nesses meses (chuva rara e próxima de zero). O CRPS médio absoluto da estação seca é o menor entre os três grupos simplesmente porque a magnitude da chuva observada é pequena — isso não deve ser lido como "melhor desempenho relativo" sem olhar o CRPSS ao lado do valor absoluto. A mesma cautela sazonal se estende à seção 3 (correlação pooled pode estar misturando este regime de baixa variância com o regime chuvoso de alta variância).

## 10. Classificação PRINCIPAL do gate por horizonte — controlada por mês (revisão sazonal, item 6)

**Nenhum limiar numérico foi escolhido depois de ver o resultado.** 4 rótulos possíveis, cruzando SEMPRE calibração de magnitude (ratio/rank histogram, seções 2/4) com informatividade CONTROLADA POR MÊS (seção 3.1):

- `spread_informativo`: bem calibrado em magnitude E correlação controlada por mês robusta.
- `ensemble_mal_calibrado_mas_potencialmente_calibravel`: mal calibrado em magnitude, MAS a correlação controlada por mês ainda é positiva (IC acima de zero) — spread informativo caso a caso, além do ciclo sazonal.
- `ensemble_mal_calibrado_spread_pouco_informativo` (NOVO): mal calibrado em magnitude E a correlação controlada por mês caiu para perto de zero — ainda pode haver calibração da dispersão MÉDIA, mas o spread caso a caso não demonstra valor como preditor dinâmico.
- `spread_pouco_informativo`: bem calibrado em magnitude, mas sem correlação controlada por mês — nada a corrigir na dispersão, e o spread também não ajuda caso a caso.

| Horizonte | Classificação PRINCIPAL | Pearson resid IC>0? | Spearman resid IC>0? | Ratio moderadamente fora de 1? | Ratio extremo? | Rank histogram sinaliza desvio? |
|---|---|---|---|---|---|---|
| H1 | `ensemble_mal_calibrado_spread_pouco_informativo` | ❌ | ❌ | ✅ | ❌ | ✅ |
| H2 | `ensemble_mal_calibrado_mas_potencialmente_calibravel` | ✅ | ✅ | ✅ | ❌ | ✅ |
| H3 | `ensemble_mal_calibrado_spread_pouco_informativo` | ❌ | ❌ | ✅ | ❌ | ✅ |
| H4 | `ensemble_mal_calibrado_spread_pouco_informativo` | ❌ | ❌ | ✅ | ❌ | ✅ |
| H5 | `ensemble_mal_calibrado_spread_pouco_informativo` | ❌ | ❌ | ✅ | ❌ | ✅ |
| H6 | `ensemble_mal_calibrado_spread_pouco_informativo` | ❌ | ❌ | ✅ | ❌ | ✅ |

- **H1** (`ensemble_mal_calibrado_spread_pouco_informativo`): ensemble mal calibrado em magnitude, E a correlação spread×erro CONTROLADA POR MÊS caiu para perto de zero (IC inclui amplamente zero) — ainda pode haver calibração da dispersão MÉDIA (constante por horizonte/mês), mas o spread caso a caso não demonstra valor como preditor dinâmico de incerteza; não recomendar EMOS com d*spread² a partir deste sinal
- **H2** (`ensemble_mal_calibrado_mas_potencialmente_calibravel`): ensemble mal calibrado em magnitude, MAS a correlação spread×erro CONTROLADA POR MÊS ainda tem IC 95% acima de zero — o spread caso a caso carrega informação além do ciclo sazonal (candidato a EMOS com média e variância, não a descarte)
- **H3** (`ensemble_mal_calibrado_spread_pouco_informativo`): ensemble mal calibrado em magnitude, E a correlação spread×erro CONTROLADA POR MÊS caiu para perto de zero (IC inclui amplamente zero) — ainda pode haver calibração da dispersão MÉDIA (constante por horizonte/mês), mas o spread caso a caso não demonstra valor como preditor dinâmico de incerteza; não recomendar EMOS com d*spread² a partir deste sinal
- **H4** (`ensemble_mal_calibrado_spread_pouco_informativo`): ensemble mal calibrado em magnitude, E a correlação spread×erro CONTROLADA POR MÊS caiu para perto de zero (IC inclui amplamente zero) — ainda pode haver calibração da dispersão MÉDIA (constante por horizonte/mês), mas o spread caso a caso não demonstra valor como preditor dinâmico de incerteza; não recomendar EMOS com d*spread² a partir deste sinal
- **H5** (`ensemble_mal_calibrado_spread_pouco_informativo`): ensemble mal calibrado em magnitude, E a correlação spread×erro CONTROLADA POR MÊS caiu para perto de zero (IC inclui amplamente zero) — ainda pode haver calibração da dispersão MÉDIA (constante por horizonte/mês), mas o spread caso a caso não demonstra valor como preditor dinâmico de incerteza; não recomendar EMOS com d*spread² a partir deste sinal
- **H6** (`ensemble_mal_calibrado_spread_pouco_informativo`): ensemble mal calibrado em magnitude, E a correlação spread×erro CONTROLADA POR MÊS caiu para perto de zero (IC inclui amplamente zero) — ainda pode haver calibração da dispersão MÉDIA (constante por horizonte/mês), mas o spread caso a caso não demonstra valor como preditor dinâmico de incerteza; não recomendar EMOS com d*spread² a partir deste sinal

### 10.1. Classificação de REFERÊNCIA apenas — baseada no pooled (NÃO decisória)

Mantida só para comparação/transparência ("não apagar métricas atuais") — mostra como a classificação teria saído sem controlar por mês. Note a diferença em relação à tabela principal acima.

| Horizonte | Classificação (referência, pooled) |
|---|---|
| H1 | `ensemble_mal_calibrado_mas_potencialmente_calibravel` |
| H2 | `ensemble_mal_calibrado_mas_potencialmente_calibravel` |
| H3 | `ensemble_mal_calibrado_mas_potencialmente_calibravel` |
| H4 | `ensemble_mal_calibrado_mas_potencialmente_calibravel` |
| H5 | `ensemble_mal_calibrado_mas_potencialmente_calibravel` |
| H6 | `ensemble_mal_calibrado_mas_potencialmente_calibravel` |

## 11. Síntese do gate e próximo passo recomendado (itens 11, 12 e 13 do pedido original; item 12 da revisão sazonal)

**Síntese:** resultado MISTO entre horizontes (classificação controlada por mês) — ver classificação por horizonte antes de qualquer decisão única; nenhuma média ou voto majoritário decide por si só.

**Próximo passo recomendado:** `resultado_misto_revisar_por_horizonte_antes_de_decidir`

**O que NÃO foi feito nesta atividade — confirmação explícita:**

- Nenhum EMOS ajustado: ✅ confirmado
- Nenhum dressing aplicado: ✅ confirmado
- Nenhuma probabilidade operacional alterada: ✅ confirmado
- Nenhum quantile mapping probabilístico executado.
- Nenhuma mudança no dashboard, SARIMAX, XGBoost ou pipeline operacional.
- O Método 3.5 **não** foi declarado aprovado nesta atividade — este documento é um gate diagnóstico, não uma aprovação.

## 12. Limitações

- `effective_ensemble_size_aprox` (seção 8) é uma aproximação HEURÍSTICA de redundância, nunca usada para reponderar nenhuma métrica deste relatório nem para expandir a amostra histórica.
- A matriz mês × lead e os grupos sazonais (seções 3.3 e 9) têm amostra pequena por célula — usados só como diagnóstico, nunca como critério de aprovação célula a célula nem como 72 testes de significância.
- O tie-break determinístico do rank histogram (seção 4) é uma convenção explícita (ponto médio do intervalo de posições válidas), não a única convenção possível na literatura.
- Este gate avalia o ensemble RAW; nenhuma correção de bias determinístico (Métodos 3.1/3.2/3.4) foi combinada com a dispersão aqui.
- **Checagem por regressão partial/`C(target_mes) + ensemble_std` (item 4 da revisão) não foi implementada como modelo separado** — pelo teorema de Frisch-Waugh-Lovell, o coeficiente de uma regressão OLS de `erro_abs` sobre dummies de `target_mes` e `ensemble_std` é algebricamente idêntico ao coeficiente de regredir os RESÍDUOS centrados por mês de `erro_abs` sobre os RESÍDUOS centrados por mês de `ensemble_std` — exatamente a transformação já feita na seção 3.1. Implementar a regressão categórica separadamente duplicaria a mesma informação (e uma segunda biblioteca estatística) sem mudar a conclusão sobre sinal/magnitude do efeito — optou-se pela isenção de segunda implementação explicitamente permitida pelo pedido de revisão (item 4: "se preferir evitar uma segunda implementação estatística, a análise residualizada da seção 2 é suficiente").

## 13. Conclusão restrita ao gate do Método 3.5

Esta conclusão vale SOMENTE para o diagnóstico de dispersão do ensemble CFSv2 RAW — nunca generalizada para "calibração do CFSv2" em geral, e nunca uma aprovação do Método 3.5.

- Classificação PRINCIPAL por horizonte (controlada por mês): H1: `ensemble_mal_calibrado_spread_pouco_informativo`; H2: `ensemble_mal_calibrado_mas_potencialmente_calibravel`; H3: `ensemble_mal_calibrado_spread_pouco_informativo`; H4: `ensemble_mal_calibrado_spread_pouco_informativo`; H5: `ensemble_mal_calibrado_spread_pouco_informativo`; H6: `ensemble_mal_calibrado_spread_pouco_informativo`.
- resultado MISTO entre horizontes (classificação controlada por mês) — ver classificação por horizonte antes de qualquer decisão única; nenhuma média ou voto majoritário decide por si só.
- A correlação spread×erro pooled (seção 3) caiu substancialmente após controlar por mês (seção 3.1/3.2) na maioria dos horizontes — confirma que o ciclo sazonal era, de fato, um confundidor relevante, como apontado na revisão independente.
- Decisão de implementar (ou não) um protocolo de calibração probabilística — EMOS ou equivalente parcimonioso — permanece de uma próxima etapa, condicionada à revisão independente deste resultado, nunca decidida automaticamente por este gate.
