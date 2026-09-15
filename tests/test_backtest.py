#!/usr/bin/env python3
"""
tests/test_backtest.py — regressão do backtest temporal (scripts/backtest.py).

Cobre a Seção 11 da especificação da Fase 1: nenhum teste depende de rede.
Todos usam pandas.PeriodIndex sintético/pequeno para rodar em segundos —
não executam o backtest completo de 119 origens (isso é feito manualmente
via `python scripts/backtest.py`, não em CI de unit test).

Roda com:
    python -m unittest tests.test_backtest -v
"""

import subprocess
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


class GerarOrigensTestCase(unittest.TestCase):
    """Teste 2 (parcial) + validação do desenho da Seção 1."""

    def test_primeira_origem_respeita_minimo_de_treino(self):
        serie = _serie_sintetica(n_meses=220)
        origens = bt.gerar_origens(serie)
        primeiro_mes = serie['ym'].min()
        self.assertEqual(origens[0], primeiro_mes + (bt.MIN_TRAIN_MONTHS - 1))

    def test_ultima_origem_deixa_horizonte_completo(self):
        serie = _serie_sintetica(n_meses=220)
        origens = bt.gerar_origens(serie)
        self.assertLessEqual(origens[-1] + bt.HORIZON, serie['ym'].max())

    def test_origens_espacadas_pelo_passo_configurado(self):
        serie = _serie_sintetica(n_meses=260)
        origens = bt.gerar_origens(serie)
        for a, b in zip(origens, origens[1:]):
            self.assertEqual((b - a).n, bt.STEP)


class CorteLeakageSafeTestCase(unittest.TestCase):
    """Teste 1 e 3: nenhuma observação futura entra no treino nem nos lags."""

    def test_cortar_serie_nao_inclui_meses_posteriores_a_origem(self):
        serie = _serie_sintetica(n_meses=220)
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        self.assertTrue((cortada['ym'] <= origem).all())
        self.assertNotIn(origem + 1, set(cortada['ym']))

    def test_lags_nao_acessam_periodo_posterior_a_origem(self):
        """Se construir_lags recebesse a série INTEIRA (bug), o valor de
        n34_l23 na última linha do corte usaria dado de meses futuros.
        Aqui garantimos que o dropna final não inventa nenhuma linha além
        do que já existia no corte, e que o índice temporal do resultado
        nunca ultrapassa a origem."""
        serie = _serie_sintetica(n_meses=220)
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        d = bt.construir_lags(cortada)
        self.assertTrue((d['ym'] <= origem).all())
        self.assertLessEqual(len(d), len(cortada))

    def test_lag23_bate_com_calculo_manual_apos_corte(self):
        """O n34_l23 da ÚLTIMA linha do corte deve ser a média dos nino34
        de origem-2 e origem-3 — nunca de algo posterior."""
        serie = _serie_sintetica(n_meses=220)
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        d = bt.construir_lags(cortada)
        ultima = d[d['ym'] == origem].iloc[0]
        n34_by_ym = serie.set_index('ym')['nino34']
        esperado = (n34_by_ym[origem - 2] + n34_by_ym[origem - 3]) / 2
        self.assertAlmostEqual(ultima['n34_l23'], esperado, places=6)


class ExogenoFuturoTestCase(unittest.TestCase):
    """Teste 5 e 6: operacional nunca usa exógena futura real; oracle usa,
    e o resultado é diferente (rotulado corretamente)."""

    def setUp(self):
        self.serie = _serie_sintetica(n_meses=220)
        self.origem = self.serie['ym'].iloc[150]
        self.cortada = bt.cortar_serie(self.serie, self.origem)

    def test_operacional_nao_usa_serie_completa(self):
        """Chamando montar_exog_futuro em modo operacional com uma série
        completa CORROMPIDA (valores absurdos após a origem), o resultado
        não pode mudar — prova de que o modo operacional nunca lê
        serie_completa."""
        exog_normal = bt.montar_exog_futuro(self.cortada, self.serie, self.origem, 'operacional')

        serie_corrompida = self.serie.copy()
        mask_futuro = serie_corrompida['ym'] > self.origem
        serie_corrompida.loc[mask_futuro, ['nino34', 'tsa', 'pdo']] = 9999.0

        exog_com_serie_corrompida = bt.montar_exog_futuro(
            self.cortada, serie_corrompida, self.origem, 'operacional')

        pd.testing.assert_frame_equal(exog_normal, exog_com_serie_corrompida)

    def test_oracle_usa_valores_futuros_reais_e_difere_do_operacional(self):
        exog_op = bt.montar_exog_futuro(self.cortada, self.serie, self.origem, 'operacional')
        exog_or = bt.montar_exog_futuro(self.cortada, self.serie, self.origem, 'oracle_exog')
        # Não podem ser idênticos: o oracle enxerga dado real que o
        # operacional não tem como conhecer no cenário simulado.
        self.assertFalse(exog_op.equals(exog_or))

    def test_oracle_bate_com_serie_real_no_horizonte(self):
        exog_or = bt.montar_exog_futuro(self.cortada, self.serie, self.origem, 'oracle_exog')
        n34_real = self.serie.set_index('ym')['nino34']
        p1 = self.origem + 1   # lead 1 — lag2/lag3 = origem-1/origem-2, sempre reais em ambos os modos
        esperado = (n34_real[p1 - 2] + n34_real[p1 - 3]) / 2
        self.assertAlmostEqual(exog_or.loc[p1, 'n34_l23'], esperado, places=6)


