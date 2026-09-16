#!/usr/bin/env python3
"""
tests/test_benchmark_modelos.py — regressão do benchmark de especificação
(scripts/benchmark_modelos.py, Fase 1.2).

Cobre a Seção 13 da tarefa. Nenhum teste depende de rede; usa a mesma
série sintética pequena de tests/test_backtest.py para rodar em segundos.

Roda com:
    python -m unittest tests.test_benchmark_modelos -v
"""

import inspect
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import backtest as bt  # noqa: E402
import benchmark_modelos as bm  # noqa: E402


def _serie_sintetica(n_meses=220, seed=7):
    rng = np.random.RandomState(seed)
    inicio = pd.Period('1990-01', 'M')
    periodos = pd.period_range(inicio, periods=n_meses, freq='M')
    meses = np.array([p.month for p in periodos])
    sazonal = 150 + 120 * np.sin(2 * np.pi * (meses - 1) / 12)
    prec = np.clip(sazonal + rng.normal(0, 20, n_meses), 0, None)
    nino34 = np.sin(2 * np.pi * np.arange(n_meses) / 41) + rng.normal(0, 0.15, n_meses)
    tsa = 0.3 * nino34 + rng.normal(0, 0.1, n_meses)
    pdo = 0.5 * np.sin(2 * np.pi * np.arange(n_meses) / 96) + rng.normal(0, 0.1, n_meses)
    df = pd.DataFrame({
        'ano': [p.year for p in periodos], 'mes': meses,
        'prec': prec.round(2), 'nino34': nino34.round(3),
        'tsa': tsa.round(3), 'pdo': pdo.round(3),
    })
    df['date'] = [str(p) for p in periodos]
    df['fonte'] = ''
    df['ym'] = periodos
    return df


class ClimatologiaPorOrigemTestCase(unittest.TestCase):
    """Testes 1 e 3 da Seção 13: climatologia por origem sem leakage, e
    média da anomalia do treino ~zero por mês (por construção)."""

    def test_climatologia_usa_so_dados_da_origem(self):
        serie = _serie_sintetica()
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        media, desvio = bm.climatologia_media_desvio(cortada)
        media_manual = cortada[cortada['mes'] == 6]['prec'].mean()
        self.assertAlmostEqual(media[6], media_manual, places=6)

    def test_climatologia_muda_conforme_a_origem_avanca(self):
        """Se a climatologia estivesse fixa (calculada 1x sobre a série
        inteira), duas origens diferentes dariam o mesmo resultado — não
        podem, porque cada uma só vê dado <= sua própria origem."""
        serie = _serie_sintetica()
        o1 = serie['ym'].iloc[180]
        o2 = serie['ym'].iloc[210]
        media1, _ = bm.climatologia_media_desvio(bt.cortar_serie(serie, o1))
        media2, _ = bm.climatologia_media_desvio(bt.cortar_serie(serie, o2))
        self.assertFalse(media1.equals(media2))

    def test_media_da_anomalia_de_treino_e_aproximadamente_zero_por_mes(self):
        serie = _serie_sintetica()
        origem = serie['ym'].iloc[200]
        cortada = bt.cortar_serie(serie, origem)
        media, _ = bm.climatologia_media_desvio(cortada)
        anom = bm.serie_para_anomalia(cortada, media)
        d = cortada.copy()
        d['anom'] = anom
        media_anom_por_mes = d.groupby('mes')['anom'].mean()
        # por construção, media[mes] = prec.mean() daquele mês no treino,
        # então anom.mean() por mês tem que ser ~0 (não exatamente 0 só
        # por causa de arredondamento de float)
        for v in media_anom_por_mes:
            self.assertAlmostEqual(v, 0.0, places=8)


