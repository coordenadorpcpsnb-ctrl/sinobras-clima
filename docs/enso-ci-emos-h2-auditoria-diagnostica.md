# ENSO-CI — Auditoria da investigação diagnóstica EMOS H2 (PR #57)

**Documento de encerramento da investigação exploratória.** Preserva os
procedimentos e resultados dos Jobs D/E/F (temporários) antes de sua
remoção de `.github/workflows/ci.yml`. **Não é uma conclusão científica**
— a resolução da instabilidade numérica é proposta como fase
independente em `docs/enso-ci-emos-h2-proposta-robustez-numerica.md`.
Nenhuma linha de `scripts/cfsv2_emos_h2_implementacao.py` ou
`tests/test_cfsv2_emos_h2_implementacao.py` foi alterada em nenhum
momento desta investigação.

## 1. Objetivo original da Fase ENSO-CI

Implementar o primeiro gatilho `pull_request` do projeto — até então
`update.yml`/`indices_semanal.yml` só rodavam agendados ou por
`workflow_dispatch`, sem validação automática de PRs antes do merge.
`.github/workflows/ci.yml` com 3 jobs independentes (A — testes
unitários, B — integridade do dashboard, C — regressão científica
completa), `permissions: contents: read`, concorrência própria. Ver
corpo da PR #57 para a especificação completa dessa fase original.

## 2. Histórico das seis execuções reais do CI nesta PR

| # | Run ID | Commit | A | B | C | D | E | F |
|---|---|---|---|---|---|---|---|---|
| 1 | 39441666419 | (pré-Jobs D/E) | PASS | PASS | **FAIL** (EMOS H2) | — | — | — |
| 2 | 39468643882 | (pré-Jobs D/E) | PASS | PASS | **FAIL** (EMOS H2) | — | — | — |
| 3 | 39486432148 | `1430304` | PASS | PASS | PASS | não registrado em detalhe suficiente nesta investigação | **FAIL** (bug de infraestrutura: `requirements-c3s.txt` faltante, falhou em 48s antes de qualquer teste real) | — |
| 4 | 39595727397 | `66db355` | PASS | PASS | PASS (AMD EPYC 9V45) | **FAIL** (AMD EPYC 7763) | **FAIL** (AMD EPYC 7763) | — |
| 5 | 39605920724 | `6f704a7` | PASS | PASS | PASS (AMD EPYC 9V45) | PASS (Intel Xeon Platinum 8573C) | **FAIL** (AMD EPYC 9V74) + 1 falha extra identificada (ver seção 4) | — |
| 6 | 39632348555 | `559af9b` | PASS | PASS | PASS (Intel Xeon Platinum 8370C) | **FAIL** (AMD EPYC 7763) | **FAIL** (AMD EPYC 7763); suíte ampla 1613/1613 sem falha extra (fix confirmado) | PASS/PASS (Intel Xeon 6973P-C, Haswell e SkylakeX forçados) |

**Job C: duas execuções iniciais com falha (runs 1-2) e quatro
execuções posteriores aprovadas (runs 3-6), depois das correções de
dependências e checkout abaixo.** Isso é evidência de melhora, **não**
prova de estabilidade — 4 execuções consecutivas não é amostra
suficiente para declarar o job estável, e a causa raiz da intermitência
nunca foi eliminada, só não se manifestou nessas 4 execuções
específicas.

## 3. Correção das dependências C3S/NMME

Achado real: a suíte completa do Job C nunca tinha rodado antes num
runner limpo. `requirements.txt` não declarava `xarray`/`PyYAML`,
usados por vários módulos `test_c3s*`/`test_nmme_*` no nível de
import — Job C falhava por `ModuleNotFoundError` antes de chegar a
qualquer teste real. Corrigido reaproveitando `requirements-c3s.txt`
(arquivo pré-existente, usado por `c3s_poc.yml`/`nmme_poc.yml`) no
install do Job C (commit `41ad8a7`), sem duplicar declaração em
`requirements.txt` — os 5 workflows operacionais não precisam dele.

