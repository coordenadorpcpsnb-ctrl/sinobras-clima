# Diagnóstico Integrado da Habilidade Preditiva Regional — Fase 2C.3E

**Papel desta atividade: auditoria científica, consolidação de evidências e diagnóstico de previsibilidade. Nenhum método foi desenvolvido, ajustado, selecionado ou promovido nesta fase.** Todo número reportado abaixo foi lido diretamente dos artefatos já aprovados das Fases 2C.3C/2C.3D (`metricas_2c3c.json`, `metricas_aditiva_2c3d.json`, `metricas_multiplicativa_2c3d.json`, `viabilidade_quantile_mapping.json`, `metricas_mos_linear_2c3d.json`, `auditoria_disponibilidade_mos_2c3d.json`, `gate_calibracao_probabilistica_2c3d.json`, `robustez_h2_spread_2c3d.json`, `metricas_emos_h2_2c3d.json`) pelo script `scripts/cfsv2_diagnostico_previsibilidade_2c3e.py` — nenhuma fórmula paralela foi usada para recalcular nenhuma métrica de skill. A única computação nova desta fase é a interseção de chaves (`init_date`, `lead`) entre os CSVs de previsão por método, necessária só para a auditoria de comparabilidade de amostra (Seção 3).

Protegidos e não alterados: CFSv2 RAW, CHIRPS v3, dashboard, pipeline operacional, `serie_subst.csv`, protocolos e resultados já aprovados dos Métodos 3.1–3.5 (confirmado por teste de regressão, ver Seção 8).

## 1. Resumo executivo

O CFSv2, sem calibração, tem **skill determinístico/probabilístico absoluto negativo e estatisticamente confirmado** em todos os horizontes H1–H6 (RMSESS absoluto IC95% totalmente abaixo de zero; CRPSS idem) — e essa degradação piora com o lead (RMSESS absoluto: -0,225 em H1 até -0,491 em H6; CRPSS: -0,519 em H1 até -0,707 em H6). Essa leitura, porém, é dominada pelo viés sistemático e pelo ciclo sazonal comum entre modelo e observação (correlação absoluta 0,80–0,83), não pela habilidade de capturar a anomalia interanual real.

Quando a referência passa a ser a climatologia **do próprio modelo** (removendo o viés sazonal sistemático), o quadro muda: o RMSESS de anomalia corrigida do RAW é **estatisticamente indeterminado** (IC95% inclui zero) em todos os horizontes — não é "ruim", é "não demonstrado", uma leitura **independente** da primeira e nunca combinada com ela.

Nenhum dos quatro métodos de calibração determinística avaliados (3.1 aditivo, 3.2 multiplicativo, 3.3 gate QM, 3.4 MOS linear) satisfaz seu critério de aprovação pré-registrado em nenhum horizonte. O Método 3.3 nunca chegou a ser testável (hindcast fixo em 20 anos, abaixo da amostra mínima por desenho). O Método 3.5 (calibração probabilística) permanece em estado diagnóstico/experimental: a dispersão do ensemble RAW é mal calibrada em magnitude em todos os horizontes, mas H2 isoladamente mostra um sinal de informatividade caso a caso robusto a exclusões mensais/sazonais — motivando a implementação experimental do EMOS H2, que **não foi aprovada** (o ganho do componente dinâmico de spread tem IC95% incluindo zero, e o EMOS completo não supera a climatologia causal).

**Em suma: nenhum método avaliado até aqui demonstra, com evidência estatística robusta e pré-registrada, uma capacidade preditiva regional operacionalmente defensável acima da climatologia causal.** O achado mais promissor e ainda não encerrado é o sinal de spread informativo em H2, tratado como hipótese para investigação futura, nunca como resultado validado.

## 2. Inventário de métodos (Seção B)

Artefato completo: `data/cfsv2_diagnostico_2c3e/inventario_metodos.json`. Resumo:

