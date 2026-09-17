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
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
# intervalo_mensal_chirps — regressão do bug real: fim do intervalo era o
# dia 1 do mês final (deixava o último target month incompleto no
# agregado do ClimateSERV), tem que ser o ÚLTIMO DIA REAL desse mês.
# ══════════════════════════════════════════════════════════════════════════

class IntervaloMensalChirpsTestCase(unittest.TestCase):

    def test_jan_a_marco_2015_fim_e_31_de_marco(self):
        ini, fim = cu.intervalo_mensal_chirps(2015, 1, 2015, 3)
        self.assertEqual(ini, '01/01/2015')
        self.assertEqual(fim, '03/31/2015')

    def test_fevereiro_2015_comum_fim_dia_28(self):
        ini, fim = cu.intervalo_mensal_chirps(2015, 2, 2015, 2)
        self.assertEqual(fim, '02/28/2015')

    def test_fevereiro_2016_bissexto_fim_dia_29(self):
        ini, fim = cu.intervalo_mensal_chirps(2016, 2, 2016, 2)
        self.assertEqual(fim, '02/29/2016')

    def test_abril_fim_dia_30(self):
        ini, fim = cu.intervalo_mensal_chirps(2020, 4, 2020, 4)
        self.assertEqual(fim, '04/30/2020')

    def test_dezembro_fim_dia_31(self):
        ini, fim = cu.intervalo_mensal_chirps(2020, 12, 2020, 12)
        self.assertEqual(fim, '12/31/2020')

    def test_dia_final_nunca_hardcoded_em_31(self):
        """Se alguém 'simplificar' para sempre usar dia 31, este teste
        pega — fevereiro e abril não podem terminar em 31."""
        import inspect
        src = inspect.getsource(cu.intervalo_mensal_chirps)
        self.assertNotIn("'31'", src)
        self.assertNotIn('/31/', src)
        self.assertIn('monthrange', src)


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


def _dataset_step_valid_time(init_date='2015-01-01', target_months=('2015-01', '2015-02', '2015-03'),
                              n_membros=5, lats=(-6.0, -5.5), lons=(-48.0, -47.5), valor_tprate=2e-8, seed=6,
                              valid_time_e_limite_final=True):
    """Esquema B (Seção 7): o que o arquivo REAL do CDS mostrou —
    number/time/step/latitude/longitude/valid_time, SEM forecastMonth/
    leadtime_month.

    `valid_time_e_limite_final=True` (default, reproduz o arquivo real):
    valid_time é o LIMITE FINAL do mês-alvo (início do mês seguinte) —
    ex. target_month=2015-01 -> valid_time=2015-02-01. Isso é
    deliberado: é exatamente a armadilha que produziu o bug de +1 mês
    corrigido nesta sessão (Period(valid_time,'M') != target_month).
    `step` é o intervalo em horas entre `time` (init) e esse valid_time.
    """
    rng = np.random.RandomState(seed)
    time_val = pd.Timestamp(init_date)
    alvos = [pd.Period(m, 'M') for m in target_months]
    if valid_time_e_limite_final:
        valid_times = pd.to_datetime([str((a + 1).start_time.date()) for a in alvos])
    else:
        valid_times = pd.to_datetime([f'{m}-01' for m in target_months])
    steps = (valid_times - time_val).values   # timedelta64[ns] — nunca lido como número bruto
    n_steps = len(steps)
    data = valor_tprate + rng.normal(0, 1e-9, size=(1, n_steps, n_membros, len(lats), len(lons)))
    ds = xr.Dataset(
        {'tprate': (('time', 'step', 'number', 'latitude', 'longitude'), data)},
        coords={'time': [time_val], 'step': steps, 'number': list(range(n_membros)),
                'latitude': list(lats), 'longitude': list(lons),
                'valid_time': (('time', 'step'), valid_times.values.reshape(1, n_steps))},
    )
    return ds


def _mapeamento_explicito(init_date, target_months, steps_horas):
    """Constrói o dict `mapeamento_step_fcmonth` que normalmente viria de
    `extrair_mapeamento_temporal_grib` (via eccodes/GRIB real) — usado
    nos testes de `dataset_para_tabela` para não depender de GRIB real
    (ver `ExtrairMapeamentoTemporalGribTestCase` para o eccodes real)."""
    init_date = pd.Period(init_date, 'M')
    alvos = [pd.Period(m, 'M') for m in target_months]
    return {
        step_h: {'fcmonth': cu.mes_alvo_para_leadtime(init_date, alvo), 'lead': cu.mes_alvo_para_leadtime(init_date, alvo),
                 'target_month': alvo}
        for step_h, alvo in zip(steps_horas, alvos)
    }


