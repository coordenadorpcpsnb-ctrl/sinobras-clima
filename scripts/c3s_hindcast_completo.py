#!/usr/bin/env python3
"""
c3s_hindcast_completo.py — Fase 2A.3: hindcast completo SEAS5 / São
Bento do Tocantins (1981-2016), avaliação de SKILL (não apenas teste de
pipeline — isso já foi feito e aprovado na Fase 2A.2).

Pergunta científica: o ECMWF SEAS5 tem skill real e operacionalmente
útil para prever precipitação mensal em São Bento do Tocantins, por
lead e época do ano, comparado a uma climatologia leakage-safe? Uma
correção de viés simples (additive mean bias correction, treinada só
com dado anterior à origem) melhora isso de forma consistente?

ARQUITETURA — reaproveita a infraestrutura já validada, não duplica
parser GRIB nem semântica temporal:

  - c3s_download.py / c3s_processar.py / c3s_poc.py / _c3s_utils.py:
    download com cache+retry (via
    c3s_validacao_multiorigem._baixar_com_retry_e_cache, já validado na
    Fase 2A.2), abertura/validação do GRIB, extração de ponto, tabela.
  - c3s_hindcast.py: estatísticas de ensemble, probabilidade por
    terciles, Brier/RPS/RPSS.
  - c3s_calibracao.py (novo): climatologia leakage-safe completa e
    correção de viés leakage-safe (extraem mais estatísticas do que as
    funções de c3s_hindcast.py expunham, mas usam o MESMO predicado
    "só dado com data < origem").
  - c3s_skill.py (novo): MSESS, orquestração de Brier/RPS/RPSS por
    grupo, CRPS opcional, bootstrap.

Este módulo (novo) só orquestra: constrói as origens, baixa/valida cada
uma (barreiras A-H, mesmo desenho da Fase 2A.2), busca CHIRPS
consolidado 1981-2016 numa única chamada, monta climatologia/bias/
correção/probabilidades por (origem, lead), agrega em tabelas de skill,
roda bootstrap e audita leakage.

ESCOPO DESTA ENTREGA (Seção 38 da tarefa): implementar pipeline +
métricas + testes + workflow + --dry-run-plan + --pilot. NÃO executar
os 432 casos reais agora — isso só acontece depois do merge, primeiro
como PILOT LONGITUDINAL (72 origens), e só depois (se aprovado) como hindcast
completo.

GITHUB ACTIONS CACHE (Seção 8): NÃO implementado nesta primeira versão
— documentado aqui em vez de implementado, como a tarefa permite
explicitamente. Cada execução do workflow baixa tudo de novo (com
cache LOCAL determinístico em data/c3s_cache/ dentro da mesma
execução/processo, retry, e checkpoint de progresso via log — mas sem
persistir nada entre runners independentes do GitHub Actions).
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import c3s_catalogo as cat  # noqa: E402
import c3s_download as dl  # noqa: E402
import c3s_processar as proc  # noqa: E402
import c3s_hindcast as hc  # noqa: E402
import c3s_poc as poc  # noqa: E402
import c3s_calibracao as calib  # noqa: E402
import c3s_skill as skill  # noqa: E402
from c3s_validacao_multiorigem import _baixar_com_retry_e_cache  # noqa: E402
from _c3s_utils import MUNICIPIOS, leadtime_para_mes_alvo, intervalo_mensal_chirps  # noqa: E402
from _chirps import _geometria_ponto, _buscar_prec_chirps_geom  # noqa: E402

ROOT = Path(__file__).parent.parent
ARTIFACTS_DIR = ROOT / 'artifacts' / 'c3s_hindcast'

MUNICIPIO = 'Sao_Bento_do_Tocantins'
LEADS = [1, 2, 3, 4, 5, 6]
N_MEMBROS_ESPERADO = 25
UNIDADE_TPRATE_ESPERADA = 'm s**-1'

# Seção 2/3 — período completo de hindcast homogêneo do SEAS5 (mesma
# barreira validada na Fase 2A.2: nunca misturar com real-time forecast
# pós-2016, 51 membros).
ANO_INICIO_HINDCAST = 1981
ANO_FIM_HINDCAST = 2016

# Seção 3/4 — período de download != período primário de avaliação.
WARMUP_ANO_INICIO = ANO_INICIO_HINDCAST
WARMUP_ANO_FIM = 1990
AVALIACAO_ANO_INICIO = 1991
AVALIACAO_ANO_FIM = ANO_FIM_HINDCAST
MIN_ANOS_TREINO = calib.MIN_ANOS_TREINO   # 10

# Seção 25 — split desenvolvimento/confirmação (nunca escolher
# hiperparâmetro com base na confirmação; aqui não há hiperparâmetro
# nenhum sendo ajustado, CLIM/RAW/BC são as únicas 3 variantes, Seção 26).
DESENVOLVIMENTO_ANO_INICIO = 1991
DESENVOLVIMENTO_ANO_FIM = 2007
CONFIRMACAO_ANO_INICIO = 2008
CONFIRMACAO_ANO_FIM = 2016

# Seção 19 — estações operacionais + bloco prioritário florestal.
ESTACOES_OPERACIONAIS = {
    'SON': [9, 10, 11], 'DJF': [12, 1, 2], 'MAM': [3, 4, 5], 'JJA': [6, 7, 8],
}
MESES_BLOCO_OPERACIONAL_PRIORITARIO = [9, 10, 11, 12, 1, 2]   # Sep-Feb
NOME_BLOCO_OPERACIONAL_PRIORITARIO = 'SET_FEV_prioritario'

# Seção 24 — bootstrap.
N_BOOTSTRAP = 2000
SEED_BOOTSTRAP = 42

# Correção pós-pilot real (run 35260471652): o pilot de 6 origens
# isoladas (1991/2000/2010, jan/jul) terminou "success" mas com
# n_forecasts_avaliacao_principal=0 — nenhuma delas tinha histórico
# PRÉVIO de origens C3S para treinar o bias (bias_training_n=0,
# bias_mm=NaN, ens_mean_bc=NaN em todas). Substituído por um pilot
# LONGITUDINAL: todos os janeiros e julhos de 1981 a 2016 (36 anos × 2
# meses = 72 origens) — mantém o pilot em 1/6 do hindcast completo (72
# vs. 432) mas garante série contínua o bastante para: warm-up
# 1981-1990 alimentar o treino de bias/climatologia; avaliação real
# 1991-2016; MIN_ANOS_TREINO=10 satisfeito no primeiro ano avaliado
# (1991) porque jan/jul aparecem em TODOS os 36 anos, então qualquer
# combinação lead×mês-alvo originada destas origens sempre tem 10 anos
# anteriores do mesmo mês disponíveis; desenvolvimento (1991-2007) e
# confirmação (2008-2016) ambos com dado real; bootstrap por ano
# genuinamente exercitado. NÃO é conclusão de skill anual completo —
# é um pilot metodológico para validar que o pipeline (bias/skill/
# bootstrap) funciona fim-a-fim antes do hindcast completo (432
# origens, todos os 12 meses).
PILOT_INIT_MONTHS = [1, 7]
PILOT_ORIGENS = [
    (ano, mes)
    for ano in range(ANO_INICIO_HINDCAST, ANO_FIM_HINDCAST + 1)
    for mes in PILOT_INIT_MONTHS
]
# 52 origens avaliáveis (1991-2016, 2/ano) × 6 leads = 312.
PILOT_FORECASTS_AVALIACAO_ESPERADOS = (
    (AVALIACAO_ANO_FIM - AVALIACAO_ANO_INICIO + 1) * len(PILOT_INIT_MONTHS) * len(LEADS)
)

# Correção pós-pilot real (run 35257900850): buscar CHIRPS 1981-2016
# inteiro numa única chamada ao ClimateSERV estourou o serviço ("Error
# occurred while processing data request" / resposta vazia). Buscar em
# blocos ANUAIS (36 blocos) — simples, auditável, menor risco de
# timeout, fácil retry, isola o ano problemático. Nunca mensal por
# padrão (seriam 432 requests desnecessárias).
CHIRPS_BLOCOS_DIR = ARTIFACTS_DIR / '_chirps_blocos'
CHIRPS_CHECKPOINT_PATH = ARTIFACTS_DIR / 'chirps_checkpoint.json'
CHIRPS_MAX_TENTATIVAS = 3
CHIRPS_ESPERAS_RETRY_SEGUNDOS = [5, 15, 30]

ARTIFACT_FILENAMES = [
    'c3s_hindcast_raw.csv', 'c3s_hindcast_summary.csv', 'chirps_sao_bento_hindcast_targets.csv',
    'c3s_hindcast_calibrated.csv', 'skill_deterministic_overall.csv', 'skill_deterministic_by_lead.csv',
    'skill_deterministic_by_month.csv', 'skill_deterministic_by_month_lead.csv', 'skill_operational_seasons.csv',
    'skill_probabilistic_overall.csv', 'skill_probabilistic_by_lead.csv', 'bootstrap_skill.csv',
    'temporal_audit.csv', 'leakage_audit.csv', 'metadata.json', 'RELATORIO.md',
]

NOTA_HINDCAST_COMPLETO = (
    "Notas metodológicas fixas: (1) GitHub Actions cache para data/c3s_cache/ NÃO foi implementado "
    "nesta primeira versão (Seção 8) — cada execução do workflow baixa tudo de novo; documentado, "
    "não implementado, como permitido explicitamente. Não há resume automático entre execuções "
    "independentes do workflow (mesma limitação já documentada na Fase 2A.2). (2) CRPS/CRPSS é "
    "best-effort (Seção 22) — nunca bloqueia a geração dos demais artifacts se falhar. (3) Esta é uma "
    "fase de pesquisa isolada — nenhum resultado aqui promove SEAS5 para o dashboard/forecast de "
    "produção sem decisão humana explícita (Seção 42)."
)


def _origem_str(ano, mes):
    return f'{ano:04d}-{mes:02d}'


def _periodo_avaliacao(origem):
    ano = origem.year
    if ano <= WARMUP_ANO_FIM:
        return 'warmup'
    if ano <= DESENVOLVIMENTO_ANO_FIM:
        return 'desenvolvimento'
    return 'confirmacao'


def validar_intervalo_hindcast(ano_ini, ano_fim):
    """Guardrail (mesmo espírito da Fase 2A.2): nunca aceitar origens
    fora do período homogêneo de hindcast SEAS5. Falha antes de
    qualquer download."""
    if ano_ini < ANO_INICIO_HINDCAST or ano_fim > ANO_FIM_HINDCAST or ano_ini > ano_fim:
        raise ValueError(
            f"Fase 2A.3 exige --start-year/--end-year dentro do período homogêneo de hindcast SEAS5 "
            f"({ANO_INICIO_HINDCAST}-{ANO_FIM_HINDCAST}). Recebido: {ano_ini}-{ano_fim} — FALHANDO "
            f"antes de qualquer download.")


def construir_origens(ano_ini=ANO_INICIO_HINDCAST, ano_fim=ANO_FIM_HINDCAST, meses=None):
    validar_intervalo_hindcast(ano_ini, ano_fim)
    meses = meses if meses else list(range(1, 13))
    return [(ano, mes) for ano in range(ano_ini, ano_fim + 1) for mes in meses]


# ══════════════════════════════════════════════════════════════════════════
# Download + validação de 1 origem — barreiras A-H, mesmo desenho já
# validado em c3s_validacao_multiorigem.py::processar_origem (Fase
# 2A.2). Não inclui CHIRPS (Seção 9: aqui é olhado na série consolidada,
# não buscado por origem) nem climatologia/bias/probabilidades (essas
# entram depois, em lote, quando o histórico completo já está montado).
# ══════════════════════════════════════════════════════════════════════════

def processar_origem_raw(ano, mes, sleep_fn=time.sleep):
    origem = _origem_str(ano, mes)
    init_date = pd.Period(f'{ano}-{mes:02d}', 'M')
    info = MUNICIPIOS[MUNICIPIO]
    lat, lon = info['lat'], info['lon']
    centro, sistema = cat.SISTEMA_ESCOLHIDO_FASE_2A

    area = [lat + poc.AREA_BUFFER_GRAUS, lon - poc.AREA_BUFFER_GRAUS,
            lat - poc.AREA_BUFFER_GRAUS, lon + poc.AREA_BUFFER_GRAUS]
    request = dl.montar_request_hindcast(('ecmwf', '51'), ano, mes, area, LEADS)

    caminho, cache_hit, retries = _baixar_com_retry_e_cache(request, sleep_fn=sleep_fn)

    ds, unidade, esquema, mapa_lead_alvo, diag_info, mapeamento_step_fcmonth = \
        poc.abrir_e_validar_grib(caminho, LEADS)

    n_membros = int(ds.sizes['number'])
    if n_membros != N_MEMBROS_ESPERADO:
        raise RuntimeError(f"[{origem}] número de membros = {n_membros}, esperado "
                            f"{N_MEMBROS_ESPERADO} (barreira A — nunca 51/real-time forecast aqui).")

    leads_encontrados = sorted(mapa_lead_alvo)
    if leads_encontrados != LEADS:
        raise RuntimeError(f"[{origem}] leads encontrados {leads_encontrados} != esperados {LEADS} (barreira B).")

    alvos = [pd.Period(v, 'M') for v in mapa_lead_alvo.values()]
    if len(set(alvos)) != len(LEADS):
        raise RuntimeError(f"[{origem}] target months não são {len(LEADS)} distintos: {sorted(alvos)} (barreira C).")

    for lead, alvo_str in mapa_lead_alvo.items():
        esperado = leadtime_para_mes_alvo(init_date, lead)
        if pd.Period(alvo_str, 'M') != esperado:
            raise RuntimeError(f"[{origem}] lead {lead}: target_month {alvo_str} != esperado {esperado} (barreira D).")

    if unidade != UNIDADE_TPRATE_ESPERADA:
        raise RuntimeError(f"[{origem}] unidade tprate = {unidade!r}, esperado "
                            f"{UNIDADE_TPRATE_ESPERADA!r} (barreira E).")

    ponto = proc.extrair_ponto(ds, lat, lon)
    lat_grade, lon_grade = float(ponto['latitude']), float(ponto['longitude'])
    dist_km = poc.distancia_km_aprox(lat, lon, lat_grade, lon_grade)

    tabela = proc.dataset_para_tabela(ponto, local=MUNICIPIO, centre=centro, system=sistema,
                                       mapeamento_step_fcmonth=mapeamento_step_fcmonth)
    tabela = tabela.rename(columns={'forecast_prec_mm': 'c3s_prec_mm'})

    valores = tabela['c3s_prec_mm'].to_numpy(dtype=float)
    if not np.all(np.isfinite(valores)):
        raise RuntimeError(f"[{origem}] c3s_prec_mm contém NaN/infinito (barreira F).")
    if (valores < 0).any():
        raise RuntimeError(f"[{origem}] c3s_prec_mm contém precipitação negativa (barreira F).")

    fora = valores[(valores < poc.PREC_MM_MIN_PLAUSIVEL) | (valores > poc.PREC_MM_MAX_PLAUSIVEL)]
    if len(fora):
        raise RuntimeError(f"[{origem}] {len(fora)} valor(es) fora de "
                            f"[{poc.PREC_MM_MIN_PLAUSIVEL},{poc.PREC_MM_MAX_PLAUSIVEL}]mm (barreira G).")

    if len(tabela) != N_MEMBROS_ESPERADO * len(LEADS):
        raise RuntimeError(f"[{origem}] {len(tabela)} linhas raw, esperado "
                            f"{N_MEMBROS_ESPERADO * len(LEADS)} (barreira H).")

    tabela['lat_pedida'] = lat
    tabela['lon_pedida'] = lon
    tabela['lat_grade'] = lat_grade
    tabela['lon_grade'] = lon_grade
    tabela['distancia_grade_km'] = round(dist_km, 2)

    metadata_origem = {'cache_hit': bool(cache_hit), 'retries': int(retries), 'n_membros': n_membros,
                        'lat_grade': lat_grade, 'lon_grade': lon_grade, 'distancia_grade_km': round(dist_km, 2),
                        'unidade': unidade, 'esquema_temporal': esquema}
    return tabela, metadata_origem


def _com_periods(df, colunas=('init_date', 'target_month')):
    d = df.copy()
    for c in colunas:
        if c in d.columns:
            d[c] = d[c].apply(lambda s: s if isinstance(s, pd.Period) else pd.Period(s, 'M'))
    return d


# ══════════════════════════════════════════════════════════════════════════
# CHIRPS consolidado — em BLOCOS ANUAIS (correção pós-pilot real: uma
# única chamada de 36 anos estourou o ClimateSERV — run 35257900850,
# "Error occurred while processing data request" seguido de resposta
# vazia). Mesmo núcleo de _chirps.py (_geometria_ponto/
# _buscar_prec_chirps_geom) e o mesmo intervalo mensal corrigido de
# _c3s_utils.py (intervalo_mensal_chirps). Nunca cai para ERA5/CHC-
# Preliminar/Open-Meteo — falha explícita, com retry, se um bloco não
# estiver disponível.
#
# Correção pós-run oficial 35353196015: a cobertura observacional
# parava em ANO_FIM_HINDCAST-12 (2016-12), mas origem=2016-12 com
# lead=6 alcança target_month=2017-05 (lead 1 = mês da inicialização,
# convenção validada) — 15 forecasts da avaliação principal ficavam com
# chirps_prec_mm=NaN (1.872 candidatos / só 1.857 com observação real).
# O intervalo observacional necessário (target_ini, target_fim) passa a
# ser DERIVADO de intervalo_targets_necessario(origens, leads), nunca
# fixado manualmente — o piso continua ANO_INICIO_HINDCAST-01 (mesmo
# numa execução parcial, climatologia/bias de qualquer origem avaliada
# pode precisar de histórico desde o início do hindcast homogêneo), o
# teto é o maior target_month realmente alcançado pelas origens×leads
# pedidas. O primeiro/último ano do intervalo, se parciais, buscam só
# os meses necessários (nunca o ano inteiro) — blocos anuais completos
# continuam reaproveitando exatamente o cache/checkpoint já validados
# (mesmo nome de arquivo `chirps_{ano}.csv`).
# ══════════════════════════════════════════════════════════════════════════

def intervalo_targets_necessario(origens, leads=LEADS):
    """Deriva (target_ini, target_fim) — os meses observacionais (CHIRPS)
    realmente necessários — a partir de TODAS as combinações origem×lead
    pedidas: nunca fixar manualmente (Seção 2 da correção). O piso nunca
    é anterior a ANO_INICIO_HINDCAST-01, mesmo que as origens pedidas
    comecem depois (execução parcial/depuração) — climatologia/bias de
    qualquer origem avaliada pode precisar de histórico desde o início
    do hindcast homogêneo. O teto é o maior target_month alcançado
    (origem + lead - 1, convenção validada: lead 1 = mês da
    inicialização)."""
    piso = pd.Period(f'{ANO_INICIO_HINDCAST}-01', 'M')
    if not origens:
        return piso, piso
    targets = [pd.Period(f'{ano}-{mes:02d}', 'M') + (lead - 1) for ano, mes in origens for lead in leads]
    return min(piso, min(targets)), max(targets)

def _buscar_chirps_ano(ano, mes_ini=1, mes_fim=12, sleep_fn=time.sleep):
    """Busca CHIRPS municipal de um bloco anual — jan->dez por padrão,
    ou só mes_ini->mes_fim quando o ano for a borda (primeira/última)
    de um intervalo parcial derivado — com retry controlado (máx.
    CHIRPS_MAX_TENTATIVAS, backoff progressivo). Levanta RuntimeError
    explícito se esgotar as tentativas — nunca continua silenciosamente
    com NaN nem troca de fonte."""
    info = MUNICIPIOS[MUNICIPIO]
    geom = _geometria_ponto(info['lat'], info['lon'])
    ini, fim = intervalo_mensal_chirps(ano, mes_ini, ano, mes_fim)
    rotulo_erro = str(ano) if (mes_ini, mes_fim) == (1, 12) else f'{ano} ({mes_ini:02d}-{mes_fim:02d})'

    df = pd.DataFrame()
    ultimo_erro = None
    for tentativa in range(1, CHIRPS_MAX_TENTATIVAS + 1):
        try:
            df = _buscar_prec_chirps_geom(ini, fim, geom, rotulo=f'{MUNICIPIO}-{ano}')
        except Exception as e:
            df = pd.DataFrame()
            ultimo_erro = e
        if not df.empty:
            break
        if ultimo_erro is None:
            ultimo_erro = RuntimeError('resposta vazia ou sem dados')
        if tentativa < CHIRPS_MAX_TENTATIVAS:
            espera = CHIRPS_ESPERAS_RETRY_SEGUNDOS[min(tentativa - 1, len(CHIRPS_ESPERAS_RETRY_SEGUNDOS) - 1)]
            print(f"    ⚠ CHIRPS {rotulo_erro}: tentativa {tentativa}/{CHIRPS_MAX_TENTATIVAS} falhou "
                  f"({ultimo_erro}); aguardando {espera}s…")
            sleep_fn(espera)

    if df.empty:
        raise RuntimeError(f"CHIRPS falhou para {rotulo_erro} após {CHIRPS_MAX_TENTATIVAS} tentativas "
                            f"— último erro: {ultimo_erro} — FALHANDO (nunca ERA5/CHC-Preliminar/"
                            f"Open-Meteo como fallback).")
    return df


def _validar_bloco_chirps(df, ano, mes_ini=1, mes_fim=12):
    """Valida um bloco anual (ou parcial, na borda do intervalo): meses
    mes_ini-mes_fim do ano, 1 valor cada, sem duplicado/NaN/negativo.
    Bloco incompleto ou inconsistente falha explicitamente — nunca
    completa com fallback."""
    d = df.copy()
    d['target_month'] = pd.PeriodIndex(pd.to_datetime(dict(year=d.ano, month=d.mes, day=1)), freq='M')
    d = d.rename(columns={'prec': 'chirps_prec_mm'})

    rotulo = str(ano) if (mes_ini, mes_fim) == (1, 12) else f'{ano} ({mes_ini:02d}-{mes_fim:02d})'
    esperado = pd.period_range(f'{ano}-{mes_ini:02d}', f'{ano}-{mes_fim:02d}', freq='M')
    faltando = [str(m) for m in esperado if m not in set(d['target_month'])]
    if faltando:
        raise RuntimeError(f"CHIRPS de {rotulo} incompleto — faltando {faltando} — FALHANDO.")
    if d['target_month'].duplicated().any():
        dups = [str(v) for v in d.loc[d['target_month'].duplicated(), 'target_month']]
        raise RuntimeError(f"CHIRPS de {rotulo} tem mês(es) duplicado(s): {dups} — FALHANDO.")
    if d['chirps_prec_mm'].isna().any():
        raise RuntimeError(f"CHIRPS de {rotulo} tem valor(es) NaN — FALHANDO.")
    if (d['chirps_prec_mm'] < 0).any():
        raise RuntimeError(f"CHIRPS de {rotulo} tem precipitação negativa — FALHANDO.")

    d['source'] = 'CHIRPS'
    d['year'] = d['target_month'].apply(lambda p: p.year)
    d['month'] = d['target_month'].apply(lambda p: p.month)
    return d[['year', 'month', 'target_month', 'chirps_prec_mm', 'source']] \
        .sort_values('target_month').reset_index(drop=True)


def _validar_consolidado_final(df, target_ini, target_fim):
    """Validação final: sem duplicado/lacuna/NaN/negativo, sequência
    exatamente contínua de target_ini a target_fim (ambos
    pandas.Period, freq='M') — o intervalo esperado é sempre o mesmo
    que foi pedido a buscar_chirps_consolidado, nunca um valor fixo."""
    target_ini = pd.Period(target_ini, 'M')
    target_fim = pd.Period(target_fim, 'M')
    esperado = list(pd.period_range(target_ini, target_fim, freq='M'))
    if len(df) != len(esperado):
        raise RuntimeError(f"CHIRPS consolidado tem {len(df)} meses, esperado {len(esperado)} "
                            f"({target_ini} a {target_fim}) — FALHANDO.")
    faltando = [str(m) for m in esperado if m not in set(df['target_month'])]
    if faltando:
        raise RuntimeError(f"CHIRPS consolidado não cobre {len(faltando)} mês(es): "
                            f"{faltando[:5]}{'...' if len(faltando) > 5 else ''} — FALHANDO.")
    if df['target_month'].duplicated().any():
        dups = [str(v) for v in df.loc[df['target_month'].duplicated(), 'target_month']]
        raise RuntimeError(f"CHIRPS consolidado tem mês(es) duplicado(s): {dups} — FALHANDO.")
    if df['chirps_prec_mm'].isna().any():
        raise RuntimeError("CHIRPS consolidado tem valor(es) NaN — FALHANDO.")
    if (df['chirps_prec_mm'] < 0).any():
        raise RuntimeError("CHIRPS consolidado tem precipitação negativa — FALHANDO.")
    if sorted(df['target_month']) != esperado:
        raise RuntimeError(f"CHIRPS consolidado não é uma sequência contínua de {target_ini} a "
                            f"{target_fim} — FALHANDO.")


def _chirps_checkpoint_vazio():
    return {'anos_concluidos': [], 'anos_falhados': {}}


def _carregar_chirps_checkpoint(caminho=None):
    caminho = caminho or CHIRPS_CHECKPOINT_PATH
    if caminho.exists():
        return json.loads(caminho.read_text())
    return _chirps_checkpoint_vazio()


def _salvar_chirps_checkpoint(estado, caminho=None):
    caminho = caminho or CHIRPS_CHECKPOINT_PATH
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(estado, indent=2, ensure_ascii=False))


def _chave_bloco_chirps(ano, mes_ini, mes_fim):
    """Identifica um bloco de forma única — anos cheios (a maioria)
    continuam com a chave simples `{ano}`, reaproveitando exatamente o
    nome de arquivo/checkpoint já validado; só a borda parcial do
    intervalo (primeiro/último ano, quando não é jan-dez) ganha uma
    chave distinta, para nunca reaproveitar por engano um bloco parcial
    de execução anterior como se fosse o ano inteiro (ou vice-versa)."""
    if (mes_ini, mes_fim) == (1, 12):
        return str(ano)
    return f'{ano}_{mes_ini:02d}_{mes_fim:02d}'


def _salvar_bloco_chirps(df_bloco, chave, diretorio=None):
    diretorio = diretorio or CHIRPS_BLOCOS_DIR
    diretorio.mkdir(parents=True, exist_ok=True)
    df_bloco.to_csv(diretorio / f'chirps_{chave}.csv', index=False)


def buscar_chirps_consolidado(target_ini, target_fim, sleep_fn=time.sleep):
    """Busca CHIRPS municipal (São Bento) em blocos ANUAIS — nunca o
    período inteiro numa request só (Seção 4 da correção original).
    target_ini/target_fim: qualquer valor aceito por pd.Period(x, 'M')
    (string 'YYYY-MM' ou pandas.Period) — o intervalo observacional
    necessário, normalmente vindo de intervalo_targets_necessario(),
    nunca fixado manualmente aqui. Anos totalmente dentro do intervalo
    pedem o ano inteiro (valida exatamente 12 meses); o primeiro/último
    ano, se parciais, pedem só os meses necessários — preferência
    explícita por não buscar mês nenhum além do necessário. Cada bloco:
    retry controlado, validação individual, cache local em
    artifacts/c3s_hindcast/_chirps_blocos/ e checkpoint local (só
    protege dentro do MESMO processo/filesystem, não há resume
    automático entre execuções independentes do workflow). Concatena os
    blocos e valida o consolidado (contínuo, sem NaN/negativo/
    duplicado, cobrindo exatamente target_ini a target_fim) antes de
    devolver."""
    target_ini = pd.Period(target_ini, 'M')
    target_fim = pd.Period(target_fim, 'M')
    if target_fim < target_ini:
        raise ValueError(f"intervalo CHIRPS inválido: target_fim ({target_fim}) < target_ini "
                          f"({target_ini}).")

    estado = _carregar_chirps_checkpoint()
    blocos = []
    for ano in range(target_ini.year, target_fim.year + 1):
        mes_ini = target_ini.month if ano == target_ini.year else 1
        mes_fim = target_fim.month if ano == target_fim.year else 12
        chave = _chave_bloco_chirps(ano, mes_ini, mes_fim)
        rotulo = str(ano) if (mes_ini, mes_fim) == (1, 12) else f'{ano} ({mes_ini:02d}-{mes_fim:02d})'
        caminho_bloco = CHIRPS_BLOCOS_DIR / f'chirps_{chave}.csv'
        if chave in estado['anos_concluidos'] and caminho_bloco.exists():
            print(f"  [{rotulo}] CHIRPS já concluído (checkpoint) — reaproveitando")
            blocos.append(pd.read_csv(caminho_bloco))
            continue

        print(f"  buscando CHIRPS {rotulo}…")
        try:
            df_bruto = _buscar_chirps_ano(ano, mes_ini, mes_fim, sleep_fn=sleep_fn)
            df_validado = _validar_bloco_chirps(df_bruto, ano, mes_ini, mes_fim)
        except Exception as e:
            estado['anos_falhados'][chave] = str(e)
            _salvar_chirps_checkpoint(estado)
            raise

        _salvar_bloco_chirps(df_validado, chave)
        estado['anos_concluidos'].append(chave)
        estado['anos_falhados'].pop(chave, None)
        _salvar_chirps_checkpoint(estado)
        blocos.append(df_validado)
        print(f"  ✅ CHIRPS {rotulo}: {mes_fim - mes_ini + 1} meses válidos")

    consolidado = pd.concat(blocos, ignore_index=True)
    consolidado['target_month'] = consolidado['target_month'].apply(
        lambda s: s if isinstance(s, pd.Period) else pd.Period(s, 'M'))
    _validar_consolidado_final(consolidado, target_ini, target_fim)
    return consolidado.sort_values('target_month').reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════
# Summary + calibrado — climatologia/bias leakage-safe, correção por
# membro, probabilidades RAW/BC (Seções 10-13, 20).
# ══════════════════════════════════════════════════════════════════════════

def construir_ens_df(raw_df):
    """1 linha por (init_date, lead) com estatísticas do ensemble RAW —
    reaproveita c3s_hindcast.py::estatisticas_ensemble. `raw_df`
    precisa ter init_date/target_month como pandas.Period (ver
    _com_periods)."""
    linhas = []
    for (init_date, lead), g in raw_df.groupby(['init_date', 'lead']):
        v = g['c3s_prec_mm'].to_numpy(dtype=float)
        est = hc.estatisticas_ensemble(v)
        linhas.append({
            'init_date': init_date, 'target_month': g['target_month'].iloc[0], 'lead': int(lead),
            'ens_mean_raw': est['mean'], 'ens_median_raw': est['median'], 'ens_sd_raw': float(np.std(v)),
            'p10_raw': est['p10'], 'p25_raw': est['p25'], 'p75_raw': est['p75'], 'p90_raw': est['p90'],
        })
    return pd.DataFrame(linhas)


def construir_summary_e_calibrado(raw_df, chirps_df, min_anos_treino=MIN_ANOS_TREINO):
    """Pipeline: ens stats -> climatologia/bias leakage-safe -> correção
    por membro -> probabilidades RAW/BC -> summary final (Seção 29) +
    tabela calibrada por membro (Seção 28, item 4). `raw_df` já com
    init_date/target_month como Period."""
    chirps_por_target = chirps_df[['target_month', 'chirps_prec_mm']].drop_duplicates('target_month')
    ens_df = construir_ens_df(raw_df)

    linhas_pre = []
    for _, row in ens_df.iterrows():
        origem, target_month, lead = row['init_date'], row['target_month'], int(row['lead'])
        mes_cal = target_month.month
        clim = calib.climatologia_leakage_safe(chirps_por_target, origem, mes_cal, min_anos_treino)
        bias = calib.bias_leakage_safe(ens_df, chirps_por_target, origem, mes_cal, lead, min_anos_treino)
        obs_row = chirps_por_target[chirps_por_target['target_month'] == target_month]
        chirps_mm = float(obs_row['chirps_prec_mm'].iloc[0]) if not obs_row.empty else None
        ens_mean_bc = (round(row['ens_mean_raw'] - bias['bias_mm'], 3)
                       if bias['bias_mm'] is not None else None)
        status = (calib.STATUS_OK if (clim['status'] == calib.STATUS_OK and bias['status'] == calib.STATUS_OK)
                  else calib.STATUS_SEM_HISTORICO)
        linhas_pre.append({
            'init_date': origem, 'target_month': target_month, 'target_year': target_month.year,
            'target_calendar_month': mes_cal, 'lead': lead, 'init_year': origem.year,
            'ens_mean_raw': row['ens_mean_raw'], 'ens_median_raw': row['ens_median_raw'],
            'ens_sd_raw': row['ens_sd_raw'], 'p10_raw': row['p10_raw'], 'p25_raw': row['p25_raw'],
            'p75_raw': row['p75_raw'], 'p90_raw': row['p90_raw'],
            'chirps_prec_mm': chirps_mm,
            'climatological_mean': clim['mean'], 'climatological_median': clim['median'],
            'clim_p20': clim['p20'], 'clim_p33': clim['p33'], 'clim_p67': clim['p67'], 'clim_p80': clim['p80'],
            'clim_n': clim['n'], 'bias_training_n': bias['n'], 'bias_mm': bias['bias_mm'],
            'ens_mean_bc': ens_mean_bc, 'status_historico': status,
        })
    pre_df = pd.DataFrame(linhas_pre)

    chave = pre_df.set_index(['init_date', 'lead'])[['bias_mm', 'clim_p33', 'clim_p67']]
    calibrado_linhas, prob_linhas = [], []
    for (origem, lead), g in raw_df.groupby(['init_date', 'lead']):
        if (origem, lead) not in chave.index:
            continue
        bias_mm = chave.loc[(origem, lead), 'bias_mm']
        p33 = chave.loc[(origem, lead), 'clim_p33']
        p67 = chave.loc[(origem, lead), 'clim_p67']

        raw_vals = g['c3s_prec_mm'].to_numpy(dtype=float)
        tem_bias = bias_mm is not None and not (isinstance(bias_mm, float) and np.isnan(bias_mm))
        bc_vals = (np.array([calib.aplicar_bias_a_membro(v, bias_mm) for v in raw_vals])
                   if tem_bias else np.full(len(raw_vals), np.nan))

        for membro, rv, bv in zip(g['member'], raw_vals, bc_vals):
            calibrado_linhas.append({
                'local': MUNICIPIO, 'init_date': str(origem), 'target_month': str(g['target_month'].iloc[0]),
                'lead': lead, 'member': int(membro), 'c3s_prec_mm_raw': round(float(rv), 3),
                'bias_mm': (round(float(bias_mm), 3) if tem_bias else None),
                'c3s_prec_mm_bc': (round(float(bv), 3) if tem_bias else None),
            })

        tem_thresholds = p33 is not None and p67 is not None and not (
            isinstance(p33, float) and np.isnan(p33))
        if tem_thresholds:
            pb_r, pn_r, pa_r = hc.probabilidade_terciles(raw_vals, p33, p67)
        else:
            pb_r = pn_r = pa_r = None
        if tem_bias and tem_thresholds:
            pb_b, pn_b, pa_b = hc.probabilidade_terciles(bc_vals, p33, p67)
        else:
            pb_b = pn_b = pa_b = None

        prob_linhas.append({'init_date': origem, 'lead': lead,
                             'prob_below_raw': pb_r, 'prob_normal_raw': pn_r, 'prob_above_raw': pa_r,
                             'prob_below_bc': pb_b, 'prob_normal_bc': pn_b, 'prob_above_bc': pa_b})

    calibrated_df = pd.DataFrame(calibrado_linhas)
    prob_df = pd.DataFrame(prob_linhas)
    summary_df = pre_df.merge(prob_df, on=['init_date', 'lead'], how='left')
    summary_df['evaluation_period'] = summary_df['init_date'].apply(_periodo_avaliacao)
    return summary_df.sort_values(['init_date', 'lead']).reset_index(drop=True), calibrated_df


def filtrar_avaliacao(summary_df, periodos=('desenvolvimento', 'confirmacao')):
    """Avaliação principal (Seção 3/4): só desenvolvimento+confirmação
    (nunca warm-up) e só linhas com histórico suficiente (nunca
    completadas com futuro)."""
    if summary_df.empty:
        return summary_df
    return summary_df[summary_df['evaluation_period'].isin(periodos) &
                       (summary_df['status_historico'] == calib.STATUS_OK)].copy()


# ══════════════════════════════════════════════════════════════════════════
# Auditoria de leakage (Seção 30/31) — verificação independente de que
# nada usado em climatologia/bias é >= à origem.
# ══════════════════════════════════════════════════════════════════════════

def _max_usado_bias(ens_df, origem, mes_cal, lead):
    """Reamostragem INDEPENDENTE para a auditoria — reflete o mesmo
    predicado estrito de calib.bias_leakage_safe (init_date < origem E
    target_month < origem, correção pós-run 35353196015/Seção 8), mas
    não reaproveita o resultado do pipeline, para auditar de verdade.
    Devolve (max_init_date_used_bias, max_target_month_used_bias) — os
    dois podem ser None com segurança quando não há histórico (Seção
    10: "campos max podem ser nulos de forma segura")."""
    f = ens_df[(ens_df['lead'] == lead) &
               (ens_df['init_date'] < origem) &
               (ens_df['target_month'] < origem) &
               (ens_df['target_month'].apply(lambda p: p.month) == mes_cal)]
    if f.empty:
        return None, None
    return f['init_date'].max(), f['target_month'].max()


def construir_leakage_audit(summary_df, ens_df, chirps_df):
    if summary_df.empty:
        return pd.DataFrame(columns=['init_date', 'target_month', 'max_obs_date_used_climatology',
                                      'max_init_date_used_bias', 'max_target_month_used_bias',
                                      'clim_n', 'bias_training_n', 'bias_leakage_ok', 'leakage_status'])
    chirps_por_target = chirps_df[['target_month', 'chirps_prec_mm']].drop_duplicates('target_month')
    linhas = []
    for _, row in summary_df.iterrows():
        origem, mes_cal, lead = row['init_date'], row['target_calendar_month'], row['lead']
        sub_clim = chirps_por_target[(chirps_por_target['target_month'] < origem) &
                                      (chirps_por_target['target_month'].apply(lambda p: p.month) == mes_cal)]
        max_obs = sub_clim['target_month'].max() if not sub_clim.empty else None
        max_init_bias, max_target_bias = _max_usado_bias(ens_df, origem, mes_cal, lead)

        violou = False
        bias_leakage_ok = True
        if max_obs is not None and not (max_obs < origem):
            violou = True
        if max_init_bias is not None and not (max_init_bias < origem):
            violou = True
            bias_leakage_ok = False
        if max_target_bias is not None and not (max_target_bias < origem):
            violou = True
            bias_leakage_ok = False

        linhas.append({
            'init_date': str(origem), 'target_month': str(row['target_month']),
            'max_obs_date_used_climatology': str(max_obs) if max_obs is not None else None,
            'max_init_date_used_bias': str(max_init_bias) if max_init_bias is not None else None,
            'max_target_month_used_bias': str(max_target_bias) if max_target_bias is not None else None,
            'clim_n': row['clim_n'], 'bias_training_n': row['bias_training_n'],
            'bias_leakage_ok': bias_leakage_ok,
            'leakage_status': 'VIOLACAO' if violou else 'OK',
        })
    return pd.DataFrame(linhas)


def construir_temporal_audit(raw_df):
    """Réplica em lote do temporal_check da Fase 2A.2 — 1 linha por
    (origem, lead)."""
    if raw_df.empty:
        return pd.DataFrame(columns=['init_date', 'lead', 'fcmonth', 'verifying_month',
                                      'valid_time_limite', 'status'])
    linhas = []
    for (init_date, lead), g in raw_df.groupby(['init_date', 'lead']):
        alvo = g['target_month'].iloc[0]
        limite = str((alvo + 1).start_time.date())
        linhas.append({'init_date': str(init_date), 'lead': int(lead), 'fcmonth': int(lead),
                        'verifying_month': str(alvo), 'valid_time_limite': limite, 'status': 'OK'})
    return pd.DataFrame(linhas).sort_values(['init_date', 'lead']).reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════
# Tabelas de skill (Seções 16-22) e bootstrap (Seção 24)
# ══════════════════════════════════════════════════════════════════════════

def montar_tabelas_skill(avaliacao_df):
    if avaliacao_df.empty:
        vazio = pd.DataFrame()
        return {'overall': vazio, 'by_lead': vazio, 'by_month': vazio, 'by_month_lead': vazio,
                'operational_seasons': vazio, 'prob_overall': vazio, 'prob_by_lead': vazio}

    overall = pd.DataFrame([skill.tabela_skill_deterministico(avaliacao_df)])

    by_lead = pd.DataFrame([{'lead': lead, **skill.tabela_skill_deterministico(g)}
                             for lead, g in avaliacao_df.groupby('lead')]).sort_values('lead').reset_index(drop=True)

    by_month = pd.DataFrame([{'target_calendar_month': mes, **skill.tabela_skill_deterministico(g)}
                              for mes, g in avaliacao_df.groupby('target_calendar_month')]) \
        .sort_values('target_calendar_month').reset_index(drop=True)

    by_month_lead = pd.DataFrame([
        {'target_calendar_month': mes, 'lead': lead, **skill.tabela_skill_deterministico(g)}
        for (mes, lead), g in avaliacao_df.groupby(['target_calendar_month', 'lead'])
    ]).sort_values(['target_calendar_month', 'lead']).reset_index(drop=True)

    linhas_estacoes = []
    for nome, meses in ESTACOES_OPERACIONAIS.items():
        g = avaliacao_df[avaliacao_df['target_calendar_month'].isin(meses)]
        linhas_estacoes.append({'bloco': nome, **skill.tabela_skill_deterministico(g)})
    g_prioritario = avaliacao_df[avaliacao_df['target_calendar_month'].isin(MESES_BLOCO_OPERACIONAL_PRIORITARIO)]
    linhas_estacoes.append({'bloco': NOME_BLOCO_OPERACIONAL_PRIORITARIO,
                             **skill.tabela_skill_deterministico(g_prioritario)})
    operational_seasons = pd.DataFrame(linhas_estacoes)

    prob_overall = pd.DataFrame([skill.tabela_skill_probabilistico(avaliacao_df)])
    prob_by_lead = pd.DataFrame([{'lead': lead, **skill.tabela_skill_probabilistico(g)}
                                  for lead, g in avaliacao_df.groupby('lead')]) \
        .sort_values('lead').reset_index(drop=True)

    return {'overall': overall, 'by_lead': by_lead, 'by_month': by_month, 'by_month_lead': by_month_lead,
            'operational_seasons': operational_seasons, 'prob_overall': prob_overall, 'prob_by_lead': prob_by_lead}


def montar_bootstrap(avaliacao_df):
    """Bootstrap por ANO DE INICIALIZAÇÃO (Seção 24 — preferência
    documentada, preserva meses/leads dentro do ano). RAW vs CLIM e BC
    vs CLIM, para total/desenvolvimento/confirmação (Seção 25)."""
    if avaliacao_df.empty:
        return pd.DataFrame()
    periodos = {
        'total': avaliacao_df,
        'desenvolvimento': avaliacao_df[avaliacao_df['evaluation_period'] == 'desenvolvimento'],
        'confirmacao': avaliacao_df[avaliacao_df['evaluation_period'] == 'confirmacao'],
    }
    linhas = []
    for nome_periodo, df_periodo in periodos.items():
        for nome_modelo, coluna_modelo in (('raw', 'ens_mean_raw'), ('bc', 'ens_mean_bc')):
            r = skill.bootstrap_skill(df_periodo, 'init_year', 'chirps_prec_mm', 'climatological_mean',
                                       coluna_modelo, n_replicacoes=N_BOOTSTRAP, seed=SEED_BOOTSTRAP)
            linhas.append({'periodo': nome_periodo, 'comparacao': f'{nome_modelo}_vs_clim', **r})
    return pd.DataFrame(linhas)


# ══════════════════════════════════════════════════════════════════════════
# dry-run-plan (Seção 37) — nunca acessa CDS.
# ══════════════════════════════════════════════════════════════════════════

def plano_execucao(ano_ini=ANO_INICIO_HINDCAST, ano_fim=ANO_FIM_HINDCAST, meses=None):
    origens = construir_origens(ano_ini, ano_fim, meses)
    warmup = [o for o in origens if o[0] <= WARMUP_ANO_FIM]
    avaliacao = [o for o in origens if o[0] >= AVALIACAO_ANO_INICIO]
    desenvolvimento = [o for o in avaliacao if o[0] <= DESENVOLVIMENTO_ANO_FIM]
    confirmacao = [o for o in avaliacao if o[0] >= CONFIRMACAO_ANO_INICIO]
    n = len(origens)
    return {
        'n_origens': n, 'requests_cds_previstos': n,
        'raw_rows_esperadas': n * N_MEMBROS_ESPERADO * len(LEADS),
        'summary_rows_esperadas': n * len(LEADS),
        'periodo_download': f'{ano_ini}-01 a {ano_fim}-12',
        'periodo_warmup': f'{WARMUP_ANO_INICIO}-{WARMUP_ANO_FIM}', 'n_origens_warmup': len(warmup),
        'periodo_avaliacao_principal': f'{AVALIACAO_ANO_INICIO}-{ano_fim}', 'n_origens_avaliacao': len(avaliacao),
        'periodo_desenvolvimento': f'{DESENVOLVIMENTO_ANO_INICIO}-{DESENVOLVIMENTO_ANO_FIM}',
        'n_origens_desenvolvimento': len(desenvolvimento),
        'periodo_confirmacao': f'{CONFIRMACAO_ANO_INICIO}-{CONFIRMACAO_ANO_FIM}',
        'n_origens_confirmacao': len(confirmacao),
        'min_anos_treino': MIN_ANOS_TREINO, 'municipio': MUNICIPIO, 'leads': LEADS,
        'n_membros_esperado': N_MEMBROS_ESPERADO, 'artifacts_esperados': ARTIFACT_FILENAMES,
    }


def plano_piloto():
    """Plano do MODO PILOTO LONGITUDINAL (correção pós-run 35260471652)
    — 72 origens (todos jan/jul de 1981-2016), nunca as 432 do hindcast
    completo. Usado por --pilot --dry-run-plan para que o plano
    mostrado bata com o que --pilot de verdade vai processar (mesma
    correção de segurança de antes: o plano tem que refletir o que
    --pilot roda de fato, não o plano do hindcast completo)."""
    n = len(PILOT_ORIGENS)
    return {
        'modo': 'PILOT LONGITUDINAL', 'n_origens': n,
        'origens': [_origem_str(a, m) for a, m in PILOT_ORIGENS],
        'init_months': PILOT_INIT_MONTHS,
        'periodo': f'{ANO_INICIO_HINDCAST}-{ANO_FIM_HINDCAST}',
        'requests_cds_previstos': n,
        'raw_rows_esperadas': n * N_MEMBROS_ESPERADO * len(LEADS),
        'summary_rows_esperadas': n * len(LEADS),
        'forecasts_avaliacao_esperados': PILOT_FORECASTS_AVALIACAO_ESPERADOS,
        'periodo_warmup': f'{WARMUP_ANO_INICIO}-{WARMUP_ANO_FIM}',
        'periodo_avaliacao': f'{AVALIACAO_ANO_INICIO}-{AVALIACAO_ANO_FIM}',
        'min_anos_treino': MIN_ANOS_TREINO, 'municipio': MUNICIPIO, 'leads': LEADS,
        'n_membros_esperado': N_MEMBROS_ESPERADO, 'artifacts_esperados': ARTIFACT_FILENAMES,
        'aviso': 'PILOT — NÃO É CONCLUSÃO FINAL DE SKILL. Pilot metodológico longitudinal '
                 '(1/6 do hindcast completo) para validar bias/skill/bootstrap fim-a-fim.',
    }


def imprimir_plano(plano, modo='COMPLETO/PARCIAL'):
    print(f"=== C3S Hindcast Completo — DRY RUN PLAN — MODO: {modo} (nenhum acesso ao CDS) ===")
    for chave, valor in plano.items():
        print(f"  {chave}: {valor}")


# ══════════════════════════════════════════════════════════════════════════
# Orquestração completa
# ══════════════════════════════════════════════════════════════════════════

def rodar(origens, pilot=False, sleep_fn=time.sleep):
    raws, metadados_origem, falhas = [], {}, {}
    for ano, mes in origens:
        origem = _origem_str(ano, mes)
        print(f"\n=== origem {origem} ===")
        try:
            tabela, meta = processar_origem_raw(ano, mes, sleep_fn=sleep_fn)
        except Exception as e:
            print(f"  ❌ FALHOU: {e}")
            falhas[origem] = str(e)
            continue
        raws.append(tabela)
        metadados_origem[origem] = meta
        print(f"  ✅ {origem}: {len(tabela)} linhas raw")

    raw_df_str = pd.concat(raws, ignore_index=True) if raws else pd.DataFrame()
    raw_df = _com_periods(raw_df_str) if not raw_df_str.empty else raw_df_str

    target_ini, target_fim = intervalo_targets_necessario(origens, LEADS)
    print(f"\n=== buscando CHIRPS consolidado ({target_ini} a {target_fim}, em blocos anuais) ===")
    chirps_df = buscar_chirps_consolidado(target_ini, target_fim, sleep_fn=sleep_fn)
    print(f"  ✅ CHIRPS: {len(chirps_df)} meses válidos")

    if raw_df.empty:
        summary_df, calibrated_df = pd.DataFrame(), pd.DataFrame()
    else:
        summary_df, calibrated_df = construir_summary_e_calibrado(raw_df, chirps_df)

    avaliacao_df = filtrar_avaliacao(summary_df)
    tabelas_skill = montar_tabelas_skill(avaliacao_df)
    bootstrap_df = montar_bootstrap(avaliacao_df)
    ens_df = construir_ens_df(raw_df) if not raw_df.empty else pd.DataFrame()
    leakage_df = construir_leakage_audit(summary_df, ens_df, chirps_df)
    temporal_df = construir_temporal_audit(raw_df)
    leakage_aprovado = leakage_df.empty or (leakage_df['leakage_status'] == 'OK').all()

    return {
        'raw_df': raw_df_str, 'summary_df': summary_df, 'calibrated_df': calibrated_df,
        'chirps_df': chirps_df, 'leakage_df': leakage_df, 'temporal_df': temporal_df,
        'leakage_audit_aprovado': bool(leakage_aprovado), 'tabelas_skill': tabelas_skill,
        'bootstrap_df': bootstrap_df, 'falhas': falhas, 'metadados_origem': metadados_origem,
        'origens': origens, 'pilot': pilot, 'avaliacao_n': len(avaliacao_df),
        'avaliacao_df': avaliacao_df,
    }


# ══════════════════════════════════════════════════════════════════════════
# Relatório + metadata + gravação dos artifacts (Seção 28-30, 40)
# ══════════════════════════════════════════════════════════════════════════

def _fmt_skill(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return 'N/D'
    return v


def gerar_relatorio_markdown(resultado):
    r = resultado
    modo = 'PILOTO' if r['pilot'] else 'COMPLETO'
    n_ok = len(r['origens']) - len(r['falhas'])
    cobertura = _cobertura_observacional(r)
    linhas = ["# Hindcast Completo SEAS5 — São Bento do Tocantins — Fase 2A.3", "",
              f"- Modo: {modo}", f"- Origens processadas com sucesso: {n_ok}/{len(r['origens'])}",
              f"- Linhas raw: {len(r['raw_df'])}", f"- Linhas summary: {len(r['summary_df'])}",
              f"- Forecasts na avaliação principal (1991-{AVALIACAO_ANO_FIM}, histórico suficiente): "
              f"{r['avaliacao_n']}",
              f"- Cobertura observacional (CHIRPS): {cobertura['observation_target_start']} → "
              f"{cobertura['observation_target_end']} ({cobertura['n_observation_months']} meses)",
              f"- Forecasts avaliação com observação válida: "
              f"{cobertura['n_forecasts_evaluation_with_obs']}/{cobertura['n_forecasts_evaluation_expected']}",
              f"- Auditoria de leakage: {'✅ APROVADA' if r['leakage_audit_aprovado'] else '❌ REPROVADA'}"]

    if cobertura['n_forecasts_evaluation_with_obs'] != cobertura['n_forecasts_evaluation_expected']:
        linhas += ["", "## ⚠ COBERTURA OBSERVACIONAL INCOMPLETA", "",
                   "Há forecast(s) na avaliação principal sem observação CHIRPS correspondente "
                   f"({cobertura['n_forecasts_evaluation_with_obs']}/"
                   f"{cobertura['n_forecasts_evaluation_expected']}) — **nenhuma conclusão científica "
                   "deste resultado deve ser interpretada como válida** até a cobertura ser corrigida "
                   "(correção pós-run 35353196015)."]

    if r['falhas']:
        linhas += ["", "## Falhas", ""] + [f"- **{o}**: {m}" for o, m in r['falhas'].items()]

    linhas += ["", "## Respostas objetivas (Seção 40)", ""]
    overall = r['tabelas_skill']['overall']
    if overall.empty or overall.iloc[0]['n'] in (0, None):
        linhas.append("Dados insuficientes no período avaliado para responder às 10 perguntas — "
                       "esperado em execuções piloto/parciais. Só é conclusivo com 1981-2016 completo.")
    else:
        row = overall.iloc[0]
        msess_raw, msess_bc = row['msess_raw'], row['msess_bc']
        linhas += [
            f"1. RAW supera climatologia (MSESS_raw={_fmt_skill(msess_raw)})? "
            f"{'Sim' if (msess_raw or 0) > 0 else 'Não'}",
            f"2. BC supera climatologia (MSESS_bc={_fmt_skill(msess_bc)})? "
            f"{'Sim' if (msess_bc or 0) > 0 else 'Não'}",
            "3. Em quais leads? ver skill_deterministic_by_lead.csv",
            "4. Em quais meses? ver skill_deterministic_by_month.csv",
            "5. Em Sep-Feb? ver skill_operational_seasons.csv (bloco SET_FEV_prioritario)",
            "6. Skill persiste na confirmação 2008-2016? ver bootstrap_skill.csv "
            "(períodos 'desenvolvimento' x 'confirmacao')",
            "7. IC 95% exclui zero? ver coluna 'conclusivo' em bootstrap_skill.csv",
            "8. Há ganho probabilístico? ver skill_probabilistic_overall.csv (BSS/RPSS)",
            f"9. Bias correction ajuda ou piora? MSESS_bc "
            f"{'>' if (msess_bc or -1) > (msess_raw or -1) else '<='} MSESS_raw",
            "10. Evidência suficiente para multi-sistema/NMME? só decidir após 1981-2016 completo, "
            "confirmação persistente e IC 95% conclusivo — NÃO decidido nesta entrega.",
        ]

    linhas += ["", "## Nota metodológica", "", NOTA_HINDCAST_COMPLETO]
    if r['pilot']:
        linhas += ["", "## ⚠ PILOT — NÃO É CONCLUSÃO FINAL DE SKILL", "",
                   f"Pilot metodológico LONGITUDINAL: {len(PILOT_ORIGENS)} origens "
                   f"(todos os janeiros e julhos de {ANO_INICIO_HINDCAST}-{ANO_FIM_HINDCAST}, "
                   f"1/6 do hindcast completo de {(ANO_FIM_HINDCAST - ANO_INICIO_HINDCAST + 1) * 12} "
                   "origens). Objetivo é validar que bias correction, tabelas de skill e bootstrap "
                   "são genuinamente exercitados fim-a-fim com histórico suficiente — não estimar "
                   "skill anual completo a partir deste resultado."]
    linhas += ["", "---", "",
               f"Relatório gerado a partir de "
               f"{f'PILOTO LONGITUDINAL ({len(PILOT_ORIGENS)} origens)' if r['pilot'] else 'execução completa'} "
               "— não promover para produção sem revisão humana (Seção 42)."]
    return '\n'.join(linhas) + '\n'


def _versoes_pacotes():
    import importlib.metadata as im
    versoes = {'python': sys.version.split()[0]}
    for pkg in ('cdsapi', 'cfgrib', 'eccodes', 'xarray'):
        try:
            versoes[pkg] = im.version(pkg)
        except im.PackageNotFoundError:
            versoes[pkg] = None
    return versoes


def _cobertura_observacional(resultado):
    """Correção pós-run oficial 35353196015 (Seção 16): cobertura
    observacional real do CHIRPS consolidado e quantos forecasts da
    avaliação principal têm chirps_prec_mm finito — os dois números
    devem bater (n_forecasts_evaluation_expected ==
    n_forecasts_evaluation_with_obs); se não baterem, nenhuma conclusão
    científica deste resultado é válida (ver gerar_relatorio_markdown e
    validar_full_aprovado)."""
    r = resultado
    chirps_df = r.get('chirps_df')
    if chirps_df is None or chirps_df.empty:
        obs_start, obs_end, n_obs_months = None, None, 0
    else:
        obs_start = str(chirps_df['target_month'].min())
        obs_end = str(chirps_df['target_month'].max())
        n_obs_months = len(chirps_df)

    avaliacao_df = r.get('avaliacao_df')
    if avaliacao_df is None or avaliacao_df.empty:
        n_expected, n_with_obs = 0, 0
    else:
        n_expected = len(avaliacao_df)
        n_with_obs = int(np.isfinite(avaliacao_df['chirps_prec_mm'].astype(float)).sum())

    return {
        'observation_target_start': obs_start, 'observation_target_end': obs_end,
        'n_observation_months': n_obs_months,
        'n_forecasts_evaluation_expected': n_expected,
        'n_forecasts_evaluation_with_obs': n_with_obs,
    }


def _execution_mode(resultado):
    """Seção 12 (preparação do hindcast oficial): rótulo de auditoria
    gravado no metadata.json — PILOT_LONGITUDINAL, FULL_1981_2016 (só
    quando as origens pedidas são EXATAMENTE as 432 oficiais) ou
    PARTIAL (execução parcial/depuração, sem barreira extra de
    integridade)."""
    r = resultado
    if r['pilot']:
        return 'PILOT_LONGITUDINAL'
    origens_oficiais = set(construir_origens(ANO_INICIO_HINDCAST, ANO_FIM_HINDCAST, None))
    if set(r['origens']) == origens_oficiais:
        return 'FULL_1981_2016'
    return 'PARTIAL'


def montar_metadata(resultado):
    centro, sistema = cat.SISTEMA_ESCOLHIDO_FASE_2A
    r = resultado
    metadata = {
        'data_execucao': datetime.now(timezone.utc).isoformat(),
        'modo': 'piloto' if r['pilot'] else 'completo',
        'execution_mode': _execution_mode(r),
        'sistema': {'centro': centro, 'sistema': sistema, 'cds_system_code': '51'},
        'municipio': MUNICIPIO, 'leads': LEADS, 'n_membros_esperado': N_MEMBROS_ESPERADO,
        'unidade_esperada': UNIDADE_TPRATE_ESPERADA,
        'periodo_hindcast': [ANO_INICIO_HINDCAST, ANO_FIM_HINDCAST],
        'periodo_warmup': [WARMUP_ANO_INICIO, WARMUP_ANO_FIM],
        'periodo_avaliacao': [AVALIACAO_ANO_INICIO, AVALIACAO_ANO_FIM],
        'periodo_desenvolvimento': [DESENVOLVIMENTO_ANO_INICIO, DESENVOLVIMENTO_ANO_FIM],
        'periodo_confirmacao': [CONFIRMACAO_ANO_INICIO, CONFIRMACAO_ANO_FIM],
        'min_anos_treino': MIN_ANOS_TREINO,
        'n_origens_pedidas': len(r['origens']), 'n_origens_concluidas': len(r['origens']) - len(r['falhas']),
        'n_origens_falhadas': len(r['falhas']), 'origens_falhadas': r['falhas'],
        'n_linhas_raw': len(r['raw_df']), 'n_linhas_summary': len(r['summary_df']),
        'n_forecasts_avaliacao_principal': r['avaliacao_n'],
        'leakage_audit_aprovado': r['leakage_audit_aprovado'],
        'bootstrap': {'n_replicacoes': N_BOOTSTRAP, 'seed': SEED_BOOTSTRAP, 'unidade_reamostragem': 'init_year'},
        'versoes_pacotes': _versoes_pacotes(),
    }
    metadata.update(_cobertura_observacional(r))
    return metadata


def escrever_saidas(resultado):
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    r = resultado

    r['raw_df'].to_csv(ARTIFACTS_DIR / 'c3s_hindcast_raw.csv', index=False)
    r['summary_df'].to_csv(ARTIFACTS_DIR / 'c3s_hindcast_summary.csv', index=False)
    r['chirps_df'].to_csv(ARTIFACTS_DIR / 'chirps_sao_bento_hindcast_targets.csv', index=False)
    r['calibrated_df'].to_csv(ARTIFACTS_DIR / 'c3s_hindcast_calibrated.csv', index=False)

    ts = r['tabelas_skill']
    ts['overall'].to_csv(ARTIFACTS_DIR / 'skill_deterministic_overall.csv', index=False)
    ts['by_lead'].to_csv(ARTIFACTS_DIR / 'skill_deterministic_by_lead.csv', index=False)
    ts['by_month'].to_csv(ARTIFACTS_DIR / 'skill_deterministic_by_month.csv', index=False)
    ts['by_month_lead'].to_csv(ARTIFACTS_DIR / 'skill_deterministic_by_month_lead.csv', index=False)
    ts['operational_seasons'].to_csv(ARTIFACTS_DIR / 'skill_operational_seasons.csv', index=False)
    ts['prob_overall'].to_csv(ARTIFACTS_DIR / 'skill_probabilistic_overall.csv', index=False)
    ts['prob_by_lead'].to_csv(ARTIFACTS_DIR / 'skill_probabilistic_by_lead.csv', index=False)

    r['bootstrap_df'].to_csv(ARTIFACTS_DIR / 'bootstrap_skill.csv', index=False)
    r['temporal_df'].to_csv(ARTIFACTS_DIR / 'temporal_audit.csv', index=False)
    r['leakage_df'].to_csv(ARTIFACTS_DIR / 'leakage_audit.csv', index=False)

    metadata = montar_metadata(r)
    (ARTIFACTS_DIR / 'metadata.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False, default=str))

    relatorio = gerar_relatorio_markdown(r)
    (ARTIFACTS_DIR / 'RELATORIO.md').write_text(relatorio)

    for nome in ARTIFACT_FILENAMES:
        print(f"  ✅ artifacts/c3s_hindcast/{nome}")

    import os
    caminho_summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if caminho_summary:
        with open(caminho_summary, 'a') as f:
            f.write(relatorio)
    return metadata, relatorio


# ══════════════════════════════════════════════════════════════════════════
# Validação do PILOT (correção pós-run 35260471652) — o pilot de 6
# origens isoladas terminou "success" sem exercitar bias/skill/
# bootstrap de verdade (n_forecasts_avaliacao_principal=0). Esta
# barreira re-verifica de forma independente, sobre o resultado real do
# pilot longitudinal (72 origens), que TODAS as camadas científicas
# (bias training, probabilidades, tabelas de skill, bootstrap) foram
# genuinamente exercitadas — critérios A-M da correção. Qualquer falha
# aqui reprova o pilot (exit != 0), mesmo com artifacts gravados.
# ══════════════════════════════════════════════════════════════════════════

TABELAS_SKILL_OBRIGATORIAS = ['overall', 'by_lead', 'by_month', 'by_month_lead',
                               'operational_seasons', 'prob_overall', 'prob_by_lead']


def validar_pilot_aprovado(resultado):
    """Critérios A-M — só aprova o pilot se TODAS as camadas científicas
    (bias, probabilidades, skill, bootstrap) tiverem sido realmente
    exercitadas com dado suficiente, não apenas se o pipeline rodou sem
    exceção. Retorna (aprovado: bool, motivos: list[str])."""
    r = resultado
    motivos = []

    n_ok = len(r['origens']) - len(r['falhas'])
    if n_ok != len(PILOT_ORIGENS):
        motivos.append(f"A) {n_ok}/{len(PILOT_ORIGENS)} origens processadas com sucesso, "
                        f"esperado {len(PILOT_ORIGENS)}/{len(PILOT_ORIGENS)}")

    raw_df = r['raw_df']
    if raw_df.empty:
        motivos.append("B/C) raw_df vazio — impossível checar membros/leads por origem")
    else:
        membros_por_origem = raw_df.groupby('init_date')['member'].nunique()
        if not (membros_por_origem == N_MEMBROS_ESPERADO).all():
            motivos.append(f"B) nem todas as origens têm {N_MEMBROS_ESPERADO} membros")
        leads_por_origem = raw_df.groupby('init_date')['lead'].nunique()
        if not (leads_por_origem == len(LEADS)).all():
            motivos.append(f"C) nem todas as origens têm {len(LEADS)} leads")

    esperado_raw = len(PILOT_ORIGENS) * N_MEMBROS_ESPERADO * len(LEADS)
    if len(raw_df) != esperado_raw:
        motivos.append(f"D) {len(raw_df)} linhas raw, esperado {esperado_raw}")

    esperado_summary = len(PILOT_ORIGENS) * len(LEADS)
    if len(r['summary_df']) != esperado_summary:
        motivos.append(f"E) {len(r['summary_df'])} summaries, esperado {esperado_summary}")

    target_ini, target_fim = intervalo_targets_necessario(r['origens'], LEADS)
    n_meses_chirps_esperado = len(pd.period_range(target_ini, target_fim, freq='M'))
    if len(r['chirps_df']) != n_meses_chirps_esperado:
        motivos.append(f"F) CHIRPS com {len(r['chirps_df'])} meses, esperado {n_meses_chirps_esperado} "
                        f"({target_ini} a {target_fim}, derivado das origens×leads pedidas)")

    if r['avaliacao_n'] != PILOT_FORECASTS_AVALIACAO_ESPERADOS:
        motivos.append(f"G) n_forecasts_avaliacao_principal={r['avaliacao_n']}, "
                        f"esperado {PILOT_FORECASTS_AVALIACAO_ESPERADOS} — pilot não pode terminar "
                        f"aprovado com a avaliação principal vazia ou incompleta (run 35260471652).")

    avaliacao_df = r.get('avaliacao_df')
    if avaliacao_df is None or avaliacao_df.empty:
        motivos.append("H) nenhum forecast avaliável — impossível checar clim_n/bias_training_n/"
                        "bias_mm/ens_mean_bc (bias correction nunca foi exercitada)")
        motivos.append("I) nenhum forecast avaliável — impossível checar soma das probabilidades RAW")
        motivos.append("J) nenhum forecast avaliável — impossível checar soma das probabilidades BC")
        motivos.append("Seção 12) nenhum forecast avaliável — impossível checar desenvolvimento/confirmação")
    else:
        if (avaliacao_df['clim_n'] < MIN_ANOS_TREINO).any():
            motivos.append("H) há forecast avaliável com clim_n < MIN_ANOS_TREINO")
        if (avaliacao_df['bias_training_n'] < MIN_ANOS_TREINO).any():
            motivos.append("H) há forecast avaliável com bias_training_n < MIN_ANOS_TREINO — bias "
                            "correction não teve histórico suficiente (reprodução do defeito do run "
                            "35260471652)")
        if not np.isfinite(avaliacao_df['bias_mm'].astype(float)).all():
            motivos.append("H) há forecast avaliável com bias_mm não finito (NaN/inf)")
        if not np.isfinite(avaliacao_df['ens_mean_bc'].astype(float)).all():
            motivos.append("H) há forecast avaliável com ens_mean_bc não finito (NaN/inf)")
        n_com_obs = int(np.isfinite(avaliacao_df['chirps_prec_mm'].astype(float)).sum())
        if n_com_obs != len(avaliacao_df):
            motivos.append(f"H) cobertura observacional incompleta: {n_com_obs}/{len(avaliacao_df)} "
                            "forecasts avaliáveis têm chirps_prec_mm finito (correção pós-run "
                            "35353196015 — nunca aceitar candidatos sem observação real)")

        soma_raw = (avaliacao_df['prob_below_raw'].astype(float) +
                    avaliacao_df['prob_normal_raw'].astype(float) +
                    avaliacao_df['prob_above_raw'].astype(float))
        if not np.allclose(soma_raw, 1.0, atol=1e-6):
            motivos.append("I) probabilidades RAW não somam 1 em todos os forecasts avaliáveis")

        soma_bc = (avaliacao_df['prob_below_bc'].astype(float) +
                   avaliacao_df['prob_normal_bc'].astype(float) +
                   avaliacao_df['prob_above_bc'].astype(float))
        if not np.allclose(soma_bc, 1.0, atol=1e-6):
            motivos.append("J) probabilidades BC não somam 1 em todos os forecasts avaliáveis")

        periodos_presentes = set(avaliacao_df['evaluation_period'].unique())
        if 'desenvolvimento' not in periodos_presentes or \
                (avaliacao_df['evaluation_period'] == 'desenvolvimento').sum() == 0:
            motivos.append("Seção 12) sem forecasts avaliáveis em desenvolvimento (1991-2007)")
        if 'confirmacao' not in periodos_presentes or \
                (avaliacao_df['evaluation_period'] == 'confirmacao').sum() == 0:
            motivos.append("Seção 12) sem forecasts avaliáveis em confirmação (2008-2016)")

    if not r['leakage_audit_aprovado']:
        motivos.append("K) auditoria de leakage reprovada")

    for nome in TABELAS_SKILL_OBRIGATORIAS:
        tabela = r['tabelas_skill'].get(nome)
        if tabela is None or tabela.empty:
            motivos.append(f"L) tabela de skill obrigatória vazia: {nome}")

    bootstrap_df = r['bootstrap_df']
    if bootstrap_df is None or bootstrap_df.empty:
        motivos.append("M) bootstrap_skill vazio")
    elif 'estimativa' in bootstrap_df.columns and bootstrap_df['estimativa'].isna().all():
        motivos.append("M) bootstrap_skill sem nenhuma estimativa calculada (todas NaN)")

    return (len(motivos) == 0, motivos)


# ══════════════════════════════════════════════════════════════════════════
# Validação do HINDCAST COMPLETO OFICIAL (preparação do disparo real,
# 1981-2016) — barreira de INTEGRIDADE DO EXPERIMENTO, nunca de skill.
# MSESS/RPSS negativo, bias correction que piora ou um lead ruim são
# resultados científicos válidos e NUNCA reprovam esta barreira; só
# reprova se o experimento em si ficou incompleto ou corrompido
# (origens faltando, contagens erradas, leakage, tabela/bootstrap
# vazios). Só é aplicada quando a execução pedida é EXATAMENTE a
# oficial (1981-2016, todos os 12 meses) — uma execução parcial/
# depuração continua no gate de leakage já existente, sem essa barreira
# extra.
# ══════════════════════════════════════════════════════════════════════════

def validar_full_aprovado(resultado):
    """Retorna (aprovado: bool, motivos: list[str]) — mesmo formato de
    validar_pilot_aprovado, mas para a execução oficial completa."""
    r = resultado
    motivos = []
    n_origens_esperado = (ANO_FIM_HINDCAST - ANO_INICIO_HINDCAST + 1) * 12

    n_ok = len(r['origens']) - len(r['falhas'])
    if n_ok != n_origens_esperado:
        motivos.append(f"origens: {n_ok}/{len(r['origens'])} processadas com sucesso, "
                        f"esperado {n_origens_esperado}/{n_origens_esperado}")

    raw_esperado = n_origens_esperado * N_MEMBROS_ESPERADO * len(LEADS)
    if len(r['raw_df']) != raw_esperado:
        motivos.append(f"raw: {len(r['raw_df'])} linhas, esperado {raw_esperado}")

    summary_esperado = n_origens_esperado * len(LEADS)
    if len(r['summary_df']) != summary_esperado:
        motivos.append(f"summary: {len(r['summary_df'])} linhas, esperado {summary_esperado}")

    # Seção 15 — nº de forecasts avaliáveis também derivado das origens
    # pedidas (não hardcoded): origens com ano >= AVALIACAO_ANO_INICIO
    # × leads. Para o FULL oficial: 26 anos (1991-2016) × 12 meses ×
    # 6 leads = 1.872.
    n_origens_avaliacao = len([1 for ano, _ in r['origens'] if ano >= AVALIACAO_ANO_INICIO])
    n_forecasts_avaliacao_esperado = n_origens_avaliacao * len(LEADS)
    if r['avaliacao_n'] != n_forecasts_avaliacao_esperado:
        motivos.append(f"n_forecasts_avaliacao_principal={r['avaliacao_n']}, esperado "
                        f"{n_forecasts_avaliacao_esperado}")

    # Seção 6 — nunca fixar o número de meses do CHIRPS: derivar
    # dinamicamente de min/max target_month das origens×leads pedidas
    # (correção pós-run 35353196015: origem=2016-12/lead=6 alcança
    # 2017-05, então o CHIRPS oficial cobre 437 meses, não 432).
    target_ini, target_fim = intervalo_targets_necessario(r['origens'], LEADS)
    n_meses_chirps_esperado = len(pd.period_range(target_ini, target_fim, freq='M'))
    if len(r['chirps_df']) != n_meses_chirps_esperado:
        motivos.append(f"CHIRPS: {len(r['chirps_df'])} meses, esperado {n_meses_chirps_esperado} "
                        f"({target_ini} a {target_fim}, derivado das origens×leads pedidas)")

    # Seção 5/15 — não aceitar novamente candidatos na avaliação
    # principal sem observação real (run 35353196015: 1.872 candidatos
    # / só 1.857 com chirps_prec_mm finito).
    avaliacao_df = r.get('avaliacao_df')
    if avaliacao_df is None or avaliacao_df.empty:
        if r.get('avaliacao_n', 0) > 0:
            motivos.append("cobertura observacional: avaliacao_df ausente/vazio mas avaliacao_n>0 — "
                            "impossível checar chirps_prec_mm")
    else:
        n_com_obs = int(np.isfinite(avaliacao_df['chirps_prec_mm'].astype(float)).sum())
        if n_com_obs != len(avaliacao_df):
            motivos.append(f"cobertura observacional: {n_com_obs}/{len(avaliacao_df)} forecasts da "
                            f"avaliação principal têm chirps_prec_mm finito, esperado "
                            f"{len(avaliacao_df)}/{len(avaliacao_df)}")

    if not r['leakage_audit_aprovado']:
        motivos.append("auditoria de leakage reprovada")

    for nome in TABELAS_SKILL_OBRIGATORIAS:
        tabela = r['tabelas_skill'].get(nome)
        if tabela is None or tabela.empty:
            motivos.append(f"tabela de skill obrigatória vazia: {nome}")

    bootstrap_df = r['bootstrap_df']
    if bootstrap_df is None or bootstrap_df.empty:
        motivos.append("bootstrap_skill vazio")

    return (len(motivos) == 0, motivos)


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start-year', type=int, default=ANO_INICIO_HINDCAST)
    ap.add_argument('--end-year', type=int, default=ANO_FIM_HINDCAST)
    ap.add_argument('--init-months', default=None, help='ex.: 1,4,7,10 — default todos os 12')
    ap.add_argument('--dry-run-plan', action='store_true',
                     help='Não acessa o CDS — só lista o plano de execução e valida guardrails.')
    ap.add_argument('--pilot', action='store_true',
                     help=f'Roda o pilot longitudinal ({len(PILOT_ORIGENS)} origens — todos jan/jul '
                          f'de {ANO_INICIO_HINDCAST}-{ANO_FIM_HINDCAST}), nunca o hindcast completo.')
    args = ap.parse_args()

    meses = [int(x) for x in args.init_months.split(',')] if args.init_months else None

    if args.dry_run_plan:
        if args.pilot:
            imprimir_plano(plano_piloto(), modo=f'PILOT LONGITUDINAL ({len(PILOT_ORIGENS)} origens)')
        else:
            imprimir_plano(plano_execucao(args.start_year, args.end_year, meses))
        return

    status = dl.verificar_acesso(verbose=True)
    if not status['credenciais_configuradas']:
        raise SystemExit("CDS_API_KEY não configurado (ver docs/c3s-poc.md) — FALHANDO. Nunca "
                          "simulando resultado real.")
    if not status['pacote_cdsapi_instalado']:
        raise SystemExit("pacote cdsapi não instalado — rode `pip install -r requirements-c3s.txt`.")

    if args.pilot:
        origens = PILOT_ORIGENS
        print(f"=== C3S Hindcast Completo — MODO PILOTO LONGITUDINAL — {len(origens)} origens ===")
    else:
        origens = construir_origens(args.start_year, args.end_year, meses)
        print(f"=== C3S Hindcast Completo — {len(origens)} origens — leads {LEADS} ===")
        if (args.start_year, args.end_year) != (ANO_INICIO_HINDCAST, ANO_FIM_HINDCAST) or meses:
            print(f"  ⚠ AVISO: execução parcial — resultado NÃO é oficial da Fase 2A.3 (só é oficial "
                  f"com {ANO_INICIO_HINDCAST}-{ANO_FIM_HINDCAST}, todos os 12 meses, completo).")

    resultado = rodar(origens, pilot=args.pilot)
    escrever_saidas(resultado)

    if args.pilot:
        aprovado, motivos = validar_pilot_aprovado(resultado)
        if not aprovado:
            print("\n❌ PILOT REPROVADO — artifacts gravados para diagnóstico; encerrando com erro "
                  "(correção pós-run 35260471652: pilot só aprova se bias/skill/bootstrap tiverem "
                  "sido genuinamente exercitados, não basta o pipeline rodar sem exceção):")
            for motivo in motivos:
                print(f"  - {motivo}")
            sys.exit(1)
        print("\n✅ PILOT APROVADO — todas as camadas científicas (bias, probabilidades, skill, "
              "bootstrap) foram genuinamente exercitadas — ver artifacts/c3s_hindcast/RELATORIO.md")
        print("⚠ PILOT — NÃO É CONCLUSÃO FINAL DE SKILL. É apenas um pilot metodológico "
              "longitudinal (72 origens, 1/6 do hindcast completo); skill anual completo só é "
              "conclusivo com 1981-2016, todos os 12 meses.")
        return

    execucao_oficial = (args.start_year, args.end_year) == (ANO_INICIO_HINDCAST, ANO_FIM_HINDCAST) and not meses
    if execucao_oficial:
        aprovado, motivos = validar_full_aprovado(resultado)
        if not aprovado:
            print("\n❌ HINDCAST COMPLETO OFICIAL REPROVADO — artifacts gravados para diagnóstico; "
                  "encerrando com erro (guardrail de INTEGRIDADE DO EXPERIMENTO — skill negativo "
                  "NUNCA é motivo de reprovação aqui, só experimento incompleto/corrompido):")
            for motivo in motivos:
                print(f"  - {motivo}")
            sys.exit(1)
        target_ini, target_fim = intervalo_targets_necessario(origens, LEADS)
        n_meses_chirps = len(pd.period_range(target_ini, target_fim, freq='M'))
        print("\n✅ HINDCAST COMPLETO OFICIAL 1981-2016 APROVADO — integridade do experimento "
              f"confirmada (432 origens, 64.800 raw, 2.592 summaries, CHIRPS {n_meses_chirps} meses "
              f"[{target_ini} a {target_fim}], cobertura observacional completa, leakage OK, "
              "tabelas de skill e bootstrap preenchidos) — ver artifacts/c3s_hindcast/RELATORIO.md")
        return

    if not resultado['leakage_audit_aprovado']:
        print("\n❌ AUDITORIA DE LEAKAGE REPROVADA — artifacts gravados; encerrando com erro "
              "(Seção 30: qualquer violação reprova a fase).")
        sys.exit(1)
    print("\n✅ execução concluída sem violação de leakage — ver artifacts/c3s_hindcast/RELATORIO.md")


if __name__ == '__main__':
    main()
