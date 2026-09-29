#!/usr/bin/env python3
"""
_chirps_v3.py — Fase 2C.3A: extração independente do CHIRPS v3.0 Final
(Climate Hazards Center / UCSB), para uma nova referência histórica de
precipitação, separada da série de produção.

Este módulo NUNCA importa nem modifica scripts/_chirps.py (que continua
servindo exclusivamente o pipeline operacional, CHIRPS v2.0 via
ClimateSERV) — é uma implementação independente, do zero, lendo direto
os rasters do CHC (sem ClimateSERV).

Metodologia verificada AO VIVO (não presumida), 2026-09-29:

- README oficial: https://data.chc.ucsb.edu/products/CHIRPS/v3.0/README-CHIRPSv3.0.txt
  "Version 3.0 released 2025.01.01" — CHIRPS v2.0 released 2015.02.12.
  Mudanças chave da v3.0: mais estações (>90 fontes), correção de
  sub-captação de pluviômetro por vento (gauge-undercatch), domínio
  espacial ampliado (60°N-60°S, antes 50°N-50°S), preenchimento de
  lacunas com ERA5 0,25° (antes CFS 0,5°) — "CHIRPS v3.0 is overall
  wetter compared to CHIRPS v2.0" (texto do próprio README).
- Produto usado: mensal já consolidado (monthly/global/), NUNCA
  reconstrução por soma de diários (item 2 da tarefa) — Final, não
  Preliminary (subpasta prelim/, não usada aqui).
- Formato preferencial: COG (Cloud-Optimized GeoTIFF) via GDAL
  /vsicurl/ — leitura remota por range-request HTTP, sem baixar o
  raster global inteiro (item 4: "evitar armazenar rasters globais
  desnecessários no repositório"). Fallback: TIFF comum, mesma
  geometria, também lido via /vsicurl/, nunca baixado por inteiro
  neste módulo.
- Grade verificada ao vivo (rasterio, 1 arquivo aberto e inspecionado):
  CRS EPSG:4326, resolução 0,05°, 7200x2400 pixels, domínio
  (-180,-60)-(180,60), dtype float32, AREA_OR_POINT=Area,
  TIFFTAG_SOFTWARE="IDL 8.9.0, L3Harris Geospatial Solutions, Inc.".
- NoData: NENHUM dos dois formatos (COG, TIFF) declara a tag GDAL
  NODATA (`dataset.nodata` retorna None nos dois) — achado registrado,
  não presumido a partir de documentação. A sentinela -9999.0 foi
  CONFIRMADA empiricamente lendo um pixel sabidamente oceânico
  (-30,0, meio do Atlântico, fora do domínio terrestre do CHIRPS) —
  ver docs/nmme-fase2c3a-piloto-chirps-v3.md, Seção 2.

Nunca converte ausência de dado em zero (Seção 5 da tarefa) — ver
classificar_valor(). Nunca reutiliza a caixa pequena do ClimateSERV
(scripts/_chirps.py::_geometria_ponto) — o pixel é localizado
diretamente pela transformação espacial do raster (Seção 3).
"""

import datetime as dt
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import rasterio
import rasterio.errors
import rasterio.windows

ROOT = Path(__file__).parent.parent

# ══════════════════════════════════════════════════════════════════════════
# Metodologia CONHECIDA (verificada ao vivo — ver docstring do módulo)
# ══════════════════════════════════════════════════════════════════════════

VERSAO_CHIRPS = 'v3.0'
DATA_LANCAMENTO_VERSAO = '2025-01-01'
FONTE_README_URL = 'https://data.chc.ucsb.edu/products/CHIRPS/v3.0/README-CHIRPSv3.0.txt'
FONTE_DIRETORIO_BASE = 'https://data.chc.ucsb.edu/products/CHIRPS/v3.0/monthly/global/'
URL_TEMPLATE = {
    'cog': FONTE_DIRETORIO_BASE + 'cogs/chirps-v3.0.{ano}.{mes:02d}.cog',
    'tif': FONTE_DIRETORIO_BASE + 'tifs/chirps-v3.0.{ano}.{mes:02d}.tif',
}

RESOLUCAO_GRAUS = 0.05
CRS_ESPERADO = 'EPSG:4326'
WIDTH_ESPERADO = 7200
HEIGHT_ESPERADO = 2400
BOUNDS_ESPERADO = (-180.0, -60.0, 180.0, 60.0)   # left, bottom, right, top
DTYPE_ESPERADO = 'float32'
UNIDADE = 'mm/mês (campo mensal Final já consolidado — não soma de registros diários)'

