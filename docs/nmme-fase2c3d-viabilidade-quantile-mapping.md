# Gate de viabilidade — Método 3.3 (Quantile Mapping), Fase 2C.3D

**Documento de GATE — não é uma avaliação de desempenho.** Nenhum `forecast_calibrado` por quantile mapping foi calculado. Nenhum RMSE, MAE, skill ou IC do Método 3.3 existe nesta atividade — só a contagem, programática, de quantas observações históricas causais cada célula (lead × mês-alvo) teria disponível para treinar um mapeamento de quantis, comparada ao limiar pré-registrado `AMOSTRA_MINIMA_ESTRATO = 20`.

## 0. Restrição estrutural da amostra

O CFSv2 histórico aprovado (`data/nmme_historico_fazendas/`) é um hindcast **FIXO**: 240 inicializações, jan/1991-dez/2010 (20 anos) — não cresce com o calendário atual, é a extração já aprovada na Fase 2C.3C. A calibração é causal (`init_date_treino < init_date_avaliada`) e específica por `lead × mês-alvo`; como mês-alvo = mês de inicialização + lead - 1 (função determinística do mês de inicialização para um lead fixo), **cada célula tem exatamente 1 inicialização por ano** — no máximo 20 observações totais por célula, no máximo 19 estritamente anteriores à última (causal nunca inclui a própria avaliada).

- N total de previsões avaliadas (todas as células, todos os leads): 1440.
- N total de células (lead × mês-alvo): 72 (6 leads × 12 meses).
- Verificação de que os 24 membros do ensemble NÃO inflaram a contagem (item 3 do pedido): 34560 linhas na base pareada (membro a membro) → 1440 linhas após deduplicar para 1 por (init_date, lead) — exatamente 1440 esperado (✅ OK).

## 1. Máximo N causal disponível por célula

**Máximo observado em TODA a base: 19** (confirmado no fim da série — a última inicialização cronológica de cada célula, ano 2010). Mínimo do máximo entre as 72 células: 19. Valores distintos de máximo observados entre as células: [19] — todas as células têm o MESMO máximo de N causal (a lista acima tem um único valor) — estrutural, não um achado de uma célula específica: cada célula tem exatamente 1 inicialização por ano, então a posição cronológica da última inicialização determina o máximo igualmente em toda célula.

### 1.1. Matriz do máximo de N causal por célula (lead × mês-alvo)

| Mês \ Lead | H1 | H2 | H3 | H4 | H5 | H6 |
|---|---|---|---|---|---|---|
| Jan | 19 | 19 | 19 | 19 | 19 | 19 |
| Fev | 19 | 19 | 19 | 19 | 19 | 19 |
| Mar | 19 | 19 | 19 | 19 | 19 | 19 |
| Abr | 19 | 19 | 19 | 19 | 19 | 19 |
| Mai | 19 | 19 | 19 | 19 | 19 | 19 |
| Jun | 19 | 19 | 19 | 19 | 19 | 19 |
| Jul | 19 | 19 | 19 | 19 | 19 | 19 |
| Ago | 19 | 19 | 19 | 19 | 19 | 19 |
| Set | 19 | 19 | 19 | 19 | 19 | 19 |
| Out | 19 | 19 | 19 | 19 | 19 | 19 |
| Nov | 19 | 19 | 19 | 19 | 19 | 19 |
| Dez | 19 | 19 | 19 | 19 | 19 | 19 |

### 1.2. Distribuição de N ao longo do tempo (agregada, todas as 72 células)

Cada célula percorre exatamente a mesma sequência cronológica de N (0, 1, 2, ..., 19) — por isso a contagem por valor é idêntica em toda a tabela (72 células, 1 ocorrência de cada valor por célula):

| N causal | N° de previsões com esse N (em todas as células) |
|---|---|
| 0 | 72 |
| 1 | 72 |
| 2 | 72 |
| 3 | 72 |
| 4 | 72 |
| 5 | 72 |
| 6 | 72 |
| 7 | 72 |
| 8 | 72 |
| 9 | 72 |
| 10 | 72 |
| 11 | 72 |
| 12 | 72 |
| 13 | 72 |
| 14 | 72 |
| 15 | 72 |
| 16 | 72 |
| 17 | 72 |
| 18 | 72 |
| 19 | 72 |

