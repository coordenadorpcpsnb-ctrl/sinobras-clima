# Auditoria da referência observacional — extração histórica CFSv2 (fazendas)

**Relatório técnico — não calcula skill, não declara aptidão científica final, só reúne evidência e decisões pendentes.**

## Evidência de partida

- Extração histórica consolidada e aprovada: run 36238169299 — 240/240 origens, 34560 registros RAW.

## 1. Cobertura da série observacional

- Período exigido (1ª inicialização a H6 da última): 1991-01 → 2011-05 (245 meses).
- Meses ausentes no calendário: 0 (nenhum).
- Meses duplicados: 0 (nenhum).
- **Cobertura de calendário completa: True**

## 2. MERRA-2 vs. Estação Sinobras (combinações origem×lead)

- `SINOBRAS por fazenda (estimativa CHIRPS ZONAL — média dos pixels dentro do polígono de cada fazenda, informada pelo responsável pelos dados — NÃO pluviômetro confirmado; versão do CHIRPS, critério de inclusão de pixel e processamento temporal ainda não verificados documentalmente; README.md: baseline 1996-presente)`: 1095 combinações
- `MERRA-2 (reanálise NASA, README.md: baseline 1981-1995)`: 345 combinações

## 3. Combinações previsão×horizonte vs. observações mensais independentes

**Nunca confundir as duas contagens — são coisas diferentes.**

- Combinações origem×lead: 1440.
- Meses observados DISTINTOS usados como alvo: 245.
- Razão combinações/mês distinto: 5.88 (reuso por mês: mínimo 1, máximo 6, médio 5.88, mediano 6).
- 1440 combinações origem×lead compartilham apenas 245 meses observados distintos — cada mês é reaproveitado como alvo, em média, 5.9 vezes (a maioria dos meses centrais da janela é usada pelas 6 combinações possíveis: origem no próprio mês com H1, origem no mês anterior com H2, ..., origem 5 meses antes com H6). Uma futura estimativa de incerteza (intervalo de confiança, erro padrão) que tratasse as 1.440 combinações como observações independentes SUPERESTIMARIA o tamanho efetivo da amostra em até 6x — precisa considerar a dependência temporal (mesmo mês observado citado por várias previsões, além da autocorrelação natural da precipitação mês a mês) antes de qualquer cálculo de significância.

## 4. Documentação efetivamente disponível

- README.md linha 18/104: "Série histórica (MERRA-2 1981-1995 + Sinobras 1996-hoje)" — uma única linha, sem coordenadas, sem procedimento de agregação, sem menção a lacunas conhecidas, sem indicação de incerteza/qualidade por período.

### Identidade MERRA-2 vs. master_monthly.csv (achado numérico)

- Meses comparados (ano<=1995): 180, diferença absoluta máxima: 0.0033 mm — **idêntico numericamente: True** (fonte original comprovada: False).
- Meses comparados (ano>=1996): 360, diferença absoluta média: 37.15 mm, máxima: 252.24 mm — **diverge: True**.
- O trecho 'MERRA-2' (ano<=1995) de serie_subst.csv é numericamente idêntico a prec_reg=média(Araguaína, Colinas do Tocantins, Tocantinópolis) de master_monthly.csv — isso é um FATO verificado. O que continua NÃO COMPROVADO é a fonte ORIGINAL dessas 3 séries municipais: a igualdade numérica só mostra que 'prec' é a média dessas 3 colunas, nunca de onde elas vieram. O rótulo 'MERRA-2' do README é a única evidência disponível para essa origem, e não é verificável a partir deste repositório (nenhum script, coordenada ou registro de commit anterior documenta se são MERRA-2, outra reanálise, ou estações de superfície das 3 cidades). Tratar como 'MERRA-2 confirmado' seria uma afirmação não sustentada pelos dados disponíveis.

### Método de agregação dos registros SINOBRAS_new.csv (achado por leitura de código)