| Método | Objetivo | Horizontes | N candidato/elegível | Regra causal | Decisão científica registrada |
|---|---|---|---|---|---|
| RAW CFSv2 (2C.3C) | Precipitação bruta do ensemble (24 membros), referência estrutural | H1–H6 | 240/horizonte (sem filtro de warm-up) | N/A (não é ajustado) | Auditoria estrutural APROVADA |
| 3.1 Aditivo | `raw + bias_aditivo_causal` | H1–H6 | 120/horizonte | `init_treino < init_avaliada` | Critério não satisfeito em nenhum horizonte |
| 3.2 Multiplicativo | `raw × razão_causal` (só meses com denominador seguro) | H1–H6 | 80/horizonte (8 meses elegíveis; jun–set excluídos por desenho) | igual ao 3.1 | Critério não satisfeito em nenhum horizonte; sem diferença distinguível do 3.1 (IC inclui zero) |
| 3.3 Gate QM | Viabilidade de quantile mapping | H1–H6 | N causal máx. = 19 (sempre < 20) | hindcast fixo 1991–2010 | **NÃO TESTÁVEL** (limitação estrutural, não resultado negativo) |
| 3.4 MOS linear | `alpha_lead + beta_lead·anom_raw` (OLS, pooled por lead) | H1–H6 | 108/107/106/105/104/103 (pós-correção causal) | `init_treino < init_avaliada` **e** `target_month_treino < init_avaliada` | Critério não satisfeito em nenhum horizonte, antes e depois da correção; sem diferença distinguível do 3.1 |
| 3.5 Gate probabilístico | Diagnóstico de dispersão do ensemble RAW | H1–H6 | 240/horizonte | N/A (diagnóstico) | Resultado MISTO por horizonte; nunca uma aprovação |
| 3.5 Robustez H2 | Robustez do sinal spread×erro em H2 | H2 | 240 | N/A (diagnóstico) | `sinal_h2_robusto` → prosseguir para protocolo EMOS |
| 3.5 EMOS H2 | Calibração probabilística dinâmica (Normal censurada) | H2 | 95 (pós warm-up) | igual ao 3.4 | Componente dinâmico de spread **NÃO APROVADO** |

## 3. Auditoria de comparabilidade de amostras (Seção C)

Artefato completo: `data/cfsv2_diagnostico_2c3e/comparabilidade_amostras.csv` (21 linhas). Metodologia: interseção das chaves `init_date` entre as linhas com `status == 'ok'` de cada método, por `lead`.

**Comparações diretamente válidas** (já existe uma métrica pareada aprovada calculada sobre a interseção exata):
- Aditivo × Multiplicativo, todos os leads (`skill_multiplicativo_vs_aditivo`) — interseção = 100% do multiplicativo (80/80), porque o multiplicativo é um subconjunto estrito do aditivo.
- Aditivo × MOS linear, todos os leads (`skill_mos_vs_aditivo`) — interseção = 100% do MOS (107/107 em H2, etc.), mesmo padrão de subconjunto.

**Comparações classificadas como NÃO comparáveis diretamente nesta fase** (interseção de amostra existe, mas nenhuma métrica pareada já aprovada cobre o par, e calcular uma nova está fora do escopo de síntese desta fase):
- Multiplicativo × MOS linear, todos os leads — interseção 70–72 casos (87,5–90% do menor conjunto), mas nunca comparados diretamente em nenhum documento aprovado (ambos foram comparados ao aditivo separadamente, nunca um ao outro).
- EMOS H2 × {Aditivo, Multiplicativo, MOS linear} em H2 — interseção de até 100% (95/95 com aditivo e MOS, 63/80 com multiplicativo), mas **famílias de métrica diferentes** (CRPS probabilístico do EMOS vs. RMSE determinístico dos demais) — nunca comparáveis numericamente direto apesar de ambos serem "skill scores", mesmo com sobreposição total de amostra.

