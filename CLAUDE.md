# Dashboard Clima Operacional — Sinobras Florestal

Painel de previsão climática para 34 fazendas de eucalipto no Norte do
Tocantins (~48.000 ha). Projeta precipitação e balanço hídrico 12 meses à
frente, condicionado ao ENSO, para orientar a janela de plantio.

## Arquitetura

```
scripts/
  fetch_monthly_data.py    1. busca ERA5-Land do mês anterior (Open-Meteo)
  update_indices.py        2. índices oceânicos (PSL/NOAA + CPC)
  update_dashboard.py      3. SARIMAX x XGBoost, cenários, BH, gera o HTML
  verificar_dashboard.py   4. BARREIRA — falha se algo estiver inconsistente
  gerar_relatorio.py       5. relatório executivo .docx (2 páginas)
data/                      série, índices e resultados intermediários
docs/index.html            o dashboard (arquivo único, publicado no Pages)
docs/relatorio-executivo.docx
.github/workflows/
  update.yml                 dia 21, 12h BRT — pipeline completo
  publicar.yml               a cada push em docs/ — só republica o Pages
  indices_semanal.yml        seg. + dia 1-5, 12h BRT — wksst (4 regiões) + RONI
  lembrete_cpc_thursday.yml  2ª quinta-feira — abre Issue (não faz parsing)
  lembrete_iri_thursday.yml  3ª quinta-feira — abre Issue (não faz parsing)
```

O dashboard é **um único HTML** com dados embutidos em objetos JS
(`const D`, `const BH`, `const CPC_IRI`, `const SARIMAX_DATA`). O
`update_dashboard.py` reescreve esses objetos por regex. Não há build.

## Comandos

```bash
pip install -r requirements.txt

python scripts/update_dashboard.py     # regenera docs/index.html
python scripts/verificar_dashboard.py  # exit 1 se houver inconsistência
python scripts/gerar_relatorio.py      # regenera o .docx

python -m unittest tests.test_fetch_fallback -v   # testa o fallback CHIRPS→Open-Meteo, sem rede real
python -m unittest tests.test_update_indices -v   # testa parse_wksst (4 regiões) e parse_roni, sem rede real
```

**Sempre rode `verificar_dashboard.py` depois de qualquer alteração que
toque no HTML ou nos scripts que o geram.** É o teste de regressão do
projeto e roda em segundos.

## Armadilhas conhecidas

Estas causaram bugs reais em produção. Leia antes de mexer.

### 1. Eixo X — nunca rotacionar arrays já alinhados

O horizonte começa no **mês corrente** e vai 12 meses à frente
(`D.fc_labels`). Os cenários em `results[sc]['prec']` **já saem nesse
eixo**. Rotacioná-los "para alinhar" é o erro clássico: o ARM ficou 2
meses adiantado em relação à chuva que o alimenta, e o solo aparecia
enchendo em novembro com chuva menor que a ETP.

Regra: a ETP é rotacionada para o eixo (`ETP_HORIZ`), a precipitação não.
Nada de rotação depois de `solve_bh`.

Exceção: `BH.clim` na aba Clima usa jul→jun fixo, e `BH_CLIM_HYD` é o
mesmo dado pré-rotado para o mês corrente. São coisas diferentes.

### 2. `re.sub` global destrói campos vizinhos

`re.sub(r'labels:\[[^\]]+\]', ...)` também casa dentro de
`fc_labels:[...]` e de `clim: { labels: [...] }`. Isso apagou o eixo X de
todos os gráficos em produção.

Regra: ao editar o HTML por regex, **delimite a região primeiro**
(`html.find('indices:')` … `html.find('fc_labels:')`) e use `count=1`.

### 3. `CPC_IRI` é curado à mão e avança com o calendário

`CPC_IRI.seasons` é atualizado manualmente a cada emissão do CPC/IRI. Se
pedir um trimestre que `SARIMAX_DATA` não tem, o JS quebra com
`Cannot read properties of undefined` e a aba Comparativo não renderiza.

Por isso os trimestres são gerados dinamicamente a partir do horizonte
(13 deles, desde o mês anterior). O `verificar_dashboard.py` checa isso.

### 4. Não inventar dados de CPC/IRI

As probabilidades por trimestre alimentam o comparativo, o cenário
central e o relatório. Quando um centro não publica a tabela em texto
(o CPC só publica figura), use `null` e rotule a série como da emissão
anterior. Nunca estimar.

CPC usa ERSSTv5, IRI usa OISSTv2 — divergência de até 0,5 °C no Niño 3.4
é esperada e não é discordância.

