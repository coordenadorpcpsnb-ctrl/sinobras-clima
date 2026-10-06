# Correção aditiva causal do CFSv2 — Fase 2C.3D (Método 3.1)

**Relatório técnico — avaliação OFFLINE e científica, completamente separada do sistema operacional. Nenhuma correção foi aplicada ao dashboard, SARIMAX, XGBoost, pipeline operacional, `serie_subst.csv`, CFSv2 RAW, CHIRPS v3 histórico nem à base pareada já aprovada da Fase 2C.3C — todos só lidos, nunca alterados.**

## 1. Metodologia

Único método implementado nesta atividade: **correção ADITIVA causal por lead × mês-alvo** (Método 3.1 do protocolo, `docs/nmme-fase2c3d-protocolo-calibracao-cfsv2.md`). Nenhum outro método (multiplicativo, quantile mapping, MOS, calibração probabilística) foi implementado.

```
erro_historico = forecast_raw - observacao
bias_aditivo(lead, mes_alvo, init_date) = média dos erros históricos elegíveis da
    MESMA combinação lead × mês-alvo, com init_date_treino < init_date_avaliada
forecast_calibrado = forecast_raw - bias_aditivo
```

Previsão determinística = média do ensemble dos 24 membros (mesma convenção da 2C.3C) — os membros individuais NÃO são recalibrados nesta atividade; consequentemente, avaliação probabilística do ensemble calibrado (CRPSS/BSS) NÃO se aplica e não foi calculada.

## 2. Warm-up e amostra elegível

`N_TREINO_MINIMO = 10` observações históricas elegíveis por combinação lead × mês-alvo, pré-registrado no protocolo (Seção 5.1) — nunca ajustado depois de ver resultados. Abaixo disso, `status_calibracao = 'warmup_amostra_insuficiente'`: sem previsão calibrada válida, nunca substituída pela previsão bruta, nunca imputada, nunca compartilhada entre meses.

**Primeira inicialização elegível por lead × mês-alvo (derivada programaticamente, nunca hardcoded):**

- Ano da primeira inicialização elegível em TODAS as células lead×mês observado nesta execução: 2001.

| Lead \ Mês | Jan | Fev | Mar | Abr | Mai | Jun | Jul | Ago | Set | Out | Nov | Dez |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H1 | 2001-01 | 2001-02 | 2001-03 | 2001-04 | 2001-05 | 2001-06 | 2001-07 | 2001-08 | 2001-09 | 2001-10 | 2001-11 | 2001-12 |
| H2 | 2001-12 | 2001-01 | 2001-02 | 2001-03 | 2001-04 | 2001-05 | 2001-06 | 2001-07 | 2001-08 | 2001-09 | 2001-10 | 2001-11 |
| H3 | 2001-11 | 2001-12 | 2001-01 | 2001-02 | 2001-03 | 2001-04 | 2001-05 | 2001-06 | 2001-07 | 2001-08 | 2001-09 | 2001-10 |
| H4 | 2001-10 | 2001-11 | 2001-12 | 2001-01 | 2001-02 | 2001-03 | 2001-04 | 2001-05 | 2001-06 | 2001-07 | 2001-08 | 2001-09 |
| H5 | 2001-09 | 2001-10 | 2001-11 | 2001-12 | 2001-01 | 2001-02 | 2001-03 | 2001-04 | 2001-05 | 2001-06 | 2001-07 | 2001-08 |
| H6 | 2001-08 | 2001-09 | 2001-10 | 2001-11 | 2001-12 | 2001-01 | 2001-02 | 2001-03 | 2001-04 | 2001-05 | 2001-06 | 2001-07 |

## 3. Auditoria anti-leakage

- Identidade algébrica do `benchmark_anomalia_reconstruida`: ✅ OK (diferença máxima absoluta = 2.84e-14, 1368 linhas verificadas).
- Verificação de leakage (periodo_treino_fim sempre < init_date avaliada): ✅ OK (0 problemas encontrados).
- Testes automatizados de leakage (nunca init_date_treino >= avaliada; própria inicialização nunca entra no seu bias; outro lead/mês-alvo nunca entra no treino; observação futura nunca modifica previsão calibrada passada; demonstração sintética de que uma implementação leaky produziria ganho artificial, bloqueada pela implementação real) — ver `tests/test_cfsv2_calibracao_aditiva.py`.

