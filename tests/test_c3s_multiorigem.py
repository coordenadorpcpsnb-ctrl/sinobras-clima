#!/usr/bin/env python3
"""
tests/test_c3s_multiorigem.py — regressão da Fase 2A.2 (validação
multi-origem C3S, scripts/c3s_validacao_multiorigem.py) e do workflow
.github/workflows/c3s_validacao_multi.yml. Tudo offline: nenhum teste
baixa nada, abre GRIB real nem precisa de credencial CDS.

A lógica de download/parsing GRIB/CHIRPS em si já é coberta em
tests/test_c3s.py e tests/test_c3s_poc.py — aqui mockamos essas camadas
(poc.abrir_e_validar_grib, proc.extrair_ponto, proc.dataset_para_tabela,
poc.buscar_chirps_target_months) para testar só a ORQUESTRAÇÃO
multi-origem: as barreiras de fail-fast da Seção 9, cache/retry,
checkpoint/resume e a montagem dos artifacts consolidados.

Roda com:
    python -m unittest tests.test_c3s_multiorigem -v
"""

import contextlib
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
import c3s_validacao_multiorigem as mvo  # noqa: E402

WORKFLOW_PATH = ROOT / '.github' / 'workflows' / 'c3s_validacao_multi.yml'


# ══════════════════════════════════════════════════════════════════════════
# 12 origens configuradas, leads 1-6, contagens esperadas
# ══════════════════════════════════════════════════════════════════════════

class OrigensConfiguradasTestCase(unittest.TestCase):

    def test_12_origens_exatas(self):
        esperado = [(2005, 1), (2005, 4), (2005, 7), (2005, 10),
                    (2010, 1), (2010, 4), (2010, 7), (2010, 10),
                    (2015, 1), (2015, 4), (2015, 7), (2015, 10)]
        self.assertEqual(mvo.ORIGENS, esperado)
        self.assertEqual(len(mvo.ORIGENS), 12)

    def test_3_anos_espacados(self):
        anos = sorted(set(a for a, _ in mvo.ORIGENS))
        self.assertEqual(anos, [2005, 2010, 2015])

    def test_4_meses_por_ano_jan_abr_jul_out(self):
        for ano in {2005, 2010, 2015}:
            meses = sorted(m for a, m in mvo.ORIGENS if a == ano)
            self.assertEqual(meses, [1, 4, 7, 10])

    def test_leads_1_a_6(self):
        self.assertEqual(mvo.LEADS, [1, 2, 3, 4, 5, 6])

    def test_150_linhas_raw_por_origem(self):
        self.assertEqual(mvo.LINHAS_RAW_ESPERADAS_POR_ORIGEM, 150)
        self.assertEqual(mvo.N_MEMBROS_ESPERADO * len(mvo.LEADS), 150)

    def test_1800_linhas_raw_totais(self):
        self.assertEqual(len(mvo.ORIGENS) * mvo.LINHAS_RAW_ESPERADAS_POR_ORIGEM, 1800)

    def test_72_summaries_totais(self):
        self.assertEqual(len(mvo.ORIGENS) * mvo.LINHAS_SUMMARY_ESPERADAS_POR_ORIGEM, 72)

    def test_municipio_e_sao_bento_apenas(self):
        self.assertEqual(mvo.MUNICIPIO, 'Sao_Bento_do_Tocantins')

    def test_retry_maximo_3_tentativas(self):
        self.assertEqual(mvo.MAX_TENTATIVAS_CDS, 3)


# ══════════════════════════════════════════════════════════════════════════
# Guardrail contra misturar hindcast (25 membros) e real-time forecast
# (51 membros) — achado real da 1ª execução (run 35225848837): 2018 e
# 2021 voltaram com number=51, fora do período homogêneo de hindcast do
# SEAS5 (1981-2016). Falha ANTES de qualquer download.
# ══════════════════════════════════════════════════════════════════════════

