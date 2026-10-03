# Validação científica retrospectiva do CFSv2 — Fase 2C.3C

**Relatório técnico — completamente separado do sistema operacional. Nenhuma métrica aqui é apresentada no dashboard de produção. Referência observacional exclusiva: `data/chirps_v3_historico/chirps_v3_1981_2011.csv` (365 meses, Fase 2C.3B) — `data/serie_subst.csv` e `data/chirps_1981_2025.csv` NÃO foram usados como referência principal em nenhum cálculo.**

**Revisão 2C.3C (refinamentos pré-merge):** esta versão substitui a definição de anomalia usada até o commit anterior (que subtraía a MESMA climatologia observada dos dois lados) por uma climatologia PRÓPRIA do modelo, sem leakage, específica por lead e mês-alvo. A versão antiga foi mantida apenas como diagnóstico explícito, nunca como a anomaly correlation principal. Também foram adicionados: IC 95% dos skill scores (RMSESS/CRPSS/BSS) via bootstrap pareado (modelo e climatologia nos MESMOS blocos), a matriz mês-alvo × lead como visão sazonal principal, e a frequência observada das categorias de tercil como contexto do Brier Score.

**Segunda revisão (dois pontos finais pré-merge):** (1) o BS da referência nominal do BSS (p=1/3) deixou de assumir a constante 2/9 — agora é calculado `mean((1/3 - o_i)^2)` sobre as MESMAS observações da amostra avaliada, por horizonte e categoria (a previsão nominal em si continua 1/3; só o cálculo do seu BS passou a ser exato); (2) o RMSESS da anomalia CORRIGIDA (seção 3.2) ganhou IC 95% próprio (seção 6.3), bootstrap em blocos por ano, INDEPENDENTE do IC do RMSESS absoluto/diagnóstico (seção 6.2) — os pontos estimados estavam próximos de zero, e o IC confirma que a incerteza INCLUI zero em todos os H1-H6; (3) as matrizes sazonais (seção 4) agora separam explicitamente RMSESS absoluto (4.2a) de RMSESS de anomalia corrigida (4.2b) — nunca mais um campo `rmsess` ambíguo.

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

### 4.2a. Matriz mês-alvo × lead — RMSESS ABSOLUTO/BRUTO (precipitação vs. climatologia observada; ponto estimado, sem IC nesta matriz)

**Rotulagem explícita (segunda revisão, item 3):** esta é a métrica RMSESS absoluta/bruta — nunca confundir com a RMSESS de anomalia corrigida da tabela 4.2b.

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

### 4.2b. Matriz mês-alvo × lead — RMSESS de ANOMALIA CORRIGIDA (climatologia própria do modelo; ponto estimado, sem IC nesta matriz)

**Rotulagem explícita (segunda revisão, item 3):** métrica DIFERENTE da 4.2a — RMSE da anomalia do modelo (previsto - climatologia própria do modelo) contra a anomalia observada, dividido pelo RMSE do benchmark de anomalia zero. Nunca a mesma coisa que o RMSESS absoluto.

| Mês \ Lead | H1 | H2 | H3 | H4 | H5 | H6 |
|---|---|---|---|---|---|---|
| Jan | -0.185 | -0.093 | -0.078 | 0.036 | -0.058 | -0.009 |
| Fev | 0.033 | 0.056 | 0.042 | 0.066 | 0.023 | -0.051 |
| Mar | 0.237 | -0.087 | 0.105 | -0.056 | -0.044 | -0.014 |
| Abr | 0.178 | -0.013 | -0.006 | 0.017 | 0.119 | 0.018 |
| Mai | 0.196 | 0.015 | 0.027 | 0.009 | -0.016 | -0.015 |
| Jun | 0.029 | 0.015 | 0.045 | -0.005 | 0.008 | 0.003 |
| Jul | 0.037 | -0.007 | -0.056 | 0.027 | -0.003 | -0.013 |
| Ago | 0.008 | -0.005 | 0.033 | 0.004 | 0.013 | 0.027 |
| Set | 0.024 | 0.018 | -0.012 | -0.000 | -0.008 | 0.001 |
| Out | 0.063 | 0.021 | 0.006 | -0.005 | -0.003 | 0.059 |
| Nov | 0.155 | 0.213 | -0.013 | 0.067 | 0.049 | 0.076 |
| Dez | -0.719 | -0.761 | -0.512 | -0.165 | -0.569 | -0.421 |

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

