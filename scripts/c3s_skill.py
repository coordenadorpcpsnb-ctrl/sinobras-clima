#!/usr/bin/env python3
"""
c3s_skill.py — Fase 2A.3: métricas de skill (determinísticas e
probabilísticas) e bootstrap para o hindcast completo SEAS5 / São
Bento.

Reaproveita ao máximo c3s_hindcast.py (já validado): `brier_score`,
`brier_skill_score`, `rps_uma_previsao`, `rpss`, `metricas_deterministicas`
não são reimplementados aqui, só orquestrados. O que é novo:

  - MSESS (skill sobre erro quadrático médio — a definição estatística
    convencional de skill quadrático, Seção 16) — c3s_hindcast.py só
    tinha RMSESS (`skill_vs_climatologia`, reaproveitado aqui como-está
    para RMSESS).
  - Brier Score separado para "abaixo" e "acima" (c3s_hindcast.py::
    brier_score já é genérico o bastante — aqui só a orquestração dos
    dois eventos).
  - CRPS empírico do ensemble (Seção 22 — opcional, best-effort; nunca
    bloqueia o resto da fase se algo der errado aqui).
  - bootstrap por ano de inicialização (Seção 24).

Toda função é pura (arrays/DataFrames -> dict) — não baixa nada, não
abre GRIB, não faz I/O.
"""

import numpy as np
import pandas as pd

import c3s_hindcast as hc

# ══════════════════════════════════════════════════════════════════════════
# Métricas determinísticas — MSE/MSESS (Seção 16). RMSESS já existe em
# c3s_hindcast.py::skill_vs_climatologia — reaproveitado como está.
# ══════════════════════════════════════════════════════════════════════════

def mse(observado, previsto):
    o, p = np.asarray(observado, dtype=float), np.asarray(previsto, dtype=float)
    return float(np.mean((o - p) ** 2))


def msess(mse_modelo, mse_climatologia):
    """MSESS = 1 - MSE_model/MSE_clim (Seção 16 — definição estatística
    convencional de skill quadrático, preferida a RMSESS). >0 melhora
    sobre climatologia, =0 igual, <0 pior."""
    if not mse_climatologia:
        return None
    return round(1 - mse_modelo / mse_climatologia, 4)


def metricas_vs_clim(df, coluna_observado, coluna_previsto):
    """Wrapper fino sobre hc.metricas_deterministicas — monta o DataFrame
    [observado, previsto] que ela espera a partir de nomes de coluna
    arbitrários, sem reimplementar o cálculo."""
    sub = pd.DataFrame({'observado': df[coluna_observado], 'previsto': df[coluna_previsto]})
    return hc.metricas_deterministicas(sub)


def tabela_skill_deterministico(df, coluna_observado='chirps_prec_mm', coluna_clim='climatological_mean',
                                 coluna_raw='ens_mean_raw', coluna_bc='ens_mean_bc'):
    """Uma linha com CLIM/RAW/BC comparados contra o observado — n,
    rmse/mae/bias/corr de cada um, e o skill (RMSESS e MSESS) de RAW e
    BC contra CLIM (Seção 16/17). `df` já deve estar filtrado para o
    período/grupo de interesse (ex.: um lead, um mês-alvo, uma estação)
    e sem linhas SEM_HISTORICO_SUFICIENTE."""
    d = df.dropna(subset=[coluna_observado, coluna_clim, coluna_raw, coluna_bc])
    if d.empty:
        return {'n': 0, 'rmse_clim': None, 'rmse_raw': None, 'rmse_bc': None,
                'mae_raw': None, 'bias_raw': None, 'corr_raw': None,
                'mae_bc': None, 'bias_bc': None, 'corr_bc': None,
                'rmsess_raw': None, 'msess_raw': None, 'rmsess_bc': None, 'msess_bc': None}

    m_clim = metricas_vs_clim(d, coluna_observado, coluna_clim)
    m_raw = metricas_vs_clim(d, coluna_observado, coluna_raw)
    m_bc = metricas_vs_clim(d, coluna_observado, coluna_bc)

    mse_clim = mse(d[coluna_observado], d[coluna_clim])
    mse_raw = mse(d[coluna_observado], d[coluna_raw])
    mse_bc = mse(d[coluna_observado], d[coluna_bc])

    return {
        'n': m_clim['n'],
        'rmse_clim': m_clim['rmse'], 'rmse_raw': m_raw['rmse'], 'rmse_bc': m_bc['rmse'],
        'mae_raw': m_raw['mae'], 'bias_raw': m_raw['bias'], 'corr_raw': m_raw['corr'],
        'mae_bc': m_bc['mae'], 'bias_bc': m_bc['bias'], 'corr_bc': m_bc['corr'],
        'rmsess_raw': hc.skill_vs_climatologia(m_raw['rmse'], m_clim['rmse']),
        'msess_raw': msess(mse_raw, mse_clim),
        'rmsess_bc': hc.skill_vs_climatologia(m_bc['rmse'], m_clim['rmse']),
        'msess_bc': msess(mse_bc, mse_clim),
    }


