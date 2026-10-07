# MOS linear causal no espaço de anomalias — Fase 2C.3D (Método 3.4)

**Relatório técnico — avaliação OFFLINE e científica, completamente separada do sistema operacional. Nenhuma correção foi aplicada ao dashboard, SARIMAX, XGBoost, pipeline operacional, `serie_subst.csv`, CFSv2 RAW, CHIRPS v3 histórico, à base pareada da 2C.3C, nem aos artefatos já aprovados dos Métodos 3.1/3.2 e do gate do Método 3.3 — todos só lidos, nunca alterados.**

## 1. Metodologia

```
anom_modelo_raw = forecast_raw - climatologia_modelo_raw
anom_observada  = observacao   - climatologia_observada
anom_observada  = alpha_lead + beta_lead * anom_modelo_raw + erro   (OLS, por lead)
forecast_mos    = climatologia_observada + alpha_lead + beta_lead * anom_modelo_raw
```

Apenas 2 parâmetros por horizonte (`alpha_lead`, `beta_lead`) — sem mês-dummy, interação, ENSO, tendência, termo quadrático, regularização ou seleção automática nesta primeira versão. Treino por `lead`, agregando TODOS os meses (pooling entre meses deliberado — nunca entre leads).

## 2. Pares válidos e warm-up

`N_TREINO_MINIMO_MOS = 120` **pares de anomalias válidas** (nunca inicializações simplesmente contadas) — uma linha só conta se `forecast_raw`, `observacao`, `climatologia_modelo_raw`, `climatologia_observada`, `anom_modelo_raw` e `anom_observada` forem TODOS finitos.

| Status | Significado |
|---|---|
| `ok` | par válido, `n_treino_mos >= 120`, OLS ajustado com sucesso |
| `warmup_amostra_insuficiente` | par válido na própria linha, mas histórico de pares válidos ainda insuficiente |
| `anomalia_indisponivel_para_linha_avaliada` | a própria linha avaliada não tem par de anomalia válido (tipicamente por falta de climatologia própria do modelo ainda causalmente disponível) |
| `erro_regressao_degenerada` | variância de `anom_modelo_raw` no treino abaixo do critério numérico fixo (1e-06) ou matriz de posto deficiente |
| `erro_coeficientes_nao_finitos` | `alpha`/`beta` resultantes não finitos |

## 3. Auditoria anti-leakage

- Identidade algébrica do `benchmark_anomalia_reconstruida`: ✅ OK (diferença máxima absoluta = 2.84e-14, 1368 linhas verificadas).
- Verificação de leakage (periodo_treino_fim sempre < init_date avaliada): ✅ OK (0 problemas encontrados).
- Verificação de que nenhum outro lead contaminou o treino: ✅ OK.
- Testes automatizados (nenhuma linha de treino com `init_date >= avaliada`; própria linha nunca entra no OLS; outro lead nunca entra no treino; observação/forecast/climatologia futuros nunca alteram alpha/beta/anomalias históricas passadas; linhas sem par válido nunca contam para `n_treino_mos`; nenhuma linha NaN/Inf entra no OLS; demonstração sintética de leakage bloqueado) — ver `tests/test_cfsv2_calibracao_mos_linear.py`.

## 4. Primeira elegibilidade por H1-H6 (derivada programaticamente)

| Horizonte | Primeira `init_date` elegível | `n_treino_mos` nessa data | Linhas anteriores descartadas por anomalia indisponível |
|---|---|---|---|
| H1 — previsão do mês corrente | 2002-01 | 120 | 12 |
| H2 — horizonte futuro (+1 mês) | 2002-01 | 120 | 12 |
| H3 — horizonte futuro (+2 meses) | 2002-01 | 120 | 12 |
| H4 — horizonte futuro (+3 meses) | 2002-01 | 120 | 12 |
| H5 — horizonte futuro (+4 meses) | 2002-01 | 120 | 12 |
| H6 — horizonte futuro (+5 meses) | 2002-01 | 120 | 12 |

**Nenhuma data foi assumida a priori** (a versão anterior deste protocolo sugeria ~2001; a implementação real confirma a data verdadeira, tipicamente adiada por causa das primeiras inicializações de cada lead, que ainda não têm climatologia própria do modelo disponível — ver tabela acima).

## 5. Coeficientes alpha/beta por horizonte