class GuardrailPeriodoHindcastTestCase(unittest.TestCase):

    def test_nenhuma_origem_configurada_e_posterior_a_2016(self):
        for ano, _ in mvo.ORIGENS:
            self.assertLessEqual(ano, mvo.PERIODO_HINDCAST_SEAS5_ANO_MAX)

    def test_origens_configuradas_sao_2005_2010_2015(self):
        anos = sorted(set(a for a, _ in mvo.ORIGENS))
        self.assertEqual(anos, [2005, 2010, 2015])

    def test_25_membros_continua_sendo_o_esperado(self):
        self.assertEqual(mvo.N_MEMBROS_ESPERADO, 25)

    def test_validar_periodo_hindcast_aceita_as_origens_configuradas(self):
        mvo.validar_periodo_hindcast(mvo.ORIGENS)   # não deve levantar

    def test_ano_2017_falha_explicitamente(self):
        with self.assertRaises(ValueError) as e:
            mvo.validar_periodo_hindcast([(2017, 1)])
        self.assertIn('2017-01', str(e.exception))
        self.assertIn('hindcast', str(e.exception).lower())

    def test_ano_2018_falha_explicitamente_como_na_execucao_real(self):
        with self.assertRaises(ValueError):
            mvo.validar_periodo_hindcast([(2018, 1)])

    def test_rodar_falha_antes_de_qualquer_download_para_origem_fora_do_periodo(self):
        """A barreira tem que disparar ANTES de processar_origem (e,
        portanto, antes de qualquer download) — nunca depender só da
        contagem de membros descoberta depois do download."""
        with mock.patch.object(mvo, 'processar_origem') as m_processar:
            with self.assertRaises(ValueError):
                mvo.rodar(origens=[(2017, 1)])
        m_processar.assert_not_called()

    def test_mistura_de_origem_valida_e_invalida_tambem_falha_antes(self):
        with mock.patch.object(mvo, 'processar_origem') as m_processar:
            with self.assertRaises(ValueError):
                mvo.rodar(origens=[(2015, 1), (2020, 1)])
        m_processar.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════
# Virada de ano — a tabela do exemplo do enunciado (origem 2015-10)
# ══════════════════════════════════════════════════════════════════════════

class ViradaDeAnoTestCase(unittest.TestCase):

    def test_origem_2015_10_lead1_a_6_out_2015_a_mar_2016(self):
        init = pd.Period('2015-10', 'M')
        esperado = ['2015-10', '2015-11', '2015-12', '2016-01', '2016-02', '2016-03']
        obtidos = [str(cu.leadtime_para_mes_alvo(init, lead)) for lead in mvo.LEADS]
        self.assertEqual(obtidos, esperado)


# ══════════════════════════════════════════════════════════════════════════
# processar_origem — barreiras de fail-fast da Seção 9. As camadas já
# validadas (abertura/parsing GRIB, extração de ponto, tabela, CHIRPS)
# são mockadas; só a lógica de orquestração desta origem é exercitada.
# ══════════════════════════════════════════════════════════════════════════

def _tabela_valida(origem, leads=None, n_membros=25, valor_mm=150.0):
    leads = leads if leads is not None else mvo.LEADS
    init_date = pd.Period(origem, 'M')
    linhas = []
    for lead in leads:
        target_month = cu.leadtime_para_mes_alvo(init_date, lead)
        for membro in range(n_membros):
            linhas.append({'local': mvo.MUNICIPIO, 'target_month': str(target_month), 'lead': lead,
                            'centre': 'ECMWF', 'system': 'SEAS5', 'member': membro,
                            'forecast_prec_mm': valor_mm})
    return pd.DataFrame(linhas)


def _chirps_valido(origem, leads=None, valor_mm=150.0):
    leads = leads if leads is not None else mvo.LEADS
    init_date = pd.Period(origem, 'M')
    return {cu.leadtime_para_mes_alvo(init_date, lead): valor_mm for lead in leads}


def _mapa_lead_alvo_valido(origem, leads=None):
    leads = leads if leads is not None else mvo.LEADS
    init_date = pd.Period(origem, 'M')
    return {lead: str(cu.leadtime_para_mes_alvo(init_date, lead)) for lead in leads}


