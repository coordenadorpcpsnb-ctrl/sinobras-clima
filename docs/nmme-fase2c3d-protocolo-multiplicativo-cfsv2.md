# Protocolo da correção multiplicativa do CFSv2 — Fase 2C.3D (Método 3.2)

**Documento de diagnóstico PRÉVIO — não é relatório de resultados.** Nenhum `forecast_calibrado` multiplicativo foi calculado. Nenhum skill, RMSE ou razão aplicada a uma previsão real foi calculado nesta atividade — só a distribuição dos dois ingredientes já aprovados (`climatologia_observada`, `climatologia_modelo_raw`) da tabela do Método 3.1, já aprovada (`data/cfsv2_calibracao_2c3d/aditiva_expanding.csv`), lida aqui, nunca reescrita. O piso de segurança proposto é definido exclusivamente por estabilidade numérica/física — nunca escolhido observando qual valor produziria melhor skill, porque nenhum skill existe ainda.

## 0. Desenho que será reaproveitado integralmente (regras fixas)

- `N_TREINO_MINIMO = 10` (protocolo, Seção 5.1) — mesmo warm-up do Método 3.1.
- Expanding-window causal como avaliação principal; avaliação principal restrita aos MESMOS casos elegíveis do método aditivo (N=720=120×6 leads, `status_calibracao='ok'` da tabela aprovada).
- LOYO full apenas descritivo; LOYO matched para a comparação direta (protocolo, Seção 5.1 da 2C.3D revisão 2).
- Três benchmarks: CFSv2 bruto, climatologia causal, `benchmark_anomalia_reconstruida`.
- Bootstrap em blocos por `target_ano`; mesmo critério de aprovação (IC 95% de `skill_vs_anomalia_reconstruida` E `RMSESS_climatologia` totalmente acima de zero, simultaneamente).
- H1 sempre separado de H2-H6.
- Matriz mês × lead só como diagnóstico de heterogeneidade, nunca 72 testes de significância.

## 1. Distribuição histórica de média(forecast_raw_treino) — o denominador

População analisada: N=720 (status_calibracao='ok' da tabela aprovada do Método 3.1 — a MESMA população que o Método 3.2 usará).

### 1.1. Por mês-alvo (todos os leads agregados)

| Mês | N | Mínimo | p05 | p10 | p25 | Mediana | Média | p75 | p90 | Máximo |
|---|---|---|---|---|---|---|---|---|---|---|
| Jan | 60 | 210.94 | 214.85 | 223.61 | 252.80 | 303.19 | 285.74 | 309.75 | 326.66 | 328.05 |
| Fev | 60 | 204.15 | 207.47 | 211.54 | 255.05 | 304.45 | 288.30 | 321.10 | 331.26 | 337.75 |
| Mar | 60 | 245.52 | 247.59 | 253.59 | 312.67 | 352.66 | 337.19 | 376.76 | 379.60 | 386.63 |
| Abr | 60 | 139.45 | 142.69 | 146.64 | 193.94 | 203.19 | 197.84 | 212.68 | 225.55 | 228.98 |
| Mai | 60 | 21.49 | 22.53 | 23.22 | 23.57 | 24.46 | 25.13 | 25.89 | 28.42 | 32.89 |
| Jun | 60 | 0.85 | 0.98 | 0.99 | 1.02 | 1.40 | 1.43 | 1.75 | 2.00 | 2.18 |
| Jul | 60 | 0.29 | 0.38 | 0.44 | 0.86 | 1.06 | 1.09 | 1.23 | 1.95 | 2.10 |
| Ago | 60 | 0.44 | 0.49 | 0.51 | 1.15 | 1.77 | 1.66 | 2.11 | 2.64 | 2.98 |
| Set | 60 | 3.23 | 3.53 | 3.76 | 5.05 | 6.01 | 5.71 | 6.60 | 6.89 | 7.27 |
| Out | 60 | 16.62 | 17.33 | 18.02 | 21.52 | 24.29 | 23.32 | 25.88 | 26.34 | 27.91 |
| Nov | 60 | 80.12 | 82.71 | 83.20 | 95.60 | 109.34 | 106.51 | 119.56 | 121.88 | 127.24 |
| Dez | 60 | 161.74 | 164.26 | 166.68 | 219.57 | 236.43 | 231.58 | 257.30 | 269.62 | 272.83 |

