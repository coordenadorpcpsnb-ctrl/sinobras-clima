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
- Alternativa (a) — janela expansível: Climatologia EXPANSÍVEL: para cada ano-alvo Y avaliado, a climatologia usa todos os anos de 1981 até Y-1 (disponibilidade real do CHIRPS desde 1981, já confirmada — data/chirps_1981_2025.csv cobre 1981-2025). Cresce ao longo do período avaliado — a climatologia usada para 1991 tem 10 anos de base (1981-1990), a usada para 2010 tem 29 anos (1981-2009). PROPOSTA INICIAL da tarefa (item 7), não a única.
- Alternativa (b) — leave-one-year-out: Climatologia LEAVE-ONE-YEAR-OUT retrospectiva: para o ano-alvo Y, a climatologia usa TODOS os anos do período de referência EXCETO Y (base fixa maior e simétrica em volta de Y, não só os anos anteriores). Metodologicamente DIFERENTE da expansível — não é uma variação menor dela.
- Regra: As duas metodologias (a) e (b) NÃO DEVEM ser misturadas nos resultados de uma mesma avaliação — produzir e reportar os dois conjuntos de resultados SEPARADAMENTE, cada um com sua própria climatologia consistente ponta a ponta, nunca um indicador único que combine anos avaliados sob climatologias diferentes.

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

