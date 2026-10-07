# Gate diagnóstico de calibração probabilística — Fase 2C.3D (Método 3.5)

**GATE DIAGNÓSTICO, não implementação. Nenhum EMOS foi ajustado, nenhum membro foi recalibrado, nenhum dressing foi aplicado, nenhum quantile mapping probabilístico foi executado, nenhuma probabilidade operacional nem o dashboard foram alterados. O único objetivo deste documento é responder, com os fatos primeiro, se a dispersão dos 24 membros do CFSv2 contém informação útil sobre a incerteza/erro da previsão — e classificar essa resposta por horizonte, nunca declarar o Método 3.5 aprovado.**

Protegidos e não alterados nesta atividade: CFSv2 RAW, CHIRPS v3 histórico, base pareada da 2C.3C, dashboard, SARIMAX/XGBoost, pipeline operacional, `serie_subst.csv`, e os artefatos já aprovados dos Métodos 3.1/3.2/3.4 e do gate do Método 3.3 — todos só lidos, nunca alterados.

## 1. Unidade de análise e auditoria de 24 membros

1 linha por `(init_date, lead)`; os 24 membros são usados SÓ para estatísticas internas do ensemble (`ensemble_mean`, `ensemble_median`, `ensemble_std` (`ddof=1`), `ensemble_variance`, `ensemble_iqr`, `ensemble_min/max/range`) — NUNCA tratados como 24 anos/observações históricas independentes em nenhum bootstrap deste módulo (todo bootstrap resample `target_ano`, em blocos, nunca membros).

Auditoria de contagem de membros: ✅ todas as linhas têm exatamente 24 membros.

## 2. Spread médio por horizonte e spread-error ratio (itens 1, 2 e 4 do pedido)

`erro_abs = |ensemble_mean - obs|`, `erro_quadratico = (ensemble_mean - obs)²`, `erro_assinado = ensemble_mean - obs` — SEM qualquer correção de bias (diagnóstico do ensemble RAW). `spread_error_ratio = mean(ensemble_std) / RMSE(ensemble_mean, obs)` — leitura SEMPRE só diagnóstica, nunca prova isolada de calibração.

| Horizonte | N | Spread médio (`ensemble_std`) | RMSE(`ensemble_mean`, obs) | spread_error_ratio | Leitura diagnóstica |
|---|---|---|---|---|---|
| H1 | 240 | 40.12 | 71.81 | 0.559 | muito abaixo de 1 — ensemble potencialmente UNDERdispersive |
| H2 | 240 | 48.94 | 74.80 | 0.654 | muito abaixo de 1 — ensemble potencialmente UNDERdispersive |
| H3 | 240 | 48.74 | 77.33 | 0.630 | muito abaixo de 1 — ensemble potencialmente UNDERdispersive |
| H4 | 240 | 48.59 | 80.92 | 0.601 | muito abaixo de 1 — ensemble potencialmente UNDERdispersive |
| H5 | 240 | 47.86 | 84.93 | 0.564 | muito abaixo de 1 — ensemble potencialmente UNDERdispersive |
| H6 | 240 | 47.21 | 87.15 | 0.542 | muito abaixo de 1 — ensemble potencialmente UNDERdispersive |

## 3. Spread-skill: Pearson e Spearman, com IC 95% (item 3 do pedido)

Bootstrap SEMPRE em blocos por `target_ano` (`v.bootstrap_blocos_por_ano`, reaproveitado sem modificação) — nunca resample de membros ou de linhas individuais. Correlação pontual positiva isolada NUNCA é suficiente para declarar relação útil — ver classificação (seção 10), que cruza isso com ratio e rank histogram.

| Horizonte | N | Pearson(std, erro_abs) | IC 95% | Spearman(std, erro_abs) | IC 95% | Pearson(variance, erro_quad.) | IC 95% |
|---|---|---|---|---|---|---|---|
| H1 | 240 | 0.290 | [0.166, 0.407] | 0.454 | [0.350, 0.544] | 0.101 | [-0.008, 0.235] |
| H2 | 240 | 0.375 | [0.280, 0.467] | 0.528 | [0.456, 0.592] | 0.212 | [0.084, 0.351] |
| H3 | 240 | 0.436 | [0.360, 0.513] | 0.571 | [0.505, 0.636] | 0.271 | [0.202, 0.373] |
| H4 | 240 | 0.453 | [0.388, 0.528] | 0.578 | [0.511, 0.635] | 0.245 | [0.158, 0.357] |
| H5 | 240 | 0.445 | [0.362, 0.530] | 0.562 | [0.493, 0.634] | 0.290 | [0.154, 0.410] |
| H6 | 240 | 0.484 | [0.407, 0.558] | 0.597 | [0.525, 0.666] | 0.315 | [0.212, 0.412] |