| Horizonte | N | alpha mín | alpha p10 | alpha mediana | alpha média | alpha p90 | alpha máx |
|---|---|---|---|---|---|---|---|
| H1 | 108 | -10.08 | -9.51 | -8.00 | -8.07 | -6.88 | -6.35 |
| H2 | 108 | -9.24 | -8.63 | -6.90 | -7.11 | -5.81 | -5.31 |
| H3 | 108 | -8.87 | -8.35 | -6.68 | -6.85 | -5.62 | -5.28 |
| H4 | 108 | -7.31 | -6.92 | -5.63 | -5.68 | -4.53 | -3.99 |
| H5 | 108 | -7.33 | -6.93 | -5.76 | -5.82 | -4.87 | -4.24 |
| H6 | 108 | -6.80 | -6.33 | -4.86 | -5.02 | -3.98 | -3.48 |

| Horizonte | N | beta mín | beta p10 | beta mediana | beta média | beta p90 | beta máx |
|---|---|---|---|---|---|---|---|
| H1 | 108 | 0.415 | 0.459 | 0.598 | 0.563 | 0.662 | 0.669 |
| H2 | 108 | 0.097 | 0.110 | 0.254 | 0.231 | 0.302 | 0.331 |
| H3 | 108 | 0.165 | 0.215 | 0.374 | 0.346 | 0.426 | 0.451 |
| H4 | 108 | 0.408 | 0.435 | 0.458 | 0.461 | 0.514 | 0.543 |
| H5 | 108 | 0.217 | 0.251 | 0.286 | 0.291 | 0.358 | 0.390 |
| H6 | 108 | 0.282 | 0.341 | 0.383 | 0.402 | 0.489 | 0.503 |

**Leitura pré-registrada (protocolo, Seção 8) — nunca uma classificação automática do método, e nunca uma inferência causal sobre o CFSv2 só a partir de `beta`.** `beta < 1` descreve o que o AJUSTE fez (amorteceu a amplitude da anomalia do CFSv2 no ajuste pooled daquele horizonte); não é, por si só, evidência de que o CFSv2 "exagera" seu próprio sinal — essa leitura exigiria olhar `R²` e o skill fora da amostra (seção 9) junto com `beta`, nunca `beta` isolado.

- H1: o ajuste MOS estimou beta mediano 0.598 < 1, portanto aplicou amortecimento à amplitude das anomalias do CFSv2 no ajuste pooled por horizonte; R² treino mediano 0.152 — relação relativamente mais forte; `beta` deve ser interpretado junto com este R² e com o skill fora da amostra (seção 9), nunca isoladamente.
- H2: o ajuste MOS estimou beta mediano 0.254 < 1, portanto aplicou amortecimento à amplitude das anomalias do CFSv2 no ajuste pooled por horizonte; R² treino mediano 0.016 — relação muito fraca dentro da própria amostra de treino; `beta` deve ser interpretado junto com este R² e com o skill fora da amostra (seção 9), nunca isoladamente.
- H3: o ajuste MOS estimou beta mediano 0.374 < 1, portanto aplicou amortecimento à amplitude das anomalias do CFSv2 no ajuste pooled por horizonte; R² treino mediano 0.022 — relação muito fraca dentro da própria amostra de treino; `beta` deve ser interpretado junto com este R² e com o skill fora da amostra (seção 9), nunca isoladamente.
- H4: o ajuste MOS estimou beta mediano 0.458 < 1, portanto aplicou amortecimento à amplitude das anomalias do CFSv2 no ajuste pooled por horizonte; R² treino mediano 0.036 — relação muito fraca dentro da própria amostra de treino; `beta` deve ser interpretado junto com este R² e com o skill fora da amostra (seção 9), nunca isoladamente.
- H5: o ajuste MOS estimou beta mediano 0.286 < 1, portanto aplicou amortecimento à amplitude das anomalias do CFSv2 no ajuste pooled por horizonte; R² treino mediano 0.014 — relação muito fraca dentro da própria amostra de treino; `beta` deve ser interpretado junto com este R² e com o skill fora da amostra (seção 9), nunca isoladamente.
- H6: o ajuste MOS estimou beta mediano 0.383 < 1, portanto aplicou amortecimento à amplitude das anomalias do CFSv2 no ajuste pooled por horizonte; R² treino mediano 0.025 — relação muito fraca dentro da própria amostra de treino; `beta` deve ser interpretado junto com este R² e com o skill fora da amostra (seção 9), nunca isoladamente.

De forma geral nesta rodada: H1 tende a apresentar a relação mais forte (maior R² treino) entre os seis horizontes, enquanto H2-H6 têm R² de treino consistentemente baixos — reforçando que `beta` nesses horizontes descreve um ajuste com pouca explicação da variância observada, não uma relação bem estabelecida.

## 6. Diagnóstico de estabilidade

