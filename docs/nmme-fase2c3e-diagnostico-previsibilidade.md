# Diagnóstico Integrado da Habilidade Preditiva Regional — Fase 2C.3E

**Papel desta atividade: auditoria científica, consolidação de evidências e diagnóstico de previsibilidade. Nenhum método foi desenvolvido, ajustado, selecionado ou promovido nesta fase.** Todo número reportado abaixo foi lido diretamente dos artefatos já aprovados das Fases 2C.3C/2C.3D (`metricas_2c3c.json`, `metricas_aditiva_2c3d.json`, `metricas_multiplicativa_2c3d.json`, `viabilidade_quantile_mapping.json`, `metricas_mos_linear_2c3d.json`, `auditoria_disponibilidade_mos_2c3d.json`, `gate_calibracao_probabilistica_2c3d.json`, `robustez_h2_spread_2c3d.json`, `metricas_emos_h2_2c3d.json`) pelo script `scripts/cfsv2_diagnostico_previsibilidade_2c3e.py` — nenhuma fórmula paralela foi usada para recalcular nenhuma métrica de skill. A única computação nova desta fase é a interseção de chaves (`init_date`, `lead`) entre os CSVs de previsão por método, necessária só para a auditoria de comparabilidade de amostra (Seção 3).

Protegidos e não alterados: CFSv2 RAW, CHIRPS v3, dashboard, pipeline operacional, `serie_subst.csv`, protocolos e resultados já aprovados dos Métodos 3.1–3.5 (confirmado por teste de regressão, ver Seção 8).

## 1. Resumo executivo

O CFSv2, sem calibração, tem **skill determinístico/probabilístico absoluto negativo e estatisticamente confirmado** em todos os horizontes H1–H6 (RMSESS absoluto IC95% totalmente abaixo de zero; CRPSS idem) — e essa degradação piora com o lead (RMSESS absoluto: -0,225 em H1 até -0,491 em H6; CRPSS: -0,519 em H1 até -0,707 em H6). **Essa leitura é consistente com a hipótese de que o viés sistemático e o ciclo sazonal comum entre modelo e observação (correlação absoluta 0,80–0,83) expliquem boa parte do padrão observado — mas o contraste com o RMSESS de anomalia corrigida (abaixo) demonstra que a definição da previsão e sua correção climatológica alteram substancialmente a avaliação, sem quantificar a parcela do erro causada pelo viés.** Trata-se de hipótese compatível com a evidência, não de uma decomposição causal demonstrada.

Quando a referência passa a ser a climatologia **do próprio modelo** (removendo o viés sazonal sistemático), o quadro muda: o RMSESS de anomalia corrigida do RAW é **estatisticamente indeterminado** (IC95% inclui zero) em todos os horizontes — não é "ruim", é "não demonstrado", uma leitura **independente** da primeira e nunca combinada com ela.

**Nenhum dos métodos de calibração avaliados satisfez integralmente os respectivos critérios pré-registrados de aprovação operacional.** Essa formulação não equivale a uma afirmação de ausência absoluta de informação preditiva — ver a ressalva de H1/aditivo abaixo e a matriz de evidência completa na Seção 7. O Método 3.3 nunca chegou a ser testável (hindcast fixo em 20 anos, abaixo da amostra mínima por desenho) — classificação distinta de "reprovado". O Método 3.5 (calibração probabilística) permanece em estado diagnóstico/experimental: a dispersão do ensemble RAW é mal calibrada em magnitude em todos os horizontes, mas H2 isoladamente mostra um sinal de informatividade caso a caso robusto a exclusões mensais/sazonais — motivando a implementação experimental do EMOS H2, que **não foi aprovada** (o ganho do componente dinâmico de spread tem IC95% incluindo zero, e o EMOS completo não supera a climatologia causal).