### 5. Dois workflows publicando

`update.yml` e `publicar.yml` compartilham `concurrency: group: pages`
para não colidirem. Se adicionar outro workflow que publique, use o mesmo
grupo.

### 6. TSA e PDO do PSL vêm com sentinelas e atraso — nunca gravar zero

Os arquivos `tsa.data` e `pdo.data` do PSL (`psl.noaa.gov/data/correlation/`)
têm ano e os 12 valores mensais **na mesma linha**, com uma linha de
cabeçalho `anoIni anoFim` no topo — não é o formato "ano numa linha,
valores na seguinte". Cada arquivo usa sua própria sentinela para dado
ausente (`tsa.data` usa `-99.99`, `pdo.data` usa `-9.90`; outros podem usar
`-9.99`/`-999.9`). `parse_psl_anual` descarta as sentinelas conhecidas E,
como segunda barreira, qualquer valor com `abs(v) > 5` — uma anomalia
física nunca chega nessa magnitude, então isso pega sentinela nova ainda
não catalogada. Não confiar só na lista fixa nem só no limite físico.

Essas fontes também atrasam: TSA fica meses sem publicar o mês corrente,
PDO pode ficar sem nenhum dado do ano corrente. Quando falta valor real,
`fetch_monthly_data.py`/`update_indices.py` persistem — TSA usa o último
valor real disponível, PDO usa a média dos últimos 3 meses reais (nunca o
último valor isolado, que pode ser um mês atípico) — e sinalizam a origem
no log e nos avisos do `verificar_dashboard.py`. Persistência/estimativa
não é dado real: nunca gravar `0.0` para "ENSO neutro" quando na verdade
é "sem dado ainda". `0.0` é uma afirmação, não um vazio.

Mesma limitação vale para **precipitação CHC-Preliminar** (ver
`fetch_monthly_data.py`, camada intermediária entre CHIRPS Final e
Open-Meteo): quando o Final ainda não publicou o mês, grava-se o valor
Preliminary com `fonte='CHC-Preliminar'` — **não** `'CHIRPS'`, porque não
é o mesmo dado (Preliminary pode ser revisado na consolidação final).
Quando o Final publicar esse mês depois, o valor Preliminary **já
gravado não é substituído automaticamente** — ninguém reprocessa
`serie_subst.csv` sozinho. Se isso importar (ex.: o Preliminary e o
Final divergirem muito para um mês específico), é preciso reprocessar
esse mês manualmente, igual à persistência do PDO.

### 7. Nenhuma fonte de satélite é intercambiável com as estações — CHIRPS é a primária, ERA5 é fallback do fallback

`fetch_monthly_data.py` busca precipitação de mês ausente em duas
fontes, nesta ordem: **CHIRPS** (UCSB, via ClimateSERV) primeiro,
**Open-Meteo ERA5-Land** só se o CHIRPS não tiver o mês ainda
(`_chirps.py`/`_openmeteo.py`). Comparando os 540 meses de 1981-2025 em
que a série tem estação Sinobras, contra as duas fontes:

| mês | ERA5 razão média | ERA5 mediana | CHIRPS razão média | CHIRPS mediana |
|---|---|---|---|---|
| jan | 1,067 | 1,040 | 1,009 | 0,977 |
| fev | 0,927 | 0,902 | 0,957 | 0,931 |
| mar | 0,893 | 0,912 | 0,917 | 0,930 |
| abr | 0,862 | 0,856 | 1,027 | 1,007 |
| mai | 0,702 | 0,638 | 0,752 | 0,717 |
| jun | 0,275 | 0,109 | 1,048 | 0,849 |
| **jul** | **0,241** | **0,073** | **0,332** | **0,171** |
| ago | 0,368 | 0,134 | 0,976 | 0,822 |
| set | 0,664 | 0,527 | 1,280 | 0,958 |
| **out** | **1,042** | 0,947 | **1,181** | 1,155 |
| **nov** | **1,219** | 1,138 | **1,299** | 1,237 |
| **dez** | **1,293** | 1,214 | **1,308** | 1,269 |

Geral (razão mediana, todos os meses): ERA5 = 0,882, CHIRPS = **0,998**
— por isso a migração: CHIRPS praticamente não tem viés no agregado,
ERA5 subestima sistematicamente.

