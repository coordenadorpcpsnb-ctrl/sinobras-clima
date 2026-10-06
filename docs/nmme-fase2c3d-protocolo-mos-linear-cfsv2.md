# Protocolo do MOS linear no espaço de anomalias — Fase 2C.3D (Método 3.4)

**Documento de desenho experimental — não é relatório de resultados.**
Nenhuma regressão foi ajustada nesta atividade. Nenhum `alpha`/`beta` real
foi calculado. Nenhum `forecast_mos` foi produzido. Nenhum RMSE, MAE,
correlação, skill ou IC do Método 3.4 existe neste documento. Nenhum dado
operacional (dashboard, SARIMAX, XGBoost, pipeline de produção,
`serie_subst.csv`), CFSv2 RAW, CHIRPS v3 histórico, nem os artefatos já
aprovados dos Métodos 3.1 (`aditiva_expanding.csv`), 3.2
(`multiplicativa_expanding.csv`) ou do gate de viabilidade do Método 3.3
(`viabilidade_quantile_mapping.json`) foram alterados. Este documento só
define o modelo matemático, a unidade de treinamento, o warm-up, as
proteções numéricas, os benchmarks e o critério de aprovação — a
implementação é uma atividade futura separada, condicionada à revisão
deste protocolo.

## 1. Modelo principal pré-registrado — regressão linear no espaço de anomalias

Para cada previsão, as anomalias (nunca a precipitação absoluta) são a
unidade da regressão:

```
anom_modelo_raw  = forecast_raw  - climatologia_modelo_raw
anom_observada   = observacao    - climatologia_observada
```

`climatologia_modelo_raw` e `climatologia_observada` são as MESMAS
climatologias causais já aprovadas e usadas nos Métodos 3.1/3.2
(`climatologia_modelo_expansivel`/`climatologia_expansivel`, 2C.3C) —
nunca recalculadas de outra forma aqui.

Para cada horizonte H1-H6, ajustado SEPARADAMENTE (nunca um único modelo
para todos os leads):

```
anom_observada = alpha_lead + beta_lead * anom_modelo_raw + erro
```

Reconstrução para a escala física (mm), para permitir comparação direta
com os métodos já aprovados:

```
forecast_mos = climatologia_observada + alpha_lead + beta_lead * anom_modelo_raw
```

**Apenas 2 parâmetros por horizonte: `alpha_lead` (intercepto) e
`beta_lead` (coeficiente da anomalia do CFSv2).** Nesta primeira versão,
NÃO incluir:

- mês como variável dummy;
- interação mês × previsão;
- índices ENSO ou qualquer outro índice climático;
- tendência temporal;
- termos quadráticos ou de ordem superior;
- regularização escolhida por validação (Ridge/Lasso/ElasticNet — ver
  Seção 7);
- seleção automática de variáveis.

A simplicidade é deliberada: minimizar o risco de overfitting dado o
tamanho de amostra disponível (Seção 5/6) — qualquer extensão do modelo é
uma decisão SEPARADA, futura, explicitamente justificada, nunca
adicionada "de passagem" durante a implementação deste protocolo.

## 2. Relação com o `benchmark_anomalia_reconstruida` — comparação CENTRAL

Já aprovado na 2C.3C/2C.3D:

```
benchmark_anomalia_reconstruida = climatologia_observada + anom_modelo_raw
```

Isto é **algebricamente o caso especial do modelo da Seção 1 com
`alpha=0` e `beta=1`** — sem nenhum ajuste causal, o benchmark 3 assume
que a anomalia do modelo é usada tal como está, sem offset nem
reescalonamento. Registrado explicitamente, nunca reafirmado como "um
benchmark qualquer":

| Quantidade estimada causalmente | O que testa |
|---|---|
| `alpha` (offset) | Se a anomalia do CFSv2 tem um viés sistemático residual que uma constante aditiva corrige — além do que a climatologia própria do modelo já removeu. |
| `beta` (amplitude) | Se o sinal de anomalia do CFSv2 precisa ser amortecido (`beta<1`) ou amplificado (`beta>1`) para corresponder à amplitude real da anomalia observada — o benchmark 3 assume implicitamente `beta=1`, nunca testado antes desta atividade. |

**Portanto, o MOS testa diretamente se estimar `alpha` e `beta`
causalmente melhora sobre o benchmark de anomalia já aprovado na 2C.3C —
esta é a comparação CENTRAL de todo o Método 3.4** (ver Seção 9 e Seção
11), não uma comparação secundária entre várias.

