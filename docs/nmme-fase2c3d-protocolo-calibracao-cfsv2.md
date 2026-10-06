# Protocolo de calibração retrospectiva do CFSv2 — Fase 2C.3D

**Documento de desenho experimental — não é relatório de resultados.** Nenhuma
calibração foi implementada ou executada nesta atividade. Nenhum dado
operacional (dashboard, SARIMAX, XGBoost, pipeline de produção,
`serie_subst.csv`), CFSv2 RAW ou CHIRPS v3 histórico foi alterado. Este
documento só define alternativas, protocolo de validação, métricas de
aprovação, riscos de overfitting e ordem de testes — a implementação do
primeiro método é uma fase separada, futura, condicionada à revisão deste
protocolo.

## 1. Por que esta fase existe — o que a Fase 2C.3C mostrou

A Fase 2C.3C (PR [#41](https://github.com/coordenadorpcpsnb-ctrl/sinobras-clima/pull/41),
merge `b5fbc87`, relatório `docs/nmme-fase2c3c-validacao-cfsv2.md`) avaliou o
ensemble **bruto** do CFSv2 (24 membros, H1-H6, 240 inicializações
jan/1991-dez/2010) contra CHIRPS v3.0 Final e encontrou **duas leituras
diferentes, que não podem ser confundidas**:

1. **Precipitação absoluta vs. climatologia causal** — RMSESS e CRPSS
   negativos em todos os H1-H6, com IC 95% (bootstrap em blocos por ano,
   modelo e benchmark nos mesmos blocos) **totalmente abaixo de zero**. A
   climatologia expansível sem leakage erra sistematicamente menos que o
   ensemble bruto nesta amostra.
2. **Anomalia após remover a climatologia PRÓPRIA do modelo** (sem leakage,
   por lead × mês-alvo) — RMSESS com pontos estimados próximos de zero (H1
   +0,045 a H6 -0,018) e IC 95% **incluindo zero** em todos os H1-H6.
   Estatisticamente indeterminado, não negativo.

A leitura (2) sugere que, uma vez removido o viés sistemático do próprio
modelo, o que resta não é claramente pior que a climatologia — mas também
não é claramente melhor. **O objetivo desta fase é avaliar, com rigor
metodológico equivalente ao da 2C.3C, se algum método de calibração
consegue transformar esse empate em ganho consistente — sem apagar
artificialmente a distinção entre as duas leituras acima.** Um método que
"ganha" só porque reproduz a correção já descrita em (2) não é um
resultado novo; o padrão de aprovação (Seção 6.2) exige superar também o
benchmark de anomalia reconstruída (Seção 5.4) — que já empata com a
climatologia causal — não só a climatologia causal isolada.

## 2. Princípio central e restrições

- **Nenhum método pode usar dados futuros em relação à inicialização
  avaliada.** Mesma garantia estrutural já testada em `climatologia_expansivel`/
  `climatologia_modelo_expansivel` (comparação por `pd.Period`, nunca string
  lexicográfica) — qualquer código de calibração desta fase deve reusar o
  mesmo padrão: o conjunto de treino de uma inicialização em `init_date` é
  estritamente `{dados com data < init_date}`, nunca `<=`.
- **Não implementar a calibração nesta atividade.** Esta é só a fase de
  protocolo. A primeira implementação é uma atividade futura separada,
  condicionada à aprovação deste desenho.
- **Não alterar ainda** dashboard (`docs/index.html`), SARIMAX, XGBoost,
  pipeline operacional (`scripts/update_dashboard.py`,
  `scripts/fetch_monthly_data.py`, `scripts/update_indices.py`,
  `scripts/gerar_relatorio.py`), `data/serie_subst.csv`, CFSv2 RAW
  (`data/nmme_historico_fazendas/`) ou CHIRPS v3 histórico
  (`data/chirps_v3_historico/`). Mesmas restrições da 2C.3C, repetidas aqui
  porque continuam valendo.
- **Nenhuma calibração entra em produção nesta fase**, mesmo que algum
  método seja aprovado pelo protocolo — aprovação aqui significa "justifica
  implementação e teste", não "pronto para o dashboard".

## 3. Alternativas metodológicas — simples e interpretáveis antes de ML

Ordem deliberada: do mais simples/interpretável para o mais complexo. Cada
método só é testado se o(s) anterior(es) já tiverem sido avaliados (Seção
6) — nunca pular direto para um método complexo "porque parece melhor",
precisamente para poder atribuir qualquer ganho a uma causa identificável.

### 3.1. Correção aditiva por lead × mês

`previsao_calibrada = previsao_bruta - viés_aditivo(lead, mês-alvo)`, onde
`viés_aditivo(lead, mês-alvo)` é a média do erro (`previsto - observado`)
nas inicializações HISTÓRICAS elegíveis (mesmo lead, mesmo mês-calendário de
inicialização, estritamente anteriores à avaliada) — mesma definição
causal já usada em `climatologia_modelo_expansivel`, aplicada ao ERRO em
vez de à previsão bruta.

- **Vantagem**: 1 parâmetro por célula (lead × mês), totalmente
  interpretável, sem risco de explosão numérica.
- **Risco identificado e já RESOLVIDO pelo warm-up da Seção 5.1**: com
  inicializações que crescem com o tempo (a primeira inicialização de
  cada mês-calendário não tem nenhum histórico — ver
  `ClimatologiaDoModeloSemLeakageTestCase` na 2C.3C), o viés aditivo das
  primeiras inicializações de cada combinação lead×mês seria estimado com
  amostra degenerada (n=1 a n=5) — variância alta do próprio estimador,
  não um sinal real. A Seção 5.1 fixa `N_TREINO_MINIMO=10` precisamente
  para impedir que esse método seja aplicado nessas combinações; ver
  Seção 4, item 1, para o trade-off que essa decisão implica.

### 3.2. Correção multiplicativa/razão, com tratamento seguro para meses secos

`previsao_calibrada = previsao_bruta × razão(lead, mês-alvo)`, onde
`razão = média(observado) / média(previsto)` nas mesmas inicializações
históricas elegíveis do item 3.1.

- **Vantagem**: captura melhor viés proporcional à magnitude (relevante em
  meses chuvosos, onde o erro absoluto tende a escalar com o volume).
- **Risco principal, já documentado em produção**: `CLAUDE.md` (armadilha
  7, da reconstrução CHIRPS) registra que corrigir julho por um fator fixo
  (razão mediana 0,073 do ERA5) multiplicou 21,6mm por quase 46× e **piorou**
  o RMSE do SARIMAX (56,2mm → 74,9mm) em vez de melhorar — precisamente o
  modo de falha que este método pode reproduzir se aplicado sem guarda em
  meses secos (jun-ago na região das fazendas, `GRUPO_SAZONAL_POR_MES`).
  **Tratamento seguro obrigatório**: nunca dividir por `média(previsto)`
  quando esse valor for menor que um piso mínimo absoluto (a definir
  empiricamente a partir da distribuição real, não um número arbitrário) —
  nesse caso, usar a correção aditiva (3.1) para a célula em vez da
  multiplicativa, e registrar explicitamente qual célula caiu nesse caso
  (nunca silenciosamente).
- Mesmo risco de amostra pequena do item 3.1 — mitigado pelo mesmo
  `N_TREINO_MINIMO=10` da Seção 5.1 (compartilhado por todos os métodos
  desta seção).

### 3.3. Quantile mapping — só se houver amostra suficiente e implementação leakage-safe

Mapeia cada quantil da distribuição empírica das previsões históricas
elegíveis para o quantil correspondente da distribuição empírica das
observações históricas elegíveis (mesmo lead × mês, mesma regra de corte
causal).

- **Risco principal**: quantile mapping precisa de amostra MAIOR que
  correção aditiva/multiplicativa para estimar quantis de forma estável —
  mesmo no período principal pós-warm-up (~10 casos/célula, Seção 5.1), a
  estimativa de quantis extremos (p10/p90) é instável por construção.
  **Decisão explícita**: `N_TREINO_MINIMO=10` (Seção 5.1) é o piso COMUM a
  qualquer método desta seção, mas é só o piso mínimo — quantile mapping
  pode exigir mais que isso, dado que é mais sensível a amostra pequena
  que média/razão (candidato a piso mais alto: `AMOSTRA_MINIMA_ESTRATO=20`,
  a mesma constante já usada na 2C.3C para avisos de amostra pequena —
  mas a decisão final cabe à implementação, documentada ali, **nunca
  decidida depois de observar qual piso produz melhor skill nesta
  amostra**). Para inicializações sem amostra suficiente para o piso
  específico de quantile mapping, usar o fallback explícito de não
  aplicar quantile mapping (não alterar a previsão, ou cair para o método
  3.1/3.2 já aprovado) — nunca interpolar quantis com poucos pontos como
  se fossem estáveis.
- **Leakage-safe**: a distribuição empírica de observações usada para o
  mapeamento é a MESMA climatologia causal já usada em
  `climatologia_expansivel` (nunca uma distribuição que inclua o próprio
  ano/mês avaliado).

### 3.4. Regressão linear / MOS simples

Regressão (ex.: `observado ~ previsto_ensemble_mean`, ou incluindo `lead` e
`mês` como fatores) treinada exclusivamente com inicializações históricas
elegíveis (mesmo corte causal). MOS (Model Output Statistics) clássico.

- **Vantagem sobre 3.1/3.2**: pode capturar relação não estritamente
  aditiva nem multiplicativa (ex.: inclinação ≠ 1), e permite incluir mais
  de um preditor (lead, mês, eventualmente índices ENSO já presentes no
  projeto — `data/master_monthly.csv`, SE estritamente anteriores à
  inicialização avaliada).
- **Risco principal**: mais parâmetros que 3.1/3.2 = mais risco de
  overfitting com a mesma amostra pequena pós-warm-up (Seção 4, item 1;
  Seção 5.1). Regressão com
  interação lead×mês completa teria 72 combinações e ultrapassaria
  rapidamente os graus de liberdade disponíveis mesmo no fim da série (240
  inicializações totais, não por célula) — qualquer regressão com mais de
  2-3 parâmetros por célula deve ser tratada como alto risco e justificada
  explicitamente antes de ser testada.

### 3.5. Calibração probabilística do ensemble — só posteriormente

Ajuste da dispersão/forma do ensemble (ex.: ensemble recalibration,
inflação/deflação de variância, ou reconstrução das categorias de tercil
calibradas) para melhorar CRPS/Brier Score — não só a média determinística.

- **Por que por último**: depende de ter primeiro estabelecido se a MÉDIA
  do ensemble consegue ganho determinístico consistente (3.1-3.4); calibrar
  dispersão de um ensemble cuja média ainda não bate climatologia de forma
  robusta arrisca mascarar o problema real atrás de uma métrica
  probabilística mais complexa.
- Reaproveita a infraestrutura probabilística já existente da 2C.3C
  (`crps_amostral`, `categoria_tercil`, `construir_linhas_avaliacao_por_lead`)
  — a calibração altera a distribuição dos membros antes dessas funções
  serem chamadas, nunca a definição delas.

## 4. Riscos de overfitting — identificados antes de qualquer implementação

1. **Amostra pequena cresce com o tempo, por desenho** — a mesma
   característica que torna a climatologia expansível leakage-safe (Seção
   5/6 da 2C.3C) também significa que qualquer parâmetro de calibração
   estimado causalmente tem MENOS dados nas primeiras inicializações de
   cada célula lead×mês. **Mitigado pelo warm-up pré-registrado da Seção
   5.1** (`N_TREINO_MINIMO=10`, nenhuma avaliação principal antes disso) —
   mas o preço dessa mitigação é reduzir a amostra de avaliação principal
   de até 240 para até ~120 inicializações (Seção 5.1): perda deliberada
   de poder estatístico em troca de defensabilidade. Mesmo com o warm-up,
   um método aprovado "no agregado por horizonte" (Seção 5.5/6.2) ainda
   pode estar sendo carregado por poucas células — por isso a matriz
   mês×lead continua obrigatória como diagnóstico de heterogeneidade
   (Seção 5.5), ainda que não mais como 72 testes de significância
   individuais.
2. **Seleção pós-hoc do "melhor" método entre os 5** é, em si, uma fonte de
   overfitting (viés de múltiplas comparações) — por isso a ordem de teste
   é FIXA e pré-registrada (Seção 5.3), e a aprovação de cada método
   (Seção 6.2) é avaliada isoladamente contra critérios fixos, nunca
   escolhendo post-hoc "qual dos 5 deu o RMSESS mais alto nesta amostra".
3. **Célula lead×mês com poucos parâmetros ainda pode overfitar se o
   parâmetro for ajustado repetidamente** — ex.: se a implementação
   recalcular e "readequar" o viés aditivo tentando várias janelas/variações
   até achar uma que melhore o RMSESS no conjunto de teste, isso é
   leakage de seleção de modelo, não leakage de dado. O protocolo de
   validação (Seção 5) deve ser decidido ANTES de olhar o resultado em
   qualquer conjunto de teste, e nunca re-decidido depois de ver o número.
4. **Quantile mapping e MOS são particularmente vulneráveis** — ver riscos
   específicos nas Seções 3.3 e 3.4.
5. **Divergência entre expanding-window operacional e LOYO retrospectivo**
   — um método pode parecer ganhar no LOYO (que usa toda a série, incluindo
   anos futuros, e por isso tem amostra de treino muito maior e mais
   estável) sem ganhar na simulação operacional expansível (que é a que
   importa de verdade, porque é a única que reflete o que estaria disponível
   em tempo real). Qualquer divergência entre os dois deve ser reportada
   explicitamente, nunca escondida atrás do resultado mais favorável.
6. **Correção multiplicativa em meses secos** — risco concreto e já
   documentado em produção (Seção 3.2); tratado com piso mínimo explícito,
   nunca silenciosamente.

## 5. Protocolo de validação

### 5.1. Pré-registro do período mínimo de treinamento (warm-up)

**Decisão fixada agora, antes de qualquer implementação — PRINCIPAL, não
ajustável depois de observar resultados:** nenhum parâmetro de calibração
é aplicado a uma combinação (lead, mês-alvo) enquanto o número de
inicializações históricas elegíveis para aquela combinação for menor que
`N_TREINO_MINIMO = 10`. **Esta é uma constante NOVA, específica da
elegibilidade de treino de calibração — não confundir com
`AMOSTRA_MINIMA_ESTRATO = 20`**, que já existe no projeto (2C.3C) e serve
para avisar sobre amostra pequena na AGREGAÇÃO/decomposição de métricas
(matriz mês×lead), não para decidir se um parâmetro de calibração pode
ser treinado.

Regras, todas obrigatórias e simultâneas:

- Treinamento sempre com `init_date_treino < init_date_avaliada`
  (comparação por `pd.Period`, nunca string) — nunca `<=`.
- Mesma combinação de lead × mês-calendário de inicialização (idêntico ao
  agrupamento já usado em `climatologia_modelo_expansivel` — mês-alvo é
  função determinística de mês de inicialização + lead, então agrupar por
  mês de inicialização é equivalente).
- Nunca usar a própria inicialização avaliada como parte do treino.
- Nunca usar dados futuros em relação à inicialização avaliada.
- **Enquanto `n_treino < 10`**, a previsão "calibrada" daquela combinação
  é marcada explicitamente como `warmup_amostra_insuficiente` e **NÃO
  entra na avaliação principal do método** (não compõe RMSESS, MAE,
  correlação de anomalias, CRPSS nem calibração por tercis da Seção 6).
- **Nunca substituir silenciosamente pela previsão bruta** quando
  `n_treino < 10` — o registro é marcado como indisponível para avaliação
  principal, não "resolvido" por um fallback silencioso que mudaria o que
  está sendo medido sem dizer.
- **Nunca imputar o parâmetro** (ex.: usar a média de outras células, ou
  um valor assumido) para contornar a amostra insuficiente.
- **Nunca compartilhar parâmetro entre meses** — cada combinação lead ×
  mês-calendário de inicialização tem seu próprio parâmetro, treinado só
  com sua própria amostra elegível.

**A data exata de entrada em warm-up de cada célula deve ser DERIVADA
PROGRAMATICAMENTE a partir dos dados reais** (contagem efetiva de
inicializações históricas elegíveis por célula), **nunca hardcoded**. A
tabela abaixo é a expectativa aproximada dado que a série do CFSv2 cobre
jan/1991-dez/2010 com uma inicialização por mês-calendário por ano (240
inicializações, `N_INICIALIZACOES_ESPERADO` da 2C.3C) — é o resultado
esperado da regra acima aplicada a estes dados, não uma data escolhida a
priori:

| Período | Papel |
|---|---|
| 1991-2000 | Formação da amostra de treino (warm-up) — nenhuma célula lead×mês tem 10 anos de histórico elegível antes disso; nenhuma avaliação principal ocorre aqui. |
| 2001-2010 | Período principal avaliável de calibração causal — cada célula lead×mês tem por volta de 10 inicializações elegíveis para avaliação (uma por ano), assumindo que a implementação confirme esse número real, não o assuma. |

**Trade-off registrado explicitamente**: esta regra reduz a amostra de
avaliação principal (de até 240 para até ~120 inicializações, dependendo
do lead/mês) — **isso é uma perda deliberada de poder estatístico em
troca de defensabilidade metodológica**: qualquer ganho medido no período
2001-2010 não pode ser atribuído a um parâmetro estimado com amostra
degenerada (n=1 a n=5), que é precisamente o risco que motivou esta regra
(ver Seção 4, item 1).

**Sensibilidade futura (não implementada agora)**: uma análise secundária
com `N_TREINO_MINIMO = 5` pode ser planejada depois, mas:

- deve ser rotulada explicitamente como análise de **sensibilidade**,
  nunca como a análise principal;
- não substitui a análise principal com mínimo 10 em nenhuma circunstância;
- não deve ser implementada na primeira execução do método aditivo (3.1),
  salvo instrução posterior explícita;
- **o valor do mínimo nunca é escolhido depois de observar qual produz
  melhor skill** — 10 é o valor principal pré-registrado por este
  documento, antes de qualquer execução; 5 só pode existir como
  sensibilidade declarada, não como substituto.

### 5.2. Treino/teste causal — nunca random split

Para cada inicialização avaliada (`init_date`), o conjunto de treino do(s)
parâmetro(s) de calibração é **exclusivamente** o conjunto de
inicializações históricas com `init_date_treino < init_date_avaliada`
(comparação por `pd.Period`, nunca string) — a mesma regra, célula a
célula (lead, mês-calendário de inicialização), já implementada e testada
em `climatologia_modelo_expansivel`, agora com o piso adicional de
`N_TREINO_MINIMO = 10` da Seção 5.1. **Nunca** random train/test split:
embaralhar inicializações destruiria a dependência temporal e permitiria
que o "treino" contivesse anos posteriores ao "teste" — exatamente o tipo
de leakage que a 2C.3B/2C.3C já corrigiu duas vezes (armadilhas do
`CLAUDE.md`, itens 6 e 9, e o próprio bug de `parse_wksst` nascido de
suposições não testadas sobre o formato dos dados).

**Desenho principal — simulação operacional expansível**: para cada uma
das 240 inicializações (jan/1991-dez/2010), treinar o parâmetro de
calibração só com o passado estritamente anterior, aplicar à previsão
daquela inicialização, e registrar o resultado. Mesmo padrão de
`'expanding_operational_simulation'` da 2C.3C — rótulo reaproveitado.

**Desenho complementar — LOYO retrospectivo**: igual ao já implementado em
`climatologia_loyo`/`executar_loyo_retrospectivo` — usa todos os anos
exceto o avaliado (passado E futuro), deliberadamente NÃO causal, rotulado
`'loyo_retrospective'`, **nunca misturado** com o resultado expansível.
Serve só para estimar o "teto" de ganho possível com amostra maior —
divergência entre os dois desenhos é um resultado a reportar (Seção 4,
item 5), não um a esconder.

### 5.3. Ordem de execução dos métodos

1. Correção aditiva por lead × mês (3.1).
2. Correção multiplicativa/razão com piso de segurança (3.2) — só depois
   de 3.1 ter sido avaliada, para poder comparar diretamente se a razão
   ganha algo sobre a soma simples.
3. Quantile mapping (3.3) — só se a amostra elegível atingir o mínimo
   pré-registrado (Seção 3.3, acima do piso comum `N_TREINO_MINIMO=10` da
   Seção 5.1); caso contrário, registrar como "não testado por amostra
   insuficiente" e seguir para o próximo método, nunca forçar.
4. Regressão linear / MOS (3.4).
5. Calibração probabilística do ensemble (3.5) — só depois de pelo menos
   um método determinístico (1-4) ter sido avaliado contra os três
   benchmarks da Seção 5.4, independentemente do resultado (aprovado ou
   não) — o objetivo é ter um ponto de comparação determinístico já
   estabelecido antes de avaliar a dimensão probabilística.

### 5.4. Benchmarks de comparação — os três, sempre na mesma escala física

Todo método é comparado contra os três ao mesmo tempo, nunca contra só
um, e **todos na mesma escala física de precipitação mensal (mm)** —
nunca comparando o RMSE absoluto de um método calibrado contra o RMSE de
uma série de anomalias em escala diferente (ver reconstrução do benchmark
3 abaixo).

1. **CFSv2 bruto** (`forecast_prec_mm`, sem nenhuma correção) — benchmark
   de referência "sem fazer nada".
2. **Climatologia causal** (`climatologia_expansivel`) — o benchmark
   principal da 2C.3C, que já venceu o CFSv2 bruto com IC 95% totalmente
   abaixo de zero.
3. **`benchmark_anomalia_reconstruida`** (nome inequívoco — NUNCA mais
   referido só como "CFSv2 com remoção da climatologia própria" sem a
   definição explícita abaixo, porque a 2C.3C avaliou esse benchmark em
   ESCALA DE ANOMALIA (mm de desvio), não em escala absoluta de
   precipitação, e os métodos de calibração (3.1-3.4) produzem
   precipitação absoluta em mm — comparar as duas escalas diretamente
   seria um erro de unidade, não uma comparação válida.

   **Definição formal, para reconstruir o benchmark 3 na mesma escala
   física dos métodos calibrados:**

   ```
   benchmark3_abs = climatologia_observada + (forecast_raw - climatologia_modelo_raw)
   ```

   onde `climatologia_observada` e `climatologia_modelo_raw` são AMBAS
   causais e sem leakage para a inicialização avaliada — exatamente
   `climatologia_expansivel` e `climatologia_modelo_expansivel` já
   implementadas e testadas na 2C.3C, nunca recalculadas de outra forma
   aqui.

   **Propriedade que torna esta reconstrução válida (não uma nova
   métrica, só uma mudança de escala)**: `benchmark3_abs - observacao` é
   matematicamente equivalente a `anom_modelo - anom_obs`, onde
   `anom_modelo = forecast_raw - climatologia_modelo_raw` e
   `anom_obs = observacao - climatologia_observada` — exatamente as duas
   quantidades já usadas na 2C.3C para calcular a anomaly correlation e o
   RMSESS de anomalia corrigida. A prova é algébrica e direta:

   ```
   benchmark3_abs - observacao
     = climatologia_observada + (forecast_raw - climatologia_modelo_raw) - observacao
     = (forecast_raw - climatologia_modelo_raw) - (observacao - climatologia_observada)
     = anom_modelo - anom_obs
   ```

   Ou seja, o erro de `benchmark3_abs` em mm é IDÊNTICO ao erro de
   anomalia já medido na 2C.3C — só a escala de apresentação muda (mm
   absolutos em vez de mm de desvio), o que permite comparar diretamente
   com o RMSE em mm dos métodos calibrados (3.1-3.4), que também produzem
   precipitação absoluta.

Um método de calibração só é um resultado genuinamente novo se superar
também o `benchmark_anomalia_reconstruida` (item 3) — bater só a
climatologia causal (item 2) não é suficiente, porque o `benchmark3_abs`
já empata com ela (2C.3C, RMSESS de anomalia corrigida com IC incluindo
zero).

### 5.5. Decomposição sazonal — heterogeneidade, não 72 testes de significância

**Ajuste em relação ao desenho original**: com o warm-up da Seção 5.1
(`N_TREINO_MINIMO=10`), o período principal avaliável (~2001-2010) deixa
aproximadamente 10 casos por célula mês × lead — amostra pequena demais
para exigir IC 95% positivo individualmente em cada uma das 72 células
(12 meses × 6 leads). **Exigir isso seria um padrão de aprovação
impossível de cumprir por desenho, não uma medida real de robustez.**
Nunca realizar 72 testes de significância independentes.

A matriz mês-alvo × lead (`metricas_matriz_mes_lead` como modelo a
seguir) continua **obrigatória**, mas sua função muda de "critério de
aprovação" para **diagnóstico de heterogeneidade**:

- Direção e coerência dos efeitos entre células (o ganho é consistente em
  sinal, ou aleatório?).
- Concentração do ganho agregado positivo em poucos meses/leads —
  **registrado como ALERTA DE HETEROGENEIDADE, nunca como reprovação
  automática**. Um ganho concentrado é um achado a reportar explicitamente
  (ex.: "o ganho agregado positivo vem majoritariamente de 2-3 meses"),
  não um motivo automático para rejeitar o método nem para aprová-lo sem
  essa ressalva.
- Degradações relevantes (células onde o método calibrado é claramente
  pior que o bruto) — reportadas mesmo que o agregado seja positivo.
- Meses ou horizontes específicos onde a correção falha.
- Padrões sazonais possíveis (ex.: funciona melhor na estação chuvosa que
  na seca) — como hipótese a registrar, não como conclusão estatística
  tirada de uma célula com n≈10.

**A aprovação estatística principal (Seção 6.2) ocorre em dois níveis
apenas**:

1. **Por horizonte** (H1-H6 agregando os 12 meses) — nível primário,
   amostra maior (~120 por horizonte no período principal).
2. **Complementarmente, por grupo sazonal × horizonte**
   (chuvosa/transição/seca × H1-H6, `GRUPO_SAZONAL_POR_MES`) — quando
   houver amostra suficiente (`AMOSTRA_MINIMA_ESTRATO=20` como referência
   de aviso, mesma constante da 2C.3C usada para decomposição/agregação,
   distinta do `N_TREINO_MINIMO=10` da Seção 5.1 que decide elegibilidade
   de treino).

Em ambos os níveis, H1 ("previsão do mês corrente") continua sempre
separado de H2-H6, nunca agregado numa métrica única — mantido de Seções
anteriores, sem alteração.

## 6. Métricas de aprovação

Para cada método, reportar, por horizonte (H1-H6) — e, complementarmente,
por grupo sazonal × horizonte quando a amostra permitir (Seção 5.5) — com
IC 95% via bootstrap em blocos por ano (modelo e benchmark nos MESMOS
blocos sorteados por reamostra, exatamente como
`bootstrap_skill_scores_por_horizonte` e
`bootstrap_rmsess_anomalia_corrigida_por_horizonte` da 2C.3C). **Somente
os registros fora de `warmup_amostra_insuficiente` (Seção 5.1) entram
nestes cálculos.**

- **RMSESS** — três formulações, uma por benchmark (ver Seção 6.1).
- **MAE** (absoluto, para contexto em mm — nunca só a métrica
  adimensional).
- **Correlação de anomalias** (usando a climatologia PRÓPRIA do modelo
  CALIBRADO, pela mesma lógica de `climatologia_modelo_expansivel` — não a
  do modelo bruto).
- **CRPSS**, quando aplicável (métodos 3.1-3.4 recalibram só a média
  determinística; para comparar probabilisticamente, o ensemble completo
  precisa ser recalibrado de alguma forma consistente — se não for, CRPSS
  não se aplica e isso deve ser dito explicitamente, nunca calculado sobre
  um ensemble que não foi de fato recalibrado).
- **Calibração/probabilidade por tercis** (rank histogram e Brier
  Score/BSS contra a referência nominal CORRIGIDA — `BS_ref_nominal`
  calculado sobre a mesma amostra, nunca a constante `2/9`, seguindo a
  correção já aplicada na 2C.3C).

### 6.1. Três formulações de skill, uma para cada benchmark — mesma escala, mesmos casos elegíveis

Com o `benchmark_anomalia_reconstruida` (Seção 5.4) na mesma escala
física (mm) dos métodos calibrados, calculam-se três razões de skill
independentes, todas na forma `1 - RMSE_calibrado / RMSE_benchmark`:

```
skill_vs_raw                     = 1 - RMSE_calibrado / RMSE_raw
RMSESS_climatologia               = 1 - RMSE_calibrado / RMSE_climatologia
skill_vs_anomalia_reconstruida    = 1 - RMSE_calibrado / RMSE_benchmark3_abs
```

Regras obrigatórias para as três, sem exceção:

- **Mesmos casos elegíveis para numerador e denominador** em cada uma —
  nunca calcular `RMSE_calibrado` sobre um conjunto de inicializações e
  `RMSE_benchmark` sobre outro conjunto diferente (ex.: um incluindo
  warm-up e o outro não).
- **No bootstrap em blocos por ano, método e benchmark usam sempre os
  mesmos blocos de anos sorteados em cada reamostra** — mesma garantia já
  implementada em `bootstrap_skill_scores_por_horizonte` e
  `bootstrap_rmsess_anomalia_corrigida_por_horizonte` da 2C.3C, nunca
  bootstraps independentes que invalidariam a razão.
- **Nunca comparar o RMSE absoluto de um método calibrado diretamente com
  o RMSE de uma série em escala diferente** — é por isso que o benchmark
  3 precisa da reconstrução da Seção 5.4 antes de entrar nesta fórmula;
  usar o RMSE da anomalia bruta da 2C.3C aqui, sem reconstruir a escala,
  seria um erro de unidade.

### 6.2. Critério de aprovação — nunca por ponto estimado isolado, nunca por célula individual

Um método é considerado **aprovado para avançar à fase de implementação**
somente se, simultaneamente:

1. O IC 95% de `skill_vs_anomalia_reconstruida` (bootstrap em blocos por
   ano, Seção 6.1) estiver **totalmente acima de zero**, calculado **por
   horizonte** (Seção 5.5) — o critério mais exigente, porque é o
   benchmark que já empata com a climatologia causal.
2. O IC 95% de `RMSESS_climatologia` também estiver totalmente acima de
   zero, pelo mesmo critério por horizonte — manter o padrão de rigor já
   usado na 2C.3C para julgar isso "bom" ou "ruim": nunca por ponto
   estimado.
3. A matriz mês×lead (Seção 5.5) não revelar degradação relevante
   escondida atrás de um agregado positivo, e qualquer concentração do
   ganho em poucos meses/leads for reportada como alerta de
   heterogeneidade — **nunca** exigida como IC 95% positivo
   individualmente em cada uma das 72 células (Seção 5.5); a aprovação
   estatística em si é decidida por horizonte e, complementarmente, por
   grupo sazonal × horizonte, nunca célula a célula.
4. O resultado da simulação operacional expansível e do LOYO retrospectivo
   não forem contraditórios de forma inexplicada (Seção 4, item 5) — se
   forem, isso é reportado como achado, e o método NÃO é aprovado até a
   divergência ser entendida.

Nenhuma classificação automática "bom"/"mau" — a mesma convenção da 2C.3C
(`_classificar_ic_relativo_a_zero`: `ic_totalmente_acima_de_zero` /
`ic_inclui_zero` / `ic_totalmente_abaixo_de_zero`) deve ser reaproveitada
literalmente na implementação futura.

## 7. Próximos passos (fora do escopo desta atividade)

1. Revisão deste protocolo.
2. Implementação do método 3.1 (correção aditiva) seguindo exatamente o
   desenho das Seções 5-6 — primeira e única implementação da próxima
   atividade, nunca os 5 métodos de uma vez.
3. Métodos seguintes (3.2-3.5), um por vez, só após o anterior ter sido
   avaliado (aprovado ou não) contra os três benchmarks.
4. Só depois de pelo menos um método ser aprovado por este protocolo,
   discutir separadamente — como decisão própria, não automática — se e
   como aplicar calibração operacional ao dashboard. Essa decisão não faz
   parte desta fase nem da próxima.

## Restrições respeitadas nesta atividade

- Nenhuma calibração foi implementada ou executada — nesta revisão
  (ajustes 1-3 do protocolo) nem na anterior.
- Nenhum dado operacional, CFSv2 RAW ou CHIRPS v3 histórico foi alterado.
- Nenhuma métrica desta fase existe ainda — este documento só define como
  elas serão calculadas quando a implementação começar.
- Esta revisão alterou SÓ este documento — nenhum código ou dado do
  repositório foi tocado (confirmado por `git diff` antes do commit).
