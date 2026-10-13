# Auditoria causal de disponibilidade observacional — Método 3.4 (MOS linear)

Fase 2C.3D. Esta atividade audita e corrige a regra de treino causal do
Método 3.4 (MOS linear pooled-by-lead, `scripts/cfsv2_calibracao_mos_linear.py`),
que apresentava a MESMA classe de bug já encontrada e corrigida no
protocolo EMOS H2 (`docs/nmme-fase2c3d-protocolo-emos-h2.md`, Seção 11):
a regra causal exigia só que a **previsão** da linha de treino já
existisse (`init_date_treino < init_date_avaliada`), nunca que sua
**observação-alvo** (`target_month_treino = init_date_treino + (lead-1)`)
já tivesse sido verificada. Para H1 (`lead=1`) as duas noções coincidem
(`target_month == init_date`) — H1 é, por desenho, o controle negativo
desta auditoria. Para H2-H6 (`lead>=2`) elas divergem, e a regra antiga
incluía indevidamente, no treino de cada avaliação, as `lead-1`
inicializações mais recentes — previsões cuja observação ainda não
tinha ocorrido no momento avaliado.

**Esta atividade NÃO implementa EMOS.** É só a correção da própria
regra causal do Método 3.4, independente do protocolo EMOS (que já
incorporou a correção equivalente para H2 numa rodada anterior).

## 1. Problema original

`construir_tabela_mos_linear` (regra antiga) crescia o histórico de
pares válidos linha a linha, em ordem de `init_date`, e usava **todo**
o histórico acumulado até aquele ponto como treino — ou seja, a única
condição aplicada era `init_date_treino < init_date_avaliada`. Nenhuma
verificação de `target_month_treino` existia.

Exemplo concreto (H2, igual ao já documentado no EMOS): avaliando
`init_date_avaliada = 2003-01`, a linha de treino com
`init_date_treino = 2002-12` tem `target_month_treino = 2003-01` — a
MESMA observação-alvo do mês sendo avaliado, que ainda não tinha
ocorrido no momento da avaliação. A regra antiga a incluía; a correta
não pode.

## 2. Auditoria (antes de qualquer correção de métrica)

Script dedicado, só leitura: `scripts/cfsv2_auditoria_mos_disponibilidade.py`
(saída: `data/cfsv2_calibracao_2c3d/auditoria_disponibilidade_mos_2c3d.json`).
Para cada H1-H6, recalcula — a partir da MESMA base causal já aprovada
da 2C.3C, 100% programaticamente, nenhum número hardcoded — o treino
sob as duas regras (antiga e corrigida), para cada previsão então
elegível pela regra antiga.

| Horizonte | Previsões elegíveis (regra antiga) | Previsões afetadas | Inclusões indevidas **acumuladas** | Linhas históricas **únicas** indevidamente incluídas | Máx. indevidas / avaliação | Teto esperado (`lead-1`) |
|---|---|---|---|---|---|---|
| H1 | 108 | 0   | 0   | 0   | 0 | 0 |
| H2 | 108 | 108 | 108 | 108 | 1 | 1 |
| H3 | 108 | 108 | 216 | 109 | 2 | 2 |
| H4 | 108 | 108 | 324 | 110 | 3 | 3 |
| H5 | 108 | 108 | 432 | 111 | 4 | 4 |
| H6 | 108 | 108 | 540 | 112 | 5 | 5 |

"Inclusões indevidas acumuladas" soma, por horizonte, quantas vezes (ao
longo de todas as avaliações) uma linha de treino sem observação
verificada entrou indevidamente no ajuste — a mesma linha histórica
pode ser contada várias vezes (uma por avaliação em que apareceu
indevidamente). "Linhas históricas únicas" conta cada linha de treino
distinta só uma vez.

O padrão observado bate EXATAMENTE com a expectativa estrutural de
auditoria (nunca usada para produzir os números acima, só para
compará-los depois: para `lead=L`, o teto de inclusões indevidas por
avaliação é `L-1`, pela aritmética de calendário de
`target_month=init_date+(lead-1)`) — confirmado programaticamente, sem
divergência em nenhum horizonte.

## 3. Correção aplicada

`construir_tabela_mos_linear` agora filtra o treino de cada avaliação
por `_indices_treino_causal` — exige SIMULTANEAMENTE:

```
init_date_treino   < init_date_avaliada
target_month_treino < init_date_avaliada
```