# ══════════════════════════════════════════════════════════════════════════
# Métricas probabilísticas (Seção 20-22) — Brier abaixo/acima, BSS,
# RPS/RPSS reaproveitando c3s_hindcast.py; CRPS empírico é novo (Seção
# 22, opcional).
# ══════════════════════════════════════════════════════════════════════════

def categoria_tercil(valor, p33, p67):
    """0=abaixo, 1=normal, 2=acima — usado tanto para RPS (índice do
    tercil observado) quanto como conferência dos eventos binários do
    Brier."""
    if valor < p33:
        return 0
    if valor > p67:
        return 2
    return 1


def tabela_skill_probabilistico(df, coluna_observado='chirps_prec_mm', coluna_p33='clim_p33',
                                 coluna_p67='clim_p67', prefixo_raw='raw', prefixo_bc='bc'):
    """Espera colunas prob_below_<prefixo>/prob_normal_<prefixo>/
    prob_above_<prefixo> para raw e bc. Brier below/above + BSS + RPS/
    RPSS para os dois, contra climatologia 1/3-1/3-1/3 (Seção 21) —
    tudo via c3s_hindcast.py::brier_score/brier_skill_score/rpss, sem
    reimplementar a fórmula."""
    d = df.dropna(subset=[coluna_observado, coluna_p33, coluna_p67,
                           f'prob_below_{prefixo_raw}', f'prob_above_{prefixo_raw}',
                           f'prob_below_{prefixo_bc}', f'prob_above_{prefixo_bc}'])
    if d.empty:
        return {'n': 0}

    evento_abaixo = (d[coluna_observado] < d[coluna_p33]).astype(float).to_numpy()
    evento_acima = (d[coluna_observado] > d[coluna_p67]).astype(float).to_numpy()
    clim_prob = np.full(len(d), 1 / 3)

    bs_clim_abaixo = hc.brier_score(clim_prob, evento_abaixo)
    bs_clim_acima = hc.brier_score(clim_prob, evento_acima)

    tercil_obs = [categoria_tercil(v, p33, p67) for v, p33, p67 in
                  zip(d[coluna_observado], d[coluna_p33], d[coluna_p67])]
    probs_clim_rps = [[1 / 3, 1 / 3, 1 / 3]] * len(d)

    resultado = {'n': len(d), 'bs_climatologia_abaixo': round(bs_clim_abaixo, 4),
                 'bs_climatologia_acima': round(bs_clim_acima, 4)}

    for prefixo in (prefixo_raw, prefixo_bc):
        bs_abaixo = hc.brier_score(d[f'prob_below_{prefixo}'], evento_abaixo)
        bs_acima = hc.brier_score(d[f'prob_above_{prefixo}'], evento_acima)
        probs_modelo_rps = list(zip(d[f'prob_below_{prefixo}'], d[f'prob_normal_{prefixo}'],
                                     d[f'prob_above_{prefixo}']))
        resultado[f'bs_{prefixo}_abaixo'] = round(bs_abaixo, 4)
        resultado[f'bs_{prefixo}_acima'] = round(bs_acima, 4)
        resultado[f'bss_{prefixo}_abaixo'] = hc.brier_skill_score(bs_abaixo, bs_clim_abaixo)
        resultado[f'bss_{prefixo}_acima'] = hc.brier_skill_score(bs_acima, bs_clim_acima)
        resultado[f'rps_{prefixo}'] = round(float(np.mean(
            [hc.rps_uma_previsao(p, o) for p, o in zip(probs_modelo_rps, tercil_obs)])), 4)
        resultado[f'rpss_{prefixo}'] = hc.rpss(probs_modelo_rps, tercil_obs, probs_clim_rps)

    return resultado


