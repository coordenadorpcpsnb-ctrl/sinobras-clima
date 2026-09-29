#!/usr/bin/env python3
"""
tests/test_chirps_v3_extracao.py — Fase 2C.3A, testes SINTÉTICOS da
extração independente do CHIRPS v3.0 Final (scripts/_chirps_v3.py).

Nenhum teste aqui faz uma requisição de rede real: a leitura de raster
usa rasterio.io.MemoryFile (grades sintéticas pequenas, nunca o raster
global de 7200x2400 — exceto no único teste que precisa dessas
dimensões exatas para validar verificar_grade, e mesmo esse não
escreve dados de pixel, só o perfil/metadata) e a checagem de
disponibilidade HTTP usa unittest.mock.patch sobre urllib.request.urlopen
— mesmo padrão de tests/test_fetch_fallback.py e
tests/test_chirps_extracao_sintetica.py (mockar na fronteira de rede,
nunca a lógica de negócio).

Roda com:
    python -m unittest tests.test_chirps_v3_extracao -v
"""

import sys
import unittest
import urllib.error
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import Affine

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import _chirps_v3 as v3  # noqa: E402


@contextmanager
def _dataset_sintetico(width=20, height=20, origem_lon=-48.5, origem_lat=-7.0,
                        res=0.05, crs='EPSG:4326', dtype='float32', dados=None):
    """Grade sintética PEQUENA (nunca o raster global 7200x2400,
    exceto no teste dedicado de verificar_grade) — controla o transform
    para posicionar o pixel de teste onde quisermos. Nenhuma rede."""
    transform = Affine(res, 0, origem_lon, 0, -res, origem_lat)
    profile = dict(driver='GTiff', height=height, width=width, count=1,
                    dtype=dtype, crs=crs, transform=transform)
    with MemoryFile() as mem:
        with mem.open(**profile) as ds:
            if dados is not None:
                ds.write(dados, 1)
        with mem.open() as ds2:
            yield ds2


def _resposta_head_ok(headers=None):
    resp = MagicMock()
    resp.status = 200
    resp.headers = headers or {'ETag': '"abc"', 'Last-Modified': 'x', 'Content-Length': '123',
                                'Content-Type': 'application/octet-stream'}
    resp.__enter__ = lambda s: resp
    resp.__exit__ = lambda s, *a: False
    return resp


class MontarUrlTestCase(unittest.TestCase):
    def test_a_url_cog(self):
        url = v3.montar_url(1991, 1, 'cog')
        self.assertEqual(
            url, 'https://data.chc.ucsb.edu/products/CHIRPS/v3.0/monthly/global/'
                 'cogs/chirps-v3.0.1991.01.cog')

    def test_b_url_tif(self):
        url = v3.montar_url(2010, 12, 'tif')
        self.assertEqual(
            url, 'https://data.chc.ucsb.edu/products/CHIRPS/v3.0/monthly/global/'
                 'tifs/chirps-v3.0.2010.12.tif')

    def test_c_formato_desconhecido_levanta_erro(self):
        with self.assertRaises(ValueError):
            v3.montar_url(2000, 1, 'netcdf')

    def test_d_nao_e_produto_diario(self):
        """Item 2 da tarefa — nunca reconstruir por soma de diários:
        as URLs usadas apontam para o produto MENSAL já consolidado."""
        for formato in ('cog', 'tif'):
            self.assertIn('/monthly/', v3.montar_url(2000, 1, formato))
            self.assertNotIn('/daily/', v3.montar_url(2000, 1, formato))
            self.assertNotIn('/pentads', v3.montar_url(2000, 1, formato))
            self.assertNotIn('/dekads', v3.montar_url(2000, 1, formato))

    def test_e_e_produto_final_nao_prelim(self):
        for formato in ('cog', 'tif'):
            self.assertNotIn('/prelim/', v3.montar_url(2000, 1, formato))


