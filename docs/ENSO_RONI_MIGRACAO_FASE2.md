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

## 11. Limitações conhecidas

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