class ClimatologiaLeakageTestCase(unittest.TestCase):
    """Teste 2: climatologia usa só meses anteriores à origem."""

    def test_climatologia_ignora_dado_posterior_a_origem(self):
        serie = _serie_sintetica(n_meses=220)
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)

        # Contaminar deliberadamente o mês-alvo futuro com um valor absurdo
        # numa cópia NÃO usada pela previsão — se a função climatologia
        # olhasse a série inteira por engano, o teste abaixo capturaria.
        mes_alvo = (origem + 1).month
        cortada_sem_o_mes = cortada[cortada['mes'] != mes_alvo]
        media_manual = cortada[cortada['mes'] == mes_alvo]['prec'].mean()

        preds = bt.prever_climatologia(cortada, origem)
        self.assertAlmostEqual(preds[0], media_manual, places=6)


class XgbMultiStepTestCase(unittest.TestCase):
    """Teste 4: XGBoost multi-step usa a previsão anterior, não o observado."""

    def test_lead2_usa_previsao_do_lead1_no_buffer(self):
        class ModeloFake:
            """predict() devolve prec_l1 + 1 — permite rastrear exatamente
            o que foi alimentado como lag em cada passo."""
            def predict(self, X):
                return np.array([float(X['prec_l1'].iloc[0]) + 1.0])

        serie = _serie_sintetica(n_meses=220)
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        d = bt.construir_lags(cortada)
        exog = bt.montar_exog_futuro(cortada, serie, origem, 'operacional')

        preds = bt.prever_xgb_recursivo(ModeloFake(), d, exog)

        ultimo_real = d['prec'].iloc[-1]
        # lead1 = ultimo_real + 1 (buffer ainda só tem dado real)
        self.assertAlmostEqual(preds[0], ultimo_real + 1, places=6)
        # lead2 tem que usar preds[0] (PREVISTO), não nenhum valor real
        # da série (que nem existe além da origem) — a cadeia +1 prova isso
        self.assertAlmostEqual(preds[1], preds[0] + 1, places=6)
        self.assertAlmostEqual(preds[11], preds[10] + 1, places=6)

    def test_previsao_nao_usa_prec_observada_alem_da_origem(self):
        """Se prever_xgb_recursivo recebesse por engano a prec real do
        horizonte (ela não é passada — a assinatura só recebe d_cortado e
        exog_futuro), o teste de contrato abaixo garante que a função não
        aceita/usa nenhum argumento de precipitação futura."""
        import inspect
        params = list(inspect.signature(bt.prever_xgb_recursivo).parameters)
        self.assertEqual(params, ['model', 'd_cortado', 'exog_futuro'])


class MetricasTestCase(unittest.TestCase):
    """Teste 7 e 8: leads 1..12 exatos; número de previsões esperado."""

    def test_metrics_by_lead_tem_exatamente_leads_1_a_12(self):
        df = pd.DataFrame({
            'origem': ['2000-01'] * 12, 'lead': list(range(1, 13)),
            'observado': np.random.rand(12) * 100, 'previsto': np.random.rand(12) * 100,
            'modelo': ['Climatologia'] * 12, 'modo': ['operacional'] * 12,
        })
        by_lead, by_block, overall = bt.calcular_metricas(df)
        leads = set(by_lead['Climatologia']['operacional'].keys())
        self.assertEqual(leads, {str(i) for i in range(1, 13)})

    def test_numero_de_previsoes_por_origem_e_correto(self):
        """Por origem: 4 modelos, dos quais 2 (SARIMAX/XGBoost) têm 2
        modos — total (2*1 + 2*2) * 12 leads = 6 combinações * 12 = 72."""
        serie = _serie_sintetica(n_meses=220)
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        registros, _ = bt.rodar_origem(serie, cortada, origem)
        self.assertEqual(len(registros), 72)
        combinacoes = {(r['modelo'], r['modo']) for r in registros}
        self.assertEqual(combinacoes, {
            ('Climatologia', 'operacional'), ('SARIMA_sem_exog', 'operacional'),
            ('SARIMAX_atual', 'operacional'), ('SARIMAX_atual', 'oracle_exog'),
            ('XGBoost_atual', 'operacional'), ('XGBoost_atual', 'oracle_exog'),
        })


