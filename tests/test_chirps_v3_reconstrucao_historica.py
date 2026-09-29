#!/usr/bin/env python3
"""
tests/test_chirps_v3_reconstrucao_historica.py — Fase 2C.3B, testes do
PLANO de reconstrução histórica (scripts/chirps_v3_reconstrucao_
historica.py). Item 4 da revisão: "Não iniciar automaticamente a
extração dos 365 meses nesta tarefa" — nenhum teste aqui faz uma
requisição de rede real; v3.extrair_pixel_mensal é sempre mockado
quando exercitamos executar_lote().

Roda com:
    python -m unittest tests.test_chirps_v3_reconstrucao_historica -v
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import chirps_v3_reconstrucao_historica as rec  # noqa: E402
import chirps_v3_piloto as piloto  # noqa: E402
import _chirps_v3 as v3  # noqa: E402


class PeriodoTestCase(unittest.TestCase):
    """Item 4 — jan/1981 a mai/2011, 365 meses, dividido em
    climatologia (1981-1990) e verificação (1991-01 a 2011-05)."""

    def test_a_periodo_completo_tem_365_meses(self):
        self.assertEqual(len(rec.PERIODO_COMPLETO), 365)

    def test_b_climatologia_tem_120_meses(self):
        self.assertEqual(len(rec.PERIODO_CLIMATOLOGIA), 120)
        self.assertEqual(rec.PERIODO_CLIMATOLOGIA[0], (1981, 1))
        self.assertEqual(rec.PERIODO_CLIMATOLOGIA[-1], (1990, 12))

    def test_c_verificacao_tem_245_meses(self):
        self.assertEqual(len(rec.PERIODO_VERIFICACAO), 245)
        self.assertEqual(rec.PERIODO_VERIFICACAO[0], (1991, 1))
        self.assertEqual(rec.PERIODO_VERIFICACAO[-1], (2011, 5))

    def test_d_soma_dos_dois_periodos_bate_com_o_completo(self):
        self.assertEqual(len(rec.PERIODO_CLIMATOLOGIA) + len(rec.PERIODO_VERIFICACAO),
                          len(rec.PERIODO_COMPLETO))
        self.assertEqual(rec.PERIODO_CLIMATOLOGIA + rec.PERIODO_VERIFICACAO, rec.PERIODO_COMPLETO)

    def test_e_periodo_completo_nao_tem_lacunas_nem_duplicatas(self):
        self.assertEqual(len(set(rec.PERIODO_COMPLETO)), len(rec.PERIODO_COMPLETO))
        for i in range(1, len(rec.PERIODO_COMPLETO)):
            ano_ant, mes_ant = rec.PERIODO_COMPLETO[i - 1]
            ano, mes = rec.PERIODO_COMPLETO[i]
            mes_esperado = mes_ant + 1 if mes_ant < 12 else 1
            ano_esperado = ano_ant if mes_ant < 12 else ano_ant + 1
            self.assertEqual((ano, mes), (ano_esperado, mes_esperado))


class LotesTestCase(unittest.TestCase):
    """Item 4 — processamento em lotes."""

    def test_a_lotes_cobrem_o_periodo_completo_sem_lacunas(self):
        todos = [m for lote in rec.LOTES_HISTORICOS for m in lote]
        self.assertEqual(todos, rec.PERIODO_COMPLETO)

    def test_b_tamanho_de_lote_customizavel(self):
        lotes = rec.definir_lotes(meses=rec.PERIODO_COMPLETO, tamanho_lote=12)
        self.assertEqual(len(lotes), 31)   # 365 / 12 = 30.4 -> 31 lotes
        self.assertEqual(sum(len(lote) for lote in lotes), 365)

    def test_c_nenhum_lote_e_o_periodo_inteiro_de_uma_vez(self):
        for lote in rec.LOTES_HISTORICOS:
            self.assertLess(len(lote), len(rec.PERIODO_COMPLETO))


class ArmazenamentoSeparadoTestCase(unittest.TestCase):
    """Item 4 — 'Não utilizar o mesmo diretório ou os mesmos arquivos
    da referência operacional existente' — nem os do piloto."""

    def test_a_caminho_diferente_do_piloto(self):
        self.assertNotEqual(rec.CAMINHO_CSV, piloto.DATA_PILOTO_CSV)

    def test_b_caminho_diferente_dos_arquivos_de_producao(self):
        self.assertNotEqual(rec.CAMINHO_CSV, piloto.CHIRPS_V2_PONTO_PATH)
        self.assertNotEqual(rec.CAMINHO_CSV, piloto.SERIE_PRODUCAO_PATH)

    def test_c_diretorio_proprio_diferente_do_diretorio_data_raiz(self):
        self.assertEqual(rec.CAMINHO_CSV.parent, rec.DIRETORIO_SAIDA)
        self.assertNotEqual(rec.DIRETORIO_SAIDA, piloto.DATA_PILOTO_CSV.parent)

    def test_d_plano_registra_os_arquivos_nunca_reutilizados(self):
        plano = rec.montar_plano_reconstrucao()
        nunca_reutiliza = plano['armazenamento_separado']['nunca_reutiliza']
        self.assertIn('data/chirps_v3_piloto.csv', nunca_reutiliza)
        self.assertIn('data/chirps_1981_2025.csv', nunca_reutiliza)
        self.assertIn('data/serie_subst.csv', nunca_reutiliza)


