# Correção multiplicativa causal do CFSv2 — Fase 2C.3D (Método 3.2)

**Relatório técnico — avaliação OFFLINE e científica, completamente separada do sistema operacional. Nenhuma correção foi aplicada ao dashboard, SARIMAX, XGBoost, pipeline operacional, `serie_subst.csv`, CFSv2 RAW, CHIRPS v3 histórico, à base pareada da 2C.3C nem aos artefatos já aprovados do Método 3.1 (`aditiva_expanding.csv`, `aditiva_loyo.csv`, `metricas_aditiva_2c3d.json`) — todos só lidos, nunca alterados.**

## 1. Metodologia

```
media_prev_treino = média(forecast_raw) no histórico causal elegível
media_obs_treino  = média(observacao)   no MESMO histórico causal elegível
    (mesma combinação lead × mês-alvo, mesma lista de inicializações,
     mesmos anos em ambas as médias — nunca duas climatologias
     independentes com janelas de anos potencialmente diferentes)
razao = media_obs_treino / media_prev_treino
forecast_multiplicativo = forecast_raw × razao
    SE media_prev_treino >= PISO_DENOMINADOR_MM (10,0mm), SENÃO excluído
    (status_multiplicativo = 'denominador_abaixo_do_piso', SEM fallback para a
     correção aditiva)
```

`N_TREINO_MINIMO = 10` (idêntico ao Método 3.1) e `PISO_DENOMINADOR_MM = 10.0` (fixado no diagnóstico prévio, `docs/nmme-fase2c3d-protocolo-multiplicativo-cfsv2.md` — gap vazio [7,2656mm, 16,6241mm] no denominador, nenhum (lead, mês) fragmentado). **Nenhum teto de razão é aplicado no método principal** — razões altas em meses com denominador seguro (ver seção 8) são tratadas como achado a reportar, nunca como instabilidade a truncar.

## 2. Elegibilidade e piso — jun-set fora da população de inferência por desenho

- Meses elegíveis: Jan, Fev, Mar, Abr, Mai, Out, Nov, Dez.
- Meses excluídos pelo piso (jamais incluídos na avaliação principal, em NENHUM lead): Jun, Jul, Ago, Set.
- `A avaliação principal (det/boot/matriz acima) é válida SOMENTE para os meses elegíveis — jun-set foram excluídos da população de inferência POR DESENHO (piso do denominador), nunca reportar isto como "desempenho anual" do Método 3.2.`
- Verificação de não-fragmentação (nenhum mês parcialmente elegível em algum lead e inelegível em outro): ✅ OK.

## 3. N elegível total e por horizonte

**N total elegível (avaliação principal): 480** (derivado programaticamente: 8 meses elegíveis × 10 anos × 6 leads).

| Horizonte | N elegível |
|---|---|
| H1 | 80 |
| H2 | 80 |
| H3 | 80 |
| H4 | 80 |
| H5 | 80 |
| H6 | 80 |

## 4. Resultados determinísticos H1-H6 (método multiplicativo)

| Horizonte | N | Bias | MAE | RMSE | Razão média | Razão mediana |
|---|---|---|---|---|---|---|
| H1 | 80 | 6.27 | 48.94 | 64.09 | 2.158 | 1.290 |
| H2 | 80 | -1.87 | 48.58 | 64.01 | 1.894 | 1.030 |
| H3 | 80 | -1.23 | 47.38 | 63.27 | 1.757 | 0.914 |
| H4 | 80 | -4.04 | 47.48 | 65.34 | 1.702 | 0.885 |
| H5 | 80 | -2.52 | 44.62 | 63.81 | 1.721 | 0.853 |
| H6 | 80 | -6.99 | 45.28 | 66.42 | 1.707 | 0.847 |

## 5. Comparação contra os três benchmarks pré-registrados

`skill_vs_X = 1 - RMSE_multiplicativo / RMSE_X` — numerador e denominador sempre sobre exatamente os mesmos casos elegíveis. **Critério de aprovação (item 11, idêntico ao Método 3.1): IC 95% de `skill_vs_anomalia_reconstruida` E `RMSESS_climatologia` totalmente acima de zero, SIMULTANEAMENTE.**