- Arquivo: `scripts/update_dashboard.py`
- Padrão verificado: `df_new.groupby(['ano','mes'])['prec_mm'].mean()` — encontrado: True
- Aplica-se a: incorporação de dados NOVOS (SINOBRAS_new.csv) a partir de quando este código passou a existir — nunca confirmado como o método usado para produzir o backfill histórico 1996-2010 (ver achado separado abaixo).
- Confirmado: a incorporação de SINOBRAS_new.csv usa df_new.groupby(['ano','mes'])['prec_mm'].mean() — média aritmética simples sobre QUANTAS estações/fazendas estiverem presentes naquele envio, sem exigência de número mínimo (1 fazenda reportando produziria o mesmo tipo de valor que 34 reportando) e sem reter o registro por estação individual — só a média sobrevive em serie_subst.csv (coluna 'prec'), a granularidade por fazenda é descartada. Isso descreve o procedimento ATUAL do código para dados NOVOS — uma possibilidade aberta pelo código, não uma contagem observada no histórico. No conjunto histórico efetivamente auditado (SINOBRAS.csv, 1996-2025 — ver achado 'nova_evidencia_sinobras_por_fazenda'), o número de fazendas reportando NUNCA variou: exatamente 34 identificadores em todos os 360 meses, sem exceção — a possibilidade de contagem variável é uma propriedade do procedimento ATUAL de incorporação de dados NOVOS, não do conjunto histórico já analisado. REGISTRADO (5ª rodada, item 4 da tarefa): `df_new.groupby(...).mean()` pondera cada fazenda IGUALMENTE — a série regional atual (data/serie_subst.csv) é a média aritmética simples das 34 estimativas zonais por fazenda, com o mesmo peso para cada uma, independentemente da área do polígono de cada fazenda. Uma fazenda pequena pesa o mesmo que uma grande nesta média — nunca ponderado pela área real (ver comparação de alternativas metodológicas em docs/nmme-fase2c2-auditoria-chirps-sinobras.md).

### Backfill histórico 1996-2010 precede o pipeline atual (achado via git)

- Primeiro commit do repositório com `data/serie_subst.csv`: `8a76a0fa`.
- Meses 1996-2010 já presentes nesse primeiro commit: 180/180 — **já completo: True**.
- O período 1996-2010 já estava COMPLETO (180/180 meses) no primeiro commit deste repositório (8a76a0fa) — ou seja, antes de qualquer execução do procedimento de incorporação hoje presente em scripts/update_dashboard.py. O método que de fato produziu esses valores históricos é DESCONHECIDO a partir deste repositório; não deve ser presumido igual ao procedimento atual só porque ambos dizem respeito a 'dados Sinobras'.

### Distribuição real das 345 combinações pré-1996 (corrigido)

- Total de combinações com procedência MERRA-2/3-municípios: 345.
- Por ano-alvo: {'1991': 57, '1992': 72, '1993': 72, '1994': 72, '1995': 72}.
- Por ano de origem: {'1991': 72, '1992': 72, '1993': 72, '1994': 72, '1995': 57}.
- Por horizonte (H_lead): {1: 60, 2: 59, 3: 58, 4: 57, 5: 56, 6: 55}.
- Distribuição real (não suposta): as 345 combinações pré-1996 estão razoavelmente distribuídas entre os 5 anos-alvo 1991-1995 (57 a 72 cada) e entre os 6 leads (55 a 60 cada) — NÃO concentradas nos leads mais longos das origens de 1991, como uma versão anterior deste relatório afirmava sem checar. A contagem menor em 1991 (57) e 1995 (57) é só efeito de borda: origens de 1991 com lead alto ainda miram 1991-1992 (dentro da janela), e origens de 1995 com lead alto já miram 1996 (fora do trecho MERRA-2, contadas em 'Estação Sinobras').

### Documentos necessários para comprovar a procedência histórica

Nenhum destes está disponível neste repositório hoje (ver achados acima):

