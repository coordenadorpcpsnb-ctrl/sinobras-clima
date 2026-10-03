# Validação científica retrospectiva do CFSv2 — Fase 2C.3C

**Relatório técnico — completamente separado do sistema operacional. Nenhuma métrica aqui é apresentada no dashboard de produção. Referência observacional exclusiva: `data/chirps_v3_historico/chirps_v3_1981_2011.csv` (365 meses, Fase 2C.3B) — `data/serie_subst.csv` e `data/chirps_1981_2025.csv` NÃO foram usados como referência principal em nenhum cálculo.**

**Revisão 2C.3C (refinamentos pré-merge):** esta versão substitui a definição de anomalia usada até o commit anterior (que subtraía a MESMA climatologia observada dos dois lados) por uma climatologia PRÓPRIA do modelo, sem leakage, específica por lead e mês-alvo. A versão antiga foi mantida apenas como diagnóstico explícito, nunca como a anomaly correlation principal. Também foram adicionados: IC 95% dos skill scores (RMSESS/CRPSS/BSS) via bootstrap pareado (modelo e climatologia nos MESMOS blocos), a matriz mês-alvo × lead como visão sazonal principal, e a frequência observada das categorias de tercil como contexto do Brier Score.

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

H1 é a previsão do **mês corrente** (H1 — previsão do mês corrente) — nunca tratado como horizonte futuro e nunca chamado de "nowcast" sem data de emissão/disponibilidade comprovada. H1 é tratado separadamente, nunca agregado com H2-H6 (horizontes futuros) numa métrica única.

### 3.1. Precipitação absoluta e anomalia DIAGNÓSTICO (climatologia observada nos dois lados)

**Esta subseção é diagnóstico, não a anomaly correlation principal** — ver 3.2. Subtrair a MESMA climatologia (observada) da previsão e da observação só remove o ciclo sazonal compartilhado; não remove o viés sistemático próprio do CFSv2. Por isso bias/MAE/RMSE/RMSESS são idênticos aos da coluna absoluta (erro = previsto-observado é invariante a essa translação) — só a correlação muda, porque depende da variância de cada série.

| Horizonte | N | Bias (abs, mm) | MAE (abs, mm) | RMSE (abs, mm) | Corr (abs) | Corr (anomalia diagnóstico) | RMSESS (abs) | RMSESS (anomalia diagnóstico) |
|---|---|---|---|---|---|---|---|---|
| H1 | 240 | -37.83 | 52.47 | 71.81 | 0.833 | 0.409 | -0.225 | -0.225 |
| H2 | 240 | -17.27 | 54.05 | 74.80 | 0.801 | 0.170 | -0.278 | -0.278 |
| H3 | 240 | -5.72 | 55.74 | 77.33 | 0.811 | 0.139 | -0.316 | -0.316 |
| H4 | 240 | 0.70 | 59.52 | 80.92 | 0.811 | 0.134 | -0.379 | -0.379 |
| H5 | 240 | 5.83 | 61.60 | 84.93 | 0.808 | 0.105 | -0.447 | -0.447 |
| H6 | 240 | 7.85 | 63.38 | 87.15 | 0.807 | 0.096 | -0.491 | -0.491 |

### 3.2. Anomalia CORRIGIDA pela climatologia própria do modelo — PRINCIPAL

`anomalia_modelo = previsao_ensemble_mean - climatologia_do_modelo(lead, mês-alvo, só inicializações < init_date atual)`; `anomalia_observada = observacao_CHIRPS - climatologia_observada`. Esta é a anomaly correlation que deve ser citada como principal daqui em diante — a subseção 3.1 existe só como diagnóstico de quanto o viés sistemático do modelo estava inflando/distorcendo a leitura anterior.

| Horizonte | N com climatologia do modelo disponível | Bias corrigido (mm) | MAE corrigido (mm) | RMSE corrigido (mm) | Corr (anomalia corrigida) | RMSESS (anomalia corrigida) |
|---|---|---|---|---|---|---|
| H1 | 228 | 9.32 | 40.05 | 56.21 | 0.403 | 0.045 |
| H2 | 228 | 6.28 | 42.55 | 61.45 | 0.136 | -0.044 |
| H3 | 228 | 6.29 | 41.10 | 59.60 | 0.165 | -0.011 |
| H4 | 228 | 4.96 | 39.55 | 57.72 | 0.214 | 0.008 |
| H5 | 228 | 5.78 | 40.24 | 58.95 | 0.154 | -0.020 |
| H6 | 228 | 3.73 | 39.86 | 58.83 | 0.157 | -0.018 |

