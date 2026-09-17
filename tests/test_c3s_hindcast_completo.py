#!/usr/bin/env python3
"""
tests/test_c3s_hindcast_completo.py — regressão da orquestração do
hindcast completo da Fase 2A.3 (scripts/c3s_hindcast_completo.py) e do
workflow .github/workflows/c3s_hindcast_completo.yml. Tudo offline —
nenhum teste baixa nada, abre GRIB real nem precisa de credencial CDS.

As camadas já validadas (abertura/parsing GRIB, extração de ponto,
tabela, download com cache+retry) são mockadas, igual ao padrão já
usado em test_c3s_multiorigem.py — aqui o foco é a orquestração nova:
guardrails de período, dry-run-plan, piloto, barreiras A-H por origem,
auditoria de leakage/temporal em lote e o item E da Seção 31
(confirmação não influencia desenvolvimento).

Roda com:
    python -m unittest tests.test_c3s_hindcast_completo -v
"""

import contextlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import _c3s_utils as cu  # noqa: E402
import c3s_hindcast_completo as h  # noqa: E402

WORKFLOW_PATH = ROOT / '.github' / 'workflows' / 'c3s_hindcast_completo.yml'


# ══════════════════════════════════════════════════════════════════════════
# Guardrail de período (mesmo espírito da Fase 2A.2)
# ══════════════════════════════════════════════════════════════════════════

class GuardrailPeriodoTestCase(unittest.TestCase):

    def test_periodo_default_e_1981_2016(self):
        self.assertEqual(h.ANO_INICIO_HINDCAST, 1981)
        self.assertEqual(h.ANO_FIM_HINDCAST, 2016)

    def test_construir_origens_default_da_432(self):
        origens = h.construir_origens()
        self.assertEqual(len(origens), 432)
        self.assertEqual(origens[0], (1981, 1))
        self.assertEqual(origens[-1], (2016, 12))

    def test_ano_2017_falha(self):
        with self.assertRaises(ValueError) as e:
            h.construir_origens(1981, 2017)
        self.assertIn('2017', str(e.exception))
        self.assertIn('hindcast', str(e.exception).lower())

    def test_ano_antes_de_1981_falha(self):
        with self.assertRaises(ValueError):
            h.construir_origens(1980, 2016)

    def test_ano_ini_maior_que_ano_fim_falha(self):
        with self.assertRaises(ValueError):
            h.construir_origens(2000, 1990)

    def test_init_months_filtra_meses(self):
        origens = h.construir_origens(1991, 1991, meses=[1, 7])
        self.assertEqual(origens, [(1991, 1), (1991, 7)])

    def test_min_anos_treino_e_10(self):
        self.assertEqual(h.MIN_ANOS_TREINO, 10)


# ══════════════════════════════════════════════════════════════════════════
# Dry-run-plan (Seção 37) — nunca acessa o CDS
# ══════════════════════════════════════════════════════════════════════════

class DryRunPlanTestCase(unittest.TestCase):

    def test_plano_default_bate_com_completude_esperada(self):
        """Seção 27: raw completo 64.800, summary 2.592."""
        plano = h.plano_execucao()
        self.assertEqual(plano['n_origens'], 432)
        self.assertEqual(plano['raw_rows_esperadas'], 64800)
        self.assertEqual(plano['summary_rows_esperadas'], 2592)

    def test_plano_warmup_e_avaliacao(self):
        plano = h.plano_execucao()
        self.assertEqual(plano['n_origens_warmup'], 120)      # 1981-1990, 10 anos x 12
        self.assertEqual(plano['n_origens_avaliacao'], 312)   # 1991-2016, 26 anos x 12
        self.assertEqual(plano['n_origens_warmup'] + plano['n_origens_avaliacao'], 432)

    def test_plano_desenvolvimento_e_confirmacao(self):
        plano = h.plano_execucao()
        self.assertEqual(plano['n_origens_desenvolvimento'], 204)   # 1991-2007, 17 anos x 12
        self.assertEqual(plano['n_origens_confirmacao'], 108)       # 2008-2016, 9 anos x 12
        self.assertEqual(plano['n_origens_desenvolvimento'] + plano['n_origens_confirmacao'],
                          plano['n_origens_avaliacao'])

    def test_plano_lista_os_16_artifacts_esperados(self):
        plano = h.plano_execucao()
        self.assertEqual(len(plano['artifacts_esperados']), 16)
        self.assertIn('leakage_audit.csv', plano['artifacts_esperados'])
        self.assertIn('RELATORIO.md', plano['artifacts_esperados'])

    def test_dry_run_nao_chama_download_nem_processar_origem(self):
        with mock.patch.object(h, 'processar_origem_raw') as m_proc, \
             mock.patch.object(h, '_baixar_com_retry_e_cache') as m_baixar:
            h.plano_execucao()
        m_proc.assert_not_called()
        m_baixar.assert_not_called()

    def test_plano_com_periodo_parcial_valido(self):
        plano = h.plano_execucao(1991, 1995)
        self.assertEqual(plano['n_origens'], 5 * 12)

    def test_plano_com_ano_invalido_falha(self):
        with self.assertRaises(ValueError):
            h.plano_execucao(1981, 2020)