## 4. Rank histogram (item 5 do pedido)

Posição (1..25) da observação entre os 24 membros ordenados. Tie-break **explícito e determinístico** (`_rank_observacao_determinístico`, próprio deste módulo — ver nota de implementação abaixo), nunca o sorteio seedado de `v.rank_observacao` usado em outros pontos da 2C.3C. Diagnóstico derivado, nunca um teste de hipótese formal como critério único: frequência nos ranks extremos (1 e 25 — formato em U sugere underdispersion), frequência central (terço central — concentração sugere overdispersion), e desvio de uniformidade (soma dos desvios absolutos da frequência esperada sob uniformidade, 1/25 por rank).

> **Nota de implementação (desvio deliberado do reuso literal):** o item 5 do pedido exige tie-break "explícito e determinístico"; `v.rank_observacao` (2C.3C) resolve empates por sorteio seedado — reprodutível, mas não determinístico no sentido de regra fixa. Por isso este módulo define sua própria `_rank_observacao_determinístico`: sem empate, mesma posição de sempre; com empate, sempre o PONTO MÉDIO do intervalo de posições válidas, arredondado meio-para-cima em caso de 0,5 exato. `crps_amostral` e `categoria_tercil` continuam reaproveitados sem modificação (itens 7/8 exigem reuso exato).

| Horizonte | N | Freq. ranks extremos (1 e 25) | Freq. central (terço central) | Desvio de uniformidade | Esperado por rank sob uniformidade |
|---|---|---|---|---|---|
| H1 | 240 | 0.350 | 0.133 | 0.920 | 9.60 |
| H2 | 240 | 0.271 | 0.200 | 0.670 | 9.60 |
| H3 | 240 | 0.267 | 0.183 | 0.592 | 9.60 |
| H4 | 240 | 0.250 | 0.142 | 0.597 | 9.60 |
| H5 | 240 | 0.317 | 0.171 | 0.623 | 9.60 |
| H6 | 240 | 0.296 | 0.146 | 0.690 | 9.60 |

Esperado sob uniformidade perfeita: 2/25 = 0,080 nos ranks extremos combinados. Frequências nos ranks extremos consistentemente acima disso em todos os horizontes (ver tabela) são consistentes com um ensemble RAW **underdispersive** — a observação cai fora da faixa dos 24 membros com frequência maior do que uma dispersão bem calibrada permitiria.

## 5. Cobertura de intervalos empíricos 50/80/90% (item 6 do pedido)

Intervalos EMPÍRICOS (percentis dos 24 membros RAW, nunca uma distribuição assumida). `coverage_error = cobertura_observada - cobertura_nominal`. **Nenhuma calibração de intervalo aplicada nesta etapa — só diagnóstico.**

| Horizonte | N | Cobertura 50% (nominal 0,50) | erro | Cobertura 80% (nominal 0,80) | erro | Cobertura 90% (nominal 0,90) | erro |
|---|---|---|---|---|---|---|---|
| H1 | 240 | 0.217 | -0.283 | 0.404 | -0.396 | 0.504 | -0.396 |
| H2 | 240 | 0.283 | -0.217 | 0.492 | -0.308 | 0.592 | -0.308 |
| H3 | 240 | 0.263 | -0.237 | 0.492 | -0.308 | 0.617 | -0.283 |
| H4 | 240 | 0.263 | -0.237 | 0.483 | -0.317 | 0.588 | -0.312 |
| H5 | 240 | 0.271 | -0.229 | 0.458 | -0.342 | 0.558 | -0.342 |
| H6 | 240 | 0.258 | -0.242 | 0.450 | -0.350 | 0.596 | -0.304 |

Coverage_error consistentemente NEGATIVO (cobertura observada abaixo da nominal) em todos os horizontes é o mesmo sinal de underdispersion já visto no spread_error_ratio (seção 2) e no rank histogram (seção 4) — três diagnósticos independentes apontando na mesma direção, nunca um só usado isoladamente para essa conclusão.

## 6. CRPS RAW (item 7 do pedido)