- Dados originais por estação/fazenda individual para 1996-2025 — PARCIALMENTE obtido via SINOBRAS.csv (arquivo recebido, não incorporado a este repositório; ver achado 'nova_evidencia_sinobras_por_fazenda' e docs/nmme-fase2c2-auditoria-sinobras-por-fazenda.md). CORRIGIDO (4ª rodada): o responsável pelos dados informou que esses registros são estimativa CHIRPS por fazenda, não medição de campo (ver achado 'reinterpretacao_chirps'). Ainda faltam: a versão/metodologia de extração do CHIRPS, eventuais preenchimentos retrospectivos, e se alguma fazenda tem, além da estimativa, um pluviômetro físico real — nenhum dos três é verificável a partir desse arquivo isoladamente. Para o trecho pré-1996 (MERRA-2/3-municípios), este item continua integralmente ausente.
- Polígono de cada uma das 34 fazendas usado na extração zonal — hoje só o centroide agregado (lat=-7,80/lon=-47,95) é conhecido, nunca o polígono individual (SINOBRAS.csv também não traz coordenadas nem polígonos) — E o mapeamento de cada um dos 34 identificadores (FAZxx) para o respectivo polígono usado na extração (prioridade, dado o novo contexto zonal) e, SE alguma fazenda tiver de fato um pluviômetro físico, para esse instrumento; as 27 séries mensais numericamente distintas encontradas em SINOBRAS.csv não devem ser presumidas como 27 polígonos/conjuntos de pixels fisicamente independentes sem esse mapeamento — polígonos DIFERENTES podem cobrir o MESMO conjunto de pixels.
- Versão do produto CHIRPS usada para gerar SINOBRAS.csv (ex.: CHIRPS v2.0 final vs. preliminar) e a data de extração — ClimateSERV serve a versão CORRENTE do CHIRPS, que pode ter sido reprocessada desde a extração original; sem essa informação, uma reextração hoje pode não reproduzir os mesmos valores mesmo com a metodologia certa. PENDENTE (5ª rodada) — ainda não respondido pelo responsável pelos dados.
- Critério de inclusão de pixel na extração zonal e tratamento de pixels parcialmente interceptados pela borda do polígono (RESOLVIDO PARCIALMENTE, 5ª rodada: confirmado que a extração é ZONAL — média dos pixels dentro do polígono de cada fazenda, CHIRPS nativo 0,05° ~5,5km no equador — mas o critério exato de inclusão de um pixel na borda — centro dentro do polígono? qualquer sobreposição? fração de área ponderada? — e o tratamento de pixels parcialmente interceptados continuam PENDENTES). Determina diretamente se o compartilhamento de valores entre fazendas próximas (Seção 3/4 de docs/nmme-fase2c2-auditoria-sinobras-por-fazenda.md) é esperado por desenho ou uma coincidência a explicar.
- Processamento temporal usado (agregação diária→mensal: soma simples? cobertura mínima de dias por mês?) e as unidades originais antes de qualquer conversão (CHIRPS nativo é mm/dia; SINOBRAS.csv está em mm/mês, inteiros) — necessário para confirmar que a conversão não introduziu arredondamento sistemático. PENDENTE (5ª rodada) — ainda não respondido pelo responsável pelos dados.
- Períodos de operação de cada estação/fazenda (quando cada uma começou/parou de medir, e quaisquer interrupções de manutenção) — necessário para saber se a amostra por mês é estável ao longo do tempo ou varia por entrada/saída de estações. Nota (4ª rodada): 'operação' aqui deveria ler-se como 'quando a extração CHIRPS por fazenda começou', não 'quando um pluviômetro foi instalado' — a empresa não tem pluviômetro em todas.
- Identificação da fonte ORIGINAL das 3 séries municipais (Araguaína/Colinas do Tocantins/Tocantinópolis) usadas no período 1981-1995: se são de fato extração MERRA-2 (e, se sim, em qual ponto de grade/data de extração), ou outra reanálise, ou estações de superfície de cada cidade — permanece NÃO COMPROVADA (item 7 da 4ª rodada), sem mudança em relação às rodadas anteriores.
- Coordenadas exatas (ou o ponto/célula de grade) usadas para extrair essas 3 séries municipais, sejam elas de reanálise ou de estação.
- O script, planilha ou processo — mesmo que externo a este repositório — que gerou o backfill 1996-2010 de serie_subst.csv antes do primeiro commit ('Create index.html'), já que o procedimento hoje em scripts/update_dashboard.py não pode ser presumido como o mesmo (ver achado 'dados_1996_2010_precedem_pipeline_atual').
- Documentação do número mínimo de estações/fazendas (se algum) considerado necessário para publicar um valor mensal válido — hoje o código aceita qualquer contagem >=1 sem distinção.
- Explicação para os 2 grupos de identificadores com série mensal completa idêntica encontrados em SINOBRAS.csv (FAZ02/FAZ03/FAZ04/FAZ05/FAZ08/FAZ09/FAZ19 e FAZ07/FAZ15) — REFINADO (5ª rodada): a extração é ZONAL, então a hipótese mais parcimoniosa é polígonos DIFERENTES de fazendas vizinhas cobrindo o MESMO conjunto de pixels CHIRPS (não mais 'pixel único compartilhado'), ao lado de pluviômetro físico compartilhado (se existir), replicação administrativa, ou preenchimento — nenhuma comprovada, e nunca afirmar que série idêntica implica polígono idêntico (ver docs/nmme-fase2c2-auditoria-sinobras-por-fazenda.md, Seção 3/4, e docs/nmme-fase2c2-auditoria-chirps-sinobras.md).

