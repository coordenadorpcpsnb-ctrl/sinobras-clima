# Investigação CHIRPS — reinterpretação da referência observacional Sinobras

**Relatório técnico — não calcula skill, não recalcula previsões/indicadores, não substitui a referência observacional atual, não altera dados históricos, dashboard nem modelos climáticos.**

## Contexto

O responsável pelos dados informou que SINOBRAS.csv (registros por fazenda, 1996-2025, já auditado em docs/nmme-fase2c2-auditoria-sinobras-por-fazenda.md) contém ESTIMATIVAS extraídas do CHIRPS por fazenda — não leituras diretas de pluviômetro. A empresa não tem pluviômetro em todas as fazendas. Em rodada posterior, confirmou que a extração é ZONAL — média dos pixels CHIRPS dentro do polígono de CADA fazenda, não um ponto único. A classificação em docs/nmme-fase2c2-auditoria-observacional-historica.md e em scripts/nmme_piloto_historico.py foi corrigida para refletir isso (achado 'reinterpretacao_chirps') — este documento é a investigação dedicada.

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

- 540 meses comparáveis entre data/serie_subst.csv (que reproduz SINOBRAS.csv para 1996-2025) e data/chirps_1981_2025.csv (CHIRPS de metodologia CONHECIDA, ponto único no centroide das fazendas). Pós-1996: correlação 0.9168, razão mediana 1.002, mas só 9/360 meses IDÊNTICOS — a correlação alta e a razão mediana próxima de 1 são CONSISTENTES com ambas as séries terem origem CHIRPS, mas a ausência de identidade numérica mês a mês mostra que NÃO são a mesma extração. Revisão pontual (5ª rodada, 2026): uma das causas dessa não-identidade deixou de ser hipótese — o responsável pelos dados confirmou que SINOBRAS.csv é extração ZONAL (média dos pixels dentro do polígono de cada fazenda), enquanto data/chirps_1981_2025.csv é PONTUAL (1 valor no centroide agregado); ponto vs. zonal é agora um FATO conhecido, não uma das possibilidades em aberto. As demais causas seguem em aberto, nenhuma confirmada: versão diferente do CHIRPS servida pelo ClimateSERV, critério de inclusão de pixel na borda do polígono, e processamento temporal diferente (ver item 3 abaixo). Pré-1996: correlação 0.9673 — mais alta ainda que pós-1996, um achado curioso que NÃO deve ser lido como prova de que o trecho MERRA-2/3-municípios também é CHIRPS (isso permanece não comprovado, item 7 da tarefa) — só registrado aqui como observação para investigação futura.

## 3. Informações necessárias para reproduzir a extração de SINOBRAS.csv