**Ressalva importante, preservada explicitamente:** o Método 3.1 (aditivo) em H1 tem `skill_vs_anomalia_reconstruida` com IC95% totalmente acima de zero (0,040 [0,002, 0,088]) — um resultado **parcialmente favorável isolado**, mesmo que o critério conjunto de aprovação (que exige esse E o RMSESS_climatologia simultaneamente acima de zero) não tenha sido satisfeito em H1. Esse resultado nunca deve ser lido como "H1/aditivo reprovado" sem essa qualificação.

**Em suma:** os resultados se dividem entre desfavoráveis (RAW absoluto, Métodos 3.1/3.2/3.4 no critério conjunto, EMOS H2 no componente dinâmico), indeterminados (RAW em anomalia corrigida, a maioria dos componentes isolados dos métodos 3.1/3.2/3.4), parcialmente favoráveis (Método 3.1 em H1, isoladamente) e não testáveis (Método 3.3). Nenhum método demonstra, com evidência pré-registrada, uma capacidade preditiva regional operacionalmente defensável e integral acima da climatologia causal — o que é diferente de dizer que não existe informação preditiva alguma. O achado mais promissor e ainda não encerrado é o sinal de spread informativo em H2, tratado como uma entre várias hipóteses para investigação futura (ver Seção 11), nunca como resultado validado nem como escolha definitivamente superior.

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

Artefato completo: `data/cfsv2_diagnostico_2c3e/comparabilidade_amostras.csv` (21 linhas). Metodologia: interseção das chaves `init_date` entre as linhas com `status == 'ok'` de cada método, por `lead` — contagens preservadas sem transformação em relação à versão anterior deste artefato; nenhum teste comparativo novo foi executado nesta rodada, só a reclassificação da categoria de comparabilidade. **Revisão desta rodada:** a classificação binária anterior ("comparável diretamente" / "não comparável") foi substituída por 4 categorias, porque "sem comparação pareada já calculada" e "sem comparação pareada possível" são afirmações distintas — a primeira é uma lacuna de trabalho, a segunda é um limite estrutural de métrica.

**`comparavel_e_ja_avaliado`** (já existe uma métrica pareada aprovada calculada sobre a interseção exata):
- Aditivo × Multiplicativo, todos os leads (`skill_multiplicativo_vs_aditivo`) — interseção = 100% do multiplicativo (80/80), porque o multiplicativo é um subconjunto estrito do aditivo.
- Aditivo × MOS linear, todos os leads (`skill_mos_vs_aditivo`) — interseção = 100% do MOS (107/107 em H2, etc.), mesmo padrão de subconjunto.

**`comparavel_em_principio_mas_nao_avaliado`** (observações comuns, previsões determinísticas, mesma família de métrica — mas a comparação pareada em si ainda não foi calculada em nenhum documento aprovado; calcular uma nova está fora do escopo desta fase, não por impossibilidade):
- Multiplicativo × MOS linear, todos os leads — interseção 70–72 casos (87,5–90% do menor conjunto). Ambos foram comparados ao aditivo separadamente (seções 2/anteriores), nunca um ao outro — essa comparação específica é uma lacuna de trabalho, não um limite de métrica ou de dados.

**`nao_comparavel_diretamente_por_metrica_ou_variavel`** (famílias de métrica diferentes sobre a mesma variável, nos dados hoje calculados):
- EMOS H2 × {Aditivo, Multiplicativo, MOS linear} em H2 — interseção de até 100% (95/95 com aditivo e MOS, 63/80 com multiplicativo). EMOS H2 reporta CRPS (probabilístico) e os demais reportam RMSE (determinístico) — não diretamente intercambiáveis nos dados hoje calculados. **Isso NÃO afirma que os dois sistemas preditivos sejam incomparáveis em princípio**: uma métrica comum adequadamente definida (ex.: CRPS determinístico equivalente, ou pinball loss comum a ambos) poderia viabilizar a comparação — essa métrica comum simplesmente não foi calculada em nenhuma fase até aqui, e calculá-la está fora do escopo desta rodada.

