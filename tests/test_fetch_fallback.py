#!/usr/bin/env python3
"""
tests/test_fetch_fallback.py — exercita a cascata de fallback em
fetch_monthly_data.py: CHIRPS Final → CHC Preliminary → Open-Meteo.

FallbackCHIRPSTestCase: três modos de falha do CHIRPS Final (host
inalcançável, timeout, resposta malformada), CHC Preliminary também
sem o mês nesses testes — cai direto pro Open-Meteo.

CoberturaParcialTestCase: CHIRPS Final cobre só parte do intervalo,
CHC Preliminary e Open-Meteo falham para o resto.

CHCPreliminarTestCase: a camada intermediária em si — cobre quando o
Final falha (e confirma que o Open-Meteo NEM é chamado nesse caso), e
cai pro Open-Meteo quando ela também falha.

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

Para a cobertura parcial (PartialCoverageTestCase), confirma também
que a lacuna resultante (meses sem NENHUMA fonte) é detectada pela
checagem de continuidade de verificar_dashboard.py — é o mesmo
mecanismo que deixou passar o buraco de jan-jun/2026 sem ninguém notar.
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
import verificar_dashboard as vd  # noqa: E402

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

        # CHC Preliminary "sem o mês" por padrão nestes testes — o que
        # está sob teste aqui é o CHIRPS Final falhando e caindo direto
        # pro Open-Meteo; a camada intermediária tem seus próprios
        # testes em CHCPreliminarTestCase
        prelim_patch = patch.object(fmd, 'buscar_prec_chc_preliminar_zonal',
                                     lambda ano, mes: None)
        prelim_patch.start()
        self.addCleanup(prelim_patch.stop)

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


class CoberturaParcialTestCase(unittest.TestCase):
    """
    CHIRPS cobre só parte do intervalo pedido (jan-mai/2024, de um
    pedido jan-jul/2024) e o Open-Meteo falha para o resto (jun-jul).
    Confirma: meses com CHIRPS são gravados (fonte=CHIRPS); meses sem
    nenhuma fonte NÃO são gravados (nunca como zero); main() não
    interrompe; e a lacuna resultante (jun-jul/2024) é pega pela
    checagem de continuidade de verificar_dashboard.py — sem essa
    checagem, é exatamente assim que o buraco de jan-jun/2026 se
    formou e ficou invisível até alguém medir o RMSE.
    """

    MESES_PEDIDOS = [(2024, m) for m in range(1, 8)]   # jan..jul/2024
    MESES_CHIRPS  = [(2024, m) for m in range(1, 6)]   # jan..mai/2024 — cobertos
    MESES_FALTAM  = [(2024, m) for m in range(6, 8)]   # jun..jul/2024 — sem fonte nenhuma

    def setUp(self):
        tmpdir_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir_ctx.cleanup)
        tmpdir = Path(tmpdir_ctx.name)

        self.serie_path = tmpdir / 'serie_subst.csv'
        self.merra_path = tmpdir / 'master_monthly.csv'

        # série existente termina em 2023-12 — a lacuna a preencher é
        # jan-jul/2024 inteiro (mes_anterior mockado abaixo p/ jul/2024)
        pd.DataFrame([{
            'ano': 2023, 'mes': 12, 'prec': 200.0, 'nino34': 0.4,
            'tsa': 0.2, 'pdo': -0.1, 'date': '2023-12-01', 'fonte': 'CHIRPS',
        }]).to_csv(self.serie_path, index=False)

        # master_monthly com índice real para todos os meses pedidos —
        # isola o teste do comportamento de persistência do ENSO, que
        # já é testado em outro lugar
        pd.DataFrame([
            {'year': y, 'month': m, 'nino34': 0.5, 'tsa': 0.15, 'pdo': -0.2}
            for (y, m) in self.MESES_PEDIDOS
        ]).to_csv(self.merra_path, index=False)

        for p in (
            patch.object(fmd, 'SERIE_PATH', self.serie_path),
            patch.object(fmd, 'MERRA_PATH', self.merra_path),
            patch.object(fmd, 'mes_anterior', lambda: (2024, 7)),
        ):
            p.start()
            self.addCleanup(p.stop)

        # CHIRPS "real": cobre só jan-mai/2024
        chirps_df = pd.DataFrame([
            {'ano': y, 'mes': m, 'prec': 100.0 + m, 'fonte': 'CHIRPS'}
            for (y, m) in self.MESES_CHIRPS
        ])
        chirps_patch = patch.object(
            fmd, 'buscar_prec_chirps',
            lambda y1, m1, y2, m2: chirps_df.copy())
        chirps_patch.start()
        self.addCleanup(chirps_patch.stop)

        # CHC Preliminary também sem esses meses — o cenário sob teste
        # aqui é dupla falha (CHIRPS parcial + Open-Meteo falho), não a
        # camada intermediária
        prelim_patch = patch.object(fmd, 'buscar_prec_chc_preliminar_zonal',
                                     lambda ano, mes: None)
        prelim_patch.start()
        self.addCleanup(prelim_patch.stop)

        # Open-Meteo falha por completo para o que sobrar (jun-jul) —
        # retorno vazio, como _openmeteo.buscar_prec_openmeteo faz de
        # verdade quando a chamada real falha
        era5_patch = patch.object(
            fmd, 'buscar_prec_openmeteo',
            lambda y1, m1, y2, m2: pd.DataFrame(columns=['ano', 'mes', 'prec', 'fonte']))
        era5_patch.start()
        self.addCleanup(era5_patch.stop)

    def test_cobertura_parcial_nao_grava_zero_e_verificador_pega_lacuna(self):
        resultado = fmd.main()
        self.assertEqual(
            resultado, 0,
            "main() não deve propagar erro mesmo com cobertura parcial + fallback falho")

        serie = pd.read_csv(self.serie_path)

        # meses cobertos pelo CHIRPS: gravados, fonte correta
        for (y, m) in self.MESES_CHIRPS:
            linha = serie[(serie['ano'] == y) & (serie['mes'] == m)]
            self.assertEqual(len(linha), 1, f"{m:02d}/{y} deveria ter sido gravado")
            self.assertEqual(linha.iloc[0]['fonte'], 'CHIRPS')
            self.assertGreater(linha.iloc[0]['prec'], 0.0)

        # meses sem nenhuma fonte: NÃO gravados — nem como zero, ausentes mesmo
        for (y, m) in self.MESES_FALTAM:
            linha = serie[(serie['ano'] == y) & (serie['mes'] == m)]
            self.assertEqual(
                len(linha), 0,
                f"{m:02d}/{y} não deveria ter sido gravado (nenhuma fonte disponível) — "
                f"gravar zero seria afirmar 'sem chuva', não 'sem dado'")

        # a lacuna resultante (jun-jul/2024) precisa ser pega pela
        # checagem de continuidade do verificador — é essa checagem que
        # deveria ter barrado a publicação quando o buraco de
        # jan-jun/2026 se formou, e não pegou porque não existia ainda
        lacunas = vd.checar_continuidade(serie, ate=(2024, 7))
        esperado = [f'{m:02d}/{y}' for (y, m) in self.MESES_FALTAM]
        self.assertEqual(
            lacunas, esperado,
            "verificar_dashboard.checar_continuidade deveria detectar exatamente "
            "os meses sem fonte nenhuma como lacuna, barrando a publicação")


class CHCPreliminarTestCase(unittest.TestCase):
    """
    Camada intermediária CHC-Preliminar: entra quando o CHIRPS Final
    não tem o mês, antes de cair pro Open-Meteo. Confirma:
    1. CHIRPS Final falha, CHC-Preliminar cobre -> grava com
       fonte='CHC-Preliminar', Open-Meteo NUNCA é chamado.
    2. CHIRPS Final e CHC-Preliminar falham -> cai pro Open-Meteo,
       exatamente como antes dessa camada existir.
    """

    def setUp(self):
        tmpdir_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir_ctx.cleanup)
        tmpdir = Path(tmpdir_ctx.name)

        self.serie_path = tmpdir / 'serie_subst.csv'
        self.merra_path = tmpdir / 'master_monthly.csv'

        pd.DataFrame([{
            'ano': 2024, 'mes': 1, 'prec': 100.0, 'nino34': 0.5,
            'tsa': 0.1, 'pdo': -0.2, 'date': '2024-01-01', 'fonte': 'CHIRPS',
        }]).to_csv(self.serie_path, index=False)

        pd.DataFrame([{
            'year': 2024, 'month': 2, 'nino34': 0.6, 'tsa': 0.12, 'pdo': -0.15,
        }]).to_csv(self.merra_path, index=False)

        for p in (
            patch.object(fmd, 'SERIE_PATH', self.serie_path),
            patch.object(fmd, 'MERRA_PATH', self.merra_path),
            patch.object(fmd, 'mes_anterior', lambda: (2024, 2)),
            patch.object(fmd, 'buscar_prec_chirps',
                         lambda y1, m1, y2, m2: pd.DataFrame(columns=['ano', 'mes', 'prec', 'fonte'])),
        ):
            p.start()
            self.addCleanup(p.stop)

    def test_chc_preliminar_cobre_e_era5_nao_e_chamado(self):
        prelim_patch = patch.object(
            fmd, 'buscar_prec_chc_preliminar_zonal',
            lambda ano, mes: {'ano': ano, 'mes': mes, 'prec': 7.5, 'fonte': 'CHC-Preliminar'})
        prelim_patch.start()
        self.addCleanup(prelim_patch.stop)

        era5_mock = patch.object(
            fmd, 'buscar_prec_openmeteo',
            side_effect=AssertionError('Open-Meteo não deveria ser chamado — '
                                        'CHC-Preliminar já cobriu o mês'))
        era5_mock.start()
        self.addCleanup(era5_mock.stop)

        resultado = fmd.main()
        self.assertEqual(resultado, 0)

        serie = pd.read_csv(self.serie_path)
        linha = serie[(serie['ano'] == 2024) & (serie['mes'] == 2)].iloc[0]
        self.assertEqual(linha['fonte'], 'CHC-Preliminar',
                          "fonte deveria ser 'CHC-Preliminar', não 'CHIRPS' — "
                          "são produtos diferentes (Final vs. Preliminary)")
        self.assertEqual(linha['prec'], 7.5)

    def test_chc_preliminar_tambem_falha_cai_pro_openmeteo(self):
        prelim_patch = patch.object(fmd, 'buscar_prec_chc_preliminar_zonal',
                                     lambda ano, mes: None)
        prelim_patch.start()
        self.addCleanup(prelim_patch.stop)

        era5_patch = patch.object(
            fmd, 'buscar_prec_openmeteo',
            lambda y1, m1, y2, m2: pd.DataFrame([
                {'ano': 2024, 'mes': 2, 'prec': PREC_FALLBACK, 'fonte': 'OpenMeteo-ERA5'}
            ]))
        era5_patch.start()
        self.addCleanup(era5_patch.stop)

        resultado = fmd.main()
        self.assertEqual(resultado, 0)

        serie = pd.read_csv(self.serie_path)
        linha = serie[(serie['ano'] == 2024) & (serie['mes'] == 2)].iloc[0]
        self.assertEqual(linha['fonte'], 'OpenMeteo-ERA5')
        self.assertEqual(linha['prec'], PREC_FALLBACK)


if __name__ == '__main__':
    unittest.main()
