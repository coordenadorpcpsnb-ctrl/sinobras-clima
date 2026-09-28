# Auditoria da nova evidência — SINOBRAS.csv (registros por fazenda, 1996-2025)

**Relatório técnico — não calcula skill, não declara aptidão científica, não altera a série histórica de produção nem elimina séries duplicadas. O arquivo original não foi incorporado a este repositório.**

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
- A agregação numérica histórica (média aritmética simples dos identificadores por mês, mesma fórmula já verificada por leitura de código em `nmme_auditoria_observacional_historica.verificar_padrao_agregacao_sinobras_no_codigo`) foi REPRODUZIDA de forma independente a partir deste arquivo e bate com data/serie_subst.csv. Isso confirma a linhagem NUMÉRICA entre o arquivo recebido e a série consolidada — não confirma a metodologia de medição em campo, eventuais preenchimentos (fill) retrospectivos, nem a independência dos instrumentos pluviométricos, que permanecem SEM COMPROVAÇÃO por este arquivo.

## 3. Grupos de séries mensais idênticas (identificados automaticamente)

- Identificadores comparados: 34.
- Séries mensais numericamente distintas: 27.
- Grupos com mais de 1 identificador compartilhando a mesma série completa: 2 — [['FAZ02', 'FAZ03', 'FAZ04', 'FAZ05', 'FAZ08', 'FAZ09', 'FAZ19'], ['FAZ07', 'FAZ15']].
- 34 identificadores comparados mês a mês (igualdade exata, não aproximada) produzem 27 séries mensais numericamente distintas. 2 grupo(s) de identificadores compartilham a mesma série completa: [['FAZ02', 'FAZ03', 'FAZ04', 'FAZ05', 'FAZ08', 'FAZ09', 'FAZ19'], ['FAZ07', 'FAZ15']]. Isto é um FATO computado — a INTERPRETAÇÃO (pluviômetro compartilhado, replicação administrativa de dados, ou preenchimento de uma fazenda a partir de outra) não é decidível a partir deste arquivo; nenhuma das hipóteses deve ser presumida sem a documentação operacional correspondente.

## 4. Identificadores × séries distintas × instrumentos independentes

**Três conceitos diferentes — nunca tratados como equivalentes nesta auditoria.**

- Identificadores de fazenda: 34.
- Séries mensais numericamente distintas: 27.
- Instrumentos pluviométricos efetivamente independentes confirmados: None (desconhecido — não verificável a partir deste arquivo).
- Três conceitos diferentes, nunca tratados como equivalentes: (1) 34 IDENTIFICADORES de fazenda (rótulos FAZxx do arquivo) — uma convenção de nomenclatura administrativa, não uma contagem de instrumentos; (2) 27 SÉRIES MENSAIS numericamente distintas — um fato computado diretamente dos dados (comparação exata dos valores mensais completos de cada identificador); (3) instrumentos pluviométricos EFETIVAMENTE INDEPENDENTES — DESCONHECIDO, não verificável a partir deste arquivo isoladamente. Ter menos séries distintas (27) que identificadores (34) é consistente com pluviômetro compartilhado entre fazendas, com replicação administrativa de um registro entre fazendas realmente distintas, ou com preenchimento (fill) de uma fazenda a partir de outra — as três hipóteses permanecem em aberto sem a documentação operacional (coordenadas, períodos de operação, um registro por instrumento) que este arquivo não contém.

### Sensibilidade da agregação espacial (informativo — nunca uma correção proposta)

- Representantes usados no teste (1 por série distinta): 27.
- Diferença absoluta média entre pesar por identificador (atual) e por série única: 1.1035 mm/mês. Máxima: 6.7081 mm/mês, em 2019-05.
- Teste de SENSIBILIDADE apenas, nunca uma correção proposta. A diferença entre pesar cada identificador igualmente (procedimento atual) e pesar cada série distinta uma única vez mostra o quanto a escolha de agregação espacial importa, mas não decide qual delas é mais correta — depende de documentação operacional ainda ausente sobre os grupos de séries idênticas.

## 5. Análise espacial — necessidade de coordenadas individuais e do mapeamento identificador→instrumento

- Coordenadas individuais disponíveis neste arquivo: False.
- Coordenadas individuais disponíveis em qualquer arquivo deste repositório: False.
- Mapeamento identificador→instrumento físico disponível: False.
- SINOBRAS.csv identifica cada registro por `estacao` (FAZxx), mas não traz coordenada nenhuma — e nenhum outro arquivo deste repositório associa um FAZxx a uma coordenada individual (CLAUDE.md, armadilha 8: data/fazendas.geojson foi deliberadamente substituído por um envelope único de 85.020,5 ha sem identificação por fazenda; decisão preservada aqui, não revertida). São necessárias DUAS coisas, nunca supridas por este arquivo: (1) as coordenadas de cada um dos 34 pontos de medição identificados por FAZxx; e (2) o mapeamento de cada um desses identificadores para seu respectivo instrumento físico — isto é, confirmar quais identificadores de fato compartilham um único pluviômetro e quais são instrumentos fisicamente distintos. As 27 séries mensais numericamente distintas encontradas (Seção 3/4) são um FATO sobre os DADOS, não uma contagem de locais físicos — NÃO presumir que elas correspondem a 27 locais de medição fisicamente independentes; sem o mapeamento identificador→instrumento, o número real de locais físicos permanece desconhecido (pode ser 27, 34, ou outro valor). Sem essas duas informações, o suporte espacial da observação — potencialmente múltiplos pontos, não um único centroide — não pode ser comparado à célula de grade do CFSv2 (~1°, ordem de 100km de lado). Sem elas, a distância de 22,91km do centroide agregado até a grade do CFSv2 (docs/nmme-fase2c2-auditoria-observacional-historica.md, Seção 5) continua sendo a distância de UM ponto agregado — nunca das medições individuais por fazenda.

## Conclusões desta auditoria (item 6 da tarefa)

- A agregação numérica histórica de 1996-2025 (`prec` de data/serie_subst.csv) foi REPRODUZIDA de forma independente a partir de SINOBRAS.csv — achado numérico, verificado acima (Seção 2).
- A metodologia de medição em campo (tipo de pluviômetro, protocolo de leitura, frequência de manutenção), eventuais preenchimentos/interpolações retrospectivas, e a independência efetiva dos instrumentos pluviométricos PERMANECEM SEM COMPROVAÇÃO — nenhum destes três pontos é decidível a partir deste arquivo isoladamente.
- Nenhuma série duplicada foi eliminada e nenhuma série histórica de produção foi alterada por esta auditoria — os grupos de séries idênticas (Seção 3) são só DOCUMENTADOS, nunca resolvidos ou removidos.

## Restrições respeitadas nesta tarefa

- Nenhuma métrica de skill foi calculada. Nenhuma aptidão científica foi declarada.
- O dashboard (docs/index.html) não foi tocado.
- A série histórica de produção (data/serie_subst.csv) não foi alterada — só lida.
- Nenhuma série duplicada foi eliminada.
- O arquivo original (SINOBRAS.csv) NÃO foi incorporado a este repositório — este módulo só o lê a partir do caminho informado em `--arquivo`.