# ══════════════════════════════════════════════════════════════════════════
# Piloto (Seção 37/39) — 6 origens fixas
# ══════════════════════════════════════════════════════════════════════════

class PilotoTestCase(unittest.TestCase):

    def test_seis_origens_fixas(self):
        self.assertEqual(h.PILOT_ORIGENS,
                          [(1991, 1), (1991, 7), (2000, 1), (2000, 7), (2010, 1), (2010, 7)])
        self.assertEqual(len(h.PILOT_ORIGENS), 6)

    def test_todas_dentro_do_periodo_hindcast(self):
        for ano, _ in h.PILOT_ORIGENS:
            self.assertLessEqual(h.ANO_INICIO_HINDCAST, ano)
            self.assertLessEqual(ano, h.ANO_FIM_HINDCAST)


# ══════════════════════════════════════════════════════════════════════════
# processar_origem_raw — barreiras A-H (mesmo desenho da Fase 2A.2,
# mockando as camadas já validadas: abertura/validação GRIB, extração
# de ponto, tabela, download).
# ══════════════════════════════════════════════════════════════════════════

def _tabela_valida(origem, leads=None, n_membros=25, valor_mm=100.0):
    leads = leads if leads is not None else h.LEADS
    init_date = pd.Period(origem, 'M')
    linhas = []
    for lead in leads:
        target_month = cu.leadtime_para_mes_alvo(init_date, lead)
        for membro in range(n_membros):
            linhas.append({'local': h.MUNICIPIO, 'target_month': str(target_month), 'lead': lead,
                            'centre': 'ECMWF', 'system': 'SEAS5', 'member': membro,
                            'forecast_prec_mm': valor_mm})
    return pd.DataFrame(linhas)


def _mapa_lead_alvo_valido(origem, leads=None):
    leads = leads if leads is not None else h.LEADS
    init_date = pd.Period(origem, 'M')
    return {lead: str(cu.leadtime_para_mes_alvo(init_date, lead)) for lead in leads}


def _mock_processar_origem_raw(ano=1991, mes=1, n_membros=25, unidade='m s**-1',
                                mapa_lead_alvo=None, tabela=None):
    origem = h._origem_str(ano, mes)
    if mapa_lead_alvo is None:
        mapa_lead_alvo = _mapa_lead_alvo_valido(origem)
    if tabela is None:
        tabela = _tabela_valida(origem, n_membros=n_membros)

    fake_ds = SimpleNamespace(sizes={'number': n_membros})
    ponto_fake = {'latitude': -6.5, 'longitude': -47.5}

    ctx = contextlib.ExitStack()
    ctx.enter_context(mock.patch.object(h, '_baixar_com_retry_e_cache',
                                         return_value=(Path('/fake/cache/x.grib'), True, 0)))
    ctx.enter_context(mock.patch.object(h.poc, 'abrir_e_validar_grib',
                                         return_value=(fake_ds, unidade, 'leadtime_month',
                                                       mapa_lead_alvo, {}, None)))
    ctx.enter_context(mock.patch.object(h.proc, 'extrair_ponto', return_value=ponto_fake))
    ctx.enter_context(mock.patch.object(h.proc, 'dataset_para_tabela', return_value=tabela.copy()))
    return ctx, ano, mes