**Fórmula do skill score:** `RMSESS = 1 - RMSE_modelo / RMSE_climatologia` — positivo significa que o modelo erra MENOS que a climatologia expansível (benchmark, calculada sem leakage); negativo significa que a climatologia sozinha seria uma previsão melhor. **Nenhum valor aqui deve ser lido como 'bom' ou 'mau' isoladamente** — ver a seção 6b (intervalos de confiança dos skill scores) antes de qualquer conclusão.

A correlação cai da precipitação absoluta (3.1, coluna 'abs') para qualquer versão de anomalia em todos os horizontes — esperado: parte da correlação absoluta é só o ciclo sazonal regional (out-abr chuvoso, jun-ago seco) que tanto o modelo quanto a climatologia capturam trivialmente. Note que a correlação em anomalia CORRIGIDA (3.2) não é sistematicamente maior nem menor que a diagnóstico (3.1) — em H1 é praticamente igual, em H3-H6 é MAIOR; isso é o esperado quando se remove um viés próprio do modelo que varia com o lead, não um artefato.

## 4. Avaliação sazonal — matriz mês-alvo × lead (PRINCIPAL) e grupo sazonal × lead

Cada célula da matriz mês × lead tem N≈20 (uma observação por ano de inicialização elegível) — amostra pequena por desenho. **Nenhuma inferência forte deve ser feita célula a célula**; células marcadas com `*` têm N abaixo do mínimo (20) definido para este projeto. A visão por grupo sazonal (chuvosa/transição/seca) agrega células adjacentes só para reduzir ruído de amostra pequena — não substitui a matriz mês × lead.

### 4.1. Matriz mês-alvo × lead — N por célula

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

### 4.2. Matriz mês-alvo × lead — RMSESS (ponto estimado, sem IC nesta matriz)

| Mês \ Lead | H1 | H2 | H3 | H4 | H5 | H6 |
|---|---|---|---|---|---|---|
| Jan | -0.193 | -0.021 | -0.123 | -0.108 | -0.202 | -0.278 |
| Fev | 0.104 | -0.045 | -0.279 | -0.510 | -0.519 | -0.659 |
| Mar | 0.320 | -0.223 | -0.293 | -0.564 | -0.764 | -0.733 |
| Abr | -0.019 | 0.019 | 0.008 | 0.033 | 0.127 | 0.062 |
| Mai | -0.195 | -0.380 | -0.383 | -0.400 | -0.413 | -0.459 |
| Jun | -0.005 | -0.041 | -0.038 | -0.077 | -0.091 | -0.099 |
| Jul | -0.061 | -0.057 | -0.068 | 0.065 | -0.021 | -0.045 |
| Ago | -0.162 | -0.141 | -0.087 | -0.108 | -0.065 | -0.076 |
| Set | -0.572 | -0.504 | -0.507 | -0.541 | -0.529 | -0.500 |
| Out | -0.841 | -0.754 | -0.646 | -0.676 | -0.705 | -0.692 |
| Nov | -0.867 | -0.688 | -0.626 | -0.467 | -0.405 | -0.347 |
| Dez | -0.654 | -0.679 | -0.697 | -0.601 | -1.098 | -1.341 |

### 4.3. Matriz mês-alvo × lead — correlação de anomalia corrigida (climatologia própria do modelo)

| Mês \ Lead | H1 | H2 | H3 | H4 | H5 | H6 |
|---|---|---|---|---|---|---|
| Jan | 0.214 | 0.010 | 0.108 | 0.257 | 0.105 | 0.181 |
| Fev | 0.386 | 0.416 | 0.333 | 0.351 | 0.321 | 0.250 |
| Mar | 0.812 | -0.010 | 0.388 | 0.092 | 0.154 | 0.196 |
| Abr | 0.576 | 0.167 | 0.110 | 0.226 | 0.488 | 0.248 |
| Mai | 0.820 | 0.310 | 0.269 | 0.116 | -0.206 | -0.229 |
| Jun | 0.406 | 0.232 | 0.493 | -0.015 | 0.141 | 0.052 |
| Jul | 0.566 | 0.026 | -0.138 | 0.251 | 0.140 | 0.033 |
| Ago | 0.276 | 0.010 | 0.408 | 0.106 | 0.189 | 0.337 |
| Set | 0.263 | 0.306 | 0.072 | 0.130 | -0.045 | 0.145 |
| Out | 0.376 | 0.287 | 0.378 | 0.151 | 0.237 | 0.428 |
| Nov | 0.604 | 0.633 | 0.157 | 0.384 | 0.265 | 0.401 |
| Dez | 0.060 | -0.404 | -0.344 | 0.007 | -0.469 | -0.216 |

