# Plano de reconstrução histórica — CHIRPS v3.0 Final (Fase 2C.3B)

**Plano — nenhuma extração dos 365 meses foi iniciada por este documento nem pelo script que o gera.**

## Período

- Completo: 1981-01 a 2011-05 — 365 meses.
- Climatologia: 1981-01 a 1990-12 — 120 meses. climatologia retrospectiva — período anterior às previsões históricas do CFSv2 (jan/1991 em diante), necessário para uma climatologia de referência que nunca usa os valores do período avaliado (ver docs/nmme-fase2c3a-protocolo-cfsv2.md, Seção 4).
- Verificação: 1991-01 a 2011-05 — 245 meses. período de verificação das previsões históricas do CFSv2 — 240 inicializações jan/1991-dez/2010 (scripts/nmme_extracao_historica.py, já aprovado) + mai/2011 como mês-alvo do último horizonte (H6) da última inicialização (dez/2010).
- Soma dos dois períodos bate com o completo: True.

## Processamento em lotes

- Tamanho do lote: 24 meses.
- Número de lotes: 16.
- Mecanismo: scripts/chirps_v3_reconstrucao_historica.py::executar_lote — reusa scripts/chirps_v3_piloto.py::executar_piloto (mesma lógica testada no piloto de 17 meses), um lote por chamada, nunca o período completo de uma vez.

## Retomada

- meses_pendentes_reconstrucao() reusa scripts/chirps_v3_piloto.py::meses_pendentes — um mês com status em STATUS_RESOLVIDOS nunca é reprocessado pela retomada normal. CORREÇÃO (revisão adicional) — esta descrição era uma lista hardcoded separada que divergiu quando 'nodata_nan' foi reconhecido em scripts/chirps_v3_piloto.py; agora é construída a partir das mesmas constantes que definem STATUS_RESOLVIDOS, para nunca mais divergir. Duas classes distintas, nunca confundidas: (1) valor científico VÁLIDO — ok/zero_real (STATUS_RESOLVIDO_REPROCESSAMENTO); (2) SEM valor válido, mas considerado "resolvido" só para fins de retomada automática (nunca para aprovação científica) — mes_ausente/nodata_nan/nodata_sentinela (STATUS_NODATA_REPROCESSAMENTO) — esses três só podem ser retentados pelo mecanismo controlado scripts/chirps_v3_piloto.py::reprocessar_ausentes_ou_nodata(), respeitando o teto de tentativas, nunca pela retomada normal. Falha real (rede/arquivo/grade/leitura) ou valor inválido/implausível — fora de STATUS_RESOLVIDOS — é retentado na próxima execução normal do mesmo lote.

## Validação individual por mês

- Cada mês passa pelas mesmas verificações do piloto (scripts/_chirps_v3.py::verificar_grade + classificar_valor) — nenhum mês é aceito sem validação própria, nenhuma extrapolação de "um mês passou, os vizinhos devem estar OK também".

## Armazenamento

- Diretório: `data/chirps_v3_historico`.
- Nunca reutiliza: `data/chirps_v3_piloto.csv`, `data/chirps_1981_2025.csv`, `data/serie_subst.csv`.
- Os 17 registros originais do piloto (data/chirps_v3_piloto.csv) preservados: True.

## Status desta tarefa

- Extração dos 365 meses iniciada nesta tarefa: False.

## Próximos passos (após aprovação explícita, fora desta tarefa)

1. Rodar executar_lote() lote a lote (LOTES_HISTORICOS), verificando avaliar_qualidade_reconstrucao() após cada lote antes de prosseguir para o próximo — nunca encadear todos os lotes sem checar o anterior.
2. Ao final dos 365 meses, rodar avaliar_qualidade_reconstrucao() sobre o conjunto completo — só prosseguir para a Fase 2C.3C se cobertura_temporal_completa=True.
3. Gerar relatório final da reconstrução (mesmo padrão do relatório do piloto, docs/nmme-fase2c3a-piloto-chirps-v3.md) antes de qualquer uso na Fase 2C.3C.