Cada métrica em sua própria linha, explicitamente rotulada — nunca uma correlação de anomalia ao lado de um RMSESS absoluto sem identificação (segunda revisão, item 3).

| Grupo | Métrica | H1 | H2 | H3 | H4 | H5 | H6 |
|---|---|---|---|---|---|---|---|
| chuvosa | N | 140 | 140 | 140 | 140 | 140 | 140 |
| chuvosa | RMSESS absoluto/bruto | -0.214 | -0.253 | -0.299 | -0.371 | -0.452 | -0.498 |
| chuvosa | RMSESS anomalia corrigida | 0.025 | -0.056 | -0.017 | 0.009 | -0.021 | -0.020 |
| chuvosa | Corr anomalia corrigida | 0.411 | 0.139 | 0.168 | 0.227 | 0.176 | 0.169 |
| transicao | N | 40 | 40 | 40 | 40 | 40 | 40 |
| transicao | RMSESS absoluto/bruto | -0.283 | -0.407 | -0.410 | -0.431 | -0.438 | -0.468 |
| transicao | RMSESS anomalia corrigida | 0.155 | 0.015 | 0.018 | 0.007 | -0.014 | -0.011 |
| transicao | Corr anomalia corrigida | 0.678 | 0.196 | 0.189 | 0.111 | -0.126 | -0.104 |
| seca | N | 60 | 60 | 60 | 60 | 60 | 60 |
| seca | RMSESS absoluto/bruto | -0.109 | -0.105 | -0.071 | -0.084 | -0.069 | -0.080 |
| seca | RMSESS anomalia corrigida | 0.017 | 0.001 | 0.028 | 0.004 | 0.010 | 0.016 |
| seca | Corr anomalia corrigida | 0.321 | 0.086 | 0.311 | 0.099 | 0.156 | 0.234 |

### 4.5. Visão agregada mensal descritiva (SECUNDÁRIA — H1 a H6 combinados)

**Rótulo: `visao_agregada_descritiva_H1_a_H6_combinados`.** Mantida só como visão descritiva de referência — a matriz 4.1-4.3 é a análise sazonal principal porque não mistura lead times diferentes dentro da mesma célula.

| Mês | Grupo sazonal | N | Bias | MAE | RMSE | Corr abs | Corr anomalia corrigida | RMSESS absoluto | RMSESS anomalia corrigida |
|---|---|---|---|---|---|---|---|---|---|
| Jan | chuvosa | 120 | 30.34 | 77.88 | 93.34 | 0.107 | 0.144 | -0.157 | -0.067 |
| Fev | chuvosa | 120 | 61.73 | 81.92 | 98.51 | 0.270 | 0.339 | -0.353 | 0.027 |
| Mar | chuvosa | 120 | 85.63 | 106.68 | 123.48 | 0.183 | 0.280 | -0.423 | 0.021 |
| Abr | chuvosa | 120 | -8.40 | 62.04 | 81.07 | 0.258 | 0.323 | 0.037 | 0.049 |
| Mai | transicao | 120 | -78.15 | 78.25 | 98.58 | 0.312 | 0.310 | -0.373 | 0.033 |
| Jun | seca | 120 | -4.91 | 5.64 | 10.41 | 0.222 | 0.230 | -0.059 | 0.016 |
| Jul | seca | 120 | -2.43 | 2.70 | 5.57 | 0.099 | 0.106 | -0.032 | -0.003 |
| Ago | seca | 120 | -8.47 | 8.96 | 15.68 | 0.157 | 0.199 | -0.107 | 0.013 |
| Set | transicao | 120 | -45.78 | 45.79 | 56.82 | 0.136 | 0.137 | -0.526 | 0.004 |
| Out | chuvosa | 120 | -81.91 | 81.91 | 87.71 | 0.267 | 0.301 | -0.720 | 0.023 |
| Nov | chuvosa | 120 | -78.95 | 80.60 | 96.39 | 0.338 | 0.411 | -0.577 | 0.088 |
| Dez | chuvosa | 120 | 38.42 | 61.17 | 75.00 | -0.127 | -0.203 | -0.866 | -0.537 |