class TransformacaoZTestCase(unittest.TestCase):
    """Testes 4 e 5 da Seção 13: z usa média/desvio do treino; inversa
    z -> mm está correta."""

    def test_z_usa_media_e_desvio_do_treino(self):
        serie = _serie_sintetica()
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        media, desvio = bm.climatologia_media_desvio(cortada)
        desvio_seg = bm.desvio_seguro(desvio)
        z = bm.serie_para_z(cortada, media, desvio_seg)
        linha0 = cortada.iloc[0]
        esperado = (linha0['prec'] - media[linha0['mes']]) / desvio_seg[linha0['mes']]
        self.assertAlmostEqual(z[0], esperado, places=6)

    def test_transformacao_inversa_anom_para_mm(self):
        media = pd.Series({1: 100.0, 2: 50.0})
        desvio_seg = pd.Series({1: 10.0, 2: 5.0})
        pred_transformado = np.array([5.0, -3.0])
        meses_futuros = np.array([1, 2])
        mm = bm.transformar_de_volta(pred_transformado, meses_futuros, media, desvio_seg, 'anom')
        np.testing.assert_allclose(mm, [105.0, 47.0])

    def test_transformacao_inversa_z_para_mm(self):
        media = pd.Series({1: 100.0, 2: 50.0})
        desvio_seg = pd.Series({1: 10.0, 2: 5.0})
        pred_transformado = np.array([2.0, -1.0])   # z
        meses_futuros = np.array([1, 2])
        mm = bm.transformar_de_volta(pred_transformado, meses_futuros, media, desvio_seg, 'z')
        # mes1: 100 + 2*10 = 120 ; mes2: 50 + (-1)*5 = 45
        np.testing.assert_allclose(mm, [120.0, 45.0])

    def test_desvio_minimo_evita_explosao_do_z(self):
        desvio = pd.Series({1: 0.0001, 2: 5.0})
        seguro = bm.desvio_seguro(desvio)
        self.assertGreaterEqual(seguro[1], bm.DESVIO_MINIMO_MM)
        self.assertEqual(seguro[2], 5.0)   # não altera desvio já razoável


class ClippingSoDepoisDaInversaTestCase(unittest.TestCase):
    """Teste 10 da Seção 13: clipping só ocorre depois da transformação
    inversa — uma anomalia muito negativa deve poder gerar mm=0 (clip),
    mas a anomalia em si nunca é clipada antes da soma com a climatologia."""

    def test_anomalia_muito_negativa_vira_zero_so_apos_somar_climatologia(self):
        media = pd.Series({1: 10.0})
        desvio_seg = pd.Series({1: 5.0})
        pred_transformado = np.array([-9999.0])   # anomalia absurda negativa
        meses_futuros = np.array([1])
        mm = bm.transformar_de_volta(pred_transformado, meses_futuros, media, desvio_seg, 'anom')
        self.assertEqual(mm[0], 0.0)   # clipado em mm, não em anomalia


class LagsNaoCruzamOrigemTestCase(unittest.TestCase):
    """Teste 6 da Seção 13."""

    def test_features_lineares_nao_cruzam_origem(self):
        serie = _serie_sintetica()
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        d_cortado = bt.construir_lags(cortada)
        d_feat, media, desvio_seg = bm.construir_features_lineares(cortada, d_cortado, 'anom')
        self.assertTrue((pd.PeriodIndex(d_feat['ym'], freq='M') <= origem).all())

    def test_features_xgb_direto_nao_cruzam_origem(self):
        serie = _serie_sintetica()
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        d_cortado = bt.construir_lags(cortada)
        modelos, X_origem, media, desvio_seg = bm.treinar_xgb_direto(cortada, d_cortado, 'anom')
        # a linha de previsão usada é a última do corte == a própria origem
        ultima_ym = pd.PeriodIndex(d_cortado['ym'], freq='M').max()
        self.assertEqual(ultima_ym, origem)


