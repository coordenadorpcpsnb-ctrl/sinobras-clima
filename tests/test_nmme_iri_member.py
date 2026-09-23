#!/usr/bin/env python3
"""
tests/test_nmme_iri_member.py — regressão da Rota B (IRI Data Library,
dataset CFSv2 member-level) adicionada nesta rodada (Seção 15 A-J da
tarefa: rota IRI CFSv2 member-level, origem 2005-01, mapeamento L
auditável, faixa de membros 24-28, nominal vs. observado, dry-run
seleciona CFSv2, request com subset espacial/temporal, sem skill).
Tudo offline — nenhum teste acessa rede real; o dataset usado em
processar_origem_modelo é SINTÉTICO (mesma convenção de
tests/test_nmme_poc.py), nunca um subset real do IRI (bloqueado nesta
sessão, ver scripts/nmme_catalogo.py/nmme_download.py).

Roda com:
    python -m unittest tests.test_nmme_iri_member -v
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import xarray as xr

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import nmme_catalogo as ncat  # noqa: E402
import nmme_download as ndl  # noqa: E402
import nmme_poc as npoc  # noqa: E402
from _c3s_utils import MUNICIPIOS  # noqa: E402

CFSV2 = ncat.sistema_por_nome('NOAA_NCEP', 'CFSv2')


def _dataset_sintetico_L_ingrid(n_membros=28, unidade='kg m-2 s-1', valor_base=0.00003,
                                 escala_ruido=0.00004):
    """xarray.Dataset sintético com L nos valores REAIS do grid Ingrid
    da Rota B (0.5, 1.5, ..., 5.5 — H1-H6), não 1..6 — usado só para
    testar o mapeamento h_lead_para_L_ingrid (Seção 8/D), nunca dado
    real."""
    info = MUNICIPIOS[npoc.MUNICIPIO]
    lons = np.array([info['lon'] - 1.0, info['lon'], info['lon'] + 1.0])
    lats = np.array([info['lat'] - 1.0, info['lat'], info['lat'] + 1.0])
    membros = np.arange(1, n_membros + 1)
    leads_L = np.array([0.5, 1.5, 2.5, 3.5, 4.5, 5.5])
    rng = np.random.RandomState(7)
    dados = valor_base + rng.rand(len(lons), len(lats), len(leads_L), len(membros)) * escala_ruido
    da = xr.DataArray(dados, dims=('X', 'Y', 'L', 'M'),
                       coords={'X': lons, 'Y': lats, 'L': leads_L, 'M': membros},
                       attrs={'units': unidade})
    return xr.Dataset({'PRATE': da})


class CatalogoRotaIriTestCase(unittest.TestCase):
    """A — CFSv2 rota IRI member-level existe no catálogo, distinta da
    Rota A (CPC/CPT)."""

    def test_a_member_level_dataset_path_presente(self):
        self.assertIsNotNone(CFSV2.member_level_dataset_path)
        self.assertIn('PRATE', CFSV2.member_level_dataset_path)
        self.assertIn('CFSv2', CFSV2.member_level_dataset_path)

    def test_a_member_level_data_source_presente(self):
        self.assertIsNotNone(CFSV2.member_level_data_source)

    def test_a_data_url_template_continua_sendo_a_rota_a_cpt(self):
        """Nunca reaproveita data_url_template (Rota A) para a Rota B —
        são estruturas diferentes (Seção 3 da tarefa)."""
        self.assertIn('cpt', CFSV2.data_url_template.lower())
        self.assertNotEqual(CFSV2.data_url_template, CFSV2.member_level_dataset_path)

    def test_a_data_access_status_poc_ready_documented(self):
        self.assertEqual(CFSV2.data_access_status, ncat.DATA_ACCESS_POC_READY_DOCUMENTED)

    def test_a_homogeneous_hindcast_end_distinto_de_hindcast_end(self):
        """Seção 6 — 1991-2020 é o período conceitual NMME3 pooled;
        homogeneous_hindcast_end é o fim do arquivo nativo da Rota B,
        um conceito diferente."""
        self.assertEqual(CFSV2.homogeneous_hindcast_end, '2011-03')
        self.assertEqual(CFSV2.hindcast_end, 2020)


class OrigemDentroDoNativoTestCase(unittest.TestCase):
    """B/C — origem 2005-01 dentro da cobertura nativa; 2015-01 fora."""

    def test_b_2005_01_dentro_do_nativo(self):
        self.assertTrue(ndl.origem_dentro_do_nativo_rota_b(2005, 1))

    def test_c_2015_01_fora_do_nativo(self):
        self.assertFalse(ndl.origem_dentro_do_nativo_rota_b(2015, 1))

    def test_limites_exatos_do_s_grid(self):
        self.assertTrue(ndl.origem_dentro_do_nativo_rota_b(1981, 12))
        self.assertTrue(ndl.origem_dentro_do_nativo_rota_b(2011, 3))
        self.assertFalse(ndl.origem_dentro_do_nativo_rota_b(1981, 11))
        self.assertFalse(ndl.origem_dentro_do_nativo_rota_b(2011, 4))

    def test_poc_origem_e_2005_01(self):
        self.assertEqual(npoc.POC_ORIGEM, (2005, 1))


class MapeamentoLeadLTestCase(unittest.TestCase):
    """D — L=0.5 não é convertido silenciosamente sem auditoria; a
    correspondência H<->L é hipótese explícita, registrada no
    temporal_audit quando usada."""

    def test_d_h_lead_para_l_ingrid_mapeamento(self):
        self.assertEqual(ndl.h_lead_para_L_ingrid(1), 0.5)
        self.assertEqual(ndl.h_lead_para_L_ingrid(6), 5.5)
        self.assertEqual(ndl.h_lead_para_L_ingrid(10), 9.5)

    def test_d_h_fora_da_faixa_reprova(self):
        with self.assertRaises(ValueError):
            ndl.h_lead_para_L_ingrid(0)
        with self.assertRaises(ValueError):
            ndl.h_lead_para_L_ingrid(11)

    def test_d_processar_origem_registra_mapeamento_no_temporal_audit(self):
        """Sem mapa_lead_para_L, comportamento original (L=lead) —
        usado pelas outras fontes. Com mapa_lead_para_L (Rota B do
        CFSv2), o temporal_audit registra explicitamente a hipótese de
        mapeamento H->L, nunca arredonda silenciosamente."""
        ds = _dataset_sintetico_L_ingrid(n_membros=24)
        _, temporal_df, _ = npoc.processar_origem_modelo(
            CFSV2, 2005, 1, ds, mapa_lead_para_L=ndl.h_lead_para_L_ingrid,
            membros_esperados_min=24, membros_esperados_max=28)
        for _, row in temporal_df.iterrows():
            self.assertIn('L=', row['source_lead_coordinate'])
            self.assertIn('HIPÓTESE', row['source_lead_coordinate'])

    def test_d_sem_mapa_l_igual_lead_mantido(self):
        """Regressão: fontes sem mapa_lead_para_L continuam com o
        comportamento original (L=lead direto)."""
        from tests.test_nmme_poc import _dataset_sintetico, SISTEMA_TESTE
        ds = _dataset_sintetico(n_membros=SISTEMA_TESTE.hindcast_members)
        _, temporal_df, _ = npoc.processar_origem_modelo(SISTEMA_TESTE, 2015, 1, ds)
        self.assertTrue((temporal_df['source_lead_coordinate'] == 'L (ingrid)').all())


class FaixaMembrosTestCase(unittest.TestCase):
    """E/F — M aceita 24-28 no dado bruto observado; nominal (24) e
    observado (bruto) são conceitos distintos, nunca confundidos."""

    def test_e_24_membros_aceito(self):
        ds = _dataset_sintetico_L_ingrid(n_membros=24)
        _, _, meta = npoc.processar_origem_modelo(
            CFSV2, 2005, 1, ds, mapa_lead_para_L=ndl.h_lead_para_L_ingrid,
            membros_esperados_min=24, membros_esperados_max=28)
        self.assertEqual(meta['n_members_observed'], 24)

    def test_e_28_membros_aceito(self):
        ds = _dataset_sintetico_L_ingrid(n_membros=28)
        _, _, meta = npoc.processar_origem_modelo(
            CFSV2, 2005, 1, ds, mapa_lead_para_L=ndl.h_lead_para_L_ingrid,
            membros_esperados_min=24, membros_esperados_max=28)
        self.assertEqual(meta['n_members_observed'], 28)

    def test_e_23_membros_fora_da_faixa_reprova(self):
        ds = _dataset_sintetico_L_ingrid(n_membros=23)
        with self.assertRaises(RuntimeError) as e:
            npoc.processar_origem_modelo(
                CFSV2, 2005, 1, ds, mapa_lead_para_L=ndl.h_lead_para_L_ingrid,
                membros_esperados_min=24, membros_esperados_max=28)
        self.assertIn('faixa aceita', str(e.exception))

    def test_e_29_membros_fora_da_faixa_reprova(self):
        ds = _dataset_sintetico_L_ingrid(n_membros=29)
        with self.assertRaises(RuntimeError) as e:
            npoc.processar_origem_modelo(
                CFSV2, 2005, 1, ds, mapa_lead_para_L=ndl.h_lead_para_L_ingrid,
                membros_esperados_min=24, membros_esperados_max=28)
        self.assertIn('faixa aceita', str(e.exception))

    def test_f_nominal_diferente_de_tamanho_bruto_do_eixo_m(self):
        """hindcast_members=24 (amostra NOMINAL do produto NMME3) é
        DISTINTO de M_NATIVO_TAMANHO=28 (tamanho do eixo M no
        catálogo-fonte Ingrid da Rota B) — nunca confundidos."""
        self.assertEqual(CFSV2.hindcast_members, 24)
        self.assertEqual(ndl.M_NATIVO_TAMANHO, 28)
        self.assertNotEqual(CFSV2.hindcast_members, ndl.M_NATIVO_TAMANHO)
        self.assertEqual((ndl.M_OBSERVADO_MIN, ndl.M_OBSERVADO_MAX), (24, 28))

    def test_f_28_membros_nao_falha_so_por_ser_diferente_de_24(self):
        """Seção 5 — 'não falhar só porque aparecem 28'."""
        ds = _dataset_sintetico_L_ingrid(n_membros=28)
        # não deve levantar:
        npoc.processar_origem_modelo(
            CFSV2, 2005, 1, ds, mapa_lead_para_L=ndl.h_lead_para_L_ingrid,
            membros_esperados_min=24, membros_esperados_max=28)


class RequestIriSubsetTestCase(unittest.TestCase):
    """I — request IRI usa subset espacial/temporal, não o globo
    inteiro."""

    def test_i_url_contem_subset_x_y_s_l(self):
        url = ndl.montar_url_iri_cfsv2_member_level(2005, 1, -6.0203, -47.9022)
        self.assertIn('X/-47.9022/VALUE', url)
        self.assertIn('Y/-6.0203/VALUE', url)
        # Execução real #3 (run 35910675855, Seção 1) — sintaxe Ingrid
        # correta para seleção mensal de S é o nome abreviado do mês
        # ('Jan'), nunca o número ('01'); a forma numérica é a que
        # causou o bug real (servidor devolvia silenciosamente o
        # primeiro valor do eixo S global, 1982-01, em vez da origem
        # pedida, sem erro HTTP).
        self.assertIn('S/(Jan%202005)/VALUE', url)
        self.assertNotIn('01%202005', url)
        self.assertIn('L/(0.5)/(5.5)/RANGEEDGES', url)
        self.assertIn(ndl.IRI_CFSV2_MEMBER_LEVEL_PATH, url)

    def test_i_nao_baixa_o_globo_nem_todos_os_anos(self):
        """Nunca deve haver seleção de X/Y global (sem VALUE) nem S sem
        recorte de uma origem única."""
        url = ndl.montar_url_iri_cfsv2_member_level(2005, 1, -6.0203, -47.9022)
        self.assertNotIn('/X/0/360', url)
        self.assertEqual(url.count('/S/'), 1)

    def test_i_origem_fora_do_nativo_falha_antes_de_montar_url(self):
        with self.assertRaises(ValueError):
            ndl.montar_url_iri_cfsv2_member_level(2015, 1, -6.0203, -47.9022)

    def test_i_faixa_de_leads_configuravel_mantem_subset_pequeno(self):
        url = ndl.montar_url_iri_cfsv2_member_level(2005, 1, -6.0203, -47.9022,
                                                       h_lead_min=1, h_lead_max=3)
        self.assertIn('L/(0.5)/(2.5)/RANGEEDGES', url)


class PocSemSkillTestCase(unittest.TestCase):
    """J — POC continua sem calcular skill (CHIRPS/RMSE/MSESS/Brier/
    RPSS), mesmo com a Rota B adicionada."""

    def test_j_modulo_download_nao_calcula_skill(self):
        import inspect
        src = inspect.getsource(ndl)
        for proibido in ('rmse', 'msess', 'brier', 'rpss', 'chirps'):
            self.assertNotIn(proibido, src.lower())

    def test_j_processar_origem_modelo_nao_calcula_skill(self):
        import inspect
        src = inspect.getsource(npoc.processar_origem_modelo)
        for proibido in ('rmse', 'msess', 'brier', 'rpss', 'chirps'):
            self.assertNotIn(proibido, src.lower())


if __name__ == '__main__':
    unittest.main()
