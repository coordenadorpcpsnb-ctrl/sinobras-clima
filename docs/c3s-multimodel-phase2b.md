# Fase 2B.1 — infraestrutura multi-modelo C3S

## Objetivo

Construir e validar a infraestrutura necessária para comparar múltiplos
sistemas sazonais C3S (ECMWF SEAS5, Météo-France System8, DWD GCFS2.1,
CMCC SPS3.5) sob o **mesmo protocolo científico** já validado e congelado
na Fase 2A.3 (CHIRPS, climatologia leakage-safe, additive mean bias
correction, `MIN_ANOS_TREINO=10`, métricas determinísticas/
probabilísticas, bootstrap).

**Esta fase NÃO executa o hindcast multi-modelo completo nem avalia
skill.** Entrega: catálogo auditável, matriz de compatibilidade, período
comum de hindcast, infraestrutura de combinação multi-modelo (equal
model weighting), um POC real pequeno (6 origens) para provar que
download/parsing/normalização funcionam para os 4 sistemas, testes, e
artifacts de diagnóstico. Ver `scripts/c3s_multimodel_catalogo.py`,
`scripts/c3s_multimodel.py`, `scripts/c3s_multimodel_poc.py`.

## Sistemas

| Centro | Sistema | `system` (CDS) | Hindcast nativo | Hindcast avaliação (comum) | Membros hindcast | Membros forecast | Leads |
|---|---|---|---|---|---|---|---|
| ECMWF | SEAS5 | 51 | 1981–2016 | 1993–2016 | 25 | 51 | 1–6 |
| Météo-France | System8 | 8 | 1993–2018 | 1993–2016 | 25 | 51 | 1–6 |
| DWD | GCFS2.1 | 21 | não atribuível (assimétrico por mês — ver abaixo) | 1993–2016 | 30 | 50 | 1–6 |
| CMCC | SPS3.5 | 35 | 1993–2016 | 1993–2016 | 40 | 50 | 1–6 |

Todos os quatro têm hindcast **fixed** (pré-computado, mesmo conjunto de
anos para qualquer execução — nunca on-the-fly/lagged) e specs
cross-confirmadas por 2+ fontes independentes nesta sessão (ver
`fontes`/`notas` de cada entrada em `c3s_multimodel_catalogo.py`).

Os quatro `system` codes acima (51/8/21/35) estão confirmados pela
documentação oficial: SEAS5 (51) e GCFS2.1 (21) por fontes ECMWF/DWD
diretas; SPS3.5 (35) pela documentação técnica oficial da CMCC (TN0288);
System8 (8) pela documentação oficial C3S "Description of the C3S
seasonal multi-system" (confluence.ecmwf.int/spaces/CKB/pages/77213502/
Description+of+the+C3S+seasonal+multi-system, ou a página atual
equivalente) — fonte apontada por revisão externa; WebFetch direto a
essa URL segue bloqueado nesta sessão (mesma limitação de rede de todo o
catálogo, ver `c3s_multimodel_catalogo.py`), então essa confirmação
específica não foi refeita de primeira mão aqui, e o módulo registra
essa ressalva explicitamente junto à fonte.

### Hindcast NATIVO vs. hindcast de AVALIAÇÃO — dois conceitos distintos

`c3s_multimodel_catalogo.py` separa os dois no dataclass
`SistemaMultiModelo` (e nas colunas do CSV/JSON gerados):

- **`native_hindcast_start`/`native_hindcast_end`** — o período de
  reforecast documentado pela fonte OFICIAL do próprio centro, que pode
  ser mais longo que o período usado na comparação. `None` quando não é
  possível atribuir um único período com confiança (ex.: **DWD GCFS2.1**
  — a própria DWD documenta cobertura DIFERENTE por mês de
  inicialização, 1982–2019 para fev/mai/ago/nov e 1990–2019 para os
  demais; um único par de anos resumiria mal essa assimetria, então o
  campo fica `None` em vez de inventado, com a assimetria completa
  explicada em `notas`).
