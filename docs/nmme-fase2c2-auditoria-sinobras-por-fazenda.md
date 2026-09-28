# Auditoria da nova evidência — SINOBRAS.csv (registros por fazenda, 1996-2025)

**Relatório técnico — não calcula skill, não declara aptidão científica, não altera a série histórica de produção nem elimina séries duplicadas. O arquivo original não foi incorporado a este repositório.**

> **Atualização (4ª rodada, 2026)**: o responsável pelos dados informou que SINOBRAS.csv contém ESTIMATIVAS extraídas do CHIRPS por fazenda, não medições diretas de pluviômetro — a empresa não tem pluviômetro em todas as fazendas. As seções abaixo foram revisadas para refletir essa informação (não comprovada documentalmente ainda). Ver docs/nmme-fase2c2-auditoria-chirps-sinobras.md para a investigação dedicada.

## Evidência analisada

- Arquivo: `SINOBRAS.csv`.
- **SHA-256: `ad44fa16d9bdba16fb6550ab1ff3eabaefdbc6dfffee0a6afc19e6c5a931ca1a`** — qualquer pessoa com o mesmo arquivo pode conferir com `sha256sum SINOBRAS.csv` e comparar com este valor.
- Reprodutibilidade: `python scripts/nmme_auditoria_sinobras_por_fazenda.py --arquivo <caminho_para_o_arquivo> --gerar-relatorio`.

## 1. Integridade estrutural

- Registros: 12240. Identificadores distintos: 34.
- Período coberto: 1996-01 → 2025-12 (360 meses).
- Meses ausentes dentro do período coberto: 0.
- Registros por identificador — máximo: 360; identificadores com contagem diferente do máximo: nenhum.
- Registros por mês — moda: 34; meses com número atípico de registros: nenhum.
- Duplicatas (ano, mês, estação): 0.
- Valores ausentes: 0. Valores fisicamente implausíveis (fora de [0.0, 1500.0] mm/mês): 0.
- **Integridade estrutural completa: True**

## 2. Reconciliação com data/serie_subst.csv (só leitura — nunca escrita)

- Meses no arquivo recebido: 360.
- Meses sem correspondência na série de produção: 0.
- Meses comparáveis: 360. Idênticos após arredondamento a 2 casas: 360.
- Diferença absoluta média: 0.0 mm. Máxima: 0.0 mm.
- **Reconciliação completa: True**
- A agregação numérica histórica (média aritmética simples dos identificadores por mês, mesma fórmula já verificada por leitura de código em `nmme_auditoria_observacional_historica.verificar_padrao_agregacao_sinobras_no_codigo`) foi REPRODUZIDA de forma independente a partir deste arquivo e bate com data/serie_subst.csv. Isso confirma a linhagem NUMÉRICA entre o arquivo recebido e a série consolidada — não confirma a versão nem a metodologia de extração do CHIRPS usadas para gerar essas estimativas (informado pelo responsável pelos dados, não verificado documentalmente), eventuais preenchimentos (fill) retrospectivos, nem se alguma fazenda tem, além da estimativa CHIRPS, um pluviômetro físico real — tudo isso permanece SEM COMPROVAÇÃO por este arquivo.

## 3. Grupos de séries mensais idênticas (identificados automaticamente)