### Nova evidência: SINOBRAS.csv (registros por fazenda, 1996-2025)

- Arquivo: `SINOBRAS.csv` — SHA-256 `ad44fa16d9bdba16fb6550ab1ff3eabaefdbc6dfffee0a6afc19e6c5a931ca1a` — não incorporado a este repositório.
- Período coberto: 1996-01 → 2025-12 (12240 registros, 34 identificadores).
- Integridade estrutural completa: True. Reconciliação com data/serie_subst.csv completa: True.
- Séries mensais numericamente distintas: 27 (de 34 identificadores) — grupos idênticos: [['FAZ02', 'FAZ03', 'FAZ04', 'FAZ05', 'FAZ08', 'FAZ09', 'FAZ19'], ['FAZ07', 'FAZ15']].
- Relatório completo e reprodutível: `docs/nmme-fase2c2-auditoria-sinobras-por-fazenda.md` (gerado por `scripts/nmme_auditoria_sinobras_por_fazenda.py`).
- A agregação numérica histórica de 1996-01 a 2025-12 foi REPRODUZIDA de forma independente a partir de 12240 registros por fazenda (34 identificadores, SHA-256 `ad44fa16d9bdba16fb6550ab1ff3eabaefdbc6dfffee0a6afc19e6c5a931ca1a`) — reconciliação 100% completa com data/serie_subst.csv (detalhamento completo em docs/nmme-fase2c2-auditoria-sinobras-por-fazenda.md). Confirmado (3ª rodada): o arquivo tem EXATAMENTE 34 registros em TODOS os 360 meses, sem exceção — a possibilidade de número variável de fazendas reportando é uma propriedade do procedimento ATUAL de incorporação de dados NOVOS (achado 'agregacao_sinobras_no_codigo' acima), nunca observada neste conjunto histórico. Isso muda o item 1 da lista de documentos necessários abaixo: dados originais por estação/fazenda individual foram PARCIALMENTE obtidos para 1996-2025 — o trecho pré-1996 (MERRA-2/3-municípios) continua integralmente sem essa evidência. A mesma auditoria independente também encontrou só 27 séries mensais numericamente distintas entre os 34 identificadores — 2 grupos compartilham a mesma série completa ([['FAZ02', 'FAZ03', 'FAZ04', 'FAZ05', 'FAZ08', 'FAZ09', 'FAZ19'], ['FAZ07', 'FAZ15']]). CORRIGIDO (4ª rodada): esses registros NÃO são medição de campo — o responsável pelos dados informou que são estimativa CHIRPS por fazenda (ver 'reinterpretacao_chirps' abaixo). O que CONTINUA sem comprovação: a versão/metodologia de extração do CHIRPS, eventuais preenchimentos retrospectivos, e se os identificadores agrupados representam pixel CHIRPS compartilhado (hipótese mais parcimoniosa dado o novo contexto), pluviômetro físico compartilhado, ou replicação administrativa de fazendas distintas — nenhuma dessas hipóteses deve ser presumida (ver docs/nmme-fase2c2-auditoria-sinobras-por-fazenda.md e docs/nmme-fase2c2-auditoria-chirps-sinobras.md).

### Reinterpretação CHIRPS (correção — 4ª rodada, 2026)

