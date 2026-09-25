# Fase 2C.1b — encerramento do POC de infraestrutura NOAA CFSv2

## Objetivo deste documento

Registrar as evidências da execução real aprovada do POC de
infraestrutura do CFSv2 (Fase 2C.1b), distinguindo o que foi
**empiricamente confirmado** nessa execução do que já estava apenas
**documentado** no catálogo antes dela. Este documento **não** é
conclusão científica sobre a habilidade preditiva do CFSv2 — o POC
nunca calculou skill, nunca comparou contra CHIRPS (Seção 18/35-S de
`nmme_poc.py`).

## Evidência principal — execução real aprovada

- **Run ID**: [`36042228571`](https://github.com/coordenadorpcpsnb-ctrl/sinobras-clima/actions/runs/36042228571)
- **Workflow**: `NMME Catálogo + POC (Fase 2C.1/2C.1b)` (`.github/workflows/nmme_poc.yml`)
- **Branch/commit**: `main`, `head_sha=6ac00e8264957dff30d8297ffc4cfbcb67a16e64`
  (merge commit da [PR #32](https://github.com/coordenadorpcpsnb-ctrl/sinobras-clima/pull/32),
  "Fase 2C.1b: RANGEEDGES como fonte principal do POC CFSv2")
- **Disparo**: `workflow_dispatch` manual, pelo usuário (`coordenadorpcpsnb-ctrl`)
- **Conclusão do job**: `success` (todos os 10 steps concluídos com sucesso)
- **Duração do step "Rodar POC real"**: ~3 segundos (18:39:57.34Z →
  18:40:00.27Z) — consistente com `requests_previstos: 1` (uma única
  requisição RANGEEDGES)

### Como esta evidência foi obtida (limite de acesso a registrar)

O artifact publicado pelo job (`nmme-catalogo-poc`, id `10827535927`,
17.612 bytes, contendo os 7 arquivos: `nmme_model_catalog.csv`,
`nmme_common_period.json`, `nmme_poc_raw.csv`,
`nmme_poc_temporal_audit.csv`, `nmme_poc_access_audit.csv`,
`metadata.json`, `RELATORIO.md`) **não pôde ser baixado nesta sessão**:
o link de download do GitHub Actions redireciona para
`productionresultssa16.blob.core.windows.net`, domínio bloqueado pela
política de rede do ambiente de execução (confirmado com `curl`/`WebFetch`,
erro `EGRESS_BLOCKED`/`CONNECT tunnel failed, response 403`).

Diante disso, a evidência abaixo foi extraída do **log do próprio job**
(`get_job_logs`, step "Rodar POC real"), que é o `stdout` literal do
script (`scripts/nmme_poc.py::main`) — a mesma informação que teria ido
para `metadata.json`/`RELATORIO.md`, só que impressa no console em vez
de lida do arquivo. Isso cobre os campos citados abaixo (status,
backend, representação, checklist, seleção de S), mas **não** cobre os
valores linha-a-linha do `nmme_poc_raw.csv` (as 144 precipitações
individuais por membro/lead) nem os textos completos do
`RELATORIO.md` — esses só existem dentro do ZIP não acessado. Se for
necessário auditar os valores brutos, é preciso baixar o artifact por
outro caminho (ex.: navegador do usuário, ou reautorizar o domínio no
proxy de rede).

### Saída literal do step "Rodar POC real" (run 36042228571)

```
=== NMME POC REAL (Fase 2C.1b) — CFSv2, origem 2005-01, H1-H6 ===
  ✅ artifacts/nmme_poc/nmme_model_catalog.csv
  ✅ artifacts/nmme_poc/nmme_common_period.json
  ✅ artifacts/nmme_poc/nmme_poc_raw.csv
  ✅ artifacts/nmme_poc/nmme_poc_temporal_audit.csv
  ✅ artifacts/nmme_poc/nmme_poc_access_audit.csv
  ✅ artifacts/nmme_poc/metadata.json
  ✅ artifacts/nmme_poc/RELATORIO.md

backend_used=IRIDL_LEGACY dataset_representation_used=NMME_HARMONIZED_MONTHLY backend_fallback_ocorreu=False
poc_status=APROVADO
  - download_bem_sucedido: True
  - um_modelo: True
  - uma_origem: True
  - h1_a_h6_presentes: True
  - members_status_ok: True
  - member_axis_size_ok: True
  - member_count_per_lead_ok: True
  - sem_duplicata: True
  - valores_finitos: True
  - precipitacao_nao_negativa: True
  - unidade_confirmada: True
  - grade_confirmada: True
  - temporal_mapping_confirmado: True
  - raw_completo: True
  - nenhum_skill_calculado: True

inicializacao_fonte_principal=RANGEEDGES inicializacao_selecao_metodo=RANGEEDGES_WINDOW_COORDINATE_MATCH
  valores de S antes da seleção: ['2005-01-01 00:00:00', '2005-02-01 00:00:00']
  valores de S depois da seleção: ['2005-01-01 00:00:00']

✅ POC real do CFSv2 APROVADO — ver artifacts/nmme_poc/RELATORIO.md
```

O mesmo job, nos steps anteriores (mesma execução, mesmo commit),
também confirmou: suíte de testes completa passando (step "Rodar suíte
de testes existente") e `verificar_dashboard.py` com resultado
`APROVADO` (step "Verificar integridade do dashboard") — ou seja, o
POC real rodou sobre um estado do repositório onde o dashboard de
produção já estava íntegro e inalterado por esta mudança.

## O que foi efetivamente observado (empírico) vs. o que já era documentado

| Item | Antes (documentado, catálogo Rodada 4/5) | Depois (empírico, run `36042228571`) |
|---|---|---|
| Backend | IRIDL_LEGACY (endpoint + 5 dimensões documentadas via `dlentries`, nunca testado) | **IRIDL_LEGACY confirmado** — requisição real respondeu |
| Representação | NMME_HARMONIZED_MONTHLY (Representação B) registrada, "nenhum downloader escrito" (nota desatualizada por uma revisão anterior a este encerramento) | **Representação B confirmada como a rota usada**, downloader (`montar_url_iri_cfsv2_nmme_harmonized`) funcionando |
| Seleção temporal | Nunca testada contra o servidor real | RANGEEDGES devolveu **janela com 2 inicializações** (jan **e** fev/2005) para os mesmos limites de S pedidos — reprodução em produção do achado da run diagnóstica `36032400919`; `selecionar_inicializacao_por_coordenada` isolou exclusivamente jan/2005 por coordenada exata |
| Calendário | Grade S/L do catálogo-fonte lida de primeira mão (Rodada 4/5), nunca aberta | `time_decode_mode`/calendário normalizados com sucesso (sem isso o mapeamento temporal teria ficado `UNCONFIRMED`, e `temporal_mapping_confirmado` seria `False`) |
| Coordenadas | X/Y grade regular 360×181 (1°×1°) documentada | Ponto mais próximo de São Bento do Tocantins selecionado com sucesso (`VALUE` em X/Y, não afetado pela migração de S) — `grade_confirmada=True` |
| Unidades | `prec` em kg/m²/s convertida para mm/day "pelo próprio catálogo" (documentado) | `unidade_confirmada=True` — conversão de precipitação executada e validada pelos guardrails de `nmme_processar.converter_precip_para_mm_mes` |
| Membros | `member_axis_size=24` (Rodada 5, leitura do `index.tex`) | **24 membros por lead confirmados de fato** (`member_axis_size_ok=True`, `member_count_per_lead_ok=True`, `sem_duplicata=True`) |
| H1–H6 | Grade L "0.5 1 9.5" documentada | `h1_a_h6_presentes=True` — os 6 horizontes presentes e mapeados |
| RAW | Esperado 24×6=144 registros | `raw_completo=True` (nenhum membro/lead faltando na Representação B para esta origem) — o valor exato de 144 não pôde ser recontado nesta sessão a partir do CSV (ver limite de acesso acima), mas é o valor estruturalmente esperado por `n_raw_expected = member_axis_size × len(leads)` e é o mesmo citado pela tarefa como evidência a registrar |
| Skill | N/A | `nenhum_skill_calculado=True` — confirmado que nenhuma métrica de habilidade preditiva foi computada |

## Interpretação — o que este resultado prova e o que não prova

**Prova**: que a arquitetura RANGEEDGES-fonte-principal (branch
`claude/fase2c1b-rangeedges-fonte-principal`, merge `6ac00e8`) funciona
contra o servidor real do IRIDL para a rota Representação B — acesso,
seleção explícita de inicialização, contagem de membros, unidade,
grade e mapeamento temporal todos confirmados por um subset real
pequeno (1 origem, H1–H6, 24 membros, 1 ponto).

**Não prova**:
- **Habilidade preditiva do CFSv2** — nenhuma skill foi calculada
  (`nenhum_skill_calculado=True`, por desenho — Seção 18/35-S de
  `nmme_poc.py`). Isso só será avaliado na Fase 2C.2 (ver
  `docs/nmme-fase2c2-especificacao.md`).
- **Que outras inicializações/anos funcionam** — só jan/2005 foi
  aberta. O achado de que RANGEEDGES pode devolver janelas com mais de
  1 inicialização é generalizável ao MÉTODO (a seleção explícita lida
  com isso corretamente, testado para os casos obrigatórios), mas não
  significa que toda origem 1982–2010 necessariamente abre sem
  problema — daí a estratégia de amostra pequena antes da extração
  completa (Seção G da especificação da Fase 2C.2).
- **Que a Representação A (RAW_NATIVE_ENSEMBLE) ou a rota CCSR_BETA
  funcionam** — nenhuma das duas foi tocada por esta execução.

## Atualização do catálogo

Alteração feita **exclusivamente** na rota efetivamente validada
(`RotaMemberLevel` de `NOAA_NCEP/CFSv2`, backend `IRIDL_LEGACY`,
representação `NMME_HARMONIZED_MONTHLY`, em `scripts/nmme_catalogo.py`):

- `status`: `POC_READY_DOCUMENTED_LEGACY` → **`EMPIRICALLY_CONFIRMED`**
  (novo valor de status de rota, adicionado nesta revisão)
- Novos campos preenchidos **só nesta rota**:
  `poc_validated_at='2026-09-24'`,
  `poc_validation_commit='6ac00e8264957dff30d8297ffc4cfbcb67a16e64'`,
  `poc_validation_run_id='36042228571'`,
  `poc_validation_evidence=(...)` (citação completa da evidência acima)
- `notes` da rota estendida com a interpretação acima (o que prova/não
  prova) e a correção do texto desatualizado sobre "nenhum downloader
  escrito"

**Nada mais foi alterado no catálogo**: a Representação A
(`RAW_NATIVE_ENSEMBLE`) continua `POC_READY_DOCUMENTED_LEGACY`; a rota
`CCSR_BETA` continua `DISCOVERY_REQUIRED`; nenhum dos outros 6 sistemas
candidatos (CanESM5, GEM5.2_NEMO, GFDL_SPEAR, NCAR_CCSM4, NCAR_CESM1,
GEOS5v2) foi tocado; `SistemaNMME.data_access_status` do próprio CFSv2
**não** foi alterado (continua `POC_READY_DOCUMENTED`) — ver "Decisões
que precisam de aprovação" no resumo final desta tarefa sobre esse
ponto específico.

Um ajuste necessário e de baixo risco acompanhou a mudança: a função
`nmme_download.ordem_tentativa_member_level` comparava o status da rota
por igualdade exata (`== ROUTE_STATUS_POC_READY_DOCUMENTED_LEGACY`);
sem generalizar essa comparação para aceitar também
`EMPIRICALLY_CONFIRMED`, a rota recém-promovida deixaria de ser
selecionada pelo pipeline (regressão silenciosa). Corrigido com uma
allowlist explícita dos dois status considerados "prontos" — nunca
`!= DISCOVERY_REQUIRED` genérico, para não aceitar por acidente um
status futuro ainda não revisado.

## Verificação

- Suíte de testes completa: `python -m unittest discover tests -v`
- `python scripts/verificar_dashboard.py`
- Ambos rodados **depois** da atualização do catálogo, nesta mesma
  tarefa (resultados no relatório final da tarefa/mensagem de
  encerramento, não duplicados aqui).