class EsquemaTemporalStepValidTimeTestCase(unittest.TestCase):
    """Teste 7C — dataset com step+valid_time (esquema real do CDS),
    testado direto em memória (sem GRIB/NetCDF real — ver ressalva no
    topo do arquivo). `dataset_para_tabela` exige um mapeamento explícito
    de step->fcmonth/target_month para este esquema (nunca deriva de
    valid_time diretamente — ver docstring de c3s_processar.py)."""

    def test_detectar_esquema_reconhece_step_valid_time(self):
        ds = _dataset_step_valid_time()
        esquema, nome_dim = proc.detectar_esquema_temporal(ds)
        self.assertEqual(esquema, proc.ESQUEMA_STEP_VALID_TIME)
        self.assertEqual(nome_dim, 'step')

    def test_dataset_para_tabela_usa_mapeamento_explicito_nao_valid_time(self):
        """Regressão do bug real: valid_time é o limite final (mês+1),
        NUNCA o target_month. Aqui valid_time do lead 1 é 2015-02-01
        (fim de janeiro), mas o mapeamento explícito (fonte autoritativa,
        equivalente ao que fcmonth/verifyingMonth diriam) diz lead1 ->
        2015-01 — e é isso que tem que aparecer na tabela, não fevereiro."""
        ds = _dataset_step_valid_time(init_date='2015-01-01', target_months=('2015-01', '2015-02', '2015-03'))
        steps_h = [int(v / np.timedelta64(1, 'h')) for v in ds['step'].values]
        mapeamento = _mapeamento_explicito('2015-01', ('2015-01', '2015-02', '2015-03'), steps_h)

        # confirma a premissa do teste: valid_time do lead 1 NÃO é 2015-01
        vt_lead1 = pd.Timestamp(ds['valid_time'].isel(time=0, step=0).values)
        self.assertEqual(pd.Period(vt_lead1, 'M'), pd.Period('2015-02', 'M'))

        df = proc.dataset_para_tabela(ds, local='X', centre='ECMWF', system='SEAS5', lat=-6.0, lon=-48.0,
                                       mapeamento_step_fcmonth=mapeamento)
        mapa = dict(zip(df['lead'], df['target_month']))
        self.assertEqual(mapa[1], '2015-01')   # e não '2015-02'
        self.assertEqual(mapa[2], '2015-02')
        self.assertEqual(mapa[3], '2015-03')

    def test_forecastMonth_e_step_valid_time_dao_o_mesmo_resultado(self):
        """Os dois esquemas, com o mesmo init/leads, têm que produzir a
        mesma tabela lead<->target_month — é a mesma convenção, só
        codificada de formas diferentes pelo cfgrib."""
        ds_a = _dataset_sintetico(init_dates=('2015-01-01',), leads=(1, 2, 3))
        ds_b = _dataset_step_valid_time(init_date='2015-01-01', target_months=('2015-01', '2015-02', '2015-03'))
        steps_h = [int(v / np.timedelta64(1, 'h')) for v in ds_b['step'].values]
        mapeamento = _mapeamento_explicito('2015-01', ('2015-01', '2015-02', '2015-03'), steps_h)
        df_a = proc.dataset_para_tabela(ds_a, local='X', centre='ECMWF', system='SEAS5', lat=-6.0, lon=-48.0)
        df_b = proc.dataset_para_tabela(ds_b, local='X', centre='ECMWF', system='SEAS5', lat=-6.0, lon=-48.0,
                                         mapeamento_step_fcmonth=mapeamento)
        self.assertEqual(sorted(df_a['target_month'].unique()), sorted(df_b['target_month'].unique()))
        self.assertEqual(set(zip(df_a['lead'], df_a['target_month'])),
                          set(zip(df_b['lead'], df_b['target_month'])))

    def test_step_sem_valid_time_falha_explicitamente(self):
        ds = xr.Dataset(
            {'tprate': (('time', 'step', 'number', 'latitude', 'longitude'),
                        np.zeros((1, 3, 5, 2, 2)) + 1.5e-8)},
            coords={'time': [pd.Timestamp('2015-01-01')], 'step': [1, 2, 3],
                    'number': list(range(5)), 'latitude': [-6.0, -5.5], 'longitude': [-48.0, -47.5]},
        )
        with self.assertRaises(KeyError) as ctx:
            proc.detectar_esquema_temporal(ds)
        self.assertIn('valid_time', str(ctx.exception))

    def test_dataset_para_tabela_sem_mapeamento_falha_explicitamente(self):
        """Seção 4 da correção: para o esquema step_valid_time,
        mapeamento_step_fcmonth é obrigatório — sem ele, ValueError
        explícito, nunca um fallback silencioso para valid_time."""
        ds = _dataset_step_valid_time()
        with self.assertRaises(ValueError) as ctx:
            proc.dataset_para_tabela(ds, local='X', centre='ECMWF', system='SEAS5', lat=-6.0, lon=-48.0)
        self.assertIn('mapeamento_step_fcmonth', str(ctx.exception))

    def test_dataset_para_tabela_step_fora_do_mapeamento_falha(self):
        """Se o mapeamento não cobre o step presente no dataset, falha
        explícita (KeyError) em vez de adivinhar."""
        ds = _dataset_step_valid_time(init_date='2015-01-01', target_months=('2015-01', '2015-02', '2015-03'))
        with self.assertRaises(KeyError):
            proc.dataset_para_tabela(ds, local='X', centre='ECMWF', system='SEAS5', lat=-6.0, lon=-48.0,
                                      mapeamento_step_fcmonth={})


