#!/usr/bin/env python3
"""
tests/test_backtest.py — regressão do backtest temporal (scripts/backtest.py).

Cobre a Seção 11 da Fase 1 e a Seção 10 da Fase 1.1 (robustez
metodológica): nenhum teste depende de rede. Todos usam pandas.PeriodIndex
sintético/pequeno para rodar em segundos — não executam o backtest
completo (isso é feito manualmente via `python scripts/backtest.py`, não
em CI de unit test).

Roda com:
    python -m unittest tests.test_backtest -v
"""

import inspect
import json
import re
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import backtest as bt  # noqa: E402


def _serie_sintetica(n_meses=220, seed=7):
    """Série mensal sintética, mesmas colunas de serie_subst.csv, com
    sazonalidade + ENSO fake — suficiente para exercitar todo o pipeline
    sem precisar do CSV real (mais rápido, e não depende de estado externo)."""
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


# Combinações (modelo, modo) esperadas em rodar_origem: 3 modelos só
# operacional_simulado (Climatologia, SeasonalNaive, SARIMA_sem_exog) + 2
# modelos com os 2 modos (SARIMAX_atual, XGBoost_atual) = 3 + 2*2 = 7
# combinações * 12 leads = 84 registros por origem.
COMBINACOES_ESPERADAS = {
    ('Climatologia', bt.MODO_OPERACIONAL), ('SeasonalNaive', bt.MODO_OPERACIONAL),
    ('SARIMA_sem_exog', bt.MODO_OPERACIONAL),
    ('SARIMAX_atual', bt.MODO_OPERACIONAL), ('SARIMAX_atual', bt.MODO_ORACLE),
    ('XGBoost_atual', bt.MODO_OPERACIONAL), ('XGBoost_atual', bt.MODO_ORACLE),
}


class GerarOrigensTestCase(unittest.TestCase):
    """Desenho da Seção 1 (Fase 1) + Seção 1 da Fase 1.1 (step=1 vs step=3)."""

    def test_primeira_origem_respeita_minimo_de_treino(self):
        serie = _serie_sintetica(n_meses=220)
        origens = bt.gerar_origens(serie, step=bt.STEP_TRIMESTRAL)
        primeiro_mes = serie['ym'].min()
        self.assertEqual(origens[0], primeiro_mes + (bt.MIN_TRAIN_MONTHS - 1))

    def test_ultima_origem_deixa_horizonte_completo(self):
        serie = _serie_sintetica(n_meses=220)
        origens = bt.gerar_origens(serie, step=bt.STEP_TRIMESTRAL)
        self.assertLessEqual(origens[-1] + bt.HORIZON, serie['ym'].max())

    def test_step1_gera_origens_mensais_consecutivas(self):
        """Teste 1 da Seção 10: step=1 produz origens mês a mês, sem pular
        nenhuma — cada par consecutivo difere em exatamente 1 mês."""
        serie = _serie_sintetica(n_meses=260)
        origens = bt.gerar_origens(serie, step=bt.STEP_MENSAL)
        self.assertGreater(len(origens), 1)
        for a, b in zip(origens, origens[1:]):
            self.assertEqual((b - a).n, 1)

    def test_step3_continua_reproduzivel(self):
        """Teste 2 da Seção 10: a config trimestral da Fase 1 não mudou —
        mesmas origens produzidas de forma determinística a cada chamada."""
        serie = _serie_sintetica(n_meses=260)
        origens_a = bt.gerar_origens(serie, step=bt.STEP_TRIMESTRAL)
        origens_b = bt.gerar_origens(serie, step=bt.STEP_TRIMESTRAL)
        self.assertEqual(origens_a, origens_b)
        for a, b in zip(origens_a, origens_a[1:]):
            self.assertEqual((b - a).n, 3)

    def test_step1_tem_mais_origens_que_step3_no_mesmo_periodo(self):
        serie = _serie_sintetica(n_meses=260)
        o1 = bt.gerar_origens(serie, step=bt.STEP_MENSAL)
        o3 = bt.gerar_origens(serie, step=bt.STEP_TRIMESTRAL)
        self.assertGreater(len(o1), len(o3))
        self.assertEqual(o1[0], o3[0])   # mesma primeira origem