### 1.2. Por lead (todos os meses agregados)

| Lead | N | Mínimo | p05 | p10 | p25 | Mediana | Média | p75 | p90 | Máximo |
|---|---|---|---|---|---|---|---|---|---|---|
| H1 | 120 | 0.29 | 0.44 | 0.49 | 2.97 | 56.51 | 94.13 | 179.19 | 225.40 | 256.40 |
| H2 | 120 | 0.69 | 0.88 | 1.10 | 4.53 | 59.43 | 115.46 | 228.76 | 259.45 | 316.89 |
| H3 | 120 | 0.96 | 1.22 | 1.32 | 4.79 | 63.31 | 127.89 | 248.56 | 304.16 | 345.96 |
| H4 | 120 | 1.31 | 1.41 | 1.75 | 3.59 | 68.94 | 134.17 | 264.57 | 318.92 | 362.83 |
| H5 | 120 | 0.85 | 1.00 | 1.13 | 4.69 | 72.05 | 139.23 | 270.26 | 321.83 | 382.73 |
| H6 | 120 | 0.77 | 0.95 | 1.00 | 5.43 | 72.99 | 141.87 | 285.19 | 333.40 | 386.63 |

### 1.3. Por grupo sazonal (chuvosa/transição/seca)

| Grupo | N | Mínimo | p05 | p10 | p25 | Mediana | Média | p75 | p90 | Máximo |
|---|---|---|---|---|---|---|---|---|---|---|
| chuvosa | 420 | 16.62 | 22.93 | 25.66 | 119.61 | 224.79 | 210.07 | 304.63 | 333.40 | 386.63 |
| transicao | 120 | 3.23 | 3.76 | 4.89 | 6.01 | 14.38 | 15.42 | 24.46 | 26.59 | 32.89 |
| seca | 180 | 0.29 | 0.44 | 0.53 | 0.99 | 1.30 | 1.39 | 1.86 | 2.11 | 2.98 |

## 2. Proposta objetiva do piso

**Piso proposto: 10.0mm.** Critério: existe um GAP VAZIO no denominador entre o maior valor dos meses mais secos e o menor valor dos demais meses — **nenhum (lead, mês) tem denominador dentro desse intervalo**, confirmado para todos os 6 leads individualmente, não só no agregado:

- Maior denominador entre os meses inteiramente abaixo do piso: 7.27mm.
- Menor denominador entre os meses inteiramente acima do piso: 16.62mm.
- Gap seguro confirmado: [7.27, 16.62]mm — o piso proposto (10.0mm) cai dentro desse gap, portanto **nenhum mês é fragmentado em nenhum lead**.
- Meses inteiramente abaixo do piso: Jun, Jul, Ago, Set.
- Meses inteiramente acima do piso: Jan, Fev, Mar, Abr, Mai, Out, Nov, Dez.
- Meses fragmentados pelo piso (deveria ser vazio): nenhum.

**O piso NUNCA foi escolhido observando qual valor produz melhor RMSE/skill — nenhum skill multiplicativo foi calculado nesta atividade.** A escolha é puramente baseada em onde a distribuição do denominador tem uma separação natural entre meses fisicamente secos e os demais.

## 3. Quantidade de casos que seriam excluídos

| Piso candidato (mm) | N excluído | % excluído |
|---|---|---|
| 0.5 | 15 | 2.1% |
| 1.0 | 50 | 6.9% |
| 2.0 | 150 | 20.8% |
| 3.0 | 180 | 25.0% |
| 5.0 | 193 | 26.8% |
| 10.0 **(proposto)** | 240 | 33.3% |
| 15.0 | 240 | 33.3% |
| 20.0 | 250 | 34.7% |
| 30.0 | 358 | 49.7% |

**No piso proposto (10.0mm): 240 de 720 casos elegíveis seriam excluídos (33.3%)** — corresponde exatamente aos meses jun-set em todos os 6 leads (4 meses × 6 leads × 10 anos = 240), o núcleo da estação seca regional (CLAUDE.md: seca bem marcada jun-ago, com setembro de transição tardia).

## 4. Distribuição das razões resultantes (puramente descritivo — nunca um skill)

