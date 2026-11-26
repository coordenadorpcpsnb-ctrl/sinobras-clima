# ENSO-ONI-FIX 1 — Correção da persistência histórica do ONI aproximado

**Correção isolada**, independente da investigação científica RONI
(Fase ENSO-RONI 4B.2A/4B.2A.1). Não altera gatilhos operacionais, não
substitui ONI por RONI, não toca `docs/index.html`.

## 1. Contexto

A Fase ENSO-RONI 4B.2A.1 encontrou, ao auditar os indicadores ENSO do
projeto, que `data/master_monthly.csv` tinha a coluna `oni` vazia em
alguns dos meses mais recentes mesmo depois que o dado necessário para
calculá-la já estava disponível. Esta fase corrige exclusivamente essa
causa raiz.

## 2. Baseline

- `main`: `596678ed95af73c3d893effe22e02424563ca0d4` — confirmada, sem
  commits posteriores, working tree limpo.
- PR #75: integrada (merge commit acima).
- PR #59: aberta, HEAD `cc022fede00dc7b293b9ae1f1f2e61c5dc961b47` — intocada.
- PR #61: aberta, HEAD `3b4fa57c68c074e2168408e1e43b110a6be5ef6a` — intocada.
- Branch desta correção: `claude/enso-oni-fix-persistencia`, criada a
  partir de `origin/main` nesse SHA.

## 3. Causa raiz

`oni` é uma média móvel **centrada** de 3 meses de Niño 3.4
(`calc_oni()`): uma linha só pode receber `oni` quando o mês *seguinte*
já existe em `nino34`. `atualizar_master_monthly()`
(`scripts/update_indices.py`) lê o `sstoi.indices` inteiro a cada
execução (contém sempre o histórico completo disponível até o mês mais
recente publicado pelo CPC), mas o laço de gravação pulava **qualquer**
`(ano,mês)` já presente no CSV:

```python
for (y, m) in sorted(nino34.keys()):
    if (y, m) in existentes:
        continue
```

Uma vez gravada com `oni` vazio (porque o mês seguinte ainda não
existia *naquela* execução), a linha nunca era revisitada — mesmo
depois que o mês seguinte chegasse em uma execução posterior e o
cálculo já fosse possível.

**Confirmado que isto nunca afetou o dashboard**: `build_series()`
(também em `scripts/update_indices.py`) recalcula `oni = calc_oni(nino34)`
do zero a cada execução, a partir do mesmo `nino34` recém-buscado — sem
nunca ler `data/master_monthly.csv`. Inspecionando `docs/index.html`
publicado no momento desta investigação, `indices.oni` já trazia
08/26=2,46 e 09/26=2,87 preenchidos, enquanto o CSV tinha as mesmas
duas células vazias. Só o registro histórico ficava com lacunas
evitáveis; o semáforo operacional (`D.now.oni`, via `latest_non_null`)
nunca usou um valor desatualizado por causa deste bug.

## 4. Evidência de reprodução

Teste `test_reproducao_lacuna_e_preenchida_quando_janela_completa`
(`tests/test_update_indices.py`): grava um CSV sintético com jun-jul/26
preenchidos e ago/26 com `oni` vazio; chama
`atualizar_master_monthly` com um dicionário `nino34` que já inclui
set/26 (mês seguinte a agosto). **Antes da correção**, o teste falhava:

```
AssertionError: np.float64(nan) != 2.46 within 2 places
```

exatamente a causa raiz esperada (janela jul=2,03 + ago=2,52 + set=2,84
completa, mas a lacuna não era preenchida).

## 5. Impacto sobre o CSV histórico vs. ausência de impacto no dashboard

| | `data/master_monthly.csv` (antes da correção) | `docs/index.html` (sempre) |
|---|---|---|
| ago/2026 `oni` | vazio | 2,46 |
| set/2026 `oni` | vazio | 2,87 |
| out/2026 `oni` | vazio (nov/26 ainda não publicado pelo CPC) | vazio (mesma razão — estrutural, não bug) |

O semáforo (`secoAtivo`/`excAtivo`) nunca foi afetado: usa só o valor
mais recente do HTML, já correto. O impacto real é na **integridade do
registro histórico**, relevante para qualquer análise retrospectiva
futura (ex.: Fase ENSO-RONI 4B.2B) que leia `master_monthly.csv`
diretamente.

## 6. Solução implementada

Nova função `_recalcular_oni_de_lacunas(df, nino34, oni)` em
`scripts/update_indices.py`, chamada por `atualizar_master_monthly()`
logo após `oni = calc_oni(nino34)` (mesmo dicionário usado para as
linhas novas — a fórmula de `calc_oni()` não foi alterada):