*`*` = célula com N abaixo da amostra mínima do projeto (20).*

### 4.4. Resumo por grupo sazonal regional (CLAUDE.md) × lead

| Grupo | Métrica | H1 | H2 | H3 | H4 | H5 | H6 |
|---|---|---|---|---|---|---|---|
| chuvosa | N | 140 | 140 | 140 | 140 | 140 | 140 |
| chuvosa | RMSESS | -0.214 | -0.253 | -0.299 | -0.371 | -0.452 | -0.498 |
| chuvosa | Corr anomalia corrigida | 0.411 | 0.139 | 0.168 | 0.227 | 0.176 | 0.169 |
| transicao | N | 40 | 40 | 40 | 40 | 40 | 40 |
| transicao | RMSESS | -0.283 | -0.407 | -0.410 | -0.431 | -0.438 | -0.468 |
| transicao | Corr anomalia corrigida | 0.678 | 0.196 | 0.189 | 0.111 | -0.126 | -0.104 |
| seca | N | 60 | 60 | 60 | 60 | 60 | 60 |
| seca | RMSESS | -0.109 | -0.105 | -0.071 | -0.084 | -0.069 | -0.080 |
| seca | Corr anomalia corrigida | 0.321 | 0.086 | 0.311 | 0.099 | 0.156 | 0.234 |

### 4.5. Visão agregada mensal descritiva (SECUNDÁRIA — H1 a H6 combinados)

**Rótulo: `visao_agregada_descritiva_H1_a_H6_combinados`.** Mantida só como visão descritiva de referência — a matriz 4.1-4.3 é a análise sazonal principal porque não mistura lead times diferentes dentro da mesma célula.

| Mês | Grupo sazonal | N | Bias | MAE | RMSE | Corr abs | Corr anomalia corrigida | RMSESS |
|---|---|---|---|---|---|---|---|---|
| Jan | chuvosa | 120 | 30.34 | 77.88 | 93.34 | 0.107 | 0.144 | -0.157 |
| Fev | chuvosa | 120 | 61.73 | 81.92 | 98.51 | 0.270 | 0.339 | -0.353 |
| Mar | chuvosa | 120 | 85.63 | 106.68 | 123.48 | 0.183 | 0.280 | -0.423 |
| Abr | chuvosa | 120 | -8.40 | 62.04 | 81.07 | 0.258 | 0.323 | 0.037 |
| Mai | transicao | 120 | -78.15 | 78.25 | 98.58 | 0.312 | 0.310 | -0.373 |
| Jun | seca | 120 | -4.91 | 5.64 | 10.41 | 0.222 | 0.230 | -0.059 |
| Jul | seca | 120 | -2.43 | 2.70 | 5.57 | 0.099 | 0.106 | -0.032 |
| Ago | seca | 120 | -8.47 | 8.96 | 15.68 | 0.157 | 0.199 | -0.107 |
| Set | transicao | 120 | -45.78 | 45.79 | 56.82 | 0.136 | 0.137 | -0.526 |
| Out | chuvosa | 120 | -81.91 | 81.91 | 87.71 | 0.267 | 0.301 | -0.720 |
| Nov | chuvosa | 120 | -78.95 | 80.60 | 96.39 | 0.338 | 0.411 | -0.577 |
| Dez | chuvosa | 120 | 38.42 | 61.17 | 75.00 | -0.127 | -0.203 | -0.866 |

| Grupo | N | Bias | MAE | RMSE | Corr abs | Corr anomalia corrigida | RMSESS |
|---|---|---|---|---|---|---|---|
| chuvosa | 840 | 6.69 | 78.89 | 94.75 | 0.563 | 0.226 | -0.352 |
| transicao | 240 | -61.96 | 62.02 | 80.46 | 0.515 | 0.249 | -0.407 |
| seca | 360 | -5.27 | 5.77 | 11.33 | 0.203 | 0.186 | -0.086 |

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