class ProcessarOrigemRawTestCase(unittest.TestCase):

    def test_happy_path_150_linhas(self):
        ctx, ano, mes = _mock_processar_origem_raw()
        with ctx:
            tabela, meta = h.processar_origem_raw(ano, mes)
        self.assertEqual(len(tabela), 150)
        self.assertEqual(meta['n_membros'], 25)
        self.assertIn('c3s_prec_mm', tabela.columns)
        self.assertIn('lat_grade', tabela.columns)

    def test_a_24_membros_falha(self):
        ctx, ano, mes = _mock_processar_origem_raw(n_membros=24, tabela=_tabela_valida('1991-01', n_membros=24))
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                h.processar_origem_raw(ano, mes)
        self.assertIn('barreira A', str(e.exception))

    def test_a_51_membros_falha(self):
        ctx, ano, mes = _mock_processar_origem_raw(n_membros=51)
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                h.processar_origem_raw(ano, mes)
        self.assertIn('barreira A', str(e.exception))
        self.assertIn('51', str(e.exception))

    def test_b_lead_faltando_falha(self):
        origem = '1991-01'
        mapa = _mapa_lead_alvo_valido(origem, leads=[1, 2, 3, 4, 5])
        ctx, ano, mes = _mock_processar_origem_raw(mapa_lead_alvo=mapa)
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                h.processar_origem_raw(ano, mes)
        self.assertIn('barreira B', str(e.exception))

    def test_c_verifying_month_duplicado_falha(self):
        origem = '1991-01'
        mapa = _mapa_lead_alvo_valido(origem)
        mapa[6] = mapa[5]
        ctx, ano, mes = _mock_processar_origem_raw(mapa_lead_alvo=mapa)
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                h.processar_origem_raw(ano, mes)
        self.assertIn('barreira C', str(e.exception))

    def test_d_verifying_month_incoerente_falha(self):
        origem = '1991-01'
        mapa = _mapa_lead_alvo_valido(origem)
        mapa[6] = '1991-08'
        ctx, ano, mes = _mock_processar_origem_raw(mapa_lead_alvo=mapa)
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                h.processar_origem_raw(ano, mes)
        self.assertIn('barreira D', str(e.exception))

    def test_e_unidade_errada_falha(self):
        ctx, ano, mes = _mock_processar_origem_raw(unidade='m s-1')
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                h.processar_origem_raw(ano, mes)
        self.assertIn('barreira E', str(e.exception))

    def test_f_nan_falha(self):
        origem = '1991-01'
        tabela = _tabela_valida(origem)
        tabela.loc[0, 'forecast_prec_mm'] = float('nan')
        ctx, ano, mes = _mock_processar_origem_raw(tabela=tabela)
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                h.processar_origem_raw(ano, mes)
        self.assertIn('barreira F', str(e.exception))

    def test_f_negativo_falha(self):
        origem = '1991-01'
        tabela = _tabela_valida(origem)
        tabela.loc[0, 'forecast_prec_mm'] = -1.0
        ctx, ano, mes = _mock_processar_origem_raw(tabela=tabela)
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                h.processar_origem_raw(ano, mes)
        self.assertIn('barreira F', str(e.exception))

    def test_g_fora_da_barreira_fisica_falha(self):
        origem = '1991-01'
        tabela = _tabela_valida(origem)
        tabela.loc[0, 'forecast_prec_mm'] = 2000.0
        ctx, ano, mes = _mock_processar_origem_raw(tabela=tabela)
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                h.processar_origem_raw(ano, mes)
        self.assertIn('barreira G', str(e.exception))

    def test_h_numero_de_linhas_errado_falha(self):
        origem = '1991-01'
        tabela = _tabela_valida(origem).iloc[:-1].copy()
        ctx, ano, mes = _mock_processar_origem_raw(tabela=tabela)
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                h.processar_origem_raw(ano, mes)
        self.assertIn('barreira H', str(e.exception))


# ══════════════════════════════════════════════════════════════════════════
# Auditoria temporal em lote
# ══════════════════════════════════════════════════════════════════════════

class TemporalAuditTestCase(unittest.TestCase):

    def test_uma_linha_por_origem_lead(self):
        raw = pd.concat([_tabela_valida('1991-01'), _tabela_valida('1991-02')], ignore_index=True)
        raw['init_date'] = ['1991-01'] * 150 + ['1991-02'] * 150
        raw = raw.rename(columns={'forecast_prec_mm': 'c3s_prec_mm'})
        raw = h._com_periods(raw)
        temporal = h.construir_temporal_audit(raw)
        self.assertEqual(len(temporal), 12)   # 2 origens x 6 leads

    def test_vazio_nao_quebra(self):
        temporal = h.construir_temporal_audit(pd.DataFrame())
        self.assertEqual(len(temporal), 0)

    def test_virada_de_ano(self):
        raw = _tabela_valida('1991-10').rename(columns={'forecast_prec_mm': 'c3s_prec_mm'})
        raw['init_date'] = '1991-10'
        raw = h._com_periods(raw)
        temporal = h.construir_temporal_audit(raw)
        esperado = {1: '1991-10', 2: '1991-11', 3: '1991-12', 4: '1992-01', 5: '1992-02', 6: '1992-03'}
        obtido = dict(zip(temporal['lead'], temporal['verifying_month']))
        self.assertEqual(obtido, esperado)


