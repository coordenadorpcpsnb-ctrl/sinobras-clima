#!/usr/bin/env python3
"""
nmme_catalogo.py — Fase 2C.1: catálogo auditável dos sistemas
candidatos ao North American Multi-Model Ensemble (NMME), fonte
dinâmica sazonal INDEPENDENTE do C3S (Fase 2B).

PERGUNTA CIENTÍFICA DA FASE 2C (Seção 1 do objetivo): a baixa
previsibilidade observada na Fase 2B.2 — set-fev, H2-H6, probabilidades
— é limitação específica do C3S ou característica mais geral da
previsibilidade sazonal de precipitação em São Bento do Tocantins?
Responder isso exige uma fonte GENUINAMENTE independente — daí a
exclusão deliberada do ECMWF (Seção 5) mesmo que apareça em alguma
configuração NMME3: ECMWF já é a espinha dorsal do C3S validado nas
Fases 2A-2B, incluí-lo aqui invalidaria a independência que a Fase 2C
busca.

PRINCÍPIO FUNDAMENTAL (Seção 1): nenhum SARIMAX/XGBoost/regressora
ONI-N34/otimização retrospectiva/peso local/seleção de modelo por skill
local. Esta fase é validação independente de previsão DINÂMICA, não
mais um ajuste estatístico.

═══════════════════════════════════════════════════════════════════════
RODADA 1 DE INVESTIGAÇÃO (sessão original da Fase 2C.1)
═══════════════════════════════════════════════════════════════════════

Restrição de rede: `www.cpc.ncep.noaa.gov` respondeu (páginas HTML
gerais), mas NENHUMA das páginas alcançadas continha a tabela atual de
modelos/membros/período. Bloqueados para WebFetch direto:
`ftp.cpc.ncep.noaa.gov`, `iridl.ldeo.columbia.edu`, `www.gfdl.noaa.gov`,
`www.weather.gov`, `wpo.noaa.gov`, `eccc-msc.github.io`,
`climate-scenarios.canada.ca`, `agupubs.onlinelibrary.wiley.com`,
`doi.org`, `climatetoolbox.org`.

Achados citáveis, por fonte (todos via WebSearch, exceto o item 1, que
foi um PDF baixado e lido de primeira mão):

1. **Emerson LaJoie (CPC), CDPW nº47, out/2022** — slide 4: "CFSv2 24
   members / GEM_NEMO 10 members / CanCM4i 10 members / GFDL_FLOR 24
   members / NASA_GEOS5v2 4 members / NCAR_CCSM4 10 members" — geração
   ANTERIOR (pré-troca CanCM4i→CanESM5 etc.), mas CFSv2 e NASA_GEOS5v2
   não foram trocados de versão, e os valores de membros coincidem com
   os confirmados na Rodada 2 (ver abaixo).
2. climatetoolbox.org (snippet): troca de geração CanCM4i→CanESM5,
   GEM5-NEMO→GEM5.2-NEMO, adição de SPEAR/CESM1.
3. climate-scenarios.canada.ca/CanSIPS (snippet, ECCC): "CanSIPSv3 uses
   a 30-year seasonal hindcast with 20 ensemble members for each model
   ... from 1991 to 2020" — CanESM5/GEM5.2-NEMO.
4. IRIDL (título indexado): "GFDL-SPEAR HINDCAST 1991-2020 Monthly", 15
   membros, entrou no NMME em 06/fev/2021.
5. "Initialized Seasonal Prediction with the NCAR Models in NMME",
   Weather and Forecasting v.40 n.6 (2025): período comum do TRIO
   CCSM3/CCSM4/CESM1 = 1991-2018 (não CCSM4/CESM1 isoladamente).
6. IRIDL — paths de catálogo indexados: `.Models/.NMME/.GFDL-SPEAR/
   .HINDCAST/.MONTHLY/`, `.Models/.NMME/.NCAR-CESM1/.HINDCAST/.MONTHLY/`,
   `.Models/.NMME/.CanSIPS-IC3/.GEM5-NEMO/.HINDCAST/.MONTHLY/.sst` (nota
   grafia "GEM5-NEMO" sem ".2", distinta da documentação textual).

═══════════════════════════════════════════════════════════════════════
RODADA 2 DE INVESTIGAÇÃO (revisão de auditabilidade pré-PR) — nova
evidência trazida por revisão externa + verificação desta sessão
═══════════════════════════════════════════════════════════════════════

A revisão externa apontou o **NOAA CPC NMME3 Operational User Manual**
(`ftp.cpc.ncep.noaa.gov/CPC/ID/figs/USER_MANUAL.html`) como fonte
oficial documentando, para os 7 candidatos, hindcast 1991-2020 e os
mesmos números de membros já reunidos na Rodada 1 (CFSv2=24,
CanESM5=20, GEM5.2_NEMO=20, GFDL_SPEAR=15, NCAR_CCSM4=10, NCAR_CESM1=10,
NASA_GEOS5v2=4), além de documentar `prate` como a variável conceitual
de precipitação do produto NMME3 (unidades `mm/day` ou `kg m-2 s-1`).

**Tentativa de verificação nesta sessão**: `ftp.cpc.ncep.noaa.gov`
permanece BLOQUEADO para WebFetch direto (mesmo bloqueio da Rodada 1,
confirmado de novo por tentativa direta) — não foi possível abrir a URL
e ler o manual de primeira mão. Uma busca independente (WebSearch) por
"NMME3 Operational User Manual" não encontrou esse documento específico
nem confirmação textual adicional dele; encontrou, em vez disso, um uso
DIFERENTE e mais antigo do termo "NMME3" num documento CPC distinto
("NMME Review for 2020"): "NMME3, operating from 2014–2019, has seven
models including CFSv2, GEOS5, CM2.1, CanCM3, CanCM4, CM2.5-FLOR, and
CCSM4" — uma configuração de modelos completamente diferente da que a
revisão externa descreve. Essa ambiguidade de nomenclatura ("NMME3"
usado para duas gerações de modelos diferentes em documentos CPC
distintos) fica registrada aqui, não resolvida.

Apesar disso, os valores numéricos citados pela revisão externa
(membros por modelo) são EXATAMENTE os já reunidos independentemente na
Rodada 1 via LaJoie (CPC, fonte primária lida diretamente) — não há
contradição de valores, só a impossibilidade de abrir a URL específica
citada e uma ambiguidade de nomenclatura documental. Por isso os campos
`hindcast_start`/`hindcast_end`/`hindcast_members`/`precip_variable`
(conceitual) sobem para `DOCUMENTED` nesta rodada — nunca
`EMPIRICALLY_CONFIRMED` (nenhum arquivo de hindcast foi aberto).

Outros achados da Rodada 2 (todos via WebSearch, nenhum WebFetch direto
bem-sucedido a domínios novos):

- **Conjunto operacional "core" desde 08/jun/2025** (página "About
  NMME", citada pela revisão externa; corroborada por um WebSearch
  independente desta sessão que devolveu a mesma lista de 6 modelos):
  CFSv2, CanESM5, GEM5.2-NEMO, NCAR-CESM1, NCAR-CCSM4, NASA-GEOS-S2S-2
  — sem GFDL_SPEAR, e com "NASA-GEOS-S2S-2" no lugar de "NASA_GEOS5v2".
  O MESMO WebSearch também encontrou outra página CPC (produtos de
  monitoramento) listando 7 modelos INCLUINDO GFDL_SPEAR e
  NASA_GEOS5v2 (nomenclatura antiga) — confirmando que páginas CPC
  diferentes, nesta mesma época, descrevem conjuntos operacionais
  distintos. Isso é tratado aqui como fato registrado, NUNCA resolvido
  por inferência (Seção 3): `current_operational_name` fica com o nome
  citado pela página "About NMME" quando existe, e uma nota explícita
  quando páginas conflitam.
- **Diretório CPC FTP para hindcast em formato CPT**
  (`ftp.cpc.ncep.noaa.gov/International/nmme/monthly_nmme_hindcast_in_cpt_format/`,
  citado pela revisão externa com o padrão de nome de arquivo
  `cfsv2_precip_hcst_...`) — BLOQUEADO para WebFetch direto nesta
  sessão (mesmo domínio). O padrão de nome de arquivo citado (com
  "precip" explícito) é uma pista útil para uma rota CPC oficial
  prioritária (Seção 6), mas nenhuma listagem de diretório foi aberta
  de primeira mão — registrado como candidato de rota, não como
  endpoint confirmado.
- **IRI CanSIPS-IC3 FORECAST MONTHLY** (estrutura, não hindcast): um
  WebSearch desta sessão encontrou evidência estrutural de que o
  produto FORECAST do CanSIPS-IC3 usa variável `prec`, dimensões
  X/Y/L/M/S (convenção "ingrid" padrão), 20 membros, leads mensais,
  grade 1°. Isso é evidência da FAMÍLIA de modelo (CanESM5/GEM5.2-NEMO
  seguem a mesma convenção estrutural), mas — seguindo a instrução
  explícita da revisão — NUNCA assumido como o mesmo endpoint do
  HINDCAST: o path HINDCAST específico continua sem confirmação, e o
  único path HINDCAST realmente indexado para esta família
  (`.CanSIPS-IC3/.GEM5-NEMO/.HINDCAST/.MONTHLY/.sst`) mostra a variável
  `sst`, não `prec` — reforçando que a variável de um produto não pode
  ser assumida para outro sem confirmação própria.

Nenhum arquivo de dado (NetCDF/GRIB) foi baixado em nenhuma das duas
rodadas — só páginas/documentos de texto, dentro do que a tarefa
permite.

═══════════════════════════════════════════════════════════════════════
RODADA 3 DE INVESTIGAÇÃO (tentativa de tornar CFSv2 executável via rota
CPC/CPT) — ver scripts/nmme_cpc_cpt.py para o relato completo
═══════════════════════════════════════════════════════════════════════

`ftp.cpc.ncep.noaa.gov` continua BLOQUEADO (confirmado de novo — diretório,
readme e um arquivo específico, todos EGRESS_BLOCKED). Nenhum byte de um
arquivo real `cfsv2_precip_hcst_..._MENSAL` foi lido. Dois achados reais
mudam a base de evidência do CFSv2, ambos obtidos fora do domínio bloqueado:

1. Padrão de nome de arquivo da rota `monthly_nmme_hindcast_in_cpt_format/`
   corroborado por múltiplas buscas independentes devolvendo URLs reais
   indexadas (não paráfrase) — `{modelo}_{variavel}_hcst_{MesAbrev}ic_
   {n}_{ano}.txt`, `n`/`ano` singulares (família MENSAL, distinta da
   família SAZONAL do diretório irmão, que usa faixas).
2. O formato CPT v10 em si foi EMPIRICAMENTE confirmado: o parser oficial
   da IRI (`github.com/iri-pycpt/pycpt`, `cpt-io/src/cptio/fileio/cpt.py`)
   foi lido de primeira mão via `raw.githubusercontent.com` (não
   bloqueado), e uma fixture de teste real do mesmo pacote — um hindcast
   NMME genuíno em CPT v10 (CanCM4i, produto SAZONAL, não CFSv2/MENSAL) —
   também foi lida de primeira mão. Essa fixture real mostra `cpt:field=
   prec` (nome interno diferente do token "precip" do NOME do arquivo!),
   `cpt:units=mm/day`, grade 1°×1°, `cpt:S`/`cpt:L` explícitos no
   cabeçalho — e **nenhum bloco com `cpt:M=`**, ou seja, ensemble mean
   por T, não por membro, embora o formato-padrão suporte a dimensão M.

Isso é evidência de FAMÍLIA de formato (mesmo raciocínio já aplicado ao
CanSIPS-IC3 FORECAST vs HINDCAST acima), não confirmação do arquivo
CFSv2/MENSAL específico. Por isso `data_access_status` do CFSv2 subiu
para `PARTIAL` nesta rodada (data_url_template agora documentado) mas
NÃO chegou a `CONFIRMED`. `scripts/nmme_cpc_cpt.py` já implementa o
parser CPT v10 e as barreiras necessárias para quando um arquivo real
puder ser aberto.

═══════════════════════════════════════════════════════════════════════
RODADA 4 DE INVESTIGAÇÃO (rota alternativa: IRI Data Library, dataset
member-level) — ver scripts/nmme_download.py e scripts/nmme_processar.py
═══════════════════════════════════════════════════════════════════════

A revisão externa apontou uma rota alternativa, documentada pelo IRI:
`SOURCES/.NOAA/.NCEP/.EMC/.CFSv2/.ENSEMBLE/.FLXF/.surface/.PRATE/` —
POTENCIALMENTE muito mais adequada ao POC por membro do que a rota CPC/
CPT (Rodada 3), porque é o mesmo tipo de estrutura X/Y/L/M/S por
membro já usado nas Fases C3S (`.sel(M=...)`), não um ensemble mean.

`iridl.ldeo.columbia.edu` continua BLOQUEADO nesta sessão (confirmado
de novo). Mas o catálogo da própria IRI é código aberto versionado —
`github.com/iridl/dlentries` (não bloqueado, github). Naveguei até
`entries/NOAA/NCEP/EMC/CFSv2/ENSEMBLE/FLXF/index.tex` e li de primeira
mão (via raw.githubusercontent.com) a definição Ingrid LITERAL deste
dataset exato — é o arquivo-fonte que gera a página que a revisão
externa descreveu, não uma paráfrase. Valores lidos verbatim:

```
S: grid: /name (S) def /calendar /365 def /units (days since 1960-01-01) def
   1981 12 12 ymd2d365c ... 5 ... 2011 3 27 ymd2d365c ... :grid
L: grid: /name /L def /units (months) def   .5 1 9.5 :grid
M: /M 28 NewIntegerGRID
X: grid: /name (X) def /units (degree_east) def   0 360 384. div dup 360 exch sub :grid
Y: 190 gaussianlat high low subgrid
PRATE: surface 0 Zvariable:/name (PRATE) def /long_name (Precipitation Rate) def
       /units (kg m-2 s-1) def :Zvariable
```

Isso é EMPIRICALLY_CONFIRMED para a DEFINIÇÃO DE CATÁLOGO do dataset
(abri e li o arquivo-fonte real) — mas continua **NÃO**
EMPIRICALLY_CONFIRMED para o dado em si (nenhum subset real foi aberto
contra `iridl.ldeo.columbia.edu`, que segue bloqueado). Interpretação:

- **S**: início 12/dez/1981, fim 27/mar/2011, passo "5" — em um
  calendário de 365 dias com unidade "dias", um passo de 5 significa
  inicializações a cada 5 DIAS, não uma por mês. Isso bate com um
  achado independente via WebSearch (não aberto de primeira mão): o
  whitepaper/paper de Yuan et al. (2011) sobre o CFSv2 descreve
  "9-month hindcasts... initiated every 5 days with 4 cycles on those
  days" — corrobora o passo de 5. A descrição textual do nível pai
  (`ENSEMBLE/index.tex`, também lida de primeira mão) diz "hindcasts
  organized as monthly starts of 24-28 members" — **não resolvido**
  como o arquivo nativo a cada 5 dias vira "monthly starts" — é uma
  agregação/pooling que a IRI aplica por cima do arquivo nativo, cujo
  mecanismo exato não foi confirmado nesta sessão. Registrado como
  pendência explícita, não resolvido por inferência.
- **L**: `.5 1 9.5` é sintaxe Ingrid de grade regular (início, passo,
  fim) = 0.5, 1.5, 2.5, ..., 9.5 — 10 valores, EMPIRICALLY_CONFIRMED,
  bate com o que a revisão externa descreveu.
- **M**: `/M 28 NewIntegerGRID` declara um eixo M de TAMANHO FIXO 28 no
  catálogo — não uma faixa "24-28". A faixa 24-28 citada pela revisão
  externa (e por Yuan et al. 2011, que fala em 24 membros para
  1982-2009) pode refletir preenchimento incompleto (menos membros
  reais, resto `missing`) em parte do período, ou uma mudança de
  tamanho ao longo do tempo — não confirmado nesta sessão; por isso o
  código aceita uma FAIXA observada [24,28], nunca um valor único
  hardcoded (Seção 5 da tarefa).
- **X**: 0-360°, 384 pontos → espaçamento 360/384 = 0.9375° —
  EMPIRICALLY_CONFIRMED, convenção 0-360 (não -180/180).
- **Y**: grade GAUSSIANA de 190 pontos, não espaçamento regular
  simples — EMPIRICALLY_CONFIRMED; nunca assumir espaçamento uniforme
  nesta grade.
- **PRATE**: nome interno confirmado "PRATE", `long_name`="Precipitation
  Rate", `units`="kg m-2 s-1" — EMPIRICALLY_CONFIRMED, já uma unidade
  reconhecida por `nmme_processar.UNIDADES_KG_M2_S_ACEITAS`.

**Sobre 1991-2020 vs. o período nativo desta rota (Seção 6 da
tarefa)**: a revisão externa afirmou "hindcasts CFSv2 para 1991-mar/2011;
forecasts arquivados para abr/2011-dez/2020" como o período nativo
homogêneo. A leitura EMPÍRICA desta sessão do S grid mostra o arquivo
nativo cobrindo **dez/1981 a mar/2011** — início diferente do que a
revisão citou (1991), mas o MESMO fim (mar/2011) — convergência entre
duas fontes independentes (a citação da revisão + a leitura empírica
desta sessão) sobre onde o arquivo nativo homogêneo PARA, mesmo com
divergência sobre onde ele COMEÇA. `hindcast_start=1991`/
`hindcast_end=2020` no catálogo continuam representando o período
CONCEITUAL do produto NMME3 pooled/multi-modelo (documentado via manual
NMME3, Rodada 2) — NUNCA confundido com o período nativo desta rota
específica, registrado à parte em `homogeneous_hindcast_end` (Seção 6:
"1991-2020 = NMME climatology construction period", não "homogeneous
native hindcast period").

Nenhum arquivo de dado real (NetCDF/GRIB) foi baixado nesta rodada —
só o catálogo-fonte (texto Ingrid) do próprio projeto IRI, lido via
GitHub, dentro do mesmo espírito de investigação documental da Rodada
3.

═══════════════════════════════════════════════════════════════════════
RODADA 5 DE INVESTIGAÇÃO (correção final pré-PR) — sunset do IRIDL,
migração para forecast.ccsr, abstração de backend, 2 representações do
CFSv2 legado
═══════════════════════════════════════════════════════════════════════

**Sunset do IRIDL confirmado e corroborado independentemente**:
WebSearch (não aberto de primeira mão — `iri.columbia.edu` segue
bloqueado) encontrou, de forma consistente em múltiplas buscas
independentes desta rodada, que o desligamento completo da IRIDL é
esperado até o final de outubro de 2026 ("by the end of October 2026,
possibly earlier"), e que a IRI está montando uma instância mais
simples em `forecast.ccsr.columbia.edu` (Columbia Climate School/CCSR)
para hospedar dados de NMME/SubX/S2S. `forecast.ccsr.columbia.edu`
também está BLOQUEADO para WebFetch direto nesta sessão — nada foi
aberto de primeira mão desse domínio.

**O que se sabe sobre forecast.ccsr (tudo via WebSearch, DOCUMENTED, não
EMPIRICALLY_CONFIRMED)**: serviço em beta desde ~dez/2025-jan/2026;
hospeda inicialmente 4 dos 5 modelos NMME ativos (precipitação, T2m,
SST); CFSv2 (o 5º modelo) estava sendo adicionado "gradualmente nas
semanas seguintes" a partir de um ponto não datado com precisão —
consistente com a citação da revisão externa de que "early month
samples" do CFSv2 já estariam disponíveis, mas SEM um endpoint/path
exato encontrado nesta sessão. Seguindo a Seção 12 da tarefa
("Não tentar descobrir endpoint CCSR por adivinhação... se o endpoint
exato não estiver documentado: manter DISCOVERY_REQUIRED"): nenhuma URL
foi construída para CCSR_BETA — o campo `dataset_path` dessa rota fica
`None` deliberadamente.

**Duas representações distintas do CFSv2 no IRIDL legado (Seção 9)**:
além da rota A já registrada na Rodada 4 (`SOURCES/.NOAA/.NCEP/.EMC/
.CFSv2/.ENSEMBLE/.FLXF/.surface/.PRATE/`, catálogo-fonte lido de
primeira mão via `github.com/iridl/dlentries`), esta rodada leu de
primeira mão (mesma via GitHub, mesmo método) uma SEGUNDA entrada real:
`entries/Models/NMME/NCEP-CFSv2/HINDCAST/MONTHLY/index.tex` —
`SOURCES/.Models/.NMME/.NCEP-CFSv2/.HINDCAST/.MONTHLY/.prec/`. Valores
lidos verbatim: S = 1/jan/1982 a 1/dez/2010 (mensal); L = `0.5 1 9.5`
(mesma convenção 0.5-9.5, passo 1 mês, da rota A); M = `/M 24
NewIntegerGRID` (tamanho FIXO 24, não 28); X = `0.0 1. 359.` (360
pontos, 1°); Y = `90. 1. -90.` (181 pontos, 1°, não Gaussiana); variável
interna `prec` (não "PRATE" nem "prate"), armazenada em kg/m²/s e
convertida para mm/day pelo próprio catálogo Ingrid (`unitconvert`).
Isso é EMPIRICALLY_CONFIRMED para a definição de catálogo desta segunda
representação, pelo mesmo método (leitura direta do catálogo-fonte real
via GitHub) já usado para a primeira.

As duas representações NÃO são reconciliadas nesta rodada (instrução
explícita da revisão, Seção 9) — ficam registradas como:
- **A. raw/native CFSv2 ensemble** (`ENSEMBLE/FLXF`, M=28, grade
  384×190 Gaussiana, variável PRATE em kg m-2 s-1) — a rota já usada
  pelo downloader/testes da Rodada 4.
- **B. NMME harmonized/monthly sample** (`Models/NMME/NCEP-CFSv2/
  HINDCAST/MONTHLY`, M=24, grade 360×181 regular 1°, variável prec
  convertida para mm/day) — mais próxima do produto NMME3
  "pooled"/24-membros documentado no manual (Rodada 2), mas ainda
  assim não confirmada como sendo LITERALMENTE o mesmo dado.

Todo uso real (quando o POC de fato executar) deve declarar
explicitamente qual das duas representações usou — nunca tratar como
intercambiáveis.

Nenhum arquivo de dado real foi baixado nesta rodada — só catálogos-
fonte (texto Ingrid) via GitHub, mesmo espírito documental das rodadas
anteriores.
"""

