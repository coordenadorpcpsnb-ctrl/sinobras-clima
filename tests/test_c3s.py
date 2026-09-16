#!/usr/bin/env python3
"""
tests/test_c3s.py — regressão dos módulos C3S (Fase 2A). Todos os testes
são offline: nenhum baixa nada nem precisa de credencial CDS. O
Dataset "C3S" usado nos testes de c3s_processar é SINTÉTICO (construído
com xarray, mesma forma documentada em c3s_processar.py), não um arquivo
GRIB real — ver a ressalva sobre bloqueio de rede em c3s_catalogo.py.

Cobre a Seção 19 da tarefa (12 itens).

Roda com:
    python -m unittest tests.test_c3s -v
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import _c3s_utils as cu  # noqa: E402
import c3s_catalogo as cat  # noqa: E402
import c3s_download as dl  # noqa: E402
import c3s_processar as proc  # noqa: E402
import c3s_hindcast as hc  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════
# Teste 1 — conversão de unidades
# ══════════════════════════════════════════════════════════════════════════

class ConversaoUnidadeTestCase(unittest.TestCase):

    def test_tprate_para_mm_janeiro_31_dias(self):
        # 1e-8 m/s * 31*86400 s * 1000 mm/m = 26.784 mm
        mm = cu.tprate_para_mm(1e-8, 2020, 1)
        self.assertAlmostEqual(mm, 1e-8 * 31 * 86400 * 1000, places=6)

    def test_tprate_para_mm_fevereiro_bissexto_vs_comum(self):
        """A armadilha específica: segundos-no-mês NÃO é constante —
        fevereiro bissexto (29d) e comum (28d) devem dar valores
        diferentes para a mesma taxa."""
        mm_2020 = cu.tprate_para_mm(1e-8, 2020, 2)   # bissexto
        mm_2021 = cu.tprate_para_mm(1e-8, 2021, 2)   # comum
        self.assertNotAlmostEqual(mm_2020, mm_2021, places=6)
        self.assertGreater(mm_2020, mm_2021)

    def test_conversao_nunca_usa_constante_fixa_de_segundos(self):
        """Se alguém 'otimizar' para uma constante tipo 30*86400, esse
        teste captura — os 12 meses do ano não podem todos ter o mesmo
        segundos_no_mes."""
        valores = {m: cu.segundos_no_mes(2023, m) for m in range(1, 13)}
        self.assertGreater(len(set(valores.values())), 1)


# ══════════════════════════════════════════════════════════════════════════
# Testes 2 e 3 — leadtime_month e target_month
# ══════════════════════════════════════════════════════════════════════════

class LeadtimeTestCase(unittest.TestCase):

    def test_leadtime_1_e_o_proprio_mes_de_inicializacao(self):
        """A armadilha central da Seção 6 — confirmada via documentação
        pública (ver docstring de _c3s_utils.py): leadtime_month=1 é o
        MESMO mês da inicialização, não o mês seguinte."""
        init = pd.Period('2020-06', 'M')
        alvo = cu.leadtime_para_mes_alvo(init, 1)
        self.assertEqual(alvo, pd.Period('2020-06', 'M'))

    def test_leadtime_2_e_um_mes_apos_init(self):
        init = pd.Period('2020-06', 'M')
        alvo = cu.leadtime_para_mes_alvo(init, 2)
        self.assertEqual(alvo, pd.Period('2020-07', 'M'))

    def test_leadtime_6_e_cinco_meses_apos_init(self):
        init = pd.Period('2020-06', 'M')
        alvo = cu.leadtime_para_mes_alvo(init, 6)
        self.assertEqual(alvo, pd.Period('2020-11', 'M'))

    def test_leadtime_zero_nao_existe(self):
        with self.assertRaises(ValueError):
            cu.leadtime_para_mes_alvo(pd.Period('2020-06', 'M'), 0)

    def test_inverso_bate(self):
        init = pd.Period('2019-03', 'M')
        for lead in range(1, 7):
            alvo = cu.leadtime_para_mes_alvo(init, lead)
            self.assertEqual(cu.mes_alvo_para_leadtime(init, alvo), lead)

    def test_virada_de_ano(self):
        """Init em novembro, lead 6 -> abril do ano seguinte — testa que
        a aritmética de Period cruza o ano corretamente."""
        init = pd.Period('2019-11', 'M')
        alvo = cu.leadtime_para_mes_alvo(init, 6)
        self.assertEqual(alvo, pd.Period('2020-04', 'M'))


# ══════════════════════════════════════════════════════════════════════════
# Dataset sintético para os testes de c3s_processar
# ══════════════════════════════════════════════════════════════════════════

def _dataset_sintetico(init_dates=('2020-06-01',), leads=(1, 2, 3), n_membros=5,
                        lats=(-6.0, -5.5), lons=(-48.0, -47.5), valor_tprate=2e-8, seed=1):
    rng = np.random.RandomState(seed)
    times = pd.to_datetime(list(init_dates))
    data = valor_tprate + rng.normal(0, 1e-9, size=(len(times), len(leads), n_membros, len(lats), len(lons)))
    ds = xr.Dataset(
        {'tprate': (('time', 'forecastMonth', 'number', 'latitude', 'longitude'), data)},
        coords={'time': times, 'forecastMonth': list(leads), 'number': list(range(n_membros)),
                'latitude': list(lats), 'longitude': list(lons)},
    )
    return ds


class ProcessarTestCase(unittest.TestCase):
    """Testes 10 e 11 (parcial) — município correto, forma da tabela."""

    def test_extrair_ponto_pega_vizinho_mais_proximo(self):
        ds = _dataset_sintetico(lats=(-6.0, -5.5), lons=(-48.0, -47.5))
        pt = proc.extrair_ponto(ds, lat=-6.02, lon=-47.90)   # perto de (-6.0,-48.0)? mais perto de -6.0/-47.5 em lon
        self.assertAlmostEqual(float(pt['latitude']), -6.0)

    def test_dataset_para_tabela_tem_colunas_esperadas(self):
        ds = _dataset_sintetico()
        df = proc.dataset_para_tabela(ds, local='Araguatins', centre='ECMWF', system='SEAS5',
                                       lat=-5.65, lon=-48.12)
        esperadas = {'local', 'init_date', 'target_month', 'lead', 'centre', 'system',
                     'member', 'forecast_prec_mm'}
        self.assertTrue(esperadas.issubset(set(df.columns)))
        self.assertTrue((df['local'] == 'Araguatins').all())

    def test_dataset_para_tabela_produz_um_membro_por_linha(self):
        ds = _dataset_sintetico(leads=(1, 2, 3), n_membros=5)
        df = proc.dataset_para_tabela(ds, local='X', centre='ECMWF', system='SEAS5', lat=-6.0, lon=-48.0)
        self.assertEqual(len(df), 3 * 5)   # 3 leads * 5 membros (1 init_date)
        self.assertEqual(sorted(df['member'].unique()), [0, 1, 2, 3, 4])

    def test_target_month_da_tabela_bate_com_leadtime_para_mes_alvo(self):
        ds = _dataset_sintetico(init_dates=('2018-09-01',), leads=(1, 2, 3, 4, 5, 6))
        df = proc.dataset_para_tabela(ds, local='X', centre='ECMWF', system='SEAS5', lat=-6.0, lon=-48.0)
        for _, row in df.iterrows():
            esperado = cu.leadtime_para_mes_alvo(pd.Period(row['init_date'], 'M'), row['lead'])
            self.assertEqual(pd.Period(row['target_month'], 'M'), esperado)

    def test_processar_municipios_usa_coordenadas_do_municipio_certo(self):
        # grade regular monotônica (como a grade real do C3S) cobrindo os 3 municípios
        ds = _dataset_sintetico(lats=(-6.5, -6.0, -5.5), lons=(-48.5, -48.0, -47.5))
        df = proc.processar_municipios(ds, 'ECMWF', 'SEAS5', municipios=['Ananas', 'Araguatins'])
        self.assertEqual(set(df['local'].unique()), {'Ananas', 'Araguatins'})


# ══════════════════════════════════════════════════════════════════════════
# Teste 5 — climatologia leakage-safe
# ══════════════════════════════════════════════════════════════════════════

class ClimatologiaLeakageTestCase(unittest.TestCase):

    def _obs(self):
        anos = list(range(2000, 2020))
        linhas = []
        for a in anos:
            for m in range(1, 13):
                linhas.append({'local': 'Ananas', 'ym': pd.Period(f'{a}-{m:02d}', 'M'),
                                'prec': 100 + 10 * np.sin(m) + (a - 2000) * 0.5})
        return pd.DataFrame(linhas)

    def test_climatologia_nao_usa_dado_do_proprio_mes_da_origem_nem_posterior(self):
        obs = self._obs()
        origem = pd.Period('2010-06', 'M')
        media, p20, p80 = hc.climatologia_ate_origem(obs, 'Ananas', origem, mes_alvo=6)
        manual = obs[(obs['local'] == 'Ananas') & (obs['ym'] < origem) &
                      (obs['ym'].apply(lambda p: p.month) == 6)]['prec'].mean()
        self.assertAlmostEqual(media, manual, places=6)

    def test_climatologia_muda_se_futuro_for_contaminado(self):
        """Contaminar só o FUTURO (ym >= origem) com valor absurdo não
        pode mudar a climatologia calculada."""
        obs = self._obs()
        origem = pd.Period('2010-06', 'M')
        media_normal, _, _ = hc.climatologia_ate_origem(obs, 'Ananas', origem, mes_alvo=6)

        obs_contaminada = obs.copy()
        mask_futuro = obs_contaminada['ym'] >= origem
        obs_contaminada.loc[mask_futuro, 'prec'] = 999999.0
        media_contaminada, _, _ = hc.climatologia_ate_origem(obs_contaminada, 'Ananas', origem, mes_alvo=6)

        self.assertAlmostEqual(media_normal, media_contaminada, places=6)

    def test_p20_menor_que_p80(self):
        obs = self._obs()
        origem = pd.Period('2015-03', 'M')
        media, p20, p80 = hc.climatologia_ate_origem(obs, 'Ananas', origem, mes_alvo=3)
        self.assertLess(p20, p80)


# ══════════════════════════════════════════════════════════════════════════
# Teste 4 — bias correction nunca usa dado futuro
# ══════════════════════════════════════════════════════════════════════════

class BiasCorrectionTestCase(unittest.TestCase):

    def test_bias_medio_so_usa_init_date_anterior_a_origem(self):
        forecasts = pd.DataFrame({
            'local': ['X'] * 4, 'lead': [2] * 4,
            'init_date': [pd.Period('2018-06', 'M'), pd.Period('2019-06', 'M'),
                          pd.Period('2020-06', 'M'), pd.Period('2021-06', 'M')],
            'target_month': [pd.Period('2018-07', 'M'), pd.Period('2019-07', 'M'),
                              pd.Period('2020-07', 'M'), pd.Period('2021-07', 'M')],
            'ensemble_mean': [100.0, 100.0, 999.0, 100.0],   # 2020 é um outlier absurdo
        })
        obs = pd.DataFrame({'local': ['X'] * 4,
                             'target_month': forecasts['target_month'],
                             'prec': [90.0, 90.0, 90.0, 90.0]})
        # origem = 2020-06: só 2018 e 2019 (init_date < origem) devem entrar
        bias = hc.bias_medio_ate_origem(forecasts, obs, 'X', pd.Period('2020-06', 'M'), mes_alvo_calendario=7, lead=2)
        self.assertAlmostEqual(bias, 10.0, places=6)   # (100-90 + 100-90)/2, sem o outlier de 2020/2021

    def test_bias_nao_inclui_a_propria_origem(self):
        forecasts = pd.DataFrame({
            'local': ['X'] * 2, 'lead': [2] * 2,
            'init_date': [pd.Period('2020-06', 'M'), pd.Period('2021-06', 'M')],
            'target_month': [pd.Period('2020-07', 'M'), pd.Period('2021-07', 'M')],
            'ensemble_mean': [500.0, 500.0],
        })
        obs = pd.DataFrame({'local': ['X'] * 2, 'target_month': forecasts['target_month'], 'prec': [0.0, 0.0]})
        bias = hc.bias_medio_ate_origem(forecasts, obs, 'X', pd.Period('2020-06', 'M'), mes_alvo_calendario=7, lead=2)
        self.assertIsNone(bias)   # nenhum init_date < 2020-06 disponível


# ══════════════════════════════════════════════════════════════════════════
# Teste 6 — ensemble statistics
# ══════════════════════════════════════════════════════════════════════════

class EnsembleStatsTestCase(unittest.TestCase):

    def test_estatisticas_batem_com_numpy(self):
        v = [10, 20, 30, 40, 50]
        r = hc.estatisticas_ensemble(v)
        self.assertAlmostEqual(r['mean'], 30.0)
        self.assertAlmostEqual(r['median'], 30.0)
        self.assertAlmostEqual(r['p10'], float(np.percentile(v, 10)))
        self.assertAlmostEqual(r['p90'], float(np.percentile(v, 90)))
        self.assertLessEqual(r['p10'], r['p25'])
        self.assertLessEqual(r['p75'], r['p90'])

    def test_lida_com_nan(self):
        v = [10, np.nan, 30]
        r = hc.estatisticas_ensemble(v)
        self.assertAlmostEqual(r['mean'], 20.0)


# ══════════════════════════════════════════════════════════════════════════
# Teste 7 — probabilidade P20/P80 (e terciles)
# ══════════════════════════════════════════════════════════════════════════

class ProbabilidadeTestCase(unittest.TestCase):

    def test_probabilidade_abaixo_bate_com_fracao_manual(self):
        v = [10, 20, 30, 40, 50]
        p = hc.probabilidade_evento(v, limiar=25, direcao='abaixo')
        self.assertAlmostEqual(p, 2 / 5)   # 10, 20 < 25

    def test_probabilidade_acima(self):
        v = [10, 20, 30, 40, 50]
        p = hc.probabilidade_evento(v, limiar=25, direcao='acima')
        self.assertAlmostEqual(p, 3 / 5)   # 30,40,50 > 25

    def test_probabilidade_nao_vem_de_um_unico_membro(self):
        """Ensemble com 1 membro só ainda funciona (fração 0 ou 1), mas
        o CÁLCULO usa sempre o array inteiro de membros, nunca hardcoded
        para pegar members[0]."""
        import inspect
        src = inspect.getsource(hc.probabilidade_evento)
        self.assertNotIn('[0]', src)

    def test_probabilidade_terciles_soma_1(self):
        v = list(range(1, 101))
        t1, t2 = np.percentile(v, [33.33, 66.67])
        pa, pn, pc = hc.probabilidade_terciles(v, t1, t2)
        self.assertAlmostEqual(pa + pn + pc, 1.0, places=6)


# ══════════════════════════════════════════════════════════════════════════
# Teste 8 — Brier Score
# ══════════════════════════════════════════════════════════════════════════

class BrierScoreTestCase(unittest.TestCase):

    def test_brier_score_previsao_perfeita_e_zero(self):
        bs = hc.brier_score([1.0, 0.0, 1.0], [1, 0, 1])
        self.assertAlmostEqual(bs, 0.0)

    def test_brier_score_previsao_oposta_e_um(self):
        bs = hc.brier_score([0.0, 1.0], [1, 0])
        self.assertAlmostEqual(bs, 1.0)

    def test_brier_score_climatologia_fixa(self):
        # previsão constante 1/3 (climatologia de tercil), eventos mistos
        bs = hc.brier_score([1 / 3] * 3, [1, 0, 0])
        esperado = np.mean([(1 / 3 - 1) ** 2, (1 / 3 - 0) ** 2, (1 / 3 - 0) ** 2])
        self.assertAlmostEqual(bs, esperado, places=6)

    def test_brier_skill_score_positivo_quando_modelo_melhor(self):
        bss = hc.brier_skill_score(bs_modelo=0.1, bs_climatologia=0.2)
        self.assertGreater(bss, 0)

    def test_rpss_previsao_perfeita_e_positivo(self):
        probs_perfeitas = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        tercis_obs = [0, 1, 2]
        probs_clim = [[1 / 3, 1 / 3, 1 / 3]] * 3
        r = hc.rpss(probs_perfeitas, tercis_obs, probs_clim)
        self.assertAlmostEqual(r, 1.0, places=6)


# ══════════════════════════════════════════════════════════════════════════
# Teste 9 — cache
# ══════════════════════════════════════════════════════════════════════════

class VerificarRedeTestCase(unittest.TestCase):
    """Regressão de um bug real encontrado nesta sessão: um socket TCP+TLS
    cru dá falso-positivo de 'rede alcançável' porque o proxy de egress
    faz interceptação TLS e só bloqueia na camada HTTP seguinte (403 no
    CONNECT). verificar_rede precisa usar urllib (mesmo caminho do
    cdsapi/requests), nunca socket.create_connection cru."""

    def test_verificar_rede_nao_usa_socket_cru(self):
        import inspect
        corpo = inspect.getsource(dl.verificar_rede).split('"""', 2)[-1]   # remove a docstring
        self.assertNotIn('socket.create_connection', corpo)
        self.assertIn('urlopen', corpo)


