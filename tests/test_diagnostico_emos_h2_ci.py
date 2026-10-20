#!/usr/bin/env python3
"""
tests/test_diagnostico_emos_h2_ci.py — Fase ENSO-CI, diagnóstico
instrumentado das duas falhas reproduzidas 2 de 2 vezes no runner real
do GitHub Actions (nunca localmente, mesmo casando versões exatas de
NumPy/SciPy e variando thread count/kernel de BLAS) em:

  - tests.test_cfsv2_emos_h2_implementacao.IndependenciaD0TestCase.
    test_d_sigma_d0_identico_ao_variar_ensemble_std_das_linhas_de_treino
  - tests.test_cfsv2_emos_h2_implementacao.MutacaoObservacaoFuturaTestCase.
    test_a_mutar_observacao_da_linha_imediatamente_anterior_nao_afeta_avaliacao_mais_recente

NÃO duplica nenhum fixture: carrega e executa os MÉTODOS DE TESTE
ORIGINAIS, inalterados, via `unittest.TestLoader`/`unittest.TestResult`
— a única instrumentação é um monkeypatch TEMPORÁRIO (sempre restaurado,
inclusive se algo lançar) de `cfsv2_emos_h2_implementacao.minimize`, que
encaminha os argumentos ao `scipy.optimize.minimize` real SEM alterar
nada e devolve exatamente o `OptimizeResult` que ele produziu — só
grava uma cópia dos campos relevantes num registro lateral, nunca
intercepta ou modifica o valor usado pelo código de produção.

`scripts/cfsv2_emos_h2_implementacao.py` e
`tests/test_cfsv2_emos_h2_implementacao.py` nunca são tocados por este
arquivo. Cada test_cenario_* RODA o teste original via TestResult
(que absorve a AssertionError dele, nunca deixa propagar como
exceção Python — por isso todos os cenários sempre executam, mesmo
que um reproduza a falha real) e em seguida faz
`self.assertTrue(passou, ...)`: se o teste original falhou, o próprio
método de diagnóstico que o invocou também é marcado FAIL pelo
unittest — uma falha científica real NUNCA é reportada como "OK" só
porque o diagnóstico conseguiu observá-la (ver
MecanismoDeteccaoFalhaTestCase, que prova essa propagação com uma
falha sintética antes de qualquer cenário real rodar).

Roda com:
    python -m unittest tests.test_diagnostico_emos_h2_ci -v

Não há necessidade de `continue-on-error` nem `|| true` em lugar
nenhum: a ordem de execução dentro de UM processo Python (requerida
pelos cenários "depois de outros testes") já é garantida pela ordem
com que os módulos aparecem na linha de comando do
`python -m unittest`, e cada cenário é um método de teste à parte —
unittest roda TODOS os métodos de uma TestCase mesmo que outro tenha
falhado (isso nunca interrompe a sequência), só o exit code final do
processo acumula as falhas reais, de forma transparente.
"""

import importlib
import platform
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import cfsv2_emos_h2_implementacao as emos  # noqa: E402

_MINIMIZE_ORIGINAL = emos.minimize


def _restaurar_minimize_original():
    """Restaura emos.minimize ao valor original — registrada via
    addClassCleanup (não tearDownClass): roda garantidamente mesmo se
    algo em setUpClass, depois desta chamada, lançar uma exceção
    (item 3 da revisão externa). Idempotente: pode ser chamada mais de
    uma vez sem efeito colateral."""
    emos.minimize = _MINIMIZE_ORIGINAL
_REGISTROS = []
_RELATORIO_CENARIOS = []

_TESTE_1 = ('IndependenciaD0TestCase',
            'test_d_sigma_d0_identico_ao_variar_ensemble_std_das_linhas_de_treino')
_TESTE_2 = ('MutacaoObservacaoFuturaTestCase',
            'test_a_mutar_observacao_da_linha_imediatamente_anterior_nao_afeta_avaliacao_mais_recente')