class ClassificarValorTestCase(unittest.TestCase):
    """Seção 5 — nunca converter ausência em zero silenciosamente."""

    def test_a_nodata_sentinela_nunca_vira_zero(self):
        resultado = v3.classificar_valor(-9999.0)
        self.assertEqual(resultado['status'], 'nodata_sentinela')
        self.assertIsNone(resultado['valor_mm'])
        self.assertNotEqual(resultado['valor_mm'], 0.0)

    def test_b_nan_nunca_vira_zero(self):
        resultado = v3.classificar_valor(float('nan'))
        self.assertEqual(resultado['status'], 'nodata_nan')
        self.assertIsNone(resultado['valor_mm'])

    def test_c_zero_real_e_distinguido_de_nodata(self):
        resultado = v3.classificar_valor(0.0)
        self.assertEqual(resultado['status'], 'zero_real')
        self.assertEqual(resultado['valor_mm'], 0.0)
        self.assertNotEqual(resultado['status'],
                             v3.classificar_valor(-9999.0)['status'])

    def test_d_valor_normal_ok(self):
        resultado = v3.classificar_valor(123.456)
        self.assertEqual(resultado['status'], 'ok')
        self.assertAlmostEqual(resultado['valor_mm'], 123.456, places=3)

    def test_e_valor_negativo_desconhecido_nao_e_tratado_como_sentinela_conhecida(self):
        """Uma sentinela NOVA e não catalogada (ex.: -999.0) não deve
        ser confundida com -9999.0 nem com um valor válido — mesmo
        princípio de CLAUDE.md armadilha 6 (TSA/PDO): não confiar só
        numa lista fixa, sinalizar qualquer negativo fora do
        catalogado."""
        resultado = v3.classificar_valor(-999.0)
        self.assertEqual(resultado['status'], 'valor_negativo_nao_e_sentinela_conhecida')
        self.assertIsNotNone(resultado['valor_mm'])   # registrado p/ diagnóstico, não descartado

    def test_f_valor_implausivelmente_alto_e_sinalizado(self):
        resultado = v3.classificar_valor(5000.0)
        self.assertEqual(resultado['status'], 'valor_implausivel_alto')


