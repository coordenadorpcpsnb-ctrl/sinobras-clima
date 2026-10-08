#!/usr/bin/env python3
"""
tests/test_cfsv2_emos_h2_viabilidade_warmup.py — Fase 2C.3D, protocolo
EMOS H2: cobre só a viabilidade ESTRUTURAL do warm-up (nenhum ajuste
de parâmetro, nenhum CRPS/skill é calculado por este módulo).

Roda com:
    python -m unittest tests.test_cfsv2_emos_h2_viabilidade_warmup -v
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import cfsv2_emos_h2_viabilidade_warmup as w  # noqa: E402
import cfsv2_validacao_cientifica as v  # noqa: E402


class IndiceCausalPorMesTestCase(unittest.TestCase):

    def test_a_nunca_inclui_a_propria_inicializacao_nem_futuras(self):
        tabela = pd.DataFrame([
            {'init_date': '2000-01', 'lead': 2, 'ensemble_std': 10.0},
            {'init_date': '2001-01', 'lead': 2, 'ensemble_std': 20.0},
            {'init_date': '2002-01', 'lead': 2, 'ensemble_std': 30.0},
        ])
        calc = w._indice_causal_por_mes(tabela, 2, 'ensemble_std')
        valores = calc('2001-01').tolist()
        self.assertEqual(valores, [10.0])
        valores_primeira = calc('2000-01').tolist()
        self.assertEqual(valores_primeira, [])

    def test_b_so_mesmo_mes_calendario(self):
        tabela = pd.DataFrame([
            {'init_date': '2000-01', 'lead': 2, 'ensemble_std': 10.0},
            {'init_date': '2000-06', 'lead': 2, 'ensemble_std': 999.0},
            {'init_date': '2001-01', 'lead': 2, 'ensemble_std': 20.0},
        ])
        calc = w._indice_causal_por_mes(tabela, 2, 'ensemble_std')
        valores = calc('2002-01').tolist()
        self.assertEqual(sorted(valores), [10.0, 20.0])


class ViabilidadeEstruturalTestCase(unittest.TestCase):

    def _pares_sinteticos(self, validos):
        """`validos` é uma lista de bools na ordem causal — constrói
        um DataFrame `pares` mínimo só com a coluna necessária para
        `viabilidade_estrutural_h2`."""
        linhas = [{'init_date': f'{2000 + i // 12}-{(i % 12) + 1:02d}', 'valido': v_}
                  for i, v_ in enumerate(validos)]
        return pd.DataFrame(linhas)

    def test_a_primeira_elegivel_e_a_linha_apos_atingir_o_treino_minimo(self):
        # 5 válidos seguidos de resto — com n_treino_minimo=3, a 4a
        # linha (índice 3) é a primeira com 3 válidas ANTES dela.
        pares = self._pares_sinteticos([True, True, True, True, True])
        resultado = w.viabilidade_estrutural_h2(pares, n_treino_minimo=3)
        self.assertEqual(resultado['n_treino_disponivel_nessa_data'], 3)
        self.assertEqual(resultado['primeira_init_date_elegivel'], pares['init_date'].iloc[3])

    def test_b_n_previsoes_avaliaveis_bate_com_contagem_manual(self):
        validos = [True, True, True, False, True, True, True, True]
        pares = self._pares_sinteticos(validos)
        resultado = w.viabilidade_estrutural_h2(pares, n_treino_minimo=3)
        n_treino_disponivel = pd.Series(validos).shift(1, fill_value=False).astype(int).cumsum()
        elegiveis = n_treino_disponivel >= 3
        esperado = int((elegiveis & pd.Series(validos)).sum())
        self.assertEqual(resultado['n_previsoes_avaliaveis_final'], esperado)

    def test_c_nenhum_parametro_emos_e_mencionado_no_resultado(self):
        pares = self._pares_sinteticos([True] * 10)
        resultado = w.viabilidade_estrutural_h2(pares, n_treino_minimo=3)
        for chave_proibida in ('crps', 'skill', 'alpha', 'beta', 'sigma'):
            self.assertNotIn(chave_proibida, json_keys_lower(resultado))


def json_keys_lower(d, prefixo=''):
    chaves = []
    for k, val in d.items():
        chaves.append(k.lower())
        if isinstance(val, dict):
            chaves.extend(json_keys_lower(val))
    return chaves


class GateViabilidadeEscalaTestCase(unittest.TestCase):

    def test_a_nenhum_piso_e_escolhido_apenas_reportado(self):
        pares = pd.DataFrame([
            {'target_mes': 7, 'valido': True, 'spread_clim_modelo_mes': 0.5, 'erro_clim_sd_mes': 0.3},
            {'target_mes': 7, 'valido': True, 'spread_clim_modelo_mes': 0.8, 'erro_clim_sd_mes': 0.4},
            {'target_mes': 1, 'valido': True, 'spread_clim_modelo_mes': 90.0, 'erro_clim_sd_mes': 80.0},
        ])
        resultado = w.gate_viabilidade_escala(pares)
        self.assertTrue(resultado['todos_spread_clim_modelo_mes_positivos'])
        self.assertTrue(resultado['todos_erro_clim_sd_mes_positivos'])
        self.assertAlmostEqual(resultado['distribuicao_por_mes'][7]['spread_clim_modelo_mes_minimo'], 0.5)

    def test_b_detecta_denominador_nao_positivo(self):
        pares = pd.DataFrame([
            {'target_mes': 7, 'valido': True, 'spread_clim_modelo_mes': 0.0001, 'erro_clim_sd_mes': 0.3},
        ])
        resultado = w.gate_viabilidade_escala(pares)
        self.assertTrue(resultado['todos_spread_clim_modelo_mes_positivos'])
        self.assertAlmostEqual(resultado['distribuicao_por_mes'][7]['spread_clim_modelo_mes_minimo'], 0.0001)


class ComDadosReaisAprovadosTestCase(unittest.TestCase):

    def test_a_executa_sem_stop_on_failure(self):
        if not v.CAMINHO_METRICAS_JSON.parent.exists():
            self.skipTest("dados reais não disponíveis nesta árvore de trabalho")
        resultado = w.executar_viabilidade()
        self.assertFalse(resultado.get('STOP_ON_FAILURE', True))
        self.assertTrue(resultado['nenhum_parametro_emos_ajustado'])
        self.assertTrue(resultado['nenhum_crps_emos_calculado'])
        viab = resultado['viabilidade_estrutural_warmup']
        self.assertGreater(viab['n_pares_validos_total'], viab['n_treino_minimo_emos'])
        self.assertIsNotNone(viab['primeira_init_date_elegivel'])


if __name__ == '__main__':
    unittest.main()