Mesmo bug, instância separada: Job E (diagnóstico amplo) só instalava
`requirements.txt`, não `requirements-c3s.txt` — falhou em 48s no run
#3 antes de rodar qualquer teste EMOS H2. Corrigido no commit `66db355`.

## 4. Correção do checkout completo (fetch-depth)

Achado real (sincronização com `main`, antes da abertura da PR):
`actions/checkout@v4.2.2` sem `fetch-depth: 0` produz clone raso
(depth=1) — `git log --follow --diff-filter=A` trata o commit único
"enxertado" como se tivesse criado todos os arquivos, dado sem
sentido que passa silenciosamente. Corrigido nos Jobs B/C com
`fetch-depth: 0`, **e** defesa em profundidade na própria função
(`verificar_dados_1996_2010_precedem_pipeline_atual`, que agora checa
`git rev-parse --is-shallow-repository` e se recusa a operar sob clone
raso).

**Achado real, run #5**: Jobs D/E não tinham recebido o mesmo
`fetch-depth: 0` (foram adicionados depois da correção acima) — a
suíte ampla do Job E rodava
`tests.test_nmme_auditoria_observacional_historica`, cujo
`test_a_dados_reais_primeiro_commit_ja_completo` exige histórico
completo; sob checkout raso, a guarda contra repositório raso reportava
corretamente `verificavel=False`, e o teste falhava com
`AssertionError: False is not true` — **sem relação com EMOS H2**,
identificado nominalmente pela instrumentação `_TestResultDetalhado`
(ver seção 6). Corrigido no commit `559af9b`; confirmado funcionando no
run #6 (suíte ampla do Job E: 1613/1613, 0 falhas).

## 5. Resultados dos Jobs A, B e C

Jobs A e B: PASS em todas as execuções registradas, nenhuma falha
relatada em nenhum momento desta investigação.

Job C: ver tabela da seção 2. Nas 4 execuções aprovadas (runs 3-6), a
suíte completa (39 módulos, 1659 testes no total, incluindo
`test_cfsv2_emos_h2_implementacao`) rodou com 0 falhas. CPU observada
variou (AMD EPYC 9V45 nos runs 4-5, Intel Xeon Platinum 8370C/8573C
nos runs 5-6) — Job C nunca falhou numa execução em que a
instrumentação de ambiente já estava presente para registrar
CPU/kernel.

## 6. Resultados diagnósticos dos Jobs D, E e F

