#!/usr/bin/env python3
"""
tests/test_c3s_poc.py — regressão da orquestração da prova de conceito
C3S (scripts/c3s_poc.py) e do workflow .github/workflows/c3s_poc.yml.

Cobre a Seção 13 da tarefa (10 itens). Tudo offline — nenhum teste
baixa nada nem precisa de credencial CDS real.

Roda com:
    python -m unittest tests.test_c3s_poc -v
"""

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import xarray as xr
import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import c3s_poc as poc  # noqa: E402
import c3s_download as dl  # noqa: E402

WORKFLOW_PATH = ROOT / '.github' / 'workflows' / 'c3s_poc.yml'


# ══════════════════════════════════════════════════════════════════════════
# Teste 1 — criação segura do .cdsapirc (feita pelo WORKFLOW, não pelo
# script Python — aqui testamos que o YAML do workflow faz isso com
# permissão restrita e nunca imprime o secret).
# ══════════════════════════════════════════════════════════════════════════

class CdsapircSeguraTestCase(unittest.TestCase):

    def test_workflow_escreve_cdsapirc_com_chmod_restrito(self):
        texto = WORKFLOW_PATH.read_text(encoding='utf-8')
        self.assertIn('.cdsapirc', texto)
        self.assertIn('chmod', texto)

    def test_workflow_nunca_imprime_o_secret(self):
        texto = WORKFLOW_PATH.read_text(encoding='utf-8')
        for linha in texto.split('\n'):
            baixo = linha.lower().strip()
            if 'secrets.cds_api_key' in baixo:
                # a única forma aceitável de usar o secret é substituí-lo
                # direto num arquivo/env — nunca dentro de um echo/cat/print
                self.assertFalse(baixo.startswith('echo') and 'cdsapirc' not in baixo,
                                  f"linha suspeita: {linha}")
                self.assertNotIn('cat $home/.cdsapirc', baixo)
                self.assertNotIn('cat ~/.cdsapirc', baixo)

    def test_cdsapirc_esta_no_gitignore(self):
        texto = (ROOT / '.gitignore').read_text(encoding='utf-8')
        self.assertIn('.cdsapirc', texto)


# ══════════════════════════════════════════════════════════════════════════
# Teste 2 — secret ausente falha com mensagem clara, sem mostrar conteúdo
# ══════════════════════════════════════════════════════════════════════════

class SecretAusenteTestCase(unittest.TestCase):

    def test_workflow_tem_pre_checagem_de_secret(self):
        texto = WORKFLOW_PATH.read_text(encoding='utf-8')
        self.assertIn('CDS_API_KEY', texto)
        # deve checar vazio/ausência antes de tentar baixar
        self.assertTrue('-z' in texto or 'if:' in texto,
                         "workflow não parece checar a ausência do secret explicitamente")

    def test_rodar_falha_com_mensagem_clara_sem_credenciais(self, ):
        import unittest.mock as mock
        with mock.patch.object(dl, 'verificar_acesso',
                                return_value={'credenciais_configuradas': False, 'rede_alcancavel': True,
                                              'pacote_cdsapi_instalado': True, 'pronto_para_download_real': False}):
            with self.assertRaises(SystemExit) as ctx:
                poc.rodar('Ananas', 2015, 1, [1, 2, 3])
            self.assertIn('CDS_API_KEY', str(ctx.exception))


# ══════════════════════════════════════════════════════════════════════════
# Teste 3 — parsing dos inputs
# ══════════════════════════════════════════════════════════════════════════

class ParsingInputsTestCase(unittest.TestCase):

    def test_parsear_leads_lista_simples(self):
        self.assertEqual(poc.parsear_leads('1,2,3'), [1, 2, 3])

    def test_parsear_leads_com_espacos(self):
        self.assertEqual(poc.parsear_leads(' 1 , 2 ,3 '), [1, 2, 3])

    def test_parsear_leads_invalido_levanta_erro(self):
        with self.assertRaises(ValueError):
            poc.parsear_leads('1,x,3')

    def test_parsear_leads_zero_levanta_erro(self):
        with self.assertRaises(ValueError):
            poc.parsear_leads('0,1')

    def test_normalizar_municipio_aceita_chave_e_nome_de_exibicao(self):
        self.assertEqual(poc.normalizar_municipio('Ananas'), 'Ananas')
        self.assertEqual(poc.normalizar_municipio('Ananás'), 'Ananas')
        self.assertEqual(poc.normalizar_municipio('São Bento do Tocantins'), 'Sao_Bento_do_Tocantins')

    def test_normalizar_municipio_desconhecido_levanta_erro(self):
        with self.assertRaises(ValueError):
            poc.normalizar_municipio('Palmas')


