#!/usr/bin/env python3
"""
tests/test_nmme_auditoria_chirps_sinobras.py — Fase 2C.2, investigação
dedicada da reinterpretação CHIRPS (4ª rodada, 2026).

Este módulo opera SÓ sobre arquivos já commitados no repositório
(data/chirps_1981_2025.csv, data/serie_subst.csv) — nunca depende do
arquivo original SINOBRAS.csv (que não está no repositório). Os testes
usam fixtures sintéticas para as funções isoladas e o dado REAL para
os testes fim a fim (mesmo padrão de RealSerieObservacionalTestCase em
outros módulos deste projeto).

Roda com:
    python -m unittest tests.test_nmme_auditoria_chirps_sinobras -v
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import nmme_auditoria_chirps_sinobras as aud  # noqa: E402


class CompararChirpsPontoComSerieProducaoTestCase(unittest.TestCase):
    """Item 5 — compara SEM presumir mesma metodologia, separado por
    período (pré/pós 1996)."""

    def test_a_meses_identicos_produzem_correlacao_1_e_diff_zero(self):
        serie_df = pd.DataFrame([
            {'ano': 2000, 'mes': 1, 'prec': 100.0},
            {'ano': 2000, 'mes': 2, 'prec': 200.0},
            {'ano': 2000, 'mes': 3, 'prec': 150.0},
        ])
        chirps_df = serie_df.rename(columns={'prec': 'prec'})[['ano', 'mes', 'prec']].copy()
        resultado = aud.comparar_chirps_ponto_com_serie_producao(chirps_df, serie_df)
        pos = resultado['periodo_pos_1996']
        self.assertEqual(pos['n_meses'], 3)
        self.assertEqual(pos['diff_abs_media_mm'], 0.0)
        self.assertEqual(pos['correlacao'], 1.0)
        self.assertEqual(pos['n_meses_identicos_diff_menor_0_01mm'], 3)

    def test_b_separa_pre_e_pos_1996_corretamente(self):
        serie_df = pd.DataFrame([
            {'ano': 1990, 'mes': 1, 'prec': 100.0},
            {'ano': 2000, 'mes': 1, 'prec': 200.0},
        ])
        chirps_df = pd.DataFrame([
            {'ano': 1990, 'mes': 1, 'prec': 90.0},
            {'ano': 2000, 'mes': 1, 'prec': 210.0},
        ])
        resultado = aud.comparar_chirps_ponto_com_serie_producao(chirps_df, serie_df)
        self.assertEqual(resultado['periodo_pre_1996']['n_meses'], 1)
        self.assertEqual(resultado['periodo_pos_1996']['n_meses'], 1)
        self.assertAlmostEqual(resultado['periodo_pre_1996']['diff_abs_media_mm'], 10.0)
        self.assertAlmostEqual(resultado['periodo_pos_1996']['diff_abs_media_mm'], 10.0)

    def test_c_meses_sem_correspondencia_nao_entram_na_comparacao(self):
        serie_df = pd.DataFrame([{'ano': 2000, 'mes': 1, 'prec': 100.0},
                                  {'ano': 2000, 'mes': 2, 'prec': 100.0}])
        chirps_df = pd.DataFrame([{'ano': 2000, 'mes': 1, 'prec': 90.0}])
        resultado = aud.comparar_chirps_ponto_com_serie_producao(chirps_df, serie_df)
        self.assertEqual(resultado['n_meses_comparados_total'], 1)

    def test_d_vazio_nao_quebra(self):
        vazio = pd.DataFrame(columns=['ano', 'mes', 'prec'])
        resultado = aud.comparar_chirps_ponto_com_serie_producao(vazio, vazio)
        self.assertEqual(resultado['n_meses_comparados_total'], 0)
        self.assertEqual(resultado['periodo_pos_1996']['n_meses'], 0)
        self.assertIsNone(resultado['periodo_pos_1996']['correlacao'])

    def test_e_nunca_presume_mesma_metodologia_no_texto(self):
        serie_df = pd.DataFrame([{'ano': 2000, 'mes': 1, 'prec': 100.0}])
        chirps_df = pd.DataFrame([{'ano': 2000, 'mes': 1, 'prec': 100.0}])
        resultado = aud.comparar_chirps_ponto_com_serie_producao(chirps_df, serie_df)
        self.assertIn('NÃO são a mesma extração', resultado['interpretacao'])

    def test_f_dados_reais_reproduzem_correlacao_conhecida(self):
        """Sanidade contra os dados REAIS já commitados — confirma que "
        os números citados no relatório continuam batendo."""
        chirps_df = aud.carregar_chirps_ponto()
        serie_df = aud.carregar_serie_producao()
        resultado = aud.comparar_chirps_ponto_com_serie_producao(chirps_df, serie_df)
        self.assertEqual(resultado['periodo_pos_1996']['n_meses'], 360)
        self.assertEqual(resultado['periodo_pre_1996']['n_meses'], 180)
        self.assertAlmostEqual(resultado['periodo_pos_1996']['correlacao'], 0.9168, places=3)
        self.assertAlmostEqual(resultado['periodo_pre_1996']['correlacao'], 0.9673, places=3)
        self.assertLess(resultado['periodo_pos_1996']['n_meses_identicos_diff_menor_0_01mm'], 20)


class CarregarArquivosTestCase(unittest.TestCase):
    """Item 5 — leitura pura, nunca modifica os arquivos de entrada
    (ambos já commitados no repositório)."""

    def test_a_carregar_chirps_ponto_nunca_escreve(self):
        import inspect
        src = inspect.getsource(aud.carregar_chirps_ponto)
        self.assertNotIn('to_csv', src)
        self.assertNotIn('.write', src)

    def test_b_carregar_serie_producao_nunca_escreve(self):
        import inspect
        src = inspect.getsource(aud.carregar_serie_producao)
        self.assertNotIn('to_csv', src)
        self.assertNotIn('.write', src)

    def test_c_arquivos_reais_existem_e_sao_carregaveis(self):
        chirps_df = aud.carregar_chirps_ponto()
        serie_df = aud.carregar_serie_producao()
        self.assertGreater(len(chirps_df), 0)
        self.assertGreater(len(serie_df), 0)
        self.assertIn('prec', chirps_df.columns)
        self.assertIn('prec', serie_df.columns)


class MontarListaInformacoesNecessariasTestCase(unittest.TestCase):
    """Item 4 — lista objetiva do que falta para reproduzir a extração
    de SINOBRAS.csv."""

    def test_a_lista_cobre_topicos_chave(self):
        lista = aud.montar_lista_informacoes_necessarias_reproducao()
        self.assertIsInstance(lista, list)
        self.assertGreater(len(lista), 0)
        texto = ' '.join(lista).lower()
        for topico in ('versão', 'coordenada', 'resolução', 'agregação', 'processamento',
                       'temporal', 'unidades'):
            self.assertIn(topico, texto)

    def test_b_todos_os_itens_sao_strings_nao_vazias(self):
        for item in aud.montar_lista_informacoes_necessarias_reproducao():
            self.assertIsInstance(item, str)
            self.assertGreater(len(item), 0)


class AvaliarViabilidadeReferenciaChirpsTestCase(unittest.TestCase):
    """Item 6 — avaliação de viabilidade, NUNCA uma execução real de
    extração (nenhum acesso à rede)."""

    def test_a_nunca_acessa_rede(self):
        """Verifica ausência de CHAMADAS de rede (requests/urlopen ou
        uma invocação real de buscar_prec_chirps) — mencionar
        'ClimateSERV' em prosa explicativa é esperado e não conta."""
        import inspect
        src = inspect.getsource(aud.avaliar_viabilidade_referencia_chirps_1991_2011)
        for termo_proibido in ('requests.', 'urlopen', 'buscar_prec_chirps(', 'import requests'):
            self.assertNotIn(termo_proibido, src)

    def test_b_confirma_cobertura_real_1991_2011(self):
        resultado = aud.avaliar_viabilidade_referencia_chirps_1991_2011()
        self.assertTrue(resultado['data_chirps_1981_2025_ja_cobre_1991_2011'])
        self.assertEqual(resultado['n_meses_1991_2011_ja_extraidos'], 252)
        self.assertEqual(resultado['n_meses_1991_2011_esperados'], 252)

    def test_c_interpretacao_nunca_declara_pronto_sem_ressalvas(self):
        resultado = aud.avaliar_viabilidade_referencia_chirps_1991_2011()
        self.assertIn('ressalvas', resultado['interpretacao'].lower())
        self.assertIn('NÃO toma', resultado['interpretacao'])

    def test_d_cita_ferramentas_ja_existentes_sem_reimplementar(self):
        resultado = aud.avaliar_viabilidade_referencia_chirps_1991_2011()
        ferramentas = resultado['ferramentas_ja_existentes']
        self.assertIn('_chirps.py', ferramentas['ponto_unico'])
        self.assertIn('_chirps.py', ferramentas['zonal_envelope'])
        self.assertIn('backfill_chirps_historico.py', ferramentas['quebra_em_blocos'])


class MontarPropostaContinuidadeTestCase(unittest.TestCase):
    def test_a_lista_nao_vazia_de_proximos_passos(self):
        proposta = aud.montar_proposta_continuidade()
        self.assertIsInstance(proposta, list)
        self.assertGreater(len(proposta), 3)


class ExecutarInvestigacaoCompletaEndToEndTestCase(unittest.TestCase):
    """Fim a fim contra os dados REAIS já commitados — nunca depende
    de SINOBRAS.csv (fora do repositório)."""

    def test_a_executa_sem_erro(self):
        metadata = aud.executar_investigacao_completa()
        self.assertTrue(metadata['nenhuma_skill_calculada'])
        self.assertTrue(metadata['nenhuma_previsao_ou_indicador_recalculado'])
        self.assertTrue(metadata['nenhuma_referencia_observacional_substituida'])
        self.assertTrue(metadata['nenhum_dado_historico_modificado'])
        self.assertTrue(metadata['nenhum_dashboard_alterado'])
        self.assertTrue(metadata['nenhum_modelo_climatico_alterado'])
        self.assertTrue(metadata['nenhuma_extracao_nova_executada'])

    def test_b_relatorio_markdown_gerado_sem_erro(self):
        metadata = aud.executar_investigacao_completa()
        relatorio = aud.gerar_relatorio_markdown(metadata)
        self.assertIn('CHIRPS', relatorio)
        self.assertIn('Proposta de continuidade', relatorio)
        self.assertIn('Informações necessárias', relatorio)
        self.assertIn('Viabilidade', relatorio)
        self.assertIn('Restrições respeitadas', relatorio)


class ZeroSkillNuncaSubstituiReferenciaTestCase(unittest.TestCase):
    """Restrições explícitas desta tarefa: nunca calcula skill, nunca
    recalcula previsões/indicadores, nunca substitui a referência
    observacional, nunca modifica dashboard/modelos/dados históricos."""

    def test_a_modulo_nunca_calcula_skill_nem_toca_dashboard(self):
        codigo = Path(aud.__file__).read_text()
        self.assertNotIn('import update_dashboard', codigo)
        self.assertNotIn('calcular_skill', codigo)
        self.assertNotIn('c3s_calibracao', codigo)

    def test_b_modulo_nunca_escreve_em_data(self):
        codigo = Path(aud.__file__).read_text()
        self.assertNotIn(".to_csv(CHIRPS_PONTO_PATH", codigo)
        self.assertNotIn(".to_csv(SERIE_PRODUCAO_PATH", codigo)

    def test_c_dry_run_nao_escreve_nada(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            original = aud.ARTIFACTS_DIR
            aud.ARTIFACTS_DIR = Path(tmp) / 'nunca_criado'
            try:
                aud.imprimir_plano()
                self.assertFalse(aud.ARTIFACTS_DIR.exists())
            finally:
                aud.ARTIFACTS_DIR = original


if __name__ == '__main__':
    unittest.main()
