#!/usr/bin/env python3
"""
tests/test_c3s_multimodel_catalogo.py — regressão do catálogo
multi-modelo da Fase 2B.1 (scripts/c3s_multimodel_catalogo.py). Tudo
offline, puro — nenhum teste baixa nada nem acessa o CDS.

Roda com:
    python -m unittest tests.test_c3s_multimodel_catalogo -v
"""

import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import c3s_multimodel_catalogo as mcat  # noqa: E402


class CatalogoTestCase(unittest.TestCase):

    def test_quatro_sistemas_candidatos(self):
        self.assertEqual(len(mcat.CATALOGO), 4)
        centros = {s.centro for s in mcat.CATALOGO}
        self.assertEqual(centros, {'ECMWF', 'METEO_FRANCE', 'DWD', 'CMCC'})

    def test_ukmo_nao_incluido(self):
        self.assertNotIn('UKMO', {s.centro for s in mcat.CATALOGO})
        self.assertIn('UKMO', mcat.SISTEMAS_EXCLUIDOS_FASE2B1)

    def test_ncep_eccc_bom_jma_nao_incluidos(self):
        centros = {s.centro for s in mcat.CATALOGO}
        for centro in ('NCEP', 'ECCC', 'BOM', 'JMA'):
            self.assertNotIn(centro, centros)
            self.assertIn(centro, mcat.SISTEMAS_EXCLUIDOS_FASE2B1)

    def test_todos_os_candidatos_cobrem_leads_1_a_6(self):
        for s in mcat.CATALOGO:
            self.assertEqual(tuple(s.leads_disponiveis), (1, 2, 3, 4, 5, 6))

    def test_todos_os_candidatos_tem_producao_fixed(self):
        for s in mcat.CATALOGO:
            self.assertEqual(s.hindcast_production, 'fixed')

    def test_todos_os_candidatos_cross_confirmados(self):
        for s in mcat.CATALOGO:
            self.assertTrue(s.verificado_cruzado, f'{s.centro}/{s.system_name} sem cross-confirmação')
            self.assertGreaterEqual(len(s.fontes), 2, f'{s.centro}/{s.system_name} com menos de 2 fontes')

    def test_membros_de_hindcast_sao_especificos_por_modelo(self):
        """Seção 17/27-C — nunca assumir 25 membros para todos."""
        membros = {s.centro: s.hindcast_members for s in mcat.CATALOGO}
        self.assertEqual(membros, {'ECMWF': 25, 'METEO_FRANCE': 25, 'DWD': 30, 'CMCC': 40})
        # confirma que não são todos iguais — o ponto central da barreira
        self.assertGreater(len(set(membros.values())), 1)

    def test_sistema_por_nome(self):
        s = mcat.sistema_por_nome('ECMWF', 'SEAS5')
        self.assertEqual(s.system_code, '51')

    def test_sistema_por_nome_inexistente_falha(self):
        with self.assertRaises(KeyError):
            mcat.sistema_por_nome('ECMWF', 'SEAS_INEXISTENTE')


class PeriodoComumHindcastTestCase(unittest.TestCase):

    # A — período comum corretamente calculado
    def test_a_periodo_comum_dos_4_candidatos_e_1993_2016(self):
        resultado = mcat.periodo_comum_hindcast(mcat.CATALOGO)
        self.assertEqual(resultado['common_start'], 1993)
        self.assertEqual(resultado['common_end'], 2016)
        self.assertEqual(resultado['incompatibilidade'], {})

    def test_a_periodo_comum_nao_e_hardcoded_muda_com_input(self):
        """Prova de que o valor é CALCULADO, não fixo: encurtar um
        sistema muda o resultado."""
        sistemas = [replace(mcat.sistema_por_nome('ECMWF', 'SEAS5'), hindcast_start=2000),
                    mcat.sistema_por_nome('DWD', 'GCFS2.1')]
        resultado = mcat.periodo_comum_hindcast(sistemas)
        self.assertEqual(resultado['common_start'], 2000)

    # B — sistema fora do período gera incompatibilidade
    def test_b_sistema_com_hindcast_none_gera_incompatibilidade(self):
        sistema_incompleto = replace(mcat.sistema_por_nome('CMCC', 'SPS3.5'), hindcast_start=None)
        resultado = mcat.periodo_comum_hindcast([sistema_incompleto, mcat.sistema_por_nome('DWD', 'GCFS2.1')])
        self.assertIn('CMCC/SPS3.5', resultado['incompatibilidade'])
        # o sistema incompatível não contamina o cálculo dos demais
        self.assertEqual(resultado['common_start'], 1993)
        self.assertEqual(resultado['common_end'], 2016)

    def test_b_sistemas_sem_sobreposicao_real_gera_incompatibilidade(self):
        antigo = replace(mcat.sistema_por_nome('ECMWF', 'SEAS5'), hindcast_start=1981, hindcast_end=1990)
        novo = replace(mcat.sistema_por_nome('DWD', 'GCFS2.1'), hindcast_start=2010, hindcast_end=2020)
        resultado = mcat.periodo_comum_hindcast([antigo, novo])
        self.assertIsNone(resultado['common_start'])
        self.assertIsNone(resultado['common_end'])
        self.assertIn('interseccao', resultado['incompatibilidade'])

    def test_lista_vazia_nao_quebra(self):
        resultado = mcat.periodo_comum_hindcast([])
        self.assertIsNone(resultado['common_start'])
        self.assertEqual(resultado['anos_disponiveis_por_modelo'], {})


class TabelaCatalogoTestCase(unittest.TestCase):

    def test_colunas_minimas_presentes(self):
        df = mcat.tabela_catalogo()
        for coluna in ('centre', 'system_name', 'system_code', 'model_id', 'hindcast_start',
                       'hindcast_end', 'hindcast_members', 'max_lead', 'forecast_type',
                       'hindcast_production', 'compatible_precip_monthly', 'compatible_leads_1_6',
                       'included_phase2b1', 'notes'):
            self.assertIn(coluna, df.columns)

    def test_todos_incluidos_por_default(self):
        df = mcat.tabela_catalogo()
        self.assertTrue(df['included_phase2b1'].all())

    def test_compatible_leads_1_6_true_para_todos(self):
        df = mcat.tabela_catalogo()
        self.assertTrue(df['compatible_leads_1_6'].all())


class CommonPeriodJsonTestCase(unittest.TestCase):

    def test_estrutura_minima(self):
        d = mcat.common_period_json()
        for chave in ('candidate_models', 'included_models', 'excluded_models', 'common_start',
                      'common_end', 'anos_disponiveis_por_modelo', 'reasoning'):
            self.assertIn(chave, d)

    def test_common_start_end_batem_com_periodo_comum_hindcast(self):
        d = mcat.common_period_json()
        self.assertEqual(d['common_start'], 1993)
        self.assertEqual(d['common_end'], 2016)

    def test_excluded_models_inclui_ukmo_e_versoes_nao_incluidas(self):
        d = mcat.common_period_json()
        self.assertIn('UKMO', d['excluded_models'])
        self.assertIn('METEO_FRANCE/System9', d['excluded_models'])
        self.assertIn('DWD/GCFS2.2', d['excluded_models'])
        self.assertIn('CMCC/SPS4', d['excluded_models'])


if __name__ == '__main__':
    unittest.main()