# ══════════════════════════════════════════════════════════════════════════
# extrair_mapeamento_temporal_grib — fonte autoritativa via eccodes real.
# eccodes é simulado (mock) para não depender de um arquivo GRIB real
# nestes testes offline — só a INTERFACE (codes_grib_new_from_file/
# codes_get/codes_release) é simulada; a lógica de dedup/validação
# testada é a função real de c3s_processar.py.
# ══════════════════════════════════════════════════════════════════════════

def _fake_eccodes_modulo(mensagens):
    """`mensagens`: lista de dicts, uma por 'mensagem GRIB' simulada, com
    as chaves lidas via codes_get ('step', 'fcmonth', 'verifyingMonth').
    Simula N mensagens (uma por membro x lead, como um GRIB real de
    hindcast) que extrair_mapeamento_temporal_grib deve deduplicar."""
    estado = {'indice': 0}

    class _FakeEccodes:
        @staticmethod
        def codes_grib_new_from_file(f):
            if estado['indice'] >= len(mensagens):
                return None
            gid = estado['indice']
            estado['indice'] += 1
            return gid

        @staticmethod
        def codes_get(gid, chave):
            return mensagens[gid][chave]

        @staticmethod
        def codes_release(gid):
            pass

    return _FakeEccodes()


def _mensagens_ensemble(init_date, mapa_lead_step_alvo, n_membros=25):
    """Gera `n_membros` mensagens por lead — reproduz a estrutura real de
    um GRIB de hindcast SEAS5 (25 membros), onde step/fcmonth/
    verifyingMonth se repetem idênticos entre membros do mesmo lead."""
    verifying = {lead: int(f'{alvo.year:04d}{alvo.month:02d}') for lead, (step, alvo) in mapa_lead_step_alvo.items()}
    msgs = []
    for lead, (step, _alvo) in mapa_lead_step_alvo.items():
        for _m in range(n_membros):
            msgs.append({'step': step, 'fcmonth': lead, 'verifyingMonth': verifying[lead]})
    return msgs


