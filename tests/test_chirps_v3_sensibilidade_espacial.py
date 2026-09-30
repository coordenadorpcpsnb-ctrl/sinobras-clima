#!/usr/bin/env python3
"""
tests/test_chirps_v3_sensibilidade_espacial.py — Fase 2C.3B, item 2,
testes SINTÉTICOS (nenhuma rede real — abrir_fn injetado com
rasterio.io.MemoryFile).

Roda com:
    python -m unittest tests.test_chirps_v3_sensibilidade_espacial -v
"""

import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd
from rasterio.io import MemoryFile
from rasterio.transform import Affine

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import chirps_v3_sensibilidade_espacial as sens  # noqa: E402
import _chirps_v3 as v3  # noqa: E402


@contextmanager
def _dataset_sintetico_grande(valor_centro=100.0, valor_leste=110.0, valor_sul=90.0,
                               dtype='float32'):
    """Grade sintética 7200x2400, grade/origem REAL do CHIRPS v3.0
    (necessária para verificar_grade aprovar), com valores controlados
    no pixel de referência e alguns vizinhos — nenhuma rede."""
    transform = Affine(v3.RESOLUCAO_GRAUS_REAL_CONFIRMADA, 0, -180.0,
                        0, -v3.RESOLUCAO_GRAUS_REAL_CONFIRMADA, 60.0)
    dados = np.full((v3.HEIGHT_ESPERADO, v3.WIDTH_ESPERADO), v3.NODATA_SENTINELA, dtype=dtype)
    with MemoryFile() as mem:
        profile = dict(driver='GTiff', height=v3.HEIGHT_ESPERADO, width=v3.WIDTH_ESPERADO,
                        count=1, dtype=dtype, crs='EPSG:4326', transform=transform)
        with mem.open(**profile) as ds:
            pixel = v3.localizar_pixel(ds, lat=v3.FAZENDAS_LAT, lon=v3.FAZENDAS_LON)
            row, col = pixel['row'], pixel['col']
            dados[row, col] = valor_centro
            dados[row, col + 1] = valor_leste     # L
            dados[row + 1, col] = valor_sul        # S
            ds.write(dados, 1)
        with mem.open() as ds2:
            yield ds2


class ExecutarAnaliseSensibilidadeTestCase(unittest.TestCase):
    def test_a_le_referencia_e_vizinhos_para_cada_mes(self):
        @contextmanager
        def _abrir_fn(ano, mes, formato):
            with _dataset_sintetico_grande() as ds:
                yield ds

        with unittest_patch_time():
            resultados = sens.executar_analise_sensibilidade(
                meses=[(1991, 1), (1991, 4)], abrir_fn=_abrir_fn)
        self.assertEqual(len(resultados), 2)
        for r in resultados:
            self.assertEqual(r['status'], 'ok')
            self.assertIn('vizinhos', r['comparacao'])
            self.assertEqual(r['comparacao']['vizinhos']['centro']['valor_mm'], 100.0)
            self.assertEqual(r['comparacao']['vizinhos']['L']['valor_mm'], 110.0)
            self.assertEqual(r['comparacao']['vizinhos']['S']['valor_mm'], 90.0)

    def test_b_grade_inesperada_e_sinalizada_sem_quebrar(self):
        @contextmanager
        def _abrir_fn_grade_errada(ano, mes, formato):
            transform = Affine(0.25, 0, -180.0, 0, -0.25, 60.0)
            with MemoryFile() as mem:
                profile = dict(driver='GTiff', height=480, width=1440, count=1,
                                dtype='float32', crs='EPSG:4326', transform=transform)
                with mem.open(**profile):
                    pass
                with mem.open() as ds:
                    yield ds

        with unittest_patch_time():
            resultados = sens.executar_analise_sensibilidade(
                meses=[(1991, 1)], abrir_fn=_abrir_fn_grade_errada)
        self.assertEqual(resultados[0]['status'], 'grade_inesperada')
        self.assertIsNone(resultados[0]['comparacao'])

    def test_c_erro_de_abertura_nao_interrompe_os_outros_meses(self):
        chamadas = []

        @contextmanager
        def _abrir_fn(ano, mes, formato):
            chamadas.append((ano, mes))
            if mes == 1:
                raise RuntimeError("falha simulada")
            with _dataset_sintetico_grande() as ds:
                yield ds

        with unittest_patch_time():
            resultados = sens.executar_analise_sensibilidade(
                meses=[(1991, 1), (1991, 4)], abrir_fn=_abrir_fn)
        self.assertEqual(resultados[0]['status'], 'erro')
        self.assertEqual(resultados[1]['status'], 'ok')
        self.assertEqual(len(chamadas), 2)

    def test_d_nunca_substitui_pixel_de_referencia(self):
        """Item 2 — nunca troca a referência automaticamente. Só
        confirmação estática: a função não escreve em _chirps_v3.py
        nem em nenhuma constante de referência."""
        import inspect
        src = inspect.getsource(sens.executar_analise_sensibilidade)
        self.assertNotIn('FAZENDAS_LAT =', src)
        self.assertNotIn('FAZENDAS_LON =', src)


