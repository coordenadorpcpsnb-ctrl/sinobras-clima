# Robustez do sinal spread×erro em H2 — Fase 2C.3D (Método 3.5)

**Análise de ROBUSTEZ, não implementação. Nenhum EMOS foi ajustado, nenhum membro foi recalibrado, nenhuma probabilidade operacional foi alterada. O objetivo é determinar se a associação residual spread×erro observada em H2 (único horizonte com IC 95% acima de zero após o controle sazonal — ver `docs/nmme-fase2c3d-gate-calibracao-probabilistica-cfsv2.md`) é robusta ou depende excessivamente de poucos meses/estações. H2 nunca é chamado de "validado" neste documento.**

Protegidos e não alterados nesta atividade: Métodos 3.1–3.4, gate 3.3, CFSv2 RAW, CHIRPS v3, dashboard, pipeline operacional, e todas as métricas já congeladas do gate do Método 3.5 (CRPS, CRPSS, Brier, BSS, cobertura, ranks, dependência de membros) — confirmadas idênticas por teste de regressão.

## 1. Resultado congelado (referência)

**H2** — Pearson residual: `0.154965`, IC 95% `[0.042564, 0.256144]`; Spearman residual: `0.179941`, IC 95% `[0.036391, 0.290664]`.

Congelamento confirmado contra o JSON real do gate: ✅ confere.

## 2-3. Leave-one-month-out para H2

Para cada mês excluído, a transformação é refeita INTEGRALMENTE sobre os dados restantes: médias mensais dos meses remanescentes → resíduos → correlação → bootstrap em blocos por `target_ano` (`g._bootstrap_residualizado_por_ano`, reaproveitado sem modificação — mesma metodologia do gate original). Nenhum resíduo da análise completa é reaproveitado.

| Mês removido | N | Pearson | IC 95% | Classificação | Spearman | IC 95% | Classificação |
|---|---|---|---|---|---|---|---|
| Jan | 220 | 0.207 | [0.054, 0.344] | IC 95% ACIMA de zero | 0.237 | [0.056, 0.369] | IC 95% ACIMA de zero |
| Fev | 220 | 0.146 | [0.018, 0.259] | IC 95% ACIMA de zero | 0.177 | [0.032, 0.284] | IC 95% ACIMA de zero |
| Mar | 220 | 0.069 | [-0.040, 0.174] | IC inclui zero | 0.124 | [-0.037, 0.242] | IC inclui zero |
| Abr | 220 | 0.140 | [0.001, 0.256] | IC 95% ACIMA de zero | 0.143 | [-0.019, 0.269] | IC inclui zero |
| Mai | 220 | 0.163 | [0.023, 0.274] | IC 95% ACIMA de zero | 0.198 | [0.044, 0.310] | IC 95% ACIMA de zero |
| Jun | 220 | 0.155 | [0.042, 0.256] | IC 95% ACIMA de zero | 0.178 | [0.035, 0.295] | IC 95% ACIMA de zero |
| Jul | 220 | 0.155 | [0.043, 0.256] | IC 95% ACIMA de zero | 0.180 | [0.039, 0.297] | IC 95% ACIMA de zero |
| Ago | 220 | 0.156 | [0.043, 0.257] | IC 95% ACIMA de zero | 0.180 | [0.041, 0.295] | IC 95% ACIMA de zero |
| Set | 220 | 0.159 | [0.040, 0.264] | IC 95% ACIMA de zero | 0.183 | [0.038, 0.293] | IC 95% ACIMA de zero |
| Out | 220 | 0.161 | [0.033, 0.266] | IC 95% ACIMA de zero | 0.193 | [0.038, 0.323] | IC 95% ACIMA de zero |
| Nov | 220 | 0.163 | [0.036, 0.269] | IC 95% ACIMA de zero | 0.170 | [0.036, 0.268] | IC 95% ACIMA de zero |
| Dez | 220 | 0.174 | [0.039, 0.283] | IC 95% ACIMA de zero | 0.189 | [0.024, 0.316] | IC 95% ACIMA de zero |

### 3.1. Resumo das 12 exclusões