from dataclasses import dataclass, field
from typing import Optional

# ══════════════════════════════════════════════════════════════════════════
# Seção 7/11 — matriz de evidência: todo campo crítico carrega um status.
# ══════════════════════════════════════════════════════════════════════════
DOCUMENTED = 'DOCUMENTED'
EMPIRICALLY_CONFIRMED = 'EMPIRICALLY_CONFIRMED'
DOCUMENTED_AND_CONFIRMED = 'DOCUMENTED_AND_CONFIRMED'
UNCONFIRMED = 'UNCONFIRMED'
STATUS_VALIDOS = {DOCUMENTED, EMPIRICALLY_CONFIRMED, DOCUMENTED_AND_CONFIRMED, UNCONFIRMED}

# Seção 19 — disponibilidade por critério de protocolo, nunca por
# performance local (Seção 19/22).
STATUS_CANDIDATO = 'CANDIDATE'
STATUS_NAO_HOMOGENEO = 'NOT_HOMOGENEOUSLY_AVAILABLE'

# Seção 7/8 (correção pós-revisão) — acesso a dado, separado de
# disponibilidade científica: um modelo pode ser um CANDIDATO válido
# (retrospectiva documentada) e ainda assim não ter endpoint/variável/
# dimensões confirmados o bastante para um POC real executar sem
# adivinhar (Seção 7/8). CONFIRMED exige as 3 coisas ao mesmo tempo E
# um subset real já ter sido aberto com sucesso — nunca marcado só por
# documentação, por mais forte que seja (Seção 4 da Rodada 4 revisão).
# POC_READY_DOCUMENTED (Seção 4 da Rodada 4) é o degrau abaixo: endpoint
# + variável + TODAS as dimensões (S/M/L/X/Y) documentadas com evidência
# forte o bastante para montar um request real auditável — mas nenhum
# subset real foi de fato aberto ainda. PARTIAL quando só parte disso
# existe; UNCONFIRMED quando nada disso existe.
DATA_ACCESS_CONFIRMED = 'CONFIRMED'
DATA_ACCESS_POC_READY_DOCUMENTED = 'POC_READY_DOCUMENTED'
DATA_ACCESS_PARTIAL = 'PARTIAL'
DATA_ACCESS_UNCONFIRMED = 'UNCONFIRMED'
DATA_ACCESS_STATUS_VALIDOS = {DATA_ACCESS_CONFIRMED, DATA_ACCESS_POC_READY_DOCUMENTED,
                                DATA_ACCESS_PARTIAL, DATA_ACCESS_UNCONFIRMED}