| Grupo | N | Bias | MAE | RMSE | Corr abs | Corr anomalia corrigida | RMSESS absoluto | RMSESS anomalia corrigida |
|---|---|---|---|---|---|---|---|---|
| chuvosa | 840 | 6.69 | 78.89 | 94.75 | 0.563 | 0.226 | -0.352 | -0.013 |
| transicao | 240 | -61.96 | 62.02 | 80.46 | 0.515 | 0.249 | -0.407 | 0.027 |
| seca | 360 | -5.27 | 5.77 | 11.33 | 0.203 | 0.186 | -0.086 | 0.012 |

## 5. Avaliação probabilística (24 membros)

CRPS calculado com a fórmula "fair" (Ferro et al. 2008), não-viesada para ensemble finito. CRPSS compara contra a climatologia probabilística (conjunto dos anos históricos elegíveis, sem leakage). Tercis calculados exclusivamente com o histórico permitido antes de cada inicialização — nunca com 1981-2011 completo.

| Horizonte | N | CRPS modelo | CRPS climatologia | CRPSS | BS seco | BS normal | BS úmido | BSS seco | BSS normal | BSS úmido |
|---|---|---|---|---|---|---|---|---|---|---|
| H1 | 240 | 42.34 | 27.87 | -0.519 | 0.3301 | 0.2344 | 0.2298 | -0.320 | -0.140 | -0.089 |
| H2 | 240 | 41.38 | 27.77 | -0.490 | 0.3244 | 0.2192 | 0.2520 | -0.298 | -0.059 | -0.202 |
| H3 | 240 | 41.55 | 27.94 | -0.487 | 0.3178 | 0.2216 | 0.2622 | -0.271 | -0.078 | -0.242 |
| H4 | 240 | 43.69 | 27.85 | -0.569 | 0.3183 | 0.2196 | 0.2740 | -0.273 | -0.061 | -0.307 |
| H5 | 240 | 46.14 | 27.85 | -0.656 | 0.3284 | 0.2303 | 0.2980 | -0.314 | -0.113 | -0.421 |
| H6 | 240 | 47.28 | 27.69 | -0.707 | 0.3398 | 0.2299 | 0.3071 | -0.359 | -0.111 | -0.465 |

**Fórmulas:** `CRPSS = 1 - CRPS_modelo / CRPS_climatologia_probabilistica` — `BSS = 1 - BS_modelo / BS_referencia_nominal, onde BS_referencia_nominal = mean((1/3 - o_i)^2) calculado sobre as MESMAS observações o_i da amostra avaliada (NUNCA a constante 2/9 — essa só é exata quando a frequência observada da categoria é exatamente 1/3). A previsão nominal em si continua sendo p=1/3 — REFERÊNCIA PRINCIPAL, nunca alterada silenciosamente.`. **A previsão climatológica NOMINAL (p=1/3 por categoria) é a referência PRINCIPAL e nunca é alterada silenciosamente** — mas o BS dessa referência (BS_ref_nominal) é SEMPRE calculado sobre as mesmas observações da amostra avaliada (segunda revisão, item 1), nunca assumido como a constante 2/9 (exata só quando a frequência observada da categoria é exatamente 1/3 — ver tabela abaixo).

| Horizonte | BS_ref_nominal seco | BS_ref_nominal normal | BS_ref_nominal úmido |
|---|---|---|---|
| H1 | 0.2500 | 0.2056 | 0.2111 |
| H2 | 0.2500 | 0.2069 | 0.2097 |
| H3 | 0.2500 | 0.2056 | 0.2111 |
| H4 | 0.2500 | 0.2069 | 0.2097 |
| H5 | 0.2500 | 0.2069 | 0.2097 |
| H6 | 0.2500 | 0.2069 | 0.2097 |

*Para comparação: a constante antiga `2/9 ≈ 0,2222` só seria exata se a frequência observada de cada categoria fosse exatamente 1/3 — a seção 5.1 mostra que não é.*

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

### 6.2. Intervalos de confiança do RMSESS/CRPSS/BSS ABSOLUTOS/DIAGNÓSTICO

