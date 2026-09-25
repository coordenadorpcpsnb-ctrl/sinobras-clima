# Fase 2C.2 — especificação técnica (extração histórica e validação retrospectiva do CFSv2)

## Status

**Documento de especificação — nenhum código de extração histórica foi
escrito, nenhum download foi executado, nenhuma skill foi calculada
nesta tarefa.** Serve para orientar a implementação de uma tarefa
futura e para registrar as decisões que precisam de aprovação antes de
começar.

## Ponto de partida

A Fase 2C.1b encerrou com o POC de infraestrutura **APROVADO** para 1
rota (`NOAA_NCEP/CFSv2`, backend `IRIDL_LEGACY`, representação
`NMME_HARMONIZED_MONTHLY`), 1 origem (2005-01), H1–H6, 24 membros — ver
`docs/nmme-fase2c1b-encerramento.md`. A Fase 2C.2 estende isso para uma
série histórica e adiciona a comparação com observações (CHIRPS) e com
os resultados científicos já validados de SEAS5/C3S MME (Fases
2A.3/2B.1).

## A. Período histórico

### Interseção documentada

| Fonte | Período | Status da evidência |
|---|---|---|
| Rota validada (IRIDL_LEGACY/NMME_HARMONIZED_MONTHLY), arquivo nativo | S: 1/jan/1982 a 1/dez/2010 (mensal) | `EMPIRICALLY_CONFIRMED` ao nível de catálogo (leitura do `index.tex` via `dlentries`, Rodada 5) — **não** é o mesmo que "todo mês desse intervalo abre com sucesso": só jan/2005 foi de fato aberto (Fase 2C.1b) |
| Série CHIRPS/blend usada pelo dashboard (`data/serie_subst.csv`) | 01/1981 → mês corrente (548 meses confirmados por `verificar_dashboard.py` em 24/09/2026, até 08/2026) | `EMPIRICALLY_CONFIRMED` — série de produção, verificada a cada execução |
| Manual NMME3 (produto pooled/multi-modelo, período CONCEITUAL) | 1991–2020 | `DOCUMENTED`, citado no catálogo — **não** é o período nativo desta rota específica (ver `CLAUDE.md`/catálogo sobre a distinção período nativo vs. pooled) |

**Interseção real (rota validada ∩ CHIRPS)**: 1982–2010 (29 anos).
**Interseção pedida pela tarefa (1991–2010)**: está inteiramente
contida na interseção real — viável em termos de disponibilidade
*documentada* nas duas pontas.

### Por que não assumir completude

A disponibilidade documental (o `index.tex` diz que a coleção cobre
1982–2010) não garante que cada uma das 12×20=240 inicializações
mensais de 1991–2010 abre sem erro, tem 24 membros completos, ou tem a
mesma semântica de L confirmada — o catálogo já registra que o eixo M
bruto observado pode variar entre 24 e 28 conforme o período (nota da
Rodada 4, `hindcast_members` nominal vs. eixo M bruto). Só 1 mês (jan/2005)
foi empiricamente aberto até agora. A Seção G (estratégia de
processamento) existe exatamente para não pular essa verificação.

### Recomendação

Usar **1991–2010** como janela inicial de desenvolvimento/validação,
conforme perguntado pela tarefa:
- Está dentro do período nativo confirmado da rota (1982–2010).
- Coincide com o início do período de avaliação comum já usado nas
  Fases 2A.3/2B.1 para C3S (1993–2016 é o comum entre os 4 sistemas
  C3S, mas o protocolo leakage-safe já suporta `MIN_ANOS_TREINO=10`
  crescendo a partir de qualquer início) — não é o MESMO período dos
  sistemas C3S, mas é uma janela comparável em tamanho (20 anos).
- Evita a década 1982–1990, que nenhuma fonte documentou com o mesmo
  nível de confiança (o manual NMME3 cita 1991 como início do produto
  pooled) — reduz o risco de abrir a primeira década com uma
  representação ligeiramente diferente sem perceber.

**Decisão que precisa de aprovação**: confirmar 1991–2010 (20 anos, 240
inicializações) como janela definitiva, ou estender para 1982–2010 (29
anos, 348 inicializações) já na primeira rodada — a segunda opção dá
mais anos de treino para `MIN_ANOS_TREINO=10` desde o início, ao custo
de processar uma década adicional sem o mesmo nível de documentação
cruzada.

## B. Inicializações