# ══════════════════════════════════════════════════════════════════════════
# Rodada 5 (correção final pré-PR) — abstração simples de backend (Seção
# 4): a lógica científica não deve ficar presa à sintaxe Ingrid do
# IRIDL. Um sistema pode ter mais de uma ROTA member-level registrada
# (backend + representação de dado), cada uma com seu próprio status —
# nunca um único data_access_status no nível do sistema tentando cobrir
# rotas com maturidade diferente (Seção 5/6/9).
# ══════════════════════════════════════════════════════════════════════════
SOURCE_BACKEND_IRIDL_LEGACY = 'IRIDL_LEGACY'
SOURCE_BACKEND_CCSR_BETA = 'CCSR_BETA'
SOURCE_BACKEND_VALIDOS = {SOURCE_BACKEND_IRIDL_LEGACY, SOURCE_BACKEND_CCSR_BETA}

# Seção 9 — duas representações de dado DISTINTAS podem existir sob o
# MESMO backend (ex.: IRIDL_LEGACY tem tanto o ensemble bruto quanto a
# amostra harmonizada do NMME) — nunca reconciliadas automaticamente.
REPR_RAW_NATIVE_ENSEMBLE = 'RAW_NATIVE_ENSEMBLE'          # A
REPR_NMME_HARMONIZED_MONTHLY = 'NMME_HARMONIZED_MONTHLY'  # B
REPR_UNKNOWN = 'UNKNOWN'                                   # CCSR_BETA, ainda não descoberta
REPR_VALIDOS = {REPR_RAW_NATIVE_ENSEMBLE, REPR_NMME_HARMONIZED_MONTHLY, REPR_UNKNOWN}

# Seção 5 — status por ROTA (não por sistema): uma rota pode estar
# documentada o bastante para uma tentativa real (LEGACY, Rodada 4/5)
# enquanto outra do MESMO sistema segue sem endpoint confirmado
# (CCSR_BETA, Seção 12 — nunca inventado por adivinhação de padrão).
ROUTE_STATUS_POC_READY_DOCUMENTED_LEGACY = 'POC_READY_DOCUMENTED_LEGACY'
ROUTE_STATUS_DISCOVERY_REQUIRED = 'DISCOVERY_REQUIRED'
ROUTE_STATUS_VALIDOS = {ROUTE_STATUS_POC_READY_DOCUMENTED_LEGACY, ROUTE_STATUS_DISCOVERY_REQUIRED}

# Seção 7 — risco de continuidade operacional da rota: HIGH para o
# serviço com data de desligamento anunciada (IRIDL legado); BETA para
# o serviço novo ainda em beta, sem garantia de estabilidade de
# metadata (forecast.ccsr).
CONTINUITY_RISK_HIGH = 'HIGH'
CONTINUITY_RISK_BETA = 'BETA'
CONTINUITY_RISK_VALIDOS = {CONTINUITY_RISK_HIGH, CONTINUITY_RISK_BETA}

# Data operacional aproximada de desligamento do IRIDL legado (Seção 7
# — "by the end of October 2026, possibly earlier", DOCUMENTED via
# WebSearch corroborado em múltiplas buscas independentes nesta rodada
# e na Rodada 4; NUNCA tratada como garantia contratual, só como sinal
# operacional para priorizar a migração).
LEGACY_SERVICE_EXPECTED_SHUTDOWN = '2026-10-31'


@dataclass(frozen=True)
class RotaMemberLevel:
    """1 rota concreta (backend + representação de dado) para acessar
    precipitação por membro de 1 sistema — Seção 4 da correção final:
    campos simples, sem tentar generalizar para os outros 6 candidatos
    nesta rodada (Seção 16, mantido de rodadas anteriores)."""
    data_backend: str                  # IRIDL_LEGACY | CCSR_BETA
    dataset_representation: str        # RAW_NATIVE_ENSEMBLE | NMME_HARMONIZED_MONTHLY | UNKNOWN
    dataset_path: Optional[str]        # None quando status=DISCOVERY_REQUIRED — nunca um path
                                        # inventado por analogia (Seção 12)
    variable_name: Optional[str]
    units_expected: Optional[str]
    member_dimension: Optional[str]
    lead_dimension: Optional[str]
    init_dimension: Optional[str]
    lat_dimension: Optional[str]
    lon_dimension: Optional[str]
    member_axis_size: Optional[int]    # tamanho declarado do eixo M no catálogo-fonte (ex.: 28 ou 24)
    grid_shape: Optional[str]          # ex.: "384x190 (Gaussiana)" ou "360x181 (1°x1°)"
    status: str                        # POC_READY_DOCUMENTED_LEGACY | DISCOVERY_REQUIRED
    source_continuity_risk: str        # HIGH | BETA
    source_reference: tuple = field(default_factory=tuple)
    notes: str = ''
    # Execução real #2 (Seção 4, item 7) — gate explícito para o Método B
    # de confirmação temporal (nmme_processar._avaliar_semantica_
    # forecast_period): só True quando a documentação oficial da
    # COLEÇÃO específica desta rota (não uma convenção genérica
    # assumida) já foi lida de primeira mão e registra S como
    # forecast_reference_time / L como forecast_period em meses. Nunca
    # True por padrão — cada rota precisa da própria citação em
    # `mapping_reference`.
    forecast_period_semantics_documented: bool = False
    mapping_reference: tuple = field(default_factory=tuple)
    # Execução real #3 (Seção 5/6-E) — gate explícito, SEPARADO do
    # anterior, para a via alternativa de confirmação de inicialização
    # quando a operação Ingrid VALUE remove a dimensão S por completo da
    # variável (nunca cai para o eixo S global do catálogo como
    # substituto — Seção 3). Só True quando o operador VALUE do Ingrid
    # (seleciona o ponto de grade mais próximo do valor pedido e remove
    # essa dimensão) está documentado o bastante para esta rota — nunca
    # assumido por padrão.
    ingrid_value_init_selection_documented: bool = False


@dataclass(frozen=True)
class SistemaNMME:
    centre: str                            # organização/centro contribuinte
    model_name: str                        # nome do sistema retrospectivo/hindcast documentado (Seção 3
                                            # — equivalente ao "hindcast_system_name" pedido na revisão)
    model_version: Optional[str]
    official_model_id: Optional[str]       # identificador em catálogos oficiais (ex.: path IRIDL)
    data_source: str                       # rota de dados PRINCIPAL investigada (Seção 9)
    data_url_template: Optional[str]       # padrão de URL só quando documentado; None se não (Seção 6)
    data_access_status: str                # CONFIRMED | PARTIAL | UNCONFIRMED (Seção 7/8, correção)
    current_operational_name: Optional[str]  # nome no conjunto operacional ATUAL (pode divergir do
                                              # nome do sistema retrospectivo — Seção 3, correção); None
                                              # quando o modelo não aparece claramente no rol operacional
                                              # corrente ou quando isso é ambíguo entre páginas CPC.
    hindcast_start: Optional[int]
    hindcast_end: Optional[int]
    hindcast_members: Optional[int]
    realtime_members: Optional[int]
    leads_available: tuple
    grid_resolution: Optional[str]
    precip_variable: Optional[str]
    precip_units: Optional[str]
    hindcast_frequency: Optional[str]
    initialization_scheme: Optional[str]
    availability_status: str               # CANDIDATE | NOT_HOMOGENEOUSLY_AVAILABLE
    source_reference: tuple = field(default_factory=tuple)
    notes: str = ''
    # Seção 7/8 — status por campo crítico; chaves ausentes tratadas como
    # UNCONFIRMED por _validar_catalogo() (Seção 35-B), nunca por omissão
    # silenciosa.
    evidence: dict = field(default_factory=dict)
    # Rodada 4 (correção pós-revisão) — rota B: dataset IRI member-level
    # (distinto do data_url_template genérico, que pode representar OUTRA
    # rota/estrutura — ex.: CPT ensemble-mean da Rodada 3, Seção 3).
    # None para os sistemas que não têm essa rota específica investigada.
    member_level_data_source: Optional[str] = None     # de onde veio a evidência (ex.: "IRI Data
                                                          # Library — SOURCES/.../.ENSEMBLE/.../.PRATE/,
                                                          # catálogo-fonte lido via github.com/iridl/dlentries")
    member_level_dataset_path: Optional[str] = None    # path Ingrid do dataset member-level (rota B),
                                                          # nunca reaproveita data_url_template (rota A)
    # Seção 6 (Rodada 4) — fim do arquivo NATIVO homogêneo desta rota
    # específica, DISTINTO de hindcast_end (que é o fim do período
    # CONCEITUAL do produto NMME3 pooled/multi-modelo, Rodada 2). Nunca
    # tratar os dois como o mesmo conceito.
    homogeneous_hindcast_end: Optional[str] = None
    # Rodada 5 — abstração de backend (Seção 4): tupla de RotaMemberLevel,
    # uma por (backend, representação) investigada. Vazia para os
    # sistemas não investigados nesta rodada (Seção 16).
    member_level_routes: tuple = field(default_factory=tuple)