| Horizonte | N | R² treino mín | R² treino p10 | R² treino mediana | R² treino média | R² treino p90 | R² treino máx |
|---|---|---|---|---|---|---|---|
| H1 | 108 | 0.059 | 0.083 | 0.152 | 0.138 | 0.187 | 0.189 |
| H2 | 108 | 0.002 | 0.003 | 0.016 | 0.014 | 0.020 | 0.025 |
| H3 | 108 | 0.005 | 0.008 | 0.022 | 0.019 | 0.026 | 0.029 |
| H4 | 108 | 0.026 | 0.031 | 0.036 | 0.035 | 0.040 | 0.045 |
| H5 | 108 | 0.009 | 0.011 | 0.014 | 0.015 | 0.020 | 0.024 |
| H6 | 108 | 0.014 | 0.020 | 0.025 | 0.032 | 0.050 | 0.053 |

**`R² treino` nunca é usado como evidência de skill** — é o ajuste DENTRO da amostra de treino de cada linha, não uma medida de desempenho fora da amostra (essa vem da seção 9, sobre casos nunca vistos no próprio treino daquela linha).

## 7. Heterogeneidade de variância mensal — só diagnóstico

Métrica PRINCIPAL de influência sobre `beta_lead`: participação em `Sxx = Σ(anom_modelo_raw - x̄_lead)²` (soma centrada na média do lead) — não `sum(x²)` bruto (mantido abaixo só como diagnóstico adicional). Com intercepto no OLS, `beta = cov(x,y)/var(x)`, e `var(x) = Sxx/n`: é a dispersão em torno da média, não a magnitude bruta, que determina o peso de cada observação na inclinação.

Verificação de que as participações em `Sxx` somam ~1 dentro de cada lead: ✅ OK ({"1": 1.0, "2": 1.0000000000000002, "3": 0.9999999999999998, "4": 1.0000000000000002, "5": 0.9999999999999999, "6": 1.0}).

`só diagnóstico — participação em Sxx (soma centrada na média do lead) é a métrica PRINCIPAL de influência sobre beta_lead; sum(x²) bruto é mantido só como diagnóstico adicional. Nenhuma reponderação do OLS, nenhuma padronização, nenhum mês dominante removido nesta versão do Método 3.4.`

### 7.1. H1 (x̄_lead = 2.101)

| Mês | N | Desvio padrão anom. modelo | Desvio padrão anom. observada | RMSE benchmark3 | Participação em Sxx | Participação em sum(x²) (adicional) |
|---|---|---|---|---|---|---|
| Jan | 19 | 75.86 | 77.66 | 97.89 | 0.336 | 111397.7 |
| Fev | 19 | 49.83 | 72.11 | 70.05 | 0.143 | 48109.4 |
| Mar | 19 | 49.04 | 83.04 | 67.43 | 0.143 | 48821.7 |
| Abr | 19 | 43.08 | 86.35 | 70.95 | 0.106 | 35441.2 |
| Mai | 19 | 21.57 | 63.97 | 57.65 | 0.027 | 8841.2 |
| Jun | 19 | 1.09 | 9.79 | 9.60 | 0.000 | 28.7 |
| Jul | 19 | 0.42 | 5.32 | 5.25 | 0.000 | 3.6 |
| Ago | 19 | 0.45 | 13.89 | 14.02 | 0.000 | 4.0 |
| Set | 19 | 2.47 | 34.30 | 37.28 | 0.001 | 133.8 |
| Out | 19 | 6.70 | 35.11 | 42.81 | 0.004 | 945.3 |
| Nov | 19 | 34.30 | 59.59 | 51.60 | 0.068 | 23214.6 |
| Dez | 19 | 54.57 | 38.05 | 65.75 | 0.172 | 57843.4 |

Meses que mais dominam a estimação de `beta` em H1 (maior participação em `Sxx`): Jan (0.336), Dez (0.172), Mar (0.143).

### 7.2. H2 (x̄_lead = -0.955)

| Mês | N | Desvio padrão anom. modelo | Desvio padrão anom. observada | RMSE benchmark3 | Participação em Sxx | Participação em sum(x²) (adicional) |
|---|---|---|---|---|---|---|
| Jan | 19 | 35.48 | 77.52 | 90.29 | 0.139 | 24006.6 |
| Fev | 19 | 47.65 | 72.11 | 68.41 | 0.248 | 43175.3 |
| Mar | 19 | 40.66 | 83.04 | 96.10 | 0.183 | 31994.3 |
| Abr | 19 | 31.32 | 86.35 | 87.52 | 0.116 | 20578.9 |
| Mai | 19 | 9.36 | 63.97 | 70.67 | 0.010 | 1742.3 |
| Jun | 19 | 1.12 | 9.79 | 9.74 | 0.000 | 25.8 |
| Jul | 19 | 0.63 | 5.32 | 5.49 | 0.000 | 7.7 |
| Ago | 19 | 1.33 | 13.89 | 14.20 | 0.000 | 33.8 |
| Set | 19 | 4.47 | 34.30 | 37.54 | 0.002 | 387.6 |
| Out | 19 | 9.42 | 35.11 | 44.75 | 0.010 | 1686.2 |
| Nov | 19 | 30.01 | 59.59 | 48.07 | 0.099 | 17210.1 |
| Dez | 19 | 41.44 | 38.05 | 67.36 | 0.193 | 33322.3 |