- Classificação anterior (até a 3ª rodada): 'Estação Sinobras (leitura direta de campo, README.md: baseline 1996-presente)' — PROCEDENCIA_ESTACAO_SINOBRAS em scripts/nmme_piloto_historico.py, commits 12cadbe a f731937
- Classificação corrigida (4ª rodada): 'SINOBRAS por fazenda (estimativa CHIRPS, informada pelo responsável pelos dados — NÃO pluviômetro confirmado...)' — commit 94ac463
- Classificação refinada (5ª rodada — extração ZONAL confirmada): `SINOBRAS por fazenda (estimativa CHIRPS ZONAL — média dos pixels dentro do polígono de cada fazenda, informada pelo responsável pelos dados — NÃO pluviômetro confirmado; versão do CHIRPS, critério de inclusão de pixel e processamento temporal ainda não verificados documentalmente; README.md: baseline 1996-presente)`
- Fonte da correção: informação recebida do responsável pelos dados — comunicação direta ao operador desta auditoria, não um documento técnico revisado por este módulo.
- Verificada documentalmente por este módulo: False. Empresa possui pluviômetro em todas as fazendas: False.
- Investigação dedicada: `docs/nmme-fase2c2-auditoria-chirps-sinobras.md`.
- Esta é uma CORREÇÃO de classificação, registrada explicitamente — a afirmação anterior não foi apagada, só substituída e documentada aqui como incorreta. O responsável pelos dados informou que SINOBRAS.csv (1996-2025) contém estimativas extraídas do CHIRPS por fazenda, não leituras diretas de pluviômetro — a empresa não tem pluviômetro em todas as fazendas. REFINADO (5ª rodada): a extração é ZONAL — média dos pixels CHIRPS dentro do POLÍGONO de cada fazenda, não um ponto/coordenada única. Isso é informação de terceiros, ainda NÃO verificada documentalmente por este módulo (nenhum documento técnico de extração foi apresentado) — tratada como acionável para efeitos de classificação (o rótulo muda), mas não como fato cientificamente comprovado (a aptidão científica continua bloqueada por este motivo, ver achado de aptidão abaixo). Ver docs/nmme-fase2c2-auditoria-chirps-sinobras.md para a investigação dedicada: comparação com data/chirps_1981_2025.csv (CHIRPS de metodologia CONHECIDA, ponto único, já extraído neste repositório), lista de informações ainda necessárias para reproduzir a extração ZONAL de SINOBRAS.csv (versão do CHIRPS, polígonos por fazenda, critério de inclusão de pixel, tratamento de pixel parcialmente interceptado, processamento temporal), comparação de 3 alternativas metodológicas para a referência regional, e avaliação de viabilidade de uma referência CHIRPS consistente para 1991-2011.

### Coordenadas dos 3 municípios do período MERRA-2 (1981-1995)

- Araguaína/Colinas do Tocantins/Tocantinópolis — nenhuma coordenada, nenhum script de geração e nenhum registro de commit anterior ao primeiro commit do repositório ("Create index.html") documentam a origem dessas 3 colunas em data/master_monthly.csv. Não verificável a partir deste repositório — não estimado aqui para não inventar dado que a tarefa pede para nunca supor.

### Lacunas e qualidade documentadas previamente

- Nenhuma lacuna conhecida do período 1991-2010 está documentada em README.md/CLAUDE.md — as armadilhas documentadas em CLAUDE.md (6/7) cobrem viés de fonte satelital (CHIRPS/ERA5, período recente) e persistência de índices oceânicos, nunca a série de precipitação pré-2011 usada nesta auditoria.

## 5. Correspondência espacial