class VerificarGradeTestCase(unittest.TestCase):
    """Seção 5 — reprova mudança inesperada de resolução/grade."""

    def test_a_grade_correta_aprova(self):
        transform = Affine(v3.RESOLUCAO_GRAUS, 0, -180.0, 0, -v3.RESOLUCAO_GRAUS, 60.0)
        profile = dict(driver='GTiff', height=v3.HEIGHT_ESPERADO, width=v3.WIDTH_ESPERADO,
                        count=1, dtype='float32', crs='EPSG:4326', transform=transform)
        with MemoryFile() as mem:
            with mem.open(**profile):
                pass
            with mem.open() as ds:
                resultado = v3.verificar_grade(ds)
        self.assertTrue(resultado['grade_ok'])
        self.assertEqual(resultado['problemas'], [])

    def test_b_resolucao_errada_reprova(self):
        transform = Affine(0.25, 0, -180.0, 0, -0.25, 60.0)
        profile = dict(driver='GTiff', height=480, width=1440, count=1,
                        dtype='float32', crs='EPSG:4326', transform=transform)
        with MemoryFile() as mem:
            with mem.open(**profile):
                pass
            with mem.open() as ds:
                resultado = v3.verificar_grade(ds)
        self.assertFalse(resultado['grade_ok'])
        self.assertTrue(any('resolução' in p for p in resultado['problemas']))

    def test_c_dimensoes_erradas_reprovam(self):
        transform = Affine(v3.RESOLUCAO_GRAUS, 0, -180.0, 0, -v3.RESOLUCAO_GRAUS, 60.0)
        profile = dict(driver='GTiff', height=100, width=100, count=1,
                        dtype='float32', crs='EPSG:4326', transform=transform)
        with MemoryFile() as mem:
            with mem.open(**profile):
                pass
            with mem.open() as ds:
                resultado = v3.verificar_grade(ds)
        self.assertFalse(resultado['grade_ok'])
        self.assertTrue(any('dimensões' in p for p in resultado['problemas']))

    def test_d_dtype_errado_reprova(self):
        transform = Affine(v3.RESOLUCAO_GRAUS, 0, -180.0, 0, -v3.RESOLUCAO_GRAUS, 60.0)
        profile = dict(driver='GTiff', height=v3.HEIGHT_ESPERADO, width=v3.WIDTH_ESPERADO,
                        count=1, dtype='int16', crs='EPSG:4326', transform=transform)
        with MemoryFile() as mem:
            with mem.open(**profile):
                pass
            with mem.open() as ds:
                resultado = v3.verificar_grade(ds)
        self.assertFalse(resultado['grade_ok'])
        self.assertTrue(any('dtype' in p for p in resultado['problemas']))

    def test_e_crs_errado_reprova(self):
        transform = Affine(v3.RESOLUCAO_GRAUS, 0, -180.0, 0, -v3.RESOLUCAO_GRAUS, 60.0)
        profile = dict(driver='GTiff', height=v3.HEIGHT_ESPERADO, width=v3.WIDTH_ESPERADO,
                        count=1, dtype='float32', crs='EPSG:3857', transform=transform)
        with MemoryFile() as mem:
            with mem.open(**profile):
                pass
            with mem.open() as ds:
                resultado = v3.verificar_grade(ds)
        self.assertFalse(resultado['grade_ok'])
        self.assertTrue(any('CRS' in p for p in resultado['problemas']))

    def test_f_origem_deslocada_reprova(self):
        """Item 2 da revisão — 'garantir que alterações inesperadas na
        origem ou no alinhamento da grade entre arquivos sejam
        detectadas'. Uma origem deslocada (ex.: meio pixel, um erro de
        georreferenciamento comum) precisa ser pega, mesmo com
        resolução/dimensões/CRS/dtype corretos."""
        transform = Affine(v3.RESOLUCAO_GRAUS, 0, -180.0 + v3.RESOLUCAO_GRAUS / 2,
                            0, -v3.RESOLUCAO_GRAUS, 60.0 + v3.RESOLUCAO_GRAUS / 2)
        profile = dict(driver='GTiff', height=v3.HEIGHT_ESPERADO, width=v3.WIDTH_ESPERADO,
                        count=1, dtype='float32', crs='EPSG:4326', transform=transform)
        with MemoryFile() as mem:
            with mem.open(**profile):
                pass
            with mem.open() as ds:
                resultado = v3.verificar_grade(ds)
        self.assertFalse(resultado['grade_ok'])
        self.assertTrue(any('origem' in p for p in resultado['problemas']))

    def test_g_resolucao_com_deriva_pequena_mas_alem_do_confirmado_reprova(self):
        """Uma resolução perto da nominal (passaria no teste antigo,
        tolerância 1e-6) mas longe do valor REAL confirmado ao vivo
        (tolerância apertada, 1e-9) deve ser reportada como possível
        deriva de grade entre arquivos — achado novo desta revisão."""
        res_com_deriva = 0.0500001   # bem mais que 1e-9 de distância do valor real confirmado
        transform = Affine(res_com_deriva, 0, -180.0, 0, -res_com_deriva, 60.0)
        profile = dict(driver='GTiff', height=v3.HEIGHT_ESPERADO, width=v3.WIDTH_ESPERADO,
                        count=1, dtype='float32', crs='EPSG:4326', transform=transform)
        with MemoryFile() as mem:
            with mem.open(**profile):
                pass
            with mem.open() as ds:
                resultado = v3.verificar_grade(ds)
        self.assertFalse(resultado['grade_ok'])
        self.assertTrue(any('REAL confirmado' in p for p in resultado['problemas']))

    def test_h_grade_com_a_resolucao_real_confirmada_aprova(self):
        """A grade REAL do CHIRPS v3.0 (resolução
        RESOLUCAO_GRAUS_REAL_CONFIRMADA, não a nominal limpa) deve
        aprovar — é exatamente o dado real, não uma anomalia."""
        transform = Affine(v3.RESOLUCAO_GRAUS_REAL_CONFIRMADA, 0, -180.0,
                            0, -v3.RESOLUCAO_GRAUS_REAL_CONFIRMADA, 60.0)
        profile = dict(driver='GTiff', height=v3.HEIGHT_ESPERADO, width=v3.WIDTH_ESPERADO,
                        count=1, dtype='float32', crs='EPSG:4326', transform=transform)
        with MemoryFile() as mem:
            with mem.open(**profile):
                pass
            with mem.open() as ds:
                resultado = v3.verificar_grade(ds)
        self.assertTrue(resultado['grade_ok'])