Meses que mais dominam a estimação de `beta` em H2 (maior participação em `Sxx`): Fev (0.248), Dez (0.193), Mar (0.183).

### 7.3. H3 (x̄_lead = -0.222)

| Mês | N | Desvio padrão anom. modelo | Desvio padrão anom. observada | RMSE benchmark3 | Participação em Sxx | Participação em sum(x²) (adicional) |
|---|---|---|---|---|---|---|
| Jan | 19 | 34.05 | 77.52 | 89.07 | 0.197 | 23246.9 |
| Fev | 19 | 39.71 | 71.85 | 70.46 | 0.257 | 30360.4 |
| Mar | 19 | 29.79 | 83.04 | 79.14 | 0.159 | 18900.6 |
| Abr | 19 | 19.54 | 86.35 | 86.87 | 0.071 | 8423.2 |
| Mai | 19 | 10.62 | 63.97 | 69.80 | 0.018 | 2145.5 |
| Jun | 19 | 0.95 | 9.79 | 9.45 | 0.000 | 17.4 |
| Jul | 19 | 1.18 | 5.32 | 5.75 | 0.000 | 26.6 |
| Ago | 19 | 1.51 | 13.89 | 13.67 | 0.000 | 45.8 |
| Set | 19 | 5.32 | 34.30 | 38.65 | 0.005 | 553.7 |
| Out | 19 | 8.86 | 35.11 | 45.41 | 0.014 | 1578.7 |
| Nov | 19 | 26.35 | 59.59 | 61.88 | 0.115 | 13593.5 |
| Dez | 19 | 31.74 | 38.05 | 57.84 | 0.164 | 19410.6 |

Meses que mais dominam a estimação de `beta` em H3 (maior participação em `Sxx`): Fev (0.257), Jan (0.197), Dez (0.164).

### 7.4. H4 (x̄_lead = -1.034)

| Mês | N | Desvio padrão anom. modelo | Desvio padrão anom. observada | RMSE benchmark3 | Participação em Sxx | Participação em sum(x²) (adicional) |
|---|---|---|---|---|---|---|
| Jan | 19 | 39.66 | 77.52 | 79.60 | 0.267 | 31871.0 |
| Fev | 19 | 38.11 | 71.85 | 68.68 | 0.257 | 29787.5 |
| Mar | 19 | 34.31 | 78.57 | 86.82 | 0.191 | 22447.4 |
| Abr | 19 | 26.29 | 86.35 | 84.90 | 0.120 | 14454.1 |
| Mai | 19 | 6.18 | 63.97 | 71.08 | 0.007 | 732.4 |
| Jun | 19 | 0.88 | 9.79 | 9.94 | 0.000 | 14.7 |
| Jul | 19 | 1.32 | 5.32 | 5.30 | 0.000 | 33.0 |
| Ago | 19 | 1.73 | 13.89 | 14.07 | 0.001 | 56.9 |
| Set | 19 | 2.69 | 34.30 | 38.22 | 0.002 | 142.3 |
| Out | 19 | 8.92 | 35.11 | 45.95 | 0.013 | 1518.9 |
| Nov | 19 | 17.12 | 59.59 | 56.98 | 0.048 | 5568.6 |
| Dez | 19 | 22.94 | 38.05 | 44.56 | 0.094 | 11458.9 |

Meses que mais dominam a estimação de `beta` em H4 (maior participação em `Sxx`): Jan (0.267), Fev (0.257), Mar (0.191).

### 7.5. H5 (x̄_lead = 0.307)

| Mês | N | Desvio padrão anom. modelo | Desvio padrão anom. observada | RMSE benchmark3 | Participação em Sxx | Participação em sum(x²) (adicional) |
|---|---|---|---|---|---|---|
| Jan | 19 | 29.59 | 77.52 | 87.35 | 0.141 | 17437.2 |
| Fev | 19 | 38.10 | 71.85 | 71.86 | 0.224 | 27645.7 |
| Mar | 19 | 43.07 | 78.57 | 85.79 | 0.290 | 35701.1 |
| Abr | 19 | 30.57 | 82.73 | 73.14 | 0.144 | 17774.8 |
| Mai | 19 | 6.62 | 63.97 | 72.86 | 0.007 | 844.7 |
| Jun | 19 | 0.62 | 9.79 | 9.81 | 0.000 | 7.5 |
| Jul | 19 | 1.35 | 5.32 | 5.46 | 0.000 | 34.9 |
| Ago | 19 | 2.22 | 13.89 | 13.95 | 0.001 | 95.4 |
| Set | 19 | 3.16 | 34.30 | 38.52 | 0.002 | 190.4 |
| Out | 19 | 6.86 | 35.11 | 45.86 | 0.007 | 929.9 |
| Nov | 19 | 13.41 | 59.59 | 58.08 | 0.032 | 3925.5 |
| Dez | 19 | 31.03 | 38.05 | 60.03 | 0.152 | 18823.6 |