`razão = climatologia_observada / climatologia_modelo_raw` — ambas já causais, herdadas do Método 3.1. Esta NÃO é uma previsão calibrada nem uma métrica de skill — é só a razão entre duas climatologias, para entender a MAGNITUDE que o fator multiplicativo teria.

### 4.1. Por mês-alvo

| Mês | N | Mínimo | p05 | p10 | p25 | Mediana | Média | p75 | p90 | Máximo |
|---|---|---|---|---|---|---|---|---|---|---|
| Jan | 60 | 0.82 | 0.84 | 0.86 | 0.89 | 0.91 | 0.99 | 1.10 | 1.25 | 1.31 |
| Fev | 60 | 0.63 | 0.66 | 0.66 | 0.69 | 0.72 | 0.78 | 0.86 | 1.04 | 1.05 |
| Mar | 60 | 0.71 | 0.71 | 0.72 | 0.73 | 0.78 | 0.83 | 0.87 | 1.08 | 1.14 |
| Abr | 60 | 0.86 | 0.88 | 0.91 | 0.92 | 0.99 | 1.04 | 1.04 | 1.38 | 1.43 |
| Mai | 60 | 2.33 | 2.63 | 2.69 | 2.97 | 3.16 | 3.12 | 3.26 | 3.53 | 3.74 |
| Jun | 60 | 3.38 | 3.59 | 3.85 | 4.43 | 5.55 | 5.78 | 7.41 | 7.82 | 9.38 |
| Jul | 60 | 2.16 | 2.26 | 2.45 | 3.85 | 4.53 | 5.46 | 5.59 | 11.23 | 15.78 |
| Ago | 60 | 4.01 | 4.46 | 4.74 | 5.61 | 7.15 | 10.06 | 11.28 | 24.61 | 26.78 |
| Set | 60 | 8.35 | 8.94 | 9.31 | 9.55 | 10.43 | 11.72 | 12.78 | 16.78 | 18.75 |
| Out | 60 | 4.66 | 4.82 | 4.90 | 5.02 | 5.35 | 5.67 | 6.10 | 7.33 | 7.61 |
| Nov | 60 | 1.59 | 1.61 | 1.62 | 1.65 | 1.84 | 1.90 | 2.08 | 2.35 | 2.47 |
| Dez | 60 | 0.73 | 0.73 | 0.73 | 0.77 | 0.84 | 0.88 | 0.90 | 1.19 | 1.23 |

## 5. Risco específico na estação seca — E um achado adicional fora da estação seca

### 5.1. Estação seca (esperado)

Jun-set têm os menores denominadores de toda a série (máximo 7.27mm) — risco de razão INSTÁVEL/EXPLOSIVA por denominador pequeno, exatamente o modo de falha já documentado em produção (`CLAUDE.md`, armadilha 7: corrigir julho por um fator fixo multiplicou a chuva por quase 46× e piorou o RMSE do SARIMAX). O piso proposto (Seção 2) remove inteiramente esse risco, excluindo esses meses da avaliação multiplicativa principal.

### 5.2. Achado adicional — risco SISTEMÁTICO mesmo acima do piso (não esperado)

**Mesmo com denominador ACIMA do piso proposto, algumas células (mês, lead) têm razão mediana consistentemente alta em TODOS os ~10 anos — não é instabilidade de amostra pequena, é um viés sistemático real do CFSv2.** Destaque: outubro, em TODOS os 6 leads, com denominador seguro (16,6-25,7mm) mas razão mediana entre 4,9× e 7,4× — o modelo climatologicamente prevê ~17-26mm para outubro quando a climatologia observada causal é ~125-133mm (consistente com a climatologia de referência do projeto, `CLIM_JAN_DEZ[9]=119,7mm` no `CLAUDE.md`). Maio e novembro mostram o mesmo padrão em menor intensidade (maio: 2,3-3,7×; novembro: 1,6-2,5×).