def _mock_processar_origem(ano=2015, mes=1, n_membros=25, unidade='m s**-1',
                            mapa_lead_alvo=None, tabela=None, chirps=None):
    """Monta um ExitStack com todas as camadas já validadas mockadas
    (download, abertura/validação do GRIB, extração de ponto, tabela,
    CHIRPS) com um cenário válido por padrão — cada teste sobrescreve só
    o que precisa para provocar a falha específica que está testando."""
    origem = mvo._origem_str(ano, mes)
    if mapa_lead_alvo is None:
        mapa_lead_alvo = _mapa_lead_alvo_valido(origem)
    if tabela is None:
        tabela = _tabela_valida(origem, n_membros=n_membros)
    if chirps is None:
        chirps = _chirps_valido(origem)

    fake_ds = SimpleNamespace(sizes={'number': n_membros})
    ponto_fake = {'latitude': -6.5, 'longitude': -47.5}

    ctx = contextlib.ExitStack()
    ctx.enter_context(mock.patch.object(mvo, '_baixar_com_retry_e_cache',
                                         return_value=(Path('/fake/cache/2015-01.grib'), True, 0)))
    ctx.enter_context(mock.patch.object(mvo.poc, 'abrir_e_validar_grib',
                                         return_value=(fake_ds, unidade, 'leadtime_month',
                                                       mapa_lead_alvo, {}, None)))
    ctx.enter_context(mock.patch.object(mvo.proc, 'extrair_ponto', return_value=ponto_fake))
    ctx.enter_context(mock.patch.object(mvo.proc, 'dataset_para_tabela', return_value=tabela.copy()))
    ctx.enter_context(mock.patch.object(mvo.poc, 'buscar_chirps_target_months', return_value=chirps))
    return ctx, ano, mes


