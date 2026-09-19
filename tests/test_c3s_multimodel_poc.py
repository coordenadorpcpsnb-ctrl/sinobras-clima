#!/usr/bin/env python3
"""
tests/test_c3s_multimodel_poc.py — regressão da orquestração do POC
multi-modelo da Fase 2B.1 (scripts/c3s_multimodel_poc.py) e do workflow
.github/workflows/c3s_multimodel_poc.yml. Tudo offline — nenhum teste
baixa nada, abre GRIB real nem precisa de credencial CDS (mesmo padrão
de tests/test_c3s_hindcast_completo.py).

Roda com:
    python -m unittest tests.test_c3s_multimodel_poc -v
"""

import contextlib
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import _c3s_utils as cu  # noqa: E402
import c3s_multimodel_catalogo as mcat  # noqa: E402
import c3s_multimodel_poc as mp  # noqa: E402

WORKFLOW_PATH = ROOT / '.github' / 'workflows' / 'c3s_multimodel_poc.yml'

ECMWF = mcat.sistema_por_nome('ECMWF', 'SEAS5')
DWD = mcat.sistema_por_nome('DWD', 'GCFS2.1')
CMCC = mcat.sistema_por_nome('CMCC', 'SPS3.5')


# ══════════════════════════════════════════════════════════════════════════
# processar_origem_modelo — barreiras (mesmo desenho de
# c3s_hindcast_completo.py::processar_origem_raw), mas com nº de
# membros esperado ESPECÍFICO por modelo (Seção 17).
# ══════════════════════════════════════════════════════════════════════════

def _tabela_valida(sistema, origem, leads=None, n_membros=None, valor_mm=100.0):
    leads = leads if leads is not None else mp.LEADS
    n_membros = n_membros if n_membros is not None else sistema.hindcast_members
    init_date = pd.Period(origem, 'M')
    linhas = []
    for lead in leads:
        target_month = cu.leadtime_para_mes_alvo(init_date, lead)
        for membro in range(n_membros):
            linhas.append({'local': mp.MUNICIPIO, 'target_month': str(target_month), 'lead': lead,
                            'centre': sistema.centro, 'system': sistema.system_name, 'member': membro,
                            'forecast_prec_mm': valor_mm})
    return pd.DataFrame(linhas)


def _mapa_lead_alvo_valido(origem, leads=None):
    leads = leads if leads is not None else mp.LEADS
    init_date = pd.Period(origem, 'M')
    return {lead: str(cu.leadtime_para_mes_alvo(init_date, lead)) for lead in leads}


def _mock_processar_origem_modelo(sistema, ano=1995, mes=1, n_membros=None, unidade='m s**-1',
                                   mapa_lead_alvo=None, tabela=None):
    origem = mp._origem_str(ano, mes)
    n_membros = n_membros if n_membros is not None else sistema.hindcast_members
    if mapa_lead_alvo is None:
        mapa_lead_alvo = _mapa_lead_alvo_valido(origem)
    if tabela is None:
        tabela = _tabela_valida(sistema, origem, n_membros=n_membros)

    fake_ds = SimpleNamespace(sizes={'number': n_membros})
    ponto_fake = {'latitude': -6.5, 'longitude': -47.5}

    ctx = contextlib.ExitStack()
    ctx.enter_context(mock.patch.object(mp, '_baixar_com_retry_e_cache',
                                         return_value=(Path('/fake/cache/x.grib'), True, 0)))
    ctx.enter_context(mock.patch.object(mp.poc, 'abrir_e_validar_grib',
                                         return_value=(fake_ds, unidade, 'leadtime_month',
                                                       mapa_lead_alvo, {}, None)))
    ctx.enter_context(mock.patch.object(mp.proc, 'extrair_ponto', return_value=ponto_fake))
    ctx.enter_context(mock.patch.object(mp.proc, 'dataset_para_tabela', return_value=tabela.copy()))
    return ctx, ano, mes