# ══════════════════════════════════════════════════════════════════════════
# Seção 5 — ECMWF explicitamente fora de escopo, mesmo que alguma config
# NMME3 o liste: queremos independência da validação C3S (Fases 2A-2B).
# Seção 21 — predecessores JAMAIS tratados como o mesmo sistema que o
# substituiu; registrados aqui só para auditoria/anti-confusão, nunca
# usados para preencher hindcast do sistema atual (Seção 22).
# ══════════════════════════════════════════════════════════════════════════
NAO_INCLUIDOS = {
    'ECMWF': {
        'motivo': 'Exclusão deliberada (Seção 5) — ECMWF já é a base do C3S validado nas Fases 2A-2B. '
                   'Incluí-lo aqui invalidaria a independência que a Fase 2C busca, mesmo que alguma '
                   'configuração NMME3 documentada recentemente o liste em algum papel.',
    },
}

PREDECESSORES_NAO_CONFUNDIR = {
    'CanCM4i': {
        'substituido_por': 'CanESM5', 'centre': 'ECCC',
        'motivo': 'Troca de sistema documentada (Seção 21) — CanCM4i e CanESM5 NÃO são o mesmo modelo; '
                   'uma série concatenando os dois não é um hindcast homogêneo (Seção 21/22).',
        'membros_documentados_geracao_anterior': 10,
        'fonte': 'LaJoie (CPC), CDPW47, out/2022 — slide 4: "CanCM4i 10 members".',
    },
    'GEM_NEMO': {
        'substituido_por': 'GEM5.2_NEMO', 'centre': 'ECCC',
        'motivo': 'Troca de sistema documentada (Seção 21) — GEM_NEMO (sem o ".2") é o predecessor, '
                   'nunca o mesmo sistema que GEM5.2_NEMO.',
        'membros_documentados_geracao_anterior': 10,
        'fonte': 'LaJoie (CPC), CDPW47, out/2022 — slide 4: "GEM_NEMO 10 members".',
    },
    'GFDL_FLOR': {
        'substituido_por': 'GFDL_SPEAR', 'centre': 'NOAA/GFDL',
        'motivo': 'Troca de sistema documentada (Seção 21) — GFDL_FLOR (CM2.5-FLOR) é o predecessor; '
                   'SPEAR entrou no NMME em 06/fev/2021 como sistema NOVO, não uma revisão do FLOR.',
        'membros_documentados_geracao_anterior': 24,
        'fonte': 'LaJoie (CPC), CDPW47, out/2022 — slide 4: "GFDL_FLOR 24 members".',
    },
}

# Fonte comum da Rodada 2 (citada em vários source_reference abaixo) —
# extraída aqui para não repetir o texto inteiro em cada entrada.
_FONTE_NMME3_MANUAL = (
    'NOAA CPC "NMME3 Operational User Manual" (ftp.cpc.ncep.noaa.gov/CPC/ID/figs/USER_MANUAL.html), '
    'citado pela revisão externa com hindcast 1991-2020 e nº de membros por modelo. NÃO aberto de '
    'primeira mão nesta sessão (ftp.cpc.ncep.noaa.gov bloqueado para WebFetch direto, mesma restrição '
    'da Rodada 1) — DOCUMENTED via citação da revisão + coerência com os valores já reunidos '
    'independentemente na Rodada 1 (LaJoie/CPC), nunca EMPIRICALLY_CONFIRMED. Nota de nomenclatura: '
    'um WebSearch independente desta sessão encontrou o termo "NMME3" usado em outro documento CPC '
    '("NMME Review for 2020") para uma configuração de 2014-2019 com modelos diferentes (CFSv2/GEOS5/'
    'CM2.1/CanCM3/CanCM4/CM2.5-FLOR/CCSM4) — ambiguidade de nomenclatura registrada, não resolvida.'
)
_FONTE_ABOUT_NMME_JUN2025 = (
    'Página CPC "About NMME", citada pela revisão externa como descrevendo o conjunto operacional '
    '"core" desde 08/jun/2025 (CFSv2, CanESM5, GEM5.2-NEMO, NCAR-CESM1, NCAR-CCSM4, NASA-GEOS-S2S-2). '
    'Corroborada por WebSearch independente desta sessão, que devolveu a mesma lista de 6 modelos — '
    'mas o MESMO WebSearch também encontrou outra página CPC de monitoramento listando 7 modelos '
    'incluindo GFDL_SPEAR e NASA_GEOS5v2 (nomenclatura antiga) para aproximadamente a mesma época — '
    'páginas CPC distintas descrevendo conjuntos operacionais diferentes, não resolvido por inferência '
    '(Seção 3).'
)

