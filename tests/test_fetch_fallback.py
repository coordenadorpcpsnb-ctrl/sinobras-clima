#!/usr/bin/env python3
"""
tests/test_fetch_fallback.py — exercita o caminho de fallback
CHIRPS → Open-Meteo em fetch_monthly_data.py sob três modos de falha
do CHIRPS: host inalcançável, timeout, resposta malformada.

Roda com:
    python3 -m unittest tests.test_fetch_fallback -v
ou:
    python3 tests/test_fetch_fallback.py

Nenhuma requisição de rede real: climateserv.api.request_data é
substituído por monkeypatch (unittest.mock) para simular cada falha —
nenhuma alteração permanente em scripts/_chirps.py, o teste só exercita
o código real dele contra respostas simuladas na fronteira de rede.

Para cada modo de falha, confirma:
  1. o mês cai para Open-Meteo (fonte='OpenMeteo-ERA5')
  2. a precipitação gravada é o valor real do fallback, nunca 0.0
  3. main() retorna 0 (não propaga exceção, não derruba o pipeline)
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import _chirps                    # noqa: E402
import fetch_monthly_data as fmd  # noqa: E402

# Precipitação "real" que o fallback Open-Meteo deveria retornar —
# usada para confirmar que o valor gravado vem do fallback, não zero
# nem inventado.
PREC_FALLBACK = 42.3


class FallbackCHIRPSTestCase(unittest.TestCase):

    def setUp(self):
        tmpdir_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir_ctx.cleanup)
        tmpdir = Path(tmpdir_ctx.name)

        self.serie_path = tmpdir / 'serie_subst.csv'
        self.merra_path = tmpdir / 'master_monthly.csv'

        # série com um único mês existente (2024-01) — 2024-02 é a
        # lacuna que o teste força o CHIRPS a falhar em preencher
        pd.DataFrame([{
            'ano': 2024, 'mes': 1, 'prec': 100.0, 'nino34': 0.5,
            'tsa': 0.1, 'pdo': -0.2, 'date': '2024-01-01', 'fonte': 'CHIRPS',
        }]).to_csv(self.serie_path, index=False)

        # master_monthly já tem o índice real do mês em questão —
        # isola o teste do fallback de precipitação (não é isso que
        # está sendo testado aqui)
        pd.DataFrame([{
            'year': 2024, 'month': 2, 'nino34': 0.6, 'tsa': 0.12, 'pdo': -0.15,
        }]).to_csv(self.merra_path, index=False)

        for p in (
            patch.object(fmd, 'SERIE_PATH', self.serie_path),
            patch.object(fmd, 'MERRA_PATH', self.merra_path),
            patch.object(fmd, 'mes_anterior', lambda: (2024, 2)),
        ):
            p.start()
            self.addCleanup(p.stop)

        # Open-Meteo "real": sempre disponível e determinístico —
        # o que muda em cada teste é só o CHIRPS
        era5_patch = patch.object(
            fmd, 'buscar_prec_openmeteo',
            lambda y1, m1, y2, m2: pd.DataFrame([
                {'ano': 2024, 'mes': 2, 'prec': PREC_FALLBACK, 'fonte': 'OpenMeteo-ERA5'}
            ]))
        era5_patch.start()
        self.addCleanup(era5_patch.stop)

    def _rodar_e_conferir_fallback(self):
        """Roda fmd.main() e confirma que o mês foi gravado via fallback."""
        resultado = fmd.main()
        self.assertEqual(
            resultado, 0,
            "main() não deve propagar erro/exceção mesmo com o CHIRPS falhando")

        serie = pd.read_csv(self.serie_path)
        linha = serie[(serie['ano'] == 2024) & (serie['mes'] == 2)]
        self.assertEqual(
            len(linha), 1,
            "o mês deveria ter sido gravado via fallback, não pulado")
        linha = linha.iloc[0]

        self.assertEqual(linha['fonte'], 'OpenMeteo-ERA5',
                          "fonte gravada deveria ser o fallback, não CHIRPS")
        self.assertEqual(linha['prec'], PREC_FALLBACK,
                          "precipitação gravada deveria ser o valor real do fallback")
        self.assertNotEqual(linha['prec'], 0.0,
                             "nunca gravar zero quando há fallback disponível")
        return linha

    def _limpar_linha_gravada(self):
        """Remove o mês de teste da série, para reusar o fixture entre subTests."""
        serie = pd.read_csv(self.serie_path)
        serie = serie[~((serie['ano'] == 2024) & (serie['mes'] == 2))]
        serie.to_csv(self.serie_path, index=False)

    # ── 1. host inalcançável ─────────────────────────────────────────
    def test_host_inalcancavel(self):
        with patch.object(
            _chirps.api, 'request_data',
            side_effect=ConnectionError(
                "Failed to establish a new connection: "
                "[Errno -2] Name or service not known"),
        ):
            self._rodar_e_conferir_fallback()

    # ── 2. timeout (endpoint que não responde) ──────────────────────
    def test_timeout(self):
        def _trava(*args, **kwargs):
            # dorme mais que o timeout patchado abaixo — simula o
            # ClimateSERV nunca respondendo
            time.sleep(1.5)
            return {'data': []}

        with patch.object(_chirps, 'TIMEOUT_SEGUNDOS', 0.2), \
             patch.object(_chirps.api, 'request_data', side_effect=_trava):
            inicio = time.monotonic()
            self._rodar_e_conferir_fallback()
            decorrido = time.monotonic() - inicio

        # o ponto do timeout é não travar o pipeline esperando o
        # serviço travado responder — se buscar_prec_chirps bloqueasse
        # até a chamada de 1,5s terminar, isso pegaria a regressão
        self.assertLess(
            decorrido, 1.0,
            "buscar_prec_chirps não deveria bloquear além do timeout "
            "patchado esperando a chamada trava terminar sozinha")

    # ── 3. resposta malformada (JSON inválido ou vazio) ─────────────
    def test_resposta_malformada(self):
        casos = {
            'None':               None,
            'dict vazio':         {},
            'data é None':        {'data': None},
            'data é lista vazia': {'data': []},
            'entrada sem chaves': {'data': [{'year': 2024}]},
            'não é um dict':      'isso não é um dict',
        }
        for nome, resposta in casos.items():
            with self.subTest(caso=nome):
                with patch.object(_chirps.api, 'request_data', return_value=resposta):
                    self._rodar_e_conferir_fallback()
                self._limpar_linha_gravada()


if __name__ == '__main__':
    unittest.main()