class ProcessarOrigemTestCase(unittest.TestCase):

    def test_happy_path_150_raw_6_summary_6_temporal(self):
        ctx, ano, mes = _mock_processar_origem()
        with ctx:
            tabela, resumo, temporal_df, meta = mvo.processar_origem(ano, mes)
        self.assertEqual(len(tabela), 150)
        self.assertEqual(len(resumo), 6)
        self.assertEqual(len(temporal_df), 6)
        self.assertEqual(meta['n_membros'], 25)
        self.assertEqual(sorted(resumo['lead']), [1, 2, 3, 4, 5, 6])
        self.assertTrue((tabela['chirps_prec_mm'] == 150.0).all())

    def test_a_24_membros_falha(self):
        ctx, ano, mes = _mock_processar_origem(n_membros=24, tabela=_tabela_valida('2015-01', n_membros=24))
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                mvo.processar_origem(ano, mes)
        self.assertIn('Seção 9.A', str(e.exception))

    def test_a_51_membros_falha_regressao_execucao_real(self):
        """Regressão direta do achado real (run 35225848837): origens
        fora do período de hindcast (2018/2021) voltaram com number=51
        (real-time forecast) — esta fase continua exigindo 25 membros
        exatos, nunca aceita 51 nem trunca para os primeiros 25."""
        ctx, ano, mes = _mock_processar_origem(n_membros=51)
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                mvo.processar_origem(ano, mes)
        self.assertIn('Seção 9.A', str(e.exception))
        self.assertIn('51', str(e.exception))

    def test_b_5_leads_falha(self):
        origem = '2015-01'
        mapa = _mapa_lead_alvo_valido(origem, leads=[1, 2, 3, 4, 5])   # falta o lead 6
        ctx, ano, mes = _mock_processar_origem(mapa_lead_alvo=mapa)
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                mvo.processar_origem(ano, mes)
        self.assertIn('Seção 9.B', str(e.exception))

    def test_c_verifying_month_duplicado_falha(self):
        origem = '2015-01'
        mapa = _mapa_lead_alvo_valido(origem)
        mapa[6] = mapa[5]   # lead 6 "aponta" para o mesmo mês do lead 5 — só 5 distintos
        ctx, ano, mes = _mock_processar_origem(mapa_lead_alvo=mapa)
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                mvo.processar_origem(ano, mes)
        self.assertIn('Seção 9.C', str(e.exception))

    def test_d_verifying_month_incoerente_com_leadtime_falha(self):
        origem = '2015-01'
        mapa = _mapa_lead_alvo_valido(origem)
        # lead 6 devia ser 2015-06 (leadtime_para_mes_alvo(2015-01,6)) —
        # desloca pra 2015-07, ainda distinto dos outros 5, mas incoerente
        mapa[6] = '2015-07'
        ctx, ano, mes = _mock_processar_origem(mapa_lead_alvo=mapa)
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                mvo.processar_origem(ano, mes)
        self.assertIn('Seção 9.D', str(e.exception))

    def test_e_unidade_errada_falha(self):
        # 'm s-1' é uma forma equivalente aceita pela POC (c3s_poc.py),
        # mas esta camada multi-origem exige a forma exata observada
        # ('m s**-1') para pegar qualquer drift entre origens/execuções.
        ctx, ano, mes = _mock_processar_origem(unidade='m s-1')
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                mvo.processar_origem(ano, mes)
        self.assertIn('Seção 9.E', str(e.exception))

    def test_f_nan_falha(self):
        origem = '2015-01'
        tabela = _tabela_valida(origem)
        tabela.loc[0, 'forecast_prec_mm'] = float('nan')
        ctx, ano, mes = _mock_processar_origem(tabela=tabela)
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                mvo.processar_origem(ano, mes)
        self.assertIn('Seção 9.F', str(e.exception))

    def test_f_negativo_falha(self):
        origem = '2015-01'
        tabela = _tabela_valida(origem)
        tabela.loc[0, 'forecast_prec_mm'] = -5.0
        ctx, ano, mes = _mock_processar_origem(tabela=tabela)
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                mvo.processar_origem(ano, mes)
        self.assertIn('Seção 9.F', str(e.exception))

    def test_g_fora_da_barreira_fisica_falha(self):
        origem = '2015-01'
        tabela = _tabela_valida(origem)
        tabela.loc[0, 'forecast_prec_mm'] = 2000.0   # > 1500mm/mês
        ctx, ano, mes = _mock_processar_origem(tabela=tabela)
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                mvo.processar_origem(ano, mes)
        self.assertIn('Seção 9.G', str(e.exception))

    def test_h_numero_de_linhas_raw_errado_falha(self):
        origem = '2015-01'
        tabela = _tabela_valida(origem).iloc[:-1].copy()   # 149 em vez de 150
        ctx, ano, mes = _mock_processar_origem(tabela=tabela)
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                mvo.processar_origem(ano, mes)
        self.assertIn('Seção 9.H', str(e.exception))

    def test_i_numero_de_summaries_errado_falha(self):
        """150 linhas no total (H ok), mas distribuídas em 7 leads
        distintos em vez de 6 — H passa, I tem que pegar."""
        origem = '2015-01'
        tabela = _tabela_valida(origem, leads=[1, 2, 3, 4, 5, 6]).iloc[:-1].copy()
        linha_extra = tabela.iloc[[0]].copy()
        linha_extra['lead'] = 99
        tabela = pd.concat([tabela, linha_extra], ignore_index=True)
        self.assertEqual(len(tabela), 150)
        self.assertEqual(tabela['lead'].nunique(), 7)
        ctx, ano, mes = _mock_processar_origem(tabela=tabela)
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                mvo.processar_origem(ano, mes)
        self.assertIn('Seção 9.I', str(e.exception))

    def test_j_chirps_incompleto_falha(self):
        origem = '2015-01'
        chirps = _chirps_valido(origem, leads=[1, 2, 3, 4, 5])   # falta o mês do lead 6
        ctx, ano, mes = _mock_processar_origem(chirps=chirps)
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                mvo.processar_origem(ano, mes)
        self.assertIn('Seção 9.J', str(e.exception))


# ══════════════════════════════════════════════════════════════════════════
# Veredito final / exit code — regressão do achado real: o script
# marcava origens como FALHOU mas terminava com exit 0, deixando o
# workflow "success" mesmo com a Fase 2A.2 reprovada.
# ══════════════════════════════════════════════════════════════════════════

def _meta_origem_generica():
    return {'cache_hit': True, 'retries': 0, 'n_membros': 25, 'lat_grade': -6.5, 'lon_grade': -47.5,
            'distancia_grade_km': 10.0, 'unidade': 'm s**-1', 'esquema_temporal': 'leadtime_month'}


