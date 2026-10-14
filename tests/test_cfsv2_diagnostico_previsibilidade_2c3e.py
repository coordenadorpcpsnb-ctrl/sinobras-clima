#!/usr/bin/env python3
"""
tests/test_cfsv2_diagnostico_previsibilidade_2c3e.py — Fase 2C.3E:
cobre o módulo de diagnóstico/síntese (não implementação de modelo),
garantindo que (1) nenhuma métrica numérica é inventada — todo número
do inventário vem literalmente dos JSONs já aprovados das Fases
2C.3C/2C.3D, (2) a interseção de amostra entre métodos é consistente
(nunca negativa, nunca maior que o menor dos dois conjuntos), e (3)
nenhuma comparação é marcada como "comparável diretamente" sem uma
fonte já aprovada citada.

Roda com:
    python -m unittest tests.test_cfsv2_diagnostico_previsibilidade_2c3e -v
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import cfsv2_diagnostico_previsibilidade_2c3e as diag  # noqa: E402


class InventarioMetodosTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not diag.CAMINHO_2C3C_METRICAS.exists():
            raise unittest.SkipTest("dados reais 2C.3C/2C.3D não disponíveis nesta árvore de trabalho")
        cls.inventario = diag.construir_inventario_metodos()

    def test_a_todos_os_metodos_esperados_presentes(self):
        esperados = {
            'raw_cfsv2_2c3c', 'metodo_3_1_aditivo', 'metodo_3_2_multiplicativo',
            'metodo_3_3_gate_qm', 'metodo_3_4_mos_linear',
            'metodo_3_5_gate_probabilistico', 'metodo_3_5_robustez_h2', 'metodo_3_5_emos_h2',
        }
        self.assertEqual(set(self.inventario.keys()), esperados)

    def test_b_metodo_3_3_marcado_nao_testavel_nunca_aprovado_ou_reprovado(self):
        decisao = self.inventario['metodo_3_3_gate_qm']['decisao_cientifica_registrada']
        self.assertIn('nao_testavel', decisao)

    def test_c_numeros_do_raw_batem_com_json_fonte_sem_transformacao(self):
        fonte = diag._carregar_json(diag.CAMINHO_2C3C_METRICAS)
        ic = fonte['expanding_operational_simulation']['intervalos_confianca_skill_scores_por_horizonte']
        for h in diag.HORIZONTES:
            esperado = ic[str(h)]['rmsess']['estimativa']
            obtido = self.inventario['raw_cfsv2_2c3c']['metricas_principais_por_horizonte'][str(h)]['rmsess_absoluto']['estimativa']
            self.assertEqual(esperado, obtido, f'H{h}: rmsess_absoluto não bate byte-a-byte com a fonte 2C.3C')

    def test_d_numeros_do_emos_h2_batem_com_json_fonte_sem_transformacao(self):
        fonte = diag._carregar_json(diag.CAMINHO_EMOS_METRICAS)
        esperado = fonte['bootstrap_crpss']['CRPSS_spread_dinamico']['estimativa']
        obtido = self.inventario['metodo_3_5_emos_h2']['metricas_principais_por_horizonte'][str(diag.LEAD_H2)]['CRPSS_spread_dinamico']['estimativa']
        self.assertEqual(esperado, obtido)
        self.assertEqual(
            fonte['decisao_criterio_pre_registrado']['aprovado_componente_dinamico_de_spread'],
            self.inventario['metodo_3_5_emos_h2']['decisao_cientifica_registrada']['aprovado_componente_dinamico_de_spread'],
        )
        self.assertFalse(self.inventario['metodo_3_5_emos_h2']['decisao_cientifica_registrada']['aprovado_componente_dinamico_de_spread'])

    def test_e_nenhum_metodo_1_a_4_e_declarado_aprovado(self):
        for chave in ('metodo_3_1_aditivo', 'metodo_3_2_multiplicativo', 'metodo_3_4_mos_linear'):
            decisao = str(self.inventario[chave]['decisao_cientifica_registrada'])
            self.assertIn('não satisfeito', decisao)

    def test_f_todos_os_horizontes_h1_h6_cobertos_onde_aplicavel(self):
        for chave in ('raw_cfsv2_2c3c', 'metodo_3_1_aditivo', 'metodo_3_2_multiplicativo', 'metodo_3_4_mos_linear', 'metodo_3_5_gate_probabilistico'):
            metricas = self.inventario[chave]['metricas_principais_por_horizonte']
            self.assertEqual(set(metricas.keys()), {str(h) for h in diag.HORIZONTES}, chave)


class ComparabilidadeAmostrasTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not diag.CAMINHO_ADITIVA_CSV.exists():
            raise unittest.SkipTest("dados reais 2C.3D não disponíveis nesta árvore de trabalho")
        cls.tabela = diag.construir_comparabilidade_amostras()

    def test_a_nenhuma_intersecao_negativa_ou_maior_que_o_menor_conjunto(self):
        for _, linha in self.tabela.iterrows():
            self.assertGreaterEqual(linha['n_intersecao'], 0)
            self.assertLessEqual(linha['n_intersecao'], min(linha['n_a'], linha['n_b']))

    def test_b_toda_linha_comparavel_cita_fonte_ja_aprovada(self):
        for _, linha in self.tabela.iterrows():
            if linha['comparavel_diretamente']:
                self.assertIn('já aprovada', linha['motivo'])

    def test_c_toda_linha_nao_comparavel_tem_motivo_explicito(self):
        for _, linha in self.tabela.iterrows():
            if not linha['comparavel_diretamente']:
                self.assertTrue(len(linha['motivo']) > 10)

    def test_d_emos_h2_vs_deterministicos_sempre_nao_comparavel(self):
        subset = self.tabela[self.tabela['metodo_a'] == 'emos_h2']
        self.assertTrue(len(subset) > 0)
        self.assertFalse(subset['comparavel_diretamente'].any())

    def test_e_aditivo_vs_multiplicativo_e_aditivo_vs_mos_sao_comparaveis_em_todos_os_leads(self):
        for h in diag.HORIZONTES:
            linha_am = self.tabela[(self.tabela['lead'] == h) & (self.tabela['metodo_a'] == 'aditivo') & (self.tabela['metodo_b'] == 'multiplicativo')]
            linha_amos = self.tabela[(self.tabela['lead'] == h) & (self.tabela['metodo_a'] == 'aditivo') & (self.tabela['metodo_b'] == 'mos_linear')]
            self.assertTrue(linha_am.iloc[0]['comparavel_diretamente'])
            self.assertTrue(linha_amos.iloc[0]['comparavel_diretamente'])

    def test_f_multiplicativo_vs_mos_nunca_comparavel_amostra_nova_nesta_fase(self):
        subset = self.tabela[(self.tabela['metodo_a'] == 'multiplicativo') & (self.tabela['metodo_b'] == 'mos_linear')]
        self.assertTrue(len(subset) == len(diag.HORIZONTES))
        self.assertFalse(subset['comparavel_diretamente'].any())


class DiagnosticoHabilidadeTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not diag.CAMINHO_2C3C_METRICAS.exists():
            raise unittest.SkipTest("dados reais 2C.3C/2C.3D não disponíveis nesta árvore de trabalho")
        cls.inventario = diag.construir_inventario_metodos()
        cls.diagnostico = diag.construir_diagnostico_habilidade(cls.inventario)

    def test_a_cobre_h1_a_h6(self):
        self.assertEqual(set(self.diagnostico['por_horizonte'].keys()), {str(h) for h in diag.HORIZONTES})

    def test_b_rmsess_e_crpss_nunca_misturados_num_unico_campo(self):
        for h in diag.HORIZONTES:
            chaves = self.diagnostico['por_horizonte'][str(h)].keys()
            chaves_rmsess = [c for c in chaves if 'rmsess' in c and 'estimativa' not in c and 'ic' not in c]
            chaves_crpss = [c for c in chaves if 'crpss' in c.lower() and 'estimativa' not in c and 'ic' not in c]
            self.assertTrue(set(chaves_rmsess).isdisjoint(set(chaves_crpss)))

    def test_c_h2_tem_campos_extras_do_emos_outros_horizontes_nao(self):
        self.assertIn('emos_h2_CRPSS_spread_dinamico', self.diagnostico['por_horizonte']['2'])
        for h in diag.HORIZONTES:
            if h != diag.LEAD_H2:
                self.assertNotIn('emos_h2_CRPSS_spread_dinamico', self.diagnostico['por_horizonte'][str(h)])

    def test_d_raw_absoluto_e_anomalia_corrigida_sao_campos_distintos_com_valores_diferentes(self):
        h1 = self.diagnostico['por_horizonte']['1']
        self.assertNotEqual(
            h1['raw_rmsess_absoluto']['estimativa'],
            h1['raw_rmsess_anomalia_corrigida']['estimativa'],
        )


class ExecucaoCompletaTestCase(unittest.TestCase):

    def test_a_executar_diagnostico_sem_stop_on_failure_e_grava_artefatos(self):
        if not diag.CAMINHO_2C3C_METRICAS.exists():
            self.skipTest("dados reais 2C.3C/2C.3D não disponíveis nesta árvore de trabalho")
        resultado = diag.executar_diagnostico_2c3e()
        self.assertFalse(resultado['STOP_ON_FAILURE'])
        self.assertTrue(diag.CAMINHO_INVENTARIO.exists())
        self.assertTrue(diag.CAMINHO_COMPARABILIDADE.exists())
        self.assertTrue(diag.CAMINHO_DIAGNOSTICO.exists())
        with open(diag.CAMINHO_INVENTARIO) as f:
            inv = json.load(f)
        self.assertIn('metodo_3_5_emos_h2', inv)

    def test_b_nenhum_arquivo_protegido_e_alterado_por_este_modulo(self):
        if not diag.CAMINHO_2C3C_METRICAS.exists():
            self.skipTest("dados reais 2C.3C/2C.3D não disponíveis nesta árvore de trabalho")
        caminhos_protegidos = [
            diag.CAMINHO_2C3C_METRICAS, diag.CAMINHO_2C3C_BASE,
            diag.CAMINHO_ADITIVA_METRICAS, diag.CAMINHO_ADITIVA_CSV,
            diag.CAMINHO_MULT_METRICAS, diag.CAMINHO_MULT_CSV,
            diag.CAMINHO_MOS_METRICAS, diag.CAMINHO_MOS_CSV,
            diag.CAMINHO_GATE_METRICAS, diag.CAMINHO_ROBUSTEZ_H2,
            diag.CAMINHO_EMOS_METRICAS, diag.CAMINHO_EMOS_CSV,
        ]
        mtimes_antes = {p: p.stat().st_mtime for p in caminhos_protegidos}
        diag.executar_diagnostico_2c3e()
        for p in caminhos_protegidos:
            self.assertEqual(mtimes_antes[p], p.stat().st_mtime, f'{p} foi alterado')


if __name__ == '__main__':
    unittest.main()
