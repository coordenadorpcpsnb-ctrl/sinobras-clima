#!/usr/bin/env python3
"""
tests/test_c3s_skill.py — regressão das métricas de skill e bootstrap
da Fase 2A.3 (scripts/c3s_skill.py). Tudo offline, puro — nenhum teste
baixa nada.

Cobre as Seções 32 (fixtures sintéticas com resultado conhecido para
RMSE/MAE/Bias/MSESS/Brier/BSS/RPS/RPSS) e 33 (bootstrap) da tarefa.

Roda com:
    python -m unittest tests.test_c3s_skill -v
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import c3s_hindcast as hc  # noqa: E402
import c3s_skill as skill  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════
# MSE/MSESS — novo nesta fase (RMSESS já era testado via
# c3s_hindcast.py::skill_vs_climatologia, reaproveitado aqui como está)
# ══════════════════════════════════════════════════════════════════════════

class MseMsessTestCase(unittest.TestCase):

    def test_previsao_perfeita_erro_zero(self):
        self.assertAlmostEqual(skill.mse([10, 20, 30], [10, 20, 30]), 0.0)

    def test_mse_bate_com_formula_manual(self):
        o, p = [10, 20, 30], [12, 18, 33]
        esperado = np.mean([(10 - 12) ** 2, (20 - 18) ** 2, (30 - 33) ** 2])
        self.assertAlmostEqual(skill.mse(o, p), esperado)

    def test_modelo_igual_climatologia_skill_zero(self):
        self.assertAlmostEqual(skill.msess(50.0, 50.0), 0.0)

    def test_modelo_pior_skill_negativo(self):
        r = skill.msess(mse_modelo=100.0, mse_climatologia=50.0)
        self.assertLess(r, 0)

    def test_modelo_melhor_skill_positivo(self):
        r = skill.msess(mse_modelo=25.0, mse_climatologia=50.0)
        self.assertGreater(r, 0)

    def test_modelo_perfeito_skill_um(self):
        self.assertAlmostEqual(skill.msess(mse_modelo=0.0, mse_climatologia=50.0), 1.0)

    def test_climatologia_zero_devolve_none(self):
        self.assertIsNone(skill.msess(10.0, 0.0))


# ══════════════════════════════════════════════════════════════════════════
# tabela_skill_deterministico — reaproveita c3s_hindcast.py, orquestra
# CLIM/RAW/BC (Seção 15-17)
# ══════════════════════════════════════════════════════════════════════════

class TabelaSkillDeterministicoTestCase(unittest.TestCase):

    def test_raw_e_bc_perfeitos_dao_skill_um(self):
        df = pd.DataFrame({
            'chirps_prec_mm': [100.0, 150.0, 80.0],
            'climatological_mean': [90.0, 140.0, 85.0],
            'ens_mean_raw': [100.0, 150.0, 80.0],
            'ens_mean_bc': [100.0, 150.0, 80.0],
        })
        r = skill.tabela_skill_deterministico(df)
        self.assertAlmostEqual(r['rmse_raw'], 0.0)
        self.assertAlmostEqual(r['msess_raw'], 1.0)
        self.assertAlmostEqual(r['msess_bc'], 1.0)

    def test_raw_igual_a_clim_da_skill_zero(self):
        df = pd.DataFrame({
            'chirps_prec_mm': [100.0, 150.0, 80.0, 120.0],
            'climatological_mean': [90.0, 140.0, 85.0, 110.0],
            'ens_mean_raw': [90.0, 140.0, 85.0, 110.0],   # RAW == CLIM
            'ens_mean_bc': [100.0, 150.0, 80.0, 120.0],
        })
        r = skill.tabela_skill_deterministico(df)
        self.assertAlmostEqual(r['msess_raw'], 0.0, places=6)

    def test_raw_pior_que_clim_da_skill_negativo(self):
        df = pd.DataFrame({
            'chirps_prec_mm': [100.0, 150.0, 80.0, 120.0],
            'climatological_mean': [95.0, 145.0, 85.0, 115.0],
            'ens_mean_raw': [300.0, 10.0, 400.0, 5.0],   # bem pior
            'ens_mean_bc': [95.0, 145.0, 85.0, 115.0],
        })
        r = skill.tabela_skill_deterministico(df)
        self.assertLess(r['msess_raw'], 0)

    def test_vazio_nao_quebra(self):
        df = pd.DataFrame({'chirps_prec_mm': [], 'climatological_mean': [],
                            'ens_mean_raw': [], 'ens_mean_bc': []})
        r = skill.tabela_skill_deterministico(df)
        self.assertEqual(r['n'], 0)
        self.assertIsNone(r['rmse_raw'])


# ══════════════════════════════════════════════════════════════════════════
# Brier/BSS/RPS/RPSS — orquestração; a fórmula em si já é testada em
# test_c3s.py::BrierScoreTestCase (c3s_hindcast.py). Aqui: previsão
# perfeita, climatologia (skill 0) e pior que climatologia (skill < 0).
# ══════════════════════════════════════════════════════════════════════════

class TabelaSkillProbabilisticoTestCase(unittest.TestCase):

    def _df_base(self, prob_raw, prob_bc):
        n = len(prob_raw)
        return pd.DataFrame({
            'chirps_prec_mm': [10.0, 50.0, 90.0, 10.0][:n],   # 2 "abaixo"(<p33), 1 "acima"(>p67), 1 "abaixo"
            'clim_p33': [30.0] * n, 'clim_p67': [70.0] * n,
            'prob_below_raw': [p[0] for p in prob_raw], 'prob_normal_raw': [p[1] for p in prob_raw],
            'prob_above_raw': [p[2] for p in prob_raw],
            'prob_below_bc': [p[0] for p in prob_bc], 'prob_normal_bc': [p[1] for p in prob_bc],
            'prob_above_bc': [p[2] for p in prob_bc],
        })

    def test_previsao_perfeita_brier_zero_bss_um(self):
        # observado: 10(abaixo),50(normal),90(acima),10(abaixo)
        probs_perfeitas = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 0, 0)]
        df = self._df_base(probs_perfeitas, probs_perfeitas)
        r = skill.tabela_skill_probabilistico(df)
        self.assertAlmostEqual(r['bs_raw_abaixo'], 0.0)
        self.assertAlmostEqual(r['bs_raw_acima'], 0.0)
        self.assertAlmostEqual(r['bss_raw_abaixo'], 1.0)
        self.assertAlmostEqual(r['rpss_raw'], 1.0, places=4)

    def test_previsao_igual_climatologia_da_skill_proximo_de_zero(self):
        probs_clim = [(1 / 3, 1 / 3, 1 / 3)] * 4
        df = self._df_base(probs_clim, probs_clim)
        r = skill.tabela_skill_probabilistico(df)
        self.assertAlmostEqual(r['bss_raw_abaixo'], 0.0, places=6)
        self.assertAlmostEqual(r['bss_raw_acima'], 0.0, places=6)
        self.assertAlmostEqual(r['rpss_raw'], 0.0, places=6)

    def test_previsao_oposta_da_skill_negativo(self):
        # sempre aposta no oposto do que aconteceu
        probs_opostas = [(0, 0, 1), (1, 0, 0), (1, 0, 0), (0, 0, 1)]
        df = self._df_base(probs_opostas, probs_opostas)
        r = skill.tabela_skill_probabilistico(df)
        self.assertLess(r['rpss_raw'], 0)

    def test_vazio_nao_quebra(self):
        df = self._df_base([], [])
        r = skill.tabela_skill_probabilistico(df)
        self.assertEqual(r['n'], 0)


# ══════════════════════════════════════════════════════════════════════════
# CRPS empírico (Seção 22, opcional/best-effort)
# ══════════════════════════════════════════════════════════════════════════

class CrpsTestCase(unittest.TestCase):

    def test_ensemble_degenerado_igual_observacao_e_zero(self):
        """Todos os membros == observação -> CRPS = 0 (previsão perfeita
        e sem dispersão)."""
        r = skill.crps_empirico([100.0] * 10, 100.0)
        self.assertAlmostEqual(r, 0.0)

    def test_crps_nao_negativo(self):
        r = skill.crps_empirico([80.0, 90.0, 100.0, 110.0, 120.0], 95.0)
        self.assertGreaterEqual(r, 0.0)

    def test_ensemble_vazio_devolve_none(self):
        self.assertIsNone(skill.crps_empirico([], 100.0))

    def test_crpss_modelo_melhor_positivo(self):
        r = skill.crpss(crps_modelo=5.0, crps_climatologia=10.0)
        self.assertGreater(r, 0)

    def test_crpss_modelo_pior_negativo(self):
        r = skill.crpss(crps_modelo=20.0, crps_climatologia=10.0)
        self.assertLess(r, 0)


# ══════════════════════════════════════════════════════════════════════════
# Bootstrap (Seção 24/33)
# ══════════════════════════════════════════════════════════════════════════

def _df_bootstrap(anos, ruido_modelo=0.0, ruido_clim=40.0, seed_dado=0):
    """Constrói um dataset sintético com sinal sazonal onde RAW é bem
    melhor que CLIM (para ter um MSESS positivo claro e testável)."""
    rng = np.random.RandomState(seed_dado)
    linhas = []
    for ano in anos:
        for mes in range(1, 13):
            obs = 100 + 50 * np.sin(mes / 12 * 2 * np.pi) + rng.normal(0, 5)
            modelo = obs + rng.normal(0, ruido_modelo) if ruido_modelo else obs
            clim = 100 + rng.normal(0, ruido_clim)   # clim não captura sazonalidade
            linhas.append({'init_year': ano, 'chirps_prec_mm': obs, 'climatological_mean': clim,
                            'ens_mean_raw': modelo})
    return pd.DataFrame(linhas)


class BootstrapSkillTestCase(unittest.TestCase):

    def test_seed_reproduzivel_mesmo_dataset_mesmo_resultado(self):
        df = _df_bootstrap(range(1991, 2006))
        r1 = skill.bootstrap_skill(df, 'init_year', 'chirps_prec_mm', 'climatological_mean', 'ens_mean_raw',
                                    n_replicacoes=500, seed=7)
        r2 = skill.bootstrap_skill(df, 'init_year', 'chirps_prec_mm', 'climatological_mean', 'ens_mean_raw',
                                    n_replicacoes=500, seed=7)
        self.assertEqual(r1, r2)

    def test_seeds_diferentes_podem_dar_replicas_diferentes_mas_mesma_estimativa_pontual(self):
        df = _df_bootstrap(range(1991, 2006))
        r1 = skill.bootstrap_skill(df, 'init_year', 'chirps_prec_mm', 'climatological_mean', 'ens_mean_raw',
                                    n_replicacoes=500, seed=1)
        r2 = skill.bootstrap_skill(df, 'init_year', 'chirps_prec_mm', 'climatological_mean', 'ens_mean_raw',
                                    n_replicacoes=500, seed=2)
        # estimativa pontual não depende da seed (é sobre o dataset inteiro, não uma réplica)
        self.assertAlmostEqual(r1['estimativa'], r2['estimativa'])

    def test_numero_de_replicacoes_respeitado(self):
        df = _df_bootstrap(range(1991, 2001))
        r = skill.bootstrap_skill(df, 'init_year', 'chirps_prec_mm', 'climatological_mean', 'ens_mean_raw',
                                   n_replicacoes=2000, seed=42)
        self.assertEqual(r['n_replicacoes'], 2000)

    def test_reamostragem_e_por_ano_nao_por_linha(self):
        """Se a reamostragem fosse por linha (não por ano), o nº de anos
        distintos usados mudaria a cada réplica de forma incompatível
        com preservar meses/leads dentro do ano — aqui só confirmamos
        que n_anos bate com o nº de anos únicos do dataset."""
        anos = list(range(1991, 2001))
        df = _df_bootstrap(anos)
        r = skill.bootstrap_skill(df, 'init_year', 'chirps_prec_mm', 'climatological_mean', 'ens_mean_raw',
                                   n_replicacoes=200, seed=42)
        self.assertEqual(r['n_anos'], len(anos))

    def test_ic_contem_a_estimativa_pontual_em_amostra_grande_com_sinal_claro(self):
        df = _df_bootstrap(range(1991, 2016), ruido_modelo=2.0, ruido_clim=60.0)
        r = skill.bootstrap_skill(df, 'init_year', 'chirps_prec_mm', 'climatological_mean', 'ens_mean_raw',
                                   n_replicacoes=2000, seed=42)
        self.assertLessEqual(r['ic95_inferior'], r['estimativa'])
        self.assertLessEqual(r['estimativa'], r['ic95_superior'])

    def test_ic_nao_cruza_zero_e_conclusivo_quando_sinal_e_forte(self):
        df = _df_bootstrap(range(1991, 2016), ruido_modelo=2.0, ruido_clim=60.0)
        r = skill.bootstrap_skill(df, 'init_year', 'chirps_prec_mm', 'climatological_mean', 'ens_mean_raw',
                                   n_replicacoes=2000, seed=42)
        self.assertGreater(r['ic95_inferior'], 0)
        self.assertTrue(r['conclusivo'])

    def test_ic_cruza_zero_e_nao_conclusivo_quando_modelo_igual_clim(self):
        rng = np.random.RandomState(0)
        linhas = []
        for ano in range(1991, 2006):
            for mes in range(1, 13):
                obs = 100 + rng.normal(0, 30)
                linhas.append({'init_year': ano, 'chirps_prec_mm': obs,
                                'climatological_mean': obs + rng.normal(0, 1),
                                'ens_mean_raw': obs + rng.normal(0, 1)})   # RAW ~ CLIM, mesmo ruído
        df = pd.DataFrame(linhas)
        r = skill.bootstrap_skill(df, 'init_year', 'chirps_prec_mm', 'climatological_mean', 'ens_mean_raw',
                                   n_replicacoes=1000, seed=3)
        self.assertLessEqual(r['ic95_inferior'], 0)
        self.assertGreaterEqual(r['ic95_superior'], 0)
        self.assertFalse(r['conclusivo'])

    def test_dataset_vazio_nao_quebra(self):
        df = pd.DataFrame({'init_year': [], 'chirps_prec_mm': [], 'climatological_mean': [], 'ens_mean_raw': []})
        r = skill.bootstrap_skill(df, 'init_year', 'chirps_prec_mm', 'climatological_mean', 'ens_mean_raw')
        self.assertEqual(r['n_anos'], 0)
        self.assertIsNone(r['estimativa'])
        self.assertFalse(r['conclusivo'])


if __name__ == '__main__':
    unittest.main()