class VereditoAprovadoTestCase(unittest.TestCase):

    def test_aprovado_so_com_todas_concluidas_e_zero_falhas(self):
        estado = mvo._checkpoint_vazio()
        for a, m in mvo.ORIGENS:
            estado['concluidas'][mvo._origem_str(a, m)] = _meta_origem_generica()
        self.assertTrue(mvo.veredito_aprovado(estado, mvo.ORIGENS))

    def test_reprovado_com_uma_falha(self):
        estado = mvo._checkpoint_vazio()
        for a, m in mvo.ORIGENS[:-1]:
            estado['concluidas'][mvo._origem_str(a, m)] = _meta_origem_generica()
        estado['falhadas'][mvo._origem_str(*mvo.ORIGENS[-1])] = {'motivo': 'simulado', 'quando': 'x'}
        self.assertFalse(mvo.veredito_aprovado(estado, mvo.ORIGENS))

    def test_reprovado_com_origem_pendente_nao_processada(self):
        estado = mvo._checkpoint_vazio()
        for a, m in mvo.ORIGENS[:-1]:
            estado['concluidas'][mvo._origem_str(a, m)] = _meta_origem_generica()
        # última origem nem concluída nem falhada — ainda assim não é 12/12
        self.assertFalse(mvo.veredito_aprovado(estado, mvo.ORIGENS))


class MainExitCodeTestCase(unittest.TestCase):
    """main() é testado com rodar()/escrever_saidas() mockados — o
    comportamento de cache/download/validação por origem já está coberto
    em ProcessarOrigemTestCase/DownloadCacheRetryTestCase; aqui o que
    importa é só a decisão de exit code a partir do veredito."""

    def _rodar_main_mockado(self, estado):
        contadores = {'requests_cds': 0, 'cache_hits': 0, 'downloads': 0, 'retries': 0}
        vazio = pd.DataFrame()
        with mock.patch.object(mvo.dl, 'verificar_acesso',
                                return_value={'credenciais_configuradas': True,
                                              'pacote_cdsapi_instalado': True}), \
             mock.patch.object(mvo, 'rodar', return_value=(vazio, vazio, vazio, estado, contadores)), \
             mock.patch.object(mvo, 'verificar_grid_point_constante', return_value=[]), \
             mock.patch.object(mvo, 'escrever_saidas', return_value=({}, 'relatorio')) as m_escrever:
            mvo.main()
        return m_escrever

    def test_reprovado_sai_com_codigo_diferente_de_zero(self):
        estado = mvo._checkpoint_vazio()
        estado['falhadas'][mvo._origem_str(*mvo.ORIGENS[0])] = {'motivo': 'simulado', 'quando': 'x'}
        contadores = {'requests_cds': 0, 'cache_hits': 0, 'downloads': 0, 'retries': 0}
        vazio = pd.DataFrame()
        with mock.patch.object(mvo.dl, 'verificar_acesso',
                                return_value={'credenciais_configuradas': True,
                                              'pacote_cdsapi_instalado': True}), \
             mock.patch.object(mvo, 'rodar', return_value=(vazio, vazio, vazio, estado, contadores)), \
             mock.patch.object(mvo, 'verificar_grid_point_constante', return_value=[]), \
             mock.patch.object(mvo, 'escrever_saidas', return_value=({}, 'relatorio')) as m_escrever:
            with self.assertRaises(SystemExit) as e:
                mvo.main()
        self.assertNotEqual(e.exception.code, 0)
        m_escrever.assert_called_once()   # artifacts gravados ANTES do exit (Seção 5)

    def test_aprovado_nao_levanta_systemexit(self):
        estado = mvo._checkpoint_vazio()
        for a, m in mvo.ORIGENS:
            estado['concluidas'][mvo._origem_str(a, m)] = _meta_origem_generica()
        try:
            m_escrever = self._rodar_main_mockado(estado)
        except SystemExit as e:
            self.fail(f"main() não deveria levantar SystemExit quando aprovado (code={e.code})")
        m_escrever.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════
# CHIRPS nunca vira ERA5 silenciosamente
# ══════════════════════════════════════════════════════════════════════════

class ChirpsNuncaViraEra5TestCase(unittest.TestCase):

    def test_modulo_nao_importa_nem_chama_fallback_openmeteo(self):
        """O módulo PODE mencionar ERA5/openmeteo em comentário explicando
        que nunca cai nesse fallback (é exatamente o que documenta) — o
        que não pode existir é um import ou chamada real da função de
        fallback (_openmeteo.py::buscar_prec_openmeteo)."""
        src = Path(mvo.__file__).read_text(encoding='utf-8')
        self.assertNotIn('_openmeteo', src)
        self.assertNotIn('buscar_prec_openmeteo', src)
        self.assertNotIn('import _openmeteo', src)

    def test_processar_origem_usa_buscar_chirps_target_months(self):
        import inspect
        src = inspect.getsource(mvo.processar_origem)
        self.assertIn('poc.buscar_chirps_target_months', src)

    def test_falha_chirps_propaga_sem_fallback_silencioso(self):
        ctx, ano, mes = _mock_processar_origem()
        ctx.enter_context(mock.patch.object(mvo.poc, 'buscar_chirps_target_months',
                                             side_effect=RuntimeError('CHIRPS indisponível simulado')))
        with ctx:
            with self.assertRaises(RuntimeError) as e:
                mvo.processar_origem(ano, mes)
        self.assertIn('CHIRPS indisponível simulado', str(e.exception))