(nunca `<=` — disponibilidade intramês nunca foi demonstrada). Novas
colunas por linha: `max_init_date_treino`, `max_target_month_treino`.
`N_TREINO_MINIMO_MOS = 120` continua pares válidos, contados **depois**
de todos os filtros (nunca reduzido para recuperar amostra).
`_verificar_nenhum_leakage_na_tabela_mos` e
`_verificar_outro_lead_nunca_contaminou_treino` foram estendidas para
exigir a condição nova — ambas `STOP_ON_FAILURE` se violadas.
`construir_tabela_mos_linear_loyo` (LOYO retrospectivo) **não foi
tocada** — é deliberadamente não causal, usa passado e futuro por
desenho, e a correção não se aplica a ela.

## 4. Impacto quantitativo — ANTES × DEPOIS

Valores "antes" (`resultado_pre_correcao_disponibilidade_observacional`)
são os já aprovados no commit `319ad4c`, preservados aqui — nunca
apagados da documentação histórica.

### Primeira inicialização elegível e N final

| Horizonte | Primeira elegível (antes) | Primeira elegível (depois) | N (antes) | N (depois) |
|---|---|---|---|---|
| H1 | 2002-01 | 2002-01 | 108 | 108 |
| H2 | 2002-01 | 2002-02 | 108 | 107 |
| H3 | 2002-01 | 2002-03 | 108 | 106 |
| H4 | 2002-01 | 2002-04 | 108 | 105 |
| H5 | 2002-01 | 2002-05 | 108 | 104 |
| H6 | 2002-01 | 2002-06 | 108 | 103 |

`n_treino_mos` na primeira elegibilidade é exatamente 120 em todos os
horizontes, antes e depois — confirmado, nunca assumido.

### Métricas determinísticas

| H | RMSE antes | RMSE depois | skill\_benchmark3 antes | skill\_benchmark3 depois | RMSESS\_clim antes | RMSESS\_clim depois | alpha mediano antes | alpha mediano depois | beta mediano antes | beta mediano depois |
|---|---|---|---|---|---|---|---|---|---|---|
| H1 | 48.3781 | 48.3781 | 0.010368 | 0.010368 | 0.154929 | 0.154929 | -8.0018 | -8.0018 | 0.5981 | 0.5981 |
| H2 | 55.3478 | 55.6013 | -0.001378 | -0.002293 | 0.021583 | 0.020926 | -6.8963 | -6.8329 | 0.2537 | 0.2532 |
| H3 | 55.5940 | 55.0858 | -0.019069 | -0.012457 | 0.028483 | 0.023755 | -6.6789 | -6.5891 | 0.3743 | 0.3743 |
| H4 | 54.8486 | 55.0491 | 0.000916 | 0.002745 | 0.028775 | 0.028926 | -5.6280 | -5.6279 | 0.4576 | 0.4575 |
| H5 | 54.8758 | 55.7271 | -0.008135 | -0.006099 | 0.019738 | 0.021800 | -5.7565 | -5.7565 | 0.2860 | 0.2860 |
| H6 | 56.0366 | 57.1206 | 0.027437 | 0.028763 | -0.001752 | 0.000234 | -4.8586 | -4.8607 | 0.3831 | 0.3835 |

**H1 é numericamente IDÊNTICO (bit a bit) antes e depois** — confirma
o controle negativo previsto: para `lead=1`, `target_month==init_date`,
então as duas condições da regra corrigida colapsam numa só, idêntica
à antiga (ver `tests/test_cfsv2_mos_linear_auditoria_disponibilidade.py::H1NaoAfetadoTestCase`).

H2-H6 mudam, mas em magnitude pequena (removendo só 1-5 das ~108
avaliações, e o ajuste OLS de cada avaliação individual perde só as
`lead-1` linhas mais recentes de um histórico que já tinha centenas de
pares — a maior parte do histórico de treino de cada avaliação
individual não muda).

### Intervalos de confiança (bootstrap em blocos por ano, 500 reamostras)

| H | skill\_benchmark3 IC95 antes | classificação antes | skill\_benchmark3 IC95 depois | classificação depois | RMSESS\_clim IC95 antes | classificação antes | RMSESS\_clim IC95 depois | classificação depois |
|---|---|---|---|---|---|---|---|---|
| H1 | [-0.0790, 0.1291] | inclui zero | [-0.0790, 0.1291] | inclui zero | [0.0565, 0.2168] | **acima de zero** | [0.0565, 0.2168] | **acima de zero** |
| H2 | [-0.0820, 0.0950] | inclui zero | [-0.0843, 0.0934] | inclui zero | [-0.0027, 0.0507] | inclui zero | [-0.0038, 0.0499] | inclui zero |
| H3 | [-0.0963, 0.0405] | inclui zero | [-0.0881, 0.0487] | inclui zero | [-0.0038, 0.0691] | inclui zero | [-0.0067, 0.0674] | inclui zero |
| H4 | [-0.0289, 0.0397] | inclui zero | [-0.0283, 0.0458] | inclui zero | [-0.0051, 0.0855] | inclui zero | [-0.0048, 0.0850] | inclui zero |
| H5 | [-0.0339, 0.0180] | inclui zero | [-0.0321, 0.0209] | inclui zero | [-0.0049, 0.0679] | inclui zero | [-0.0024, 0.0702] | inclui zero |
| H6 | [-0.0068, 0.0560] | inclui zero | [-0.0052, 0.0574] | inclui zero | [-0.0406, 0.0528] | inclui zero | [-0.0403, 0.0544] | inclui zero |