class LocalizarPixelTestCase(unittest.TestCase):
    """Seção 3 — localização direta pela transformação espacial EFETIVA
    do raster aberto, nunca a caixa pequena do ClimateSERV nem a
    constante nominal RESOLUCAO_GRAUS para aritmética de fração de
    pixel (correção da auditoria independente)."""

    def test_a_ponto_no_interior_de_um_pixel_fica_interior(self):
        with _dataset_sintetico(origem_lon=-48.5, origem_lat=-7.0) as ds:
            # -48.475 está a meio caminho do pixel [-48.50,-48.45) — bem
            # longe de qualquer borda
            pixel = v3.localizar_pixel(ds, lat=-7.025, lon=-48.475)
        self.assertEqual(pixel['classificacao_proximidade_lon'], 'interior_do_pixel')
        self.assertEqual(pixel['classificacao_proximidade_lat'], 'interior_do_pixel')
        self.assertFalse(pixel['ponto_sobre_ou_proximo_de_borda'])
        self.assertFalse(pixel['ponto_proximo_de_quina_compartilhada_por_4_pixels'])

    def test_b_ponto_exatamente_sobre_multiplo_da_resolucao_fica_sobre_borda_exata(self):
        """Numa grade SINTÉTICA construída com resolução limpa (0.05
        exato em Python/float64, sem o resíduo de precisão float32 da
        grade real do CHIRPS), um ponto cujas duas coordenadas são
        múltiplos exatos da resolução cai EXATAMENTE sobre a quina —
        cenário controlado, distinto do achado real com a grade
        verdadeira (ver test_f abaixo)."""
        with _dataset_sintetico(origem_lon=-48.5, origem_lat=-7.0, res=0.05) as ds:
            pixel = v3.localizar_pixel(ds, lat=-7.10, lon=-48.35)
        self.assertEqual(pixel['classificacao_proximidade_lon'], 'sobre_borda_exata')
        self.assertEqual(pixel['classificacao_proximidade_lat'], 'sobre_borda_exata')
        self.assertTrue(pixel['ponto_sobre_ou_proximo_de_borda'])
        self.assertTrue(pixel['ponto_proximo_de_quina_compartilhada_por_4_pixels'])

    def test_c_documenta_convencao_de_indexacao(self):
        with _dataset_sintetico() as ds:
            pixel = v3.localizar_pixel(ds, lat=-7.025, lon=-48.475)
        self.assertIn('floor', pixel['convencao_indexacao'])

    def test_d_bounds_e_centro_do_pixel_calculados_corretamente(self):
        with _dataset_sintetico(origem_lon=-48.5, origem_lat=-7.0) as ds:
            pixel = v3.localizar_pixel(ds, lat=-7.025, lon=-48.475)
        self.assertAlmostEqual(pixel['pixel_bounds_lon_min'], -48.5, places=4)
        self.assertAlmostEqual(pixel['pixel_bounds_lon_max'], -48.45, places=4)
        self.assertAlmostEqual(pixel['pixel_bounds_lat_min'], -7.05, places=4)
        self.assertAlmostEqual(pixel['pixel_bounds_lat_max'], -7.0, places=4)
        self.assertAlmostEqual(pixel['pixel_centro_lon'], -48.475, places=4)
        self.assertAlmostEqual(pixel['pixel_centro_lat'], -7.025, places=4)

    def test_e_nunca_usa_a_caixa_pequena_do_climateserv(self):
        """A função não CHAMA _geometria_ponto de scripts/_chirps.py
        (a caixa pequena da extração ClimateSERV atual) — Seção 3 da
        tarefa é explícita sobre isso. Mencionar o nome em prosa no
        docstring, explicando o que NÃO é feito, é esperado e não
        conta — o que importa é ausência de uma CHAMADA real."""
        import inspect
        src = inspect.getsource(v3.localizar_pixel)
        self.assertNotIn('_geometria_ponto(', src)
        self.assertNotIn('import _chirps', src)

    def test_f_regressao_grade_real_ponto_fica_proximo_nao_exatamente_sobre_borda(self):
        """REGRESSÃO do bug real encontrado pela auditoria independente
        (item 2): usando a resolução REAL confirmada da grade do
        CHIRPS v3.0 (não a nominal 0.05) e a mesma origem da grade
        real (-180,60), FAZENDAS_LAT/FAZENDAS_LON ficam classificados
        como 'proximo_de_borda' nos dois eixos — NÃO 'sobre_borda_exata'
        — reproduzindo exatamente o que data/chirps_v3_piloto.csv
        registra (pixel_bounds_* mostram o ponto a ~1-2 milionésimos
        de grau de duas bordas, não em cima delas). A versão anterior
        de localizar_pixel() usava a constante nominal RESOLUCAO_GRAUS
        como divisor e classificava isso, erradamente, como
        'sobre_borda_exata'/quina."""
        with _dataset_sintetico(width=7200, height=2400, origem_lon=-180.0, origem_lat=60.0,
                                 res=v3.RESOLUCAO_GRAUS_REAL_CONFIRMADA) as ds:
            pixel = v3.localizar_pixel(ds, lat=v3.FAZENDAS_LAT, lon=v3.FAZENDAS_LON)
        self.assertEqual(pixel['classificacao_proximidade_lon'], 'proximo_de_borda')
        self.assertEqual(pixel['classificacao_proximidade_lat'], 'proximo_de_borda')
        self.assertNotEqual(pixel['classificacao_proximidade_lon'], 'sobre_borda_exata')
        self.assertNotEqual(pixel['classificacao_proximidade_lat'], 'sobre_borda_exata')

    def test_g_usa_coeficientes_reais_do_transform_nao_a_constante_nominal(self):
        """A função lê dataset.transform.a/e (os coeficientes REAIS do
        arquivo aberto) — nunca a constante de módulo RESOLUCAO_GRAUS —
        para a aritmética de fração de pixel."""
        import inspect
        src = inspect.getsource(v3.localizar_pixel)
        self.assertIn('dataset.transform.a', src)
        self.assertIn('dataset.transform.e', src)
        # RESOLUCAO_GRAUS (nominal) não deve aparecer como divisor da
        # fração — só dataset.transform.a/e (via res_lon_real/res_lat_real)
        self.assertNotIn('/ RESOLUCAO_GRAUS', src)