| Métrica | Mínimo | Mediana | Máximo | Exclusões com valor > 0 (de 12) | Exclusões com IC 95% acima de zero (de 12) |
|---|---|---|---|---|---|
| Pearson | 0.069 | 0.158 | 0.207 | 12 | 11 |
| Spearman | 0.124 | 0.180 | 0.237 | 12 | 10 |

## 4. Classificação de robustez de H2

**Critério pré-registrado (fixado antes de rodar contra dados reais — ver constantes no topo de `scripts/cfsv2_robustez_h2_spread.py`):**

- `sinal_h2_robusto`: Pearson E Spearman positivos em >= 10/12 exclusões, pelo menos uma métrica com IC 95% acima de zero na maioria (>= 7/12), e nenhuma exclusão com inversão forte (< -0.1).
- `sinal_h2_promissor_mas_fragil`: sinal mediano positivo e maioria das exclusões ainda positivas, mas sem atingir o limiar robusto.
- `sinal_h2_dependente_de_poucos_meses`: poucas exclusões mantêm o sinal positivo, ou alguma exclusão produz inversão forte.

**Resultado:** `sinal_h2_robusto`

Pearson e Spearman positivos em >= 10/12 exclusões, pelo menos uma métrica com IC 95% acima de zero na maioria (>= 7/12) das exclusões, e nenhuma exclusão produziu inversão forte (< -0.1).

| Sinal | Valor |
|---|---|
| Pearson e Spearman positivos em >= limiar robusto | ✅ |
| Pelo menos uma métrica com IC>0 na maioria | ✅ |
| Alguma exclusão com inversão forte | ❌ |
| Pearson e Spearman positivos na maioria | ✅ |
| Sinal mediano positivo | ✅ |

## 5. Leave-one-season-out

Mesma reutilização de `g._bootstrap_residualizado_por_ano` — grupos sazonais já existentes no projeto (chuvosa/transição/seca).

| Estação excluída | N | Pearson | IC 95% | Classificação | Spearman | IC 95% | Classificação |
|---|---|---|---|---|---|---|---|
| chuvosa | 100 | 0.095 | [-0.210, 0.373] | IC inclui zero | 0.033 | [-0.227, 0.334] | IC inclui zero |
| transicao | 200 | 0.168 | [0.024, 0.286] | IC 95% ACIMA de zero | 0.203 | [0.051, 0.322] | IC 95% ACIMA de zero |
| seca | 180 | 0.156 | [0.043, 0.258] | IC 95% ACIMA de zero | 0.166 | [0.032, 0.296] | IC 95% ACIMA de zero |

O sinal não pertence exclusivamente a uma estação: excluir transição ou seca mantém IC 95% acima de zero; excluir a estação chuvosa (a maior das três, N cai para 100) reduz a amostra o bastante para o IC passar a incluir zero — consistente com perda de poder estatístico, não necessariamente com ausência de sinal fora da estação chuvosa. **Controle mensal (seções 2-4) continua sendo a análise principal — este agrupamento sazonal é só complementar.**

## 6. Diagnóstico complementar dos 12 meses (valores brutos por célula)

Descritivo — nenhum teste de significância por mês.

| Mês | N | Pearson | Spearman | Spread médio | Erro absoluto médio |
|---|---|---|---|---|---|
| Jan | 20 | -0.236 | -0.314 | 97.91 | 69.73 |
| Fev | 20 | 0.227 | 0.135 | 89.83 | 60.81 |
| Mar | 20 | 0.485 | 0.505 | 99.55 | 87.66 |
| Abr | 20 | 0.252 | 0.254 | 80.13 | 59.69 |
| Mai | 20 | 0.133 | 0.099 | 21.75 | 78.81 |
| Jun | 20 | 0.081 | 0.374 | 2.70 | 5.59 |
| Jul | 20 | -0.103 | -0.741 | 1.47 | 2.71 |
| Ago | 20 | -0.065 | 0.126 | 1.96 | 9.42 |
| Set | 20 | 0.058 | 0.188 | 8.32 | 45.16 |
| Out | 20 | 0.017 | 0.042 | 21.75 | 83.84 |
| Nov | 20 | 0.084 | 0.298 | 61.89 | 92.78 |
| Dez | 20 | -0.007 | 0.030 | 100.06 | 52.41 |

