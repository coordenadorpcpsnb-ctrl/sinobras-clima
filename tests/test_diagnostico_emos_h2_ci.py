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
import traceback
import unittest
from datetime import datetime, timezone
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
_FALHAS_MODULO_AMPLO = []


class _TestResultDetalhado(unittest.TestResult):
    """Subclasse MÍNIMA de unittest.TestResult — só ACRESCENTA captura
    de detalhes (nome completo do teste, tipo de exceção, traceback
    original, módulo/classe de origem, timestamp) a cada falha/erro,
    via addFailure/addError. Cada override chama super() PRIMEIRO,
    preservando exatamente a semântica/contagem original do
    TestResult (failures/errors/testsRun/wasSuccessful() continuam
    exatamente como o unittest padrão produziria) — `falhas_detalhadas`
    é só uma cópia lateral, NUNCA a fonte de verdade de PASS/FAIL
    (investigação, item 1: 'usar os resultados reais do
    unittest.TestResult, preservando asserts e resultados')."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.falhas_detalhadas = []

    def _registrar_detalhe(self, test, err, categoria):
        exc_type, exc_value, exc_tb = err
        self.falhas_detalhadas.append({
            'nome_completo': test.id(),
            'categoria': categoria,  # 'failure' (AssertionError) ou 'error' (outra exceção)
            'tipo_excecao': exc_type.__name__ if exc_type else None,
            'mensagem_excecao': str(exc_value) if exc_value else None,
            'traceback': ''.join(traceback.format_exception(exc_type, exc_value, exc_tb)),
            'modulo_origem': test.__class__.__module__,
            'classe_origem': test.__class__.__name__,
            'momento_utc': datetime.now(timezone.utc).isoformat(),
        })

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._registrar_detalhe(test, err, 'failure')

    def addError(self, test, err):
        super().addError(test, err)
        self._registrar_detalhe(test, err, 'error')

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


def _backend_blas_efetivo():
    """Investigação, item 2: distingue o BUILD do OpenBLAS
    (numpy.show_config(), estático — sempre reporta o baseline
    'Haswell' do wheel, independente da CPU real) da configuração
    EFETIVAMENTE usada em tempo de execução. threadpoolctl só detecta
    a biblioteca depois que ela é de fato carregada no processo (dlopen
    preguiçoso) — por isso o aquecimento abaixo: uma operação BLAS
    trivial (produto escalar de 8 elementos), isolada, sem nenhuma
    relação com EMOS H2, só para forçar o carregamento antes de
    perguntar a threadpoolctl o que está carregado. Confirmado
    localmente nesta investigação: antes do aquecimento,
    threadpool_info() devolve [] (biblioteca ainda não carregada);
    depois, devolve a arquitetura REAL selecionada pelo DYNAMIC_ARCH do
    OpenBLAS para a CPU do processo atual — valor que já foi observado
    divergir do baseline estático do build nesta mesma investigação.
    Não altera nenhum cálculo do EMOS H2: array próprio, descartado —
    demonstrado bit-a-bit (ver
    BackendBlasEfetivoTestCase.test_b_aquecimento_nao_altera_resultado_do_otimizador_real,
    inclusive no pior caso — aquecimento no MESMO processo,
    imediatamente antes do ajuste real; o uso de produção é sempre
    menos arriscado que esse pior caso: no passo 'Ambiente' do
    ci.yml roda num processo `python -c` separado e descartado antes
    do processo que roda os testes científicos; dentro deste arquivo,
    só roda via _imprimir_resumo_final()/addClassCleanup, depois que
    TODAS as chamadas EMOS H2 da classe já terminaram e foram
    registradas).

    LIMITAÇÃO REGISTRADA (revisão externa, item 2): quando esta função
    roda dentro do passo 'Ambiente' do ci.yml (processo `python -c`
    isolado, nunca o mesmo processo que roda os testes científicos),
    o valor de 'architecture' é uma INFERÊNCIA — assume que o
    DYNAMIC_ARCH do OpenBLAS detecta a mesma CPU (via CPUID) e
    seleciona o mesmo kernel em qualquer processo nesse runner, não
    uma medição direta do processo que de fato rodou o EMOS H2. Já
    quando chamada por _info_ambiente()/_imprimir_resumo_final() nos
    Jobs D/E (mesmo processo que rodou os testes), a leitura É direta
    e exata, não inferida — essa distinção nunca foi verificada
    experimentalmente entre processos (não há motivo para o
    DYNAMIC_ARCH escolher diferente por processo na mesma CPU, mas
    isso não foi comprovado nesta investigação, só assumido como
    comportamento conhecido do OpenBLAS). Esta função nunca define
    nenhuma variável de ambiente (ex.: OPENBLAS_CORETYPE) nem de outra
    forma força uma arquitetura/configuração específica — só lê o que
    o processo já carregaria de qualquer forma na primeira operação
    BLAS real."""
    try:
        import threadpoolctl
    except ImportError:
        return {'disponivel': False, 'motivo': 'threadpoolctl não instalado neste ambiente'}
    try:
        _ = np.dot(np.ones(8), np.ones(8))  # aquecimento — força dlopen do backend BLAS
        info = threadpoolctl.threadpool_info()
    except Exception as e:
        return {'disponivel': False, 'motivo': f'threadpool_info() falhou: {e}'}
    relevantes = [
        {k: d.get(k) for k in (
            'user_api', 'internal_api', 'prefix', 'filepath', 'version',
            'threading_layer', 'architecture', 'num_threads')}
        for d in info if d.get('user_api') in ('blas', 'lapack')
    ]
    return {'disponivel': True, 'bibliotecas': relevantes}


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
    info['backend_blas_efetivo'] = _backend_blas_efetivo()
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
    deixam atrás.

    Usa _TestResultDetalhado (subclasse de TestResult, não uma
    reimplementação) — investigação, item 1: antes só a CONTAGEM de
    falhas/erros era reportada (ex.: Job E run 39595727397, '1613
    testes, 1 falha(s)/erro(s)' sem identificar qual); agora também
    devolve nome completo/tipo de exceção/traceback/módulo/timestamp
    de cada falha real, sem mudar nenhuma contagem nem lógica de
    aprovação dos testes originais."""
    modulo = importlib.import_module(nome_modulo_dotted)
    suite = unittest.TestLoader().loadTestsFromModule(modulo)
    resultado = _TestResultDetalhado()
    suite.run(resultado)
    return resultado.testsRun, len(resultado.failures) + len(resultado.errors), resultado.falhas_detalhadas