- Versão do produto CHIRPS usada para gerar SINOBRAS.csv (ex.: CHIRPS v2.0 Final vs. Preliminary) e a data de extração. Contraste: nem mesmo data/chirps_1981_2025.csv (extraído NESTE repositório) tem isso documentado — ClimateSERV serve a versão corrente, sem versionamento explícito registrado em scripts/backfill_chirps_historico.py. PENDENTE.
- Polígono usado para extrair a estimativa ZONAL de CADA uma das 34 fazendas (não uma coordenada única — a extração é confirmadamente zonal) — SINOBRAS.csv não traz polígonos nem coordenadas (achado de scripts/nmme_auditoria_sinobras_por_fazenda.py). Sem isso, não é possível saber se os grupos de séries idênticas (FAZ02/03/04/05/08/09/19 e FAZ07/FAZ15) correspondem a fazendas cujos polígonos cobrem o MESMO conjunto de pixels CHIRPS. PENDENTE.
- RESOLVIDO (5ª rodada): a agregação espacial é ZONAL — média dos pixels CHIRPS dentro do polígono de cada fazenda (CHIRPS nativo 0,05°, ~5,5km no equador), confirmado pelo responsável pelos dados. Contraste: data/chirps_1981_2025.csv (já extraído neste repositório) é PONTUAL — 1 valor no centroide agregado, uma metodologia diferente por desenho, não uma dúvida a resolver.
- Critério de inclusão de pixel na borda do polígono — centro do pixel dentro do polígono? qualquer sobreposição, por menor que seja? fração de área ponderada? — determina quantos pixels entram na média de cada fazenda. PENDENTE.
- Tratamento de pixels parcialmente interceptados pela borda do polígono — incluídos por inteiro, excluídos, ou ponderados pela fração de área dentro do polígono? PENDENTE.
- Processamento temporal — CHIRPS nativo é diário; confirmar a regra de agregação diária→mensal (soma simples do mês? exigência de cobertura mínima de dias válidos?). PENDENTE.
- Unidades e arredondamento — SINOBRAS.csv está em mm/mês, valores inteiros; CHIRPS nativo é mm/dia. Confirmar se o arredondamento para inteiro foi feito na extração ou em uma etapa posterior (perda de precisão relevante para meses de chuva baixa, ex.: jul/ago, onde CLAUDE.md armadilha 7 já documenta viés conhecido de fontes de satélite). PENDENTE.
- Ferramenta/serviço de extração usado (ClimateSERV, como este repositório usa? Google Earth Engine? download direto dos GeoTIFFs do CHIRPS?) — determina quais dos vieses conhecidos de ClimateSERV (CLAUDE.md armadilha 7, tabela ERA5/CHIRPS por mês) se aplicam ou não a SINOBRAS.csv. PENDENTE.
- Confirmação de quais das 34 fazendas — se alguma — têm, além da estimativa CHIRPS, um pluviômetro físico real instalado; a empresa não tem pluviômetro em todas. PENDENTE.

## 4. Comparação de três alternativas metodológicas para a referência regional (5ª rodada)

**Nenhuma das três foi calculada ou implementada — só comparação metodológica (atividade 6).**

### (a) Média simples das 34 estimativas por fazenda — metodologia histórica, atual

- Já implementada em: `scripts/update_dashboard.py — df_new.groupby(['ano','mes'])['prec_mm'].mean()`.
- Peso por fazenda: IGUAL para todas as 34 fazendas, independente da área do polígono.
- Requisito de dados adicional: nenhum — já é a série de produção (data/serie_subst.csv).

### (b) Média das 34 estimativas por fazenda, ponderada pela área do polígono

- Onde já está implementada: em nenhum lugar — não existe neste repositório.
- Peso por fazenda: proporcional à área do polígono de cada fazenda.
- Requisito de dados adicional: a área do polígono de cada uma das 34 fazendas — não disponível neste repositório (CLAUDE.md armadilha 8).

### (c) Média zonal direta sobre a união dos 34 polígonos

- Onde já está implementada: em nenhum lugar — scripts/_chirps.py::buscar_prec_chirps_zonal existe, mas opera sobre o envelope ÚNICO e ANONIMIZADO das 34 fazendas (CLAUDE.md armadilha 8), não sobre a união exata dos 34 polígonos individuais — o envelope é MAIOR que essa união (85.020,5 ha vs. 48.737,3 ha da união dos 37 perímetros reais antigos, por preencher reentrâncias entre fazendas).
- Requisito de dados adicional: os 34 polígonos individuais (para a união exata) OU o envelope único já existente (para uma aproximação MAIOR que a união real, com área desconhecida de quanto excede) + uma extração zonal nova sobre essa geometria.

### Possibilidade de sobreposição espacial entre os polígonos

- Verificável com os dados atuais: False.
- os 2 grupos de séries mensais idênticas identificados em scripts/nmme_auditoria_sinobras_por_fazenda.py (FAZ02/03/04/05/08/09/19 e FAZ07/FAZ15) são um sinal de que ALGUMAS fazendas compartilham o mesmo CONJUNTO DE PIXELS CHIRPS cobertos — mas isso NÃO é a mesma coisa que sobreposição de POLÍGONO: polígonos vizinhos, sem nenhuma sobreposição de área, podem ainda assim cair sobre os mesmos pixels grosseiros do CHIRPS (0,05°, ~5,5km) se forem pequenos e próximos. Compartilhar pixel NÃO implica sobrepor polígono, e sobrepor polígono não é a única causa possível de série idêntica — nenhuma das duas é presumida aqui.
- a possibilidade de sobreposição espacial entre os polígonos das 34 fazendas permanece EM ABERTO, nem confirmada nem descartada — este módulo não afirma que existe, nem que não existe.