## 5. Critério de aprovação (pré-registrado, nunca alterado após ver resultados)

Critério inalterado: um horizonte só aprova se IC95(skill vs.
`benchmark_anomalia_reconstruida`) **e** IC95(RMSESS\_climatologia)
estiverem SIMULTANEAMENTE acima de zero.

**Resultado ANTES e DEPOIS da correção: nenhum horizonte passa o
critério** — H1 tem RMSESS\_climatologia acima de zero, mas falha em
skill vs. benchmark3; todos os demais horizontes falham nos dois. A
frase já registrada "sem evidência de ganho sobre o aditivo"
permanece válida — a correção não muda a conclusão de aprovação em
nenhum horizonte, embora mude a magnitude das métricas em H2-H6.

## 6. Impacto na comparação com o Método 3.1 (aditivo)

`skill_mos_vs_aditivo` permanece negativo (MOS pior que o aditivo) em
H1-H5 antes e depois, e positivo só em H6 antes e depois — o sinal da
comparação não muda em nenhum horizonte; só a magnitude varia dentro
da mesma faixa pequena observada nas demais métricas.

## 7. Conclusão científica corrigida do Método 3.4

A correção da disponibilidade observacional **não altera a conclusão
de aprovação do Método 3.4** (nenhum horizonte habilitado para
substituir o aditivo), mas é uma correção metodológica real e
necessária: antes dela, a simulação operacional expanding de H2-H6
usava, em toda avaliação, previsões de 1 a 5 meses no futuro como se
já fossem observação passada conhecida — um leakage observacional
real, independente de ter mudado ou não o resultado agregado desta
vez. A primeira inicialização elegível de cada horizonte agora reflete
corretamente `lead-1` meses adicionais de warm-up, e `N_TREINO_MINIMO_MOS`
é contado só depois de toda a disponibilidade real ser respeitada.

H1 funciona como controle negativo que reforça a confiança na
implementação: por não ter a lacuna estrutural (target_month==init_date),
seus resultados são bit-a-bit idênticos antes e depois — se tivessem
mudado, seria evidência de um bug na correção, não da correção em si.

## 8. O que NÃO foi alterado nesta atividade

Método 3.1 (aditivo), Método 3.2 (multiplicativo), gate 3.3, gate
probabilístico (Método 3.5), robustez de H2, protocolo/viabilidade do
EMOS H2, CFSv2 RAW, CHIRPS v3 histórico, dashboard, pipeline
operacional — nenhum tocado (confirmado via diff, ver
`tests/test_cfsv2_calibracao_mos_linear.py::ComDadosReaisTestCase::test_j_metodos_3_1_e_3_2_permanecem_byte_identicos`).
LOYO retrospectivo (`mos_linear_loyo.csv`) também não foi alterado
metodologicamente — a pequena diferença numérica de 1 ULP observada em
`condicao_numerica` ao regenerar o arquivo é ruído de ponto flutuante
entre builds de numpy/BLAS diferentes (ambiente deste container vs. o
que gerou o arquivo anteriormente), não uma mudança de regra; nenhuma
métrica de skill/RMSE do LOYO foi afetada.

## 9. Limitações desta auditoria

- O teste de robustez multiplicidade (H2 é 1 de 6 horizontes testados)
  já discutido no gate probabilístico continua se aplicando aqui sem
  correção adicional — nenhuma correção de Bonferroni/FDR foi aplicada.
- Esta auditoria cobre só a disponibilidade observacional da janela de
  treino — não reavalia as demais premissas já aprovadas do Método 3.4
  (pooling entre meses, warm-up mínimo, proteções numéricas do OLS).
- O protocolo EMOS H2 já tinha corrigido a mesma lacuna, de forma
  independente, antes desta auditoria existir — as duas correções são
  consistentes (mesma regra causal), mas foram implementadas e
  testadas em módulos separados.
