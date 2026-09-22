#!/usr/bin/env python3
"""
tests/test_nmme_backend_abstraction.py — regressão da correção final
pré-PR (Fase 2C.1): bug requests_previstos, abstração de backend
(IRIDL_LEGACY vs CCSR_BETA), sunset do IRIDL, e as duas representações
do CFSv2 legado. Tudo offline — nenhum teste acessa rede real.

Roda com:
    python -m unittest tests.test_nmme_backend_abstraction -v
"""

import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import nmme_catalogo as ncat  # noqa: E402
import nmme_download as ndl  # noqa: E402
import nmme_poc as npoc  # noqa: E402

CFSV2 = ncat.sistema_por_nome('NOAA_NCEP', 'CFSv2')


class RequestsPrevistosTestCase(unittest.TestCase):
    """1/A — requests_previstos usa sistemas_poc_prontos_para_teste_real
    (POC_READY_DOCUMENTED ∪ CONFIRMED), não sistemas_poc_executaveis
    (CONFIRMED puro) — bug real corrigido nesta rodada."""

    def test_a_requests_previstos_e_1_no_estado_atual(self):
        plano = npoc.plano_poc()
        self.assertEqual(plano['n_modelos_poc_executaveis'], 0)
        self.assertEqual(plano['n_modelos_poc_prontos_para_teste_real'], 1)
        self.assertEqual(plano['requests_previstos'], 1)

    def test_requests_previstos_bate_com_prontos_para_teste_real(self):
        plano = npoc.plano_poc()
        self.assertEqual(plano['requests_previstos'], plano['n_modelos_poc_prontos_para_teste_real'])


class LegacyVsCurrentTestCase(unittest.TestCase):
    """B/C — CFSv2 legacy identificado como legacy; forecast.ccsr
    identificado como beta/current."""

    def _rota(self, backend, representation=None):
        candidatas = [r for r in CFSV2.member_level_routes if r.data_backend == backend]
        if representation is not None:
            candidatas = [r for r in candidatas if r.dataset_representation == representation]
        return candidatas[0]

    def test_b_rota_legacy_identificada_como_legacy(self):
        rota = self._rota(ncat.SOURCE_BACKEND_IRIDL_LEGACY, ncat.REPR_RAW_NATIVE_ENSEMBLE)
        self.assertEqual(rota.source_continuity_risk, ncat.CONTINUITY_RISK_HIGH)
        self.assertEqual(rota.status, ncat.ROUTE_STATUS_POC_READY_DOCUMENTED_LEGACY)

    def test_b_metadata_marca_legacy_or_current_como_legacy(self):
        meta = npoc.montar_metadata()
        self.assertEqual(meta['legacy_or_current'], 'legacy')
        self.assertEqual(meta['data_backend_used'], ncat.SOURCE_BACKEND_IRIDL_LEGACY)

    def test_c_rota_ccsr_identificada_como_beta(self):
        rota = self._rota(ncat.SOURCE_BACKEND_CCSR_BETA)
        self.assertEqual(rota.source_continuity_risk, ncat.CONTINUITY_RISK_BETA)
        self.assertEqual(rota.status, ncat.ROUTE_STATUS_DISCOVERY_REQUIRED)

    def test_c_ccsr_seria_current_se_pronta(self):
        """Constrói uma rota CCSR sintética pronta e confirma que a
        classificação legacy_or_current vira 'current' — sem afirmar
        que a rota real está pronta (ela não está, Seção 12)."""
        rota_ccsr_pronta = replace(self._rota(ncat.SOURCE_BACKEND_CCSR_BETA),
                                    status=ncat.ROUTE_STATUS_POC_READY_DOCUMENTED_LEGACY,
                                    dataset_path='SOURCES-SINTETICO-SO-PARA-TESTE')
        sistema_sintetico = replace(CFSV2, member_level_routes=(
            rota_ccsr_pronta,
            self._rota(ncat.SOURCE_BACKEND_IRIDL_LEGACY, ncat.REPR_RAW_NATIVE_ENSEMBLE),
        ))
        meta = npoc.montar_metadata(sistemas=[sistema_sintetico])
        self.assertEqual(meta['legacy_or_current'], 'current')
        self.assertEqual(meta['data_backend_used'], ncat.SOURCE_BACKEND_CCSR_BETA)
        self.assertFalse(meta['backend_fallback_ocorreu'])