## 4. Resultados H1–H6 (método calibrado)

Somente sobre casos com `status_calibracao = 'ok'` e `benchmark_anomalia_reconstruida` disponível — nunca misturando com warm-up.

| Horizonte | N elegível | Bias | MAE | RMSE | Corr absoluta | N p/ anomalia | Corr anomalia calibrada |
|---|---|---|---|---|---|---|---|
| H1 | 120 | 5.41 | 33.66 | 46.75 | 0.903 | 108 | 0.556 |
| H2 | 120 | 2.32 | 35.66 | 52.35 | 0.872 | 108 | 0.311 |
| H3 | 120 | -0.41 | 34.64 | 51.63 | 0.876 | 108 | 0.344 |
| H4 | 120 | -2.39 | 34.69 | 53.35 | 0.867 | 108 | 0.251 |
| H5 | 120 | -1.73 | 33.88 | 52.25 | 0.873 | 108 | 0.303 |
| H6 | 120 | -4.55 | 33.76 | 54.74 | 0.861 | 108 | 0.164 |

## 5. Comparação contra os três benchmarks pré-registrados

`skill_vs_X = 1 - RMSE_calibrado / RMSE_X` — numerador e denominador sempre sobre exatamente os mesmos casos elegíveis. **Critério pré-registrado de aprovação (protocolo, Seção 6.2): o ponto PRINCIPAL é `skill_vs_anomalia_reconstruida`, nunca `skill_vs_raw` isoladamente.**

| Horizonte | RMSE calibrado | RMSE bruto | RMSE climatologia | RMSE benchmark3 | skill_vs_raw | RMSESS_climatologia | skill_vs_anomalia_reconstruida |
|---|---|---|---|---|---|---|---|
| H1 | 46.75 | 65.88 | 55.75 | 48.71 | 0.290 | 0.162 | 0.040 |
| H2 | 52.35 | 71.47 | 55.16 | 54.33 | 0.268 | 0.051 | 0.036 |
| H3 | 51.63 | 71.46 | 55.50 | 53.07 | 0.278 | 0.070 | 0.027 |
| H4 | 53.35 | 76.02 | 55.48 | 54.54 | 0.298 | 0.038 | 0.022 |
| H5 | 52.25 | 79.16 | 55.49 | 53.87 | 0.340 | 0.058 | 0.030 |
| H6 | 54.74 | 81.23 | 55.17 | 55.47 | 0.326 | 0.008 | 0.013 |

## 6. Intervalos de confiança (bootstrap em blocos por target_ano)

Método calibrado e os três benchmarks sempre nos MESMOS blocos de ano sorteados em cada reamostra — IC nunca derivado dividindo intervalos separados. **Classificação meramente descritiva — nunca convertida automaticamente em 'bom'/'mau'.**

| Horizonte | skill_vs_raw | IC 95% | Classe | RMSESS_climatologia | IC 95% | Classe | skill_vs_anomalia_reconstruida | IC 95% | Classe |
|---|---|---|---|---|---|---|---|---|---|
| H1 | 0.290 | [0.186, 0.349] | IC 95% totalmente ACIMA de zero | 0.162 | [-0.020, 0.261] | IC 95% inclui zero (indeterminado) | 0.040 | [0.002, 0.088] | IC 95% totalmente ACIMA de zero |
| H2 | 0.268 | [0.199, 0.333] | IC 95% totalmente ACIMA de zero | 0.051 | [-0.047, 0.120] | IC 95% inclui zero (indeterminado) | 0.036 | [-0.001, 0.075] | IC 95% inclui zero (indeterminado) |
| H3 | 0.278 | [0.211, 0.352] | IC 95% totalmente ACIMA de zero | 0.070 | [0.005, 0.152] | IC 95% totalmente ACIMA de zero | 0.027 | [-0.010, 0.060] | IC 95% inclui zero (indeterminado) |
| H4 | 0.298 | [0.202, 0.398] | IC 95% totalmente ACIMA de zero | 0.038 | [-0.032, 0.130] | IC 95% inclui zero (indeterminado) | 0.022 | [-0.017, 0.064] | IC 95% inclui zero (indeterminado) |
| H5 | 0.340 | [0.221, 0.455] | IC 95% totalmente ACIMA de zero | 0.058 | [0.003, 0.119] | IC 95% totalmente ACIMA de zero | 0.030 | [-0.010, 0.072] | IC 95% inclui zero (indeterminado) |
| H6 | 0.326 | [0.182, 0.455] | IC 95% totalmente ACIMA de zero | 0.008 | [-0.079, 0.119] | IC 95% inclui zero (indeterminado) | 0.013 | [-0.025, 0.053] | IC 95% inclui zero (indeterminado) |