**`nao_comparavel_por_dados_ou_amostra`** (categoria da taxonomia reservada para pares bloqueados por limitação de dados/amostra, ex.: interseção insuficiente ou definições de horizonte/observação incompatíveis): nenhum dos 21 pares avaliados nesta fase se qualifica nesta categoria — todas as interseções observadas são substanciais (78,75% a 100% do menor conjunto); mantida na taxonomia para uso em fases futuras com outros pares.

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

1. **Precipitação absoluta vs. anomalia corrigida**: o RMSESS absoluto do RAW piora monotonicamente com o lead (-0,225 → -0,491) e tem IC95% sempre abaixo de zero. A amostra tem correlação absoluta alta (0,80–0,83 no 2C.3C), compatível com forte influência do ciclo sazonal comum entre modelo e observação sobre essa leitura — mas isso é uma hipótese plausível, não uma decomposição quantitativa do erro. Já o RMSESS de anomalia corrigida (climatologia própria do modelo) é indeterminado (IC inclui zero) em TODOS os horizontes, sem padrão monotônico claro com o lead. O contraste entre as duas métricas demonstra que a definição da previsão e sua correção climatológica alteram substancialmente a avaliação de skill — mas não quantifica automaticamente qual parcela da "perda de skill com o lead" visível no absoluto é causada pelo viés sazonal versus por perda real de informação sobre a anomalia; ambas seguem como hipóteses compatíveis com a evidência, não causas demonstradas.
2. **Lead vs. perda de skill**: CRPSS do RAW também piora monotonicamente (-0,519 → -0,707), mas, como a CRPSS absoluta sofre da mesma confusão sazonal que o RMSESS absoluto (nunca testado em anomalia nesta fase, pois o protocolo original do 2C.3C não calculou CRPSS de anomalia), essa tendência não pode ser atribuída com segurança só à perda de informação do modelo com o lead — permanece hipótese, não conclusão.
3. **Calibração determinística**: nenhum dos três métodos (3.1, 3.2, 3.4) atinge IC95% simultaneamente acima de zero nos dois critérios pré-registrados em nenhum horizonte; H1 é o único caso em que ao menos um dos dois componentes do critério do aditivo (skill_vs_anomalia_reconstruida) tem IC95% totalmente acima de zero isoladamente.
4. **Calibração probabilística (dispersão)**: mal calibrada em magnitude (underdispersive, coverage_error sistematicamente negativo) em todos os horizontes; só H2 mostra correlação spread×erro controlada por mês com IC95% acima de zero — achado isolado entre 6 horizontes testados, sem correção formal de multiplicidade, tratado como exploratório (ver Seção 5).
5. **Matrizes mês × lead e grupos sazonais** (já registradas em cada documento de método, não recomputadas aqui): amostra pequena por célula (N≈8-20) em todos os métodos — usadas só como diagnóstico de heterogeneidade nos documentos originais, nunca como critério de aprovação célula a célula; esta fase não computou nenhuma nova análise sazonal (nenhum agrupamento sazonal novo foi definido — reaproveita só os grupos chuvosa/transição/seca já pré-definidos nos protocolos de 2C.3D).

## 5. Fontes de incerteza (Seção E)

**Observações (CHIRPS v3):** a aprovação estrutural da base pareada (2C.3C) cobre alinhamento de datas, unicidade e ausência de valores faltantes — não avalia incerteza espacial de CHIRPS como estimador da chuva nas fazendas (questão fora do escopo computacional desta fase, tratada qualitativamente: CHIRPS é um produto de sensoriamento remoto+estações, com viés conhecido e documentado no `CLAUDE.md` do projeto para a série operacional, mas essa auditoria de viés foi feita para a série Sinobras/operacional, não para a base pareada CFSv2-CHIRPS usada nestas fases — **hipótese não demonstrada aqui**: o mesmo padrão de viés sazonal documentado para a série operacional pode se aplicar à base pareada, mas isso não foi testado nesta fase nem nas anteriores).

