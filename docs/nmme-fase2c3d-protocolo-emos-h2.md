# Protocolo do EMOS para H2 — Fase 2C.3D (Método 3.5)

**Documento de desenho experimental — não é relatório de resultados.**
Nenhum parâmetro `a`/`b`/`c`/`d` foi ajustado nesta atividade. Nenhum CRPS do
EMOS foi calculado. Nenhuma probabilidade calibrada foi produzida.
Nenhum pipeline operacional ou dashboard foi alterado. A única exceção
é um diagnóstico puramente **estrutural** de viabilidade do warm-up
proposto (seção 12) e do gate de viabilidade da escala (seção 8) —
ambos sem calcular skill, CRPS ou qualquer coisa que dependa de um
parâmetro ajustado.

A decisão científica que autoriza esta atividade (`classificacao_
robustez_h2 = sinal_h2_robusto`, commit `e7da9f6`, PR #47) **não
significa aprovação de EMOS nem demonstração definitiva de skill
probabilístico** — é só a autorização para escrever este protocolo.

**Revisão desta versão (commit `8ef7f3d` → esta revisão):** a revisão
independente aprovou o escopo (H2), a Normal censurada em zero, a
localização baseada em anomalia, a normalização sazonal do spread, a
escala causal mensal, o warm-up de 120, os 216 pares válidos e o
benchmark `d=0`, mas exigiu fechar 17 pontos matemáticos antes da
implementação real — todos tratados nesta revisão, sem ajustar nenhum
parâmetro EMOS. Em particular: distinção explícita entre `mu_latente`
(parâmetro da Normal latente) e `E[Y]` (média preditiva da variável
censurada — nunca a mesma coisa); fórmula do CRPS fixada como
**analítica e determinística** (nunca amostral/Monte Carlo), com a
expressão verificada numericamente contra integração direta antes de
entrar no protocolo (seção 15); parametrização que garante `sigma > 0`
algebricamente (`c = exp(gamma_c)`); exigência explícita de que o
benchmark `d=0` seja reajustado de forma independente, nunca reaproveitando
os parâmetros do modelo completo; estratégia de inicialização e
otimizador únicos, fixados agora; regra de congelamento da amostra
avaliável; e convenção única de PIT (mid-PIT, determinística) para a
massa em zero.

## 1. Escopo

O EMOS será testado **exclusivamente para H2**. Motivo pré-registrado
(ver `docs/nmme-fase2c3d-robustez-spread-h2.md`): H2 foi o único
horizonte, entre os seis avaliados no gate do Método 3.5, que:

- manteve Pearson residual (controlado por mês) com IC 95% > 0;
- manteve Spearman residual (controlado por mês) com IC 95% > 0;
- passou no leave-one-month-out (positivo nas 12 exclusões, IC>0 em
  11/12 Pearson e 10/12 Spearman, nenhuma inversão forte);
- recebeu a classificação pré-registrada `sinal_h2_robusto`.

H1, H3–H6 não implementam EMOS nesta primeira versão — todos caíram em
`ensemble_mal_calibrado_spread_pouco_informativo` ou não atingiram o
critério de robustez. Uma eventual extensão a outros horizontes é uma
decisão separada, condicionada a uma análise de robustez própria para
cada um (não feita aqui).

## 2. Distribuição preditiva e terminologia (revisão, item 1)

**Normal censurada à esquerda em 0 mm.** Representação conceitual:

```
Z ~ Normal(mu_latente, sigma²)
Y = max(0, Z)
```

**Terminologia fixada — nunca confundir estes campos:**

- `mu_latente` — parâmetro de localização da variável NORMAL LATENTE
  `Z`. **Nunca** chamado de "média da precipitação calibrada" nem de
  qualquer sinônimo que sugira ser diretamente a previsão de chuva.
- `sigma` — desvio-padrão da variável latente `Z` (sempre > 0, seção 10).
- `k = mu_latente / sigma` — razão sinal-ruído do parâmetro latente,
  reaproveitada em todo o documento (seções 3, 4, 15) sob o mesmo nome,
  nunca uma segunda notação paralela para a mesma quantidade.
- `P(Y=0) = Phi(-k)` — probabilidade de precipitação exatamente zero
  (`Phi` = CDF da Normal padrão).
- `media_preditiva_censurada = E[Y] = mu_latente * Phi(k) + sigma * phi(k)`
  — a média da variável CENSURADA (`phi` = PDF da Normal padrão) — é
  esta quantidade, e NUNCA `mu_latente`, que deve ser reportada como
  "previsão pontual" do EMOS quando uma métrica de localização final
  for exigida (ver seção 19).
- `mediana_preditiva` — reportada separadamente via o quantil único da
  seção 4 (`Q(0.5)`), respeitando a massa em zero por construção.

Vantagens desta escolha de distribuição, nesta ordem:

- Não produz valores negativos de precipitação (ao contrário da Normal
  não censurada).
- Tem massa de probabilidade em `Y = 0`, coerente com meses secos onde
  `P(chuva = 0)` não é desprezível.
- Permanece parcimoniosa: 2 parâmetros condicionais (`mu_latente`,
  `sigma`), sem reparametrização elaborada.

**Decisões fixadas, não revisáveis dentro desta primeira versão:**

- Não usar a Normal não censurada.
- Não escolher a distribuição depois de observar qual gera melhor
  CRPS — a censurada em zero foi escolhida aqui, antes de qualquer
  ajuste real.
- Não testar simultaneamente Gamma, GEV, lognormal ou outras
  alternativas nesta primeira versão — um comparativo de família de
  distribuição é um protocolo e uma decisão separados, não desta
  atividade.

## 3. CDF única da distribuição (revisão, item 4)

```
F_Y(y) = 0                              se y < 0
F_Y(y) = Phi((y - mu_latente) / sigma)  se y >= 0
```

A massa em zero é exatamente `F_Y(0) = Phi(-mu_latente/sigma) = Phi(-k)
= P(Y=0)` — a MESMA quantidade já definida na seção 2, nunca uma
segunda fórmula calculada de outra forma.

Esta é a ÚNICA CDF usada em todo o protocolo — para probabilidades de
tercil (seção 19), para os intervalos (seção 4 abaixo), para o PIT
(seção 19) e para a probabilidade de zero. **Não** implementar uma
fórmula independente por métrica — qualquer uma dessas quantidades
deve ser derivada de `F_Y`, nunca recalculada à parte.

## 4. Quantil censurado único (revisão, item 5)

```
Q(p) = 0                                se p <= P(Y=0)
Q(p) = mu_latente + sigma * Phi^-1(p)   se p >  P(Y=0)
```

Garantia algébrica de `Q(p) >= 0`: quando `p > P(Y=0) = Phi(-k)`, então
`Phi^-1(p) > -k = -mu_latente/sigma`, logo `sigma * Phi^-1(p) >
-mu_latente` (pois `sigma > 0`), logo `mu_latente + sigma * Phi^-1(p) >
0`; no outro ramo `Q(p) = 0` por definição — portanto `Q(p) >= 0` em
qualquer caso, nunca verificado só numericamente depois do fato.

Usar este quantil único para os intervalos centrais 50/80/90%, com a
MESMA convenção de percentis já usada no gate para o ensemble RAW
(`_INTERVALOS_NOMINAIS = {50: (25,75), 80: (10,90), 90: (5,95)}` em
`cfsv2_gate_calibracao_probabilistica.py`) — ex.: intervalo 50% =
`[Q(0.25), Q(0.75)]`. **Não** obter intervalos por amostragem Monte
Carlo, e **não** criar uma segunda convenção de nível de intervalo só
para o EMOS.

## 5. Localização (`mu_latente`)

**Não** usar `mu_latente = a + b * ensemble_mean` sobre precipitação
bruta — isso reintroduziria exatamente o confundimento sazonal que o
gate já expôs (seções 3/3.1 de `docs/nmme-fase2c3d-gate-calibracao-
probabilistica-cfsv2.md`).

Em vez disso, usar o espaço de anomalia já aprovado metodologicamente
(mesma convenção causal do Método 3.4 — MOS linear):

```
anom_ensemble = ensemble_mean - climatologia_modelo_raw
mu_latente    = climatologia_observada + a + b * anom_ensemble
```

onde `climatologia_modelo_raw` e `climatologia_observada` são EXATAMENTE
os campos já causais e aprovados (`clim_modelo_media`/`clim_media` em
`cfsv2_validacao_cientifica._enriquecer_com_climatologia`,
reaproveitados sem redefinição) — ambos calculados com a disponibilidade
real daquela própria `init_date`, nunca recalculados retrospectivamente
com dados futuros.

Isso garante que o ciclo sazonal principal seja absorvido pelas duas
climatologias (a do modelo e a observada), deixando `a`/`b` livres para
ajustar prioritariamente o sinal interanual — não o ciclo sazonal, que
já é tratado antes de `a`/`b` entrarem na equação.

## 6. Benchmark de localização (revisão, item 2)

Fixar `a = 0`, `b = 1` reduz `mu_latente` a:

```
mu_latente = climatologia_observada + anom_ensemble
           = climatologia_observada + (ensemble_mean - climatologia_modelo_raw)
```

que é exatamente o `benchmark_anomalia_reconstruida` já definido e usado
no Método 3.4 — a mesma identidade algébrica, mesmo nome, nunca uma
segunda fórmula paralela.

**Precisão exigida pela revisão:** essa equivalência é do **parâmetro
de localização LATENTE**, não da previsão final. **Não afirmar que
`E[Y] = benchmark_anomalia_reconstruida`** — depois da censura em zero,
`E[Y] = mu_latente * Phi(k) + sigma * phi(k) != mu_latente` em geral
(as duas quantidades só coincidiriam no limite degenerado `sigma → 0`
ou `k → ∞`, que não ocorre na prática). A leitura correta do benchmark
é: "o parâmetro de localização latente do EMOS, sem ajuste nenhum,
coincide com a reconstrução causal pela anomalia" — a média preditiva
final (`E[Y]`) é sempre menor que `mu_latente` em valor esperado,
porque a censura em zero "puxa" a massa negativa da Normal latente
para cima, em vez de descartá-la.

## 7. Dispersão — evitar confundimento sazonal

O gate (seção 2 de `docs/nmme-fase2c3d-gate-calibracao-probabilistica-
cfsv2.md`) já mostrou que `ensemble_std` bruto é fortemente sazonal.
**Não** usar, como primeira formulação, `sigma² = c + d * ensemble_std²`
sobre todos os meses agregados — isso herdaria o mesmo confundimento que
motivou toda a revisão sazonal do gate.

Em vez disso:

```
spread_clim_modelo_mes = climatologia EXPANSÍVEL causal de ensemble_std,
                          usando só inicializações históricas anteriores
                          do mesmo target_mes (mesmo padrão causal de
                          v.climatologia_modelo_expansivel, aplicado ao
                          spread em vez da média)

spread_relativo = ensemble_std / spread_clim_modelo_mes
                   (só quando o denominador é válido e > 0)

sigma = erro_clim_sd_mes * sqrt(c + d * spread_relativo²)
```

com `c >= 0`, `d >= 0` (garantia algébrica de positividade estrita na
seção 10), e `erro_clim_sd_mes` definido como a **escala climatológica
base**:

```
erro_clim_sd_mes = desvio-padrão EXPANSÍVEL causal de erro_assinado
                    (ensemble_mean - obs), usando só inicializações
                    históricas anteriores do mesmo target_mes — mesmo
                    padrão causal de spread_clim_modelo_mes, aplicado
                    ao erro em vez do spread
```

Essa formulação separa deliberadamente dois efeitos:

- **heterogeneidade sazonal de escala** — absorvida por
  `erro_clim_sd_mes`, que varia naturalmente entre a estação seca
  (escala pequena) e a chuvosa (escala grande);
- **modulação dinâmica caso a caso** — o termo `spread_relativo²`, que
  é o que o gate e a análise de robustez de H2 efetivamente testaram
  (correlação spread×erro **controlada por mês**, nunca a correlação
  pooled).

## 8. Gate de viabilidade da escala

Antes de qualquer ajuste real, o protocolo exige confirmar que
`spread_clim_modelo_mes > 0` e `erro_clim_sd_mes > 0` nos casos
elegíveis. Diagnóstico estrutural executado na atividade anterior
(script `scripts/cfsv2_emos_h2_viabilidade_warmup.py --executar`, SEM
calcular nenhum CRPS/skill — não refeito nesta revisão, números
inalterados):

- **216 de 240** inicializações de H2 têm par causal válido (as duas
  climatologias disponíveis e positivas).
- **Todos** os 216 casos válidos têm `spread_clim_modelo_mes > 0` e
  `erro_clim_sd_mes > 0` — nenhum denominador zero ou negativo foi
  encontrado, nem nos meses secos.
- Mínimos por mês (entre os casos válidos) ficam pequenos, mas
  claramente positivos, mesmo nos meses mais secos:

| Mês | N válidos | `spread_clim_modelo_mes` mínimo | `erro_clim_sd_mes` mínimo |
|---|---|---|---|
| Jun | 18 | 1,35 mm | 0,62 mm |
| Jul | 18 | 1,07 mm | 0,24 mm |
| Ago | 18 | 1,40 mm | 9,19 mm |
| Set | 18 | 4,33 mm | 33,25 mm |

(demais meses com mínimos de 15mm a 91mm — ver
`data/cfsv2_calibracao_2c3d/emos_h2_viabilidade_warmup_2c3d.json` para
a tabela completa dos 12 meses.)

**Conclusão do gate:** nenhum piso numérico precisa ser definido nesta
versão — os denominadores observados nunca chegam perto de zero, mesmo
nos meses mais secos. **Nenhum piso foi escolhido com base em
desempenho** (isso é proibido pelo próprio protocolo); se uma versão
futura com dados diferentes encontrar um denominador patologicamente
pequeno, o critério numérico precisa ser definido então, antes de
calcular qualquer skill — nunca depois.

## 9. Parâmetros

Modelo principal: **4 parâmetros globais** para H2 — `a`, `b`, `c`, `d`
(mais a reparametrização `gamma_c` da seção 10, que não é um parâmetro
científico adicional, só uma transformação de `c`).

**Não** estimar parâmetros separados por mês. **Não** criar:

- 12 interceptos ou 12 slopes por mês;
- interação mês × spread;
- termos de ENSO;
- termos quadráticos adicionais;
- mixture model.

A sazonalidade entra pelas climatologias/escala causais (`climatologia_
modelo_raw`, `climatologia_observada`, `erro_clim_sd_mes`), nunca por
dezenas de coeficientes extras — mesma filosofia de parcimônia já usada
no MOS linear (Método 3.4): poucos parâmetros, sazonalidade absorvida
pelas climatologias, nunca por um mês-dummy.

## 10. Restrições e garantia algébrica de `sigma > 0` (revisão, item 6)

As condições originais `c >= 0`, `d >= 0` **não impedem** `c = d = 0`,
o que produziria `sigma = 0` e tornaria a CDF/CRPS numericamente
inválidos (divisão por zero em `z = (y-mu_latente)/sigma`). Corrigido
com reparametrização:

```
gamma_c irrestrito (qualquer real)
c       = exp(gamma_c)           →  c > 0 ESTRITAMENTE, nunca c = 0
d      >= 0                       →  bound direto no otimizador (seção 16)

sigma = erro_clim_sd_mes * sqrt(c + d * spread_relativo²)
```

Como `erro_clim_sd_mes > 0` (confirmado no gate, seção 8, em todos os
216 casos válidos) e `c = exp(gamma_c) > 0` por construção da função
exponencial (nunca zero, para nenhum `gamma_c` finito), `sigma > 0` é
**garantido algebricamente** — nunca dependente de um piso numérico
escolhido por desempenho.

**Proteção numérica (nunca parâmetro científico):** pode existir um
termo extremamente pequeno (ex.: `1e-12`) somado dentro da raiz só como
salvaguarda de ponto flutuante contra instabilidade numérica da CDF/CRPS
em casos extremos de avaliação computacional — isso deve ser
documentado explicitamente no código, exatamente como "proteção de
ponto flutuante", e **nunca** apresentado como um piso científico ou
ajustado para melhorar desempenho.

Para `a` e `b`, **não** impor truncamento arbitrário. Registrar (nunca
impedir silenciosamente) se o ajuste real produzir:

- `b < 0` (destaque científico obrigatório — investigar antes de
  qualquer conclusão, mesma convenção já usada no MOS linear);
- `b ≈ 0` (anomalia do CFSv2 praticamente ignorada);
- `b ≈ 1` (comportamento próximo do benchmark de localização, seção 6);
- `b > 1` (amplificação da anomalia do CFSv2).

## 11. Treinamento causal

Avaliação principal: **expanding-window**. Para cada `init_date` de H2
avaliada:

- usar SOMENTE casos de treino com `init_date_treino < init_date_avaliada`
  (nunca `<=`);
- nunca usar a própria linha avaliada no ajuste;
- nunca usar informação futura;
- todos os componentes causais de cada linha histórica (climatologia do
  modelo, climatologia observada, `spread_clim_modelo_mes`,
  `erro_clim_sd_mes`) devem ser os que estavam REALMENTE disponíveis
  naquela `init_date` — nunca recalculados com o benefício de dados
  publicados depois.

## 12. Warm-up (revisão, item 10 — definitivo)

```
N_TREINO_MINIMO_EMOS = 120 casos válidos
```

**Mantido definitivamente — não reduzido.** Motivos:

- 4 parâmetros globais no modelo completo;
- ~30 observações por parâmetro, mesma régua já usada;
- mesma filosofia conservadora do warm-up do MOS linear (Método 3.4,
  `N_TREINO_MINIMO_MOS = 120`);
- a escolha foi feita (e registrada) ANTES de qualquer resultado real
  de EMOS;
- reduzir agora, só para aumentar o N de avaliação, seria uma decisão
  metodológica motivada pelo resultado — exatamente o que o protocolo
  existe para evitar.

**Viabilidade estrutural** (calculada na atividade anterior, SEM
nenhum CRPS/skill do EMOS — script `cfsv2_emos_h2_viabilidade_
warmup.py`, não refeito nesta revisão):

| Quantidade | Valor |
|---|---|
| Inicializações de H2 no total | 240 |
| Pares H2 válidos (causal, ambas climatologias + spread/erro mensais > 0) | 216 |
| Primeira `init_date` elegível (`n_treino_disponivel >= 120`) | `2003-01` |
| `n_treino_disponivel` nessa data | 120 |
| **Previsões finais avaliáveis** | **96** (≈ 8 anos) |

**Limitação registrada explicitamente, para constar em qualquer
relatório futuro de resultados:** a avaliação principal cobre apenas
**96 previsões (≈ 8 anos)** — uma janela sensivelmente mais curta que
as 240 inicializações totais de H2, porque o warm-up consome 120 dos
216 pares válidos (~56%). Isso é o preço da escolha conservadora da
seção 9, aceito deliberadamente, não uma falha a corrigir depois.

## 13. Casos avaliáveis e congelamento da amostra (revisão, item 11)

O conjunto principal de avaliação é definido por esta regra, congelada
ANTES de qualquer ajuste real:

Uma `init_date` de H2 entra na avaliação principal se, e somente se:

1. é H2 (`lead = 2`);
2. tem par causal válido (seção 8);
3. `n_treino_disponivel >= 120` (seção 12);
4. a otimização do **EMOS completo** convergiu, usando só o treino
   causal disponível até essa data;
5. a otimização do **EMOS `d=0`** convergiu, de forma INDEPENDENTE
   (seção 17), usando a MESMA janela de treino;
6. todos os benchmarks (RAW, climatologia causal) estão disponíveis
   nessa mesma data.

**Nunca** avaliar o EMOS completo e o EMOS `d=0` em amostras diferentes
— se um dos dois modelos falhar a convergir numa data específica, essa
data precisa ser tratada EXPLICITAMENTE (reportada, nunca
silenciosamente excluída) antes de qualquer comparação entre os dois.
Se isso ocorrer na base real, **STOP-ON-FAILURE** — a implementação
não decide por conta própria o que fazer com uma data que quebra essa
regra.

**Esperado estrutural:** `N = 96` (seção 12). Se o número real de
casos avaliáveis divergir disso na implementação (por exemplo, por
falhas de convergência), a divergência precisa ser explicada antes de
calcular qualquer CRPS/skill — nunca silenciosamente aceita.

## 14. Estimação dos parâmetros

Método pré-registrado: **minimização do CRPS médio da Normal censurada
em zero** (fórmula analítica fixada na seção 15) sobre a janela de
treinamento (expanding, causal).

- **Não** minimizar RMSE.
- **Não** maximizar log-likelihood como primeira alternativa.
- Motivo: CRPS é a métrica probabilística PRINCIPAL já usada em todo o
  projeto (Métodos de validação 2C.3C, gate do Método 3.5) e avalia
  localização e dispersão simultaneamente — manter a mesma métrica de
  ajuste e de avaliação evita um descompasso entre o que o modelo
  otimiza e o que o relatório reporta.

## 15. CRPS — fórmula definitiva e determinística (revisão, item 3)

**Fixado definitivamente — removida a escolha aberta entre fórmula
fechada e forma amostral.** A implementação deve usar o CRPS
**ANALÍTICO e DETERMINÍSTICO** da Normal censurada em zero — nunca
Monte Carlo/amostragem na função objetivo, para garantir que o
otimizador seja completamente determinístico.

Para uma observação `y >= 0` (toda observação de precipitação é
`>= 0` por definição):

```
z  = (y - mu_latente) / sigma
a0 = -mu_latente / sigma         (= -k, mesma quantidade da seção 2)

G(t) = t * Phi(t)^2 + 2*Phi(t)*phi(t) - Phi(sqrt(2)*t) / sqrt(pi)

CRPS = sigma * [ G(z) + G(-z) - G(a0) ]
```

**Validação numérica realizada nesta atividade** (verificação
matemática pura com valores sintéticos de `mu_latente`/`sigma`/`y` —
NÃO é ajuste de EMOS, nenhum dado real de H2 foi usado): a fórmula
fechada acima foi comparada contra integração numérica direta de
`∫ (F_Y(x) - 1{x>=y})² dx` (`F_Y` da seção 3) para 7 casos, incluindo
`y=0`, `mu_latente` negativo, `mu_latente` positivo, `sigma` pequeno
(0,3) e `sigma` grande (5,0) — concordância em todos os casos dentro de
`1e-10`, muito abaixo de qualquer tolerância razoável de implementação.

**Teste futuro obrigatório** (a ser codificado na implementação, não
nesta atividade): automatizar exatamente essa comparação (fórmula
fechada vs. integração numérica, `scipy.integrate.quad` ou equivalente)
para os mesmos 5 tipos de caso, com tolerância pré-definida (ex.:
`1e-6`) fixada ANTES de rodar o teste — nunca ajustada depois de ver se
passa. Ver seção 24.

## 16. Otimização (revisão, itens 8/9)

Fixado explicitamente ANTES da implementação real:

**Algoritmo único:** `scipy.optimize.minimize(method='L-BFGS-B')` —
suporta os `bounds` necessários (`d >= 0`; `gamma_c`, `a`, `b`
irrestritos) sem exigir um bound explícito em `c` (a reparametrização
`c = exp(gamma_c)` da seção 10 já garante `c > 0` sem bound). **Não**
testar vários otimizadores e escolher o que produz o melhor score
depois de ver os resultados — um único algoritmo, decidido agora.

**Inicialização determinística, igual para TODAS as datas causais e
para os dois modelos onde aplicável:**

- Localização: `a0 = 0`, `b0 = 1`.
- Dispersão, EMOS completo: `gamma_c0 = 0` (ou seja, `c0 = 1`), `d0 = 0,1`.
- Dispersão, EMOS `d=0`: `gamma_c0 = 0` (`c0 = 1`); `d` fica FIXO em 0
  durante toda a otimização (nunca um parâmetro livre nesse modelo —
  ver seção 17).

**Não** experimentar múltiplos pontos de partida e selecionar o de
menor CRPS depois de ver os resultados. Se problemas numéricos reais
exigirem multi-start, isso precisa ser aprovado ANTES da implementação,
com todos os pontos de partida fixados a priori (nunca escolhidos
post-hoc).

**Convergência:** tolerância, `maxiter` e critério de convergência
devem ser fixados e documentados no código da implementação (valores
exatos não fazem parte deste protocolo, mas precisam estar decididos
antes de rodar contra dados reais). Falha de convergência:

```
status_emos = 'otimizacao_nao_convergiu'
```

e **STOP-ON-FAILURE** na base real antes de qualquer conclusão
científica — nunca trocar de algoritmo automaticamente para contornar
uma falha de convergência.

## 17. Benchmarks probabilísticos obrigatórios (revisão, item 7)

EMOS H2 deve ser comparado, **nos MESMOS casos avaliáveis** (seção 13),
contra:

1. **Ensemble RAW CFSv2** (sem qualquer correção) — mesma definição já
   usada no gate (`crps_amostral` sobre os 24 membros brutos).
2. **Climatologia causal observada probabilística** — mesma definição
   já usada no gate e na 2C.3C (`anos_hist` elegíveis).
3. **Versão probabilística SEM spread dinâmico** (`EMOS d=0`) —
   modelo restrito que mantém a MESMA estrutura de média (seção 5) e de
   escala climatológica (`erro_clim_sd_mes`), mas fixa `d = 0`:
   ```
   sigma_d0 = erro_clim_sd_mes * sqrt(c_d0)
   ```
   **Exigência obrigatória da revisão:** os parâmetros `a`, `b`, `c`
   deste modelo restrito (aqui `c_d0`, para deixar explícito que é uma
   estimativa PRÓPRIA, não a mesma do modelo completo) devem ser
   **reajustados causal e INDEPENDENTEMENTE**, minimizando a MESMA
   função objetivo (CRPS, seção 15) sobre a MESMA janela de treino —
   **nunca** reaproveitar os `a`, `b`, `c` já ajustados do modelo
   completo e só substituir `d` por `0`. Fazer isso favoreceria
   artificialmente o modelo completo (ele teria seus próprios `a,b,c`
   ótimos, enquanto o restrito ficaria com parâmetros sub-ótimos para
   sua própria estrutura), inflando de forma espúria a diferença entre
   os dois. É esperado — e deve ser reportado quando ocorrer — que
   `a_d0`, `b_d0`, `c_d0` sejam DIFERENTES de `a`, `b`, `c` do modelo
   completo (ver teste obrigatório na seção 24).

   Este terceiro benchmark é **essencial** — responde diretamente se o
   termo dinâmico do spread melhora a previsão probabilística, ou se
   basta corrigir média e dispersão climatológica (sem usar o spread
   caso a caso). É o benchmark probabilístico CENTRAL desta fase.

## 18. Comparação EMOS completo × EMOS sem spread

A ser calculado na implementação futura (NÃO nesta atividade):

```
CRPSS_spread_dinamico = 1 - CRPS_EMOS_completo / CRPS_EMOS_d0
```

com bootstrap em blocos por `target_ano` (seção 21), sobre os mesmos
96 casos congelados (seção 13). Este é o teste mais direto da hipótese
levantada pelo gate — e deve ser calculado e reportado explicitamente,
nunca inferido indiretamente de outras comparações.

**Se o IC 95% de `CRPSS_spread_dinamico` incluir zero: não afirmar que
o spread dinâmico acrescenta valor**, mesmo que o EMOS completo supere
o ensemble RAW — a melhoria, nesse caso, viria só da correção de
média/dispersão climatológica, não do termo `d * spread_relativo²`.

## 19. Métricas (revisão, itens 13/14/15)

Pré-registradas para H2 (calculadas na implementação futura), todas
derivadas da ÚNICA `F_Y`/`Q(p)` das seções 3/4 — nunca uma fórmula
paralela por métrica:

- CRPS médio (EMOS completo, fórmula da seção 15);
- CRPSS vs. RAW;
- CRPSS vs. climatologia causal;
- CRPSS vs. EMOS `d=0` (seção 18 — o teste central);
- **Brier Score por tercil** — reaproveitar EXATAMENTE os limiares `t33`/
  `t67` já causais e aprovados (2C.3C/gate), nunca uma nova convenção de
  tercis para o EMOS. Probabilidades calculadas a partir da `F_Y` única
  (seção 3): `P(seco) = F_Y(t33)`, `P(umido) = 1 - F_Y(t67)`,
  `P(normal) = 1 - P(seco) - P(umido)`. **Atenção explícita a meses
  secos com `t33 = 0` ou muito próximo de zero** (possível, já que
  `Y=0` tem massa própria): garantir que as três categorias não sejam
  contadas duplamente (a massa em `Y=0` precisa cair inteiramente em
  UMA categoria, nunca dividida), que as três probabilidades somem 1,
  e que o Brier Score permaneça finito — caso sintético dedicado na
  seção 24.
- BSS (mesma referência nominal `mean((1/3-o_i)²)` já aprovada, nunca a
  constante `2/9`);
- cobertura empírica 50/80/90%, via o quantil único `Q(p)` (seção 4);
- largura média dos intervalos;
- **PIT com massa em zero** — como a distribuição é MISTA (massa
  discreta em `Y=0` + componente contínuo em `Y>0`), **não** usar PIT
  contínuo ingênuo nas observações iguais a zero (produziria um valor
  mal definido). Convenção ÚNICA pré-registrada: **mid-PIT**,
  determinística, sem RNG:
  ```
  PIT(y) = F_Y(y)                 se y > 0   (PIT contínuo padrão)
  PIT(y) = F_Y(0) / 2 = P(Y=0)/2  se y = 0   (ponto médio da massa discreta)
  ```
  Escolhida especificamente por ser reprodutível sem seed (nenhum
  sorteio aleatório na análise principal) — alternativa ao PIT
  randomizado, que exigiria RNG documentada. **Uma única convenção**,
  decidida agora — nunca alternar entre mid-PIT e PIT randomizado
  conforme o resultado observado.
- **Bias — duas métricas distintas, nunca confundidas:**
  - `bias_mu_latente = mean(mu_latente - obs)` — diagnóstico do
    parâmetro LATENTE, não a métrica de previsão final;
  - `bias_media_preditiva_censurada = mean(E[Y] - obs)` — a métrica
    PRINCIPAL de bias da previsão final, porque `E[Y]` (não
    `mu_latente`) é o que de fato é comparável a uma previsão de
    precipitação.
  A métrica principal de bias reportada em qualquer relatório futuro
  DEVE usar `E[Y]`, nunca `mu_latente`.

**Não** aprovar o modelo só por cobertura — cobertura isolada não
distingue, como o próprio gate já registrou, se o problema é de
localização ou de dispersão.

## 20. Critério de aprovação (revisão, item 16 — mantido sem alteração)

Para justificar o componente dinâmico de spread, exigir, SIMULTANEAMENTE:

1. `IC 95%(CRPSS_spread_dinamico) > 0` (seção 18) — condição
   necessária, não suficiente por si só.
2. EMOS completo supera a climatologia probabilística causal com
   `IC 95%(CRPSS vs. climatologia) > 0`.
3. Nenhuma degradação grave de Brier Score/BSS em relação aos
   benchmarks.
4. Melhora substancial na calibração de cobertura/PIT frente ao
   ensemble RAW (que o gate já mostrou underdispersive com componente
   de bias — seção 4.1 do relatório do gate).

**Se o EMOS só superar o RAW mas não a climatologia: não aprovar.** O
RAW já é conhecidamente fraco (CRPSS negativo em todos os horizontes no
gate) — superá-lo não é uma barra suficiente.

## 21. Bootstrap (revisão, item 12 — esclarecimento: sem refit)

Sempre em blocos por `target_ano` (mesmo padrão de todo o projeto desde
a 2C.3C). **Esclarecimento explícito desta revisão:** depois de gerar a
sequência causal das 96 previsões out-of-sample (seção 13), o bootstrap
principal reamostra `target_ano` **sobre essas previsões JÁ
produzidas** — ele **não reajusta** o EMOS (nem completo, nem `d=0`)
dentro de cada reamostra. Em outras palavras, o IC resultante é
**condicional à sequência causal de forecasts já ajustados por
expanding-window** — a mesma convenção já usada nos Métodos 3.1–3.4
(nenhum deles reajustava `alpha`/`beta` dentro do bootstrap). Essa
limitação deve ser registrada explicitamente em qualquer relatório
futuro de resultados, não omitida.

Nos MESMOS anos sorteados em cada reamostra, comparar simultaneamente:

- EMOS completo;
- EMOS `d=0`;
- RAW;
- climatologia causal.

**Não** calcular ICs independentes para cada um e depois combinar ou
dividir médias separadamente — o numerador e o denominador de cada
CRPSS precisam vir do MESMO sorteio de anos (mesma lição já aplicada em
toda a 2C.3C/2C.3D).

## 22. Avaliação mensal

H2 pode ser avaliado posteriormente por mês **somente como
diagnóstico** descritivo (mesmo padrão da matriz mês×lead já usada no
gate e na robustez de H2) — **não** ajustar um EMOS separado por mês,
**não** fazer 12 testes formais de significância.

Dar atenção a março, que foi o mês de maior influência na análise de
robustez (seções 3.2.1 e 7 de `docs/nmme-fase2c3d-robustez-spread-h2.md`)
— mas **não** tratá-lo de forma diferente no modelo (nenhum parâmetro
específico de março, nenhuma exclusão automática).

## 23. LOYO

Pode haver um LOYO (leave-one-year-out) como diagnóstico secundário,
mesmo padrão já usado nos Métodos 3.1–3.4. **Nunca** usado como
avaliação operacional. Se implementado, a comparação expanding × LOYO
precisa usar exatamente os mesmos casos (`matched`), nunca comparar
amostras diferentes diretamente — mesma lição já registrada no MOS
linear (Método 3.4).

## 24. Testes futuros obrigatórios (revisão — expandido)

A implementação futura deve incluir testes para:

- censura em zero corretamente aplicada (`Y = max(0, Z)`);
- probabilidade em `Y = 0` corretamente calculada por `F_Y(0) =
  Phi(-mu_latente/sigma)` (seções 2/3);
- **CRPS fechado (seção 15) concordando com integração numérica
  direta** (`∫(F_Y(x) - 1{x>=y})² dx`) dentro de tolerância
  pré-definida, para os 5 tipos de caso já verificados nesta atividade
  (`y=0`; `mu_latente` negativo; `mu_latente` positivo; `sigma`
  pequeno; `sigma` grande) — a verificação numérica desta atividade
  (seção 15) não substitui este teste automatizado, só confirma que a
  fórmula escolhida é razoável antes de codificá-la;
- `c = exp(gamma_c)` nunca produz `c <= 0` para nenhum `gamma_c` finito
  avaliado; `d >= 0` sempre respeitado (nunca violado silenciosamente
  pelo otimizador); `sigma` sempre estritamente positivo, linha a
  linha, mesmo em casos extremos de `gamma_c`/`d` (seção 10);
- **os parâmetros `a_d0, b_d0, c_d0` do modelo `d=0` PODEM (e devem,
  tipicamente) diferir dos parâmetros `a, b, c` do modelo completo** —
  teste que compara os dois conjuntos de parâmetros e levanta alerta se
  forem suspeitosamente idênticos sem explicação (sinal de que o
  modelo `d=0` não foi de fato reajustado de forma independente —
  seção 17);
- **STOP-ON-FAILURE disparado corretamente** quando o otimizador não
  converge, para o modelo completo OU para o `d=0`, e confirmação de
  que a data correspondente é tratada explicitamente (nunca excluída
  em silêncio — seção 13);
- o N de casos avaliáveis bate com o valor estrutural esperado (`96`,
  seção 12) ou, se divergir, a implementação levanta e documenta a
  divergência antes de calcular qualquer CRPS/skill;
- o bootstrap (seção 21) reamostra só as previsões JÁ produzidas —
  nenhuma chamada ao otimizador ocorre dentro do laço de bootstrap;
- ausência de leakage (nenhuma linha de treino com `init_date >=
  avaliada`; nenhum dado futuro em nenhuma climatologia);
- climatologias históricas preservadas linha a linha (mesma garantia já
  testada no MOS linear);
- `spread_relativo` calculado apenas com `spread_clim_modelo_mes`
  CAUSAL (nunca com uma climatologia do spread calculada
  retrospectivamente);
- `d=0` realmente remove TODA informação caso a caso do spread (ou
  seja, `sigma_d0` não depende de `ensemble_std` de forma alguma);
- **Brier Score finito e as três probabilidades de tercil somando 1**
  mesmo em caso sintético de mês seco com `t33 = 0` (ou muito próximo),
  sem contagem duplicada da massa em `Y=0` (seção 19);
- **mid-PIT calculado exatamente pela fórmula da seção 19** (`F_Y(0)/2`
  quando `y=0`, `F_Y(y)` quando `y>0`), nunca com RNG na análise
  principal;
- bias de `E[Y]` e de `mu_latente` reportados e testados como métricas
  DISTINTAS (seção 19), nunca uma substituindo a outra;
- as MESMAS chaves (`init_date × lead`) em todos os benchmarks
  comparados;
- bootstrap usando os MESMOS anos sorteados entre EMOS completo, EMOS
  `d=0`, RAW e climatologia.

## 25. Limitações a registrar

- H2 foi 1 horizonte entre 6 avaliados — nenhuma correção formal de
  multiplicidade (Bonferroni/FDR) foi aplicada como critério de gate;
  a evidência é tratada como exploratória, ainda que robusta
  internamente (12/12 exclusões mensais positivas, 11/12 e 10/12 com
  IC>0).
- O período histórico é curto: 240 inicializações de H2, 216 pares
  válidos, e o warm-up definitivo de 120 (seção 12) deixa só **96
  previsões avaliáveis (≈ 8 anos)** — uma janela sensivelmente curta
  para inferência probabilística robusta. Isso não foi reduzido para
  aumentar a amostra, e deve ser comunicado junto com qualquer
  resultado futuro, nunca suavizado.
- `mu_latente` (parâmetro ajustado) e `E[Y]` (média preditiva censurada)
  são quantidades DIFERENTES (seção 2/6) — qualquer comunicação de
  resultados futura precisa deixar explícito qual das duas está sendo
  reportada.
- Os 24 membros do ensemble NÃO equivalem a 24 amostras temporais
  independentes (dependência par-a-par alta mesmo após remoção da
  climatologia mensal — seção 8 do relatório do gate).
- O spread contém informação MODESTA (correlações residuais na faixa
  de 0,07 a 0,24), não FORTE — isso deve ser comunicado explicitamente
  em qualquer relatório futuro de resultados, nunca inflado.
- Calibração probabilística não cria skill dinâmico que não existe —
  o EMOS pode, na melhor das hipóteses, extrair o sinal modesto já
  identificado; não deve ser apresentado como uma fonte de skill nova.

## 26. Esta atividade é protocolo apenas

**Não realizado nesta atividade (nem na revisão):**

- ajuste de `a`, `b`, `c`, `d` (nem do modelo completo, nem do `d=0`);
- cálculo de CRPS do EMOS sobre dados reais de H2;
- produção de probabilidades calibradas;
- alteração do pipeline operacional;
- alteração do dashboard.

**Realizado nesta revisão** (e só isso, além deste documento):
verificação numérica da fórmula fechada do CRPS contra integração
direta, usando exclusivamente valores sintéticos de `mu_latente`/
`sigma`/`y` (seção 15) — matemática pura, nenhum dado real de H2
envolvido. Os números estruturais de viabilidade (216 pares válidos,
warm-up em `2003-01`, 96 previsões avaliáveis — seções 8/12) são os
MESMOS já calculados na atividade anterior, não recalculados aqui.

Suíte de testes existente e `scripts/verificar_dashboard.py` foram
executados só para confirmar ausência de regressão — não para validar
nenhum resultado novo de EMOS (que não existe nesta atividade).
