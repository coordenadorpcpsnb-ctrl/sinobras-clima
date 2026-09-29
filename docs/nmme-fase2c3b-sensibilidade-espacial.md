# Análise de sensibilidade espacial — piloto CHIRPS v3.0 (Fase 2C.3B, item 2)

**Análise descritiva — NUNCA substitui automaticamente o pixel de referência do projeto (`CHIRPS_v3_ponto_centroide`). Resultados apresentados separadamente do relatório do primeiro lote histórico, para permitir decisão metodológica antes da reconstrução completa.**

## Contexto

O ponto de referência (lat=-7,80, lon=-47,95) fica classificado como `proximo_de_borda` nos dois eixos (achado confirmado na correção da auditoria independente, Fase 2C.3A) — a cerca de 0,1-0,2m de duas bordas do pixel selecionado. Os vizinhos LESTE (L), SUL (S) e SUDESTE (SL) são os candidatos mais próximos de uma escolha alternativa de pixel sob uma convenção de arredondamento ligeiramente diferente.

## Resultados (17 meses do piloto)

- 17 meses comparáveis (dos 17 do piloto). Diferença absoluta média entre o pixel de referência e os vizinhos L/S/SL (os candidatos mais próximos de uma seleção alternativa, dada a proximidade de borda confirmada nesses dois eixos): 5.032 mm. Diferença absoluta média para os outros 5 vizinhos (sem relação especial com a borda observada): 7.253 mm. A proximidade à borda NÃO parece ter influência prática relevante nos valores — a diferença para os vizinhos mais próximos da borda observada não é sistematicamente maior que para os demais. Esta é uma leitura DESCRITIVA da amostra de 17 meses — nenhuma alternativa de pixel foi adotada, nenhuma referência foi substituída.

### Estatísticas por vizinho

| Vizinho | Relevante p/ borda conhecida | N meses | Diff. abs. média (mm) | Diff. abs. máxima (mm) | Diff. relativa média (%) |
|---|---|---|---|---|---|
| L | SIM | 17 | 1.001 | 20.192 | -2.8 |
| N | não | 17 | 1.623 | 14.868 | -0.87 |
| NL | não | 17 | 3.276 | 29.692 | -2.98 |
| NO | não | 17 | -1.557 | 39.83 | 2.53 |
| O | não | 17 | -3.782 | 49.283 | 1.02 |
| S | SIM | 17 | -0.847 | 14.208 | 5.54 |
| SL | SIM | 17 | 0.112 | 19.956 | -5.42 |
| SO | não | 17 | -3.47 | 61.932 | 23.1 |

## Restrições respeitadas

- Nenhuma alternativa de pixel foi adotada — `CHIRPS_v3_ponto_centroide` continua sendo definido por `scripts/_chirps_v3.py::localizar_pixel()`.
- Nenhum indicador de habilidade preditiva foi calculado.
- Resultados brutos (por mês/vizinho) em `data/chirps_v3_sensibilidade_piloto.csv`.