| Mês | Lead | Denom. mínimo (mm) | Razão mediana | Razão min-max | N |
|---|---|---|---|---|---|
| Out | H1 | 16.62 | 7.39 | 7.05-7.61 | 10 |
| Out | H2 | 20.53 | 6.11 | 5.84-6.20 | 10 |
| Out | H5 | 22.49 | 5.43 | 5.09-5.93 | 10 |
| Out | H6 | 23.82 | 5.20 | 5.02-5.37 | 10 |
| Out | H3 | 25.72 | 4.95 | 4.66-5.15 | 10 |
| Out | H4 | 24.71 | 4.92 | 4.71-5.40 | 10 |
| Mai | H6 | 21.49 | 3.46 | 3.20-3.74 | 10 |
| Mai | H3 | 23.45 | 3.21 | 2.98-3.59 | 10 |
| Mai | H5 | 23.14 | 3.18 | 3.09-3.58 | 10 |
| Mai | H4 | 22.56 | 3.15 | 3.02-3.55 | 10 |
| Mai | H2 | 25.42 | 2.96 | 2.60-3.39 | 10 |
| Mai | H1 | 26.58 | 2.68 | 2.33-2.85 | 10 |
| Nov | H1 | 80.12 | 2.37 | 2.26-2.47 | 10 |
| Nov | H2 | 91.13 | 2.08 | 1.99-2.11 | 10 |
| Nov | H3 | 99.57 | 1.91 | 1.87-1.96 | 10 |
| Nov | H4 | 109.96 | 1.78 | 1.71-1.81 | 10 |
| Nov | H5 | 119.23 | 1.65 | 1.61-1.68 | 10 |
| Nov | H6 | 119.81 | 1.62 | 1.59-1.64 | 10 |

**Implicação para a implementação futura do Método 3.2**: um piso baseado só na magnitude do denominador NÃO protege contra esse risco — outubro passa pelo piso de 10mm sem ser excluído, mas pediria um fator multiplicativo de ~5-7× baseado em só ~10 pontos históricos por lead, risco real de overfitting (protocolo, Seção 4, item 1: seleção/ajuste de parâmetro com amostra pequena). Isso deve ser avaliado explicitamente quando o Método 3.2 for implementado — por exemplo, reportando outubro separadamente na matriz mês×lead (diagnóstico de heterogeneidade, nunca removido silenciosamente) e considerando se um teto na razão (Seção 6) é também necessário, não só um piso no denominador.

## 6. Regra para impedir previsão negativa ou explosiva

- Climatologia observada causal <= 0 em 0 casos; climatologia do modelo bruto causal <= 0 em 0 casos; forecast_raw negativo em 0 casos.
- **A razão NUNCA pode ser negativa nesta amostra — precipitação é sempre >= 0 em ambas as climatologias causais e no forecast_raw, confirmado programaticamente.**
- Após aplicar o piso proposto, a razão varia entre 0.633× e 7.608× — **o risco real remanescente é EXPLOSIVO/sistemático (Seção 5.2), não negativo**.
- Regra proposta para a implementação futura: `status_multiplicativo = 'denominador_abaixo_do_piso'` quando `climatologia_modelo_raw < 10mm` — exclusão da avaliação multiplicativa principal, SEM fallback automático para a correção aditiva (isso criaria um método híbrido aditivo/multiplicativo, dificultando saber qual método produziu o resultado — uma versão híbrida pode ser avaliada posteriormente como método SEPARADO, se houver justificativa, nunca implícita).

## 7. Confirmação de que nenhum skill multiplicativo foi calculado

- `nenhum_skill_multiplicativo_calculado`: True.
- `nenhum_forecast_calibrado_multiplicativo_calculado`: True.
- Esta atividade analisou só a distribuição de duas climatologias causais já aprovadas (`climatologia_observada`, `climatologia_modelo_raw`) e sua razão — nenhum `forecast_calibrado = forecast_raw × razão` foi computado, nenhum RMSE, MAE, correlação de anomalia, skill ou IC do método multiplicativo foi calculado.
- `data/cfsv2_calibracao_2c3d/aditiva_expanding.csv` (Método 3.1, aprovado) foi só lido, nunca alterado.

## Próximos passos (fora do escopo desta atividade)

1. Revisão deste diagnóstico e do piso proposto (10mm).
2. Implementação do Método 3.2 em si: `forecast_calibrado = forecast_raw × razão`, com `status_multiplicativo='denominador_abaixo_do_piso'` para `climatologia_modelo_raw < 10mm`, reaproveitando integralmente o desenho da Seção 0.
3. Avaliação explícita do achado da Seção 5.2 (outubro e, em menor grau, maio e novembro) na matriz mês×lead da implementação — nunca escondida.
4. Só depois disso, calcular os três skills e os ICs do Método 3.2 — nunca antes de fixar o piso.