class CorteLeakageSafeTestCase(unittest.TestCase):
    """Nenhuma observação futura entra no treino nem nos lags."""

    def test_cortar_serie_nao_inclui_meses_posteriores_a_origem(self):
        serie = _serie_sintetica(n_meses=220)
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        self.assertTrue((cortada['ym'] <= origem).all())
        self.assertNotIn(origem + 1, set(cortada['ym']))

    def test_lags_nao_acessam_periodo_posterior_a_origem(self):
        serie = _serie_sintetica(n_meses=220)
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        d = bt.construir_lags(cortada)
        self.assertTrue((d['ym'] <= origem).all())
        self.assertLessEqual(len(d), len(cortada))

    def test_lag23_bate_com_calculo_manual_apos_corte(self):
        serie = _serie_sintetica(n_meses=220)
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        d = bt.construir_lags(cortada)
        ultima = d[d['ym'] == origem].iloc[0]
        n34_by_ym = serie.set_index('ym')['nino34']
        esperado = (n34_by_ym[origem - 2] + n34_by_ym[origem - 3]) / 2
        self.assertAlmostEqual(ultima['n34_l23'], esperado, places=6)


class ExogenoFuturoTestCase(unittest.TestCase):
    """operacional_simulado nunca usa exógena futura real; oracle usa, e o
    resultado é diferente (rotulado corretamente — Fase 1.1 Seção 8)."""

    def setUp(self):
        self.serie = _serie_sintetica(n_meses=220)
        self.origem = self.serie['ym'].iloc[150]
        self.cortada = bt.cortar_serie(self.serie, self.origem)

    def test_operacional_nao_usa_serie_completa(self):
        exog_normal = bt.montar_exog_futuro(self.cortada, self.serie, self.origem, bt.MODO_OPERACIONAL)

        serie_corrompida = self.serie.copy()
        mask_futuro = serie_corrompida['ym'] > self.origem
        serie_corrompida.loc[mask_futuro, ['nino34', 'tsa', 'pdo']] = 9999.0

        exog_com_serie_corrompida = bt.montar_exog_futuro(
            self.cortada, serie_corrompida, self.origem, bt.MODO_OPERACIONAL)

        pd.testing.assert_frame_equal(exog_normal, exog_com_serie_corrompida)

    def test_oracle_usa_valores_futuros_reais_e_difere_do_operacional(self):
        exog_op = bt.montar_exog_futuro(self.cortada, self.serie, self.origem, bt.MODO_OPERACIONAL)
        exog_or = bt.montar_exog_futuro(self.cortada, self.serie, self.origem, bt.MODO_ORACLE)
        self.assertFalse(exog_op.equals(exog_or))

    def test_oracle_bate_com_serie_real_no_horizonte(self):
        exog_or = bt.montar_exog_futuro(self.cortada, self.serie, self.origem, bt.MODO_ORACLE)
        n34_real = self.serie.set_index('ym')['nino34']
        p1 = self.origem + 1
        esperado = (n34_real[p1 - 2] + n34_real[p1 - 3]) / 2
        self.assertAlmostEqual(exog_or.loc[p1, 'n34_l23'], esperado, places=6)

    def test_nomenclatura_modo_operacional_simulado_no_modulo(self):
        """Teste 11 da Seção 10: o nome usado nas saídas é
        'operacional_simulado', não mais o antigo 'operacional' puro."""
        self.assertEqual(bt.MODO_OPERACIONAL, 'operacional_simulado')
        self.assertEqual(bt.MODO_ORACLE, 'oracle_exog')


class ClimatologiaLeakageTestCase(unittest.TestCase):

    def test_climatologia_ignora_dado_posterior_a_origem(self):
        serie = _serie_sintetica(n_meses=220)
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        mes_alvo = (origem + 1).month
        media_manual = cortada[cortada['mes'] == mes_alvo]['prec'].mean()
        preds = bt.prever_climatologia(cortada, origem)
        self.assertAlmostEqual(preds[0], media_manual, places=6)


