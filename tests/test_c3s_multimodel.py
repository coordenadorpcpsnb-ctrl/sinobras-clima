#!/usr/bin/env python3
"""
tests/test_c3s_multimodel.py — regressão da combinação multi-modelo
por equal-model-weighting (scripts/c3s_multimodel.py). Tudo offline,
puro (DataFrames sintéticos) — nenhum teste baixa nada.

Roda com:
    python -m unittest tests.test_c3s_multimodel -v
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import c3s_multimodel as mm  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════
# Seção 28 — teste OBRIGATÓRIO de pesos: modelo com mais membros nunca
# pesa mais que modelo com menos membros (o número de membros nem
# entra na função — só os ensemble means já agregados).
# ══════════════════════════════════════════════════════════════════════════

class PesoIgualDeterministicoTestCase(unittest.TestCase):

    def test_exemplo_obrigatorio_secao_28(self):
        """Modelo A: 25 membros, ensemble mean=100. Modelo B: 30
        membros, ensemble mean=200. MME correto = 150, NUNCA ponderado
        pelos 55 membros (o que daria outro valor se os membros fossem
        passados como pesos)."""
        resultado = mm.mme_deterministico({'A': 100.0, 'B': 200.0})
        self.assertAlmostEqual(resultado, 150.0)

    # E — MME determinístico usa peso igual por modelo
    def test_e_peso_igual_com_tres_modelos(self):
        resultado = mm.mme_deterministico({'A': 90.0, 'B': 120.0, 'C': 150.0})
        self.assertAlmostEqual(resultado, 120.0)

    # F — modelo com 30 membros não pesa mais que modelo com 25
    def test_f_numero_de_membros_nao_influencia_o_resultado(self):
        """A função nem recebe número de membros — só o ensemble mean
        já agregado de cada modelo. Simula A com 25 membros (mean=100)
        e B com 30 membros (mean=200): o resultado é idêntico
        independente de quantos membros cada ensemble mean resume."""
        membros_a = np.full(25, 100.0)
        membros_b = np.full(30, 200.0)
        mean_a, mean_b = float(np.mean(membros_a)), float(np.mean(membros_b))
        resultado = mm.mme_deterministico({'A': mean_a, 'B': mean_b})
        self.assertAlmostEqual(resultado, 150.0)
        # nunca a média ponderada pelos 55 membros totais (que daria outro valor)
        media_ponderada_errada = (membros_a.sum() + membros_b.sum()) / 55
        self.assertNotAlmostEqual(resultado, media_ponderada_errada, places=3)

    def test_modelo_com_valor_none_e_excluido_da_media(self):
        resultado = mm.mme_deterministico({'A': 100.0, 'B': None})
        self.assertAlmostEqual(resultado, 100.0)

    def test_modelo_com_nan_e_excluido_da_media(self):
        resultado = mm.mme_deterministico({'A': 100.0, 'B': float('nan')})
        self.assertAlmostEqual(resultado, 100.0)

    def test_todos_ausentes_devolve_none(self):
        self.assertIsNone(mm.mme_deterministico({'A': None, 'B': float('nan')}))

    # L — RAW não é alterado pela combinação
    def test_l_raw_de_entrada_nunca_e_alterado(self):
        valores = {'A': 100.0, 'B': 200.0}
        original = dict(valores)
        mm.mme_deterministico(valores)
        self.assertEqual(valores, original)


# ══════════════════════════════════════════════════════════════════════════
# Seção 29 — teste probabilístico obrigatório.
# ══════════════════════════════════════════════════════════════════════════

class PesoIgualProbabilisticoTestCase(unittest.TestCase):

    def test_exemplo_obrigatorio_secao_29(self):
        resultado = mm.mme_probabilistico({'A': (0.60, 0.20, 0.20), 'B': (0.20, 0.30, 0.50)})
        below, normal, above = resultado
        self.assertAlmostEqual(below, 0.40)
        self.assertAlmostEqual(normal, 0.25)
        self.assertAlmostEqual(above, 0.35)

    # G — probabilidades MME são média das probabilidades de modelo
    def test_g_media_com_tres_modelos(self):
        below, normal, above = mm.mme_probabilistico({
            'A': (0.6, 0.2, 0.2), 'B': (0.3, 0.4, 0.3), 'C': (0.3, 0.3, 0.4),
        })
        self.assertAlmostEqual(below, 0.4)
        self.assertAlmostEqual(normal, 0.3)
        self.assertAlmostEqual(above, 0.3)

    # H — probabilidades somam 1 (entrada e saída)
    def test_h_probabilidades_de_entrada_que_nao_somam_1_levantam_erro(self):
        with self.assertRaises(ValueError):
            mm.mme_probabilistico({'A': (0.5, 0.5, 0.5)})

    def test_h_mme_de_saida_sempre_soma_1(self):
        below, normal, above = mm.mme_probabilistico({'A': (0.6, 0.2, 0.2), 'B': (0.2, 0.3, 0.5)})
        self.assertAlmostEqual(below + normal + above, 1.0)

    def test_modelo_com_none_e_excluido(self):
        below, normal, above = mm.mme_probabilistico({
            'A': (0.6, 0.2, 0.2), 'B': None,
        })
        self.assertAlmostEqual(below, 0.6)
        self.assertAlmostEqual(normal, 0.2)
        self.assertAlmostEqual(above, 0.2)

    def test_todos_ausentes_devolve_none_none_none(self):
        self.assertEqual(mm.mme_probabilistico({'A': None}), (None, None, None))

    # NÃO juntar membros de modelos diferentes — a assinatura da função
    # só aceita triplas já calculadas por modelo, nunca listas de
    # membros brutos; este teste documenta essa garantia de contrato.
    def test_nao_ha_caminho_para_passar_membros_brutos(self):
        import inspect
        assinatura = inspect.signature(mm.mme_probabilistico)
        self.assertIn('probs_por_modelo', assinatura.parameters)


# ══════════════════════════════════════════════════════════════════════════
# Variantes de comparação (Seção 11)
# ══════════════════════════════════════════════════════════════════════════

class VariantesComparacaoTestCase(unittest.TestCase):

    def test_variantes_incluem_clim_raw_bc_por_modelo_e_mme(self):
        class _S:
            def __init__(self, centro):
                self.centro = centro
        sistemas = [_S('ECMWF'), _S('DWD')]
        variantes = mm.variantes_comparacao(sistemas)
        self.assertIn('CLIM', variantes)
        self.assertIn('ECMWF_RAW', variantes)
        self.assertIn('ECMWF_BC', variantes)
        self.assertIn('DWD_RAW', variantes)
        self.assertIn('DWD_BC', variantes)
        self.assertIn('MME_RAW', variantes)
        self.assertIn('MME_BC', variantes)


# ══════════════════════════════════════════════════════════════════════════
# I — modelo ausente bloqueia MME (INCOMPLETE_MODEL_SET)
# ══════════════════════════════════════════════════════════════════════════

class StatusConjuntoModelosTestCase(unittest.TestCase):

    def test_i_todos_presentes_e_ok(self):
        status, faltando = mm.status_conjunto_modelos(['ECMWF', 'DWD'], ['ECMWF', 'DWD'])
        self.assertEqual(status, mm.MODELO_COMPLETO_STATUS)
        self.assertEqual(faltando, [])

    def test_i_modelo_faltando_bloqueia(self):
        status, faltando = mm.status_conjunto_modelos(['ECMWF', 'DWD', 'CMCC'], ['ECMWF', 'DWD'])
        self.assertEqual(status, mm.MODELO_AUSENTE_STATUS)
        self.assertEqual(faltando, ['CMCC'])


def _linha_summary(centre, init_date, lead, target_month, ens_mean_raw, ens_mean_bc,
                    prob_below_raw=0.33, prob_normal_raw=0.34, prob_above_raw=0.33,
                    prob_below_bc=0.33, prob_normal_bc=0.34, prob_above_bc=0.33):
    return {'centre': centre, 'init_date': init_date, 'target_month': target_month, 'lead': lead,
            'ens_mean_raw': ens_mean_raw, 'ens_mean_bc': ens_mean_bc,
            'prob_below_raw': prob_below_raw, 'prob_normal_raw': prob_normal_raw,
            'prob_above_raw': prob_above_raw, 'prob_below_bc': prob_below_bc,
            'prob_normal_bc': prob_normal_bc, 'prob_above_bc': prob_above_bc}


# ══════════════════════════════════════════════════════════════════════════
# Correção pós-run real 35437819463 — os 4 sistemas C3S funcionaram (6/6
# origens, membros/leads/unidade/mapeamento temporal corretos), mas o
# POC quebrou em mme_probabilistico() com
# "ValueError: probabilidades de um modelo não somam 1 (soma=nan)"
# porque uma tripla (NaN, NaN, NaN) passava como "válida" (o filtro
# antigo só checava `is not None`, e `np.nan is not None` é True). Isso
# não é falha científica — BC/probabilidades indisponíveis por falta de
# histórico é o resultado ESPERADO no POC (6 origens isoladas) — o bug
# era o crash em si. Seção 8 (itens A-L) da correção.
# ══════════════════════════════════════════════════════════════════════════

class ClassificarTriplaTestCase(unittest.TestCase):

    # A — (NaN, NaN, NaN) é tratado como probabilidade indisponível
    def test_a_tripla_toda_nan_e_ausente(self):
        self.assertEqual(mm._classificar_tripla((float('nan'), float('nan'), float('nan'))), 'ausente')

    # B — (None, None, None) é indisponível
    def test_b_tripla_toda_none_e_ausente(self):
        self.assertEqual(mm._classificar_tripla((None, None, None)), 'ausente')

    def test_tripla_com_inf_e_ausente(self):
        self.assertEqual(mm._classificar_tripla((float('inf'), float('-inf'), float('nan'))), 'ausente')

    # C — (0.4, NaN, 0.6) é classificada como corrompida
    def test_c_tripla_parcial_e_corrompida(self):
        self.assertEqual(mm._classificar_tripla((0.4, float('nan'), 0.6)), 'corrompida')

    # D — (0.4, 0.3, 0.3) é válida
    def test_d_tripla_finita_e_valida(self):
        self.assertEqual(mm._classificar_tripla((0.4, 0.3, 0.3)), 'valida')


class MmeProbabilisticoNaNTestCase(unittest.TestCase):

    # A — regressão direta do bug real: (NaN, NaN, NaN) não quebra mais,
    # é excluída da média como indisponível.
    def test_a_regressao_run_35437819463_nan_nan_nan_nao_quebra(self):
        below, normal, above = mm.mme_probabilistico({
            'ECMWF': (float('nan'), float('nan'), float('nan')),
            'DWD': (0.4, 0.3, 0.3),
        })
        self.assertAlmostEqual(below, 0.4)
        self.assertAlmostEqual(normal, 0.3)
        self.assertAlmostEqual(above, 0.3)

    # B — (None, None, None) como tripla explícita também é indisponível
    def test_b_tripla_none_none_none_e_excluida(self):
        below, normal, above = mm.mme_probabilistico({
            'ECMWF': (None, None, None), 'DWD': (0.4, 0.3, 0.3),
        })
        self.assertAlmostEqual(below, 0.4)

    # C — (0.4, NaN, 0.6) gera erro (inconsistência real, nunca ausência)
    def test_c_tripla_parcialmente_preenchida_levanta_erro(self):
        with self.assertRaises(ValueError):
            mm.mme_probabilistico({'ECMWF': (0.4, float('nan'), 0.6), 'DWD': (0.4, 0.3, 0.3)})

    # D — (0.4, 0.3, 0.3) é válida e entra na média normalmente
    def test_d_tripla_valida_entra_na_media(self):
        below, normal, above = mm.mme_probabilistico({'A': (0.4, 0.3, 0.3)})
        self.assertAlmostEqual(below, 0.4)
        self.assertAlmostEqual(normal, 0.3)
        self.assertAlmostEqual(above, 0.3)

    # E — (0.4, 0.3, 0.4) continua gerando erro porque soma != 1
    def test_e_tripla_finita_com_soma_diferente_de_1_levanta_erro(self):
        with self.assertRaises(ValueError):
            mm.mme_probabilistico({'A': (0.4, 0.3, 0.4)})

    def test_todos_os_modelos_nan_devolve_none_sem_erro(self):
        resultado = mm.mme_probabilistico({
            'ECMWF': (float('nan'),) * 3, 'DWD': (float('nan'),) * 3,
        })
        self.assertEqual(resultado, (None, None, None))

    # L — probabilidades disponíveis continuam somando 1
    def test_l_mme_de_probabilidades_disponiveis_soma_1(self):
        below, normal, above = mm.mme_probabilistico({
            'ECMWF': (float('nan'),) * 3, 'DWD': (0.5, 0.25, 0.25), 'CMCC': (0.3, 0.35, 0.35),
        })
        self.assertAlmostEqual(below + normal + above, 1.0)


class MmeDeterministicoAllowMissingTestCase(unittest.TestCase):

    # F — todos os modelos com BC NaN → mme_mean_bc = None
    def test_f_todos_bc_nan_devolve_none(self):
        resultado = mm.mme_deterministico({'ECMWF': float('nan'), 'DWD': float('nan')}, allow_missing=True)
        self.assertIsNone(resultado)

    # G — RAW finito dos quatro modelos → MME RAW calculado normalmente
    def test_g_raw_finito_dos_quatro_modelos_calcula_normalmente(self):
        resultado = mm.mme_deterministico(
            {'ECMWF': 100.0, 'METEO_FRANCE': 110.0, 'DWD': 120.0, 'CMCC': 130.0}, allow_missing=False)
        self.assertAlmostEqual(resultado, 115.0)

    # H — RAW NaN de um modelo falha explicitamente com allow_missing=False,
    # nunca calcula MME parcial silenciosamente
    def test_h_raw_nan_com_allow_missing_false_levanta_erro(self):
        with self.assertRaises(ValueError):
            mm.mme_deterministico({'ECMWF': 100.0, 'DWD': float('nan')}, allow_missing=False)

    def test_h_raw_none_com_allow_missing_false_levanta_erro(self):
        with self.assertRaises(ValueError):
            mm.mme_deterministico({'ECMWF': 100.0, 'DWD': None}, allow_missing=False)

    def test_bc_com_allow_missing_true_nunca_levanta_erro_por_ausencia(self):
        # mesmo com todos ausentes, allow_missing=True nunca levanta —
        # só devolve None (comportamento correto para BC)
        resultado = mm.mme_deterministico({'ECMWF': None, 'DWD': float('nan')}, allow_missing=True)
        self.assertIsNone(resultado)


class ModelSetStatusVsAvailabilityTestCase(unittest.TestCase):
    """Seções 6/13 — model_set_status é sobre PRESENÇA de modelo, nunca
    confundido com disponibilidade de BC/probabilidades."""

    def _summary_quatro_modelos_bc_indisponivel(self):
        centros = ['ECMWF', 'METEO_FRANCE', 'DWD', 'CMCC']
        linhas = [_linha_summary(c, '1995-01', 1, '1995-01', 100.0 + i * 10, float('nan'),
                                  prob_below_bc=float('nan'), prob_normal_bc=float('nan'),
                                  prob_above_bc=float('nan'))
                  for i, c in enumerate(centros)]
        return pd.DataFrame(linhas), centros

    # I — os 4 modelos presentes + BC indisponível → model_set_status = OK
    def test_i_quatro_modelos_presentes_bc_indisponivel_status_ok(self):
        summary, centros = self._summary_quatro_modelos_bc_indisponivel()
        df = mm.construir_mme_por_origem_lead(summary, centros)
        self.assertEqual(len(df), 1)
        row = df.iloc[0]
        self.assertEqual(row['model_set_status'], mm.MODELO_COMPLETO_STATUS)

    # J — bc_available=False não equivale a INCOMPLETE_MODEL_SET
    def test_j_bc_available_false_nao_e_incomplete_model_set(self):
        summary, centros = self._summary_quatro_modelos_bc_indisponivel()
        df = mm.construir_mme_por_origem_lead(summary, centros)
        row = df.iloc[0]
        self.assertFalse(row['bc_available'])
        self.assertFalse(row['bc_prob_available'])
        self.assertNotEqual(row['model_set_status'], mm.MODELO_AUSENTE_STATUS)
        self.assertTrue(row['raw_available'])

    def test_raw_available_true_quando_raw_finito(self):
        summary, centros = self._summary_quatro_modelos_bc_indisponivel()
        df = mm.construir_mme_por_origem_lead(summary, centros)
        row = df.iloc[0]
        self.assertTrue(row['raw_available'])
        self.assertIsNotNone(row['mme_mean_raw'])
        self.assertIsNone(row['raw_error'])

    # K — equal weighting permanece intacto (mesmo cenário do teste obrigatório)
    def test_k_equal_weighting_intacto_apesar_de_bc_indisponivel(self):
        summary, centros = self._summary_quatro_modelos_bc_indisponivel()
        df = mm.construir_mme_por_origem_lead(summary, centros)
        row = df.iloc[0]
        # ens_mean_raw = 100,110,120,130 -> média simples = 115
        self.assertAlmostEqual(row['mme_mean_raw'], 115.0)

    # H (nível de orquestração) — RAW NaN de UM modelo (mesmo com os 4
    # presentes) marca erro explícito em vez de calcular MME parcial
    def test_h_raw_nan_de_um_modelo_marca_raw_error_sem_quebrar_o_poc(self):
        centros = ['ECMWF', 'METEO_FRANCE', 'DWD', 'CMCC']
        linhas = [_linha_summary(c, '1995-01', 1, '1995-01', 100.0, 90.0) for c in centros]
        linhas[1]['ens_mean_raw'] = float('nan')   # inconsistência simulada, nunca deveria ocorrer
        summary = pd.DataFrame(linhas)
        df = mm.construir_mme_por_origem_lead(summary, centros)
        row = df.iloc[0]
        # model_set_status continua OK: os 4 modelos estão presentes,
        # o problema é a qualidade do valor RAW, não a ausência do modelo
        self.assertEqual(row['model_set_status'], mm.MODELO_COMPLETO_STATUS)
        self.assertFalse(row['raw_available'])
        self.assertIsNone(row['mme_mean_raw'])
        self.assertIsNotNone(row['raw_error'])


class ConstruirMmePorOrigemLeadTestCase(unittest.TestCase):

    def test_vazio_nao_quebra(self):
        df = mm.construir_mme_por_origem_lead(pd.DataFrame(), ['ECMWF', 'DWD'])
        self.assertEqual(len(df), 0)

    def test_todos_modelos_presentes_calcula_mme(self):
        summary = pd.DataFrame([
            _linha_summary('ECMWF', '1995-01', 1, '1995-01', 100.0, 90.0),
            _linha_summary('DWD', '1995-01', 1, '1995-01', 200.0, 190.0),
        ])
        df = mm.construir_mme_por_origem_lead(summary, ['ECMWF', 'DWD'])
        self.assertEqual(len(df), 1)
        row = df.iloc[0]
        self.assertEqual(row['model_set_status'], mm.MODELO_COMPLETO_STATUS)
        self.assertAlmostEqual(row['mme_mean_raw'], 150.0)
        self.assertAlmostEqual(row['mme_mean_bc'], 140.0)

    # I — modelo ausente bloqueia MME completo (nunca calcula parcial silenciosamente)
    def test_i_modelo_configurado_ausente_bloqueia_mme_da_origem(self):
        summary = pd.DataFrame([
            _linha_summary('ECMWF', '1995-01', 1, '1995-01', 100.0, 90.0),
            # DWD ausente para esta origem/lead
        ])
        df = mm.construir_mme_por_origem_lead(summary, ['ECMWF', 'DWD'])
        self.assertEqual(len(df), 1)
        row = df.iloc[0]
        self.assertEqual(row['model_set_status'], mm.MODELO_AUSENTE_STATUS)
        self.assertIsNone(row['mme_mean_raw'])
        self.assertIsNone(row['mme_mean_bc'])

    def test_uma_origem_completa_outra_incompleta_sao_independentes(self):
        summary = pd.DataFrame([
            _linha_summary('ECMWF', '1995-01', 1, '1995-01', 100.0, 90.0),
            _linha_summary('DWD', '1995-01', 1, '1995-01', 200.0, 190.0),
            _linha_summary('ECMWF', '1995-07', 1, '1995-07', 100.0, 90.0),
        ])
        df = mm.construir_mme_por_origem_lead(summary, ['ECMWF', 'DWD'])
        self.assertEqual(len(df), 2)
        completa = df[df['init_date'] == '1995-01'].iloc[0]
        incompleta = df[df['init_date'] == '1995-07'].iloc[0]
        self.assertEqual(completa['model_set_status'], mm.MODELO_COMPLETO_STATUS)
        self.assertEqual(incompleta['model_set_status'], mm.MODELO_AUSENTE_STATUS)

    def test_probabilidades_mme_somam_1(self):
        summary = pd.DataFrame([
            _linha_summary('ECMWF', '1995-01', 1, '1995-01', 100.0, 90.0,
                            prob_below_raw=0.6, prob_normal_raw=0.2, prob_above_raw=0.2),
            _linha_summary('DWD', '1995-01', 1, '1995-01', 200.0, 190.0,
                            prob_below_raw=0.2, prob_normal_raw=0.3, prob_above_raw=0.5),
        ])
        df = mm.construir_mme_por_origem_lead(summary, ['ECMWF', 'DWD'])
        row = df.iloc[0]
        soma = row['prob_below_raw'] + row['prob_normal_raw'] + row['prob_above_raw']
        self.assertAlmostEqual(soma, 1.0)
        self.assertAlmostEqual(row['prob_below_raw'], 0.4)


if __name__ == '__main__':
    unittest.main()