1. Localiza linhas já existentes com `oni` vazio.
2. Para cada uma, consulta `oni.get((y, m))` — se `None` ou não-finito,
   a janela ainda está incompleta (comportamento correto, não é bug) e
   a linha é deixada como está.
3. Se há um valor candidato, verifica a consistência dos 3 meses da
   janela (anterior, central, posterior) entre o `nino34` já persistido
   (quando esse mês já é uma linha do CSV) e o `nino34` desta execução.
   Divergência → lacuna **não** preenchida, aviso impresso no log.
4. Sem divergência → a célula `oni` é preenchida. Nenhuma outra coluna
   é tocada.

`atualizar_master_monthly()` passou a gravar o CSV também quando só
houve preenchimento de lacunas (antes, `if not novas: return 0`
pulava a escrita inteira nesse caso).

## 7. Regras de consistência dos três meses

- Comparação feita com a mesma precisão de 2 casas decimais já usada
  no projeto (`round(x, 2)`) — sem tolerância numérica arbitrária nova.
- Um mês da janela que **ainda não é uma linha persistida** (vai ser
  inserido nesta mesma execução, como linha nova, mais abaixo no mesmo
  `atualizar_master_monthly()`) não conta como divergência — não há
  nada para divergir ainda. Isso é automático: o dicionário de
  `nino34_persistido` é construído a partir do `df` **antes** de
  qualquer linha nova ser concatenada, então o resultado não depende da
  ordem de processamento entre o preenchimento de lacunas e a inserção
  de linhas novas.
- Testado explicitamente: divergência no mês anterior, no mês central e
  no mês posterior — nos três casos a lacuna permanece vazia e o
  `nino34` já persistido não é alterado.

## 8. Proveniência

`oni` **não é registrado** em `data/indices_proveniencia.csv` — nem
antes, nem depois desta correção. O esquema atual
(`observado`/`persistido`/`estimado`/`desconhecido`, em
`scripts/proveniencia_indices.py`) foi desenhado para dado de origem
externa (Niño 3.4, TSA, PDO); nenhuma dessas quatro classificações
descreve adequadamente um índice **derivado**, recalculado sobre
componentes já conhecidos, numa execução posterior à em que a linha foi
criada. Formalizar isso exigiria alterar `proveniencia_indices.py`, que
está **fora do escopo de arquivos autorizados** desta fase — a decisão
foi registrar essa lacuna de esquema em vez de forçar `oni` numa
classificação que não o descreve (ex.: `estimado` sugeriria incerteza
que não existe; `observado` sugeriria uma fonte externa que não existe).
Consequência direta: nenhuma data de preenchimento é gravada como se
fosse data histórica de disponibilidade, e nenhuma proveniência
desconhecida vira conhecida sem evidência — porque nada é escrito para
`oni` de forma alguma.

## 9. Casos de teste

`tests/test_update_indices.py`, classe
`AtualizarMasterMonthlyBackfillOniTestCase`, 24 testes:

| Grupo | Testes | Cobertura |
|---|---|---|
| Reprodução | 1 | Falha antes da correção, pela causa raiz exata |
| A — comportamento principal | 6 | Preenche quando completo; preserva válido; preserva ausência (falta mês posterior/anterior); múltiplas lacunas; combinação calculável/não-calculável; mês posterior inserido na mesma execução |
| B — integridade dos componentes | 9 | Divergência em cada um dos 3 meses da janela; valor candidato não-finito (NaN/±Infinito) via injeção direta e via `nino34` real; ausência temporal intermediária; diferença só de precisão decimal não é falsa divergência |
| C — calendário | 4 | Janelas nov-dez-jan e dez-jan-fev (viradas de ano); primeira observação da série (sem mês anterior); última observação (sem mês posterior) |
| D — preservação histórica | 1 (7 asserções) | Nenhum `oni` válido sobrescrito; nenhum `nino34`/`tsa`/`pdo` histórico alterado; nenhuma linha removida/duplicada; ordenação preservada; sem alteração semântica em colunas não relacionadas |
| E — idempotência e proveniência | 3 | Segunda execução idêntica não produz mudança adicional; `oni` nunca aparece em `indices_proveniencia.csv`; divergência de origem gera aviso no log e nunca é "corrigida" silenciosamente |

Suíte completa: **24/24 OK** (`python -m unittest
tests.test_update_indices.AtualizarMasterMonthlyBackfillOniTestCase -v`).

## 10. Resultado da validação sobre cópia do CSV real