Meses que mais dominam a estimação de `beta` em H5 (maior participação em `Sxx`): Mar (0.290), Fev (0.224), Dez (0.152).

### 7.6. H6 (x̄_lead = -1.530)

| Mês | N | Desvio padrão anom. modelo | Desvio padrão anom. observada | RMSE benchmark3 | Participação em Sxx | Participação em sum(x²) (adicional) |
|---|---|---|---|---|---|---|
| Jan | 19 | 24.68 | 77.52 | 83.30 | 0.093 | 11780.3 |
| Fev | 19 | 43.18 | 71.85 | 77.30 | 0.278 | 36245.7 |
| Mar | 19 | 44.52 | 78.57 | 83.37 | 0.306 | 40066.2 |
| Abr | 19 | 28.38 | 82.73 | 81.52 | 0.121 | 15867.1 |
| Mai | 19 | 6.65 | 62.32 | 72.54 | 0.008 | 866.6 |
| Jun | 19 | 0.41 | 9.79 | 9.86 | 0.000 | 3.5 |
| Jul | 19 | 0.71 | 5.32 | 5.52 | 0.001 | 10.4 |
| Ago | 19 | 1.46 | 13.89 | 13.75 | 0.001 | 41.4 |
| Set | 19 | 3.33 | 34.30 | 38.17 | 0.002 | 216.2 |
| Out | 19 | 8.58 | 35.11 | 43.02 | 0.011 | 1416.4 |
| Nov | 19 | 15.77 | 59.59 | 56.42 | 0.037 | 4776.5 |
| Dez | 19 | 30.97 | 38.05 | 54.35 | 0.143 | 18311.6 |

Meses que mais dominam a estimação de `beta` em H6 (maior participação em `Sxx`): Mar (0.306), Fev (0.278), Dez (0.143).

**Nenhuma reponderação do OLS, nenhuma padronização e nenhum mês dominante removido nesta versão do Método 3.4** — esta seção serve só para verificar se `beta_lead` está sendo dominado por poucos meses de alta variância (agora medida corretamente por `Sxx`, não por `sum(x²)` bruto), antes de interpretar o coeficiente como representativo do horizonte. Os meses dominantes são lidos diretamente dos números recalculados acima, nunca assumidos a priori.

## 8. Resultados determinísticos H1-H6

`corr_anomalia_mos` (correlação de `anom_mos = forecast_mos - climatologia_observada` com `anom_observada`) é a métrica PRINCIPAL de correlação de anomalia do Método 3.4 — **corrigida nesta revisão**: a versão anterior reportava `corr_anomalia_raw` (correlação da anomalia BRUTA do CFSv2, o preditor de entrada do OLS, nunca o resultado do ajuste) sob o rótulo ambíguo `corr_anomalia`. As duas são mantidas, com nomes inequívocos, para comparação.

| Horizonte | N | Bias | MAE | RMSE | Corr. absoluta | Corr. anomalia (MOS, principal) | Corr. anomalia (raw, CFSv2 bruto) |
|---|---|---|---|---|---|---|---|
| H1 | 108 | 0.30 | 33.64 | 48.38 | 0.894 | 0.547 | 0.565 |
| H2 | 108 | 0.17 | 36.68 | 55.35 | 0.855 | 0.181 | 0.266 |
| H3 | 108 | -0.93 | 36.75 | 55.59 | 0.856 | 0.235 | 0.303 |
| H4 | 108 | -1.02 | 35.85 | 54.85 | 0.860 | 0.227 | 0.247 |
| H5 | 108 | -1.43 | 35.33 | 54.88 | 0.861 | 0.209 | 0.248 |
| H6 | 108 | -1.82 | 36.01 | 56.04 | 0.855 | 0.039 | 0.085 |

## 9. Comparação contra os três benchmarks pré-registrados

`skill_vs_X = 1 - RMSE_mos / RMSE_X` — numerador e denominador sempre sobre exatamente os mesmos casos elegíveis.