## 2. Avaliação formal contra o limiar pré-registrado

`AMOSTRA_MINIMA_ESTRATO = 20` — mesmo limiar já usado em toda a Fase 2C.3C/2C.3D, **nunca reduzido** depois de conhecer os resultados dos Métodos 3.1/3.2.

- **Número de previsões com N >= 20: 0** (de 1440 avaliadas).
- **Número de células com N >= 20: 0** (de 72).
- Primeiro ano elegível: não aplicável — nenhuma previsão real atinge o limiar nesta base histórica fixa (1991-2010, 20 anos/célula). Hipoteticamente, SE o hindcast tivesse 21 anos numa célula (falta 1 ano além dos 20 disponíveis), a 21ª inicialização cronológica daquela célula seria a primeira elegível — mas essa inicialização NÃO existe na base aprovada; não é uma projeção de calendário (a base é um hindcast fixo, não um fluxo que cresce com o tempo presente).
- Período avaliável restante: nenhum — toda a amostra causal disponível (240 inicializações × 6 leads) foi esgotada sem nenhuma previsão atingir o limiar; não há período adicional a esperar dentro da base de hindcast aprovada.

## 3. LOYO — SOMENTE como contexto (nunca como substituto da avaliação causal)

`SÓ diagnóstico de viabilidade — NUNCA usado para declarar o método testável se o causal não atingir o mínimo (item 4 do pedido). LOYO exclui só o próprio ano, logo n_treino_loyo é uniforme por célula (= N_total_da_célula - 1), não cresce com o tempo como o causal.`

- Máximo de N em desenho LOYO (exclui só o próprio ano, usa passado E futuro): 19.
- Número de células que atingiriam o limiar em LOYO: 0 de 72.
- **O mesmo teto estrutural (20 anos totais na base) limita o LOYO tanto quanto o causal** — LOYO ganha só 1 ano extra por célula (o próprio ano, no caso causal sempre excluído; aqui também excluído, mas sem a exigência de ser só passado), nunca o suficiente para cruzar o limiar de 20. Isto confirma que a limitação é estrutural do período histórico disponível, não um artefato do desenho causal especificamente.

## 4. Decisão final

**`metodo_3_3_status = nao_testavel_amostra_insuficiente`**

O Método 3.3 (quantile mapping) é **NÃO TESTÁVEL por insuficiência de amostra** — **isto não é uma falha do pipeline**, é uma limitação estrutural do período histórico disponível (20 anos de hindcast CFSv2, máximo de 19 observações causais por célula, sempre abaixo do limiar de 20 exigido para quantile mapping).

Conforme o próprio protocolo pré-registrado, o Método 3.3 é **pulado** por insuficiência de amostra. O próximo método elegível é:

**`metodo_3_4_regressao_linear_mos_simples`** — Método 3.4, regressão linear / MOS simples. **Não implementado nesta atividade.**

## 5. O que NÃO foi feito nesta atividade (item 3 do pedido)

- Nenhum pooling entre meses ou entre leads.
- Nenhuma redução do limiar de 20 observado nos resultados.
- Nenhuma interpolação de quantis com N < 20.
- LOYO usado SOMENTE como contexto (seção 3), nunca como substituto da avaliação causal para declarar o método testável.
- Nenhum uso de 1981-1990 como se fossem previsões CFSv2 (o CFSv2 não existe nesse período; só CHIRPS/estações têm dado observacional ali).
- Nenhum random split.
- Nenhuma expansão artificial de N usando os 24 membros do ensemble como anos independentes — confirmado pela verificação de deduplicação (seção 0).
- Nenhum `forecast_calibrado` por quantile mapping, nenhum RMSE/MAE/skill/IC do Método 3.3 foi calculado.