**Job D** (`tests.test_diagnostico_emos_h2_ci.DiagnosticoCenariosTestCase`,
timeout 15min): roda os 2 testes-alvo isolados, em sequência, e depois
do módulo real completo — 4 cenários. Run #4: todos os 4 FAIL (AMD EPYC
7763). Run #5: todos os 4 PASS (Intel Xeon Platinum 8573C). Run #6:
todos os 4 FAIL (AMD EPYC 7763, valores numéricos idênticos ao run #4).

**Job E** (`DiagnosticoCenario5TestCase`, timeout 45min): roda a mesma
lista ampla de módulos do Job C (sem `test_cfsv2_emos_h2_implementacao`,
rodado separadamente) e então os 2 testes-alvo. Run #4: FAIL (AMD EPYC
7763). Run #5: FAIL (AMD EPYC 9V74) + 1 falha extra (seção 4). Run #6:
FAIL (AMD EPYC 7763, valores numéricos idênticos aos runs #4/5), suíte
ampla sem falha extra (fix confirmado).

**Job F** (`scripts/experimento_kernel_openblas_emos_h2.py`, timeout
10min, só existiu no run #6): experimento controlado — mesma CPU, dois
processos novos sequenciais, `OPENBLAS_CORETYPE` forçado
(`HASWELL`/`SKYLAKEX`) e confirmado via `threadpoolctl.threadpool_info()`
antes de rodar os testes reais. Run #6: PASS nos dois kernels, na CPU
alocada (Intel Xeon 6973P-C). Classificação explícita
PASS/FAIL/INCONCLUSIVO, com `sys.exit(1)` se qualquer kernel reprovar
de verdade — nunca mascarado.

Toda a instrumentação (`_TestResultDetalhado`, `_backend_blas_efetivo`,
captura de `jac` por componente) foi validada com testes sintéticos
antes de ser usada sobre o EMOS H2 real — nunca alterou nenhum
resultado científico (demonstrado bit-a-bit em
`BackendBlasEfetivoTestCase.test_b_aquecimento_nao_altera_resultado_do_otimizador_real`).

## 7. Matriz CPU × kernel OpenBLAS × PASS/FAIL (consolidada)

| CPU | Kernel confirmado | Resultado | Execuções |
|---|---|---|---|
| AMD EPYC 7763 | Haswell (automático) | **FAIL** | runs 4 (D,E), 6 (D,E) |
| AMD EPYC 9V74 | Haswell (automático) | **FAIL** | run 5 (E) |
| AMD EPYC 9V45 | SkylakeX (automático) | PASS | runs 4 (C), 5 (C) |
| Intel Xeon Platinum 8573C | SkylakeX (automático) | PASS | run 5 (D) |
| Intel Xeon Platinum 8370C | SkylakeX (automático) | PASS | run 6 (C) |
| Intel Xeon 6973P-C | Haswell (**forçado**) | PASS | run 6 (F) |
| Intel Xeon 6973P-C | SkylakeX (**forçado**) | PASS | run 6 (F) |

Todas as leituras: numpy 2.4.6, scipy 1.17.1, OpenBLAS 0.3.31.188.0,
`threading_layer=pthreads`, `num_threads=4`.

## 8. Resultados numéricos relevantes do L-BFGS-B

A chamada decisiva, reproduzida **identicamente** (até várias casas
decimais) em todas as execuções AMD+Haswell observadas:
```
success=False status=2 message='ABNORMAL: ' nit=38 nfev=316
fun_inicial=8.379397819039323 fun_final=0.00021219482301305947
jac=[2.393306108216331e-05, 0.001515917621979863, 0.00010609730260496464]
x_final=[≈4.0000012, ≈0.6, -20.0]  (gamma_c exatamente no limite inferior)
```
Comparada à chamada imediatamente vizinha na mesma sequência, que
converge (`success=True status=0`) para um `fun_final` quase idêntico
(diferença ~1,3e-11) — a qualidade da solução em si é virtualmente a
mesma; só o flag `status` do scipy diverge.

## 9. Evidências sobre soluções no limite de gamma_c

Levantamento de 72 chamadas reais (run #4, Job D): 49 convergentes com
`gamma_c` no limite inferior exato, 9 não convergentes com `gamma_c`
no limite, 3 não convergentes **fora** do limite. **Conclusão
corrigida (revisão externa)**: a fronteira não é condição necessária
nem suficiente para a não convergência — 84,7% das soluções no limite
convergem normalmente, e existem não convergências sem estar no
limite.

O componente do gradiente em `gamma_c` (`jac[2]`) é positivo e
praticamente idêntico (~0,0001061) em toda chamada com `gamma_c` no
limite — convergente ou não — consistente com a condição de KKT para
um mínimo com limite inferior ativo, satisfeita igualmente nos dois
casos.

## 10. Limitações da análise de KKT e dos critérios de sanidade

- O gradiente dos componentes livres (`a_d0`, `b_d0`) **não discrimina**
  convergência: a chamada decisiva FAIL tem `jac[1]=0,0015`, menor em
  módulo que várias chamadas PASS (ex.: `jac[1]=-0,0888` numa chamada
  convergente) — descarta a hipótese "gradiente grande causa falha".
- A única chamada genuinamente mal otimizada observada (`fun_final`
  97,5× pior que o cluster bom) tem gradiente 2-3 ordens de magnitude
  maior (`jac[0]=0,67`, `jac[1]=18,9`) — essa é a assinatura real de
  não convergência, ausente na chamada decisiva FAIL.
- **Achado crítico sobre `_sanidade_d0`/`_sanidade_completo`**: chamando
  essas funções reais (não reimplementadas) com os dados capturados da
  chamada ABNORMAL decisiva, `_sanidade_d0` retorna `True` — a solução
  passaria em todos os 6 critérios de sanidade se chegasse a ser
  avaliada. **Mas a mesma função também retorna `True` para a chamada
  genuinamente mal otimizada** (`fun` 97,5× pior) — ou seja, `_sanidade_*`
  isolado **não distingue** fronteira benigna de otimização ruim. Um
  bypass do gate `success` baseado só em sanidade seria cientificamente
  inseguro (seção 13).
- O teste de KKT aqui feito é parcial: usa o `jac` bruto (gradiente não
  projetado) retornado pelo scipy, não o gradiente projetado interno
  que o próprio L-BFGS-B usa para seu critério de parada (`PGTOL`) —
  essa quantidade interna não é exposta pela API do scipy.

## 11. Evidências favoráveis e contrárias à hipótese de interação CPU × kernel

**Favoráveis**: 3/3 observações AMD+Haswell falharam; 2/2 AMD+SkylakeX
passaram; 4/4 Intel (qualquer kernel, forçado ou automático) passaram
— padrão de interação específica, não efeito isolado de CPU ou kernel.

**Contrárias / não resolvidas**: o único experimento controlado
(mesma máquina, kernel forçado — Job F) rodou em CPU Intel nas duas
tentativas de kernel, por sorte do alocador do runner, e nunca
reproduziu a falha em nenhum kernel nessa máquina. **Nunca houve um
Job F executado numa máquina AMD** — toda evidência "AMD falha" vem de
execuções não controladas (DYNAMIC_ARCH automático em jobs diferentes),
não do experimento isolado que testaria kernel como única variável
numa AMD real.

## 12. Hipóteses não comprovadas

- Que o mecanismo exato seja uma diferença de arredondamento ponto
  flutuante entre implementações AMD/Intel do mesmo kernel nominal
  "Haswell" (plausível, não testado diretamente).
- Que forçar SkylakeX numa máquina AMD eliminaria a falha (nunca
  testado — Job F nunca rodou em AMD).
- Que o padrão se mantém com amostra maior — todas as observações
  somam 5 combinações CPU×kernel reais, número pequeno para uma
  afirmação estatística forte.
- Qual exatamente é a falha adicional identificada no run #5 antes da
  correção do checkout teria uma causa diferente se investigada a
  fundo (foi aceita como explicada pela causa raiz óbvia — checkout
  raso — sem exploração de hipóteses alternativas).

## 13. Riscos de alterar o gate `OptimizeResult.success`

Qualquer modificação do gate atual (`if not res.success: STATUS_NAO_CONVERGIU`)
em produção **não foi implementada nem proposta como pronta** nesta
investigação. Risco demonstrado concretamente (seção 10): usar só
`_sanidade_*` como critério alternativo aceitaria também soluções
genuinamente mal otimizadas, não só as de fronteira benigna — seria
uma regressão científica, não uma correção. Qualquer fix real
precisaria de um critério adicional (ex.: comparação de magnitude do
gradiente livre, ou um segundo ajuste com Jacobiana analítica) e
validação completa contra as 95 avaliações históricas reais, não só
contra os 2 testes sintéticos — fora do escopo desta PR.

## 14. Recomendação

Encerrar esta investigação exploratória nesta PR, sem afirmar causa
raiz definitivamente identificada. A resolução científica proposta
como fase independente — ver
`docs/enso-ci-emos-h2-proposta-robustez-numerica.md`.