class ExtrairMapeamentoTemporalGribTestCase(unittest.TestCase):
    """Testa a fonte autoritativa da correção (Seção 4/7/8 da tarefa):
    lead=fcmonth, target_month=verifyingMonth, deduplicado, validado
    contra leadtime_para_mes_alvo, percorrendo o arquivo inteiro."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix='.grib', delete=False)
        self._tmp.close()
        self.caminho = self._tmp.name

    def tearDown(self):
        Path(self.caminho).unlink(missing_ok=True)

    def _rodar(self, mensagens, init_date='2015-01', leads_esperados=None):
        fake = _fake_eccodes_modulo(mensagens)
        with mock.patch.dict(sys.modules, {'eccodes': fake}):
            return proc.extrair_mapeamento_temporal_grib(self.caminho, init_date, leads_esperados=leads_esperados)

    def test_evidencia_real_lead1_e_janeiro_nao_fevereiro(self):
        """Reproduz literalmente a evidência real desta sessão: init
        2015-01, fcmonth=1, verifyingMonth=201501, step=744h. A
        correção anterior (valid_time=2015-02-01 -> Period='2015-02')
        teria dado fevereiro — aqui tem que dar janeiro."""
        mensagens = [{'step': 744, 'fcmonth': 1, 'verifyingMonth': 201501}]
        mapa = self._rodar(mensagens, init_date='2015-01', leads_esperados=[1])
        self.assertEqual(mapa[744]['lead'], 1)
        self.assertEqual(mapa[744]['target_month'], pd.Period('2015-01', 'M'))
        self.assertNotEqual(mapa[744]['target_month'], pd.Period('2015-02', 'M'))

    def test_25_membros_3_leads_dao_3_combinacoes_unicas(self):
        """Seção 4/7: um arquivo com 25 membros x 3 leads = 75 mensagens
        tem que deduplicar para exatamente 3 combinações — nunca 75 nem
        25."""
        mapa_lead_step_alvo = {
            1: (744, pd.Period('2015-01', 'M')),
            2: (1416, pd.Period('2015-02', 'M')),
            3: (2160, pd.Period('2015-03', 'M')),
        }
        mensagens = _mensagens_ensemble('2015-01', mapa_lead_step_alvo, n_membros=25)
        self.assertEqual(len(mensagens), 75)
        mapa = self._rodar(mensagens, init_date='2015-01', leads_esperados=[1, 2, 3])
        self.assertEqual(len(mapa), 3)
        self.assertEqual(sorted(v['lead'] for v in mapa.values()), [1, 2, 3])
        self.assertEqual(mapa[744]['target_month'], pd.Period('2015-01', 'M'))
        self.assertEqual(mapa[1416]['target_month'], pd.Period('2015-02', 'M'))
        self.assertEqual(mapa[2160]['target_month'], pd.Period('2015-03', 'M'))

    def test_percorre_arquivo_inteiro_nao_so_as_primeiras_mensagens(self):
        """Regressão do bug do diagnóstico antigo (capado em 20
        mensagens): lead 3 só aparece na mensagem 51 em diante (25
        membros de lead1 + 25 de lead2 antes) — tem que ser encontrado."""
        mapa_lead_step_alvo = {
            1: (744, pd.Period('2015-01', 'M')),
            2: (1416, pd.Period('2015-02', 'M')),
            3: (2160, pd.Period('2015-03', 'M')),
        }
        mensagens = _mensagens_ensemble('2015-01', mapa_lead_step_alvo, n_membros=25)
        mapa = self._rodar(mensagens, init_date='2015-01', leads_esperados=[1, 2, 3])
        self.assertIn(2160, mapa)
        self.assertEqual(mapa[2160]['lead'], 3)

    def test_virada_de_ano(self):
        mensagens = [{'step': 3624, 'fcmonth': 6, 'verifyingMonth': 202004}]
        mapa = self._rodar(mensagens, init_date='2019-11', leads_esperados=[6])
        self.assertEqual(mapa[3624]['target_month'], pd.Period('2020-04', 'M'))

    def test_conflito_fcmonth_verifyingmonth_falha(self):
        """fcmonth=1 implica target_month=2015-01 pela convenção (lead 1 =
        mês de inicialização), mas a mensagem diz verifyingMonth=201502 —
        metadado GRIB inconsistente, tem que falhar, nunca aceitar."""
        mensagens = [{'step': 744, 'fcmonth': 1, 'verifyingMonth': 201502}]
        with self.assertRaises(RuntimeError) as ctx:
            self._rodar(mensagens, init_date='2015-01', leads_esperados=[1])
        self.assertIn('Conflito', str(ctx.exception))

    def test_step_com_combinacoes_conflitantes_falha(self):
        mensagens = [{'step': 744, 'fcmonth': 1, 'verifyingMonth': 201501},
                      {'step': 744, 'fcmonth': 2, 'verifyingMonth': 201502}]
        with self.assertRaises(RuntimeError) as ctx:
            self._rodar(mensagens, init_date='2015-01', leads_esperados=None)
        self.assertIn('step=744h', str(ctx.exception))

    def test_leads_encontrados_diferentes_dos_pedidos_falha(self):
        mensagens = [{'step': 744, 'fcmonth': 1, 'verifyingMonth': 201501},
                      {'step': 1416, 'fcmonth': 2, 'verifyingMonth': 201502}]
        with self.assertRaises(RuntimeError) as ctx:
            self._rodar(mensagens, init_date='2015-01', leads_esperados=[1, 2, 3])
        self.assertIn('leads encontrados', str(ctx.exception))

    def test_nenhuma_mensagem_falha(self):
        with self.assertRaises(RuntimeError) as ctx:
            self._rodar([], init_date='2015-01', leads_esperados=[1])
        self.assertIn('nenhuma mensagem', str(ctx.exception))

    def test_nao_usa_valid_time_nenhuma_vez(self):
        """A função não deve sequer tentar ler 'valid_time' via eccodes —
        só step/fcmonth/verifyingMonth (Seção 3)."""
        import inspect
        src = inspect.getsource(proc.extrair_mapeamento_temporal_grib)
        self.assertNotIn("'valid_time'", src)
        self.assertNotIn('"valid_time"', src)


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
