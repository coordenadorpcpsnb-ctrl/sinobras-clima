#!/usr/bin/env python3
"""
tests/test_c3s_calibracao.py — regressão da climatologia/bias
leakage-safe da Fase 2A.3 (scripts/c3s_calibracao.py). Tudo offline,
puro (DataFrames sintéticos) — nenhum teste baixa nada.

Cobre a Seção 31 da tarefa (itens A, B, C, D, F — a auditoria
"confirmação não influencia desenvolvimento", item E, é um teste de
integração e está em tests/test_c3s_hindcast_completo.py, que tem
acesso ao pipeline completo).

Roda com:
    python -m unittest tests.test_c3s_calibracao -v
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import c3s_calibracao as calib  # noqa: E402


def _chirps_df(pares):
    """pares: lista de (target_month_str, valor)."""
    linhas = [{'target_month': pd.Period(tm, 'M'), 'chirps_prec_mm': v} for tm, v in pares]
    return pd.DataFrame(linhas, columns=['target_month', 'chirps_prec_mm'])


def _ens_df(pares):
    """pares: lista de (init_date_str, target_month_str, lead, ens_mean_raw)."""
    linhas = [{'init_date': pd.Period(i, 'M'), 'target_month': pd.Period(t, 'M'), 'lead': lead,
               'ens_mean_raw': v} for i, t, lead, v in pares]
    return pd.DataFrame(linhas, columns=['init_date', 'target_month', 'lead', 'ens_mean_raw'])


# ══════════════════════════════════════════════════════════════════════════
# Climatologia leakage-safe
# ══════════════════════════════════════════════════════════════════════════

class ClimatologiaLeakageSafeTestCase(unittest.TestCase):

    def test_usa_so_anos_anteriores_mesmo_mes_calendario(self):
        chirps = _chirps_df([('1981-01', 100), ('1982-01', 200), ('1981-02', 999)])   # fev não entra
        r = calib.climatologia_leakage_safe(chirps, pd.Period('1990-01', 'M'), mes_alvo_calendario=1,
                                             min_anos_treino=1)
        self.assertAlmostEqual(r['mean'], 150.0)
        self.assertEqual(r['n'], 2)

    def test_d_nunca_usa_a_propria_observacao_do_alvo(self):
        """Item D da Seção 31: a observação do próprio target_month nunca
        entra na climatologia, mesmo que já exista na série completa —
        aqui o 'alvo' é jan/1990, presente em chirps, mas a origem é
        1990-01 (a previsão é emitida ANTES de jan/1990 acontecer)."""
        chirps = _chirps_df([('1988-01', 100), ('1989-01', 100), ('1990-01', 999999)])
        r = calib.climatologia_leakage_safe(chirps, pd.Period('1990-01', 'M'), mes_alvo_calendario=1,
                                             min_anos_treino=1)
        self.assertEqual(r['n'], 2)
        self.assertAlmostEqual(r['mean'], 100.0)

    def test_a_alterar_chirps_futuro_nao_muda_climatologia_passada(self):
        """Item A da Seção 31: contaminar o FUTURO com um valor absurdo
        não pode mudar uma climatologia já calculada para uma origem
        passada."""
        chirps_normal = _chirps_df([('1981-01', 100), ('1982-01', 120), ('1995-01', 300)])
        chirps_contaminada = _chirps_df([('1981-01', 100), ('1982-01', 120), ('1995-01', 9999999)])
        origem = pd.Period('1985-01', 'M')   # 1995 é futuro em relação a 1985
        r_normal = calib.climatologia_leakage_safe(chirps_normal, origem, 1, min_anos_treino=1)
        r_contaminada = calib.climatologia_leakage_safe(chirps_contaminada, origem, 1, min_anos_treino=1)
        self.assertEqual(r_normal, r_contaminada)

    def test_f_terciles_seguem_a_mesma_regra_past_only(self):
        """Item F da Seção 31: p33/p67 (usados como thresholds de
        tercil) vêm da mesma chamada leakage-safe — contaminar o futuro
        não muda os thresholds de uma origem passada."""
        chirps_normal = _chirps_df([('1981-01', 50), ('1982-01', 100), ('1983-01', 150), ('1990-01', 400)])
        chirps_contaminada = _chirps_df([('1981-01', 50), ('1982-01', 100), ('1983-01', 150), ('1990-01', -999)])
        origem = pd.Period('1985-01', 'M')
        r_normal = calib.climatologia_leakage_safe(chirps_normal, origem, 1, min_anos_treino=1)
        r_contaminada = calib.climatologia_leakage_safe(chirps_contaminada, origem, 1, min_anos_treino=1)
        self.assertEqual(r_normal['p33'], r_contaminada['p33'])
        self.assertEqual(r_normal['p67'], r_contaminada['p67'])

    def test_sem_nenhum_ano_anterior_devolve_none(self):
        chirps = _chirps_df([('1981-01', 100)])
        r = calib.climatologia_leakage_safe(chirps, pd.Period('1981-01', 'M'), mes_alvo_calendario=1)
        self.assertEqual(r['n'], 0)
        self.assertIsNone(r['mean'])
        self.assertEqual(r['status'], calib.STATUS_SEM_HISTORICO)

    def test_min_anos_treino_marca_status(self):
        chirps = _chirps_df([(f'{a}-01', 100) for a in range(1981, 1989)])   # 8 anos
        r = calib.climatologia_leakage_safe(chirps, pd.Period('1990-01', 'M'), mes_alvo_calendario=1,
                                             min_anos_treino=10)
        self.assertEqual(r['n'], 8)
        self.assertIsNotNone(r['mean'])   # calcula mesmo com n<10 — só o status muda
        self.assertEqual(r['status'], calib.STATUS_SEM_HISTORICO)

    def test_min_anos_treino_exato_e_status_ok(self):
        chirps = _chirps_df([(f'{a}-01', 100) for a in range(1981, 1991)])   # 10 anos
        r = calib.climatologia_leakage_safe(chirps, pd.Period('1991-01', 'M'), mes_alvo_calendario=1,
                                             min_anos_treino=10)
        self.assertEqual(r['n'], 10)
        self.assertEqual(r['status'], calib.STATUS_OK)

    def test_todas_as_estatisticas_presentes(self):
        chirps = _chirps_df([(f'{a}-06', 50 + a) for a in range(1981, 1991)])
        r = calib.climatologia_leakage_safe(chirps, pd.Period('1995-06', 'M'), mes_alvo_calendario=6)
        for chave in ('mean', 'median', 'p20', 'p33', 'p67', 'p80', 'n', 'status'):
            self.assertIn(chave, r)


# ══════════════════════════════════════════════════════════════════════════
# Bias correction leakage-safe
# ══════════════════════════════════════════════════════════════════════════

class BiasLeakageSafeTestCase(unittest.TestCase):

    def test_bias_e_media_previsto_menos_observado_so_passado(self):
        ens = _ens_df([
            ('1981-01', '1981-01', 1, 110.0), ('1982-01', '1982-01', 1, 130.0),
        ])
        chirps = _chirps_df([('1981-01', 100.0), ('1982-01', 100.0)])
        r = calib.bias_leakage_safe(ens, chirps, pd.Period('1990-01', 'M'), mes_alvo_calendario=1, lead=1,
                                     min_anos_treino=1)
        # bias = mean((110-100),(130-100)) = mean(10,30) = 20
        self.assertAlmostEqual(r['bias_mm'], 20.0)
        self.assertEqual(r['n'], 2)

    def test_c_propria_origem_nunca_entra_no_bias(self):
        """Item C da Seção 31: init_date == origem nunca entra, mesmo que
        exista em ens_df."""
        ens = _ens_df([('1990-01', '1990-01', 1, 999999.0)])   # a própria origem avaliada
        chirps = _chirps_df([('1990-01', 100.0)])
        r = calib.bias_leakage_safe(ens, chirps, pd.Period('1990-01', 'M'), mes_alvo_calendario=1, lead=1)
        self.assertEqual(r['n'], 0)
        self.assertIsNone(r['bias_mm'])

    def test_origem_posterior_tambem_nunca_entra(self):
        ens = _ens_df([('1995-01', '1995-01', 1, 999999.0)])   # origem POSTERIOR à avaliada
        chirps = _chirps_df([('1995-01', 100.0)])
        r = calib.bias_leakage_safe(ens, chirps, pd.Period('1990-01', 'M'), mes_alvo_calendario=1, lead=1)
        self.assertEqual(r['n'], 0)

    def test_b_alterar_hindcast_futuro_nao_muda_bias_passado(self):
        """Item B da Seção 31: contaminar um hindcast FUTURO com um valor
        absurdo não muda o bias já calculado para uma origem passada."""
        chirps = _chirps_df([('1981-01', 100.0), ('1982-01', 100.0), ('1995-01', 100.0)])
        ens_normal = _ens_df([
            ('1981-01', '1981-01', 1, 110.0), ('1982-01', '1982-01', 1, 120.0),
            ('1995-01', '1995-01', 1, 130.0),
        ])
        ens_contaminado = _ens_df([
            ('1981-01', '1981-01', 1, 110.0), ('1982-01', '1982-01', 1, 120.0),
            ('1995-01', '1995-01', 1, 99999999.0),
        ])
        origem = pd.Period('1985-01', 'M')   # 1995 é futuro em relação a 1985
        r_normal = calib.bias_leakage_safe(ens_normal, chirps, origem, 1, 1, min_anos_treino=1)
        r_contaminado = calib.bias_leakage_safe(ens_contaminado, chirps, origem, 1, 1, min_anos_treino=1)
        self.assertEqual(r_normal, r_contaminado)

    def test_estratificado_por_lead(self):
        """Mesmo mês-alvo, leads diferentes -> bias diferente (nunca
        misturar leads no mesmo cálculo)."""
        ens = _ens_df([
            ('1981-01', '1981-01', 1, 110.0), ('1980-12', '1981-01', 2, 200.0),
        ])
        chirps = _chirps_df([('1981-01', 100.0)])
        r_lead1 = calib.bias_leakage_safe(ens, chirps, pd.Period('1990-01', 'M'), 1, lead=1, min_anos_treino=1)
        r_lead2 = calib.bias_leakage_safe(ens, chirps, pd.Period('1990-01', 'M'), 1, lead=2, min_anos_treino=1)
        self.assertAlmostEqual(r_lead1['bias_mm'], 10.0)
        self.assertAlmostEqual(r_lead2['bias_mm'], 100.0)

    def test_sem_par_disponivel_devolve_none(self):
        ens = _ens_df([])
        chirps = _chirps_df([])
        r = calib.bias_leakage_safe(ens, chirps, pd.Period('1990-01', 'M'), 1, lead=1)
        self.assertEqual(r['n'], 0)
        self.assertIsNone(r['bias_mm'])
        self.assertEqual(r['status'], calib.STATUS_SEM_HISTORICO)

    def test_min_anos_treino_marca_status_sem_impedir_calculo(self):
        ens = _ens_df([(f'{a}-01', f'{a}-01', 1, 110.0) for a in range(1981, 1986)])   # 5 anos
        chirps = _chirps_df([(f'{a}-01', 100.0) for a in range(1981, 1986)])
        r = calib.bias_leakage_safe(ens, chirps, pd.Period('1990-01', 'M'), 1, lead=1, min_anos_treino=10)
        self.assertEqual(r['n'], 5)
        self.assertAlmostEqual(r['bias_mm'], 10.0)   # calculado mesmo com n<10
        self.assertEqual(r['status'], calib.STATUS_SEM_HISTORICO)


# ══════════════════════════════════════════════════════════════════════════
# Correção por membro (Seção 12)
# ══════════════════════════════════════════════════════════════════════════

class AplicarBiasAMembroTestCase(unittest.TestCase):

    def test_subtrai_o_bias(self):
        self.assertAlmostEqual(calib.aplicar_bias_a_membro(100.0, 20.0), 80.0)

    def test_bias_negativo_soma(self):
        self.assertAlmostEqual(calib.aplicar_bias_a_membro(100.0, -20.0), 120.0)

    def test_nunca_fica_negativo(self):
        """Precipitação negativa não é física (Seção 12) — sempre
        max(0, corrigido)."""
        self.assertEqual(calib.aplicar_bias_a_membro(10.0, 50.0), 0.0)

    def test_zero_e_o_piso_exato(self):
        self.assertEqual(calib.aplicar_bias_a_membro(10.0, 10.0), 0.0)


if __name__ == '__main__':
    unittest.main()