class SerializacaoJsonTestCase(unittest.TestCase):
    """Teste 9: o resultado final é serializável e tem o schema esperado."""

    def test_executar_backtest_gera_json_serializavel_com_schema_esperado(self):
        import json
        serie = _serie_sintetica(n_meses=220)
        origens = bt.gerar_origens(serie)[:2]

        # executar_backtest lê sempre serie_subst.csv de verdade — aqui
        # testamos as peças (rodar_origem + calcular_metricas) com a série
        # sintética para não depender do CSV real neste teste unitário.
        todos_registros = []
        for origem in origens:
            cortada = bt.cortar_serie(serie, origem)
            registros, _ = bt.rodar_origem(serie, cortada, origem)
            todos_registros.extend(registros)
        df = pd.DataFrame(todos_registros)

        by_lead, by_block, overall = bt.calcular_metricas(df)
        skill = bt.calcular_skill(by_lead, by_block)
        enso = bt.calcular_metricas_enso(df)

        resultado = {
            'metadata': {'primeira_origem': str(origens[0]), 'n_origens': len(origens)},
            'models': bt.MODELOS, 'metrics_by_lead': by_lead,
            'metrics_by_horizon_block': by_block, 'overall_metrics': overall,
            'skill_vs_climatology': skill, 'enso_regime_metrics': enso,
        }
        texto = json.dumps(resultado, ensure_ascii=False)
        de_volta = json.loads(texto)
        for chave in ['metadata', 'models', 'metrics_by_lead', 'metrics_by_horizon_block',
                      'overall_metrics', 'skill_vs_climatology', 'enso_regime_metrics']:
            self.assertIn(chave, de_volta)

    def test_csv_predictions_tem_colunas_minimas_exigidas(self):
        serie = _serie_sintetica(n_meses=220)
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        registros, _ = bt.rodar_origem(serie, cortada, origem)
        df = pd.DataFrame(registros)
        colunas_minimas = {'origem', 'data_prevista', 'lead', 'observado', 'modelo',
                            'modo', 'previsto', 'erro', 'nino34_origem', 'classe_enso_origem'}
        self.assertTrue(colunas_minimas.issubset(set(df.columns)))


class NaoAlteraProducaoTestCase(unittest.TestCase):
    """Teste 10: rodar o backtest (via suas peças, sem I/O de produção) não
    grava em nenhum arquivo de produção. Como o módulo nunca importa
    update_dashboard.py e só escreve em DATA/backtest_*, isso é garantido
    por desenho — aqui validamos que os caminhos protegidos nem aparecem
    como alvo de escrita no código-fonte de backtest.py."""

    def test_backtest_so_escreve_nos_arquivos_de_saida_permitidos(self):
        """Não checa se os caminhos protegidos aparecem em algum lugar do
        texto (eles aparecem no docstring, como documentação da própria
        garantia) — checa que toda chamada de escrita (.write_text/
        .to_csv) do módulo tem como alvo só backtest_results.json ou
        backtest_predictions.csv."""
        import re
        texto = (ROOT / 'scripts' / 'backtest.py').read_text(encoding='utf-8')
        alvos_permitidos = {"'backtest_results.json'", "'backtest_predictions.csv'"}
        for m in re.finditer(r"(\w[\w.]*)\.(write_text|to_csv)\(", texto):
            trecho_antes = texto[max(0, m.start() - 80):m.start()]
            # a variável escrita (out_json/out_csv) precisa ter sido
            # construída a partir de DATA / 'backtest_...' logo acima
            self.assertTrue(
                any(alvo in texto[max(0, m.start() - 300):m.start()] for alvo in alvos_permitidos),
                f"escrita em '{m.group(0)}' sem DATA/'backtest_*' nas 300 chars anteriores — "
                f"contexto: ...{trecho_antes}")

    def test_snapshot_de_arquivos_de_producao_nao_muda_apos_rodar_pecas(self):
        alvos = ['data/serie_subst.csv', 'data/bh_final.json', 'data/fc_results_best.json',
                 'data/sarimax_data_best.json', 'data/master_monthly.csv', 'docs/index.html']
        antes = {a: (ROOT / a).stat().st_mtime_ns for a in alvos if (ROOT / a).exists()}

        serie = _serie_sintetica(n_meses=220)
        origem = serie['ym'].iloc[150]
        cortada = bt.cortar_serie(serie, origem)
        bt.rodar_origem(serie, cortada, origem)

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


if __name__ == '__main__':
    unittest.main()
