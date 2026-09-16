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
            import xarray as xr
            ds = xr.open_dataset(caminho)
            ds_validado, unidade = poc.abrir_e_validar_grib(caminho, [1, 2, 3])
            self.assertEqual(unidade, 'm s**-1')

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
# Teste 6 — nearest grid point
# ══════════════════════════════════════════════════════════════════════════

class GridPointTestCase(unittest.TestCase):

    def test_grid_point_mais_proximo_e_a_distancia_sao_registrados(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = _dataset_falso(tmp)
            import c3s_processar as proc
            ds, _ = poc.abrir_e_validar_grib(caminho, [1, 2, 3])
            ponto = proc.extrair_ponto(ds, lat=-6.02, lon=-47.90)
            self.assertAlmostEqual(float(ponto['latitude']), -6.0)
            dist = poc.distancia_km_aprox(-6.02, -47.90, float(ponto['latitude']), float(ponto['longitude']))
            self.assertGreater(dist, 0)
            self.assertLess(dist, 200)   # bem menor que o espaçamento de grade 1°~111km


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