def _minimize_instrumentado(fun, x0, args=(), method=None, bounds=None, options=None, **kwargs):
    """Encaminha para o scipy.optimize.minimize REAL sem alterar
    nenhum argumento, e devolve exatamente o OptimizeResult recebido
    — só grava uma cópia dos campos relevantes. Nunca intercepta,
    nunca modifica o valor usado pelo código de produção (confirmado
    por EquivalenciaDoWrapperTestCase abaixo)."""
    res = _MINIMIZE_ORIGINAL(fun, x0, args=args, method=method, bounds=bounds, options=options, **kwargs)
    try:
        x_final = [float(val) for val in res.x]
    except Exception:
        x_final = None
    jac = getattr(res, 'jac', None)
    jac_list = [float(val) for val in jac] if jac is not None else None
    dist_bounds = None
    if bounds is not None and x_final is not None:
        dist_bounds = []
        for xi, b in zip(x_final, bounds):
            lo, hi = b if b is not None else (None, None)
            dist_bounds.append({
                'valor': xi,
                'dist_para_lo': None if lo is None else xi - lo,
                'dist_para_hi': None if hi is None else hi - xi,
            })
    try:
        fun_x0 = float(fun(np.asarray(x0, dtype=float), *args))
    except Exception:
        fun_x0 = None
    _REGISTROS.append({
        'success': bool(res.success),
        'status': int(res.status) if getattr(res, 'status', None) is not None else None,
        'message': str(getattr(res, 'message', '')),
        'nit': int(res.nit) if hasattr(res, 'nit') else None,
        'nfev': int(res.nfev) if hasattr(res, 'nfev') else None,
        'fun_inicial': fun_x0,
        'fun_final': float(res.fun) if res.fun is not None else None,
        'x0': [float(val) for val in x0],
        'x_final': x_final,
        'jac': jac_list,
        'norma_gradiente': float(np.linalg.norm(jac)) if jac_list is not None else None,
        'dist_bounds': dist_bounds,
        'bounds': bounds,
        'method': method,
        'options': options,
        'finito_x': bool(np.all(np.isfinite(res.x))) if x_final is not None else None,
        'finito_fun': bool(np.isfinite(res.fun)) if res.fun is not None else None,
    })
    return res


def _info_ambiente():
    import os
    import scipy
    info = {
        'python': sys.version.split()[0],
        'platform': platform.platform(),
        'processor': platform.processor(),
        'numpy': np.__version__,
        'scipy': scipy.__version__,
    }
    for var in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'OPENBLAS_CORETYPE'):
        info[var] = os.environ.get(var)
    try:
        with open('/proc/cpuinfo') as f:
            for linha in f:
                if linha.startswith('model name'):
                    info['cpu_model'] = linha.split(':', 1)[1].strip()
                    break
    except OSError:
        info['cpu_model'] = None
    return info


def _rodar_metodo_original(classe_nome, metodo_nome):
    """Carrega e roda o MÉTODO DE TESTE ORIGINAL (sem cópia, sem
    modificação de nenhuma linha) via unittest.TestLoader — reutiliza
    o fixture e a lógica reais inteiros, nunca reimplementados aqui.
    emos.minimize já precisa estar instrumentado ANTES desta chamada
    (feito em setUpClass das TestCases abaixo). Retorna
    (passou: bool, mensagem: str, chamadas_capturadas_neste_metodo: list)."""
    inicio = len(_REGISTROS)
    modulo = importlib.import_module('tests.test_cfsv2_emos_h2_implementacao')
    classe = getattr(modulo, classe_nome)
    suite = unittest.TestLoader().loadTestsFromName(metodo_nome, classe)
    resultado = unittest.TestResult()
    suite.run(resultado)
    passou = resultado.wasSuccessful()
    partes_msg = [tb for _, tb in (resultado.failures + resultado.errors)]
    mensagem = '\n'.join(partes_msg) if partes_msg else 'OK — status_emos(/d0) == STATUS_OK, sem exceção'
    return passou, mensagem, _REGISTROS[inicio:]


def _rodar_modulo_inteiro(nome_modulo_dotted):
    """Roda TODOS os testes de um módulo via TestLoader/TestResult,
    absorvendo falhas sem lançar (TestResult nunca propaga
    AssertionError) — usado só para fazer o módulo "já ter rodado
    antes" no mesmo processo, nos cenários 4/5. Não é o resultado
    desses testes que importa aqui, é o estado de processo que eles
    deixam atrás."""
    modulo = importlib.import_module(nome_modulo_dotted)
    suite = unittest.TestLoader().loadTestsFromModule(modulo)
    resultado = unittest.TestResult()
    suite.run(resultado)
    return resultado.testsRun, len(resultado.failures) + len(resultado.errors)


