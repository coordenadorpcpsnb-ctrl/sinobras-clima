# Protocolo científico proposto — Fase 2C.3C (CFSv2 × CHIRPS v3.0)

**Especificação — nenhum cálculo de skill/habilidade preditiva é feito neste documento nem em nenhum script desta tarefa (Fase 2C.3A).**

## 1. Previsões do CFSv2 usadas

- Período: jan/1991 a dez/2010 (240 inicializações).
- Fonte: `scripts/nmme_extracao_historica.py (já aprovado, 34.560 registros RAW)`.
- Horizontes: H1-H6 (scripts/nmme_extracao_historica.py::LEADS_ESPERADOS).
- Membros: 24 membros por horizonte.

## 2. Correspondência inicialização × horizonte × mês-alvo

- RIGOROSA — cada registro RAW já carrega init_date, target_month e lead (L) explícitos (scripts/nmme_processar.py::montar_linha_raw); o protocolo da 2C.3C deve casar cada previsão com o mês-alvo (target_month) usando exatamente esses três campos, nunca inferir o mês-alvo por contagem posicional a partir do init_date sem checar o valor já gravado.

## 3. Referência observacional para comparação

- A MESMA referência CHIRPS v3.0 (scripts/_chirps_v3.py) para TODO o período 1991-2011 — nunca misturar, dentro de uma mesma avaliação, um trecho com uma metodologia de referência e outro trecho com outra (ver CLAUDE.md armadilha 1 sobre não misturar eixos/referências de naturezas diferentes). Este piloto (17 meses) NÃO é essa reconstrução completa — é a validação da metodologia antes de reconstruir os ~252 meses de 1991-01 a 2011-05 na Fase 2C.3B.

## 4. Climatologia de referência

- Restrição: NUNCA calculada usando os valores do período avaliado (contaminação look-ahead/data leakage) — separação temporal estrita entre a climatologia de referência e o período de teste.
- Correção do corte temporal (item 5): CORREÇÃO (item 5, auditoria independente) — "climatologia expansível usando só anos ANTERIORES ao ano-alvo" ainda pode vazar informação POSTERIOR à data de emissão de uma previsão específica. Exemplo concreto: para o ano-alvo 2000, a regra "anos < 2000" inclui o ano de 1999 inteiro (jan-dez/1999) na climatologia — mas uma previsão inicializada em ago/1999 com H6 (mês-alvo jan/2000) foi EMITIDA antes de set-dez/1999 acontecerem; incluir esses 4 meses de 1999 na climatologia usada para avaliar essa previsão específica é look-ahead, mesmo que 1999 inteiro seja "um ano anterior ao ano-alvo". O corte correto NÃO é por ANO-ALVO — é pela DATA DE INICIALIZAÇÃO (init_date) de CADA previsão avaliada: o conjunto de treinamento da climatologia usada para avaliar uma previsão inicializada em init_date deve conter só observações CHIRPS com data <= o mês anterior a init_date, nunca observações posteriores — independentemente de em que ano-alvo a previsão caia.
- Alternativa (a) — janela expansível: Climatologia EXPANSÍVEL, corrigida: para CADA INICIALIZAÇÃO (init_date) avaliada — não para cada ano-alvo — a climatologia usa todas as observações CHIRPS disponíveis com data estritamente anterior a init_date (disponibilidade real do CHIRPS desde 1981, já confirmada — data/chirps_1981_2025.csv cobre 1981-2025). Cresce ao longo do período avaliado, mas o corte acompanha o CALENDÁRIO REAL de cada inicialização, não um ano-alvo agregado — duas inicializações no mesmo ano-alvo mas em meses diferentes podem (e devem) usar climatologias de tamanho ligeiramente diferente. PROPOSTA INICIAL da tarefa (item 7), não a única.
- Alternativa (b) — leave-one-year-out: Climatologia LEAVE-ONE-YEAR-OUT retrospectiva: para o ano-alvo Y, a climatologia usa TODOS os anos do período de referência EXCETO Y (base fixa maior e simétrica em volta de Y, não só os anos anteriores). Metodologicamente DIFERENTE da expansível — não é uma variação menor dela. Por construção NÃO evita o mesmo tipo de look-ahead residual descrito acima dentro do próprio ano Y-1/Y+1 adjacente a Y — a mesma correção de corte por init_date, quando aplicável, deve ser considerada também aqui.
- Regra: As duas metodologias (a) e (b) NÃO DEVEM ser misturadas nos resultados de uma mesma avaliação — produzir e reportar os dois conjuntos de resultados SEPARADAMENTE, cada um com sua própria climatologia consistente ponta a ponta, nunca um indicador único que combine anos avaliados sob climatologias diferentes.
- Distinção de simulação vs. operação real: Esta é uma SIMULAÇÃO RETROSPECTIVA do que uma climatologia "sem look-ahead" teria sido, usando dados de HOJE — NÃO é uma reprodução estrita das condições operacionais históricas: o CHIRPS v3.0 não existia nos anos 1990 (lançado em 2025-01-01, ver ressalva_retrospectiva_chirps_v3), então nenhuma climatologia baseada nele jamais esteve de fato disponível para um previsor operando naquela época, por mais rigoroso que seja o corte temporal aplicado aqui. O corte por init_date evita UM tipo de contaminação (look-ahead dentro desta simulação), não reconstrói a informação real disponível operacionalmente.
- H1 permanece separado: A separação de H1 dos horizontes genuinamente futuros (ver semantica_de_h1) vale INDEPENDENTEMENTE do corte de climatologia escolhido: por construção, o mês-alvo de H1 é o mesmo mês de init_date, então nenhuma climatologia com corte em "antes de init_date" jamais incluiria a própria observação de H1 — mas H1 ainda deve ser reportado e avaliado separadamente dos demais horizontes (ver separacao_de_resultados), nunca agregado a eles como se fosse igualmente "futuro".

