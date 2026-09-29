#!/usr/bin/env python3
"""
tests/test_chirps_v3_piloto.py — Fase 2C.3A, testes do orquestrador do
piloto (scripts/chirps_v3_piloto.py): retomada, limitação de
downloads, controle de qualidade, comparação com dados existentes
(estatística descritiva, nunca skill), especificação do protocolo
científico.

A lógica de EXTRAÇÃO propriamente dita (leitura de raster, classificação
de valor, verificação de grade) já é testada em
tests/test_chirps_v3_extracao.py — aqui o alvo é a ORQUESTRAÇÃO, com
v3.extrair_pixel_mensal mockado (nenhuma rede real).

Roda com:
    python -m unittest tests.test_chirps_v3_piloto -v
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import chirps_v3_piloto as piloto  # noqa: E402
import _chirps_v3 as v3  # noqa: E402


def _resultado_falso(ano, mes, status='ok', valor_mm=10.0):
    return {'ano': ano, 'mes': mes, 'status': status, 'valor_mm': valor_mm,
            'formato': 'cog', 'url': f'http://x/{ano}.{mes:02d}.cog', 'versao_chirps': 'v3.0',
            'data_extracao_utc': '2026-01-01T00:00:00+00:00'}


class MesesPilotoTestCase(unittest.TestCase):
    def test_a_dezessete_meses_fixos(self):
        self.assertEqual(len(piloto.MESES_PILOTO), 17)

    def test_b_cobre_os_quatro_anos_e_trimestres_pedidos(self):
        for ano in (1991, 1998, 2005, 2010):
            for mes in (1, 4, 7, 10):
                self.assertIn((ano, mes), piloto.MESES_PILOTO)

    def test_c_inclui_maio_2011(self):
        self.assertIn((2011, 5), piloto.MESES_PILOTO)

    def test_d_nunca_a_serie_completa(self):
        """Nenhum mês fora da lista fixa de 17 — nunca 1981-presente."""
        anos = {a for a, m in piloto.MESES_PILOTO}
        self.assertEqual(anos, {1991, 1998, 2005, 2010, 2011})


class RetomadaTestCase(unittest.TestCase):
    """Item 4 — mecanismo de retomada: meses já resolvidos nunca são
    reprocessados; falhas são retentadas."""

    def setUp(self):
        tmpdir_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir_ctx.cleanup)
        self.tmpdir = Path(tmpdir_ctx.name)
        self.csv_path = self.tmpdir / 'chirps_v3_piloto.csv'
        p1 = patch.object(piloto, 'DATA_PILOTO_CSV', self.csv_path)
        p1.start()
        self.addCleanup(p1.stop)

    def test_a_todos_pendentes_quando_nao_ha_csv_persistido(self):
        pendentes = piloto.meses_pendentes(meses=[(1991, 1), (1991, 4)])
        self.assertEqual(set(pendentes), {(1991, 1), (1991, 4)})

    def test_b_mes_ok_nao_e_reprocessado(self):
        pd.DataFrame([_resultado_falso(1991, 1, status='ok')]).to_csv(self.csv_path, index=False)
        pendentes = piloto.meses_pendentes(meses=[(1991, 1), (1991, 4)])
        self.assertEqual(pendentes, [(1991, 4)])

    def test_c_mes_com_falha_e_retentado(self):
        pd.DataFrame([_resultado_falso(1991, 1, status='erro_inesperado', valor_mm=None)]
                     ).to_csv(self.csv_path, index=False)
        pendentes = piloto.meses_pendentes(meses=[(1991, 1), (1991, 4)])
        self.assertIn((1991, 1), pendentes)

    def test_d_mes_ausente_no_servidor_nao_e_retentado(self):
        """404 real do CHC é uma resposta VÁLIDA (mês ausente), não
        uma falha — não deveria ficar retentando indefinidamente."""
        pd.DataFrame([_resultado_falso(1991, 1, status='mes_ausente', valor_mm=None)]
                     ).to_csv(self.csv_path, index=False)
        pendentes = piloto.meses_pendentes(meses=[(1991, 1), (1991, 4)])
        self.assertNotIn((1991, 1), pendentes)


class ExecutarPilotoTestCase(unittest.TestCase):
    """Orquestração fim a fim com v3.extrair_pixel_mensal mockado —
    nenhuma rede real."""

    def setUp(self):
        tmpdir_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir_ctx.cleanup)
        self.tmpdir = Path(tmpdir_ctx.name)
        self.csv_path = self.tmpdir / 'chirps_v3_piloto.csv'
        p1 = patch.object(piloto, 'DATA_PILOTO_CSV', self.csv_path)
        p1.start()
        self.addCleanup(p1.stop)

    def test_a_persiste_resultados_novos(self):
        with patch.object(v3, 'extrair_pixel_mensal',
                           side_effect=lambda ano, mes: _resultado_falso(ano, mes)), \
             patch.object(piloto.time, 'sleep', return_value=None):
            resultado_df = piloto.executar_piloto(meses=[(1991, 1), (1991, 4)])
        self.assertEqual(len(resultado_df), 2)
        self.assertTrue(self.csv_path.exists())

    def test_b_limite_de_requisicoes_por_execucao_e_respeitado(self):
        chamadas = []

        def _fake(ano, mes):
            chamadas.append((ano, mes))
            return _resultado_falso(ano, mes)

        with patch.object(v3, 'extrair_pixel_mensal', side_effect=_fake), \
             patch.object(piloto.time, 'sleep', return_value=None):
            piloto.executar_piloto(meses=[(1991, 1), (1991, 4), (1991, 7)], max_requisicoes=2)
        self.assertEqual(len(chamadas), 2,
                          "não deveria processar mais que max_requisicoes por execução")

    def test_c_segunda_execucao_nao_reprocessa_meses_ja_ok(self):
        chamadas = []

        def _fake(ano, mes):
            chamadas.append((ano, mes))
            return _resultado_falso(ano, mes)

        with patch.object(v3, 'extrair_pixel_mensal', side_effect=_fake), \
             patch.object(piloto.time, 'sleep', return_value=None):
            piloto.executar_piloto(meses=[(1991, 1)])
            piloto.executar_piloto(meses=[(1991, 1)])
        self.assertEqual(len(chamadas), 1, "segunda execução não deveria refazer a requisição")

    def test_d_nao_duplica_linha_ao_retentar_mes_com_falha(self):
        respostas = iter([
            _resultado_falso(1991, 1, status='erro_inesperado', valor_mm=None),
            _resultado_falso(1991, 1, status='ok', valor_mm=99.0),
        ])
        with patch.object(v3, 'extrair_pixel_mensal', side_effect=lambda a, m: next(respostas)), \
             patch.object(piloto.time, 'sleep', return_value=None):
            piloto.executar_piloto(meses=[(1991, 1)])
            resultado_final = piloto.executar_piloto(meses=[(1991, 1)])
        self.assertEqual(len(resultado_final), 1)
        self.assertEqual(resultado_final.iloc[0]['status'], 'ok')


class AvaliarQualidadePilotoTestCase(unittest.TestCase):
    """Item 5 — reprova o piloto se algo comprometer a integridade."""

    def test_a_todos_ok_aprova(self):
        df = pd.DataFrame([_resultado_falso(a, m) for a, m in piloto.MESES_PILOTO])
        resultado = piloto.avaliar_qualidade_piloto(df)
        self.assertTrue(resultado['aprovado'])

    def test_b_mes_faltando_reprova(self):
        df = pd.DataFrame([_resultado_falso(a, m) for a, m in piloto.MESES_PILOTO[:-1]])
        resultado = piloto.avaliar_qualidade_piloto(df)
        self.assertFalse(resultado['aprovado'])
        self.assertEqual(len(resultado['meses_faltando_sem_nenhuma_tentativa']), 1)

    def test_c_arquivo_corrompido_reprova(self):
        linhas = [_resultado_falso(a, m) for a, m in piloto.MESES_PILOTO]
        linhas[0]['status'] = 'arquivo_corrompido_ou_incompleto'
        linhas[0]['valor_mm'] = None
        df = pd.DataFrame(linhas)
        resultado = piloto.avaliar_qualidade_piloto(df)
        self.assertFalse(resultado['aprovado'])
        self.assertEqual(len(resultado['meses_com_falha']), 1)

    def test_d_grade_inesperada_reprova(self):
        linhas = [_resultado_falso(a, m) for a, m in piloto.MESES_PILOTO]
        linhas[0]['status'] = 'grade_inesperada'
        linhas[0]['valor_mm'] = None
        df = pd.DataFrame(linhas)
        resultado = piloto.avaliar_qualidade_piloto(df)
        self.assertFalse(resultado['aprovado'])

    def test_e_mes_ausente_no_servidor_nao_reprova(self):
        """404 real é uma resposta válida do CHC, não uma falha da
        nossa extração."""
        linhas = [_resultado_falso(a, m) for a, m in piloto.MESES_PILOTO]
        linhas[0]['status'] = 'mes_ausente'
        linhas[0]['valor_mm'] = None
        df = pd.DataFrame(linhas)
        resultado = piloto.avaliar_qualidade_piloto(df)
        self.assertTrue(resultado['aprovado'])
        self.assertEqual(resultado['n_meses_ausentes_no_servidor'], 1)

    def test_f_zero_real_conta_como_ok(self):
        linhas = [_resultado_falso(a, m) for a, m in piloto.MESES_PILOTO]
        linhas[0]['status'] = 'zero_real'
        linhas[0]['valor_mm'] = 0.0
        df = pd.DataFrame(linhas)
        resultado = piloto.avaliar_qualidade_piloto(df)
        self.assertTrue(resultado['aprovado'])
        self.assertEqual(resultado['n_meses_ok_ou_zero_real'], len(piloto.MESES_PILOTO))


class CompararComDadosExistentesTestCase(unittest.TestCase):
    """Item 6 — só estatística descritiva, nunca skill."""

    def test_a_sem_meses_validos_retorna_vazio(self):
        df = pd.DataFrame([_resultado_falso(1991, 1, status='mes_ausente', valor_mm=None)])
        resultado = piloto.comparar_com_dados_existentes(df)
        self.assertEqual(resultado['n_meses_comparaveis'], 0)

    def test_b_compara_contra_dados_reais_do_repositorio(self):
        """Sanidade contra os arquivos REAIS já commitados — para o
        mesmo mês/ano do piloto real (1991-01), a comparação deve
        achar as duas referências existentes."""
        df = pd.DataFrame([_resultado_falso(1991, 1, status='ok', valor_mm=342.9423)])
        resultado = piloto.comparar_com_dados_existentes(df)
        self.assertEqual(resultado['n_meses_comparaveis'], 1)
        c = resultado['comparacoes'][0]
        self.assertIn('prec_v2_ponto_existente', c)
        self.assertIn('prec_serie_producao', c)

    def test_c_nunca_calcula_skill(self):
        import inspect
        src = inspect.getsource(piloto.comparar_com_dados_existentes)
        for termo_proibido in ('rmse', 'mae', 'crps', 'correlacao', 'skill', 'calcular_skill'):
            self.assertNotIn(termo_proibido, src.lower())


class MontarEspecificacaoProtocoloTestCase(unittest.TestCase):
    """Item 7 — especificação, nenhuma execução/cálculo."""

    def test_a_cobre_todos_os_elementos_pedidos(self):
        e = piloto.montar_especificacao_protocolo_cfsv2()
        for chave in ('previsoes_cfsv2', 'correspondencia_inicializacao_horizonte_alvo',
                      'referencia_observacional_para_comparacao', 'climatologia_de_referencia',
                      'avaliacao_deterministica_e_probabilistica', 'separacao_de_resultados',
                      'dependencia_temporal_das_previsoes', 'semantica_de_h1',
                      'ressalva_retrospectiva_chirps_v3'):
            self.assertIn(chave, e)

    def test_b_apresenta_duas_climatologias_sem_misturar(self):
        e = piloto.montar_especificacao_protocolo_cfsv2()
        clim = e['climatologia_de_referencia']
        self.assertIn('alternativa_a_janela_expansivel', clim)
        self.assertIn('alternativa_b_leave_one_year_out', clim)
        self.assertIn('NÃO DEVEM ser misturadas', clim['regra_de_nao_mistura'])

    def test_c_h1_confirmado_como_mes_de_inicializacao(self):
        e = piloto.montar_especificacao_protocolo_cfsv2()
        texto = e['semantica_de_h1']
        self.assertIn('IGUAL ao mês da própria inicialização', texto)
        self.assertIn('lead1_igual_mes_inicializacao', texto)

    def test_d_ressalva_retrospectiva_presente(self):
        e = piloto.montar_especificacao_protocolo_cfsv2()
        self.assertIn('NÃO equivale', e['ressalva_retrospectiva_chirps_v3'])

    def test_e_nenhum_calculo_de_skill_na_funcao(self):
        import inspect
        src = inspect.getsource(piloto.montar_especificacao_protocolo_cfsv2)
        self.assertNotIn('pd.read_csv', src)
        self.assertNotIn('import requests', src)


class RelatoriosTestCase(unittest.TestCase):
    def test_a_relatorio_piloto_gerado_sem_erro(self):
        df = pd.DataFrame([_resultado_falso(a, m) for a, m in piloto.MESES_PILOTO])
        metadata = piloto.montar_metadata_piloto(df)
        relatorio = piloto.gerar_relatorio_piloto_markdown(df, metadata)
        self.assertIn('CHIRPS_v3_ponto_centroide', relatorio)
        self.assertIn('APROVADO', relatorio)

    def test_b_relatorio_protocolo_gerado_sem_erro(self):
        e = piloto.montar_especificacao_protocolo_cfsv2()
        relatorio = piloto.gerar_relatorio_protocolo_markdown(e)
        self.assertIn('Semântica de H1', relatorio)
        self.assertIn('Fase 2C.3C', relatorio)

    def test_c_metadata_registra_restricoes(self):
        df = pd.DataFrame([_resultado_falso(a, m) for a, m in piloto.MESES_PILOTO])
        metadata = piloto.montar_metadata_piloto(df)
        self.assertTrue(metadata['nenhuma_skill_calculada'])
        self.assertTrue(metadata['scripts_chirps_py_nao_modificado'])
        self.assertTrue(metadata['sarimax_xgboost_dashboard_nao_alterados'])
        self.assertTrue(metadata['nenhuma_serie_historica_completa_baixada'])


class NuncaAlteraModelosOuDashboardTestCase(unittest.TestCase):
    def test_a_script_nao_importa_update_dashboard_nem_modelos(self):
        """Menções a SARIMAX/XGBoost/dashboard em prosa (docstring, o
        campo de metadata que REGISTRA a restrição, a linha do
        relatório que a documenta) são esperadas e não contam — o que
        importa é ausência de IMPORT/CHAMADA real desses módulos."""
        codigo = (ROOT / 'scripts' / 'chirps_v3_piloto.py').read_text()
        self.assertNotIn('import update_dashboard', codigo)
        self.assertNotIn('import statsmodels', codigo)
        self.assertNotIn('import xgboost', codigo)
        self.assertNotIn('.fit(', codigo)
        self.assertNotIn('.predict(', codigo)

    def test_b_nao_escreve_em_data_chirps_1981_2025_nem_serie_subst(self):
        codigo = (ROOT / 'scripts' / 'chirps_v3_piloto.py').read_text()
        self.assertNotIn('CHIRPS_V2_PONTO_PATH.parent.mkdir', codigo)
        self.assertNotIn("CHIRPS_V2_PONTO_PATH, 'w'", codigo)
        self.assertNotIn("SERIE_PRODUCAO_PATH, 'w'", codigo)
        self.assertNotIn('.to_csv(CHIRPS_V2_PONTO_PATH', codigo)
        self.assertNotIn('.to_csv(SERIE_PRODUCAO_PATH', codigo)


if __name__ == '__main__':
    unittest.main()