### 6.1. Avaliação do critério de aprovação pré-registrado — NENHUM horizonte isolado

O protocolo (Seção 6.2) exige, SIMULTANEAMENTE, que o IC 95% de `skill_vs_anomalia_reconstruida` E de `RMSESS_climatologia` estejam totalmente acima de zero — bater só um dos dois **não é suficiente** para aprovação. Atender só `skill_vs_anomalia_reconstruida` (como H1) não habilita a chamar aquele horizonte de aprovado.

| Horizonte | skill_vs_anomalia_reconstruida acima de zero? | RMSESS_climatologia acima de zero? | Atende ao critério pré-registrado? |
|---|---|---|---|
| H1 | ✅ sim | ❌ não | ❌ NÃO |
| H2 | ❌ não | ❌ não | ❌ NÃO |
| H3 | ❌ não | ✅ sim | ❌ NÃO |
| H4 | ❌ não | ❌ não | ❌ NÃO |
| H5 | ❌ não | ✅ sim | ❌ NÃO |
| H6 | ❌ não | ❌ não | ❌ NÃO |

**Nenhum horizonte H1–H6 atende integralmente ao critério pré-registrado de aprovação do Método 3.1 nesta rodada.** H1 pode ser descrito como: *único horizonte com evidência de ganho sobre o benchmark de anomalia reconstruída, porém sem evidência conclusiva de ganho sobre a climatologia causal* — nunca chamado de "aprovado".

## 7. Matriz mês-alvo × lead (diagnóstico de heterogeneidade — NUNCA 72 testes de significância)

Usada só para verificar direção/coerência dos efeitos, concentração do ganho, degradações relevantes e padrões sazonais — nunca como critério de aprovação célula a célula.

### 7.1. N elegível por célula

| Mês \ Lead | H1 | H2 | H3 | H4 | H5 | H6 |
|---|---|---|---|---|---|---|
| Jan | 10 | 10 | 10 | 10 | 10 | 10 |
| Fev | 10 | 10 | 10 | 10 | 10 | 10 |
| Mar | 10 | 10 | 10 | 10 | 10 | 10 |
| Abr | 10 | 10 | 10 | 10 | 10 | 10 |
| Mai | 10 | 10 | 10 | 10 | 10 | 10 |
| Jun | 10 | 10 | 10 | 10 | 10 | 10 |
| Jul | 10 | 10 | 10 | 10 | 10 | 10 |
| Ago | 10 | 10 | 10 | 10 | 10 | 10 |
| Set | 10 | 10 | 10 | 10 | 10 | 10 |
| Out | 10 | 10 | 10 | 10 | 10 | 10 |
| Nov | 10 | 10 | 10 | 10 | 10 | 10 |
| Dez | 10 | 10 | 10 | 10 | 10 | 10 |

### 7.2. skill_vs_anomalia_reconstruida por célula (ponto estimado, sem IC nesta matriz)

| Mês \ Lead | H1 | H2 | H3 | H4 | H5 | H6 |
|---|---|---|---|---|---|---|
| Jan | 0.053* | 0.063* | 0.051* | 0.003* | 0.080* | 0.063* |
| Fev | -0.039* | -0.029* | -0.018* | -0.024* | -0.009* | -0.010* |
| Mar | 0.139* | 0.062* | 0.043* | 0.081* | 0.041* | 0.004* |
| Abr | -0.020* | -0.016* | -0.014* | -0.014* | -0.022* | -0.028* |
| Mai | 0.104* | 0.083* | 0.071* | 0.063* | 0.062* | 0.043* |
| Jun | 0.071* | 0.042* | 0.017* | 0.029* | 0.028* | 0.023* |
| Jul | -0.020* | -0.018* | -0.012* | -0.034* | -0.017* | -0.014* |
| Ago | -0.048* | -0.044* | -0.036* | -0.046* | -0.045* | -0.050* |
| Set | 0.130* | 0.146* | 0.134* | 0.141* | 0.137* | 0.139* |
| Out | 0.013* | 0.027* | 0.073* | 0.060* | 0.084* | 0.052* |
| Nov | 0.041* | 0.050* | 0.054* | 0.082* | 0.064* | 0.063* |
| Dez | 0.004* | -0.006* | 0.002* | -0.052* | -0.010* | -0.006* |