class ProcessarOrigemModeloTestCase(unittest.TestCase):

    def test_happy_path_ecmwf_25_membros(self):
        ctx, ano, mes = _mock_processar_origem_modelo(ECMWF)
        with ctx:
            tabela, temporal, meta = mp.processar_origem_modelo(ECMWF, ano, mes)
        self.assertEqual(len(tabela), 25 * 6)
        self.assertEqual(meta['n_membros'], 25)
        self.assertIn('grid_distance_km', tabela.columns)
        self.assertIn('units_original', tabela.columns)
        self.assertIn('conversion_applied', tabela.columns)

    # C/17 — membros esperados são ESPECÍFICOS por modelo, nunca 25 fixo
    def test_dwd_espera_30_membros_nao_25(self):
        ctx, ano, mes = _mock_processar_origem_modelo(DWD, n_membros=30)
        with ctx:
            tabela, temporal, meta = mp.processar_origem_modelo(DWD, ano, mes)
        self.assertEqual(meta['n_membros'], 30)
        self.assertEqual(len(tabela), 30 * 6)

    def test_cmcc_espera_40_membros(self):
        ctx, ano, mes = _mock_processar_origem_modelo(CMCC, n_membros=40)
        with ctx:
            tabela, temporal, meta = mp.processar_origem_modelo(CMCC, ano, mes)
        self.assertEqual(meta['n_membros'], 40)

    def test_dwd_com_25_membros_falha_barreira_a(self):
        """DWD espera 30 membros (Seção 17) — receber 25 (o número do
        ECMWF) tem que falhar explicitamente, não passar silenciosamente."""
        ctx, ano, mes = _mock_processar_origem_modelo(DWD, n_membros=25)
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                mp.processar_origem_modelo(DWD, ano, mes)
        self.assertIn('barreira A', str(e.exception))
        self.assertIn('30', str(e.exception))

    # D — mapeamento temporal validado por modelo (lead 1 = mês nominal
    # da inicialização); semântica incoerente falha explicitamente.
    def test_d_target_month_incoerente_falha_para_qualquer_modelo(self):
        origem = '1995-01'
        mapa = _mapa_lead_alvo_valido(origem)
        mapa[6] = '1995-08'   # incoerente com a convenção lead 1 = mês nominal
        ctx, ano, mes = _mock_processar_origem_modelo(DWD, mapa_lead_alvo=mapa)
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                mp.processar_origem_modelo(DWD, ano, mes)
        self.assertIn('barreira D', str(e.exception))

    def test_d_lead_faltando_falha_barreira_b(self):
        origem = '1995-01'
        mapa = _mapa_lead_alvo_valido(origem, leads=[1, 2, 3, 4, 5])
        ctx, ano, mes = _mock_processar_origem_modelo(CMCC, mapa_lead_alvo=mapa)
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                mp.processar_origem_modelo(CMCC, ano, mes)
        self.assertIn('barreira B', str(e.exception))

    def test_temporal_audit_tem_uma_linha_por_lead(self):
        ctx, ano, mes = _mock_processar_origem_modelo(ECMWF)
        with ctx:
            tabela, temporal, meta = mp.processar_origem_modelo(ECMWF, ano, mes)
        self.assertEqual(len(temporal), len(mp.LEADS))
        for coluna in ('centre', 'system_name', 'init_date', 'lead', 'esquema_temporal',
                       'fcmonth', 'target_month', 'nominal_start_date'):
            self.assertIn(coluna, temporal.columns)

    # J — unidade validada por metadata, nunca assumida pelo nome da variável
    def test_j_unidade_fora_do_conjunto_aceito_falha(self):
        ctx, ano, mes = _mock_processar_origem_modelo(ECMWF, unidade='kg m-2 s-1')
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                mp.processar_origem_modelo(ECMWF, ano, mes)
        self.assertIn('barreira E', str(e.exception))

    def test_j_unidade_equivalente_registrada_na_tabela(self):
        ctx, ano, mes = _mock_processar_origem_modelo(ECMWF, unidade='m/s')
        with ctx:
            tabela, temporal, meta = mp.processar_origem_modelo(ECMWF, ano, mes)
        self.assertTrue((tabela['units_original'] == 'm/s').all())
        self.assertTrue((tabela['conversion_applied'] != '').all())

    # K — distância de grade registrada
    def test_k_grade_registrada_requested_e_selected(self):
        ctx, ano, mes = _mock_processar_origem_modelo(ECMWF)
        with ctx:
            tabela, temporal, meta = mp.processar_origem_modelo(ECMWF, ano, mes)
        info = mp.MUNICIPIOS[mp.MUNICIPIO]
        self.assertTrue((tabela['requested_lat'] == info['lat']).all())
        self.assertTrue((tabela['requested_lon'] == info['lon']).all())
        self.assertTrue((tabela['selected_lat'] == -6.5).all())
        self.assertTrue((tabela['selected_lon'] == -47.5).all())
        self.assertGreaterEqual(meta['distancia_grade_km'], 0)

    def test_system_code_e_system_name_registrados(self):
        ctx, ano, mes = _mock_processar_origem_modelo(DWD, n_membros=30)
        with ctx:
            tabela, temporal, meta = mp.processar_origem_modelo(DWD, ano, mes)
        self.assertTrue((tabela['system_code'] == '21').all())
        self.assertTrue((tabela['system_name'] == 'GCFS2.1').all())
        self.assertTrue((tabela['centre'] == 'DWD').all())