class SeasonalNaiveTestCase(unittest.TestCase):
    """Testes 4 e 5 da Seção 10: SeasonalNaive usa exatamente M-12 e nunca
    usa dado posterior à origem."""

    def test_seasonal_naive_usa_exatamente_m_menos_12(self):
        serie = _serie_sintetica(n_meses=220)
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        preds = bt.prever_seasonal_naive(cortada, origem)
        prec_by_ym = serie.set_index('ym')['prec']
        for lead in range(1, 13):
            p = origem + lead
            esperado = float(prec_by_ym[p - 12])
            self.assertAlmostEqual(preds[lead - 1], esperado, places=6,
                                    msg=f"lead {lead}: SeasonalNaive não bateu com observado em M-12")

    def test_seasonal_naive_nao_usa_dado_posterior_a_origem(self):
        """Contamina a série completa (não o corte) além da origem com
        valores absurdos — como SeasonalNaive só recebe serie_cortada,
        isso não pode mudar o resultado."""
        serie = _serie_sintetica(n_meses=220)
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        preds_normal = bt.prever_seasonal_naive(cortada, origem)

        cortada_e_futuro = serie.copy()
        mask_futuro = cortada_e_futuro['ym'] > origem
        cortada_e_futuro.loc[mask_futuro, 'prec'] = 999999.0
        cortada_recortada_de_novo = bt.cortar_serie(cortada_e_futuro, origem)
        preds_com_corte_correto = bt.prever_seasonal_naive(cortada_recortada_de_novo, origem)

        np.testing.assert_allclose(preds_normal, preds_com_corte_correto)
        self.assertTrue(np.all(preds_normal < 999999.0))

    def test_seasonal_naive_nao_usa_recursao(self):
        """A assinatura não tem nenhum estado que se acumule entre leads
        (diferente do XGBoost) — cada lead é um lookup independente."""
        params = list(inspect.signature(bt.prever_seasonal_naive).parameters)
        self.assertEqual(params, ['serie_cortada', 'origem'])


class XgbMultiStepTestCase(unittest.TestCase):

    def test_lead2_usa_previsao_do_lead1_no_buffer(self):
        class ModeloFake:
            def predict(self, X):
                return np.array([float(X['prec_l1'].iloc[0]) + 1.0])

        serie = _serie_sintetica(n_meses=220)
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        d = bt.construir_lags(cortada)
        exog = bt.montar_exog_futuro(cortada, serie, origem, bt.MODO_OPERACIONAL)

        preds = bt.prever_xgb_recursivo(ModeloFake(), d, exog)

        ultimo_real = d['prec'].iloc[-1]
        self.assertAlmostEqual(preds[0], ultimo_real + 1, places=6)
        self.assertAlmostEqual(preds[1], preds[0] + 1, places=6)
        self.assertAlmostEqual(preds[11], preds[10] + 1, places=6)

    def test_previsao_nao_usa_prec_observada_alem_da_origem(self):
        params = list(inspect.signature(bt.prever_xgb_recursivo).parameters)
        self.assertEqual(params, ['model', 'd_cortado', 'exog_futuro'])


class MesAlvoTestCase(unittest.TestCase):
    """Teste 3 da Seção 10: target_month (mes_alvo) deriva corretamente
    da data prevista."""

    def test_mes_alvo_bate_com_mes_da_data_prevista(self):
        serie = _serie_sintetica(n_meses=220)
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        registros, _, _, _ = bt.rodar_origem(serie, cortada, origem)
        for r in registros:
            p = pd.Period(r['data_prevista'], 'M')
            self.assertEqual(r['mes_alvo'], p.month)

    def test_metrics_by_target_month_agrupa_1_a_12(self):
        df = pd.DataFrame({
            'origem': ['2000-01'] * 24, 'lead': list(range(1, 13)) * 2,
            'mes_alvo': list(range(1, 13)) * 2,
            'observado': np.random.rand(24) * 100, 'previsto': np.random.rand(24) * 100,
            'modelo': ['Climatologia'] * 24, 'modo': [bt.MODO_OPERACIONAL] * 24,
        })
        resultado = bt.calcular_metricas_por_mes_alvo(df)
        meses = set(resultado['Climatologia'][bt.MODO_OPERACIONAL].keys())
        self.assertEqual(meses, {str(m) for m in range(1, 13)})


