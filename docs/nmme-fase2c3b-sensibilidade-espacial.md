# Análise de sensibilidade espacial — piloto CHIRPS v3.0 (Fase 2C.3B, item 2)

**Análise descritiva — NUNCA substitui automaticamente o pixel de referência do projeto (`CHIRPS_v3_ponto_centroide`). Resultados apresentados separadamente do relatório do primeiro lote histórico, para permitir decisão metodológica antes da reconstrução completa.**

## Contexto

O ponto de referência (lat=-7,80, lon=-47,95) fica classificado como `proximo_de_borda` nos dois eixos (achado confirmado na correção da auditoria independente, Fase 2C.3A) — a cerca de 0,1-0,2m de duas bordas do pixel selecionado. Os vizinhos LESTE (L), SUL (S) e SUDESTE (SL) são os candidatos mais próximos de uma escolha alternativa de pixel sob uma convenção de arredondamento ligeiramente diferente.

## Resultados (17 meses do piloto)

- 17 meses comparáveis (dos 17 do piloto). Diferença ABSOLUTA média entre o pixel de referência e os vizinhos L/S/SL (os candidatos mais próximos de uma seleção alternativa, dada a proximidade de borda confirmada nesses dois eixos): 5.03 mm — máxima observada 20.19 mm (vizinho L, 2010-01). Diferença absoluta média para os outros 5 vizinhos (sem relação especial com a borda observada): 7.25 mm — máxima observada 61.93 mm (vizinho SO, 1991-01). A média absoluta mais baixa nos três vizinhos selecionados, isoladamente, NÃO é suficiente para concluir que a proximidade à borda tem influência prática irrelevante — uma média apaga a variação mês a mês, e as diferenças MÁXIMAS mostram que casos individuais chegam a dezenas de mm em ambos os grupos (ver tabela por vizinho). A importância prática de uma diferença desse tamanho depende da aplicação (o balanço hídrico é mais sensível perto do mês crítico, quando o ARM já está baixo, do que num mês de solo saturado) e da época do ano (a mesma diferença em mm pode ser desprezível num mês chuvoso e representar grande fração da chuva total num mês seco — CLAUDE.md armadilha 7 documenta como o viés de fonte já varia fortemente por mês nesta região). Esta análise NÃO conclui, isoladamente, se a proximidade à borda importa ou não na prática — essa avaliação cabe a quem decide sobre a reconstrução, considerando o uso pretendido dos dados. Esta é uma leitura DESCRITIVA da amostra de 17 meses — nenhuma alternativa de pixel foi adotada, nenhuma referência foi substituída.

### Estatísticas por vizinho

Três métricas SEPARADAS, nunca confundidas: diferença média COM SINAL (pode ser positiva ou negativa — indica se o vizinho tende a ficar acima ou abaixo do centro), diferença ABSOLUTA média (magnitude típica, ignora o sinal) e diferença ABSOLUTA máxima observada na amostra (com o mês em que ocorreu).

| Vizinho | Relevante p/ borda conhecida | N meses | Diff. média COM SINAL (mm) | Diff. ABSOLUTA média (mm) | Diff. ABSOLUTA máxima (mm) | Mês da máxima | Diff. relativa média (%) |
|---|---|---|---|---|---|---|---|
| L | SIM | 17 | 1.0 | 5.63 | 20.19 | 2010-01 | -2.8 |
| N | não | 17 | 1.62 | 3.37 | 14.87 | 2011-05 | -0.87 |
| NL | não | 17 | 3.28 | 8.05 | 29.69 | 1998-01 | -2.98 |
| NO | não | 17 | -1.56 | 8.91 | 39.83 | 1991-04 | 2.53 |
| O | não | 17 | -3.78 | 7.77 | 49.28 | 1991-01 | 1.02 |
| S | SIM | 17 | -0.85 | 4.13 | 14.21 | 1991-01 | 5.54 |
| SL | SIM | 17 | 0.11 | 5.34 | 19.96 | 1991-01 | -5.42 |
| SO | não | 17 | -3.47 | 8.17 | 61.93 | 1991-01 | 23.1 |

### Diferenças máximas — resumo por grupo

As diferenças ABSOLUTAS máximas mostram que casos individuais chegam a dezenas de mm em ambos os grupos, mesmo quando a média absoluta de um grupo é menor que a do outro — a importância prática dessas máximas depende da aplicação (mês crítico do balanço hídrico vs. mês de solo saturado) e da época do ano (a mesma diferença em mm pode ser desprezível num mês chuvoso e representar grande fração da chuva total num mês seco).

- Vizinhos relevantes p/ borda (L/S/SL): diferença absoluta máxima 20.19 mm.
- Demais vizinhos: diferença absoluta máxima 61.93 mm.

## Restrições respeitadas

- Nenhuma alternativa de pixel foi adotada — `CHIRPS_v3_ponto_centroide` continua sendo definido por `scripts/_chirps_v3.py::localizar_pixel()`.
- Nenhum indicador de habilidade preditiva foi calculado.
- Resultados brutos (por mês/vizinho) em `data/chirps_v3_sensibilidade_piloto.csv` — preservados intactos desta correção (nenhuma extração real foi refeita).