def _registrar_cenario(nome, passou, mensagem, chamadas):
    _RELATORIO_CENARIOS.append({
        'cenario': nome,
        'passou': passou,
        'mensagem': mensagem,
        'n_chamadas_minimize': len(chamadas),
        'chamadas': chamadas,
    })
    print(f'\n--- {nome}: {"PASS" if passou else "FAIL"} ---')
    print(mensagem[:2000])
    for i, c in enumerate(chamadas):
        print(f'  chamada minimize #{i}: success={c["success"]} status={c["status"]} '
              f'message={c["message"]!r} nit={c["nit"]} nfev={c["nfev"]} '
              f'fun_inicial={c["fun_inicial"]} fun_final={c["fun_final"]} '
              f'finito_x={c["finito_x"]} finito_fun={c["finito_fun"]} '
              f'norma_gradiente={c["norma_gradiente"]}')
        if c['dist_bounds']:
            print(f'    dist_bounds={c["dist_bounds"]}')


def _imprimir_resumo_final():
    import json
    print('\n' + '=' * 70)
    print('RESUMO FINAL — diagnóstico instrumentado EMOS H2 (Fase ENSO-CI)')
    print('=' * 70)
    print(json.dumps(_info_ambiente(), indent=2, ensure_ascii=False))
    print('-' * 70)
    print(f'{"cenário":<55} {"resultado":<6} {"#chamadas minimize"}')
    for c in _RELATORIO_CENARIOS:
        print(f'{c["cenario"]:<55} {"PASS" if c["passou"] else "FAIL":<6} {c["n_chamadas_minimize"]}')
    print('=' * 70)


class EquivalenciaDoWrapperTestCase(unittest.TestCase):
    """Prova, antes de qualquer cenário, que o wrapper instrumentado
    devolve EXATAMENTE o mesmo resultado que o scipy.optimize.minimize
    real, para a mesma entrada determinística — a instrumentação não
    pode, por construção, alterar nenhum resultado científico."""

    def test_a_wrapper_e_identico_ao_minimize_real_para_entrada_fixa(self):
        theta0 = np.array([0.0, 1.0, 0.0, 0.1])
        bounds = emos.BOUNDS_COMPLETO
        clim_obs = np.full(10, 70.0)
        anom = np.linspace(-5, 5, 10)
        erro_sd = np.full(10, 20.0)
        spread_rel = np.full(10, 1.0)
        y = 70.0 + 0.5 * anom
        args = (clim_obs, anom, erro_sd, spread_rel, y)

        res_real = _MINIMIZE_ORIGINAL(
            emos._objetivo_completo, theta0, args=args,
            method='L-BFGS-B', bounds=bounds, options=emos.OPCOES_OTIMIZADOR)
        res_wrapper = _minimize_instrumentado(
            emos._objetivo_completo, theta0, args=args,
            method='L-BFGS-B', bounds=bounds, options=emos.OPCOES_OTIMIZADOR)

        self.assertEqual(res_real.success, res_wrapper.success)
        self.assertEqual(res_real.status, res_wrapper.status)
        self.assertEqual(res_real.message, res_wrapper.message)
        self.assertEqual(res_real.nit, res_wrapper.nit)
        self.assertEqual(res_real.nfev, res_wrapper.nfev)
        np.testing.assert_array_equal(res_real.x, res_wrapper.x)
        self.assertEqual(res_real.fun, res_wrapper.fun)


class MecanismoDeteccaoFalhaTestCase(unittest.TestCase):
    """Prova, com uma falha deliberada e sintética (não o EMOS H2),
    que o mecanismo usado por _rodar_metodo_original REALMENTE marca
    FAIL quando o teste original falha — nunca reporta PASS só porque
    o diagnóstico conseguiu capturar/observar a falha sem lançar.
    Item 2 da revisão externa: uma falha científica real nunca pode
    ser classificada como teste aprovado."""

    def test_a_teste_original_que_falha_e_reportado_como_fail(self):
        class _FalhaDeliberadaTestCase(unittest.TestCase):
            def test_isso_sempre_falha(self):
                self.fail('falha sintética, só para provar a propagação')

        suite = unittest.TestLoader().loadTestsFromName(
            'test_isso_sempre_falha', _FalhaDeliberadaTestCase)
        resultado = unittest.TestResult()
        suite.run(resultado)
        self.assertFalse(
            resultado.wasSuccessful(),
            'uma falha sintética DEVE ser detectada como falha pelo TestResult — '
            'se isso não for verdade, o mecanismo de diagnóstico poderia mascarar '
            'uma falha científica real como aprovada')
        self.assertEqual(len(resultado.failures), 1)

    def test_b_teste_original_que_passa_e_reportado_como_pass(self):
        class _SucessoDeliberadoTestCase(unittest.TestCase):
            def test_isso_sempre_passa(self):
                self.assertTrue(True)

        suite = unittest.TestLoader().loadTestsFromName(
            'test_isso_sempre_passa', _SucessoDeliberadoTestCase)
        resultado = unittest.TestResult()
        suite.run(resultado)
        self.assertTrue(resultado.wasSuccessful())