| Horizonte | RMSE mult. | RMSE bruto | RMSE climatologia | RMSE benchmark3 | skill_vs_raw | RMSESS_climatologia | skill_vs_anomalia_reconstruida |
|---|---|---|---|---|---|---|---|
| H1 | 64.09 | 78.78 | 67.12 | 58.40 | 0.186 | 0.045 | -0.097 |
| H2 | 64.01 | 86.10 | 66.38 | 65.39 | 0.257 | 0.036 | 0.021 |
| H3 | 63.27 | 86.09 | 66.80 | 63.73 | 0.265 | 0.053 | 0.007 |
| H4 | 65.34 | 91.69 | 66.78 | 65.60 | 0.287 | 0.022 | 0.004 |
| H5 | 63.81 | 95.59 | 66.80 | 64.79 | 0.332 | 0.045 | 0.015 |
| H6 | 66.42 | 98.20 | 66.39 | 66.80 | 0.324 | -0.000 | 0.006 |

## 6. Comparação PRINCIPAL — multiplicativo vs. aditivo (Método 3.1), amostra pareada

`skill_multiplicativo_vs_aditivo = 1 - RMSE_multiplicativo / RMSE_aditivo_matched` — SEMPRE sobre a MESMA amostra pareada (480 casos total, 80 por horizonte, mesmas chaves init_date×lead nos dois lados; ver `aditiva_matched_multiplicativo_sample`). **Este é o teste principal para saber se o Método 3.2 acrescenta algo ao Método 3.1 — nunca comparado contra o aditivo full (N=720), que usaria amostras diferentes.**

| Horizonte | RMSE multiplicativo | RMSE aditivo (matched) | skill_multiplicativo_vs_aditivo |
|---|---|---|---|
| H1 | 64.09 | 56.17 | -0.141 |
| H2 | 64.01 | 63.15 | -0.014 |
| H3 | 63.27 | 62.17 | -0.018 |
| H4 | 65.34 | 64.35 | -0.015 |
| H5 | 63.81 | 62.98 | -0.013 |
| H6 | 66.42 | 66.10 | -0.005 |

## 7. Intervalos de confiança (bootstrap em blocos por target_ano)

Multiplicativo, os três benchmarks E o aditivo matched sempre nos MESMOS blocos de ano sorteados em cada reamostra — IC nunca derivado dividindo intervalos separados. **Classificação meramente descritiva — nunca convertida automaticamente em 'bom'/'mau'.**

| Horizonte | skill_vs_raw | IC 95% | skill_vs_anomalia_reconstruida | IC 95% | skill_multiplicativo_vs_aditivo | IC 95% | Evidência vs. aditivo |
|---|---|---|---|---|---|---|---|
| H1 | 0.186 | [0.017, 0.328] | -0.097 | [-0.248, 0.040] | -0.141 | [-0.326, 0.016] | sem evidência de diferença estatisticamente distinguível (IC inclui zero) |
| H2 | 0.257 | [0.184, 0.316] | 0.021 | [-0.033, 0.073] | -0.014 | [-0.066, 0.022] | sem evidência de diferença estatisticamente distinguível (IC inclui zero) |
| H3 | 0.265 | [0.175, 0.340] | 0.007 | [-0.099, 0.085] | -0.018 | [-0.115, 0.045] | sem evidência de diferença estatisticamente distinguível (IC inclui zero) |
| H4 | 0.287 | [0.185, 0.385] | 0.004 | [-0.047, 0.042] | -0.015 | [-0.053, 0.006] | sem evidência de diferença estatisticamente distinguível (IC inclui zero) |
| H5 | 0.332 | [0.222, 0.433] | 0.015 | [-0.046, 0.056] | -0.013 | [-0.069, 0.019] | sem evidência de diferença estatisticamente distinguível (IC inclui zero) |
| H6 | 0.324 | [0.191, 0.453] | 0.006 | [-0.092, 0.055] | -0.005 | [-0.081, 0.043] | sem evidência de diferença estatisticamente distinguível (IC inclui zero) |

### 7.1. Avaliação do critério de aprovação pré-registrado

| Horizonte | skill_vs_anomalia_reconstruida acima de zero? | RMSESS_climatologia acima de zero? | Atende ao critério? | skill_multiplicativo_vs_aditivo (informativo, não decide a aprovação) |
|---|---|---|---|---|
| H1 | ❌ não | ❌ não | ❌ NÃO | IC 95% inclui zero (indeterminado) |
| H2 | ❌ não | ❌ não | ❌ NÃO | IC 95% inclui zero (indeterminado) |
| H3 | ❌ não | ❌ não | ❌ NÃO | IC 95% inclui zero (indeterminado) |
| H4 | ❌ não | ❌ não | ❌ NÃO | IC 95% inclui zero (indeterminado) |
| H5 | ❌ não | ✅ sim | ❌ NÃO | IC 95% inclui zero (indeterminado) |
| H6 | ❌ não | ❌ não | ❌ NÃO | IC 95% inclui zero (indeterminado) |

