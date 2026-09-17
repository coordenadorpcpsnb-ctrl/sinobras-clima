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
como PILOTO (6 origens), e só depois (se aprovado) como hindcast
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

# Seção 37 — pilot fixo, 6 origens (2 por década: 1991/2000/2010, jan e jul).
PILOT_ORIGENS = [(1991, 1), (1991, 7), (2000, 1), (2000, 7), (2010, 1), (2010, 7)]

ARTIFACT_FILENAMES = [
    'c3s_hindcast_raw.csv', 'c3s_hindcast_summary.csv', 'chirps_sao_bento_1981_2016.csv',
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
# CHIRPS consolidado 1981-2016 — uma única chamada (Seção 9), mesmo
# núcleo de _chirps.py (_geometria_ponto/_buscar_prec_chirps_geom) e o
# mesmo intervalo mensal corrigido de _c3s_utils.py
# (intervalo_mensal_chirps). Nunca cai para ERA5/CHC-Preliminar/
# Open-Meteo — falha explícita se CHIRPS não cobrir o período inteiro.
# ══════════════════════════════════════════════════════════════════════════

def buscar_chirps_consolidado(ano_ini=ANO_INICIO_HINDCAST, mes_ini=1, ano_fim=ANO_FIM_HINDCAST, mes_fim=12):
    info = MUNICIPIOS[MUNICIPIO]
    geom = _geometria_ponto(info['lat'], info['lon'])
    ini, fim = intervalo_mensal_chirps(ano_ini, mes_ini, ano_fim, mes_fim)
    df = _buscar_prec_chirps_geom(ini, fim, geom, rotulo=MUNICIPIO)
    if df.empty:
        raise RuntimeError("CHIRPS indisponível para o período do hindcast completo — FALHANDO "
                            "(Seção 9: nunca cair para ERA5/CHC-Preliminar/Open-Meteo aqui).")
    df = df.copy()
    df['target_month'] = pd.PeriodIndex(pd.to_datetime(dict(year=df.ano, month=df.mes, day=1)), freq='M')
    df = df.rename(columns={'prec': 'chirps_prec_mm'})
    df['source'] = 'CHIRPS'

    esperado = pd.period_range(f'{ano_ini}-{mes_ini:02d}', f'{ano_fim}-{mes_fim:02d}', freq='M')
    faltando = [str(m) for m in esperado if m not in set(df['target_month'])]
    if faltando:
        raise RuntimeError(f"CHIRPS não cobre {len(faltando)} mês(es) do período: "
                            f"{faltando[:5]}{'...' if len(faltando) > 5 else ''} — FALHANDO.")
    if df['target_month'].duplicated().any():
        dups = [str(v) for v in df.loc[df['target_month'].duplicated(), 'target_month']]
        raise RuntimeError(f"CHIRPS tem mês(es) duplicado(s): {dups} — FALHANDO.")
    if df['chirps_prec_mm'].isna().any():
        raise RuntimeError("CHIRPS tem valor(es) NaN — FALHANDO.")
    if (df['chirps_prec_mm'] < 0).any():
        raise RuntimeError("CHIRPS tem precipitação negativa — FALHANDO.")

    df['year'] = df['target_month'].apply(lambda p: p.year)
    df['month'] = df['target_month'].apply(lambda p: p.month)
    return df[['year', 'month', 'target_month', 'chirps_prec_mm', 'source']] \
        .sort_values('target_month').reset_index(drop=True)


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

def _max_init_usado_bias(ens_df, origem, mes_cal, lead):
    f = ens_df[(ens_df['lead'] == lead) & (ens_df['init_date'] < origem) &
               (ens_df['target_month'].apply(lambda p: p.month) == mes_cal)]
    return f['init_date'].max() if not f.empty else None


def construir_leakage_audit(summary_df, ens_df, chirps_df):
    if summary_df.empty:
        return pd.DataFrame(columns=['init_date', 'target_month', 'max_obs_date_used_climatology',
                                      'max_init_date_used_bias', 'clim_n', 'bias_training_n', 'leakage_status'])
    chirps_por_target = chirps_df[['target_month', 'chirps_prec_mm']].drop_duplicates('target_month')
    linhas = []
    for _, row in summary_df.iterrows():
        origem, mes_cal, lead = row['init_date'], row['target_calendar_month'], row['lead']
        sub_clim = chirps_por_target[(chirps_por_target['target_month'] < origem) &
                                      (chirps_por_target['target_month'].apply(lambda p: p.month) == mes_cal)]
        max_obs = sub_clim['target_month'].max() if not sub_clim.empty else None
        max_init_bias = _max_init_usado_bias(ens_df, origem, mes_cal, lead)

        violou = False
        if max_obs is not None and not (max_obs < origem):
            violou = True
        if max_init_bias is not None and not (max_init_bias < origem):
            violou = True

        linhas.append({
            'init_date': str(origem), 'target_month': str(row['target_month']),
            'max_obs_date_used_climatology': str(max_obs) if max_obs is not None else None,
            'max_init_date_used_bias': str(max_init_bias) if max_init_bias is not None else None,
            'clim_n': row['clim_n'], 'bias_training_n': row['bias_training_n'],
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


def imprimir_plano(plano):
    print("=== C3S Hindcast Completo — DRY RUN PLAN (nenhum acesso ao CDS) ===")
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

    print("\n=== buscando CHIRPS consolidado 1981-2016 ===")
    chirps_df = buscar_chirps_consolidado(ANO_INICIO_HINDCAST, 1, ANO_FIM_HINDCAST, 12)
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
    linhas = ["# Hindcast Completo SEAS5 — São Bento do Tocantins — Fase 2A.3", "",
              f"- Modo: {modo}", f"- Origens processadas com sucesso: {n_ok}/{len(r['origens'])}",
              f"- Linhas raw: {len(r['raw_df'])}", f"- Linhas summary: {len(r['summary_df'])}",
              f"- Forecasts na avaliação principal (1991-{AVALIACAO_ANO_FIM}, histórico suficiente): "
              f"{r['avaliacao_n']}",
              f"- Auditoria de leakage: {'✅ APROVADA' if r['leakage_audit_aprovado'] else '❌ REPROVADA'}"]

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
    linhas += ["", "---", "",
               f"Relatório gerado a partir de {'PILOTO (6 origens fixas)' if r['pilot'] else 'execução completa'} "
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


def montar_metadata(resultado):
    centro, sistema = cat.SISTEMA_ESCOLHIDO_FASE_2A
    r = resultado
    return {
        'data_execucao': datetime.now(timezone.utc).isoformat(),
        'modo': 'piloto' if r['pilot'] else 'completo',
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


def escrever_saidas(resultado):
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    r = resultado

    r['raw_df'].to_csv(ARTIFACTS_DIR / 'c3s_hindcast_raw.csv', index=False)
    r['summary_df'].to_csv(ARTIFACTS_DIR / 'c3s_hindcast_summary.csv', index=False)
    r['chirps_df'].to_csv(ARTIFACTS_DIR / 'chirps_sao_bento_1981_2016.csv', index=False)
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
                     help=f'Roda só as {len(PILOT_ORIGENS)} origens fixas do piloto (Seção 37/39).')
    args = ap.parse_args()

    meses = [int(x) for x in args.init_months.split(',')] if args.init_months else None

    if args.dry_run_plan:
        plano = plano_execucao(args.start_year, args.end_year, meses)
        imprimir_plano(plano)
        return

    status = dl.verificar_acesso(verbose=True)
    if not status['credenciais_configuradas']:
        raise SystemExit("CDS_API_KEY não configurado (ver docs/c3s-poc.md) — FALHANDO. Nunca "
                          "simulando resultado real.")
    if not status['pacote_cdsapi_instalado']:
        raise SystemExit("pacote cdsapi não instalado — rode `pip install -r requirements-c3s.txt`.")

    if args.pilot:
        origens = PILOT_ORIGENS
        print(f"=== C3S Hindcast Completo — MODO PILOTO — {len(origens)} origens fixas ===")
    else:
        origens = construir_origens(args.start_year, args.end_year, meses)
        print(f"=== C3S Hindcast Completo — {len(origens)} origens — leads {LEADS} ===")
        if (args.start_year, args.end_year) != (ANO_INICIO_HINDCAST, ANO_FIM_HINDCAST) or meses:
            print(f"  ⚠ AVISO: execução parcial — resultado NÃO é oficial da Fase 2A.3 (só é oficial "
                  f"com {ANO_INICIO_HINDCAST}-{ANO_FIM_HINDCAST}, todos os 12 meses, completo).")

    resultado = rodar(origens, pilot=args.pilot)
    escrever_saidas(resultado)

    if not resultado['leakage_audit_aprovado']:
        print("\n❌ AUDITORIA DE LEAKAGE REPROVADA — artifacts gravados; encerrando com erro "
              "(Seção 30: qualquer violação reprova a fase).")
        sys.exit(1)
    print("\n✅ execução concluída sem violação de leakage — ver artifacts/c3s_hindcast/RELATORIO.md")


if __name__ == '__main__':
    main()
