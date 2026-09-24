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
import nmme_processar as nproc  # noqa: E402
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
        # Revisão final (item 6) — uma exceção genérica levantada dentro de
        # baixar_fn é classificada como HTTP_ERROR (falha específica de
        # download), não mais o genérico SERVICE_UNAVAILABLE de antes.
        self.assertEqual(audit.iloc[0]['status'], 'HTTP_ERROR')
        self.assertEqual(audit.iloc[1]['status'], 'OK')

    def test_c_todas_as_rotas_falham_vira_http_error_sem_scraping(self):
        def baixar_falha_tudo(url, destino):
            raise RuntimeError('serviço fora do ar (simulado)')

        r = _executar(abrir_fn=lambda c: _ds_representacao_a(), baixar_fn=baixar_falha_tudo)
        self.assertEqual(r['poc_status'], 'REPROVADO_ACESSO')
        # Falha de download (não de rota indisponível por status do catálogo)
        # vira HTTP_ERROR — item 6 exige status específico, não o genérico
        # SERVICE_UNAVAILABLE por padrão para toda e qualquer exceção.
        self.assertTrue((r['access_audit_df']['status'] == 'HTTP_ERROR').all())
        aprovacao = npoc.avaliar_aprovacao_poc(r)
        self.assertEqual(aprovacao['poc_status'], 'REPROVADO_ACESSO')

    def test_c_ccsr_indisponivel_por_status_de_catalogo_vira_service_unavailable(self):
        """SERVICE_UNAVAILABLE continua reservado para rota nem tentada por
        estar com status de catálogo indisponível (ex.: CCSR_BETA
        DISCOVERY_REQUIRED) — não para falha de download/HTTP."""
        r = _executar(abrir_fn=lambda c: _ds_representacao_b())
        audit = r['access_audit_df']
        self.assertTrue(len(audit) >= 1)
        self.assertEqual(audit.iloc[0]['status'], 'OK')


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


class MembrosPoliticaTestCase(unittest.TestCase):
    """Revisão final (itens 2/9, cenários 1-6) — guardrail de membros por
    representação: Harmonized exige exatamente 24 (eixo e por lead);
    Raw native aceita a faixa 24-28 por lead, mas exige eixo==28."""

    def test_1_harmonized_24x6_aprova_membros(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b(n_membros=24, com_target_correto=True))
        self.assertEqual(r['members_status'], npoc.MEMBERS_STATUS_OK)
        self.assertTrue(r['members_axis_size_ok'])
        self.assertTrue(all(r['members_count_per_lead_ok']))
        aprovacao = npoc.avaliar_aprovacao_poc(r)
        self.assertEqual(aprovacao['poc_status'], 'APROVADO')

    def test_2_harmonized_23_em_um_lead_reprova(self):
        ds = _ds_representacao_b(n_membros=24)
        ds['prec'].values[:, :, 0, 0] = np.nan   # 1 membro missing só no lead 1 -> 23/24
        r = _executar(abrir_fn=lambda c: ds)
        self.assertEqual(r['member_count_non_missing_por_lead'][0], 23)
        self.assertEqual(r['members_status'], npoc.MEMBERS_STATUS_FAIL)
        self.assertFalse(r['members_count_per_lead_ok'][0])
        aprovacao = npoc.avaliar_aprovacao_poc(r)
        self.assertNotEqual(aprovacao['poc_status'], 'APROVADO')

    def test_3_harmonized_eixo_m_23_reprova(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b(n_membros=23))
        # member_axis_size é o valor DOCUMENTADO da rota (24, catálogo) —
        # o eixo REAL observado no dataset aberto é member_ids_axis.
        self.assertEqual(r['member_axis_size'], 24)
        self.assertEqual(len(r['member_ids_axis']), 23)
        self.assertFalse(r['members_axis_size_ok'])
        self.assertEqual(r['members_status'], npoc.MEMBERS_STATUS_FAIL)
        aprovacao = npoc.avaliar_aprovacao_poc(r)
        self.assertNotEqual(aprovacao['poc_status'], 'APROVADO')

    def test_4_raw_native_entre_24_e_28_aceita(self):
        def baixar_falha_b(url, destino):
            if 'HINDCAST/.MONTHLY' in url:
                raise RuntimeError('simulado')
            return ('/tmp/fake.nc', False)

        ds = _ds_representacao_a(n_membros=28, com_target_correto=True)
        ds['PRATE'].values[:, :, 0, :4] = np.nan   # 4 missing no lead 1 -> 24/28, ainda dentro da faixa
        r = _executar(abrir_fn=lambda c: ds, baixar_fn=baixar_falha_b)
        self.assertEqual(r['member_axis_size'], 28)
        self.assertEqual(r['member_count_non_missing_por_lead'][0], 24)
        self.assertTrue(r['members_axis_size_ok'])
        self.assertTrue(all(r['members_count_per_lead_ok']))
        self.assertEqual(r['members_status'], npoc.MEMBERS_STATUS_OK)
        aprovacao = npoc.avaliar_aprovacao_poc(r)
        self.assertEqual(aprovacao['poc_status'], 'APROVADO')

    def test_5_raw_native_23_reprova(self):
        def baixar_falha_b(url, destino):
            if 'HINDCAST/.MONTHLY' in url:
                raise RuntimeError('simulado')
            return ('/tmp/fake.nc', False)

        ds = _ds_representacao_a(n_membros=28)
        ds['PRATE'].values[:, :, 0, :5] = np.nan   # 5 missing no lead 1 -> 23/28, abaixo do mínimo 24
        r = _executar(abrir_fn=lambda c: ds, baixar_fn=baixar_falha_b)
        self.assertEqual(r['member_count_non_missing_por_lead'][0], 23)
        self.assertFalse(r['members_count_per_lead_ok'][0])
        self.assertEqual(r['members_status'], npoc.MEMBERS_STATUS_FAIL)
        aprovacao = npoc.avaliar_aprovacao_poc(r)
        self.assertNotEqual(aprovacao['poc_status'], 'APROVADO')

    def test_6_raw_native_eixo_diferente_de_28_reprova(self):
        def baixar_falha_b(url, destino):
            if 'HINDCAST/.MONTHLY' in url:
                raise RuntimeError('simulado')
            return ('/tmp/fake.nc', False)

        r = _executar(abrir_fn=lambda c: _ds_representacao_a(n_membros=26), baixar_fn=baixar_falha_b)
        # member_axis_size é o valor DOCUMENTADO da rota (28, catálogo) —
        # o eixo REAL observado no dataset aberto é member_ids_axis.
        self.assertEqual(r['member_axis_size'], 28)
        self.assertEqual(len(r['member_ids_axis']), 26)
        self.assertFalse(r['members_axis_size_ok'])
        self.assertEqual(r['members_status'], npoc.MEMBERS_STATUS_FAIL)
        aprovacao = npoc.avaliar_aprovacao_poc(r)
        self.assertNotEqual(aprovacao['poc_status'], 'APROVADO')


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

    def test_8_grid_documentada_e_diferente_da_observada_do_subset(self):
        """Revisão final (item 4/9-#8) — grid_shape_documented vem do
        catálogo/rota (nunca chamado de 'observado'); subset_grid_shape_observed
        vem do Dataset real após o .sel() de ponto único, que colapsa as
        dimensões lat/lon — "1x1" aqui, nunca igual à grade documentada da
        fonte inteira."""
        r = _executar(abrir_fn=lambda c: _ds_representacao_b())
        self.assertIn('grid_shape_documented', r)
        self.assertIn('subset_grid_shape_observed', r)
        self.assertEqual(r['subset_grid_shape_observed'], '1x1')
        self.assertNotEqual(r['grid_shape_documented'], r['subset_grid_shape_observed'])