- As três alternativas NÃO são intercambiáveis por desenho, e nenhuma foi calculada ou implementada aqui (atividade 6). (a), a metodologia histórica em produção, dá peso IGUAL às 34 fazendas independente de área — diverge de (b) sempre que as áreas das fazendas forem desiguais (o que não se pode presumir sem os polígonos, mas é improvável que 34 fazendas tenham área exatamente igual). (b) e (c) só coincidem entre si se os 34 polígonos NÃO se sobrepuserem espacialmente — com sobreposição, (b) conta a área compartilhada mais de uma vez (proporcionalmente a quantas fazendas a reivindicam), enquanto (c) conta cada parcela espacial uma única vez, por construção. (c) é a mais correta espacialmente, mas exige infraestrutura que não existe hoje: os 34 polígonos individuais (ou, como aproximação com área desconhecida de erro, o envelope único e anonimizado) e uma extração zonal sobre essa geometria. A possibilidade de sobreposição espacial entre os polígonos é HOJE INVERIFICÁVEL sem os próprios polígonos — o sinal indireto disponível (grupos de séries mensais idênticas) indica compartilhamento de PIXEL, não necessariamente sobreposição de POLÍGONO, e as duas coisas não devem ser confundidas. Nenhuma decisão sobre qual alternativa adotar é tomada aqui — essa é uma decisão explícita e futura, condicionada a primeiro obter os polígonos (o que por sua vez exige revisitar CLAUDE.md armadilha 8) e/ou aceitar a aproximação do envelope único já existente.

## 5. Viabilidade de uma referência CHIRPS consistente para 1991-2011

- data/chirps_1981_2025.csv já cobre 1991-2011: True (252/252 meses).
- TECNICAMENTE VIÁVEL só para uma referência PONTUAL — nunca executado aqui. data/chirps_1981_2025.csv JÁ COBRE 1991-2011 (252/252 meses esperados) com metodologia conhecida (ponto único, centroide das fazendas, ClimateSERV). Mas essa metodologia NÃO é a mesma de SINOBRAS.csv (zonal por polígono de fazenda, confirmado pelo responsável pelos dados) — não é mais uma ressalva em aberto, é um fato: comparar as duas sem marcar essa diferença seria comparar metodologias distintas como se fossem a mesma. Ressalvas: (1) a VERSÃO do CHIRPS servida pelo ClimateSERV pode ter mudado desde a extração original (não versionada, não documentada — mesma lacuna que impede reproduzir SINOBRAS.csv, item 4 acima); reextrair hoje pode não bater byte a byte com o arquivo já salvo; (2) reproduzir a metodologia ZONAL POR FAZENDA de SINOBRAS.csv exigiria: (a) os 34 polígonos individuais, que o projeto decidiu deliberadamente NÃO manter neste repositório (CLAUDE.md armadilha 8 — anonimização, decisão que precisaria ser revisitada explicitamente, não contornada); e (b) uma função de extração zonal POR FAZENDA que ainda não existe (buscar_prec_chirps_zonal hoje opera só sobre o envelope único anonimizado, não 34 polígonos individuais); (3) mesmo uma referência zonal sobre a UNIÃO do envelope (sem precisar dos 34 polígonos individuais) teria o problema de buscar_prec_chirps_zonal nunca ter passado pela suíte de falha de tests/test_fetch_fallback.py; (4) qualquer uma dessas referências, se construída, SUBSTITUIRIA a referência observacional atual — decisão explícita que este módulo NÃO toma (restrição desta tarefa). Próximo passo recomendado, se aprovado no futuro: (a) reextrair 1991-2011 com buscar_prec_chirps (ponto) e comparar contra o data/chirps_1981_2025.csv já salvo para confirmar estabilidade de versão; (b) decidir explicitamente se manter polígonos por fazenda é aceitável (revisão da armadilha 8) antes de cogitar reproduzir a metodologia zonal por fazenda; (c) rodar buscar_prec_chirps_zonal pela suíte de falha de tests/test_fetch_fallback.py antes de considerar promover qualquer variante zonal a primário.