**CFSv2 (modelo):** skill determinístico de anomalia corrigida é indeterminado (não demonstrado, não negado) em todos os horizontes — RAW não decompõe bias de localização vs. erro de fase/amplitude nesta fase. Dependência entre membros é alta em precipitação bruta (correlação par-a-par ~0,77–0,85) mas cai substancialmente em anomalia mensal (~0,06–0,29, já documentado no gate 3.5) — ciclo sazonal comum entre membros, não falta de diversidade real. Hindcast fixo em 20 anos (1991–2010) é a limitação estrutural que torna o Método 3.3 não testável e restringe qualquer abordagem baseada em distribuição empírica de quantis.

**Calibração:** o ganho determinístico sobre o RAW (`skill_vs_raw`) é positivo e com IC95% acima de zero nos três métodos de correção de viés (3.1/3.2/3.4) em praticamente todos os horizontes, enquanto nenhum dos três bate o benchmark de anomalia reconstruída em nenhum horizonte com os dois componentes do critério simultaneamente acima de zero. Esse contraste é **compatível com a hipótese** de que o ganho sobre o RAW reflita majoritariamente remoção de viés sistemático em vez de skill de anomalia genuína — mas nenhuma decomposição quantitativa (que fração do ganho vem de bias vs. de variância/fase) foi calculada nesta fase nem nas anteriores, então essa atribuição não é demonstrada, só plausível. O ganho incremental de qualquer método sobre a climatologia causal pura não foi demonstrado em nenhum horizonte. A restrição de amostra por warm-up (de 240 candidatos para 80–120 elegíveis, dependendo do método) é uma perda deliberada de poder estatístico em troca de defensabilidade causal — size real de teste reduzido pode explicar parte dos ICs largos observados. O componente dinâmico de spread do EMOS H2 não mostrou ganho comprovado (hipótese explicada em detalhe na Seção 1, não repetida aqui).

**Escala regional:** todos os resultados acima são calculados sobre a geometria única/envelope de fazendas (`data/fazendas.geojson`, ver `CLAUDE.md` Armadilha 8) — nenhum resultado é, nem pode ser interpretado como, skill por fazenda individual; nenhuma avaliação de escala por fazenda foi feita nesta fase ou em qualquer fase anterior (dado que o repositório deliberadamente não permite identificação de fazenda individual).

**Hipótese explicativa vs. causa demonstrada — disciplina aplicada em toda esta seção:** cada afirmação acima foi redigida para distinguir o que foi estatisticamente testado (ex.: RMSESS absoluto degrada com lead, IC confirmado) do que é hipótese plausível mas não testada nesta fase nem nas anteriores (ex.: viés espacial de CHIRPS na base pareada, decomposição bias/fase do CFSv2).

## 6. Disciplina estatística anti-artefato (Seção F)

Nenhum novo critério de aprovação foi introduzido nesta fase. As únicas computações novas (interseções de amostra, Seção 3) usam as mesmas chaves (`init_date`, `lead`) já usadas nos métodos de origem, nunca tratam membros de ensemble como observações independentes, e nunca produzem um novo teste de significância — são contagens determinísticas de conjuntos. Nenhuma matriz mês×lead nova foi calculada nesta fase. O achado de H2 (robustez do spread) já tinha a ressalva de multiplicidade registrada no documento original (`docs/nmme-fase2c3d-robustez-spread-h2.md`, Seção 8) e é citado aqui com a mesma ressalva, não reforçada nem enfraquecida.

## 7. Resposta às 7 perguntas e matriz de evidência (Seção H)