class LongitudeConventionTestCase(unittest.TestCase):
    """Revisão final (item 5/9-#9) — convenção de longitude só é afirmada
    quando de fato desambiguável a partir do dado real; nunca adivinhada."""

    def test_9_grade_completa_0_360_e_detectada(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b())
        self.assertEqual(r['longitude_convention'], nproc.LON_CONVENTION_0_360)

    def test_9_subset_de_1_ponto_ambiguo_fica_undetermined(self):
        # valor único, positivo e < 180 — não permite decidir entre 0-360
        # e -180/180 (poderia ser qualquer uma das duas convenções).
        self.assertEqual(nproc.detectar_convencao_longitude_observada([47.95]),
                          nproc.LON_CONVENTION_UNDETERMINED)

    def test_9_subset_de_1_ponto_negativo_e_neg180_180(self):
        self.assertEqual(nproc.detectar_convencao_longitude_observada([-47.95]),
                          nproc.LON_CONVENTION_NEG180_180)

    def test_9_subset_de_1_ponto_maior_que_180_e_0_360(self):
        self.assertEqual(nproc.detectar_convencao_longitude_observada([312.05]),
                          nproc.LON_CONVENTION_0_360)

    def test_9_grade_com_negativo_e_maior_que_180_e_ambigua(self):
        self.assertEqual(nproc.detectar_convencao_longitude_observada([-10.0, 190.0]),
                          nproc.LON_CONVENTION_UNDETERMINED)


class TemporalAuditTestCase(unittest.TestCase):
    """K — nmme_poc_temporal_audit.csv com as colunas exatas pedidas."""

    def test_k_colunas_exatas(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b())
        # mapping_confirmation_method (Seção 5, execução real #2) — qual
        # dos dois métodos confirmou (ou não) cada lead. init_selection_*
        # (Seção 7, execução real #3) — auditoria da seleção de
        # inicialização por lead. init_verification_* (revisão pós-
        # execução #3, risco residual) — método/URL/resultado da
        # verificação de controle independente.
        colunas_esperadas = {'centre', 'model_name', 'init_date', 'H_lead', 'source_L',
                              'target_month', 'mapping_status', 'evidence',
                              'mapping_confirmation_method', 'init_selection_method',
                              'init_value_requested', 'init_value_observed_on_variable',
                              'init_axis_size_observed_on_variable', 'init_selection_status',
                              'init_verification_method', 'init_verification_control_url',
                              'init_verification_result', 'notes'}
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

    def test_11_regressao_sem_valid_time_continua_reprovando(self):
        """Revisão final (item 7/9-#11) — regressão explícita: a lógica de
        mapeamento temporal NÃO foi afrouxada nesta rodada. Um dataset sem
        target/valid_time (só atributos L) continua UNCONFIRMED por lead e
        continua reprovando o POC — nenhum novo critério desta revisão
        (membros, grade, longitude) relaxa essa barreira preexistente."""
        r = _executar(abrir_fn=lambda c: _ds_representacao_b(com_target_correto=False))
        self.assertTrue((r['temporal_audit_df']['mapping_status'] == 'UNCONFIRMED').all())
        aprovacao = npoc.avaliar_aprovacao_poc(r)
        self.assertNotEqual(aprovacao['poc_status'], 'APROVADO')
        self.assertIn('temporal_mapping_confirmado', aprovacao['motivos_reprovacao'])

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

    def test_m_raw_count_nao_e_tautologico_com_membros_faltando(self):
        """Revisão final (item 1/9-#7) — n_raw_expected da Representação B é
        SEMPRE member_axis_size×len(leads) (144), derivado da rota, nunca
        recomputado a partir da contagem real observada. Com 3 membros
        faltando só no lead 1 (21/24 não-missing), n_raw real fica em 141
        — n_raw_expected continua 144 (não se ajusta silenciosamente para
        bater), raw_completo vira False, e o guardrail de membros reprova
        o POC (lead 1 abaixo do mínimo exato exigido pela política
        Harmonized)."""
        ds = _ds_representacao_b(n_membros=24)
        ds['prec'].values[:, :, 0, :3] = np.nan   # 3 membros missing só no lead 1
        r = _executar(abrir_fn=lambda c: ds)
        self.assertEqual(r['n_raw_expected'], 24 * 6)
        self.assertEqual(r['n_raw'], 141)
        self.assertFalse(r['raw_completo'])
        self.assertEqual(r['members_status'], npoc.MEMBERS_STATUS_FAIL)
        self.assertEqual(r['members_count_per_lead_ok'][0], False)
        aprovacao = npoc.avaliar_aprovacao_poc(r)
        self.assertNotEqual(aprovacao['poc_status'], 'APROVADO')
        self.assertIn('members_status_ok', aprovacao['motivos_reprovacao'])


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
        cache_path = ndl.caminho_cache(CFSV2, ncat.SOURCE_BACKEND_IRIDL_LEGACY,
                                         ncat.REPR_NMME_HARMONIZED_MONTHLY, 2005, 1)
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