## 3. Unidade de treinamento — por lead, agregando todos os meses (pooling deliberado)

**Nunca treinar separadamente por `lead × mês`.** Treinar por `lead`,
agregando todos os meses históricos disponíveis daquele horizonte.

**Motivo**: uma regressão `lead × mês` teria no máximo 10-19 observações
históricas por célula (ver o gate de viabilidade do Método 3.3,
`docs/nmme-fase2c3d-viabilidade-quantile-mapping.md` — máximo N causal
confirmado = 19 em todas as 72 células) — amostra insuficiente para uma
regressão estável, com o mesmo risco de overfitting já documentado para
quantile mapping.

**Por que o pooling ENTRE MESES é permitido aqui, ao contrário dos
Métodos 3.1/3.2 e do gate do Método 3.3** (nenhum dos quais faz pooling
entre meses ou leads):

- o modelo trabalha em ANOMALIAS, não em precipitação absoluta;
- o ciclo sazonal já foi removido por climatologias causais PRÓPRIAS
  (`climatologia_modelo_raw` para o modelo, `climatologia_observada` para
  a observação) antes de qualquer ajuste de regressão;
- o objetivo é estimar uma relação GERAL entre anomalia prevista e
  anomalia observada, válida para aquele horizonte como um todo — não uma
  relação específica de um mês-calendário.

**Nunca fazer pooling entre leads** — cada `beta_lead`/`alpha_lead` é
estimado e avaliado isoladamente, nunca uma única regressão abrangendo
H1-H6 simultaneamente (consistente com `ROTULO_HORIZONTE` nunca
agregado, já estabelecido desde a 2C.3C).

## 4. Treino causal

Para uma previsão em `init_date`, usar somente registros do MESMO lead
com:

```
init_date_treino < init_date_avaliada
```

**Nunca `<=`** — mesma regra estrita já usada nos Métodos 3.1/3.2.

As anomalias de TREINO também devem usar somente climatologias que eram
causalmente disponíveis na data daquele registro histórico — ou seja,
`anom_modelo_raw` e `anom_observada` de uma observação histórica usada no
treino de uma previsão em 2005 são calculadas com as climatologias que
estavam disponíveis EM 2005 (ou antes), nunca recalculadas
retrospectivamente com a climatologia mais recente/mais completa
disponível hoje. **Nunca recalcular retrospectivamente as anomalias
históricas usando climatologia futura** — isso seria leakage mesmo que o
`alpha`/`beta` em si sejam treinados só com `init_date < init_date_avaliada`,
porque a climatologia embutida em cada anomalia de treino já teria
"visto" dados que não estariam disponíveis na época.

## 5. Warm-up

Pré-registrado, **antes de qualquer execução**:

```
N_TREINO_MINIMO_MOS = 120
```

