#!/usr/bin/env python3
"""
tests/test_nmme_poc_espacial_fazendas.py — regressão do POC espacial
independente no centroide das fazendas (Fase 2C.2, item 2 da tarefa):
scripts/nmme_poc_espacial_fazendas.py. Tudo offline — baixar_fn/abrir_fn
são sempre injetados (nunca requests/xarray reais); os datasets usados
são SINTÉTICOS, nunca um subset NMME real. Todo teste que grava em
disco usa monkeypatch de ARTIFACTS_DIR para um diretório temporário —
nunca escreve em artifacts/nmme_poc_espacial_fazendas/ real.

Este módulo reaproveita nmme_poc.executar_poc_real_cfsv2/
avaliar_aprovacao_poc SEM modificação (só passa lat/lon explícitos, o
parâmetro aditivo da Fase 2C.2) — os guardrails de integridade já têm
cobertura própria em tests/test_nmme_poc_real_cfsv2.py e não são
reexercitados em detalhe aqui. O que este arquivo testa é o que é
ESPECÍFICO deste módulo: usa exatamente lat=-7.80/lon=-47.95 (nunca as
coordenadas de São Bento), nunca altera MUNICIPIOS/MUNICIPIO/POC_ORIGEM
do POC original, nunca considera a localização validada automaticamente
mesmo com poc_status=APROVADO, e mantém o dataset completamente
separado de artifacts/nmme_poc/.

Roda com:
    python -m unittest tests.test_nmme_poc_espacial_fazendas -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import nmme_poc as npoc  # noqa: E402
import nmme_poc_espacial_fazendas as espacial  # noqa: E402
from _c3s_utils import MUNICIPIOS  # noqa: E402

FLAT, FLON = espacial.FAZENDAS_LAT, espacial.FAZENDAS_LON
SAO_BENTO = MUNICIPIOS['Sao_Bento_do_Tocantins']


def _ds_fazendas(n_membros=24, valor_base=5.0, escala=3.0):
    """Dataset sintético válido (Representação B) CENTRADO no
    centroide das fazendas — nunca em São Bento — para provar que a
    coordenada realmente usada é a passada explicitamente."""
    lon_360 = FLON % 360.0
    lons = np.array([lon_360 - 1.0, lon_360, lon_360 + 1.0])
    lats = np.array([FLAT - 1.0, FLAT, FLAT + 1.0])
    l_valores = (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)
    membros = np.arange(1, n_membros + 1)
    rng = np.random.RandomState(2005 * 100 + 1)
    dados = valor_base + rng.rand(3, 3, len(l_valores), n_membros) * escala
    da_S = xr.DataArray([pd.Timestamp('2005-01-01')], dims=('S',),
                          attrs={'standard_name': 'forecast_reference_time'})
    da_L = xr.DataArray(np.array(l_valores), dims=('L',),
                          attrs={'units': 'months', 'standard_name': 'forecast_period'})
    prec = xr.DataArray(dados, dims=('X', 'Y', 'L', 'M'),
                          coords={'X': lons, 'Y': lats, 'L': da_L, 'M': membros, 'S': da_S.isel(S=0)})
    prec.attrs['units'] = 'mm/day'
    return xr.Dataset({'prec': prec})


def _baixar_ok(url, destino):
    return ('/tmp/fake-espacial-nmme.nc', False)


def _baixar_falha(url, destino):
    raise RuntimeError('rede indisponível simulada')


def _executar(abrir_fn=None, baixar_fn=None):
    return espacial.executar_poc_espacial_fazendas(
        baixar_fn=baixar_fn or _baixar_ok, abrir_fn=abrir_fn or (lambda c: _ds_fazendas()))


class CoordenadasTestCase(unittest.TestCase):
    """Usa exatamente lat=-7.80/lon=-47.95 — mesmo valor de
    scripts/_chirps.py::FAZENDAS_LAT/FAZENDAS_LON."""

    def test_a_coordenadas_hardcoded_no_valor_certo(self):
        self.assertEqual(espacial.FAZENDAS_LAT, -7.80)
        self.assertEqual(espacial.FAZENDAS_LON, -47.95)

    def test_b_coordenadas_batem_com_chirps_e_openmeteo(self):
        import _chirps
        self.assertEqual(espacial.FAZENDAS_LAT, _chirps.FAZENDAS_LAT)
        self.assertEqual(espacial.FAZENDAS_LON, _chirps.FAZENDAS_LON)

    def test_c_execucao_real_usa_as_coordenadas_das_fazendas_nao_sao_bento(self):
        resultado, _ = _executar()
        raw = resultado['raw_df']
        self.assertTrue((raw['requested_lat'] == FLAT).all())
        self.assertTrue((raw['requested_lon'] == FLON).all())
        self.assertFalse((raw['requested_lat'] == SAO_BENTO['lat']).any())

    def test_d_grade_selecionada_proxima_da_coordenada_pedida(self):
        resultado, _ = _executar()
        raw = resultado['raw_df']
        self.assertTrue((raw['selected_lat'] - FLAT).abs().max() < 1.0)


class NaoAlteraPocOriginalTestCase(unittest.TestCase):
    """Nunca altera as coordenadas do POC já validado (São Bento) —
    nem MUNICIPIOS, nem nmme_poc.MUNICIPIO/POC_ORIGEM."""

    def test_a_municipios_sao_bento_intacto(self):
        self.assertEqual(SAO_BENTO['lat'], -6.0203)
        self.assertEqual(SAO_BENTO['lon'], -47.9022)

    def test_b_nmme_poc_municipio_e_origem_intactos(self):
        self.assertEqual(npoc.MUNICIPIO, 'Sao_Bento_do_Tocantins')
        self.assertEqual(npoc.POC_ORIGEM, (2005, 1))

    def test_c_executar_poc_espacial_nunca_modifica_municipios_dict(self):
        antes = dict(MUNICIPIOS['Sao_Bento_do_Tocantins'])
        _executar()
        depois = dict(MUNICIPIOS['Sao_Bento_do_Tocantins'])
        self.assertEqual(antes, depois)

    def test_d_modulo_nunca_atribui_a_municipios(self):
        """Só LÊ MUNICIPIOS (via MUNICIPIOS[npoc.MUNICIPIO]) — nunca
        atribui a uma chave/campo dele. Checa código executável, não
        docstrings/comentários (que legitimamente mencionam
        `MUNICIPIOS['Sao_Bento_do_Tocantins']` como prosa)."""
        import ast
        arvore = ast.parse(Path(espacial.__file__).read_text())
        atribuicoes_a_municipios = [
            n for n in ast.walk(arvore) if isinstance(n, ast.Assign)
            for alvo in n.targets
            if isinstance(alvo, ast.Subscript) and isinstance(alvo.value, ast.Name)
            and alvo.value.id == 'MUNICIPIOS'
        ]
        self.assertEqual(atribuicoes_a_municipios, [])


class ControlesReaproveitadosTestCase(unittest.TestCase):
    """Mesmos controles de seleção temporal, membros, horizontes,
    unidades e grade do POC original — reaproveitados sem modificação
    via nmme_poc.executar_poc_real_cfsv2/avaliar_aprovacao_poc."""

    def test_a_leads_h1_a_h6(self):
        resultado, _ = _executar()
        temporal = resultado['temporal_audit_df']
        self.assertEqual(set(temporal['H_lead']), {1, 2, 3, 4, 5, 6})

    def test_b_24_membros_por_lead(self):
        resultado, _ = _executar()
        raw = resultado['raw_df']
        contagem = raw.groupby('lead').size()
        self.assertTrue((contagem == 24).all())

    def test_c_origem_default_e_a_mesma_do_poc_de_sao_bento(self):
        resultado, _ = _executar()
        self.assertEqual(resultado['init_date'], npoc._origem_str(*npoc.POC_ORIGEM))

    def test_d_aprovacao_usa_os_mesmos_criterios_do_poc_original(self):
        resultado, aprovacao = _executar()
        self.assertEqual(aprovacao['poc_status'], 'APROVADO')
        self.assertTrue(aprovacao['checklist']['h1_a_h6_presentes'])
        self.assertTrue(aprovacao['checklist']['member_count_per_lead_ok'])
        self.assertTrue(aprovacao['checklist']['grade_confirmada'])
        self.assertTrue(aprovacao['checklist']['nenhum_skill_calculado'])

    def test_e_falha_de_acesso_e_reprovada_explicitamente(self):
        resultado, aprovacao = _executar(baixar_fn=_baixar_falha)
        self.assertNotEqual(aprovacao['poc_status'], 'APROVADO')

    def test_f_reaproveita_avaliar_aprovacao_poc_sem_redefinir_checklist(self):
        import inspect
        src = inspect.getsource(espacial.executar_poc_espacial_fazendas)
        self.assertIn('npoc.executar_poc_real_cfsv2', src)
        self.assertIn('npoc.avaliar_aprovacao_poc', src)


class LocalizacaoNuncaValidadaAutomaticamenteTestCase(unittest.TestCase):
    """Seção 2 da tarefa — 'não considerar a nova localização validada
    antes de uma execução real aprovada' — localizacao_validada é
    SEMPRE False, mesmo com poc_status=APROVADO."""

    def test_a_localizacao_validada_false_mesmo_aprovado(self):
        resultado, aprovacao = _executar()
        self.assertEqual(resultado['poc_status'], 'APROVADO')
        metadata = espacial.montar_metadata_espacial(resultado, aprovacao)
        self.assertFalse(metadata['localizacao_validada'])

    def test_b_localizacao_validada_false_quando_reprovado_tambem(self):
        resultado, aprovacao = _executar(baixar_fn=_baixar_falha)
        metadata = espacial.montar_metadata_espacial(resultado, aprovacao)
        self.assertFalse(metadata['localizacao_validada'])

    def test_c_relatorio_menciona_explicitamente_a_nao_validacao(self):
        resultado, aprovacao = _executar()
        metadata = espacial.montar_metadata_espacial(resultado, aprovacao)
        relatorio = espacial.gerar_relatorio_espacial_markdown(resultado, metadata)
        self.assertIn('localizacao_validada=False', relatorio)

    def test_d_modulo_nunca_importa_catalogo_para_promocao(self):
        codigo = Path(espacial.__file__).read_text()
        self.assertNotIn('import nmme_catalogo', codigo)


class SeparacaoDeDatasetsTestCase(unittest.TestCase):
    """Os conjuntos de dados das duas localidades ficam COMPLETAMENTE
    separados e identificados."""

    def test_a_artifacts_dir_e_exclusivo_e_diferente_de_sao_bento(self):
        self.assertEqual(espacial.ARTIFACTS_DIR.name, 'nmme_poc_espacial_fazendas')
        self.assertNotEqual(espacial.ARTIFACTS_DIR, npoc.ARTIFACTS_DIR)

    def test_b_escrever_saidas_grava_so_no_diretorio_proprio(self):
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / 'nmme_poc_espacial_fazendas'
            original = espacial.ARTIFACTS_DIR
            espacial.ARTIFACTS_DIR = destino
            try:
                resultado, aprovacao = _executar()
                espacial.escrever_saidas_espacial(resultado, aprovacao)
                for nome in ('poc_espacial_fazendas_raw.csv',
                              'poc_espacial_fazendas_temporal_audit.csv',
                              'poc_espacial_fazendas_access_audit.csv',
                              'metadata.json', 'RELATORIO.md'):
                    self.assertTrue((destino / nome).exists(), nome)
                # Nada escrito no diretório de São Bento durante este teste.
                self.assertFalse((original.parent / 'nmme_poc' / 'poc_espacial_fazendas_raw.csv').exists())
            finally:
                espacial.ARTIFACTS_DIR = original

    def test_c_metadata_declara_a_separacao_explicitamente(self):
        resultado, aprovacao = _executar()
        metadata = espacial.montar_metadata_espacial(resultado, aprovacao)
        self.assertIn('nmme_poc_espacial_fazendas', metadata['dataset_separado_de_sao_bento'])
        self.assertNotIn('nmme_poc/', metadata['dataset_separado_de_sao_bento'].split('(')[0])

    def test_d_localizacao_id_identifica_o_conjunto(self):
        resultado, aprovacao = _executar()
        metadata = espacial.montar_metadata_espacial(resultado, aprovacao)
        self.assertEqual(metadata['localizacao_id'], 'Fazendas_Sinobras_Centroide')


class DistanciaEntrePontosTestCase(unittest.TestCase):
    """A distância entre os dois pontos é registrada (~198 km,
    documentado em docs/nmme-fase2c2-piloto-cobertura-observacional.md)."""

    def test_a_distancia_proxima_de_198km(self):
        resultado, aprovacao = _executar()
        metadata = espacial.montar_metadata_espacial(resultado, aprovacao)
        self.assertAlmostEqual(metadata['distancia_ate_poc_sao_bento_km'], 198.0, delta=2.0)

    def test_b_poc_sao_bento_coordenadas_alteradas_e_sempre_false(self):
        resultado, aprovacao = _executar()
        metadata = espacial.montar_metadata_espacial(resultado, aprovacao)
        self.assertFalse(metadata['poc_sao_bento_coordenadas_alteradas'])


class ZeroSkillESemDashboardTestCase(unittest.TestCase):
    def test_a_nunca_calcula_skill(self):
        resultado, aprovacao = _executar()
        metadata = espacial.montar_metadata_espacial(resultado, aprovacao)
        self.assertTrue(metadata['nenhuma_skill_calculada'])

    def test_b_nunca_modifica_dashboard(self):
        resultado, aprovacao = _executar()
        metadata = espacial.montar_metadata_espacial(resultado, aprovacao)
        self.assertTrue(metadata['nenhum_dashboard_alterado'])

    def test_c_nunca_promove_rota_ou_representacao(self):
        resultado, aprovacao = _executar()
        metadata = espacial.montar_metadata_espacial(resultado, aprovacao)
        self.assertTrue(metadata['nenhuma_rota_ou_representacao_promovida'])

    def test_d_modulo_nunca_importa_dashboard_ou_skill(self):
        codigo = Path(espacial.__file__).read_text()
        self.assertNotIn('update_dashboard', codigo)
        self.assertNotIn('calcular_skill', codigo)


class CliDryRunTestCase(unittest.TestCase):
    """--dry-run-plan nunca acessa a rede — só imprime o plano."""

    def test_a_imprimir_plano_nao_lanca(self):
        espacial.imprimir_plano()   # não deve levantar exceção nem acessar rede


if __name__ == '__main__':
    unittest.main()