| Horizonte | RMSE MOS | RMSE bruto | RMSE climatologia | RMSE benchmark3 | skill_vs_raw | RMSESS_climatologia | skill_vs_anomalia_reconstruida |
|---|---|---|---|---|---|---|---|
| H1 | 48.38 | 66.60 | 57.25 | 48.88 | 0.274 | 0.155 | 0.010 |
| H2 | 55.35 | 71.64 | 56.57 | 55.27 | 0.227 | 0.022 | -0.001 |
| H3 | 55.59 | 72.15 | 57.22 | 54.55 | 0.229 | 0.028 | -0.019 |
| H4 | 54.85 | 75.24 | 56.47 | 54.90 | 0.271 | 0.029 | 0.001 |
| H5 | 54.88 | 77.60 | 55.98 | 54.43 | 0.293 | 0.020 | -0.008 |
| H6 | 56.04 | 81.35 | 55.94 | 57.62 | 0.311 | -0.002 | 0.027 |

## 10. Comparação PRINCIPAL — MOS vs. aditivo (Método 3.1), amostra pareada

`skill_mos_vs_aditivo = 1 - RMSE_mos / RMSE_aditivo_matched` — SEMPRE sobre a MESMA amostra pareada (`aditiva_matched_mos_sample`, mesmas chaves `init_date×lead` nos dois lados). **Nunca comparado contra o aditivo full** (que usaria amostras diferentes).

| Horizonte | RMSE MOS | RMSE aditivo (matched) | skill_mos_vs_aditivo |
|---|---|---|---|
| H1 | 48.38 | 47.28 | -0.023 |
| H2 | 55.35 | 53.30 | -0.038 |
| H3 | 55.59 | 53.00 | -0.049 |
| H4 | 54.85 | 53.80 | -0.019 |
| H5 | 54.88 | 53.01 | -0.035 |
| H6 | 56.04 | 56.94 | 0.016 |

## 11. Intervalos de confiança (bootstrap em blocos por target_ano)

MOS, os três benchmarks E o aditivo matched sempre nos MESMOS blocos de ano sorteados em cada reamostra. **Classificação meramente descritiva.**

| Horizonte | skill_vs_raw | IC 95% | skill_vs_anomalia_reconstruida | IC 95% | skill_mos_vs_aditivo | IC 95% | Evidência vs. aditivo |
|---|---|---|---|---|---|---|---|
| H1 | 0.274 | [0.216, 0.350] | 0.010 | [-0.079, 0.129] | -0.023 | [-0.103, 0.085] | sem evidência de diferença estatisticamente distinguível (IC inclui zero) |
| H2 | 0.227 | [0.147, 0.329] | -0.001 | [-0.082, 0.095] | -0.038 | [-0.116, 0.058] | sem evidência de diferença estatisticamente distinguível (IC inclui zero) |
| H3 | 0.229 | [0.138, 0.307] | -0.019 | [-0.096, 0.041] | -0.049 | [-0.126, 0.010] | sem evidência de diferença estatisticamente distinguível (IC inclui zero) |
| H4 | 0.271 | [0.152, 0.366] | 0.001 | [-0.029, 0.040] | -0.019 | [-0.078, 0.036] | sem evidência de diferença estatisticamente distinguível (IC inclui zero) |
| H5 | 0.293 | [0.201, 0.393] | -0.008 | [-0.034, 0.018] | -0.035 | [-0.092, 0.013] | sem evidência de diferença estatisticamente distinguível (IC inclui zero) |
| H6 | 0.311 | [0.222, 0.425] | 0.027 | [-0.007, 0.056] | 0.016 | [-0.043, 0.066] | sem evidência de diferença estatisticamente distinguível (IC inclui zero) |

### 11.1. Avaliação do critério de aprovação pré-registrado

| Horizonte | skill_vs_anomalia_reconstruida acima de zero? | RMSESS_climatologia acima de zero? | Atende ao critério? | skill_mos_vs_aditivo (informativo) |
|---|---|---|---|---|
| H1 | ❌ não | ✅ sim | ❌ NÃO | IC 95% inclui zero (indeterminado) |
| H2 | ❌ não | ❌ não | ❌ NÃO | IC 95% inclui zero (indeterminado) |
| H3 | ❌ não | ❌ não | ❌ NÃO | IC 95% inclui zero (indeterminado) |
| H4 | ❌ não | ❌ não | ❌ NÃO | IC 95% inclui zero (indeterminado) |
| H5 | ❌ não | ❌ não | ❌ NÃO | IC 95% inclui zero (indeterminado) |
| H6 | ❌ não | ❌ não | ❌ NÃO | IC 95% inclui zero (indeterminado) |

**Nenhum horizonte H1–H6 atende integralmente ao critério pré-registrado de aprovação do Método 3.4 nesta rodada.** O critério nunca foi alterado depois de observar este resultado.