**Fórmulas:** `CRPSS = 1 - CRPS_modelo / CRPS_climatologia_probabilistica` — `BSS = 1 - BS_modelo / BS_referencia_climatologica (p=1/3, BS_ref=2/9) — REFERÊNCIA PRINCIPAL, nunca alterada silenciosamente.`. **O Brier Score de referência nominal (p=1/3) é a referência PRINCIPAL e nunca é alterada silenciosamente** — a seção 5.1 só complementa.

### 5.1. Frequência observada das categorias e sensibilidade do Brier/BSS

A referência nominal do Brier Score (seção 5) assume 1/3 de probabilidade climatológica para cada categoria (seco/normal/úmido) por desenho — nunca alterada. A tabela abaixo mostra a frequência EFETIVAMENTE observada de cada categoria nesta amostra, que pode divergir de 1/3 por tamanho de amostra finito e empates nos limiares de tercil.

| Horizonte | Freq. observada seco | Freq. observada normal | Freq. observada úmido |
|---|---|---|---|
| H1 | 0.417 | 0.283 | 0.300 |
| H2 | 0.417 | 0.287 | 0.296 |
| H3 | 0.417 | 0.283 | 0.300 |
| H4 | 0.417 | 0.287 | 0.296 |
| H5 | 0.417 | 0.287 | 0.296 |
| H6 | 0.417 | 0.287 | 0.296 |

**BSS de sensibilidade (climatologia empírica causal, em vez do nominal 1/3) — NUNCA substitui o BSS nominal da seção 5, só complementa:**

| Horizonte | BSS sens. seco | BSS sens. normal | BSS sens. úmido |
|---|---|---|---|
| H1 | -0.333 | -0.149 | -0.073 |
| H2 | -0.311 | -0.067 | -0.185 |
| H3 | -0.285 | -0.090 | -0.226 |
| H4 | -0.289 | -0.071 | -0.287 |
| H5 | -0.330 | -0.125 | -0.399 |
| H6 | -0.378 | -0.121 | -0.440 |

### Rank histogram (posição da observação entre os 24 membros ordenados, 1-25)

- H1: 1:1, 3:4, 4:3, 5:4, 6:1, 7:3, 8:4, 9:1, 10:3, 11:2, 12:8, 13:3, 14:3, 15:9, 16:3, 17:6, 18:9, 19:5, 20:11, 21:12, 22:11, 23:18, 24:33, 25:83
- H2: 1:7, 2:6, 3:2, 4:5, 5:3, 6:5, 7:2, 8:6, 9:5, 10:2, 11:7, 12:8, 13:4, 14:7, 15:7, 16:8, 17:6, 18:5, 19:7, 20:10, 21:13, 22:14, 23:22, 24:21, 25:58
- H3: 1:9, 2:7, 3:7, 4:3, 5:5, 6:7, 7:7, 8:7, 9:2, 10:4, 11:7, 12:7, 13:5, 14:5, 15:7, 16:7, 17:6, 18:3, 19:8, 20:8, 21:12, 22:15, 23:17, 24:20, 25:55
- H4: 1:16, 2:11, 3:4, 4:8, 5:9, 6:1, 7:5, 8:7, 9:1, 10:4, 11:7, 12:8, 13:5, 14:3, 15:5, 16:1, 17:7, 18:11, 19:11, 20:7, 21:10, 22:14, 23:15, 24:26, 25:44
- H5: 1:19, 2:11, 3:7, 4:7, 5:5, 6:3, 7:1, 8:6, 9:8, 10:7, 11:4, 12:3, 13:4, 14:2, 15:6, 16:7, 17:11, 18:6, 19:8, 20:5, 21:13, 22:9, 23:15, 24:16, 25:57
- H6: 1:26, 2:7, 3:8, 4:5, 5:1, 6:4, 7:8, 8:7, 9:6, 10:3, 11:1, 12:5, 13:5, 14:4, 15:3, 16:8, 17:6, 18:6, 19:14, 20:3, 21:12, 22:15, 23:21, 24:17, 25:45

## 6. Intervalos de confiança (bootstrap em blocos por ano, nunca linhas independentes)