def _registrar_falhas_modulo_amplo(nome_modulo_dotted, falhas_detalhadas):
    for f in falhas_detalhadas:
        registro = dict(f)
        registro['modulo_chamado_como'] = nome_modulo_dotted
        _FALHAS_MODULO_AMPLO.append(registro)
        print(f'\n  !! FALHA/ERRO em {nome_modulo_dotted}: {f["nome_completo"]} '
              f'({f["categoria"]}: {f["tipo_excecao"]}: {f["mensagem_excecao"]}) '
              f'em {f["momento_utc"]}')
        print(f'     traceback original:\n{f["traceback"]}')


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
        if c['jac']:
            # Investigação, item 3: já era calculado (norma_gradiente
            # acima é só a norma L2 deste vetor) mas nunca impresso —
            # o gradiente POR COMPONENTE é o que falta para verificar a
            # condição de KKT no limite ativo (sinal do componente de
            # gamma_c quando ele está preso no bound, não só a norma
            # do vetor completo, que mistura componentes limitados e
            # não-limitados e por isso não serve como teste de
            # estacionariedade por si só).
            print(f'    jac (por componente, ordem = bounds)={c["jac"]}')


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
    if _FALHAS_MODULO_AMPLO:
        print('-' * 70)
        print(f'Falhas/erros identificados na suíte ampla (fora do EMOS H2): '
              f'{len(_FALHAS_MODULO_AMPLO)}')
        for f in _FALHAS_MODULO_AMPLO:
            print(f'  - {f["nome_completo"]} [{f["categoria"]}: {f["tipo_excecao"]}] '
                  f'em {f["momento_utc"]} (chamado via {f["modulo_chamado_como"]})')
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


