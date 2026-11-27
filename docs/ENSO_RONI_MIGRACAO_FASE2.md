# ENSO-RONI-MIGRAÇÃO — Fase 2: série histórica, snapshots e proveniência do RONI

## 1. Objetivo

Implementar a série histórica oficial do RONI (Relative Oceanic Niño
Index), com snapshots imutáveis da fonte e proveniência prospectiva,
alimentando o mesmo card do dashboard que antes dependia só do parser
tolerante legado (`update_indices.parse_roni()`). Decisão aprovada na
Fase 1 e detalhada na Fase 2: nenhum conteúdo descartado deve se tornar
irrecuperável — hashes identificam conteúdo, mas não o recuperam, por
isso a arquitetura preserva o **conteúdo bruto completo** de cada
aquisição distinta, não só seu hash.

## 2. Fonte canônica e versão metodológica

`https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt`

Confirmado institucionalmente nesta fase, por duas vias independentes
(não só por coincidência de valores com uma tabela HTML):

1. **Catálogo oficial** `https://www.cpc.ncep.noaa.gov/data/indices/`,
   seção "Relative Sea Surface Temperature": linha "**Seasonal
   Relative** ERSSTv6 (1991–2020 base period) 3-month running average
   in Niño 3.4 (5°North–5°South) (170–120°West)" → link `Data` com
   `href="/data/indices/RONI.ascii.txt"` → rótulo "(Relative Oceanic
   Nino Index)".
2. **NWS Public Information Statement 26-05** (lido por completo nesta
   fase, PDF extraído localmente com `pdftotext` — texto bloqueado em
   fases anteriores, desbloqueado nesta sessão): cita nominalmente
   "The following is a text file of the RONI:
   https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt".

Versão metodológica: **ERSSTv6**, base climatológica 1991–2020 (fixa —
distinta da base "centered" usada pelo produto ONI legado). Gravada
como constante do módulo (`roni_historico.VERSAO_METODOLOGICA`), nunca
inferida do conteúdo do arquivo (que não se autodeclara).

## 3. Convenção temporal (confirmada ao vivo, não documentada na fonte)

A coluna `YR` do arquivo é o ano do **mês central** do trimestre —
confirmado pelo alinhamento dos picos históricos de El Niño/La Niña na
própria série (ex.: o pico do evento 2015/16 aparece em `NDJ 2015` e
`DJF 2016`, consistente com dezembro central de 2015 e janeiro central
de 2016). O arquivo **não documenta essa convenção explicitamente** —
é uma inferência evidenciada, não uma suposição.

| Temporada | Ano (YR) | Mês inicial | Mês central | Mês final |
|---|---|---|---|---|
| DJF | AAAA | dez/(AAAA-1) | jan/AAAA | fev/AAAA |
| ASO | AAAA | ago/AAAA | set/AAAA | out/AAAA |
| NDJ | AAAA | nov/AAAA | dez/AAAA | jan/(AAAA+1) |

## 4. Arquitetura (decisão aprovada — rejeita "só série + hashes")

```
data/roni_historico.csv      série normalizada (produto derivado)
data/roni_proveniencia.csv   log append-only, upsert por aquisicao_id
data/roni_snapshots/
  <sha256>.txt                conteúdo bruto IMUTÁVEL de cada aquisição
                               distinta já observada
```

- **Snapshot**: nunca sobrescrito; novo snapshot só se o hash SHA-256
  ainda não existir. Se o mesmo hash reaparecer com conteúdo diferente
  (colisão ou corrupção), a aquisição é rejeitada (`SerieRejeitada`,
  convertida em `rejeitada_snapshot_corrompido` — nunca propagada como
  exceção não tratada).
- **Proveniência**: toda aquisição processada gera uma linha — aceita
  ou rejeitada. Upsert por `aquisicao_id` (reprocessar a mesma aquisição
  substitui sua própria linha), nunca por conteúdo (uma nova coleta real
  sempre tem um novo id/timestamp, mesmo quando o conteúdo é idêntico ao
  anterior).
- **Série normalizada**: só é reescrita quando uma aquisição é
  `promovida`. Reconstruível integralmente a partir do snapshot da
  última aquisição `promovida`/`reaproveitada_sem_mudanca` registrada
  no manifesto (`serie_ativa_corresponde_ao_snapshot()`).

Nenhum dos 3 artefatos existia antes desta fase. O primeiro snapshot
criado aqui **não reconstrói vintages anteriores à implementação** —
representa só a versão efetivamente observada na data desta aquisição
(26/11/2026).

## 5. Validador estrito (`parse_roni_serie_completa`)