# ══════════════════════════════════════════════════════════════════════════
# Dry-run / plano — nunca acessa o CDS.
# ══════════════════════════════════════════════════════════════════════════

class DryRunPlanTestCase(unittest.TestCase):

    def test_plano_lista_os_4_modelos(self):
        plano = mp.plano_poc()
        self.assertEqual(plano['n_modelos'], 4)
        self.assertEqual(plano['n_origens'], 6)
        self.assertEqual(plano['requests_cds_previstos'], 24)

    def test_plano_periodo_comum_e_1993_2016(self):
        plano = mp.plano_poc()
        self.assertEqual(plano['periodo_comum_hindcast'], '1993-2016')

    def test_plano_nao_acessa_cds(self):
        with mock.patch.object(mp, '_baixar_com_retry_e_cache') as m_baixar, \
             mock.patch.object(mp.dl, 'baixar') as m_dl_baixar:
            mp.plano_poc()
        m_baixar.assert_not_called()
        m_dl_baixar.assert_not_called()

    def test_escrever_catalogo_apenas_nao_acessa_cds(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(mp, 'ARTIFACTS_DIR', Path(tmp)), \
                 mock.patch.object(mp, '_baixar_com_retry_e_cache') as m_baixar:
                mp.escrever_catalogo_apenas()
            m_baixar.assert_not_called()
            self.assertTrue((Path(tmp) / 'c3s_multimodel_catalog.csv').exists())
            self.assertTrue((Path(tmp) / 'c3s_multimodel_common_period.json').exists())

    def test_main_dry_run_default_nunca_acessa_cds(self):
        """Clicar sem mexer em nada (nenhum --executar-poc-real) tem
        que cair no caminho dry-run, mesmo sem passar --dry-run-plan
        explicitamente (Seção 31 — default seguro)."""
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(mp, 'ARTIFACTS_DIR', Path(tmp)), \
                 mock.patch.object(mp, '_baixar_com_retry_e_cache') as m_baixar, \
                 mock.patch('sys.argv', ['c3s_multimodel_poc.py']):
                mp.main()
            m_baixar.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════
# Produção intocada (Seção 27-M / 33)
# ══════════════════════════════════════════════════════════════════════════

class ProducaoIntocadaTestCase(unittest.TestCase):

    def test_modulos_nao_importam_scripts_de_producao(self):
        import inspect
        for modulo in (mp, mcat):
            src = inspect.getsource(modulo)
            for proibido in ('import update_dashboard', 'import fetch_monthly_data',
                              'import update_indices', 'import gerar_relatorio'):
                self.assertNotIn(proibido, src)

    def test_nenhum_token_real(self):
        import re
        padrao_uuid = re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
                                  r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b')
        for caminho in (ROOT / 'scripts' / 'c3s_multimodel_poc.py', ROOT / 'scripts' / 'c3s_multimodel.py',
                        ROOT / 'scripts' / 'c3s_multimodel_catalogo.py', WORKFLOW_PATH):
            texto = caminho.read_text(encoding='utf-8')
            self.assertIsNone(padrao_uuid.search(texto), f"possível token real em {caminho.name}")


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

    def _indice(self, nome_substring):
        for i, s in enumerate(self.steps):
            if nome_substring.lower() in s.get('name', '').lower():
                return i
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

    def test_defaults_do_click_run_nunca_acessam_cds(self):
        defaults = {nome: cfg.get('default', '') for nome, cfg in self.inputs.items()}
        self.assertEqual(defaults['dry_run_plan'], 'true')
        self.assertEqual(defaults['executar_poc_real'], 'false')

    def test_guardrail_vem_antes_do_setup_python(self):
        self.assertLess(self._indice('guardrail'), self._indice('set up python'))
        self.assertLess(self._indice('guardrail'), self._indice('criar ~/.cdsapirc'))

    def test_guardrail_nao_referencia_script_python_nem_cdsapi(self):
        step = self._step('guardrail')
        self.assertNotIn('c3s_multimodel_poc.py', step['run'])
        self.assertNotIn('cdsapi', step['run'].lower())

    def test_mostrar_catalogo_sempre_roda_sem_condicao(self):
        step = self._step('mostrar catálogo')
        self.assertNotIn('if', step)

    def _rodar_guardrail_bash(self, dry_run_plan, executar_poc_real, confirm):
        step = self._step('guardrail')
        condicao_ativa = (dry_run_plan != 'true') and (executar_poc_real == 'true')
        if not condicao_ativa:
            return None
        script = step['run'].replace("${{ inputs.confirm_poc_real }}", confirm)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as tmp:
            summary_path = tmp.name
        try:
            env = dict(os.environ, GITHUB_STEP_SUMMARY=summary_path)
            return subprocess.run(['bash', '-c', script], capture_output=True, text=True, env=env)
        finally:
            Path(summary_path).unlink(missing_ok=True)

    def test_default_nunca_dispara_guardrail(self):
        r = self._rodar_guardrail_bash(dry_run_plan='true', executar_poc_real='false', confirm='')
        self.assertIsNone(r)

    def test_poc_real_sem_confirmacao_falha(self):
        r = self._rodar_guardrail_bash(dry_run_plan='false', executar_poc_real='true', confirm='')
        self.assertIsNotNone(r)
        self.assertNotEqual(r.returncode, 0)

    def test_poc_real_confirmacao_errada_falha(self):
        r = self._rodar_guardrail_bash(dry_run_plan='false', executar_poc_real='true', confirm='sim')
        self.assertIsNotNone(r)
        self.assertNotEqual(r.returncode, 0)

    def test_poc_real_com_confirmacao_correta_libera(self):
        r = self._rodar_guardrail_bash(dry_run_plan='false', executar_poc_real='true',
                                        confirm='EXECUTAR_POC_MULTIMODEL')
        self.assertIsNotNone(r)
        self.assertEqual(r.returncode, 0)

    def test_roda_testes_e_verifica_dashboard(self):
        texto = WORKFLOW_PATH.read_text(encoding='utf-8')
        self.assertIn('unittest discover tests', texto)
        self.assertIn('verificar_dashboard.py', texto)

    def test_artifact_nao_inclui_grib_ou_nc(self):
        texto = WORKFLOW_PATH.read_text(encoding='utf-8')
        self.assertNotIn('.grib', texto)
        self.assertNotIn('.nc\n', texto)

    def test_artifact_publica_os_arquivos_esperados(self):
        texto = WORKFLOW_PATH.read_text(encoding='utf-8')
        for nome in mp.ARTIFACT_FILENAMES:
            self.assertIn(nome, texto)

    def test_remocao_de_credencial_tem_if_always(self):
        s = self._step('remover credencial')
        self.assertEqual(s.get('if'), 'always()')


if __name__ == '__main__':
    unittest.main()