# ══════════════════════════════════════════════════════════════════════════
# Teste 4 — leads 1,2,3 -> target_month corretos
# ══════════════════════════════════════════════════════════════════════════

class Leads123TestCase(unittest.TestCase):

    def test_leads_1_2_3_mapeiam_para_jan_fev_mar(self):
        from _c3s_utils import leadtime_para_mes_alvo
        init = pd.Period('2015-01', 'M')
        alvos = [leadtime_para_mes_alvo(init, L) for L in [1, 2, 3]]
        self.assertEqual([str(a) for a in alvos], ['2015-01', '2015-02', '2015-03'])


# ══════════════════════════════════════════════════════════════════════════
# Dataset sintético "real" — mesma forma de tests/test_c3s.py, reusado
# para validar abrir_e_validar_grib / plausibilidade / grid point.
# ══════════════════════════════════════════════════════════════════════════

def _dataset_falso(tmpdir, unidade='m s**-1', com_membro=True, leads=(1, 2, 3), valor_tprate=1.5e-8):
    rng = np.random.RandomState(3)
    times = pd.to_datetime(['2015-01-01'])
    n_membros = 5 if com_membro else 1
    lats = [-7.0, -6.0, -5.0]
    lons = [-49.0, -48.0, -47.0]
    shape = (len(times), len(leads), n_membros, len(lats), len(lons)) if com_membro else \
            (len(times), len(leads), len(lats), len(lons))
    data = valor_tprate + rng.normal(0, 1e-9, size=shape)
    dims = ('time', 'forecastMonth', 'number', 'latitude', 'longitude') if com_membro else \
           ('time', 'forecastMonth', 'latitude', 'longitude')
    coords = {'time': times, 'forecastMonth': list(leads), 'latitude': lats, 'longitude': lons}
    if com_membro:
        coords['number'] = list(range(n_membros))
    ds = xr.Dataset({'tprate': (dims, data)}, coords=coords)
    ds['tprate'].attrs['units'] = unidade
    caminho = Path(tmpdir) / 'fake.nc'
    ds.to_netcdf(caminho)
    return caminho