Sinal positivo mais forte (Pearson > 0,3): Mar. Sinal negativo (Pearson < -0,1): Jan, Jul. Próximo de zero: Fev, Abr, Mai, Jun, Ago, Set, Out, Nov, Dez.

## 7. Sensibilidade ao mês de maior associação

**Análise de INFLUÊNCIA, não seleção de modelo** — nenhuma destas exclusões decide a metodologia final.

- Mês com maior Pearson observado (célula bruta, seção 6): **Mar**.
- Mês com maior Spearman observado: **Mar**.
- Março é o mês de maior Pearson E maior Spearman — uma única análise ("sem março") atende aos itens "sem março", "sem o mês de maior Pearson" e "sem o mês de maior Spearman" simultaneamente.

| Cenário | N | Pearson | IC 95% | Spearman | IC 95% |
|---|---|---|---|---|---|
| H2 completo (referência) | 240 | 0.155 | [0.043, 0.256] | 0.180 | [0.036, 0.291] |
| Sem março | 220 | 0.069 | [-0.040, 0.174] | 0.124 | [-0.037, 0.242] |

Remover março leva Pearson ao seu valor MÍNIMO entre as 12 exclusões (ver seção 3) e o IC passa a incluir zero — março tem influência real, mas o sinal permanece positivo e numericamente próximo das demais exclusões (não há um colapso para valores negativos), o que é compatível com a classificação de robustez da seção 4.

## 8. Multiplicidade

Foram avaliados H1-H6 no gate principal controlado por mês e apenas H2 apresentou IC 95% totalmente acima de zero. Nenhuma correção formal de multiplicidade (Bonferroni/FDR) foi aplicada como novo critério de gate nesta atividade — mas um achado isolado entre seis horizontes é tratado aqui como evidência EXPLORATÓRIA que exige robustez interna (este documento) antes de justificar um novo modelo. H2 nunca é chamado de "validado".

## 9. Decisão sobre EMOS

**`prosseguir_para_protocolo_emos_h2`**

- `prosseguir_para_protocolo_emos_h2`: recomendado se a classificação de robustez (seção 4) for `sinal_h2_robusto`.
- `nao_justificar_emos_dinamico_h2`: se `sinal_h2_dependente_de_poucos_meses`.
- `h2_promissor_mas_evidencia_insuficiente`: se `sinal_h2_promissor_mas_fragil`.

**Nenhum EMOS foi implementado nesta atividade** — esta é só a decisão de próximo passo, condicionada à revisão independente deste resultado.

## 10. H1, H3-H6 — preservados como comparação (não repetidos)

Já falharam no gate principal controlado por mês (ver `docs/nmme-fase2c3d-gate-calibracao-probabilistica-cfsv2.md`); leave-one-month-out NÃO foi repetido para eles nesta atividade.

| Horizonte | Pearson residual (gate principal, congelado) |
|---|---|
| H1 | -0.023 |
| H3 | 0.115 |
| H4 | 0.011 |
| H5 | -0.069 |
| H6 | -0.046 |

## 11. Métricas congeladas (CRPS/CRPSS/Brier/BSS/cobertura/ranks/dependência)

**Não alteradas nesta atividade** — confirmado por teste de regressão automatizado (`tests/test_cfsv2_robustez_h2_spread.py`) comparando byte-a-byte contra o JSON do gate já publicado.

## 12. Escopo

Não implementados nesta atividade: EMOS, dressing, recalibração de membros, probabilidades operacionais. Não alterados: Métodos 3.1–3.4, gate 3.3, CFSv2 RAW, CHIRPS v3, dashboard, pipeline operacional.

## 13. Conclusão restrita a esta análise de robustez

Esta conclusão vale SOMENTE para a robustez do sinal spread×erro controlado por mês em H2 — nunca uma validação do Método 3.5 nem uma aprovação de EMOS.

- Classificação de robustez: `sinal_h2_robusto`.
- Decisão de próximo passo: `prosseguir_para_protocolo_emos_h2`.
- H2 permanece o único horizonte candidato a calibração probabilística dinâmica entre os seis avaliados — tratado aqui como achado exploratório robusto às 12 exclusões mensais e à maior parte das exclusões sazonais, nunca como "modelo validado".
- Implementação de EMOS (se decidida) permanece de uma próxima etapa, condicionada à revisão independente deste resultado.
