#!/usr/bin/env python3
"""
c3s_hindcast.py — Fase 2A: backtest e métricas do C3S vs climatologia
local (Seções 8-14).

Toda função aqui é pura (recebe DataFrames, devolve DataFrames/dicts) —
não baixa nada, não abre GRIB. Entrada esperada: a tabela de
c3s_processar.py (local, init_date, target_month, lead, centre, system,
member, forecast_prec_mm) e uma série observada [local, ano, mes, prec]
(CHIRPS, ver c3s_observado_chirps.py).

CLIMATOLOGIA (Seção 8): sempre recalculada por origem (=init_date) e por
município, usando só observação com data <= init_date — mesmo desenho
leakage-safe da infraestrutura de pesquisa (cortar por origem antes de
qualquer estatística), aplicado aqui à série CHIRPS por município.

BIAS CORRECTION (Seção 9): variante B usa só hindcasts com init_date <
origem avaliada — nunca o próprio período de teste. Variante C (quantile
mapping) NÃO foi implementada nesta fase — a tarefa permite
explicitamente pular se ficar complexo/instável, e sem dado real do C3S
para validar a implementação seria pura especulação sobre uma amostra
sintética.

NOTA (branch claude/c3s-poc-integration, derivada de main): esta versão
NÃO importa benchmark_modelos.py/backtest.py (infraestrutura da Fase 1.x
de pesquisa, que não existe nesta branch mínima) — a versão original em
claude/fase2a-c3s-hindcast reaproveitava MES_PARA_ESTACAO/
classificar_periodo_operacional de lá só para diagnósticos por estação
que nenhum dos módulos desta POC (c3s_poc.py, tests/test_c3s*.py) usa;
removidos aqui para manter a branch autocontida.
"""

import numpy as np
import pandas as pd

PERCENTIS_ENSEMBLE = {'p10': 10, 'p25': 25, 'p75': 75, 'p90': 90}
BLOCOS_MESES_CRITICOS = [9, 10, 11, 12, 1, 2]   # Seção 13 — set a fev


# ══════════════════════════════════════════════════════════════════════════
# 1. CLIMATOLOGIA LEAKAGE-SAFE POR ORIGEM (Seção 8)
# ══════════════════════════════════════════════════════════════════════════

def climatologia_ate_origem(obs_df, local, origem, mes_alvo):
    """obs_df: colunas [local, ym (Period 'M'), prec]. Só dado com
    ym < origem entra — o init_date em si nunca tem observação própria
    ainda disponível no momento em que o hindcast/forecast é emitido
    (a rodada de origem é inicializada ANTES do mês em si acontecer)."""
    sub = obs_df[(obs_df['local'] == local) & (obs_df['ym'] < origem) &
                 (obs_df['ym'].apply(lambda p: p.month) == mes_alvo)]
    if sub.empty:
        return None, None, None
    return float(sub['prec'].mean()), float(sub['prec'].quantile(0.20)), float(sub['prec'].quantile(0.80))


def terciles_ate_origem(obs_df, local, origem, mes_alvo):
    sub = obs_df[(obs_df['local'] == local) & (obs_df['ym'] < origem) &
                 (obs_df['ym'].apply(lambda p: p.month) == mes_alvo)]
    if len(sub) < 3:
        return None, None
    return float(sub['prec'].quantile(1 / 3)), float(sub['prec'].quantile(2 / 3))


# ══════════════════════════════════════════════════════════════════════════
# 2. BIAS CORRECTION (Seção 9) — só hindcasts com init_date < origem
# ══════════════════════════════════════════════════════════════════════════

def bias_medio_ate_origem(df_forecast_membros_mean, df_obs_por_target, local, origem, mes_alvo_calendario, lead):
    """Viés médio (previsto_ensemble_mean - observado) para (local,
    mês-calendário-alvo, lead), usando só pares com init_date < origem.
    df_forecast_membros_mean: [local, init_date(Period), target_month(Period),
    lead, ensemble_mean]. df_obs_por_target: [local, target_month(Period), prec]."""
    f = df_forecast_membros_mean[
        (df_forecast_membros_mean['local'] == local) &
        (df_forecast_membros_mean['lead'] == lead) &
        (df_forecast_membros_mean['init_date'] < origem) &
        (df_forecast_membros_mean['target_month'].apply(lambda p: p.month) == mes_alvo_calendario)
    ]
    if f.empty:
        return None
    m = f.merge(df_obs_por_target[df_obs_por_target['local'] == local], on=['local', 'target_month'], how='inner')
    if m.empty:
        return None
    return float((m['ensemble_mean'] - m['prec']).mean())


def aplicar_bias_correction(df_previsao, df_obs_por_target):
    """Para cada linha de df_previsao (já com ensemble_mean calculado),
    calcula forecast_corr = ensemble_mean - bias_medio_ate_origem(...).
    Retorna df_previsao com coluna nova 'ensemble_mean_corrigido'."""
    df = df_previsao.copy()
    correcoes = []
    for _, row in df.iterrows():
        b = bias_medio_ate_origem(df, df_obs_por_target, row['local'], row['init_date'],
                                   row['target_month'].month, row['lead'])
        correcoes.append(row['ensemble_mean'] - b if b is not None else np.nan)
    df['ensemble_mean_corrigido'] = correcoes
    return df


# ══════════════════════════════════════════════════════════════════════════
# 3. ESTATÍSTICAS DE ENSEMBLE E PROBABILIDADES (Seção 10)
# ══════════════════════════════════════════════════════════════════════════

