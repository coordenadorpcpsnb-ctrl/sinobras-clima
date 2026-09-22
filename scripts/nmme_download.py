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


# ══════════════════════════════════════════════════════════════════════════
# Rodada 4 (correção pós-revisão) — Rota B: dataset IRI member-level do
# CFSv2 (distinto da Rota A/CPT ensemble-mean, Rodada 3). Endpoint +
# variável + as 5 dimensões (S/M/L/X/Y) EMPIRICALLY_CONFIRMED via
# leitura direta do catálogo-fonte Ingrid (github.com/iridl/dlentries,
# entries/NOAA/NCEP/EMC/CFSv2/ENSEMBLE/FLXF/index.tex) — ver a nota
# completa em nmme_catalogo.py. O servidor real (iridl.ldeo.columbia.edu)
# continua bloqueado nesta sessão — a sintaxe de seleção abaixo (RANGE
# de L) segue a convenção pública "ingrid" já usada em montar_url_iridl,
# mas NÃO foi testada contra o servidor real (Seção 11 da tarefa: "gerado
# de forma auditável", não "confirmado").
# ══════════════════════════════════════════════════════════════════════════

IRI_CFSV2_MEMBER_LEVEL_BASE = 'https://iridl.ldeo.columbia.edu'
IRI_CFSV2_MEMBER_LEVEL_PATH = 'SOURCES/.NOAA/.NCEP/.EMC/.CFSv2/.ENSEMBLE/.FLXF/.surface/.PRATE'

# S grid nativo (EMPIRICALLY_CONFIRMED, Rodada 4) — início/fim do
# arquivo homogêneo desta rota; DISTINTO do período conceitual NMME3
# (hindcast_start/end no catálogo, 1991-2020).
S_NATIVO_INICIO = (1981, 12, 12)
S_NATIVO_FIM = (2011, 3, 27)

# L grid nativo (EMPIRICALLY_CONFIRMED, Rodada 4): "grid: /name /L def
# /units (months) def   .5 1 9.5 :grid" — início 0.5, passo 1, fim 9.5.
L_NATIVO_INICIO, L_NATIVO_PASSO, L_NATIVO_FIM = 0.5, 1.0, 9.5

# M grid nativo (EMPIRICALLY_CONFIRMED, Rodada 4): "/M 28 NewIntegerGRID"
# — tamanho FIXO 28 no catálogo. A contagem REAL de membros não-missing
# num subset pode ser menor (Seção 5 da tarefa — nunca hardcodar 24).
M_NATIVO_TAMANHO = 28
M_OBSERVADO_MIN, M_OBSERVADO_MAX = 24, 28


def origem_dentro_do_nativo_rota_b(ano, mes):
    """Verifica (ano, mes) contra o S grid NATIVO empiricamente
    confirmado da rota B (Seção 15-B/C da tarefa) — nunca contra
    hindcast_start/hindcast_end do catálogo (que são o período
    CONCEITUAL do NMME3 pooled, Seção 6)."""
    ini = pd_period(*S_NATIVO_INICIO[:2])
    fim = pd_period(*S_NATIVO_FIM[:2])
    alvo = pd_period(ano, mes)
    return ini <= alvo <= fim


def pd_period(ano, mes):
    import pandas as pd
    return pd.Period(f'{ano:04d}-{mes:02d}', 'M')


def h_lead_para_L_ingrid(h):
    """Mapeia H1..H10 (nossa convenção inteira de lead) para o valor L
    real do grid Ingrid (0.5, 1.5, ..., 9.5 — EMPIRICALLY_CONFIRMED,
    Rodada 4). NUNCA arredonda silenciosamente: a correspondência H{h}
    <-> L={h-0.5} é HIPÓTESE (Seção 8 da tarefa — 'não deve ser mapeado
    automaticamente pela lógica C3S'), não confirmada contra um subset
    real aberto. Todo uso desta função deve registrar
    source_lead_coordinate/mapping_status explicitamente (ver
    nmme_processar.montar_linha_temporal_audit)."""
    if not (1 <= h <= 10):
        raise ValueError(f"H fora da faixa nativa do grid L (H1-H10, L 0.5-9.5); recebido H{h}.")
    return h - 0.5


def montar_url_iri_cfsv2_member_level(ano, mes, lat, lon, h_lead_min=1, h_lead_max=6):
    """Monta a URL de subset IRIDL (sintaxe ingrid, Rota B) para 1
    origem x 1 ponto x uma faixa de leads H — NUNCA baixa o globo nem
    todos os 30 anos: X/Y recortados a um ponto, S a uma única origem,
    L a uma faixa pequena de leads (Seção 11 da tarefa). M fica
    IRRESTRITO (queremos todos os membros — esse é o objetivo do POC
    por membro). Levanta ValueError explícito se a origem estiver fora
    do S grid nativo (Seção 15-C) — nunca monta um request para um
    período que o arquivo não cobre."""
    if not origem_dentro_do_nativo_rota_b(ano, mes):
        raise ValueError(f"origem {ano:04d}-{mes:02d} fora do S grid nativo da Rota B "
                          f"({S_NATIVO_INICIO[0]}-{S_NATIVO_INICIO[1]:02d} a "
                          f"{S_NATIVO_FIM[0]}-{S_NATIVO_FIM[1]:02d}) — nunca montar request para "
                          f"período que o catálogo-fonte não documenta (Seção 15-C).")
    l_ini, l_fim = h_lead_para_L_ingrid(h_lead_min), h_lead_para_L_ingrid(h_lead_max)
    base = f'{IRI_CFSV2_MEMBER_LEVEL_BASE}/{IRI_CFSV2_MEMBER_LEVEL_PATH}'
    return (f"{base}/X/{lon}/VALUE/Y/{lat}/VALUE/"
            f"S/({mes:02d}%20{ano})/VALUE/"
            f"L/({l_ini})/({l_fim})/RANGEEDGES/data.nc")


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