- Identificadores comparados: 34.
- Séries mensais numericamente distintas: 27.
- Grupos com mais de 1 identificador compartilhando a mesma série completa: 2 — [['FAZ02', 'FAZ03', 'FAZ04', 'FAZ05', 'FAZ08', 'FAZ09', 'FAZ19'], ['FAZ07', 'FAZ15']].
- 34 identificadores comparados mês a mês (igualdade exata, não aproximada) produzem 27 séries mensais numericamente distintas. 2 grupo(s) de identificadores compartilham a mesma série completa: [['FAZ02', 'FAZ03', 'FAZ04', 'FAZ05', 'FAZ08', 'FAZ09', 'FAZ19'], ['FAZ07', 'FAZ15']]. Isto é um FATO computado — a INTERPRETAÇÃO não é decidível a partir deste arquivo isoladamente. Hipóteses em aberto, NENHUMA presumida sem a documentação operacional correspondente: (a) COMPARTILHAMENTO DE PIXEL CHIRPS — dado que SINOBRAS.csv é estimativa CHIRPS por fazenda (informado pelo responsável pelos dados, ver docs/nmme-fase2c2-auditoria-chirps-sinobras.md), fazendas cujas coordenadas nominais caem no mesmo pixel CHIRPS (~0,05°, ~5,5km no equador) receberiam exatamente o mesmo valor extraído — hipótese mais parcimoniosa dado o novo contexto, mas NÃO comprovada (exigiria as coordenadas de cada fazenda, ainda ausentes); (b) pluviômetro físico compartilhado (se alguma das fazendas do grupo de fato tiver instrumento); (c) replicação administrativa de um registro entre fazendas distintas; (d) preenchimento (fill) de uma fazenda a partir de outra.

## 4. Identificadores × séries distintas × pixels CHIRPS × instrumentos independentes

**Quatro conceitos diferentes — nunca tratados como equivalentes nesta auditoria.**

- Identificadores de fazenda: 34.
- Séries mensais numericamente distintas: 27.
- Pontos de extração CHIRPS efetivamente distintos confirmados: None (desconhecido — exigiria as coordenadas de extração de cada fazenda).
- Instrumentos pluviométricos efetivamente independentes confirmados: None (desconhecido — nem sequer presumido que exista instrumento físico para cada fazenda).
- Quatro conceitos diferentes, nunca tratados como equivalentes: (1) 34 IDENTIFICADORES de fazenda (rótulos FAZxx do arquivo) — uma convenção de nomenclatura administrativa; (2) 27 SÉRIES MENSAIS numericamente distintas — um fato computado diretamente dos dados; (3) pontos/pixels de extração CHIRPS EFETIVAMENTE DISTINTOS — DESCONHECIDO, exigiria as coordenadas usadas na extração de cada fazenda (ainda ausentes); (4) instrumentos pluviométricos EFETIVAMENTE INDEPENDENTES — DESCONHECIDO e, dado que SINOBRAS.csv foi informado pelo responsável pelos dados como estimativa CHIRPS (a empresa não tem pluviômetro em todas as fazendas), NEM SEQUER PRESUMIDO QUE EXISTA um instrumento físico para cada uma das 34 fazendas. Ter menos séries distintas (27) que identificadores (34) é consistente, em ordem de parcimônia dado o novo contexto, com: pixel CHIRPS compartilhado entre fazendas geograficamente próximas (hipótese mais provável, mas não comprovada — ver docs/nmme-fase2c2-auditoria-chirps-sinobras.md); pluviômetro físico compartilhado, SE alguma fazenda do grupo tiver instrumento; replicação administrativa de um registro entre fazendas distintas; ou preenchimento (fill) de uma fazenda a partir de outra — nenhuma das hipóteses deve ser presumida sem a documentação operacional (coordenadas/polígonos usados na extração, versão/metodologia do CHIRPS, e confirmação de quais fazendas — se alguma — têm pluviômetro real) que este arquivo não contém.

### Sensibilidade da agregação espacial (informativo — nunca uma correção proposta)

- Representantes usados no teste (1 por série distinta): 27.
- Diferença absoluta média entre pesar por identificador (atual) e por série única: 1.1035 mm/mês. Máxima: 6.7081 mm/mês, em 2019-05.
- Teste de SENSIBILIDADE apenas, nunca uma correção proposta. A diferença entre pesar cada identificador igualmente (procedimento atual) e pesar cada série distinta uma única vez mostra o quanto a escolha de agregação espacial importa, mas não decide qual delas é mais correta. Se a hipótese de pixel CHIRPS compartilhado (ver 'interpretacao' de identificar_grupos_series_identicas) for confirmada, pesar por série única corrigiria uma superponderação implícita de pixels com mais fazendas mapeadas a eles — mas essa confirmação depende de documentação operacional (coordenadas/pixels de extração) ainda ausente.