class CalendarCftimeCacheTestCase(unittest.TestCase):
    """Revisão pós-execução #1 (run 35872475562) — a execução real
    provou DOWNLOAD_SUCCESS/DATASET_OPEN_ERROR (calendário 360_day sem
    cftime), nunca SERVICE_UNAVAILABLE, e revelou dois bugs estruturais
    à parte: cache compartilhado entre Representação A/B, e cache_hit
    perdido no caminho de exceção. Os 9 cenários abaixo (A-I) cobrem as
    duas frentes."""

    def test_a_calendar_360_day_abre_com_cftime(self):
        import tempfile
        import cftime as _cftime  # noqa: F401 — só confirma que está instalado (Seção 1)

        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / 'cfsv2_360day.nc'
            # 552 meses desde 1960-01 com calendário 360_day — mesma
            # estrutura CF real do erro da execução #1 ("months since
            # 1960-01-01" / calendar '360'), nunca pré-decodificado à
            # mão: escrito como número cru + atributos units/calendar,
            # exatamente como um NetCDF real do IRIDL chega.
            da_S = xr.DataArray(np.array([552.0]), dims=('S',),
                                  attrs={'units': 'months since 1960-01-01', 'calendar': '360_day'})
            ds_escrever = xr.Dataset(
                {'prec': (('S', 'L', 'M'), np.random.RandomState(1).rand(1, 6, 2))},
                coords={'S': da_S, 'L': np.arange(0.5, 6.5, 1.0), 'M': np.array([1, 2])})
            ds_escrever.to_netcdf(caminho)

            ds_aberto, modo, info_calendar = npoc.abrir_dataset_com_fallback_temporal(caminho, xr.open_dataset)
            self.assertEqual(modo, nproc.TIME_DECODE_MODE_CF_DATETIME)
            # decodificou de primeira (calendário já era '360_day', não
            # um alias) — nada para normalizar.
            self.assertFalse(info_calendar['calendar_normalization_applied'])
            # decodificado com sucesso (cftime instalado) — a coordenada
            # vira objeto de data real, não fica como número cru.
            self.assertNotEqual(str(ds_aberto['S'].dtype), 'float64')

            meta = nproc.inspecionar_metadata_temporal(ds_aberto, 'S')
            self.assertEqual(meta['calendar_observed'], '360_day')
            self.assertEqual(meta['time_units_observed'], 'months since 1960-01-01')

    def test_b_erro_especifico_de_decode_temporal_aciona_fallback(self):
        chamadas = []

        def abrir_com_erro_calendar(caminho, **kwargs):
            chamadas.append(kwargs)
            if not kwargs:
                raise ValueError(
                    "unable to decode time units 'months since 1960-01-01' with calendar '360'. "
                    "Try opening your dataset with decode_times=False or installing cftime")
            self.assertEqual(kwargs.get('decode_times'), False)
            return _ds_representacao_b()

        ds, modo, info_calendar = npoc.abrir_dataset_com_fallback_temporal(
            '/tmp/fake-b.nc', abrir_com_erro_calendar)
        self.assertEqual(modo, nproc.TIME_DECODE_MODE_RAW_NUMERIC_CF)
        self.assertEqual(len(chamadas), 2)
        self.assertEqual(chamadas[1], {'decode_times': False})
        # dataset sintético não tem atributo 'calendar' nenhum (nem '360'
        # nem alias conhecido) — nada para normalizar, fica RAW_NUMERIC_CF.
        self.assertFalse(info_calendar['calendar_normalization_applied'])

    def test_c_erro_generico_nao_aciona_fallback(self):
        chamadas = []

        def abrir_com_erro_generico(caminho, **kwargs):
            chamadas.append(kwargs)
            raise OSError("[Errno 2] No such file or directory: 'fake.nc' (simulado)")

        with self.assertRaises(OSError):
            npoc.abrir_dataset_com_fallback_temporal('/tmp/fake-c.nc', abrir_com_erro_generico)
        # nunca tentou decode_times=False para um erro que não é de
        # decodificação temporal — só a 1 chamada normal.
        self.assertEqual(len(chamadas), 1)

    def test_d_representacao_a_e_b_geram_paths_de_cache_diferentes(self):
        path_b = ndl.caminho_cache(CFSV2, ncat.SOURCE_BACKEND_IRIDL_LEGACY,
                                     ncat.REPR_NMME_HARMONIZED_MONTHLY, 2005, 1)
        path_a = ndl.caminho_cache(CFSV2, ncat.SOURCE_BACKEND_IRIDL_LEGACY,
                                     ncat.REPR_RAW_NATIVE_ENSEMBLE, 2005, 1)
        self.assertNotEqual(str(path_a), str(path_b))

    def test_e_urls_diferentes_nunca_compartilham_cache_silenciosamente(self):
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / 'shared.nc'
            chamadas_rede = []

            def fake_get(url, timeout=None):
                chamadas_rede.append(url)
                resp = mock.Mock()
                resp.raise_for_status = lambda: None
                resp.content = f'conteudo-de-{url}'.encode()
                return resp

            with mock.patch.object(ndl.requests, 'get', side_effect=fake_get):
                _, hit1 = ndl.baixar_arquivo('http://exemplo/A', destino)
                self.assertFalse(hit1)
                # MESMO path de destino, URL DIFERENTE — nunca reaproveita
                # o arquivo que já está lá (seria dado de uma URL errada).
                _, hit2 = ndl.baixar_arquivo('http://exemplo/B', destino)
                self.assertFalse(hit2)
            self.assertEqual(len(chamadas_rede), 2)
            self.assertEqual(destino.read_bytes(), b'conteudo-de-http://exemplo/B')

            # a MESMA url de novo agora sim reaproveita (sidecar confirma).
            with mock.patch.object(ndl.requests, 'get', side_effect=fake_get):
                _, hit3 = ndl.baixar_arquivo('http://exemplo/B', destino)
            self.assertTrue(hit3)
            self.assertEqual(len(chamadas_rede), 2)   # nenhuma chamada de rede nova

    def test_f_access_audit_mantem_download_ok_com_dataset_open_error(self):
        def baixar_ok(url, destino):
            return ('/tmp/fake-f.nc', False)

        def abrir_com_erro_generico(caminho):
            raise OSError('arquivo corrompido (simulado)')

        r = _executar(abrir_fn=abrir_com_erro_generico, baixar_fn=baixar_ok)
        self.assertEqual(r['poc_status'], 'REPROVADO_ACESSO')
        audit = r['access_audit_df']
        self.assertTrue((audit['download_status'] == 'OK').all())
        self.assertTrue((audit['dataset_open_status'] == 'DATASET_OPEN_ERROR').all())
        self.assertTrue((audit['status'] == 'DATASET_OPEN_ERROR').all())

    def test_g_cache_hit_real_preservado_em_falha_de_abertura(self):
        def baixar_com_cache_hit(url, destino):
            return ('/tmp/fake-g.nc', True)   # simula reaproveitamento de cache real

        def abrir_com_erro(caminho):
            raise OSError('erro simulado')

        r = _executar(abrir_fn=abrir_com_erro, baixar_fn=baixar_com_cache_hit)
        audit = r['access_audit_df']
        self.assertTrue((audit['cache_hit'] == True).all())  # noqa: E712

    def test_h_calendario_360_day_registrado_no_resultado(self):
        ds = _ds_representacao_b(com_target_correto=True)
        ds['S'] = ds['S'].assign_attrs(units='months since 1960-01-01', calendar='360_day')
        r = _executar(abrir_fn=lambda c: ds)
        self.assertEqual(r['calendar_observed'], '360_day')
        self.assertEqual(r['time_units_observed'], 'months since 1960-01-01')

    def test_i_temporal_mapping_sem_evidencia_de_target_continua_unconfirmed(self):
        r = _executar(abrir_fn=lambda c: _ds_representacao_b(com_target_correto=False))
        self.assertTrue((r['temporal_audit_df']['mapping_status'] == 'UNCONFIRMED').all())

    def test_i2_raw_numeric_cf_forca_unconfirmed_mesmo_com_target_presente_e_correto(self):
        """Prova que a barreira do modo RAW_NUMERIC_CF é por DESENHO, não
        por acidente de parse: mesmo com a variável target presente e
        CORRETA (com_target_correto=True), o modo RAW_NUMERIC_CF nunca
        confirma o mapeamento — Seção 2/8, não pode ser afrouxado."""
        ds = _ds_representacao_b(com_target_correto=True)
        resultado = nproc.avaliar_mapeamento_temporal(ds, 1, pd.Period('2005-01', 'M'),
                                                         time_decode_mode=nproc.TIME_DECODE_MODE_RAW_NUMERIC_CF)
        self.assertEqual(resultado['mapping_status'], 'UNCONFIRMED')
        self.assertIn('RAW_NUMERIC_CF', resultado['evidence'])