class DiagnosticoCenariosTestCase(unittest.TestCase):
    """Cada test_cenario_* roda o MÉTODO DE TESTE ORIGINAL (via
    _rodar_metodo_original, que usa unittest.TestResult — nunca deixa
    uma AssertionError do teste original se propagar como exceção
    Python) e IMPRIME PASS/FAIL + dados do otimizador — mas também faz
    `self.assertTrue(passou, ...)` ao final: se o teste original
    falhar (reproduzindo a falha real do EMOS H2), ESTE método de
    diagnóstico também é marcado FAIL pelo próprio unittest, nunca
    reportado como OK só porque conseguiu observar a falha (item 2 da
    revisão externa — ver também MecanismoDeteccaoFalhaTestCase, que
    prova a propagação com uma falha sintética). Isso não impede os
    demais cenários de rodar: cada método de teste nesta classe é
    independente — unittest sempre roda todos, mesmo que um falhe."""

    @classmethod
    def setUpClass(cls):
        emos.minimize = _minimize_instrumentado
        # addClassCleanup (não tearDownClass): garantido rodar mesmo
        # que uma linha POSTERIOR de setUpClass lance uma exceção —
        # a restauração é registrada no mesmo instante em que o patch
        # é aplicado, antes de qualquer outra coisa poder falhar.
        cls.addClassCleanup(_restaurar_minimize_original)
        cls.addClassCleanup(_imprimir_resumo_final)

    def test_cenario_1_isolado_independencia_d0(self):
        passou, msg, chamadas = _rodar_metodo_original(*_TESTE_1)
        _registrar_cenario('Cenário 1 — isolado (IndependenciaD0)', passou, msg, chamadas)
        self.assertTrue(passou, msg=f'teste original falhou:\n{msg}')

    def test_cenario_2_isolado_mutacao_observacao_futura(self):
        passou, msg, chamadas = _rodar_metodo_original(*_TESTE_2)
        _registrar_cenario('Cenário 2 — isolado (MutacaoObservacaoFutura)', passou, msg, chamadas)
        self.assertTrue(passou, msg=f'teste original falhou:\n{msg}')

    def test_cenario_3_ambos_em_sequencia_direta_mesmo_processo(self):
        passou1, msg1, c1 = _rodar_metodo_original(*_TESTE_1)
        _registrar_cenario('Cenário 3a — ambos em sequência (IndependenciaD0)', passou1, msg1, c1)
        passou2, msg2, c2 = _rodar_metodo_original(*_TESTE_2)
        _registrar_cenario('Cenário 3b — ambos em sequência (MutacaoObservacaoFutura)', passou2, msg2, c2)
        self.assertTrue(passou1 and passou2,
                         msg=f'teste original falhou — 1:{passou1} 2:{passou2}\n{msg1}\n{msg2}')

    def test_cenario_4_depois_do_modulo_real_completo(self):
        n_testes, n_falhas = _rodar_modulo_inteiro('tests.test_cfsv2_emos_h2_implementacao')
        print(f'\n[Cenário 4] módulo real completo rodou {n_testes} testes, '
              f'{n_falhas} falha(s)/erro(s) — estado de processo resultante usado a seguir')
        passou1, msg1, c1 = _rodar_metodo_original(*_TESTE_1)
        _registrar_cenario('Cenário 4a — depois do módulo completo (IndependenciaD0)', passou1, msg1, c1)
        passou2, msg2, c2 = _rodar_metodo_original(*_TESTE_2)
        _registrar_cenario('Cenário 4b — depois do módulo completo (MutacaoObservacaoFutura)', passou2, msg2, c2)
        self.assertTrue(passou1 and passou2,
                         msg=f'teste original falhou — 1:{passou1} 2:{passou2}\n{msg1}\n{msg2}')


