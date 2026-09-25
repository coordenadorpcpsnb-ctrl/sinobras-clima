# Fase 2C.2 — estimativa revisada de recursos para a extração histórica completa

## Status desta estimativa

Revisão da estimativa de `docs/nmme-fase2c2-especificacao.md` (Seção
G), incorporando os dados empíricos reais disponíveis até agora.
**Nenhuma nova execução real de rede foi feita nesta tarefa** — a base
empírica continua sendo só a execução aprovada da Fase 2C.1b (run
`36042228571`, 1 origem). O piloto de 16 origens desta tarefa **não foi
executado de verdade** (instrução explícita: "não executar o piloto
real nesta tarefa") — por isso as projeções abaixo permanecem
extrapolações de 1 único ponto de dado real, não uma média de várias
execuções. Isso deve ficar explícito sempre que esta estimativa for
citada.

## Dado empírico-base

| Métrica | Valor | Fonte |
|---|---|---|
| Duração da requisição (1 origem, H1-H6, 24 membros) | **~2,9 s** | Run `36042228571`, step "Rodar POC real": 18:39:57.34Z → 18:40:00.27Z |
| Requisições HTTP por origem | **1** | `requests_previstos: 1` (RANGEEDGES único, S com limites iguais) |
| Tamanho do artifact ZIP (7 arquivos, 1 origem) | 17.612 bytes | Artifact `nmme-catalogo-poc` da mesma run (comprimido, CSV+JSON+MD juntos) |
| Linhas RAW por origem | 144 (24 membros × 6 leads) | Estrutural — `member_axis_size × len(leads)`, confirmado `raw_completo=True` |

**Limite desta base**: um único ponto de dado real não permite estimar
variância (poderia ser mais rápido ou mais lento dependendo do horário,
carga do IRIDL, tamanho específico da resposta RANGEEDGES quando a
janela retorna 2 inicializações como observado). Nenhuma dessas fontes
de variação foi medida.

## Projeção para o piloto de 16 origens (não executado nesta tarefa)

| Métrica | Estimativa linear | Observação |
|---|---|---|
| Tempo de execução | ~47 s (16 × 2,9 s) | Otimista — mesmo processo Python, sem overhead de reinício de workflow por origem (diferente de 16 execuções separadas do workflow do POC) |
| Requisições HTTP | 16 | 1 por origem, nunca em lote |
| Linhas RAW (se 16/16 aprovadas) | 2.304 (16 × 144) | |
| Linhas de auditoria temporal | 96 (16 × 6) | |

## Projeção para a extração histórica completa (240 origens, 1991-2010)

| Métrica | Estimativa linear (240 origens) | Observação |
|---|---|---|
| Tempo de execução | **~11,6 minutos** (240 × 2,9 s) | **Extrapolação ingênua — não considera**: rate limiting do IRIDL (nunca testado com requisições em sequência rápida), variação de latência por período histórico (S mais antigo pode ter comportamento diferente), nem retentativas em caso de falha pontual |
| Requisições HTTP | 240 | 1 por origem |
| Linhas RAW (se 100% aprovadas) | 34.560 (240 × 144) | |
| Linhas de auditoria temporal | 1.440 (240 × 6) | |
| Volume de dados (CSV agregado, estimativa) | **da ordem de poucos MB** (não medido de primeira mão) | O ZIP de 1 origem (17,6 KB, comprimido, 7 arquivos) não permite decompor o tamanho de cada CSV individualmente sem acesso ao artifact descompactado (bloqueado nesta sessão, ver `docs/nmme-cfsv2-fontes-alternativas.md`) — extrapolação linear ingênua daria ~4,2 MB comprimidos para 240 origens, mas a compressão de CSV se beneficia de repetição (cabeçalhos, URLs), então o volume real pode ser proporcionalmente maior ou menor; tratar como estimativa grosseira, não um número de planejamento de armazenamento |

### Por que a extrapolação de tempo é a parte menos confiável

1. **Rate limiting não testado** — 240 requisições em sequência rápida
   contra o mesmo servidor Ingrid nunca foi tentado; o IRIDL pode
   throttling/bloquear temporariamente, o que aumentaria o tempo real
   muito além da extrapolação linear.
2. **Continuidade do serviço** — o IRIDL legado tem desligamento
   esperado até 31/10/2026 (`docs/nmme-cfsv2-fontes-alternativas.md`);
   se a extração completa rodar perto dessa data, o serviço pode ficar
   instável antes do desligamento formal.
3. **Falhas parciais exigem nova lógica de retentativa** — o piloto
   (Seção 2, item 7) só REGISTRA falhas por origem, não tenta de novo
   automaticamente; a extração completa provavelmente vai precisar de
   uma política de retry (quantas vezes, com que intervalo) ainda não
   especificada.
4. **Timeout do job do GitHub Actions** — os workflows atuais
   (`nmme_poc.yml`, `nmme_piloto_historico.yml`) têm `timeout-minutes:
   30`. A projeção de ~12 minutos para 240 origens cabe confortavelmente
   dentro desse limite **se a extrapolação linear se sustentar** — mas
   um fator de lentidão de apenas 3x (rate limiting moderado) já
   estouraria o timeout atual. Recomenda-se rever esse valor antes da
   extração completa, não assumir que 30 minutos é suficiente.

## Critério objetivo para autorizar a extração completa

Reafirmando `docs/nmme-fase2c2-especificacao.md` (Seção G): a extração
completa (240 origens) só deve começar **depois** que o piloto de 16
origens rodar de verdade (não simulado) e:
1. 16/16 origens `APROVADO`.
2. Nenhum `RANGEEDGES_FAIL_*` inesperado (só o padrão já compreendido
   de janela com 2 inicializações vizinhas).
3. Cobertura observacional confirmada ≥ 90% (já verificado
   estruturalmente como 100% possível — `docs/nmme-fase2c2-piloto-
   cobertura-observacional.md` — mas isso descreve a OBSERVAÇÃO, não
   se o CFSv2 vai de fato abrir as 16 origens).
4. **Novo, incorporado nesta revisão**: o tempo real de execução do
   piloto (16 origens) medido, para recalibrar a projeção dos 240 antes
   de comprometer uma janela de workflow — se 16 origens levarem
   muito mais que ~47s, a projeção linear de ~12 minutos para 240 deixa
   de ser confiável e precisa ser refeita com o dado real.

Nenhuma dessas condições foi satisfeita nesta tarefa — a extração de
240 origens permanece não iniciada e não autorizada.