Fórmula "fair" (Ferro et al. 2008) reaproveitada sem modificação (`v.crps_amostral`) — nunca uma segunda fórmula paralela. `crps_medio_climatologia` usa a mesma climatologia causal observada já aprovada na 2C.3C (`anos_hist`, elegíveis por `v.construir_linhas_avaliacao_por_lead`) como referência DIRETAMENTE comparável, já que ambos os CRPS são calculados sobre as MESMAS linhas/observações — por isso a comparação formal (CRPSS) É reportada aqui, não diferida.

| Horizonte | N | CRPS médio (modelo RAW) | CRPS médio (climatologia causal) | CRPSS |
|---|---|---|---|---|
| H1 | 240 | 42.34 | 27.87 | -0.519 |
| H2 | 240 | 41.38 | 27.77 | -0.490 |
| H3 | 240 | 41.55 | 27.94 | -0.487 |
| H4 | 240 | 43.69 | 27.85 | -0.569 |
| H5 | 240 | 46.14 | 27.85 | -0.656 |
| H6 | 240 | 47.28 | 27.69 | -0.707 |

CRPSS negativo em todos os horizontes indica que o ensemble RAW do CFSv2, sem qualquer correção, tem CRPS pior que a climatologia causal observada — achado consistente com o skill interanual determinístico fraco já documentado nos Métodos 3.1/3.2/3.4, nunca uma conclusão nova deste gate isoladamente.

## 7. Brier Score e BSS por tercil (item 8 do pedido)

Categorias de tercil (seco/normal/úmido) e `BS_ref_nominal = mean((1/3 - o_i)^2)` reaproveitados EXATAMENTE da 2C.3C (`v.categoria_tercil`), nunca redefinidos. Probabilidades RAW = fração dos 24 membros em cada categoria.

| Horizonte | BS seco | BS normal | BS úmido | BSS seco | BSS normal | BSS úmido |
|---|---|---|---|---|---|---|
| H1 | 0.330 | 0.234 | 0.230 | -0.320 | -0.140 | -0.089 |
| H2 | 0.324 | 0.219 | 0.252 | -0.298 | -0.059 | -0.202 |
| H3 | 0.318 | 0.222 | 0.262 | -0.271 | -0.078 | -0.242 |
| H4 | 0.318 | 0.220 | 0.274 | -0.273 | -0.061 | -0.307 |
| H5 | 0.328 | 0.230 | 0.298 | -0.314 | -0.113 | -0.421 |
| H6 | 0.340 | 0.230 | 0.307 | -0.359 | -0.111 | -0.465 |

BSS calculado sempre contra a referência nominal `mean((1/3-o_i)^2)` já corrigida na 2C.3C — nunca a constante 2/9.

## 8. Dependência/diversidade entre membros (item 9 do pedido)

Correlação de Pearson par-a-par média entre as 24 séries temporais de membro (fora da diagonal) — perto de 1 indica membros quase idênticos (pouca diversidade real); perto de 0, membros efetivamente independentes. `effective_ensemble_size_aprox = M / (1 + (M-1)·ρ_média)` (Bretherton et al. 1999, adaptada) — **diagnóstico apenas, NUNCA usado para inflar a amostra histórica de 240 inicializações.**

| Horizonte | N inicializações | N membros | Correlação média par-a-par | Effective Ensemble Size (aprox.) |
|---|---|---|---|---|
| H1 | 240 | 24 | 0.783 | 1.26 |
| H2 | 240 | 24 | 0.773 | 1.28 |
| H3 | 240 | 24 | 0.811 | 1.22 |
| H4 | 240 | 24 | 0.829 | 1.20 |
| H5 | 240 | 24 | 0.840 | 1.18 |
| H6 | 240 | 24 | 0.850 | 1.17 |

Correlação par-a-par média alta (ver tabela) com Effective Ensemble Size muito abaixo de 24 em todos os horizontes indica que os 24 membros do CFSv2 são fortemente redundantes ao longo do tempo — a maior parte da variação entre membros não traz diversidade temporal nova, o que é coerente com a natureza do CFSv2 (perturbações iniciais de um mesmo modelo dinâmico, não 24 modelos independentes).

## 9. Sazonalidade — mês × lead e grupo sazonal × lead, atenção à estação seca (item 10 do pedido)

Diagnóstico DESCRITIVO — nunca 72 testes de significância independentes nem um critério de aprovação célula a célula.

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

