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

**Revisão pontual** — a primeira versão deste documento/módulo
classificava cada combinação num único rótulo `OBSERVACAO_CONFIRMADA`,
que superclamava verificação nunca feita: um mês com `fonte` vazia
virava "confirmado" só por não ter uma tag de fallback, sem checar se o
valor numérico existia, se não havia duplicata na série, ou se o valor
era fisicamente plausível. `nmme_piloto_historico.
verificar_cobertura_observacional` agora separa **3 conceitos
independentes** por combinação (origem, lead) → mês-alvo, nunca
colapsados num único "confirmado":

| Conceito | Coluna | O que verifica |
|---|---|---|
| Disponibilidade | `disponibilidade` | O mês-alvo tem QUALQUER registro na série (`PRESENTE`/`AUSENTE`) |
| Procedência documental | `procedencia_documental` | De onde o registro vem, segundo README.md/fetch_monthly_data.py (MERRA-2, Estação Sinobras, CHIRPS Final, CHC Preliminary, ERA5) — descrição, nunca afirmação de qualidade |
| Qualidade efetivamente verificada | `qualidade_verificada_status` | Checagens COMPUTADAS: `VALOR_AUSENTE` (NaN), `REGISTRO_DUPLICADO` (mesmo ano/mês 2+ vezes na série), `VALOR_FISICAMENTE_IMPLAUSIVEL` (fora de [0, 1.500] mm/mês, limite reaproveitado de `scripts/c3s_poc.py`) — `OK` quando nenhuma dispara |

Adicionalmente, `fonte_e_substituta_nao_usar` preserva o guardrail já
existente: `True` para `fonte` em `{CHC-Preliminar, OpenMeteo-ERA5}` —
preliminar/estimado (CLAUDE.md, armadilha 6), nunca usável como
observação real mesmo estando disponível e sem flag de qualidade.

**Resultado empírico** (verificado nesta tarefa, `tests/
test_nmme_piloto_historico.py::RealSerieObservacionalTestCase`, rodando
contra o arquivo real, para as 96 combinações do piloto):
- **Disponibilidade**: 96/96 `PRESENTE` (nenhum mês ausente).
- **Procedência documental**: 24/96 `MERRA-2` (as 4 combinações×6 leads
  de origens em 1991) e 72/96 `Estação Sinobras` (1998/2005/2010).
- **Substituído/estimado**: 0/96 (nenhuma combinação usa CHC-Preliminar/
  OpenMeteo-ERA5).
- **Qualidade verificada**: 96/96 `OK` (nenhum NaN, duplicata ou valor
  implausível encontrado nos dados reais).

Isso é esperado: o período do piloto (1991-2010) está inteiramente
dentro do baseline histórico original (1981-2025), que não depende da
cascata de fallback recente — só os meses mais novos (2026) usam
CHIRPS/CHC-Preliminar/ERA5. **Isso NÃO significa que a referência está
"100% confirmada" ou pronta para avaliação científica** — mesmo com
disponibilidade/qualidade limpas, a aptidão para cálculo de skill
(`avaliar_aptidao_referencia_observacional`) continua bloqueada pelo
desalinhamento espacial descrito abaixo (bloqueio estrutural, sempre
presente nesta revisão).

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

**Isso não bloqueia a aprovação de INFRAESTRUTURA do piloto**
(`avaliar_aprovacao_piloto` — acesso/seleção temporal/membros/
horizontes/RAW, nunca depende da série observacional) — mas bloqueia
estruturalmente a **aptidão da referência observacional para avaliação
científica** (`avaliar_aptidao_referencia_observacional`, veredito
SEPARADO — Seção 3, revisão pontual). Enquanto essa correspondência
espacial não for resolvida por decisão explícita, essa função **sempre**
devolve `apto_para_avaliacao_cientifica=False`, mesmo com
disponibilidade/procedência/qualidade 100% limpas — qualquer RMSE/RPSS
calculado no futuro estaria medindo, em parte, esse desalinhamento
espacial, não só a habilidade preditiva do CFSv2 (Fase 2C.2 completa,
Seção F da especificação).

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
registrado aqui para decisão consciente. Até essa decisão,
`avaliar_aptidao_referencia_observacional` continua reportando esse
bloqueio explicitamente a cada execução do piloto, nunca silenciado.