- Distância REAL grade CFSv2 ↔ centroide das fazendas (lida do RAW aprovado): **22.91 km**.
- Referência anterior (São Bento do Tocantins, piloto): 198.0 km — melhoria de 175.1 km com o centroide das fazendas.
- Observação pré-1996: ÁREA difusa e não documentada — média de 3 municípios (Araguaína/Colinas do Tocantins/Tocantinópolis), coordenadas não verificáveis a partir do repositório.
- Observação pós-1996: ÁREA — média de EXATAMENTE 34 fazendas em todos os 360 meses de 1996-2025 (achado verificado, ver 'nova_evidencia_sinobras_por_fazenda'), dentro do envelope de ~85.020,5 ha (CLAUDE.md armadilha 8), não um ponto único. A possibilidade de um número VARIÁVEL de fazendas reportando, sem mínimo exigido, é uma propriedade do procedimento ATUAL de incorporação de dados NOVOS (ver achado de documentação) — nunca observada no conjunto histórico já auditado. CORRIGIDO (4ª rodada): esta 'área' não é uma malha de pluviômetros — o responsável pelos dados informou que cada fazenda tem uma estimativa CHIRPS, não necessariamente um instrumento (ver achado 'reinterpretacao_chirps'). REFINADO (5ª rodada): a extração é ZONAL — cada fazenda é representada pela média dos pixels CHIRPS dentro do seu PRÓPRIO POLÍGONO, não um ponto/pixel único; a série regional atual (data/serie_subst.csv) é a média aritmética simples dessas 34 estimativas zonais, com peso IGUAL para cada fazenda, independente da área do seu polígono — ver achado 'agregacao_sinobras_no_codigo'. A 'área' real representada é a UNIÃO dos 34 polígonos, ainda desconhecidos.
- **Descasamento de suporte espacial**: A previsão do CFSv2 é 1 valor por célula de grade (~1° ~ 100km de lado); a observação é uma média sobre uma área (município triplo ou envelope de fazendas), nunca um ponto equivalente à célula de grade — mesmo com a distância melhorada (~23km em vez de 198km), comparar os dois exige decidir explicitamente se a média de área é um proxy aceitável do valor pontual de grade, o que este módulo NÃO decide. REFINADO (5ª rodada, item 7 da tarefa): com a extração ZONAL confirmada para 1996-2025, a área pós-1996 tem um significado geométrico mais preciso — a UNIÃO dos polígonos das 34 fazendas (contando cada parcela espacial uma única vez, não a soma das 34 áreas, que pode superestimar se houver sobreposição) — mas essa união ainda não pode ser calculada (polígonos ausentes). O protocolo de comparação com o CFSv2 precisa decidir explicitamente se compara a célula de grade contra essa união de polígonos (mais correto, ainda não calculável) ou contra o centroide agregado (o que é feito hoje, um proxy grosseiro da área real) — nenhuma escolha feita aqui.
- **Necessidade de coordenadas individuais**: Item 7 (3ª/4ª/5ª rodada) — a nova evidência SINOBRAS.csv (achado da Seção 4, EVIDENCIA_SINOBRAS_POR_FAZENDA) identifica 27 séries mensais distintas entre os 34 identificadores de fazenda, mas nenhuma coordenada individual — nem no arquivo recebido, nem em qualquer outro arquivo deste repositório (CLAUDE.md armadilha 8: data/fazendas.geojson foi deliberadamente substituído por um envelope único sem identificação por fazenda). CORRIGIDO/REFINADO: com a extração ZONAL confirmada (achado 'reinterpretacao_chirps'), são NECESSÁRIAS três coisas: (1) o POLÍGONO usado para extrair a estimativa CHIRPS zonal de cada um dos 34 identificadores FAZxx — não um ponto único; (2) a versão do CHIRPS, o critério de inclusão de pixel e o tratamento de pixel parcialmente interceptado (ver docs/nmme-fase2c2-auditoria-chirps-sinobras.md); e (3), SE alguma fazenda tiver de fato um pluviômetro físico, o mapeamento correspondente — a empresa não tem pluviômetro em todas as fazendas. As 27 séries mensais numericamente distintas são um FATO sobre os dados, NUNCA uma contagem de locais físicos OU conjuntos de pixels CHIRPS independentes — não presumir que elas correspondem a 27 polígonos fisicamente independentes: polígonos DIFERENTES de fazendas vizinhas podem cobrir o MESMO conjunto de pixels e produzir a mesma média zonal; sem o mapeamento identificador→polígono, o número real de conjuntos de pixels distintos permanece desconhecido. Sem essas informações, o suporte espacial da observação — a UNIÃO dos polígonos das 34 fazendas, não um único centroide nem um ponto — não pode ser comparado à célula de grade do CFSv2 com precisão. A distância de 22,91km acima continua sendo a distância de UM ponto agregado, nunca da área real coberta pelos polígonos (detalhamento completo em docs/nmme-fase2c2-auditoria-sinobras-por-fazenda.md e docs/nmme-fase2c2-auditoria-chirps-sinobras.md).

## 6. Alinhamento temporal H1-H6

- Combinações origem×lead auditadas: 1440/1440.
- `mapping_status=OK` em todas: True (1440 confirmadas).
- H1 = mês da própria inicialização (confirmado nos dados persistidos): True.
- Mês-alvo mais distante (H6 da origem 2010-12): 2011-05.

## 7. Períodos utilizáveis

- Combinações disponíveis, não substitutas (nunca CHC-Preliminar/ERA5) e com qualidade OK: 1440/1440.
  - `SINOBRAS por fazenda (estimativa CHIRPS ZONAL — média dos pixels dentro do polígono de cada fazenda, informada pelo responsável pelos dados — NÃO pluviômetro confirmado; versão do CHIRPS, critério de inclusão de pixel e processamento temporal ainda não verificados documentalmente; README.md: baseline 1996-presente)`: 1095
  - `MERRA-2 (reanálise NASA, README.md: baseline 1981-1995)`: 345
- A procedência rotulada MERRA-2 (achado da Seção 4: fonte original não comprovada — é, numericamente, a média de 3 municípios) só se aplica a alvos com ano<=1995: 345/1.440 combinações, razoavelmente distribuídas entre 1991-1995 e entre os 6 leads (ver Seção 4, distribuição real pré-1996) — nunca concentradas num único trecho.
- **Recomendação**: Reportar qualquer avaliação futura SEPARADAMENTE para alvos MERRA-2/3-municípios (ano<=1995) e alvos Estação Sinobras (ano>=1996) — nunca uma métrica agregada única que misture as duas procedências, dado que já divergem em magnitude (achado da Seção 4, diff média >1mm/mês pós-1996) e em suporte espacial (Seção 5).