1. **Quais métodos superam a climatologia?** Nenhum dos métodos de calibração avaliados satisfez integralmente os respectivos critérios pré-registrados de aprovação operacional — nem os três determinísticos (3.1, 3.2, 3.4), nem o componente dinâmico de spread do EMOS H2 (que supera o RAW com IC95% acima de zero, mas não supera a climatologia probabilística causal, IC95% inclui zero). Ressalva: o Método 3.1 em H1 satisfaz isoladamente o componente `skill_vs_anomalia_reconstruida` do seu critério (IC95% acima de zero) — um resultado parcialmente favorável, não uma aprovação integral.
2. **Quais horizontes mostram maior/menor previsibilidade?** Em precipitação absoluta, a habilidade (RMSESS/CRPSS do RAW) degrada monotonicamente de H1 para H6. Em anomalia corrigida — a leitura mais relevante para skill genuíno — nenhum horizonte mostra IC95% deslocado de zero; não há horizonte "melhor" demonstrado estatisticamente, só H2 se destaca isoladamente no diagnóstico de dispersão (Seção 4, item 4).
3. **Quanto do ganho é só remoção de viés?** Não quantificado por nenhuma decomposição formal nesta fase ou nas anteriores — não há percentual de contribuição demonstrável com os dados disponíveis. O que a evidência mostra: os três métodos de correção de viés (3.1/3.2/3.4) têm `skill_vs_raw` positivo e significativo, mas nenhum bate o benchmark de anomalia reconstruída (que controla por viés) com os dois componentes do critério simultaneamente acima de zero. Esse padrão é **compatível com a hipótese** de que o ganho seja majoritariamente remoção de bias sistemático em vez de captura de anomalia interanual real, mas isso é uma leitura qualitativa do contraste entre dois benchmarks, não uma decomposição quantitativa do erro.
4. **A dispersão do CFSv2 agregou informação útil?** Parcialmente e só em H2: mal calibrada em magnitude em todos os horizontes; correlação spread×erro controlada por mês com IC95% acima de zero só em H2, robusta a 10-11/12 exclusões mensais — motivou o EMOS H2, que não demonstrou ganho líquido aprovável.
5. **Quais limitações vêm de amostra, observação, escala espacial ou fonte?** Amostra: hindcast fixo de 20 anos inviabiliza QM (3.3) e restringe todos os ICs a 80-120 casos efetivos. Observação: viés espacial de CHIRPS na base pareada não testado nesta fase. Escala: nenhum resultado é válido por fazenda individual (geometria única). Fonte: CFSv2 tem viés sazonal sistemático forte e dependência de membro alta em precipitação bruta.
6. **Quais hipóteses seguem plausíveis mas não comprovadas?** (a) o spread do CFSv2 em H2 carrega informação real de incerteza além do ciclo sazonal — robustez exploratória já demonstrada a exclusões mensais/sazonais, mas sem ganho incremental comprovado quando implementado (EMOS H2) e sem descartar a possibilidade de que não exista skill preditivo utilizável nesse sinal; (b) a perda de skill absoluto com o lead pode estar associada, ao menos em parte, ao viés sazonal em vez de refletir só perda real de informação sobre a anomalia — hipótese compatível com o contraste RMSESS absoluto vs. anomalia corrigida, não uma decomposição demonstrada; (c) o mesmo padrão de viés sazonal de CHIRPS documentado para a série operacional pode se aplicar à base pareada CFSv2-CHIRPS — não testado em nenhuma fase. Nenhuma destas é tratada como mais provável ou prioritária que as demais só por estar listada primeiro (ver Seção 11 para as candidatas de investigação, apresentadas sem ranking definitivo).
7. **Qual a melhor próxima investigação pelo critério potencial/dado/complexidade?** Três candidatas plausíveis, apresentadas **sem ranking definitivo** na Seção 11 — a escolha depende de prioridade científica e de recursos, uma decisão de revisão externa, não automática desta síntese.

### Matriz de evidência (Desfavorável / Indeterminado / Parcialmente favorável / Não testável / comparabilidade entre métodos — ver categorias ao final da tabela)