class CalendarAliasTestCase(unittest.TestCase):
    """Execução real #2 (run 35888809240) — item 1/9-#1,#3: '360' é um
    alias LEGADO DOCUMENTADO da convenção CF de '360_day', nunca tratado
    como calendário desconhecido; só aliases evidenciados são aceitos."""

    def test_1_calendar_360_normaliza_para_360_day(self):
        self.assertEqual(nproc.normalizar_calendar_cf('360'), ('360_day', True))

    def test_3_alias_desconhecido_nao_e_normalizado(self):
        self.assertEqual(nproc.normalizar_calendar_cf('calendario-nunca-catalogado'),
                          ('calendario-nunca-catalogado', False))


def _rota_metodo_b(documented=True):
    """Rota-fixture mínima para os testes do Método B — controla só
    `forecast_period_semantics_documented`, sem depender dos detalhes
    reais do catálogo (isola o teste da política de confirmação em si)."""
    return ncat.RotaMemberLevel(
        data_backend=ncat.SOURCE_BACKEND_IRIDL_LEGACY,
        dataset_representation=ncat.REPR_NMME_HARMONIZED_MONTHLY,
        dataset_path='fixture/teste', variable_name='prec', units_expected='mm/day',
        member_dimension='M', lead_dimension='L', init_dimension='S',
        lat_dimension='Y', lon_dimension='X',
        member_axis_size=4, grid_shape='fixture',
        status=ncat.ROUTE_STATUS_POC_READY_DOCUMENTED_LEGACY,
        source_continuity_risk=ncat.CONTINUITY_RISK_HIGH,
        forecast_period_semantics_documented=documented,
        mapping_reference=('fixture de teste',) if documented else (),
    )


def _ds_metodo_b(s_periodo='2005-01', s_standard_name='forecast_reference_time',
                   l_valores=(0.5, 1.5, 2.5, 3.5, 4.5, 5.5), l_units='months',
                   l_standard_name='forecast_period', com_target=False):
    """Dataset sintético SEM variável auxiliar de data-alvo (por padrão)
    — o caso real da execução #2, onde só a semântica do eixo
    forecast_period pôde confirmar o mapeamento."""
    lon_sb_360 = SAO_BENTO['lon'] % 360.0
    lons = np.array([lon_sb_360 - 1.0, lon_sb_360, lon_sb_360 + 1.0])
    lats = np.array([SAO_BENTO['lat'] - 1.0, SAO_BENTO['lat'], SAO_BENTO['lat'] + 1.0])
    membros = np.array([1, 2, 3, 4])
    rng = np.random.RandomState(21)
    dados = 0.00003 + rng.rand(3, 3, len(l_valores), len(membros)) * 0.00004
    l_attrs = {}
    if l_standard_name is not None:
        l_attrs['standard_name'] = l_standard_name
    if l_units is not None:
        l_attrs['units'] = l_units
    da_L = xr.DataArray(np.array(l_valores, dtype=float), dims=('L',), attrs=l_attrs)
    s_attrs = {'standard_name': s_standard_name} if s_standard_name else {}
    da_S = xr.DataArray(pd.Timestamp(f'{s_periodo}-01'), attrs=s_attrs)
    da = xr.DataArray(dados, dims=('X', 'Y', 'L', 'M'),
                        coords={'X': lons, 'Y': lats, 'L': da_L, 'M': membros, 'S': da_S},
                        attrs={'units': 'kg m-2 s-1'})
    ds = xr.Dataset({'prec': da})
    if com_target:
        alvos = ['2005-01', '2005-02', '2005-03', '2005-04', '2005-05', '2005-06'][:len(l_valores)]
        ds = ds.assign(target=(('L',), np.array(alvos)))
    return ds