class EstatisticasSensibilidadeTestCase(unittest.TestCase):
    def _df_bruto_sintetico(self, diff_leste=10.0, diff_sul=-10.0, diff_norte=0.5):
        linhas = []
        for ano, mes in [(1991, 1), (1991, 4)]:
            linhas.append({'ano': ano, 'mes': mes, 'vizinho': 'centro', 'status_entrada': 'ok',
                            'dentro_do_raster': True, 'status_pixel': 'ok', 'valor_mm': 100.0})
            linhas.append({'ano': ano, 'mes': mes, 'vizinho': 'L', 'status_entrada': 'ok',
                            'dentro_do_raster': True, 'status_pixel': 'ok',
                            'valor_mm': 100.0 + diff_leste})
            linhas.append({'ano': ano, 'mes': mes, 'vizinho': 'S', 'status_entrada': 'ok',
                            'dentro_do_raster': True, 'status_pixel': 'ok',
                            'valor_mm': 100.0 + diff_sul})
            linhas.append({'ano': ano, 'mes': mes, 'vizinho': 'N', 'status_entrada': 'ok',
                            'dentro_do_raster': True, 'status_pixel': 'ok',
                            'valor_mm': 100.0 + diff_norte})
        return pd.DataFrame(linhas)

    def test_a_vazio_retorna_zero_comparaveis(self):
        resultado = sens.montar_estatisticas_sensibilidade(pd.DataFrame())
        self.assertEqual(resultado['n_meses_comparaveis'], 0)

    def test_b_calcula_diferenca_absoluta_e_relativa_por_vizinho(self):
        df = self._df_bruto_sintetico()
        resultado = sens.montar_estatisticas_sensibilidade(df)
        self.assertEqual(resultado['n_meses_comparaveis'], 2)
        # diff_media_mm é COM SINAL — L acima do centro (+10), S abaixo (-10)
        self.assertAlmostEqual(resultado['por_vizinho']['L']['diff_media_mm'], 10.0)
        self.assertAlmostEqual(resultado['por_vizinho']['S']['diff_media_mm'], -10.0)
        # diff_abs_media_mm é a magnitude — 10.0 para os dois, nunca negativa
        self.assertAlmostEqual(resultado['por_vizinho']['L']['diff_abs_media_mm'], 10.0)
        self.assertAlmostEqual(resultado['por_vizinho']['S']['diff_abs_media_mm'], 10.0)
        self.assertAlmostEqual(resultado['por_vizinho']['L']['diff_rel_media_pct'], 10.0)

    def test_b2_diferenca_com_sinal_nunca_e_confundida_com_absoluta_em_amostra_mista(self):
        """CORREÇÃO (auditoria independente) — com diferenças de sinais
        opostos na amostra, a média COM SINAL se cancela parcialmente
        (mascarando a dispersão real), enquanto a média ABSOLUTA não.
        As duas precisam ser numericamente DIFERENTES aqui, provando
        que não são mais a mesma conta com nome trocado."""
        linhas = [
            {'ano': 1991, 'mes': 1, 'vizinho': 'centro', 'status_entrada': 'ok',
             'dentro_do_raster': True, 'status_pixel': 'ok', 'valor_mm': 100.0},
            {'ano': 1991, 'mes': 1, 'vizinho': 'L', 'status_entrada': 'ok',
             'dentro_do_raster': True, 'status_pixel': 'ok', 'valor_mm': 120.0},  # +20
            {'ano': 1991, 'mes': 4, 'vizinho': 'centro', 'status_entrada': 'ok',
             'dentro_do_raster': True, 'status_pixel': 'ok', 'valor_mm': 100.0},
            {'ano': 1991, 'mes': 4, 'vizinho': 'L', 'status_entrada': 'ok',
             'dentro_do_raster': True, 'status_pixel': 'ok', 'valor_mm': 90.0},   # -10
        ]
        df = pd.DataFrame(linhas)
        resultado = sens.montar_estatisticas_sensibilidade(df)
        stats_l = resultado['por_vizinho']['L']
        self.assertAlmostEqual(stats_l['diff_media_mm'], 5.0)        # (20 + -10) / 2
        self.assertAlmostEqual(stats_l['diff_abs_media_mm'], 15.0)   # (20 + 10) / 2
        self.assertNotEqual(stats_l['diff_media_mm'], stats_l['diff_abs_media_mm'])
        self.assertAlmostEqual(stats_l['diff_abs_maxima_mm'], 20.0)
        self.assertEqual(stats_l['diff_abs_maxima_mes'], '1991-01')
        self.assertEqual(stats_l['diff_abs_maxima_vizinho'], 'L')

    def test_c_distingue_vizinhos_relevantes_dos_demais(self):
        df = self._df_bruto_sintetico(diff_leste=50.0, diff_sul=50.0, diff_norte=1.0)
        resultado = sens.montar_estatisticas_sensibilidade(df)
        self.assertGreater(resultado['diff_abs_media_vizinhos_relevantes_mm'],
                            resultado['diff_abs_media_demais_vizinhos_mm'])

    def test_c2_nao_conclui_automaticamente_irrelevancia_pratica(self):
        """CORREÇÃO (auditoria independente) — mesmo quando a média
        absoluta dos vizinhos relevantes é MENOR que a dos demais (o
        cenário que antes disparava a conclusão automática de
        'influência prática irrelevante'), a interpretação não pode
        mais afirmar isso automaticamente."""
        df = self._df_bruto_sintetico(diff_leste=1.0, diff_sul=1.0, diff_norte=50.0)
        resultado = sens.montar_estatisticas_sensibilidade(df)
        self.assertLess(resultado['diff_abs_media_vizinhos_relevantes_mm'],
                         resultado['diff_abs_media_demais_vizinhos_mm'])
        interpretacao = resultado['interpretacao'].lower()
        self.assertNotIn('não parece ter influência prática relevante', interpretacao)
        self.assertIn('não é suficiente', interpretacao)
        self.assertIn('depende da aplicação', interpretacao)
        self.assertIn('época do ano', interpretacao)

    def test_c3_apresenta_diferencas_maximas_no_resultado(self):
        df = self._df_bruto_sintetico(diff_leste=50.0, diff_sul=-30.0, diff_norte=1.0)
        resultado = sens.montar_estatisticas_sensibilidade(df)
        self.assertIn('diff_abs_maxima_vizinhos_relevantes_mm', resultado)
        self.assertIn('diff_abs_maxima_demais_vizinhos_mm', resultado)
        self.assertIsNotNone(resultado['diff_abs_maxima_vizinhos_relevantes_mm'])
        self.assertGreaterEqual(resultado['diff_abs_maxima_vizinhos_relevantes_mm'], 50.0)

    def test_d_ignora_vizinhos_fora_do_raster_ou_com_nodata(self):
        linhas = [
            {'ano': 1991, 'mes': 1, 'vizinho': 'centro', 'status_entrada': 'ok',
             'dentro_do_raster': True, 'status_pixel': 'ok', 'valor_mm': 100.0},
            {'ano': 1991, 'mes': 1, 'vizinho': 'L', 'status_entrada': 'ok',
             'dentro_do_raster': False},
            {'ano': 1991, 'mes': 1, 'vizinho': 'S', 'status_entrada': 'ok',
             'dentro_do_raster': True, 'status_pixel': 'nodata_sentinela', 'valor_mm': None},
        ]
        df = pd.DataFrame(linhas)
        resultado = sens.montar_estatisticas_sensibilidade(df)
        self.assertNotIn('L', resultado['por_vizinho'])
        self.assertNotIn('S', resultado['por_vizinho'])

    def test_e_nunca_calcula_skill(self):
        import inspect
        src = inspect.getsource(sens.montar_estatisticas_sensibilidade)
        for termo in ('rmse', 'mae', 'crps', 'skill'):
            self.assertNotIn(termo, src.lower())


class RelatorioSensibilidadeTestCase(unittest.TestCase):
    def test_a_relatorio_gerado_sem_erro(self):
        df = EstatisticasSensibilidadeTestCase()._df_bruto_sintetico()
        metadata = sens.montar_metadata_sensibilidade(df)
        relatorio = sens.gerar_relatorio_sensibilidade_markdown(metadata)
        self.assertIn('sensibilidade espacial', relatorio.lower())
        self.assertIn('CHIRPS_v3_ponto_centroide', relatorio)

    def test_b_metadata_confirma_pixel_nao_alterado(self):
        df = EstatisticasSensibilidadeTestCase()._df_bruto_sintetico()
        metadata = sens.montar_metadata_sensibilidade(df)
        self.assertFalse(metadata['pixel_de_referencia_alterado'])


def unittest_patch_time():
    from unittest.mock import patch
    return patch.object(sens.time, 'sleep', return_value=None)


if __name__ == '__main__':
    unittest.main()
