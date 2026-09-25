# Fase 2C.2 — procedência e cobertura observacional do piloto histórico CFSv2

## Objetivo

Verificar a procedência real dos dados históricos usados como
observação de referência para o piloto de 16 inicializações,
distinguindo explicitamente dados confirmados de valores substituídos/
estimados (Seção 3 da tarefa), e verificar a correspondência espacial
entre essa referência e o ponto de grade usado pelo CFSv2. Este
documento é gerado a partir de leitura **local** de `data/serie_subst.csv`
(sem rede) e do código-fonte de `scripts/fetch_monthly_data.py` —
nenhum dado foi inventado ou assumido sem checar o arquivo/código real.

## Achado principal — a série de referência NÃO é CHIRPS para o período do piloto

`README.md` descreve `data/serie_subst.csv` como: **"Série histórica
(MERRA-2 1981-1995 + Sinobras 1996-hoje)"**. Isso foi confirmado
diretamente no arquivo: das 548 linhas da série, só **8** têm a coluna
`fonte` preenchida (`CHIRPS` ×7, `CHC-Preliminar` ×1), e **todas** as 8
são de **2026** (jan-ago/2026) — os meses mais recentes, preenchidos
pela cascata de `fetch_monthly_data.py` (CHIRPS Final → CHC Preliminary
→ Open-Meteo ERA5-Land) introduzida depois que a série de base já
existia. As **540 linhas restantes (1981-2025)** têm `fonte` vazia —
não são CHIRPS, são o baseline histórico original:

- **1981–1995**: reanálise **MERRA-2** (NASA) — não é observação
  in situ nem satélite de precipitação dedicado (CHIRPS), é um produto
  de reanálise atmosférica.
- **1996–2025**: leituras das **estações da própria Sinobras** — dado
  de campo direto (pluviômetros da empresa), não derivado de satélite.

**Nenhuma das 16 origens do piloto (1991, 1998, 2005, 2010) usa
CHIRPS como referência** — 1991 usa MERRA-2; 1998/2005/2010 usam a
estação Sinobras. Isso é uma correção necessária de terminologia: nos
documentos anteriores desta fase (`docs/nmme-fase2c2-especificacao.md`),
a observação de referência foi chamada genericamente de "CHIRPS" por
seguir a nomenclatura predominante do resto do projeto — o nome correto
para o período 1991-2010 é "a série histórica de produção
(MERRA-2/Sinobras)", não CHIRPS. `scripts/nmme_piloto_historico.py`
usa esse nome mais preciso na documentação do código.

## Classificação de cobertura das 16×6 = 96 combinações origem×lead

`nmme_piloto_historico.verificar_cobertura_observacional` classifica
cada combinação (origem, lead) → mês-alvo em 3 categorias:

| Classificação | Critério | Uso permitido como observação real |
|---|---|---|
| `OBSERVACAO_CONFIRMADA` | mês presente, `fonte` vazia (baseline MERRA-2/Sinobras) OU `fonte='CHIRPS'` (CHIRPS Final) | Sim |
| `VALOR_SUBSTITUIDO_NAO_USAR` | mês presente, mas `fonte` em `{CHC-Preliminar, OpenMeteo-ERA5}` — preliminar/estimado (CLAUDE.md, armadilha 6) | **Não** — a tarefa pede explicitamente para nunca tratar como observação real |
| `MES_AUSENTE` | mês-alvo não está na série | Não (sem dado) |

**Resultado empírico** (verificado nesta tarefa, `tests/
test_nmme_piloto_historico.py::RealSerieObservacionalTestCase`, rodando
contra o arquivo real): as **96/96** combinações origem×lead do piloto
estão `OBSERVACAO_CONFIRMADA` — nenhum mês ausente, nenhum valor
substituído/estimado. A cobertura observacional do piloto é **100%**,
acima do critério mínimo de 90% já definido em
`docs/nmme-fase2c2-especificacao.md` (Seção G).

Isso é esperado: o período do piloto (1991-2010) está inteiramente
dentro do baseline histórico original (1981-2025), que não depende da
cascata de fallback recente — só os meses mais novos (2026) usam
CHIRPS/CHC-Preliminar/ERA5.

## Correspondência espacial — achado de um desalinhamento pré-existente

A tarefa pede para "verificar também a correspondência espacial entre
a referência observacional e a grade do CFSv2". Verificado:

- **Referência observacional** (`data/serie_subst.csv`): representa o
  **centroide das fazendas** — `FAZENDAS_LAT, FAZENDAS_LON = -7.80,
  -47.95` (`scripts/_chirps.py`/`scripts/_openmeteo.py`).
- **Ponto usado pelo CFSv2** (POC de infraestrutura e piloto): **São
  Bento do Tocantins** — `lat=-6.0203, lon=-47.9022`
  (`scripts/_c3s_utils.py::MUNICIPIOS`), herdado das fases C3S
  ("mesma localização das Fases C3S", comentário em
  `scripts/nmme_processar.py:25`).
- **Distância entre os dois pontos**: **198,0 km**
  (`nmme_piloto_historico.distancia_fazendas_ate_municipio_km()`,
  reaproveitando `nmme_processar.distancia_km_aprox` — a mesma função
  já usada para `grid_distance_km` no RAW do POC, nunca uma fórmula
  nova).

**Isso não é um problema introduzido por esta tarefa** — é uma
característica herdada de toda a infraestrutura C3S/NMME desde a Fase
2A (nenhum documento revisado nesta sessão explica por que São Bento
foi escolhido em vez do centroide das fazendas). Para uma variável com
forte variabilidade convectiva local (CLAUDE.md, armadilha 7: "chuva
convectiva rara e isolada"), 198 km é uma distância grande o bastante
para que a previsão do CFSv2 em São Bento e a observação da série de
produção (fazendas) possam divergir por razões puramente espaciais,
não de habilidade do modelo.

**Isso não bloqueia o piloto de infraestrutura** (o piloto só verifica
acesso/parsing/guardrails, nunca skill) — mas é uma limitação que
precisa estar explícita em qualquer avaliação científica futura
(Fase 2C.2 completa, Seção F da especificação): qualquer RMSE/RPSS
calculado estará medindo, em parte, esse desalinhamento espacial, não
só a habilidade preditiva do CFSv2.

## Decisão que precisa de aprovação

Esse desalinhamento espacial (198 km) já existe nas comparações C3S/
SEAS5 anteriores (mesmo ponto São Bento do Tocantins, mesma série de
referência `data/serie_subst.csv`) — então ele não muda a
comparabilidade entre CFSv2 e SEAS5/C3S MME pedida na Seção 4 da
tarefa (todos usam a mesma referência com o mesmo desalinhamento,
comparação ainda like-for-like). A decisão em aberto é se vale a pena,
numa fase futura, buscar uma referência observacional mais próxima do
ponto usado pelo CFSv2/C3S (ou mudar o ponto de avaliação do CFSv2/C3S
para o centroide das fazendas) — fora do escopo desta tarefa, só
registrado aqui para decisão consciente.
