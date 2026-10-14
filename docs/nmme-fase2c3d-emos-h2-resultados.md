# EMOS H2 — resultados (Fase 2C.3D, Método 3.5)
Implementação real do EMOS (Normal censurada em zero, CRPS minimizado analiticamente) restrita a H2, seguindo estritamente `docs/nmme-fase2c3d-protocolo-emos-h2.md`. Avaliação expanding-window causal, regra exigindo simultaneamente `init_date_treino < init_date_avaliada` e `target_month_treino < init_date_avaliada` (mesma regra já corrigida no Método 3.4). Warm-up `N_TREINO_MINIMO_EMOS = 120` pares válidos.

## 1. Amostra avaliada
- N final de previsões avaliáveis: **95** (esperado estrutural: 95, bate: True).
- Primeira `init_date` avaliável: **2003-02**.
- Leakage observacional: nenhum encontrado.
- Falhas de convergência/sanidade: nenhuma.

## 2. CRPS médio (fórmula analítica, protocolo seção 15)
| Modelo | CRPS médio (mm) |
|---|---|
| EMOS completo | 27.4771 |
| EMOS d=0 | 27.4771 |
| Ensemble RAW CFSv2 | 39.7739 |
| Climatologia causal | 26.7109 |

## 3. CRPSS e intervalos de confiança (bootstrap em blocos por target_ano, sem refit)
N anos distintos: 9, N reamostras: 500.
| Comparação | Estimativa pontual | IC 95% | Classificação |
|---|---|---|---|
| EMOS completo vs. RAW | 0.3092 | [0.2181, 0.3983] | IC 95% totalmente ACIMA de zero |
| EMOS completo vs. climatologia causal | -0.0287 | [-0.0727, 0.0146] | IC 95% inclui zero (indeterminado) |
| EMOS completo vs. EMOS d=0 (teste CENTRAL) | 0.0000 | [-0.0000, 0.0000] | IC 95% inclui zero (indeterminado) |
| EMOS d=0 vs. RAW | 0.3092 | [0.2181, 0.3983] | IC 95% totalmente ACIMA de zero |
| EMOS d=0 vs. climatologia causal | -0.0287 | [-0.0727, 0.0146] | IC 95% inclui zero (indeterminado) |

**Teste central (CRPSS_spread_dinamico):** se o IC 95% inclui zero, o termo dinâmico de spread (`d * spread_relativo²`) não acrescenta valor comprovado sobre corrigir só média e dispersão climatológica — qualquer melhoria do EMOS completo sobre o RAW, nesse caso, vem da correção de localização/escala, não do spread caso a caso (protocolo, seção 18).

## 4. Brier Score e BSS por categoria de tercil
| Categoria | Brier Score (EMOS) | Brier ref. nominal (1/3) | BSS |
|---|---|---|---|
| seco | 0.2579 | 0.2620 | 0.0157 |
| normal | 0.2001 | 0.1953 | -0.0246 |
| umido | 0.2281 | 0.2094 | -0.0898 |

Verificação de que as probabilidades somam 1 em todos os casos: True (desvio máximo: 1.11e-16).

## 5. Cobertura dos intervalos — EMOS vs. RAW (mesmos 95 casos)
| Nível nominal | Cobertura EMOS | Largura média EMOS (mm) | Cobertura RAW | Largura média RAW (mm) |
|---|---|---|---|---|
| 50% | 0.453 | 57.0 | 0.274 | 56.4 |
| 80% | 0.726 | 108.4 | 0.505 | 111.3 |
| 90% | 0.842 | 138.8 | 0.568 | 142.5 |

## 6. PIT (mid-PIT, determinístico, sem RNG)
Média: 0.5605 (ideal: 0,5). Variância: 0.0949 (ideal: 1/12 ≈ 0,0833). N: 95.

Contagens por decil (0,0-1,0): [4, 13, 9, 8, 11, 6, 7, 9, 6, 22]

## 7. Bias
- `bias_mu_latente` (diagnóstico do parâmetro latente): -5.1549 mm.
- `bias_media_preditiva_censurada` (**métrica principal**, usa E[Y]): -3.7365 mm.

