#!/usr/bin/env python3
"""
nmme_download.py — Fase 2C.1: acesso a dados NMME (infraestrutura,
Seção 27). NÃO executado contra a rede real nesta tarefa (Seção 38/50)
— só a estrutura/URLs/cache ficam prontas para revisão humana antes do
primeiro POC real.

ROTA DE DADOS ESCOLHIDA (Seção 9/17) — das 4 investigadas:
  A. CPC/NOAA arquivos atuais — páginas HTML alcançadas nesta sessão
     (`cpc.ncep.noaa.gov/products/NMME/*`) não continham link direto a
     arquivo de dado (só descrição textual/navegação/galerias de mapa).
  B. CPC FTP (`ftp.cpc.ncep.noaa.gov`) — BLOQUEADO para WebFetch nesta
     sessão (EGRESS_BLOCKED confirmado por tentativa direta); não pôde
     ser investigado de primeira mão.
  C. IRI Data Library — já listada como rota oficial no enunciado
     (Seção 2, "se ainda necessário para hindcasts"); foi a ÚNICA rota
     para a qual esta sessão encontrou paths de catálogo REAIS (via
     título indexado por busca, não abertura direta — ver
     nmme_catalogo.py) para GFDL-SPEAR, GEM5-NEMO (CanSIPS-IC3) e
     NCAR-CESM1. Escolhida como PRINCIPAL por eliminação.
  D. outra rota oficial — não identificada nesta sessão.

A sintaxe de URL abaixo segue o padrão público "ingrid" da IRIDL
(seleção X/Y/S encadeada, terminando em `data.nc` para subset já
recortado — evita baixar o dataset global, Seção 9) — mas
`iridl.ldeo.columbia.edu` ficou BLOQUEADO para WebFetch nesta sessão,
então o path exato por modelo/variável nunca foi aberto e confirmado de
primeira mão. Tratar como PLANO A REVISAR, nunca como acesso já
validado — o primeiro uso real é o próprio POC (Seção 17/38), que deve
falhar explicitamente (nunca simular sucesso) se o path estiver errado.
"""

import time
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
CACHE_DIR = ROOT / 'cache' / 'nmme'

TIMEOUT_SEGUNDOS = 60
MAX_TENTATIVAS = 3
ESPERAS_RETRY_SEGUNDOS = [5, 15, 30]


def montar_url_iridl(sistema, ano, mes, lat, lon, variavel=None):
    """Constrói a URL de subset IRIDL (sintaxe ingrid) para 1 origem x 1
    ponto. NUNCA adivinha path/variável ausentes no catálogo — levanta
    ValueError explícito em vez disso (Seção 6: 'quando uma informação
    não puder ser comprovada, usar None, nunca inventar' — o mesmo vale
    para não *usar* um None como se fosse um valor)."""
    if not sistema.data_url_template:
        raise ValueError(f"{sistema.centre}/{sistema.model_name}: data_url_template não confirmado "
                          f"no catálogo — não é possível montar a URL sem inventar o path (Seção 6).")
    variavel = variavel or sistema.precip_variable
    if not variavel:
        raise ValueError(f"{sistema.centre}/{sistema.model_name}: precip_variable não confirmado no "
                          f"catálogo — nunca adivinhar o nome da variável (Seção 11).")
    base = sistema.data_url_template.split(' ')[0].rstrip('/')
    return f"{base}/.{variavel}/X/{lon}/VALUE/Y/{lat}/VALUE/S/({mes:02d}%20{ano})/VALUE/data.nc"


def verificar_acesso():
    """NMME não exige credencial conhecida (Seção 29 — preferir fontes
    públicas; se alguma rota exigir autenticação, documentar e nunca
    pedir token nesta etapa). Não testa a rede de verdade — isso só
    acontece no POC real, fora do escopo desta tarefa (Seção 38/50)."""
    return {'credenciais_necessarias': False,
            'nota': 'Fontes públicas oficiais investigadas (Seção 2) — sem token/segredo esperado. '
                     'Se o POC real encontrar uma rota que exija autenticação, documentar aqui antes '
                     'de prosseguir, nunca inserir segredo em código (Seção 29).'}


def caminho_cache(sistema, ano, mes):
    """Nunca commitado (Seção 28, ver .gitignore) — só NetCDF pequeno já
    recortado por ponto (Seção 9), nunca dataset global."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    nome = f'{sistema.centre}_{sistema.model_name}_{ano:04d}-{mes:02d}.nc'
    return CACHE_DIR / nome


def baixar_arquivo(url, destino, sleep_fn=time.sleep, max_tentativas=MAX_TENTATIVAS):
    """Download genérico com cache local + retry (nunca sobrescreve um
    cache já presente e não-vazio). Mesma filosofia de
    c3s_validacao_multiorigem.py::_baixar_com_retry_e_cache (cache
    local, retry com backoff, falha explícita), via `requests` (HTTP
    simples) em vez de `cdsapi` — protocolo diferente, mesmo desenho.
    Devolve (caminho, cache_hit)."""
    destino = Path(destino)
    if destino.exists() and destino.stat().st_size > 0:
        return destino, True
    ultimo_erro = None
    for tentativa in range(1, max_tentativas + 1):
        try:
            resp = requests.get(url, timeout=TIMEOUT_SEGUNDOS)
            resp.raise_for_status()
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(resp.content)
            return destino, False
        except Exception as e:
            ultimo_erro = e
            if tentativa < max_tentativas:
                espera = ESPERAS_RETRY_SEGUNDOS[min(tentativa - 1, len(ESPERAS_RETRY_SEGUNDOS) - 1)]
                sleep_fn(espera)
    raise RuntimeError(f"download NMME falhou após {max_tentativas} tentativas ({url}): {ultimo_erro}")