- **`evaluation_hindcast_start`/`evaluation_hindcast_end`** — o período
  retrospectivo COMUM servido/usado pelo produto C3S multi-sistema para
  comparação homogênea entre os 4 candidatos: **1993–2016** para todos.

Para a maioria dos sistemas os dois períodos DIFEREM (ex.: SEAS5 nativo
1981–2016 vs. avaliação 1993–2016). A exceção é a **CMCC SPS3.5**, cuja
fonte oficial (TN0288) documenta o hindcast nativo como o próprio
intervalo 1993–2016 — não há reforecast mais longo publicado para esse
sistema, então `native_hindcast_*` == `evaluation_hindcast_*` nesse caso
específico, não por coincidência de cálculo.

`periodo_comum_hindcast()` **sempre** calcula a partir dos campos
`evaluation_hindcast_*`, nunca dos `native_hindcast_*` — testado
explicitamente (`tests/test_c3s_multimodel_catalogo.py`,
`test_native_hindcast_start_nunca_influencia_o_periodo_comum` e
`test_real_ecmwf_native_1981_evaluation_1993_confirma_a_distincao`).

### Por que essas versões, e não as "atuais" do catálogo CDS

O sistema "atual" listado hoje no catálogo CDS para METFR/DWD/CMCC é
System9/GCFS2.2/SPS4, respectivamente — todos introduzidos muito
recentemente (2025/2026 segundo a busca feita nesta sessão) e sem specs
de membros/leads/resolução cross-confirmáveis. A CMCC documenta
explicitamente, sobre o SPS4: *"decisions on CMCC SPS4 forecast system
are still pending, with details to be communicated"*. Por isso os 4
candidatos desta fase usam a versão ANTERIOR de cada sistema
(System8/GCFS2.1/SPS3.5), que tem hindcast, membros e leads documentados
pela fonte oficial do próprio centro. Isso é controle de escopo/
documentação (Seção 1 — nunca skill), não rejeição científica; as
versões atuais ficam registradas em `NAO_INCLUIDOS_VERSAO` para
reavaliação quando a infraestrutura permitir confirmar suas specs (ex.:
request mínimo real ao CDS).

### Sistemas fora de escopo nesta fase

- **UKMO** — hindcast com esquema operacional/on-the-fly e
  inicializações particulares (lagged ensemble), incompatível com o
  protocolo "hindcast fixo" reutilizado sem adaptação adicional. Será
  avaliado depois que a infraestrutura multi-modelo fixa estiver
  validada.
- **NCEP, ECCC, BOM, JMA** — fora de escopo por controle de escopo desta
  fase, não por rejeição científica.

## Período comum de hindcast

`c3s_multimodel_catalogo.py::periodo_comum_hindcast(sistemas)` calcula a
interseção de `evaluation_hindcast_start`/`evaluation_hindcast_end` de
cada sistema — **nunca fixado manualmente, e nunca a partir dos campos
`native_hindcast_*`** (ver seção acima). Para os 4 candidatos desta
fase, a interseção calculada é **1993–2016** (confirmado por 2 fontes
independentes: a descrição geral do produto C3S multi-sistema, e a
tabela de sistemas do NOAA PSL — ambas dizem que esse é o período de
referência comum "for all providers" desde novembro/2018).

## Equal-model weighting

Cada sistema pode ter um número de membros diferente (25/25/30/40 nos
quatro candidatos). **Nunca concatenamos os membros de sistemas
diferentes** num ensemble único — isso daria peso maior aos sistemas com
mais membros.

Regra (`scripts/c3s_multimodel.py`):
1. Para cada `(init_date, lead, modelo)`, calcula-se a estatística do
   modelo isoladamente — ensemble mean RAW/BC, probabilidades RAW/BC
   pelos mesmos tercis leakage-safe da Fase 2A.3.