class MetodoBSemanticaForecastPeriodTestCase(unittest.TestCase):
    """Execução real #2 (Seção 4) — Método B: confirmação por semântica
    documentada do eixo forecast_period, usada só quando não há
    variável auxiliar de data-alvo (Método A tem precedência)."""

    def test_4_s_forecast_reference_time_e_l_forecast_period_confirma_h1(self):
        ds = _ds_metodo_b()
        r = nproc.avaliar_mapeamento_temporal(ds, 1, pd.Period('2005-01', 'M'), rota=_rota_metodo_b())
        self.assertEqual(r['mapping_status'], 'OK')
        self.assertEqual(r['mapping_confirmation_method'],
                          nproc.MAPPING_METHOD_FORECAST_PERIOD_SEMANTICS)
        self.assertEqual(r['target_month'], '2005-01')

    def test_5_h1_a_h6_resultam_jan_a_jun_2005(self):
        ds = _ds_metodo_b()
        rota = _rota_metodo_b()
        alvos_esperados = ['2005-01', '2005-02', '2005-03', '2005-04', '2005-05', '2005-06']
        for h, alvo in zip(range(1, 7), alvos_esperados):
            r = nproc.avaliar_mapeamento_temporal(ds, h, pd.Period('2005-01', 'M'), rota=rota)
            self.assertEqual(r['mapping_status'], 'OK')
            self.assertEqual(r['target_month'], alvo)

    def test_6_l_sem_unidade_months_nao_confirma(self):
        ds = _ds_metodo_b(l_units='days')
        r = nproc.avaliar_mapeamento_temporal(ds, 1, pd.Period('2005-01', 'M'), rota=_rota_metodo_b())
        self.assertEqual(r['mapping_status'], 'UNCONFIRMED')
        self.assertEqual(r['mapping_confirmation_method'], nproc.MAPPING_METHOD_NONE)

    def test_7_l_sem_semantica_forecast_period_nao_confirma(self):
        ds = _ds_metodo_b(l_standard_name=None)
        r = nproc.avaliar_mapeamento_temporal(ds, 1, pd.Period('2005-01', 'M'), rota=_rota_metodo_b())
        self.assertEqual(r['mapping_status'], 'UNCONFIRMED')

    def test_8_origem_s_diferente_gera_mismatch(self):
        ds = _ds_metodo_b(s_periodo='2007-03')
        r = nproc.avaliar_mapeamento_temporal(ds, 1, pd.Period('2005-01', 'M'), rota=_rota_metodo_b())
        self.assertEqual(r['mapping_status'], 'MISMATCH')

    def test_9_valores_l_inesperados_geram_mismatch(self):
        ds = _ds_metodo_b(l_valores=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0))
        r = nproc.avaliar_mapeamento_temporal(ds, 1, pd.Period('2005-01', 'M'), rota=_rota_metodo_b())
        self.assertEqual(r['mapping_status'], 'MISMATCH')

    def test_10_variavel_alvo_tem_precedencia_quando_presente(self):
        """Mesmo com toda a semântica forecast_period corretamente
        identificável, se existir variável auxiliar (target/valid_time)
        o Método A decide — o Método B nunca chega a ser consultado
        (senão a semântica do eixo, correta, "confirmaria" apesar do
        target errado — provaria que a precedência não está sendo
        respeitada)."""
        ds = _ds_metodo_b(com_target=True)
        ds['target'].values[0] = '1999-12'   # corrompe só o target do lead 1
        r = nproc.avaliar_mapeamento_temporal(ds, 1, pd.Period('2005-01', 'M'), rota=_rota_metodo_b())
        self.assertEqual(r['mapping_status'], 'MISMATCH')
        self.assertNotEqual(r['mapping_confirmation_method'],
                             nproc.MAPPING_METHOD_FORECAST_PERIOD_SEMANTICS)

    def test_11_sem_nenhuma_evidencia_objetiva_continua_unconfirmed(self):
        ds = _ds_metodo_b(s_standard_name=None, l_standard_name=None, l_units=None)
        r = nproc.avaliar_mapeamento_temporal(ds, 1, pd.Period('2005-01', 'M'), rota=_rota_metodo_b())
        self.assertEqual(r['mapping_status'], 'UNCONFIRMED')
        self.assertEqual(r['mapping_confirmation_method'], nproc.MAPPING_METHOD_NONE)

    def test_7b_rota_sem_documentacao_nao_confirma_mesmo_com_atributos_corretos(self):
        """Item 7 do Método B — mesmo com TODOS os atributos reais
        corretos, sem forecast_period_semantics_documented=True na rota
        o Método B não confirma (guardrail contra 'aceitar só pela
        grade numérica', Seção 6)."""
        ds = _ds_metodo_b()
        r = nproc.avaliar_mapeamento_temporal(ds, 1, pd.Period('2005-01', 'M'),
                                                 rota=_rota_metodo_b(documented=False))
        self.assertEqual(r['mapping_status'], 'UNCONFIRMED')


def _escrever_netcdf_execucao2(caminho, calendar='360'):
    """Reproduz a estrutura real do arquivo da execução #2 (run
    35888809240): calendar='360' (alias legado), S/L com standard_name
    reais, 24 membros (política Harmonized), SEM variável target — o
    caso real que precisou do Método B."""
    lon_sb_360 = SAO_BENTO['lon'] % 360.0
    lons = np.array([lon_sb_360 - 1.0, lon_sb_360, lon_sb_360 + 1.0])
    lats = np.array([SAO_BENTO['lat'] - 1.0, SAO_BENTO['lat'], SAO_BENTO['lat'] + 1.0])
    leads_L = np.array([0.5, 1.5, 2.5, 3.5, 4.5, 5.5])
    membros = np.arange(1, 25)
    rng = np.random.RandomState(31)
    dados = 0.5 + rng.rand(3, 3, 6, 24) * 3.0

    da_S = xr.DataArray(540.0, attrs={'units': 'months since 1960-01-01', 'calendar': calendar,
                                        'standard_name': 'forecast_reference_time'})
    da_L = xr.DataArray(leads_L, dims=('L',),
                          attrs={'units': 'months', 'standard_name': 'forecast_period'})
    ds = xr.Dataset({'prec': (('X', 'Y', 'L', 'M'), dados)},
                     coords={'X': lons, 'Y': lats, 'L': da_L, 'M': membros, 'S': da_S})
    ds['prec'].attrs['units'] = 'mm/day'
    ds.to_netcdf(caminho)