def crps_empirico(membros, observado):
    """CRPS empírico de um ensemble finito (fórmula exata para amostra
    finita, Seção 22 — opcional/best-effort):
    CRPS = mean_i|X_i - y| - 0.5 * mean_{i,j}|X_i - X_j|.
    Devolve None se o ensemble estiver vazio, em vez de lançar."""
    v = np.asarray(membros, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return None
    termo1 = float(np.mean(np.abs(v - observado)))
    termo2 = 0.5 * float(np.mean(np.abs(v[:, None] - v[None, :])))
    return termo1 - termo2


def crpss(crps_modelo, crps_climatologia):
    if not crps_climatologia:
        return None
    return round(1 - crps_modelo / crps_climatologia, 4)


# ══════════════════════════════════════════════════════════════════════════
# Bootstrap por ano de inicialização (Seção 24)
# ══════════════════════════════════════════════════════════════════════════

def bootstrap_skill(df, coluna_ano, coluna_observado, coluna_clim, coluna_modelo,
                     n_replicacoes=2000, seed=42):
    """Reamostra ANOS DE INICIALIZAÇÃO com reposição (preserva meses/
    leads dentro de cada ano, aproximando a dependência interna — Seção
    24) e recalcula MSESS a cada réplica. Devolve estimativa pontual
    (sobre os dados observados, não a média das réplicas), IC 95%
    (percentis 2.5/97.5 das réplicas) e se é conclusivo (IC não cruza
    zero). Seed fixa e documentada — mesmo dataset + mesma seed = mesmo
    resultado (testado)."""
    d = df.dropna(subset=[coluna_observado, coluna_clim, coluna_modelo])
    anos = np.sort(d[coluna_ano].unique())
    if len(anos) == 0:
        return {'n_anos': 0, 'estimativa': None, 'ic95_inferior': None, 'ic95_superior': None,
                'conclusivo': False, 'n_replicacoes': n_replicacoes, 'seed': seed}

    mse_clim_total = mse(d[coluna_observado], d[coluna_clim])
    mse_modelo_total = mse(d[coluna_observado], d[coluna_modelo])
    estimativa = msess(mse_modelo_total, mse_clim_total)

    rng = np.random.RandomState(seed)
    replicas = []
    por_ano = {ano: d[d[coluna_ano] == ano] for ano in anos}
    for _ in range(n_replicacoes):
        anos_amostrados = rng.choice(anos, size=len(anos), replace=True)
        amostra = pd.concat([por_ano[a] for a in anos_amostrados], ignore_index=True)
        mse_clim_r = mse(amostra[coluna_observado], amostra[coluna_clim])
        mse_modelo_r = mse(amostra[coluna_observado], amostra[coluna_modelo])
        r = msess(mse_modelo_r, mse_clim_r)
        if r is not None:
            replicas.append(r)

    if not replicas:
        return {'n_anos': len(anos), 'estimativa': estimativa, 'ic95_inferior': None,
                'ic95_superior': None, 'conclusivo': False, 'n_replicacoes': n_replicacoes, 'seed': seed}

    ic_inf, ic_sup = np.percentile(replicas, [2.5, 97.5])
    conclusivo = not (ic_inf <= 0 <= ic_sup)
    return {'n_anos': len(anos), 'estimativa': estimativa,
            'ic95_inferior': round(float(ic_inf), 4), 'ic95_superior': round(float(ic_sup), 4),
            'conclusivo': bool(conclusivo), 'n_replicacoes': n_replicacoes, 'seed': seed}
