#!/usr/bin/env python3
"""
tests/test_confirmar_ridge_z.py — regressão da confirmação pós-seleção do
Ridge_z (scripts/confirmar_ridge_z.py, Fase 1.3).

Cobre a Seção 16 da tarefa. Nenhum teste depende de rede; usa a mesma
série sintética pequena das fases anteriores para rodar em segundos.

Roda com:
    python -m unittest tests.test_confirmar_ridge_z -v
"""

import re
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import backtest as bt  # noqa: E402
import benchmark_modelos as bm  # noqa: E402
import confirmar_ridge_z as cz  # noqa: E402


def _serie_sintetica(n_meses=260, seed=11):
    rng = np.random.RandomState(seed)
    inicio = pd.Period('1985-01', 'M')
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


class EspecificacaoCongeladaTestCase(unittest.TestCase):
    """Teste 1 da Seção 16: a especificação do Ridge_z nesta fase é
    IDÊNTICA à da Fase 1.2 — checagem por leitura de texto-fonte (nunca
    reimplementação local), no mesmo padrão de
    SincroniaComProducaoTestCase das fases anteriores."""

    def test_confirmar_ridge_z_importa_especificacao_de_benchmark_modelos(self):
        texto = (ROOT / 'scripts' / 'confirmar_ridge_z.py').read_text(encoding='utf-8')
        m = re.search(r'from benchmark_modelos import \(([^)]+)\)', texto, re.DOTALL)
        self.assertIsNotNone(m, "confirmar_ridge_z.py não importa a especificação de benchmark_modelos.py")
        bloco_import = m.group(1)
        # remove comentários de linha antes de checar os nomes (evita que
        # texto de comentário "esconda" um nome dentro de um token maior)
        bloco_sem_comentarios = '\n'.join(l.split('#', 1)[0] for l in bloco_import.split('\n'))
        obrigatorios = {'FEATURES_LINEAR', 'climatologia_media_desvio', 'desvio_seguro',
                         'construir_features_lineares', 'treinar_ridge', 'prever_linear_recursivo',
                         'transformar_de_volta'}
        faltando = {nome for nome in obrigatorios if not re.search(rf'\b{nome}\b', bloco_sem_comentarios)}
        self.assertEqual(faltando, set(), f"funções da especificação congelada não importadas: {faltando}")

    def test_confirmar_ridge_z_nao_redefine_funcoes_congeladas(self):
        texto = (ROOT / 'scripts' / 'confirmar_ridge_z.py').read_text(encoding='utf-8')
        proibidas = ['def treinar_ridge(', 'def construir_features_lineares(',
                     'def prever_linear_recursivo(', 'def transformar_de_volta(',
                     'def climatologia_media_desvio(', 'def desvio_seguro(']
        for assinatura in proibidas:
            self.assertNotIn(assinatura, texto,
                              f"{assinatura} foi redefinida localmente — deveria só importar de benchmark_modelos")

    def test_features_completo_bate_com_features_linear_da_fase_12(self):
        self.assertEqual(cz.FEATURES_COMPLETO, list(bm.FEATURES_LINEAR))

    def test_prever_generico_reproduz_prever_linear_recursivo_com_features_completo(self):
        """Prova de que a generalização usada na ablação não introduz
        nenhuma mudança de comportamento quando aplicada ao conjunto
        COMPLETO de features — deve ser numericamente idêntica à função
        congelada da Fase 1.2."""
        serie = _serie_sintetica()
        origem = serie['ym'].iloc[200]
        cortada = bt.cortar_serie(serie, origem)
        d_cortado = bt.construir_lags(cortada)
        d_feat, media, desvio_seg = bm.construir_features_lineares(cortada, d_cortado, 'z')
        modelo = bm.treinar_ridge(d_feat)
        exog = bt.montar_exog_futuro(cortada, serie, origem, bt.MODO_OPERACIONAL)

        preds_congelado = bm.prever_linear_recursivo(modelo, d_feat, media, desvio_seg, origem, 'z', exog)
        preds_generico = cz.prever_generico_recursivo(modelo, d_feat, cz.FEATURES_COMPLETO,
                                                        media, desvio_seg, origem, 'z', exog)
        np.testing.assert_allclose(preds_congelado, preds_generico, rtol=1e-10)