**Atenção especial à estação seca (jun-ago, ver seção 9.3)** — os Métodos 3.2/3.4 já mostraram baixa variabilidade de sinal nesses meses (chuva rara e próxima de zero). O CRPS médio absoluto da estação seca é o menor entre os três grupos (ver tabela) simplesmente porque a magnitude da chuva observada é pequena — isso não deve ser lido como "melhor desempenho relativo" sem olhar o CRPSS (que compara contra a climatologia do próprio período) ao lado do valor absoluto.

## 10. Classificação do gate por horizonte (item 11 do pedido)

**Nenhum limiar numérico foi escolhido depois de ver o resultado** — os limiares usados (spread_error_ratio fora de [0,8; 1,2] como desvio moderado, fora de [0,5; 2,0] como extremo; múltiplos simples sobre a frequência esperada do rank histogram) estavam fixados no código antes desta execução. A classificação cruza SEMPRE correlação (seção 3) com ratio (seção 2) e rank histogram (seção 4) — correlação positiva isolada nunca basta para `spread_informativo`.

| Horizonte | Classificação | Pearson IC>0? | Spearman IC>0? | Ratio moderadamente fora de 1? | Ratio extremo? | Rank histogram sinaliza desvio? |
|---|---|---|---|---|---|---|
| H1 | `ensemble_mal_calibrado_mas_potencialmente_calibravel` | ✅ | ✅ | ✅ | ❌ | ✅ |
| H2 | `ensemble_mal_calibrado_mas_potencialmente_calibravel` | ✅ | ✅ | ✅ | ❌ | ✅ |
| H3 | `ensemble_mal_calibrado_mas_potencialmente_calibravel` | ✅ | ✅ | ✅ | ❌ | ✅ |
| H4 | `ensemble_mal_calibrado_mas_potencialmente_calibravel` | ✅ | ✅ | ✅ | ❌ | ✅ |
| H5 | `ensemble_mal_calibrado_mas_potencialmente_calibravel` | ✅ | ✅ | ✅ | ❌ | ✅ |
| H6 | `ensemble_mal_calibrado_mas_potencialmente_calibravel` | ✅ | ✅ | ✅ | ❌ | ✅ |

- **H1** (`ensemble_mal_calibrado_mas_potencialmente_calibravel`): pelo menos uma correlação spread×erro com IC 95% totalmente acima de zero, MAS spread_error_ratio e/ou rank histogram demonstram under/overdispersion — o ensemble bruto não está bem calibrado, porém o spread ainda carrega alguma informação sobre o erro (candidato a correção por EMOS ou equivalente, não a descarte)
- **H2** (`ensemble_mal_calibrado_mas_potencialmente_calibravel`): pelo menos uma correlação spread×erro com IC 95% totalmente acima de zero, MAS spread_error_ratio e/ou rank histogram demonstram under/overdispersion — o ensemble bruto não está bem calibrado, porém o spread ainda carrega alguma informação sobre o erro (candidato a correção por EMOS ou equivalente, não a descarte)
- **H3** (`ensemble_mal_calibrado_mas_potencialmente_calibravel`): pelo menos uma correlação spread×erro com IC 95% totalmente acima de zero, MAS spread_error_ratio e/ou rank histogram demonstram under/overdispersion — o ensemble bruto não está bem calibrado, porém o spread ainda carrega alguma informação sobre o erro (candidato a correção por EMOS ou equivalente, não a descarte)
- **H4** (`ensemble_mal_calibrado_mas_potencialmente_calibravel`): pelo menos uma correlação spread×erro com IC 95% totalmente acima de zero, MAS spread_error_ratio e/ou rank histogram demonstram under/overdispersion — o ensemble bruto não está bem calibrado, porém o spread ainda carrega alguma informação sobre o erro (candidato a correção por EMOS ou equivalente, não a descarte)
- **H5** (`ensemble_mal_calibrado_mas_potencialmente_calibravel`): pelo menos uma correlação spread×erro com IC 95% totalmente acima de zero, MAS spread_error_ratio e/ou rank histogram demonstram under/overdispersion — o ensemble bruto não está bem calibrado, porém o spread ainda carrega alguma informação sobre o erro (candidato a correção por EMOS ou equivalente, não a descarte)
- **H6** (`ensemble_mal_calibrado_mas_potencialmente_calibravel`): pelo menos uma correlação spread×erro com IC 95% totalmente acima de zero, MAS spread_error_ratio e/ou rank histogram demonstram under/overdispersion — o ensemble bruto não está bem calibrado, porém o spread ainda carrega alguma informação sobre o erro (candidato a correção por EMOS ou equivalente, não a descarte)