Cópia temporária de `data/master_monthly.csv` (nunca o arquivo
versionado), fonte Niño 3.4 = `sstoi.indices` já baixado ao vivo nesta
sessão (Fase ENSO-RONI 4B.2A):

- Hash SHA-256 da fonte `sstoi.indices`: `c7993d1e051d182d1f55f7f937e5b74b3bbd20e08da5cbfc74bc5351a050a6c0`.
- Hash do CSV antes: `631bf12589ed522ccedecde12602f53576786525704fe4a6a02e115080880528`.
- Hash do CSV depois (1ª execução): `db13e38241381ebde0be052e65b31b4de60d01cc20ce4bccacb7357ded1fb08a`.
- Linhas antes/depois: 550/550 (nenhuma linha nova nesta fonte — já
  estavam todas presentes).
- Células `oni` válidas: 547 → 549.
- Lacunas preenchidas: **2** (ago/26 = 2,46; set/26 = 2,87).
- out/26 permanece vazio — nov/26 ainda não publicado pelo CPC no
  momento desta validação (estrutural, não bug).
- Valores `oni` previamente válidos que mudaram: **0**.
- Outras colunas (`nino34`/`tsa`/`pdo`) alteradas onde já havia valor: **0**.
- **Comparação textual linha a linha**: as 543 linhas anteriores a
  jun/2026 são byte-idênticas antes/depois; das 7 linhas finais, só
  ago/26 e set/26 mudam, e mudam exclusivamente na célula `oni` — nenhuma
  outra célula dessas duas linhas (incluindo `tsa`/`pdo`) é tocada. A
  diferença de hash do arquivo inteiro vem só dessas duas células —
  não há diferença textual sem diferença semântica, nem o inverso.

### Idempotência

2ª execução sobre o CSV já corrigido: retorno `0` linhas novas, hash
idêntico ao da 1ª execução (`True`).

### Arquivo versionado

`data/master_monthly.csv` nunca foi tocado — hash antes/depois de toda
a investigação permanece `631bf12589ed522ccedecde12602f53576786525704fe4a6a02e115080880528`.

## 11. Limitações

