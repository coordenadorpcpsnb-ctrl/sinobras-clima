# Proposta — Fase futura de robustez numérica do EMOS H2

**Proposta, não implementação.** Nenhuma alteração científica foi
feita a partir deste documento. Baseado inteiramente nas evidências
reunidas em `docs/enso-ci-emos-h2-auditoria-diagnostica.md` (Fase
ENSO-CI, PR #57). Qualquer execução das atividades abaixo é uma fase
separada, com sua própria autorização e revisão.

## 1. Problema de reprodutibilidade observado

Dois testes de `tests/test_cfsv2_emos_h2_implementacao.py`
(`IndependenciaD0TestCase.test_d_sigma_d0_identico_ao_variar_ensemble_std_das_linhas_de_treino`
e
`MutacaoObservacaoFuturaTestCase.test_a_mutar_observacao_da_linha_imediatamente_anterior_nao_afeta_avaliacao_mais_recente`)
falham intermitentemente no runner real do GitHub Actions — nunca
localmente, mesmo casando versões exatas de numpy/scipy — por causa de
`scipy.optimize.minimize` (L-BFGS-B) retornar `success=False status=2
message='ABNORMAL: '` para uma solução cujo valor objetivo é quase
idêntico a uma solução vizinha que converge normalmente.

## 2. Condições de reprodução conhecidas

- Observado em CPUs AMD EPYC (7763, 9V74) quando o OpenBLAS seleciona o
  kernel "Haswell" (via `DYNAMIC_ARCH`, automático).
- Nunca observado em CPUs Intel Xeon testadas, com nenhum kernel
  (SkylakeX automático, Haswell forçado, SkylakeX forçado).
- Nunca observado em CPU AMD com kernel SkylakeX (automático, EPYC
  9V45).
- **Nunca testado**: kernel forçado numa máquina AMD real — essa é a
  lacuna experimental mais importante para fechar antes de qualquer
  outra etapa.

## 3. Fixtures envolvidos

Ambos os testes usam séries sintéticas determinísticas de 125 linhas
(`_pares`, climatologia/anomalia/erro fixos, variando só
`ensemble_std`/observação mutada) — por desenho, levam `gamma_c` ao
limite inferior exato (`GAMMA_C_LO = -20.0`) na avaliação final. Não
reaproveitar fixtures: qualquer teste novo chama
`ajustar_emos_d0`/`ajustar_emos_completo` reais com os MESMOS dados,
nunca reimplementados.

## 4. Avaliação de gradiente projetado e KKT

A API pública do scipy não expõe o gradiente projetado interno que o
L-BFGS-B usa para seu critério de parada (`PGTOL`) — só o gradiente
bruto (`res.jac`). Proposta: instrumentar via `options={'iprint': ...}`
ou um wrapper de mais baixo nível (`scipy.optimize._lbfgsb_py`) para
capturar o estado interno do Fortran (`task`, `wa`, gradiente
projetado real) nas iterações finais — maior invasividade que a
instrumentação já feita nesta PR, por isso proposta para fase própria,
nunca dentro de CI.

## 5. Comparação entre soluções aceitas/rejeitadas

Já reunido na auditoria (seção 10): o gradiente livre não discrimina
(chamada FAIL tem gradiente menor que chamadas PASS); a assinatura real
de má otimização é 2-3 ordens de magnitude maior em todos os
componentes livres. Próximo passo: repetir essa comparação com uma
amostra maior de chamadas ABNORMAL reais (exigiria mais execuções
reais no runner — não disponível localmente).

## 6. Avaliação de métodos de otimização alternativos (só em ambiente experimental)

Candidatos a avaliar, **nunca em produção sem validação completa**:
- `method='Powell'` ou `'Nelder-Mead'` (sem gradiente, imunes a esse
  modo de falha específico, mas mais lentos).
- Jacobiana analítica fornecida a `minimize` (elimina a diferença
  finita que introduz o ruído de ponto flutuante na origem da
  instabilidade) — candidato mais promissor, exige derivar
  analiticamente o CRPS censurado.
- Reinício automático com `x0` perturbado quando `status=2` — risco de
  mascarar não convergência real (ver seção 7 da auditoria, achado
  sobre `_sanidade_*`).

## 7. Protocolo de validação científica em backtests históricos

Qualquer mudança ao otimizador ou ao gate `success` precisa, antes de
ir a produção:
1. Reprocessar as 95 avaliações históricas reais (não só os 2 testes
   sintéticos) com a mudança proposta.
2. Comparar `status_emos`/`status_emos_d0`, `a`/`b`/`gamma_c`/`d`,
   `crps_emos`/`crps_d0` linha a linha contra os valores já publicados
   em `docs/nmme-fase2c3d-emos-h2-resultados.md`.
3. Qualquer linha cujo resultado mude precisa de justificativa
   individual — nunca aceitar "a métrica agregada não mudou" como
   suficiente, por causa do histórico de `armadilha` deste projeto
   (nunca aceitar métrica agregada escondendo mudança de linha
   individual).

## 8. Critérios de aceitação que não dependam só de uma execução favorável do CI

Mínimo proposto antes de qualquer merge que toque o otimizador real:
- Rodar a suíte completa (não só os 2 testes-alvo) pelo menos 3 vezes
  em runners reais, idealmente forçando kernel/CPU diferentes
  (reaproveitando `scripts/experimento_kernel_openblas_emos_h2.py` ou
  equivalente) — nunca aceitar 1 execução verde como prova.
- Backtest completo (seção 7) sem diferença não justificada.
- Revisão explícita do risco científico de qualquer novo critério de
  aceitação (nunca só "'ABNORMAL' deixou de aparecer").