class MetricasTestCase(unittest.TestCase):

    def test_metrics_by_lead_tem_exatamente_leads_1_a_12(self):
        df = pd.DataFrame({
            'origem': ['2000-01'] * 12, 'lead': list(range(1, 13)),
            'mes_alvo': list(range(1, 13)),
            'observado': np.random.rand(12) * 100, 'previsto': np.random.rand(12) * 100,
            'modelo': ['Climatologia'] * 12, 'modo': [bt.MODO_OPERACIONAL] * 12,
        })
        by_lead, by_block, overall = bt.calcular_metricas(df)
        leads = set(by_lead['Climatologia'][bt.MODO_OPERACIONAL].keys())
        self.assertEqual(leads, {str(i) for i in range(1, 13)})

    def test_numero_de_previsoes_por_origem_e_correto(self):
        """Por origem: 7 combinações (modelo,modo) * 12 leads = 84
        (ver COMBINACOES_ESPERADAS, expandido na Fase 1.1 com SeasonalNaive)."""
        serie = _serie_sintetica(n_meses=220)
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        registros, diag, residuo, _ = bt.rodar_origem(serie, cortada, origem)
        self.assertEqual(len(registros), 84)
        combinacoes = {(r['modelo'], r['modo']) for r in registros}
        self.assertEqual(combinacoes, COMBINACOES_ESPERADAS)
        # diagnóstico de convergência: 1 registro por modelo que usa SARIMAX/SARIMA
        self.assertEqual({d['modelo'] for d in diag}, {'SARIMA_sem_exog', 'SARIMAX_atual'})
        self.assertIsNotNone(residuo)   # coletar_residuos=True por padrão


class ConvergenciaTestCase(unittest.TestCase):
    """Teste 8 da Seção 10: captura de convergência funciona mesmo quando
    converged=False."""

    def test_fit_diag_tem_campos_esperados_convergindo(self):
        serie = _serie_sintetica(n_meses=220)
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        preds, diag = bt.prever_sarima_sem_exog(cortada, origem)
        for campo in ['converged', 'iterations', 'optimizer', 'aic', 'llf']:
            self.assertIn(campo, diag)
        self.assertIsInstance(diag['converged'], bool)

    def test_diag_registra_nao_convergencia_com_maxiter_zero(self):
        """maxiter=0 força o otimizador a não rodar nenhuma iteração —
        caso controlado para garantir que converged=False é capturado e
        registrado, não escondido."""
        serie = _serie_sintetica(n_meses=220)
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        preds, diag = bt.prever_sarima_sem_exog(cortada, origem, maxiter=0)
        self.assertIn('converged', diag)
        self.assertFalse(diag['converged'])
        self.assertIsInstance(preds, np.ndarray)
        self.assertEqual(len(preds), bt.HORIZON)

    def test_resumo_convergencia_calcula_percentual(self):
        df_diag = pd.DataFrame([
            {'modelo': 'SARIMAX_atual', 'origem': '2000-01', 'converged': True},
            {'modelo': 'SARIMAX_atual', 'origem': '2000-04', 'converged': False},
        ])
        df_preds = pd.DataFrame({
            'origem': ['2000-01'] * 12 + ['2000-04'] * 12,
            'modelo': ['SARIMAX_atual'] * 24, 'modo': [bt.MODO_OPERACIONAL] * 24,
            'lead': list(range(1, 13)) * 2,
            'observado': np.random.rand(24) * 100, 'previsto': np.random.rand(24) * 100,
        })
        resumo = bt.resumo_convergencia(df_diag, df_preds)
        self.assertEqual(resumo['SARIMAX_atual']['n_fits'], 2)
        self.assertEqual(resumo['SARIMAX_atual']['n_convergentes'], 1)
        self.assertEqual(resumo['SARIMAX_atual']['pct_convergente'], 50.0)


