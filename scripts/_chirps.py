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
import tempfile
import urllib.request
from pathlib import Path
from calendar import monthrange
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import pandas as pd
import climateserv.api as api

# CHC (UCSB) direto — Preliminary, reservado para o mês mais recente
# quando o Final (ClimateSERV) ainda não publicou (ver
# buscar_prec_chc_preliminar_zonal). Importados só quando essa função
# é chamada, não no topo do módulo — rasterio/rasterstats não são
# necessários no caminho comum (ClimateSERV), só nesse fallback.
CHC_PRELIM_URL = ('https://data.chc.ucsb.edu/products/CHIRPS-2.0/prelim/'
                   'global_monthly/tifs/chirps-v2.0.{ano}.{mes:02d}.tif')

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


def _buscar_prec_chirps_geom(ini, fim, geom, rotulo='CHIRPS'):
    """
    Núcleo comum: uma chamada ao ClimateSERV para um anel de polígono
    já pronto (`geom`, lista de [lon,lat]), com timeout limitado e
    tratamento de resposta malformada. Usada tanto pelo ponto único
    (buscar_prec_chirps) quanto pela busca por grupo geográfico
    (buscar_prec_chirps_zonal) — não duplicar essa lógica.

    Retorna DataFrame [ano, mes, prec, fonte]. Meses sem publicação
    ainda (CHIRPS tem alguns meses de defasagem) simplesmente não
    aparecem no resultado — não vêm como zero.
    """
    def _chamar():
        return api.request_data(0, 'Average', ini, fim, geom, '', '', 'memory_object')

    vazio = pd.DataFrame(columns=['ano', 'mes', 'prec', 'fonte'])

    # Sem "with": o gerenciador de contexto do ThreadPoolExecutor chama
    # shutdown(wait=True) na saída, que BLOQUEIA até a thread em segundo
    # plano terminar sozinha — mesmo depois de future.result(timeout=…)
    # já ter estourado o timeout. Isso anularia o propósito do timeout
    # (a chamada só "voltaria" quando o serviço travado finalmente
    # respondesse, não em TIMEOUT_SEGUNDOS). shutdown(wait=False) evita
    # isso: a thread órfã termina sozinha em segundo plano, descartada.
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        future = ex.submit(_chamar)
        result = future.result(timeout=TIMEOUT_SEGUNDOS)
    except FutureTimeoutError:
        print(f"  ⚠ CHIRPS ({rotulo}) indisponível: sem resposta em {TIMEOUT_SEGUNDOS}s")
        return vazio
    except Exception as e:
        print(f"  ⚠ CHIRPS ({rotulo}) indisponível: {e}")
        return vazio
    finally:
        ex.shutdown(wait=False, cancel_futures=True)

    if not result or not isinstance(result, dict) or not result.get('data'):
        print(f"  ⚠ CHIRPS ({rotulo}) indisponível: resposta vazia ou sem dados")
        return vazio

    # Resposta malformada (chaves faltando, tipo inesperado) não pode
    # derrubar o pipeline inteiro — vira fallback, como qualquer outra
    # falha do CHIRPS.
    try:
        df = pd.DataFrame([{
            'ano': r['year'], 'mes': r['month'],
            'prec': (r.get('value') or {}).get('avg') or 0.0,
        } for r in result['data']])
        mensal = df.groupby(['ano', 'mes'])['prec'].sum().reset_index()
        mensal['prec']  = mensal['prec'].round(1)
        mensal['fonte'] = 'CHIRPS'
        return mensal
    except Exception as e:
        print(f"  ⚠ CHIRPS ({rotulo}) indisponível: resposta malformada ({e})")
        return vazio


def buscar_prec_chirps(ano_ini, mes_ini, ano_fim, mes_fim):
    """
    Precipitação mensal via CHIRPS (dataset 0 do ClimateSERV) para o
    intervalo inteiro, numa única chamada, usando uma caixa pequena ao
    redor do ponto centroide das fazendas (não o envelope das fazendas —
    para isso, ver buscar_prec_chirps_zonal). Pedidos muito longos (~45
    anos) falham no lado do servidor — para históricos grandes, quebre
    em blocos de poucos anos (ver backfill_chirps_historico.py).

    Retorna DataFrame [ano, mes, prec, fonte].
    """
    ultimo_dia = monthrange(ano_fim, mes_fim)[1]
    ini = f'{mes_ini:02d}/01/{ano_ini}'
    fim = f'{mes_fim:02d}/{ultimo_dia:02d}/{ano_fim}'
    geom = _geometria_ponto(FAZENDAS_LAT, FAZENDAS_LON)
    return _buscar_prec_chirps_geom(ini, fim, geom, rotulo='ponto único')