Processar as 12 inicializações mensais de cada ano da janela escolhida
(1991–01 a 2010–12, ou 1982–01 a 2010–12 se a janela for estendida),
uma por uma — nunca em lote/intervalo `RANGEEDGES` amplo, pela mesma
razão que motivou a correção da Fase 2C.1b: `RANGEEDGES` pode devolver
mais de 1 inicialização por janela mesmo quando os limites pedidos
apontam para 1 mês só. Cada requisição deve:

1. Usar `RANGEEDGES` com limites de S iguais (início=fim=mês/ano
   pedido) — nunca `VALUE` para a cláusula de tempo (Fase 2C.1b,
   Seção 1).
2. Rodar `nmme_processar.selecionar_inicializacao_por_coordenada` para
   isolar exclusivamente a inicialização pedida, com todos os
   guardrails já implementados (ausente/duplicado/múltipla-após-seleção/
   divergente-após-seleção).
3. **Preservar a data de inicialização original em todo registro** —
   cada linha do RAW histórico carrega `init_date` (a inicialização
   real, não um índice sequencial) e `target_month` (calculado a partir
   dela + lead), exatamente como o POC de infraestrutura já faz por
   linha (`montar_linha_raw`). Nenhuma tabela agregada deve perder essa
   coluna — é o que permite reconstruir qual previsão valeu para qual
   mês, e é a defesa estrutural contra vazamento temporal (Seção E).

## C. Horizontes

Manter H1–H6 (`leads_available=(1,2,3,4,5,6)` do catálogo) e o
mapeamento temporal empiricamente validado pela Fase 2C.1b
(`nmme_processar.avaliar_mapeamento_temporal`/
`_avaliar_semantica_forecast_period`, Método A por variável auxiliar
com precedência sobre o Método B de semântica documentada do eixo L).

| H (lead) | L (Ingrid) | Mês de previsão (relativo à inicialização) |
|---|---|---|
| H1 | 0.5 | mês da própria inicialização (ex.: init 1995-03 → alvo 1995-03) |
| H2 | 1.5 | 1 mês depois (1995-04) |
| H3 | 2.5 | 2 meses depois (1995-05) |
| H4 | 3.5 | 3 meses depois (1995-06) |
| H5 | 4.5 | 4 meses depois (1995-07) |
| H6 | 5.5 | 5 meses depois (1995-08) |

Esse mapeamento (esquema `lead1_igual_mes_inicializacao`) é o mesmo já
usado e testado no POC — **não precisa ser redescoberto**, só reaplicado
a cada origem histórica com a mesma verificação de evidência objetiva
por lead (nunca assumido sem `mapping_status=OK`). Uma origem/lead com
`mapping_status != OK` deve ser marcada e excluída da avaliação, nunca
silenciosamente aceita.

## D. Integridade dos dados

Reaproveitar, sem modificação de lógica, todos os guardrails já
implementados e testados no POC (`nmme_poc.py`/`nmme_processar.py`):

- **Seleção temporal exata** — `selecionar_inicializacao_por_coordenada`
  (Fase 2C.1b), nunca por posição/índice/proximidade.
- **Identificação dos membros** — eixo M lido do dado real por
  origem/lead, nunca hardcoded; faixa aceita `[24,28]` já documentada
  (Rodada 4) mas a política de aprovação atual do POC exige 24/24 por
  lead (`member_count_per_lead_ok`) — decisão explícita a confirmar
  para o histórico completo (ver "decisões" abaixo: manter 24 exato ou
  aceitar a faixa 24–28 e registrar o valor observado por origem?).
- **Unidades de precipitação** — `converter_precip_para_mm_mes`,
  mesma tabela de unidades aceitas.
- **Coordenadas** — seleção do ponto de grade mais próximo de São
  Bento do Tocantins (`VALUE` em X/Y), distância registrada
  (`distancia_km_aprox`) — nunca assumida igual a 0.
- **Completude** — `raw_completo`/`n_raw_expected` por origem×lead,
  nunca recalculado para bater com o que veio (Seção M do POC,
  regressão já coberta por teste).

Diferença estrutural do histórico completo vs. o POC: o POC roda esses
guardrails **uma vez** (1 origem); o histórico precisa rodá-los **por
origem** e agregar o resultado num `access_audit`/`temporal_audit`
histórico — uma origem que falhe um guardrail deve ficar marcada e
**excluída da comparação com CHIRPS** (nunca preenchida com um valor
estimado), com o motivo registrado, seguindo o mesmo princípio de
"nunca inventar dado" que rege o resto do projeto (CLAUDE.md, armadilha
6).