Diferente da seção 6.1, aqui o bootstrap reamostra os MESMOS blocos (mesmos anos sorteados) para recalcular modelo E climatologia a cada reamostra — garante que RMSESS/CRPSS/BSS sejam proporções válidas a cada iteração, em vez de dividir dois ICs calculados de forma independente. **A classificação abaixo nunca é 'bom'/'mau' — só indica se o IC 95% está totalmente acima de zero, inclui zero, ou totalmente abaixo de zero.** Esta seção é sobre o RMSESS/CRPSS/BSS **absolutos/diagnóstico** (precipitação bruta e BS nominal) — o IC do RMSESS de **anomalia corrigida** é INDEPENDENTE e está na seção 6.3, nunca reaproveitado daqui (segunda revisão, item 2).

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
| H1 | -0.320 | [-0.587, -0.113] | -0.140 | [-0.237, -0.034] | -0.089 | [-0.181, 0.031] |
| H2 | -0.298 | [-0.526, -0.115] | -0.059 | [-0.135, 0.022] | -0.202 | [-0.325, -0.049] |
| H3 | -0.271 | [-0.536, -0.057] | -0.078 | [-0.163, 0.021] | -0.242 | [-0.407, -0.043] |
| H4 | -0.273 | [-0.507, -0.045] | -0.061 | [-0.140, 0.036] | -0.307 | [-0.469, -0.142] |
| H5 | -0.314 | [-0.571, -0.097] | -0.113 | [-0.212, 0.002] | -0.421 | [-0.600, -0.228] |
| H6 | -0.359 | [-0.607, -0.144] | -0.111 | [-0.215, 0.006] | -0.465 | [-0.627, -0.285] |

### 6.3. Intervalo de confiança do RMSESS de ANOMALIA CORRIGIDA — INDEPENDENTE da seção 6.2

Segunda revisão, item 2. Mesmo desenho da seção 6.2 (bootstrap em blocos por ano, modelo e benchmark nos MESMOS blocos sorteados a cada reamostra), mas aplicado à anomalia CORRIGIDA (modelo: previsto - climatologia própria do modelo; benchmark: climatologia observada prevendo anomalia zero) — **nunca o IC do RMSESS absoluto/diagnóstico da seção 6.2 reaproveitado aqui**: amostra elegível e métrica são diferentes. Os pontos estimados (seção 3.2) estavam muito próximos de zero — este IC diz se essa proximidade é estatisticamente estável ou só ruído amostral. **Classificação meramente DESCRITIVA — nunca convertida em 'bom'/'mau'.**

| Horizonte | RMSESS anomalia corrigida | IC 95% | Posição do IC em relação a zero |
|---|---|---|---|
| H1 | 0.045 | [-0.043, 0.133] | IC 95% inclui zero (indeterminado) |
| H2 | -0.044 | [-0.111, 0.008] | IC 95% inclui zero (indeterminado) |
| H3 | -0.011 | [-0.076, 0.056] | IC 95% inclui zero (indeterminado) |
| H4 | 0.008 | [-0.035, 0.050] | IC 95% inclui zero (indeterminado) |
| H5 | -0.020 | [-0.076, 0.028] | IC 95% inclui zero (indeterminado) |
| H6 | -0.018 | [-0.060, 0.031] | IC 95% inclui zero (indeterminado) |

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

Esta seção separa deliberadamente SETE leituras DIFERENTES (a segunda revisão desdobrou o item 3 em 3 e 3b, porque são dois skill scores INDEPENDENTES com ICs próprios) — nunca resumidas numa frase como "modelo validado" ou "boa habilidade":