## 5. Avaliação determinística e probabilística

- Determinística: ex.: viés, MAE, RMSE, correlação entre a média/mediana do ensemble e a referência CHIRPS — especificação apenas, nenhum desses é calculado nesta tarefa.
- Probabilística: ex.: CRPS, histograma de rank (rank histogram/Talagrand), diagramas de confiabilidade — usam os 24 membros como distribuição, não só a média/mediana — especificação apenas.
- nenhuma dessas métricas é calculada nesta tarefa (item 6 e item 8 da tarefa são explícitos: não calcular skill nesta etapa).

## 6. Separação dos resultados

- Os resultados da 2C.3C devem ser reportados SEPARADAMENTE por horizonte (H1..H6) e por mês do ano (jan..dez) — nunca um único número agregado que esconda variação sazonal ou degradação de habilidade com o aumento do horizonte. Precedente direto: CLAUDE.md já documenta um viés sazonal forte e heterogêneo entre fontes de satélite (armadilha 7, tabela ERA5/CHIRPS por mês) — não há motivo para esperar que a habilidade do CFSv2 seja homogênea ao longo do ano.

## 7. Dependência temporal das previsões

- Inicializações consecutivas do CFSv2 (mensais) e seus horizontes SE SOBREPÕEM no tempo — o mês-alvo de dez/1990+H3 pode coincidir com o de jan/1991+H2, por exemplo — introduzindo autocorrelação entre "amostras" nominalmente independentes. O protocolo da 2C.3C precisa decidir explicitamente como tratar essa dependência (ex.: blocos por ano-alvo em vez de por inicialização, ou métodos de reamostragem/bootstrap que respeitem a estrutura temporal) — NENHUMA decisão é tomada aqui, só o requisito é registrado.

## 8. Semântica de H1

- CONFIRMADO em scripts/nmme_processar.py (leadtime_para_mes_alvo_nmme, esquema padrão 'lead1_igual_mes_inicializacao', validado por _avaliar_semantica_forecast_period/Método B): H1 tem target_month IGUAL ao mês da própria inicialização — não o mês seguinte. Isso significa que H1 NÃO é uma previsão de um período genuinamente futuro no sentido estrito: no momento em que o CFSv2 inicializa (tipicamente no início do mês), o mês-alvo de H1 ainda está em curso e sua precipitação observada ainda não está disponível por completo. A tarefa pede explicitamente para confirmar se H1 deve ser classificado como "previsão" ou "previsão do mês corrente" — a REGISTRAR EXPLICITAMENTE na 2C.3C, considerando a disponibilidade temporal real dos dados: tratar H1 igual a H2-H6 (horizontes genuinamente futuros no momento da inicialização) arriscaria superestimar a habilidade do CFSv2 nesse horizonte especificamente por conter informação parcial do próprio mês-alvo. Nenhuma decisão de classificação é tomada aqui — só o achado e o risco são registrados, com a fonte exata no código que confirma a semântica.

## 9. Ressalva sobre uso retrospectivo do CHIRPS v3.0

- Usar CHIRPS v3.0 (lançado em 2025-01-01, README oficial) retrospectivamente para avaliar previsões do CFSv2 de 1991-2010 NÃO equivale a ter os mesmos dados que estariam disponíveis operacionalmente naquela década — é uma referência de verificação com informação/estações incorporadas DEPOIS do fato (>90 fontes de estação na v3.0 contra as fontes disponíveis nos anos 1990; correção de sub-captação por vento; preenchimento de lacunas com ERA5, produto que só existe desde muito depois). Isso é o padrão da literatura de verificação retrospectiva (reanalysis/reforecast usa a melhor referência disponível HOJE, não a de época) — mas precisa ser registrado explicitamente como limitação de interpretação, nunca apresentado como "os mesmos dados que os previsores tinham em mãos na década de 1990".

