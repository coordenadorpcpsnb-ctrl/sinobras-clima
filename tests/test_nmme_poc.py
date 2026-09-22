#!/usr/bin/env python3
"""
tests/test_nmme_poc.py — regressão de nmme_processar.py/nmme_download.py/
nmme_poc.py e do workflow .github/workflows/nmme_poc.yml (Fase 2C.1).
Tudo offline — nenhum teste acessa rede real; `processar_origem_modelo`
é exercitado com um xarray.Dataset SINTÉTICO (convenção de dimensões
X/Y/L/M/S padrão IRIDL), nunca um arquivo NMME real (não baixado nesta
tarefa — Seção 38/50).

Roda com:
    python -m unittest tests.test_nmme_poc -v
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import nmme_catalogo as ncat  # noqa: E402
import nmme_download as ndl  # noqa: E402
import nmme_processar as nproc  # noqa: E402
import nmme_poc as npoc  # noqa: E402
from _c3s_utils import MUNICIPIOS  # noqa: E402

WORKFLOW_PATH = ROOT / '.github' / 'workflows' / 'nmme_poc.yml'

SISTEMA_TESTE = ncat.sistema_por_nome('NOAA_GFDL', 'GFDL_SPEAR')   # hindcast_members=15, documentado


def _dataset_sintetico(n_membros=15, leads=(1, 2, 3, 4, 5, 6), unidade='mm/day', variavel='prec',
                        valor_base=5.0, escala_ruido=3.0):
    """xarray.Dataset sintético com a convenção de dimensões padrão
    IRIDL (X=lon, Y=lat, L=lead, M=member) — usado só para testar o
    PARSING, nunca dado real (Seção 38/50)."""
    info = MUNICIPIOS[npoc.MUNICIPIO]
    lons = np.array([info['lon'] - 1.0, info['lon'], info['lon'] + 1.0])
    lats = np.array([info['lat'] - 1.0, info['lat'], info['lat'] + 1.0])
    membros = np.arange(n_membros)
    leads_arr = np.array(leads)
    rng = np.random.RandomState(3)
    dados = valor_base + rng.rand(len(lons), len(lats), len(leads_arr), len(membros)) * escala_ruido
    da = xr.DataArray(dados, dims=('X', 'Y', 'L', 'M'),
                       coords={'X': lons, 'Y': lats, 'L': leads_arr, 'M': membros},
                       attrs={'units': unidade})
    return xr.Dataset({variavel: da})


# ══════════════════════════════════════════════════════════════════════════
# H/J/K/I — conversão de unidade mm/mês, considerando dias do mês-alvo.
# ══════════════════════════════════════════════════════════════════════════

class ConversaoUnidadeTestCase(unittest.TestCase):

    def test_h_dias_no_mes_usados_na_conversao(self):
        r31 = nproc.converter_precip_para_mm_mes(1.0, 'mm/day', '2024-01')   # janeiro, 31 dias
        r30 = nproc.converter_precip_para_mm_mes(1.0, 'mm/day', '2024-04')   # abril, 30 dias
        self.assertEqual(r31['forecast_prec_mm_month'], 31.0)
        self.assertEqual(r30['forecast_prec_mm_month'], 30.0)

    def test_i_fevereiro_bissexto_29_dias(self):
        self.assertEqual(nproc.dias_no_mes('2024-02'), 29)   # 2024 é bissexto
        self.assertEqual(nproc.dias_no_mes('2023-02'), 28)   # 2023 não é

    def test_i_fevereiro_bissexto_na_conversao(self):
        r = nproc.converter_precip_para_mm_mes(2.0, 'mm/day', '2024-02')
        self.assertEqual(r['forecast_prec_mm_month'], 58.0)   # 2.0 * 29

    def test_j_mm_dia_para_mm_mes(self):
        r = nproc.converter_precip_para_mm_mes(3.0, 'mm/day', '2020-06')   # junho, 30 dias
        self.assertEqual(r['forecast_prec_mm_month'], 90.0)
        self.assertIn('mm/day', r['conversion_applied'])

    def test_k_kg_m2_s_para_mm_mes(self):
        # 1 kg m-2 s-1 == 1 mm/s -> * 86400 s/dia * dias_no_mes
        r = nproc.converter_precip_para_mm_mes(0.0001, 'kg m-2 s-1', '2021-01')   # 31 dias
        esperado = round(0.0001 * 86400.0 * 31, 3)
        self.assertEqual(r['forecast_prec_mm_month'], esperado)

    def test_unidade_desconhecida_falha_explicitamente(self):
        with self.assertRaises(ValueError):
            nproc.converter_precip_para_mm_mes(1.0, 'unidade-nunca-vista', '2020-01')

    def test_conversion_applied_e_units_original_sempre_registrados(self):
        r = nproc.converter_precip_para_mm_mes(1.0, 'mm/day', '2020-01')
        self.assertTrue(r['conversion_applied'])
        self.assertEqual(r['units_original'], 'mm/day')


# ══════════════════════════════════════════════════════════════════════════
# L/M — mapeamento de target month, H1-H6 distintos.
# ══════════════════════════════════════════════════════════════════════════

class TargetMonthTestCase(unittest.TestCase):

    def test_l_target_month_lead1_igual_mes_inicializacao(self):
        alvo = nproc.leadtime_para_mes_alvo_nmme('2015-01', 1, 'lead1_igual_mes_inicializacao')
        self.assertEqual(str(alvo), '2015-01')

    def test_l_target_month_lead1_mes_seguinte(self):
        alvo = nproc.leadtime_para_mes_alvo_nmme('2015-01', 1, 'lead1_mes_seguinte')
        self.assertEqual(str(alvo), '2015-02')

    def test_l_esquema_desconhecido_falha(self):
        with self.assertRaises(ValueError):
            nproc.leadtime_para_mes_alvo_nmme('2015-01', 1, 'esquema-inventado')

    def test_m_h1_a_h6_distintos(self):
        alvos = {nproc.leadtime_para_mes_alvo_nmme('2015-01', lead) for lead in range(1, 7)}
        self.assertEqual(len(alvos), 6)

    def test_lead_menor_que_1_falha(self):
        with self.assertRaises(ValueError):
            nproc.leadtime_para_mes_alvo_nmme('2015-01', 0)


# ══════════════════════════════════════════════════════════════════════════
# N — lat/lon selecionados registrados; grid_distance_km calculada.
# ══════════════════════════════════════════════════════════════════════════

class GradeTestCase(unittest.TestCase):

    def test_n_lat_lon_selecionados_registrados_na_linha_raw(self):
        linha = nproc.montar_linha_raw(
            SISTEMA_TESTE, '2015-01', '2015-01', 1, 0, 100.0,
            requested_lat=-6.0203, requested_lon=-47.9022,
            selected_lat=-6.0, selected_lon=-48.0,
            variable_original='prec', units_original='mm/day', conversion_applied='x',
            source_url='http://x', source_type='NetCDF/IRIDL')
        self.assertEqual(linha['requested_lat'], -6.0203)
        self.assertEqual(linha['selected_lat'], -6.0)
        self.assertEqual(linha['selected_lon'], -48.0)
        self.assertGreater(linha['grid_distance_km'], 0)

    def test_localizacao_e_a_mesma_das_fases_c3s(self):
        self.assertEqual(npoc.MUNICIPIO, 'Sao_Bento_do_Tocantins')
        self.assertIn(npoc.MUNICIPIO, MUNICIPIOS)


# ══════════════════════════════════════════════════════════════════════════
# O — equal-model weighting não depende do número de membros.
# ══════════════════════════════════════════════════════════════════════════

class EqualModelWeightingTestCase(unittest.TestCase):

    def test_o_estatistica_nao_recebe_peso_por_membro(self):
        import inspect
        assinatura = inspect.signature(nproc.estatisticas_ensemble_modelo)
        self.assertEqual(list(assinatura.parameters), ['valores_membros'])   # nenhum parâmetro de peso/nº

    def test_o_media_e_so_a_media_dos_membros_do_proprio_modelo(self):
        poucos = nproc.estatisticas_ensemble_modelo([10.0, 20.0])
        muitos = nproc.estatisticas_ensemble_modelo([10.0] * 50 + [20.0] * 50)
        self.assertEqual(poucos['mean'], 15.0)
        self.assertEqual(muitos['mean'], 15.0)   # nº de membros não muda a estatística em si


# ══════════════════════════════════════════════════════════════════════════
# P/Q/R — barreiras: variável ausente, NaN/inf, precipitação negativa.
# ══════════════════════════════════════════════════════════════════════════

class BarreirasTestCase(unittest.TestCase):

    def test_p_arquivo_sem_variavel_precipitacao_reprova(self):
        with self.assertRaises(RuntimeError) as e:
            nproc.validar_variavel_precipitacao(['sst', 'tsmx', 'z500'])
        self.assertIn('nenhuma variável de precipitação', str(e.exception))

    def test_p_variavel_reconhecida_aceita_case_insensitive(self):
        nome = nproc.validar_variavel_precipitacao(['SST', 'PRATE', 'Z500'])
        self.assertEqual(nome, 'PRATE')

    def test_q_nan_reprova_raw(self):
        with self.assertRaises(RuntimeError) as e:
            nproc.validar_raw([1.0, np.nan, 3.0])
        self.assertIn('não finito', str(e.exception))

    def test_q_inf_reprova_raw(self):
        with self.assertRaises(RuntimeError):
            nproc.validar_raw([1.0, np.inf, 3.0])

    def test_r_precipitacao_negativa_reprova_raw(self):
        with self.assertRaises(RuntimeError) as e:
            nproc.validar_raw([1.0, -5.0, 3.0])
        self.assertIn('negativa', str(e.exception))

    def test_raw_valido_passa(self):
        self.assertTrue(nproc.validar_raw([0.0, 10.0, 500.0]))

    def test_fora_da_faixa_plausivel_reprova(self):
        with self.assertRaises(RuntimeError):
            nproc.validar_raw([1.0, 5000.0])   # acima de PREC_MM_MAX_PLAUSIVEL


# ══════════════════════════════════════════════════════════════════════════
# processar_origem_modelo — fim a fim com dataset sintético (barreira A
# de membros, parsing, conversão, temporal_audit).
# ══════════════════════════════════════════════════════════════════════════

class ProcessarOrigemModeloTestCase(unittest.TestCase):

    def test_happy_path_membros_esperados(self):
        ds = _dataset_sintetico(n_membros=SISTEMA_TESTE.hindcast_members, unidade='mm/day')
        raw_df, temporal_df, meta = npoc.processar_origem_modelo(SISTEMA_TESTE, 2015, 1, ds)
        self.assertEqual(meta['n_membros'], 15)
        self.assertEqual(len(raw_df), 15 * 6)
        self.assertEqual(len(temporal_df), 6)
        self.assertTrue((raw_df['units_original'] == 'mm/day').all())
        self.assertEqual(set(raw_df['lead'].unique()), {1, 2, 3, 4, 5, 6})

    def test_membros_diferentes_do_documentado_falha_barreira_a(self):
        ds = _dataset_sintetico(n_membros=8, unidade='mm/day')   # SPEAR documenta 15, não 8
        with self.assertRaises(RuntimeError) as e:
            npoc.processar_origem_modelo(SISTEMA_TESTE, 2015, 1, ds)
        self.assertIn('barreira A', str(e.exception))
        self.assertIn('15', str(e.exception))

    def test_kg_m2_s_tambem_processa(self):
        # valores pequenos (kg m-2 s-1 típico é ~1e-5) — 5e-5 kg/m2/s * 86400 * 31 dias ≈ 134mm/mês,
        # dentro da faixa plausível.
        ds = _dataset_sintetico(n_membros=SISTEMA_TESTE.hindcast_members, unidade='kg m-2 s-1',
                                 valor_base=0.00003, escala_ruido=0.00004)
        raw_df, _, _ = npoc.processar_origem_modelo(SISTEMA_TESTE, 2015, 1, ds)
        self.assertTrue((raw_df['units_original'] == 'kg m-2 s-1').all())
        self.assertTrue((raw_df['forecast_prec_mm'] >= 0).all())

    def test_temporal_audit_marca_mapeamento_como_assumido_nao_validado(self):
        ds = _dataset_sintetico(n_membros=SISTEMA_TESTE.hindcast_members)
        _, temporal_df, _ = npoc.processar_origem_modelo(SISTEMA_TESTE, 2015, 1, ds)
        self.assertTrue((temporal_df['mapping_status'] == 'ASSUMIDO_NAO_VALIDADO').all())

    def test_s_processar_origem_nunca_calcula_skill(self):
        """Confirma que a função de processamento não importa nem chama
        nada relacionado a métricas/skill/bootstrap (Seção 18/35-S)."""
        import inspect
        src = inspect.getsource(npoc)
        for proibido in ('c3s_skill', 'bootstrap', 'rmse', 'msess', 'brier'):
            self.assertNotIn(proibido, src.lower())


# ══════════════════════════════════════════════════════════════════════════
# nmme_download.py — montagem de URL nunca inventa path/variável.
# ══════════════════════════════════════════════════════════════════════════

class DownloadUrlTestCase(unittest.TestCase):

    def test_url_sem_data_url_template_falha(self):
        s = ncat.sistema_por_nome('NOAA_NCEP', 'CFSv2')   # data_url_template=None
        with self.assertRaises(ValueError) as e:
            ndl.montar_url_iridl(s, 2015, 1, -6.0, -48.0)
        self.assertIn('data_url_template', str(e.exception))

    def test_url_sem_variavel_falha(self):
        s = ncat.sistema_por_nome('NOAA_GFDL', 'GFDL_SPEAR')   # data_url_template ok, precip_variable None
        with self.assertRaises(ValueError) as e:
            ndl.montar_url_iridl(s, 2015, 1, -6.0, -48.0)
        self.assertIn('precip_variable', str(e.exception))

    def test_url_montada_quando_ambos_confirmados(self):
        s = ncat.sistema_por_nome('NOAA_GFDL', 'GFDL_SPEAR')
        url = ndl.montar_url_iridl(s, 2015, 1, -6.0, -48.0, variavel='prec')
        self.assertIn('.prec/', url)
        self.assertIn('data.nc', url)

    def test_verificar_acesso_nao_exige_credencial(self):
        status = ndl.verificar_acesso()
        self.assertFalse(status['credenciais_necessarias'])


# ══════════════════════════════════════════════════════════════════════════
# Seção 17/19 — POC nunca assume cobertura de origem por omissão;
# modelos não homogêneos registrados por critério de disponibilidade.
# ══════════════════════════════════════════════════════════════════════════

class OrigemPocTestCase(unittest.TestCase):

    def test_origem_confirmada_para_modelos_com_periodo_documentado(self):
        canesm5 = ncat.sistema_por_nome('ECCC', 'CanESM5')
        self.assertTrue(npoc.verificar_origem_no_hindcast(canesm5, 2015, 1))

    def test_origem_none_quando_periodo_unconfirmed(self):
        """Após a Rodada 2 (manual NMME3), os 7 sistemas reais do
        catálogo têm hindcast_start/end DOCUMENTED — não há mais nenhum
        UNCONFIRMED real para testar este caminho. Usa um sistema
        sintético com evidence UNCONFIRMED para continuar cobrindo o
        caso "não dá para saber" (Seção 17/19)."""
        from dataclasses import replace
        canesm5 = ncat.sistema_por_nome('ECCC', 'CanESM5')
        sintetico = replace(
            canesm5, centre='TEST', model_name='TESTMODEL',
            evidence={**canesm5.evidence, 'hindcast_start': ncat.UNCONFIRMED,
                      'hindcast_end': ncat.UNCONFIRMED})
        self.assertIsNone(npoc.verificar_origem_no_hindcast(sintetico, 2015, 1))

    def test_origem_false_quando_fora_do_periodo_confirmado(self):
        canesm5 = ncat.sistema_por_nome('ECCC', 'CanESM5')
        self.assertFalse(npoc.verificar_origem_no_hindcast(canesm5, 1980, 1))

    def test_plano_poc_nao_reprova_por_performance_local(self):
        """Nenhum critério de exclusão do plano é baseado em skill/
        performance — só disponibilidade documental (Seção 19). A
        própria função pode CITAR 'skill' só para dizer que nunca
        calcula (ver plano_poc's aviso) — o que não pode existir é uma
        métrica de skill real usada como critério, daí checar termos
        de cálculo (rmse/msess), não a palavra 'skill' isolada."""
        import inspect
        src = inspect.getsource(npoc.plano_poc) + inspect.getsource(npoc.verificar_origem_no_hindcast)
        for proibido in ('rmse', 'msess', 'bootstrap', 'brier'):
            self.assertNotIn(proibido, src.lower())


# ══════════════════════════════════════════════════════════════════════════
# Dry-run / plano — nunca acessa rede.
# ══════════════════════════════════════════════════════════════════════════

class DryRunPlanTestCase(unittest.TestCase):

    def test_plano_lista_os_7_candidatos(self):
        plano = npoc.plano_poc()
        self.assertEqual(plano['n_modelos_candidatos_documentados'], 7)
        self.assertEqual(len(plano['modelos']), 7)

    def test_plano_origem_2015_01(self):
        plano = npoc.plano_poc()
        self.assertEqual(plano['origem_poc'], '2015-01')

    # 8 — dry-run lista candidatos vs executáveis (Seção 13).
    def test_8_plano_lista_executaveis_vs_nao_executaveis(self):
        plano = npoc.plano_poc()
        self.assertIn('modelos_poc_executaveis', plano)
        self.assertIn('modelos_poc_nao_executaveis', plano)
        self.assertEqual(plano['n_modelos_poc_executaveis'], len(plano['modelos_poc_executaveis']))
        self.assertEqual(len(plano['modelos_poc_nao_executaveis']),
                          plano['n_modelos_candidatos_documentados'] - plano['n_modelos_poc_executaveis'])
        for item in plano['modelos_poc_nao_executaveis']:
            self.assertIn(item['motivo'], (ncat.DATA_ACCESS_UNCONFIRMED, ncat.DATA_ACCESS_PARTIAL))

    def test_plano_mostra_periodo_comum_documentado(self):
        plano = npoc.plano_poc()
        self.assertEqual(plano['periodo_comum_documentado'], '1991-2020')

    def test_main_dry_run_nunca_acessa_rede(self):
        from unittest import mock
        with mock.patch.object(ndl, 'baixar_arquivo') as m_baixar, \
             mock.patch('sys.argv', ['nmme_poc.py', '--dry-run-plan']):
            npoc.main()
        m_baixar.assert_not_called()

    def test_executar_poc_real_falha_por_lista_executavel_vazia(self):
        """Com o catálogo atual (nenhum sistema CONFIRMED), o guardrail
        da Seção 13 dispara ANTES do "não implementado" — prova de que
        a checagem está ativa e correta, mesmo com a execução real
        ainda não implementada nesta entrega."""
        from unittest import mock
        with mock.patch('sys.argv', ['nmme_poc.py', '--executar-poc-real']):
            with self.assertRaises(RuntimeError) as e:
                npoc.main()
        self.assertIn('SISTEMAS_POC_EXECUTAVEIS', str(e.exception))

    def test_executar_poc_real_falha_como_nao_implementado_quando_ha_executavel(self):
        """Se algum dia houver >=1 sistema CONFIRMED, o guardrail da
        Seção 13 passa e cai no SystemExit "não implementado" (Seção
        38/50) — comportamento verificado com um catálogo sintético."""
        from unittest import mock
        from dataclasses import replace
        sistema_confirmado = replace(ncat.sistema_por_nome('NOAA_GFDL', 'GFDL_SPEAR'),
                                      data_access_status=ncat.DATA_ACCESS_CONFIRMED,
                                      precip_variable='prec')
        with mock.patch.object(ncat, 'CATALOGO', [sistema_confirmado]), \
             mock.patch('sys.argv', ['nmme_poc.py', '--executar-poc-real']):
            with self.assertRaises(SystemExit):
                npoc.main()

    def test_escrever_saidas_gera_todos_os_artifacts_esperados(self):
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(npoc, 'ARTIFACTS_DIR', Path(tmp)):
                npoc.escrever_saidas()
            for nome in npoc.ARTIFACT_FILENAMES:
                self.assertTrue((Path(tmp) / nome).exists(), f'{nome} não foi gerado')


# ══════════════════════════════════════════════════════════════════════════
# T — produção/dashboard intocado.
# ══════════════════════════════════════════════════════════════════════════

class ProducaoIntocadaTestCase(unittest.TestCase):

    def test_modulos_nao_importam_scripts_de_producao(self):
        import inspect
        for modulo in (ncat, ndl, nproc, npoc):
            src = inspect.getsource(modulo)
            for proibido in ('import update_dashboard', 'import fetch_monthly_data',
                              'import update_indices', 'import gerar_relatorio'):
                self.assertNotIn(proibido, src)

    def test_nenhum_token_real(self):
        import re
        padrao_uuid = re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
                                  r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b')
        for caminho in (ROOT / 'scripts' / 'nmme_catalogo.py', ROOT / 'scripts' / 'nmme_download.py',
                        ROOT / 'scripts' / 'nmme_processar.py', ROOT / 'scripts' / 'nmme_poc.py',
                        WORKFLOW_PATH):
            texto = caminho.read_text(encoding='utf-8')
            self.assertIsNone(padrao_uuid.search(texto), f"possível token real em {caminho.name}")

    def test_nenhum_segredo_hardcoded(self):
        for caminho in (ROOT / 'scripts' / 'nmme_download.py', WORKFLOW_PATH):
            texto = caminho.read_text(encoding='utf-8').lower()
            for termo in ('api_key=', 'token=', 'password=', 'secret='):
                self.assertNotIn(termo, texto)


# ══════════════════════════════════════════════════════════════════════════
# Workflow — default seguro, guardrail do POC real.
# ══════════════════════════════════════════════════════════════════════════

class WorkflowTestCase(unittest.TestCase):

    def setUp(self):
        self.spec = yaml.safe_load(WORKFLOW_PATH.read_text(encoding='utf-8'))
        self.steps = next(iter(self.spec['jobs'].values()))['steps']
        gatilhos = self.spec.get('on', self.spec.get(True))
        self.inputs = gatilhos['workflow_dispatch']['inputs']

    def _step(self, nome_substring):
        for s in self.steps:
            if nome_substring.lower() in s.get('name', '').lower():
                return s
        self.fail(f"nenhum step com nome contendo {nome_substring!r} encontrado")

    def test_trigger_e_workflow_dispatch_sem_cron(self):
        gatilhos = self.spec.get('on', self.spec.get(True))
        self.assertIn('workflow_dispatch', gatilhos)
        self.assertNotIn('schedule', gatilhos)

    def test_dry_run_plan_default_true(self):
        self.assertEqual(self.inputs['dry_run_plan']['default'], 'true')

    def test_executar_poc_real_default_false(self):
        self.assertEqual(self.inputs['executar_poc_real']['default'], 'false')

    def test_confirm_poc_real_default_vazio(self):
        self.assertEqual(self.inputs['confirm_poc_real']['default'], '')

    def test_roda_testes_e_verifica_dashboard(self):
        texto = WORKFLOW_PATH.read_text(encoding='utf-8')
        self.assertIn('unittest discover tests', texto)
        self.assertIn('verificar_dashboard.py', texto)

    def test_mostrar_catalogo_sempre_roda_sem_condicao(self):
        step = self._step('catálogo')
        self.assertNotIn('if', step)

    def test_guardrail_vem_antes_do_setup_python(self):
        nomes = [s.get('name', '') for s in self.steps]
        idx_guardrail = next(i for i, n in enumerate(nomes) if 'guardrail' in n.lower())
        idx_python = next(i for i, n in enumerate(nomes) if 'python' in n.lower())
        self.assertLess(idx_guardrail, idx_python)

    def test_artifact_nao_inclui_netcdf_ou_grib(self):
        texto = WORKFLOW_PATH.read_text(encoding='utf-8')
        self.assertNotIn('.nc\n', texto)
        self.assertNotIn('.grib', texto)

    def test_defaults_do_click_run_nunca_acessam_rede(self):
        defaults = {nome: cfg.get('default', '') for nome, cfg in self.inputs.items()}
        self.assertEqual(defaults['dry_run_plan'], 'true')
        self.assertEqual(defaults['executar_poc_real'], 'false')


if __name__ == '__main__':
    unittest.main()