## 11. Síntese do gate e próximo passo recomendado (itens 11, 12 e 13 do pedido)

**Síntese:** ensemble_mal_calibrado_mas_potencialmente_calibravel em todos os horizontes avaliáveis — o ensemble bruto está consistentemente mal calibrado em magnitude (spread_error_ratio e/ou rank histogram fora do esperado em todos os horizontes), mas o spread ainda carrega relação com o erro em todos eles (correlação com IC 95% acima de zero). Não é "pouco informativo" — é um candidato razoável a um protocolo de calibração probabilística simples (EMOS ou equivalente parcimonioso), que corrige explicitamente a relação spread-variância ao mesmo tempo em que usa o spread como preditor — mas isso é uma recomendação de próximo passo, nunca uma aprovação do Método 3.5 nesta atividade (item 11/13 do pedido).

**Próximo passo recomendado:** `protocolo_calibracao_probabilistica_simples_recomendado_com_correcao_de_dispersao`

**O que NÃO foi feito nesta atividade (item 13 do pedido) — confirmação explícita:**

- Nenhum EMOS ajustado: ✅ confirmado
- Nenhum dressing aplicado: ✅ confirmado
- Nenhuma probabilidade operacional alterada: ✅ confirmado
- Nenhum quantile mapping probabilístico executado.
- Nenhuma mudança no dashboard, SARIMAX, XGBoost ou pipeline operacional.
- O Método 3.5 **não** foi declarado aprovado nesta atividade — este documento é um gate diagnóstico, não uma aprovação.

## 12. Limitações

- `effective_ensemble_size_aprox` (seção 8) é uma aproximação de diagnóstico, nunca usada para reponderar nenhuma métrica deste relatório.
- A matriz mês × lead e os grupos sazonais (seção 9) têm amostra pequena por célula — usados só como diagnóstico, nunca como critério de aprovação célula a célula.
- O tie-break determinístico do rank histogram (seção 4) é uma convenção explícita (ponto médio do intervalo de posições válidas), não a única convenção possível na literatura — está documentada e é reprodutível por construção, nunca aleatória.
- Este gate avalia o ensemble RAW; nenhuma correção de bias determinístico (Métodos 3.1/3.2/3.4) foi combinada com a dispersão aqui — avaliar a dispersão em torno de uma previsão já corrigida por bias é uma pergunta diferente, fora do escopo desta atividade.

## 13. Conclusão restrita ao gate do Método 3.5

Esta conclusão vale SOMENTE para o diagnóstico de dispersão do ensemble CFSv2 RAW — nunca generalizada para "calibração do CFSv2" em geral, e nunca uma aprovação do Método 3.5.

- Classificação por horizonte: H1: `ensemble_mal_calibrado_mas_potencialmente_calibravel`; H2: `ensemble_mal_calibrado_mas_potencialmente_calibravel`; H3: `ensemble_mal_calibrado_mas_potencialmente_calibravel`; H4: `ensemble_mal_calibrado_mas_potencialmente_calibravel`; H5: `ensemble_mal_calibrado_mas_potencialmente_calibravel`; H6: `ensemble_mal_calibrado_mas_potencialmente_calibravel`.
- ensemble_mal_calibrado_mas_potencialmente_calibravel em todos os horizontes avaliáveis — o ensemble bruto está consistentemente mal calibrado em magnitude (spread_error_ratio e/ou rank histogram fora do esperado em todos os horizontes), mas o spread ainda carrega relação com o erro em todos eles (correlação com IC 95% acima de zero). Não é "pouco informativo" — é um candidato razoável a um protocolo de calibração probabilística simples (EMOS ou equivalente parcimonioso), que corrige explicitamente a relação spread-variância ao mesmo tempo em que usa o spread como preditor — mas isso é uma recomendação de próximo passo, nunca uma aprovação do Método 3.5 nesta atividade (item 11/13 do pedido).
- Decisão de implementar (ou não) um protocolo de calibração probabilística — EMOS ou equivalente parcimonioso — permanece de uma próxima etapa, condicionada à revisão independente deste resultado, nunca decidida automaticamente por este gate.