2. **Só depois** os resultados por modelo são combinados por **média
   simples entre modelos** — peso `1/N_modelos`, independente de quantos
   membros cada um tinha internamente.

Exemplo mínimo (também coberto por teste, `tests/test_c3s_multimodel.py`):
modelo A com 25 membros e ensemble mean 100, modelo B com 30 membros e
ensemble mean 200 → `MME = 150`, nunca a média ponderada pelos 55
membros totais.

Probabilidades seguem o mesmo princípio: `MME_P_below/normal/above` é a
média das probabilidades (já calculadas por modelo) — nunca uma mistura
de membros de sistemas diferentes. Toda tripla de probabilidade
(entrada de cada modelo e saída do MME) é validada para somar 1 dentro
de tolerância numérica.

**Modelo ausente bloqueia o MME**: se algum modelo configurado para uma
comparação não tiver dado disponível para uma combinação
`(init_date, lead)`, essa linha do MME vem marcada
`model_set_status=INCOMPLETE_MODEL_SET` (não calcula um MME parcial
silenciosamente). Um sistema só sai do conjunto "configurado" por
decisão formal no catálogo, nunca implicitamente em tempo de execução.

**O que esta fase explicitamente NÃO faz** (Seção 26): ranquear modelos,
escolher vencedor, descartar modelo por RMSE local, pesos por skill,
otimização de pesos, ML, stacking, Bayesian model averaging. O primeiro
baseline é sempre equal weighting.

## Definição do POC

Origens fixas: `1995-01, 1995-07, 2005-01, 2005-07, 2015-01, 2015-07`
(3 décadas × 2 estações, jan/jul) — todos os 4 modelos incluídos, leads
1–6. **O objetivo não é medir skill** — é verificar download, schemas,
nº de membros, unidade, mapeamento temporal (lead 1 = mês nominal da
inicialização, provado por sistema via `extrair_mapeamento_temporal_grib`
— eccodes, arquivo GRIB inteiro, falha explícita se algum sistema tiver
semântica diferente), grade (distância do ponto pedido ao ponto de
grade selecionado, registrada mas não exigida igual entre sistemas) e a
combinação multi-modelo. **O resultado do POC não é conclusão
científica** — com só 6 origens isoladas, raramente há histórico prévio
suficiente para calibrar bias (o mesmo padrão já observado no primeiro
pilot isolado da Fase 2A.3); BC/probabilidades podem ficar
`SEM_HISTORICO_SUFICIENTE`/`NaN`, e isso é esperado, não um bug.

## O que é reaproveitado da Fase 2A.3 (metodologia congelada)

- CHIRPS como única fonte observacional, cobertura derivada de
  `min(target_month)`→`max(target_month)` das origens×leads pedidas
  (`c3s_hindcast_completo.py::intervalo_targets_necessario`/
  `buscar_chirps_consolidado`, sem reimplementar).
- Climatologia leakage-safe: `target_month < origem corrente`
  (`c3s_calibracao.py::climatologia_leakage_safe`, inalterada).
- Bias additive mean, predicado estrito: `candidate.init_date < origem`
  **e** `candidate.target_month < origem`, observação finita e
  disponível (`c3s_calibracao.py::bias_leakage_safe`, correção da
  auditoria científica final da Fase 2A.3).
- `MIN_ANOS_TREINO=10`, correção membro a membro
  (`aplicar_bias_a_membro`), probabilidades por tercis
  (`c3s_hindcast.py::probabilidade_terciles`).
- RMSE/MAE/Bias/correlação/MSESS/RMSESS/Brier/BSS/RPS/RPSS/CRPS,
  bootstrap 2.000 réplicas seed 42 (`c3s_skill.py`/`c3s_hindcast.py`,
  reservados para quando a Fase 2B avaliar skill de verdade — não usados
  no POC de infraestrutura desta entrega).
- Auditoria de leakage.

## Outputs (`artifacts/c3s_multimodel_poc/`)

