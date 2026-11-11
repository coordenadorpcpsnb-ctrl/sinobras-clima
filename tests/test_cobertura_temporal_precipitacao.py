#!/usr/bin/env python3
"""
tests/test_cobertura_temporal_precipitacao.py — ENSO-COBERTURA:
cobre a correção científica de integridade temporal da precipitação
diária em scripts/_openmeteo.py (schema `daily.time`/
`daily.precipitation_sum`, confirmado e já em uso) e a integração
ponta a ponta da cascata CHIRPS → CHC-Preliminar → Open-Meteo em
scripts/fetch_monthly_data.py, após a correção de scripts/_chirps.py.

A correção de scripts/_chirps.py (identificação diária via
year/month/day confirmada por verificação controlada real; ver
cabeçalho de scripts/_chirps.py) tem sua própria suíte dedicada em
tests/test_chirps_extracao_sintetica.py — este arquivo foca no lado
Open-Meteo e na integração entre as três fontes.

Nenhuma requisição de rede real: `urllib.request.urlopen` e
`climateserv.api.request_data` são sempre mockados (unittest.mock),
igual ao padrão de tests/test_fetch_fallback.py.

Roda com:
    python -m unittest tests.test_cobertura_temporal_precipitacao -v
"""

import json
import sys
import tempfile
import unittest
from calendar import monthrange
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import _chirps                    # noqa: E402
import _openmeteo                 # noqa: E402
import fetch_monthly_data as fmd  # noqa: E402


# ══════════════════════════════════════════════════════════════════
# Helpers — fixtures no schema real/confirmado de cada fonte
# ══════════════════════════════════════════════════════════════════

def _dias_chirps(ano, mes, avg_por_dia=None, dias_presentes=None):
    """Monta registros CHIRPS reais (schema confirmado) para os dias
    pedidos (todos do mês, por padrão)."""
    n = monthrange(ano, mes)[1]
    dias_presentes = dias_presentes if dias_presentes is not None else range(1, n + 1)
    fn = avg_por_dia if callable(avg_por_dia) else (lambda d: avg_por_dia if avg_por_dia is not None else 1.0)
    out = []
    for d in dias_presentes:
        epoch = int(datetime(ano, mes, d, tzinfo=timezone.utc).timestamp())
        out.append({'year': ano, 'month': mes, 'day': d,
                     'date': f'{mes:02d}/{d:02d}/{ano}', 'epochTime': epoch,
                     'value': {'avg': fn(d)}})
    return out


def _openmeteo_payload(ano, mes, valor_por_dia=None, dias_presentes=None):
    """Monta o JSON daily.time/daily.precipitation_sum para os dias
    pedidos do mês (todos, por padrão)."""
    n = monthrange(ano, mes)[1]
    dias_presentes = dias_presentes if dias_presentes is not None else range(1, n + 1)
    fn = valor_por_dia if callable(valor_por_dia) else (lambda d: valor_por_dia if valor_por_dia is not None else 1.0)
    tempos = [f'{ano}-{mes:02d}-{d:02d}' for d in dias_presentes]
    valores = [fn(d) for d in dias_presentes]
    return {'daily': {'time': tempos, 'precipitation_sum': valores}}


def _fake_urlopen(payload_dict):
    body = json.dumps(payload_dict).encode('utf-8')
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = body
    cm.__exit__.return_value = False
    return cm


# ══════════════════════════════════════════════════════════════════
# Open-Meteo — mesma disciplina de cobertura diária do CHIRPS
# ══════════════════════════════════════════════════════════════════

