# Primeiro lote histórico CHIRPS v3.0 — lote 0 (1981-01 a 1982-12) — Fase 2C.3B

**Relatório técnico — não substitui dados operacionais, não calcula skill, não altera SARIMAX/XGBoost/dashboard/previsões históricas do CFSv2.**

## 1. Resultados do lote

- Período: 1981-01 a 1982-12 (24 meses).
- Veredito: **APROVADO**.
- APROVADO — cobertura temporal completa: de 24 meses obrigatórios, 24 estavam disponíveis no servidor, 24 tiveram extração bem-sucedida (raster aberto, grade validada, pixel lido e classificado), mas só 24 têm um VALOR VÁLIDO utilizável (ok/zero_real) — 0 ausentes no servidor e 0 com NoData NÃO contam como valor válido, mesmo sendo respostas 'esperadas' do servidor/produto. Um período obrigatório e fixo (como este — todos os meses já deveriam estar publicados) só é considerado com cobertura temporal completa quando TODOS os meses têm valor válido — mes_ausente/NoData/falha de extração em QUALQUER mês impede a aprovação plena, mesmo que sejam respostas 'legítimas' do servidor. Reprovação bloqueia o uso científico deste período até a causa raiz ser corrigida — nunca prosseguir com dado incompleto/corrompido/ausente tratado como se fosse íntegro.

### Quatro dimensões

1. Disponibilidade no servidor: 24/24.
2. Extração bem-sucedida: 24/24.
3. Valor válido disponível: 24/24.
4. Cobertura temporal completa: SIM.

## 2. Comparação com os dados existentes (descritiva)

- 24 meses comparados a três referências: (1) CHIRPS v3.0 Final, novo, ponto único no centroide, versão e metodologia CONTROLADAS (esta extração); (2) CHIRPS histórico existente (data/chirps_1981_2025.csv), extraído pelo ClimateSERV — a versão do CHIRPS usada NUNCA foi registrada por aquele pipeline, então NÃO é identificada aqui como 'CHIRPS v2 confirmado'; (3) série consolidada de produção (data/serie_subst.csv), que combina procedência pré-1996 não comprovada com estimativas CHIRPS ZONAIS por fazenda pós-1996 (metodologia diferente por desenho — zonal vs. ponto). NESTA amostra de 24 meses: 11 meses com CHIRPS v3 superior ao existente, 13 inferior, 0 iguais — diferença média assinada de -5.9 mm (diferença absoluta média 15.47 mm). Isto NÃO confirma nem contradiz, isoladamente, a afirmação geral do README oficial de que "CHIRPS v3.0 is overall wetter compared to CHIRPS v2.0" — aquela é uma caracterização do produto AGREGADO/GLOBAL; esta amostra é REGIONAL (1 ponto, 24 meses, região historicamente com viés conhecido em jun-ago e out-dez, CLAUDE.md armadilha 7) e pequena demais para generalizar. As duas coisas são distintas e não devem ser confundidas: comportamento documentado do produto vs. comportamento observado nesta amostra específica. Nenhum indicador de habilidade preditiva do CFSv2 foi calculado — só estatística descritiva de comparação entre referências (item 6 da tarefa).

## 3. Análise de sensibilidade espacial

- Análise de sensibilidade espacial (item 2) apresentada SEPARADAMENTE — ver o relatório dedicado, não duplicada aqui. Ver `docs/nmme-fase2c3b-sensibilidade-espacial.md`.

## 4. Estado geral da reconstrução histórica

- Lotes com cobertura temporal completa: 1/16.

| Lote | Período | Cobertura completa | Meses válidos |
|---|---|---|---|
| 0 | 1981-01 a 1982-12 | SIM | 24/24 |
| 1 | 1983-01 a 1984-12 | não | 0/24 |
| 2 | 1985-01 a 1986-12 | não | 0/24 |
| 3 | 1987-01 a 1988-12 | não | 0/24 |
| 4 | 1989-01 a 1990-12 | não | 0/24 |
| 5 | 1991-01 a 1992-12 | não | 0/24 |
| 6 | 1993-01 a 1994-12 | não | 0/24 |
| 7 | 1995-01 a 1996-12 | não | 0/24 |
| 8 | 1997-01 a 1998-12 | não | 0/24 |
| 9 | 1999-01 a 2000-12 | não | 0/24 |
| 10 | 2001-01 a 2002-12 | não | 0/24 |
| 11 | 2003-01 a 2004-12 | não | 0/24 |
| 12 | 2005-01 a 2006-12 | não | 0/24 |
| 13 | 2007-01 a 2008-12 | não | 0/24 |
| 14 | 2009-01 a 2010-12 | não | 0/24 |
| 15 | 2011-01 a 2011-05 | não | 0/5 |

## Restrições respeitadas

- Nenhum dado operacional foi substituído.
- SARIMAX, XGBoost, dashboard e as previsões históricas do CFSv2 não foram alterados.
- Nenhum indicador de habilidade preditiva foi calculado.
- Os demais lotes NÃO foram iniciados automaticamente.
