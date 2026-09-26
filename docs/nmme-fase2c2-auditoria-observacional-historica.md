# Auditoria da referência observacional — extração histórica CFSv2 (fazendas)

**Relatório técnico — não calcula skill, não declara aptidão científica final, só reúne evidência e decisões pendentes.**

## Evidência de partida

- Extração histórica consolidada e aprovada: run 36238169299 — 240/240 origens, 34560 registros RAW.

## 1. Cobertura da série observacional

- Período exigido (1ª inicialização a H6 da última): 1991-01 → 2011-05 (245 meses).
- Meses ausentes no calendário: 0 (nenhum).
- Meses duplicados: 0 (nenhum).
- **Cobertura de calendário completa: True**

## 2. MERRA-2 vs. Estação Sinobras (combinações origem×lead)

- `Estação Sinobras (leitura direta de campo, README.md: baseline 1996-presente)`: 1095 combinações
- `MERRA-2 (reanálise NASA, README.md: baseline 1981-1995)`: 345 combinações

## 3. Documentação efetivamente disponível

- README.md linha 18/104: "Série histórica (MERRA-2 1981-1995 + Sinobras 1996-hoje)" — uma única linha, sem coordenadas, sem procedimento de agregação, sem menção a lacunas conhecidas, sem indicação de incerteza/qualidade por período.

### Identidade MERRA-2 vs. master_monthly.csv (achado numérico)

- Meses comparados (ano<=1995): 180, diferença absoluta máxima: 0.0033 mm — **idêntico: True**.
- Meses comparados (ano>=1996): 360, diferença absoluta média: 37.15 mm, máxima: 252.24 mm — **diverge: True**.
- O trecho 'MERRA-2' (ano<=1995) de serie_subst.csv é numericamente idêntico a prec_reg=média(Araguaína, Colinas do Tocantins, Tocantinópolis) de master_monthly.csv. Nenhum script deste repositório documenta a origem, as coordenadas, o procedimento de agregação ou a data de criação dessas 3 colunas — o arquivo já as continha por completo no commit que o introduziu. O rótulo 'MERRA-2' do README não pôde ser confirmado como reanálise de grade única no centroide das fazendas; é, na prática, uma média de 3 sedes municipais cuja identidade como MERRA-2 (em vez de, por exemplo, estações de superfície das 3 cidades) não é verificável a partir do repositório.

### Método de agregação das leituras de campo Sinobras (achado por leitura de código)

- Arquivo: `scripts/update_dashboard.py`
- Padrão verificado: `df_new.groupby(['ano','mes'])['prec_mm'].mean()` — encontrado: True
- Confirmado: a incorporação de SINOBRAS_new.csv usa df_new.groupby(['ano','mes'])['prec_mm'].mean() — média aritmética simples sobre QUANTAS estações/fazendas estiverem presentes naquele envio, sem exigência de número mínimo (1 fazenda reportando produz o mesmo tipo de valor que 34 reportando) e sem reter a leitura por estação individual — só a média sobrevive em serie_subst.csv (coluna 'prec'), a granularidade por fazenda é descartada.

### Coordenadas dos 3 municípios do período MERRA-2 (1981-1995)

- Araguaína/Colinas do Tocantins/Tocantinópolis — nenhuma coordenada, nenhum script de geração e nenhum registro de commit anterior ao primeiro commit do repositório ("Create index.html") documentam a origem dessas 3 colunas em data/master_monthly.csv. Não verificável a partir deste repositório — não estimado aqui para não inventar dado que a tarefa pede para nunca supor.

### Lacunas e qualidade documentadas previamente

- Nenhuma lacuna conhecida do período 1991-2010 está documentada em README.md/CLAUDE.md — as armadilhas documentadas em CLAUDE.md (6/7) cobrem viés de fonte satelital (CHIRPS/ERA5, período recente) e persistência de índices oceânicos, nunca a série de precipitação pré-2011 usada nesta auditoria.

## 4. Correspondência espacial

- Distância REAL grade CFSv2 ↔ centroide das fazendas (lida do RAW aprovado): **22.91 km**.
- Referência anterior (São Bento do Tocantins, piloto): 198.0 km — melhoria de 175.1 km com o centroide das fazendas.
- Observação pré-1996: ÁREA difusa e não documentada — média de 3 municípios (Araguaína/Colinas do Tocantins/Tocantinópolis), coordenadas não verificáveis a partir do repositório.
- Observação pós-1996: ÁREA — média de até 34 fazendas dentro do envelope de ~85.020,5 ha (CLAUDE.md armadilha 8), não um ponto único; número de fazendas reportando varia mês a mês sem mínimo exigido (ver achados de documentação).
- **Descasamento de suporte espacial**: A previsão do CFSv2 é 1 valor por célula de grade (~1° ~ 100km de lado); a observação é uma média sobre uma área (município triplo ou envelope de fazendas), nunca um ponto equivalente à célula de grade — mesmo com a distância melhorada (~23km em vez de 198km), comparar os dois exige decidir explicitamente se a média de área é um proxy aceitável do valor pontual de grade, o que este módulo NÃO decide.

## 5. Alinhamento temporal H1-H6

- Combinações origem×lead auditadas: 1440/1440.
- `mapping_status=OK` em todas: True (1440 confirmadas).
- H1 = mês da própria inicialização (confirmado nos dados persistidos): True.
- Mês-alvo mais distante (H6 da origem 2010-12): 2011-05.

## 6. Períodos utilizáveis