## 8. Diagnóstico de parâmetros (distribuição temporal, 95 avaliações)
| Parâmetro | min | p10 | mediana | média | p90 | máx |
|---|---|---|---|---|---|---|
| a | -12.0179 | -11.2091 | -10.2710 | -10.0853 | -8.9187 | -4.3558 |
| b | 0.0644 | 0.0846 | 0.2692 | 0.2461 | 0.3232 | 0.3473 |
| c | 0.7394 | 0.7510 | 0.7793 | 0.7788 | 0.8017 | 0.8249 |
| d | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| a_d0 | -12.0179 | -11.2090 | -10.2710 | -10.0853 | -8.9187 | -4.3558 |
| b_d0 | 0.0644 | 0.0846 | 0.2692 | 0.2461 | 0.3232 | 0.3473 |
| c_d0 | 0.7394 | 0.7510 | 0.7793 | 0.7788 | 0.8017 | 0.8249 |

Destaques: `d` praticamente zero em 95/95 avaliações; `d` no bound inferior (0) em 95/95; `gamma_c` no bound em 0; `gamma_c_d0` no bound em 0; `b` negativo em 0; `b_d0` negativo em 0.

**Achado consistente nas 95 avaliações:** o otimizador converge para `d ≈ 0` (bound inferior) em TODAS elas — o EMOS completo colapsa estruturalmente ao EMOS `d=0` nesta amostra. Isso não é um sinal de implementação malfeita (os dois modelos são ajustados de forma independente — ver `tests/test_cfsv2_emos_h2_implementacao.py::IndependenciaD0TestCase`, que confirma divergência genuína num cenário sintético onde o sinal do spread é real); é o próprio otimizador descobrindo, a partir dos dados, que o termo dinâmico do spread não reduz o CRPS médio de treino — coerente com a informação MODESTA do spread já registrada no gate (correlações residuais 0,07-0,24) e nas limitações do protocolo (seção 25).

## 9. Decisão segundo o critério pré-registrado (protocolo, seção 20)
| Critério | Resultado |
|---|---|
| 1. IC95(CRPSS_spread_dinamico) > 0 | False |
| 2. IC95(CRPSS vs. climatologia) > 0 | False |
| 3. Sem degradação grave de Brier/BSS | True |
| 4. Cobertura melhor ou igual ao RAW (3 níveis) | True |
| **Aprovado o componente dinâmico de spread?** | **False** |

Os 4 critérios são exigidos SIMULTANEAMENTE (protocolo, seção 20). Superar só o RAW sem superar a climatologia NÃO basta (seção 20, "se o EMOS só superar o RAW mas não a climatologia: não aprovar").

## 10. Conclusão
O critério pré-registrado NÃO foi satisfeito (2/4 critério(s) reprovado(s)) — o componente dinâmico de spread NÃO tem evidência suficiente para ser considerado como acrescentando valor sobre corrigir só média e dispersão climatológica. O EMOS (completo e `d=0`, estruturalmente equivalentes nesta amostra) supera claramente o ensemble RAW (CRPSS≈0.3092, IC95 totalmente acima de zero) mas não supera a climatologia probabilística causal (CRPSS≈-0.0287, IC95 inclui zero) — pelo protocolo (seção 20), superar só o RAW não basta.

## Limitações (protocolo, seção 25 — reafirmadas aqui)
- Amostra curta: 95 previsões avaliáveis (~8 anos), warm-up de 120 pares consome a maior parte do histórico disponível.
- H2 foi 1 de 6 horizontes testados no gate — nenhuma correção de multiplicidade aplicada.
- O bootstrap é condicional à sequência causal já ajustada por expanding-window (sem refit dentro da reamostra).
- `mu_latente` e `E[Y]` (média preditiva censurada) são quantidades diferentes — este relatório usa `E[Y]` como métrica principal de localização final.
- O spread CFSv2 contém informação modesta, não forte — o resultado `d≈0` é consistente com essa limitação já documentada, não uma surpresa isolada.

---
**Esta atividade implementa e avalia o EMOS H2 real.** Nenhum pipeline operacional ou dashboard foi alterado. A decisão reportada na Seção 9 segue estritamente o critério pré-registrado no protocolo — não foi ajustada depois de observar o resultado.