O mesmo `target_month` aparece em vários horizontes/inicializações — as observações NÃO são independentes. O IC 95% usa reamostragem em blocos por ANO do target_month (nunca bootstrap de linhas soltas, que subestimaria a incerteza real).

### 6.1. Bias/MAE/RMSE absolutos

| Horizonte | RMSE | IC 95% | MAE | IC 95% | Bias | IC 95% |
|---|---|---|---|---|---|---|
| H1 | 71.81 | [65.12, 78.34] | 52.47 | [48.27, 56.60] | -37.83 | [-44.04, -30.92] |
| H2 | 74.80 | [68.08, 80.79] | 54.05 | [49.48, 58.33] | -17.27 | [-23.78, -11.02] |
| H3 | 77.33 | [68.13, 86.60] | 55.74 | [49.15, 63.05] | -5.72 | [-9.66, -1.47] |
| H4 | 80.92 | [73.04, 88.89] | 59.52 | [53.82, 65.56] | 0.70 | [-3.17, 4.49] |
| H5 | 84.93 | [76.67, 93.53] | 61.60 | [55.58, 68.17] | 5.83 | [1.67, 10.40] |
| H6 | 87.15 | [78.33, 95.88] | 63.38 | [56.85, 70.62] | 7.85 | [4.10, 11.83] |

### 6.2. Intervalos de confiança dos skill scores (RMSESS, CRPSS, BSS) — PRINCIPAL para interpretação de habilidade

Diferente da seção 6.1, aqui o bootstrap reamostra os MESMOS blocos (mesmos anos sorteados) para recalcular modelo E climatologia a cada reamostra — garante que RMSESS/CRPSS/BSS sejam proporções válidas a cada iteração, em vez de dividir dois ICs calculados de forma independente. **A classificação abaixo nunca é 'bom'/'mau' — só indica se o IC 95% está totalmente acima de zero, inclui zero, ou totalmente abaixo de zero.**

| Horizonte | RMSESS | IC 95% | Classificação | CRPSS | IC 95% | Classificação |
|---|---|---|---|---|---|---|
| H1 | -0.225 | [-0.329, -0.143] | IC 95% totalmente ABAIXO de zero | -0.519 | [-0.652, -0.416] | IC 95% totalmente ABAIXO de zero |
| H2 | -0.278 | [-0.387, -0.194] | IC 95% totalmente ABAIXO de zero | -0.490 | [-0.616, -0.380] | IC 95% totalmente ABAIXO de zero |
| H3 | -0.316 | [-0.479, -0.159] | IC 95% totalmente ABAIXO de zero | -0.487 | [-0.672, -0.304] | IC 95% totalmente ABAIXO de zero |
| H4 | -0.379 | [-0.518, -0.244] | IC 95% totalmente ABAIXO de zero | -0.569 | [-0.739, -0.400] | IC 95% totalmente ABAIXO de zero |
| H5 | -0.447 | [-0.592, -0.307] | IC 95% totalmente ABAIXO de zero | -0.656 | [-0.831, -0.479] | IC 95% totalmente ABAIXO de zero |
| H6 | -0.491 | [-0.626, -0.340] | IC 95% totalmente ABAIXO de zero | -0.707 | [-0.897, -0.508] | IC 95% totalmente ABAIXO de zero |

**BSS por categoria, com IC 95% (mesmos blocos do bootstrap acima):**

| Horizonte | BSS seco | IC 95% | BSS normal | IC 95% | BSS úmido | IC 95% |
|---|---|---|---|---|---|---|
| H1 | -0.485 | [-0.700, -0.304] | -0.055 | [-0.241, 0.122] | -0.034 | [-0.185, 0.139] |
| H2 | -0.460 | [-0.653, -0.295] | 0.014 | [-0.134, 0.160] | -0.134 | [-0.312, 0.049] |
| H3 | -0.430 | [-0.640, -0.220] | 0.003 | [-0.182, 0.183] | -0.180 | [-0.398, 0.056] |
| H4 | -0.433 | [-0.638, -0.213] | 0.012 | [-0.146, 0.193] | -0.233 | [-0.446, -0.018] |
| H5 | -0.478 | [-0.755, -0.264] | -0.036 | [-0.223, 0.137] | -0.341 | [-0.560, -0.096] |
| H6 | -0.529 | [-0.742, -0.310] | -0.035 | [-0.219, 0.146] | -0.382 | [-0.582, -0.174] |

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

