# Fontes alternativas para o hindcast histórico do CFSv2 (sem depender do IRIDL legado)

## Por que este documento existe

O catálogo já registra (Seção 7 de `scripts/nmme_catalogo.py`) que o
IRIDL legado — a rota que a Fase 2C.1b acabou de validar
empiricamente — tem desligamento esperado até **31 de outubro de
2026, possivelmente antes** (fonte: página oficial "IRI Data Library
Sunset", citada abaixo). Isso é um risco operacional real para
qualquer extração histórica de longa duração (Fase 2C.2, Seção G) —
este documento investiga alternativas que não dependam desse serviço.

**Princípio seguido**: nunca tratar duas coleções como equivalentes só
porque usam o mesmo modelo CFSv2 (instrução explícita da tarefa). O
CFSv2 tem pelo menos 3 produtos distintos e não intercambiáveis:
(1) o **hindcast retrospectivo histórico** de 29 anos (1982–2011) usado
para calibração estatística — é este que a Fase 2C.2 precisa;
(2) o **forecast operacional em tempo real** (inicializações diárias,
1982–presente para a reanálise/análise, mas o forecast operacional
propriamente dito é mais recente); (3) o produto **NMME pooled/
harmonizado** (24-28 membros, mensal) que é uma curadoria específica do
NMME sobre o hindcast bruto — a mesma distinção que o catálogo já faz
entre Representação A (bruto) e B (harmonizada). Cada fonte abaixo é
avaliada quanto a **qual** desses produtos ela realmente oferece.

## Checklist de verificação (como cada afirmação abaixo foi confirmada)

- Fontes marcadas **EMPIRICALLY_CONFIRMED** foram acessadas de
  primeira mão nesta sessão (requisição HTTP real, resposta lida
  diretamente) — citado o comando/URL exato.
- Fontes marcadas **DOCUMENTED** vieram de busca (`WebSearch`), sem
  acesso de primeira mão ao servidor de origem — o domínio estava
  bloqueado pela política de rede deste ambiente
  (`EGRESS_BLOCKED`/`CONNECT tunnel failed`) em todos os casos citados
  abaixo. Marcadas assim explicitamente, nunca apresentadas como
  confirmadas.
- Nenhum número (contagem de membros, resolução, período) foi
  inventado — onde a fonte não permitiu confirmar um valor, o campo
  fica em branco/"não verificado" na tabela.

## Fontes investigadas

### 1. NOAA NCEI — arquivo histórico do CFSv2 (NOMADS/THREDDS)

- **Instituição**: NOAA National Centers for Environmental Information
  (NCEI), sucessora do NCDC.
- **Endereço oficial**: catálogo THREDDS em
  `https://www.ncei.noaa.gov/thredds/catalog/model/cfs.html`; acesso
  histórico também documentado via `nomads.ncdc.noaa.gov` (FTP/THREDDS).
- **Status de verificação**: **DOCUMENTED** — domínio `www.ncei.noaa.gov`
  bloqueado (`EGRESS_BLOCKED`) e `nomads.ncdc.noaa.gov` não resolveu
  (`ENOTFOUND`) nesta sessão; não foi possível abrir o catálogo THREDDS
  de primeira mão.
- **Disponibilidade do hindcast histórico**: segundo a página oficial
  do produto NCEI, citada pela busca, "o reforecast completo do CFS ao
  longo do período de 29 anos (1982–2011) fornece calibração e
  estimativas de skill estáveis para o novo sistema" — bate com o
  período nativo já documentado no catálogo deste projeto (S:
  1/jan/1982 a 1/dez/2010) para a rota IRIDL validada. Isso sugere que
  o NCEI é a fonte **primária/de origem** da qual o próprio IRIDL
  espelhava o hindcast — não uma cópia derivada.
  ["Completion of Climate Forecast System Version 2 Archive" (NCEI)](https://www.ncdc.noaa.gov/news/completion-climate-forecast-system-version-2-archive);
  ["Archiving New Climate Forecast System Data" (NCEI)](https://www.ncdc.noaa.gov/news/archiving-new-climate-forecast-system-data);
  ["Climate Forecast System (CFS)" — página de produto (NCEI)](https://www.ncei.noaa.gov/products/weather-climate-models/climate-forecast-system).
- **Variável/unidade de precipitação**: não verificado nesta sessão
  (dependeria de abrir o catálogo THREDDS ou um arquivo real).
- **Resolução espacial**: não verificado nesta sessão.
- **Identificação dos membros**: o arquivo completo é descrito como
  "864 terabytes", "o arquivo de dados de previsão mais abrangente
  disponível internacionalmente de um único sistema de previsão" —
  inclui reforecasts retrospectivos 1982–2011 e climatologias de
  calibração, mas a estrutura exata de membros por mês não foi
  confirmada de primeira mão.
  ["Completion of Climate Forecast System Version 2 Archive" (NCEI)](https://www.ncdc.noaa.gov/news/completion-climate-forecast-system-version-2-archive).
- **Formato**: GRIB2 (mesmo formato nativo do CFSv2, DOCUMENTED).
- **Automatização**: THREDDS normalmente expõe OPeNDAP (subconjunto
  remoto sem baixar o arquivo inteiro) — se confirmado, seria
  significativamente mais automatizável que o IRIDL Ingrid (que exige
  a sintaxe de seleção testada na Fase 2C.1b). **Não confirmado nesta
  sessão** por bloqueio de rede.
- **Prioridade recomendada**: **alta** — é a fonte mais provável de
  reproduzir exatamente a coleção já validada (mesmo período nativo
  citado), sendo o NOAA/NCEI a origem primária dos dados que o IRIDL
  também serve. Precisa de uma sessão com acesso de rede a
  `ncei.noaa.gov`/`nomads.ncdc.noaa.gov` para confirmar estrutura de
  arquivo, variável de precipitação e viabilidade de automação antes
  de qualquer decisão.

### 2. NOAA Open Data Dissemination / AWS S3 (`noaa-cfs-pds`)

- **Instituição**: NOAA, via o programa NODD (NOAA Open Data
  Dissemination), hospedado na AWS.
- **Endereço oficial**: `s3://noaa-cfs-pds` (bucket público, sem
  autenticação); página de registro em
  `https://registry.opendata.aws/noaa-cfs/`.
- **Status de verificação**: **EMPIRICALLY_CONFIRMED** — bucket
  consultado de primeira mão nesta sessão via HTTPS direto
  (`curl "https://noaa-cfs-pds.s3.amazonaws.com/?list-type=2..."`,
  API de listagem do S3, sem necessidade de credencial).
- **Disponibilidade do hindcast histórico**: **NÃO cobre 1982–2010**.
  Confirmado empiricamente: o prefixo `cfs.YYYYMMDD/` (dados do CFSv2
  operacional, 4 ciclos/dia — `00`/`06`/`12`/`18`) só começa em
  **2018-10-31**; buscas por prefixo `cfs.1982`, `cfs.1991`, `cfs.2000`,
  `cfs.2010`, `cfs.2011`, `cfs.2012`, `cfs.2015` devolveram 0 objetos.
  Existe também um prefixo `cdas.YYYYMMDD/` (análise/reanálise, não o
  hindcast retrospectivo). **Esta fonte não é um substituto para o
  período histórico que a Fase 2C.2 precisa** — é um produto diferente
  (forecast operacional recente), exatamente o tipo de confusão que a
  tarefa pediu para não cometer.
- **Variável/unidade de precipitação**: arquivos `flxf.<membro>.
  <inicialização>.<mês-alvo>.avrg.grib.grb2` — família "FLXF" (fluxos
  de superfície), a MESMA família do produto que a Representação A do
  catálogo já documenta como fonte do `PRATE` (`SOURCES/.../.FLXF/
  .surface/.PRATE/`) — forte indício de que a variável de precipitação
  está no mesmo arquivo, mas o conteúdo interno do GRIB2 não foi
  decodificado nesta sessão (sem ferramenta GRIB disponível) — variável
  exata **não confirmada**, só a família de produto.
- **Resolução espacial**: não verificado (dependeria de decodificar o
  GRIB2).
- **Identificação dos membros**: **confirmado** — 4 pastas
  `monthly_grib_01` a `monthly_grib_04` por ciclo de inicialização
  (4 ciclos/dia), consistente com o esquema operacional já documentado
  no catálogo ("múltiplas inicializações a cada 5 dias" é a leitura do
  eixo S do IRIDL; aqui a granularidade observada é diária × 4
  ciclos — mais fina que o pooled mensal do NMME).
- **Inicializações e horizontes**: cobertura 2018-10-31 até o presente
  (não medido o fim exato); cada `monthly_grib_NN` contém previsões
  mensais para vários meses-alvo à frente por inicialização
  (`avrg` = média mensal), sugerindo H1+ já presente na nomenclatura do
  arquivo (`<inicialização>.<mês-alvo>.avrg`).
- **Automatização**: **alta** — S3 é trivialmente automatizável (list +
  download por HTTPS puro, sem autenticação, sem rate limit conhecido
  documentado), e não depende do IRIDL nem de nenhuma sintaxe Ingrid.
- **Prioridade recomendada**: **baixa para o objetivo principal da Fase
  2C.2** (não tem o período histórico 1991–2010), mas **útil como fonte
  secundária automatizável** para estender a série além de 2010/2011 no
  futuro, se o projeto decidir avaliar anos recentes do CFSv2
  operacional — decisão fora do escopo desta tarefa.
  [Registro do dataset "NOAA Climate Forecast System (CFS)" (Registry of Open Data on AWS)](https://registry.opendata.aws/noaa-cfs/).

### 3. APDRC — Asia-Pacific Data Research Center (Universidade do Havaí)

- **Instituição**: APDRC, IPRC/SOEST, University of Hawaiʻi at Mānoa —
  **não é uma agência federal dos EUA**, é um centro de pesquisa
  universitário que espelha/redistribui dados de várias agências,
  incluindo NOAA.
- **Endereço oficial**: `http://apdrc.soest.hawaii.edu/datadoc/
  cfsv2_mon_ensemble_reforecast.php` (página de documentação);
  variáveis individuais servidas via ERDDAP/OPeNDAP
  (`apdrc.soest.hawaii.edu/erddap/griddap/...`).
- **Status de verificação**: **DOCUMENTED** — domínio bloqueado
  (`EGRESS_BLOCKED`) nesta sessão, não foi possível abrir a página de
  documentação nem inspecionar as variáveis servidas.
- **Disponibilidade do hindcast histórico**: chamado explicitamente de
  "CFSv2 monthly ensemble **reforecast**" pela própria APDRC — nome
  sugere ser o produto certo, mas o resumo da busca menciona cobertura
  "2010 a 2018" para pelo menos algumas variáveis (`bcld`, `wnd10m`,
  `z1000`, `hcld`) — **não bate** com o período nativo 1982–2010
  documentado para a coleção NMME. Pode ser (a) um subconjunto
  temporal diferente do reforecast completo, (b) uma imprecisão do
  resumo de busca, ou (c) uma coleção genuinamente diferente com o
  mesmo nome — **não resolvido, não verificado de primeira mão**.
  Precipitação (`prec`) especificamente não apareceu na amostra de
  variáveis retornada pela busca (só nuvens, vento, altura geopotencial)
  — **presença da variável de precipitação não confirmada**.
  ["APDRC Datadoc | CFS v2 monthly ensemble reforecast"](http://apdrc.soest.hawaii.edu/datadoc/cfsv2_mon_ensemble_reforecast.php).
- **Automatização**: ERDDAP/OPeNDAP costuma ser altamente
  automatizável (subconjunto remoto por URL, formatos NetCDF/CSV/JSON
  à escolha) — **se** a variável de precipitação e o período completo
  forem confirmados, seria uma fonte tecnicamente conveniente.
- **Prioridade recomendada**: **média, condicionada a verificação** —
  não descartar, mas não promover sem antes (a) confirmar que `prec`
  está disponível, (b) confirmar o período real coberto, (c) considerar
  que é uma fonte de terceiros (universidade), não a agência de origem
  — risco de continuidade não avaliado (diferente de um serviço
  federal, não há garantia formal de manutenção).

### 4. `forecast.ccsr.columbia.edu` (CCSR_BETA — já catalogado)

- **Instituição**: Columbia Climate School, Center for Climate Systems
  Research (CCSR) — a MESMA instituição por trás do IRI/IRIDL,
  construindo o serviço sucessor.
- **Endereço oficial**: `https://forecast.ccsr.columbia.edu`.
- **Status de verificação**: **DOCUMENTED**, já registrado no catálogo
  como `CCSR_BETA`/`DISCOVERY_REQUIRED` desde a Rodada 5 — esta sessão
  tentou reverificar via `WebFetch` (bloqueado,
  `EGRESS_BLOCKED`) e via `WebSearch` (sem acesso de primeira mão).
- **Novidade encontrada nesta sessão** (via busca, não confirmada
  diretamente): o serviço "está disponível para acesso público desde
  janeiro de 2026" e contém "hindcasts e forecasts de 4 dos 5 membros
  ativos do NMME... com o CFSv2 (o 5º) sendo adicionado gradualmente
  nas próximas semanas" — mesma informação qualitativa já registrada no
  catálogo (comunicação de 25/ago/2026 citada na Rodada 5: "early
  month samples" do CFSv2 já disponíveis, "pentad samples" a caminho).
  Não há evidência nova de que o CFSv2 já esteja **completo** nesse
  serviço — o catálogo permanece corretamente como `DISCOVERY_REQUIRED`
  (nenhuma promoção automática feita nesta tarefa, conforme instrução).
  ["Data Library Sunset" (IRI)](https://iri.columbia.edu/resources/data-library/sunset/).
- **Disponibilidade do hindcast histórico**: não determinado — mesmo
  quando o CFSv2 completo estiver disponível, não está confirmado se
  incluirá o reforecast 1982–2010 ou só o forecast operacional
  recente (mesma armadilha da fonte #2 acima).
- **Prioridade recomendada**: **monitorar, não agir agora** — é o
  sucessor natural, da mesma instituição, mas ainda em beta para
  CFSv2 especificamente. Reavaliar quando (a) o CFSv2 estiver
  anunciado como completo nesse serviço, e (b) o próprio ambiente de
  execução tiver acesso de rede a `forecast.ccsr.columbia.edu` para
  confirmar de primeira mão — nenhuma das duas condições está satisfeita
  hoje.

### 5. NOAA CPC FTP — formato CPT ensemble-mean (já catalogado, Rota A)

- **Instituição**: NOAA Climate Prediction Center (CPC).
- **Endereço oficial**:
  `ftp.cpc.ncep.noaa.gov/International/nmme/monthly_nmme_hindcast_in_cpt_format/`
  — já documentado no catálogo (`data_url_template` do `SistemaNMME`
  CFSv2) e já implementado em `scripts/nmme_cpc_cpt.py`.
- **Status de verificação**: `DOCUMENTED` (herdado da Rodada 3, não
  reverificado nesta sessão — domínio historicamente bloqueado para
  `WebFetch` direto neste ambiente).
- **Por que não resolve sozinho o problema desta investigação**: é
  **ensemble-MEAN**, não por membro — não permite reproduzir a coleção
  por-membro que o POC de infraestrutura validou (24 membros
  individuais). Útil como fonte auxiliar/comparação de ensemble mean,
  nunca como substituto direto da coleção member-level.
- **Prioridade recomendada**: manter como está (já implementada e
  catalogada); não é uma alternativa ao problema desta seção, é um
  produto complementar diferente.

## Comparação resumida

| Fonte | Instituição | Cobre 1982–2010 por membro? | Automatizável | Status de verificação |
|---|---|---|---|---|
| NCEI (NOMADS/THREDDS) | NOAA/NCEI | Provável (DOCUMENTED, não confirmado) | Provável (OPeNDAP, não confirmado) | DOCUMENTED |
| AWS S3 `noaa-cfs-pds` | NOAA (NODD) | **Não** (só 2018-10-31+, confirmado) | **Sim** (confirmado) | EMPIRICALLY_CONFIRMED |
| APDRC (Havaí) | Univ. Hawaiʻi (3º) | Incerto — período/variável não confirmados | Provável (ERDDAP, não confirmado) | DOCUMENTED |
| forecast.ccsr | Columbia CCSR | Desconhecido — CFSv2 ainda em rollout | Desconhecido | DOCUMENTED |
| CPC FTP (CPT) | NOAA/CPC | Sim, mas só ensemble-mean (não por membro) | Já implementado | DOCUMENTED (herdado) |
| IRIDL legado (rota validada) | Columbia IRI | **Sim, confirmado 1 mês (jan/2005)** | Sim (Ingrid, já implementado) | EMPIRICALLY_CONFIRMED (parcial) |

## Recomendação e próximo passo

Nenhuma fonte alternativa foi confirmada de primeira mão como capaz de
reproduzir a coleção validada (member-level, 1982–2010) — o bloqueio de
rede deste ambiente impediu verificar as duas candidatas mais
promissoras (NCEI/NOMADS e APDRC). **Não trocar de fonte de dados agora**
com base só em documentação de busca — seria repetir o mesmo erro que
a Fase 2C.1b corrigiu (confiar em documentação sem abrir um arquivo
real).

**Decisão que precisa de aprovação**: autorizar uma sessão futura com
acesso de rede liberado para `ncei.noaa.gov`/`nomads.ncdc.noaa.gov` (e,
se possível, `apdrc.soest.hawaii.edu`) para investigar essas duas
fontes de primeira mão — sem isso, a Fase 2C.2 (Seção G) deve prosseguir
inicialmente sobre o IRIDL legado já validado, ciente do prazo de
desligamento (31/10/2026) e com a migração de fonte como item de risco
em aberto, não resolvido por este documento.