Nenhuma comparação de métrica entre RAW (2C.3C) e os métodos calibrados foi recomputada nesta fase: cada método calibrado já contém sua própria comparação interna contra o RAW (`skill_vs_raw`), calculada sobre sua própria amostra elegível — essa é a única via de comparação RAW-vs-calibrado já validada, e é reaproveitada como está (ver Seção 2).

## 4. Diagnóstico de habilidade preditiva H1–H6 (Seção D)

Artefato completo: `data/cfsv2_diagnostico_2c3e/diagnostico_habilidade.json`.

| H | RAW RMSESS absoluto (IC95%) | RAW RMSESS anom. corrigida | RAW CRPSS | Aditivo skill_vs_anom_reconstr. | Multiplic. skill_vs_anom_reconstr. | MOS skill_vs_anom_reconstr. | Gate 3.5 (controlado por mês) |
|---|---|---|---|---|---|---|---|
| H1 | -0,225 [-0,329,-0,143] | 0,045 (IC inclui zero) | -0,519 | **0,040 (IC>0)** | -0,097 | 0,010 | spread pouco informativo |
| H2 | -0,278 [-0,387,-0,194] | -0,044 (IC inclui zero) | -0,490 | 0,036 (IC inclui zero) | 0,021 | -0,002 | **potencialmente calibrável** |
| H3 | -0,316 [-0,479,-0,159] | -0,011 (IC inclui zero) | -0,487 | 0,027 (IC inclui zero) | 0,007 | -0,012 | spread pouco informativo |
| H4 | -0,379 [-0,518,-0,244] | 0,008 (IC inclui zero) | -0,569 | 0,022 (IC inclui zero) | 0,004 | 0,003 | spread pouco informativo |
| H5 | -0,447 [-0,592,-0,307] | -0,020 (IC inclui zero) | -0,656 | 0,030 (IC inclui zero) | 0,015 | -0,006 | spread pouco informativo |
| H6 | -0,491 [-0,626,-0,340] | -0,018 (IC inclui zero) | -0,707 | 0,013 (IC inclui zero) | 0,006 | 0,029 | spread pouco informativo |

**Leituras separadas, nunca combinadas numa única pontuação** (RMSESS e CRPSS são famílias de skill score distintas — determinística vs. probabilística):

1. **Precipitação absoluta vs. anomalia corrigida**: o RMSESS absoluto do RAW piora monotonicamente com o lead (-0,225 → -0,491) e tem IC95% sempre abaixo de zero — mas essa degradação é dominada pelo viés sazonal sistemático (corr. absoluta 0,80–0,83 no 2C.3C, maior parte explicada pelo ciclo sazonal comum). Já o RMSESS de anomalia corrigida (climatologia própria do modelo) é indeterminado (IC inclui zero) em TODOS os horizontes, sem padrão monotônico claro com o lead — sinal de que a "perda de skill com o lead" visível no absoluto é majoritariamente um artefato do viés sazonal, não uma perda demonstrada de informação sobre a anomalia real.
2. **Lead vs. perda de skill**: CRPSS do RAW também piora monotonicamente (-0,519 → -0,707), mas, como a CRPSS absoluta sofre da mesma confusão sazonal que o RMSESS absoluto (nunca testado em anomalia nesta fase, pois o protocolo original do 2C.3C não calculou CRPSS de anomalia), essa tendência não pode ser atribuída com segurança só à perda de informação do modelo com o lead — permanece hipótese, não conclusão.
3. **Calibração determinística**: nenhum dos três métodos (3.1, 3.2, 3.4) atinge IC95% simultaneamente acima de zero nos dois critérios pré-registrados em nenhum horizonte; H1 é o único caso em que ao menos um dos dois componentes do critério do aditivo (skill_vs_anomalia_reconstruida) tem IC95% totalmente acima de zero isoladamente.
4. **Calibração probabilística (dispersão)**: mal calibrada em magnitude (underdispersive, coverage_error sistematicamente negativo) em todos os horizontes; só H2 mostra correlação spread×erro controlada por mês com IC95% acima de zero — achado isolado entre 6 horizontes testados, sem correção formal de multiplicidade, tratado como exploratório (ver Seção 5).
5. **Matrizes mês × lead e grupos sazonais** (já registradas em cada documento de método, não recomputadas aqui): amostra pequena por célula (N≈8-20) em todos os métodos — usadas só como diagnóstico de heterogeneidade nos documentos originais, nunca como critério de aprovação célula a célula; esta fase não computou nenhuma nova análise sazonal (nenhum agrupamento sazonal novo foi definido — reaproveita só os grupos chuvosa/transição/seca já pré-definidos nos protocolos de 2C.3D).