class OpenMeteoCoberturaCompletaTestCase(unittest.TestCase):

    def _rodar(self, payload, ano_ini, mes_ini, ano_fim=None, mes_fim=None):
        ano_fim = ano_fim or ano_ini
        mes_fim = mes_fim or mes_ini
        with patch.object(_openmeteo.urllib.request, 'urlopen',
                           return_value=_fake_urlopen(payload)):
            return _openmeteo.buscar_prec_openmeteo(ano_ini, mes_ini, ano_fim, mes_fim)

    def test_mes_completo_com_chuva_positiva(self):
        payload = _openmeteo_payload(2024, 6, lambda d: float(d))
        df = self._rodar(payload, 2024, 6)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]['prec'], round(sum(range(1, 31)), 1))
        self.assertEqual(df.iloc[0]['fonte'], 'OpenMeteo-ERA5')

    def test_mes_completo_com_dias_legitimos_de_chuva_zero(self):
        payload = _openmeteo_payload(2024, 6, lambda d: 0.0 if d % 2 == 0 else 2.0)
        df = self._rodar(payload, 2024, 6)
        self.assertEqual(len(df), 1)
        esperado = round(sum(0.0 if d % 2 == 0 else 2.0 for d in range(1, 31)), 1)
        self.assertEqual(df.iloc[0]['prec'], esperado)

    def test_dia_ausente_invalida_o_mes(self):
        """Dia 15 inteiramente ausente do array (não aparece nem como
        None) — ANTES do fix equivalente de Open-Meteo, isso resultava
        num total sobre 29 dias, sem nenhum aviso. AGORA: mês rejeitado."""
        dias = [d for d in range(1, 31) if d != 15]
        payload = _openmeteo_payload(2024, 6, 1.0, dias_presentes=dias)
        df = self._rodar(payload, 2024, 6)
        self.assertTrue(df.empty)

    def test_valor_none_invalida_o_mes_nunca_vira_zero(self):
        payload = _openmeteo_payload(2024, 6, lambda d: None if d == 15 else 1.0)
        df = self._rodar(payload, 2024, 6)
        self.assertTrue(df.empty, "precipitation_sum=None nunca deve ser aceito "
                                   "como mês completo, nem convertido em 0.0")

    def test_valor_nan_invalida_o_mes(self):
        payload = _openmeteo_payload(2024, 6, lambda d: float('nan') if d == 15 else 1.0)
        df = self._rodar(payload, 2024, 6)
        self.assertTrue(df.empty)

    def test_valor_infinito_invalida_o_mes(self):
        payload = _openmeteo_payload(2024, 6, lambda d: float('inf') if d == 15 else 1.0)
        df = self._rodar(payload, 2024, 6)
        self.assertTrue(df.empty)

    def test_valor_negativo_invalida_o_mes(self):
        payload = _openmeteo_payload(2024, 6, lambda d: -1.0 if d == 15 else 1.0)
        df = self._rodar(payload, 2024, 6)
        self.assertTrue(df.empty)

    def test_valor_nao_numerico_invalida_o_mes(self):
        payload = _openmeteo_payload(2024, 6, lambda d: 'N/A' if d == 15 else 1.0)
        df = self._rodar(payload, 2024, 6)
        self.assertTrue(df.empty)

    def test_datas_duplicadas_invalidam_o_mes(self):
        payload = _openmeteo_payload(2024, 6, 1.0)
        payload['daily']['time'].append('2024-06-01')
        payload['daily']['precipitation_sum'].append(1.0)
        df = self._rodar(payload, 2024, 6)
        self.assertTrue(df.empty)

    def test_quantidades_de_datas_e_valores_divergentes_sao_rejeitadas(self):
        payload = _openmeteo_payload(2024, 6, 1.0)
        payload['daily']['precipitation_sum'].pop()   # 29 valores para 30 datas
        df = self._rodar(payload, 2024, 6)
        self.assertTrue(df.empty)

    def test_fevereiro_bissexto_exige_29_dias(self):
        payload = _openmeteo_payload(2024, 2, 1.0)   # 2024 bissexto -> 29 dias
        df = self._rodar(payload, 2024, 2)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]['prec'], 29.0)

    def test_fevereiro_nao_bissexto_exige_28_dias(self):
        payload = _openmeteo_payload(2023, 2, 1.0)   # 2023 não bissexto -> 28 dias
        df = self._rodar(payload, 2023, 2)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]['prec'], 28.0)

    def test_intervalo_com_varios_meses_alguns_completos_outros_nao(self):
        junho = _openmeteo_payload(2024, 6, 2.0)
        julho_incompleto = _openmeteo_payload(2024, 7, 3.0, dias_presentes=range(1, 31))  # falta dia 31
        tempos = junho['daily']['time'] + julho_incompleto['daily']['time']
        valores = junho['daily']['precipitation_sum'] + julho_incompleto['daily']['precipitation_sum']
        payload = {'daily': {'time': tempos, 'precipitation_sum': valores}}
        df = self._rodar(payload, 2024, 6, 2024, 7)
        resultado = {(r['ano'], r['mes']): r['prec'] for r in df.to_dict('records')}
        self.assertIn((2024, 6), resultado)
        self.assertEqual(resultado[(2024, 6)], round(2.0 * 30, 1))
        self.assertNotIn((2024, 7), resultado, "julho com 30/31 dias não deve aparecer")