class CapturaDetalhadaDeFalhaTestCase(unittest.TestCase):
    """Investigação, item 1: prova, com falhas deliberadas e sintéticas
    (não o EMOS H2, nem a suíte ampla real), que _TestResultDetalhado
    (a) preserva EXATAMENTE a mesma contagem/semântica de PASS/FAIL do
    unittest.TestResult padrão — nunca usada como fonte de verdade
    alternativa — e (b) captura corretamente nome completo, tipo de
    exceção, módulo/classe de origem e traceback tanto para uma
    'failure' (AssertionError) quanto para um 'error' (outra
    exceção), que o TestResult padrão distingue internamente mas que
    _rodar_modulo_inteiro, antes desta mudança, reportava só como uma
    contagem agregada."""

    def test_a_falha_assertion_e_capturada_com_detalhe_correto(self):
        class _FalhaDeliberadaTestCase(unittest.TestCase):
            def test_isso_sempre_falha(self):
                self.fail('falha sintética, só para provar a captura detalhada')

        # Duas instâncias de TestSuite separadas — reutilizar a mesma
        # TestSuite entre duas chamadas a .run() não é um padrão
        # suportado pelo unittest (confirmado localmente nesta
        # investigação: a segunda chamada falha com
        # "TypeError: 'NoneType' object is not callable"); cada
        # _rodar_*/_registrar_* do resto do arquivo já evitava isso
        # por carregar/rodar uma suite nova a cada chamada — só este
        # teste, que compara padrão vs. detalhado lado a lado,
        # precisava de duas instâncias explícitas.
        resultado_padrao = unittest.TestResult()
        unittest.TestLoader().loadTestsFromName(
            'test_isso_sempre_falha', _FalhaDeliberadaTestCase).run(resultado_padrao)
        resultado_detalhado = _TestResultDetalhado()
        unittest.TestLoader().loadTestsFromName(
            'test_isso_sempre_falha', _FalhaDeliberadaTestCase).run(resultado_detalhado)

        # mesma semântica do TestResult padrão, nada muda
        self.assertEqual(resultado_padrao.wasSuccessful(), resultado_detalhado.wasSuccessful())
        self.assertEqual(len(resultado_padrao.failures), len(resultado_detalhado.failures))

        self.assertEqual(len(resultado_detalhado.falhas_detalhadas), 1)
        detalhe = resultado_detalhado.falhas_detalhadas[0]
        self.assertTrue(detalhe['nome_completo'].endswith(
            '_FalhaDeliberadaTestCase.test_isso_sempre_falha'))
        self.assertEqual(detalhe['categoria'], 'failure')
        self.assertEqual(detalhe['tipo_excecao'], 'AssertionError')
        self.assertIn('falha sintética, só para provar a captura detalhada', detalhe['mensagem_excecao'])
        self.assertEqual(detalhe['classe_origem'], '_FalhaDeliberadaTestCase')
        self.assertIn('AssertionError', detalhe['traceback'])
        self.assertIsNotNone(detalhe['momento_utc'])

    def test_b_erro_nao_assertion_e_capturado_com_tipo_correto(self):
        class _ErroDeliberadoTestCase(unittest.TestCase):
            def test_isso_sempre_lanca_valueerror(self):
                raise ValueError('erro sintético, não-AssertionError, só para provar a captura')

        resultado_padrao = unittest.TestResult()
        unittest.TestLoader().loadTestsFromName(
            'test_isso_sempre_lanca_valueerror', _ErroDeliberadoTestCase).run(resultado_padrao)
        resultado_detalhado = _TestResultDetalhado()
        unittest.TestLoader().loadTestsFromName(
            'test_isso_sempre_lanca_valueerror', _ErroDeliberadoTestCase).run(resultado_detalhado)

        self.assertEqual(resultado_padrao.wasSuccessful(), resultado_detalhado.wasSuccessful())
        self.assertEqual(len(resultado_padrao.errors), len(resultado_detalhado.errors))

        self.assertEqual(len(resultado_detalhado.falhas_detalhadas), 1)
        detalhe = resultado_detalhado.falhas_detalhadas[0]
        self.assertEqual(detalhe['categoria'], 'error')
        self.assertEqual(detalhe['tipo_excecao'], 'ValueError')
        self.assertIn('erro sintético, não-AssertionError', detalhe['mensagem_excecao'])

    def test_c_teste_que_passa_nao_gera_nenhum_detalhe(self):
        class _SucessoDeliberadoTestCase(unittest.TestCase):
            def test_isso_sempre_passa(self):
                self.assertTrue(True)

        suite = unittest.TestLoader().loadTestsFromName(
            'test_isso_sempre_passa', _SucessoDeliberadoTestCase)
        resultado_detalhado = _TestResultDetalhado()
        suite.run(resultado_detalhado)
        self.assertTrue(resultado_detalhado.wasSuccessful())
        self.assertEqual(resultado_detalhado.falhas_detalhadas, [])