## 5. Fontes de incerteza (Seção E)

**Observações (CHIRPS v3):** a aprovação estrutural da base pareada (2C.3C) cobre alinhamento de datas, unicidade e ausência de valores faltantes — não avalia incerteza espacial de CHIRPS como estimador da chuva nas fazendas (questão fora do escopo computacional desta fase, tratada qualitativamente: CHIRPS é um produto de sensoriamento remoto+estações, com viés conhecido e documentado no `CLAUDE.md` do projeto para a série operacional, mas essa auditoria de viés foi feita para a série Sinobras/operacional, não para a base pareada CFSv2-CHIRPS usada nestas fases — **hipótese não demonstrada aqui**: o mesmo padrão de viés sazonal documentado para a série operacional pode se aplicar à base pareada, mas isso não foi testado nesta fase nem nas anteriores).

**CFSv2 (modelo):** skill determinístico de anomalia corrigida é indeterminado (não demonstrado, não negado) em todos os horizontes — RAW não decompõe bias de localização vs. erro de fase/amplitude nesta fase. Dependência entre membros é alta em precipitação bruta (correlação par-a-par ~0,77–0,85) mas cai substancialmente em anomalia mensal (~0,06–0,29, já documentado no gate 3.5) — ciclo sazonal comum entre membros, não falta de diversidade real. Hindcast fixo em 20 anos (1991–2010) é a limitação estrutural que torna o Método 3.3 não testável e restringe qualquer abordagem baseada em distribuição empírica de quantis.

**Calibração:** o ganho determinístico sobre o RAW (`skill_vs_raw`) é positivo e com IC95% acima de zero nos três métodos de correção de viés (3.1/3.2/3.4) em praticamente todos os horizontes — mas isso reflete principalmente a remoção de viés sistemático, não skill de anomalia genuína (nenhum dos três bate o benchmark de anomalia reconstruída). O ganho incremental de qualquer método sobre a climatologia causal pura não foi demonstrado em nenhum horizonte. A restrição de amostra por warm-up (de 240 candidatos para 80–120 elegíveis, dependendo do método) é uma perda deliberada de poder estatístico em troca de defensabilidade causal — size real de teste reduzido pode explicar parte dos ICs largos observados. O componente dinâmico de spread do EMOS H2 não mostrou ganho comprovado (hipótese explicada em detalhe na Seção 1, não repetida aqui).

**Escala regional:** todos os resultados acima são calculados sobre a geometria única/envelope de fazendas (`data/fazendas.geojson`, ver `CLAUDE.md` Armadilha 8) — nenhum resultado é, nem pode ser interpretado como, skill por fazenda individual; nenhuma avaliação de escala por fazenda foi feita nesta fase ou em qualquer fase anterior (dado que o repositório deliberadamente não permite identificação de fazenda individual).

**Hipótese explicativa vs. causa demonstrada — disciplina aplicada em toda esta seção:** cada afirmação acima foi redigida para distinguir o que foi estatisticamente testado (ex.: RMSESS absoluto degrada com lead, IC confirmado) do que é hipótese plausível mas não testada nesta fase nem nas anteriores (ex.: viés espacial de CHIRPS na base pareada, decomposição bias/fase do CFSv2).