class ExecutarLoteTestCase(unittest.TestCase):
    """Reaproveita scripts/chirps_v3_piloto.py::executar_piloto — só
    confirmamos aqui que a integração usa CAMINHO_CSV (não o do
    piloto) e nunca processa mais que o lote passado. Sempre com
    v3.extrair_pixel_mensal mockado — nenhuma rede real."""

    def setUp(self):
        tmpdir_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir_ctx.cleanup)
        self.tmpdir = Path(tmpdir_ctx.name)
        self.csv_path = self.tmpdir / 'chirps_v3_1981_2011.csv'
        p1 = patch.object(rec, 'CAMINHO_CSV', self.csv_path)
        p1.start()
        self.addCleanup(p1.stop)

    def test_a_executa_so_o_lote_pedido(self):
        chamadas = []

        def _fake(ano, mes):
            chamadas.append((ano, mes))
            return {'ano': ano, 'mes': mes, 'status': 'ok', 'valor_mm': 5.0}

        lote = rec.PERIODO_CLIMATOLOGIA[:3]
        with patch.object(v3, 'extrair_pixel_mensal', side_effect=_fake), \
             patch.object(piloto.time, 'sleep', return_value=None):
            resultado = rec.executar_lote(lote)
        self.assertEqual(len(chamadas), 3)
        self.assertEqual(len(resultado), 3)
        self.assertTrue(self.csv_path.exists())

    def test_b_grava_em_caminho_csv_nao_no_arquivo_do_piloto(self):
        with patch.object(v3, 'extrair_pixel_mensal',
                           side_effect=lambda a, m: {'ano': a, 'mes': m, 'status': 'ok',
                                                      'valor_mm': 1.0}), \
             patch.object(piloto.time, 'sleep', return_value=None):
            rec.executar_lote(rec.PERIODO_CLIMATOLOGIA[:2])
        self.assertTrue(self.csv_path.exists())
        self.assertFalse((self.tmpdir / 'chirps_v3_piloto.csv').exists())


class MontarPlanoReconstrucaoTestCase(unittest.TestCase):
    def test_a_nao_executa_extracao_nenhuma(self):
        plano = rec.montar_plano_reconstrucao()
        self.assertFalse(plano['extracao_dos_365_meses_iniciada_nesta_tarefa'])

    def test_b_preserva_os_17_registros_do_piloto(self):
        plano = rec.montar_plano_reconstrucao()
        self.assertTrue(plano['os_17_registros_do_piloto_preservados'])

    def test_c_funcao_nao_chama_rede(self):
        import inspect
        src = inspect.getsource(rec.montar_plano_reconstrucao)
        self.assertNotIn('requests.', src)
        self.assertNotIn('urlopen', src)
        self.assertNotIn('extrair_pixel_mensal(', src)

    def test_d_relatorio_gerado_sem_erro(self):
        plano = rec.montar_plano_reconstrucao()
        relatorio = rec.gerar_relatorio_plano_markdown(plano)
        self.assertIn('365', relatorio)
        self.assertIn('120', relatorio)
        self.assertIn('245', relatorio)

    def test_e_dry_run_plan_nao_toca_rede(self):
        """imprimir_plano() (chamado por --dry-run-plan) não deve
        fazer nenhuma chamada de rede — mockamos extrair_pixel_mensal
        para levantar se for chamado."""
        with patch.object(v3, 'extrair_pixel_mensal',
                           side_effect=AssertionError("não deveria ser chamado")):
            rec.imprimir_plano()   # não deve levantar


if __name__ == '__main__':
    unittest.main()