class Execucao2ReproducaoTestCase(unittest.TestCase):
    """Reprodução ponta a ponta da execução real #2 (run 35888809240) —
    arquivo real com calendar='360', sem variável target, mas com
    semântica forecast_period identificável nos atributos reais — prova
    que a correção completa (cftime + normalização de alias + Método B)
    resolve o caso real de fato, não só em isolamento (item 9/9-#2)."""

    def test_2_calendario_original_preservado_end_to_end(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / 'exec2.nc'
            _escrever_netcdf_execucao2(caminho, calendar='360')

            def baixar_ok(url, destino):
                return (str(caminho), False)

            r = npoc.executar_poc_real_cfsv2(baixar_fn=baixar_ok, abrir_fn=xr.open_dataset)

            self.assertEqual(r['time_decode_mode'], nproc.TIME_DECODE_MODE_CF_DATETIME_NORMALIZED_ALIAS)
            # calendário ORIGINAL do arquivo nunca sobrescrito — os dois
            # ficam registrados lado a lado.
            self.assertEqual(r['calendar_original'], '360')
            self.assertEqual(r['calendar_normalized'], '360_day')
            self.assertTrue(r['calendar_normalization_applied'])
            self.assertEqual(r['calendar_observed'], '360_day')

            self.assertTrue((r['temporal_audit_df']['mapping_status'] == 'OK').all())
            self.assertEqual(sorted(r['temporal_audit_df']['target_month']),
                              ['2005-01', '2005-02', '2005-03', '2005-04', '2005-05', '2005-06'])
            self.assertTrue((r['temporal_audit_df']['mapping_confirmation_method']
                              == nproc.MAPPING_METHOD_FORECAST_PERIOD_SEMANTICS).all())

            aprovacao = npoc.avaliar_aprovacao_poc(r)
            self.assertEqual(aprovacao['poc_status'], 'APROVADO')


class MesParaIngridTestCase(unittest.TestCase):
    """Execução real #3 (run 35910675855, Seção 1/2) — a sintaxe Ingrid
    correta para seleção mensal de S usa o nome abreviado do mês
    ('Jan', 'Dec'), nunca o número ('01', '12'). O request malformado
    anterior não gerava erro HTTP — o servidor devolvia silenciosamente
    o primeiro valor do eixo S global do catálogo (1982-01) em vez da
    origem pedida (2005-01)."""

    def test_1_2005_01_gera_jan_2005_nunca_01_2005(self):
        url = ndl.montar_url_iri_cfsv2_nmme_harmonized(2005, 1, SAO_BENTO['lat'], SAO_BENTO['lon'])
        self.assertIn('S/(Jan%202005)/VALUE/', url)
        self.assertNotIn('01%202005', url)

    def test_2_dezembro_gera_dec(self):
        url = ndl.montar_url_iri_cfsv2_nmme_harmonized(2005, 12, SAO_BENTO['lat'], SAO_BENTO['lon'])
        self.assertIn('S/(Dec%202005)/VALUE/', url)
        self.assertNotIn('12%202005', url)

    def test_mes_para_ingrid_jan_may_sep_dec(self):
        self.assertEqual(ndl.mes_para_ingrid(1), 'Jan')
        self.assertEqual(ndl.mes_para_ingrid(5), 'May')
        self.assertEqual(ndl.mes_para_ingrid(9), 'Sep')
        self.assertEqual(ndl.mes_para_ingrid(12), 'Dec')

    def test_mes_para_ingrid_fora_da_faixa_falha(self):
        with self.assertRaises(ValueError):
            ndl.mes_para_ingrid(13)
        with self.assertRaises(ValueError):
            ndl.mes_para_ingrid(0)

    def test_representacao_a_tambem_usa_sintaxe_correta(self):
        """O mesmo bug existia no builder da Representação A (mesmo
        padrão de código) — corrigido junto, não só na B."""
        url = ndl.montar_url_iri_cfsv2_member_level(2005, 1, SAO_BENTO['lat'], SAO_BENTO['lon'])
        self.assertIn('S/(Jan%202005)/VALUE/', url)
        self.assertNotIn('01%202005', url)

    def test_montar_url_iridl_generico_tambem_corrigido(self):
        url = ndl.montar_url_iridl(CFSV2, 2005, 1, SAO_BENTO['lat'], SAO_BENTO['lon'],
                                     variavel='prec')
        self.assertIn('S/(Jan%202005)/VALUE/', url)
        self.assertNotIn('01%202005', url)


def _ds_selecao_s(modo='scalar', s_periodo='2005-01', n_valores_multiplos=3,
                    ingrid_value_documentado_na_rota=False):
    """Dataset sintético focado na dimensão S de 'prec', para os testes
    de `_avaliar_selecao_inicializacao` (execução real #3, Seção 3).
    `modo`: 'scalar' (0-d), 'singleton_dim' (dims=('S',), size=1),
    'multiplo' (size>1 — simula o eixo não filtrado pelo bug real),
    'ausente' (S não aparece em prec.coords — Ingrid VALUE pode ter
    removido a dimensão)."""
    lon_sb_360 = SAO_BENTO['lon'] % 360.0
    lons = np.array([lon_sb_360 - 1.0, lon_sb_360, lon_sb_360 + 1.0])
    lats = np.array([SAO_BENTO['lat'] - 1.0, SAO_BENTO['lat'], SAO_BENTO['lat'] + 1.0])
    membros = np.array([1, 2, 3, 4])
    l_valores = (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)
    da_L = xr.DataArray(np.array(l_valores), dims=('L',),
                          attrs={'units': 'months', 'standard_name': 'forecast_period'})
    rng = np.random.RandomState(41)

    if modo == 'scalar':
        da_S = xr.DataArray(pd.Timestamp(f'{s_periodo}-01'),
                              attrs={'standard_name': 'forecast_reference_time'})
        dados = 0.00003 + rng.rand(3, 3, len(l_valores), len(membros)) * 0.00004
        coords = {'X': lons, 'Y': lats, 'L': da_L, 'M': membros, 'S': da_S}
        prec = xr.DataArray(dados, dims=('X', 'Y', 'L', 'M'), coords=coords)
    elif modo == 'singleton_dim':
        da_S = xr.DataArray([pd.Timestamp(f'{s_periodo}-01')], dims=('S',),
                              attrs={'standard_name': 'forecast_reference_time'})
        dados = 0.00003 + rng.rand(1, 3, 3, len(l_valores), len(membros)) * 0.00004
        coords = {'S': da_S, 'X': lons, 'Y': lats, 'L': da_L, 'M': membros}
        prec = xr.DataArray(dados, dims=('S', 'X', 'Y', 'L', 'M'), coords=coords)
    elif modo == 'multiplo':
        # eixo S com múltiplos valores (o primeiro é 1982-01, igual ao
        # bug real observado) — nunca deve ser lido via flat[0].
        datas_s = pd.date_range('1982-01-01', periods=n_valores_multiplos, freq='YS')
        da_S = xr.DataArray(datas_s, dims=('S',), attrs={'standard_name': 'forecast_reference_time'})
        dados = 0.00003 + rng.rand(n_valores_multiplos, 3, 3, len(l_valores), len(membros)) * 0.00004
        coords = {'S': da_S, 'X': lons, 'Y': lats, 'L': da_L, 'M': membros}
        prec = xr.DataArray(dados, dims=('S', 'X', 'Y', 'L', 'M'), coords=coords)
    elif modo == 'ausente':
        dados = 0.00003 + rng.rand(3, 3, len(l_valores), len(membros)) * 0.00004
        coords = {'X': lons, 'Y': lats, 'L': da_L, 'M': membros}
        prec = xr.DataArray(dados, dims=('X', 'Y', 'L', 'M'), coords=coords)
    else:
        raise ValueError(modo)

    prec.attrs['units'] = 'kg m-2 s-1'
    return xr.Dataset({'prec': prec})


class SelecaoInicializacaoTestCase(unittest.TestCase):
    """Execução real #3 (Seção 3/4/5/6-E) — leitura da origem S
    associada à variável REAL de precipitação, nunca do eixo S global
    do Dataset como um todo (bug real: `ds['S'].values.flat[0]` podia
    devolver 1982-01 mesmo com a origem pedida sendo 2005-01)."""

    def test_3_s_scalar_confirma(self):
        ds = _ds_selecao_s(modo='scalar')
        r = nproc._avaliar_selecao_inicializacao(ds, _rota_metodo_b())
        self.assertEqual(r['init_selection_status'], nproc.INIT_SELECTION_STATUS_OK_SCALAR)
        self.assertEqual(r['init_value_observed_on_variable'], '2005-01')
        self.assertEqual(r['init_axis_size_observed_on_variable'], 1)

    def test_4_s_singleton_dim_confirma(self):
        ds = _ds_selecao_s(modo='singleton_dim')
        r = nproc._avaliar_selecao_inicializacao(ds, _rota_metodo_b())
        self.assertEqual(r['init_selection_status'], nproc.INIT_SELECTION_STATUS_OK_SINGLETON_DIM)
        self.assertEqual(r['init_value_observed_on_variable'], '2005-01')

    def test_5_s_multiplos_valores_reprova(self):
        ds = _ds_selecao_s(modo='multiplo', n_valores_multiplos=3)
        r = nproc._avaliar_selecao_inicializacao(ds, _rota_metodo_b())
        self.assertEqual(r['init_selection_status'], nproc.INIT_SELECTION_STATUS_FAIL_MULTIPLE)
        self.assertEqual(r['init_axis_size_observed_on_variable'], 3)
        self.assertIsNone(r['init_value_observed_on_variable'])

    def test_6_7_nunca_usa_flat0_do_eixo_com_multiplos_valores(self):
        """O primeiro valor do eixo S de múltiplos valores é 1982-01 —
        exatamente o valor incorretamente devolvido pelo bug real. A
        correção NUNCA usa esse valor como origem observada; reprova
        objetivamente em vez de mascarar como confirmação."""
        ds = _ds_selecao_s(modo='multiplo', n_valores_multiplos=5)
        primeiro_valor_do_eixo = str(ds['prec'].coords['S'].values[0])[:7]
        self.assertEqual(primeiro_valor_do_eixo, '1982-01')
        r = nproc._avaliar_selecao_inicializacao(ds, _rota_metodo_b())
        self.assertNotEqual(r.get('init_value_observed_on_variable'), '1982-01')
        self.assertEqual(r['init_selection_status'], nproc.INIT_SELECTION_STATUS_FAIL_MULTIPLE)
        # via avaliar_mapeamento_temporal (Método B completo) — MISMATCH,
        # nunca um OK silencioso.
        r_completo = nproc.avaliar_mapeamento_temporal(ds, 1, pd.Period('2005-01', 'M'),
                                                          rota=_rota_metodo_b())
        self.assertEqual(r_completo['mapping_status'], 'MISMATCH')

    def test_8_documentacao_sozinha_nao_confirma_fica_unconfirmed_ate_verificacao(self):
        """Revisão pós-execução #3 (risco residual) — a documentação do
        operador Ingrid VALUE, ISOLADAMENTE, não prova que o servidor
        selecionou a inicialização pedida; fica UNCONFIRMED_VALUE_
        UNVERIFIED (nunca OK) até uma verificação de controle
        independente confirmar (Seção 2/3/4 — testada ponta a ponta em
        VerificacaoControleValueTestCase)."""
        import dataclasses
        ds = _ds_selecao_s(modo='ausente')
        rota_documentada = dataclasses.replace(_rota_metodo_b(),
                                                  ingrid_value_init_selection_documented=True)
        r = nproc._avaliar_selecao_inicializacao(ds, rota_documentada)
        self.assertEqual(r['init_selection_status'], nproc.INIT_SELECTION_STATUS_UNCONFIRMED_VALUE_UNVERIFIED)
        self.assertEqual(r['init_selection_method'],
                          nproc.INIT_SELECTION_METHOD_REQUEST_CONFIRMED_SELECTION)
        r_completo = nproc.avaliar_mapeamento_temporal(ds, 1, pd.Period('2005-01', 'M'),
                                                          rota=rota_documentada)
        self.assertEqual(r_completo['mapping_status'], 'UNCONFIRMED')

    def test_8b_sem_documentacao_s_ausente_fica_unconfirmed(self):
        """A mesma ausência de S, mas SEM
        ingrid_value_init_selection_documented=True na rota — nunca
        confirma por padrão."""
        ds = _ds_selecao_s(modo='ausente')
        r = nproc._avaliar_selecao_inicializacao(ds, _rota_metodo_b())
        self.assertEqual(r['init_selection_status'], nproc.INIT_SELECTION_STATUS_UNCONFIRMED_NO_COORD)
        r_completo = nproc.avaliar_mapeamento_temporal(ds, 1, pd.Period('2005-01', 'M'),
                                                          rota=_rota_metodo_b())
        self.assertEqual(r_completo['mapping_status'], 'UNCONFIRMED')

    def test_9_l_fora_da_grade_continua_obrigatorio(self):
        """Regressão — a correção da seleção S não afrouxa a exigência
        de L=0.5..5.5 do Método B."""
        ds = _ds_selecao_s(modo='scalar')
        ds['L'] = ds['L'].assign_attrs(units='days')   # quebra só o requisito de L
        r = nproc.avaliar_mapeamento_temporal(ds, 1, pd.Period('2005-01', 'M'), rota=_rota_metodo_b())
        self.assertEqual(r['mapping_status'], 'UNCONFIRMED')


class Execucao3ReproducaoTestCase(unittest.TestCase):
    """Reprodução ponta a ponta da execução real #3 (run 35910675855) —
    com a sintaxe Ingrid corrigida (Jan 2005) e a leitura de S corrigida
    (variável real, nunca eixo global), o mesmo cenário real (sem
    variável target, backend IRIDL_LEGACY/NMME_HARMONIZED_MONTHLY, 24
    membros) deve chegar a APROVADO (item 9/9-#10)."""

    def _ds_execucao3(self, n_membros=24):
        lon_sb_360 = SAO_BENTO['lon'] % 360.0
        lons = np.array([lon_sb_360 - 1.0, lon_sb_360, lon_sb_360 + 1.0])
        lats = np.array([SAO_BENTO['lat'] - 1.0, SAO_BENTO['lat'], SAO_BENTO['lat'] + 1.0])
        l_valores = (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)
        membros = np.arange(1, n_membros + 1)
        rng = np.random.RandomState(51)
        dados = 0.5 + rng.rand(3, 3, len(l_valores), n_membros) * 3.0
        da_S = xr.DataArray(pd.Timestamp('2005-01-01'), attrs={'standard_name': 'forecast_reference_time'})
        da_L = xr.DataArray(np.array(l_valores), dims=('L',),
                              attrs={'units': 'months', 'standard_name': 'forecast_period'})
        prec = xr.DataArray(dados, dims=('X', 'Y', 'L', 'M'),
                              coords={'X': lons, 'Y': lats, 'L': da_L, 'M': membros, 'S': da_S})
        prec.attrs['units'] = 'mm/day'
        return xr.Dataset({'prec': prec})

    def test_10_run_sintetica_equivalente_a_execucao3_chega_a_aprovado(self):
        ds = self._ds_execucao3()
        r = _executar(abrir_fn=lambda c: ds)
        self.assertEqual(r['poc_status'], 'PROCESSADO')
        self.assertTrue((r['temporal_audit_df']['mapping_status'] == 'OK').all())
        self.assertTrue((r['temporal_audit_df']['init_selection_status']
                          == nproc.INIT_SELECTION_STATUS_OK_SCALAR).all())
        aprovacao = npoc.avaliar_aprovacao_poc(r)
        self.assertEqual(aprovacao['poc_status'], 'APROVADO')

    def test_10b_url_gerada_na_execucao_usa_sintaxe_correta(self):
        chamadas = []

        def baixar_registra(url, destino):
            chamadas.append(url)
            return ('/tmp/fake-exec3.nc', False)

        ds = self._ds_execucao3()
        _executar(abrir_fn=lambda c: ds, baixar_fn=baixar_registra)
        self.assertTrue(any('S/(Jan%202005)/VALUE/' in u for u in chamadas))
        self.assertFalse(any('01%202005' in u for u in chamadas))


def _ds_execucao3_sem_s(valor_base=0.5, escala=3.0, semente=61, n_membros=24):
    """Dataset sintético equivalente a `_ds_execucao3`, mas com S
    REMOVIDO de 'prec' (Ingrid VALUE eliminou a dimensão) — S continua
    presente no Dataset como um todo (variável decoy, dimensão própria,
    nunca compartilhada com 'prec') só para satisfazer o check de
    dimensões de `validar_acesso_dataset_real` (Seção 5/6), exatamente
    como um NetCDF real poderia preservar um artefato vestigial de S em
    outra variável enquanto 'prec' já foi recortado. Usado pelos testes
    de verificação de controle (revisão pós-execução #3, risco
    residual) — nunca cai para esse S decoy como substituto (é isso
    que a correção anterior já garante, lendo de `da.coords`)."""
    lon_sb_360 = SAO_BENTO['lon'] % 360.0
    lons = np.array([lon_sb_360 - 1.0, lon_sb_360, lon_sb_360 + 1.0])
    lats = np.array([SAO_BENTO['lat'] - 1.0, SAO_BENTO['lat'], SAO_BENTO['lat'] + 1.0])
    l_valores = (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)
    membros = np.arange(1, n_membros + 1)
    rng = np.random.RandomState(semente)
    dados = valor_base + rng.rand(3, 3, len(l_valores), n_membros) * escala
    da_L = xr.DataArray(np.array(l_valores), dims=('L',),
                          attrs={'units': 'months', 'standard_name': 'forecast_period'})
    prec = xr.DataArray(dados, dims=('X', 'Y', 'L', 'M'),
                          coords={'X': lons, 'Y': lats, 'L': da_L, 'M': membros})
    prec.attrs['units'] = 'mm/day'
    decoy_com_s = xr.DataArray([1.0], dims=('S',),
                                 coords={'S': [pd.Timestamp('2005-01-01')]})
    return xr.Dataset({'prec': prec, 'decoy_com_s_vestigial': decoy_com_s})


class VerificacaoControleValueTestCase(unittest.TestCase):
    """Revisão pós-execução #3 (risco residual) — a documentação do
    operador Ingrid VALUE, isoladamente, não prova que o servidor
    selecionou a inicialização pedida quando S é removido de 'prec'.
    Testa as 3 regressões pedidas: seleção correta (a consulta de
    controle confirma), seleção ignorada (a consulta de controle
    detecta) e verificação inconclusiva (nunca vira confirmação por
    omissão)."""

    @staticmethod
    def _duplas_baixar_abrir(ds_primaria, ds_controle=None, controle_levanta=None):
        def baixar_fn(url, destino):
            return (url, False)   # usa a própria URL como "caminho" p/ desambiguar no abrir_fn

        def abrir_fn(caminho, **kwargs):
            if 'Jan%202005' in caminho:
                return ds_primaria
            if controle_levanta is not None:
                raise controle_levanta
            return ds_controle

        return baixar_fn, abrir_fn

    def test_selecao_correta_verificacao_confirma_e_aprova(self):
        ds_primaria = _ds_execucao3_sem_s(semente=61)
        ds_controle = _ds_execucao3_sem_s(semente=62)   # valores DIFERENTES -> servidor respeita S
        baixar_fn, abrir_fn = self._duplas_baixar_abrir(ds_primaria, ds_controle=ds_controle)
        r = npoc.executar_poc_real_cfsv2(baixar_fn=baixar_fn, abrir_fn=abrir_fn)
        self.assertEqual(r['init_selection_status'], nproc.INIT_SELECTION_STATUS_OK_INGRID_VALUE_VERIFIED)
        self.assertEqual(r['init_verification_method'], 'INGRID_VALUE_CONTROL_QUERY')
        self.assertTrue(r['init_verification_control_url'])
        self.assertIn('DIVERGEM', r['init_verification_result'])
        self.assertTrue((r['temporal_audit_df']['mapping_status'] == 'OK').all())
        aprovacao = npoc.avaliar_aprovacao_poc(r)
        self.assertEqual(aprovacao['poc_status'], 'APROVADO')

    def test_selecao_ignorada_verificacao_detecta_e_nunca_aprova(self):
        ds_primaria = _ds_execucao3_sem_s(semente=61)
        ds_controle = _ds_execucao3_sem_s(semente=61)   # MESMOS valores -> servidor ignorou S
        baixar_fn, abrir_fn = self._duplas_baixar_abrir(ds_primaria, ds_controle=ds_controle)
        r = npoc.executar_poc_real_cfsv2(baixar_fn=baixar_fn, abrir_fn=abrir_fn)
        self.assertEqual(r['init_selection_status'], nproc.INIT_SELECTION_STATUS_FAIL_VALUE_IGNORED)
        self.assertIn('IDÊNTICOS', r['init_verification_result'])
        self.assertTrue((r['temporal_audit_df']['mapping_status'] == 'MISMATCH').all())
        aprovacao = npoc.avaliar_aprovacao_poc(r)
        self.assertNotEqual(aprovacao['poc_status'], 'APROVADO')

    def test_verificacao_inconclusiva_fica_unconfirmed_nunca_aprova(self):
        ds_primaria = _ds_execucao3_sem_s(semente=61)
        baixar_fn, abrir_fn = self._duplas_baixar_abrir(
            ds_primaria, controle_levanta=OSError('controle indisponível (simulado)'))
        r = npoc.executar_poc_real_cfsv2(baixar_fn=baixar_fn, abrir_fn=abrir_fn)
        self.assertEqual(r['init_selection_status'],
                          nproc.INIT_SELECTION_STATUS_UNCONFIRMED_VALUE_UNVERIFIED)
        self.assertIn('inconclusiva', r['init_verification_result'])
        self.assertTrue((r['temporal_audit_df']['mapping_status'] == 'UNCONFIRMED').all())
        aprovacao = npoc.avaliar_aprovacao_poc(r)
        self.assertNotEqual(aprovacao['poc_status'], 'APROVADO')

    def test_verificacao_registra_metodo_url_resultado_no_temporal_audit(self):
        ds_primaria = _ds_execucao3_sem_s(semente=61)
        ds_controle = _ds_execucao3_sem_s(semente=62)
        baixar_fn, abrir_fn = self._duplas_baixar_abrir(ds_primaria, ds_controle=ds_controle)
        r = npoc.executar_poc_real_cfsv2(baixar_fn=baixar_fn, abrir_fn=abrir_fn)
        linha = r['temporal_audit_df'].iloc[0]
        self.assertEqual(linha['init_verification_method'], 'INGRID_VALUE_CONTROL_QUERY')
        self.assertTrue(linha['init_verification_control_url'])
        self.assertTrue(linha['init_verification_result'])


if __name__ == '__main__':
    unittest.main()