# ══════════════════════════════════════════════════════════════════════════
# Download com cache determinístico + retry controlado (nunca infinito)
# ══════════════════════════════════════════════════════════════════════════

class DownloadCacheRetryTestCase(unittest.TestCase):

    def test_cache_hit_nao_baixa_nem_espera(self):
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / 'ja_em_cache.grib'
            destino.write_bytes(b'fake grib')
            sleep_fn = mock.Mock()
            with mock.patch.object(mvo.dl, 'caminho_cache', return_value=destino), \
                 mock.patch.object(mvo.dl, 'baixar', return_value=destino) as m_baixar:
                caminho, cache_hit, retries = mvo._baixar_com_retry_e_cache({'x': 1}, sleep_fn=sleep_fn)
        self.assertEqual(caminho, destino)
        self.assertTrue(cache_hit)
        self.assertEqual(retries, 0)
        m_baixar.assert_called_once()
        sleep_fn.assert_not_called()

    def test_retry_com_sucesso_na_terceira_tentativa(self):
        with tempfile.TemporaryDirectory() as tmp:
            destino_inexistente = Path(tmp) / 'nao_existe_ainda.grib'
            resultado_final = Path(tmp) / 'baixado.grib'
            sleep_fn = mock.Mock()
            m_baixar = mock.Mock(side_effect=[RuntimeError('falha 1'), RuntimeError('falha 2'), resultado_final])
            with mock.patch.object(mvo.dl, 'caminho_cache', return_value=destino_inexistente), \
                 mock.patch.object(mvo.dl, 'baixar', m_baixar):
                caminho, cache_hit, retries = mvo._baixar_com_retry_e_cache({'x': 1}, sleep_fn=sleep_fn)
        self.assertEqual(caminho, resultado_final)
        self.assertFalse(cache_hit)
        self.assertEqual(retries, 2)
        self.assertEqual(m_baixar.call_count, 3)
        sleep_fn.assert_has_calls([mock.call(15), mock.call(30)])
        self.assertEqual(sleep_fn.call_count, 2)

    def test_esgota_tentativas_e_falha_sem_loop_infinito(self):
        with tempfile.TemporaryDirectory() as tmp:
            destino_inexistente = Path(tmp) / 'nunca_baixa.grib'
            sleep_fn = mock.Mock()
            m_baixar = mock.Mock(side_effect=RuntimeError('sempre falha'))
            with mock.patch.object(mvo.dl, 'caminho_cache', return_value=destino_inexistente), \
                 mock.patch.object(mvo.dl, 'baixar', m_baixar):
                with self.assertRaises(RuntimeError) as e:
                    mvo._baixar_com_retry_e_cache({'x': 1}, sleep_fn=sleep_fn)
        self.assertIn(str(mvo.MAX_TENTATIVAS_CDS), str(e.exception))
        self.assertEqual(m_baixar.call_count, mvo.MAX_TENTATIVAS_CDS)
        self.assertEqual(sleep_fn.call_count, mvo.MAX_TENTATIVAS_CDS - 1)


# ══════════════════════════════════════════════════════════════════════════
# Checkpoint/resume — origem já concluída não é reprocessada
# ══════════════════════════════════════════════════════════════════════════

class CheckpointResumeTestCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(self._tmp.name)
        self._patches = [
            mock.patch.object(mvo, 'ARTIFACTS_DIR', tmp_path),
            mock.patch.object(mvo, 'CHECKPOINT_PATH', tmp_path / 'checkpoint.json'),
            mock.patch.object(mvo, 'DADOS_ORIGEM_DIR', tmp_path / '_dados_origem'),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(lambda: [p.stop() for p in self._patches])

    def test_checkpoint_vazio_lista_as_12_origens_pendentes(self):
        estado = mvo.carregar_checkpoint()
        self.assertEqual(estado['concluidas'], {})
        self.assertEqual(estado['falhadas'], {})
        self.assertEqual(len(estado['pendentes']), 12)
        self.assertIn('2015-01', estado['pendentes'])

    def test_origem_concluida_nao_e_reprocessada(self):
        origem_pronta = '2015-01'
        tabela = _tabela_valida(origem_pronta)
        resumo_linhas = [{'init_date': origem_pronta, 'lead': lead, 'ens_mean': 150.0} for lead in mvo.LEADS]
        resumo = pd.DataFrame(resumo_linhas)
        temporal = pd.DataFrame([{'init_date': origem_pronta, 'lead': lead} for lead in mvo.LEADS])
        mvo._salvar_dados_origem(origem_pronta, tabela, resumo, temporal)

        estado = mvo._checkpoint_vazio()
        estado['concluidas'][origem_pronta] = {'cache_hit': True, 'retries': 0, 'n_membros': 25,
                                                 'lat_grade': -6.5, 'lon_grade': -47.5,
                                                 'distancia_grade_km': 10.0, 'unidade': 'm s**-1',
                                                 'esquema_temporal': 'leadtime_month'}
        estado['pendentes'].remove(origem_pronta)
        mvo.salvar_checkpoint(estado)

        chamadas = []

        def _fake_processar_origem(ano, mes, sleep_fn=None):
            chamadas.append((ano, mes))
            origem = mvo._origem_str(ano, mes)
            t = _tabela_valida(origem)
            r = pd.DataFrame([{'init_date': origem, 'lead': lead, 'ens_mean': 200.0} for lead in mvo.LEADS])
            tc = pd.DataFrame([{'init_date': origem, 'lead': lead} for lead in mvo.LEADS])
            meta = {'cache_hit': False, 'retries': 0, 'n_membros': 25, 'lat_grade': -6.5, 'lon_grade': -47.5,
                    'distancia_grade_km': 10.0, 'unidade': 'm s**-1', 'esquema_temporal': 'leadtime_month'}
            return t, r, tc, meta

        with mock.patch.object(mvo, 'processar_origem', side_effect=_fake_processar_origem):
            raw_final, summary_final, temporal_final, estado_final, contadores = mvo.rodar(
                origens=[(2015, 1), (2015, 4)])

        self.assertEqual(chamadas, [(2015, 4)])   # 2015-01 nunca reprocessada
        self.assertIn('2015-01', estado_final['concluidas'])
        self.assertIn('2015-04', estado_final['concluidas'])
        self.assertEqual(len(raw_final), 300)   # 150 (cache) + 150 (nova)


# ══════════════════════════════════════════════════════════════════════════
# Credenciais nunca aparecem em código/output; workflow manual sem cron
# ══════════════════════════════════════════════════════════════════════════

class CredenciaisTestCase(unittest.TestCase):

    def test_nenhum_token_real_no_script_nem_no_workflow(self):
        import re
        padrao_uuid = re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
                                  r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b')
        for caminho in (ROOT / 'scripts' / 'c3s_validacao_multiorigem.py', WORKFLOW_PATH):
            texto = caminho.read_text(encoding='utf-8')
            self.assertIsNone(padrao_uuid.search(texto), f"possível token real em {caminho.name}")

    def test_metadata_nao_tem_campo_de_credencial(self):
        import inspect
        src = inspect.getsource(mvo.montar_metadata)
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


class WorkflowManualTestCase(unittest.TestCase):

    def setUp(self):
        self.spec = yaml.safe_load(WORKFLOW_PATH.read_text(encoding='utf-8'))

    def test_trigger_e_workflow_dispatch(self):
        gatilhos = self.spec.get('on', self.spec.get(True))
        self.assertIn('workflow_dispatch', gatilhos)

    def test_nao_tem_cron(self):
        gatilhos = self.spec.get('on', self.spec.get(True))
        self.assertNotIn('schedule', gatilhos)

    def test_nome_do_workflow(self):
        self.assertEqual(self.spec['name'], 'C3S Validação Multi-origem')

    def test_tem_timeout_razoavel(self):
        job = next(iter(self.spec['jobs'].values()))
        self.assertIn('timeout-minutes', job)
        self.assertGreaterEqual(job['timeout-minutes'], 60)

    def test_cdsapirc_removido_sempre(self):
        texto = WORKFLOW_PATH.read_text(encoding='utf-8')
        self.assertIn('.cdsapirc', texto)
        self.assertIn('if: always()', texto)

    def test_artifact_nao_inclui_grib_ou_nc(self):
        texto = WORKFLOW_PATH.read_text(encoding='utf-8')
        self.assertNotIn('.grib', texto)
        self.assertNotIn('.nc\n', texto)

    def test_artifact_publica_os_arquivos_esperados(self):
        texto = WORKFLOW_PATH.read_text(encoding='utf-8')
        for esperado in ('c3s_multi_raw.csv', 'c3s_multi_summary.csv', 'c3s_multi_temporal_check.csv',
                          'c3s_multi_metadata.json', 'checkpoint.json', 'RELATORIO.md'):
            self.assertIn(esperado, texto)

    def test_roda_testes_e_verifica_dashboard(self):
        texto = WORKFLOW_PATH.read_text(encoding='utf-8')
        self.assertIn('unittest discover tests', texto)
        self.assertIn('verificar_dashboard.py', texto)

    def _step(self, nome_substring):
        steps = next(iter(self.spec['jobs'].values()))['steps']
        for s in steps:
            if nome_substring.lower() in s.get('name', '').lower():
                return s
        self.fail(f"nenhum step com nome contendo {nome_substring!r} encontrado")

    def test_remocao_de_credencial_tem_if_always(self):
        """Seção 6 da correção: como o script principal agora pode sair
        com erro (veredito REPROVADO), este passo precisa rodar mesmo
        assim — se não rodar, a credencial temporária fica no runner."""
        s = self._step('remover credencial')
        self.assertEqual(s.get('if'), 'always()')

    def test_publicacao_de_artifacts_tem_if_always(self):
        """Mesma razão do teste acima — os artifacts (incluindo o
        RELATORIO.md com o motivo da reprovação) têm que ser publicados
        mesmo quando o passo principal falha."""
        s = self._step('publicar artifacts')
        self.assertEqual(s.get('if'), 'always()')

    def test_step_principal_nao_tem_continue_on_error(self):
        """Se alguém adicionar continue-on-error: true ao passo
        principal, o job voltaria a terminar 'success' mesmo com a
        validação reprovada — exatamente o bug desta correção."""
        s = self._step('rodar validação multi-origem')
        self.assertNotIn('continue-on-error', s)


# ══════════════════════════════════════════════════════════════════════════
# Checkpoint — documentação não pode afirmar resume automático entre
# execuções independentes do workflow (isso não existe hoje).
# ══════════════════════════════════════════════════════════════════════════

class ChecklistDocumentacaoCheckpointTestCase(unittest.TestCase):

    def test_docstring_esclarece_que_nao_ha_resume_automatico_entre_runners(self):
        src = Path(mvo.__file__).read_text(encoding='utf-8')
        self.assertIn('filesystem limpo', src.lower())
        self.assertIn('não há resume automático entre', src.lower())

    def test_nota_real_time_forecast_pos_2016_existe_e_e_incluida_no_relatorio(self):
        self.assertIn('51 membros', mvo.NOTA_REAL_TIME_FORECAST_POS_2016)
        self.assertIn('separadamente', mvo.NOTA_REAL_TIME_FORECAST_POS_2016.lower())

        estado = mvo._checkpoint_vazio()
        contadores = {'requests_cds': 0, 'cache_hits': 0, 'downloads': 0, 'retries': 0}
        vazio = pd.DataFrame()
        relatorio = mvo.gerar_relatorio_markdown(estado, contadores, vazio, vazio, [])
        self.assertIn(mvo.NOTA_REAL_TIME_FORECAST_POS_2016, relatorio)


# ══════════════════════════════════════════════════════════════════════════
# Não altera produção
# ══════════════════════════════════════════════════════════════════════════

class ProducaoIntocadaTestCase(unittest.TestCase):

    def test_modulo_nao_importa_scripts_de_producao(self):
        import inspect
        src = inspect.getsource(mvo)
        for proibido in ('import update_dashboard', 'import fetch_monthly_data',
                          'import update_indices', 'import gerar_relatorio'):
            self.assertNotIn(proibido, src)


if __name__ == '__main__':
    unittest.main()