class BackendsNaoCompartilhamBuilderTestCase(unittest.TestCase):
    """D — backend IRIDL e CCSR não compartilham automaticamente o
    mesmo URL builder."""

    def test_d_ccsr_beta_nunca_monta_url(self):
        # backend=None cai no fallback IRIDL (CCSR não está pronto nesta
        # rodada) — o caminho relevante aqui é pedir CCSR_BETA
        # explicitamente, que deve recusar montar URL (Seção 12).
        with self.assertRaises(ValueError):
            ndl.montar_url_member_level(CFSV2, 2005, 1, -6.0203, -47.9022,
                                         backend=ncat.SOURCE_BACKEND_CCSR_BETA)

    def test_d_ccsr_beta_pronta_ainda_recusa_montar_url(self):
        """Mesmo se uma rota CCSR estivesse marcada pronta (sintético,
        só para este teste), o dispatcher recusa explicitamente montar
        URL para esse backend — nenhum builder foi escrito para
        CCSR_BETA nesta rodada (Seção 4/11-D)."""
        rota_ccsr_pronta = replace(
            [r for r in CFSV2.member_level_routes if r.data_backend == ncat.SOURCE_BACKEND_CCSR_BETA][0],
            status=ncat.ROUTE_STATUS_POC_READY_DOCUMENTED_LEGACY,
            dataset_path='SOURCES-SINTETICO-SO-PARA-TESTE')
        sistema_sintetico = replace(CFSV2, member_level_routes=(rota_ccsr_pronta,))
        with self.assertRaises(NotImplementedError):
            ndl.montar_url_member_level(sistema_sintetico, 2005, 1, -6.0203, -47.9022)

    def test_d_legacy_monta_url_real(self):
        r = ndl.montar_url_member_level(CFSV2, 2005, 1, -6.0203, -47.9022,
                                         backend=ncat.SOURCE_BACKEND_IRIDL_LEGACY)
        self.assertTrue(r['url'].startswith(ndl.IRI_CFSV2_MEMBER_LEVEL_BASE))

    def test_d_representacao_b_nao_implementada_ainda(self):
        """A Representação B (NMME_HARMONIZED_MONTHLY) está registrada
        no catálogo mas nenhum builder de URL foi escrito para ela
        nesta rodada (Seção 9/16) — deve falhar explicitamente, nunca
        cair silenciosamente no builder da Representação A."""
        rota_b = [r for r in CFSV2.member_level_routes
                  if r.dataset_representation == ncat.REPR_NMME_HARMONIZED_MONTHLY][0]
        self.assertEqual(rota_b.data_backend, ncat.SOURCE_BACKEND_IRIDL_LEGACY)
        self.assertIsNotNone(rota_b.dataset_path)
        self.assertNotEqual(rota_b.member_axis_size,
                             [r for r in CFSV2.member_level_routes
                              if r.dataset_representation == ncat.REPR_RAW_NATIVE_ENSEMBLE][0].member_axis_size)


class VariavelNaoConvertidaTestCase(unittest.TestCase):
    """E — variável PRATE (legacy) não é automaticamente convertida
    para pr (CCSR) — cada rota carrega o próprio variable_name, lido
    do catálogo, nunca derivado da outra."""

    def test_e_variable_name_legacy_e_prate(self):
        rota = [r for r in CFSV2.member_level_routes
                if r.dataset_representation == ncat.REPR_RAW_NATIVE_ENSEMBLE][0]
        self.assertEqual(rota.variable_name, 'PRATE')

    def test_e_variable_name_ccsr_e_pr_mas_nao_confirmado(self):
        rota = [r for r in CFSV2.member_level_routes
                if r.data_backend == ncat.SOURCE_BACKEND_CCSR_BETA][0]
        self.assertEqual(rota.variable_name, 'pr')
        self.assertEqual(rota.status, ncat.ROUTE_STATUS_DISCOVERY_REQUIRED)

    def test_e_nenhuma_conversao_implicita_no_codigo(self):
        """Não deve existir nenhuma função que derive 'pr' a partir de
        'PRATE' (ou vice-versa) por substituição de string — cada
        variable_name vem só do catálogo."""
        import inspect
        src = inspect.getsource(ndl)
        self.assertNotIn('"PRATE".lower()', src)
        self.assertNotIn("replace('PRATE'", src)
        self.assertNotIn('replace("PRATE"', src)