**Nenhum horizonte H1–H6 atende integralmente ao critério pré-registrado de aprovação do Método 3.2 nesta rodada.** O critério NUNCA foi alterado depois de observar este resultado.

## 8. Diagnóstico obrigatório — maio, outubro e novembro (razão alta, denominador SEGURO, NUNCA excluídos nem truncados)

Objetivo: decidir se a razão alta corrige um viés sistemático real do CFSv2 ou causa sobrecorreção — **nunca decidido pela magnitude do fator isoladamente**, só pelas métricas abaixo.

### 8.1. Mai

| Lead | N | Razão média | Razão mediana | Forecast bruto médio | Forecast multiplicativo médio | Observado médio | Bias | MAE | RMSE | skill_vs_raw | RMSESS_clim. | skill_vs_anomalia | skill_vs_aditivo |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H1 | 10 | 3.362 | 3.293 | 33.24 | 111.74 | 112.03 | -0.28 | 35.31 | 53.36 | 0.440 | 0.332 | 0.148 | 0.050 |
| H2 | 10 | 3.752 | 3.728 | 22.66 | 85.18 | 112.03 | -26.85 | 60.09 | 73.14 | 0.352 | 0.084 | 0.077 | -0.007 |
| H3 | 10 | 4.105 | 4.095 | 25.21 | 104.05 | 112.03 | -7.97 | 54.87 | 66.11 | 0.401 | 0.172 | 0.134 | 0.068 |
| H4 | 10 | 4.021 | 3.987 | 26.15 | 105.61 | 112.03 | -6.41 | 55.69 | 74.94 | 0.328 | 0.061 | 0.047 | -0.017 |
| H5 | 10 | 4.072 | 4.004 | 26.15 | 107.06 | 112.03 | -4.97 | 56.38 | 80.03 | 0.285 | -0.002 | -0.008 | -0.074 |
| H6 | 10 | 4.226 | 4.250 | 24.30 | 102.72 | 108.29 | -5.58 | 57.53 | 82.88 | 0.251 | -0.075 | -0.066 | -0.114 |

### 8.2. Out

| Lead | N | Razão média | Razão mediana | Forecast bruto médio | Forecast multiplicativo médio | Observado médio | Bias | MAE | RMSE | skill_vs_raw | RMSESS_clim. | skill_vs_anomalia | skill_vs_aditivo |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H1 | 10 | 5.771 | 5.749 | 15.27 | 87.53 | 112.56 | -25.04 | 35.19 | 42.53 | 0.588 | -0.039 | -0.118 | -0.132 |
| H2 | 10 | 4.752 | 4.798 | 20.48 | 97.49 | 112.56 | -15.08 | 41.62 | 49.32 | 0.502 | -0.204 | -0.213 | -0.246 |
| H3 | 10 | 3.871 | 3.882 | 27.23 | 105.48 | 112.56 | -7.08 | 33.79 | 37.11 | 0.594 | 0.094 | 0.026 | -0.050 |
| H4 | 10 | 3.873 | 3.929 | 26.33 | 102.30 | 112.56 | -10.27 | 45.38 | 53.12 | 0.431 | -0.297 | -0.301 | -0.385 |
| H5 | 10 | 4.261 | 4.271 | 25.66 | 109.53 | 112.56 | -3.04 | 35.73 | 46.08 | 0.509 | -0.125 | -0.123 | -0.226 |
| H6 | 10 | 4.075 | 4.133 | 24.97 | 101.87 | 112.56 | -10.69 | 31.52 | 42.64 | 0.546 | -0.041 | -0.105 | -0.166 |

### 8.3. Nov