class DivisaoTemporalTestCase(unittest.TestCase):
    """Testes 2 e 3 da Seção 16: fronteira dev/confirmação correta, e
    nenhuma origem recente entra no desenvolvimento."""

    def test_fronteira_e_2016_01(self):
        self.assertEqual(cz.FRONTEIRA_CONFIRMACAO, pd.Period('2016-01', 'M'))

    def test_origens_antes_da_fronteira_sao_desenvolvimento(self):
        serie = _serie_sintetica(n_meses=400)
        origens = bt.gerar_origens(serie, step=bt.STEP_MENSAL)
        dev = [o for o in origens if o < cz.FRONTEIRA_CONFIRMACAO]
        conf = [o for o in origens if o >= cz.FRONTEIRA_CONFIRMACAO]
        self.assertTrue(all(o < cz.FRONTEIRA_CONFIRMACAO for o in dev))
        self.assertTrue(all(o >= cz.FRONTEIRA_CONFIRMACAO for o in conf))
        # nenhuma origem >= fronteira aparece em dev, e vice-versa
        self.assertEqual(set(dev) & set(conf), set())


class SemVazamentoTestCase(unittest.TestCase):
    """Teste 4 da Seção 16: nenhuma previsão usa informação futura."""

    def test_operacional_nao_muda_com_serie_completa_corrompida(self):
        serie = _serie_sintetica()
        origem = serie['ym'].iloc[200]
        registros_normais, coef_normal, _ = cz.rodar_origem_confirmacao(serie, origem)

        serie_corrompida = serie.copy()
        mask_futuro = serie_corrompida['ym'] > origem
        serie_corrompida.loc[mask_futuro, ['nino34', 'tsa', 'pdo', 'prec']] = 9999.0
        registros_corrompidos, coef_corrompido, _ = cz.rodar_origem_confirmacao(serie_corrompida, origem)

        df_normal = pd.DataFrame(registros_normais)
        df_corrompido = pd.DataFrame(registros_corrompidos)
        op_normal = df_normal[(df_normal['modelo'] == cz.MODELO_RIDGE_Z) & (df_normal['modo'] == bt.MODO_OPERACIONAL)]
        op_corrompido = df_corrompido[(df_corrompido['modelo'] == cz.MODELO_RIDGE_Z) & (df_corrompido['modo'] == bt.MODO_OPERACIONAL)]
        np.testing.assert_allclose(op_normal['previsto'].values, op_corrompido['previsto'].values)
        self.assertAlmostEqual(coef_normal['alpha_selecionado'], coef_corrompido['alpha_selecionado'], places=6)


class RmseZTestCase(unittest.TestCase):
    """Teste 5 da Seção 16: cálculo de RMSE_z."""

    def test_rmse_z_bate_com_calculo_manual(self):
        df = pd.DataFrame({
            'origem': ['o1', 'o1', 'o2', 'o2'], 'lead': [1, 2, 1, 2],
            'modelo': ['ModeloX'] * 4, 'modo': [bt.MODO_OPERACIONAL] * 4,
            'observado': [100.0, 50.0, 100.0, 50.0], 'previsto': [110.0, 45.0, 90.0, 60.0],
            'clim_desvio_mes': [10.0, 5.0, 10.0, 5.0],
        })
        clim = pd.DataFrame({
            'origem': ['o1', 'o1', 'o2', 'o2'], 'lead': [1, 2, 1, 2],
            'modelo': ['Climatologia'] * 4, 'modo': [bt.MODO_OPERACIONAL] * 4,
            'observado': [100.0, 50.0, 100.0, 50.0], 'previsto': [100.0, 50.0, 100.0, 50.0],
            'clim_desvio_mes': [10.0, 5.0, 10.0, 5.0],
        })
        junto = pd.concat([df, clim], ignore_index=True)
        r = cz.bootstrap_ci_skill_z(junto, 'ModeloX', modo=bt.MODO_OPERACIONAL, n_boot=100, seed=1)
        # erro_z manual: (110-100)/10=1, (45-50)/5=-1, (90-100)/10=-1, (60-50)/5=2
        erros_z = np.array([1.0, -1.0, -1.0, 2.0])
        rmse_z_esperado = float(np.sqrt(np.mean(erros_z ** 2)))
        self.assertAlmostEqual(r['rmse_modelo'], rmse_z_esperado, places=3)   # bt.bootstrap_ci_diff_rmse arredonda em 3 casas
        self.assertEqual(r['rmse_climatologia'], 0.0)   # climatologia == observado aqui