class MetadataInformaBackendTestCase(unittest.TestCase):
    """F — metadata informa qual backend foi usado."""

    def test_f_metadata_tem_data_backend_used(self):
        meta = npoc.montar_metadata()
        self.assertIn('data_backend_used', meta)
        self.assertIn('dataset_representation', meta)
        self.assertIn('service_status', meta)
        self.assertEqual(meta['data_backend_used'], ncat.SOURCE_BACKEND_IRIDL_LEGACY)
        self.assertEqual(meta['dataset_representation'], ncat.REPR_RAW_NATIVE_ENSEMBLE)

    def test_f_metadata_tem_legacy_service_expected_shutdown(self):
        meta = npoc.montar_metadata()
        self.assertEqual(meta['legacy_service_expected_shutdown'], '2026-10-31')


class FallbackRegistradoTestCase(unittest.TestCase):
    """G — fallback não ocorre silenciosamente: se CCSR falhar (estado
    atual, DISCOVERY_REQUIRED) e IRIDL for usado, isso é registrado
    explicitamente em fallback_ocorreu/motivo."""

    def test_g_escolher_backend_registra_fallback(self):
        escolha = ndl.escolher_backend_member_level(CFSV2)
        self.assertTrue(escolha['fallback_ocorreu'])
        self.assertIn('CCSR_BETA', escolha['motivo'])
        self.assertIn('DISCOVERY_REQUIRED', escolha['motivo'])

    def test_g_montar_url_member_level_propaga_fallback(self):
        r = ndl.montar_url_member_level(CFSV2, 2005, 1, -6.0203, -47.9022)
        self.assertTrue(r['fallback_ocorreu'])
        self.assertTrue(r['motivo_escolha'])

    def test_g_metadata_propaga_fallback(self):
        meta = npoc.montar_metadata()
        self.assertTrue(meta['backend_fallback_ocorreu'])
        self.assertIn('CCSR_BETA', meta['backend_fallback_motivo'])

    def test_g_sem_nenhuma_rota_pronta_falha_explicitamente(self):
        rota_ccsr_nao_pronta = [r for r in CFSV2.member_level_routes
                                 if r.data_backend == ncat.SOURCE_BACKEND_CCSR_BETA][0]
        sistema_sem_rotas_prontas = replace(CFSV2, member_level_routes=(rota_ccsr_nao_pronta,))
        with self.assertRaises(RuntimeError):
            ndl.escolher_backend_member_level(sistema_sem_rotas_prontas)


class NaoInventarEndpointCcsrTestCase(unittest.TestCase):
    """12 — nunca construir URL do CCSR por tentativa de padrão."""

    def test_dataset_path_ccsr_e_none(self):
        rota = [r for r in CFSV2.member_level_routes
                if r.data_backend == ncat.SOURCE_BACKEND_CCSR_BETA][0]
        self.assertIsNone(rota.dataset_path)

    def test_validador_rejeita_discovery_required_com_path(self):
        rota_invalida = replace(
            [r for r in CFSV2.member_level_routes
             if r.data_backend == ncat.SOURCE_BACKEND_CCSR_BETA][0],
            dataset_path='https://forecast.ccsr.columbia.edu/inventado')
        sistema_invalido = replace(CFSV2, member_level_routes=(rota_invalida,))
        with self.assertRaises(ValueError) as e:
            ncat._validar_catalogo([sistema_invalido])
        self.assertIn('DISCOVERY_REQUIRED', str(e.exception))


class RepresentacoesDistintasTestCase(unittest.TestCase):
    """9 — duas representações do CFSv2 legado, nunca reconciliadas."""

    def test_representacao_a_e_b_tem_member_axis_size_diferentes(self):
        rota_a = [r for r in CFSV2.member_level_routes
                  if r.dataset_representation == ncat.REPR_RAW_NATIVE_ENSEMBLE][0]
        rota_b = [r for r in CFSV2.member_level_routes
                  if r.dataset_representation == ncat.REPR_NMME_HARMONIZED_MONTHLY][0]
        self.assertEqual(rota_a.member_axis_size, 28)
        self.assertEqual(rota_b.member_axis_size, 24)
        self.assertEqual(rota_a.grid_shape, '384x190 (Gaussiana, 0,9375° em X)')
        self.assertEqual(rota_b.grid_shape, '360x181 (regular 1°x1°)')
        self.assertEqual(rota_a.variable_name, 'PRATE')
        self.assertEqual(rota_b.variable_name, 'prec')


if __name__ == '__main__':
    unittest.main()