# Confirmado empiricamente (não documentado no README nem na tag GDAL
# NODATA de nenhum dos dois formatos — ver docstring do módulo).
NODATA_SENTINELA = -9999.0

# Teto físico generoso p/ detectar corrupção/erro de unidade — não um
# limite climatológico da região (que é bem menor, CLAUDE.md).
LIMITE_FISICO_PLAUSIVEL_MM_MES = 1500.0

FAZENDAS_LAT = -7.80
FAZENDAS_LON = -47.95

TIMEOUT_SEGUNDOS = 60
MAX_TENTATIVAS = 3
BACKOFF_BASE_SEGUNDOS = 2


# ══════════════════════════════════════════════════════════════════════════
# Identificação/integridade do arquivo (SEM baixar o conteúdo)
# ══════════════════════════════════════════════════════════════════════════

def montar_url(ano, mes, formato='cog'):
    if formato not in URL_TEMPLATE:
        raise ValueError(f"formato desconhecido: {formato!r} (use 'cog' ou 'tif')")
    return URL_TEMPLATE[formato].format(ano=ano, mes=mes)


def verificar_disponibilidade_http(url, timeout=TIMEOUT_SEGUNDOS, tentativas=MAX_TENTATIVAS):
    """HEAD request — identificação e integridade básica do arquivo
    (ETag, Last-Modified, Content-Length) SEM baixar o conteúdo.
    Distingue mês ausente (HTTP 404) de outras falhas de rede — um 404
    NUNCA deve virar precipitação zero (Seção 5). Retentativas com
    backoff exponencial só para falhas de rede transitórias, nunca
    para 404 (mês ausente é uma resposta válida, não uma falha)."""
    ultimo_erro = None
    for tentativa in range(1, tentativas + 1):
        req = urllib.request.Request(url, method='HEAD',
                                      headers={'User-Agent': 'sinobras-clima/1.0 (Fase 2C.3A)'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return {
                    'disponivel': True,
                    'status_http': resp.status,
                    'etag': resp.headers.get('ETag'),
                    'last_modified': resp.headers.get('Last-Modified'),
                    'content_length_bytes': resp.headers.get('Content-Length'),
                    'content_type': resp.headers.get('Content-Type'),
                    'tentativas_ate_sucesso': tentativa,
                }
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {'disponivel': False, 'status_http': 404, 'motivo': 'mes_ausente'}
            ultimo_erro = f'http_error_{e.code}'
        except Exception as e:
            ultimo_erro = f'erro_rede: {e}'
        if tentativa < tentativas:
            time.sleep(BACKOFF_BASE_SEGUNDOS * tentativa)
    return {'disponivel': False, 'status_http': None, 'motivo': ultimo_erro,
            'tentativas_esgotadas': tentativas}


# ══════════════════════════════════════════════════════════════════════════
# Verificação de grade — reprova mudança inesperada de resolução/grade
# ══════════════════════════════════════════════════════════════════════════

def verificar_grade(dataset):
    """Confirma que a grade do raster aberto bate com a grade
    verificada ao vivo (CRS, resolução, dimensões, domínio espacial,
    dtype) — reprova mudanças inesperadas (Seção 5 da tarefa). Nunca
    presume que a grade é sempre a mesma entre arquivos/meses."""
    problemas = []

    crs_str = str(dataset.crs) if dataset.crs else None
    if crs_str is None or crs_str.upper() != CRS_ESPERADO:
        problemas.append(f"CRS inesperado: {crs_str} (esperado {CRS_ESPERADO})")

    res_x, res_y = dataset.res
    if abs(res_x - RESOLUCAO_GRAUS) > 1e-6 or abs(res_y - RESOLUCAO_GRAUS) > 1e-6:
        problemas.append(f"resolução inesperada: {dataset.res} (esperado "
                          f"{RESOLUCAO_GRAUS} nos dois eixos)")

    if dataset.width != WIDTH_ESPERADO or dataset.height != HEIGHT_ESPERADO:
        problemas.append(f"dimensões inesperadas: {dataset.width}x{dataset.height} "
                          f"(esperado {WIDTH_ESPERADO}x{HEIGHT_ESPERADO})")

    b = dataset.bounds
    tolerancia = RESOLUCAO_GRAUS   # 1 pixel de tolerância de borda
    esperado = BOUNDS_ESPERADO
    if (abs(b.left - esperado[0]) > tolerancia or abs(b.bottom - esperado[1]) > tolerancia
            or abs(b.right - esperado[2]) > tolerancia or abs(b.top - esperado[3]) > tolerancia):
        problemas.append(f"domínio espacial inesperado: {tuple(b)} (esperado {esperado})")

    dtype = dataset.dtypes[0] if dataset.dtypes else None
    if dtype != DTYPE_ESPERADO:
        problemas.append(f"dtype inesperado: {dtype} (esperado {DTYPE_ESPERADO})")

    return {'grade_ok': len(problemas) == 0, 'problemas': problemas}


# ══════════════════════════════════════════════════════════════════════════
# Localização do pixel — direto pela transformação espacial (Seção 3)
# ══════════════════════════════════════════════════════════════════════════

def localizar_pixel(dataset, lat=FAZENDAS_LAT, lon=FAZENDAS_LON):
    """Localiza o pixel correspondente a (lat,lon) DIRETAMENTE pela
    transformação espacial do raster (`dataset.index`), nunca a caixa
    pequena da extração ClimateSERV atual (scripts/_chirps.py::
    _geometria_ponto — essa função nem é importada aqui).

    Documenta explicitamente a convenção de indexação usada
    (numpy.floor, padrão do rasterio) e sinaliza quando o ponto cai
    exatamente (dentro de tolerância de ponto flutuante) sobre uma
    borda ou quina de pixel — caso em que a escolha entre pixels
    vizinhos depende dessa convenção de arredondamento, não é uma
    propriedade física do dado. Achado empírico confirmado nesta
    tarefa: com FAZENDAS_LAT=-7.80/FAZENDAS_LON=-47.95 (múltiplos
    exatos de 0,05°, já registrado em scripts/nmme_auditoria_chirps_
    sinobras.py na rodada anterior), o ponto cai exatamente numa quina
    compartilhada por até 4 pixels da grade real do CHIRPS v3.0."""
    row, col = dataset.index(lon, lat)   # op=numpy.floor, padrão do rasterio
    window = rasterio.windows.Window(col, row, 1, 1)
    left, bottom, right, top = rasterio.windows.bounds(window, dataset.transform)

    origem_lon, origem_lat = dataset.transform.c, dataset.transform.f
    frac_lon = ((lon - origem_lon) / RESOLUCAO_GRAUS) % 1.0
    frac_lat = ((origem_lat - lat) / RESOLUCAO_GRAUS) % 1.0
    tolerancia_fracao = 1e-6
    sobre_borda_lon = frac_lon < tolerancia_fracao or frac_lon > (1 - tolerancia_fracao)
    sobre_borda_lat = frac_lat < tolerancia_fracao or frac_lat > (1 - tolerancia_fracao)

    return {
        'row': int(row), 'col': int(col),
        'pixel_bounds_lon_min': left, 'pixel_bounds_lon_max': right,
        'pixel_bounds_lat_min': bottom, 'pixel_bounds_lat_max': top,
        'pixel_centro_lon': (left + right) / 2, 'pixel_centro_lat': (bottom + top) / 2,
        'ponto_consultado_lon': lon, 'ponto_consultado_lat': lat,
        'convencao_indexacao': 'numpy.floor (padrão de rasterio.DatasetReader.index)',
        'ponto_sobre_borda_ou_quina_de_pixel': bool(sobre_borda_lon or sobre_borda_lat),
        'ponto_sobre_quina_compartilhada_por_4_pixels': bool(sobre_borda_lon and sobre_borda_lat),
    }


# ══════════════════════════════════════════════════════════════════════════
# Classificação do valor — nunca ausência vira zero (Seção 5)
# ══════════════════════════════════════════════════════════════════════════

def classificar_valor(valor_bruto):
    """Distingue precipitação real ZERO de NoData — nunca converte
    ausência em zero silenciosamente (restrição central da Seção 5).
    Também sinaliza valor negativo que NÃO é a sentinela conhecida
    (poderia ser uma sentinela nova não catalogada — mesmo princípio
    de CLAUDE.md armadilha 6 para TSA/PDO) e valor implausivelmente
    alto (possível erro de unidade ou corrupção)."""
    valor = float(valor_bruto)
    if np.isnan(valor):
        return {'status': 'nodata_nan', 'valor_mm': None}
    if abs(valor - NODATA_SENTINELA) < 1e-3:
        return {'status': 'nodata_sentinela', 'valor_mm': None}
    if valor < 0:
        return {'status': 'valor_negativo_nao_e_sentinela_conhecida', 'valor_mm': valor}
    if valor > LIMITE_FISICO_PLAUSIVEL_MM_MES:
        return {'status': 'valor_implausivel_alto', 'valor_mm': valor}
    if valor == 0.0:
        return {'status': 'zero_real', 'valor_mm': 0.0}
    return {'status': 'ok', 'valor_mm': round(valor, 4)}


# ══════════════════════════════════════════════════════════════════════════
# Abertura remota (rede) — separada da lógica pura acima para permitir
# teste sintético via rasterio.io.MemoryFile, sem rede real
# ══════════════════════════════════════════════════════════════════════════

def abrir_dataset_remoto(ano, mes, formato='cog', timeout=TIMEOUT_SEGUNDOS):
    """Abre o raster remoto via GDAL /vsicurl/ (range-request HTTP) —
    NUNCA baixa o arquivo inteiro para disco. Chamador deve usar como
    context manager (`with abrir_dataset_remoto(...) as ds:`)."""
    url = montar_url(ano, mes, formato)
    env = rasterio.Env(GDAL_HTTP_TIMEOUT=timeout, GDAL_HTTP_CONNECTTIMEOUT=timeout,
                        CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.cog,.tif')
    env.__enter__()
    try:
        ds = rasterio.open(f'/vsicurl/{url}')
    except Exception:
        env.__exit__(None, None, None)
        raise
    return _DatasetComEnv(ds, env)


class _DatasetComEnv:
    """Fecha o rasterio.Env junto com o dataset ao sair do `with` —
    evita vazar configuração de ambiente GDAL entre extrações."""

    def __init__(self, dataset, env):
        self._dataset = dataset
        self._env = env

    def __enter__(self):
        return self._dataset

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._dataset.close()
        self._env.__exit__(exc_type, exc_val, exc_tb)
        return False


# ══════════════════════════════════════════════════════════════════════════
# Extração de um mês — orquestra tudo acima
# ══════════════════════════════════════════════════════════════════════════

def extrair_pixel_mensal(ano, mes, lat=FAZENDAS_LAT, lon=FAZENDAS_LON, formato='cog',
                          timeout=TIMEOUT_SEGUNDOS, abrir_fn=None):
    """Extração de UM mês, ponto único no centroide (ou coordenada
    fornecida), direto do CHIRPS v3.0 Final mensal já consolidado —
    nunca soma de diários (item 2). Nunca grava zero para mês/valor
    ausente (item 5) — ver classificar_valor(). Reprova (status !=
    'ok'/'zero_real') se a grade não bater com a esperada (item 5) ou
    se o arquivo estiver corrompido/incompleto.

    `abrir_fn`, se fornecido, substitui abrir_dataset_remoto por uma
    função injetada — usado SÓ em teste sintético
    (tests/test_chirps_v3_extracao.py, via rasterio.io.MemoryFile),
    nunca em produção real."""
    url = montar_url(ano, mes, formato)
    resultado = {
        'ano': ano, 'mes': mes, 'formato': formato, 'url': url,
        'versao_chirps': VERSAO_CHIRPS,
        'data_extracao_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
    }

    identificacao = verificar_disponibilidade_http(url, timeout=timeout)
    resultado['identificacao_arquivo'] = identificacao
    if not identificacao['disponivel']:
        resultado['status'] = ('mes_ausente' if identificacao.get('motivo') == 'mes_ausente'
                                else 'erro_verificacao_disponibilidade')
        resultado['valor_mm'] = None
        return resultado

    abrir = abrir_fn or (lambda: abrir_dataset_remoto(ano, mes, formato, timeout))
    try:
        with abrir() as ds:
            grade = verificar_grade(ds)
            resultado['verificacao_grade'] = grade
            if not grade['grade_ok']:
                resultado['status'] = 'grade_inesperada'
                resultado['valor_mm'] = None
                return resultado

            pixel = localizar_pixel(ds, lat=lat, lon=lon)
            resultado['pixel'] = pixel

            window = rasterio.windows.Window(pixel['col'], pixel['row'], 1, 1)
            arr = ds.read(1, window=window)
            if arr.size != 1:
                resultado['status'] = 'leitura_de_pixel_falhou'
                resultado['valor_mm'] = None
                return resultado

            classificacao = classificar_valor(arr[0, 0])
            resultado.update(classificacao)
    except rasterio.errors.RasterioIOError as e:
        resultado['status'] = 'arquivo_corrompido_ou_incompleto'
        resultado['valor_mm'] = None
        resultado['erro'] = str(e)
    except Exception as e:
        resultado['status'] = 'erro_inesperado'
        resultado['valor_mm'] = None
        resultado['erro'] = str(e)
    return resultado