class CacheTestCase(unittest.TestCase):

    def test_mesmo_request_gera_mesmo_caminho(self):
        req = {'system': '51', 'year': ['2020'], 'month': ['06']}
        c1 = dl.caminho_cache('seasonal-monthly-single-levels', req)
        c2 = dl.caminho_cache('seasonal-monthly-single-levels', dict(req))
        self.assertEqual(c1, c2)

    def test_requests_diferentes_geram_caminhos_diferentes(self):
        c1 = dl.caminho_cache('ds', {'year': ['2020']})
        c2 = dl.caminho_cache('ds', {'year': ['2021']})
        self.assertNotEqual(c1, c2)

    def test_cache_fica_dentro_de_data_c3s_cache(self):
        c = dl.caminho_cache('ds', {'a': 1})
        self.assertIn('c3s_cache', str(c))


# ══════════════════════════════════════════════════════════════════════════
# Teste 11 — hindcast/forecast usam o mesmo sistema
# ══════════════════════════════════════════════════════════════════════════

class SistemaCompativelTestCase(unittest.TestCase):

    def test_montar_request_hindcast_e_forecast_usam_mesmo_originating_centre_e_system(self):
        system = ('ECMWF', '51')
        rh = dl.montar_request_hindcast(system, 2020, 6, [10, -50, -10, -40], [1, 2, 3])
        rf = dl.montar_request_forecast(system, 2026, 9, [10, -50, -10, -40], [1, 2, 3])
        self.assertEqual(rh['originating_centre'], rf['originating_centre'])
        self.assertEqual(rh['system'], rf['system'])

    def test_sistema_escolhido_esta_no_catalogo_e_e_verificado(self):
        centro, sistema = cat.SISTEMA_ESCOLHIDO_FASE_2A
        s = cat.sistema_por_nome(centro, sistema)
        self.assertTrue(s.verificado_cruzado)

    def test_sistemas_verificados_tem_pelo_menos_um(self):
        self.assertGreaterEqual(len(cat.sistemas_verificados()), 1)


