# Investigação CHIRPS — reinterpretação da referência observacional Sinobras

**Relatório técnico — não calcula skill, não recalcula previsões/indicadores, não substitui a referência observacional atual, não altera dados históricos, dashboard nem modelos climáticos.**

## Contexto

O responsável pelos dados informou que SINOBRAS.csv (registros por fazenda, 1996-2025, já auditado em docs/nmme-fase2c2-auditoria-sinobras-por-fazenda.md) contém ESTIMATIVAS extraídas do CHIRPS por fazenda — não leituras diretas de pluviômetro. A empresa não tem pluviômetro em todas as fazendas. A classificação em docs/nmme-fase2c2-auditoria-observacional-historica.md e em scripts/nmme_piloto_historico.py foi corrigida para refletir isso (achado 'reinterpretacao_chirps') — este documento é a investigação dedicada.

## 1. Metodologia do CHIRPS já extraído neste repositório (referência de contraste)

- Fonte: CHIRPS (UCSB), via ClimateSERV, dataset 0.
- Geometria: ponto único no centroide das fazendas (lat=-7.80, lon=-47.95).
- Resolução: 0.05° (~5,5km no equador).
- Script: `scripts/_chirps.py::buscar_prec_chirps`.
- Backfill histórico: `scripts/backfill_chirps_historico.py (execução única, já rodada)`.
- Versão do CHIRPS pinada/documentada: False. Data de extração documentada: False.
- Esta metodologia é CONHECIDA (verificada por leitura de código) — serve de contraste explícito: mesmo este CHIRPS, extraído dentro deste repositório, tem lacunas de versionamento. A metodologia de SINOBRAS.csv é inteiramente DESCONHECIDA.

## 2. Comparação: data/chirps_1981_2025.csv × data/serie_subst.csv

- Meses comparados no total: 540.

### Período pós-1996 (SINOBRAS.csv, agora reinterpretado como CHIRPS)

- Meses comparados: 360.
- Diferença absoluta média: 33.93 mm. Máxima: 220.49 mm.
- Correlação: 0.9168. Razão mediana (série/CHIRPS-ponto): 1.002.
- Meses numericamente idênticos (diff < 0,01mm): 9/360.

### Período pré-1996 (MERRA-2/3-municípios — procedência não comprovada, item 7)

- Meses comparados: 180.
- Diferença absoluta média: 22.34 mm. Máxima: 138.8 mm.
- Correlação: 0.9673. Razão mediana (série/CHIRPS-ponto): 0.97.
- Meses numericamente idênticos (diff < 0,01mm): 1/180.

- 540 meses comparáveis entre data/serie_subst.csv (que reproduz SINOBRAS.csv para 1996-2025) e data/chirps_1981_2025.csv (CHIRPS de metodologia CONHECIDA, ponto único no centroide das fazendas). Pós-1996: correlação 0.9168, razão mediana 1.002, mas só 9/360 meses IDÊNTICOS — a correlação alta e a razão mediana próxima de 1 são CONSISTENTES com ambas as séries terem origem CHIRPS, mas a ausência de identidade numérica mês a mês mostra que NÃO são a mesma extração (ponto/pixel diferente, versão diferente do CHIRPS, ou agregação espacial diferente — todas possibilidades em aberto, nenhuma confirmada). Pré-1996: correlação 0.9673 — mais alta ainda que pós-1996, um achado curioso que NÃO deve ser lido como prova de que o trecho MERRA-2/3-municípios também é CHIRPS (isso permanece não comprovado, item 7 da tarefa) — só registrado aqui como observação para investigação futura.

## 3. Informações necessárias para reproduzir a extração de SINOBRAS.csv

- Versão do produto CHIRPS usada para gerar SINOBRAS.csv (ex.: CHIRPS v2.0 Final vs. Preliminary) e a data de extração. Contraste: nem mesmo data/chirps_1981_2025.csv (extraído NESTE repositório) tem isso documentado — ClimateSERV serve a versão corrente, sem versionamento explícito registrado em scripts/backfill_chirps_historico.py.
- Coordenada ou polígono usado para extrair a estimativa de CADA uma das 34 fazendas — SINOBRAS.csv não traz coordenadas (achado de scripts/nmme_auditoria_sinobras_por_fazenda.py). Sem isso, não é possível saber se os grupos de séries idênticas (FAZ02/03/04/05/08/09/19 e FAZ07/FAZ15) correspondem a fazendas no mesmo pixel CHIRPS.
- Resolução espacial usada — CHIRPS nativo é 0,05° (~5,5km no equador); confirmar se a extração de SINOBRAS.csv usou essa resolução nativa (ponto único por fazenda, como scripts/_chirps.py::buscar_prec_chirps faz para o centroide) ou uma agregação sobre múltiplos pixels por fazenda (análogo a buscar_prec_chirps_zonal, mas por fazenda individual).
- Regra de agregação espacial — se mais de um pixel CHIRPS foi usado por fazenda, qual critério (média simples? ponderada pela área de sobreposição?) resume os valores.
- Processamento temporal — CHIRPS nativo é diário; confirmar a regra de agregação diária→mensal (soma simples do mês? exigência de cobertura mínima de dias válidos?).
- Unidades e arredondamento — SINOBRAS.csv está em mm/mês, valores inteiros; CHIRPS nativo é mm/dia. Confirmar se o arredondamento para inteiro foi feito na extração ou em uma etapa posterior (perda de precisão relevante para meses de chuva baixa, ex.: jul/ago, onde CLAUDE.md armadilha 7 já documenta viés conhecido de fontes de satélite).
- Ferramenta/serviço de extração usado (ClimateSERV, como este repositório usa? Google Earth Engine? download direto dos GeoTIFFs do CHIRPS?) — determina quais dos vieses conhecidos de ClimateSERV (CLAUDE.md armadilha 7, tabela ERA5/CHIRPS por mês) se aplicam ou não a SINOBRAS.csv.
- Confirmação de quais das 34 fazendas — se alguma — têm, além da estimativa CHIRPS, um pluviômetro físico real instalado; a empresa não tem pluviômetro em todas.