# ══════════════════════════════════════════════════════════════════════════
# Seção 4/6/8 — os 7 candidatos investigados. NENHUM valor numérico
# aparece sem `source_reference` não-vazio (barreira em
# _validar_catalogo). Onde a investigação não permitiu confirmação
# (rede bloqueada), o campo fica `None`/status `UNCONFIRMED` — nunca
# inventado (Seção 6: "Quando uma informação não puder ser comprovada:
# usar None. Nunca inventar.").
# ══════════════════════════════════════════════════════════════════════════
CATALOGO = [
    SistemaNMME(
        centre='NOAA_NCEP', model_name='CFSv2', model_version=None, official_model_id=None,
        data_source='Rota A (CPC/CPT, Rodada 3): NOAA CPC FTP — '
                     '`International/nmme/monthly_nmme_hindcast_in_cpt_format/` — ensemble-mean por T, '
                     'não por membro (ver member_level_data_source para a rota realmente usada no POC '
                     'por membro). Rota B (IRI, Rodada 4, PRIORITÁRIA para o POC por membro): ver '
                     'member_level_data_source/member_level_dataset_path.',
        data_url_template='https://ftp.cpc.ncep.noaa.gov/International/nmme/'
                           'monthly_nmme_hindcast_in_cpt_format/cfsv2_precip_hcst_{MesAbrev}ic_{n}_'
                           '{ano}.txt (Rota A — CPT ensemble-mean, Rodada 3; NÃO é a rota do POC por '
                           'membro, mantida só para auditoria — ver nmme_cpc_cpt.py)',
        data_access_status=DATA_ACCESS_POC_READY_DOCUMENTED,   # Rodada 4: endpoint + variável + TODAS
                                                    # as dimensões (S/M/L/X/Y) da rota B (IRI member-
                                                    # level) documentadas com evidência forte (leitura
                                                    # de primeira mão do catálogo-fonte Ingrid via
                                                    # GitHub) — mas nenhum subset real foi aberto contra
                                                    # iridl.ldeo.columbia.edu (bloqueado). Não é CONFIRMED.
        current_operational_name='CFSv2',   # citado como core operacional em ambas as páginas CPC (Seção 3)
        hindcast_start=1991, hindcast_end=2020,   # período CONCEITUAL do produto NMME3 pooled — NUNCA
                                                    # confundir com o período nativo da rota B, ver
                                                    # homogeneous_hindcast_end abaixo (Seção 6, Rodada 4)
        hindcast_members=24, realtime_members=None,   # 24 = amostra NOMINAL do produto NMME3 (manual,
                                                         # Rodada 2) — DISTINTO do tamanho bruto do eixo M
                                                         # da rota B (28, EMPIRICALLY_CONFIRMED, Rodada 4;
                                                         # ver scripts/nmme_download.py sobre a faixa
                                                         # aceita [24,28] no dado bruto observado)
        leads_available=(1, 2, 3, 4, 5, 6),
        grid_resolution='Rota A (CPT, Rodada 3): 1° (DOCUMENTED por analogia de família de formato). '
                          'Rota B (IRI ENSEMBLE/FLXF, Rodada 4): X 0-360°/384 pontos (0,9375° de '
                          'espaçamento) e Y grade GAUSSIANA de 190 pontos (NÃO uniforme) — '
                          'EMPIRICALLY_CONFIRMED via leitura direta do catálogo-fonte Ingrid '
                          '(github.com/iridl/dlentries).',
        precip_variable='prate', precip_units='kg m-2 s-1',   # kg m-2 s-1 é o valor EMPIRICALLY_CONFIRMED
                                                                 # (Rodada 4) para a variável PRATE da rota
                                                                 # B — já reconhecido por
                                                                 # nmme_processar.UNIDADES_KG_M2_S_ACEITAS;
                                                                 # continua UNCONFIRMED para a rota A (CPT)
        hindcast_frequency='monthly (rota A/CPT); rota B (IRI) é nativamente a cada 5 DIAS '
                            '(EMPIRICALLY_CONFIRMED via catálogo-fonte Ingrid, Rodada 4 — S grid com '
                            'passo "5" num calendário de 365 dias/unidade dias) — como isso vira '
                            '"monthly starts of 24-28 members" na descrição da IRI não foi confirmado '
                            'nesta sessão (pendência explícita, Rodada 4).',
        initialization_scheme='CFSv2 roda com múltiplas inicializações a cada 5 dias, 4 ciclos/dia '
                               '(EMPIRICALLY_CONFIRMED via catálogo-fonte Ingrid da rota B, Rodada 4, '
                               'corroborado independentemente por Yuan et al. 2011 via WebSearch, não '
                               'aberto de primeira mão) — como o ensemble "mensal"/pooled de 24-28 '
                               'membros é formado a partir dessas rodadas de 5 em 5 dias NÃO foi '
                               'confirmado nesta sessão; nunca misturar rodada nativa com o pooled sem '
                               'essa confirmação.',
        availability_status=STATUS_CANDIDATO,
        source_reference=(
            'LaJoie (CPC), Climate Diagnostics and Prediction Workshop nº47, 25-27/out/2022, slide 4: '
            '"CFSv2 24 members" (cpc.ncep.noaa.gov/products/outreach/CDPW/47/sessions/presentations/'
            'session8-oral1.pdf — PDF lido de primeira mão nesta sessão).',
            _FONTE_NMME3_MANUAL, _FONTE_ABOUT_NMME_JUN2025,
            'WebSearch (Rodada 3) — múltiplos resultados independentes devolvendo URLs reais indexadas '
            'em ftp.cpc.ncep.noaa.gov/International/nmme/monthly_nmme_hindcast_in_cpt_format/ — Rota A.',
            'github.com/iri-pycpt/pycpt, cpt-io/src/cptio/fileio/cpt.py + fixture real CanCM4i/SAZONAL '
            '(cpt-io/tests/data/SEASONAL_CANCM4I_...) — lidos de primeira mão via '
            'raw.githubusercontent.com (Rodada 3) — evidência de que a Rota A é ensemble-mean-only.',
            'github.com/iridl/dlentries, entries/NOAA/NCEP/EMC/CFSv2/ENSEMBLE/FLXF/index.tex — '
            'catálogo-fonte Ingrid REAL da Rota B (IRI SOURCES/.NOAA/.NCEP/.EMC/.CFSv2/.ENSEMBLE/.FLXF/'
            '.surface/.PRATE/), lido de primeira mão via raw.githubusercontent.com (Rodada 4): S grid '
            '(1981-12-12 a 2011-03-27, passo 5 dias), L grid (0.5 a 9.5, passo 1 mês), M (28, '
            'NewIntegerGRID), X (0-360°, 384 pontos), Y (gaussianlat, 190 pontos), PRATE '
            '(long_name="Precipitation Rate", units="kg m-2 s-1").',
            'WebSearch (Rodada 4, não aberto de primeira mão) — Yuan et al. (2011), Geophysical '
            'Research Letters, "A first look at CFSv2 for hydrological seasonal prediction": hindcasts '
            'iniciados a cada 5 dias, 4 ciclos/dia, 1982-2009, 24 membros — corrobora o passo "5" do S '
            'grid lido de primeira mão.',
            'WebSearch (Rodada 4) — página IRI "Data Library Sunset" (iri.columbia.edu/resources/'
            'data-library/sunset/, não aberta de primeira mão): a IRIDL está prevista para deixar de '
            'operar na forma atual a partir de abr/2026 por falta de financiamento — ver notes, risco '
            'operacional real para a Rota B.',
        ),
        notes='ROTA A (CPT, Rodada 3) vs. ROTA B (IRI member-level, Rodada 4) — nunca confundidas '
              '(Seção 3 da tarefa): data_url_template continua representando SÓ a Rota A '
              '(ensemble-mean, Rodada 3); a Rota B tem seus PRÓPRIOS campos '
              '(member_level_data_source/member_level_dataset_path), nunca reaproveitando '
              'data_url_template para uma estrutura diferente.'
              '\n\nPor que data_access_status é POC_READY_DOCUMENTED e não CONFIRMED (Seção 4, Rodada '
              '4): a Rota B tem endpoint + variável (PRATE) + as 5 dimensões (S/M/L/X/Y) documentadas '
              'com evidência FORTE — não uma busca ou paráfrase, mas a leitura direta do arquivo-fonte '
              'Ingrid que a própria IRI usa para gerar a página do dataset (via GitHub, não bloqueado). '
              'Isso é o bastante para montar um request real auditável (ver '
              'nmme_download.montar_url_iri_cfsv2_member_level). Mas continua abaixo de CONFIRMED '
              'porque nenhum request de fato foi enviado contra iridl.ldeo.columbia.edu (bloqueado '
              'nesta sessão) — "documentado o suficiente para testar" não é "já empiricamente '
              'validado" (Seção 4). CFSv2 sobe para CONFIRMED só depois de um subset real pequeno abrir '
              'com sucesso e confirmar variável/unidade/dimensões/acesso.'
              '\n\nRisco operacional (Rodada 4): a página oficial "Data Library Sunset" da IRI (não '
              'aberta de primeira mão, só via WebSearch) diz que a IRIDL está prevista para deixar de '
              'ter equipe suficiente para operar na forma atual a partir de abril/2026 por queda de '
              'financiamento — o primeiro passo de qualquer tentativa real contra esta rota deve ser '
              'verificar se o serviço ainda está no ar, não assumir que a documentação implica '
              'disponibilidade contínua.'
              '\n\nMembros — nominal vs. bruto (Seção 5, Rodada 4): hindcast_members=24 é a amostra '
              'NOMINAL do produto NMME3 (manual, Rodada 2) — o eixo M bruto da Rota B tem tamanho FIXO '
              '28 no catálogo-fonte (EMPIRICALLY_CONFIRMED), mas a contagem REAL de membros não-'
              '"missing" observada num subset pode variar entre 24 e 28 conforme o período (Yuan et '
              'al. 2011 cita 24 para 1982-2009) — nunca hardcodar um valor único para o dado bruto da '
              'Rota B; aceitar a faixa observada [24,28] e registrar n_members_observed (ver '
              'nmme_processar.processar_origem_modelo).'
              '\n\nPeríodo nativo vs. período NMME3 pooled (Seção 6, Rodada 4): homogeneous_hindcast_end '
              '="2011-03" registra o fim do arquivo NATIVO da Rota B (EMPIRICALLY_CONFIRMED via S grid: '
              '27/mar/2011) — DISTINTO de hindcast_end=2020 (fim do período CONCEITUAL do produto NMME3 '
              'pooled/multi-modelo). O início do arquivo nativo lido nesta sessão (dez/1981) diverge do '
              'que a revisão externa citou (1991) — convergência só no FIM (mar/2011), não no início; '
              'registrado como pendência, não resolvido por inferência.',
        evidence={'hindcast_members': DOCUMENTED, 'hindcast_start': DOCUMENTED, 'hindcast_end': DOCUMENTED,
                   'precip_variable': DOCUMENTED, 'realtime_members': UNCONFIRMED,
                   'grid_resolution': EMPIRICALLY_CONFIRMED, 'precip_units': EMPIRICALLY_CONFIRMED,
                   'initialization_scheme': EMPIRICALLY_CONFIRMED, 'data_url_template': DOCUMENTED},
        member_level_data_source='IRI Data Library — catálogo-fonte Ingrid lido de primeira mão via '
                                  'github.com/iridl/dlentries (Rodada 4); o servidor '
                                  'iridl.ldeo.columbia.edu em si continua bloqueado nesta sessão.',
        member_level_dataset_path='SOURCES/.NOAA/.NCEP/.EMC/.CFSv2/.ENSEMBLE/.FLXF/.surface/.PRATE/ '
                                   '(Ingrid, base https://iridl.ldeo.columbia.edu/ — EMPIRICALLY_'
                                   'CONFIRMED ao nível de definição de catálogo, NÃO testado contra o '
                                   'servidor real)',
        homogeneous_hindcast_end='2011-03',
        member_level_routes=(
            RotaMemberLevel(
                data_backend=SOURCE_BACKEND_CCSR_BETA,
                dataset_representation=REPR_UNKNOWN,
                dataset_path=None,   # Seção 12 — nunca inventado por adivinhação de padrão
                variable_name='pr',   # citado pela revisão externa (25/ago/2026) — DOCUMENTED, não
                                       # confirmado num endpoint real
                units_expected='mm/day',
                member_dimension=None, lead_dimension=None, init_dimension=None,
                lat_dimension=None, lon_dimension=None,
                member_axis_size=None, grid_shape=None,
                status=ROUTE_STATUS_DISCOVERY_REQUIRED,
                source_continuity_risk=CONTINUITY_RISK_BETA,
                source_reference=(
                    'WebSearch (Rodada 5, não aberto de primeira mão — forecast.ccsr.columbia.edu '
                    'bloqueado): serviço em beta desde ~dez/2025-jan/2026, hospedando 4 dos 5 modelos '
                    'NMME ativos (precipitação/T2m/SST); CFSv2 sendo adicionado gradualmente. '
                    'Comunicação oficial IRI citada pela revisão externa (25/ago/2026): "early month '
                    'samples" do CFSv2 já disponível, "pentad samples" a caminho, variável padronizada '
                    'como "pr" em mm/day, convenções mais próximas de CMIP6.',
                ),
                notes='DISCOVERY_REQUIRED deliberado (Seção 12) — nenhum endpoint/path exato foi '
                      'encontrado nesta sessão para forecast.ccsr, e o domínio está bloqueado para '
                      'WebFetch direto. Nunca construir URL por tentativa de padrão. Promover para '
                      'POC_READY_DOCUMENTED só depois de confirmar endpoint+formato+cobertura de '
                      'hindcast+membro+lead+coordenadas+arquivos reais (Seção 5).',
            ),
            RotaMemberLevel(
                data_backend=SOURCE_BACKEND_IRIDL_LEGACY,
                dataset_representation=REPR_RAW_NATIVE_ENSEMBLE,
                dataset_path='SOURCES/.NOAA/.NCEP/.EMC/.CFSv2/.ENSEMBLE/.FLXF/.surface/.PRATE/',
                variable_name='PRATE', units_expected='kg m-2 s-1',
                member_dimension='M', lead_dimension='L', init_dimension='S',
                lat_dimension='Y', lon_dimension='X',
                member_axis_size=28, grid_shape='384x190 (Gaussiana, 0,9375° em X)',
                status=ROUTE_STATUS_POC_READY_DOCUMENTED_LEGACY,
                source_continuity_risk=CONTINUITY_RISK_HIGH,
                source_reference=(
                    'github.com/iridl/dlentries, entries/NOAA/NCEP/EMC/CFSv2/ENSEMBLE/FLXF/index.tex — '
                    'lido de primeira mão via raw.githubusercontent.com (Rodada 4).',
                    'WebSearch (Rodada 5) — página IRI "Data Library Sunset": desligamento completo '
                    'esperado até o final de outubro de 2026, possivelmente antes.',
                ),
                notes='Representação A (Seção 9) — dado bruto/nativo por membro, a rota já usada pelo '
                      'downloader/testes da Rodada 4 (nmme_download.montar_url_iri_cfsv2_member_level). '
                      f'source_continuity_risk=HIGH: legacy_service_expected_shutdown='
                      f'{LEGACY_SERVICE_EXPECTED_SHUTDOWN} (aproximado, não uma garantia contratual). '
                      'forecast_period_semantics_documented=False (default) — diferente da Representação '
                      'B, o index.tex desta rota (FLXF/PRATE) NÃO foi lido com o mesmo nível de detalhe '
                      'sobre a grade L; não promover para True sem essa citação específica (Seção 4-#7, '
                      'execução real #2).',
                # Execução real #3 (Seção 5/6-E) — VALUE é o MESMO operador
                # Ingrid já usado por X/Y/VALUE nesta própria URL
                # (montar_url_iri_cfsv2_member_level); documentado
                # publicamente como "seleciona o ponto de grade mais
                # próximo do valor pedido e remove essa dimensão do
                # resultado" — propriedade da LINGUAGEM Ingrid, não desta
                # coleção específica, por isso True aqui mesmo com
                # forecast_period_semantics_documented=False.
                ingrid_value_init_selection_documented=True,
                mapping_reference=(
                    'Operador Ingrid VALUE (iridl.ldeo.columbia.edu, sintaxe pública "ingrid"): '
                    '"select nearest grid point to value, dropping that dimension" — mesmo operador já '
                    'usado para X/Y nesta rota (Rodada 4); propriedade do operador, não da coleção.',
                ),
            ),
            RotaMemberLevel(
                data_backend=SOURCE_BACKEND_IRIDL_LEGACY,
                dataset_representation=REPR_NMME_HARMONIZED_MONTHLY,
                dataset_path='SOURCES/.Models/.NMME/.NCEP-CFSv2/.HINDCAST/.MONTHLY/.prec/',
                variable_name='prec', units_expected='mm/day',
                member_dimension='M', lead_dimension='L', init_dimension='S',
                lat_dimension='Y', lon_dimension='X',
                member_axis_size=24, grid_shape='360x181 (regular 1°x1°)',
                status=ROUTE_STATUS_POC_READY_DOCUMENTED_LEGACY,
                source_continuity_risk=CONTINUITY_RISK_HIGH,
                source_reference=(
                    'github.com/iridl/dlentries, entries/Models/NMME/NCEP-CFSv2/HINDCAST/MONTHLY/'
                    'index.tex — lido de primeira mão via raw.githubusercontent.com (Rodada 5): S '
                    '1/jan/1982 a 1/dez/2010 (mensal), L "0.5 1 9.5", M "/M 24 NewIntegerGRID", X "0.0 '
                    '1. 359." (360 pontos), Y "90. 1. -90." (181 pontos), variável "prec" em kg/m²/s '
                    'convertida para mm/day pelo próprio catálogo (unitconvert).',
                ),
                notes='Representação B (Seção 9) — amostra harmonizada do NMME (mais próxima do '
                      'produto NMME3 "pooled"/24-membros documentado no manual, Rodada 2, mas NÃO '
                      'confirmada como sendo literalmente o mesmo dado — nunca reconciliada com a '
                      'Representação A nesta rodada, instrução explícita da revisão). Nenhum downloader '
                      'foi escrito para esta representação especificamente nesta rodada — registrada '
                      'para auditoria/futuro uso, não é a rota padrão escolhida por '
                      'nmme_download.escolher_backend_member_level (que prioriza a Representação A).',
                # Execução real #2 (run 35888809240, Seção 4-#7) — gate
                # do Método B de confirmação temporal: o index.tex desta
                # rota já foi lido de primeira mão (source_reference
                # acima) e documenta explicitamente S como a grade de
                # inicialização mensal (forecast_reference_time) e L
                # como a grade de lead "0.5 1 9.5" em meses
                # (forecast_period) — a mesma convenção S/L do IRI Data
                # Library usada em todo este projeto (CLAUDE.md Seção
                # 9). Os atributos standard_name/units REAIS do dataset
                # aberto continuam checados empiricamente a cada
                # execução (itens 1-6 do Método B); este campo só
                # libera a TENTATIVA do Método B para esta rota
                # específica, nunca confirma sozinho.
                forecast_period_semantics_documented=True,
                # Execução real #3 (Seção 5/6-E) — mesmo operador VALUE já
                # documentado para a Representação A acima (propriedade da
                # linguagem Ingrid, não da coleção).
                ingrid_value_init_selection_documented=True,
                mapping_reference=(
                    'github.com/iridl/dlentries, entries/Models/NMME/NCEP-CFSv2/HINDCAST/MONTHLY/'
                    'index.tex (mesma fonte de source_reference, Rodada 5) — S documentado como grade '
                    'mensal de inicialização (forecast_reference_time), L documentado como grade de '
                    'lead "0.5 1 9.5" em meses (forecast_period), convenção padrão S/L do IRI Data '
                    'Library.',
                    'Operador Ingrid VALUE (iridl.ldeo.columbia.edu, sintaxe pública "ingrid"): '
                    '"select nearest grid point to value, dropping that dimension" — mesmo operador já '
                    'usado para X/Y nesta rota; propriedade do operador, não da coleção.',
                ),
            ),
        ),
    ),
    SistemaNMME(
        centre='ECCC', model_name='CanESM5', model_version='CanESM5 (uma fonte cita "CanESM5.1" — '
                                                              'divergência de sufixo não resolvida)',
        official_model_id=None,
        data_source='IRI Data Library (NMME collection), catálogo CanSIPS-IC3',
        data_url_template=None,   # path exato do HINDCAST não confirmado — ver notes
        data_access_status=DATA_ACCESS_UNCONFIRMED,
        current_operational_name='CanESM5',   # citado na página "About NMME" 08/jun/2025 (Seção 3)
        hindcast_start=1991, hindcast_end=2020,
        hindcast_members=20, realtime_members=None,   # ver notes — esquema de 4 dias pode dobrar p/ 40
        leads_available=(1, 2, 3, 4, 5, 6),
        grid_resolution='1° (documentado para o produto FORECAST do CanSIPS-IC3, mesma família — Seção '
                          '9; NÃO confirmado para o HINDCAST especificamente)',
        precip_variable='prec (documentado para o produto FORECAST do CanSIPS-IC3, mesma família — '
                          'Seção 9; o único path HINDCAST desta família realmente indexado mostra a '
                          'variável "sst", não "prec" — NUNCA assumir que o HINDCAST usa o mesmo nome '
                          'sem confirmação própria)',
        precip_units=None,
        hindcast_frequency='monthly',
        initialization_scheme='Real-time: relato (via busca, não confirmado de primeira mão) de que em '
                               '11/jun/2024 o tamanho do ensemble operacional passou de 20 para 40 '
                               'combinando o dia mais recente com inicializações de até 4 dias antes '
                               '— se verdadeiro, isso é um ensemble LAGGED no forecast, distinto do '
                               'hindcast de 20 membros/mês; precisa validação explícita antes do POC '
                               'real (Seção 14).',
        availability_status=STATUS_CANDIDATO,
        source_reference=(
            'WebSearch sobre climate-scenarios.canada.ca (ECCC, técnico CanSIPS) — bloqueado para '
            'WebFetch direto nesta sessão: "CanSIPSv3 uses a 30-year seasonal hindcast with 20 '
            'ensemble members for each model initialized near the start of each month from 1991 to '
            '2020."',
            'WebSearch sobre mudança de ensemble 20→40 (fonte não plenamente identificada nesta '
            'sessão — citada com reserva, ver notes).',
            'WebSearch sobre estrutura do IRI CanSIPS-IC3 FORECAST MONTHLY: variável prec, dimensões '
            'X/Y/L/M/S, 20 membros, grade 1°, leads mensais (Seção 9 — evidência estrutural da '
            'FAMÍLIA de modelo, não do endpoint HINDCAST específico).',
            _FONTE_NMME3_MANUAL, _FONTE_ABOUT_NMME_JUN2025,
        ),
        notes='Substitui CanCM4i (Seção 21 — nunca concatenar as duas séries). Path IRIDL exato do '
              'HINDCAST não confirmado — só foi visto o path de GEM5-NEMO (mesma família CanSIPS-IC3), '
              'com variável "sst" (não precipitação). Nunca assumir a URL/variável do produto FORECAST '
              'como válida para o HINDCAST (Seção 9) — marcado data_access_status=UNCONFIRMED até o '
              'POC real confirmar o endpoint específico do hindcast.',
        evidence={'hindcast_start': DOCUMENTED, 'hindcast_end': DOCUMENTED,
                   'hindcast_members': DOCUMENTED, 'realtime_members': UNCONFIRMED,
                   'model_version': UNCONFIRMED, 'data_url_template': UNCONFIRMED,
                   'grid_resolution': UNCONFIRMED, 'precip_variable': UNCONFIRMED,
                   'precip_units': UNCONFIRMED, 'initialization_scheme': UNCONFIRMED},
    ),
    SistemaNMME(
        centre='ECCC', model_name='GEM5.2_NEMO', model_version='GEM5.2-NEMO', official_model_id=None,
        data_source='IRI Data Library (NMME collection), catálogo CanSIPS-IC3',
        data_url_template='https://iridl.ldeo.columbia.edu/SOURCES/.Models/.NMME/.CanSIPS-IC3/'
                           '.GEM5-NEMO/.HINDCAST/.MONTHLY/ (grafia do path SEM o ".2" — ver notes; '
                           'variável indexada nesse path é "sst", não precipitação)',
        data_access_status=DATA_ACCESS_PARTIAL,   # endpoint do MODELO/HINDCAST conhecido, variável de
                                                    # precipitação NÃO confirmada nesse path específico
        current_operational_name='GEM5.2-NEMO',   # citado na página "About NMME" 08/jun/2025 (Seção 3)
        hindcast_start=1991, hindcast_end=2020,
        hindcast_members=20, realtime_members=None,
        leads_available=(1, 2, 3, 4, 5, 6),
        grid_resolution='1° (documentado para o produto FORECAST do CanSIPS-IC3, mesma família — Seção '
                          '9; NÃO confirmado para o HINDCAST especificamente)',
        precip_variable=None,   # path do HINDCAST mostrou "sst"; "prec" só confirmado no FORECAST (Seção 9)
        precip_units=None,
        hindcast_frequency='monthly',
        initialization_scheme='Mesma ressalva de CanESM5 sobre possível ensemble lagged de 4 dias no '
                               'forecast operacional (20→40) — não confirmada de primeira mão.',
        availability_status=STATUS_CANDIDATO,
        source_reference=(
            'WebSearch sobre climate-scenarios.canada.ca (ECCC) — mesma citação de CanESM5: hindcast '
            '20 membros/modelo, 1991-2020.',
            'WebSearch sobre catálogo IRIDL — título indexado ".Models/.NMME/.CanSIPS-IC3/.GEM5-NEMO/'
            '.HINDCAST/.MONTHLY/.sst" (variável mostrada foi sst, não precipitação — path real '
            'confirma o MODELO/HINDCAST, não a variável de precipitação).',
            'WebSearch sobre estrutura do IRI CanSIPS-IC3 FORECAST MONTHLY (Seção 9) — mesma nota de '
            'CanESM5: variável prec só confirmada no produto FORECAST, nunca assumida igual no HINDCAST.',
            _FONTE_NMME3_MANUAL, _FONTE_ABOUT_NMME_JUN2025,
        ),
        notes='Substitui GEM_NEMO (Seção 21 — nunca concatenar). Path IRIDL usa a grafia "GEM5-NEMO" '
              '(sem ".2"), enquanto a documentação textual da ECCC/CPC usa "GEM5.2-NEMO" — '
              'inconsistência de nomenclatura entre catálogo e documentação registrada, não resolvida; '
              'o POC real deve confirmar qual grafia o path realmente aceita. data_access_status='
              'PARTIAL (não CONFIRMED) porque falta a variável de precipitação confirmada NESSE path '
              'específico do hindcast (Seção 7/8) — o path em si aponta pro modelo certo, mas abrir '
              'esse path hoje mostraria sst, não precipitação, sem mais investigação.',
        evidence={'hindcast_start': DOCUMENTED, 'hindcast_end': DOCUMENTED,
                   'hindcast_members': DOCUMENTED, 'data_url_template': DOCUMENTED,
                   'realtime_members': UNCONFIRMED, 'grid_resolution': UNCONFIRMED,
                   'precip_variable': UNCONFIRMED, 'precip_units': UNCONFIRMED,
                   'initialization_scheme': UNCONFIRMED},
    ),
    SistemaNMME(
        centre='NOAA_GFDL', model_name='GFDL_SPEAR', model_version='SPEAR', official_model_id=None,
        data_source='IRI Data Library (NMME collection)',
        data_url_template='https://iridl.ldeo.columbia.edu/SOURCES/.Models/.NMME/.GFDL-SPEAR/'
                           '.HINDCAST/.MONTHLY/ (sufixo de variável de precipitação ainda não '
                           'identificado)',
        data_access_status=DATA_ACCESS_PARTIAL,   # endpoint do modelo/hindcast conhecido; variável de
                                                    # precipitação não confirmada nesse path
        current_operational_name=None,   # NÃO listado no conjunto "core" da página "About NMME" desde
                                          # 08/jun/2025 (Seção 3) — ver notes; isso não exclui o
                                          # candidato histórico/retrospectivo (Seção 5).
        hindcast_start=1991, hindcast_end=2020,
        hindcast_members=15, realtime_members=None,
        leads_available=(1, 2, 3, 4, 5, 6),
        grid_resolution=None, precip_variable=None, precip_units=None,
        hindcast_frequency='monthly', initialization_scheme=None,
        availability_status=STATUS_CANDIDATO,
        source_reference=(
            'WebSearch sobre título indexado do catálogo IRIDL: "Models NMME GFDL-SPEAR HINDCAST '
            '1991-2020 Monthly".',
            'WebSearch: "Ensemble Size: The SPEAR seasonal prediction ensemble has 15 members" e '
            '"As of February 6, 2021, SPEAR became part of the North American Multi-Model Ensemble '
            '(NMME)".',
            _FONTE_NMME3_MANUAL, _FONTE_ABOUT_NMME_JUN2025,
        ),
        notes='Substitui GFDL_FLOR (Seção 21 — sistema novo, não uma revisão do FLOR, nunca '
              'concatenar as duas séries). Entrou no NMME em 06/fev/2021 (data documentada). Seção 5 '
              '(correção pós-revisão): a página "About NMME" (08/jun/2025) não lista SPEAR no conjunto '
              '"core" operacional atual, mas o NMME3 manual documenta 15 membros/1991-2020 e outra '
              'página CPC de monitoramento ainda o inclui — status operacional atual E retrospectiva '
              'documentada são questões DISTINTAS; SPEAR permanece candidato histórico válido para o '
              'POC retrospectivo desta fase, o status operacional incerto não é motivo de exclusão.',
        evidence={'hindcast_start': DOCUMENTED, 'hindcast_end': DOCUMENTED,
                   'hindcast_members': DOCUMENTED, 'data_url_template': DOCUMENTED,
                   'realtime_members': UNCONFIRMED, 'grid_resolution': UNCONFIRMED,
                   'precip_variable': UNCONFIRMED, 'precip_units': UNCONFIRMED,
                   'initialization_scheme': UNCONFIRMED},
    ),
    SistemaNMME(
        centre='NCAR', model_name='NCAR_CCSM4', model_version='CCSM4', official_model_id=None,
        data_source='IRI Data Library (NMME collection) — padrão esperado, path exato não confirmado',
        data_url_template=None,
        data_access_status=DATA_ACCESS_UNCONFIRMED,
        current_operational_name='NCAR-CCSM4',   # citado na página "About NMME" 08/jun/2025 (Seção 3)
        hindcast_start=1991, hindcast_end=2020,
        hindcast_members=10, realtime_members=None,
        leads_available=(1, 2, 3, 4, 5, 6),
        grid_resolution=None, precip_variable='prate', precip_units=None,
        hindcast_frequency='monthly', initialization_scheme=None,
        availability_status=STATUS_CANDIDATO,
        source_reference=(
            'WebSearch sobre "Initialized Seasonal Prediction with the NCAR Models in NMME", Weather '
            'and Forecasting v.40 n.6 (2025), doi:10.1175/WAF-D-24-0123.1 (bloqueado para WebFetch '
            'direto): "the common period currently available for the three models [CCSM3, CCSM4, '
            'CESM1] ... 1991-2018" — cobre os 3 modelos NCAR juntos, período DIFERENTE do NMME3 manual '
            '(ver notes).',
            _FONTE_NMME3_MANUAL, _FONTE_ABOUT_NMME_JUN2025,
        ),
        notes='Seção 2 (correção pós-revisão): o NMME3 manual (citado pela revisão externa) documenta '
              '1991-2020 para os 7 candidatos, incluindo CCSM4 — usado aqui como a fonte principal do '
              'período (mais recente e mais específica ao produto NMME3 operacional). O artigo de 2025 '
              '(fonte independente desta sessão) cita 1991-2018 para o TRIO NCAR — um período '
              'ligeiramente mais curto e referente aos 3 modelos NCAR juntos, não necessariamente ao '
              'produto NMME3 hindcast isolado; essa divergência de 2 anos (2018 vs 2020) fica '
              'registrada, não resolvida — o POC real deve confirmar empiricamente qual janela o '
              'arquivo realmente cobre. precip_variable="prate" é conceitual (documentado no manual '
              'NMME3), nome real no arquivo específico continua UNCONFIRMED.',
        evidence={'hindcast_members': DOCUMENTED, 'hindcast_start': DOCUMENTED, 'hindcast_end': DOCUMENTED,
                   'precip_variable': DOCUMENTED, 'realtime_members': UNCONFIRMED,
                   'grid_resolution': UNCONFIRMED, 'precip_units': UNCONFIRMED,
                   'initialization_scheme': UNCONFIRMED, 'data_url_template': UNCONFIRMED},
    ),
    SistemaNMME(
        centre='NCAR', model_name='NCAR_CESM1', model_version='CESM1', official_model_id=None,
        data_source='IRI Data Library (NMME collection)',
        data_url_template='https://iridl.ldeo.columbia.edu/SOURCES/.Models/.NMME/.NCAR-CESM1/'
                           '.HINDCAST/.MONTHLY/ (sufixo de variável de precipitação ainda não '
                           'identificado — path visto na busca só mostrou a variável tsmx)',
        data_access_status=DATA_ACCESS_PARTIAL,   # endpoint do modelo/hindcast conhecido; variável de
                                                    # precipitação não confirmada nesse path (tsmx, não prec)
        current_operational_name='NCAR-CESM1',   # citado na página "About NMME" 08/jun/2025 (Seção 3)
        hindcast_start=1991, hindcast_end=2020,
        hindcast_members=10, realtime_members=None,
        leads_available=(1, 2, 3, 4, 5, 6),
        grid_resolution=None, precip_variable='prate', precip_units=None,
        hindcast_frequency='monthly',
        initialization_scheme='CESM1 usa CAM5 (atmosfera) — documentado (WebSearch sobre página NCAR) '
                               'que é uma evolução de CCSM4; nunca tratar CCSM4 e CESM1 como o mesmo '
                               'sistema (são dois candidatos distintos nesta lista, não uma sucessão '
                               'a concatenar).',
        availability_status=STATUS_CANDIDATO,
        source_reference=(
            'WebSearch sobre catálogo IRIDL — título indexado ".Models/.NMME/.NCAR-CESM1/.HINDCAST/'
            '.MONTHLY/tsmx" confirma que o path do MODELO/HINDCAST existe no catálogo (variável '
            'mostrada foi tsmx, não precipitação).',
            'WebSearch sobre "Initialized Seasonal Prediction with the NCAR Models in NMME" (2025) — '
            'mesma citação de período comum 1991-2018 usada em NCAR_CCSM4 (ver notes de NCAR_CCSM4 '
            'sobre a divergência com o NMME3 manual).',
            _FONTE_NMME3_MANUAL, _FONTE_ABOUT_NMME_JUN2025,
        ),
        notes='hindcast_members=10 e hindcast_start/end=1991/2020 agora DOCUMENTED via NMME3 manual '
              '(Seção 2 da correção) — antes desta rodada eram UNCONFIRMED, vindos só da especificação '
              'da tarefa. data_access_status=PARTIAL (não CONFIRMED): o path do hindcast é conhecido, '
              'mas a variável indexada nesse path é "tsmx" (temperatura), não precipitação — falta '
              'confirmar onde a variável de precipitação está dentro desse mesmo catálogo.',
        evidence={'hindcast_members': DOCUMENTED, 'hindcast_start': DOCUMENTED, 'hindcast_end': DOCUMENTED,
                   'data_url_template': DOCUMENTED, 'precip_variable': DOCUMENTED,
                   'realtime_members': UNCONFIRMED, 'grid_resolution': UNCONFIRMED,
                   'precip_units': UNCONFIRMED},
    ),
    SistemaNMME(
        centre='NASA', model_name='GEOS5v2', model_version='GEOS5v2', official_model_id=None,
        data_source='IRI Data Library (NMME collection) — padrão esperado, path exato não confirmado',
        data_url_template=None,
        data_access_status=DATA_ACCESS_UNCONFIRMED,
        # Seção 4 (correção pós-revisão): NUNCA afirmar GEOS5v2 == GEOS-S2S-2 automaticamente. A página
        # "About NMME" (08/jun/2025) cita "NASA-GEOS-S2S-2" no conjunto operacional core — registrado
        # aqui como o nome operacional ATUAL, mas como possível sucessão/nomenclatura diferente do
        # sistema retrospectivo documentado GEOS5v2, nunca como confirmação de equivalência. Se o
        # arquivo acessível no POC real vier identificado como "NASA_GEOS5v2", usar esse nome; se vier
        # como "GEOS-S2S-2", NÃO assumir equivalência sem metadata/documentação que prove que é a
        # mesma configuração (mesma lógica de versão da Seção 21, aplicada aqui como pergunta aberta,
        # não como fato resolvido).
        current_operational_name='NASA-GEOS-S2S-2 (possível sucessor de GEOS5v2 — NÃO confirmado como '
                                   'o mesmo sistema, ver notes/Seção 4)',
        hindcast_start=1991, hindcast_end=2020,
        hindcast_members=4, realtime_members=None,
        leads_available=(1, 2, 3, 4, 5, 6),
        grid_resolution=None, precip_variable='prate', precip_units=None,
        hindcast_frequency='monthly', initialization_scheme=None,
        availability_status=STATUS_CANDIDATO,
        source_reference=(
            'LaJoie (CPC), CDPW47, out/2022, slide 4: "NASA_GEOS5v2 4 members" (PDF lido de primeira '
            'mão nesta sessão).',
            _FONTE_NMME3_MANUAL, _FONTE_ABOUT_NMME_JUN2025,
        ),
        notes='hindcast_members=4 e hindcast_start/end=1991/2020 agora DOCUMENTED via NMME3 manual '
              '(coerente com LaJoie 2022, PDF lido de primeira mão). Seção 4/9 (correção pós-revisão): '
              'NUNCA tratar GEOS5v2 e GEOS-S2S-2 como o mesmo sistema sem confirmação — a página "About '
              'NMME" 08/jun/2025 cita "NASA-GEOS-S2S-2" no rol operacional atual, uma fonte secundária '
              'não-oficial encontrada na Rodada 1 já apontava essa mesma divergência de nome com outro '
              'nº de membros (10, não 4) — se forem sistemas DIFERENTES (sucessão real), misturar os '
              'dois seria o mesmo erro da Seção 21 para os outros modelos. Para a análise histórica '
              'usar SOMENTE a retrospectiva identificável no dataset como "NASA_GEOS5v2" — se o arquivo '
              'acessível vier como "GEOS-S2S-2", tratar como candidato NOVO a investigar, não como '
              'confirmação retroativa desta entrada.',
        evidence={'hindcast_members': DOCUMENTED, 'hindcast_start': DOCUMENTED, 'hindcast_end': DOCUMENTED,
                   'precip_variable': DOCUMENTED, 'model_version': UNCONFIRMED,
                   'realtime_members': UNCONFIRMED, 'grid_resolution': UNCONFIRMED,
                   'precip_units': UNCONFIRMED, 'initialization_scheme': UNCONFIRMED,
                   'data_url_template': UNCONFIRMED},
    ),
]