Distinto do parser tolerante legado (`update_indices.parse_roni()`,
**nunca modificado**): rejeita o documento **inteiro** ante qualquer
inconsistência — cabeçalho inválido, resposta vazia/HTML/truncada,
temporada/ano não reconhecidos, valor não numérico/infinito/
fisicamente implausível (`|RONI|>5°C`), duplicata com valor divergente,
ou lacuna interna na sequência cronológica (lacuna só no final — mais
recente ainda não publicado — não é lacuna interna). A tolerância do
parser legado nunca é usada para promover a série histórica.

## 6. Política de revisões

A própria página oficial do RONI declara: *"RONI values may change up
to two months after the initial 'real time' value is posted."*
`JANELA_REVISAO_RECENTE_MESES = 2` implementa essa janela, contada do
mês central do trimestre revisado até o mês de execução:

- Revisão **dentro** da janela → aceita, `promovida`.
- Revisão **fora** da janela → `rejeitada_revisao_historica_inesperada`
  — **não** promovida automaticamente, mas também **não** tratada como
  erro científico definitivo: a evidência já foi preservada em
  snapshot antes da decisão, sinalizada para avaliação externa.
- Cobertura reduzida (trimestre da série ativa ausente na nova
  aquisição) → `rejeitada_cobertura_reduzida`, nunca promovida.
- Nada mudou → `reaproveitada_sem_mudanca` (idempotente — nova linha de
  proveniência registrada, série/snapshot inalterados).

## 7. Integração com `update_indices.py`

`parse_roni()` e seu único call site anterior foram substituídos por
`roni_hist.processar_aquisicao()` dentro de `main()` — o card `const
RONI` do dashboard agora recebe o mesmo valor que alimenta a série
histórica, nunca um valor que o mecanismo histórico tenha rejeitado.
Em falha de coleta ou rejeição, `processar_aquisicao()` já devolve o
último trimestre válido persistido — o comportamento informativo do
dashboard (preserva o último card bom, nunca grava `null`/zero) é
idêntico ao que já existia. `parse_roni()` permanece intocado no
arquivo, com seu contrato preservado (ainda testado em
`tests/test_update_indices.py`).

## 8. Testes (53 testes novos, `tests/test_roni_historico.py`)

- **Grupo A** (20 testes) — parsing e calendário: série real válida,
  cabeçalho/HTML/vazio/truncado inválidos, ano/temporada/valor
  inválidos (NaN/±inf/implausível), duplicata idêntica vs. divergente,
  lacuna interna vs. lacuna no final, viradas DJF/NDJ, precisão
  preservada.
- **Grupo B** (12 testes) — snapshots e proveniência: aquisição
  inicial, hash↔conteúdo, revisão recente promovida, trimestre novo,
  conteúdo idêntico não duplica snapshot, reprocessamento da mesma
  aquisição é idempotente, retorno a conteúdo anterior reaproveita
  snapshot, preservação de snapshots antigos após revisão, snapshot
  corrompido detectado (direto e via pipeline).
- **Grupo C** (8 testes) — revisões e integridade: revisão recente vs.
  inesperada, cobertura reduzida, versão metodológica sempre constante
  (nunca inferida), falha de coleta/estrutural preserva último valor
  válido, reconstrução exata pelo snapshot.
- **Grupo D** (6 testes) — persistência e recuperação: snapshot
  corrompido nunca promove, proveniência tolera linha final truncada,
  **interrupção entre operações é detectada E recuperável**
  (demonstrado: apagar `roni_proveniencia.csv`, confirmar detecção via
  `serie_ativa_corresponde_ao_snapshot()`, reprocessar a mesma
  aquisição restaura a consistência sem duplicar nada), nenhum arquivo
  `.tmp` residual após qualquer fluxo.
- **Grupo E** (6 testes) — compatibilidade: `parse_roni()` legado
  intocado, formato do card preservado, `ultimo=None` quando nunca
  promovido (preserva comportamento de ausência), módulo nunca
  referencia o dashboard HTML nem variáveis de modelos científicos.

Todos isolados via `tempfile.TemporaryDirectory()` + `patch.object` —
nunca tocam `data/roni_historico.csv` real durante o teste. A fixture
`tests/_roni_ascii_fixture.txt` é um snapshot congelado de uma
aquisição real (hash `1297887f...4285254f35c8`) — os testes nunca
dependem de rede.

## 9. Validação real (sobre a aquisição efetivamente obtida)

Aquisição isolada em 26/11/2026 19:47:59 UTC, reaproveitada (nunca
reconsultada só para gerar hash):

- URL: `https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt`
- Bytes: 14.752 — Hash SHA-256:
  `1297887f581b6190e459cbbf8bdec9a703ff65c1a229e2de4dd94285254f35c8`