## 4. Viabilidade de uma referência CHIRPS consistente para 1991-2011

- data/chirps_1981_2025.csv já cobre 1991-2011: True (252/252 meses).
- TECNICAMENTE VIÁVEL, com ressalvas — nunca executado aqui. data/chirps_1981_2025.csv JÁ COBRE 1991-2011 (252/252 meses esperados) com metodologia conhecida (ponto único, centroide das fazendas, ClimateSERV) — tecnicamente, boa parte do trabalho de construir uma referência CHIRPS consistente para esse período JÁ FOI FEITO, não precisa ser refeito do zero. Ressalvas que impedem declarar isso 'pronto': (1) a VERSÃO do CHIRPS servida pelo ClimateSERV pode ter mudado desde a extração original (não versionada, não documentada — mesma lacuna que impede reproduzir SINOBRAS.csv, item 4 acima); reextrair hoje pode não bater byte a byte com o arquivo já salvo; (2) ponto único vs. zonal — o envelope de 34 fazendas tem ~85.020 ha, MUITO maior que 1 pixel CHIRPS (0,05°, ~30 km²); um ponto único no centroide é um proxy, não uma média representativa da área toda — buscar_prec_chirps_zonal existe mas não tem a cobertura de teste de falha exigida para promoção a primário; (3) ainda que uma referência CHIRPS ponto-único fosse aceita, ela SUBSTITUIRIA a referência observacional atual (MERRA-2/3-municípios pré-1996 + SINOBRAS.csv pós-1996) — decisão explícita que este módulo NÃO toma (restrição desta tarefa: não substituir automaticamente a referência observacional). Próximo passo recomendado, se essa substituição for aprovada no futuro: (a) reextrair 1991-2011 com buscar_prec_chirps e comparar contra o data/chirps_1981_2025.csv já salvo para confirmar estabilidade de versão; (b) rodar buscar_prec_chirps_zonal pela suíte de falha de tests/test_fetch_fallback.py antes de considerar promovê-lo.

## 5. Proposta de continuidade

1. Obter do responsável pelos dados um documento técnico (não apenas comunicação verbal) descrevendo a extração de SINOBRAS.csv: versão do CHIRPS, ferramenta, coordenadas/polígonos por fazenda, resolução, agregação espacial e temporal, unidades — ver montar_lista_informacoes_necessarias_reproducao() para a lista completa.
2. Obter confirmação explícita de quais das 34 fazendas — se alguma — têm pluviômetro físico real, para não tratar nenhuma fazenda como instrumentada sem confirmação.
3. Com as coordenadas/polígonos em mãos, verificar computacionalmente se os 2 grupos de séries idênticas (FAZ02/03/04/05/08/09/19 e FAZ07/FAZ15) correspondem a fazendas no mesmo pixel CHIRPS (0,05°) — isso confirmaria ou refutaria a hipótese de compartilhamento de pixel como explicação, sem precisar reextrair nada.
4. Reextrair 1991-2011 com scripts/_chirps.py::buscar_prec_chirps (ponto único, já testado) e comparar contra data/chirps_1981_2025.csv já salvo — se os valores baterem, confirma estabilidade de versão do CHIRPS ao longo do tempo; se não baterem, documenta a divergência antes de qualquer uso científico.
5. Rodar scripts/_chirps.py::buscar_prec_chirps_zonal pela suíte de falha de tests/test_fetch_fallback.py (hoje só cobre buscar_prec_chirps) antes de considerar promovê-lo a fonte primária para qualquer finalidade.
6. Só depois de tudo acima: decisão EXPLÍCITA e documentada (não automática, fora do escopo desta tarefa) sobre se/como uma referência CHIRPS construída internamente substituiria, complementaria, ou seria reportada lado a lado com a referência observacional atual (MERRA-2/3-municípios pré-1996 + SINOBRAS.csv pós-1996) para fins de validação do CFSv2.

## Restrições respeitadas nesta tarefa

- Nenhuma métrica de skill foi calculada.
- Nenhuma previsão ou indicador de desempenho foi recalculado.
- A referência observacional de produção (data/serie_subst.csv) NÃO foi substituída — só lida para comparação.
- Nenhum dado histórico foi modificado.
- O dashboard (docs/index.html) não foi tocado. Nenhum modelo climático foi alterado.
- Nenhuma nova extração do CHIRPS foi executada (nenhum acesso à rede/ClimateSERV nesta tarefa) — a comparação usa exclusivamente data/chirps_1981_2025.csv, já existente no repositório.