def sistema_por_nome(centre, model_name):
    for s in CATALOGO:
        if s.centre == centre and s.model_name == model_name:
            return s
    raise KeyError(f"sistema não encontrado no catálogo NMME: {centre}/{model_name}")


# ══════════════════════════════════════════════════════════════════════════
# Seção 8 (correção pós-revisão) — separa o catálogo CIENTÍFICO (todos os
# candidatos documentados, usado para o período comum/relatório) da
# lista EXECUTÁVEL do POC (só sistemas com endpoint+variável+dimensões
# confirmados o bastante para montar um request real sem adivinhar).
# Um modelo NUNCA sai do catálogo científico por faltar acesso — as duas
# listas são conceitos ortogonais (Seção 8: "nunca falhar em série
# apenas porque quatro modelos ainda têm endpoint não confirmado. Mas
# também nunca excluir um modelo por skill.").
# ══════════════════════════════════════════════════════════════════════════

def sistemas_poc_executaveis(catalogo=None):
    """Só entra na lista executável quem tem data_access_status=CONFIRMED
    — endpoint + variável + dimensões documentados E um subset real já
    aberto com sucesso (Seção 7/8, Seção 4 da Rodada 4). Nesta rodada,
    NENHUM dos 7 candidatos atinge essa barra — nem CFSv2, que subiu
    para POC_READY_DOCUMENTED (evidência forte o bastante para montar
    um request real, mas nenhum subset de fato aberto ainda) — resultado
    esperado e honesto desta etapa, não um bug."""
    catalogo = catalogo if catalogo is not None else CATALOGO
    return [s for s in catalogo if s.data_access_status == DATA_ACCESS_CONFIRMED]


