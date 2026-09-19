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
import os
import subprocess
import sys
import tempfile
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
# Piloto (correção pós-run 35260471652) — pilot LONGITUDINAL, 72
# origens (todos jan/jul de 1981-2016), não mais 6 origens isoladas.
# ══════════════════════════════════════════════════════════════════════════

class PilotoTestCase(unittest.TestCase):

    def test_setenta_e_duas_origens(self):
        self.assertEqual(len(h.PILOT_ORIGENS), 72)

    def test_origens_sao_exatamente_todos_jan_jul_1981_2016(self):
        esperado = [(ano, mes) for ano in range(1981, 2017) for mes in (1, 7)]
        self.assertEqual(h.PILOT_ORIGENS, esperado)

    def test_somente_meses_1_e_7(self):
        meses = {mes for _, mes in h.PILOT_ORIGENS}
        self.assertEqual(meses, {1, 7})

    def test_anos_vao_de_1981_a_2016(self):
        anos = sorted({ano for ano, _ in h.PILOT_ORIGENS})
        self.assertEqual(anos[0], 1981)
        self.assertEqual(anos[-1], 2016)
        self.assertEqual(len(anos), 36)

    def test_todas_dentro_do_periodo_hindcast(self):
        for ano, _ in h.PILOT_ORIGENS:
            self.assertLessEqual(h.ANO_INICIO_HINDCAST, ano)
            self.assertLessEqual(ano, h.ANO_FIM_HINDCAST)

    def test_raw_esperado_10800(self):
        self.assertEqual(len(h.PILOT_ORIGENS) * h.N_MEMBROS_ESPERADO * len(h.LEADS), 10800)

    def test_summary_esperado_432(self):
        self.assertEqual(len(h.PILOT_ORIGENS) * len(h.LEADS), 432)

    def test_forecasts_avaliacao_esperados_312(self):
        self.assertEqual(h.PILOT_FORECASTS_AVALIACAO_ESPERADOS, 312)

    def test_primeiro_ano_avaliado_1991_tem_10_anos_anteriores_do_mesmo_mes(self):
        """Para 1991-01 (jan) e 1991-07 (jul), os 10 anos de treino
        (1981-1990) devem estar todos presentes no pilot — condição
        necessária para bias_training_n>=MIN_ANOS_TREINO no primeiro
        ano avaliado (defeito do run 35260471652: pilot antigo não
        tinha NENHUM ano anterior carregado)."""
        anos_jan_pilot = {ano for ano, mes in h.PILOT_ORIGENS if mes == 1}
        anos_jul_pilot = {ano for ano, mes in h.PILOT_ORIGENS if mes == 7}
        anos_treino_esperados = set(range(1981, 1991))
        self.assertTrue(anos_treino_esperados.issubset(anos_jan_pilot))
        self.assertTrue(anos_treino_esperados.issubset(anos_jul_pilot))


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