| Item avaliado | Classificação |
|---|---|
| RAW CFSv2 — skill absoluto (RMSESS/CRPSS) | **Desfavorável** (IC95% abaixo de zero, todos os horizontes) |
| RAW CFSv2 — skill de anomalia corrigida | **Indeterminado** (IC95% inclui zero, todos os horizontes — não é "ruim", é "não demonstrado") |
| Método 3.1 (aditivo) — critério conjunto pré-registrado | **Desfavorável** (não satisfeito em nenhum horizonte) |
| Método 3.1 (aditivo) — H1, `skill_vs_anomalia_reconstruida` isolado | **Parcialmente favorável** (IC95% [0,002, 0,088], totalmente acima de zero — não satisfaz o critério conjunto, mas é um resultado isolado real, preservado explicitamente) |
| Método 3.2 (multiplicativo) — critério pré-registrado | **Desfavorável** (não satisfeito em nenhum horizonte) |
| Método 3.2 vs. 3.1 (comparação pareada já avaliada) | **Indeterminado** (IC95% inclui zero, todos os horizontes) |
| Método 3.3 (gate QM) | **Não testável** (hindcast estruturalmente insuficiente — classificação distinta de desfavorável) |
| Método 3.4 (MOS linear) — critério pré-registrado | **Desfavorável** (não satisfeito em nenhum horizonte) |
| Método 3.4 vs. 3.1 (comparação pareada já avaliada) | **Indeterminado** (IC95% inclui zero, todos os horizontes) |
| Método 3.2 vs. 3.4 (comparação direta) | **Comparável em princípio, mas não avaliada** (`comparavel_em_principio_mas_nao_avaliado` — observações comuns e mesma família de métrica; a comparação pareada em si está fora do escopo desta fase, não é um limite estrutural) |
| Gate 3.5 — dispersão RAW, H1/H3–H6 | **Desfavorável** (mal calibrado e spread pouco informativo) |
| Gate 3.5 — dispersão RAW, H2 | **Parcialmente favorável** (spread informativo, robusto a exclusões, mas só diagnóstico — nunca "validado") |
| EMOS H2 — componente dinâmico de spread | **Desfavorável** (IC95% do ganho inclui zero; não supera climatologia) |
| EMOS H2 vs. métodos determinísticos (3.1/3.2/3.4) em H2 | **Não comparável diretamente por métrica/variável** (`nao_comparavel_diretamente_por_metrica_ou_variavel` — CRPS vs. RMSE nos dados hoje calculados; não é uma afirmação de incomparabilidade em princípio, ver Seção 3) |

Categorias usadas: **Desfavorável** (critério/IC não satisfeito), **Indeterminado** (IC95% inclui zero — ausência de evidência, não evidência de ausência), **Parcialmente favorável** (um componente isolado do critério satisfeito, ou achado exploratório robusto mas não validado), **Não testável** (limitação estrutural do hindcast/amostra), e as duas categorias de comparabilidade da Seção 3 (**comparável em princípio mas não avaliado**, **não comparável diretamente por métrica/variável**) para os pares de métodos entre si.

## 8. Validação e regressão (Seção J)

- Baseline pré-alterações (1ª rodada): suíte completa executada antes de qualquer artefato desta fase; única falha pré-existente conhecida e já documentada em sessões anteriores (`test_a_dados_reais_primeiro_commit_ja_completo`, artefato de histórico de fork, confirmada idêntica em `main`).
- Testes dedicados (2ª rodada, após as correções de interpretação/comparabilidade desta auditoria): `tests/test_cfsv2_diagnostico_previsibilidade_2c3e.py` — 30 testes (18 da 1ª rodada + 12 novos para as 4 classes de comparabilidade e a consistência relatório↔JSON), todos passando.
- `python scripts/verificar_dashboard.py`: mesma única falha pré-existente conhecida (`serie_subst.csv` sem o mês corrente 09/2026), confirmada byte-idêntica a `main`.
- Nenhum arquivo em `docs/` (exceto este relatório), `data/cfsv2_validacao_2c3c/`, `data/cfsv2_calibracao_2c3d/`, pipeline operacional ou dashboard foi alterado — confirmado por teste dedicado (`ExecucaoCompletaTestCase::test_b_nenhum_arquivo_protegido_e_alterado_por_este_modulo`).
- Todos os valores numéricos históricos de skill/CRPS/RMSESS/ICs confirmados byte-idênticos à versão anterior deste artefato (comparação direta contra o commit `b6968e2`, ver entrega desta rodada) — só a interpretação em prosa e a classificação de comparabilidade foram revisadas.

