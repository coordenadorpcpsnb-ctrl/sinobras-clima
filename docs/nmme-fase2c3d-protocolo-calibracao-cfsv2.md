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
resultado novo; o padrão de aprovação (Seção 5) exige superar também o
benchmark (2), não só o benchmark (1).

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
- **Risco principal**: com `AMOSTRA_MINIMA_ESTRATO=20` como referência de
  amostra mínima (mesma constante da 2C.3C) e inicializações que crescem
  com o tempo (a primeira inicialização de cada mês-calendário não tem
  nenhum histórico — ver `ClimatologiaDoModeloSemLeakageTestCase` na 2C.3C),
  o viés aditivo das primeiras ~2-3 inicializações de cada combinação
  lead×mês é estimado com amostra muito pequena (n=1 a n=5) — variância alta
  do próprio estimador do viés, não um sinal real. Ver Seção 4.

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
- Mesmo risco de amostra pequena do item 3.1 — herda a Seção 4.

### 3.3. Quantile mapping — só se houver amostra suficiente e implementação leakage-safe

Mapeia cada quantil da distribuição empírica das previsões históricas
elegíveis para o quantil correspondente da distribuição empírica das
observações históricas elegíveis (mesmo lead × mês, mesma regra de corte
causal).

- **Risco principal**: quantile mapping precisa de amostra MAIOR que
  correção aditiva/multiplicativa para estimar quantis de forma estável —
  com N≈20 inicializações por célula lead×mês no fim da série (e muito
  menos no início, por desenho expansível), a estimativa de quantis
  extremos (p10/p90) é instável por construção. **Decisão explícita**: só
  testar quantile mapping se a amostra elegível na inicialização avaliada
  atingir um mínimo pré-registrado (candidato: `AMOSTRA_MINIMA_ESTRATO=20`,
  a mesma constante já usada no projeto — mas com possibilidade de exigir
  mais, dado que quantile mapping é mais sensível a amostra pequena que
  média/razão; decisão final cabe à implementação, documentada ali, nunca
  decidida silenciosamente). Para inicializações sem amostra suficiente,
  usar o fallback explícito de não aplicar quantile mapping (não alterar a
  previsão, ou cair para o método 3.1/3.2 já aprovado) — nunca interpolar
  quantis com poucos pontos como se fossem estáveis.
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
  overfitting com a mesma amostra pequena (Seção 4). Regressão com
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
   cada célula lead×mês. Um método aprovado "no agregado" (N=240 por
   horizonte) pode estar sendo carregado por poucas células com amostra
   grande — a Seção 6 exige decomposição por mês×lead antes de aprovar
   qualquer método, não só a métrica agregada.
2. **Seleção pós-hoc do "melhor" método entre os 5** é, em si, uma fonte de
   overfitting (viés de múltiplas comparações) — por isso a ordem de teste
   é FIXA e pré-registrada (Seção 3), e a aprovação de cada método (Seção
   5) é avaliada isoladamente contra critérios fixos, nunca escolhendo
   post-hoc "qual dos 5 deu o RMSESS mais alto nesta amostra".
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

### 5.1. Treino/teste causal — nunca random split

Para cada inicialização avaliada (`init_date`), o conjunto de treino do(s)
parâmetro(s) de calibração é **exclusivamente** o conjunto de
inicializações históricas com `init_date_treino < init_date_avaliada`
(comparação por `pd.Period`, nunca string) — a mesma regra, célula a
célula (lead, mês-calendário de inicialização), já implementada e testada
em `climatologia_modelo_expansivel`. **Nunca** random train/test split:
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

### 5.2. Ordem de execução dos métodos

1. Correção aditiva por lead × mês (3.1).
2. Correção multiplicativa/razão com piso de segurança (3.2) — só depois
   de 3.1 ter sido avaliada, para poder comparar diretamente se a razão
   ganha algo sobre a soma simples.
3. Quantile mapping (3.3) — só se a amostra elegível atingir o mínimo
   pré-registrado (Seção 3.3); caso contrário, registrar como "não testado
   por amostra insuficiente" e seguir para o próximo método, nunca forçar.
4. Regressão linear / MOS (3.4).
5. Calibração probabilística do ensemble (3.5) — só depois de pelo menos
   um método determinístico (1-4) ter sido avaliado contra os três
   benchmarks da Seção 5.3, independentemente do resultado (aprovado ou
   não) — o objetivo é ter um ponto de comparação determinístico já
   estabelecido antes de avaliar a dimensão probabilística.

### 5.3. Benchmarks de comparação — os três, sempre, nunca só um

Todo método é comparado contra os três ao mesmo tempo, nunca contra só um:

1. **CFSv2 bruto** (`forecast_prec_mm`, sem nenhuma correção) — benchmark
   de referência "sem fazer nada".
2. **Climatologia causal** (`climatologia_expansivel`) — o benchmark
   principal da 2C.3C, que já venceu o CFSv2 bruto com IC 95% totalmente
   abaixo de zero.
3. **CFSv2 com remoção da climatologia própria** (a "anomalia corrigida" da
   2C.3C, RMSESS com IC incluindo zero) — o benchmark mais exigente: um
   método de calibração só é um resultado genuinamente novo se superar
   também este, não só o item 2.

### 5.4. Decomposição obrigatória antes de qualquer conclusão de ganho

Reaproveitar o padrão já validado na 2C.3C — nunca só a métrica agregada:

- Matriz mês-alvo × lead (`metricas_matriz_mes_lead` como modelo a seguir),
  com aviso de amostra insuficiente por célula (`AMOSTRA_MINIMA_ESTRATO`).
- Resumo por grupo sazonal × lead (chuvosa/transição/seca,
  `GRUPO_SAZONAL_POR_MES`) como visão complementar, nunca substituta.
- H1 ("previsão do mês corrente") sempre separado de H2-H6, nunca
  agregado numa métrica única.

## 6. Métricas de aprovação

Para cada método, reportar, por horizonte (H1-H6) e com IC 95% via
bootstrap em blocos por ano (modelo e benchmark nos MESMOS blocos
sorteados por reamostra, exatamente como `bootstrap_skill_scores_por_horizonte`
e `bootstrap_rmsess_anomalia_corrigida_por_horizonte` da 2C.3C):

- **RMSESS** contra os três benchmarks da Seção 5.3.
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

### 6.1. Critério de aprovação — nunca por ponto estimado isolado

Um método é considerado **aprovado para avançar à fase de implementação**
somente se, simultaneamente:

1. O IC 95% do RMSESS (bootstrap em blocos por ano) estiver **totalmente
   acima de zero** contra o benchmark (3) da Seção 5.3 (CFSv2 com remoção
   da climatologia própria) — o critério mais exigente, porque é o que já
   está empatado com a climatologia.
2. O mesmo IC 95% também estiver totalmente acima de zero contra o
   benchmark (2) (climatologia causal) — manter o padrão de rigor já usado
   na 2C.3C para julgar isso "bom" ou "ruim": nunca por ponto estimado.
3. O ganho se sustentar na decomposição por mês×lead (Seção 5.4) — não
   apenas no agregado; um ganho concentrado em 1-2 meses/leads específicos
   deve ser reportado como tal, nunca generalizado para "o método funciona".
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

- Nenhuma calibração foi implementada ou executada.
- Nenhum dado operacional, CFSv2 RAW ou CHIRPS v3 histórico foi alterado.
- Nenhuma métrica desta fase existe ainda — este documento só define como
  elas serão calculadas quando a implementação começar.