## 8. Interpretação — separada por dimensão, nunca uma conclusão única

Esta seção separa deliberadamente SEIS leituras DIFERENTES — nunca resumidas numa frase como "modelo validado" ou "boa habilidade":

1. **Precipitação absoluta** — correlação alta (0.80-0.83) em todos os horizontes, mas dominada pelo ciclo sazonal regional (chuva concentrada out-abr); não é medida de habilidade preditiva real.
2. **Anomalia corrigida pela climatologia própria do modelo (seção 3.2, PRINCIPAL)** — correlação entre 0,14 e 0,40 (H2 mais baixa, H4 mais alta — não monotônica com o lead, diferente do padrão da versão diagnóstico). Ao remover o viés sistemático próprio do CFSv2 (em vez de só o ciclo sazonal compartilhado), a leitura muda qualitativamente em relação à versão diagnóstico anterior: bias e RMSE caem fortemente (ex.: RMSE de H1 cai de ~72mm para ~56mm), e a correlação em H3-H6 fica MAIOR que na versão diagnóstico — evidência de que parte do que parecia 'sem skill' na versão anterior era viés sistemático do modelo, não ausência de sinal.
3. **Skill relativo à climatologia (RMSESS/CRPSS, seção 6.2)** — ponto estimado ainda negativo em todos os horizontes tanto para RMSESS quanto CRPSS, e os ICs 95% calculados nesta revisão (bootstrap pareado, mesmos blocos) ficaram TOTALMENTE ABAIXO de zero em todos os H1-H6 testados — ou seja, a incerteza amostral não muda a conclusão de que a climatologia expansível sem leakage teve erro MENOR que o ensemble bruto do CFSv2 nesta amostra. Isso é mais forte que apenas 'o ponto estimado é negativo': a faixa de incerteza também não inclui zero.
4. **Probabilístico (CRPSS/BSS, seções 5 e 6.2)** — predominantemente negativo, consistente com o item 3; a seção 5.1 mostra que a frequência observada de 'seco' (~41,7% em H1) se desvia do nominal 1/3, contexto relevante para a leitura do Brier Score mas que não altera a referência nominal.
5. **Dependência com o lead** — RMSESS (ponto estimado) piora monotonicamente de H1 (-0,22) a H6 (-0,49); a anomalia corrigida NÃO segue o mesmo padrão monotônico (ver item 2) — os dois fenômenos (skill relativo à climatologia vs. correlação de anomalia) respondem de forma diferente ao aumento do lead, e não devem ser lidos como a mesma coisa.
6. **Dependência com a época do ano (seção 4)** — a matriz mês × lead mostra variação relevante célula a célula (N≈20/célula), mas qualquer leitura por mês isolado deve considerar a amostra pequena; o resumo por grupo sazonal (4.4) suaviza esse ruído sem substituir a matriz completa.

**O ensemble bruto aqui avaliado (`forecast_prec_mm`, sem qualquer correção operacional de viés ou downscaling) não deve ser confundido com um produto operacional corrigido — esta é avaliação científica do RAW, nenhuma correção de viés foi aplicada nesta fase.** Nenhuma das seis leituras acima, isoladamente, autoriza uma conclusão geral de habilidade. Qualquer decisão sobre uso operacional do CFSv2 deve revisar conjuntamente: magnitude do skill, intervalo de confiança (seção 6.2), horizonte, época do ano (seção 4) e tamanho da amostra (N=240 inicializações, mas com dependência temporal relevante — daí o bootstrap em blocos).

## Restrições respeitadas

- Dashboard, SARIMAX, XGBoost, pipeline operacional, série de produção e dados RAW do CFSv2 não foram alterados.
- Nenhuma correção operacional de viés foi aplicada — esta fase permanece avaliação científica do ensemble RAW.
- Nenhuma métrica desta fase é apresentada automaticamente no dashboard de produção.
- `serie_subst.csv`/`chirps_1981_2025.csv` não foram usados como referência principal em nenhum cálculo.
- Testes de controle de leakage (climatologia observada, climatologia do modelo, tercis, pareamento, mistura de membros, demonstração sintética das duas definições de anomalia) executados e aprovados antes do cálculo das métricas — ver `tests/test_cfsv2_validacao_cientifica.py`.