class BootstrapCiTestCase(unittest.TestCase):
    """Testes 6 e 7 da Seção 10: block bootstrap reproduzível, IC ordenado."""

    def _df_para_bootstrap(self, n_origens=20, seed=3):
        rng = np.random.RandomState(seed)
        linhas = []
        for i in range(n_origens):
            origem = f'orig_{i:03d}'
            obs = rng.normal(100, 30, 12)
            prev_clim = obs + rng.normal(0, 20, 12)
            prev_modelo = obs + rng.normal(-2, 15, 12)   # levemente melhor
            for lead in range(1, 13):
                linhas.append({'origem': origem, 'lead': lead, 'mes_alvo': lead,
                                'observado': obs[lead - 1], 'previsto': prev_clim[lead - 1],
                                'modelo': 'Climatologia', 'modo': bt.MODO_OPERACIONAL})
                linhas.append({'origem': origem, 'lead': lead, 'mes_alvo': lead,
                                'observado': obs[lead - 1], 'previsto': prev_modelo[lead - 1],
                                'modelo': 'ModeloTeste', 'modo': bt.MODO_OPERACIONAL})
        return pd.DataFrame(linhas)

    def test_bootstrap_e_reproduzivel_com_seed_fixa(self):
        df = self._df_para_bootstrap()
        r1 = bt.bootstrap_ci_diff_rmse(df, 'ModeloTeste', n_boot=300, seed=42)
        r2 = bt.bootstrap_ci_diff_rmse(df, 'ModeloTeste', n_boot=300, seed=42)
        self.assertEqual(r1['diff_rmse_ic95'], r2['diff_rmse_ic95'])
        self.assertEqual(r1['skill_ic95'], r2['skill_ic95'])

    def test_seeds_diferentes_podem_dar_resultado_diferente(self):
        df = self._df_para_bootstrap()
        r1 = bt.bootstrap_ci_diff_rmse(df, 'ModeloTeste', n_boot=300, seed=1)
        r2 = bt.bootstrap_ci_diff_rmse(df, 'ModeloTeste', n_boot=300, seed=2)
        # não é garantido que sejam diferentes, mas o ponto central é sempre igual
        self.assertEqual(r1['diff_rmse_pontual'], r2['diff_rmse_pontual'])

    def test_ic_possui_limites_ordenados(self):
        df = self._df_para_bootstrap()
        r = bt.bootstrap_ci_diff_rmse(df, 'ModeloTeste', n_boot=500, seed=42)
        for chave in ['diff_rmse_ic95', 'diff_mae_ic95', 'skill_ic95']:
            lo, hi = r[chave]
            self.assertIsNotNone(lo)
            self.assertLessEqual(lo, hi, f"{chave}: limite inferior > superior")

    def test_bloco_de_reamostragem_e_a_origem(self):
        df = self._df_para_bootstrap()
        r = bt.bootstrap_ci_diff_rmse(df, 'ModeloTeste', n_boot=100, seed=42)
        self.assertIn('origem', r['bloco_de_reamostragem'])