`c3s_multimodel_catalog.csv`, `c3s_multimodel_common_period.json`
(gerados até pelo dry-run — não dependem do CDS), e, só depois de um
POC real: `c3s_multimodel_raw.csv`, `c3s_multimodel_summary.csv`,
`c3s_multimodel_mme.csv`, `c3s_multimodel_temporal_audit.csv`,
`metadata.json`, `RELATORIO.md`.

## Como rodar

```bash
# Dry-run (default seguro) — nunca acessa o CDS, mostra catálogo/plano
python scripts/c3s_multimodel_poc.py --dry-run-plan

# POC real (6 origens x 4 modelos) — exige CDS_API_KEY configurado
python scripts/c3s_multimodel_poc.py --executar-poc-real
```

Workflow (`.github/workflows/c3s_multimodel_poc.yml`, manual, sem cron):
default `dry_run_plan=true`/`executar_poc_real=false` — clicar "Run
workflow" sem mexer em nada nunca acessa o CDS. Rodar o POC real exige
`dry_run_plan=false`, `executar_poc_real=true` e
`confirm_poc_real=EXECUTAR_POC_MULTIMODEL` (texto exato) — sem isso, o
job falha antes de instalar qualquer dependência.

## O que NÃO pode ser concluído a partir do POC

- **Nenhuma comparação de skill entre sistemas.** Seis origens isoladas
  não constroem histórico suficiente para bias/climatologia
  leakage-safe na maioria dos casos — o mesmo problema já identificado e
  corrigido para o pilot isolado da Fase 2A.3 (run 35260471652), aqui
  deliberadamente aceito porque o POC não tem esse objetivo.
- **Nenhuma promoção de sistema ou do MME para produção.** Nenhum
  resultado desta fase entra no dashboard operacional
  (`update_dashboard.py`, `docs/index.html`, `data/bh_final.json`) —
  ainda estamos validando infraestrutura, não decidindo o modelo
  operacional.
- **Nenhuma conclusão sobre a semântica temporal ou de membros dos
  sistemas além do que o parser efetivamente validou.** Specs de
  resolução para DWD/CMCC e `model_id` para ECMWF/CMCC não foram
  cross-confirmados nesta sessão (campos `None` no catálogo) — só o que
  está marcado `verificado_cruzado=True` com fontes tem essa garantia.
- **Nenhuma conclusão sobre a assimetria de cobertura por mês de
  inicialização da DWD** (hindcast nativo documentado como 1982–2019 em
  fev/mai/ago/nov vs. 1990–2019 nos demais meses) além de que o período
  comum 1993–2016 usado aqui está contido nos dois casos — a validação
  completa dessa assimetria fica para uma fase futura com acesso real ao
  CDS.

## Fontes C3S consultadas

- **C3S Summary of available data** — descrição geral do produto
  multi-sistema sazonal, incluindo o período de referência comum
  1993–2016 "for all providers" desde novembro/2018.
- **C3S Description of the seasonal multi-system** (ECMWF Confluence
  Knowledge Base) — descrição de como os sistemas individuais compõem o
  produto multi-sistema.
- NOAA PSL — `psl.noaa.gov/forecasts/s2s_C3S_monthly_to_seasonal/description/`
  (tabela de sistemas/códigos, período de hindcast comum).
- IRI/LDEO Columbia — mirror de metadados do catálogo CDS C3S
  (`iridl.ldeo.columbia.edu/SOURCES/.EU/.Copernicus/.CDS/.C3S/`), usado
  para confirmar resolução/leads/membros de Météo-France System8.
- Documentação oficial de cada centro: Météo-France (`umr-cnrm.fr`,
  Zenodo), DWD (`dwd.de`, EGU/AGU), CMCC (`cmcc.it`, TN0288).

URLs completas e o texto exato encontrado ficam registrados em
`fontes`/`notas` de cada `SistemaMultiModelo` em
`scripts/c3s_multimodel_catalogo.py` — não duplicados aqui para evitar
desatualização.