def buscar_prec_chirps_zonal(ano_ini, mes_ini, ano_fim, mes_fim):
    """
    Precipitação mensal via CHIRPS, com o polígono do envelope das
    fazendas (data/fazendas.geojson, Fazendas_v2.kmz — sem identificação
    individual) em vez do ponto único — ver CLAUDE.md, armadilha 8, e
    _farm_geometry.py.

    Uma geometria única, uma chamada ao ClimateSERV (antes eram 7,
    quando o geojson tinha as 37 fazendas em 7 grupos desconectados —
    a fragilidade de "sucesso parcial por grupo" não existe mais).

    Retorna DataFrame [ano, mes, prec, fonte='CHIRPS-zonal'] — vazio se
    a chamada falhar (rede, timeout, resposta malformada); nunca grava
    zero.
    """
    from _farm_geometry import anel_simplificado

    ultimo_dia = monthrange(ano_fim, mes_fim)[1]
    ini = f'{mes_ini:02d}/01/{ano_ini}'
    fim = f'{mes_fim:02d}/{ultimo_dia:02d}/{ano_fim}'

    anel, erro_pct = anel_simplificado()
    if erro_pct:
        print(f"  ℹ CHIRPS zonal: anel simplificado, erro de área {erro_pct:.2f}%")

    resultado = _buscar_prec_chirps_geom(ini, fim, anel, rotulo='envelope fazendas')
    if not resultado.empty:
        resultado['fonte'] = 'CHIRPS-zonal'
    return resultado


def buscar_prec_chc_preliminar_zonal(ano, mes, timeout_segundos=120):
    """
    Precipitação de UM mês via CHIRPS Preliminary — download direto do
    CHC (data.chc.ucsb.edu), zonal stats via rasterio/rasterstats sobre
    o polígono do envelope das fazendas (data/fazendas.geojson, sem
    simplificar — sem a limitação de anel único do ClimateSERV, aqui é
    processamento local, não uma URL).

    Reservado para o mês mais recente quando o CHIRPS Final (via
    buscar_prec_chirps/buscar_prec_chirps_zonal) ainda não publicou —
    o Preliminary sai antes, mas sem a consolidação/correção final.
    NÃO é substituto do Final para meses já consolidados: só usar aqui
    quando o Final genuinamente não tiver o mês ainda.

    Retorna dict {'ano', 'mes', 'prec', 'fonte': 'CHIRPS-prelim-zonal'}
    ou None se o arquivo não existir ainda (mês não publicado, mesmo no
    Preliminary) ou o download/processamento falhar — nunca inventa
    zero.
    """
    from _farm_geometry import poligono
    from shapely.geometry import mapping

    url = CHC_PRELIM_URL.format(ano=ano, mes=mes)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as tmp:
            tmp_path = Path(tmp.name)
            req = urllib.request.Request(url, headers={'User-Agent': 'sinobras-clima/1.0'})
            with urllib.request.urlopen(req, timeout=timeout_segundos) as r:
                tmp.write(r.read())

        import rasterio  # noqa: F401 (só pra falhar cedo e claro se faltar a dependência)
        from rasterstats import zonal_stats

        stats = zonal_stats(mapping(poligono()), str(tmp_path), stats=['mean', 'count'], nodata=-9999)

        if not stats or stats[0]['mean'] is None or stats[0]['count'] == 0:
            print(f"  ⚠ CHC Preliminary {mes:02d}/{ano}: zonal stats sem pixels válidos")
            return None

        return {
            'ano': ano, 'mes': mes,
            'prec': round(stats[0]['mean'], 1),
            'fonte': 'CHIRPS-prelim-zonal',
        }
    except Exception as e:
        print(f"  ⚠ CHC Preliminary {mes:02d}/{ano} indisponível: {e}")
        return None
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
