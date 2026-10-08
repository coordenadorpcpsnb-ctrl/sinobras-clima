# Protocolo do EMOS para H2 — Fase 2C.3D (Método 3.5)

**Documento de desenho experimental — não é relatório de resultados.**
Nenhum parâmetro `a`/`b`/`c`/`d` foi ajustado nesta atividade. Nenhum CRPS do
EMOS foi calculado. Nenhuma probabilidade calibrada foi produzida.
Nenhum pipeline operacional ou dashboard foi alterado. A única exceção
é um diagnóstico puramente **estrutural** de viabilidade do warm-up
proposto (seção 10) e do gate de viabilidade da escala (seção 6) —
ambos sem calcular skill, CRPS ou qualquer coisa que dependa de um
parâmetro ajustado.

A decisão científica que autoriza esta atividade (`classificacao_
robustez_h2 = sinal_h2_robusto`, commit `e7da9f6`, PR #47) **não
significa aprovação de EMOS nem demonstração definitiva de skill
probabilístico** — é só a autorização para escrever este protocolo.

## 1. Escopo

O EMOS será testado **exclusivamente para H2**. Motivo pré-registrado
(ver `docs/nmme-fase2c3d-robustez-spread-h2.md`): H2 foi o único
horizonte, entre os seis avaliados no gate do Método 3.5, que:

- manteve Pearson residual (controlado por mês) com IC 95% > 0;
- manteve Spearman residual (controlado por mês) com IC 95% > 0;
- passou no leave-one-month-out (positivo nas 12 exclusões, IC>0 em
  11/12 Pearson e 10/12 Spearman, nenhuma inversão forte);
- recebeu a classificação pré-registrada `sinal_h2_robusto`.

H1, H3–H6 não implementam EMOS nesta primeira versão — todos caíram em
`ensemble_mal_calibrado_spread_pouco_informativo` ou não atingiram o
critério de robustez. Uma eventual extensão a outros horizontes é uma
decisão separada, condicionada a uma análise de robustez própria para
cada um (não feita aqui).

## 2. Distribuição preditiva

**Normal censurada à esquerda em 0 mm.** Representação conceitual:

```
Z ~ Normal(mu, sigma²)
Y = max(0, Z)
```

Vantagens desta escolha, nesta ordem:

- Não produz valores negativos de precipitação (ao contrário da Normal
  não censurada).
- Tem massa de probabilidade em `Y = 0`, coerente com meses secos onde
  `P(chuva = 0)` não é desprezível.
- Permanece parcimoniosa: 2 parâmetros condicionais (`mu`, `sigma`),
  sem reparametrização elaborada.

**Decisões fixadas, não revisáveis dentro desta primeira versão:**

- Não usar a Normal não censurada.
- Não escolher a distribuição depois de observar qual gera melhor
  CRPS — a censurada em zero foi escolhida aqui, antes de qualquer
  ajuste real.
- Não testar simultaneamente Gamma, GEV, lognormal ou outras
  alternativas nesta primeira versão — um comparativo de família de
  distribuição é um protocolo e uma decisão separados, não desta
  atividade.

## 3. Localização / média probabilística

**Não** usar `mu = a + b * ensemble_mean` sobre precipitação bruta —
isso reintroduziria exatamente o confundimento sazonal que o gate já
expôs (seções 3/3.1 de `docs/nmme-fase2c3d-gate-calibracao-
probabilistica-cfsv2.md`).

Em vez disso, usar o espaço de anomalia já aprovado metodologicamente
(mesma convenção causal do Método 3.4 — MOS linear):

```
anom_ensemble = ensemble_mean - climatologia_modelo_raw
mu            = climatologia_observada + a + b * anom_ensemble
```

onde `climatologia_modelo_raw` e `climatologia_observada` são EXATAMENTE
os campos já causais e aprovados (`clim_modelo_media`/`clim_media` em
`cfsv2_validacao_cientifica._enriquecer_com_climatologia`,
reaproveitados sem redefinição) — ambos calculados com a disponibilidade
real daquela própria `init_date`, nunca recalculados retrospectivamente
com dados futuros.

Isso garante que o ciclo sazonal principal seja absorvido pelas duas
climatologias (a do modelo e a observada), deixando `a`/`b` livres para
ajustar prioritariamente o sinal interanual — não o ciclo sazonal, que
já é tratado antes de `a`/`b` entrarem na equação.

## 4. Benchmark de localização

Fixar `a = 0`, `b = 1` reduz `mu` a:

```
mu = climatologia_observada + anom_ensemble
   = climatologia_observada + (ensemble_mean - climatologia_modelo_raw)
```

que é exatamente o `benchmark_anomalia_reconstruida` já definido e usado
no Método 3.4 — a mesma identidade algébrica, mesmo nome, nunca uma
segunda fórmula paralela. Isso dá, de novo, um benchmark científico
diretamente interpretável: "o EMOS de localização, sem ajuste nenhum,
coincide com a reconstrução causal pela anomalia".

## 5. Dispersão — evitar confundimento sazonal

O gate (seção 2 de `docs/nmme-fase2c3d-gate-calibracao-probabilistica-
cfsv2.md`) já mostrou que `ensemble_std` bruto é fortemente sazonal.
**Não** usar, como primeira formulação, `sigma² = c + d * ensemble_std²`
sobre todos os meses agregados — isso herdaria o mesmo confundimento que
motivou toda a revisão sazonal do gate.

Em vez disso:

```
spread_clim_modelo_mes = climatologia EXPANSÍVEL causal de ensemble_std,
                          usando só inicializações históricas anteriores
                          do mesmo target_mes (mesmo padrão causal de
                          v.climatologia_modelo_expansivel, aplicado ao
                          spread em vez da média)

spread_relativo = ensemble_std / spread_clim_modelo_mes
                   (só quando o denominador é válido e > 0)

sigma = erro_clim_sd_mes * sqrt(c + d * spread_relativo²)
```

com `c >= 0`, `d >= 0`, e `erro_clim_sd_mes` definido como a **escala
climatológica base**:

```
erro_clim_sd_mes = desvio-padrão EXPANSÍVEL causal de erro_assinado
                    (ensemble_mean - obs), usando só inicializações
                    históricas anteriores do mesmo target_mes — mesmo
                    padrão causal de spread_clim_modelo_mes, aplicado
                    ao erro em vez do spread
```

Essa formulação separa deliberadamente dois efeitos:

- **heterogeneidade sazonal de escala** — absorvida por
  `erro_clim_sd_mes`, que varia naturalmente entre a estação seca
  (escala pequena) e a chuvosa (escala grande);
- **modulação dinâmica caso a caso** — o termo `spread_relativo²`, que
  é o que o gate e a análise de robustez de H2 efetivamente testaram
  (correlação spread×erro **controlada por mês**, nunca a correlação
  pooled).

## 6. Gate de viabilidade da escala

Antes de qualquer ajuste real, o protocolo exige confirmar que
`spread_clim_modelo_mes > 0` e `erro_clim_sd_mes > 0` nos casos
elegíveis. Diagnóstico estrutural executado nesta atividade (script
`scripts/cfsv2_emos_h2_viabilidade_warmup.py --executar`, SEM calcular
nenhum CRPS/skill):

- **216 de 240** inicializações de H2 têm par causal válido (as duas
  climatologias disponíveis e positivas).
- **Todos** os 216 casos válidos têm `spread_clim_modelo_mes > 0` e
  `erro_clim_sd_mes > 0` — nenhum denominador zero ou negativo foi
  encontrado, nem nos meses secos.
- Mínimos por mês (entre os casos válidos) ficam pequenos, mas
  claramente positivos, mesmo nos meses mais secos:

| Mês | N válidos | `spread_clim_modelo_mes` mínimo | `erro_clim_sd_mes` mínimo |
|---|---|---|---|
| Jun | 18 | 1,35 mm | 0,62 mm |
| Jul | 18 | 1,07 mm | 0,24 mm |
| Ago | 18 | 1,40 mm | 9,19 mm |
| Set | 18 | 4,33 mm | 33,25 mm |

(demais meses com mínimos de 15mm a 91mm — ver
`data/cfsv2_calibracao_2c3d/emos_h2_viabilidade_warmup_2c3d.json` para
a tabela completa dos 12 meses.)

**Conclusão do gate:** nenhum piso numérico precisa ser definido nesta
versão — os denominadores observados nunca chegam perto de zero, mesmo
nos meses mais secos. **Nenhum piso foi escolhido com base em
desempenho** (isso é proibido pelo próprio protocolo); se uma versão
futura com dados diferentes encontrar um denominador patologicamente
pequeno, o critério numérico precisa ser definido então, antes de
calcular qualquer skill — nunca depois.

## 7. Parâmetros

Modelo principal: **4 parâmetros globais** para H2 — `a`, `b`, `c`, `d`.

**Não** estimar parâmetros separados por mês. **Não** criar:

- 12 interceptos ou 12 slopes por mês;
- interação mês × spread;
- termos de ENSO;
- termos quadráticos adicionais;
- mixture model.

A sazonalidade entra pelas climatologias/escala causais (`climatologia_
modelo_raw`, `climatologia_observada`, `erro_clim_sd_mes`), nunca por
dezenas de coeficientes extras — mesma filosofia de parcimônia já usada
no MOS linear (Método 3.4): poucos parâmetros, sazonalidade absorvida
pelas climatologias, nunca por um mês-dummy.

## 8. Restrições

Impor sempre:

```
c >= 0
d >= 0
sigma > 0   (verificado linha a linha, nunca assumido)
```

Para `a` e `b`, **não** impor truncamento arbitrário. Registrar
(nunca impedir silenciosamente) se o ajuste real produzir:

- `b < 0` (destaque científico obrigatório — investigar antes de
  qualquer conclusão, mesma convenção já usada no MOS linear);
- `b ≈ 0` (anomalia do CFSv2 praticamente ignorada);
- `b ≈ 1` (comportamento próximo do benchmark de localização, seção 4);
- `b > 1` (amplificação da anomalia do CFSv2).

## 9. Treinamento causal

Avaliação principal: **expanding-window**. Para cada `init_date` de H2
avaliada:

- usar SOMENTE casos de treino com `init_date_treino < init_date_avaliada`
  (nunca `<=`);
- nunca usar a própria linha avaliada no ajuste;
- nunca usar informação futura;
- todos os componentes causais de cada linha histórica (climatologia do
  modelo, climatologia observada, `spread_clim_modelo_mes`,
  `erro_clim_sd_mes`) devem ser os que estavam REALMENTE disponíveis
  naquela `init_date` — nunca recalculados com o benefício de dados
  publicados depois.

## 10. Warm-up

**Não** escolher o warm-up por skill. Com 4 parâmetros EMOS, uma regra
conservadora e pré-registrada equivalente ao warm-up do MOS linear
(Método 3.4, `N_TREINO_MINIMO_MOS = 120`) e a ~30 observações por
parâmetro:

```
N_TREINO_MINIMO_EMOS = 120 casos válidos
```

**Viabilidade estrutural calculada nesta atividade** (SEM nenhum
CRPS/skill do EMOS — script `cfsv2_emos_h2_viabilidade_warmup.py`):

| Quantidade | Valor |
|---|---|
| Inicializações de H2 no total | 240 |
| Pares H2 válidos (causal, ambas climatologias + spread/erro mensais > 0) | 216 |
| Primeira `init_date` elegível (`n_treino_disponivel >= 120`) | `2003-01` |
| `n_treino_disponivel` nessa data | 120 |
| **Previsões finais avaliáveis** | **96** |

**Trazido para revisão, não resolvido aqui** (conforme item 10 do
pedido): `N_TREINO_MINIMO_EMOS = 120` consome **mais da metade** (120
de 216, ~56%) dos pares válidos só para treino, deixando **96**
previsões para a avaliação principal — uma janela de avaliação
sensivelmente mais curta que a amostra completa de 240 inicializações.
Isso não foi reduzido automaticamente. Antes de implementar, a revisão
deve decidir se 96 previsões avaliáveis são suficientes para uma
inferência probabilística confiável sobre H2, ou se um warm-up menor
(com a troca correspondente em estabilidade dos 4 parâmetros) é
preferível.

## 11. Estimação dos parâmetros

Método pré-registrado: **minimização do CRPS médio da Normal censurada
em zero** sobre a janela de treinamento (expanding, causal).

- **Não** minimizar RMSE.
- **Não** maximizar log-likelihood como primeira alternativa.
- Motivo: CRPS é a métrica probabilística PRINCIPAL já usada em todo o
  projeto (Métodos de validação 2C.3C, gate do Método 3.5) e avalia
  localização e dispersão simultaneamente — manter a mesma métrica de
  ajuste e de avaliação evita um descompasso entre o que o modelo
  otimiza e o que o relatório reporta.
- A implementação futura deve usar **uma única função objetivo**,
  documentada e testada (CRPS fechado da Normal censurada em zero, ou
  sua forma amostral — a escolha exata de fórmula fica para a
  implementação, não para este protocolo).

## 12. Otimização

Pré-registrado para a implementação futura:

- algoritmo determinístico (ex.: `scipy.optimize.minimize`, já
  disponível no projeto — ver `requirements.txt`);
- seed fixa se houver qualquer componente estocástico (ex.: otimizador
  com reinícios aleatórios);
- limites/restrições explícitos (`c >= 0`, `d >= 0`) passados ao
  otimizador, nunca impostos só por checagem posterior;
- critérios de convergência documentados (tolerância, número máximo de
  iterações);
- **STOP-ON-FAILURE** quando o otimizador não convergir — nunca
  silenciosamente aceitar um resultado não convergido.
- **Não** testar vários otimizadores e escolher o que produz o melhor
  score — um único otimizador, decidido antes de ver o resultado.

## 13. Benchmarks probabilísticos obrigatórios

EMOS H2 deve ser comparado, **nos MESMOS casos avaliáveis**, contra:

1. **Ensemble RAW CFSv2** (sem qualquer correção) — mesma definição já
   usada no gate (`crps_amostral` sobre os 24 membros brutos).
2. **Climatologia causal observada probabilística** — mesma definição
   já usada no gate e na 2C.3C (`anos_hist` elegíveis).
3. **Versão probabilística SEM spread dinâmico** (`EMOS d=0`) —
   modelo restrito que mantém a MESMA estrutura de média (seção 3) e de
   escala climatológica (`erro_clim_sd_mes`), mas fixa `d = 0`:
   ```
   sigma_d0 = erro_clim_sd_mes * sqrt(c)
   ```
   Este terceiro benchmark é **essencial** — responde diretamente se o
   termo dinâmico do spread melhora a previsão probabilística, ou se
   basta corrigir média e dispersão climatológica (sem usar o spread
   caso a caso). É o benchmark probabilístico CENTRAL desta fase.

## 14. Comparação EMOS completo × EMOS sem spread

A ser calculado na implementação futura (NÃO nesta atividade):

```
CRPSS_spread_dinamico = 1 - CRPS_EMOS_completo / CRPS_EMOS_d0
```

com bootstrap em blocos por `target_ano` (mesmo padrão causal já usado
em todo o gate e na robustez de H2). Este é o teste mais direto da
hipótese levantada pelo gate — e deve ser calculado e reportado
explicitamente, nunca inferido indiretamente de outras comparações.

**Se o IC 95% de `CRPSS_spread_dinamico` incluir zero: não afirmar que
o spread dinâmico acrescenta valor**, mesmo que o EMOS completo supere
o ensemble RAW — a melhoria, nesse caso, viria só da correção de
média/dispersão climatológica, não do termo `d * spread_relativo²`.

## 15. Métricas

Pré-registradas para H2 (calculadas na implementação futura):

- CRPS médio (EMOS completo);
- CRPSS vs. RAW;
- CRPSS vs. climatologia causal;
- CRPSS vs. EMOS `d=0` (seção 14 — o teste central);
- Brier Score por tercil (reaproveitando as mesmas categorias/
  referência nominal já aprovadas na 2C.3C e no gate — nunca
  redefinidas);
- BSS;
- cobertura empírica 50/80/90% (da distribuição Normal censurada
  ajustada, não mais dos 24 membros brutos);
- largura média dos intervalos;
- PIT (Probability Integral Transform) ou rank probabilístico
  apropriado à distribuição contínua censurada — nunca o rank
  histogram discreto dos 24 membros (que não se aplica a uma
  distribuição contínua ajustada);
- Bias da média/mediana preditiva, como diagnóstico complementar
  (nunca como critério de aprovação isolado).

**Não** aprovar o modelo só por cobertura — cobertura isolada não
distingue, como o próprio gate já registrou, se o problema é de
localização ou de dispersão.

## 16. Critério de aprovação

Para justificar o componente dinâmico de spread, exigir, SIMULTANEAMENTE:

1. `IC 95%(CRPSS_spread_dinamico) > 0` (seção 14) — condição
   necessária, não suficiente por si só.
2. EMOS completo supera a climatologia probabilística causal com
   `IC 95%(CRPSS vs. climatologia) > 0`.
3. Nenhuma degradação grave de Brier Score/BSS em relação aos
   benchmarks.
4. Melhora substancial na calibração de cobertura/PIT frente ao
   ensemble RAW (que o gate já mostrou underdispersive com componente
   de bias — seção 4.1 do relatório do gate).

**Se o EMOS só superar o RAW mas não a climatologia: não aprovar.** O
RAW já é conhecidamente fraco (CRPSS negativo em todos os horizontes no
gate) — superá-lo não é uma barra suficiente.

## 17. Bootstrap

Sempre em blocos por `target_ano` (mesmo padrão de todo o projeto desde
a 2C.3C). Nos MESMOS anos sorteados em cada reamostra, comparar
simultaneamente:

- EMOS completo;
- EMOS `d=0`;
- RAW;
- climatologia causal.

**Não** calcular ICs independentes para cada um e depois combinar ou
dividir médias separadamente — o numerador e o denominador de cada
CRPSS precisam vir do MESMO sorteio de anos (mesma lição já aplicada em
toda a 2C.3C/2C.3D).

## 18. Avaliação mensal

H2 pode ser avaliado posteriormente por mês **somente como
diagnóstico** descritivo (mesmo padrão da matriz mês×lead já usada no
gate e na robustez de H2) — **não** ajustar um EMOS separado por mês,
**não** fazer 12 testes formais de significância.

Dar atenção a março, que foi o mês de maior influência na análise de
robustez (seção 3.2.1 e 7 de `docs/nmme-fase2c3d-robustez-spread-h2.md`)
— mas **não** tratá-lo de forma diferente no modelo (nenhum parâmetro
específico de março, nenhuma exclusão automática).

## 19. LOYO

Pode haver um LOYO (leave-one-year-out) como diagnóstico secundário,
mesmo padrão já usado nos Métodos 3.1–3.4. **Nunca** usado como
avaliação operacional. Se implementado, a comparação expanding × LOYO
precisa usar exatamente os mesmos casos (`matched`), nunca comparar
amostras diferentes diretamente — mesma lição já registrada no MOS
linear (Método 3.4).

## 20. Testes futuros obrigatórios

A implementação futura deve incluir testes para:

- censura em zero corretamente aplicada (`Y = max(0, Z)`);
- probabilidade em `Y = 0` corretamente calculada pela CDF da Normal
  não-censurada em `0`;
- CRPS de casos sintéticos conhecido/verificado à mão (fórmula fechada
  da Normal censurada, ou comparação numérica contra integração);
- `c >= 0`, `d >= 0` sempre respeitados (nunca silenciosamente violados
  pelo otimizador);
- `sigma` sempre positivo, linha a linha;
- ausência de leakage (nenhuma linha de treino com `init_date >=
  avaliada`; nenhum dado futuro em nenhuma climatologia);
- climatologias históricas preservadas linha a linha (mesma garantia já
  testada no MOS linear);
- `spread_relativo` calculado apenas com `spread_clim_modelo_mes`
  CAUSAL (nunca com uma climatologia do spread calculada
  retrospectivamente);
- `d=0` realmente remove TODA informação caso a caso do spread (ou
  seja, `sigma_d0` não depende de `ensemble_std` de forma alguma);
- as MESMAS chaves (`init_date × lead`) em todos os benchmarks
  comparados;
- bootstrap usando os MESMOS anos sorteados entre EMOS completo, EMOS
  `d=0`, RAW e climatologia.

## 21. Limitações a registrar

- H2 foi 1 horizonte entre 6 avaliados — nenhuma correção formal de
  multiplicidade (Bonferroni/FDR) foi aplicada como critério de gate;
  a evidência é tratada como exploratória, ainda que robusta
  internamente (12/12 exclusões mensais positivas, 11/12 e 10/12 com
  IC>0).
- O período histórico é curto (240 inicializações de H2, 216 pares
  válidos, e o warm-up proposto consumiria quase 56% deles).
- Os 24 membros do ensemble NÃO equivalem a 24 amostras temporais
  independentes (dependência par-a-par alta mesmo após remoção da
  climatologia mensal — seção 8 do relatório do gate).
- O spread contém informação MODESTA (correlações residuais na faixa
  de 0,07 a 0,24), não FORTE — isso deve ser comunicado explicitamente
  em qualquer relatório futuro de resultados, nunca inflado.
- Calibração probabilística não cria skill dinâmico que não existe —
  o EMOS pode, na melhor das hipóteses, extrair o sinal modesto já
  identificado; não deve ser apresentado como uma fonte de skill nova.

## 22. Esta atividade é protocolo apenas

**Não realizado nesta atividade:**

- ajuste de `a`, `b`, `c`, `d`;
- cálculo de CRPS do EMOS;
- produção de probabilidades calibradas;
- alteração do pipeline operacional;
- alteração do dashboard.

**Realizado nesta atividade** (e só isso, além deste documento):
diagnóstico estrutural de viabilidade do warm-up e do gate de
viabilidade da escala (seções 6 e 10), via
`scripts/cfsv2_emos_h2_viabilidade_warmup.py` — nenhum CRPS, skill ou
parâmetro ajustado nesse script; só contagens de disponibilidade
causal.

Suíte de testes existente e `scripts/verificar_dashboard.py` foram
executados só para confirmar ausência de regressão — não para validar
nenhum resultado novo de EMOS (que não existe nesta atividade).