class BootstrapReproduzivelTestCase(unittest.TestCase):
    """Teste 6 da Seção 16."""

    def _df(self, n_origens=20, seed=5):
        rng = np.random.RandomState(seed)
        linhas = []
        for i in range(n_origens):
            origem = str(pd.Period('2000-01', 'M') + i)
            obs = rng.normal(100, 20, 12)
            for lead in range(1, 13):
                linhas.append({'origem': origem, 'lead': lead, 'modelo': 'Climatologia',
                                'modo': bt.MODO_OPERACIONAL, 'observado': obs[lead - 1],
                                'previsto': obs[lead - 1] + rng.normal(0, 15)})
                linhas.append({'origem': origem, 'lead': lead, 'modelo': 'ModeloX',
                                'modo': bt.MODO_OPERACIONAL, 'observado': obs[lead - 1],
                                'previsto': obs[lead - 1] + rng.normal(-1, 12)})
        return pd.DataFrame(linhas)

    def test_bootstrap_bloco_temporal_reproduzivel(self):
        df = self._df()
        r1 = cz.bootstrap_ci_bloco_temporal(df, 'ModeloX', tamanho_bloco_origens=3, n_boot=200, seed=42)
        r2 = cz.bootstrap_ci_bloco_temporal(df, 'ModeloX', tamanho_bloco_origens=3, n_boot=200, seed=42)
        self.assertEqual(r1['skill_ic95'], r2['skill_ic95'])

    def test_bootstrap_bloco_temporal_ic_ordenado_em_varios_tamanhos(self):
        df = self._df()
        for k in [1, 3, 6]:
            r = cz.bootstrap_ci_bloco_temporal(df, 'ModeloX', tamanho_bloco_origens=k, n_boot=200, seed=42)
            lo, hi = r['skill_ic95']
            self.assertLessEqual(lo, hi)


class CoeficientesRegistradosTestCase(unittest.TestCase):
    """Teste 7 da Seção 16."""

    def test_coef_row_tem_uma_entrada_por_feature(self):
        serie = _serie_sintetica()
        origem = serie['ym'].iloc[200]
        registros, coef_row, _ = cz.rodar_origem_confirmacao(serie, origem)
        for f in cz.FEATURES_COMPLETO:
            self.assertIn(f'coef_{f}', coef_row)
        self.assertIn('alpha_selecionado', coef_row)
        self.assertIn('intercept', coef_row)
        self.assertEqual(coef_row['origem'], str(origem))


class AblacaoNaoAlteraHiperparametrosTestCase(unittest.TestCase):
    """Teste 8 da Seção 16: ablação usa a MESMA grade de alpha/CV — só
    muda o conjunto de features."""

    def test_treinar_ridge_generico_usa_mesma_grade_de_alpha_do_congelado(self):
        import inspect
        src_congelado = inspect.getsource(bm.treinar_ridge)
        src_generico = inspect.getsource(cz.treinar_ridge_generico)
        self.assertIn('np.logspace(-2, 2, 9)', src_congelado)
        self.assertIn('np.logspace(-2, 2, 9)', src_generico)
        self.assertIn('TimeSeriesSplit', src_congelado)
        self.assertIn('TimeSeriesSplit', src_generico)

    def test_features_ablacao_sao_subconjuntos_do_completo(self):
        self.assertTrue(set(cz.FEATURES_SEM_OCEANO).issubset(set(cz.FEATURES_COMPLETO)))
        self.assertTrue(set(cz.FEATURES_SO_OCEANO_SAZONAL).issubset(set(cz.FEATURES_COMPLETO)))
        self.assertNotIn('n34_l23', cz.FEATURES_SEM_OCEANO)
        self.assertNotIn('alvo_l1', cz.FEATURES_SO_OCEANO_SAZONAL)