- Combinações disponíveis, não substitutas (nunca CHC-Preliminar/ERA5) e com qualidade OK: 1440/1440.
  - `Estação Sinobras (leitura direta de campo, README.md: baseline 1996-presente)`: 1095
  - `MERRA-2 (reanálise NASA, README.md: baseline 1981-1995)`: 345
- A procedência MERRA-2 (na verdade, achado do item 3: média de 3 municípios não verificável) só se aplica a alvos com ano<=1995 — poucas combinações no início da janela 1991-2010, concentradas nos leads mais longos das origens de 1991.
- **Recomendação**: Reportar qualquer avaliação futura SEPARADAMENTE para alvos MERRA-2/3-municípios (ano<=1995) e alvos Estação Sinobras (ano>=1996) — nunca uma métrica agregada única que misture as duas procedências, dado que já divergem em magnitude (achado do item 3, diff média >1mm/mês pós-1996) e em suporte espacial (item 4).

## 7. Protocolo estatístico proposto (NÃO calculado nesta tarefa)

Proposta para uma etapa FUTURA e SEPARADA — nenhum destes cálculos foi executado aqui.

### 7.1 Determinístico
- Viés médio (bias) e MAE do ensemble mean por lead (H1-H6), separadamente para alvos MERRA-2/3-municípios (ano<=1995) e Estação Sinobras (ano>=1996) — nunca agregados entre si (achado do item 3: já divergem em magnitude).
- Correlação de Pearson/Spearman entre ensemble mean e observação, por lead.

### 7.2 Probabilístico
- CRPS (Continuous Ranked Probability Score) do ensemble de 24 membros por lead.
- Brier Skill Score (BSS) para terços de probabilidade (abaixo/normal/acima), com a climatologia de referência definida na Seção 7.3 como benchmark.
- Diagrama de confiabilidade (reliability diagram) por lead, para checar calibração do ensemble.

### 7.3 Climatologia de referência — mecanismo contra vazamento de informação
- **Nunca** usar a climatologia de referência do dashboard (1981-2025 completa) para avaliar previsões cujo período de emissão (1991-2010) está DENTRO dela — isso vazaria informação futura (relativa a cada ano avaliado) para dentro do benchmark de comparação.
- Proposta: climatologia EXPANSÍVEL retrospectiva — para avaliar o alvo do ano Y, usar só a climatologia calculada com anos < Y (ou, no mínimo, excluir o próprio ano Y e os 2 anos vizinhos, para reduzir autocorrelação de baixa frequência tipo PDO). Alternativa mais simples e auditável: climatologia leave-one-year-out (LOYO) sobre 1981-2010 inteiro, recalculada a cada alvo excluindo o ano do próprio alvo.
- Qualquer que seja a escolha, documentar explicitamente qual conjunto de anos define a climatologia de cada avaliação, no mesmo arquivo/tabela do resultado — nunca implícito.

### 7.4 Decisões que precisam de aprovação explícita antes do cálculo de skill
1. Usar ou não os alvos MERRA-2/3-municípios (ano<=1995) na avaliação, dado que sua procedência como reanálise não foi confirmada (item 3) e as coordenadas dos 3 municípios não são verificáveis.
2. Aceitar ou não a média de área (3 municípios ou até 34 fazendas) como proxy do valor pontual de grade do CFSv2 (item 4) — e se aceitar, registrar isso como premissa explícita do estudo, não como equivalência.
3. Definir o mecanismo exato de climatologia sem vazamento (Seção 7.3) antes de qualquer BSS/anomalia ser calculado.
4. Definir o tratamento de meses com `qualidade_verificada_status` diferente de OK — excluir da avaliação (recomendado) ou uma estratégia de imputação, nunca silenciosamente incluídos como se fossem OK.

## Verdito de aptidão para avaliação científica (infraestrutura + observação)

- `apto_para_avaliacao_cientifica`: **False**
- Motivos de bloqueio:
  - correspondência espacial não resolvida — 22.9 km entre a referência observacional (centroide das fazendas) e o ponto do CFSv2 (centroide das fazendas (grade CFSv2, extração histórica aprovada, run 36238169299)); decisão explícita pendente (docs/nmme-fase2c2-piloto-cobertura-observacional.md)

### Ressalvas adicionais (não incluídas no verdito de infraestrutura acima, mas igualmente bloqueantes para uma avaliação científica)

`avaliar_aptidao_referencia_observacional` (reaproveitada sem modificação) só verifica cobertura/procedência-substituta/qualidade numérica e a distância espacial — ela NÃO avalia se a documentação de procedência é suficiente. As seções 3 e 4 acima levantam problemas que continuam pendentes mesmo se a distância espacial fosse aceita:
- A identidade do trecho "MERRA-2" (1981-1995) com uma média de 3 municípios sem coordenadas/metodologia verificáveis (Seção 3) — usar isso como reanálise de grade seria uma afirmação não sustentada pelo repositório.
- O descasamento de suporte espacial (célula de grade vs. média de área difusa e variável, Seção 4) — não resolvido só por a distância ter melhorado.
- A agregação Sinobras sem mínimo de estações (Seção 3) — um mês com 1 fazenda reportando é tratado, na série, exatamente como um mês com 34.

## Restrições respeitadas nesta tarefa

- Nenhuma métrica de skill foi calculada.
- O dashboard (docs/index.html) não foi tocado.
- Nenhum modelo climático (SARIMAX/XGBoost) foi alterado.
- Os 34.560 registros RAW já extraídos (data/nmme_historico_fazendas/) foram preservados integralmente — este módulo só LÊ esses arquivos.