## E. Comparação com as observações (CHIRPS)

### Alinhamento temporal

Cada previsão é identificada por `(init_date, lead) → target_month`
(Seção C). A comparação com CHIRPS usa **só** `target_month` como chave
de junção com `data/serie_subst.csv` (ou a série CHIRPS equivalente
usada pela Fase 2C) — nunca a data de inicialização.

### Alinhamento espacial

O ponto CFSv2 já selecionado no POC (grade mais próxima de São Bento do
Tocantins) é um **ponto único**, enquanto CHIRPS no dashboard de
produção é agregado por fazenda/envelope (`data/fazendas.geojson`,
Armadilha 8 do `CLAUDE.md`). Para a Fase 2C.2, a comparação deve
declarar explicitamente qual CHIRPS está sendo usado como referência:
- **Ponto único** (mesmo ponto do POC) — comparação mais direta com o
  próprio subset CFSv2 já validado, mas não representa a agregação
  regional usada no dashboard.
- **Zonal/envelope** (`buscar_prec_chirps_zonal`) — mais alinhado com o
  uso operacional do CHIRPS no projeto, mas essa função **ainda não
  passou pela suíte de falha** (`tests/test_fetch_fallback.py`) —
  Armadilha 8 do `CLAUDE.md` é explícita: promover o zonal a primário é
  decisão separada, não tomada.

**Decisão que precisa de aprovação**: qual CHIRPS usar como observação
de referência na Fase 2C.2 (ponto único vs. zonal), e se vale a pena
antecipar a suíte de falha do zonal para esta fase.

### Cobertura, dados ausentes e vazamento temporal

- **Cobertura**: uma origem/lead só entra na avaliação se **ambos**
  CFSv2 (todos os guardrails da Seção D) e CHIRPS (mês real, não
  substituto/estimado) estiverem disponíveis para o `target_month`
  correspondente — nunca preencher um lado com o outro.
- **Dados ausentes**: registrados e excluídos, nunca imputados. Contagem
  de cobertura (`% de origens×leads avaliáveis`) deve ser reportada
  explicitamente, não escondida atrás de uma média.
- **Vazamento temporal**: reaproveitar o desenho já leakage-safe da
  Fase 2A.3 (`c3s_calibracao.py::climatologia_leakage_safe`/
  `bias_leakage_safe`, `MIN_ANOS_TREINO=10`) — a climatologia/bias usada
  para avaliar a previsão de um ano **nunca** inclui esse mesmo ano no
  treino. Isso já é código existente e testado; a Fase 2C.2 só precisa
  alimentá-lo com o RAW do CFSv2 no lugar do RAW do C3S, mantendo a
  mesma barreira.

## F. Avaliação científica

**Reaproveitar o protocolo já validado e congelado nas Fases 2A.3/2B.1**
(mesma climatologia leakage-safe, mesma correção de viés aditiva,
mesmas métricas, mesmo bootstrap) — não inventar um protocolo novo para
o CFSv2. Isso é o que torna a comparação com SEAS5/C3S MME (pedida pela
tarefa) uma comparação like-for-like, não duas metodologias diferentes
coincidentemente comparadas lado a lado.

Métricas já implementadas em `scripts/c3s_skill.py`/
`c3s_hindcast_completo.py`, a reaproveitar sem modificação:
- **Determinísticas**: RMSE/MSESS (mean squared error skill score)
  contra climatologia leakage-safe, para precipitação acumulada por
  lead.
- **Probabilísticas**: Brier Score/RPS/RPSS por tercil (abaixo/normal/
  acima), CRPS opcional.
- **Robustez**: bootstrap por ano (não por origem×lead isolado — evita
  pseudo-replicação dentro do mesmo ano).
- **Anomalias**: já suportado pela climatologia leakage-safe (valor
  previsto − climatologia do próprio período de treino daquele
  origem/lead).

**Comparações a produzir**:
1. CFSv2 (RAW e com correção de viés) vs. climatologia leakage-safe —
   o baseline mínimo, mesmo teste que qualquer sistema já passou.
2. CFSv2 vs. SEAS5 (Fase 2A.3) e vs. C3S MME (Fase 2B.1), no período
   comum entre os três (a interseção de 1991–2010 com 1993–2016 é
   1993–2010 — 18 anos; calcular explicitamente, nunca assumir).