# ══════════════════════════════════════════════════════════════════════════
# Teste 12 — arquivos grandes não entram no Git
# ══════════════════════════════════════════════════════════════════════════

class GitignoreTestCase(unittest.TestCase):

    def test_cache_dir_esta_no_gitignore(self):
        texto = (ROOT / '.gitignore').read_text(encoding='utf-8')
        self.assertIn('data/c3s_cache/', texto)

    def test_cache_dir_e_onde_grib_realmente_cai(self):
        """Nesta branch mínima (claude/c3s-poc-integration) o .gitignore
        só tem as 3 entradas pedidas (.cdsapirc, data/c3s_cache/,
        artifacts/) — sem *.grib/*.nc genéricos. A proteção real contra
        commitar um GRIB/NetCDF é indireta: c3s_download.py sempre grava
        em CACHE_DIR (data/c3s_cache/), que está ignorado; aqui só
        confirmamos que esse é de fato o destino, não um caminho solto
        na raiz do repo."""
        import c3s_download as dl
        self.assertEqual(dl.CACHE_DIR, ROOT / 'data' / 'c3s_cache')
        texto = (ROOT / '.gitignore').read_text(encoding='utf-8')
        self.assertIn('data/c3s_cache/', texto)

    def test_nenhum_arquivo_grib_ou_nc_esta_rastreado_pelo_git(self):
        import subprocess
        r = subprocess.run(['git', 'ls-files', '*.grib', '*.grib2', '*.nc'],
                            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), '', f"arquivos grandes rastreados pelo git: {r.stdout}")


# ══════════════════════════════════════════════════════════════════════════
# Credenciais — nunca commitadas, e o módulo nunca as lê/imprime.
# ══════════════════════════════════════════════════════════════════════════

class CredenciaisTestCase(unittest.TestCase):

    def test_verificar_credenciais_nao_le_conteudo_da_chave(self):
        import inspect
        src = inspect.getsource(dl.verificar_credenciais) + inspect.getsource(dl._credenciais_por_env)
        self.assertNotIn('print(', src)

    def test_nenhum_arquivo_do_modulo_c3s_contem_token_real(self):
        """Não busca a palavra 'key' (aparece no docstring como exemplo
        de formato, com um placeholder) — busca o FORMATO de um token
        real do CDS (UUID: 8-4-4-4-12 hex), que nunca deveria aparecer
        aqui de verdade."""
        import re
        padrao_uuid = re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
                                  r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b')
        for nome in ['c3s_download.py', 'c3s_catalogo.py', '_c3s_utils.py']:
            texto = (ROOT / 'scripts' / nome).read_text(encoding='utf-8')
            self.assertIsNone(padrao_uuid.search(texto), f"possível token real em {nome}")


if __name__ == '__main__':
    unittest.main()