Aproximadamente 10 anos × 12 meses por horizonte (consistente com o
pooling entre meses da Seção 3 — a unidade de contagem agora é "quantas
observações históricas daquele lead, de qualquer mês, estão disponíveis
causalmente", não mais por célula lead×mês como nos Métodos 3.1/3.2).

Enquanto `n_treino < 120`:

```
status_mos = warmup_amostra_insuficiente
```

**Nenhum forecast MOS válido é produzido para a avaliação principal.**
Regras obrigatórias, idênticas em espírito às dos Métodos 3.1/3.2:

- **Nunca** usar a previsão bruta como fallback.
- **Nunca** usar o `benchmark_anomalia_reconstruida` como fallback.
- **Nunca** imputar coeficientes (nem de outro lead, nem de uma média
  assumida).

**A data real da primeira previsão elegível deve ser DERIVADA
PROGRAMATICAMENTE** a partir da contagem efetiva de observações
históricas causais, nunca hardcoded. Com base na estrutura atual do CFSv2
(240 inicializações, jan/1991-dez/2010, 12 observações/ano por lead após
o pooling entre meses da Seção 3), **espera-se** aproximadamente avaliação
principal em 2001-2010 (120 observações/ano-base ÷ 12 meses = 10 anos de
warm-up) — mas esta é só uma expectativa a ser CONFIRMADA pela
implementação real, nunca assumida ou hardcoded no código.

## 6. Justificativa do warm-up — registrada antes da execução

- 2 parâmetros por regressão (`alpha_lead`, `beta_lead`).
- Mínimo de 120 observações históricas.
- Razão de aproximadamente **60 observações por parâmetro** — muito mais
  conservador que uma eventual regressão `lead × mês` (que teria, no
  máximo, 19 observações para 2 parâmetros, razão ~9,5 — já insuficiente
  pelos padrões usuais de regressão, e é exatamente por isso que o
  Método 3.3 foi declarado não testável e que este protocolo rejeita
  pooling por célula).
- **Não testar vários valores de warm-up e escolher o que produz melhor
  skill.** 120 é o valor PRINCIPAL pré-registrado por este documento,
  antes de qualquer execução. Uma eventual análise de sensibilidade com
  outro mínimo só pode ser feita DEPOIS, explicitamente separada e
  rotulada como sensibilidade — nunca como substituto da análise
  principal, mesma regra já aplicada ao `N_TREINO_MINIMO=10` dos Métodos
  3.1/3.2.

## 7. Estimação

**OLS simples.** Nesta primeira versão, NÃO usar:

- Ridge;
- Lasso;
- ElasticNet;
- seleção automática de variáveis.

Registrar, por previsão (uma vez implementado):

- `alpha`;
- `beta`;
- `n_treino`;
- `r2_treino` (do ajuste na amostra de treino, nunca confundido com skill
  fora da amostra);
- período inicial/final do treino (`periodo_treino_inicio`/`fim`, mesma
  convenção dos Métodos 3.1/3.2);
- condição numérica da regressão, se disponível (ex.: razão entre maior e
  menor valor singular, ou proxy equivalente).

**Proteções numéricas obrigatórias**, cada uma com status explícito, nunca
um resultado silenciosamente substituído:

- matriz degenerada (ex.: `anom_modelo_raw` constante no treino —
  variância insuficiente para OLS);
- variância quase zero de `anom_modelo_raw` (caso particular do anterior,
  mas vale a pena nomear separadamente porque pode ocorrer sem a matriz
  ser estritamente singular);
- coeficientes `NaN`/`Inf` resultantes do ajuste.

Se houver degeneração: status explícito (ex.:
`erro_regressao_degenerada`) e **STOP-ON-FAILURE se inesperado** — ou
seja, se a degeneração ocorrer num volume ou padrão que o diagnóstico
prévio (análise da distribuição de `anom_modelo_raw` por lead, antes de
qualquer ajuste real) não previu, a execução para para investigação, em
vez de silenciosamente pular ou aproximar.

**Nunca truncar `alpha` ou `beta` por magnitude** — mesma filosofia já
aplicada à razão multiplicativa do Método 3.2 (nenhum teto aplicado ao
método principal): um `beta` extremo é um achado científico a reportar e
investigar (Seção 8), não um valor a cortar silenciosamente.

## 8. Diagnóstico de coeficientes antes da interpretação

Na futura execução, reportar por horizonte a evolução temporal de
`alpha`, `beta` e `R²` de treino (como eles mudam conforme a janela de
treino se expande com o tempo) — nunca só o valor final.

Regras de leitura, pré-registradas AGORA, antes de qualquer coeficiente
real existir — nunca formuladas depois de olhar o resultado:

- `beta ≈ 1` e `alpha ≈ 0` indicam comportamento semelhante ao
  `benchmark_anomalia_reconstruida` (Seção 2) — o MOS não estaria
  acrescentando ajuste substancial.
- `beta < 1` sugere amortecimento das anomalias do CFSv2 (o modelo exagera
  os desvios em relação à climatologia própria, e a regressão encolhe
  esse sinal).
- `beta > 1` sugere amplificação (o modelo subestima a amplitude real dos
  desvios, e a regressão expande o sinal).
- `beta <= 0` é **matematicamente possível e NÃO deve ser impedido
  silenciosamente** — mas exige destaque científico explícito (um `beta`
  negativo significaria que a anomalia do CFSv2 é, causalmente, um
  indicador INVERSO da anomalia observada, o que seria um achado
  extraordinário e exigiria verificação cuidadosa antes de qualquer
  conclusão, nunca aceito ao pé da letra sem investigação).
- Coeficientes instáveis ao longo do tempo (grandes saltos de `alpha`/
  `beta` entre inicializações sucessivas, mesmo com warm-up satisfeito)
  são um ALERTA de baixa robustez, a reportar explicitamente.

**Estas regras de leitura NUNCA se tornam uma conclusão automática** — elas
orientam o que destacar no relatório da implementação futura, não
substituem o critério de aprovação formal (Seção 11).

## 9. Comparações obrigatórias (na futura implementação)

Comparar o MOS contra:

1. CFSv2 bruto;
2. climatologia causal;
3. `benchmark_anomalia_reconstruida` — comparação CENTRAL (Seção 2);
4. Método 3.1 aditivo.

Para a comparação com o Método 3.1, usar EXATAMENTE os mesmos casos
elegíveis do MOS: `aditiva_matched_mos_sample` — mesma lógica já aplicada
em `aditiva_matched_multiplicativo_sample` (Método 3.2): restringir a
tabela aditiva já aprovada (`aditiva_expanding.csv`, só lida, nunca
reescrita) às chaves `(init_date, lead)` elegíveis do MOS.
**Nunca comparar MOS N≈120/horizonte diretamente com o aditivo full
(N=120/horizonte do Método 3.1, mas potencialmente com chaves diferentes
das do MOS) se as chaves divergirem** — a mesma lição já aplicada ao
comparar o Método 3.2 (N=80/horizonte, meses elegíveis) contra o
aditivo full (N=120/horizonte, todos os meses): comparar amostras
diferentes mistura o efeito do método com o efeito da amostra.

**O Método 3.2 multiplicativo pode aparecer apenas como referência
secundária** nos relatórios futuros, porque cobre somente 8 meses
elegíveis (jan-mai, out-dez) e uma população diferente (N=80/horizonte,
contra uma expectativa de N≈120/horizonte do MOS, que cobre todos os
meses por desenho — Seção 3). **Não torná-lo benchmark obrigatório do
MOS** — a comparação obrigatória de "outro método já aprovado" é
exclusivamente com o Método 3.1 (item 4 acima), que compartilha a mesma
cobertura mensal completa.

## 10. Métricas futuras (nenhuma calculada nesta atividade)

Pré-registradas para a implementação futura:

- Bias;
- MAE;
- RMSE;
- correlação absoluta;
- correlação de anomalia;
- `skill_vs_raw`;
- `RMSESS_climatologia`;
- `skill_vs_anomalia_reconstruida`;
- `skill_mos_vs_aditivo`.

Bootstrap em blocos por `target_ano` — todos os comparados (MOS, os três
benchmarks, e o aditivo matched) devem usar os MESMOS blocos dentro de
cada reamostra, mesma garantia estrutural já implementada e testada nos
Métodos 3.1/3.2 (`bootstrap_skills_aditiva_por_horizonte`,
`bootstrap_skills_multiplicativa_vs_aditiva_por_horizonte`).

## 11. Critério de aprovação

Mantém o critério científico já usado nos Métodos 3.1/3.2 — para um
horizonte ser considerado aprovado:

1. IC 95% de `skill_vs_anomalia_reconstruida` totalmente acima de zero;
2. IC 95% de `RMSESS_climatologia` totalmente acima de zero.

**Ambas as condições, SIMULTANEAMENTE, nunca uma isolada.**

Além disso, para justificar o MOS sobre o Método 3.1 já existente e
aprovado para integração: reportar `skill_mos_vs_aditivo` com IC 95% (mesmo
desenho do `skill_multiplicativo_vs_aditivo` do Método 3.2). **Se esse IC
incluir zero, não afirmar superioridade do MOS sobre o aditivo** — a
leitura correta nesse caso é "sem evidência de ganho estatisticamente
distinguível", nunca "equivalente" nem "melhor na prática".

**O critério nunca é alterado depois de observar os resultados** — mesma
regra já aplicada em todos os métodos anteriores desta fase.

## 12. H1 sempre separado

Manter H1 separado e rotulado `previsão do mês corrente`
(`ROTULO_HORIZONTE[1]`, já estabelecido desde a 2C.3C). **Nunca misturar
H1 com H2-H6 numa conclusão de "previsão futura"** — H1 responde a uma
pergunta estrutural diferente (nowcasting dentro do próprio mês) das dos
demais horizontes (previsão de meses ainda não iniciados).

## 13. Análise mensal e sazonal — diagnóstico, não parâmetro adicional

Mesmo treinando por lead (Seção 3), a futura avaliação (nunca a
estimação) deve decompor por:

- mês-alvo × lead;
- grupo sazonal × lead (`GRUPO_SAZONAL_POR_MES`).

**Isto é diagnóstico de heterogeneidade** (mesma função da matriz mês×lead
nos Métodos 3.1/3.2) — serve para verificar se a relação `alpha`/`beta`
estimada agregadamente por lead se comporta de forma consistente entre
meses, ou se esconde uma heterogeneidade relevante (ex.: o modelo ajusta
bem meses chuvosos mas mal meses de transição).

**Não estimar coeficientes específicos por mês nesta primeira versão**
(contradiria a Seção 1 e a Seção 3 — o modelo principal é deliberadamente
só por lead). **Não realizar 72 testes independentes** (12 meses × 6
leads) — mesma restrição já aplicada em todos os métodos anteriores desta
fase; a matriz é usada para ver direção/coerência/concentração do efeito,
nunca como 72 critérios de aprovação individuais.

## 14. LOYO — diagnóstico complementar, nunca operacional

Pré-registrada uma análise LOYO complementar para a implementação futura:

- excluir o ano-alvo (nunca só o passado — LOYO usa passado E futuro, por
  definição, mesma regra já aplicada nos Métodos 3.1/3.2 e no gate do
  Método 3.3);
- treinar a regressão por lead (mesma unidade de treinamento da Seção 3,
  mas com "todos os outros anos" em vez de "só os anteriores");
- **nunca chamar de operacional** — rótulo `mos_loyo_retrospective` (ou
  equivalente), mesma convenção de nomenclatura já usada.

Como nos métodos anteriores, a comparação DIRETA entre o desenho
expansível (operacional-simulado) e o LOYO deve usar um período de
avaliação `matched` (interseção explícita de chaves elegíveis, mesmo
padrão de `construir_tabela_loyo_matched`/
`construir_multiplicativa_loyo_matched_intersecao`) — nunca comparar
N diferentes diretamente.

## 15. Testes anti-leakage futuros

O protocolo EXIGE, na implementação futura, testes garantindo:

1. Nenhuma linha de treino com `init_date >= init_date_avaliada`.
2. A própria previsão (a linha avaliada) NUNCA entra no seu próprio
   ajuste de regressão.
3. Observação futura NÃO altera `forecast_mos` passado (mutar uma
   observação futura e confirmar que o resultado de uma previsão passada
   já elegível permanece numericamente idêntico — mesmo padrão dos testes
   de leakage dos Métodos 3.1/3.2).
4. As climatologias usadas nas ANOMALIAS HISTÓRICAS de treino permanecem
   as causais originalmente disponíveis na época daquele registro (Seção
   4) — nunca recalculadas retrospectivamente.
5. Outro lead NUNCA entra no treinamento de um lead diferente (mesmo com
   o pooling entre meses da Seção 3, o pooling NUNCA se estende entre
   leads).
6. Alterar dados futuros NÃO muda `alpha`/`beta` passados (variante da
   regra 3, no nível dos próprios coeficientes, não só do forecast final).

**Criar também um teste sintético onde uma regressão com leakage
(deliberadamente construída incluindo a própria observação avaliada, ou
dados futuros, no conjunto de treino) apresenta um ajuste artificialmente
superior — e confirmar que a implementação CORRETA bloqueia esse caso**
(mesmo padrão de `DemonstracaoLeakyBloqueadoTestCase` já usado no Método
3.1).

## 16. O que NÃO foi feito nesta atividade

- Nenhuma regressão MOS foi ajustada.
- Nenhum `alpha`/`beta` real foi calculado.
- Nenhum `forecast_mos` foi produzido.
- Nenhum RMSE/MAE/correlação/skill/IC do Método 3.4 foi calculado.
- Nenhum PR foi aberto.
- Nenhum dado operacional, CFSv2 RAW, CHIRPS v3 histórico, ou os
  artefatos já aprovados dos Métodos 3.1/3.2 e do gate do Método 3.3
  foram alterados — confirmado por `git diff` antes do commit e pela
  suíte de testes já existente (sem nenhum teste novo necessário nesta
  atividade, já que nenhuma funcionalidade nova foi implementada).

## Próximos passos (fora do escopo desta atividade)

1. Revisão deste protocolo.
2. Implementação do Método 3.4 em si, seguindo exatamente o desenho das
   Seções 1-10 — primeira e única implementação da próxima atividade.
3. Execução dos testes anti-leakage da Seção 15, incluindo o teste
   sintético de demonstração de leakage bloqueado.
4. Diagnóstico de coeficientes (Seção 8) ANTES de qualquer interpretação
   de desempenho.
5. Avaliação contra os quatro comparadores da Seção 9, com bootstrap
   conforme a Seção 10.
6. Aplicação do critério de aprovação da Seção 11 — nunca alterado depois
   de observar os resultados.