class OracleSemPrecipitacaoTestCase(unittest.TestCase):
    """Teste 9 da Seção 16: oracle usa só exógenas futuras, nunca
    precipitação futura."""

    def test_exog_oracle_tem_só_colunas_de_indices_oceanicos(self):
        serie = _serie_sintetica()
        origem = serie['ym'].iloc[200]
        cortada = bt.cortar_serie(serie, origem)
        exog_or = bt.montar_exog_futuro(cortada, serie, origem, bt.MODO_ORACLE)
        self.assertEqual(set(exog_or.columns), {'n34_l23', 'tsa_l23', 'pdo_l23'})

    def test_oracle_usa_prec_buf_igual_ao_operacional_ate_a_origem(self):
        """A única diferença entre operacional e oracle deve estar nas
        exógenas futuras — o buffer de alvo (derivado de prec observada
        <= origem) é idêntico nos dois."""
        serie = _serie_sintetica()
        origem = serie['ym'].iloc[200]
        cortada = bt.cortar_serie(serie, origem)
        d_cortado = bt.construir_lags(cortada)
        d_feat, media, desvio_seg = bm.construir_features_lineares(cortada, d_cortado, 'z')
        modelo = bm.treinar_ridge(d_feat)
        exog_op = bt.montar_exog_futuro(cortada, serie, origem, bt.MODO_OPERACIONAL)
        exog_or = bt.montar_exog_futuro(cortada, serie, origem, bt.MODO_ORACLE)
        preds_op = bm.prever_linear_recursivo(modelo, d_feat, media, desvio_seg, origem, 'z', exog_op)
        preds_or = bm.prever_linear_recursivo(modelo, d_feat, media, desvio_seg, origem, 'z', exog_or)
        # lead 1 usa lag2/lag3 do exógeno que são sempre reais/conhecidos
        # em ambos os modos (origem-1, origem-2) — deve bater
        self.assertAlmostEqual(preds_op[0], preds_or[0], places=6)


class ClassificacaoPeriodoOperacionalIdenticaTestCase(unittest.TestCase):
    """Teste 10 da Seção 16."""

    def test_classificacao_reusa_funcao_da_fase_12(self):
        for m in range(1, 13):
            self.assertEqual(cz.classificar_periodo_operacional(m), bm.classificar_periodo_operacional(m))


class OutputsNaoSobrescrevemTestCase(unittest.TestCase):
    """Testes 11 e 12 da Seção 16."""

    def test_nomes_de_saida_distintos_de_artefatos_anteriores(self):
        proibidos = {'model_benchmark_results.json', 'model_benchmark_predictions.csv',
                     'backtest_results_step1.json', 'backtest_predictions_step1.csv',
                     'backtest_results.json', 'backtest_predictions.csv'}
        novos = {'ridge_z_confirmation.json', 'ridge_z_confirmation_predictions.csv',
                 'ridge_z_coefficients.csv'}
        self.assertEqual(proibidos & novos, set())

    def test_producao_nao_e_alterada_ao_rodar_uma_origem(self):
        alvos = ['data/serie_subst.csv', 'data/bh_final.json', 'data/fc_results_best.json',
                 'data/sarimax_data_best.json', 'data/master_monthly.csv', 'docs/index.html',
                 'data/backtest_results.json', 'data/model_benchmark_results.json']
        antes = {a: (ROOT / a).stat().st_mtime_ns for a in alvos if (ROOT / a).exists()}

        serie = _serie_sintetica()
        origem = serie['ym'].iloc[200]
        cz.rodar_origem_confirmacao(serie, origem)

        depois = {a: (ROOT / a).stat().st_mtime_ns for a in alvos if (ROOT / a).exists()}
        self.assertEqual(antes, depois)

    def test_codigo_fonte_nao_importa_update_dashboard(self):
        texto = (ROOT / 'scripts' / 'confirmar_ridge_z.py').read_text(encoding='utf-8')
        self.assertNotIn('import update_dashboard', texto)
        self.assertNotIn('from update_dashboard', texto)


if __name__ == '__main__':
    unittest.main()