# ══════════════════════════════════════════════════════════════════════════
# Item E da Seção 31 — confirmação (2008-2016) não influencia
# calibração de desenvolvimento (1991-2007). Teste de integração:
# roda o pipeline completo com e sem os dados de confirmação e confirma
# que climatologia/bias de uma origem de desenvolvimento não mudam.
# ══════════════════════════════════════════════════════════════════════════

def _raw_sintetico(origens, leads, n_membros=25, seed=0):
    rng = np.random.RandomState(seed)
    linhas = []
    for ano, mes in origens:
        init_date = pd.Period(f'{ano}-{mes:02d}', 'M')
        for lead in leads:
            target = init_date + (lead - 1)
            base = 100 + 60 * np.sin(target.month / 12 * 2 * np.pi)
            for membro in range(n_membros):
                val = max(0.0, base + rng.normal(0, 15))
                linhas.append({'local': h.MUNICIPIO, 'init_date': str(init_date), 'target_month': str(target),
                                'lead': lead, 'centre': 'ECMWF', 'system': 'SEAS5', 'member': membro,
                                'c3s_prec_mm': round(val, 3), 'lat_pedida': -6.02, 'lon_pedida': -47.9,
                                'lat_grade': -6.5, 'lon_grade': -47.5, 'distancia_grade_km': 69.4})
    return pd.DataFrame(linhas)


def _chirps_sintetico(ano_ini, ano_fim, seed=1):
    rng = np.random.RandomState(seed)
    linhas = []
    for ano in range(ano_ini, ano_fim + 1):
        for mes in range(1, 13):
            tm = pd.Period(f'{ano}-{mes:02d}', 'M')
            base = 90 + 50 * np.sin(mes / 12 * 2 * np.pi)
            val = max(0.0, base + rng.normal(0, 20))
            linhas.append({'year': ano, 'month': mes, 'target_month': tm, 'chirps_prec_mm': round(val, 2),
                            'source': 'CHIRPS'})
    return pd.DataFrame(linhas)


class ConfirmacaoNaoInfluenciaDesenvolvimentoTestCase(unittest.TestCase):

    def test_bias_e_clim_de_1995_iguais_com_ou_sem_dado_de_2010(self):
        origens = [(a, m) for a in range(1981, 2011) for m in [1]]   # jan de 1981 a 2010, lead 1 só
        raw_str = _raw_sintetico(origens, leads=[1])
        raw = h._com_periods(raw_str)
        chirps_completo = _chirps_sintetico(1981, 2016)
        chirps_truncado_2007 = chirps_completo[chirps_completo['target_month'] <= pd.Period('2007-12', 'M')].copy()

        # também precisamos truncar o raw para não ter origens pós-2007
        raw_ate_2007 = raw[raw['init_date'] <= pd.Period('2007-12', 'M')].copy()

        summary_completo, _ = h.construir_summary_e_calibrado(raw, chirps_completo)
        summary_truncado, _ = h.construir_summary_e_calibrado(raw_ate_2007, chirps_truncado_2007)

        linha_completo = summary_completo[(summary_completo['init_date'] == pd.Period('1995-01', 'M')) &
                                           (summary_completo['lead'] == 1)].iloc[0]
        linha_truncado = summary_truncado[(summary_truncado['init_date'] == pd.Period('1995-01', 'M')) &
                                           (summary_truncado['lead'] == 1)].iloc[0]

        self.assertEqual(linha_completo['climatological_mean'], linha_truncado['climatological_mean'])
        self.assertEqual(linha_completo['bias_mm'], linha_truncado['bias_mm'])
        self.assertEqual(linha_completo['clim_n'], linha_truncado['clim_n'])
        self.assertEqual(linha_completo['bias_training_n'], linha_truncado['bias_training_n'])


# ══════════════════════════════════════════════════════════════════════════
# CHIRPS consolidado — nunca cai para ERA5/CHC-Preliminar/Open-Meteo
# ══════════════════════════════════════════════════════════════════════════