*`*` = célula com N abaixo da amostra mínima do projeto (20).*

## 8. Grupos sazonais (chuvosa/transição/seca) × lead

| Grupo | Métrica | H1 | H2 | H3 | H4 | H5 | H6 |
|---|---|---|---|---|---|---|---|
| chuvosa | N | 70 | 70 | 70 | 70 | 70 | 70 |
| chuvosa | skill_vs_anomalia_reconstruida | 0.028 | 0.023 | 0.015 | 0.010 | 0.020 | 0.004 |
| chuvosa | RMSESS_climatologia | 0.137 | 0.040 | 0.060 | 0.028 | 0.055 | -0.002 |
| transicao | N | 20 | 20 | 20 | 20 | 20 | 20 |
| transicao | skill_vs_anomalia_reconstruida | 0.109 | 0.091 | 0.080 | 0.073 | 0.071 | 0.055 |
| transicao | RMSESS_climatologia | 0.277 | 0.100 | 0.112 | 0.085 | 0.077 | 0.050 |
| seca | N | 30 | 30 | 30 | 30 | 30 | 30 |
| seca | skill_vs_anomalia_reconstruida | -0.035 | -0.032 | -0.027 | -0.037 | -0.033 | -0.037 |
| seca | RMSESS_climatologia | -0.006 | -0.033 | -0.017 | -0.043 | -0.047 | -0.017 |

## 9. Comparação expanding vs. LOYO

### 9.1. LOYO full (retrospectivo descritivo — amostra DIFERENTE do expanding)

**Rótulo: `aditiva_loyo_full_retrospective`.** NÃO simula uso em tempo real — usa anos futuros no cálculo do bias, E usa uma amostra MAIOR (N=240, 1991-2010) que o expanding (N=120, 2001-2010) — nunca comparado diretamente ao expanding como se fosse só efeito do método de treinamento. Análise retrospectiva descritiva adicional, nunca misturada com expanding_operational_simulation nem chamada de operacional. Para a comparação pareada e justa, ver loyo_matched_evaluation_period.

| Horizonte | N expanding | N LOYO full | RMSESS_climatologia expanding | RMSESS_climatologia LOYO full | Divergência (LOYO full − expanding) |
|---|---|---|---|---|---|
| H1 | 120 | 240 | 0.162 | 0.074 | -0.087 |
| H2 | 120 | 240 | 0.051 | -0.035 | -0.086 |
| H3 | 120 | 240 | 0.070 | -0.002 | -0.072 |
| H4 | 120 | 240 | 0.038 | 0.016 | -0.022 |
| H5 | 120 | 240 | 0.058 | -0.006 | -0.065 |
| H6 | 120 | 240 | 0.008 | -0.010 | -0.018 |

**Esta comparação mistura dois efeitos: o desenho de treinamento (causal vs. passado+futuro) E o período de avaliação (N=120, 2001-2010 vs. N=240, 1991-2010) — nunca interpretar a divergência acima como efeito puro do método de treinamento.** Ver 9.2 para a comparação pareada.

### 9.2. LOYO matched evaluation period — comparação PRINCIPAL (mesmos 120 casos)

**Rótulo: `aditiva_loyo_matched_evaluation_period`.** LOYO (treino com passado+futuro, excluindo o ano avaliado) restrito ao MESMO conjunto de verificação do expanding (mesmos init_date×lead, N=120/horizonte) — isola o efeito do desenho de treinamento do efeito do período de avaliação. Esta é a comparação PRINCIPAL expanding × LOYO, nunca o loyo_retrospective (full, N=240) acima.

- Identidade algébrica do `benchmark_anomalia_reconstruida_loyo`: ✅ OK (diferença máxima absoluta = 2.84e-14, 1440 linhas verificadas).