## 9. Restrições respeitadas (Seção I)

Dashboard, pipeline/workflows, CHIRPS/CFSv2 RAW/bases originais, protocolos já aprovados, resultados passados, Métodos 3.1–3.5 (recalibração) — nenhum alterado. Nenhum preditor ENSO/Atlântico foi adicionado. Nenhum método foi promovido à operação.

## 10. Escopo e limitações desta síntese

- Esta é uma atividade de consolidação: nenhuma métrica nova de skill foi calculada além das interseções de amostra (Seção 3).
- A análise de fontes de incerteza (Seção 5) mistura evidência testada e hipótese explicitamente rotulada — nunca apresentada como conclusão demonstrada quando é hipótese.
- A matriz de evidência (Seção 7) reflete só os critérios e resultados já registrados nos documentos de origem; nenhum novo limiar foi escolhido nesta fase.
- Decisão sobre investigar H2 mais a fundo, ou qualquer outra linha, permanece de responsabilidade de revisão externa — este documento não recomenda implementação automática.

## 11. Hipóteses candidatas para a próxima fase (sem ranking definitivo)

**Revisão desta rodada (item 4):** a versão anterior deste relatório apresentava o aprofundamento do sinal de H2 como a aposta de "menor complexidade e maior potencial" — uma priorização implícita não solicitada e não justificada por um critério explícito. Esta seção substitui essa priorização por três candidatas lado a lado, cada uma com pergunta científica, dados necessários, limitação principal e o resultado que justificaria avançar — a escolha entre elas é uma decisão de revisão externa.

Antes das três candidatas, cinco distinções que **não devem ser colapsadas numa só conclusão** sobre H2 especificamente:
1. **Robustez exploratória da associação spread×erro em H2** — demonstrada (IC95% acima de zero na maioria das 12 exclusões mensais e em 2 das 3 exclusões sazonais, `docs/nmme-fase2c3d-robustez-spread-h2.md`).
2. **Ausência de ganho incremental comprovado quando implementado (EMOS H2)** — também demonstrada (IC95% de `CRPSS_spread_dinamico` inclui zero; EMOS não supera a climatologia causal).
3. **Possível ausência de habilidade preditiva utilizável nesse sinal** — não descartada pelos itens 1–2: um sinal pode ser estatisticamente robusto num diagnóstico retrospectivo e ainda não se traduzir em ganho probabilístico utilizável quando implementado, como o item 2 mostrou neste caso específico.
4. **Limitações da amostra histórica** — N=95 pós warm-up, 9 anos-alvo distintos no bootstrap; ICs largos são esperados com essa amostra, independentemente do sinal subjacente.
5. **Necessidade de avaliar hipóteses alternativas antes de priorizar qualquer uma** — os itens 1–4 descrevem só H2; as candidatas B e C abaixo não dependem do sinal de H2 ser real ou não.

### Candidata A — Decomposição do erro absoluto e da anomalia do CFSv2