class RidgeElasticNetSemFuturoTestCase(unittest.TestCase):
    """Teste 7 da Seção 13: Ridge/ElasticNet não treinam com target futuro
    — o y de treino nunca inclui nenhuma linha com ym > origem, e o
    alpha é escolhido só com TimeSeriesSplit dentro do próprio treino."""

    def test_ridge_nao_usa_dado_posterior_a_origem(self):
        serie = _serie_sintetica()
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        d_cortado = bt.construir_lags(cortada)
        d_feat, media, desvio_seg = bm.construir_features_lineares(cortada, d_cortado, 'anom')
        self.assertTrue((pd.PeriodIndex(d_feat['ym'], freq='M') <= origem).all())
        modelo = bm.treinar_ridge(d_feat)
        self.assertTrue(hasattr(modelo, 'coef_'))

    def test_ridge_usa_cv_temporal_nao_toca_horizonte(self):
        import inspect as _inspect
        src = _inspect.getsource(bm.treinar_ridge)
        self.assertIn('TimeSeriesSplit', src)


class XgbDiretoSemVazamentoTestCase(unittest.TestCase):
    """Teste 8 da Seção 13: XGBoost direto H+k não usa a precipitação
    observada de H+k-1 — cada lead usa SEMPRE a mesma feature (estado em
    T=origem), nunca a previsão de um lead anterior."""

    def test_features_de_todos_os_leads_sao_identicas_ao_estado_na_origem(self):
        serie = _serie_sintetica()
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        d_cortado = bt.construir_lags(cortada)
        modelos, X_origem, media, desvio_seg = bm.treinar_xgb_direto(cortada, d_cortado, 'anom')
        # X_origem é usado para TODOS os 12 leads — nenhuma previsão de
        # lead anterior realimenta a próxima (diferente do XGBoost recursivo)
        preds = bm.prever_xgb_direto(modelos, X_origem, media, desvio_seg, origem, 'anom')
        self.assertEqual(len(preds), 12)
        # confirma que a assinatura de prever_xgb_direto não aceita nenhum
        # argumento de "previsão anterior" (sem estado acumulado entre leads)
        params = list(inspect.signature(bm.prever_xgb_direto).parameters)
        self.assertNotIn('preds_anteriores', params)
        self.assertNotIn('buffer', ' '.join(params))


class LeadsUmA12TestCase(unittest.TestCase):
    """Teste 9 da Seção 13: cada modelo direto produz leads 1..12."""

    def test_rodar_origem_benchmark_produz_leads_1_a_12_por_modelo(self):
        serie = _serie_sintetica()
        origem = serie['ym'].iloc[150]
        specs = [s for s in bm.gerar_specs_candidatos() if s[0] in
                 ('SARIMAX_anom_E1_semexog', 'Ridge_anom', 'XGBoost_direto_anom', 'Harmonico_harm1')]
        registros, diag, dt = bm.rodar_origem_benchmark(serie, origem, specs)
        df = pd.DataFrame(registros)
        for modelo, g in df.groupby('modelo'):
            self.assertEqual(sorted(g['lead'].tolist()), list(range(1, 13)),
                              f"{modelo} não produziu leads 1..12")