| Horizonte | N exp. | N LOYO matched | RMSE calibrado exp. | RMSE calibrado LOYO matched | skill_vs_raw exp. | skill_vs_raw LOYO matched | RMSESS_climatologia exp. | RMSESS_climatologia LOYO matched | skill_vs_anomalia_reconstruida exp. | skill_vs_anomalia_reconstruida LOYO matched |
|---|---|---|---|---|---|---|---|---|---|---|
| H1 | 120 | 120 | 46.75 | 46.48 | 0.290 | 0.294 | 0.162 | 0.154 | 0.040 | 0.031 |
| H2 | 120 | 120 | 52.35 | 52.29 | 0.268 | 0.268 | 0.051 | 0.040 | 0.036 | 0.022 |
| H3 | 120 | 120 | 51.63 | 51.33 | 0.278 | 0.282 | 0.070 | 0.061 | 0.027 | 0.019 |
| H4 | 120 | 120 | 53.35 | 53.03 | 0.298 | 0.302 | 0.038 | 0.031 | 0.022 | 0.015 |
| H5 | 120 | 120 | 52.25 | 51.83 | 0.340 | 0.345 | 0.058 | 0.053 | 0.030 | 0.022 |
| H6 | 120 | 120 | 54.74 | 54.01 | 0.326 | 0.335 | 0.008 | 0.009 | 0.013 | 0.012 |

**Delta (LOYO matched − expanding), meramente descritivo — nunca um teste de significância automático:**

| Horizonte | delta skill_vs_raw | delta RMSESS_climatologia | delta skill_vs_anomalia_reconstruida |
|---|---|---|---|
| H1 | 0.0041 | -0.0074 | -0.0094 |
| H2 | 0.0008 | -0.0109 | -0.0146 |
| H3 | 0.0041 | -0.0087 | -0.0077 |
| H4 | 0.0042 | -0.0078 | -0.0064 |
| H5 | 0.0053 | -0.0057 | -0.0079 |
| H6 | 0.0089 | 0.0011 | -0.0007 |

**IC 95% dos três skills do LOYO matched (bootstrap em blocos por target_ano, mesmos blocos para método e benchmarks em cada reamostra):**

| Horizonte | skill_vs_raw | IC 95% | Classe | RMSESS_climatologia | IC 95% | Classe | skill_vs_anomalia_reconstruida | IC 95% | Classe |
|---|---|---|---|---|---|---|---|---|---|
| H1 | 0.294 | [0.192, 0.360] | IC 95% totalmente ACIMA de zero | 0.154 | [-0.016, 0.249] | IC 95% inclui zero (indeterminado) | 0.031 | [-0.006, 0.071] | IC 95% inclui zero (indeterminado) |
| H2 | 0.268 | [0.188, 0.336] | IC 95% totalmente ACIMA de zero | 0.040 | [-0.069, 0.101] | IC 95% inclui zero (indeterminado) | 0.022 | [-0.015, 0.055] | IC 95% inclui zero (indeterminado) |
| H3 | 0.282 | [0.198, 0.360] | IC 95% totalmente ACIMA de zero | 0.061 | [0.003, 0.132] | IC 95% totalmente ACIMA de zero | 0.019 | [-0.016, 0.049] | IC 95% inclui zero (indeterminado) |
| H4 | 0.302 | [0.200, 0.401] | IC 95% totalmente ACIMA de zero | 0.031 | [-0.042, 0.119] | IC 95% inclui zero (indeterminado) | 0.015 | [-0.019, 0.052] | IC 95% inclui zero (indeterminado) |
| H5 | 0.345 | [0.226, 0.455] | IC 95% totalmente ACIMA de zero | 0.053 | [-0.002, 0.106] | IC 95% inclui zero (indeterminado) | 0.022 | [-0.017, 0.058] | IC 95% inclui zero (indeterminado) |
| H6 | 0.335 | [0.189, 0.453] | IC 95% totalmente ACIMA de zero | 0.009 | [-0.073, 0.101] | IC 95% inclui zero (indeterminado) | 0.012 | [-0.024, 0.049] | IC 95% inclui zero (indeterminado) |

### 9.3. Contradição entre os desenhos?