class CompararPixelComVizinhosTestCase(unittest.TestCase):
    """Seção 2 da revisão — teste de sensibilidade: compara o pixel
    selecionado com seus vizinhos, sem nunca trocar automaticamente a
    referência oficial do projeto."""

    def test_a_retorna_pixel_referencia_e_vizinhos(self):
        dados = np.full((20, 20), 5.0, dtype='float32')
        dados[10, 10] = 42.0   # pixel "central" — resultado depende de onde o índice cai
        with _dataset_sintetico(origem_lon=-48.5, origem_lat=-7.0, dados=dados) as ds:
            resultado = v3.comparar_pixel_com_vizinhos(ds, lat=-7.525, lon=-47.995)
        self.assertIn('pixel_referencia', resultado)
        self.assertIn('vizinhos', resultado)
        self.assertEqual(len(resultado['vizinhos']), 9)   # 3x3, incluindo o centro

    def test_b_nunca_altera_a_referencia_automaticamente(self):
        """Função é só leitura/relato — não escreve em nenhum arquivo
        nem retorna uma instrução para substituir a referência."""
        import inspect
        src = inspect.getsource(v3.comparar_pixel_com_vizinhos)
        self.assertNotIn('.write(', src)
        self.assertIn('NUNCA', src.upper())

    def test_c_vizinho_fora_do_raster_e_sinalizado(self):
        dados = np.full((3, 3), 1.0, dtype='float32')
        with _dataset_sintetico(width=3, height=3, origem_lon=-48.5, origem_lat=-7.0,
                                 dados=dados) as ds:
            # canto (row=0,col=0) do raster — vizinhos N/O/NO ficam fora
            resultado = v3.comparar_pixel_com_vizinhos(ds, lat=-7.025, lon=-48.475)
        self.assertEqual(resultado['pixel_referencia']['row'], 0)
        self.assertEqual(resultado['pixel_referencia']['col'], 0)
        fora = [v for v in resultado['vizinhos'].values() if not v['dentro_do_raster']]
        self.assertGreater(len(fora), 0)