def _chirps_sintetico_intervalo(target_ini, target_fim, seed=1):
    """Como _chirps_sintetico, mas cobre exatamente o intervalo
    [target_ini, target_fim] (pandas.Period) — pode incluir um ano
    parcial no fim/início, do mesmo jeito que buscar_chirps_consolidado
    cobre de verdade (correção pós-run oficial 35353196015)."""
    target_ini = pd.Period(target_ini, 'M')
    target_fim = pd.Period(target_fim, 'M')
    rng = np.random.RandomState(seed)
    linhas = []
    for tm in pd.period_range(target_ini, target_fim, freq='M'):
        base = 90 + 50 * np.sin(tm.month / 12 * 2 * np.pi)
        val = max(0.0, base + rng.normal(0, 20))
        linhas.append({'year': tm.year, 'month': tm.month, 'target_month': tm, 'chirps_prec_mm': round(val, 2),
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

def _ano_de_ini(ini):
    """ini no formato MM/DD/AAAA (o que intervalo_mensal_chirps produz)."""
    return int(ini.split('/')[-1])


def _mes_de_ini(ini):
    return int(ini.split('/')[0])


def _mes_de_fim(fim):
    return int(fim.split('/')[0])


def _fake_ano_completo(ano, valor_base=100.0):
    return pd.DataFrame({'ano': [ano] * 12, 'mes': list(range(1, 13)),
                          'prec': [valor_base + m for m in range(1, 13)], 'fonte': ['CHIRPS'] * 12})


def _fake_bloco(ano, mes_ini=1, mes_fim=12, valor_base=100.0):
    meses = list(range(mes_ini, mes_fim + 1))
    return pd.DataFrame({'ano': [ano] * len(meses), 'mes': meses,
                          'prec': [valor_base + m for m in meses], 'fonte': ['CHIRPS'] * len(meses)})


def _espiao_generico(ini, fim, geom, rotulo=''):
    """Devolve exatamente os meses pedidos (mes_ini-mes_fim do ano) —
    ao contrário de _fake_ano_completo (sempre 12 meses), este espião
    respeita blocos parciais (borda do intervalo derivado), como o
    ClimateSERV real faria."""
    return _fake_bloco(_ano_de_ini(ini), _mes_de_ini(ini), _mes_de_fim(fim))


class ChirpsConsolidadoTestCase(unittest.TestCase):
    """Correção pós-pilot real (run 35257900850): buscar 1981-2016
    numa request só estourou o ClimateSERV. Agora em blocos anuais —
    ver Seção 12 (itens A-M) e Seção 13 (regressão) da tarefa.

    Correção pós-run oficial 35353196015: target_ini/target_fim agora
    são DERIVADOS (intervalo_targets_necessario), nunca fixados — o
    primeiro/último ano do intervalo pode ser parcial (Seção 1-4)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self._tmp.name)
        self._patches = [
            mock.patch.object(h, 'ARTIFACTS_DIR', tmp_path),
            mock.patch.object(h, 'CHIRPS_BLOCOS_DIR', tmp_path / '_chirps_blocos'),
            mock.patch.object(h, 'CHIRPS_CHECKPOINT_PATH', tmp_path / 'chirps_checkpoint.json'),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: [p.stop() for p in self._patches])

    # L — nunca referencia fallback ERA5/CHC-Preliminar/Open-Meteo
    def test_l_nao_referencia_fallback_openmeteo(self):
        src = Path(h.__file__).read_text(encoding='utf-8')
        self.assertNotIn('_openmeteo', src)
        self.assertNotIn('buscar_prec_openmeteo', src)
        self.assertNotIn('chc_preliminar', src.lower())

    # M — CHIRPS continua sendo municipal/ponto de São Bento (não zonal/envelope)
    def test_m_usa_ponto_municipal_sao_bento(self):
        chamadas = []

        def _espiao(ini, fim, geom, rotulo=''):
            chamadas.append(geom)
            return _fake_ano_completo(_ano_de_ini(ini))

        with mock.patch.object(h, '_buscar_prec_chirps_geom', side_effect=_espiao):
            h.buscar_chirps_consolidado('1981-01', '1981-12', sleep_fn=lambda s: None)
        info = h.MUNICIPIOS[h.MUNICIPIO]
        geom_esperado = h._geometria_ponto(info['lat'], info['lon'])
        self.assertEqual(chamadas[0], geom_esperado)

    # A — 1981-2016 gera exatamente 36 blocos anuais
    def test_a_36_blocos_anuais(self):
        with mock.patch.object(h, '_buscar_prec_chirps_geom',
                                side_effect=lambda ini, fim, geom, rotulo='': _fake_ano_completo(
                                    _ano_de_ini(ini))) as m:
            h.buscar_chirps_consolidado('1981-01', '2016-12', sleep_fn=lambda s: None)
        self.assertEqual(m.call_count, 36)

    # B — cada bloco cheio pede jan->dez do mesmo ano
    def test_b_bloco_pede_jan_a_dez_do_mesmo_ano(self):
        capturado = {}

        def _espiao(ini, fim, geom, rotulo=''):
            capturado[_ano_de_ini(ini)] = (ini, fim)
            return _fake_ano_completo(_ano_de_ini(ini))

        with mock.patch.object(h, '_buscar_prec_chirps_geom', side_effect=_espiao):
            h.buscar_chirps_consolidado('1995-01', '1995-12', sleep_fn=lambda s: None)
        ini, fim = capturado[1995]
        self.assertEqual(ini, '01/01/1995')
        self.assertEqual(fim, '12/31/1995')

    # C — ano bissexto é tratado corretamente (o bloco sempre vai até 31/12,
    # então fevereiro — bissexto ou não — cai inteiro dentro do intervalo)
    def test_c_ano_bissexto_intervalo_ate_31_12(self):
        capturado = {}

        def _espiao(ini, fim, geom, rotulo=''):
            capturado[_ano_de_ini(ini)] = (ini, fim)
            return _fake_ano_completo(_ano_de_ini(ini))

        with mock.patch.object(h, '_buscar_prec_chirps_geom', side_effect=_espiao):
            h.buscar_chirps_consolidado('2016-01', '2016-12', sleep_fn=lambda s: None)   # 2016 é bissexto
        ini, fim = capturado[2016]
        self.assertEqual(ini, '01/01/2016')
        self.assertEqual(fim, '12/31/2016')
        # a função de baixo nível já testada (test_c3s.py) usa monthrange —
        # confirmamos aqui só que fevereiro bissexto is not special-cased
        # incorretamente num intervalo mensal isolado
        _, fim_fev = cu.intervalo_mensal_chirps(2016, 2, 2016, 2)
        self.assertEqual(fim_fev, '02/29/2016')

    # D — bloco com 11 meses falha
    def test_d_bloco_com_11_meses_falha(self):
        df = _fake_ano_completo(1990).iloc[:-1]   # remove dezembro
        with self.assertRaises(RuntimeError) as e:
            h._validar_bloco_chirps(df, 1990)
        self.assertIn('incompleto', str(e.exception).lower())

    # E — bloco com mês duplicado falha
    def test_e_bloco_com_mes_duplicado_falha(self):
        df = pd.concat([_fake_ano_completo(1990), _fake_ano_completo(1990).iloc[[0]]], ignore_index=True)
        with self.assertRaises(RuntimeError) as e:
            h._validar_bloco_chirps(df, 1990)
        self.assertIn('duplicado', str(e.exception).lower())

    # F — bloco com NaN falha
    def test_f_bloco_com_nan_falha(self):
        df = _fake_ano_completo(1990)
        df.loc[0, 'prec'] = float('nan')
        with self.assertRaises(RuntimeError) as e:
            h._validar_bloco_chirps(df, 1990)
        self.assertIn('nan', str(e.exception).lower())

    # G — bloco com valor negativo falha
    def test_g_bloco_com_negativo_falha(self):
        df = _fake_ano_completo(1990)
        df.loc[0, 'prec'] = -1.0
        with self.assertRaises(RuntimeError) as e:
            h._validar_bloco_chirps(df, 1990)
        self.assertIn('negativa', str(e.exception).lower())

    # H — retry chega no máximo a 3 tentativas
    def test_h_retry_no_maximo_3_tentativas(self):
        sleeps = []
        with mock.patch.object(h, '_buscar_prec_chirps_geom', return_value=pd.DataFrame()) as m:
            with self.assertRaises(RuntimeError):
                h._buscar_chirps_ano(1990, sleep_fn=lambda s: sleeps.append(s))
        self.assertEqual(m.call_count, h.CHIRPS_MAX_TENTATIVAS)
        self.assertEqual(len(sleeps), h.CHIRPS_MAX_TENTATIVAS - 1)
        self.assertEqual(sleeps, [5, 15])

    def test_h_retry_sucesso_apos_falhas(self):
        respostas = [pd.DataFrame(), pd.DataFrame(), _fake_ano_completo(1990)]
        with mock.patch.object(h, '_buscar_prec_chirps_geom', side_effect=respostas):
            df = h._buscar_chirps_ano(1990, sleep_fn=lambda s: None)
        self.assertEqual(len(df), 12)

    # I — falha em um ano informa explicitamente o ano
    def test_i_falha_informa_o_ano_explicitamente(self):
        with mock.patch.object(h, '_buscar_prec_chirps_geom', return_value=pd.DataFrame()):
            with self.assertRaises(RuntimeError) as e:
                h._buscar_chirps_ano(1999, sleep_fn=lambda s: None)
        self.assertIn('1999', str(e.exception))

    def test_i_falha_de_um_ano_e_registrada_no_checkpoint(self):
        def _espiao(ini, fim, geom, rotulo=''):
            ano = _ano_de_ini(ini)
            if ano == 1983:
                return pd.DataFrame()
            return _fake_ano_completo(ano)

        with mock.patch.object(h, '_buscar_prec_chirps_geom', side_effect=_espiao):
            with self.assertRaises(RuntimeError) as e:
                h.buscar_chirps_consolidado('1981-01', '1985-12', sleep_fn=lambda s: None)
        self.assertIn('1983', str(e.exception))
        estado = h._carregar_chirps_checkpoint()
        self.assertIn('1983', estado['anos_falhados'])
        self.assertEqual(estado['anos_concluidos'], ['1981', '1982'])

    # J — 36 blocos válidos geram 432 meses
    def test_j_36_blocos_geram_432_meses(self):
        with mock.patch.object(h, '_buscar_prec_chirps_geom',
                                side_effect=lambda ini, fim, geom, rotulo='': _fake_ano_completo(
                                    _ano_de_ini(ini))):
            df = h.buscar_chirps_consolidado('1981-01', '2016-12', sleep_fn=lambda s: None)
        self.assertEqual(len(df), 432)

    # K — sequência final é contínua de 1981-01 a 2016-12
    def test_k_sequencia_final_continua(self):
        with mock.patch.object(h, '_buscar_prec_chirps_geom',
                                side_effect=lambda ini, fim, geom, rotulo='': _fake_ano_completo(
                                    _ano_de_ini(ini))):
            df = h.buscar_chirps_consolidado('1981-01', '2016-12', sleep_fn=lambda s: None)
        esperado = list(pd.period_range('1981-01', '2016-12', freq='M'))
        self.assertEqual(list(df['target_month']), esperado)

    def test_validacao_final_detecta_lacuna(self):
        df = _fake_ano_completo(1981)
        df['target_month'] = pd.PeriodIndex(pd.to_datetime(dict(year=df.ano, month=df.mes, day=1)), freq='M')
        df = df.rename(columns={'prec': 'chirps_prec_mm'})
        with self.assertRaises(RuntimeError) as e:
            h._validar_consolidado_final(df, '1981-01', '1982-12')   # só 1981 processado, falta 1982
        self.assertIn('esperado', str(e.exception).lower())

    # cache local dos blocos + checkpoint — dentro do mesmo processo
    def test_bloco_e_salvo_localmente_por_ano(self):
        with mock.patch.object(h, '_buscar_prec_chirps_geom',
                                side_effect=lambda ini, fim, geom, rotulo='': _fake_ano_completo(
                                    _ano_de_ini(ini))):
            h.buscar_chirps_consolidado('1981-01', '1983-12', sleep_fn=lambda s: None)
        salvos = sorted(p.name for p in h.CHIRPS_BLOCOS_DIR.glob('*.csv'))
        self.assertEqual(salvos, ['chirps_1981.csv', 'chirps_1982.csv', 'chirps_1983.csv'])

    def test_ano_ja_concluido_no_checkpoint_nao_e_rebuscado(self):
        chamados = []

        def _espiao(ini, fim, geom, rotulo=''):
            ano = _ano_de_ini(ini)
            chamados.append(ano)
            return _fake_ano_completo(ano)

        with mock.patch.object(h, '_buscar_prec_chirps_geom', side_effect=_espiao):
            h.buscar_chirps_consolidado('1981-01', '1983-12', sleep_fn=lambda s: None)   # 1ª vez: busca tudo
            chamados.clear()
            df2 = h.buscar_chirps_consolidado('1981-01', '1983-12', sleep_fn=lambda s: None)   # 2ª: em cache
        self.assertEqual(chamados, [])
        self.assertEqual(len(df2), 36)

    # Seção 13 — regressão direta do bug real: uma request para o
    # período inteiro (36 anos) falha (reproduz o ClimateSERV real);
    # blocos anuais continuam funcionando.
    def test_regressao_request_unica_36_anos_falha_blocos_anuais_funcionam(self):
        def _simula_climateserv_real(ini, fim, geom, rotulo=''):
            from datetime import datetime
            dias = (datetime.strptime(fim, '%m/%d/%Y') - datetime.strptime(ini, '%m/%d/%Y')).days
            if dias > 400:   # request multi-anual — exatamente o que quebrou na execução real
                return pd.DataFrame()   # "resposta vazia ou sem dados"
            return _fake_ano_completo(_ano_de_ini(ini))

        with mock.patch.object(h, '_buscar_prec_chirps_geom', side_effect=_simula_climateserv_real):
            # a implementação ANTIGA (uma request para o período inteiro) teria falhado:
            ini_completo, fim_completo = cu.intervalo_mensal_chirps(1981, 1, 2016, 12)
            resposta_request_unica = h._buscar_prec_chirps_geom(ini_completo, fim_completo, None)
            self.assertTrue(resposta_request_unica.empty, "pré-condição: request de 36 anos deve falhar")

            # a implementação NOVA (blocos anuais) funciona sob a mesma condição
            df = h.buscar_chirps_consolidado('1981-01', '1985-12', sleep_fn=lambda s: None)
        self.assertEqual(len(df), 60)
        self.assertFalse(df['chirps_prec_mm'].isna().any())

    # ══════════════════════════════════════════════════════════════════
    # Correção pós-run oficial 35353196015 (Seção 1-4, 18: B/C/F) —
    # borda parcial do intervalo (último ano com < 12 meses).
    # ══════════════════════════════════════════════════════════════════

    # Item 4 — para o último ano parcial (2017, jan-mai), busca só os
    # meses necessários, nunca o ano inteiro.
    def test_ultimo_ano_parcial_busca_so_os_meses_necessarios(self):
        capturado = {}

        def _espiao(ini, fim, geom, rotulo=''):
            capturado[_ano_de_ini(ini)] = (ini, fim)
            return _espiao_generico(ini, fim, geom, rotulo)

        with mock.patch.object(h, '_buscar_prec_chirps_geom', side_effect=_espiao):
            df = h.buscar_chirps_consolidado('2016-01', '2017-05', sleep_fn=lambda s: None)
        ini, fim = capturado[2017]
        self.assertEqual(ini, '01/01/2017')
        self.assertEqual(fim, '05/31/2017')
        self.assertEqual(len(df), 12 + 5)

    # simetria: primeiro ano parcial também busca só os meses necessários
    def test_primeiro_ano_parcial_busca_so_os_meses_necessarios(self):
        capturado = {}

        def _espiao(ini, fim, geom, rotulo=''):
            capturado[_ano_de_ini(ini)] = (ini, fim)
            return _espiao_generico(ini, fim, geom, rotulo)

        with mock.patch.object(h, '_buscar_prec_chirps_geom', side_effect=_espiao):
            df = h.buscar_chirps_consolidado('1981-07', '1982-12', sleep_fn=lambda s: None)
        ini, fim = capturado[1981]
        self.assertEqual(ini, '07/01/1981')
        self.assertEqual(fim, '12/31/1981')
        self.assertEqual(len(df), 6 + 12)

    # Item B/C da correção — cobertura dinâmica: intervalo derivado do
    # hindcast oficial (1981-2016, todos os meses) produz 437 meses,
    # 1981-01 a 2017-05.
    def test_b_intervalo_do_full_oficial_produz_437_meses_ate_2017_05(self):
        origens = h.construir_origens(h.ANO_INICIO_HINDCAST, h.ANO_FIM_HINDCAST, None)
        target_ini, target_fim = h.intervalo_targets_necessario(origens, h.LEADS)
        with mock.patch.object(h, '_buscar_prec_chirps_geom', side_effect=_espiao_generico):
            df = h.buscar_chirps_consolidado(target_ini, target_fim, sleep_fn=lambda s: None)
        self.assertEqual(len(df), 437)
        self.assertEqual(df['target_month'].min(), pd.Period('1981-01', 'M'))
        self.assertEqual(df['target_month'].max(), pd.Period('2017-05', 'M'))

    # F — teste obrigatório de borda (Seção 7/18): 2016-12 lead 6 →
    # 2017-05, e esse mês existe de verdade no CHIRPS consolidado.
    def test_f_2016_12_lead6_target_2017_05_existe_no_consolidado(self):
        target_ini, target_fim = h.intervalo_targets_necessario([(2016, 12)], h.LEADS)
        with mock.patch.object(h, '_buscar_prec_chirps_geom', side_effect=_espiao_generico):
            df = h.buscar_chirps_consolidado(target_ini, target_fim, sleep_fn=lambda s: None)
        self.assertIn(pd.Period('2017-05', 'M'), set(df['target_month']))

    def test_bloco_parcial_e_salvo_com_nome_distinto(self):
        with mock.patch.object(h, '_buscar_prec_chirps_geom', side_effect=_espiao_generico):
            h.buscar_chirps_consolidado('2016-01', '2017-05', sleep_fn=lambda s: None)
        salvos = sorted(p.name for p in h.CHIRPS_BLOCOS_DIR.glob('*.csv'))
        self.assertEqual(salvos, ['chirps_2016.csv', 'chirps_2017_01_05.csv'])

    def test_bloco_parcial_incompleto_falha(self):
        df = _fake_bloco(2017, 1, 4)   # falta maio
        with self.assertRaises(RuntimeError) as e:
            h._validar_bloco_chirps(df, 2017, mes_ini=1, mes_fim=5)
        self.assertIn('incompleto', str(e.exception).lower())

    def test_target_fim_menor_que_target_ini_falha(self):
        with self.assertRaises(ValueError):
            h.buscar_chirps_consolidado('2017-05', '2016-01', sleep_fn=lambda s: None)


# ══════════════════════════════════════════════════════════════════════════
# intervalo_targets_necessario — deriva a cobertura observacional
# necessária a partir de origens×leads, nunca fixada manualmente
# (correção pós-run oficial 35353196015, Seção 1/2/6/18).
# ══════════════════════════════════════════════════════════════════════════

class IntervaloTargetsNecessarioTestCase(unittest.TestCase):

    # A — FULL gera target máximo 2017-05
    def test_a_full_gera_target_maximo_2017_05(self):
        origens = h.construir_origens(h.ANO_INICIO_HINDCAST, h.ANO_FIM_HINDCAST, None)
        _, target_fim = h.intervalo_targets_necessario(origens, h.LEADS)
        self.assertEqual(target_fim, pd.Period('2017-05', 'M'))

    def test_full_piso_e_1981_01(self):
        origens = h.construir_origens(h.ANO_INICIO_HINDCAST, h.ANO_FIM_HINDCAST, None)
        target_ini, _ = h.intervalo_targets_necessario(origens, h.LEADS)
        self.assertEqual(target_ini, pd.Period('1981-01', 'M'))

    # C — cobertura contém 437 meses
    def test_c_full_cobre_437_meses(self):
        origens = h.construir_origens(h.ANO_INICIO_HINDCAST, h.ANO_FIM_HINDCAST, None)
        target_ini, target_fim = h.intervalo_targets_necessario(origens, h.LEADS)
        self.assertEqual(len(pd.period_range(target_ini, target_fim, freq='M')), 437)

    def test_pilot_continua_432_meses(self):
        """O pilot longitudinal (jan/jul, até 2016-07) nunca alcançou a
        virada de ano mesmo com lead 6 (2016-07+5=2016-12) — cobertura
        inalterada, prova de que a correção não afeta o pilot já
        validado em execução real (run 35340386904)."""
        target_ini, target_fim = h.intervalo_targets_necessario(h.PILOT_ORIGENS, h.LEADS)
        self.assertEqual(target_ini, pd.Period('1981-01', 'M'))
        self.assertEqual(target_fim, pd.Period('2016-12', 'M'))
        self.assertEqual(len(pd.period_range(target_ini, target_fim, freq='M')), 432)

    def test_execucao_parcial_mantem_piso_em_1981(self):
        """Mesmo pedindo só origens de 1991-1995, o piso nunca é
        anterior a ANO_INICIO_HINDCAST — climatologia/bias de qualquer
        origem avaliada pode precisar de histórico desde o início do
        hindcast homogêneo, não só das origens desta execução."""
        origens = h.construir_origens(1991, 1995, None)
        target_ini, target_fim = h.intervalo_targets_necessario(origens, h.LEADS)
        self.assertEqual(target_ini, pd.Period('1981-01', 'M'))
        self.assertEqual(target_fim, pd.Period('1996-05', 'M'))   # 1995-12 + 5

    # F — teste obrigatório de borda (Seção 7/18)
    def test_f_2016_12_lead6_produz_target_2017_05(self):
        _, target_fim = h.intervalo_targets_necessario([(2016, 12)], h.LEADS)
        self.assertEqual(target_fim, pd.Period('2017-05', 'M'))

    def test_2016_08_lead6_produz_target_2017_01(self):
        _, target_fim = h.intervalo_targets_necessario([(2016, 8)], h.LEADS)
        self.assertEqual(target_fim, pd.Period('2017-01', 'M'))

    def test_lista_vazia_devolve_piso_nos_dois_extremos(self):
        target_ini, target_fim = h.intervalo_targets_necessario([], h.LEADS)
        self.assertEqual(target_ini, target_fim)
        self.assertEqual(target_ini, pd.Period(f'{h.ANO_INICIO_HINDCAST}-01', 'M'))


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

    # J — auditoria expandida (Seção 10/18): verifica os DOIS máximos
    # do bias (max_init_date_used_bias e max_target_month_used_bias),
    # não só o de climatologia.
    def test_j_audit_tem_as_colunas_dos_dois_maximos_de_bias(self):
        origens = [(a, m) for a in range(1981, 1993) for m in [1, 6]]
        raw = h._com_periods(_raw_sintetico(origens, leads=[1, 3]))
        chirps = _chirps_sintetico(1981, 2016)
        summary, _ = h.construir_summary_e_calibrado(raw, chirps)
        ens_df = h.construir_ens_df(raw)
        leakage = h.construir_leakage_audit(summary, ens_df, chirps)
        for coluna in ('max_obs_date_used_climatology', 'max_init_date_used_bias',
                       'max_target_month_used_bias', 'bias_leakage_ok'):
            self.assertIn(coluna, leakage.columns)
        # há linhas com histórico de bias (max_init/max_target não nulos)
        com_bias = leakage[leakage['max_init_date_used_bias'].notna()]
        self.assertGreater(len(com_bias), 0)
        self.assertTrue(com_bias['max_target_month_used_bias'].notna().all())
        self.assertTrue(leakage['bias_leakage_ok'].all())

    def test_max_target_month_used_bias_nulo_quando_sem_historico(self):
        """Seção 10: campos max podem ser nulos com segurança quando não
        há histórico de bias (nunca um valor inventado)."""
        origens = [(1981, 1)]   # primeira origem: não tem NENHUM histórico anterior
        raw = h._com_periods(_raw_sintetico(origens, leads=[1]))
        chirps = _chirps_sintetico(1981, 1981)
        summary, _ = h.construir_summary_e_calibrado(raw, chirps)
        ens_df = h.construir_ens_df(raw)
        leakage = h.construir_leakage_audit(summary, ens_df, chirps)
        self.assertTrue(leakage['max_init_date_used_bias'].isna().all())
        self.assertTrue(leakage['max_target_month_used_bias'].isna().all())
        self.assertTrue(leakage['bias_leakage_ok'].all())   # sem histórico não é violação


# ══════════════════════════════════════════════════════════════════════════
# Pilot longitudinal — correção pós-run 35260471652. O pilot antigo (6
# origens isoladas) terminava com n_forecasts_avaliacao_principal=0
# porque não tinha NENHUM histórico prévio de origens C3S para treinar
# bias. Aqui rodamos o pipeline completo (construir_summary_e_calibrado
# + filtrar_avaliacao) sobre dado sintético gerado com as 72 origens
# reais do novo PILOT_ORIGENS (todos os 6 leads, 25 membros — o mesmo
# volume que a execução real produziria) e confirmamos que a avaliação
# principal (1991-2016) é genuinamente exercitada.
# ══════════════════════════════════════════════════════════════════════════

class PilotLongitudinalIntegradoTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        raw_str = _raw_sintetico(h.PILOT_ORIGENS, leads=h.LEADS, n_membros=h.N_MEMBROS_ESPERADO)
        cls.raw = h._com_periods(raw_str)
        cls.chirps = _chirps_sintetico(h.ANO_INICIO_HINDCAST, h.ANO_FIM_HINDCAST)
        cls.summary, cls.calibrated = h.construir_summary_e_calibrado(cls.raw, cls.chirps)
        cls.avaliacao = h.filtrar_avaliacao(cls.summary)

    def test_raw_tem_10800_linhas(self):
        self.assertEqual(len(self.raw), 10800)

    def test_summary_tem_432_linhas(self):
        self.assertEqual(len(self.summary), 432)

    def test_avaliacao_principal_tem_312_forecasts(self):
        self.assertEqual(len(self.avaliacao), h.PILOT_FORECASTS_AVALIACAO_ESPERADOS)
        self.assertEqual(len(self.avaliacao), 312)

    def test_origem_1991_01_tem_bias_training_n_maior_ou_igual_a_10(self):
        linhas = self.summary[self.summary['init_date'] == pd.Period('1991-01', 'M')]
        self.assertEqual(len(linhas), len(h.LEADS))
        self.assertTrue((linhas['bias_training_n'] >= h.MIN_ANOS_TREINO).all(),
                         f"bias_training_n por lead: {dict(zip(linhas['lead'], linhas['bias_training_n']))}")
        self.assertTrue((linhas['clim_n'] >= h.MIN_ANOS_TREINO).all())

    def test_origem_1991_07_tem_bias_training_n_maior_ou_igual_a_10(self):
        linhas = self.summary[self.summary['init_date'] == pd.Period('1991-07', 'M')]
        self.assertEqual(len(linhas), len(h.LEADS))
        self.assertTrue((linhas['bias_training_n'] >= h.MIN_ANOS_TREINO).all(),
                         f"bias_training_n por lead: {dict(zip(linhas['lead'], linhas['bias_training_n']))}")
        self.assertTrue((linhas['clim_n'] >= h.MIN_ANOS_TREINO).all())

    def test_confirmacao_contem_dado(self):
        self.assertGreater((self.avaliacao['evaluation_period'] == 'confirmacao').sum(), 0)

    def test_desenvolvimento_contem_dado(self):
        self.assertGreater((self.avaliacao['evaluation_period'] == 'desenvolvimento').sum(), 0)

    def test_avaliacao_nunca_inclui_warmup(self):
        self.assertNotIn('warmup', set(self.avaliacao['evaluation_period'].unique()))

    def test_bias_mm_e_ens_mean_bc_finitos_em_toda_avaliacao(self):
        self.assertTrue(np.isfinite(self.avaliacao['bias_mm'].astype(float)).all())
        self.assertTrue(np.isfinite(self.avaliacao['ens_mean_bc'].astype(float)).all())

    def test_probabilidades_raw_e_bc_somam_1_em_toda_avaliacao(self):
        soma_raw = (self.avaliacao['prob_below_raw'].astype(float) +
                    self.avaliacao['prob_normal_raw'].astype(float) +
                    self.avaliacao['prob_above_raw'].astype(float))
        soma_bc = (self.avaliacao['prob_below_bc'].astype(float) +
                   self.avaliacao['prob_normal_bc'].astype(float) +
                   self.avaliacao['prob_above_bc'].astype(float))
        self.assertTrue(np.allclose(soma_raw, 1.0, atol=1e-6))
        self.assertTrue(np.allclose(soma_bc, 1.0, atol=1e-6))


# ══════════════════════════════════════════════════════════════════════════
# validar_pilot_aprovado — nunca repetir o falso-positivo do run
# 35260471652 (workflow terminou "success" sem ter exercitado bias/
# skill/bootstrap de verdade). Cada teste isola UM critério A-M
# quebrado a partir de um resultado "bom" (o pipeline sintético da
# classe acima) e confirma que o pilot é reprovado.
# ══════════════════════════════════════════════════════════════════════════

def _resultado_pilot_bom():
    """Resultado completo e aprovável do pilot, montado sobre o mesmo
    dado sintético íntegro de PilotLongitudinalIntegradoTestCase — serve
    de base para os testes de reprovação, que corrompem só UM campo."""
    raw_str = _raw_sintetico(h.PILOT_ORIGENS, leads=h.LEADS, n_membros=h.N_MEMBROS_ESPERADO)
    raw = h._com_periods(raw_str)
    chirps = _chirps_sintetico(h.ANO_INICIO_HINDCAST, h.ANO_FIM_HINDCAST)
    summary, calibrated = h.construir_summary_e_calibrado(raw, chirps)
    avaliacao = h.filtrar_avaliacao(summary)
    tabelas_skill = h.montar_tabelas_skill(avaliacao)
    bootstrap_df = h.montar_bootstrap(avaliacao)
    ens_df = h.construir_ens_df(raw)
    leakage_df = h.construir_leakage_audit(summary, ens_df, chirps)
    leakage_aprovado = leakage_df.empty or (leakage_df['leakage_status'] == 'OK').all()
    return {
        'raw_df': raw_str, 'summary_df': summary, 'calibrated_df': calibrated,
        'chirps_df': chirps, 'leakage_df': leakage_df, 'temporal_df': h.construir_temporal_audit(raw),
        'leakage_audit_aprovado': bool(leakage_aprovado), 'tabelas_skill': tabelas_skill,
        'bootstrap_df': bootstrap_df, 'falhas': {}, 'metadados_origem': {},
        'origens': list(h.PILOT_ORIGENS), 'pilot': True, 'avaliacao_n': len(avaliacao),
        'avaliacao_df': avaliacao,
    }


class ValidarPilotAprovadoTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.resultado_bom = _resultado_pilot_bom()

    def test_resultado_bom_e_aprovado(self):
        aprovado, motivos = h.validar_pilot_aprovado(self.resultado_bom)
        self.assertTrue(aprovado, motivos)
        self.assertEqual(motivos, [])

    def test_reprova_se_n_forecasts_avaliacao_principal_e_zero(self):
        resultado = dict(self.resultado_bom)
        resultado['avaliacao_n'] = 0
        resultado['avaliacao_df'] = self.resultado_bom['avaliacao_df'].iloc[0:0]
        aprovado, motivos = h.validar_pilot_aprovado(resultado)
        self.assertFalse(aprovado)
        self.assertTrue(any('G)' in m or 'n_forecasts_avaliacao_principal' in m for m in motivos))

    def test_reprova_se_bc_inteiramente_nan(self):
        resultado = dict(self.resultado_bom)
        avaliacao = self.resultado_bom['avaliacao_df'].copy()
        avaliacao['ens_mean_bc'] = np.nan
        avaliacao['bias_mm'] = np.nan
        resultado['avaliacao_df'] = avaliacao
        aprovado, motivos = h.validar_pilot_aprovado(resultado)
        self.assertFalse(aprovado)
        self.assertTrue(any('bias_mm' in m or 'ens_mean_bc' in m for m in motivos))

    def test_reprova_se_tabela_de_skill_obrigatoria_vazia(self):
        resultado = dict(self.resultado_bom)
        tabelas = dict(self.resultado_bom['tabelas_skill'])
        tabelas['by_lead'] = pd.DataFrame()
        resultado['tabelas_skill'] = tabelas
        aprovado, motivos = h.validar_pilot_aprovado(resultado)
        self.assertFalse(aprovado)
        self.assertTrue(any('by_lead' in m for m in motivos))

    def test_reprova_se_probabilidades_bc_nao_somam_1(self):
        resultado = dict(self.resultado_bom)
        avaliacao = self.resultado_bom['avaliacao_df'].copy()
        avaliacao['prob_below_bc'] = avaliacao['prob_below_bc'] + 0.5
        resultado['avaliacao_df'] = avaliacao
        aprovado, motivos = h.validar_pilot_aprovado(resultado)
        self.assertFalse(aprovado)
        self.assertTrue(any('J)' in m for m in motivos))

    def test_reprova_se_bootstrap_vazio(self):
        resultado = dict(self.resultado_bom)
        resultado['bootstrap_df'] = pd.DataFrame()
        aprovado, motivos = h.validar_pilot_aprovado(resultado)
        self.assertFalse(aprovado)
        self.assertTrue(any('M)' in m for m in motivos))

    def test_reprova_se_origens_incompletas(self):
        resultado = dict(self.resultado_bom)
        resultado['falhas'] = {'1981-01': 'simulado'}
        aprovado, motivos = h.validar_pilot_aprovado(resultado)
        self.assertFalse(aprovado)
        self.assertTrue(any('A)' in m for m in motivos))

    def test_reprova_se_leakage_reprovado(self):
        resultado = dict(self.resultado_bom)
        resultado['leakage_audit_aprovado'] = False
        aprovado, motivos = h.validar_pilot_aprovado(resultado)
        self.assertFalse(aprovado)
        self.assertTrue(any('K)' in m for m in motivos))


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
        for nome in ('start_year', 'end_year', 'init_months', 'dry_run_plan', 'modo_execucao',
                     'confirm_full_hindcast'):
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


# ══════════════════════════════════════════════════════════════════════════
# Guardrail de segurança operacional — modo_execucao=PILOT é o default;
# o hindcast completo OFICIAL (modo_execucao=HINDCAST_COMPLETO_1981_2016)
# exige confirm_full_hindcast == EXECUTAR_1981_2016, verificado ANTES de
# qualquer instalação/download. Preparação do disparo oficial pós-pilot
# validado em execução real (run 35340386904): sem isso, clicar "Run
# workflow" sem mexer em nada disparava os 432 casos reais direto.
# ══════════════════════════════════════════════════════════════════════════

class GuardrailWorkflowTestCase(unittest.TestCase):

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

    # A — modo_execucao existe
    def test_a_modo_execucao_existe(self):
        self.assertIn('modo_execucao', self.inputs)
        self.assertEqual(self.inputs['modo_execucao']['type'], 'choice')
        self.assertEqual(set(self.inputs['modo_execucao']['options']),
                          {'PILOT', 'HINDCAST_COMPLETO_1981_2016'})

    # B — default é PILOT
    def test_b_modo_execucao_default_e_pilot(self):
        self.assertEqual(self.inputs['modo_execucao']['default'], 'PILOT')

    def test_confirm_full_hindcast_default_vazio(self):
        self.assertEqual(self.inputs['confirm_full_hindcast']['default'], '')

    # C — pilot continua seguro por default: sem alterar inputs, o
    # workflow nunca dispara o hindcast completo
    def test_c_defaults_do_click_run_rodam_so_o_pilot(self):
        defaults = {nome: cfg.get('default', '') for nome, cfg in self.inputs.items()}
        self.assertEqual(defaults['modo_execucao'], 'PILOT')
        self.assertEqual(defaults['dry_run_plan'], 'false')
        # com modo_execucao=PILOT (default), a condição do guardrail é falsa —
        # nunca bloqueia nem libera o hindcast completo; o step de execução
        # usa --pilot nesse caso.
        step_exec = self._step('rodar hindcast completo')
        self.assertIn('--pilot', step_exec['run'])
        self.assertIn("inputs.modo_execucao", step_exec['run'])

    def test_guardrail_vem_antes_do_setup_python_e_do_download(self):
        self.assertLess(self._indice('guardrail'), self._indice('set up python'))
        self.assertLess(self._indice('guardrail'), self._indice('criar ~/.cdsapirc'))
        self.assertLess(self._indice('guardrail'), self._indice('rodar hindcast completo'))

    def test_guardrail_condicao_e_a_esperada(self):
        step = self._step('guardrail')
        self.assertEqual(step['if'],
                          "inputs.dry_run_plan != 'true' && inputs.modo_execucao == "
                          "'HINDCAST_COMPLETO_1981_2016'")

    def test_g_guardrail_nao_referencia_script_python_nem_cdsapi(self):
        """O guardrail é bash puro — nenhum request CDS pode acontecer
        nele, já que nem chama o script Python nem o pacote cdsapi."""
        step = self._step('guardrail')
        self.assertNotIn('c3s_hindcast_completo.py', step['run'])
        self.assertNotIn('cdsapi', step['run'].lower())

    def _rodar_guardrail_bash(self, modo_execucao, dry_run_plan, confirm):
        """Executa o script bash REAL extraído do YAML (mesma lógica de
        avaliação de `if:` do GitHub Actions: só roda quando a condição
        é verdadeira) — devolve None se o step nem chegaria a rodar."""
        step = self._step('guardrail')
        condicao_ativa = (dry_run_plan != 'true') and (modo_execucao == 'HINDCAST_COMPLETO_1981_2016')
        if not condicao_ativa:
            return None
        script = step['run'].replace("${{ inputs.confirm_full_hindcast }}", confirm)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as tmp:
            summary_path = tmp.name
        try:
            env = dict(os.environ, GITHUB_STEP_SUMMARY=summary_path)
            return subprocess.run(['bash', '-c', script], capture_output=True, text=True, env=env)
        finally:
            Path(summary_path).unlink(missing_ok=True)

    # D — full sem confirmação explícita falha antes de chamar o script
    def test_d_full_sem_confirmacao_falha(self):
        r = self._rodar_guardrail_bash(modo_execucao='HINDCAST_COMPLETO_1981_2016',
                                        dry_run_plan='false', confirm='')
        self.assertIsNotNone(r)
        self.assertNotEqual(r.returncode, 0)

    def test_d_full_confirmacao_errada_tambem_falha(self):
        r = self._rodar_guardrail_bash(modo_execucao='HINDCAST_COMPLETO_1981_2016',
                                        dry_run_plan='false', confirm='sim, por favor')
        self.assertIsNotNone(r)
        self.assertNotEqual(r.returncode, 0)

    # D — full + confirm_full_hindcast correto libera a execução
    def test_d_full_com_confirmacao_correta_libera(self):
        r = self._rodar_guardrail_bash(modo_execucao='HINDCAST_COMPLETO_1981_2016',
                                        dry_run_plan='false', confirm='EXECUTAR_1981_2016')
        self.assertIsNotNone(r)
        self.assertEqual(r.returncode, 0)

    # dry_run_plan=true nunca exige confirmação (guardrail nem roda)
    def test_dry_run_true_nao_exige_confirmacao(self):
        r = self._rodar_guardrail_bash(modo_execucao='HINDCAST_COMPLETO_1981_2016',
                                        dry_run_plan='true', confirm='')
        self.assertIsNone(r)

    # G — pilot não exige confirmação
    def test_g_pilot_nao_exige_confirmacao(self):
        r = self._rodar_guardrail_bash(modo_execucao='PILOT', dry_run_plan='false', confirm='')
        self.assertIsNone(r)

    # H — dry-run pilot mostra 72 origens (via plano_piloto())
    def test_h_plano_piloto_tem_72_origens(self):
        plano = h.plano_piloto()
        self.assertEqual(plano['n_origens'], 72)
        self.assertEqual(len(plano['origens']), 72)
        self.assertEqual(plano['modo'], 'PILOT LONGITUDINAL')
        self.assertEqual(plano['init_months'], [1, 7])
        self.assertEqual(plano['periodo'], '1981-2016')
        self.assertEqual(plano['raw_rows_esperadas'], 10800)
        self.assertEqual(plano['summary_rows_esperadas'], 432)
        self.assertEqual(plano['forecasts_avaliacao_esperados'], 312)
        self.assertEqual(plano['periodo_warmup'], '1981-1990')
        self.assertEqual(plano['periodo_avaliacao'], '1991-2016')

    # I — dry-run full mostra 432 origens (via plano_execucao() default)
    def test_i_plano_execucao_default_tem_432_origens(self):
        plano = h.plano_execucao()
        self.assertEqual(plano['n_origens'], 432)
        self.assertEqual(plano['raw_rows_esperadas'], 64800)
        self.assertEqual(plano['summary_rows_esperadas'], 2592)

    def test_mostrar_plano_ramifica_por_modo_no_yaml(self):
        step = self._step('mostrar plano de execução')
        self.assertIn('--pilot --dry-run-plan', step['run'])
        self.assertIn('--start-year 1981 --end-year 2016 --dry-run-plan', step['run'])
        self.assertIn("inputs.modo_execucao", step['run'])

    # E/F/G — modo oficial sempre 1981-2016, sem --pilot, sem --init-months
    def test_efg_step_execucao_full_forca_1981_2016_sem_pilot_sem_init_months(self):
        step = self._step('rodar hindcast completo')
        self.assertIn('--start-year 1981 --end-year 2016', step['run'])
        self.assertNotIn('init_months', step['run'])
        self.assertNotIn('inputs.start_year', step['run'])
        self.assertNotIn('inputs.end_year', step['run'])

    def test_resumo_do_modo_escreve_no_step_summary_antes_da_execucao(self):
        self.assertLess(self._indice('resumo do modo de execução'), self._indice('criar ~/.cdsapirc'))
        self.assertLess(self._indice('resumo do modo de execução'), self._indice('rodar hindcast completo'))
        step = self._step('resumo do modo de execução')
        self.assertIn('GITHUB_STEP_SUMMARY', step['run'])
        self.assertIn('PILOT LONGITUDINAL', step['run'])
        self.assertIn('HINDCAST COMPLETO OFICIAL', step['run'])

    def test_dry_run_plan_com_pilot_usa_plano_piloto_nao_o_completo(self):
        with mock.patch.object(h, 'plano_execucao') as m_completo, \
             mock.patch.object(h, 'plano_piloto', wraps=h.plano_piloto) as m_piloto, \
             mock.patch.object(h, 'imprimir_plano') as m_imprimir, \
             mock.patch('sys.argv', ['c3s_hindcast_completo.py', '--pilot', '--dry-run-plan']):
            h.main()
        m_completo.assert_not_called()
        m_piloto.assert_called_once()
        args, kwargs = m_imprimir.call_args
        modo = kwargs.get('modo', args[1] if len(args) > 1 else None)
        self.assertIn('PILOT', modo)


# ══════════════════════════════════════════════════════════════════════════
# Preparação do hindcast OFICIAL 1981-2016 — validar_full_aprovado() e
# execution_mode no metadata.json. Barreira de INTEGRIDADE DO
# EXPERIMENTO, nunca de skill: MSESS/RPSS negativo é resultado
# científico válido e nunca reprova esta barreira (Seção 14).
# ══════════════════════════════════════════════════════════════════════════

def _resultado_full_bom():
    """Resultado completo e aprovável da execução oficial (432 origens,
    1981-2016, todos os meses), montado sobre o mesmo padrão sintético
    de _resultado_pilot_bom — só troca as origens pedidas. CHIRPS
    sintético cobre o intervalo REAL derivado (1981-01 a 2017-05, 437
    meses — correção pós-run oficial 35353196015), não mais um range
    fixo de 432 meses que deixaria os targets de 2017 sem observação."""
    origens = h.construir_origens(h.ANO_INICIO_HINDCAST, h.ANO_FIM_HINDCAST, None)
    raw_str = _raw_sintetico(origens, leads=h.LEADS, n_membros=h.N_MEMBROS_ESPERADO)
    raw = h._com_periods(raw_str)
    target_ini, target_fim = h.intervalo_targets_necessario(origens, h.LEADS)
    chirps = _chirps_sintetico_intervalo(target_ini, target_fim)
    summary, calibrated = h.construir_summary_e_calibrado(raw, chirps)
    avaliacao = h.filtrar_avaliacao(summary)
    tabelas_skill = h.montar_tabelas_skill(avaliacao)
    bootstrap_df = h.montar_bootstrap(avaliacao)
    ens_df = h.construir_ens_df(raw)
    leakage_df = h.construir_leakage_audit(summary, ens_df, chirps)
    leakage_aprovado = leakage_df.empty or (leakage_df['leakage_status'] == 'OK').all()
    return {
        'raw_df': raw_str, 'summary_df': summary, 'calibrated_df': calibrated,
        'chirps_df': chirps, 'leakage_df': leakage_df, 'temporal_df': h.construir_temporal_audit(raw),
        'leakage_audit_aprovado': bool(leakage_aprovado), 'tabelas_skill': tabelas_skill,
        'bootstrap_df': bootstrap_df, 'falhas': {}, 'metadados_origem': {},
        'origens': origens, 'pilot': False, 'avaliacao_n': len(avaliacao),
        'avaliacao_df': avaliacao,
    }


class ValidarFullAprovadoTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.resultado_bom = _resultado_full_bom()

    def test_resultado_bom_e_aprovado(self):
        aprovado, motivos = h.validar_full_aprovado(self.resultado_bom)
        self.assertTrue(aprovado, motivos)
        self.assertEqual(motivos, [])

    # J — metadata recebe execution_mode
    def test_j_execution_mode_full_1981_2016(self):
        metadata = h.montar_metadata(self.resultado_bom)
        self.assertEqual(metadata['execution_mode'], 'FULL_1981_2016')

    def test_j_execution_mode_pilot_longitudinal(self):
        resultado_pilot = dict(self.resultado_bom)
        resultado_pilot['pilot'] = True
        resultado_pilot['origens'] = list(h.PILOT_ORIGENS)
        metadata = h.montar_metadata(resultado_pilot)
        self.assertEqual(metadata['execution_mode'], 'PILOT_LONGITUDINAL')

    def test_j_execution_mode_partial_quando_origens_nao_sao_as_432_oficiais(self):
        resultado_parcial = dict(self.resultado_bom)
        resultado_parcial['origens'] = h.construir_origens(1991, 1995, None)
        metadata = h.montar_metadata(resultado_parcial)
        self.assertEqual(metadata['execution_mode'], 'PARTIAL')

    # K — full falha com raw != 64800
    def test_k_falha_se_raw_diferente_de_64800(self):
        resultado = dict(self.resultado_bom)
        resultado['raw_df'] = self.resultado_bom['raw_df'].iloc[:-1]
        aprovado, motivos = h.validar_full_aprovado(resultado)
        self.assertFalse(aprovado)
        self.assertTrue(any('raw' in m for m in motivos))

    # L — full falha com summary != 2592
    def test_l_falha_se_summary_diferente_de_2592(self):
        resultado = dict(self.resultado_bom)
        resultado['summary_df'] = self.resultado_bom['summary_df'].iloc[:-1]
        aprovado, motivos = h.validar_full_aprovado(resultado)
        self.assertFalse(aprovado)
        self.assertTrue(any('summary' in m for m in motivos))

    # M — full falha com origem != 432
    def test_m_falha_se_origens_incompletas(self):
        resultado = dict(self.resultado_bom)
        resultado['falhas'] = {'1981-01': 'simulado'}
        aprovado, motivos = h.validar_full_aprovado(resultado)
        self.assertFalse(aprovado)
        self.assertTrue(any('origens' in m for m in motivos))

    def test_falha_se_chirps_diferente_do_esperado(self):
        """Esperado dinâmico agora é 437 (1981-01 a 2017-05), não mais
        432 (correção pós-run oficial 35353196015)."""
        resultado = dict(self.resultado_bom)
        resultado['chirps_df'] = self.resultado_bom['chirps_df'].iloc[:-1]
        aprovado, motivos = h.validar_full_aprovado(resultado)
        self.assertFalse(aprovado)
        self.assertTrue(any('CHIRPS' in m and '437' in m for m in motivos), motivos)

    def test_falha_se_forecasts_avaliacao_diferente_de_1872(self):
        resultado = dict(self.resultado_bom)
        resultado['avaliacao_n'] = self.resultado_bom['avaliacao_n'] - 1
        aprovado, motivos = h.validar_full_aprovado(resultado)
        self.assertFalse(aprovado)
        self.assertTrue(any('1872' in m for m in motivos), motivos)

    def test_avaliacao_n_esperado_e_1872(self):
        self.assertEqual(self.resultado_bom['avaliacao_n'], 1872)

    def test_falha_se_cobertura_observacional_incompleta(self):
        """Item D/E da Seção 18 — reproduz o defeito real (run
        35353196015): 15 forecasts avaliáveis sem chirps_prec_mm
        finito."""
        resultado = dict(self.resultado_bom)
        avaliacao = self.resultado_bom['avaliacao_df'].copy()
        avaliacao.loc[avaliacao.index[:15], 'chirps_prec_mm'] = np.nan
        resultado['avaliacao_df'] = avaliacao
        aprovado, motivos = h.validar_full_aprovado(resultado)
        self.assertFalse(aprovado)
        self.assertTrue(any('cobertura observacional' in m for m in motivos), motivos)

    def test_todos_os_1872_forecasts_de_avaliacao_tem_observacao(self):
        avaliacao = self.resultado_bom['avaliacao_df']
        self.assertEqual(len(avaliacao), 1872)
        self.assertTrue(np.isfinite(avaliacao['chirps_prec_mm'].astype(float)).all())

    # N — full falha se leakage != OK
    def test_n_falha_se_leakage_reprovado(self):
        resultado = dict(self.resultado_bom)
        resultado['leakage_audit_aprovado'] = False
        aprovado, motivos = h.validar_full_aprovado(resultado)
        self.assertFalse(aprovado)
        self.assertTrue(any('leakage' in m for m in motivos))

    def test_falha_se_tabela_de_skill_obrigatoria_vazia(self):
        resultado = dict(self.resultado_bom)
        tabelas = dict(self.resultado_bom['tabelas_skill'])
        tabelas['prob_by_lead'] = pd.DataFrame()
        resultado['tabelas_skill'] = tabelas
        aprovado, motivos = h.validar_full_aprovado(resultado)
        self.assertFalse(aprovado)
        self.assertTrue(any('prob_by_lead' in m for m in motivos))

    def test_falha_se_bootstrap_vazio(self):
        resultado = dict(self.resultado_bom)
        resultado['bootstrap_df'] = pd.DataFrame()
        aprovado, motivos = h.validar_full_aprovado(resultado)
        self.assertFalse(aprovado)
        self.assertTrue(any('bootstrap' in m for m in motivos))

    # O — skill negativo NÃO causa falha
    def test_o_skill_negativo_nao_causa_falha(self):
        resultado = dict(self.resultado_bom)
        tabelas = {k: v.copy() for k, v in self.resultado_bom['tabelas_skill'].items()}
        for coluna in ('msess_raw', 'msess_bc'):
            if coluna in tabelas['overall'].columns:
                tabelas['overall'][coluna] = -0.9
        if 'rpss_raw' in tabelas['prob_overall'].columns:
            tabelas['prob_overall']['rpss_raw'] = -0.5
        resultado['tabelas_skill'] = tabelas
        aprovado, motivos = h.validar_full_aprovado(resultado)
        self.assertTrue(aprovado, motivos)


class MainGatingExecucaoOficialTestCase(unittest.TestCase):
    """main() só aplica validar_full_aprovado() quando os parâmetros
    pedidos são EXATAMENTE os oficiais (1981-2016, todos os meses) —
    uma execução parcial/depuração continua no gate de leakage já
    existente, sem essa barreira extra (Seção 14 — não alterar o
    comportamento de execuções parciais)."""

    def _mockar_acesso_ok(self, m_dl):
        m_dl.verificar_acesso.return_value = {'credenciais_configuradas': True,
                                               'pacote_cdsapi_instalado': True}

    def test_execucao_oficial_aplica_validar_full_aprovado(self):
        resultado_fake = {'leakage_audit_aprovado': True}
        with mock.patch.object(h, 'dl') as m_dl, \
             mock.patch.object(h, 'rodar', return_value=resultado_fake), \
             mock.patch.object(h, 'escrever_saidas'), \
             mock.patch.object(h, 'validar_full_aprovado', return_value=(True, [])) as m_validar, \
             mock.patch('sys.argv', ['c3s_hindcast_completo.py',
                                      '--start-year', '1981', '--end-year', '2016']):
            self._mockar_acesso_ok(m_dl)
            h.main()
        m_validar.assert_called_once_with(resultado_fake)

    def test_execucao_parcial_nao_aplica_validar_full_aprovado(self):
        resultado_fake = {'leakage_audit_aprovado': True}
        with mock.patch.object(h, 'dl') as m_dl, \
             mock.patch.object(h, 'rodar', return_value=resultado_fake), \
             mock.patch.object(h, 'escrever_saidas'), \
             mock.patch.object(h, 'validar_full_aprovado') as m_validar, \
             mock.patch('sys.argv', ['c3s_hindcast_completo.py',
                                      '--start-year', '1991', '--end-year', '1995']):
            self._mockar_acesso_ok(m_dl)
            h.main()
        m_validar.assert_not_called()

    def test_execucao_oficial_reprovada_sai_com_erro(self):
        resultado_fake = {'leakage_audit_aprovado': True}
        with mock.patch.object(h, 'dl') as m_dl, \
             mock.patch.object(h, 'rodar', return_value=resultado_fake), \
             mock.patch.object(h, 'escrever_saidas'), \
             mock.patch.object(h, 'validar_full_aprovado', return_value=(False, ['motivo x'])), \
             mock.patch('sys.argv', ['c3s_hindcast_completo.py',
                                      '--start-year', '1981', '--end-year', '2016']):
            self._mockar_acesso_ok(m_dl)
            with self.assertRaises(SystemExit) as e:
                h.main()
        self.assertNotEqual(e.exception.code, 0)

    def test_pilot_nao_aplica_validar_full_aprovado(self):
        resultado_fake = {'leakage_audit_aprovado': True}
        with mock.patch.object(h, 'dl') as m_dl, \
             mock.patch.object(h, 'rodar', return_value=resultado_fake), \
             mock.patch.object(h, 'escrever_saidas'), \
             mock.patch.object(h, 'validar_full_aprovado') as m_validar_full, \
             mock.patch.object(h, 'validar_pilot_aprovado', return_value=(True, [])), \
             mock.patch('sys.argv', ['c3s_hindcast_completo.py', '--pilot']):
            self._mockar_acesso_ok(m_dl)
            h.main()
        m_validar_full.assert_not_called()


if __name__ == '__main__':
    unittest.main()