class SerializacaoJsonTestCase(unittest.TestCase):

    def test_executar_backtest_gera_json_serializavel_com_schema_esperado(self):
        serie = _serie_sintetica(n_meses=220)
        origens = bt.gerar_origens(serie, step=bt.STEP_TRIMESTRAL)[:3]

        todos_registros, todos_diag, todos_residuos = [], [], []
        tempos = []
        for origem in origens:
            cortada = bt.cortar_serie(serie, origem)
            registros, diag, residuo, dt = bt.rodar_origem(serie, cortada, origem)
            todos_registros.extend(registros)
            todos_diag.extend(diag)
            if residuo is not None:
                todos_residuos.append(residuo)
            tempos.append(dt)
        df = pd.DataFrame(todos_registros)
        df_diag = pd.DataFrame(todos_diag)
        df_residuos = pd.DataFrame(todos_residuos)

        resultado = bt.montar_resultado(df, df_diag, df_residuos, tempos, serie, origens,
                                         step=bt.STEP_TRIMESTRAL, smoke=True)
        texto = json.dumps(resultado, ensure_ascii=False)
        de_volta = json.loads(texto)
        for chave in ['metadata', 'models', 'metrics_by_lead', 'metrics_by_horizon_block',
                      'overall_metrics', 'skill_vs_climatology', 'enso_regime_metrics',
                      'metrics_by_target_month', 'metrics_by_lead_and_target_month',
                      'convergence_diagnostics', 'residual_diagnostics']:
            self.assertIn(chave, de_volta)

    def test_csv_predictions_tem_colunas_minimas_exigidas(self):
        serie = _serie_sintetica(n_meses=220)
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        registros, _, _, _ = bt.rodar_origem(serie, cortada, origem)
        df = pd.DataFrame(registros)
        colunas_minimas = {'origem', 'data_prevista', 'lead', 'mes_alvo', 'observado', 'modelo',
                            'modo', 'previsto', 'erro', 'nino34_origem', 'classe_enso_origem'}
        self.assertTrue(colunas_minimas.issubset(set(df.columns)))


class ResultadosStepNaoSeSobrescrevemTestCase(unittest.TestCase):
    """Teste 10 da Seção 10: nomes de arquivo de step1 e step3 nunca colidem,
    e nenhum dos dois colide com os artefatos originais da Fase 1."""

    def test_nomes_de_arquivo_por_step_sao_distintos(self):
        nomes = set()
        for step in (1, 3):
            sufixo = f'_step{step}'
            nomes.add(f'backtest_results{sufixo}.json')
            nomes.add(f'backtest_predictions{sufixo}.csv')
        self.assertEqual(len(nomes), 4)   # nenhuma colisão
        # nenhum dos novos nomes é igual ao artefato original (sem sufixo)
        self.assertNotIn('backtest_results.json', nomes)
        self.assertNotIn('backtest_predictions.csv', nomes)

    def test_codigo_fonte_usa_sufixo_de_step_no_nome_de_saida(self):
        texto = (ROOT / 'scripts' / 'backtest.py').read_text(encoding='utf-8')
        self.assertIn("f'backtest_results{sufixo}.json'", texto)
        self.assertIn("f'backtest_predictions{sufixo}.csv'", texto)
        self.assertIn("sufixo = f'_step{args.step}'", texto)


class NaoAlteraProducaoTestCase(unittest.TestCase):

    def test_backtest_so_escreve_nos_arquivos_de_saida_permitidos(self):
        texto = (ROOT / 'scripts' / 'backtest.py').read_text(encoding='utf-8')
        alvos_permitidos = {"'backtest_results", "'backtest_predictions",
                             "'backtest_convergence", "'backtest_residuals",
                             "'backtest_optimizer_experiment.json'"}
        for m in re.finditer(r"(\w[\w.]*)\.(write_text|to_csv)\(", texto):
            trecho_antes = texto[max(0, m.start() - 400):m.start()]
            self.assertTrue(
                any(alvo in trecho_antes for alvo in alvos_permitidos),
                f"escrita em '{m.group(0)}' sem DATA/'backtest_*' nas 400 chars anteriores — "
                f"contexto: ...{trecho_antes[-200:]}")

    def test_snapshot_de_arquivos_de_producao_nao_muda_apos_rodar_pecas(self):
        alvos = ['data/serie_subst.csv', 'data/bh_final.json', 'data/fc_results_best.json',
                 'data/sarimax_data_best.json', 'data/master_monthly.csv', 'docs/index.html',
                 'data/backtest_results.json', 'data/backtest_predictions.csv']
        antes = {a: (ROOT / a).stat().st_mtime_ns for a in alvos if (ROOT / a).exists()}

        serie = _serie_sintetica(n_meses=220)
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        bt.rodar_origem(serie, cortada, origem)

        depois = {a: (ROOT / a).stat().st_mtime_ns for a in alvos if (ROOT / a).exists()}
        self.assertEqual(antes, depois)

    def test_experimento_optimizer_nao_altera_producao(self):
        """Teste 9 da Seção 10: rodar o experimento diagnóstico de
        otimizador (numa série sintética, subamostra mínima) não escreve
        em nenhum arquivo de produção."""
        alvos = ['data/serie_subst.csv', 'data/bh_final.json', 'data/fc_results_best.json',
                 'data/sarimax_data_best.json', 'data/master_monthly.csv', 'docs/index.html']
        antes = {a: (ROOT / a).stat().st_mtime_ns for a in alvos if (ROOT / a).exists()}

        serie = _serie_sintetica(n_meses=220)
        origens = bt.gerar_origens(serie, step=bt.STEP_MENSAL)[:2]
        resultados = bt.rodar_experimento_optimizer(serie, origens, verbose=False)
        bt.resumir_experimento_optimizer(serie, resultados, origens)

        depois = {a: (ROOT / a).stat().st_mtime_ns for a in alvos if (ROOT / a).exists()}
        self.assertEqual(antes, depois)