## 12. Matriz mês-alvo × lead (diagnóstico de heterogeneidade — NUNCA 72 testes de significância)

### 12.1. N elegível por célula

| Mês \ Lead | H1 | H2 | H3 | H4 | H5 | H6 |
|---|---|---|---|---|---|---|
| Jan | 9 | 9 | 9 | 9 | 9 | 9 |
| Fev | 9 | 9 | 9 | 9 | 9 | 9 |
| Mar | 9 | 9 | 9 | 9 | 9 | 9 |
| Abr | 9 | 9 | 9 | 9 | 9 | 9 |
| Mai | 9 | 9 | 9 | 9 | 9 | 9 |
| Jun | 9 | 9 | 9 | 9 | 9 | 9 |
| Jul | 9 | 9 | 9 | 9 | 9 | 9 |
| Ago | 9 | 9 | 9 | 9 | 9 | 9 |
| Set | 9 | 9 | 9 | 9 | 9 | 9 |
| Out | 9 | 9 | 9 | 9 | 9 | 9 |
| Nov | 9 | 9 | 9 | 9 | 9 | 9 |
| Dez | 9 | 9 | 9 | 9 | 9 | 9 |

### 12.2. skill_vs_anomalia_reconstruida por célula

| Mês \ Lead | H1 | H2 | H3 | H4 | H5 | H6 |
|---|---|---|---|---|---|---|
| Jan | 0.287* | 0.110* | 0.095* | 0.083* | 0.080* | 0.065* |
| Fev | -0.270* | -0.330* | -0.091* | -0.052* | -0.034* | 0.061* |
| Mar | -0.001* | 0.122* | -0.165* | -0.067* | -0.030* | -0.069* |
| Abr | -0.072* | -0.013* | 0.003* | 0.008* | -0.056* | 0.027* |
| Mai | -0.188* | -0.053* | -0.072* | -0.031* | -0.031* | -0.017* |
| Jun | -0.758* | -0.525* | -0.470* | -0.262* | -0.279* | -0.240* |
| Jul | -0.572* | -0.440* | -0.338* | -0.395* | -0.268* | -0.233* |
| Ago | -0.198* | -0.152* | -0.159* | -0.095* | -0.109* | -0.110* |
| Set | 0.137* | 0.122* | 0.123* | 0.109* | 0.104* | 0.093* |
| Out | 0.033* | 0.061* | 0.028* | 0.038* | 0.054* | 0.014* |
| Nov | -0.010* | -0.280* | 0.099* | 0.044* | -0.012* | 0.033* |
| Dez | 0.229* | 0.141* | 0.148* | 0.122* | 0.130* | 0.159* |

### 12.3. skill_mos_vs_aditivo por célula

| Mês \ Lead | H1 | H2 | H3 | H4 | H5 | H6 |
|---|---|---|---|---|---|---|
| Jan | 0.253* | -0.006* | -0.016* | 0.001* | -0.078* | -0.042* |
| Fev | -0.202* | -0.276* | -0.072* | -0.029* | -0.024* | 0.071* |
| Mar | -0.151* | 0.074* | -0.203* | -0.112* | -0.028* | -0.034* |
| Abr | -0.053* | 0.004* | 0.016* | 0.022* | -0.027* | 0.055* |
| Mai | -0.275* | -0.123* | -0.128* | -0.082* | -0.078* | -0.056* |
| Jun | -0.852* | -0.579* | -0.488* | -0.283* | -0.293* | -0.255* |
| Jul | -0.529* | -0.399* | -0.310* | -0.337* | -0.240* | -0.201* |
| Ago | -0.136* | -0.095* | -0.109* | -0.043* | -0.050* | -0.053* |
| Set | 0.013* | -0.025* | -0.015* | -0.034* | -0.034* | -0.049* |
| Out | -0.001* | -0.003* | -0.094* | 0.003* | -0.042* | -0.058* |
| Nov | -0.108* | -0.380* | 0.038* | -0.041* | -0.082* | -0.033* |
| Dez | 0.228* | 0.149* | 0.152* | 0.161* | 0.133* | 0.159* |

*`*` = célula com N abaixo da amostra mínima do projeto (20).*

## 13. Grupos sazonais (chuvosa/transição/seca) × lead — diagnóstico complementar