Maior `|delta|` observado entre LOYO matched e expanding (mesmos 120 casos, seção 9.2): **0.0146**. Maior divergência observada entre LOYO full e expanding (amostras diferentes, N=240 vs. N=120, seção 9.1): **0.0874**.

Quando o período de avaliação é mantido CONSTANTE (9.2), os deltas ficam substancialmente MENORES que a divergência observada em 9.1 — isto sugere que a maior parte da divergência vista entre LOYO full e expanding é atribuível à diferença de amostra/período (N=240 vs. N=120), não ao desenho de treinamento em si. Leitura descritiva dos números acima, não um teste estatístico de equivalência entre os dois desenhos.
Em ambos os casos, esta seção é descritiva — nunca transforma automaticamente a comparação em teste de significância.

## 10. Limitações

- Warm-up de 10 anos reduz a amostra de avaliação principal de 240 para 120 inicializações por horizonte (perda deliberada de poder estatístico em troca de defensabilidade — protocolo, Seção 5.1).
- A correlação de anomalia do modelo calibrado depende de uma SEGUNDA climatologia causal (do modelo já calibrado), com amostra ainda menor que o bias aditivo — ver coluna 'N p/ anomalia' na seção 4, sempre reportada explicitamente.
- A matriz mês × lead (seção 7) tem N≈10/célula no período principal — amostra pequena demais para qualquer inferência célula a célula; usada só como diagnóstico de heterogeneidade (protocolo, Seção 5.5).
- Avaliação probabilística do ensemble calibrado (CRPSS/BSS) não se aplica nesta implementação — os 24 membros não foram recalibrados individualmente.
- Nenhuma correção operacional de viés foi aplicada — permanece avaliação científica offline.

## 11. Conclusão restrita ao Método 3.1 (correção aditiva)

Esta conclusão vale SOMENTE para a correção aditiva causal por lead × mês-alvo — nunca generalizada para "calibração do CFSv2" em geral, e nunca chamando o modelo de validado ou pronto para produção.

### 11.1. Evidência expanding

- Melhora robusta contra o CFSv2 bruto (`skill_vs_raw`) em TODOS os H1-H6: IC 95% totalmente acima de zero em todos os horizontes (seção 6) — remover o viés aditivo causal melhora de forma consistente sobre o ensemble bruto não corrigido. Isto NÃO é, por si só, o critério de aprovação.
- Contra a climatologia causal (`RMSESS_climatologia`): IC 95% totalmente acima de zero somente em H3 e H5 (seção 6) — nos demais horizontes, o IC inclui zero.
- Contra o `benchmark_anomalia_reconstruida` (`skill_vs_anomalia_reconstruida`): IC 95% totalmente acima de zero somente em H1 (seção 6).
- **Portanto, nenhum horizonte H1-H6 satisfaz simultaneamente os dois critérios estatísticos principais (seção 6.1).**
- H1: único horizonte com evidência de ganho sobre o benchmark de anomalia reconstruída, porém SEM evidência conclusiva de ganho sobre a climatologia causal — nunca descrito como aprovado.

### 11.2. Evidência LOYO

- **LOYO full** (seção 9.1, N=240, 1991-2010): retrospectivo descritivo adicional — amostra DIFERENTE do expanding, nunca comparado diretamente como se fosse só efeito do método de treinamento.
- **LOYO matched** (seção 9.2, N=120, mesmos casos do expanding): comparação metodologicamente justa — isola o efeito do desenho de treinamento do efeito do período de avaliação.
- Maior `|delta|` entre LOYO matched e expanding: 0.0146; maior divergência entre LOYO full e expanding: 0.0874 — ver discussão quantitativa na seção 9.3 sobre se isso indica ou não contradição real entre os desenhos, antes de qualquer conclusão.

### 11.3. Síntese

- Não implementar o método multiplicativo, quantile mapping, MOS ou calibração probabilística nesta atividade — são decisões de uma próxima etapa, condicionadas à revisão independente deste resultado.
- Nenhum horizonte deve ser chamado de "aprovado" nesta rodada quando o critério pré-registrado não for integralmente satisfeito; a leitura correta é que a correção aditiva ainda não demonstrou, para esse(s) horizonte(s), ganho estatisticamente distinguível SIMULTANEAMENTE sobre a climatologia causal e sobre o benchmark de anomalia reconstruída — um resultado válido e informativo, não uma falha de implementação.
