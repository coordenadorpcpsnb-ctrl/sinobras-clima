#!/usr/bin/env python3
"""
tests/test_nmme_poc_real_cfsv2.py — regressão do primeiro POC REAL
(Fase 2C.1b): scripts/nmme_poc.py::executar_poc_real_cfsv2/
avaliar_aprovacao_poc. Tudo offline — baixar_fn/abrir_fn são sempre
injetados (nunca requests/xarray reais); os datasets usados são
SINTÉTICOS, nunca um subset NMME real (a rede real nunca é acessada
nesta tarefa — Seção 17).

Roda com:
    python -m unittest tests.test_nmme_poc_real_cfsv2 -v
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import nmme_catalogo as ncat  # noqa: E402
import nmme_download as ndl  # noqa: E402
import nmme_poc as npoc  # noqa: E402
from _c3s_utils import MUNICIPIOS  # noqa: E402

CFSV2 = ncat.sistema_por_nome('NOAA_NCEP', 'CFSv2')
SAO_BENTO = MUNICIPIOS['Sao_Bento_do_Tocantins']


def _ds_representacao_b(n_membros=24, valor_base=0.00003, escala=0.00004, unidade='kg m-2 s-1',
                          var='prec', com_target_correto=False):
    """Dataset sintético no formato da Representação B (grade regular,
    lon 0-360, M=24 nominal)."""
    lon_sb_360 = SAO_BENTO['lon'] % 360.0
    lons = np.array([lon_sb_360 - 1.0, lon_sb_360, lon_sb_360 + 1.0])
    lats = np.array([SAO_BENTO['lat'] - 1.0, SAO_BENTO['lat'], SAO_BENTO['lat'] + 1.0])
    leads_L = np.array([0.5, 1.5, 2.5, 3.5, 4.5, 5.5])
    membros = np.arange(1, n_membros + 1)
    rng = np.random.RandomState(11)
    dados = valor_base + rng.rand(3, 3, 6, n_membros) * escala
    da = xr.DataArray(dados, dims=('X', 'Y', 'L', 'M'),
                       coords={'X': lons, 'Y': lats, 'L': leads_L, 'M': membros,
                               'S': pd.Timestamp('2005-01-01')},
                       attrs={'units': unidade})
    ds = xr.Dataset({var: da})
    if com_target_correto:
        ds = ds.assign(target=(('L',), np.array(
            ['2005-01', '2005-02', '2005-03', '2005-04', '2005-05', '2005-06'])))
    return ds


def _ds_representacao_a(n_membros=28, valor_base=0.00003, escala=0.00004, com_target_correto=False):
    """Dataset sintético no formato da Representação A (grade
    Gaussiana aproximada, M até 28)."""
    lon_sb_360 = SAO_BENTO['lon'] % 360.0
    lons = np.array([lon_sb_360 - 0.9375, lon_sb_360, lon_sb_360 + 0.9375])
    lats = np.array([SAO_BENTO['lat'] - 1.0, SAO_BENTO['lat'], SAO_BENTO['lat'] + 1.0])
    leads_L = np.array([0.5, 1.5, 2.5, 3.5, 4.5, 5.5])
    membros = np.arange(1, n_membros + 1)
    rng = np.random.RandomState(13)
    dados = valor_base + rng.rand(3, 3, 6, n_membros) * escala
    da = xr.DataArray(dados, dims=('X', 'Y', 'L', 'M'),
                       coords={'X': lons, 'Y': lats, 'L': leads_L, 'M': membros,
                               'S': pd.Timestamp('2005-01-01')},
                       attrs={'units': 'kg m-2 s-1'})
    ds = xr.Dataset({'PRATE': da})
    if com_target_correto:
        ds = ds.assign(target=(('L',), np.array(
            ['2005-01', '2005-02', '2005-03', '2005-04', '2005-05', '2005-06'])))
    return ds


def _baixar_ok(url, destino):
    return ('/tmp/fake-nmme-poc-test.nc', False)


def _executar(abrir_fn, baixar_fn=None):
    return npoc.executar_poc_real_cfsv2(baixar_fn=baixar_fn or _baixar_ok, abrir_fn=abrir_fn)


class SomenteCFSv2TestCase(unittest.TestCase):
    """A — execução real usa somente CFSv2."""

    def test_a_model_e_cfsv2(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b())
        self.assertEqual(r['model'], 'NOAA_NCEP/CFSv2')

    def test_a_sistema_default_e_cfsv2_do_catalogo_real(self):
        import inspect
        src = inspect.getsource(npoc.executar_poc_real_cfsv2)
        self.assertIn("sistema_por_nome('NOAA_NCEP', 'CFSv2')", src)


class BackendPriorityTestCase(unittest.TestCase):
    """B — prioridade de backend/representação: CCSR (se pronto) >
    Representação B (NMME_HARMONIZED_MONTHLY) > Representação A
    (RAW_NATIVE_ENSEMBLE)."""

    def test_b_ordem_prioriza_representacao_b_sobre_a(self):
        ordem = ndl.ordem_tentativa_member_level(CFSV2)
        self.assertEqual(ordem[0].dataset_representation, ncat.REPR_NMME_HARMONIZED_MONTHLY)
        self.assertEqual(ordem[1].dataset_representation, ncat.REPR_RAW_NATIVE_ENSEMBLE)

    def test_b_execucao_tenta_representacao_b_primeiro(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b())
        self.assertEqual(r['backend_requested'], ncat.SOURCE_BACKEND_IRIDL_LEGACY)
        self.assertEqual(r['dataset_representation_requested'], ncat.REPR_NMME_HARMONIZED_MONTHLY)
        self.assertEqual(r['dataset_representation_used'], ncat.REPR_NMME_HARMONIZED_MONTHLY)

    def test_b_ccsr_nunca_tentado_por_download_real_enquanto_discovery_required(self):
        chamadas = []

        def baixar_registra(url, destino):
            chamadas.append(url)
            return ('/tmp/fake.nc', False)

        _executar(abrir_fn=lambda c: _ds_representacao_b(), baixar_fn=baixar_registra)
        self.assertTrue(all('ccsr' not in u.lower() for u in chamadas))


class FallbackExplicitoTestCase(unittest.TestCase):
    """C — fallback explícito: se a Representação B falhar por acesso,
    tenta a Representação A e registra a mudança — nunca silencioso."""

    def test_c_falha_em_b_cai_para_a_com_registro(self):
        def baixar_falha_b(url, destino):
            if 'HINDCAST/.MONTHLY' in url:
                raise RuntimeError('simulado: endpoint indisponível para Representação B')
            return ('/tmp/fake.nc', False)

        r = _executar(abrir_fn=lambda c: _ds_representacao_a(), baixar_fn=baixar_falha_b)
        self.assertEqual(r['dataset_representation_used'], ncat.REPR_RAW_NATIVE_ENSEMBLE)
        self.assertTrue(r['representation_changed'])
        self.assertTrue(r['backend_fallback_ocorreu'])
        self.assertIn('NMME_HARMONIZED_MONTHLY', r['fallback_reason'])
        self.assertIn('RAW_NATIVE_ENSEMBLE', r['fallback_reason'])

    def test_c_access_audit_mostra_a_tentativa_falha_e_a_bem_sucedida(self):
        def baixar_falha_b(url, destino):
            if 'HINDCAST/.MONTHLY' in url:
                raise RuntimeError('simulado')
            return ('/tmp/fake.nc', False)

        r = _executar(abrir_fn=lambda c: _ds_representacao_a(), baixar_fn=baixar_falha_b)
        audit = r['access_audit_df']
        self.assertEqual(len(audit), 2)
        self.assertEqual(audit.iloc[0]['status'], 'SERVICE_UNAVAILABLE')
        self.assertEqual(audit.iloc[1]['status'], 'OK')

    def test_c_todas_as_rotas_falham_vira_service_unavailable_sem_scraping(self):
        def baixar_falha_tudo(url, destino):
            raise RuntimeError('serviço fora do ar (simulado)')

        r = _executar(abrir_fn=lambda c: _ds_representacao_a(), baixar_fn=baixar_falha_tudo)
        self.assertEqual(r['poc_status'], 'REPROVADO_ACESSO')
        self.assertTrue((r['access_audit_df']['status'] == 'SERVICE_UNAVAILABLE').all())
        aprovacao = npoc.avaliar_aprovacao_poc(r)
        self.assertEqual(aprovacao['poc_status'], 'REPROVADO_ACESSO')


class RepresentacaoRegistradaTestCase(unittest.TestCase):
    """D — representação usada é registrada explicitamente no
    resultado e na metadata."""

    def test_d_resultado_registra_representacao_usada(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b())
        self.assertIn('dataset_representation_used', r)
        self.assertEqual(r['dataset_representation_used'], ncat.REPR_NMME_HARMONIZED_MONTHLY)

    def test_d_metadata_reflete_representacao_do_resultado_real(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_a())
        # força representação A explicitamente via backend override no teste C;
        # aqui confirmamos que montar_metadata propaga o que veio em r.
        meta = npoc.montar_metadata(resultado_poc=r)
        self.assertEqual(meta['dataset_representation'], r['dataset_representation_used'])


class MemberCountTestCase(unittest.TestCase):
    """E — nº de membros observado é distinto do tamanho do eixo
    declarado; nunca inferido como igual."""

    def test_e_representacao_b_membro_esperado_24(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b(n_membros=24))
        self.assertEqual(r['member_axis_size'], 24)
        self.assertEqual(r['member_count_non_missing'], 24)

    def test_e_representacao_a_membro_ate_28(self):
        def baixar_falha_b(url, destino):
            if 'HINDCAST/.MONTHLY' in url:
                raise RuntimeError('simulado')
            return ('/tmp/fake.nc', False)

        r = _executar(abrir_fn=lambda c: _ds_representacao_a(n_membros=28), baixar_fn=baixar_falha_b)
        self.assertEqual(r['member_axis_size'], 28)
        self.assertEqual(r['member_count_non_missing'], 28)

    def test_e_membros_missing_nao_viram_linha_raw(self):
        ds = _ds_representacao_b(n_membros=24)
        # marca 3 membros como missing (NaN) no primeiro lead
        ds['prec'].values[:, :, 0, :3] = np.nan
        r = _executar(abrir_fn=lambda c: ds)
        linhas_lead1 = r['raw_df'][r['raw_df']['lead'] == 1]
        self.assertEqual(len(linhas_lead1), 21)   # 24 - 3 missing
        self.assertEqual(r['member_count_non_missing_por_lead'][0], 21)

    def test_e_member_axis_size_nunca_confundido_com_non_missing(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b(n_membros=24))
        # campos DISTINTOS por design (chaves separadas no resultado),
        # mesmo quando o valor numérico observado coincide.
        self.assertIn('member_axis_size', r)
        self.assertIn('member_count_non_missing', r)
        # com 3 membros marcados missing no lead 1, os dois valores
        # divergem de verdade — prova que não são o mesmo cálculo.
        ds = _ds_representacao_b(n_membros=24)
        ds['prec'].values[:, :, 0, :3] = np.nan
        r2 = _executar(abrir_fn=lambda c: ds)
        self.assertEqual(r2['member_axis_size'], 24)
        self.assertEqual(r2['member_count_non_missing'], 21)
        self.assertNotEqual(r2['member_axis_size'], r2['member_count_non_missing'])


class H1aH6TestCase(unittest.TestCase):
    """F — H1-H6 presentes e sem duplicata."""

    def test_f_temporal_audit_tem_h1_a_h6(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b())
        self.assertEqual(set(r['temporal_audit_df']['H_lead']), {1, 2, 3, 4, 5, 6})

    def test_f_raw_tem_os_6_leads(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b())
        self.assertEqual(set(r['raw_df']['lead']), {1, 2, 3, 4, 5, 6})

    def test_f_lead_values_requested_e_1_a_6(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b())
        self.assertEqual(r['lead_values_requested'], [1, 2, 3, 4, 5, 6])


class LeadLTestCase(unittest.TestCase):
    """G — L observado é 0.5-5.5 (H1-H6), nunca 1-6 direto."""

    def test_g_source_l_e_0_5_a_5_5(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b())
        self.assertEqual(sorted(r['source_lead_values_observed']), [0.5, 1.5, 2.5, 3.5, 4.5, 5.5])

    def test_g_temporal_audit_source_l_bate_com_h_lead_menos_meio(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b())
        for _, row in r['temporal_audit_df'].iterrows():
            self.assertEqual(row['source_L'], row['H_lead'] - 0.5)


class UnidadeTestCase(unittest.TestCase):
    """H — unidade lida do arquivo real, nunca assumida."""

    def test_h_units_observed_kg_m2_s1(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b(unidade='kg m-2 s-1'))
        self.assertEqual(r['units_observed'], 'kg m-2 s-1')

    def test_h_units_observed_mm_day(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b(unidade='mm/day', valor_base=2.0, escala=3.0))
        self.assertEqual(r['units_observed'], 'mm/day')

    def test_h_unidade_desconhecida_reprova_acesso(self):
        """A tentativa na Representação B (primeira da ordem) é quem
        acusa a unidade não reconhecida — a tentativa seguinte
        (Representação A) falha por outro motivo (variável PRATE
        ausente no dataset sintético desta unidade, já que o mock
        devolve o mesmo dataset independente da rota), mas o
        poc_status final continua REPROVADO_ACESSO de qualquer forma."""
        r = _executar(abrir_fn=lambda c: _ds_representacao_b(unidade='unidade-inexistente'))
        self.assertEqual(r['poc_status'], 'REPROVADO_ACESSO')
        self.assertIn('unidade', r['access_audit_df'].iloc[0]['motivo'].lower())


class ConversaoTestCase(unittest.TestCase):
    """I — conversão de unidade aplicada corretamente e registrada."""

    def test_i_kg_m2_s1_convertido_e_positivo(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b(unidade='kg m-2 s-1'))
        self.assertTrue((r['raw_df']['forecast_prec_mm'] > 0).all())
        self.assertTrue(r['raw_df']['conversion_applied'].str.contains('kg m-2 s-1').all())

    def test_i_mm_day_convertido_multiplicando_dias_do_mes(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b(unidade='mm/day', valor_base=2.0, escala=1.0))
        linha_jan = r['raw_df'][r['raw_df']['target_month'] == '2005-01'].iloc[0]
        self.assertIn('31', linha_jan['conversion_applied'])   # janeiro tem 31 dias

    def test_i_units_original_sempre_registrado(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b())
        self.assertTrue(r['raw_df']['units_original'].notna().all())


class GradeTestCase(unittest.TestCase):
    """J — grade (lat/lon selecionados, distância, forma observada)
    registrada."""

    def test_j_selected_lat_lon_presentes(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b())
        self.assertIn('selected_lat', r)
        self.assertIn('selected_lon', r)
        self.assertIsInstance(r['grid_distance_km'], float)

    def test_j_grid_distance_pequena_para_grade_fina(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b())
        self.assertLess(r['grid_distance_km'], 200.0)

    def test_j_raw_df_tem_requested_e_selected(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b())
        for col in ('requested_lat', 'requested_lon', 'selected_lat', 'selected_lon', 'grid_distance_km'):
            self.assertIn(col, r['raw_df'].columns)


class TemporalAuditTestCase(unittest.TestCase):
    """K — nmme_poc_temporal_audit.csv com as colunas exatas pedidas."""

    def test_k_colunas_exatas(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b())
        colunas_esperadas = {'centre', 'model_name', 'init_date', 'H_lead', 'source_L',
                              'target_month', 'mapping_status', 'evidence', 'notes'}
        self.assertEqual(colunas_esperadas, set(r['temporal_audit_df'].columns))

    def test_k_uma_linha_por_lead(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b())
        self.assertEqual(len(r['temporal_audit_df']), 6)

    def test_k_mapping_status_unconfirmed_sem_evidencia_objetiva(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b(com_target_correto=False))
        self.assertTrue((r['temporal_audit_df']['mapping_status'] == 'UNCONFIRMED').all())
        self.assertTrue(r['temporal_audit_df']['evidence'].str.len().gt(0).all())

    def test_k_mapping_status_ok_com_evidencia_objetiva(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b(com_target_correto=True))
        self.assertTrue((r['temporal_audit_df']['mapping_status'] == 'OK').all())


class TemporalMappingReprovaTestCase(unittest.TestCase):
    """L — POC reprova se o mapeamento temporal não estiver
    confirmado, mesmo com download/parsing bem-sucedidos."""

    def test_l_download_ok_mas_mapping_unconfirmed_reprova(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b(com_target_correto=False))
        self.assertEqual(r['poc_status'], 'PROCESSADO')   # acesso/parsing OK
        aprovacao = npoc.avaliar_aprovacao_poc(r)
        self.assertNotEqual(aprovacao['poc_status'], 'APROVADO')
        self.assertFalse(aprovacao['checklist']['temporal_mapping_confirmado'])

    def test_l_mapping_ok_em_todos_os_leads_aprova(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b(com_target_correto=True))
        aprovacao = npoc.avaliar_aprovacao_poc(r)
        self.assertEqual(aprovacao['poc_status'], 'APROVADO')

    def test_l_um_lead_mismatch_reprova_mesmo_com_outros_ok(self):
        ds = _ds_representacao_b(com_target_correto=True)
        # corrompe o target de um lead só, criando um MISMATCH isolado
        alvo = ds['target'].values.copy()
        alvo[2] = '1999-12'
        ds = ds.assign(target=(('L',), alvo))
        r = _executar(abrir_fn=lambda c: ds)
        self.assertIn('MISMATCH', set(r['temporal_audit_df']['mapping_status']))
        aprovacao = npoc.avaliar_aprovacao_poc(r)
        self.assertNotEqual(aprovacao['poc_status'], 'APROVADO')


class RawCountTestCase(unittest.TestCase):
    """M — nº de linhas RAW computado a partir do nº real de membros
    observado, nunca hardcoded (144/168 etc.)."""

    def test_m_raw_count_bate_com_membros_reais_x_leads(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b(n_membros=24))
        self.assertEqual(r['n_raw_expected'], 24 * 6)
        self.assertEqual(r['n_raw'], 144)
        self.assertTrue(r['raw_completo'])

    def test_m_raw_count_com_28_membros_nao_e_144(self):
        def baixar_falha_b(url, destino):
            if 'HINDCAST/.MONTHLY' in url:
                raise RuntimeError('simulado')
            return ('/tmp/fake.nc', False)

        r = _executar(abrir_fn=lambda c: _ds_representacao_a(n_membros=28), baixar_fn=baixar_falha_b)
        self.assertEqual(r['n_raw_expected'], 28 * 6)
        self.assertEqual(r['n_raw'], 168)
        self.assertNotEqual(r['n_raw_expected'], 144)

    def test_m_raw_count_reflete_membros_missing_por_lead(self):
        ds = _ds_representacao_b(n_membros=24)
        ds['prec'].values[:, :, 0, :3] = np.nan   # 3 membros missing só no lead 1
        r = _executar(abrir_fn=lambda c: ds)
        # 21 no lead 1 + 24*5 nos demais = 141, nunca 144 fixo
        self.assertEqual(r['n_raw_expected'], 21 + 24 * 5)
        self.assertEqual(r['n_raw'], r['n_raw_expected'])


class ZeroSkillTestCase(unittest.TestCase):
    """N — nenhum skill calculado em nenhum ponto do pipeline real."""

    def test_n_executar_poc_real_nao_calcula_skill(self):
        """Termos de CÁLCULO de skill nunca aparecem no código — 'chirps'
        fica de fora desta checagem porque o próprio docstring da função
        MENCIONA explicitamente 'nunca usa CHIRPS' (prosa esperada, não
        uso real); a ausência de uso real é coberta por
        test_n_resultado_nao_tem_colunas_de_skill e pela própria
        inexistência de qualquer import/chamada a c3s_observado_chirps
        neste módulo (ver ProducaoIntocadaTestCase em outros arquivos)."""
        import inspect
        src = inspect.getsource(npoc.executar_poc_real_cfsv2)
        for proibido in ('rmse', 'msess', 'brier', 'rpss', 'bootstrap'):
            self.assertNotIn(proibido, src.lower())
        self.assertNotIn('import c3s_observado_chirps', src)
        self.assertNotIn('chirps.', src.lower())

    def test_n_avaliar_aprovacao_nao_calcula_skill(self):
        import inspect
        src = inspect.getsource(npoc.avaliar_aprovacao_poc)
        for proibido in ('rmse', 'msess', 'brier', 'rpss', 'chirps', 'bootstrap'):
            self.assertNotIn(proibido, src.lower())

    def test_n_resultado_nao_tem_colunas_de_skill(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b())
        proibidas = {'rmse', 'msess', 'brier', 'rpss', 'skill'}
        self.assertFalse(proibidas & set(c.lower() for c in r['raw_df'].columns))


class NetCDFNaoPublicadoTestCase(unittest.TestCase):
    """O — nenhum NetCDF/GRIB bruto é publicado como artifact final."""

    def test_o_artifact_filenames_nunca_tem_nc_ou_grib(self):
        for nome in npoc.ARTIFACT_FILENAMES:
            self.assertFalse(nome.endswith('.nc'))
            self.assertFalse(nome.endswith('.grib'))
            self.assertFalse(nome.endswith('.grb'))

    def test_o_access_audit_esta_na_lista_de_artifacts(self):
        self.assertIn('nmme_poc_access_audit.csv', npoc.ARTIFACT_FILENAMES)

    def test_o_cache_do_dataset_fica_fora_do_diretorio_de_artifacts(self):
        cache_path = ndl.caminho_cache(CFSV2, 2005, 1)
        self.assertNotIn(str(npoc.ARTIFACTS_DIR), str(cache_path))
        self.assertTrue(str(cache_path).endswith('.nc'))

    def test_o_escrever_saidas_gera_access_audit_csv(self):
        """O access_audit.csv pode legitimamente CITAR uma URL que
        termina em data.nc (é o request real, auditável) — o que Seção
        12 proíbe é PUBLICAR o arquivo NetCDF em si como artifact, não
        mencionar sua URL em texto."""
        import tempfile
        from unittest import mock
        r = _executar(abrir_fn=lambda c: _ds_representacao_b())
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(npoc, 'ARTIFACTS_DIR', Path(tmp)):
                npoc.escrever_saidas(resultado_poc=r)
            arquivos_gerados = {p.name for p in Path(tmp).iterdir()}
            self.assertIn('nmme_poc_access_audit.csv', arquivos_gerados)
            self.assertFalse(any(nome.endswith('.nc') for nome in arquivos_gerados))


if __name__ == '__main__':
    unittest.main()