3. Desempenho sazonal — separar por trimestre/estação (mesma
   granularidade já usada no dashboard, jul→jun) para não esconder um
   resultado bom numa estação atrás de um resultado ruim em outra.

**Não afirmar ganhos preditivos antes da validação** — nenhuma
conclusão sobre CFSv2 ser "melhor" ou "pior" que SEAS5/C3S MME deve
aparecer em nenhum artifact desta fase até que RPSS/MSESS estejam
calculados com a amostra completa (ou, no mínimo, com a amostra piloto
da Seção G com significância suficiente para o bootstrap não ficar
inconclusivo).

## G. Estratégia de processamento

### Fase G.1 — amostra piloto (obrigatória antes da extração completa)

Seguindo o mesmo padrão já usado no POC de infraestrutura C3S (Fase
2B.1: 6 origens, 3 décadas × 2 estações) e no CFSv2 (Fase 2C.1b: 1
origem): uma amostra pequena e deliberadamente representativa, **nunca
aleatória**, cobrindo:
- **Décadas**: início (1991 ou 1982), meio (~2000), fim (2010) do
  período nativo.
- **Estações**: pelo menos 1 mês de cada trimestre hidrológico (jan,
  abr, jul, out) — cobre o ano hidrológico jul→jun usado no dashboard.
- **Horizontes**: todos os H1–H6 para cada origem da amostra (não vale
  a pena economizar aqui — o custo por origem já inclui todos os
  leads numa única requisição RANGEEDGES).

Proposta concreta: 4 anos × 4 meses = **16 origens**, H1–H6, 1 ponto —
16 requisições RANGEEDGES (mesma ordem de grandeza que o piloto C3S de
6 origens × 4 sistemas = 24 requisições da Fase 2B.1).

### Critérios objetivos de aprovação da amostra piloto

- 100% das 16 origens devolvem `poc_status=APROVADO` (todos os
  guardrails da Seção D) — qualquer reprovação exige diagnóstico antes
  de prosseguir, nunca só descartar a origem problemática em silêncio.
- Nenhuma reprovação por `RANGEEDGES_FAIL_*` inesperada (a única
  reprovação "esperada e já compreendida" é uma janela com 2
  inicializações vizinhas, que o seletor já isola corretamente — Fase
  2C.1b).
- Cobertura CHIRPS ≥ 90% das 16×6=96 combinações origem×lead (mês
  observado disponível).

### Fase G.2 — extração histórica completa (só depois de G.1 aprovada)

- **Volume de dados**: 1 requisição RANGEEDGES por origem mensal.
  240 origens (1991–2010) ou 348 origens (1982–2010) — 1 requisição
  cada, H1–H6 e 24 membros por requisição (mesmo payload por origem já
  medido no POC: artifact de 17.612 bytes para 1 origem/6 leads/24
  membros/CSV+JSON — a extrapolação linear para 240 origens é da ordem
  de **4 MB** de CSV+JSON agregados, não conta o overhead do NetCDF
  baixado por origem, que não foi medido nesta tarefa).
- **Quantidade de requisições**: 240 (ou 348) — mesma ordem de grandeza
  do "1 requisição por origem" já confirmado no POC (`requests_previstos: 1`
  por origem).
- **Tempo de processamento**: o POC real levou ~3s para 1 origem
  (download + parsing + todos os guardrails). Extrapolação linear
  ingênua: 240×3s ≈ 12 minutos; 348×3s ≈ 17 minutos — **mas isso não
  considera** rate limiting do IRIDL (não testado com requisições em
  sequência rápida) nem o risco de continuidade do serviço (Seção 7 do
  catálogo: desligamento esperado do IRIDL legado até 31/10/2026 —
  **a extração completa da Fase 2C.2 precisa estar rodando ou concluída
  antes dessa data**, ou migrada para uma fonte alternativa a tempo —
  ver `docs/nmme-cfsv2-fontes-alternativas.md`).
- **Critério objetivo de aprovação da extração completa**: mesmos 3
  critérios de G.1, aplicados às 240/348 origens; adicionalmente,
  `verificar_dashboard.py` continua `APROVADO` (nunca a extração
  histórica deve tocar em `docs/index.html`/dados de produção) e a
  suíte de testes completa continua passando.

**Não fazer nesta tarefa nem propor iniciar automaticamente**: a
extração completa (G.2) só deve começar depois que G.1 rodar de fato
(execução real, não simulada) e passar nos 3 critérios acima — decisão
explícita do usuário, não automática.