**Julho continua ruim nas duas fontes, e não é tratado à parte —
decisão deliberada, não descuido.** Razão mediana 0,073 (ERA5) / 0,171
(CHIRPS): ambas capturam mal a chuva convectiva rara e isolada desse
mês, provável limite físico de sensoriamento remoto ali, não defeito
de uma fonte específica (testado: corrigir julho por fator mediano
piora o RMSE do SARIMAX em vez de melhorar — ver histórico do commit
que teve essa investigação). Por que não vale corrigir:
- Impacto real é pequeno: a subestimativa de julho equivale a ~5,3
  mm/ano (0,31% do total anual da série) — irrelevante em qualquer
  cenário de plantio.
- ETP de julho é 107mm — o solo esgota (ARM crítico) tanto com 1mm de
  chuva quanto com 6mm; a diferença não muda a decisão.
- A amostra de julho (n=17, filtrando `prec_sinobras > 5mm`) contém só
  os meses anômalos de julho — julho típico é seco demais para passar
  no filtro, então a razão medida não representa "julho normal", é
  ruído de amostra pequena inflando o problema aparente.

**O viés que IMPORTA de verdade é out-nov-dez — e ele é o oposto:
as duas fontes SUPERESTIMAM.** ERA5 +18,5% (75mm no trimestre), CHIRPS
+26,3% (101mm no trimestre) acima do que as estações registram, mais
forte em novembro e dezembro. Esse é o trimestre onde a decisão de
plantio se concentra — um viés de superestimativa aqui é mais perigoso
que a subestimativa de julho, porque pode indicar solo mais úmido (ARM
maior, déficit menor) do que a realidade, levando a plantar cedo
demais. Se alguém for tratar viés de fonte no futuro, é aqui que vale
o esforço, não em julho.

**Não corrigir com fator fixo em nenhum mês.** O viés jun-ago do ERA5
varia mais de 3x entre décadas (razão mediana: 1981-90=0,22,
1991-00=0,03, 2001-10=0,06, 2011-20=0,14, 2021-25=0,19); o CHIRPS é
mais estável (0,63 a 0,86 nas 4 primeiras décadas) mas ainda assim não
é uma constante confiável. Testado: aplicar o fator mediano de julho
(0,073, ERA5) a jul/2026 (21,6mm → 297mm, quase 46x a climatologia)
piorou o RMSE do SARIMAX (56,2mm → 74,9mm) em vez de melhorar.

### 8. `data/fazendas.geojson` é um envelope único, não os 37 perímetros reais — e `buscar_prec_chirps_zonal` continua ferramenta manual

`data/fazendas.geojson` guardou por um tempo os 37 polígonos reais das
fazendas (nome, região, cluster_id). Foi **substituído** por um único
polígono sem identificação (`Fazendas_v2.kmz`, fornecido pela Sinobras;
área 85.020,5 ha — maior que a união dissolvida dos 37 perímetros reais,
48.737,3 ha, porque preenche reentrâncias entre fazendas; não é um
convex hull matemático, tem concavidades). Decisão deliberada: nenhum
arquivo do repositório deve permitir identificar fazenda individual.
`_farm_geometry.py` foi reescrito para essa geometria única — não há
mais `grupos_geograficos()`/`cluster_id`, só `poligono()` e
`anel_simplificado()`.

`_chirps.py` tem duas formas de buscar CHIRPS: `buscar_prec_chirps`
(ponto único, é o que `fetch_monthly_data.py` usa de verdade) e
`buscar_prec_chirps_zonal` (o envelope acima). Com uma geometria única,
**uma chamada ao ClimateSERV cobre tudo** — antes, com os 37 polígonos
em 7 grupos geograficamente desconectados, eram 7 chamadas por mês (a
API só aceita um anel simples por chamada), com a fragilidade de
"sucesso parcial por grupo". Essa fragilidade não existe mais.

Testado ao vivo com o envelope novo:
- jan/2024: zonal 301,9mm vs. ponto único 297,6mm — diferença de 1,4%
  (era 301,6mm com os 7 grupos do polígono real — a generalização não
  mudou o resultado zonal de forma perceptível).
- ago/2026 (via `buscar_prec_chc_preliminar_zonal`, zonal local por
  rasterstats): 7,5mm vs. 6,5mm no ponto único — 15% de diferença, mas
  só 1mm em valor absoluto (mês seco, denominador pequeno infla a
  razão; era o mesmo 7,5mm com a união dos 37 polígonos reais).

Diferença pequena em mm → **mantido ponto único no dia a dia**
(`buscar_prec_chirps` no pipeline automático, `fetch_monthly_data.py`).
O envelope/zonal fica reservado para os casos em que a defesa
metodológica importa (ex.: relatório executivo) ou reprocessamento de
histórico.