- A correção só roda na **próxima execução real** de
  `scripts/update_indices.py` (via `update.yml`/`indices_semanal.yml`)
  — não foi aplicada ao `data/master_monthly.csv` versionado nesta
  fase (não autorizado: "alteração futura dos arquivos históricos
  produzida por uma execução operacional será objeto de autorização
  separada").
- `oni` permanece fora do esquema de proveniência — ver Seção 8.
- Esta correção não resolve, nem pretende resolver, a defasagem
  estrutural mínima (~1-2 meses) inerente a uma média centrada — isso
  não é um bug, é a definição do índice.

## 12. Estratégia proposta para atualização operacional futura

Quando autorizado: rodar `update_indices.py` normalmente (workflow
agendado ou `workflow_dispatch` supervisionado) — a correção já being
parte do fluxo normal, preencherá as lacunas calculáveis automaticamente
na primeira execução real subsequente, sem necessidade de script
avulso. Não proponho um script de backfill separado — seria uma segunda
via de escrita para a mesma coluna, contrariando o princípio de "um
único ponto de escrita" já estabelecido para `oni`.

## 13. Critérios de aceitação

- [x] Causa raiz comprovada por leitura de código e reprodução numérica.
- [x] Teste de regressão falha antes da correção, pela razão exata.
- [x] Correção mínima, fórmula de `calc_oni()` inalterada.
- [x] 24/24 testes novos aprovados.
- [x] Validação sobre cópia do CSV real: 2 lacunas preenchidas, 0
      valores válidos alterados, idempotência confirmada.
- [x] `data/master_monthly.csv` versionado nunca tocado.
- [x] Suíte `test_update_indices.py` completa (98 testes), `test_enso_roni_fase4b1.py`
      + `PreservacaoDeModelosCientificosTestCase` + `test_cobertura_temporal_precipitacao.py`
      (73 testes) e `verificar_dashboard.py` — todos aprovados, sem regressão.
- [x] Diff restrito a `scripts/update_indices.py` e `tests/test_update_indices.py`.

---

## 14. Fase ENSO-ONI-FIX 1.2 — correção da consistência residual

A revisão da Fase 1.1 (própria deste documento, não repetida aqui)
aprovou tudo acima, mas **não aprovou push/PR**: a reprodução de um
cenário adicional ("Cenário 6") demonstrou uma falha de integridade
real, corrigida nesta seção.

### 14.1. Falha residual identificada

A versão da Seção 6/7 acima construía `nino34_persistido` **excluindo**
linhas com `nino34` ausente/inválido do dicionário de comparação. Para
uma lacuna de `oni`, o laço de consistência fazia:

```python
persistido = nino34_persistido.get((yy, mm))
atual = nino34.get((yy, mm))
if persistido is None or atual is None:
    continue   # tratado como "nada a comparar"
```

Isso tratava da mesma forma dois casos diferentes: **(a)** o mês ainda
não é uma linha do CSV (vai ser inserido validamente nesta execução) e
**(b)** o mês **já é uma linha**, mas seu `nino34` está ausente/inválido.
No caso (b), a lacuna de `oni` era preenchida mesmo assim, usando um
`nino34` que **nunca foi persistido/confirmado** para aquela linha
específica — só porque a fonte atual (`nino34`, o dict vindo de
`sstoi.indices` desta execução) tinha um valor para aquele mês.

### 14.2. Reprodução antes da correção

Teste `test_reproducao_f_mes_central_existente_com_nino34_ausente_nao_preenche`:
uma linha de agosto/2026 **já existente** no CSV, com `nino34` ausente e
`oni` vazio; fonte atual com a janela jul/ago/set completa. **Antes da
correção**, o teste falhava:

```
AssertionError: False is not true : linha de agosto já existe com
nino34 ausente — oni NÃO deveria ser preenchido...
```

confirmando que a lacuna era preenchida (`oni=2.46`) mesmo com o
componente central da própria linha ausente.

### 14.3. Distinção implementada

`_recalcular_oni_de_lacunas()` passou a receber um 4º parâmetro,
`novas_linhas` (a lista `novas` que `atualizar_master_monthly()` já
monta para as linhas que serão inseridas nesta execução), e a chamada
foi **movida para depois** desse laço de montagem (antes, era chamada
antes). Em vez de um dicionário só de linhas já existentes, constrói
uma **visão efetiva** da série ao final da execução:

```python
persistido_efetivo = {}
for r in df.itertuples():
    v = _valor_numerico_finito(r.nino34)
    if v is not None:
        persistido_efetivo[(int(r.year), int(r.month))] = v
for linha in novas_linhas:
    v = _valor_numerico_finito(linha.get('nino34'))
    if v is not None:
        persistido_efetivo[(int(linha['year']), int(linha['month']))] = v
```

Um mês da janela só é aceito se aparecer em `persistido_efetivo` **com**
um valor que bate com `nino34` (a mesma fonte usada para calcular
`oni`) — nunca mais presumido só por `nino34` ter algo para aquele mês.
Uma linha que **existe mas está inválida** nunca entra em
`persistido_efetivo` por nenhum dos dois caminhos — é tratada como
rejeição, não como ausência.

### 14.4. Achado adicional durante os novos testes (corrigido nesta mesma fase)

O teste "componente existente com valor não numérico" revelou um bug
real na implementação: `math.isfinite()` lança `TypeError` para uma
string (ex.: uma célula `nino34` corrompida como `"N/D"`, que faz a
coluna inteira virar `dtype object` no pandas) — isso derrubaria a
atualização inteira por causa de uma única célula histórica corrompida.
Corrigido com `_valor_numerico_finito(v)`, que tenta converter com
segurança e devolve `None` (nunca lança exceção) para qualquer valor
que não seja um número real finito.

### 14.5. Novos testes (Grupos F e G)

Além dos 24 testes da Fase 1 (preservados, sem redução de cobertura) +
1 de reprodução do Cenário 6:

| Grupo | Cenário | Teste |
|---|---|---|
| F1 | Mês anterior existente com nino34 ausente | `test_f1_mes_anterior_existente_com_nino34_ausente_nao_preenche` |
| F2 | Mês central existente com nino34 ausente | reutiliza a reprodução do Cenário 6 |
| F3 | Mês posterior existente com nino34 ausente | `test_f3_mes_posterior_existente_com_nino34_ausente_nao_preenche` |
| F4 | Componente existente não numérico | `test_f4_componente_existente_nao_numerico_nao_preenche` (revelou o bug do `math.isfinite`, §14.4) |
| F5 | Componente existente NaN | reutiliza F1/F2/F3 |
| F6/F7 | Componente existente ±Infinito | `test_f6`/`test_f7` |
| F8 | Registro existente ausente do dicionário de valores válidos | `test_f8_registro_existente_ausente_do_dicionario_de_valores_validos` — também confirma que um `oni` pré-existente "órfão" de um `nino34` NaN não é alterado |
| F9 | Linhas duplicadas (mesma chave ano/mês) | `test_f9_linhas_duplicadas_mesmo_mes_comportamento_documentado` — estado que `atualizar_master_monthly()` nunca produz por construção; documentado (não corrigido): a última linha processada prevalece silenciosamente, sem exceção |
| G10–G16 | Preservação do comportamento correto (inserção na mesma execução, janela completa, mudança de ano, sem sobrescrita, idempotência) | reutilizam `test_a7`, `test_reproducao_lacuna_e_preenchida_quando_janela_completa`/`test_a2`, `test_c17`/`test_c18`, `test_d21_a_d27`, `test_e28`; `test_g12_janela_valida_e_janela_invalida_na_mesma_execucao` é o único genuinamente novo (uma lacuna válida e uma rejeitada na mesma chamada) |

Suíte completa da classe: **33/33 OK**.

### 14.6. Validação sobre cópia do CSV real (repetida)

Mesma fonte congelada (`sstoi.indices`, hash
`c7993d1e051d182d1f55f7f937e5b74b3bbd20e08da5cbfc74bc5351a050a6c0`),
nova cópia de `data/master_monthly.csv` (hash antes
`631bf12589ed522ccedecde12602f53576786525704fe4a6a02e115080880528`,
**idêntico ao arquivo versionado real no momento desta validação**,
confirmando que ele segue intocado). Resultado **idêntico ao da Fase
1**: hash depois `db13e38241381ebde0be052e65b31b4de60d01cc20ce4bccacb7357ded1fb08a`
— a correção residual não muda o resultado para os dados reais atuais
(nenhuma célula real está corrompida hoje), só fecha a brecha teórica.
550→550 linhas, 547→549 `oni` válidos, ago/26=2,46, set/26=2,87, out/26
ausente, 0 valores válidos alterados, 0 outras colunas alteradas,
idempotência confirmada (2ª execução: hash idêntico).

### 14.7. Limitação de proveniência (reafirmada, não resolvida)

A ampliação de `indices_proveniencia.csv` **não foi implementada**
nesta fase (fora do escopo autorizado). Proposta mínima avaliada, não
implementada:

- **Registro específico para índices derivados**, separado do esquema
  atual (que é para dado de origem externa) — ex.: um CSV próprio
  (`data/indices_derivados_preenchimentos.csv`) ou uma extensão de
  `proveniencia_indices.py` com uma 5ª classificação (`'derivado'` ou
  equivalente), contendo: indicador, arquivo de destino, período
  climático, meses da janela, os 3 valores de Niño 3.4 usados, valor
  anterior (sempre vazio, hoje), valor preenchido, fonte, hash da fonte,
  método, data efetiva do preenchimento, estado de disponibilidade
  histórica (sempre "desconhecida", hoje, por falta de vintages — ver
  Fase ENSO-RONI 4B.2A.1 §6.2).
- **Caminho candidato**: módulo independente, não uma extensão de
  `scripts/proveniencia_indices.py` (menor acoplamento, sem risco de
  regressão nas 4 classificações existentes).
- **Não resolve integralmente o problema de vintages** — mesmo com esse
  registro, não há como reconstruir o que *já havia sido preenchido*
  antes da primeira execução que tiver esse registro (ou seja, os
  preenchimentos de ago/set-2026 feitos pela primeira execução real
  pós-merge desta correção não teriam esse registro, a menos que ele já
  exista nesse momento).
- **Decisão sobre implementar**: não tomada nesta fase, por instrução
  explícita — fica para antes do merge ou para o desenho da Fase 4B.2B.

### 14.8. Workflows — correção documental

`docs/ENSO_ONI_FIX_PERSISTENCIA.md` (este arquivo) está sob
`docs/**`, o mesmo filtro `paths` de `publicar.yml`
(`on: push: branches: [main], paths: ['docs/**']`). **Correção à Fase
1.1**: um push desta branch em `main` dispararia `publicar.yml`
(deploy do GitHub Pages) só por causa deste arquivo `.md` — mesmo que
`docs/index.html` não tenha mudado. Não é destrutivo (o workflow
revalida o conteúdo de `docs/` contra o `main` atual antes de publicar,
e o conteúdo publicado seria idêntico ao já publicado), mas é um
deploy redundante — mesma categoria de redundância já registrada na PR
#59 para `update.yml`/`indices_semanal.yml`. Nenhuma dependência
indireta foi encontrada que faça `publicar.yml` executar
`update_indices.py` ou qualquer recálculo de dados — ele só empacota e
publica o conteúdo já existente em `docs/`.

A afirmação da Fase 1.1 de que "o merge não dispara diretamente
`indices_semanal.yml` nem `update.yml`" **permanece correta** — não
muda com este achado.

Esta documentação não contém conclusões sobre superioridade científica
do RONI e não formaliza o protocolo experimental da Fase 4B.2B.
