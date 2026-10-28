# RN-2H — Escala numérica interna da otimização EMOS H2

**Documento científico da implementação experimental RN-2H.** Registra o
problema numérico, a cadeia de evidências (RN-2C a RN-2G) que levou à
correção, a justificativa matemática da reescala, seus efeitos sobre
`ftol`/`gtol`, a distinção entre mínimo matemático e trajetória numérica,
limitações de reprodutibilidade, riscos residuais (incluindo um achado
NOVO desta rodada), o resultado da revalidação histórica e o plano de
rollback. **A implementação permanece experimental até aprovação externa
explícita** — este documento não substitui essa aprovação.

Implementado em `scripts/cfsv2_emos_h2_implementacao.py`:
`K_ESCALA_INTERNA_OTIMIZACAO`, `_aplicar_escala_interna`, e os wrappers
finos `ajustar_emos_completo`/`ajustar_emos_d0`. `_objetivo_completo`,
`_objetivo_d0`, `crps_normal_censurada`, `theta0`, `bounds`, `ftol` e
`maxiter` permanecem byte a byte os mesmos — nenhum deles foi
reimplementado ou alterado nesta rodada.

## 1. Problema numérico identificado

RN-2C (run `40562771232`, AMD EPYC 7763/Haswell): o submodelo `completo`
retornou `success=True`, `status=0`,
`message='CONVERGENCE: RELATIVE REDUCTION OF F <= FACTR*EPSMCH'`,
`fun=0.000418233`. O contrato de qualidade já aprovado da RN-2B
(`_verificar_resultado_otimizador`, independente de `success`) rejeitou
essa solução: um vizinho determinístico da MESMA função objetivo, sem
rodar `minimize` de novo, encontrou `fun_vizinho=0.000255165` — **38,99%
de melhoria disponível** no mesmo ponto que o scipy classificou como
"convergido". Ou seja: `success=True` não significa, aqui, "ótimo
alcançado" — significa apenas "o critério `ftol` do L-BFGS-B foi
satisfeito", e esse critério pode ser satisfeito longe do ótimo quando a
escala do objetivo é pequena (seção 4).

## 2. Evidências RN-2D a RN-2G