## 6. Disciplina estatística anti-artefato (Seção F)

Nenhum novo critério de aprovação foi introduzido nesta fase. As únicas computações novas (interseções de amostra, Seção 3) usam as mesmas chaves (`init_date`, `lead`) já usadas nos métodos de origem, nunca tratam membros de ensemble como observações independentes, e nunca produzem um novo teste de significância — são contagens determinísticas de conjuntos. Nenhuma matriz mês×lead nova foi calculada nesta fase. O achado de H2 (robustez do spread) já tinha a ressalva de multiplicidade registrada no documento original (`docs/nmme-fase2c3d-robustez-spread-h2.md`, Seção 8) e é citado aqui com a mesma ressalva, não reforçada nem enfraquecida.

## 7. Resposta às 7 perguntas e matriz de evidência (Seção H)

1. **Quais métodos superam a climatologia?** Nenhum dos métodos determinísticos (3.1, 3.2, 3.4) satisfaz seu critério pré-registrado de superar simultaneamente o RAW e o benchmark de anomalia reconstruída em nenhum horizonte. O EMOS H2 supera o RAW (IC95% acima de zero) mas não supera a climatologia probabilística causal (IC95% inclui zero) — logo, **nenhum método supera a climatologia** sob os critérios pré-registrados.
2. **Quais horizontes mostram maior/menor previsibilidade?** Em precipitação absoluta, a habilidade (RMSESS/CRPSS do RAW) degrada monotonicamente de H1 para H6. Em anomalia corrigida — a leitura mais relevante para skill genuíno — nenhum horizonte mostra IC95% deslocado de zero; não há horizonte "melhor" demonstrado estatisticamente, só H2 se destaca isoladamente no diagnóstico de dispersão (Seção 4, item 4).
3. **Quanto do ganho é só remoção de viés?** A maior parte: os três métodos de correção de viés (3.1/3.2/3.4) mostram `skill_vs_raw` positivo e significativo, mas falham no benchmark de anomalia reconstruída (que controla por viés) — o ganho é predominantemente remoção de bias sistemático, não captura de anomalia interanual real.
4. **A dispersão do CFSv2 agregou informação útil?** Parcialmente e só em H2: mal calibrada em magnitude em todos os horizontes; correlação spread×erro controlada por mês com IC95% acima de zero só em H2, robusta a 10-11/12 exclusões mensais — motivou o EMOS H2, que não demonstrou ganho líquido aprovável.
5. **Quais limitações vêm de amostra, observação, escala espacial ou fonte?** Amostra: hindcast fixo de 20 anos inviabiliza QM (3.3) e restringe todos os ICs a 80-120 casos efetivos. Observação: viés espacial de CHIRPS na base pareada não testado nesta fase. Escala: nenhum resultado é válido por fazenda individual (geometria única). Fonte: CFSv2 tem viés sazonal sistemático forte e dependência de membro alta em precipitação bruta.
6. **Quais hipóteses seguem plausíveis mas não comprovadas?** (a) o spread do CFSv2 em H2 carrega informação real de incerteza além do ciclo sazonal; (b) a perda de skill absoluto com o lead é majoritariamente artefato do viés sazonal, não perda real de informação sobre a anomalia; (c) o mesmo padrão de viés sazonal de CHIRPS documentado para a série operacional pode se aplicar à base pareada CFSv2-CHIRPS.
7. **Qual a melhor próxima investigação pelo critério potencial/dado/complexidade?** Aprofundar o sinal de H2 (hipótese "a") é a aposta com menor complexidade incremental (reaproveita infraestrutura causal e de bootstrap já existente) e maior potencial informado por evidência prévia (robustez já demonstrada a exclusões mensais/sazonais) — mas qualquer decisão de implementação fica para revisão externa, não é automática.

### Matriz de evidência (Favorável / Desfavorável / Inconclusivo / Não testável / Não comparável)