# ══════════════════════════════════════════════════════════════════
# Integração ponta a ponta: cascata CHIRPS → CHC-Preliminar → Open-Meteo
# ══════════════════════════════════════════════════════════════════

class FallbackIntegracaoPontaAPontaTestCase(unittest.TestCase):
    """Exercita fetch_monthly_data.main() com _chirps.py e
    _openmeteo.py REAIS (só a fronteira de rede é mockada:
    climateserv.api.request_data e urllib.request.urlopen) — nenhum
    destes testes mocka buscar_prec_chirps/buscar_prec_openmeteo
    diretamente, ao contrário de tests/test_fetch_fallback.py (que
    testa falhas de transporte, não cobertura temporal)."""

    def setUp(self):
        tmpdir_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir_ctx.cleanup)
        tmpdir = Path(tmpdir_ctx.name)

        self.serie_path = tmpdir / 'serie_subst.csv'
        self.merra_path = tmpdir / 'master_monthly.csv'

        pd.DataFrame([{
            'ano': 2024, 'mes': 5, 'prec': 50.0, 'nino34': 0.3,
            'tsa': 0.1, 'pdo': -0.2, 'date': '2024-05-01', 'fonte': 'CHIRPS',
        }]).to_csv(self.serie_path, index=False)
        pd.DataFrame([{
            'year': 2024, 'month': 6, 'nino34': 0.4, 'tsa': 0.15, 'pdo': -0.1,
        }]).to_csv(self.merra_path, index=False)

        for p in (
            patch.object(fmd, 'SERIE_PATH', self.serie_path),
            patch.object(fmd, 'MERRA_PATH', self.merra_path),
            patch.object(fmd, 'mes_anterior', lambda: (2024, 6)),
        ):
            p.start()
            self.addCleanup(p.stop)

    def test_chirps_incompleto_cai_para_chc_preliminar(self):
        """CHIRPS com cobertura incompleta (29/30 dias) -> CHC-Preliminar
        cobre o mês -> fonte final deve ser 'CHC-Preliminar', nunca o
        total parcial do CHIRPS."""
        dias_chirps = _dias_chirps(2024, 6, 5.0, dias_presentes=range(1, 30))  # falta dia 30
        with patch.object(_chirps.api, 'request_data',
                           return_value={'data': dias_chirps}), \
             patch.object(fmd, 'buscar_prec_chc_preliminar_zonal',
                           lambda ano, mes: {'ano': ano, 'mes': mes, 'prec': 42.0,
                                              'fonte': 'CHC-Preliminar'}):
            resultado = fmd.main()
        self.assertEqual(resultado, 0)
        serie = pd.read_csv(self.serie_path)
        linha = serie[(serie['ano'] == 2024) & (serie['mes'] == 6)].iloc[0]
        self.assertEqual(linha['fonte'], 'CHC-Preliminar')
        self.assertEqual(linha['prec'], 42.0)

    def test_chirps_incompleto_e_chc_falho_cai_para_openmeteo(self):
        """CHIRPS incompleto, CHC-Preliminar falha -> Open-Meteo REAL
        (mockado só no transporte HTTP) cobre o mês completo."""
        dias_chirps = _dias_chirps(2024, 6, 5.0, dias_presentes=range(1, 30))  # falta dia 30
        payload_om = _openmeteo_payload(2024, 6, 3.0)   # completo, 30 dias
        with patch.object(_chirps.api, 'request_data',
                           return_value={'data': dias_chirps}), \
             patch.object(fmd, 'buscar_prec_chc_preliminar_zonal', lambda ano, mes: None), \
             patch.object(_openmeteo.urllib.request, 'urlopen',
                           return_value=_fake_urlopen(payload_om)):
            resultado = fmd.main()
        self.assertEqual(resultado, 0)
        serie = pd.read_csv(self.serie_path)
        linha = serie[(serie['ano'] == 2024) & (serie['mes'] == 6)].iloc[0]
        self.assertEqual(linha['fonte'], 'OpenMeteo-ERA5')
        self.assertEqual(linha['prec'], round(3.0 * 30, 1))

    def test_todas_as_fontes_temporalmente_incompletas_mes_fica_ausente(self):
        """CHIRPS incompleto, CHC falha, Open-Meteo TAMBÉM incompleto
        -> o mês não é gravado em nenhuma fonte — nunca um total
        artificial, a lacuna fica para a checagem de continuidade
        bloquear a publicação (ver verificar_dashboard.py)."""
        dias_chirps = _dias_chirps(2024, 6, 5.0, dias_presentes=range(1, 30))
        payload_om_incompleto = _openmeteo_payload(2024, 6, 3.0, dias_presentes=range(1, 30))
        with patch.object(_chirps.api, 'request_data',
                           return_value={'data': dias_chirps}), \
             patch.object(fmd, 'buscar_prec_chc_preliminar_zonal', lambda ano, mes: None), \
             patch.object(_openmeteo.urllib.request, 'urlopen',
                           return_value=_fake_urlopen(payload_om_incompleto)):
            resultado = fmd.main()
        self.assertEqual(resultado, 0, "main() nunca deve propagar exceção, mesmo "
                                         "com todas as fontes temporalmente incompletas")
        serie = pd.read_csv(self.serie_path)
        linha = serie[(serie['ano'] == 2024) & (serie['mes'] == 6)]
        self.assertEqual(len(linha), 0, "mês com todas as fontes incompletas não "
                                          "deve ser gravado — nunca como zero, nunca "
                                          "com total parcial")

        import importlib
        vd = importlib.import_module('verificar_dashboard')
        lacunas = vd.checar_continuidade(serie, ate=(2024, 6))
        self.assertIn('06/2024', lacunas, "a checagem de continuidade deve detectar "
                                            "a lacuna e bloquear a publicação")

    def test_chirps_completo_e_usado_diretamente_fonte_preservada(self):
        """CHIRPS com cobertura completa (30/30) -> usado diretamente,
        sem acionar CHC-Preliminar nem Open-Meteo."""
        dias_chirps = _dias_chirps(2024, 6, 5.0)   # completo

        def _chc_nao_deveria_ser_chamado(ano, mes):
            raise AssertionError('CHC-Preliminar não deveria ser chamado — '
                                  'CHIRPS já cobriu o mês completamente')

        with patch.object(_chirps.api, 'request_data',
                           return_value={'data': dias_chirps}), \
             patch.object(fmd, 'buscar_prec_chc_preliminar_zonal',
                           _chc_nao_deveria_ser_chamado):
            resultado = fmd.main()
        self.assertEqual(resultado, 0)
        serie = pd.read_csv(self.serie_path)
        linha = serie[(serie['ano'] == 2024) & (serie['mes'] == 6)].iloc[0]
        self.assertEqual(linha['fonte'], 'CHIRPS')
        self.assertEqual(linha['prec'], round(5.0 * 30, 1))


if __name__ == '__main__':
    unittest.main()