1. **Precipitação absoluta** — correlação alta (0.80-0.83) em todos os horizontes, mas dominada pelo ciclo sazonal regional (chuva concentrada out-abr); não é medida de habilidade preditiva real.
2. **Anomalia corrigida pela climatologia própria do modelo (seção 3.2, PRINCIPAL)** — correlação entre 0,14 e 0,40 (H2 mais baixa, H4 mais alta — não monotônica com o lead, diferente do padrão da versão diagnóstico). Ao remover o viés sistemático próprio do CFSv2 (em vez de só o ciclo sazonal compartilhado), a leitura muda qualitativamente em relação à versão diagnóstico anterior: bias e RMSE caem fortemente (ex.: RMSE de H1 cai de ~72mm para ~56mm), e a correlação em H3-H6 fica MAIOR que na versão diagnóstico — evidência de que parte do que parecia 'sem skill' na versão anterior era viés sistemático do modelo, não ausência de sinal.
3. **Skill ABSOLUTO/DIAGNÓSTICO relativo à climatologia (RMSESS/CRPSS, seção 6.2)** — ponto estimado negativo em todos os horizontes tanto para RMSESS quanto CRPSS, e os ICs 95% (bootstrap pareado, mesmos blocos) ficaram TOTALMENTE ABAIXO de zero em todos os H1-H6 — a incerteza amostral não muda a conclusão de que a climatologia expansível sem leakage teve erro MENOR que o ensemble bruto do CFSv2 (precipitação absoluta) nesta amostra. **Esta conclusão vale só para a versão absoluta/diagnóstico — NÃO pode ser estendida à anomalia corrigida sem olhar o IC próprio dela (item 3b abaixo), que é outra métrica, sobre outra amostra.**
3b. **Skill da ANOMALIA CORRIGIDA relativo à climatologia (RMSESS, seção 6.3 — INDEPENDENTE do item 3)** — os pontos estimados (seção 3.2) já estavam muito próximos de zero (entre -0,04 e +0,05 conforme o horizonte); o IC 95% (bootstrap próprio, nunca reaproveitado do item 3) confirma que a incerteza amostral INCLUI zero em todos os H1-H6 — diferente do item 3, aqui não há evidência de que o modelo seja sistematicamente melhor OU pior que o benchmark de anomalia zero; o resultado é estatisticamente indeterminado, não negativo.
4. **Probabilístico (CRPSS/BSS, seções 5 e 6.2)** — CRPSS predominantemente negativo com IC abaixo de zero, consistente com o item 3 (mesma métrica absoluta). O BSS nominal foi recalculado nesta revisão: BS_ref_nominal agora é computado sobre as mesmas observações da amostra (nunca a constante 2/9) — a seção 5.1 mostra que a frequência observada de 'seco' (~41,7% em H1) se desvia do nominal 1/3, por isso BS_ref_nominal difere de 2/9 e o BSS muda de valor em relação à revisão anterior (mesma conclusão qualitativa: negativo), sem alterar a referência nominal em si.
5. **Dependência com o lead** — RMSESS absoluto (ponto estimado) piora monotonicamente de H1 a H6; o RMSESS de anomalia corrigida NÃO segue o mesmo padrão monotônico e, com IC incluindo zero em todos os horizontes (item 3b), não há sequer uma tendência estatisticamente distinguível de ruído para interpretar — os dois fenômenos (skill absoluto vs. skill de anomalia corrigida) respondem de forma diferente ao aumento do lead, e não devem ser lidos como a mesma coisa.
6. **Dependência com a época do ano (seção 4)** — a matriz mês × lead agora reporta RMSESS absoluto (4.2a) e RMSESS de anomalia corrigida (4.2b) em tabelas SEPARADAS e explicitamente rotuladas — nunca uma ao lado da outra sem identificação. Variação relevante célula a célula (N≈20/célula) em ambas, mas qualquer leitura por mês isolado deve considerar a amostra pequena e a ausência de IC nesta matriz; o resumo por grupo sazonal (4.4) suaviza esse ruído sem substituir a matriz completa.

**O ensemble bruto aqui avaliado (`forecast_prec_mm`, sem qualquer correção operacional de viés ou downscaling) não deve ser confundido com um produto operacional corrigido — esta é avaliação científica do RAW, nenhuma correção de viés foi aplicada nesta fase.** Nenhuma das leituras acima, isoladamente, autoriza uma conclusão geral de habilidade — e, especificamente, a conclusão negativa do item 3 (RMSESS/CRPSS absolutos) NUNCA deve ser extrapolada para a anomalia corrigida (item 3b), cujo próprio IC (seção 6.3) a contradiz. Qualquer decisão sobre uso operacional do CFSv2 deve revisar conjuntamente: qual definição de skill (absoluta vs. anomalia corrigida), magnitude, intervalo de confiança (seções 6.2 e 6.3), horizonte, época do ano (seção 4) e tamanho da amostra (N=240 inicializações, mas com dependência temporal relevante — daí o bootstrap em blocos).

## Restrições respeitadas

- Dashboard, SARIMAX, XGBoost, pipeline operacional, série de produção e dados RAW do CFSv2 não foram alterados.
- Nenhuma correção operacional de viés foi aplicada — esta fase permanece avaliação científica do ensemble RAW.
- Nenhuma métrica desta fase é apresentada automaticamente no dashboard de produção.
- `serie_subst.csv`/`chirps_1981_2025.csv` não foram usados como referência principal em nenhum cálculo.
- Testes de controle de leakage (climatologia observada, climatologia do modelo, tercis, pareamento, mistura de membros, demonstração sintética das duas definições de anomalia) executados e aprovados antes do cálculo das métricas — ver `tests/test_cfsv2_validacao_cientifica.py`.
