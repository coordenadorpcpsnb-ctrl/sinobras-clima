#!/usr/bin/env python3
"""
tests/test_c3s_multimodel_hindcast.py — regressão da infraestrutura do
HINDCAST MULTI-MODELO COMPLETO da Fase 2B.2 (scripts/c3s_multimodel_hindcast.py)
e do workflow .github/workflows/c3s_multimodel_hindcast.yml. Tudo
offline — nenhum teste baixa nada, abre GRIB real nem precisa de
credencial CDS.

Roda com:
    python -m unittest tests.test_c3s_multimodel_hindcast -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import c3s_multimodel_catalogo as mcat  # noqa: E402
import c3s_multimodel as mm  # noqa: E402
import c3s_multimodel_hindcast as h  # noqa: E402
import _c3s_utils as cu  # noqa: E402

WORKFLOW_PATH = ROOT / '.github' / 'workflows' / 'c3s_multimodel_hindcast.yml'

ECMWF = mcat.sistema_por_nome('ECMWF', 'SEAS5')
METFR = mcat.sistema_por_nome('METEO_FRANCE', 'System8')
DWD = mcat.sistema_por_nome('DWD', 'GCFS2.1')
CMCC = mcat.sistema_por_nome('CMCC', 'SPS3.5')
SISTEMAS4 = [ECMWF, METFR, DWD, CMCC]


# ══════════════════════════════════════════════════════════════════════════
# Cenário sintético reutilizável — pequeno o bastante para rodar rápido,
# mas com anos suficientes (>= MIN_ANOS_TREINO) para exercitar bias/
# climatologia de verdade. Cada modelo tem um viés SISTEMÁTICO diferente
# (constante por modelo) — usado para provar que o bias é separado por
# modelo (item Q).
# ══════════════════════════════════════════════════════════════════════════

VIES_POR_MODELO = {'ECMWF': 5.0, 'METEO_FRANCE': -8.0, 'DWD': 12.0, 'CMCC': -3.0}
N_MEMBROS_SINTETICO = {'ECMWF': 4, 'METEO_FRANCE': 4, 'DWD': 5, 'CMCC': 6}


def _construir_cenario_sintetico(sistemas=SISTEMAS4, ano_ini=1993, ano_fim=2006, leads=(1, 3),
                                  n_membros_por_modelo=None, seed=7):
    """Constrói (raw_df, chirps_df) sintéticos: chirps é uma climatologia
    senoidal simples por mês-calendário; cada modelo prevê chirps +
    viés fixo do modelo + ruído — o bias_leakage_safe deve recuperar
    aproximadamente esse viés, SEPARADO por modelo."""
    n_membros_por_modelo = n_membros_por_modelo or N_MEMBROS_SINTETICO
    rng = np.random.RandomState(seed)

    meses_alvo = pd.period_range(f'{ano_ini}-01', f'{ano_fim + 1}-12', freq='M')
    clim_por_mes = {m: 100 + 40 * np.sin(2 * np.pi * (m % 12) / 12) for m in range(1, 13)}
    chirps_df = pd.DataFrame({
        'target_month': meses_alvo,
        'chirps_prec_mm': [max(0.0, clim_por_mes[m.month] + rng.normal(0, 5)) for m in meses_alvo],
    })

    linhas = []
    for sistema in sistemas:
        vies = VIES_POR_MODELO[sistema.centro]
        n_membros = n_membros_por_modelo[sistema.centro]
        for ano in range(ano_ini, ano_fim + 1):
            for mes in range(1, 13):
                init_date = pd.Period(f'{ano}-{mes:02d}', 'M')
                for lead in leads:
                    target_month = cu.leadtime_para_mes_alvo(init_date, lead)
                    obs = chirps_df.loc[chirps_df['target_month'] == target_month, 'chirps_prec_mm']
                    base = float(obs.iloc[0]) if not obs.empty else clim_por_mes[target_month.month]
                    for membro in range(n_membros):
                        valor = max(0.0, base + vies + rng.normal(0, 3))
                        linhas.append({
                            'centre': sistema.centro, 'system_name': sistema.system_name,
                            'system_code': sistema.system_code, 'init_date': str(init_date),
                            'target_month': str(target_month), 'lead': lead, 'member': membro,
                            'c3s_prec_mm': round(valor, 3),
                            'units_original': 'm s**-1', 'conversion_applied': 'tprate_m_s_para_mm_mes',
                        })
    raw_df = pd.DataFrame(linhas)
    return raw_df, chirps_df


def _temporal_audit_sintetico(raw_df):
    """1 linha por (centre, system_name, init_date, lead) presente no
    raw_df — sempre aprovado (lead1_e_mes_nominal_da_inicializacao=True),
    mesmo desenho de c3s_multimodel_poc.py::processar_origem_modelo para
    o cenário sintético (a validação real do mapeamento temporal já é
    coberta por tests/test_c3s_multimodel_poc.py)."""
    combinacoes = raw_df[['centre', 'system_name', 'init_date', 'lead']].drop_duplicates()
    combinacoes = combinacoes.copy()
    combinacoes['lead1_e_mes_nominal_da_inicializacao'] = True
    return combinacoes.reset_index(drop=True)


class CenarioSinteticoTestCase(unittest.TestCase):
    """Confere que o cenário sintético em si está bem formado antes de
    usá-lo nos testes de comportamento abaixo."""

    def test_cenario_tem_linhas_para_os_4_modelos(self):
        raw_df, chirps_df = _construir_cenario_sintetico()
        self.assertEqual(set(raw_df['centre'].unique()), {s.centro for s in SISTEMAS4})
        self.assertFalse(chirps_df.empty)


# ══════════════════════════════════════════════════════════════════════════
# A-F — contagens FULL derivadas do catálogo/período comum, nunca
# hardcoded (conferidas contra os números exatos do enunciado).
# ══════════════════════════════════════════════════════════════════════════

class ContagensFullTestCase(unittest.TestCase):

    def test_a_288_origens_por_modelo(self):
        self.assertEqual(h.N_ORIGENS_POR_MODELO_FULL, 288)
        self.assertEqual(len(h.montar_origens(h.ANO_INICIO_HINDCAST, h.ANO_FIM_HINDCAST)), 288)

    def test_b_1152_modelo_origem(self):
        self.assertEqual(h.N_MODELO_ORIGEM_FULL, 1152)

    def test_c_contagens_raw_por_modelo(self):
        self.assertEqual(h.N_RAW_ESPERADO_POR_MODELO_FULL,
                          {'ECMWF': 43200, 'METEO_FRANCE': 43200, 'DWD': 51840, 'CMCC': 69120})

    def test_d_raw_total_207360(self):
        self.assertEqual(h.N_RAW_ESPERADO_TOTAL_FULL, 207360)

    def test_e_summary_6912(self):
        self.assertEqual(h.N_SUMMARY_ESPERADO_FULL, 6912)

    def test_f_mme_1728(self):
        self.assertEqual(h.N_MME_ESPERADO_FULL, 1728)

    def test_periodo_comum_e_1993_2016(self):
        self.assertEqual((h.ANO_INICIO_HINDCAST, h.ANO_FIM_HINDCAST), (1993, 2016))


# ══════════════════════════════════════════════════════════════════════════
# G-K — chunking (blocos, contagem por chunk, nº de chunks, max-parallel,
# nomes de artifact únicos).
# ══════════════════════════════════════════════════════════════════════════

class ChunkingTestCase(unittest.TestCase):

    def test_g_blocos_corretos(self):
        self.assertEqual(h.construir_blocos_chunk(),
                          [(1993, 1998), (1999, 2004), (2005, 2010), (2011, 2016)])

    def test_g_bloco_nao_multiplo_falha(self):
        with self.assertRaises(ValueError):
            h.construir_blocos_chunk(1993, 2015, 6)

    def test_h_72_origens_por_chunk(self):
        self.assertEqual(h.N_ORIGENS_POR_CHUNK, 72)

    def test_i_16_chunks(self):
        self.assertEqual(h.N_CHUNKS, 16)
        self.assertEqual(len(h.construir_matriz_chunks()), 16)

    def test_j_max_parallel_2(self):
        self.assertEqual(h.MAX_PARALLEL_CHUNKS, 2)

    def test_k_artifact_names_unicos(self):
        nomes = [c['artifact_name'] for c in h.construir_matriz_chunks()]
        self.assertEqual(len(nomes), len(set(nomes)))

    def test_k_exemplo_nomes_artifact(self):
        self.assertEqual(h.nome_artifact_chunk('ECMWF', 1993, 1998), 'c3s-mm-ecmwf-1993-1998')
        self.assertEqual(h.nome_artifact_chunk('METEO_FRANCE', 1993, 1998), 'c3s-mm-metfr-1993-1998')

    def test_contagens_por_chunk_conferem(self):
        self.assertEqual(h.N_RAW_ESPERADO_POR_CHUNK,
                          {'ECMWF': 10800, 'METEO_FRANCE': 10800, 'DWD': 12960, 'CMCC': 17280})


# ══════════════════════════════════════════════════════════════════════════
# validar_chunk_aprovado / N — membros corretos por modelo.
# ══════════════════════════════════════════════════════════════════════════

class ValidarChunkTestCase(unittest.TestCase):

    def _chunk_valido(self, sistema, ano_ini=1993, ano_fim=1993):
        raw_df, _ = _construir_cenario_sintetico([sistema], ano_ini, ano_fim, leads=tuple(h.LEADS),
                                                   n_membros_por_modelo={sistema.centro: sistema.hindcast_members})
        origens = h.montar_origens(ano_ini, ano_fim)
        temporal_linhas = []
        for ano, mes in origens:
            init_date = pd.Period(f'{ano}-{mes:02d}', 'M')
            for lead in h.LEADS:
                temporal_linhas.append({
                    'centre': sistema.centro, 'system_name': sistema.system_name, 'init_date': str(init_date),
                    'lead': lead, 'target_month': str(cu.leadtime_para_mes_alvo(init_date, lead)),
                    'lead1_e_mes_nominal_da_inicializacao': True,
                })
        temporal_audit_df = pd.DataFrame(temporal_linhas)
        return {'sistema': sistema, 'ano_ini': ano_ini, 'ano_fim': ano_fim, 'origens': origens,
                'raw_df': raw_df, 'temporal_audit_df': temporal_audit_df, 'falhas': {}, 'metadados': {}}

    def test_n_chunk_valido_aprova(self):
        resultado = self._chunk_valido(DWD)
        aprovado, motivos = h.validar_chunk_aprovado(resultado)
        self.assertTrue(aprovado, motivos)

    def test_n_membros_errados_reprova(self):
        """DWD espera 30 membros — um chunk sintético com só 5 (nº
        genérico, não o do DWD) tem que ser reprovado explicitamente."""
        resultado = self._chunk_valido(DWD)
        resultado['raw_df'] = resultado['raw_df'][resultado['raw_df']['member'] < 3].copy()
        aprovado, motivos = h.validar_chunk_aprovado(resultado)
        self.assertFalse(aprovado)
        self.assertTrue(any('membros' in m for m in motivos))

    def test_falha_de_download_reprova(self):
        resultado = self._chunk_valido(DWD)
        resultado['falhas'] = {'1993-01': 'erro simulado'}
        aprovado, motivos = h.validar_chunk_aprovado(resultado)
        self.assertFalse(aprovado)

    def test_duplicata_reprova(self):
        resultado = self._chunk_valido(DWD)
        resultado['raw_df'] = pd.concat([resultado['raw_df'], resultado['raw_df'].iloc[[0]]],
                                         ignore_index=True)
        aprovado, motivos = h.validar_chunk_aprovado(resultado)
        self.assertFalse(aprovado)
        self.assertTrue(any('duplicada' in m for m in motivos))


# ══════════════════════════════════════════════════════════════════════════
# L/M — consolidação detecta chunk ausente / duplicata.
# ══════════════════════════════════════════════════════════════════════════

class ConsolidacaoTestCase(unittest.TestCase):

    def test_l_chunk_incompleto_falha(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / 'ECMWF_1993_1993'
            d.mkdir()
            (d / 'raw.csv').write_text('centre\n')
            with self.assertRaises(RuntimeError) as e:
                h.consolidar_chunks([d])
            self.assertIn('incompleto', str(e.exception))

    def test_l_diretorios_completos_concatenam(self):
        raw_df, _ = _construir_cenario_sintetico([ECMWF], 1993, 1993, leads=(1,),
                                                   n_membros_por_modelo={'ECMWF': 3})
        with tempfile.TemporaryDirectory() as tmp:
            d1, d2 = Path(tmp) / 'a', Path(tmp) / 'b'
            for d in (d1, d2):
                d.mkdir()
                raw_df.to_csv(d / 'raw.csv', index=False)
                pd.DataFrame({'lead1_e_mes_nominal_da_inicializacao': [True]}).to_csv(
                    d / 'temporal_audit.csv', index=False)
            consolidado, temporal = h.consolidar_chunks([d1, d2])
            self.assertEqual(len(consolidado), 2 * len(raw_df))

    def test_m_duplicata_detectada_na_integridade_global(self):
        raw_df, _ = _construir_cenario_sintetico(SISTEMAS4, 1993, 1993, leads=(1,))
        raw_dup = pd.concat([raw_df, raw_df.iloc[[0]]], ignore_index=True)
        temporal_df = pd.DataFrame({'lead1_e_mes_nominal_da_inicializacao': [True] * 10})
        aprovado, motivos = h.validar_integridade_global(raw_dup, temporal_df, SISTEMAS4, 1993, 1993)
        self.assertFalse(aprovado)
        self.assertTrue(any('duplicada' in m for m in motivos))

    def test_modelo_ausente_detectado_na_integridade_global(self):
        raw_df, _ = _construir_cenario_sintetico(SISTEMAS4, 1993, 1993, leads=(1,))
        raw_sem_cmcc = raw_df[raw_df['centre'] != 'CMCC']
        temporal_df = pd.DataFrame({'lead1_e_mes_nominal_da_inicializacao': [True] * 10})
        aprovado, motivos = h.validar_integridade_global(raw_sem_cmcc, temporal_df, SISTEMAS4, 1993, 1993)
        self.assertFalse(aprovado)
        self.assertTrue(any('CMCC' in m for m in motivos))


# ══════════════════════════════════════════════════════════════════════════
# O/P — equal weighting preservado, MME completo exige os 4 modelos.
# ══════════════════════════════════════════════════════════════════════════

class MmeMultimodeloTestCase(unittest.TestCase):

    def test_o_variantes_batem_com_equal_weighting_de_c3s_multimodel(self):
        self.assertEqual(h.VARIANTES, mm.variantes_comparacao(SISTEMAS4))

    def test_p_mme_completo_exige_4_modelos(self):
        raw_df, chirps_df = _construir_cenario_sintetico(SISTEMAS4, 1993, 2006, leads=(1,))
        summary_df = h.construir_summary_multimodelo(raw_df, chirps_df)
        summary_incompleto = summary_df[summary_df['centre'] != 'CMCC']
        mme_df = mm.construir_mme_por_origem_lead(summary_incompleto, [s.centro for s in SISTEMAS4])
        self.assertTrue((mme_df['model_set_status'] == mm.MODELO_AUSENTE_STATUS).all())

    def test_p_mme_completo_com_4_modelos_e_ok(self):
        raw_df, chirps_df = _construir_cenario_sintetico(SISTEMAS4, 1993, 2006, leads=(1,))
        summary_df = h.construir_summary_multimodelo(raw_df, chirps_df)
        mme_df = mm.construir_mme_por_origem_lead(summary_df, [s.centro for s in SISTEMAS4])
        self.assertTrue((mme_df['model_set_status'] == mm.MODELO_COMPLETO_STATUS).all())
        self.assertEqual(len(mme_df), (2006 - 1993 + 1) * 12)


# ══════════════════════════════════════════════════════════════════════════
# Q — bias SEMPRE separado por modelo (nunca usa erro de um modelo para
# corrigir outro).
# ══════════════════════════════════════════════════════════════════════════

class BiasSeparadoPorModeloTestCase(unittest.TestCase):

    def test_q_bias_recuperado_e_proximo_do_vies_de_cada_modelo(self):
        raw_df, chirps_df = _construir_cenario_sintetico(SISTEMAS4, 1993, 2006, leads=(1, 3))
        summary_df = h.construir_summary_multimodelo(raw_df, chirps_df)
        avaliavel = summary_df[summary_df['status_historico'] == 'OK']
        self.assertFalse(avaliavel.empty)
        for centro, vies_esperado in VIES_POR_MODELO.items():
            sub = avaliavel[avaliavel['centre'] == centro]
            self.assertFalse(sub.empty, f'sem linhas avaliáveis para {centro}')
            bias_medio = sub['bias_mm'].astype(float).mean()
            # bias_mm = média(raw - obs); raw foi construído como obs + viés + ruído,
            # então bias_mm deve ficar perto do viés do próprio modelo, nunca do de outro.
            self.assertAlmostEqual(bias_medio, vies_esperado, delta=4.0,
                                    msg=f'{centro}: bias recuperado {bias_medio} longe do viés real '
                                        f'{vies_esperado} — suspeita de mistura entre modelos')

    def test_q_bias_de_um_modelo_nao_influencia_outro(self):
        """Zera o histórico de um modelo (ECMWF) só na climatologia/bias
        do PRÓPRIO — não deve mudar o bias calculado para os outros 3."""
        raw_df, chirps_df = _construir_cenario_sintetico(SISTEMAS4, 1993, 2006, leads=(1,))
        summary_completo = h.construir_summary_multimodelo(raw_df, chirps_df)

        raw_sem_ecmwf_historico = raw_df[~((raw_df['centre'] == 'ECMWF') &
                                            (raw_df['init_date'] < '2000-01'))]
        summary_alterado = h.construir_summary_multimodelo(raw_sem_ecmwf_historico, chirps_df)

        for centro in ('METEO_FRANCE', 'DWD', 'CMCC'):
            a = summary_completo[summary_completo['centre'] == centro].set_index(['init_date', 'lead'])['bias_mm']
            b = summary_alterado[summary_alterado['centre'] == centro].set_index(['init_date', 'lead'])['bias_mm']
            comuns = a.index.intersection(b.index)
            self.assertTrue(len(comuns) > 0)
            pd.testing.assert_series_equal(a.loc[comuns].sort_index(), b.loc[comuns].sort_index(),
                                            check_names=False)


# ══════════════════════════════════════════════════════════════════════════
# R — leakage audit estrito (mesma reamostragem independente da Fase
# 2A.3, generalizada por modelo).
# ══════════════════════════════════════════════════════════════════════════

class LeakageAuditTestCase(unittest.TestCase):

    def test_r_leakage_aprovado_no_cenario_correto(self):
        raw_df, chirps_df = _construir_cenario_sintetico(SISTEMAS4, 1993, 2006, leads=(1, 3))
        summary_df = h.construir_summary_multimodelo(raw_df, chirps_df)
        ens_df = h.construir_ens_df_por_modelo(h._com_periods(raw_df))
        leakage_df = h.construir_leakage_audit_multimodelo(summary_df, ens_df, chirps_df)
        self.assertFalse(leakage_df.empty)
        self.assertTrue((leakage_df['leakage_status'] == 'OK').all())

    def test_r_leakage_audit_tem_uma_linha_por_summary_row(self):
        raw_df, chirps_df = _construir_cenario_sintetico(SISTEMAS4, 1993, 2000, leads=(1,))
        summary_df = h.construir_summary_multimodelo(raw_df, chirps_df)
        ens_df = h.construir_ens_df_por_modelo(h._com_periods(raw_df))
        leakage_df = h.construir_leakage_audit_multimodelo(summary_df, ens_df, chirps_df)
        self.assertEqual(len(leakage_df), len(summary_df))


# ══════════════════════════════════════════════════════════════════════════
# S/T/Y — avaliação principal só começa com histórico suficiente, 1.008
# forecasts esperados no FULL, split 2003-2009/2010-2016 congelado.
# ══════════════════════════════════════════════════════════════════════════

class AvaliacaoPrincipalTestCase(unittest.TestCase):

    def test_s_avaliacao_principal_comeca_em_2003(self):
        self.assertEqual(h.AVALIACAO_ANO_INICIO, h.ANO_INICIO_HINDCAST + h.MIN_ANOS_TREINO)
        self.assertEqual(h.AVALIACAO_ANO_INICIO, 2003)

    def test_s_status_historico_sem_10_anos_e_sem_historico(self):
        raw_df, chirps_df = _construir_cenario_sintetico(SISTEMAS4, 1993, 2006, leads=(1,))
        summary_df = h.construir_summary_multimodelo(raw_df, chirps_df)
        primeira_origem = summary_df[summary_df['init_date'] == pd.Period('1993-01', 'M')]
        self.assertTrue((primeira_origem['status_historico'] == 'SEM_HISTORICO_SUFICIENTE').all())

    def test_t_1008_forecasts_esperados_no_full(self):
        self.assertEqual(h.N_AVALIACAO_PRINCIPAL_ESPERADO_FULL, 1008)
        self.assertEqual(h.N_AVALIACAO_PRINCIPAL_ESPERADO_FULL,
                          (h.AVALIACAO_ANO_FIM - h.AVALIACAO_ANO_INICIO + 1) * 12 * len(h.LEADS))

    def test_y_split_development_temporal_validation_congelado(self):
        self.assertEqual((h.DEVELOPMENT_ANO_INICIO, h.DEVELOPMENT_ANO_FIM), (2003, 2009))
        self.assertEqual((h.TEMPORAL_VALIDATION_ANO_INICIO, h.TEMPORAL_VALIDATION_ANO_FIM), (2010, 2016))
        self.assertEqual(h._periodo_avaliacao(pd.Period('2003-01', 'M')), 'development')
        self.assertEqual(h._periodo_avaliacao(pd.Period('2009-12', 'M')), 'development')
        self.assertEqual(h._periodo_avaliacao(pd.Period('2010-01', 'M')), 'temporal_validation')
        self.assertEqual(h._periodo_avaliacao(pd.Period('2016-12', 'M')), 'temporal_validation')
        self.assertEqual(h._periodo_avaliacao(pd.Period('2002-12', 'M')), 'warmup')

    def test_amostra_comum_filtra_variantes_incompletas(self):
        raw_df, chirps_df = _construir_cenario_sintetico(SISTEMAS4, 1993, 2006, leads=(1,))
        summary_df = h.construir_summary_multimodelo(raw_df, chirps_df)
        mme_df = mm.construir_mme_por_origem_lead(summary_df, [s.centro for s in SISTEMAS4])
        avaliacao_principal = h.filtrar_avaliacao_principal(summary_df)
        wide = h.construir_avaliacao_wide(avaliacao_principal, mme_df, SISTEMAS4)
        comum = h.filtrar_amostra_comum(wide, SISTEMAS4)
        self.assertFalse(comum.empty)
        colunas_obrigatorias = ['chirps_prec_mm', 'climatological_mean'] + \
            [f'{s.centro}_bc' for s in SISTEMAS4] + ['MME_bc']
        for c in colunas_obrigatorias:
            self.assertTrue(np.isfinite(comum[c].astype(float)).all())


# ══════════════════════════════════════════════════════════════════════════
# U — cobertura CHIRPS completa, derivada (nunca hardcoded): 1981-01 a
# 2017-05, 437 meses para o FULL oficial.
# ══════════════════════════════════════════════════════════════════════════

class CoberturaChirpsTestCase(unittest.TestCase):

    def test_u_cobertura_full_e_1981_01_a_2017_05_437_meses(self):
        origens = h.montar_origens(h.ANO_INICIO_HINDCAST, h.ANO_FIM_HINDCAST)
        ini, fim = h.intervalo_targets_necessario(origens, h.LEADS)
        self.assertEqual(str(ini), '1981-01')
        self.assertEqual(str(fim), '2017-05')
        self.assertEqual(len(pd.period_range(ini, fim, freq='M')), 437)

    def test_u_nunca_hardcoded_reflete_origens_pedidas(self):
        origens = [(2000, 1)]
        ini, fim = h.intervalo_targets_necessario(origens, [1, 2, 3])
        self.assertEqual(str(fim), '2000-03')


# ══════════════════════════════════════════════════════════════════════════
# V — probabilidades somam 1 nas tabelas probabilísticas multi-modelo.
# ══════════════════════════════════════════════════════════════════════════

class ProbabilisticoTestCase(unittest.TestCase):

    def test_v_variantes_probabilisticas_excluem_clim(self):
        variantes = h.variantes_probabilisticas(SISTEMAS4)
        self.assertNotIn('CLIM', variantes)
        self.assertEqual(len(variantes), 8 + 2)   # 4 modelos x RAW/BC + MME RAW/BC

    def test_v_tabela_probabilistica_nao_quebra_com_dado_sintetico(self):
        raw_df, chirps_df = _construir_cenario_sintetico(SISTEMAS4, 1993, 2006, leads=(1,))
        summary_df = h.construir_summary_multimodelo(raw_df, chirps_df)
        mme_df = mm.construir_mme_por_origem_lead(summary_df, [s.centro for s in SISTEMAS4])
        avaliacao_principal = h.filtrar_avaliacao_principal(summary_df)
        wide = h.construir_avaliacao_wide(avaliacao_principal, mme_df, SISTEMAS4)
        comum = h.filtrar_amostra_comum(wide, SISTEMAS4)
        tab = h.tabela_skill_probabilistico_overall(comum, SISTEMAS4)
        self.assertEqual(len(tab), 10)
        self.assertTrue((tab['n'] > 0).all())


# ══════════════════════════════════════════════════════════════════════════
# W — comparação pareada usa exatamente a mesma amostra da avaliação
# principal comum.
# ══════════════════════════════════════════════════════════════════════════

class PairedComparisonTestCase(unittest.TestCase):

    def _avaliacao_comum(self):
        raw_df, chirps_df = _construir_cenario_sintetico(SISTEMAS4, 1993, 2006, leads=(1, 3))
        summary_df = h.construir_summary_multimodelo(raw_df, chirps_df)
        mme_df = mm.construir_mme_por_origem_lead(summary_df, [s.centro for s in SISTEMAS4])
        avaliacao_principal = h.filtrar_avaliacao_principal(summary_df)
        wide = h.construir_avaliacao_wide(avaliacao_principal, mme_df, SISTEMAS4)
        return h.filtrar_amostra_comum(wide, SISTEMAS4)

    def test_w_paired_mme_vs_ecmwf_mesma_amostra(self):
        comum = self._avaliacao_comum()
        paired = h.paired_mme_vs_ecmwf(comum)
        self.assertEqual(len(paired), len(comum))

    def test_w_paired_mme_vs_models_mesma_amostra_por_modelo(self):
        comum = self._avaliacao_comum()
        paired = h.paired_mme_vs_models(comum, SISTEMAS4)
        for sistema in SISTEMAS4:
            self.assertEqual(len(paired[paired['modelo'] == sistema.centro]), len(comum))

    def test_delta_negativo_favorece_mme(self):
        comum = self._avaliacao_comum().copy()
        comum['MME_bc'] = comum['chirps_prec_mm']   # MME "perfeito"
        paired = h.paired_mme_vs_ecmwf(comum)
        self.assertTrue((paired['delta_mse'] <= 0).all())


# ══════════════════════════════════════════════════════════════════════════
# X — bootstrap por init_year, reprodutível com a mesma seed.
# ══════════════════════════════════════════════════════════════════════════

class BootstrapTestCase(unittest.TestCase):

    def test_x_bootstrap_reprodutivel_com_mesma_seed(self):
        raw_df, chirps_df = _construir_cenario_sintetico(SISTEMAS4, 1993, 2006, leads=(1,))
        summary_df = h.construir_summary_multimodelo(raw_df, chirps_df)
        mme_df = mm.construir_mme_por_origem_lead(summary_df, [s.centro for s in SISTEMAS4])
        avaliacao_principal = h.filtrar_avaliacao_principal(summary_df)
        wide = h.construir_avaliacao_wide(avaliacao_principal, mme_df, SISTEMAS4)
        comum = h.filtrar_amostra_comum(wide, SISTEMAS4)

        r1 = h.montar_bootstrap_multimodel(comum, SISTEMAS4, n_bootstrap=100, seed=42)
        r2 = h.montar_bootstrap_multimodel(comum, SISTEMAS4, n_bootstrap=100, seed=42)
        pd.testing.assert_frame_equal(r1, r2)
        self.assertFalse(r1.empty)
        self.assertTrue({'ECMWF_BC', 'METEO_FRANCE_BC', 'DWD_BC', 'CMCC_BC', 'MME_BC'}.issubset(
            set(r1['variant'])))

    def test_x_bootstrap_por_ano_de_inicializacao(self):
        import inspect
        assinatura = inspect.signature(h.montar_bootstrap_multimodel)
        # reamostragem é feita internamente por 'init_year' — conferido
        # indiretamente via skill.bootstrap_skill (já testado em
        # tests/test_c3s_hindcast_completo.py); aqui só garante que a
        # coluna existe na amostra usada.
        raw_df, chirps_df = _construir_cenario_sintetico(SISTEMAS4, 1993, 2006, leads=(1,))
        summary_df = h.construir_summary_multimodelo(raw_df, chirps_df)
        self.assertIn('init_year', summary_df.columns)

    def test_x_paired_bootstrap_reprodutivel(self):
        raw_df, chirps_df = _construir_cenario_sintetico(SISTEMAS4, 1993, 2006, leads=(1,))
        summary_df = h.construir_summary_multimodelo(raw_df, chirps_df)
        mme_df = mm.construir_mme_por_origem_lead(summary_df, [s.centro for s in SISTEMAS4])
        avaliacao_principal = h.filtrar_avaliacao_principal(summary_df)
        wide = h.construir_avaliacao_wide(avaliacao_principal, mme_df, SISTEMAS4)
        comum = h.filtrar_amostra_comum(wide, SISTEMAS4)
        paired = h.paired_mme_vs_ecmwf(comum)
        r1 = h.bootstrap_paired_mme_vs_ecmwf(paired, n_bootstrap=100, seed=42)
        r2 = h.bootstrap_paired_mme_vs_ecmwf(paired, n_bootstrap=100, seed=42)
        self.assertEqual(r1, r2)


# ══════════════════════════════════════════════════════════════════════════
# Consolidação fim-a-fim (pequena escala) — exercita rodar_consolidacao
# menos a busca real de CHIRPS (mockada).
# ══════════════════════════════════════════════════════════════════════════

class RodarConsolidacaoTestCase(unittest.TestCase):

    _MEMBROS_REAIS = {s.centro: s.hindcast_members for s in SISTEMAS4}

    def test_consolidacao_fim_a_fim_pequena_escala(self):
        from unittest import mock
        raw_df, chirps_df = _construir_cenario_sintetico(SISTEMAS4, 1993, 2005, leads=tuple(h.LEADS),
                                                           n_membros_por_modelo=self._MEMBROS_REAIS)
        temporal_audit_df = _temporal_audit_sintetico(raw_df)
        with mock.patch.object(h, 'buscar_chirps_consolidado', return_value=chirps_df):
            resultado = h.rodar_consolidacao(raw_df, temporal_audit_df, SISTEMAS4, 1993, 2005, n_bootstrap=50)
        self.assertTrue(resultado['integridade_aprovada'])
        self.assertTrue(resultado['leakage_aprovado'])
        self.assertFalse(resultado['mme_df'].empty)
        self.assertFalse(resultado['avaliacao_comum'].empty)
        for nome, tabela in resultado['tabelas_skill'].items():
            self.assertFalse(tabela.empty, f'tabela {nome} vazia')

    def test_integridade_reprovada_levanta_erro(self):
        raw_df, chirps_df = _construir_cenario_sintetico(SISTEMAS4, 1993, 1993, leads=tuple(h.LEADS),
                                                           n_membros_por_modelo=self._MEMBROS_REAIS)
        raw_incompleto = raw_df[raw_df['centre'] != 'CMCC']
        temporal_audit_df = _temporal_audit_sintetico(raw_incompleto)
        with self.assertRaises(RuntimeError) as e:
            h.rodar_consolidacao(raw_incompleto, temporal_audit_df, SISTEMAS4, 1993, 1993)
        self.assertIn('integridade global', str(e.exception))


# ══════════════════════════════════════════════════════════════════════════
# validar_full_multimodel_aprovado / validar_pilot_multimodel_aprovado
# ══════════════════════════════════════════════════════════════════════════

class ValidarAprovacaoTestCase(unittest.TestCase):

    _MEMBROS_REAIS = {s.centro: s.hindcast_members for s in SISTEMAS4}

    def test_pilot_aprova_mesmo_sem_avaliacao_principal(self):
        from unittest import mock
        raw_df, chirps_df = _construir_cenario_sintetico(SISTEMAS4, 1993, 1993, leads=tuple(h.LEADS),
                                                           n_membros_por_modelo=self._MEMBROS_REAIS)
        temporal_audit_df = _temporal_audit_sintetico(raw_df)
        with mock.patch.object(h, 'buscar_chirps_consolidado', return_value=chirps_df):
            resultado = h.rodar_consolidacao(raw_df, temporal_audit_df, SISTEMAS4, 1993, 1993, n_bootstrap=50)
        # só 1 ano de histórico — nenhuma linha deveria ter status_historico OK.
        self.assertTrue(resultado['avaliacao_comum'].empty)
        aprovado, motivos = h.validar_pilot_multimodel_aprovado(resultado, SISTEMAS4, 1993, 1993)
        self.assertTrue(aprovado, motivos)

    def test_full_reprova_se_avaliacao_principal_menor_que_esperado(self):
        from unittest import mock
        raw_df, chirps_df = _construir_cenario_sintetico(SISTEMAS4, 1993, 2005, leads=tuple(h.LEADS),
                                                           n_membros_por_modelo=self._MEMBROS_REAIS)
        temporal_audit_df = _temporal_audit_sintetico(raw_df)
        with mock.patch.object(h, 'buscar_chirps_consolidado', return_value=chirps_df):
            resultado = h.rodar_consolidacao(raw_df, temporal_audit_df, SISTEMAS4, 1993, 2005, n_bootstrap=50)
        aprovado, motivos = h.validar_full_multimodel_aprovado(resultado, SISTEMAS4)
        self.assertFalse(aprovado)
        self.assertTrue(any('avaliação principal' in m for m in motivos))


# ══════════════════════════════════════════════════════════════════════════
# Dry-run / plano — nunca acessa o CDS.
# ══════════════════════════════════════════════════════════════════════════

class DryRunPlanTestCase(unittest.TestCase):

    def test_plano_full_contagens(self):
        plano = h.plano_execucao('FULL')
        self.assertEqual(plano['n_raw_esperado_total'], 207360)
        self.assertEqual(plano['n_summary_esperado'], 6912)
        self.assertEqual(plano['n_mme_esperado'], 1728)
        self.assertEqual(plano['n_avaliacao_principal_esperado'], 1008)
        self.assertEqual(plano['n_chunks'], 16)

    def test_plano_pilot_menor_que_full(self):
        plano_pilot = h.plano_execucao('PILOT')
        plano_full = h.plano_execucao('FULL')
        self.assertLess(plano_pilot['n_raw_esperado_total'], plano_full['n_raw_esperado_total'])

    def test_main_dry_run_default_nunca_acessa_cds(self):
        from unittest import mock
        with mock.patch.object(h.mp, '_baixar_com_retry_e_cache') as m_baixar, \
             mock.patch('sys.argv', ['c3s_multimodel_hindcast.py']):
            h.main()
        m_baixar.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════
# Z — produção intocada.
# ══════════════════════════════════════════════════════════════════════════

class ProducaoIntocadaTestCase(unittest.TestCase):

    def test_modulo_nao_importa_scripts_de_producao(self):
        import inspect
        src = inspect.getsource(h)
        for proibido in ('import update_dashboard', 'import fetch_monthly_data',
                          'import update_indices', 'import gerar_relatorio'):
            self.assertNotIn(proibido, src)

    def test_nenhum_token_real(self):
        import re
        padrao_uuid = re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
                                  r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b')
        for caminho in (ROOT / 'scripts' / 'c3s_multimodel_hindcast.py', WORKFLOW_PATH):
            texto = caminho.read_text(encoding='utf-8')
            self.assertIsNone(padrao_uuid.search(texto), f"possível token real em {caminho.name}")

    def test_catalogo_e_multimodel_congelados_nao_reescritos(self):
        """Este módulo reaproveita SISTEMAS = mcat.CATALOGO — nunca
        redefine system_code/hindcast_members localmente."""
        import inspect
        src = inspect.getsource(h)
        self.assertNotIn("system_code=", src)
        self.assertNotIn("hindcast_members=", src)


# ══════════════════════════════════════════════════════════════════════════
# Workflow — matrix chunked, max-parallel, guardrails.
# ══════════════════════════════════════════════════════════════════════════

class WorkflowTestCase(unittest.TestCase):

    def setUp(self):
        self.spec = yaml.safe_load(WORKFLOW_PATH.read_text(encoding='utf-8'))
        self.jobs = self.spec['jobs']
        gatilhos = self.spec.get('on', self.spec.get(True))
        self.inputs = gatilhos['workflow_dispatch']['inputs']

    def test_trigger_e_workflow_dispatch_sem_cron(self):
        gatilhos = self.spec.get('on', self.spec.get(True))
        self.assertIn('workflow_dispatch', gatilhos)
        self.assertNotIn('schedule', gatilhos)

    def test_modo_execucao_default_pilot(self):
        self.assertEqual(self.inputs['modo_execucao']['default'], 'PILOT')
        self.assertIn('HINDCAST_COMPLETO_1993_2016', self.inputs['modo_execucao']['options'])

    def test_dry_run_plan_default_true(self):
        self.assertEqual(self.inputs['dry_run_plan']['default'], 'true')

    def test_confirm_full_hindcast_default_vazio(self):
        self.assertEqual(self.inputs['confirm_full_hindcast']['default'], '')

    def test_existe_job_de_aquisicao_com_matrix(self):
        job = next((j for j in self.jobs.values() if 'matrix' in str(j.get('strategy', {}))), None)
        self.assertIsNotNone(job, "nenhum job com strategy.matrix encontrado")
        self.assertIn('max-parallel', job['strategy'])
        self.assertEqual(job['strategy']['max-parallel'], 2)

    def test_existe_job_de_consolidacao_que_depende_da_aquisicao(self):
        nomes_jobs = list(self.jobs.keys())
        job_consolidacao = next((nome for nome in nomes_jobs if 'consolid' in nome.lower()), None)
        self.assertIsNotNone(job_consolidacao, "nenhum job de consolidação encontrado")
        needs = self.jobs[job_consolidacao].get('needs')
        self.assertIsNotNone(needs, "job de consolidação precisa depender (needs) do job de aquisição")

    def test_artifact_nao_inclui_grib_ou_nc(self):
        texto = WORKFLOW_PATH.read_text(encoding='utf-8')
        self.assertNotIn('.grib', texto)
        self.assertNotIn('.nc\n', texto)

    def test_roda_testes_e_verifica_dashboard(self):
        texto = WORKFLOW_PATH.read_text(encoding='utf-8')
        self.assertIn('unittest discover tests', texto)
        self.assertIn('verificar_dashboard.py', texto)

    def test_default_click_run_nunca_acessa_cds(self):
        defaults = {nome: cfg.get('default', '') for nome, cfg in self.inputs.items()}
        self.assertEqual(defaults['dry_run_plan'], 'true')
        self.assertEqual(defaults['modo_execucao'], 'PILOT')


if __name__ == '__main__':
    unittest.main()