class ChirpsConsolidadoTestCase(unittest.TestCase):

    def test_nao_referencia_fallback_openmeteo(self):
        src = Path(h.__file__).read_text(encoding='utf-8')
        self.assertNotIn('_openmeteo', src)
        self.assertNotIn('buscar_prec_openmeteo', src)

    def test_falha_se_mes_faltando(self):
        df_incompleto = pd.DataFrame({
            'ano': [1981], 'mes': [1], 'prec': [100.0], 'fonte': ['CHIRPS'],
        })
        with mock.patch.object(h, '_buscar_prec_chirps_geom', return_value=df_incompleto):
            with self.assertRaises(RuntimeError) as e:
                h.buscar_chirps_consolidado(1981, 1, 1981, 3)
        self.assertIn('não cobre', str(e.exception).lower())

    def test_falha_se_vazio(self):
        with mock.patch.object(h, '_buscar_prec_chirps_geom', return_value=pd.DataFrame()):
            with self.assertRaises(RuntimeError) as e:
                h.buscar_chirps_consolidado(1981, 1, 1981, 1)
        self.assertIn('indisponível', str(e.exception).lower())

    def test_falha_se_nan(self):
        df = pd.DataFrame({'ano': [1981], 'mes': [1], 'prec': [float('nan')], 'fonte': ['CHIRPS']})
        with mock.patch.object(h, '_buscar_prec_chirps_geom', return_value=df):
            with self.assertRaises(RuntimeError) as e:
                h.buscar_chirps_consolidado(1981, 1, 1981, 1)
        self.assertIn('nan', str(e.exception).lower())

    def test_falha_se_negativo(self):
        df = pd.DataFrame({'ano': [1981], 'mes': [1], 'prec': [-5.0], 'fonte': ['CHIRPS']})
        with mock.patch.object(h, '_buscar_prec_chirps_geom', return_value=df):
            with self.assertRaises(RuntimeError) as e:
                h.buscar_chirps_consolidado(1981, 1, 1981, 1)
        self.assertIn('negativa', str(e.exception).lower())

    def test_sucesso_com_periodo_completo(self):
        df = pd.DataFrame({'ano': [1981, 1981], 'mes': [1, 2], 'prec': [100.0, 120.0], 'fonte': ['CHIRPS'] * 2})
        with mock.patch.object(h, '_buscar_prec_chirps_geom', return_value=df):
            r = h.buscar_chirps_consolidado(1981, 1, 1981, 2)
        self.assertEqual(len(r), 2)
        self.assertIn('chirps_prec_mm', r.columns)


# ══════════════════════════════════════════════════════════════════════════
# Leakage audit — nunca aprova violação
# ══════════════════════════════════════════════════════════════════════════

