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

Inclui (2ª rodada de auditoria) testes para a reclassificação de
comparabilidade em 4 classes (nunca um booleano único) e para
consistência entre o relatório (`docs/nmme-fase2c3e-diagnostico-
previsibilidade.md`) e os artefatos JSON/CSV que ele cita.

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

CAMINHO_RELATORIO = ROOT / 'docs' / 'nmme-fase2c3e-diagnostico-previsibilidade.md'


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
            'decisao_consolidada_fase_2c3e',
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

    def test_g_decisao_consolidada_usa_a_formulacao_exata_pre_registrada(self):
        self.assertEqual(self.inventario['decisao_consolidada_fase_2c3e'], diag.DECISAO_CONSOLIDADA_FASE_2C3E)
        self.assertNotIn('nenhuma informação', diag.DECISAO_CONSOLIDADA_FASE_2C3E.lower())
        self.assertNotIn('nenhuma capacidade', diag.DECISAO_CONSOLIDADA_FASE_2C3E.lower())

    def test_h_ressalva_h1_preserva_o_ic_exato_da_fonte_aditiva(self):
        fonte = diag._carregar_json(diag.CAMINHO_ADITIVA_METRICAS)
        ic_h1 = fonte['expanding_operational_simulation']['intervalos_confianca_skills_por_horizonte']['1']['skill_vs_anomalia_reconstruida']
        ressalva = self.inventario['metodo_3_1_aditivo']['ressalva_parcial_h1']
        self.assertEqual(ressalva['skill_vs_anomalia_reconstruida_h1']['estimativa'], ic_h1['estimativa'])
        self.assertEqual(ressalva['skill_vs_anomalia_reconstruida_h1']['ic95_lo'], ic_h1['ic95_lo'])
        self.assertGreater(ressalva['skill_vs_anomalia_reconstruida_h1']['ic95_lo'], 0, 'IC95% deveria estar totalmente acima de zero em H1')
        self.assertEqual(ressalva['classificacao'], 'parcialmente_favoravel_isolado')


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

    def test_b_toda_linha_ja_avaliada_cita_fonte_ja_aprovada(self):
        for _, linha in self.tabela.iterrows():
            if linha['classificacao_comparabilidade'] == diag.CLASSE_JA_AVALIADO:
                self.assertIn('já aprovada', linha['motivo'])

    def test_c_toda_linha_tem_motivo_explicito_e_classificacao_valida(self):
        for _, linha in self.tabela.iterrows():
            self.assertTrue(len(linha['motivo']) > 10)
            self.assertIn(linha['classificacao_comparabilidade'], diag.CLASSIFICACOES_COMPARABILIDADE_VALIDAS)

    def test_d_emos_h2_vs_deterministicos_sempre_nao_comparavel_por_metrica(self):
        subset = self.tabela[self.tabela['metodo_a'] == 'emos_h2']
        self.assertTrue(len(subset) > 0)
        self.assertTrue((subset['classificacao_comparabilidade'] == diag.CLASSE_NAO_COMPARAVEL_METRICA).all())

    def test_d2_motivo_do_emos_nunca_afirma_incomparabilidade_absoluta(self):
        subset = self.tabela[self.tabela['metodo_a'] == 'emos_h2']
        for _, linha in subset.iterrows():
            self.assertIn('NÃO afirma', linha['motivo'])

    def test_e_aditivo_vs_multiplicativo_e_aditivo_vs_mos_sao_ja_avaliados_em_todos_os_leads(self):
        for h in diag.HORIZONTES:
            linha_am = self.tabela[(self.tabela['lead'] == h) & (self.tabela['metodo_a'] == 'aditivo') & (self.tabela['metodo_b'] == 'multiplicativo')]
            linha_amos = self.tabela[(self.tabela['lead'] == h) & (self.tabela['metodo_a'] == 'aditivo') & (self.tabela['metodo_b'] == 'mos_linear')]
            self.assertEqual(linha_am.iloc[0]['classificacao_comparabilidade'], diag.CLASSE_JA_AVALIADO)
            self.assertEqual(linha_amos.iloc[0]['classificacao_comparabilidade'], diag.CLASSE_JA_AVALIADO)

    def test_f_multiplicativo_vs_mos_e_comparavel_em_principio_mas_nao_avaliado(self):
        subset = self.tabela[(self.tabela['metodo_a'] == 'multiplicativo') & (self.tabela['metodo_b'] == 'mos_linear')]
        self.assertTrue(len(subset) == len(diag.HORIZONTES))
        self.assertTrue((subset['classificacao_comparabilidade'] == diag.CLASSE_EM_PRINCIPIO_NAO_AVALIADO).all())

    def test_g_nenhum_par_classificado_nao_comparavel_por_dados_nesta_rodada(self):
        # Nenhum dos 21 pares avaliados tem interseção insuficiente a ponto
        # de justificar nao_comparavel_por_dados_ou_amostra — a categoria
        # existe na taxonomia, mas não é usada nestes dados; se algum dia
        # for usada, a fração de interseção daquela linha deve ser baixa.
        subset = self.tabela[self.tabela['classificacao_comparabilidade'] == diag.CLASSE_NAO_COMPARAVEL_DADOS]
        self.assertEqual(len(subset), 0)

    def test_h_interseccoes_preservadas_identicas_a_rodada_anterior(self):
        # Valores conhecidos da rodada anterior (antes da reclassificação
        # de 4 classes) — a reclassificação NUNCA pode alterar a contagem
        # de interseção, só o rótulo/motivo.
        esperado = {
            (1, 'aditivo', 'multiplicativo'): 80, (1, 'aditivo', 'mos_linear'): 108, (1, 'multiplicativo', 'mos_linear'): 72,
            (2, 'aditivo', 'multiplicativo'): 80, (2, 'aditivo', 'mos_linear'): 107, (2, 'multiplicativo', 'mos_linear'): 71,
            (6, 'aditivo', 'multiplicativo'): 80, (6, 'aditivo', 'mos_linear'): 103, (6, 'multiplicativo', 'mos_linear'): 71,
        }
        for (lead, a, b), n_esperado in esperado.items():
            linha = self.tabela[(self.tabela['lead'] == lead) & (self.tabela['metodo_a'] == a) & (self.tabela['metodo_b'] == b)]
            self.assertEqual(linha.iloc[0]['n_intersecao'], n_esperado, f'{lead}/{a}/{b}')
        linha_emos_adit = self.tabela[(self.tabela['metodo_a'] == 'emos_h2') & (self.tabela['metodo_b'] == 'aditivo')]
        self.assertEqual(linha_emos_adit.iloc[0]['n_intersecao'], 95)
        linha_emos_mult = self.tabela[(self.tabela['metodo_a'] == 'emos_h2') & (self.tabela['metodo_b'] == 'multiplicativo')]
        self.assertEqual(linha_emos_mult.iloc[0]['n_intersecao'], 63)


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