class VerificarDisponibilidadeHttpTestCase(unittest.TestCase):
    """Distingue mês ausente (404) de outras falhas — nenhum vira
    zero, e retentativa só para falha transitória, nunca para 404."""

    def test_a_disponivel_traz_metadados_de_identificacao(self):
        with patch('urllib.request.urlopen', return_value=_resposta_head_ok()):
            resultado = v3.verificar_disponibilidade_http('http://x/y.cog')
        self.assertTrue(resultado['disponivel'])
        self.assertEqual(resultado['etag'], '"abc"')

    def test_b_404_vira_mes_ausente_sem_retentativa_desnecessaria(self):
        erro = urllib.error.HTTPError('url', 404, 'Not Found', {}, None)
        with patch('urllib.request.urlopen', side_effect=erro) as mock_urlopen:
            resultado = v3.verificar_disponibilidade_http('http://x/y.cog')
        self.assertFalse(resultado['disponivel'])
        self.assertEqual(resultado['motivo'], 'mes_ausente')
        self.assertEqual(mock_urlopen.call_count, 1,
                          "404 é uma resposta válida (mês ausente), não deveria retentar")

    def test_c_falha_de_rede_transitoria_retenta_e_depois_sucede(self):
        chamadas = {'n': 0}

        def _efeito(*a, **kw):
            chamadas['n'] += 1
            if chamadas['n'] < 2:
                raise ConnectionError("falha transitória")
            return _resposta_head_ok()

        with patch('urllib.request.urlopen', side_effect=_efeito), \
             patch('time.sleep', return_value=None):
            resultado = v3.verificar_disponibilidade_http('http://x/y.cog')
        self.assertTrue(resultado['disponivel'])
        self.assertEqual(chamadas['n'], 2)

    def test_d_falha_persistente_esgota_tentativas_sem_gravar_zero(self):
        with patch('urllib.request.urlopen', side_effect=ConnectionError("fora do ar")), \
             patch('time.sleep', return_value=None):
            resultado = v3.verificar_disponibilidade_http('http://x/y.cog')
        self.assertFalse(resultado['disponivel'])
        self.assertNotEqual(resultado.get('motivo'), 'mes_ausente')