`buscar_prec_chirps_zonal` **continua fora do pipeline automático** —
mesmo com uma chamada só agora, isso ainda não foi testado sob os três
modos de falha da suíte (`tests/test_fetch_fallback.py`); só
`buscar_prec_chirps` (ponto único) tem essa cobertura hoje. Promover o
zonal a primário é uma decisão separada, ainda não tomada — passar a
suíte de falha por ele antes de considerar essa promoção.

A geometria simplificada usada nas chamadas (Douglas-Peucker adaptativo,
`_farm_geometry.anel_simplificado()`) tem um detalhe não óbvio:
`simplify()` garante anel válido **antes** de arredondar as coordenadas
pra 6 casas, mas o arredondamento pode reintroduzir auto-interseção —
sempre validar/reparar (`buffer(0)`) **depois** de arredondar, não antes
(já implementado, mas fácil de esquecer se alguém reescrever essa
função). Com o envelope atual (26 vértices) a simplificação nem chega a
entrar em ação — é salvaguarda para se a geometria for substituída por
algo mais detalhado no futuro.

### 9. Calendário de atualização ENSO — 2 fontes automatizáveis, 2 só lembrete; RONI ≠ ONI-aprox

**Investigado antes de escrever qualquer parser nesta seção** (testado
ao vivo, não assumido): a CPC publica "subsuperfície equatorial" só
como figura (`ensodisc.shtml`, `[Fig. 3]`/`[Fig. 4]`) — não existe
ascii equivalente em `/data/indices/`, testado com várias URLs prováveis,
todas 404. Registrado como lacuna, sem parser. SOI, ventos (850mb
Pacífico central/leste/oeste, zwnd200) e convecção (OLR) **existem**
como ascii estruturado (`soi`, `cpac850`, `epac850`, `wpac850`,
`zwnd200`, `olr` em `/data/indices/`), mas são **mensais, não
semanais** — `Readme.index.shtml` confirma: "updated around the 10th
of each month". Não foram automatizados aqui: os itens concretos desta
seção pediam só a extensão do wksst e o RONI — se algum dia fizer
sentido automatizar SOI/ventos/OLR também, é fetch mensal, não semanal,
e reaproveita o padrão de `parse_psl_anual` (mesmo layout "YEAR JAN FEV
... DEZ").

**`parse_wksst` tinha um bug real de silenciosa perda de dado**, achado
testando o arquivo ao vivo antes de estender pra 4 regiões: o layout
FORTRAN do `wksst9120.for` é de **coluna fixa**, não separado de forma
confiável por espaço — quando a anomalia é negativa, o sinal gruda
direto no número anterior sem espaço (`"20.6-0.1"` = SST 20.6, anomalia
-0.1, um token só). O parser antigo usava `line.split()` e exigia 9
tokens; com qualquer uma das 4 regiões negativa, a linha cai pra menos
de 9 tokens e era **pulada inteira**. Medido contra as 2.349 linhas do
arquivo (1981-2026): **73,6% têm essa concatenação em pelo menos uma
região**. Efeito real: sempre que a semana mais recente tivesse
qualquer anomalia negativa em qualquer uma das 4 regiões, a função
devolvia o valor de semanas atrás, sem aviso. Corrigido com slicing de
coluna fixa (`_WKSST_COLS`, blocos de 8 chars: `[0:4]`=SST, `[4:8]`=
anomalia), validado sem falha nas 2.349 linhas. `parse_wksst` agora
retorna as 4 regiões (Niño1+2, Niño3, Niño3.4, Niño4), não só Niño3.4.

**Achado operacional ao comparar antes/depois no dado real desta
sessão (11/09/2026):** o valor semanal registrado hoje **não mudou**
(02SEP2026, Niño 3.4 = +2,70°C nas duas versões) — a semana mais
recente tem as 4 anomalias positivas (El Niño forte em curso), caso em
que o parser antigo por coincidência funcionava. A prova de que o bug
era real, não hipotético: rodando os dois parsers sobre o mesmo arquivo
truncado até 11MAR2026 (a semana mais recente com concatenação
negativa, Niño3.4 = -0,1°C) o parser antigo devolve **09JUL2025
(+0,1°C)** — uma semana de **35 semanas atrás**, com o sinal da
anomalia errado — enquanto o novo devolve corretamente 11MAR2026
(-0,1°C). Ou seja: o bug não afetou o dado exibido hoje por sorte de
calendário (El Niño forte sem nenhuma região negativa), mas teria
afetado silenciosamente qualquer semana com La Niña ou transição de
fase — inclusive há só 6 meses.

**RONI (`RONI.ascii.txt`) e `D.now.oni` (nosso "ONI-aprox") são
métricas diferentes por desenho — nunca tratar como o mesmo número:**

| | RONI | ONI-aprox (`calc_oni`) |
|---|---|---|
| Fonte | CPC, oficial, `RONI.ascii.txt` | Calculado aqui, `sstoi.indices` |
| Cálculo | Niño 3.4 **menos** a tendência de aquecimento tropical global, depois padronizado | Média móvel simples de 3 meses do Niño 3.4 bruto |
| Cadência | Trimestral, publicada ~dia 10 do mês | Recalculado a cada fetch |
| Exemplo (mesmo trimestre) | JJA/2026 = **+1,36 °C** | jul/2026 (aprox. JJA) = **+2,03 °C** |
| Diferença | — | **0,67 °C**, mesmo trimestre, sem ser erro |

RONI roda sistematicamente mais baixo porque desconta o aquecimento
global de fundo — um El Niño "forte" pelo ONI-aprox pode não parecer
tão extremo no RONI, e isso é esperado, não discrepância de dado. Por
isso os dois têm cards separados no dashboard ("ONI aprox. (Niño 3,4,
3m)" e "RONI (oficial NOAA)") com nota cruzada em cada um, `const RONI`
é um objeto próprio (não um campo dentro de `now:{...}`, pra não
arriscar corromper os dois com um regex só — armadilha 2), e
`verificar_dashboard.py` reprova se o card RONI aparecer com o card ONI
ainda no rótulo ambíguo antigo ("ONI" puro, sem "aprox").

**Calendário final:**

| Cadência | O quê | Automação | Workflow |
|---|---|---|---|
| Semanal (seg.) | wksst 4 regiões | Completa (parser) | `indices_semanal.yml` |
| Dia 1-5 do mês | RONI | Completa (parser) | `indices_semanal.yml` |
| 2ª quinta-feira | CPC ENSO Diagnostic Discussion | Só lembrete (Issue) | `lembrete_cpc_thursday.yml` |
| 3ª quinta-feira | IRI Prediction Plume | Só lembrete (Issue) | `lembrete_iri_thursday.yml` |

"Dia 1-5" usa a faixa de dia-do-mês nativa do cron (`1-5` no campo de
dia) — não precisa de lógica de contagem, diferente de "Nª
dia-da-semana do mês" (2ª/3ª quinta-feira), que o cron não expressa
(campo dia-da-semana e dia-do-mês são combinados por OR, não AND).
Pra isso, os dois workflows de lembrete rodam **diário** e um passo
calcula `ordinal = (dia_do_mês - 1) // 7 + 1`, agindo só quando
`dia_da_semana == quinta E ordinal == 2 (ou 3)`.

Os workflows de lembrete **não têm parser nenhum** para o conteúdo das
páginas do CPC/IRI — é prosa, e um regex sobre prosa é exatamente o
tipo de bug frágil que este projeto já corrigiu várias vezes (armadilhas
1, 2, 6, 7 nasceram de parsing ingênuo de fonte que não era tão
estruturada quanto parecia). O produto final desses dois workflows é a
Issue com checklist — a extração continua manual.

## Convenções

- Português brasileiro em tudo: código, comentários, commits, saída.
- Números no padrão pt-BR (1.409 mm, +2,70 °C).
- Ano hidrológico jul→jun na aba Clima; horizonte móvel nas demais.
- Climatologia de referência: 1981–2025, média 1.714 mm/ano.
- CAD = 100 mm; "mês crítico" = ARM < 20 mm.

## Constantes

```python
CLIM_JAN_DEZ = [267.3,282.3,308.4,220.4,83.1,15.6,6.4,10.4,41.7,119.7,159.2,199.9]
ETP_JAN_DEZ  = [116,110,115,118,125,112,107,120,138,145,138,122]  # 1.466 mm/ano
FAZENDAS_LAT, FAZENDAS_LON = -7.80, -47.95
HOLDOUT = 36   # meses de holdout para escolher entre SARIMAX e XGBoost
```

## Ao propor mudanças

1. Rode `verificar_dashboard.py` antes e depois.
2. Se mexer em rotação de arrays, mostre a tabela mês a mês comparando
   rótulo do eixo com o valor, para conferência visual.
3. Mudanças em `update_dashboard.py` afetam o HTML inteiro — regenere e
   verifique, não edite o HTML à mão.
4. O que é gerado (`docs/`, `data/`) o robô sobrescreve todo dia 21.
   Correção de verdade vai sempre nos `scripts/`.