class SincroniaComProducaoTestCase(unittest.TestCase):
    """Garante que os hiperparâmetros do backtest não divergem em silêncio
    dos de update_dashboard.py — lendo o TEXTO-FONTE, nunca importando
    (importar update_dashboard.py executa o pipeline de produção inteiro)."""

    def test_ordem_sarimax_bate_com_producao(self):
        texto = bt.UPDATE_DASHBOARD_PATH.read_text(encoding='utf-8')
        o = bt.SARIMAX_ORDER
        so = bt.SARIMAX_SEASONAL_ORDER
        self.assertIn(f"order=({o[0]},{o[1]},{o[2]})", texto)
        self.assertIn(f"seasonal_order=({so[0]},{so[1]},{so[2]},{so[3]})", texto)

    def test_hiperparametros_xgboost_batem_com_producao(self):
        texto = bt.UPDATE_DASHBOARD_PATH.read_text(encoding='utf-8')
        for chave in ['n_estimators', 'max_depth', 'learning_rate', 'subsample',
                      'colsample_bytree', 'min_child_weight', 'gamma']:
            esperado = f"{chave}={bt.XGB_PARAMS[chave]}"
            self.assertIn(esperado, texto,
                           f"hiperparâmetro '{chave}' do backtest não bate com "
                           f"update_dashboard.py — checar se produção mudou")

    def test_construcao_de_lags_bate_com_producao(self):
        texto = bt.UPDATE_DASHBOARD_PATH.read_text(encoding='utf-8')
        self.assertIn("d['n34_l23'] = (d['n34_l2'] + d['n34_l3']) / 2", texto)
        self.assertIn("d['tsa_l23'] = (d['tsa_l2'] + d['tsa_l3']) / 2", texto)
        self.assertIn("d['pdo_l23'] = (d['pdo_l2'] + d['pdo_l3']) / 2", texto)

    def test_backtest_nunca_importa_update_dashboard(self):
        texto = (ROOT / 'scripts' / 'backtest.py').read_text(encoding='utf-8')
        self.assertNotIn('import update_dashboard', texto)
        self.assertNotIn('from update_dashboard', texto)

    def test_producao_nao_foi_tocada_pela_fase_1_1(self):
        """Confirma que nenhum dos scripts de produção listados como
        proibidos na Fase 1.1 (Seção 11) foi editado nesta tarefa — checagem
        estática simples: os arquivos existem e continuam sem nenhuma
        referência a backtest.py dentro deles (ninguém os fez importar o
        módulo de diagnóstico)."""
        proibidos = ['update_dashboard.py', 'update_indices.py', 'fetch_monthly_data.py']
        for nome in proibidos:
            caminho = ROOT / 'scripts' / nome
            self.assertTrue(caminho.exists())
            texto = caminho.read_text(encoding='utf-8')
            self.assertNotIn('backtest', texto.lower())


if __name__ == '__main__':
    unittest.main()