## 6. Proposta de continuidade

1. Obter do responsável pelos dados um documento técnico (não apenas comunicação verbal) descrevendo a extração de SINOBRAS.csv: versão do CHIRPS, ferramenta, polígono por fazenda, critério de inclusão de pixel na borda, tratamento de pixel parcialmente interceptado, processamento temporal, unidades — ver montar_lista_informacoes_necessarias_reproducao() para a lista completa.
2. Obter confirmação explícita de quais das 34 fazendas — se alguma — têm pluviômetro físico real, para não tratar nenhuma fazenda como instrumentada sem confirmação.
3. Com os polígonos em mãos, verificar computacionalmente se os 2 grupos de séries idênticas (FAZ02/03/04/05/08/09/19 e FAZ07/FAZ15) correspondem a fazendas cujos polígonos cobrem o mesmo conjunto de pixels CHIRPS (0,05°) — isso confirmaria ou refutaria a hipótese de compartilhamento de pixel como explicação, sem presumir que compartilhar pixel implica sobrepor polígono (ver comparar_tres_alternativas_metodologicas()).
4. Avaliar EXPLICITAMENTE, antes de implementar qualquer uma, as diferenças metodológicas entre as três alternativas de referência regional (média simples atual, média ponderada por área, média zonal sobre a união dos polígonos) e a possibilidade de sobreposição espacial entre os 34 polígonos — ver comparar_tres_alternativas_metodologicas() para a comparação já feita aqui, sem cálculo ou implementação de nenhuma delas. Atividade 6 desta rodada é explícita: não implementar automaticamente nenhuma alternativa.
5. Revisitar EXPLICITAMENTE a decisão de CLAUDE.md armadilha 8 (não manter polígonos por fazenda no repositório, por anonimização) antes de cogitar qualquer alternativa que exija esses polígonos (b e c) — essa é uma decisão de privacidade/governança de dados, não uma decisão técnica, e não deve ser contornada implicitamente ao buscar os polígonos por outra via.
6. Reextrair 1991-2011 com scripts/_chirps.py::buscar_prec_chirps (ponto único, já testado) e comparar contra data/chirps_1981_2025.csv já salvo — se os valores baterem, confirma estabilidade de versão do CHIRPS ao longo do tempo; se não baterem, documenta a divergência antes de qualquer uso científico.
7. Rodar scripts/_chirps.py::buscar_prec_chirps_zonal pela suíte de falha de tests/test_fetch_fallback.py (hoje só cobre buscar_prec_chirps) antes de considerar promovê-lo a fonte primária para qualquer finalidade.
8. Só depois de tudo acima: decisão EXPLÍCITA e documentada (não automática, fora do escopo desta tarefa) sobre se/como uma referência CHIRPS construída internamente (pontual, ponderada por área, ou zonal sobre a união dos polígonos) substituiria, complementaria, ou seria reportada lado a lado com a referência observacional atual (MERRA-2/3-municípios pré-1996 + SINOBRAS.csv pós-1996) para fins de validação do CFSv2, considerando a diferença entre a célula de grade do modelo e a área representada pelos polígonos (ver descasamento_de_suporte_espacial em scripts/nmme_auditoria_observacional_historica.py).

## Restrições respeitadas nesta tarefa

- Nenhuma métrica de skill foi calculada.
- Nenhuma previsão ou indicador de desempenho foi recalculado.
- A referência observacional de produção (data/serie_subst.csv) NÃO foi substituída — só lida para comparação.
- Nenhum dado histórico foi modificado.
- O dashboard (docs/index.html) não foi tocado. Nenhum modelo climático foi alterado.
- Nenhuma nova extração do CHIRPS foi executada (nenhum acesso à rede/ClimateSERV nesta tarefa) — a comparação usa exclusivamente data/chirps_1981_2025.csv, já existente no repositório.