- 921 observações, DJF/1950 → ASO/2026, sem rejeição, sem avisos.
- Inicialização real: `estado_promocao=promovida`, último trimestre
  ASO/2026 = +1,97°C.
- Idempotência confirmada: 2ª execução com o mesmo conteúdo →
  `reaproveitada_sem_mudanca`, `data/roni_historico.csv` byte-a-byte
  idêntico, nenhum snapshot duplicado (1 arquivo em
  `data/roni_snapshots/`).
- `serie_ativa_corresponde_ao_snapshot()` → `True` — a série ativa é
  integralmente reconstruível a partir do snapshot que a originou.

## 10. Compatibilidade com workflows e CI (análise — nenhuma alteração)

- `git add docs/index.html data/` (ambos os workflows) já inclui
  recursivamente qualquer arquivo novo dentro de `data/`, inclusive
  `data/roni_snapshots/<hash>.txt` nunca visto antes — confirmado
  (comportamento padrão do `git add` sobre diretório, diferente do
  `git diff` usado só para DECIDIR se há algo a commitar).
- A barreira "Verificar alterações" (`git diff --quiet docs/index.html
  data/`) tem o mesmo ponto cego já documentado na armadilha 9 do
  CLAUDE.md (não detecta arquivo nunca commitado) — mas **não afeta
  este mecanismo na prática**: `data/roni_proveniencia.csv` é um
  arquivo **já rastreado** (será commitado nesta própria fase) cujo
  conteúdo muda em **toda** execução real de `processar_aquisicao()`
  (cada aquisição grava uma linha nova, com timestamp novo, mesmo
  quando `reaproveitada_sem_mudanca`) — então `git diff --quiet data/`
  sempre detecta essa mudança e aciona o commit, que por sua vez,
  via `git add data/`, inclui também qualquer snapshot novo
  untracked. Não há risco residual de "novo snapshot nunca commitado"
  enquanto a proveniência continuar gravando incondicionalmente.