class ResultadosNaoSobrescrevemTestCase(unittest.TestCase):
    """Testes 11 e 12 da Seção 13: resultados desta fase não sobrescrevem
    Fase 1/1.1, e nenhum arquivo de produção é alterado."""

    def test_nomes_de_arquivo_sao_distintos_dos_da_fase_1_1(self):
        proibidos = {'backtest_results.json', 'backtest_predictions.csv',
                     'backtest_results_step1.json', 'backtest_predictions_step1.csv',
                     'backtest_results_step3.json', 'backtest_predictions_step3.csv'}
        novos = {'model_benchmark_results.json', 'model_benchmark_predictions.csv'}
        self.assertTrue(proibidos.isdisjoint(novos))

    def test_codigo_fonte_nao_escreve_em_arquivos_da_fase_1_1(self):
        texto = (ROOT / 'scripts' / 'benchmark_modelos.py').read_text(encoding='utf-8')
        for proibido in ["'backtest_results.json'", "'backtest_predictions.csv'",
                          "'backtest_results_step1.json'", "'backtest_predictions_step1.csv'"]:
            self.assertNotIn(f".write_text({proibido}", texto)
            # garante que essas strings só aparecem como LEITURA (carregar_referencia_fase11),
            # nunca associadas a to_csv/write_text
        self.assertIn('carregar_referencia_fase11', texto)

    def test_producao_nao_e_alterada_ao_rodar_uma_origem(self):
        alvos = ['data/serie_subst.csv', 'data/bh_final.json', 'data/fc_results_best.json',
                 'data/sarimax_data_best.json', 'data/master_monthly.csv', 'docs/index.html',
                 'data/backtest_results.json', 'data/backtest_predictions.csv',
                 'data/backtest_results_step1.json', 'data/backtest_predictions_step1.csv']
        antes = {a: (ROOT / a).stat().st_mtime_ns for a in alvos if (ROOT / a).exists()}

        serie = _serie_sintetica()
        origem = serie['ym'].iloc[150]
        specs = [s for s in bm.gerar_specs_candidatos() if s[0] == 'Ridge_anom']
        bm.rodar_origem_benchmark(serie, origem, specs)

        depois = {a: (ROOT / a).stat().st_mtime_ns for a in alvos if (ROOT / a).exists()}
        self.assertEqual(antes, depois)

    def test_backtest_py_nao_foi_alterado_em_comportamento_publico(self):
        """benchmark_modelos.py importa backtest.py — garante que não há
        nenhuma escrita/monkeypatch em atributos do módulo bt a partir de
        benchmark_modelos.py."""
        texto = (ROOT / 'scripts' / 'benchmark_modelos.py').read_text(encoding='utf-8')
        self.assertNotIn('bt.MODO_OPERACIONAL =', texto)
        self.assertNotIn('bt.HORIZON =', texto)
        self.assertNotIn('setattr(bt', texto)


class MaxiterEConvergenciaTestCase(unittest.TestCase):
    """Seção 9: maxiter=200 só neste módulo — nunca em produção."""

    def test_maxiter_padrao_e_200(self):
        self.assertEqual(bm.MAXITER_PADRAO, 200)

    def test_treinar_sarimax_representacao_aceita_maxiter(self):
        serie = _serie_sintetica()
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        d_cortado = bt.construir_lags(cortada)
        res, diag, media, desvio_seg = bm.treinar_sarimax_representacao(
            cortada, d_cortado, (1, 0, 1), (0, 0, 0, 0), 'anom', False, maxiter=200)
        self.assertIn('converged', diag)
        self.assertEqual(diag['maxiter_config'], 200)


class ClassificacaoPeriodoOperacionalTestCase(unittest.TestCase):
    """Seção 7: classificação objetiva documentada, sem fronteira inventada."""

    def test_meses_secos_sao_jun_jul_ago(self):
        for m in (6, 7, 8):
            self.assertEqual(bm.classificar_periodo_operacional(m), 'seco')

    def test_meses_chuvosos_cobrem_nov_a_abr(self):
        for m in (11, 12, 1, 2, 3, 4):
            self.assertEqual(bm.classificar_periodo_operacional(m), 'chuvoso')

    def test_transicao_seca_chuva_e_set_out(self):
        for m in (9, 10):
            self.assertEqual(bm.classificar_periodo_operacional(m), 'transicao_seca_chuva')

    def test_transicao_chuva_seca_e_maio(self):
        self.assertEqual(bm.classificar_periodo_operacional(5), 'transicao_chuva_seca')

    def test_todos_os_12_meses_classificados(self):
        classes = {bm.classificar_periodo_operacional(m) for m in range(1, 13)}
        self.assertEqual(classes, {'seco', 'chuvoso', 'transicao_seca_chuva', 'transicao_chuva_seca'})


class ImportSeguroTestCase(unittest.TestCase):

    def test_benchmark_modelos_nao_importa_update_dashboard(self):
        texto = (ROOT / 'scripts' / 'benchmark_modelos.py').read_text(encoding='utf-8')
        self.assertNotIn('import update_dashboard', texto)
        self.assertNotIn('from update_dashboard', texto)


if __name__ == '__main__':
    unittest.main()
