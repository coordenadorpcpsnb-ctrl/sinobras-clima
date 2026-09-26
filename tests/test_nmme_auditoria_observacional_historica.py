#!/usr/bin/env python3
"""
tests/test_nmme_auditoria_observacional_historica.py — Fase 2C.2,
validação científica da referência observacional (centroide das
fazendas). Tudo offline — nenhuma rede, nenhuma execução de
scripts/update_dashboard.py (só leitura de texto). Fixtures sintéticas
para os achados isolados; alguns testes rodam contra os dados REAIS já
commitados (data/serie_subst.csv, data/master_monthly.csv,
data/nmme_historico_fazendas/) para confirmar que os números
reportados no relatório continuam batendo — mesmo padrão de
RealSerieObservacionalTestCase em test_nmme_piloto_historico.py.

Roda com:
    python -m unittest tests.test_nmme_auditoria_observacional_historica -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import nmme_auditoria_observacional_historica as aud  # noqa: E402
import nmme_piloto_historico as pilo  # noqa: E402


class PeriodoAlvoCompletoTestCase(unittest.TestCase):
    """Item 1 — o período exigido vai além da última origem, até o H6
    dela (não só até a última origem em si)."""

    def test_a_com_origens_reais_vai_ate_maio_2011(self):
        primeiro, ultimo = aud.periodo_alvo_completo()
        self.assertEqual(str(primeiro), '1991-01')
        self.assertEqual(str(ultimo), '2011-05')

    def test_b_generico_com_origens_customizadas(self):
        primeiro, ultimo = aud.periodo_alvo_completo(origens=((2000, 6),), leads=(1, 2, 3, 4, 5, 6))
        self.assertEqual(str(primeiro), '2000-06')
        self.assertEqual(str(ultimo), '2000-11')   # H6 = +5 meses


class CoberturaCalendarioTestCase(unittest.TestCase):
    """Item 1 — auditoria direta pelo calendário, independente da lente
    origem×lead."""

    def _serie_completa(self):
        linhas = []
        for periodo in pd.period_range('1991-01', '2011-05', freq='M'):
            linhas.append({'ano': periodo.year, 'mes': periodo.month, 'prec': 100.0, 'fonte': None})
        return pd.DataFrame(linhas)

    def test_a_serie_completa_sem_lacuna(self):
        resultado = aud.verificar_cobertura_calendario_bruta(self._serie_completa())
        self.assertTrue(resultado['cobertura_calendario_completa'])
        self.assertEqual(resultado['n_meses_ausentes'], 0)
        self.assertEqual(resultado['n_meses_duplicados'], 0)
        self.assertEqual(resultado['n_meses_esperados'], 245)

    def test_b_com_lacuna_detectada(self):
        serie = self._serie_completa()
        serie = serie[~((serie['ano'] == 2000) & (serie['mes'] == 6))]
        resultado = aud.verificar_cobertura_calendario_bruta(serie)
        self.assertFalse(resultado['cobertura_calendario_completa'])
        self.assertIn('2000-06', resultado['meses_ausentes'])
        self.assertEqual(resultado['n_meses_ausentes'], 1)

    def test_c_com_duplicata_detectada(self):
        serie = self._serie_completa()
        linha_dup = serie[(serie['ano'] == 2005) & (serie['mes'] == 3)]
        serie = pd.concat([serie, linha_dup], ignore_index=True)
        resultado = aud.verificar_cobertura_calendario_bruta(serie)
        self.assertFalse(resultado['cobertura_calendario_completa'])
        self.assertIn('2005-03', resultado['meses_duplicados'])

    def test_d_serie_real_sem_lacuna(self):
        """Sanidade contra o dado real commitado — deve bater com o
        que o relatório reporta (245 meses, 0 lacunas)."""
        resultado = aud.verificar_cobertura_calendario_bruta()
        self.assertEqual(resultado['n_meses_esperados'], 245)
        self.assertTrue(resultado['cobertura_calendario_completa'], resultado['meses_ausentes'])


class IdentidadeMerra2TestCase(unittest.TestCase):
    """Item 3 — achado numérico: idêntico pré-1996, divergente pós."""

    def test_a_identico_pre_1996_diverge_pos(self):
        with tempfile.TemporaryDirectory() as tmp:
            serie_path = Path(tmp) / 'serie.csv'
            master_path = Path(tmp) / 'master.csv'
            serie = pd.DataFrame([
                {'ano': 1994, 'mes': 1, 'prec': 100.0},
                {'ano': 1994, 'mes': 2, 'prec': 200.0},
                {'ano': 1996, 'mes': 1, 'prec': 50.0},   # Sinobras real, diverge de prec_reg
            ])
            master = pd.DataFrame([
                {'year': 1994, 'month': 1, 'prec_reg': 100.0},
                {'year': 1994, 'month': 2, 'prec_reg': 200.0},
                {'year': 1996, 'month': 1, 'prec_reg': 300.0},   # bem diferente do real Sinobras
            ])
            serie.to_csv(serie_path, index=False)
            master.to_csv(master_path, index=False)

            original_serie, original_master = aud.SERIE_OBSERVACIONAL_PATH, aud.MASTER_MONTHLY_PATH
            aud.SERIE_OBSERVACIONAL_PATH, aud.MASTER_MONTHLY_PATH = serie_path, master_path
            try:
                resultado = aud.verificar_identidade_merra2_com_master_monthly()
            finally:
                aud.SERIE_OBSERVACIONAL_PATH, aud.MASTER_MONTHLY_PATH = original_serie, original_master

            self.assertTrue(resultado['comparavel'])
            self.assertTrue(resultado['identico_pre_1996'])
            self.assertTrue(resultado['diverge_pos_1996'])
            self.assertEqual(resultado['n_meses_comparados_pre_1996'], 2)
            self.assertEqual(resultado['n_meses_comparados_pos_1996'], 1)

    def test_b_master_ausente_reporta_nao_comparavel(self):
        original_master = aud.MASTER_MONTHLY_PATH
        aud.MASTER_MONTHLY_PATH = Path('/tmp/nao_existe_de_verdade_12345.csv')
        try:
            resultado = aud.verificar_identidade_merra2_com_master_monthly()
        finally:
            aud.MASTER_MONTHLY_PATH = original_master
        self.assertFalse(resultado['comparavel'])

    def test_c_dados_reais_confirmam_identidade_pre_1996(self):
        """Sanidade contra o dado real — o achado central do relatório
        (Seção 3) precisa continuar verdadeiro."""
        resultado = aud.verificar_identidade_merra2_com_master_monthly()
        self.assertTrue(resultado['comparavel'])
        self.assertTrue(resultado['identico_pre_1996'])
        self.assertGreater(resultado['n_meses_comparados_pre_1996'], 0)


class AgregacaoSinobrasCodigoTestCase(unittest.TestCase):
    """Item 3 — achado por leitura de código, nunca por execução."""

    def test_a_padrao_encontrado_no_arquivo_real(self):
        resultado = aud.verificar_padrao_agregacao_sinobras_no_codigo()
        self.assertTrue(resultado['encontrado'])

    def test_b_nunca_importa_update_dashboard_como_modulo(self):
        """Estrutural — confirma que o módulo lê o arquivo como TEXTO
        (Path.read_text), nunca via import (que executaria a pipeline
        de produção inteira)."""
        import inspect
        src = inspect.getsource(aud.verificar_padrao_agregacao_sinobras_no_codigo)
        self.assertIn('read_text', src)
        self.assertNotIn('import update_dashboard', src)

    def test_c_arquivo_ausente_reporta_motivo(self):
        original = aud.UPDATE_DASHBOARD_PATH
        aud.UPDATE_DASHBOARD_PATH = Path('/tmp/nao_existe_de_verdade_67890.py')
        try:
            resultado = aud.verificar_padrao_agregacao_sinobras_no_codigo()
        finally:
            aud.UPDATE_DASHBOARD_PATH = original
        self.assertFalse(resultado['encontrado'])
        self.assertIn('motivo', resultado)


class DistanciaGradeCfsv2TestCase(unittest.TestCase):
    """Item 4 — distância lida diretamente do RAW persistido, nunca
    resuposta."""

    def test_a_valor_constante_entre_lotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            for lote_id in ('a', 'b'):
                pd.DataFrame({'grid_distance_km': [22.91, 22.91, 22.91]}).to_csv(
                    diretorio / f'lote_{lote_id}_raw.csv', index=False)
            dist = aud.distancia_grade_cfsv2_fazendas_km(diretorio=diretorio)
            self.assertEqual(dist, 22.91)

    def test_b_divergencia_entre_lotes_lanca_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            pd.DataFrame({'grid_distance_km': [22.91]}).to_csv(diretorio / 'lote_a_raw.csv', index=False)
            pd.DataFrame({'grid_distance_km': [30.0]}).to_csv(diretorio / 'lote_b_raw.csv', index=False)
            with self.assertRaises(RuntimeError):
                aud.distancia_grade_cfsv2_fazendas_km(diretorio=diretorio)

    def test_c_diretorio_vazio_lanca_erro_explicito(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                aud.distancia_grade_cfsv2_fazendas_km(diretorio=Path(tmp))

    def test_d_dados_reais_confirmam_22_91km(self):
        """Sanidade contra o dado real persistido pela extração
        histórica aprovada (run 36238169299)."""
        dist = aud.distancia_grade_cfsv2_fazendas_km()
        self.assertAlmostEqual(dist, 22.91, delta=0.5)


class AlinhamentoTemporalTestCase(unittest.TestCase):
    """Item 5 — H1-H6 confirmado a partir do temporal_audit persistido."""

    def _escrever_temporal(self, diretorio, origem, mapping_ok=True):
        ano, mes = origem
        linhas = []
        for lead in range(1, 7):
            alvo = pd.Period(f'{ano}-{mes:02d}', 'M') + (lead - 1)
            linhas.append({'origem_piloto': f'{ano}-{mes:02d}', 'H_lead': lead,
                             'target_month': str(alvo),
                             'mapping_status': 'OK' if mapping_ok else 'DIVERGENTE'})
        pd.DataFrame(linhas).to_csv(diretorio / 'lote_x_temporal_audit.csv', index=False)

    def test_a_tudo_ok_e_h1_igual_mes_inicializacao(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            self._escrever_temporal(diretorio, (2000, 1))
            resultado = aud.verificar_alinhamento_temporal(diretorio=diretorio)
            self.assertTrue(resultado['todas_ok'])
            self.assertTrue(resultado['h1_igual_mes_inicializacao_confirmado'])
            self.assertEqual(resultado['origem_alvo_mais_distante'], '2000-06')

    def test_b_mapping_divergente_e_detectado(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            self._escrever_temporal(diretorio, (2000, 1), mapping_ok=False)
            resultado = aud.verificar_alinhamento_temporal(diretorio=diretorio)
            self.assertFalse(resultado['todas_ok'])

    def test_c_dados_reais_1440_combinacoes_ok(self):
        resultado = aud.verificar_alinhamento_temporal()
        self.assertEqual(resultado['n_combinacoes_origem_lead'], 1440)
        self.assertEqual(resultado['n_esperado'], 1440)
        self.assertTrue(resultado['todas_ok'])
        self.assertTrue(resultado['h1_igual_mes_inicializacao_confirmado'])


class IdentificarPeriodosUtilizaveisTestCase(unittest.TestCase):
    """Item 6 — separa por procedência, nunca mistura."""

    def _cobertura(self):
        return pd.DataFrame([
            {'disponibilidade': 'PRESENTE', 'fonte_e_substituta_nao_usar': False,
             'qualidade_verificada_status': pilo.QUALIDADE_STATUS_OK,
             'procedencia_documental': pilo.PROCEDENCIA_MERRA2},
            {'disponibilidade': 'PRESENTE', 'fonte_e_substituta_nao_usar': False,
             'qualidade_verificada_status': pilo.QUALIDADE_STATUS_OK,
             'procedencia_documental': pilo.PROCEDENCIA_ESTACAO_SINOBRAS},
            {'disponibilidade': 'PRESENTE', 'fonte_e_substituta_nao_usar': True,
             'qualidade_verificada_status': pilo.QUALIDADE_STATUS_OK,
             'procedencia_documental': pilo.PROCEDENCIA_CHC_PRELIMINAR},
            {'disponibilidade': 'AUSENTE', 'fonte_e_substituta_nao_usar': False,
             'qualidade_verificada_status': pilo.QUALIDADE_STATUS_NAO_APLICAVEL_AUSENTE,
             'procedencia_documental': None},
        ])

    def test_a_exclui_ausentes_e_substitutas(self):
        resultado = aud.identificar_periodos_utilizaveis(self._cobertura())
        self.assertEqual(resultado['n_total_combinacoes'], 4)
        self.assertEqual(resultado['n_disponivel_e_qualidade_ok'], 2)
        self.assertEqual(
            resultado['combinacoes_utilizaveis_por_procedencia'][pilo.PROCEDENCIA_MERRA2], 1)
        self.assertEqual(
            resultado['combinacoes_utilizaveis_por_procedencia'][pilo.PROCEDENCIA_ESTACAO_SINOBRAS], 1)


class AvaliarCorrespondenciaEspacialTestCase(unittest.TestCase):
    def test_a_com_dados_reais_melhoria_positiva(self):
        resultado = aud.avaliar_correspondencia_espacial()
        self.assertLess(resultado['distancia_grade_cfsv2_ate_centroide_km'],
                         resultado['distancia_sao_bento_ate_centroide_km_referencia_anterior'])
        self.assertGreater(resultado['melhoria_vs_sao_bento_km'], 100)


class AuditoriaCompletaEndToEndTestCase(unittest.TestCase):
    """Fim a fim contra os dados reais — confirma que a orquestração
    inteira roda sem erro e produz um veredito nunca silenciosamente
    'apto', dado que a distância espacial (ainda que pequena) e as
    lacunas de documentação continuam presentes."""

    def test_a_executa_sem_erro_e_nunca_declara_apto_as_cegas(self):
        cobertura_df, metadata = aud.executar_auditoria_completa()
        self.assertEqual(len(cobertura_df), 1440)
        self.assertFalse(metadata['aptidao_referencia_observacional']['apto_para_avaliacao_cientifica'])
        self.assertTrue(metadata['nenhuma_skill_calculada'])
        self.assertTrue(metadata['nenhum_dashboard_alterado'])
        self.assertTrue(metadata['nenhum_modelo_climatico_alterado'])

    def test_b_relatorio_markdown_gerado_sem_erro(self):
        cobertura_df, metadata = aud.executar_auditoria_completa()
        relatorio = aud.gerar_relatorio_markdown(cobertura_df, metadata)
        self.assertIn('apto_para_avaliacao_cientifica', relatorio)
        self.assertIn('Protocolo estatístico proposto', relatorio)
        self.assertIn('vazamento', relatorio)


class ReusoDeInfraestruturaTestCase(unittest.TestCase):
    """Estrutural — confirma reuso (nunca reimplementação) das funções
    já testadas do piloto."""

    def test_a_usa_verificar_cobertura_observacional_sem_reimplementar(self):
        import inspect
        src = inspect.getsource(aud.executar_auditoria_cobertura_por_origem_lead)
        self.assertIn('pilo.verificar_cobertura_observacional', src)

    def test_b_usa_avaliar_aptidao_sem_reimplementar(self):
        import inspect
        src = inspect.getsource(aud.executar_auditoria_completa)
        self.assertIn('pilo.avaliar_aptidao_referencia_observacional', src)

    def test_c_usa_leadtime_para_mes_alvo_nmme_sem_formula_nova(self):
        import inspect
        src = inspect.getsource(aud.periodo_alvo_completo)
        self.assertIn('nproc.leadtime_para_mes_alvo_nmme', src)


class ZeroSkillNuncaModificaDashboardTestCase(unittest.TestCase):
    def test_a_modulo_nunca_importa_dashboard_ou_calibracao(self):
        codigo = Path(aud.__file__).read_text()
        self.assertNotIn('import update_dashboard', codigo)
        self.assertNotIn('c3s_calibracao', codigo)
        self.assertNotIn('calcular_skill', codigo)

    def test_b_metadata_declara_restricoes(self):
        _, metadata = aud.executar_auditoria_completa()
        self.assertTrue(metadata['nenhuma_skill_calculada'])
        self.assertTrue(metadata['nenhum_dashboard_alterado'])
        self.assertTrue(metadata['nenhum_modelo_climatico_alterado'])

    def test_c_dry_run_nao_escreve_nada(self):
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