class ExtrairPixelMensalTestCase(unittest.TestCase):
    """Fim a fim, com abrir_fn injetado (MemoryFile) — nunca rede
    real, mas exercitando o código de produção real."""

    def _abrir_fn_com_valor(self, valor, origem_lon=-48.5, origem_lat=-7.0):
        dados = np.full((20, 20), v3.NODATA_SENTINELA, dtype='float32')
        dados[15, 10] = valor   # ver comentário no teste sobre lat=-7.5,lon=-48.0

        @contextmanager
        def _abrir():
            with _dataset_sintetico(origem_lon=origem_lon, origem_lat=origem_lat,
                                     dados=dados) as ds:
                yield ds
        return _abrir

    # As três checagens abaixo isolam a leitura/classificação de
    # pixel (o que estão testando) da validação de grade (já coberta
    # à parte em VerificarGradeTestCase) — por isso patcham
    # verificar_grade para sempre aprovar; a integração real das duas
    # (grade reprovada barra a leitura) é testada em
    # test_e_grade_inesperada_reprova_sem_ler_pixel, sem esse patch.

    def test_a_extracao_com_sucesso(self):
        abrir_fn = self._abrir_fn_com_valor(88.8)
        with patch.object(v3, 'verificar_disponibilidade_http',
                           return_value={'disponivel': True, 'status_http': 200}), \
             patch.object(v3, 'verificar_grade', return_value={'grade_ok': True, 'problemas': []}):
            resultado = v3.extrair_pixel_mensal(1991, 1, lat=-7.75, lon=-48.0,
                                                 abrir_fn=abrir_fn)
        self.assertEqual(resultado['status'], 'ok')
        self.assertAlmostEqual(resultado['valor_mm'], 88.8, places=1)

    def test_b_nodata_nunca_vira_zero(self):
        abrir_fn = self._abrir_fn_com_valor(v3.NODATA_SENTINELA)
        with patch.object(v3, 'verificar_disponibilidade_http',
                           return_value={'disponivel': True, 'status_http': 200}), \
             patch.object(v3, 'verificar_grade', return_value={'grade_ok': True, 'problemas': []}):
            resultado = v3.extrair_pixel_mensal(1991, 1, lat=-7.75, lon=-48.0,
                                                 abrir_fn=abrir_fn)
        self.assertEqual(resultado['status'], 'nodata_sentinela')
        self.assertIsNone(resultado['valor_mm'])

    def test_c_zero_real_preservado(self):
        abrir_fn = self._abrir_fn_com_valor(0.0)
        with patch.object(v3, 'verificar_disponibilidade_http',
                           return_value={'disponivel': True, 'status_http': 200}), \
             patch.object(v3, 'verificar_grade', return_value={'grade_ok': True, 'problemas': []}):
            resultado = v3.extrair_pixel_mensal(1991, 1, lat=-7.75, lon=-48.0,
                                                 abrir_fn=abrir_fn)
        self.assertEqual(resultado['status'], 'zero_real')
        self.assertEqual(resultado['valor_mm'], 0.0)

    def test_d_mes_ausente_nao_tenta_abrir_dataset(self):
        abrir_fn = MagicMock(side_effect=AssertionError("não deveria ser chamado"))
        with patch.object(v3, 'verificar_disponibilidade_http',
                           return_value={'disponivel': False, 'motivo': 'mes_ausente'}):
            resultado = v3.extrair_pixel_mensal(2030, 1, abrir_fn=abrir_fn)
        self.assertEqual(resultado['status'], 'mes_ausente')
        self.assertIsNone(resultado['valor_mm'])
        abrir_fn.assert_not_called()

    def test_e_grade_inesperada_reprova_sem_ler_pixel(self):
        @contextmanager
        def _abrir_grade_errada():
            transform = Affine(0.25, 0, -180.0, 0, -0.25, 60.0)
            profile = dict(driver='GTiff', height=480, width=1440, count=1,
                            dtype='float32', crs='EPSG:4326', transform=transform)
            with MemoryFile() as mem:
                with mem.open(**profile):
                    pass
                with mem.open() as ds:
                    yield ds

        with patch.object(v3, 'verificar_disponibilidade_http',
                           return_value={'disponivel': True, 'status_http': 200}):
            resultado = v3.extrair_pixel_mensal(1991, 1, abrir_fn=_abrir_grade_errada)
        self.assertEqual(resultado['status'], 'grade_inesperada')
        self.assertIsNone(resultado['valor_mm'])
        self.assertFalse(resultado['verificacao_grade']['grade_ok'])

    def test_f_arquivo_corrompido_e_classificado_como_tal_nao_como_zero(self):
        @contextmanager
        def _abrir_corrompido():
            raise rasterio.errors.RasterioIOError("TIFF truncado")
            yield  # pragma: no cover — necessário p/ ser um gerador

        with patch.object(v3, 'verificar_disponibilidade_http',
                           return_value={'disponivel': True, 'status_http': 200}):
            resultado = v3.extrair_pixel_mensal(1991, 1, abrir_fn=_abrir_corrompido)
        self.assertEqual(resultado['status'], 'arquivo_corrompido_ou_incompleto')
        self.assertIsNone(resultado['valor_mm'])
        self.assertNotEqual(resultado['valor_mm'], 0.0)

    def test_g_erro_inesperado_nao_vira_zero(self):
        @contextmanager
        def _abrir_com_erro():
            raise RuntimeError("algo inesperado")
            yield  # pragma: no cover

        with patch.object(v3, 'verificar_disponibilidade_http',
                           return_value={'disponivel': True, 'status_http': 200}):
            resultado = v3.extrair_pixel_mensal(1991, 1, abrir_fn=_abrir_com_erro)
        self.assertEqual(resultado['status'], 'erro_inesperado')
        self.assertIsNone(resultado['valor_mm'])

    def test_h_resultado_carrega_proveniencia_completa(self):
        abrir_fn = self._abrir_fn_com_valor(50.0)
        with patch.object(v3, 'verificar_disponibilidade_http',
                           return_value={'disponivel': True, 'status_http': 200,
                                          'etag': '"xyz"'}), \
             patch.object(v3, 'verificar_grade', return_value={'grade_ok': True, 'problemas': []}):
            resultado = v3.extrair_pixel_mensal(1998, 4, lat=-7.75, lon=-48.0,
                                                 abrir_fn=abrir_fn)
        for chave in ('ano', 'mes', 'url', 'versao_chirps', 'data_extracao_utc',
                      'identificacao_arquivo', 'verificacao_grade', 'pixel'):
            self.assertIn(chave, resultado)
        self.assertEqual(resultado['versao_chirps'], 'v3.0')