class ConversaoUnidadeMetadataTestCase(unittest.TestCase):
    """Teste 5 — conversão baseada em metadata (não assumida)."""

    def test_unidade_correta_passa(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _dataset_falso(tmp, unidade='m s**-1')
            ds_validado, unidade, esquema, mapa, diag, mpf = poc.abrir_e_validar_grib(caminho, [1, 2, 3])
            self.assertEqual(unidade, 'm s**-1')
            self.assertEqual(esquema, 'leadtime_month')
            self.assertIsNone(mpf)   # esquema A não usa/precisa do mapeamento eccodes

    def test_unidade_errada_falha_explicitamente(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _dataset_falso(tmp, unidade='kg m**-2 s**-1')   # unidade diferente, não tratada
            with self.assertRaises(RuntimeError) as ctx:
                poc.abrir_e_validar_grib(caminho, [1, 2, 3])
            self.assertIn('unidade', str(ctx.exception).lower())

    def test_variavel_ausente_falha_explicitamente(self):
        with tempfile.TemporaryDirectory() as tmp:
            ds = xr.Dataset({'outra_var': (('x',), [1.0])})
            caminho = Path(tmp) / 'sem_tprate.nc'
            ds.to_netcdf(caminho)
            with self.assertRaises(RuntimeError) as ctx:
                poc.abrir_e_validar_grib(caminho, [1, 2, 3])
            self.assertIn('tprate', str(ctx.exception))

    def test_ensemble_ausente_falha_explicitamente(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _dataset_falso(tmp, com_membro=False)
            with self.assertRaises(RuntimeError) as ctx:
                poc.abrir_e_validar_grib(caminho, [1, 2, 3])
            self.assertIn('ensemble', str(ctx.exception).lower())

    def test_leads_diferentes_do_pedido_falha_explicitamente(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _dataset_falso(tmp, leads=(1, 2, 3))
            with self.assertRaises(RuntimeError) as ctx:
                poc.abrir_e_validar_grib(caminho, [1, 2, 3, 4])   # pediu 4 leads, arquivo só tem 3
            self.assertIn('lead', str(ctx.exception).lower())


# ══════════════════════════════════════════════════════════════════════════
# ESQUEMA REAL DO CDS: step + valid_time (3ª execução real do workflow,
# request cd5eba24-a49a-4ee7-ae56-9240aab18516 — cfgrib expôs number/
# time/step/surface/latitude/longitude/valid_time, SEM forecastMonth/
# leadtime_month). Seção 7 da correção: init janeiro, leads 1/2/3,
# virada de ano, step como timedelta64, valid_time ausente falha,
# nº de target months != nº de leads pedidos falha.
# ══════════════════════════════════════════════════════════════════════════

def _dataset_falso_step_valid_time(tmpdir, init_date='2015-01-01', target_months=('2015-01', '2015-02', '2015-03'),
                                    com_membro=True, unidade='m s**-1', step_como_timedelta=True,
                                    valor_tprate=1.5e-8, nome_arquivo='fake_step.nc',
                                    valid_time_e_limite_final=True):
    """`valid_time_e_limite_final=True` (default) reproduz o arquivo REAL
    do CDS: valid_time é o limite final do mês-alvo (início do mês
    seguinte), não o mês-alvo em si — ex. target_month=2015-01 ->
    valid_time=2015-02-01. É deliberadamente a armadilha corrigida nesta
    sessão; por isso `abrir_e_validar_grib` não deriva mais target_month
    de valid_time (ver EsquemaStepValidTimeTestCase abaixo)."""
    rng = np.random.RandomState(4)
    time_val = pd.Timestamp(init_date)
    alvos_p = [pd.Period(m, 'M') for m in target_months]
    if valid_time_e_limite_final:
        valid_times = pd.to_datetime([str((a + 1).start_time.date()) for a in alvos_p])
    else:
        valid_times = pd.to_datetime([f'{m}-01' for m in target_months])
    if step_como_timedelta:
        steps = (valid_times - time_val).values   # timedelta64[ns]
    else:
        steps = ((valid_times - time_val) / pd.Timedelta('1h')).astype('int64').values   # horas, inteiro

    n_steps = len(steps)
    n_membros = 5 if com_membro else 1
    lats = [-7.0, -6.0, -5.0]
    lons = [-49.0, -48.0, -47.0]
    shape = (1, n_steps, n_membros, len(lats), len(lons)) if com_membro else (1, n_steps, len(lats), len(lons))
    data = valor_tprate + rng.normal(0, 1e-9, size=shape)
    dims = ('time', 'step', 'number', 'latitude', 'longitude') if com_membro else ('time', 'step', 'latitude', 'longitude')
    coords = {
        'time': [time_val], 'step': steps, 'latitude': lats, 'longitude': lons,
        'valid_time': (('time', 'step'), valid_times.values.reshape(1, n_steps)),
    }
    if com_membro:
        coords['number'] = list(range(n_membros))
    ds = xr.Dataset({'tprate': (dims, data)}, coords=coords)
    ds['tprate'].attrs['units'] = unidade
    caminho = Path(tmpdir) / nome_arquivo
    ds.to_netcdf(caminho)
    return caminho


def _dataset_falso_so_step_sem_valid_time(tmpdir, leads_como_steps=(1, 2, 3)):
    """Simula um arquivo com 'step' mas SEM 'valid_time' — caso que deve
    falhar explicitamente (nunca assumir que o valor bruto de step é o
    lead mensal)."""
    rng = np.random.RandomState(5)
    n_steps = len(leads_como_steps)
    data = 1.5e-8 + rng.normal(0, 1e-9, size=(1, n_steps, 5, 3, 3))
    ds = xr.Dataset(
        {'tprate': (('time', 'step', 'number', 'latitude', 'longitude'), data)},
        coords={'time': [pd.Timestamp('2015-01-01')], 'step': list(leads_como_steps),
                'number': list(range(5)), 'latitude': [-7.0, -6.0, -5.0], 'longitude': [-49.0, -48.0, -47.0]},
    )
    ds['tprate'].attrs['units'] = 'm s**-1'
    caminho = Path(tmpdir) / 'sem_valid_time.nc'
    ds.to_netcdf(caminho)
    return caminho


def _mapeamento_mock(init_date, target_months, steps_horas=None):
    """Simula o retorno de proc.extrair_mapeamento_temporal_grib (leitura
    eccodes de um GRIB real) — usado para testar a ORQUESTRAÇÃO em
    abrir_e_validar_grib sem precisar de um arquivo GRIB real (os
    fixtures deste arquivo escrevem NetCDF sintético, que eccodes não
    lê). A lógica real de leitura via eccodes/fcmonth/verifyingMonth é
    testada em tests/test_c3s.py::ExtrairMapeamentoTemporalGribTestCase."""
    from _c3s_utils import mes_alvo_para_leadtime
    init_date = pd.Period(init_date, 'M')
    alvos = [pd.Period(m, 'M') for m in target_months]
    if steps_horas is None:
        steps_horas = list(range(1, len(alvos) + 1))
    return {
        step_h: {'fcmonth': mes_alvo_para_leadtime(init_date, alvo),
                 'lead': mes_alvo_para_leadtime(init_date, alvo),
                 'target_month': alvo}
        for step_h, alvo in zip(steps_horas, alvos)
    }


class EsquemaStepValidTimeTestCase(unittest.TestCase):
    """Esquema real do CDS (step+valid_time). `abrir_e_validar_grib` usa
    `proc.extrair_mapeamento_temporal_grib` (eccodes sobre o GRIB real)
    como fonte autoritativa de lead/target_month — aqui essa chamada é
    mockada (ver `_mapeamento_mock`), porque os fixtures deste arquivo
    escrevem NetCDF sintético, não GRIB. O que se testa aqui é a
    ORQUESTRAÇÃO: abrir_e_validar_grib repassa caminho/init_date/
    leads_esperados corretamente, usa o mapeamento retornado (nunca
    deriva de valid_time) e propaga falhas da fonte autoritativa."""

    def test_init_janeiro_leads_1_2_3_mapeiam_jan_fev_mar(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _dataset_falso_step_valid_time(
                tmp, init_date='2015-01-01', target_months=('2015-01', '2015-02', '2015-03'))
            mapeamento = _mapeamento_mock('2015-01', ('2015-01', '2015-02', '2015-03'))
            with mock.patch.object(poc.proc, 'extrair_mapeamento_temporal_grib',
                                    return_value=mapeamento) as m:
                ds, unidade, esquema, mapa, diag, mpf = poc.abrir_e_validar_grib(caminho, [1, 2, 3])
            self.assertEqual(esquema, 'step_valid_time')
            self.assertEqual(mapa, {1: '2015-01', 2: '2015-02', 3: '2015-03'})
            self.assertEqual(mpf, mapeamento)
            m.assert_called_once()
            args, kwargs = m.call_args
            self.assertEqual(args[0], caminho)
            self.assertEqual(pd.Period(args[1], 'M'), pd.Period('2015-01', 'M'))
            self.assertEqual(kwargs.get('leads_esperados'), [1, 2, 3])

    def test_virada_de_ano(self):
        """Init novembro/2014, leads 1,2,3 -> nov/dez/2014 + jan/2015."""
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _dataset_falso_step_valid_time(
                tmp, init_date='2014-11-01', target_months=('2014-11', '2014-12', '2015-01'),
                nome_arquivo='virada.nc')
            mapeamento = _mapeamento_mock('2014-11', ('2014-11', '2014-12', '2015-01'))
            with mock.patch.object(poc.proc, 'extrair_mapeamento_temporal_grib', return_value=mapeamento):
                ds, unidade, esquema, mapa, diag, mpf = poc.abrir_e_validar_grib(caminho, [1, 2, 3])
            self.assertEqual(mapa, {1: '2014-11', 2: '2014-12', 3: '2015-01'})

    def test_step_como_timedelta64(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _dataset_falso_step_valid_time(tmp, step_como_timedelta=True, nome_arquivo='td.nc')
            ds_bruto = xr.open_dataset(caminho)
            self.assertTrue(np.issubdtype(ds_bruto['step'].dtype, np.timedelta64))
            mapeamento = _mapeamento_mock('2015-01', ('2015-01', '2015-02', '2015-03'))
            with mock.patch.object(poc.proc, 'extrair_mapeamento_temporal_grib', return_value=mapeamento):
                ds, unidade, esquema, mapa, diag, mpf = poc.abrir_e_validar_grib(caminho, [1, 2, 3])
            self.assertEqual(sorted(mapa), [1, 2, 3])

    def test_step_como_horas_inteiras_tambem_funciona(self):
        """step como inteiro (horas) em vez de timedelta64 — não afeta
        abrir_e_validar_grib, que nem lê 'step' diretamente nesse
        esquema (só repassa caminho para a fonte autoritativa)."""
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _dataset_falso_step_valid_time(tmp, step_como_timedelta=False, nome_arquivo='horas.nc')
            mapeamento = _mapeamento_mock('2015-01', ('2015-01', '2015-02', '2015-03'))
            with mock.patch.object(poc.proc, 'extrair_mapeamento_temporal_grib', return_value=mapeamento):
                ds, unidade, esquema, mapa, diag, mpf = poc.abrir_e_validar_grib(caminho, [1, 2, 3])
            self.assertEqual(mapa, {1: '2015-01', 2: '2015-02', 3: '2015-03'})

    def test_step_sem_valid_time_falha_explicitamente(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _dataset_falso_so_step_sem_valid_time(tmp)
            with self.assertRaises(KeyError) as ctx:
                poc.abrir_e_validar_grib(caminho, [1, 2, 3])
            self.assertIn('valid_time', str(ctx.exception))

    def test_numero_de_target_months_diferente_do_pedido_falha(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _dataset_falso_step_valid_time(
                tmp, target_months=('2015-01', '2015-02', '2015-03'), nome_arquivo='tres_meses.nc')
            # a fonte autoritativa só encontrou 3 leads; pedimos 5 —
            # abrir_e_validar_grib tem que falhar (mesma checagem que
            # vale para o esquema A).
            mapeamento = _mapeamento_mock('2015-01', ('2015-01', '2015-02', '2015-03'))
            with mock.patch.object(poc.proc, 'extrair_mapeamento_temporal_grib', return_value=mapeamento):
                with self.assertRaises(RuntimeError) as ctx:
                    poc.abrir_e_validar_grib(caminho, [1, 2, 3, 4, 5])   # pediu 5, arquivo só tem 3
            self.assertIn('lead', str(ctx.exception).lower())

    def test_regressao_valid_time_nao_sobrescreve_verifyingmonth(self):
        """Regressão direta do bug real desta sessão: mesmo com valid_time
        do lead 1 apontando para 2015-02-01 (limite final de janeiro —
        comportamento default do fixture, igual ao arquivo real do CDS),
        o resultado tem que vir do mapeamento eccodes (fcmonth/
        verifyingMonth via extrair_mapeamento_temporal_grib), nunca de
        Period(valid_time,'M')."""
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _dataset_falso_step_valid_time(
                tmp, init_date='2015-01-01', target_months=('2015-01', '2015-02', '2015-03'),
                valid_time_e_limite_final=True, nome_arquivo='regressao.nc')
            mapeamento = _mapeamento_mock('2015-01', ('2015-01', '2015-02', '2015-03'))
            with mock.patch.object(poc.proc, 'extrair_mapeamento_temporal_grib', return_value=mapeamento):
                ds, unidade, esquema, mapa, diag, mpf = poc.abrir_e_validar_grib(caminho, [1, 2, 3])
            # confirma a premissa: valid_time do lead 1 (índice 0) É fevereiro,
            # não janeiro — é exatamente a armadilha da correção anterior
            vt_lead1 = pd.Timestamp(ds['valid_time'].isel(time=0, step=0).values)
            self.assertEqual(pd.Period(vt_lead1, 'M'), pd.Period('2015-02', 'M'))
            # mas o resultado usado (via mapeamento eccodes) é janeiro, não fevereiro
            self.assertEqual(mapa[1], '2015-01')

    def test_falha_na_fonte_autoritativa_se_propaga(self):
        """Se extrair_mapeamento_temporal_grib falhar (metadado GRIB
        inconsistente, leads não batem etc.), abrir_e_validar_grib nunca
        engole o erro nem tenta um fallback silencioso."""
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _dataset_falso_step_valid_time(tmp, nome_arquivo='falha.nc')
            with mock.patch.object(poc.proc, 'extrair_mapeamento_temporal_grib',
                                    side_effect=RuntimeError('conflito de metadado GRIB simulado')):
                with self.assertRaises(RuntimeError) as ctx:
                    poc.abrir_e_validar_grib(caminho, [1, 2, 3])
            self.assertIn('conflito de metadado GRIB simulado', str(ctx.exception))

    def test_nao_chama_mais_cross_check_eccodes_removido(self):
        """cross_check_eccodes foi removido de c3s_processar.py (Seção 7
        da correção — substituído pela função uncapped
        extrair_mapeamento_temporal_grib); abrir_e_validar_grib não pode
        mais referenciá-lo."""
        import inspect
        self.assertFalse(hasattr(poc.proc, 'cross_check_eccodes'))
        src = inspect.getsource(poc.abrir_e_validar_grib)
        self.assertNotIn('cross_check_eccodes', src)


# ══════════════════════════════════════════════════════════════════════════
# Teste 6 — nearest grid point
# ══════════════════════════════════════════════════════════════════════════

class GridPointTestCase(unittest.TestCase):

    def test_grid_point_mais_proximo_e_a_distancia_sao_registrados(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _dataset_falso(tmp)
            import c3s_processar as proc
            ds, _, _, _, _, _ = poc.abrir_e_validar_grib(caminho, [1, 2, 3])
            ponto = proc.extrair_ponto(ds, lat=-6.02, lon=-47.90)
            self.assertAlmostEqual(float(ponto['latitude']), -6.0)
            dist = poc.distancia_km_aprox(-6.02, -47.90, float(ponto['latitude']), float(ponto['longitude']))
            self.assertGreater(dist, 0)
            self.assertLess(dist, 200)   # bem menor que o espaçamento de grade 1°~111km


# ══════════════════════════════════════════════════════════════════════════
# buscar_chirps_target_months — regressão do bug real encontrado na
# execução #6: fim do intervalo pedido ao ClimateSERV era o dia 1 do
# último target month, cortando esse mês quase inteiro no agregado
# (março/2015 saiu como 8,6mm em vez de ~200mm). Também cobre a Seção 8:
# validação observacional final (1 valor por mês, sem NaN, sem negativo).
# ══════════════════════════════════════════════════════════════════════════

def _serie_chirps(pares):
    """pares: lista de (target_month_str, prec) -> pandas Series indexada
    por Period, no formato que buscar_chirps_target_months monta a partir
    do DataFrame retornado por _buscar_prec_chirps_geom."""
    idx = pd.PeriodIndex([p[0] for p in pares], freq='M')
    return pd.Series([p[1] for p in pares], index=idx, name='prec')


class BuscarChirpsTargetMonthsTestCase(unittest.TestCase):

    def setUp(self):
        # garante que o cache local (data/c3s_observado_chirps_poc.csv)
        # nunca interfere nestes testes — sempre exercitam o caminho de
        # busca ao vivo, que é onde o bug estava.
        self._patch_cache = mock.patch.object(poc, 'CACHE_CHIRPS_POC', Path('/inexistente/nao_existe.csv'))
        self._patch_cache.start()
        self.addCleanup(self._patch_cache.stop)

    def test_intervalo_pedido_cobre_o_mes_final_inteiro(self):
        """Regressão direta (Seção 6 da correção): para target months
        jan/fev/mar de 2015, o intervalo pedido ao ClimateSERV tem que
        ir até 03/31/2015 — não 03/01/2015 (o bug real). Com a
        implementação antiga (fim = dia 1 do mês final) este teste falha."""
        target_months = [pd.Period('2015-01', 'M'), pd.Period('2015-02', 'M'), pd.Period('2015-03', 'M')]
        df_fake = pd.DataFrame({'ano': [2015, 2015, 2015], 'mes': [1, 2, 3],
                                 'prec': [335.7, 259.9, 197.1], 'fonte': ['CHIRPS'] * 3})
        with mock.patch.object(poc, '_buscar_prec_chirps_geom', return_value=df_fake) as m:
            resultado = poc.buscar_chirps_target_months('Sao_Bento_do_Tocantins', target_months)
        args, kwargs = m.call_args
        ini, fim = args[0], args[1]
        self.assertEqual(ini, '01/01/2015')
        self.assertEqual(fim, '03/31/2015')   # não '03/01/2015'
        self.assertEqual(resultado[pd.Period('2015-03', 'M')], 197.1)

    def test_fevereiro_bissexto_no_intervalo_pedido(self):
        target_months = [pd.Period('2016-01', 'M'), pd.Period('2016-02', 'M')]
        df_fake = pd.DataFrame({'ano': [2016, 2016], 'mes': [1, 2], 'prec': [300.0, 200.0],
                                 'fonte': ['CHIRPS'] * 2})
        with mock.patch.object(poc, '_buscar_prec_chirps_geom', return_value=df_fake) as m:
            poc.buscar_chirps_target_months('Sao_Bento_do_Tocantins', target_months)
        args, kwargs = m.call_args
        self.assertEqual(args[1], '02/29/2016')

    def test_mes_faltando_falha_explicitamente(self):
        target_months = [pd.Period('2015-01', 'M'), pd.Period('2015-02', 'M'), pd.Period('2015-03', 'M')]
        df_fake = pd.DataFrame({'ano': [2015, 2015], 'mes': [1, 2], 'prec': [335.7, 259.9],
                                 'fonte': ['CHIRPS'] * 2})   # março ausente
        with mock.patch.object(poc, '_buscar_prec_chirps_geom', return_value=df_fake):
            with self.assertRaises(RuntimeError) as ctx:
                poc.buscar_chirps_target_months('Sao_Bento_do_Tocantins', target_months)
        self.assertIn('2015-03', str(ctx.exception))

    def test_mes_duplicado_falha_explicitamente(self):
        r = _serie_chirps([('2015-01', 335.7), ('2015-01', 999.0)])
        with self.assertRaises(RuntimeError) as ctx:
            poc._extrair_chirps_validado(r, [pd.Period('2015-01', 'M')])
        self.assertIn('2015-01', str(ctx.exception))

    def test_nan_falha_explicitamente(self):
        r = _serie_chirps([('2015-01', float('nan'))])
        with self.assertRaises(RuntimeError) as ctx:
            poc._extrair_chirps_validado(r, [pd.Period('2015-01', 'M')])
        self.assertIn('NaN', str(ctx.exception))

    def test_negativo_falha_explicitamente(self):
        r = _serie_chirps([('2015-01', -5.0)])
        with self.assertRaises(RuntimeError) as ctx:
            poc._extrair_chirps_validado(r, [pd.Period('2015-01', 'M')])
        self.assertIn('negativa', str(ctx.exception).lower())

    def test_valor_valido_unico_passa(self):
        r = _serie_chirps([('2015-01', 197.1)])
        resultado = poc._extrair_chirps_validado(r, [pd.Period('2015-01', 'M')])
        self.assertEqual(resultado, {pd.Period('2015-01', 'M'): 197.1})

    def test_evento_extremo_nao_e_bloqueado(self):
        """Seção 8: nenhum limite climatológico rígido — um valor baixo
        mas fisicamente válido (>=0, não-NaN) tem que passar."""
        r = _serie_chirps([('2015-03', 8.6)])
        resultado = poc._extrair_chirps_validado(r, [pd.Period('2015-03', 'M')])
        self.assertEqual(resultado[pd.Period('2015-03', 'M')], 8.6)


# ══════════════════════════════════════════════════════════════════════════
# Teste 7 — output schema
# ══════════════════════════════════════════════════════════════════════════

class OutputSchemaTestCase(unittest.TestCase):

    def test_schema_raw_e_summary_documentado_no_codigo(self):
        import inspect
        import c3s_processar as proc
        # 'member' vem de c3s_processar.dataset_para_tabela (reaproveitado
        # por poc.rodar, não retiptado) — já coberto em
        # tests/test_c3s.py::ProcessarTestCase; aqui checamos as colunas
        # que poc.rodar adiciona/renomeia por conta própria.
        self.assertIn('member', inspect.getsource(proc._linha))
        src = inspect.getsource(poc.rodar)
        for coluna in ['init_date', 'lead', 'target_month', 'c3s_prec_mm', 'chirps_prec_mm']:
            self.assertIn(coluna, src)
        for coluna in ['ens_mean', 'ens_median', 'p10', 'p25', 'p75', 'p90']:
            self.assertIn(coluna, src)


# ══════════════════════════════════════════════════════════════════════════
# Teste 8 — cache ignorado pelo Git (reforça o teste já existente em
# test_c3s.py, mas também cobre 'artifacts/' não indo para o cache)
# ══════════════════════════════════════════════════════════════════════════

class CacheGitignoreTestCase(unittest.TestCase):

    def test_c3s_cache_no_gitignore(self):
        texto = (ROOT / '.gitignore').read_text(encoding='utf-8')
        self.assertIn('data/c3s_cache/', texto)

    def test_artifacts_dir_usado_pelo_script_nao_e_o_cache_dir(self):
        self.assertNotEqual(poc.ARTIFACTS_DIR, dl.CACHE_DIR)


# ══════════════════════════════════════════════════════════════════════════
# Teste 9 — secret nunca presente em nenhum output
# ══════════════════════════════════════════════════════════════════════════

class SecretNuncaEmOutputTestCase(unittest.TestCase):

    def test_metadata_nao_contem_campo_de_credencial(self):
        import inspect
        src = inspect.getsource(poc.rodar)
        proibidos = ['api_key', 'cdsapi_key', 'token', 'secrets.']
        # 'request_cds' é incluído no metadata — garantir que o dict de
        # request nunca carrega credencial (cdsapi injeta isso por fora,
        # via ~/.cdsapirc, nunca no corpo do request)
        import c3s_download as dl
        req = dl.montar_request_hindcast(('ecmwf', '51'), 2015, 1, [1, 1, 1, 1], [1])
        for chave in req:
            self.assertNotIn('key', chave.lower())
            self.assertNotIn('token', chave.lower())

    def test_workflow_nao_expoe_secret_como_output_de_step(self):
        texto = WORKFLOW_PATH.read_text(encoding='utf-8')
        self.assertNotIn('echo "::set-output name=key', texto)
        self.assertNotIn('GITHUB_OUTPUT" <<< "${{ secrets', texto)


# ══════════════════════════════════════════════════════════════════════════
# Teste 10 — workflow não tem cron / é manual
# ══════════════════════════════════════════════════════════════════════════

class WorkflowManualTestCase(unittest.TestCase):

    def setUp(self):
        self.spec = yaml.safe_load(WORKFLOW_PATH.read_text(encoding='utf-8'))

    def test_trigger_e_workflow_dispatch(self):
        # YAML: chave 'on' pode virar bool True ao carregar — normaliza
        gatilhos = self.spec.get('on', self.spec.get(True))
        self.assertIn('workflow_dispatch', gatilhos)

    def test_nao_tem_cron(self):
        gatilhos = self.spec.get('on', self.spec.get(True))
        self.assertNotIn('schedule', gatilhos)

    def test_inputs_esperados_presentes(self):
        gatilhos = self.spec.get('on', self.spec.get(True))
        inputs = gatilhos['workflow_dispatch'].get('inputs', {})
        for nome in ['municipio', 'init_year', 'init_month', 'leads']:
            self.assertIn(nome, inputs)

    def test_defaults_seguros(self):
        gatilhos = self.spec.get('on', self.spec.get(True))
        inputs = gatilhos['workflow_dispatch']['inputs']
        self.assertIn('Bento', inputs['municipio']['default'])
        self.assertEqual(str(inputs['init_month']['default']), '01')
        self.assertEqual(inputs['leads']['default'], '1,2,3')
        ano_default = int(inputs['init_year']['default'])
        self.assertTrue(1993 <= ano_default <= 2016,
                         "init_year default deve cair dentro do período de hindcast do SEAS5")


if __name__ == '__main__':
    unittest.main()