class DiagnosticoCenario5TestCase(unittest.TestCase):
    """Cenário 5 — depois da suíte científica ampla (a mesma lista de
    módulos do Job C de ci.yml), separado dos cenários 1-4 por ser
    pesado (roda a suíte inteira antes, timeout próprio no workflow —
    ver Job D "amplo"). Mesmo princípio de DiagnosticoCenariosTestCase:
    faz assert sobre o resultado do teste original ao final, para que
    uma falha real nunca seja reportada como OK."""

    _MODULOS_JOB_C = [
        'tests.test_c3s', 'tests.test_c3s_calibracao', 'tests.test_c3s_hindcast_completo',
        'tests.test_c3s_multimodel', 'tests.test_c3s_multimodel_catalogo',
        'tests.test_c3s_multimodel_hindcast', 'tests.test_c3s_multimodel_poc',
        'tests.test_c3s_multiorigem', 'tests.test_c3s_poc', 'tests.test_c3s_skill',
        'tests.test_cfsv2_calibracao_aditiva', 'tests.test_cfsv2_calibracao_mos_linear',
        'tests.test_cfsv2_calibracao_multiplicativa', 'tests.test_cfsv2_diagnostico_multiplicativo',
        'tests.test_cfsv2_diagnostico_previsibilidade_2c3e',
        'tests.test_cfsv2_emos_h2_viabilidade_warmup',
        'tests.test_cfsv2_gate_calibracao_probabilistica',
        'tests.test_cfsv2_mos_linear_auditoria_disponibilidade',
        'tests.test_cfsv2_robustez_h2_spread', 'tests.test_cfsv2_validacao_cientifica',
        'tests.test_cfsv2_viabilidade_quantile_mapping', 'tests.test_chirps_extracao_sintetica',
        'tests.test_chirps_v3_extracao', 'tests.test_chirps_v3_piloto',
        'tests.test_chirps_v3_reconstrucao_historica', 'tests.test_chirps_v3_sensibilidade_espacial',
        'tests.test_nmme_auditoria_chirps_sinobras', 'tests.test_nmme_auditoria_observacional_historica',
        'tests.test_nmme_auditoria_sinobras_por_fazenda', 'tests.test_nmme_backend_abstraction',
        'tests.test_nmme_catalogo', 'tests.test_nmme_cpc_cpt', 'tests.test_nmme_extracao_historica',
        'tests.test_nmme_iri_member', 'tests.test_nmme_piloto_historico', 'tests.test_nmme_poc',
        'tests.test_nmme_poc_espacial_fazendas', 'tests.test_nmme_poc_real_cfsv2',
        # test_cfsv2_emos_h2_implementacao de propósito NÃO entra nesta lista — é
        # rodado separadamente por _rodar_metodo_original a seguir, para isolar
        # o efeito de "veio antes" sem rodá-lo duas vezes por engano.
    ]

    @classmethod
    def setUpClass(cls):
        emos.minimize = _minimize_instrumentado
        cls.addClassCleanup(_restaurar_minimize_original)
        cls.addClassCleanup(_imprimir_resumo_final)

    def test_cenario_5_depois_da_suite_cientifica_ampla(self):
        totais = {'testes': 0, 'falhas': 0}
        for nome_modulo in self._MODULOS_JOB_C:
            n_testes, n_falhas = _rodar_modulo_inteiro(nome_modulo)
            totais['testes'] += n_testes
            totais['falhas'] += n_falhas
        print(f'\n[Cenário 5] suíte ampla (Job C, sem EMOS H2) rodou '
              f'{totais["testes"]} testes, {totais["falhas"]} falha(s)/erro(s) — '
              f'estado de processo resultante usado a seguir')
        passou1, msg1, c1 = _rodar_metodo_original(*_TESTE_1)
        _registrar_cenario('Cenário 5a — depois da suíte ampla (IndependenciaD0)', passou1, msg1, c1)
        passou2, msg2, c2 = _rodar_metodo_original(*_TESTE_2)
        _registrar_cenario('Cenário 5b — depois da suíte ampla (MutacaoObservacaoFutura)', passou2, msg2, c2)
        self.assertTrue(passou1 and passou2,
                         msg=f'teste original falhou — 1:{passou1} 2:{passou2}\n{msg1}\n{msg2}')


if __name__ == '__main__':
    unittest.main()