| Grupo | Métrica | H1 | H2 | H3 | H4 | H5 | H6 |
|---|---|---|---|---|---|---|---|
| chuvosa | N | 63 | 63 | 63 | 63 | 63 | 63 |
| chuvosa | skill_vs_anomalia_reconstruida | 0.044 | 0.009 | -0.010 | 0.007 | -0.004 | 0.037 |
| chuvosa | skill_mos_vs_aditivo | 0.018 | -0.019 | -0.032 | -0.004 | -0.024 | 0.033 |
| transicao | N | 18 | 18 | 18 | 18 | 18 | 18 |
| transicao | skill_vs_anomalia_reconstruida | -0.132 | -0.033 | -0.048 | -0.015 | -0.016 | -0.004 |
| transicao | skill_mos_vs_aditivo | -0.230 | -0.113 | -0.116 | -0.077 | -0.074 | -0.056 |
| seca | N | 27 | 27 | 27 | 27 | 27 | 27 |
| seca | skill_vs_anomalia_reconstruida | -0.311 | -0.238 | -0.225 | -0.156 | -0.154 | -0.144 |
| seca | skill_mos_vs_aditivo | -0.257 | -0.189 | -0.183 | -0.109 | -0.105 | -0.097 |

## 14. Comparação expanding vs. LOYO matched

**LOYO full** (`mos_loyo_retrospective`): NÃO simula uso em tempo real — usa anos futuros (e exclui o ano-alvo INTEIRO, todos os 12 meses, do treino). Análise descritiva adicional, nunca operacional, amostra DIFERENTE do expanding — nunca comparada diretamente. Ver loyo_matched_evaluation_period para a comparação pareada.

**LOYO matched** (`mos_loyo_matched_evaluation_period`) — comparação PRINCIPAL, mesmas chaves do expanding:

| Horizonte | N expanding | N LOYO matched | RMSE expanding | RMSE LOYO matched | delta skill_vs_raw | delta RMSESS_climatologia | delta skill_vs_anomalia_reconstruida |
|---|---|---|---|---|---|---|---|
| H1 | 108 | 108 | 48.38 | 48.13 | 0.0038 | 0.0044 | 0.0051 |
| H2 | 108 | 108 | 55.35 | 55.21 | 0.0020 | 0.0025 | 0.0025 |
| H3 | 108 | 108 | 55.59 | 55.30 | 0.0041 | 0.0052 | 0.0054 |
| H4 | 108 | 108 | 54.85 | 54.83 | 0.0002 | 0.0003 | 0.0003 |
| H5 | 108 | 108 | 54.88 | 54.68 | 0.0025 | 0.0035 | 0.0036 |
| H6 | 108 | 108 | 56.04 | 55.96 | 0.0010 | 0.0015 | 0.0014 |

**Delta meramente descritivo — nunca um teste de significância automático. LOYO full (amostra diferente) nunca comparado diretamente com o expanding — só a comparação matched acima é interpretável.**

## 15. Limitações

- Warm-up de 120 pares válidos reduz substancialmente a amostra de avaliação principal em relação ao total de 240 inicializações — perda deliberada de poder estatístico em troca de defensabilidade metodológica (protocolo, Seção 6).
- O pooling entre meses (Seção 3 do protocolo) assume implicitamente que a relação `alpha`/`beta` é homogênea entre meses — a seção 7 (heterogeneidade de variância) mostra até que ponto isso é razoável, mas não corrige por isso nesta versão.
- `R² treino` (seção 6) não é uma medida de skill fora da amostra — nunca interpretado como tal.
- A matriz mês × lead (seção 12) e os grupos sazonais (seção 13) têm amostra pequena por célula — usados só como diagnóstico de heterogeneidade, nunca como critério de aprovação célula a célula.
- Nenhuma correção operacional de viés foi aplicada — permanece avaliação científica offline.

## 16. Conclusão restrita ao Método 3.4 (MOS linear)

Esta conclusão vale SOMENTE para o MOS linear causal no espaço de anomalias, treinado por lead com pooling entre meses — nunca generalizada para "calibração do CFSv2" em geral, nunca chamando o modelo de validado ou pronto para produção.

- Critério pré-registrado de aprovação: nenhum horizonte H1-H6 satisfaz simultaneamente os dois critérios estatísticos principais (seção 11.1).
- Comparação principal com o Método 3.1 (seção 10/11): H1: sem evidência de diferença estatisticamente distinguível (IC inclui zero); H2: sem evidência de diferença estatisticamente distinguível (IC inclui zero); H3: sem evidência de diferença estatisticamente distinguível (IC inclui zero); H4: sem evidência de diferença estatisticamente distinguível (IC inclui zero); H5: sem evidência de diferença estatisticamente distinguível (IC inclui zero); H6: sem evidência de diferença estatisticamente distinguível (IC inclui zero).
- Não implementar extensão do modelo (dummy mensal, interação, ENSO, tendência, termo quadrático, regularização, seleção automática), quantile mapping, nem correção híbrida nesta atividade — decisões de uma próxima etapa, condicionadas à revisão independente deste resultado.
