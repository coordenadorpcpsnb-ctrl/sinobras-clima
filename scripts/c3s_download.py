#!/usr/bin/env python3
"""
c3s_download.py — Fase 2A: download/cache de dados C3S via CDS API.

CREDENCIAIS (Seção 17) — NUNCA commitadas aqui nem em nenhum outro
arquivo deste repositório. O CDS exige uma conta gratuita em
https://cds.climate.copernicus.eu e uma chave de API salva em
`~/.cdsapirc` (formato oficial, 2 linhas):

    url: https://cds.climate.copernicus.eu/api
    key: <seu-personal-access-token>

Ou as variáveis de ambiente `CDSAPI_URL` e `CDSAPI_KEY` (o pacote
`cdsapi` lê qualquer uma das duas formas). Nenhuma das duas está
presente nesta sessão (verificado — ver `verificar_acesso()`), e a
própria rede desta sessão bloqueia por política o domínio
cds.climate.copernicus.eu (testado com curl/WebFetch: "gateway
answered 403 to CONNECT"), então mesmo com credenciais válidas o
download não funcionaria neste ambiente específico. Isso é uma
limitação do AMBIENTE, não do código — rodando este mesmo módulo numa
máquina com rede liberada e `~/.cdsapirc` configurado, `baixar_*()`
deve funcionar sem alteração.

CACHE (Seção 16): tudo grande (GRIB/NetCDF) vai para `data/c3s_cache/`,
listado no `.gitignore` — nunca commitado. Só metadados pequenos (JSON)
descrevendo o que está em cache entram no controle de versão indiretamente
(via os CSVs derivados que c3s_processar.py grava fora do cache).
"""

import hashlib
import json
import os
import warnings
from pathlib import Path

ROOT = Path(__file__).parent.parent
CACHE_DIR = ROOT / 'data' / 'c3s_cache'


def _cdsapirc_existe():
    return Path.home().joinpath('.cdsapirc').exists()


def _credenciais_por_env():
    return bool(os.environ.get('CDSAPI_URL')) and bool(os.environ.get('CDSAPI_KEY'))


def verificar_credenciais():
    """Não lê nem imprime a chave — só diz se ALGUMA fonte de credencial
    está configurada."""
    return _cdsapirc_existe() or _credenciais_por_env()


def verificar_rede(timeout_segundos=8):
    """Tenta uma requisição HTTPS real ao endpoint do CDS, pelo mesmo
    caminho que `requests`/`cdsapi` usariam (respeitando HTTP_PROXY/
    HTTPS_PROXY do ambiente). IMPORTANTE: um socket TCP+TLS cru
    (socket.create_connection + ssl wrap) NÃO serve para esse teste —
    nesta sessão ele completa com sucesso porque o proxy de egress faz
    interceptação TLS e responde ao handshake mesmo para domínios
    bloqueados, devolvendo o bloqueio (403) só na camada HTTP seguinte.
    Usar socket cru aqui daria falso-positivo (testado e corrigido)."""
    import urllib.request
    try:
        urllib.request.urlopen('https://cds.climate.copernicus.eu/api', timeout=timeout_segundos)
        return True
    except Exception:
        return False


def verificar_acesso(verbose=True):
    """Diagnóstico único, sem lançar exceção — usado por baixar_*() antes
    de tentar qualquer requisição real, e diretamente pelos scripts para
    decidir se seguem em frente ou caem no caminho offline/mock."""
    credenciais_ok = verificar_credenciais()
    rede_ok = verificar_rede()
    try:
        import cdsapi  # noqa: F401
        pacote_ok = True
    except ImportError:
        pacote_ok = False

    status = {
        'credenciais_configuradas': credenciais_ok,
        'rede_alcancavel': rede_ok,
        'pacote_cdsapi_instalado': pacote_ok,
        'pronto_para_download_real': credenciais_ok and rede_ok and pacote_ok,
    }
    if verbose and not status['pronto_para_download_real']:
        faltando = []
        if not pacote_ok:
            faltando.append("pip install cdsapi")
        if not credenciais_ok:
            faltando.append("configurar ~/.cdsapirc (ver docstring deste módulo) com uma "
                             "chave de https://cds.climate.copernicus.eu")
        if not rede_ok:
            faltando.append("rede até cds.climate.copernicus.eu:443 (bloqueada nesta sessão "
                             "por política do proxy de egress)")
        print("  ⚠ Download real do C3S indisponível nesta sessão. Faltando: " + "; ".join(faltando))
    return status


def _chave_cache(request_dict):
    """Nome de arquivo determinístico a partir do dicionário de request
    do CDS (mesmo request -> mesmo arquivo, sem baixar de novo)."""
    blob = json.dumps(request_dict, sort_keys=True).encode('utf-8')
    return hashlib.sha256(blob).hexdigest()[:24]


def caminho_cache(dataset, request_dict, extensao='grib'):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{dataset}_{_chave_cache(request_dict)}.{extensao}"


def montar_request_hindcast(system, ano, mes, area, leadtime_months, variavel='total_precipitation'):
    """Monta o dicionário de request do CDS para o dataset
    'seasonal-monthly-single-levels', produto hindcast. `area` é
    [north, west, south, east] em graus — construído a partir do ponto
    + DELTA_CAIXA_GRAU em _c3s_utils.py, nunca a fazenda."""
    return {
        'originating_centre': system[0].lower(), 'system': system[1],
        'variable': variavel, 'product_type': 'monthly_mean',
        'year': [str(ano)], 'month': [f'{mes:02d}'],
        'leadtime_month': [str(L) for L in leadtime_months],
        'area': area, 'format': 'grib',
    }


def montar_request_forecast(system, ano, mes, area, leadtime_months, variavel='total_precipitation'):
    req = montar_request_hindcast(system, ano, mes, area, leadtime_months, variavel)
    return req   # mesmo schema — 'year'/'month' de forecast real (não passado) é o que distingue


def baixar(dataset, request_dict, extensao='grib', forcar=False):
    """Download real (usa cdsapi.Client().retrieve). Levanta RuntimeError
    com mensagem acionável se credenciais/rede/pacote não estiverem
    prontos — nunca inventa dado nem baixa silenciosamente algo mockado."""
    destino = caminho_cache(dataset, request_dict, extensao)
    if destino.exists() and not forcar:
        return destino

    status = verificar_acesso(verbose=False)
    if not status['pronto_para_download_real']:
        raise RuntimeError(
            "Download real do C3S não está disponível nesta sessão "
            f"(diagnóstico: {status}). Ver docstring de c3s_download.py "
            "para o que precisa ser configurado. Use dados sintéticos/mock "
            "para desenvolvimento e teste offline (ver tests/test_c3s_*.py).")

    import cdsapi
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        client = cdsapi.Client()
        client.retrieve(dataset, request_dict, str(destino))
    return destino