## 8. Protocolo estatístico proposto (NÃO calculado nesta tarefa)

Proposta para uma etapa FUTURA e SEPARADA — nenhum destes cálculos foi executado aqui.

### 8.1 Determinístico
- Viés médio (bias) e MAE do ensemble mean por lead (H1-H6), separadamente para alvos MERRA-2/3-municípios (ano<=1995) e Estação Sinobras (ano>=1996) — nunca agregados entre si (achado da Seção 4: já divergem em magnitude).
- Correlação de Pearson/Spearman entre ensemble mean e observação, por lead.

### 8.2 Probabilístico
- CRPS (Continuous Ranked Probability Score) do ensemble de 24 membros por lead.
- Brier Skill Score (BSS) para terços de probabilidade (abaixo/normal/acima), com a climatologia de referência definida na Seção 8.3 como benchmark.
- Diagrama de confiabilidade (reliability diagram) por lead, para checar calibração do ensemble.
- Qualquer estimativa de incerteza estatística (intervalo de confiança, erro padrão, significância) deve tratar as combinações como dependentes, não como amostra i.i.d. — ver Seção 3 (1.440 combinações compartilham só 245 meses observados distintos).

### 8.3 Protocolo de validação e climatologia de referência — duas abordagens, não escolhidas aqui

Apresentadas separadamente, com as diferenças entre elas — este módulo NÃO escolhe um protocolo definitivo; a escolha fica para a etapa futura de cálculo de skill.

**(a) Validação retrospectiva com exclusão do ano avaliado (leave-one-year-out, LOYO).** Usa o período completo disponível (ex.: 1981-2010) menos o próprio ano-alvo Y para montar a climatologia de referência de cada avaliação. Mais simples e auditável (o conjunto de anos de cada climatologia é sempre "todos menos Y"), mas PODE incluir anos POSTERIORES a Y na climatologia — informação que, na data real de emissão da previsão de Y, ainda não existia. Isso não é vazamento literal treino/teste (a climatologia não usa o próprio valor de Y), mas é uso de informação futura em relação ao momento da previsão, e precisa ser declarado explicitamente se esta abordagem for escolhida.

**(b) Validação com janela temporal expansível, só informação anterior à emissão.** Para avaliar o alvo do ano Y, usa só a climatologia calculada com anos < Y — nunca anos posteriores. Operacionalmente mais realista (reproduz o que estaria disponível no momento real da previsão), mas sofre de amostra pequena ou ZERO nos primeiros anos da janela 1991-2010 quando restrita a registros Sinobras (>=1996) — ver análise abaixo.

- Combinações origem×lead auditadas: 1440.
- Anos de origem avaliados: 1991-2010.
- Anos de climatologia Sinobras-apenas (>=1996) disponíveis por ano de origem, sob a abordagem (b): {1991: 0, 1992: 0, 1993: 0, 1994: 0, 1995: 0, 1996: 0, 1997: 1, 1998: 2, 1999: 3, 2000: 4, 2001: 5, 2002: 6, 2003: 7, 2004: 8, 2005: 9, 2006: 10, 2007: 11, 2008: 12, 2009: 13, 2010: 14}.
- Anos de origem com ZERO anos prévios disponíveis: 6. Anos de origem com menos de 5 anos prévios: 10.
- Na abordagem (b) — janela expansível, só informação anterior à emissão —, uma climatologia restrita a registros Sinobras (>=1996) teria ZERO anos prévios disponíveis para 6 dos 20 anos de origem avaliados (1991 a 1996, inclusive) e menos de 5 anos de amostra para 10 deles — amostra pequena demais para uma climatologia estável nos primeiros anos da janela. Exemplos concretos (calculados, não estimados): ano de origem 1997 → 1 ano(s) prévio(s) disponível(is); 2000 → 4; 2005 → 9; 2010 → 14. Isso não invalida a abordagem (b) — é uma limitação amostral real que precisa ser decidida explicitamente antes de qualquer cálculo de skill: usar uma climatologia mais longa que misture a procedência MERRA-2/3-municípios (cuja fonte original não é comprovada — achado da Seção 4) para os primeiros anos, ou aceitar a amostra pequena/zero documentando a incerteza adicional que isso implica.

- **Nunca** usar a climatologia de referência do dashboard (1981-2025 completa) para avaliar previsões cujo período de emissão (1991-2010) está DENTRO dela sem declarar isso explicitamente — em qualquer uma das duas abordagens acima, o conjunto de anos que define a climatologia de CADA avaliação deve ser documentado no mesmo arquivo/tabela do resultado, nunca implícito.