| Item avaliado | Classificação |
|---|---|
| RAW CFSv2 — skill absoluto (RMSESS/CRPSS) | **Desfavorável** (IC95% abaixo de zero, todos os horizontes) |
| RAW CFSv2 — skill de anomalia corrigida | **Inconclusivo** (IC95% inclui zero, todos os horizontes) |
| Método 3.1 (aditivo) — critério pré-registrado | **Desfavorável** (não satisfeito em nenhum horizonte) |
| Método 3.2 (multiplicativo) — critério pré-registrado | **Desfavorável** (não satisfeito em nenhum horizonte) |
| Método 3.2 vs. 3.1 (comparação pareada) | **Inconclusivo** (IC95% inclui zero, todos os horizontes) |
| Método 3.3 (gate QM) | **Não testável** (hindcast estruturalmente insuficiente) |
| Método 3.4 (MOS linear) — critério pré-registrado | **Desfavorável** (não satisfeito em nenhum horizonte) |
| Método 3.4 vs. 3.1 (comparação pareada) | **Inconclusivo** (IC95% inclui zero, todos os horizontes) |
| Método 3.2 vs. 3.4 (comparação direta) | **Não comparável** (nenhuma métrica pareada já aprovada entre os dois) |
| Gate 3.5 — dispersão RAW, H1/H3–H6 | **Desfavorável** (mal calibrado e spread pouco informativo) |
| Gate 3.5 — dispersão RAW, H2 | **Favorável condicionado** (spread informativo, robusto, mas só diagnóstico) |
| EMOS H2 — componente dinâmico de spread | **Desfavorável** (IC95% do ganho inclui zero; não supera climatologia) |
| EMOS H2 vs. métodos determinísticos (3.1/3.2/3.4) em H2 | **Não comparável** (famílias de métrica diferentes) |

## 8. Validação e regressão (Seção J)

- Baseline pré-alterações (Seção A): suíte completa executada antes de qualquer artefato desta fase; única falha pré-existente conhecida e já documentada em sessões anteriores (`test_a_dados_reais_primeiro_commit_ja_completo`, artefato de histórico de fork, confirmada idêntica em `main`).
- Testes dedicados novos: `tests/test_cfsv2_diagnostico_previsibilidade_2c3e.py` — 18 testes, todos passando (ver Seção 9 da entrega).
- `python scripts/verificar_dashboard.py`: mesma única falha pré-existente conhecida (`serie_subst.csv` sem o mês corrente 09/2026), confirmada byte-idêntica a `main`.
- Nenhum arquivo em `docs/` (exceto este novo relatório), `data/cfsv2_validacao_2c3c/`, `data/cfsv2_calibracao_2c3d/`, pipeline operacional ou dashboard foi alterado — confirmado por teste dedicado (`ExecucaoCompletaTestCase::test_b_nenhum_arquivo_protegido_e_alterado_por_este_modulo`).

## 9. Restrições respeitadas (Seção I)

Dashboard, pipeline/workflows, CHIRPS/CFSv2 RAW/bases originais, protocolos já aprovados, resultados passados, Métodos 3.1–3.5 (recalibração) — nenhum alterado. Nenhum preditor ENSO/Atlântico foi adicionado. Nenhum método foi promovido à operação.

## 10. Escopo e limitações desta síntese

- Esta é uma atividade de consolidação: nenhuma métrica nova de skill foi calculada além das interseções de amostra (Seção 3).
- A análise de fontes de incerteza (Seção 5) mistura evidência testada e hipótese explicitamente rotulada — nunca apresentada como conclusão demonstrada quando é hipótese.
- A matriz de evidência (Seção 7) reflete só os critérios e resultados já registrados nos documentos de origem; nenhum novo limiar foi escolhido nesta fase.
- Decisão sobre investigar H2 mais a fundo, ou qualquer outra linha, permanece de responsabilidade de revisão externa — este documento não recomenda implementação automática.