- **RN-2D** (PR #61, run `40681237774`): instrumentação de observação
  pura confirmou que chamadas A (teste isolado), B (interna do pipeline)
  e C (direta, mesmo conjunto causal) são **bit-idênticas** entre si —
  mesmo `x`, `jac`, `fun`, `nit`, `nfev`, `success`, `status`, mesma
  fingerprint sha256 dos arrays de treino. Isso **descartou** a hipótese
  de não-determinismo entre chamadas dentro do mesmo processo (ex.:
  paralelismo do OpenBLAS) como causa — o resultado é determinístico e
  reproduzível *neste* ambiente, não um flake.
- **RN-2E**: derivação e validação offline do gradiente analítico do
  CRPS da EMOS H2, usada para construir a Configuração D do experimento
  decisório (RN-2F) e para descartar "precisão do cálculo do gradiente"
  como explicação isolada.
- **RN-2E.1** (validação controlada, offline, antes de tocar em código de
  produção): a partir do `theta0` ORIGINAL (a trajetória operacional
  real), `ftol ∈ {1e-10, 1e-12, 1e-14}` deu resultado **bit-idêntico**
  — reduzir só `ftol` não muda nada na trajetória real. Só reiniciando
  artificialmente a partir do ponto subótimo já conhecido (cenário
  puramente diagnóstico, nunca a trajetória operacional) um `ftol` menor
  escapava para a solução boa — não extrapolável para o caso real.
- **RN-2E.2** (PR #61, run `40707148382`, mesmo experimento, agora na CI
  real): confirmou o mesmo resultado — `ftol` isolado, a partir do ponto
  de partida que a produção de fato usa, não resolve.
- **RN-2F** (PR #61, run `40727315630`), experimento decisório de 4
  configurações, a partir do `theta0` real, submodelo `completo`:

  | Config | success | Contrato RN-2B | fun (escala original) |
  |---|---|---|---|
  | A — baseline | True | reprovado (38,99% melhoria disponível) | 0,00041823 |
  | B — jacobiano analítico isolado | True | reprovado, **PIOR que A** (59,41% melhoria disponível) | 0,00056792 |
  | C — objetivo reescalado (K=10000), jacobiano numérico | True | **aprovado** | 0,00021219 |
  | D — reescalado + jacobiano analítico | True | **aprovado** | 0,00021219 |

  A Configuração B prova que **trocar a fonte do gradiente não resolve
  (e piora)** — a causa raiz não é a precisão do cálculo do gradiente,
  é a interação entre a escala do objetivo e o critério `ftol` (seção
  4). C e D chegam ao MESMO ótimo (`fun=0,00021219`), confirmando que a
  reescala, por si só, já é suficiente — o jacobiano analítico (D) não
  traz benefício adicional sobre o numérico padrão do scipy (C).
- **RN-2G**: validação científica completa de K=10000 contra as 95
  avaliações históricas reais, usando uma réplica standalone da lógica
  de reescala (ainda não integrada ao código de produção) — resultado
  posteriormente **re-confirmado de forma independente** nesta rodada
  (RN-2H) com a implementação real integrada (seção 8).

## 3. Justificativa matemática da reescala

Para qualquer constante `K > 0`, `F(θ) = K·f(θ)` tem exatamente os
mesmos minimizadores que `f(θ)`: `∇F(θ) = K·∇f(θ)`, que se anula
exatamente nos mesmos pontos que `∇f(θ)=0`, e qualquer direção de
descida para `f` é direção de descida para `F` (mesmo sinal). **A
reescala positiva nunca move o mínimo matemático verdadeiro** — ela só
pode alterar a trajetória numérica discreta de um otimizador cujos
critérios de parada dependem da escala absoluta do valor da função
(seção 4).

## 4. Efeito da escala sobre `ftol` e `gtol`

O parâmetro `ftol` do scipy corresponde ao teste de parada do Fortran
L-BFGS-B: `(f_k - f_{k+1}) <= ftol · max(|f_k|, |f_{k+1}|, 1)`. Quando
`|f| << 1` (CRPS real desta série, ordem 1e-4 a 1e2 mm), o termo
`max(..., 1)` é dominado pela constante `1`, e o teste degenera para um
limiar **ABSOLUTO** fixo: `delta_f <= ftol` (= 1e-10 em unidades
originais), **independente de quão longe `f` está do ótimo verdadeiro**.
Esse limiar absoluto pode ser satisfeito bem antes da convergência
genuína, porque os incrementos de `f` produzidos pela busca em linha e
pela diferença finita do scipy, nessa escala pequena, podem cair abaixo
de 1e-10 sem o algoritmo ter de fato convergido — é exatamente o que a
seção 1 documentou.

Multiplicando o objetivo por `K=10000` (`F=K·f`, `|F| ~ O(1-10)` para
este CRPS), o MESMO termo `max(...,1)` passa a ser dominado por `|F|`,
tornando o teste genuinamente **relativo**: `delta_F <= ftol·|F|`.
Convertendo de volta às unidades originais (`delta_f = delta_F/K`,
`|F|=K·f`): `delta_f <= ftol·f` — ou seja, o limiar EFETIVO em unidades
originais passa a ser proporcional ao `f` atual (≈1e-10 × 4e-4 ≈ 4e-14),
cerca de **10.000× mais apertado** que o limiar absoluto fixo (1e-10) de
antes da reescala. É por isso que a reescala evita a parada prematura: o
otimizador deixa de poder parar sobre um piso de melhoria absoluta
comparativamente folgado, e passa a exigir uma melhoria relativa
genuinamente pequena antes de parar.

`gtol` é reescalado na MESMA proporção (`K·1e-6`) — não para afrouxar ou
apertar o critério de gradiente, mas para **preservar seu significado no
espaço ORIGINAL de θ**: como `∇F = K·∇f`, exigir `|∇F| < K·gtol` é
exatamente equivalente a exigir `|∇f| < gtol`. `ftol` e `maxiter`
permanecem com seus valores numéricos ORIGINAIS (1e-10 / 2000), por
instrução explícita — só o CARÁTER efetivo de `ftol` muda (absoluto →
relativo) como consequência de ele agora se aplicar a `F`, nunca a
constante em si.

## 5. Mínimo matemático vs. trajetória numérica

O mínimo MATEMÁTICO de `F=K·f` é idêntico ao de `f` (seção 3) — a
reescala nunca move o ótimo verdadeiro. O que muda é a TRAJETÓRIA
NUMÉRICA discreta do L-BFGS-B: o critério de parada por `ftol` muda de
caráter (seção 4); o passo absoluto da diferença finita do scipy no
espaço de θ (mesmo `h≈1,49e-8` nos dois casos) tem influência relativa
diferente sobre a decisão de parada, porque a escala de `f` mudou; e a
busca em linha interage com essas mesmas quantidades. A Configuração B
do RN-2F (jacobiano ANALÍTICO, SEM reescala) prova isso empiricamente:
trocar só a fonte do gradiente, mantendo a escala original, não corrigiu
o problema e piorou — confirmando que a causa raiz está na interação
entre escala do objetivo e critério de parada, nunca na precisão do
cálculo do gradiente em si.

## 6. Limitações de reprodutibilidade

A falha original é reproduzível de forma DETERMINÍSTICA no ambiente
AMD EPYC 7763/Haswell (numpy 2.4.6, scipy 1.17.1) usado pelos runners de
CI deste projeto neste período — RN-2C e RN-2D produziram `x`/`fun`/
`jac`/`success`/`status` bit-idênticos nesse ambiente. A própria
auditoria da RN-2B (`docs/enso-ci-emos-h2-auditoria-diagnostica.md`,
seção 7) já havia documentado que ESTE MESMO tipo de fixture numérico
extremo se comporta diferente em CPUs/kernels OpenBLAS diferentes
(Haswell vs. SkylakeX) — **não está confirmado que a melhoria observada
com K=10000 se mantém em todos os ambientes de CI possíveis**. É por
isso que esta rodada autoriza só UMA execução de CI, sem repetição em
busca de ambiente favorável, e por que o item de entrega inclui um plano
explícito de validação adicional em ambientes diferentes antes de
qualquer merge (ver relatório final).

## 7. Riscos residuais

**Já conhecido (RN-2B), não eliminado por esta mudança:** soluções no
limite de `gamma_c`/`d` com `success=False`/ABNORMAL continuam exigindo
o diagnóstico de fronteira benigna já aprovado — a reescala não elimina
esse regime, só desloca QUAIS avaliações específicas caem nele (ver
achado novo abaixo).

**Achado NOVO desta rodada (RN-2H), ao rodar a suíte COMPLETA do módulo,
não só os 8 testes novos:** `RegraCausalTreinoTestCase.
test_a_exemplo_literal_2003_01` — um fixture sintético perfeitamente
linear/sem ruído (mesma família de degenerescência numérica que a RN-2B
já havia corrigido em outros dois lugares deste arquivo de testes) —
falhou com a implementação reescalada: `status_emos_completo` passou de
`'ok'` (sem reescala) para `'otimizacao_nao_convergiu'` (com K=10000).
Investigação direta confirmou:

- O ponto encontrado é **numericamente equivalente**: `fun≈0,00021219`,
  idêntico ao do submodelo `d0` no MESMO processo, que converge com
  `success=True` nesse MESMO ponto (`x≈[4, 0.6, -20]`).
- O contrato já aprovado da RN-2B (`_verificar_resultado_otimizador`)
  classifica corretamente o resultado do `completo` como "ABNORMAL de
  fronteira benigna" — gradiente livre máximo ≈7,16e-6, sinal KKT
  consistente com mínimo de fronteira, assinatura `status=2`/`'ABNORMAL:
  '` exatamente a já documentada.
- **Isso é uma troca de RÓTULO do scipy, não uma solução pior.** Antes
  da reescala, esse mesmo ponto era alcançado com `success=True` e a
  mensagem de parada prematura por `ftol` (`'RELATIVE REDUCTION OF F <=
  FACTR*EPSMCH'`) — exatamente o sintoma que a reescala corrige em
  outros casos.
- **Risco de produção:** `construir_emos_h2_expanding` nunca foi
  alterado nesta rodada e seu gate STOP-ON-FAILURE depende
  EXCLUSIVAMENTE de `res.success`, nunca do contrato mais permissivo da
  RN-2B. Se esse flip (`success=True`→`False` no mesmo ponto ótimo)
  ocorrer em dado real, uma avaliação que antes era publicada
  (`STATUS_OK`) passaria a ser bloqueada (`STATUS_NAO_CONVERGIU`), apesar
  do ajuste ser numericamente equivalente.
- **Verificado explicitamente que isso NÃO ocorreu em nenhuma das 95
  avaliações históricas reais** (seção 8: `success_completo`/
  `success_d0`/`status_emos_completo`/`status_emos_d0`/`status_emos`
  batem EXATAMENTE nas 95 linhas, sem excessão). O flip só apareceu, até
  aqui, no fixture sintético perfeitamente linear/sem ruído citado acima
  — um regime que precipitação real raramente produz, mas que não pode
  ser descartado para sempre (ex.: janelas de treino muito curtas e
  homogêneas).
- **Mitigação não implementada nesta rodada** (fora do escopo mínimo
  autorizado): se esse padrão se mostrar relevante no futuro, uma opção
  a avaliar seria fazer o STOP-ON-FAILURE de produção reaproveitar o
  contrato de qualidade já aprovado da RN-2B em vez de só `res.success`
  — decisão científica separada, não tomada aqui, e que precisaria de
  aprovação e revisão própria.

**Submodelo D0 especificamente:** nos dois fixtures degenerados de teste
reaproveitados desta rodada (série B de `IndependenciaD0TestCase` e a de
`MutacaoObservacaoFuturaTestCase`), `ajustar_emos_d0` reportou
`success=False`/ABNORMAL de fronteira benigna nos DOIS, no mesmo ponto
(`x≈[4, 0.6, -20]`, `fun≈0,00021219`) — sempre aceito pelo contrato já
aprovado, nunca uma solução pior. Nas 95 avaliações reais, `success_d0`
bateu exatamente com o publicado em todas as linhas — este comportamento
também não se manifestou em dado real até aqui.

## 8. Resultado da comparação histórica (95 avaliações reais)

Reprocessamento com a implementação REAL e integrada desta branch (nunca
uma réplica standalone):

- Baseline reproduzido **exatamente**: 95/95 avaliações com
  `status_emos == 'ok'` (contagem estrutural esperada), leakage OK, zero
  falhas de convergência/sanidade na reconstrução completa (240 pares
  causais).
- Comparação linha a linha contra o CSV publicado
  (`data/cfsv2_calibracao_2c3d/emos_h2_expanding.csv`, md5
  `fe9e12b53bbb47a2004cd91173f53df8`, não alterado), usando a regra
  COMBINADA corrigida (seção de equivalência revisada desta rodada: AND
  entre diferença absoluta e relativa; `a`/`a_d0` recategorizados para o
  grupo físico-mm, pois são bias ADITIVO em
  `mu_latente = clim_obs + a + b·anom`, nunca adimensionais):
  - Todos os campos categóricos/estruturais (`success_completo`,
    `success_d0`, `status_emos_completo`, `status_emos_d0`,
    `status_emos`, datas causais, `n_treino_emos`) bateram **EXATAMENTE**
    nas 95 linhas — zero divergência.
  - **Zero violações** em todos os 21 campos numéricos comparados sob a
    regra combinada.
  - Pior diferença absoluta entre TODOS os campos físicos em mm:
    **0,0005001mm** (`a_d0`, linha 2006-10) — consistente, como ordem de
    grandeza, com a materialidade já estimada de forma independente pela
    RN-2G (réplica standalone, antes da integração real).
  - `prob_zero`: 16 linhas excedem o limiar estrito original (1e-6,
    nunca pré-registrado como critério de produção), nenhuma excede o
    limiar operacional defensável (1e-4 = 0,01 ponto percentual); pior
    diferença absoluta observada: 9,043e-6.
- Conclusão: **nenhuma mudança cientificamente relevante nem diferença
  não justificada identificada** nas 95 avaliações reais — o critério
  explícito de "interromper antes de implementar" (item 2 do pedido) não
  foi acionado para os dados reais; o achado da seção 7 (flip de rótulo
  em fixture sintético) foi tratado separadamente, como risco residual
  documentado, não como reprovação da revalidação histórica.

## 9. Plano de rollback

A mudança está isolada em exatamente 2 arquivos:

- `scripts/cfsv2_emos_h2_implementacao.py`: a constante
  `K_ESCALA_INTERNA_OTIMIZACAO`, a função `_aplicar_escala_interna`, e os
  wrappers finos `ajustar_emos_completo`/`ajustar_emos_d0` (46
  inserções, 8 remoções — as 8 remoções são só a substituição dos dois
  corpos de função originais pelas 2 linhas de delegação ao helper).
- `tests/test_cfsv2_emos_h2_implementacao.py`: 2 ajustes mínimos em
  testes pré-existentes (um `Mock` incompleto e duas checagens de
  identidade que dependiam do objetivo não ser envolvido por um fecho),
  1 fixture sintética corrigida (ruído determinístico, mesmo padrão já
  usado pela RN-2B, por ser incidentalmente degenerada — seção 7), e a
  nova classe `EscalaInternaOtimizacaoTestCase` (8 testes).

Nenhuma outra função (`_objetivo_completo`, `_objetivo_d0`,
`crps_normal_censurada`, `theta0`, `bounds`, regras de seleção
científica, workflows) foi tocada. Nenhum dado histórico ou relatório de
produção foi gerado ou alterado nesta rodada. Reverter é um `git revert`
de ponta a ponta do(s) commit(s) desta branch/PR — sem dependência
cruzada com PR #59 ou PR #61, ambas intocadas e independentes desta
mudança.