### 8.4 Decisões que precisam de aprovação explícita antes do cálculo de skill
1. Usar ou não os alvos MERRA-2/3-municípios (ano<=1995) na avaliação, dado que sua fonte original não foi comprovada (Seção 4) e as coordenadas dos 3 municípios não são verificáveis.
2. Aceitar ou não a média de área (3 municípios ou até 34 fazendas) como proxy do valor pontual de grade do CFSv2 (Seção 5) — e se aceitar, registrar isso como premissa explícita do estudo, não como equivalência.
3. Escolher entre as abordagens (a) LOYO e (b) janela expansível da Seção 8.3 — ou outra — e documentar explicitamente qual conjunto de anos define a climatologia de cada avaliação, antes de qualquer BSS/anomalia ser calculado.
4. Definir o tratamento de meses com `qualidade_verificada_status` diferente de OK — excluir da avaliação (recomendado) ou uma estratégia de imputação, nunca silenciosamente incluídos como se fossem OK.
5. Definir como tratar a dependência temporal entre combinações (Seção 3: 1.440 combinações, 245 meses distintos) em qualquer estimativa de incerteza estatística.

## Verdito de aptidão para avaliação científica (infraestrutura + observação)

- `apto_para_avaliacao_cientifica`: **False**
- Motivos de bloqueio:
  - correspondência espacial não resolvida — 22.9 km entre a referência observacional (centroide das fazendas) e o ponto do CFSv2 (centroide das fazendas (grade CFSv2, extração histórica aprovada, run 36238169299)); decisão explícita pendente (docs/nmme-fase2c2-piloto-cobertura-observacional.md)
  - referência pós-1996 é estimativa CHIRPS ZONAL por fazenda (média dos pixels dentro do polígono de cada fazenda, informada pelo responsável pelos dados — NÃO leitura direta de pluviômetro confirmada; a empresa não tem pluviômetro em todas as fazendas; versão do CHIRPS, critério de inclusão de pixel e processamento temporal ainda não verificados documentalmente) — decisão explícita pendente (docs/nmme-fase2c2-auditoria-chirps-sinobras.md)

### Ressalvas adicionais (não incluídas no verdito de infraestrutura acima, mas igualmente bloqueantes para uma avaliação científica)

`avaliar_aptidao_referencia_observacional` (reaproveitada sem modificação) só verifica cobertura/procedência-substituta/qualidade numérica e a distância espacial — ela NÃO avalia se a documentação de procedência é suficiente. As seções 4 e 5 acima levantam problemas que continuam pendentes mesmo se a distância espacial fosse aceita:
- A fonte original do trecho "MERRA-2" (1981-1995) — numericamente idêntico a uma média de 3 municípios sem coordenadas/metodologia verificáveis (Seção 4) — não comprovada; tratar como reanálise de grade confirmada seria uma afirmação não sustentada pelo repositório.
- O descasamento de suporte espacial (célula de grade vs. média de área difusa e variável, Seção 5) — não resolvido só por a distância ter melhorado.
- A agregação Sinobras sem mínimo de estações (Seção 4) é uma propriedade do PROCEDIMENTO ATUAL do código para incorporar dados NOVOS — um mês com 1 fazenda reportando seria tratado exatamente como um mês com 34, SE isso viesse a ocorrer. Não ocorreu no conjunto histórico já auditado: SINOBRAS.csv (1996-2025) confirma exatamente 34 identificadores em todos os 360 meses, sem exceção (Seção 4). O método real do backfill 1996-2010 anterior ao primeiro commit deste repositório continua desconhecido (Seção 4).
- A dependência temporal entre combinações origem×lead (Seção 3) — 1.440 combinações não são 1.440 observações independentes.
- O mapeamento entre os 34 identificadores de fazenda e seus respectivos instrumentos físicos (Seção 5) — as 27 séries mensais numericamente distintas encontradas não devem ser presumidas como 27 locais de medição fisicamente independentes.

## Restrições respeitadas nesta tarefa

- Nenhuma métrica de skill foi calculada.
- O dashboard (docs/index.html) não foi tocado.
- Nenhum modelo climático (SARIMAX/XGBoost) foi alterado.
- Nenhum dado histórico foi modificado.
- Os 34.560 registros RAW já extraídos (data/nmme_historico_fazendas/) foram preservados integralmente — este módulo só LÊ esses arquivos.
