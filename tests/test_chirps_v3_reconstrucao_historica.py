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

import pandas as pd

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

    def test_f_descricao_da_retomada_inclui_nodata_nan(self):
        """CORREÇÃO (revisão adicional) — a descrição de 'retomada' era
        uma lista hardcoded ('ok/zero_real/nodata_sentinela/
        mes_ausente') que ficou incompleta quando 'nodata_nan' passou a
        integrar STATUS_NODATA_REPROCESSAMENTO/STATUS_RESOLVIDOS em
        scripts/chirps_v3_piloto.py. Agora tem que refletir o conjunto
        real, não uma lista solta que pode divergir de novo."""
        plano = rec.montar_plano_reconstrucao()
        self.assertIn('nodata_nan', plano['retomada'])

    def test_g_descricao_da_retomada_e_derivada_das_constantes_do_piloto(self):
        """Preferência explícita da revisão: evitar lista hardcoded de
        novo — todo status de piloto.STATUS_RESOLVIDOS precisa aparecer
        na descrição, e ela precisa distinguir valor científico válido
        de 'resolvido só para retomada'."""
        plano = rec.montar_plano_reconstrucao()
        texto = plano['retomada']
        for status in piloto.STATUS_RESOLVIDOS:
            self.assertIn(status, texto)
        self.assertIn('reprocessar_ausentes_ou_nodata', texto)
        self.assertIn('valor científico', texto.lower())

    def test_h_relatorio_do_plano_reflete_a_descricao_corrigida(self):
        plano = rec.montar_plano_reconstrucao()
        relatorio = rec.gerar_relatorio_plano_markdown(plano)
        self.assertIn('nodata_nan', relatorio)


class InterfaceDeSelecaoDeLoteTestCase(unittest.TestCase):
    """Fase 2C.3B, item 3 — 'selecionar explicitamente um lote,
    verificar seu estado e consultar os meses pendentes'."""

    def setUp(self):
        tmpdir_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir_ctx.cleanup)
        self.tmpdir = Path(tmpdir_ctx.name)
        self.csv_path = self.tmpdir / 'chirps_v3_1981_2011.csv'
        p1 = patch.object(rec, 'CAMINHO_CSV', self.csv_path)
        p1.start()
        self.addCleanup(p1.stop)

    def test_a_obter_lote_por_indice(self):
        lote = rec.obter_lote(0)
        self.assertEqual(lote, rec.LOTES_HISTORICOS[0])
        self.assertEqual(lote[0], (1981, 1))
        self.assertEqual(lote[-1], (1982, 12))

    def test_b_obter_lote_indice_invalido_levanta_erro(self):
        with self.assertRaises(ValueError):
            rec.obter_lote(len(rec.LOTES_HISTORICOS))
        with self.assertRaises(ValueError):
            rec.obter_lote(-1)

    def test_c_obter_lote_aceita_lista_explicita(self):
        lote_custom = [(1981, 1), (1981, 2)]
        self.assertEqual(rec.obter_lote(lote_custom), lote_custom)

    def test_d_listar_lotes_cobre_todos_com_indices_sequenciais(self):
        lista = rec.listar_lotes()
        self.assertEqual(len(lista), len(rec.LOTES_HISTORICOS))
        self.assertEqual([l['indice'] for l in lista], list(range(len(rec.LOTES_HISTORICOS))))
        self.assertEqual(lista[0]['inicio'], '1981-01')
        self.assertEqual(lista[0]['fim'], '1982-12')
        self.assertEqual(lista[0]['n_meses'], 24)

    def test_e_meses_pendentes_lote_por_indice(self):
        pendentes = rec.meses_pendentes_lote(0)
        self.assertEqual(set(pendentes), set(rec.LOTES_HISTORICOS[0]))

    def test_f_meses_pendentes_lote_exclui_meses_ja_resolvidos(self):
        linha = {'ano': 1981, 'mes': 1, 'status': 'ok', 'valor_mm': 10.0}
        pd.DataFrame([linha]).to_csv(self.csv_path, index=False)
        pendentes = rec.meses_pendentes_lote(0)
        self.assertNotIn((1981, 1), pendentes)
        self.assertEqual(len(pendentes), 23)

    def test_g_estado_lote_sem_dados_reprova(self):
        estado = rec.estado_lote(0)
        self.assertFalse(estado['aprovado'])
        self.assertEqual(estado['n_meses_esperados'], 24)

    def test_h_estado_lote_ignora_meses_de_outro_lote_persistido(self):
        """Fase 2C.3B, item 1b — mesmo com outro lote já persistido no
        MESMO arquivo, estado_lote(0) só deve contar os meses do lote
        0."""
        linhas_lote_0 = [{'ano': a, 'mes': m, 'status': 'ok', 'valor_mm': 5.0}
                          for a, m in rec.LOTES_HISTORICOS[0]]
        linhas_lote_1 = [{'ano': a, 'mes': m, 'status': 'erro_inesperado', 'valor_mm': None}
                          for a, m in rec.LOTES_HISTORICOS[1]]
        pd.DataFrame(linhas_lote_0 + linhas_lote_1).to_csv(self.csv_path, index=False)
        estado = rec.estado_lote(0)
        self.assertTrue(estado['aprovado'])
        self.assertEqual(estado['meses_com_falha'], [])

    def test_i_executar_lote_aceita_indice(self):
        chamadas = []

        def _fake(ano, mes):
            chamadas.append((ano, mes))
            return {'ano': ano, 'mes': mes, 'status': 'ok', 'valor_mm': 5.0}

        with patch.object(v3, 'extrair_pixel_mensal', side_effect=_fake), \
             patch.object(piloto.time, 'sleep', return_value=None):
            rec.executar_lote(0, max_requisicoes=2)
        self.assertEqual(len(chamadas), 2)
        self.assertEqual(set(chamadas), {(1981, 1), (1981, 2)})

    def test_j_montar_relatorio_lote_nao_dispara_outros_lotes(self):
        chamado = {'n': 0}

        def _fake(*a, **kw):
            chamado['n'] += 1
            raise AssertionError("não deveria chamar rede")

        with patch.object(v3, 'extrair_pixel_mensal', side_effect=_fake):
            dados = rec.montar_relatorio_lote(0)
        self.assertEqual(chamado['n'], 0)
        self.assertEqual(dados['indice_lote'], 0)
        self.assertIn('estado_geral_reconstrucao', dados)
        self.assertEqual(dados['estado_geral_reconstrucao']['n_lotes_total'],
                          len(rec.LOTES_HISTORICOS))

    def test_k_relatorio_lote_markdown_referencia_sensibilidade_sem_duplicar(self):
        dados = rec.montar_relatorio_lote(0)
        relatorio = rec.gerar_relatorio_lote_markdown(dados)
        self.assertIn('sensibilidade espacial', relatorio.lower())
        self.assertIn('SEPARADAMENTE', relatorio)

    def test_l_relatorio_lote_markdown_nunca_calcula_skill(self):
        dados = rec.montar_relatorio_lote(0)
        relatorio = rec.gerar_relatorio_lote_markdown(dados)
        self.assertNotIn('RMSE', relatorio.upper())
        self.assertNotIn('CRPS', relatorio.upper())


if __name__ == '__main__':
    unittest.main()