class NuncaModificaPipelineOperacionalTestCase(unittest.TestCase):
    """Seção 5 — 'Não alterar scripts/_chirps.py nem o pipeline
    operacional existente'."""

    def test_a_modulo_nao_importa_nem_chama_chirps_py(self):
        codigo = (ROOT / 'scripts' / '_chirps_v3.py').read_text()
        self.assertNotIn('import _chirps\n', codigo)
        self.assertNotIn('from _chirps import', codigo)

    def test_b_chirps_py_nao_foi_modificado_por_esta_tarefa(self):
        """Confirma que a versão de scripts/_chirps.py neste checkout
        ainda contém o comentário de auditoria da rodada anterior
        (Fase 2C.2, ajuste final) — sinal de que não foi tocado aqui."""
        codigo = (ROOT / 'scripts' / '_chirps.py').read_text()
        self.assertIn('Achado de auditoria', codigo)

    def test_c_nunca_baixa_o_raster_inteiro_para_disco(self):
        """Só HEAD (identificação) + /vsicurl/ (range-request via
        GDAL) — nunca um download completo do arquivo (urlretrieve,
        .read() de um response HTTP de dados binários completo)."""
        codigo = (ROOT / 'scripts' / '_chirps_v3.py').read_text()
        self.assertNotIn('urlretrieve', codigo)
        self.assertNotIn('.write(resp.read())', codigo)
        self.assertIn('/vsicurl/', codigo)


if __name__ == '__main__':
    unittest.main()