def sistemas_poc_nao_executaveis(catalogo=None):
    """Complemento de sistemas_poc_executaveis — cada entrada com o
    motivo (data_access_status) para auditoria (Seção 8/13)."""
    catalogo = catalogo if catalogo is not None else CATALOGO
    return [s for s in catalogo if s.data_access_status != DATA_ACCESS_CONFIRMED]


def sistemas_poc_prontos_para_teste_real(catalogo=None):
    """Seção 4/13 da Rodada 4 — degrau abaixo de sistemas_poc_executaveis:
    inclui CONFIRMED **e** POC_READY_DOCUMENTED (evidência documental
    forte o bastante para autorizar uma tentativa real controlada, ainda
    que nenhum subset tenha sido aberto). É esta lista, não
    sistemas_poc_executaveis, que o workflow real deve consultar para
    decidir se libera uma tentativa de POC real (Seção 13)."""
    catalogo = catalogo if catalogo is not None else CATALOGO
    return [s for s in catalogo
            if s.data_access_status in (DATA_ACCESS_CONFIRMED, DATA_ACCESS_POC_READY_DOCUMENTED)]


# ══════════════════════════════════════════════════════════════════════════
# Seção 35-A — guardrail: nenhum campo numérico de período pode existir
# sem fonte citada (nunca "período inventado"). Seção 35-B — todo campo
# sem evidência explícita é tratado como UNCONFIRMED, nunca omitido
# silenciosamente.
# ══════════════════════════════════════════════════════════════════════════

