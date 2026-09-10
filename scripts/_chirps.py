#!/usr/bin/env python3
"""
_chirps.py — busca de precipitação via CHIRPS (UCSB), pelo ClimateSERV
Compartilhado por fetch_monthly_data.py e scripts/backfill_chirps_historico.py.

CHIRPS é a fonte primária de fallback (ver CLAUDE.md, armadilha 7): tem
viés desprezível contra as estações Sinobras (razão mediana 0,998 no
período 1981-2025), contra 0,88 do Open-Meteo ERA5-Land. Julho é
exceção conhecida em ambas as fontes — não tratado à parte (ver
armadilha 7 para a justificativa).
"""

import time
from calendar import monthrange
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import pandas as pd
import climateserv.api as api

FAZENDAS_LAT = -7.80
FAZENDAS_LON = -47.95

# ClimateSERV é um serviço acadêmico (SERVIR/NASA) e pode ficar fora do
# ar ou demorar — generoso, mas limitado, para não travar o workflow
# indefinidamente se o serviço nunca responder.
TIMEOUT_SEGUNDOS = 600


def _geometria_ponto(lat, lon, delta=0.01):
    """Caixa pequena ao redor do ponto — a API exige um polígono, não
    aceita ponto puro. delta=0.01° (~1km) é bem menor que a resolução
    do CHIRPS (0.05°), então a média do polígono equivale ao valor do
    pixel que contém o ponto."""
    return [[lon-delta, lat+delta], [lon+delta, lat+delta],
            [lon+delta, lat-delta], [lon-delta, lat-delta],
            [lon-delta, lat+delta]]


def buscar_prec_chirps(ano_ini, mes_ini, ano_fim, mes_fim):
    """
    Precipitação mensal via CHIRPS (dataset 0 do ClimateSERV) para o
    intervalo inteiro, numa única chamada. Pedidos muito longos (~45
    anos) falham no lado do servidor — para históricos grandes, quebre
    em blocos de poucos anos (ver backfill_chirps_historico.py).

    Retorna DataFrame [ano, mes, prec, fonte]. Meses sem publicação
    ainda (CHIRPS tem alguns meses de defasagem) simplesmente não
    aparecem no resultado — não vêm como zero.
    """
    ultimo_dia = monthrange(ano_fim, mes_fim)[1]
    ini = f'{mes_ini:02d}/01/{ano_ini}'
    fim = f'{mes_fim:02d}/{ultimo_dia:02d}/{ano_fim}'
    geom = _geometria_ponto(FAZENDAS_LAT, FAZENDAS_LON)

    def _chamar():
        return api.request_data(0, 'Average', ini, fim, geom, '', '', 'memory_object')

    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_chamar)
            result = future.result(timeout=TIMEOUT_SEGUNDOS)
    except FutureTimeoutError:
        print(f"  ⚠ CHIRPS indisponível: sem resposta em {TIMEOUT_SEGUNDOS}s")
        return pd.DataFrame(columns=['ano', 'mes', 'prec', 'fonte'])
    except Exception as e:
        print(f"  ⚠ CHIRPS indisponível: {e}")
        return pd.DataFrame(columns=['ano', 'mes', 'prec', 'fonte'])

    if not result or 'data' not in result:
        print(f"  ⚠ CHIRPS indisponível: resposta vazia ou sem dados")
        return pd.DataFrame(columns=['ano', 'mes', 'prec', 'fonte'])

    df = pd.DataFrame([{
        'ano': r['year'], 'mes': r['month'],
        'prec': r['value']['avg'] if r['value']['avg'] is not None else 0.0,
    } for r in result['data']])
    mensal = df.groupby(['ano', 'mes'])['prec'].sum().reset_index()
    mensal['prec']  = mensal['prec'].round(1)
    mensal['fonte'] = 'CHIRPS'
    return mensal