- **Pergunta científica:** que fração da degradação de RMSESS/CRPSS absoluto com o lead é atribuível a viés de localização (média) versus erro de variância/fase, e o quanto disso é especificamente ciclo sazonal comum versus outra fonte?
- **Dados necessários:** a base pareada já existente (`base_pareada_cfsv2_chirps_v3.csv`) é suficiente como ponto de partida; exige desenho de uma decomposição formal (ex.: decomposição de RMSE em bias²+variância, ou MSE skill score decomposto) ainda não implementada em nenhuma fase.
- **Limitação principal:** qualquer decomposição nova é, por definição, desenvolvimento de método de análise (não de calibração) — precisa de desenho e pré-registro de critério antes de ver o resultado, para não repetir o padrão já corrigido nesta auditoria (afirmar causalidade sem decomposição).
- **Resultado que justificaria avançar:** se a decomposição mostrar que a maior parte da degradação com o lead é mesmo viés sazonal (não erro de fase/variância crescente), isso tornaria a hipótese (b) da Seção 7 uma conclusão demonstrada, não apenas compatível — com valor direto para interpretar os métodos 3.1–3.4.

### Candidata B — Qualidade/representatividade das observações CHIRPS na escala regional

- **Pergunta científica:** o padrão de viés sazonal de CHIRPS já documentado para a série operacional Sinobras (`CLAUDE.md`, Armadilha 7) se replica na base pareada CFSv2-CHIRPS usada nestas fases? Caso sim, em que medida isso contamina as métricas de skill já calculadas?
- **Dados necessários:** comparação direta entre a série CHIRPS da base pareada e a série de estações Sinobras (ambas já existem no repositório) — nenhum dado novo precisa ser baixado.
- **Limitação principal:** a base pareada usa CHIRPS como referência "verdade"; se CHIRPS tiver o mesmo viés sazonal já documentado para a série operacional, isso não invalida as métricas de skill (que comparam modelo-vs-CHIRPS), mas pode significar que o viés "do CFSv2" medido nas fases 2C.3C/2C.3D é, em parte, viés compartilhado entre CFSv2 e CHIRPS no mesmo sentido (ambos subestimando/sobrestimando os mesmos meses) — questão de atribuição, não de magnitude.
- **Resultado que justificaria avançar:** evidência de que o padrão sazonal de CHIRPS (out-nov-dez superestimado, conforme já quantificado para a série operacional) está presente também na base pareada seria motivo para revisar a magnitude (não a direção) das métricas de skill desses meses nos Métodos 3.1–3.4 — sem reclassificar decisões já aprovadas.

### Candidata C — Diagnóstico adicional da informatividade de H2, limitado ao que ainda não foi testado

- **Pergunta científica:** o sinal de spread×erro de H2 é específico desse horizonte (lead=2) ou aparece, com magnitude menor, em alguma subdivisão de H1/H3 ainda não testada (ex.: só meses de transição, já que H2 "potencialmente calibrável" e H1/H3 "pouco informativo" diferem por só 1 mês de lead)? E o sinal se mantém com uma definição alternativa de erro (ex.: erro absoluto vs. erro quadrático, já parcialmente feito, mas não cruzado com todas as exclusões da robustez)?
- **Dados necessários:** mesma base do gate probabilístico (`gate_calibracao_probabilistica_2c3d.json`) e da robustez H2 (`robustez_h2_spread_2c3d.json`) — nenhum dado novo.
- **Limitação principal:** é diagnóstico adicional sobre um achado já exploratório entre 6 horizontes testados (sem correção de multiplicidade) — qualquer novo teste aumenta ainda mais o número de comparações informais feitas sobre o mesmo sinal, exigindo disciplina redobrada contra múltiplos testes (Seção 6).
- **Resultado que justificaria avançar:** se o sinal aparecer de forma consistente numa subdivisão não testada de H1/H3 com a mesma robustez já vista em H2, isso fortaleceria a hipótese de que o sinal é sobre o REGIME (ex.: estação) e não sobre o HORIZONTE lead=2 especificamente — mudando a prioridade de qualquer calibração probabilística futura de "H2" para "o regime identificado".

Nenhuma das três candidatas é apresentada como superior às demais; a ordem de listagem não implica prioridade.