class BackendBlasEfetivoTestCase(unittest.TestCase):
    """Investigação, item 2: prova que _backend_blas_efetivo() consegue
    distinguir build estático (numpy.show_config) de configuração
    efetiva (threadpoolctl, após aquecimento) neste próprio processo —
    não depende de reproduzir a falha do EMOS H2, só confirma que o
    mecanismo de coleta funciona e não lança exceção em nenhum
    ambiente (inclusive um sem threadpoolctl, se algum dia faltar)."""

    def test_a_backend_blas_efetivo_nao_lanca_e_retorna_estrutura_valida(self):
        resultado = _backend_blas_efetivo()
        self.assertIn('disponivel', resultado)
        if resultado['disponivel']:
            self.assertIn('bibliotecas', resultado)
            self.assertIsInstance(resultado['bibliotecas'], list)
        else:
            self.assertIn('motivo', resultado)

    def test_b_aquecimento_nao_altera_resultado_do_otimizador_real(self):
        """Revisão externa (21/10/2026, item 2): exige demonstrar o
        efeito do aquecimento BLAS, não só afirmar que não há efeito.
        Roda o MESMO ajuste real (emos.ajustar_emos_d0, não
        reimplementado) duas vezes com entrada determinística idêntica
        — uma vez chamando _backend_blas_efetivo() (aquecimento +
        leitura threadpoolctl) IMEDIATAMENTE ANTES do ajuste, no pior
        caso possível (mesmo processo, aquecimento logo antes da
        chamada real — mais conservador do que o uso de produção, onde
        o aquecimento roda num processo python -c separado no passo
        'Ambiente' do ci.yml, ou, dentro do próprio arquivo de teste,
        só depois de TODAS as chamadas EMOS H2 já terem rodado, via
        addClassCleanup). Se nem neste pior caso há diferença
        bit-exata, não há efeito numérico em nenhum uso real.
        Não força nenhuma arquitetura/configuração — só lê o que o
        processo já carregaria de qualquer forma na primeira operação
        BLAS real."""
        clim_obs = np.full(10, 70.0)
        anom = np.linspace(-5, 5, 10)
        erro_sd = np.full(10, 20.0)
        y = 70.0 + 0.5 * anom

        res_sem_aquecimento = emos.ajustar_emos_d0(clim_obs, anom, erro_sd, y)
        _backend_blas_efetivo()  # aquecimento + leitura, propositalmente ENTRE as duas chamadas
        res_com_aquecimento = emos.ajustar_emos_d0(clim_obs, anom, erro_sd, y)

        self.assertEqual(res_sem_aquecimento.success, res_com_aquecimento.success)
        self.assertEqual(res_sem_aquecimento.status, res_com_aquecimento.status)
        self.assertEqual(res_sem_aquecimento.nit, res_com_aquecimento.nit)
        self.assertEqual(res_sem_aquecimento.nfev, res_com_aquecimento.nfev)
        self.assertEqual(res_sem_aquecimento.fun, res_com_aquecimento.fun,
                          msg='aquecimento BLAS alterou o valor objetivo final — '
                              'efeito numérico real, não apenas teórico')
        np.testing.assert_array_equal(res_sem_aquecimento.x, res_com_aquecimento.x)


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
        n_testes, n_falhas, falhas_detalhadas = _rodar_modulo_inteiro(
            'tests.test_cfsv2_emos_h2_implementacao')
        print(f'\n[Cenário 4] módulo real completo rodou {n_testes} testes, '
              f'{n_falhas} falha(s)/erro(s) — estado de processo resultante usado a seguir')
        _registrar_falhas_modulo_amplo('tests.test_cfsv2_emos_h2_implementacao', falhas_detalhadas)
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
            n_testes, n_falhas, falhas_detalhadas = _rodar_modulo_inteiro(nome_modulo)
            totais['testes'] += n_testes
            totais['falhas'] += n_falhas
            _registrar_falhas_modulo_amplo(nome_modulo, falhas_detalhadas)
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