class LeakageAuditTestCase(unittest.TestCase):

    def test_pipeline_sintetico_nao_produz_violacao(self):
        origens = [(a, m) for a in range(1981, 1993) for m in [1, 6]]
        raw = h._com_periods(_raw_sintetico(origens, leads=[1, 3]))
        chirps = _chirps_sintetico(1981, 2016)
        summary, _ = h.construir_summary_e_calibrado(raw, chirps)
        ens_df = h.construir_ens_df(raw)
        leakage = h.construir_leakage_audit(summary, ens_df, chirps)
        self.assertGreater(len(leakage), 0)
        self.assertTrue((leakage['leakage_status'] == 'OK').all())

    def test_vazio_nao_quebra(self):
        leakage = h.construir_leakage_audit(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        self.assertEqual(len(leakage), 0)


# ══════════════════════════════════════════════════════════════════════════
# Credenciais / produção intocada
# ══════════════════════════════════════════════════════════════════════════

class CredenciaisTestCase(unittest.TestCase):

    def test_nenhum_token_real(self):
        import re
        padrao_uuid = re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
                                  r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b')
        for caminho in (ROOT / 'scripts' / 'c3s_hindcast_completo.py', ROOT / 'scripts' / 'c3s_calibracao.py',
                        ROOT / 'scripts' / 'c3s_skill.py', WORKFLOW_PATH):
            texto = caminho.read_text(encoding='utf-8')
            self.assertIsNone(padrao_uuid.search(texto), f"possível token real em {caminho.name}")

    def test_metadata_sem_campo_de_credencial(self):
        import inspect
        src = inspect.getsource(h.montar_metadata)
        for proibido in ('api_key', 'cdsapi_key', 'token', 'secrets.'):
            self.assertNotIn(proibido, src.lower())

    def test_workflow_nunca_imprime_o_secret(self):
        texto = WORKFLOW_PATH.read_text(encoding='utf-8')
        for linha in texto.split('\n'):
            baixo = linha.lower().strip()
            if 'secrets.cds_api_key' in baixo:
                self.assertFalse(baixo.startswith('echo') and 'cdsapirc' not in baixo,
                                  f"linha suspeita: {linha}")
                self.assertNotIn('cat $home/.cdsapirc', baixo)
                self.assertNotIn('cat ~/.cdsapirc', baixo)


class ProducaoIntocadaTestCase(unittest.TestCase):

    def test_modulo_nao_importa_scripts_de_producao(self):
        import inspect
        src = inspect.getsource(h)
        for proibido in ('import update_dashboard', 'import fetch_monthly_data',
                          'import update_indices', 'import gerar_relatorio'):
            self.assertNotIn(proibido, src)


# ══════════════════════════════════════════════════════════════════════════
# Workflow — manual, sem cron, timeout generoso, if:always() nos passos
# certos, artifacts esperados, nunca publica GRIB/NetCDF.
# ══════════════════════════════════════════════════════════════════════════

class WorkflowTestCase(unittest.TestCase):

    def setUp(self):
        self.spec = yaml.safe_load(WORKFLOW_PATH.read_text(encoding='utf-8'))
        self.steps = next(iter(self.spec['jobs'].values()))['steps']

    def _step(self, nome_substring):
        for s in self.steps:
            if nome_substring.lower() in s.get('name', '').lower():
                return s
        self.fail(f"nenhum step com nome contendo {nome_substring!r} encontrado")

    def test_trigger_e_workflow_dispatch(self):
        gatilhos = self.spec.get('on', self.spec.get(True))
        self.assertIn('workflow_dispatch', gatilhos)

    def test_nao_tem_cron(self):
        gatilhos = self.spec.get('on', self.spec.get(True))
        self.assertNotIn('schedule', gatilhos)

    def test_inputs_esperados(self):
        gatilhos = self.spec.get('on', self.spec.get(True))
        inputs = gatilhos['workflow_dispatch']['inputs']
        for nome in ('start_year', 'end_year', 'init_months', 'dry_run_plan', 'pilot'):
            self.assertIn(nome, inputs)

    def test_defaults_sao_o_periodo_oficial_completo(self):
        gatilhos = self.spec.get('on', self.spec.get(True))
        inputs = gatilhos['workflow_dispatch']['inputs']
        self.assertEqual(inputs['start_year']['default'], '1981')
        self.assertEqual(inputs['end_year']['default'], '2016')

    def test_timeout_generoso(self):
        job = next(iter(self.spec['jobs'].values()))
        self.assertIn('timeout-minutes', job)
        self.assertGreaterEqual(job['timeout-minutes'], 180)

    def test_remocao_de_credencial_tem_if_always(self):
        s = self._step('remover credencial')
        self.assertEqual(s.get('if'), 'always()')

    def test_publicacao_de_artifacts_roda_mesmo_com_falha(self):
        s = self._step('publicar artifacts')
        self.assertIn('always()', str(s.get('if', '')))

    def test_step_principal_nao_tem_continue_on_error(self):
        s = self._step('rodar hindcast completo')
        self.assertNotIn('continue-on-error', s)

    def test_artifact_nao_inclui_grib_ou_nc(self):
        texto = WORKFLOW_PATH.read_text(encoding='utf-8')
        self.assertNotIn('.grib', texto)
        self.assertNotIn('.nc\n', texto)

    def test_artifact_publica_os_16_arquivos_esperados(self):
        texto = WORKFLOW_PATH.read_text(encoding='utf-8')
        for nome in h.ARTIFACT_FILENAMES:
            self.assertIn(nome, texto)

    def test_roda_testes_e_verifica_dashboard(self):
        texto = WORKFLOW_PATH.read_text(encoding='utf-8')
        self.assertIn('unittest discover tests', texto)
        self.assertIn('verificar_dashboard.py', texto)

    def test_tem_passo_de_dry_run(self):
        texto = WORKFLOW_PATH.read_text(encoding='utf-8')
        self.assertIn('--dry-run-plan', texto)


if __name__ == '__main__':
    unittest.main()