def _validar_catalogo(catalogo):
    for s in catalogo:
        chave = f'{s.centre}/{s.model_name}'
        if (s.hindcast_start is not None or s.hindcast_end is not None) and not s.source_reference:
            raise ValueError(f"{chave}: hindcast_start/hindcast_end numérico sem source_reference — "
                              f"período não pode ser inventado (Seção 35-A).")
        for campo in ('hindcast_start', 'hindcast_end', 'hindcast_members'):
            if getattr(s, campo) is not None and campo not in s.evidence:
                raise ValueError(f"{chave}: campo {campo!r} tem valor numérico mas nenhum status na "
                                  f"matriz de evidência — todo valor precisa de status explícito "
                                  f"(Seção 7/35-B).")
        for campo, status in s.evidence.items():
            if status not in STATUS_VALIDOS:
                raise ValueError(f"{chave}: status de evidência inválido para {campo!r}: {status!r} "
                                  f"(precisa ser um de {sorted(STATUS_VALIDOS)}).")
        if s.availability_status not in (STATUS_CANDIDATO, STATUS_NAO_HOMOGENEO):
            raise ValueError(f"{chave}: availability_status inválido: {s.availability_status!r}.")
        if s.data_access_status not in DATA_ACCESS_STATUS_VALIDOS:
            raise ValueError(f"{chave}: data_access_status inválido: {s.data_access_status!r} "
                              f"(precisa ser um de {sorted(DATA_ACCESS_STATUS_VALIDOS)}).")
        if s.data_access_status == DATA_ACCESS_CONFIRMED and \
                (s.data_url_template is None or s.precip_variable is None):
            raise ValueError(f"{chave}: data_access_status=CONFIRMED exige data_url_template E "
                              f"precip_variable preenchidos (nunca confirmado por omissão, Seção 7/8).")
        if s.data_access_status == DATA_ACCESS_POC_READY_DOCUMENTED and \
                (s.member_level_dataset_path is None or s.precip_variable is None):
            raise ValueError(f"{chave}: data_access_status=POC_READY_DOCUMENTED exige "
                              f"member_level_dataset_path E precip_variable preenchidos (Seção 4 da "
                              f"Rodada 4 — 'documentado o bastante para testar' não é omissão).")
        for r in s.member_level_routes:
            rchave = f'{chave}/{r.data_backend}/{r.dataset_representation}'
            if r.data_backend not in SOURCE_BACKEND_VALIDOS:
                raise ValueError(f"{rchave}: data_backend inválido: {r.data_backend!r} (precisa ser "
                                  f"um de {sorted(SOURCE_BACKEND_VALIDOS)}).")
            if r.dataset_representation not in REPR_VALIDOS:
                raise ValueError(f"{rchave}: dataset_representation inválido: "
                                  f"{r.dataset_representation!r} (precisa ser um de {sorted(REPR_VALIDOS)}).")
            if r.status not in ROUTE_STATUS_VALIDOS:
                raise ValueError(f"{rchave}: status de rota inválido: {r.status!r} (precisa ser um de "
                                  f"{sorted(ROUTE_STATUS_VALIDOS)}).")
            if r.source_continuity_risk not in CONTINUITY_RISK_VALIDOS:
                raise ValueError(f"{rchave}: source_continuity_risk inválido: "
                                  f"{r.source_continuity_risk!r} (precisa ser um de "
                                  f"{sorted(CONTINUITY_RISK_VALIDOS)}).")
            if r.status == ROUTE_STATUS_POC_READY_DOCUMENTED_LEGACY and \
                    (r.dataset_path is None or r.variable_name is None):
                raise ValueError(f"{rchave}: status=POC_READY_DOCUMENTED_LEGACY exige dataset_path E "
                                  f"variable_name preenchidos (Seção 4/5, Rodada 5).")
            if r.status == ROUTE_STATUS_DISCOVERY_REQUIRED and r.dataset_path is not None:
                raise ValueError(f"{rchave}: status=DISCOVERY_REQUIRED nunca pode ter dataset_path "
                                  f"preenchido — isso seria inventar URL por adivinhação (Seção 12).")
            if not r.source_reference:
                raise ValueError(f"{rchave}: rota sem source_reference — nada pode ser registrado sem "
                                  f"citação (Seção 35-A aplicada às rotas).")
    return True


_validar_catalogo(CATALOGO)


def status_evidencia(sistema, campo):
    """Devolve o status de evidência de `campo` para `sistema` — UNCONFIRMED
    se o campo não tiver entrada explícita na matriz (Seção 35-B: nunca
    tratar ausência de registro como confirmação por omissão)."""
    return sistema.evidence.get(campo, UNCONFIRMED)


# ══════════════════════════════════════════════════════════════════════════
# Seção 20 — período comum só é calculado DEPOIS do catálogo estar
# pronto, nunca antecipado. Usa só sistemas com hindcast_start/end não
# nulos E status de evidência em {DOCUMENTED, EMPIRICALLY_CONFIRMED,
# DOCUMENTED_AND_CONFIRMED} — um valor UNCONFIRMED nunca entra no
# cálculo do período comum, mesmo que o campo não seja None (defensivo:
# nesta versão do catálogo isso não ocorre, já que todo valor não-None
# tem evidence != UNCONFIRMED por construção de _validar_catalogo, mas a
# checagem fica explícita para robustez a edições futuras).
# ══════════════════════════════════════════════════════════════════════════

def periodo_comum_hindcast(sistemas):
    """Deriva o período comum de hindcast entre os sistemas dados — NUNCA
    hardcoded (Seção 20). Devolve dict com common_start/common_end (None
    se não houver interseção viável ou se nenhum sistema tiver período
    defensável), `elegiveis`/`incompatibilidade` para auditoria, e
    `n_documented_models`/`n_empirically_confirmed_models` (Seção 2,
    correção pós-revisão — distinção explícita entre "documentado" e
    "confirmado empiricamente", nunca confundidos)."""
    elegiveis = {}
    incompatibilidade = {}
    inicios, fins = [], []
    n_empiricamente_confirmados = 0
    for s in sistemas:
        chave = f'{s.centre}/{s.model_name}'
        if s.hindcast_start is None or s.hindcast_end is None:
            incompatibilidade[chave] = 'hindcast_start/hindcast_end ausente (UNCONFIRMED) no catálogo'
            continue
        status_ini = status_evidencia(s, 'hindcast_start')
        status_fim = status_evidencia(s, 'hindcast_end')
        if UNCONFIRMED in (status_ini, status_fim):
            incompatibilidade[chave] = (f'hindcast_start/end presente mas evidence=UNCONFIRMED '
                                         f'({status_ini}/{status_fim}) — não entra no período comum.')
            continue
        if s.hindcast_start > s.hindcast_end:
            incompatibilidade[chave] = f'hindcast_start ({s.hindcast_start}) > hindcast_end ({s.hindcast_end})'
            continue
        elegiveis[chave] = [s.hindcast_start, s.hindcast_end]
        inicios.append(s.hindcast_start)
        fins.append(s.hindcast_end)
        if status_ini in (EMPIRICALLY_CONFIRMED, DOCUMENTED_AND_CONFIRMED) and \
                status_fim in (EMPIRICALLY_CONFIRMED, DOCUMENTED_AND_CONFIRMED):
            n_empiricamente_confirmados += 1

    if not inicios:
        return {'common_start': None, 'common_end': None, 'elegiveis': elegiveis,
                'incompatibilidade': incompatibilidade, 'status': UNCONFIRMED,
                'n_documented_models': 0, 'n_empirically_confirmed_models': 0,
                'n_elegiveis': 0, 'n_total': len(sistemas)}

    common_start, common_end = max(inicios), min(fins)
    if common_start > common_end:
        incompatibilidade['interseccao'] = (f'sem sobreposição real: common_start ({common_start}) > '
                                             f'common_end ({common_end})')
        return {'common_start': None, 'common_end': None, 'elegiveis': elegiveis,
                'incompatibilidade': incompatibilidade, 'status': UNCONFIRMED,
                'n_documented_models': len(elegiveis), 'n_empirically_confirmed_models': 0,
                'n_elegiveis': len(elegiveis), 'n_total': len(sistemas)}

    return {'common_start': common_start, 'common_end': common_end, 'elegiveis': elegiveis,
            'incompatibilidade': incompatibilidade, 'status': DOCUMENTED,
            'n_documented_models': len(elegiveis),
            'n_empirically_confirmed_models': n_empiricamente_confirmados,
            'n_elegiveis': len(elegiveis), 'n_total': len(sistemas)}


def tabela_catalogo(sistemas=None):
    import pandas as pd
    sistemas = sistemas if sistemas is not None else CATALOGO
    linhas = []
    for s in sistemas:
        linhas.append({
            'centre': s.centre, 'model_name': s.model_name, 'model_version': s.model_version,
            'current_operational_name': s.current_operational_name,
            'official_model_id': s.official_model_id, 'data_source': s.data_source,
            'data_url_template': s.data_url_template, 'data_access_status': s.data_access_status,
            'hindcast_start': s.hindcast_start, 'hindcast_end': s.hindcast_end,
            'hindcast_members': s.hindcast_members, 'realtime_members': s.realtime_members,
            'leads_available': ','.join(str(x) for x in s.leads_available),
            'grid_resolution': s.grid_resolution, 'precip_variable': s.precip_variable,
            'precip_units': s.precip_units, 'hindcast_frequency': s.hindcast_frequency,
            'initialization_scheme': s.initialization_scheme,
            'availability_status': s.availability_status,
            'evidence_hindcast_start': status_evidencia(s, 'hindcast_start'),
            'evidence_hindcast_end': status_evidencia(s, 'hindcast_end'),
            'evidence_hindcast_members': status_evidencia(s, 'hindcast_members'),
            'source_reference': ' | '.join(s.source_reference), 'notes': s.notes,
        })
    return pd.DataFrame(linhas)


def common_period_json(sistemas=None):
    sistemas = sistemas if sistemas is not None else CATALOGO
    return periodo_comum_hindcast(sistemas)