## 5. Análise espacial — necessidade de coordenadas/pixels de extração e do mapeamento identificador→instrumento

- Coordenadas individuais disponíveis neste arquivo: False.
- Coordenadas individuais disponíveis em qualquer arquivo deste repositório: False.
- Mapeamento identificador→instrumento físico disponível: False.
- Mapeamento identificador→pixel CHIRPS disponível: False.
- SINOBRAS.csv identifica cada registro por `estacao` (FAZxx), mas não traz coordenada nenhuma — e nenhum outro arquivo deste repositório associa um FAZxx a uma coordenada individual (CLAUDE.md, armadilha 8: data/fazendas.geojson foi deliberadamente substituído por um envelope único de 85.020,5 ha sem identificação por fazenda; decisão preservada aqui, não revertida). Com a reinterpretação CHIRPS (ver docs/nmme-fase2c2-auditoria-chirps-sinobras.md), são necessárias TRÊS coisas, nunca supridas por este arquivo: (1) a coordenada/polígono usado para extrair a estimativa CHIRPS de cada um dos 34 identificadores FAZxx; (2) a versão e a metodologia de extração do CHIRPS empregadas; e (3), SE alguma fazenda tiver de fato um pluviômetro físico, o mapeamento de qual(is) identificador(es) correspondem a instrumento real — a empresa não tem pluviômetro em todas as fazendas, então essa lista pode ser um subconjunto pequeno dos 34, ou vazia. As 27 séries mensais numericamente distintas encontradas (Seção 3/4) são um FATO sobre os DADOS, não uma contagem de locais físicos NEM de pixels CHIRPS distintos — NÃO presumir que elas correspondem a 27 pontos de extração fisicamente independentes; sem o mapeamento identificador→coordenada/pixel, o número real de pontos de extração permanece desconhecido (pode ser 27, 34, ou outro valor). Sem essas informações, o suporte espacial da observação — potencialmente múltiplos pixels CHIRPS, não um único centroide — não pode ser comparado à célula de grade do CFSv2 (~1°, ordem de 100km de lado). Sem elas, a distância de 22,91km do centroide agregado até a grade do CFSv2 (docs/nmme-fase2c2-auditoria-observacional-historica.md, Seção 5) continua sendo a distância de UM ponto agregado — nunca das estimativas individuais por fazenda.

## Conclusões desta auditoria (item 6 da tarefa)

- A agregação numérica histórica de 1996-2025 (`prec` de data/serie_subst.csv) foi REPRODUZIDA de forma independente a partir de SINOBRAS.csv — achado numérico, verificado acima (Seção 2).
- O responsável pelos dados informou que SINOBRAS.csv é estimativa CHIRPS por fazenda, não leitura de pluviômetro — a versão/metodologia de extração do CHIRPS, eventuais preenchimentos/interpolações retrospectivas, e se alguma fazenda tem, além disso, um pluviômetro físico real PERMANECEM SEM COMPROVAÇÃO — nenhum destes pontos é decidível a partir deste arquivo isoladamente (ver docs/nmme-fase2c2-auditoria-chirps-sinobras.md).
- Nenhuma série duplicada foi eliminada e nenhuma série histórica de produção foi alterada por esta auditoria — os grupos de séries idênticas (Seção 3) são só DOCUMENTADOS, nunca resolvidos ou removidos.

## Restrições respeitadas nesta tarefa

- Nenhuma métrica de skill foi calculada. Nenhuma aptidão científica foi declarada.
- O dashboard (docs/index.html) não foi tocado.
- A série histórica de produção (data/serie_subst.csv) não foi alterada — só lida.
- Nenhuma série duplicada foi eliminada.
- O arquivo original (SINOBRAS.csv) NÃO foi incorporado a este repositório — este módulo só o lê a partir do caminho informado em `--arquivo`.