class RelatorioConsistenciaTestCase(unittest.TestCase):
    """2ª rodada de auditoria (item 5) — garante que o relatório em
    prosa não diverge dos artefatos JSON/CSV que ele descreve, e que a
    linguagem causal/de comparabilidade corrigida nesta rodada não
    regride silenciosamente numa edição futura."""

    @classmethod
    def setUpClass(cls):
        if not CAMINHO_RELATORIO.exists():
            raise unittest.SkipTest("relatório não encontrado nesta árvore de trabalho")
        cls.texto = CAMINHO_RELATORIO.read_text(encoding='utf-8')

    def test_a_formulacao_consolidada_aparece_verbatim_no_relatorio(self):
        self.assertIn(diag.DECISAO_CONSOLIDADA_FASE_2C3E, self.texto)

    def test_b_ressalva_h1_preservada_no_relatorio(self):
        self.assertIn('parcialmente favorável', self.texto.lower())
        self.assertIn('0,040', self.texto)

    def test_c_as_4_classes_de_comparabilidade_aparecem_no_relatorio(self):
        for classe in diag.CLASSIFICACOES_COMPARABILIDADE_VALIDAS:
            self.assertIn(classe, self.texto, f'classe {classe} não citada no relatório')

    def test_d_linguagem_causal_absoluta_banida_nao_regride(self):
        proibidas = [
            'é dominada pelo viés',
            'é predominantemente remoção',
            'é majoritariamente um artefato do viés sazonal',
            'nunca comparáveis numericamente direto apesar de ambas serem',
        ]
        for frase in proibidas:
            self.assertNotIn(frase, self.texto, f'linguagem causal não qualificada regrediu: "{frase}"')

    def test_e_emos_vs_deterministico_nao_afirma_incomparabilidade_em_principio(self):
        self.assertIn('NÃO afirma que os dois sistemas', self.texto)

    def test_f_nenhum_numero_historico_de_skill_crps_rmsess_foi_alterado(self):
        # Números âncora já confirmados byte-a-byte contra as fontes em
        # InventarioMetodosTestCase/DiagnosticoHabilidadeTestCase — aqui
        # só confirma que a prosa do relatório continua citando os
        # mesmos valores, não recalculados.
        for numero in ('-0,519', '-0,707', '-0,225', '-0,491', '0,040'):
            self.assertIn(numero, self.texto, f'número histórico {numero} ausente do relatório')

    def test_g_secao_de_hipoteses_candidatas_presente_sem_ranking_no_texto(self):
        self.assertIn('Hipóteses candidatas', self.texto)
        self.assertIn('sem ranking definitivo', self.texto.lower())


if __name__ == '__main__':
    unittest.main()