| Lead | N | Razão média | Razão mediana | Forecast bruto médio | Forecast multiplicativo médio | Observado médio | Bias | MAE | RMSE | skill_vs_raw | RMSESS_clim. | skill_vs_anomalia | skill_vs_aditivo |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H1 | 10 | 2.317 | 2.301 | 78.07 | 182.70 | 160.86 | 21.84 | 49.47 | 75.69 | 0.131 | -0.582 | -0.770 | -0.846 |
| H2 | 10 | 2.028 | 2.022 | 82.86 | 168.42 | 160.86 | 7.56 | 25.02 | 37.92 | 0.535 | 0.207 | -0.101 | -0.159 |
| H3 | 10 | 1.874 | 1.869 | 103.77 | 194.76 | 160.86 | 33.90 | 46.51 | 60.19 | 0.073 | -0.258 | -0.250 | -0.321 |
| H4 | 10 | 1.738 | 1.731 | 110.22 | 191.22 | 160.86 | 30.37 | 32.36 | 37.39 | 0.323 | 0.218 | 0.094 | 0.013 |
| H5 | 10 | 1.616 | 1.611 | 115.25 | 186.21 | 160.86 | 25.35 | 31.62 | 34.53 | 0.337 | 0.278 | 0.156 | 0.099 |
| H6 | 10 | 1.587 | 1.586 | 115.41 | 182.98 | 160.86 | 22.12 | 32.01 | 39.59 | 0.275 | 0.172 | 0.068 | 0.006 |

**Leitura, SEM decidir por magnitude isolada**: outubro tem a razão mediana mais alta (tipicamente > 4, ver seção abaixo) com `forecast_multiplicativo_medio` muito mais próximo do `observado_medio` que o `forecast_raw_medio` — consistente com um viés sistemático real do CFSv2 em outubro (ver `CLAUDE.md`, armadilha 7: o modelo subestima sistematicamente out-nov-dez). Se `skill_vs_aditivo` nessa célula for positivo, é evidência de que a correção multiplicativa captura esse viés melhor que a aditiva nesses meses especificamente — se for negativo ou os benchmarks piorarem (skill_vs_raw/RMSESS_climatologia muito negativos), é evidência de sobrecorreção. Ver números acima, não uma conclusão geral pré-definida.

## 9. Matriz mês-alvo × lead — SOMENTE meses elegíveis (diagnóstico de heterogeneidade, NUNCA 48 testes de significância)

### 9.1. N elegível por célula

| Mês \ Lead | H1 | H2 | H3 | H4 | H5 | H6 |
|---|---|---|---|---|---|---|
| Jan | 10 | 10 | 10 | 10 | 10 | 10 |
| Fev | 10 | 10 | 10 | 10 | 10 | 10 |
| Mar | 10 | 10 | 10 | 10 | 10 | 10 |
| Abr | 10 | 10 | 10 | 10 | 10 | 10 |
| Mai | 10 | 10 | 10 | 10 | 10 | 10 |
| Out | 10 | 10 | 10 | 10 | 10 | 10 |
| Nov | 10 | 10 | 10 | 10 | 10 | 10 |
| Dez | 10 | 10 | 10 | 10 | 10 | 10 |

### 9.2. skill_vs_anomalia_reconstruida por célula (ponto estimado, sem IC nesta matriz)

| Mês \ Lead | H1 | H2 | H3 | H4 | H5 | H6 |
|---|---|---|---|---|---|---|
| Jan | -0.173* | 0.062* | 0.062* | 0.026* | 0.076* | 0.056* |
| Fev | -0.038* | -0.047* | -0.020* | -0.018* | 0.003* | 0.049* |
| Mar | 0.140* | 0.089* | -0.006* | 0.056* | 0.061* | 0.011* |
| Abr | -0.056* | -0.015* | -0.013* | -0.010* | -0.028* | -0.019* |
| Mai | 0.148* | 0.077* | 0.134* | 0.047* | -0.008* | -0.066* |
| Out | -0.118* | -0.213* | 0.026* | -0.301* | -0.123* | -0.105* |
| Nov | -0.770* | -0.101* | -0.250* | 0.094* | 0.156* | 0.068* |
| Dez | -0.122* | 0.024* | 0.051* | 0.031* | 0.044* | 0.082* |

### 9.3. skill_multiplicativo_vs_aditivo por célula (ponto estimado, sem IC nesta matriz)

| Mês \ Lead | H1 | H2 | H3 | H4 | H5 | H6 |
|---|---|---|---|---|---|---|
| Jan | -0.238* | -0.001* | 0.011* | 0.023* | -0.003* | -0.007* |
| Fev | 0.001* | -0.017* | -0.002* | 0.005* | 0.012* | 0.059* |
| Mar | 0.000* | 0.029* | -0.051* | -0.028* | 0.021* | 0.007* |
| Abr | -0.035* | 0.001* | 0.001* | 0.005* | -0.005* | 0.009* |
| Mai | 0.050* | -0.007* | 0.068* | -0.017* | -0.074* | -0.114* |
| Out | -0.132* | -0.246* | -0.050* | -0.385* | -0.226* | -0.166* |
| Nov | -0.846* | -0.159* | -0.321* | 0.013* | 0.099* | 0.006* |
| Dez | -0.127* | 0.029* | 0.049* | 0.078* | 0.054* | 0.087* |