def estatisticas_ensemble(valores_membros):
    v = np.asarray(valores_membros, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return {k: None for k in ['mean', 'median', 'p10', 'p25', 'p75', 'p90']}
    r = {'mean': float(np.mean(v)), 'median': float(np.median(v))}
    for nome, pct in PERCENTIS_ENSEMBLE.items():
        r[nome] = float(np.percentile(v, pct))
    return r


def probabilidade_evento(valores_membros, limiar, direcao):
    """direcao: 'abaixo' ou 'acima'. Fração de membros do ensemble que
    satisfaz o evento — NUNCA a partir de um único membro (Seção 12)."""
    v = np.asarray(valores_membros, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return None
    if direcao == 'abaixo':
        return float(np.mean(v < limiar))
    elif direcao == 'acima':
        return float(np.mean(v > limiar))
    raise ValueError("direcao deve ser 'abaixo' ou 'acima'")


def probabilidade_terciles(valores_membros, t1, t2):
    """(p_abaixo_do_normal, p_normal, p_acima_do_normal) — fração do
    ensemble em cada faixa definida pelos terciles climatológicos
    (t1=tercil inferior, t2=tercil superior)."""
    v = np.asarray(valores_membros, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return None, None, None
    return float(np.mean(v < t1)), float(np.mean((v >= t1) & (v <= t2))), float(np.mean(v > t2))


# ══════════════════════════════════════════════════════════════════════════
# 4. MÉTRICAS DETERMINÍSTICAS (Seção 11)
# ══════════════════════════════════════════════════════════════════════════

def _rmse(o, p):
    o, p = np.asarray(o, dtype=float), np.asarray(p, dtype=float)
    return float(np.sqrt(np.mean((o - p) ** 2)))


def _mae(o, p):
    o, p = np.asarray(o, dtype=float), np.asarray(p, dtype=float)
    return float(np.mean(np.abs(o - p)))


def _bias(o, p):
    o, p = np.asarray(o, dtype=float), np.asarray(p, dtype=float)
    return float(np.mean(p - o))


def _corr(o, p):
    o, p = np.asarray(o, dtype=float), np.asarray(p, dtype=float)
    if len(o) < 2 or np.std(o) == 0 or np.std(p) == 0:
        return None
    return float(np.corrcoef(o, p)[0, 1])


def metricas_deterministicas(df):
    """df precisa ter colunas observado/previsto. Devolve dict com
    rmse/mae/bias/corr/n."""
    d = df.dropna(subset=['observado', 'previsto'])
    if d.empty:
        return {'n': 0, 'rmse': None, 'mae': None, 'bias': None, 'corr': None}
    return {'n': len(d), 'rmse': round(_rmse(d['observado'], d['previsto']), 2),
            'mae': round(_mae(d['observado'], d['previsto']), 2),
            'bias': round(_bias(d['observado'], d['previsto']), 2),
            'corr': (round(_corr(d['observado'], d['previsto']), 4)
                     if _corr(d['observado'], d['previsto']) is not None else None)}


def skill_vs_climatologia(rmse_modelo, rmse_climatologia):
    if not rmse_climatologia:
        return None
    return round(1 - rmse_modelo / rmse_climatologia, 4)


# ══════════════════════════════════════════════════════════════════════════
# 5. MÉTRICAS PROBABILÍSTICAS (Seção 12)
# ══════════════════════════════════════════════════════════════════════════

def brier_score(probabilidades, eventos_binarios):
    p = np.asarray(probabilidades, dtype=float)
    o = np.asarray(eventos_binarios, dtype=float)
    mask = np.isfinite(p) & np.isfinite(o)
    if mask.sum() == 0:
        return None
    return float(np.mean((p[mask] - o[mask]) ** 2))


def brier_skill_score(bs_modelo, bs_climatologia):
    if not bs_climatologia:
        return None
    return round(1 - bs_modelo / bs_climatologia, 4)


def rps_uma_previsao(probs_terciles_previstas, tercil_observado_idx):
    """RPS de UMA previsão: soma dos quadrados das diferenças das somas
    acumuladas de probabilidade entre previsto e observado (one-hot),
    ao longo das 3 categorias (abaixo/normal/acima)."""
    obs_onehot = np.zeros(3)
    obs_onehot[tercil_observado_idx] = 1.0
    cum_prev = np.cumsum(probs_terciles_previstas)
    cum_obs = np.cumsum(obs_onehot)
    return float(np.sum((cum_prev - cum_obs) ** 2))


def rpss(lista_probs_previstas, lista_tercil_observado_idx, lista_probs_climatologia):
    rps_modelo = [rps_uma_previsao(p, o) for p, o in zip(lista_probs_previstas, lista_tercil_observado_idx)]
    rps_clim = [rps_uma_previsao(p, o) for p, o in zip(lista_probs_climatologia, lista_tercil_observado_idx)]
    media_clim = float(np.mean(rps_clim))
    if media_clim == 0:
        return None
    return round(1 - float(np.mean(rps_modelo)) / media_clim, 4)


# ══════════════════════════════════════════════════════════════════════════
# 6. AGRUPAMENTOS (município / lead / mês-alvo / estação / período operacional)
# ══════════════════════════════════════════════════════════════════════════

def metricas_por_grupo(df, colunas_grupo):
    resultado = {}
    for chave, g in df.groupby(colunas_grupo):
        resultado[chave if isinstance(chave, tuple) else (chave,)] = metricas_deterministicas(g)
    return resultado