- **CI não executa os novos testes automaticamente.** `ci.yml` lista
  os módulos de teste explicitamente por nome (não há
  `discover`/glob) — `tests.test_roni_historico` **não está** na
  lista do Job A (`python -m unittest -v tests.test_update_indices
  tests.test_update_indices_enso_auto tests.test_fetch_fallback
  tests.test_cobertura_temporal_precipitacao
  tests.test_enso_integridade_fase3a
  tests.test_enso_integridade_fase3b0`). **Alteração mínima
  necessária** (identificada, não implementada — fora do escopo
  autorizado desta fase): adicionar uma linha
  `tests.test_roni_historico \` a essa mesma lista em
  `.github/workflows/ci.yml`.
- Nenhum workflow foi alterado nesta fase.

## 10.1. Fase 2.1 — CI, verificação de integridade somente leitura e correção de uma lacuna real

**SHA completo do commit inicial desta migração**: `361bf00e60db9f1457620efb425d7e223786eeb2`.

**Inclusão na CI**: `.github/workflows/ci.yml`, Job A, passou a incluir
`tests.test_roni_historico` na mesma lista `python -m unittest -v`
dos demais módulos (nenhum módulo existente removido/alterado). Job B
já incluía `tests.test_verificar_dashboard`/
`tests.test_verificar_dashboard_enso_auto` — nenhuma alteração
necessária ali para cobrir a nova verificação de integridade.

**Verificação de integridade somente leitura**: nova função
`roni_historico.verificar_integridade_roni()` — nunca consulta a NOAA,
nunca grava/recupera/recalibra nada, nunca reimplementa o parser
(delega a `serie_ativa_corresponde_ao_snapshot`/
`reconstruir_da_snapshot`/`ultimo_da_lista`, já existentes). Integrada
a `scripts/verificar_dashboard.py` como item 14, incondicional
(roda igual com ou sem `--pular-continuidade-serie-subst`, que é
exclusiva da checagem de continuidade de `serie_subst.csv`). Nunca
compara o valor persistido contra `docs/index.html` — `const RONI`
pode legitimamente estar atrás da série mais recente por defasagem
normal de publicação, isso nunca é tratado como erro.

**Achado real da revisão direcionada** (corrigido nesta fase): a
distinção entre "`roni_historico.csv` ainda não existe" (primeira
aquisição, legítimo) e "`roni_historico.csv` existe mas está corrompido
e ilegível" não existia — os dois casos produziam o mesmo resultado
(`None`), o que permitiria reinicializar silenciosamente sobre uma base
corrompida, descartando evidência de que havia algo ali antes. Corrigido
com a exceção `BaseCorrompida`, nunca propagada ao chamador externo:
`processar_aquisicao()` agora devolve o estado explícito
`rejeitada_base_corrompida` nesse cenário, preserva o arquivo corrompido
sem reescrevê-lo, e `ultimo_da_serie_ativa()`/
`serie_ativa_corresponde_ao_snapshot()` degradam com segurança (`None`/
`False`) em vez de lançar. 2 testes novos cobrem especificamente esse
cenário (`test_d7`/`test_d8`), usando uma corrupção realista (linhas
com número de campos divergente, que o parser C do pandas rejeita com
`ParserError`) — uma simples sequência de bytes "lixo" não serviria de
teste, porque o `pandas.read_csv` a interpreta como um cabeçalho de uma
coluna só, sem lançar exceção alguma.

**Correção de fixture de teste**: `tests/test_verificar_dashboard.py`
(`_montar_arvore_isolada_verificador`) copiava só
`verificar_dashboard.py`+`proveniencia_indices.py` para a árvore
isolada usada por `ComandoExatoDoWorkflowSemanalTestCase` — ao tornar
`roni_historico` uma dependência direta de `verificar_dashboard.py`,
essas 5 chamadas de subprocesso passaram a falhar por `ImportError`
(stdout vazio, returncode 1). Corrigido copiando também
`roni_historico.py` para a árvore isolada; a ausência de
`data/roni_historico.csv`/`roni_proveniencia.csv`/`roni_snapshots/`
nessas árvores permanece válida — a verificação trata ausência total
como "nada a verificar ainda", nunca como falha.

**Testes locais (Seção 9)**: os 53 testes de `tests.test_roni_historico`
reportados na Fase 2 **já estavam incluídos** no total de 200 testes
daquele relatório — não eram adicionais. Nesta fase, a suíte cresceu de
53 para **65** (12 novos: 2 para `BaseCorrompida`, 10 para
`verificar_integridade_roni`). Regressão combinada desta fase: **235/235
OK** (`test_roni_historico` + `test_update_indices` +
`test_enso_roni_fase4b1` + `test_verificar_dashboard` +
`test_verificar_dashboard_enso_auto` +
`PreservacaoDeModelosCientificosTestCase` +
`test_cobertura_temporal_precipitacao`). `verificar_dashboard.py` real
(dados commitados, sem rede): **APROVADO**, com e sem
`--pular-continuidade-serie-subst`, mostrando
`✅ RONI histórico: série RONI íntegra: 921 observações, DJF/1950 a
ASO/2026`.

**Compatibilidade operacional**: confirmado que `data/roni_proveniencia.csv`
(arquivo já versionado nesta fase) muda de conteúdo em TODA execução real
de `processar_aquisicao()` — mesmo quando `reaproveitada_sem_mudanca`,
grava uma nova linha com timestamp novo — então a barreira
`git diff --quiet docs/index.html data/` de `indices_semanal.yml`
sempre detecta algo a commitar, e o `git add data/` subsequente inclui
corretamente qualquer snapshot novo ainda não rastreado. Nenhum
workflow operacional foi alterado.

## 10.2. Fase 2.2 — correções finais de integridade, revisão temporal e rastreabilidade

Cinco achados confirmados por inspeção independente do código e corrigidos nesta fase (`scripts/roni_historico.py`, `tests/test_roni_historico.py` — nenhum outro arquivo tocado).

**Correção 1 — janela de revisão oficial.** `decidir_promocao()` contava
a janela de 2 meses do CPC a partir do **mês central** do trimestre —
mas mês central, mês final, publicação inicial e primeira observação
pelo sistema são eventos distintos. Reproduzido: para ASO/2026 (mês
central set/2026), uma revisão legítima em dezembro já contava 3 meses
pela regra antiga e seria rejeitada. Corrigido com
`_referencia_disponibilidade()`: usa (1) uma data de publicação
EFETIVAMENTE conhecida, se informada explicitamente (nunca inventada —
só usada em fixtures de teste hipotéticas, já que a fonte real não
publica essa data); ou, na ausência dela, (2) uma ESTIMATIVA pelo
calendário do CPC (mês final + 1, coerente com a atualização "by the
5th of each month" já confirmada). A aquisição inicial (dados desde
1950) nunca passa por essa lógica para nenhum trimestre histórico —
`comparar_series` não tem base prévia para "revisar" nada na primeira
carga.

**Correção 2 — alterações exclusivamente textuais.** Uma reaquisição
com texto diferente mas valores climáticos idênticos criava um hash/
snapshot novo, mas o mecanismo de reconstrução escaneava "qual é a
linha mais recente aceita no manifesto" para decidir a âncora — o que
podia apontar para esse hash novo sem a série ter sido de fato
reescrita. Corrigido: a âncora de reconstrução agora é lida
DIRETAMENTE da própria coluna `snapshot_sha256` da série (nunca
inferida do manifesto); um texto diferente com valores idênticos ao
ativo gera o novo estado `observada_texto_diferente_valor_identico`
(Alternativa B, mais simples: registra a observação com seu próprio
snapshot imutável, nunca troca a referência ativa sem reescrever a
série). `alterou_texto` agora compara contra o hash ATIVO, não contra
"o snapshot precisou ser criado".

**Correção 3 — verificação efetiva de hash.** `reconstruir_da_snapshot()`
lia o conteúdo e confiava no nome do arquivo sem recalcular o SHA-256.
Corrigido: recalcula e compara antes de usar — detecta adulteração
mesmo quando só espaços/quebras de linha mudam (sem alterar os valores
climáticos). `verificar_integridade_roni()` passou a confirmar o hash
de **todos** os snapshots de aquisições aceitas no manifesto, não só o
ativo, e valida formato de hash e caminho registrado contra a
estrutura aprovada.

**Correção 4 — unicidade e cobertura.** `parse_roni_serie_completa()`
colapsava duplicidades idênticas (`test_a10` antigo confirmava esse
comportamento). Corrigido: qualquer duplicidade da chave ano/temporada
— idêntica, divergente, ou coincidente só após arredondamento —
rejeita o documento inteiro, nunca escolhe uma linha. A política de
"não aceitar cobertura reduzida em relação à série ativa" já existia
em `comparar_series`/`decidir_promocao` (demonstrado por teste, não
reimplementado) — o validador estrutural em si nunca fixa contagem de
observações nem uma data de início hardcoded (confirmado por teste:
aceita séries sintéticas de qualquer tamanho).

**Correção 5 — imutabilidade do manifesto e recuperação.**
`_registrar_proveniencia()` fazia upsert (apaga e reinsere) por
`aquisicao_id` — podia alterar timestamp/resultado de uma aquisição já
concluída. Corrigido: reprocessar o MESMO id com os MESMOS fatos é
agora um no-op idempotente (preserva o registro original, inclusive
seu `coletado_em_utc`, capturado no início de `processar_aquisicao`,
nunca no instante da persistência); o mesmo id com fatos incompatíveis
é um `ConflitoDeAquisicao` explícito. `ler_proveniencia_seguro()`
continua detectando corrupção, mas agora NINGUÉM prossegue com uma
escrita quando ela é detectada — `_registrar_proveniencia()` recusa
(levanta `BaseCorrompida`) em vez de reescrever o manifesto
descartando linhas malformadas. Nova função explícita (não automática)
`reconstruir_serie_a_partir_do_manifesto()` para o Cenário B (série
ausente/corrompida, manifesto+snapshot íntegros) — nunca inventa dados,
só reaplica o validador sobre um snapshot cujo hash já foi conferido.
Cenário C (manifesto ausente com série presente) é tratado como perda
de evidência, nunca como primeira inicialização — `processar_aquisicao()`
recusa explicitamente processar qualquer coisa nessa condição, e
`reconstruir_serie_a_partir_do_manifesto()` também falha (não há
evidência suficiente para recuperação inequívoca).

**Verificação do manifesto inicial real**: as 2 linhas com o mesmo
hash (`1297887f...`) têm `aquisicao_id` DIFERENTES
(`20261126T194759Z` e `20261126T195819.363274Z`, ~13s de diferença).
Isso confirma apenas que o código os trata como 2 observações
distintas, nunca fundidas e nunca um conflito (ids diferentes não
disparam `ConflitoDeAquisicao`, que exige o MESMO id). **Correção
(Fase 2.2A, Seção 10)**: a afirmação anterior de que isso "confirma
duas coletas reais distintas à NOAA" foi retirada — ids diferentes com
o mesmo hash, isoladamente, não demonstram duas consultas reais e
independentes (poderiam, por exemplo, refletir dois ids gerados em
sequência rápida para o mesmo conteúdo já obtido, como a verificação de
idempotência da Fase 2). Não há nos 3 artefatos reais nenhuma evidência
adicional (ex.: data de publicação informada por fonte externa) que
resolva essa ambiguidade. Documentada como limitação aberta (seção 11);
os registros e seus timestamps históricos reais permanecem exatamente
como estão, sem alteração.

**Testes**: suíte RONI 65 → 105 (40 novos, 5 grupos:
`JanelaRevisaoOficialTestCase`, `AlteracoesTextuaisTestCase`,
`VerificacaoEfetivaDeHashTestCase`, `UnicidadeECoberturaTestCase`,
`ImutabilidadeDoManifestoTestCase`). Regressão combinada: **275/275
OK**. `verificar_dashboard.py` sobre os dados reais commitados (sem
rede), com e sem `--pular-continuidade-serie-subst`: **APROVADO** —
`✅ RONI histórico: série RONI íntegra: 921 observações, DJF/1950 a
ASO/2026`. Snapshot inicial, série e proveniência reais permanecem
byte a byte idênticos aos da Fase 2 (hash do snapshot confirmado igual
ao nome do arquivo; nenhum `git diff` nos 3 arquivos de dados).

## 10.3. Fase 2.2A — consolidação: ordem de validação, fonte única da versão ativa e recuperação

Atividade de **consolidação** da implementação existente (não uma nova
fase de arquitetura) — revisão independente da Fase 2.2 confirmou as 5
correções daquela fase como satisfatórias e pediu só a reorganização de
`processar_aquisicao()` para fechar uma lacuna de ordem de operações,
mais a unificação de uma regra que ainda tinha mais de uma
implementação. Alterações localizadas em `scripts/roni_historico.py`,
`tests/test_roni_historico.py` e este documento — nenhuma reescrita
integral do módulo, nenhuma alteração em `scripts/update_indices.py`
(avaliado e confirmado não indispensável — ver abaixo).

**Achado real (Seção 4)**: `processar_aquisicao()` gravava a série
normalizada (`_gravar_serie_historico`) ANTES de validar a identidade
da aquisição (`aquisicao_id`) contra o manifesto — um conflito de
identificador só era detectado depois que a nova série já tinha sido
escrita. Corrigido: a identidade da aquisição e a saúde do estado já
existente são validadas **antes** de qualquer decodificação, análise ou
escrita. Reprocessar uma aquisição já concluída (mesmos fatos) é
idempotente e devolve o resultado ORIGINAL sem nenhuma escrita, mesmo
quando essa aquisição é antiga e já foi superada por uma promoção
posterior — nesse caso, a versão ATIVA nunca é alterada ou revertida.
Um identificador repetido com fatos incompatíveis é rejeitado antes de
qualquer gravação.

**Fonte única de verdade (Seção 5)**: nova função `_ultima_promocao_valida(prov)`
— "a linha com `estado_promocao == 'promovida'` mais recente por
`coletado_em_utc`" — reutilizada por `verificar_integridade_roni()`,
`processar_aquisicao()` e `reconstruir_serie_a_partir_do_manifesto()`,
eliminando 2 implementações divergentes da mesma regra. Corrigido um
bug real de regressão: o cruzamento em `verificar_integridade_roni()`
aceitava o hash ativo se ele correspondesse a **qualquer** promoção do
histórico (`.any()`), inclusive uma já superada por uma promoção mais
recente — agora exige correspondência exatamente com a última promoção
válida. Reproduzido por teste dedicado
(`test_serie_presa_numa_promocao_antiga_ja_superada_e_reprovada`) antes
da correção.

**Validação de estado pré-existente (Seção 6)**: `processar_aquisicao()`
agora distingue, antes de preparar qualquer promoção nova: Cenário A
(primeira inicialização — nenhuma série/manifesto, mesmo com um
snapshot órfão sem relação alguma — tratado no Passo 3 como possível
colisão de hash, nunca como "estado anterior inconsistente"); Cenário B
(manifesto com promoção registrada, série ausente/vazia — nunca tratado
como primeira aquisição, recuperação sempre explícita via
`reconstruir_serie_a_partir_do_manifesto()`); Cenário C (série presente,
manifesto ausente — perda de evidência, nunca inicialização); Cenários
D/E (manifesto e série presentes, mas divergentes ou com snapshot
corrompido — reaproveita `verificar_integridade_roni()` integralmente,
sem duplicar a lógica de hash).

**Validação estrutural mínima do manifesto (Seção 7)**: nova
`_validar_estrutura_manifesto()`, integrada em `ler_proveniencia_seguro()`
(logo todo chamador — leitura, escrita e recuperação — se beneficia sem
mudança adicional): colunas obrigatórias presentes; `aquisicao_id`
único (duplicata rejeitada mesmo quando os registros são idênticos,
nunca escolhendo arbitrariamente uma linha); nenhum campo obrigatório
ausente/vazio; `estado_promocao` reconhecido. "Lido sem lançar exceção"
nunca é interpretado como "íntegro".

**Ordem de persistência (Seção 8)**: confirmada e testada a ordem
recomendada — (1) validar identidade + estado existente; (2) decidir a
promoção; (3) persistir/verificar o snapshot; (4) registrar
atomicamente a promoção no manifesto; (5) gerar a série normalizada,
só se `'promovida'`; (6) verificar a consistência final antes de
devolver sucesso. Teste dedicado simula uma interrupção real entre os
passos 4 e 5 (`_gravar_serie_historico` falhando depois do manifesto já
ter registrado a promoção) e confirma: a inconsistência é detectável
por `verificar_integridade_roni()` (nunca silenciosa) e a série é
reconstruível a partir da última promoção registrada — nunca uma
atomicidade conjunta inventada entre os dois arquivos. Um teste
separado confirma que uma falha ANTES do passo 4 (escrita do manifesto)
preserva a base anterior exatamente como estava, sem ser confundida com
uma inconsistência real.

**`scripts/update_indices.py` — avaliado, nenhuma mudança necessária**:
o ponto de integração já trata `resultado_roni['ultimo'] is None` como
"preserva o `const RONI` já publicado, não sobrescreve" — contrato que
cobre genericamente todos os novos estados de rejeição introduzidos
nesta fase (`rejeitada_estado_existente_inconsistente`,
`rejeitada_serie_ausente_com_manifesto_integro`,
`rejeitada_manifesto_perdido`, `rejeitada_inconsistencia_pos_escrita`),
sem precisar de nenhum caso novo. A barreira de publicação
(`verificar_dashboard.py`, item 14) já chama
`verificar_integridade_roni()` incondicionalmente antes de qualquer
publicação.

**Correção da Seção 10 (framing, não fato novo)**: a afirmação da Fase
2.2 de que os 2 registros iniciais do manifesto real (mesmo hash,
`aquisicao_id` diferentes) "confirmam duas coletas reais distintas à
NOAA" foi **retirada** — ids diferentes com o mesmo hash, isoladamente,
não demonstram isso (poderiam refletir, por exemplo, dois ids gerados
em sequência rápida para o mesmo conteúdo já obtido, como a verificação
de idempotência da própria Fase 2). Documentado como limitação aberta
(seção 11); os 2 registros e seus timestamps históricos reais
permanecem exatamente como estão, sem nenhuma alteração.

**Testes**: suíte RONI 105 → **117** (12 novos/reescritos: expansão do
teste de conflito de identificador com verificação completa de estado;
`FonteUnicaDaVersaoAtivaTestCase`, 4 testes; `CenariosDeAceitacaoTestCase`,
7 testes; reforço do teste de duplicidade de `aquisicao_id` para
reprovação estrutural). Regressão combinada relevante:
`tests.test_roni_historico` **117/117**, `tests.test_update_indices`
**74/74**, `tests.test_regressao_cientifica_enso_ci` +
`tests.test_cobertura_temporal_precipitacao` +
`tests.test_verificar_dashboard` + `tests.test_verificar_dashboard_enso_auto`
+ `tests.test_enso_roni_fase4b1` **84/84**. `verificar_dashboard.py`
sobre os dados reais commitados (sem rede), com e sem
`--pular-continuidade-serie-subst`: **APROVADO** nas duas execuções —
`✅ RONI histórico: série RONI íntegra: 921 observações, DJF/1950 a
ASO/2026`. `data/roni_historico.csv`, `data/roni_proveniencia.csv` e o
snapshot inicial (`1297887f...`) permanecem byte a byte idênticos — `git
diff --name-only data/` vazio durante toda a fase.

## 10.4. Fase 2.3 — correção residual: nenhum valor não comprovado, inicialização controlada

Correção residual localizada (não uma nova arquitetura), identificada
por revisão independente após a CI do commit `047ee82`/`6ffc1e4`
aprovar 2.321 testes. Confirmado: `processar_aquisicao()` ainda tinha
retornos antecipados que entregavam `ultimo_da_serie_ativa()`
diretamente — sem confirmar que a base persistida estava íntegra —
nos caminhos de falha de rede, reprocessamento, conflito de
identidade e manifesto perdido.

**Correções**:
1. Nova `_ultimo_se_integro()` — só devolve `ultimo_da_serie_ativa()`
   se `verificar_integridade_roni()` aprovar a base atual; caso
   contrário devolve `None`. Substitui todo uso de
   `ultimo_da_serie_ativa()` nos retornos antecipados (falha de
   coleta, manifesto problema, reprocessamento idempotente, conflito
   de identidade, Cenário C).
2. Reprocessamento idempotente agora preserva o `estado_promocao`
   HISTÓRICO original (nunca reclassifica), mas só entrega `ultimo`
   se a integridade da série ativa estiver comprovada no momento da
   chamada — os dois podem divergir (ex.: a série foi corrompida
   *depois* da promoção original).
3. Novo parâmetro `autorizar_inicializacao_com_snapshot_orfao=False`:
   quando nem série nem manifesto existem mas HÁ snapshot(s) em
   `data/roni_snapshots/`, isso não é mais tratado silenciosamente
   como primeira inicialização — rejeitado por padrão
   (`rejeitada_snapshot_orfao_sem_autorizacao`), só prossegue com
   autorização explícita do chamador. Distingue inicialização
   controlada de atualização operacional automática;
   `scripts/update_indices.py` nunca passa esse parâmetro, preservando
   o padrão seguro em produção.
4. Passo 6 (verificação final antes de devolver sucesso) passou de
   `serie_ativa_corresponde_ao_snapshot()` (self-check) para
   `verificar_integridade_roni()` completa, e passou a rodar para
   QUALQUER estado aceito (`promovida`/`reaproveitada_sem_mudanca`/
   `observada_texto_diferente_valor_identico`), não só para o que
   reescreveu a série.
5. `reconstruir_serie_a_partir_do_manifesto()` já reutilizava
   `ler_proveniencia_seguro()` (validação estrutural, Fase 2.2A) e
   `reconstruir_da_snapshot()` (hash) antes de recuperar — confirmado
   por teste novo, sem necessidade de alteração.

**Testes**: suíte RONI 117 → **127** (10 novos, cobrindo os 9 cenários
pedidos: falha de rede com base íntegra/adulterada, reprocessamento com
série íntegra/inconsistente, conflito com base íntegra/inconsistente,
snapshot órfão sem autorização, inicialização legítima autorizada,
recuperação bloqueada por manifesto estruturalmente inválido,
verificação completa após estado não-promovido). Os 2 testes que
simulavam colisão de hash num snapshot órfão (`test_d1`, `test_b9b`)
foram ajustados para autorizar explicitamente a inicialização, sem
alterar seu propósito original. Regressão combinada: `test_roni_historico`
127/127, `test_update_indices` 74/74, demais suítes de preservação
84/84 — **285/285 OK**. `verificar_dashboard.py` aprovado com e sem
`--pular-continuidade-serie-subst`. Nenhuma mudança em
`scripts/update_indices.py`/`scripts/verificar_dashboard.py` (API
pública inalterada, parâmetro novo com default seguro). Dados reais
RONI (série, manifesto, snapshot inicial) permanecem byte a byte
idênticos.

## 11. Limitações conhecidas

- **(Fase 2.2A)** Os 2 registros iniciais do manifesto real têm o
  mesmo hash e `aquisicao_id` diferentes (~13s de diferença) — isso
  não demonstra, por si só, duas consultas reais e independentes à
  NOAA (poderia refletir, por exemplo, dois ids gerados em sequência
  rápida para o mesmo conteúdo já obtido, como a verificação de
  idempotência da própria Fase 2). Não há nos 3 artefatos reais
  nenhuma evidência adicional que resolva essa ambiguidade. Os
  registros e seus timestamps históricos reais permanecem exatamente
  como estão — nunca alterados para investigar isso.
- A política de disponibilidade (Correção 1, Fase 2.2) implementa só 2
  dos 3 níveis descritos originalmente: data informada explicitamente
  (nunca usada em produção hoje — não há fonte real para ela) e
  estimativa pelo calendário. Um 3º nível, "primeira observação
  comprovada pelo sistema" (rastrear quando cada trimestre
  individualmente apareceu pela primeira vez como novo numa aquisição
  real), exigiria uma extensão de esquema maior (uma coluna por
  trimestre no manifesto ou numa tabela própria) — não implementado
  nesta fase por não ser necessário para corrigir o defeito confirmado
  (contagem pelo mês central); fica registrado como possível refinamento
  futuro, não como lacuna da correção atual.
- O arquivo `RONI.ascii.txt` não se autodeclara ERSSTv6 — a versão é
  uma constante do módulo, confirmada por evidência institucional
  externa (catálogo + PNS 26-05), não extraída do conteúdo. Uma futura
  mudança de versão metodológica pelo CPC **não seria detectada
  automaticamente** por este módulo — exigiria atualização manual da
  constante após nova verificação institucional.
- A convenção de ano (mês central) foi confirmada por inferência sobre
  os picos históricos da própria série, não por documentação textual
  da fonte — permanece como premissa evidenciada, não uma garantia
  contratual do CPC.
- Criar o snapshot/manifesto agora não reconstrói o histórico de
  versões observadas pelo sistema **antes** desta fase — só a partir
  desta implementação o sistema passa a registrar prospectivamente
  qual versão da fonte alimentou cada atualização.
- `data/roni_proveniencia.csv` é reescrito por completo (não um append
  físico puro) a cada chamada, para suportar o upsert por
  `aquisicao_id` com substituição atômica — custo desprezível dado o
  volume (uma linha por execução, cadência semanal/mensal), mas não é
  um append O(1).