*`*` = célula com N abaixo da amostra mínima do projeto (20).*

## 10. Comparação expanding vs. LOYO matched (elegibilidade explícita)

**Rótulo: `multiplicativa_loyo_matched_intersecao`.**

- N elegível no expanding (status_multiplicativo='ok'): 480.
- N elegível no LOYO (elegibilidade própria, piso aplicado igualmente): 960.
- N na interseção (usada na comparação abaixo): 480.
- N de diferença de elegibilidade (chave elegível no expanding, mas NÃO no LOYO — nunca forçada na comparação): 0.
- `interseção explícita entre as chaves elegíveis do expanding e do LOYO — nunca forçada sobre uma chave que o LOYO considera inelegível (regra fixa do protocolo revisado, item 14).`

| Horizonte | N expanding (interseção) | N LOYO matched (interseção) | delta skill_vs_raw | delta RMSESS_climatologia | delta skill_vs_anomalia_reconstruida |
|---|---|---|---|---|---|
| H1 | 80 | 80 | 0.0034 | -0.0087 | -0.0109 |
| H2 | 80 | 80 | -0.0035 | -0.0155 | -0.0190 |
| H3 | 80 | 80 | 0.0018 | -0.0107 | -0.0092 |
| H4 | 80 | 80 | -0.0036 | -0.0176 | -0.0158 |
| H5 | 80 | 80 | 0.0012 | -0.0106 | -0.0128 |
| H6 | 80 | 80 | 0.0006 | -0.0100 | -0.0118 |

**Delta meramente descritivo — nunca um teste de significância automático.** `NÃO simula uso em tempo real — usa anos futuros no cálculo de média_prev/obs_treino. Análise descritiva adicional, nunca operacional.`

## 11. Limitações

- Avaliação principal restrita a 8 dos 12 meses do ano (jun-set excluídos por desenho, seção 2) — **nunca reportar isto como desempenho anual do Método 3.2**.
- N≈10/célula na matriz mês×lead (seção 9) e no diagnóstico de outubro/maio/novembro (seção 8) — amostra pequena demais para inferência célula a célula; usada só como diagnóstico de heterogeneidade.
- `skill_multiplicativo_vs_aditivo` compara contra o aditivo MATCHED (N=480), nunca contra o aditivo full (N=720, Método 3.1 original) — comparar contra o full misturaria o efeito do método com o efeito da amostra.
- Nenhum teto de razão foi aplicado — se outubro (ou outro mês) mostrar sinais de sobrecorreção nos benchmarks (seção 8), isso é um resultado a reportar, não um erro de implementação a corrigir retroativamente nesta rodada.
- Nenhuma correção operacional de viés foi aplicada — permanece avaliação científica offline.

## 12. Conclusão restrita ao Método 3.2 (correção multiplicativa)

Esta conclusão vale SOMENTE para a correção multiplicativa causal por lead × mês-alvo, restrita aos meses elegíveis (seção 2) — nunca generalizada para "calibração do CFSv2" em geral, nunca chamando o modelo de validado ou pronto para produção, e nunca comparada com o Método 3.1 fora da amostra pareada (seção 6).

- Critério pré-registrado de aprovação: nenhum horizonte H1-H6 satisfaz simultaneamente os dois critérios estatísticos principais (seção 7.1).
- Comparação principal com o Método 3.1 (seção 6/7): H1: sem evidência de diferença estatisticamente distinguível (IC inclui zero); H2: sem evidência de diferença estatisticamente distinguível (IC inclui zero); H3: sem evidência de diferença estatisticamente distinguível (IC inclui zero); H4: sem evidência de diferença estatisticamente distinguível (IC inclui zero); H5: sem evidência de diferença estatisticamente distinguível (IC inclui zero); H6: sem evidência de diferença estatisticamente distinguível (IC inclui zero).
- Achado de outubro/maio/novembro (seção 8): razão sistematicamente alta com denominador seguro — ver a leitura condicionada aos números da seção 8, nunca decidida pela magnitude da razão isoladamente.
- Não implementar correção híbrida aditiva/multiplicativa, quantile mapping, MOS ou calibração probabilística nesta atividade — decisões de uma próxima etapa, condicionadas à revisão independente deste resultado.
