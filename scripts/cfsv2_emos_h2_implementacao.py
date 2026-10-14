#!/usr/bin/env python3
"""
cfsv2_emos_h2_implementacao.py — Fase 2C.3D: implementação real do EMOS
(Ensemble Model Output Statistics) para H2, Método 3.5, seguindo
ESTRITAMENTE o protocolo já aprovado em
`docs/nmme-fase2c3d-protocolo-emos-h2.md`. O protocolo não é alterado
nesta atividade, salvo STOP-ON-FAILURE explícito.

Distribuição: Normal censurada em zero (`Z ~ N(mu_latente, sigma²)`,
`Y = max(0,Z)`), ajustada por minimização do CRPS médio (fórmula
analítica fechada, seção 15 do protocolo) via
`scipy.optimize.minimize(method='L-BFGS-B')`, com `sigma > 0` garantido
algebricamente (`c = exp(gamma_c)`, `gamma_c ∈ [-20,20]`, `d >= 0`).

Escopo: só H2, avaliação principal expanding-window causal, regra
exigindo SIMULTANEAMENTE `init_date_treino < init_date_avaliada` E
`target_month_treino < init_date_avaliada` (reaproveitada literalmente
de `cfsv2_calibracao_mos_linear._indices_treino_causal` — mesma regra
causal, nunca uma terceira implementação paralela). Warm-up
`N_TREINO_MINIMO_EMOS = 120`.

EMOS completo (`theta=[a,b,gamma_c,d]`) e EMOS `d=0` (`theta_d0=
[a_d0,b_d0,gamma_c_d0]`) são ajustados de forma INDEPENDENTE a cada
data causal — nunca reaproveitando `a,b,c` de um no outro.

Roda com:
    python scripts/cfsv2_emos_h2_implementacao.py --executar
    python scripts/cfsv2_emos_h2_implementacao.py --gerar-relatorio
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import norm

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import cfsv2_calibracao_mos_linear as mos  # noqa: E402 — reaproveita _indices_treino_causal
import cfsv2_emos_h2_viabilidade_warmup as warm  # noqa: E402 — reaproveita _indice_causal_por_mes
import cfsv2_gate_calibracao_probabilistica as g  # noqa: E402
import cfsv2_validacao_cientifica as v  # noqa: E402

DIRETORIO_SAIDA = g.DIRETORIO_SAIDA
CAMINHO_TABELA_EXPANDING = DIRETORIO_SAIDA / 'emos_h2_expanding.csv'
CAMINHO_METRICAS_JSON = DIRETORIO_SAIDA / 'metricas_emos_h2_2c3d.json'
RELATORIO_PATH = ROOT / 'docs' / 'nmme-fase2c3d-emos-h2-resultados.md'

LEAD_H2 = 2
N_TREINO_MINIMO_EMOS = 120   # protocolo, seção 12 — pares válidos, nunca inicializações

# Protocolo, seção 10/16.1 — bound NUMÉRICO (nunca científico)
GAMMA_C_LO, GAMMA_C_HI = -20.0, 20.0

# Protocolo, seção 16.1 — inicialização determinística, igual para TODAS
# as datas causais e para os dois modelos.
THETA0_COMPLETO = np.array([0.0, 1.0, 0.0, 0.1])         # a, b, gamma_c, d
THETA0_D0 = np.array([0.0, 1.0, 0.0])                     # a_d0, b_d0, gamma_c_d0
BOUNDS_COMPLETO = [(None, None), (None, None), (GAMMA_C_LO, GAMMA_C_HI), (0.0, None)]
BOUNDS_D0 = [(None, None), (None, None), (GAMMA_C_LO, GAMMA_C_HI)]

# Protocolo, seção 16.2 — configuração fixada, mesma para todas as datas/modelos.
OPCOES_OTIMIZADOR = {'maxiter': 2000, 'ftol': 1e-10, 'gtol': 1e-6}

STATUS_OK = 'ok'
STATUS_WARMUP = 'warmup_amostra_insuficiente'
STATUS_PAR_INVALIDO = 'par_emos_invalido_para_linha_avaliada'
STATUS_NAO_CONVERGIU = 'otimizacao_nao_convergiu'
STATUS_INVALIDO = 'solucao_numericamente_invalida'


# ══════════════════════════════════════════════════════════════════════════
# Distribuição — Normal censurada em zero: UMA ÚNICA implementação para
# CDF, quantil, massa em zero, média censurada, CRPS e PIT (protocolo,
# seção 2/3/4/15/19 — nunca uma segunda fórmula paralela por métrica).
# ══════════════════════════════════════════════════════════════════════════

def _Phi(x):
    return norm.cdf(x)


def _phi(x):
    return norm.pdf(x)


def _Phi_inv(p):
    return norm.ppf(p)


def razao_k(mu_latente, sigma):
    return mu_latente / sigma


def prob_zero(mu_latente, sigma):
    """P(Y=0) = Phi(-k) = F_Y(0) — protocolo, seção 2/3, a MESMA
    quantidade em ambos os lugares."""
    return _Phi(-razao_k(mu_latente, sigma))


def media_preditiva_censurada(mu_latente, sigma):
    """E[Y] = mu_latente*Phi(k) + sigma*phi(k) — protocolo, seção 2/6.
    Sempre >= mu_latente (prova na seção 6 do protocolo)."""
    k = razao_k(mu_latente, sigma)
    return mu_latente * _Phi(k) + sigma * _phi(k)


def cdf_censurada(y, mu_latente, sigma):
    """F_Y única — protocolo, seção 3. Usada para tercis, intervalos,
    PIT e massa em zero — nunca recalculada à parte em nenhum lugar."""
    y = np.asarray(y, dtype=float)
    return np.where(y < 0, 0.0, _Phi((y - mu_latente) / sigma))


def quantil_censurado(p, mu_latente, sigma):
    """Q(p) único — protocolo, seção 4. Garantia algébrica Q(p)>=0
    demonstrada no protocolo (nunca só checada numericamente)."""
    p = np.asarray(p, dtype=float)
    pz = prob_zero(mu_latente, sigma)
    p_seguro = np.clip(p, 1e-300, 1 - 1e-16)
    return np.where(p <= pz, 0.0, mu_latente + sigma * _Phi_inv(p_seguro))


def mid_pit(y, mu_latente, sigma):
    """PIT único, mid-PIT determinístico (sem RNG) — protocolo, seção
    19: F_Y(y) se y>0, F_Y(0)/2 se y=0."""
    y = np.asarray(y, dtype=float)
    f0 = prob_zero(mu_latente, sigma)
    fy = cdf_censurada(y, mu_latente, sigma)
    return np.where(y > 0, fy, f0 / 2.0)


def _G(t):
    """Núcleo da fórmula fechada do CRPS — protocolo, seção 15."""
    t = np.asarray(t, dtype=float)
    return t * _Phi(t) ** 2 + 2 * _Phi(t) * _phi(t) - _Phi(np.sqrt(2) * t) / np.sqrt(np.pi)


def crps_normal_censurada(y, mu_latente, sigma):
    """CRPS analítico e determinístico — protocolo, seção 15 (fórmula
    fixada, validada numericamente contra integração direta — ver
    tests/test_cfsv2_emos_h2_implementacao.py::CrpsAnaliticoTestCase).
    Nunca Monte Carlo/amostral nesta função — é o núcleo da função
    objetivo do otimizador."""
    y = np.asarray(y, dtype=float)
    mu_latente = np.asarray(mu_latente, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    z = (y - mu_latente) / sigma
    a0 = -mu_latente / sigma
    return sigma * (_G(z) + _G(-z) - _G(a0))


# ══════════════════════════════════════════════════════════════════════════
# Construção da base causal H2 (reaproveita a validade estrutural já
# aprovada em cfsv2_emos_h2_viabilidade_warmup, estendida com os campos
# que a estimação real precisa: ensemble_mean/std, anom_ensemble,
# spread_relativo, tercis/anos_hist da climatologia observada).
# ══════════════════════════════════════════════════════════════════════════

def construir_pares_h2_emos(tabela_ensemble, base_enriquecida, obs_dict):
    sub = tabela_ensemble[tabela_ensemble['lead'] == LEAD_H2].copy()
    sub = sub.assign(_p=pd.PeriodIndex(sub['init_date'], freq='M')).sort_values('_p').reset_index(drop=True)

    clim_por_init = base_enriquecida[base_enriquecida['lead'] == LEAD_H2].drop_duplicates(
        'init_date').set_index('init_date')[['clim_media', 'clim_modelo_media']]

    calc_spread = warm._indice_causal_por_mes(tabela_ensemble, LEAD_H2, 'ensemble_std')
    calc_erro = warm._indice_causal_por_mes(tabela_ensemble, LEAD_H2, 'erro_assinado')

    linhas = []
    for _, row in sub.iterrows():
        init_date = row['init_date']
        mes_alvo = int(row['target_mes'])
        clim_modelo_raw = clim_por_init['clim_modelo_media'].get(init_date)
        clim_obs = clim_por_init['clim_media'].get(init_date)
        ensemble_mean = row['ensemble_mean']
        ensemble_std = row['ensemble_std']
        observacao = row['observacao']

        spread_hist = calc_spread(init_date)
        spread_clim_modelo_mes = float(spread_hist.mean()) if len(spread_hist) >= 1 else None
        erro_hist = calc_erro(init_date)
        erro_clim_sd_mes = float(erro_hist.std(ddof=1)) if len(erro_hist) >= 2 else None

        anom_ensemble = (float(ensemble_mean - clim_modelo_raw)
                          if pd.notna(clim_modelo_raw) and pd.notna(ensemble_mean) else None)
        spread_relativo = (float(ensemble_std / spread_clim_modelo_mes)
                             if (ensemble_std is not None and pd.notna(ensemble_std)
                                 and spread_clim_modelo_mes is not None and spread_clim_modelo_mes > 0)
                             else None)

        clim_terciles = v.climatologia_expansivel(mes_alvo, init_date, obs_dict)
        anos_hist = (np.array([obs_dict[(a, mes_alvo)] for a in clim_terciles['anos_usados']])
                     if clim_terciles['n_anos'] > 0 else np.array([]))

        valido = bool(
            pd.notna(clim_modelo_raw) and pd.notna(clim_obs)
            and anom_ensemble is not None
            and spread_clim_modelo_mes is not None and spread_clim_modelo_mes > 0
            and erro_clim_sd_mes is not None and erro_clim_sd_mes > 0
            and spread_relativo is not None
            and pd.notna(observacao)
        )

        linhas.append({
            'init_date': init_date, 'target_month': row['target_month'],
            'target_ano': int(row['target_ano']), 'target_mes': mes_alvo,
            'observacao': float(observacao) if pd.notna(observacao) else None,
            'ensemble_mean': float(ensemble_mean) if pd.notna(ensemble_mean) else None,
            'ensemble_std': (float(ensemble_std) if ensemble_std is not None
                              and pd.notna(ensemble_std) else None),
            'membros': row['membros'],
            'climatologia_modelo_raw': float(clim_modelo_raw) if pd.notna(clim_modelo_raw) else None,
            'climatologia_observada': float(clim_obs) if pd.notna(clim_obs) else None,
            'anom_ensemble': anom_ensemble,
            'spread_clim_modelo_mes': spread_clim_modelo_mes,
            'erro_clim_sd_mes': erro_clim_sd_mes,
            'spread_relativo': spread_relativo,
            'tercil_33': clim_terciles['tercil_33'], 'tercil_67': clim_terciles['tercil_67'],
            'anos_hist_climatologia': anos_hist,
            'valido': valido,
        })
    return pd.DataFrame(linhas)


# ══════════════════════════════════════════════════════════════════════════
# Ajuste — CRPS médio minimizado por L-BFGS-B (protocolo, seções 14/16)
# ══════════════════════════════════════════════════════════════════════════

def _objetivo_completo(theta, clim_obs_arr, anom_arr, erro_sd_arr, spread_rel_arr, y_arr):
    a, b, gamma_c, d = theta
    mu_latente = clim_obs_arr + a + b * anom_arr
    c = np.exp(gamma_c)
    sigma = erro_sd_arr * np.sqrt(c + d * spread_rel_arr ** 2)
    with np.errstate(invalid='ignore', divide='ignore'):
        crps = crps_normal_censurada(y_arr, mu_latente, sigma)
    if not np.all(np.isfinite(crps)):
        return np.inf
    return float(np.mean(crps))


def _objetivo_d0(theta_d0, clim_obs_arr, anom_arr, erro_sd_arr, y_arr):
    a_d0, b_d0, gamma_c_d0 = theta_d0
    mu_latente = clim_obs_arr + a_d0 + b_d0 * anom_arr
    c_d0 = np.exp(gamma_c_d0)
    sigma = erro_sd_arr * np.sqrt(c_d0)
    with np.errstate(invalid='ignore', divide='ignore'):
        crps = crps_normal_censurada(y_arr, mu_latente, sigma)
    if not np.all(np.isfinite(crps)):
        return np.inf
    return float(np.mean(crps))


def ajustar_emos_completo(clim_obs_arr, anom_arr, erro_sd_arr, spread_rel_arr, y_arr):
    res = minimize(_objetivo_completo, THETA0_COMPLETO,
                    args=(clim_obs_arr, anom_arr, erro_sd_arr, spread_rel_arr, y_arr),
                    method='L-BFGS-B', bounds=BOUNDS_COMPLETO, options=OPCOES_OTIMIZADOR)
    return res


def ajustar_emos_d0(clim_obs_arr, anom_arr, erro_sd_arr, y_arr):
    res = minimize(_objetivo_d0, THETA0_D0,
                    args=(clim_obs_arr, anom_arr, erro_sd_arr, y_arr),
                    method='L-BFGS-B', bounds=BOUNDS_D0, options=OPCOES_OTIMIZADOR)
    return res


def _sanidade_completo(theta, erro_sd_arr, spread_rel_arr, crps_final):
    """Protocolo, seção 16.5 — as 6 condições de sanidade, incluindo a
    sexta (`o CRPS objetivo final é finito`), que a auditoria externa
    identificou como ausente desta função até esta revisão: `crps_final`
    é `res.fun` (o valor da função objetivo na solução), nunca o CRPS
    retrospectivo da linha avaliada (que é uma quantidade separada,
    fora de amostra, e não decide a sanidade do AJUSTE em si)."""
    a, b, gamma_c, d = theta
    if not np.all(np.isfinite(theta)):
        return False
    if not (GAMMA_C_LO <= gamma_c <= GAMMA_C_HI):
        return False
    if d < 0:
        return False
    c = np.exp(gamma_c)
    if not (c > 0) or not np.isfinite(c):
        return False
    sigma = erro_sd_arr * np.sqrt(c + d * spread_rel_arr ** 2)
    if not np.all(np.isfinite(sigma)) or np.any(sigma <= 0):
        return False
    if not np.isfinite(crps_final):
        return False
    return True


def _sanidade_d0(theta_d0, erro_sd_arr, crps_final):
    """Protocolo, seção 16.5 — mesmas 6 condições, versão restrita
    (sem `d`)."""
    a_d0, b_d0, gamma_c_d0 = theta_d0
    if not np.all(np.isfinite(theta_d0)):
        return False
    if not (GAMMA_C_LO <= gamma_c_d0 <= GAMMA_C_HI):
        return False
    c_d0 = np.exp(gamma_c_d0)
    if not (c_d0 > 0) or not np.isfinite(c_d0):
        return False
    sigma = erro_sd_arr * np.sqrt(c_d0)
    if not np.all(np.isfinite(sigma)) or np.any(sigma <= 0):
        return False
    if not np.isfinite(crps_final):
        return False
    return True


def _sanidade_linha_avaliada(mu_latente, sigma, prob_zero_v, media_censurada_v, mediana_v, crps_v):
    """Protocolo, seção 16.5 — a sanidade numérica não pode se limitar
    às linhas de TREINO: a própria linha avaliada (fora de amostra)
    também precisa ter sigma>0 finito e todos os campos probabilísticos
    derivados finitos. Identificado pela auditoria externa como
    ausente (a implementação original só verificava as linhas de
    treino, nunca a avaliada)."""
    valores = (mu_latente, sigma, prob_zero_v, media_censurada_v, mediana_v, crps_v)
    if not all(np.isfinite(v_) for v_ in valores):
        return False
    if sigma <= 0:
        return False
    return True


# ══════════════════════════════════════════════════════════════════════════
# Tabela expanding — treino causal (reaproveita mos._indices_treino_causal)
# ══════════════════════════════════════════════════════════════════════════

def construir_emos_h2_expanding(pares):
    pares = pares.assign(_p=pd.PeriodIndex(pares['init_date'], freq='M')).sort_values('_p')
    linhas = []

    (clim_obs_hist, anom_hist, erro_sd_hist, spread_rel_hist, y_hist,
     inits_hist_p, targets_hist_p) = [], [], [], [], [], [], []

    for _, row in pares.iterrows():
        avaliada_p = v._periodo(row['init_date'])
        idx_treino = mos._indices_treino_causal(inits_hist_p, targets_hist_p, avaliada_p)
        n_treino_emos = len(idx_treino)

        linha = {
            'init_date': row['init_date'], 'target_month': row['target_month'],
            'target_ano': row['target_ano'], 'target_mes': row['target_mes'],
            'observacao': row['observacao'], 'ensemble_mean': row['ensemble_mean'],
            'ensemble_std': row['ensemble_std'], 'membros': row['membros'],
            'climatologia_modelo_raw': row['climatologia_modelo_raw'],
            'climatologia_observada': row['climatologia_observada'],
            'anom_ensemble': row['anom_ensemble'],
            'spread_clim_modelo_mes': row['spread_clim_modelo_mes'],
            'spread_relativo': row['spread_relativo'],
            'erro_clim_sd_mes': row['erro_clim_sd_mes'],
            'tercil_33': row['tercil_33'], 'tercil_67': row['tercil_67'],
            'n_treino_emos': n_treino_emos,
            'max_init_date_treino': None, 'max_target_month_treino': None,
            'a': None, 'b': None, 'gamma_c': None, 'c': None, 'd': None,
            'mu_latente': None, 'sigma': None, 'prob_zero': None,
            'media_preditiva_censurada': None, 'mediana_preditiva': None, 'crps_emos': None,
            'a_d0': None, 'b_d0': None, 'gamma_c_d0': None, 'c_d0': None,
            'mu_latente_d0': None, 'sigma_d0': None, 'crps_d0': None,
            'success_completo': None, 'status_opt_completo': None, 'message_completo': None,
            'nit_completo': None, 'nfev_completo': None, 'crps_final_treino_completo': None,
            'success_d0': None, 'status_opt_d0': None, 'message_d0': None,
            'nit_d0': None, 'nfev_d0': None, 'crps_final_treino_d0': None,
            'crps_raw': None, 'crps_climatologia': None,
            'status_emos_completo': None, 'status_emos_d0': None, 'status_emos': None,
        }

        if not row['valido']:
            linha['status_emos'] = STATUS_PAR_INVALIDO
        elif n_treino_emos < N_TREINO_MINIMO_EMOS:
            linha['status_emos'] = STATUS_WARMUP
        else:
            idx_arr = np.array(idx_treino)
            clim_obs_t = np.array(clim_obs_hist)[idx_arr]
            anom_t = np.array(anom_hist)[idx_arr]
            erro_sd_t = np.array(erro_sd_hist)[idx_arr]
            spread_rel_t = np.array(spread_rel_hist)[idx_arr]
            y_t = np.array(y_hist)[idx_arr]
            inits_t = [inits_hist_p[i] for i in idx_treino]
            targets_t = [targets_hist_p[i] for i in idx_treino]
            linha['max_init_date_treino'] = str(max(inits_t))
            linha['max_target_month_treino'] = str(max(targets_t))

            res_completo = ajustar_emos_completo(clim_obs_t, anom_t, erro_sd_t, spread_rel_t, y_t)
            res_d0 = ajustar_emos_d0(clim_obs_t, anom_t, erro_sd_t, y_t)

            # crps_final_treino_* = res.fun — o valor da função objetivo
            # (CRPS médio sobre a janela de TREINO) na solução retornada
            # pelo otimizador. Registrado para TODO ajuste, mesmo quando
            # success=False (protocolo, seção 16.4) — nunca confundido
            # com crps_emos/crps_d0 abaixo, que são o CRPS calculado
            # retrospectivamente sobre a ÚNICA observação AVALIADA
            # (fora de amostra, não é o que o otimizador minimizou).
            crps_final_treino_completo = float(res_completo.fun)
            crps_final_treino_d0 = float(res_d0.fun)

            linha['success_completo'] = bool(res_completo.success)
            linha['status_opt_completo'] = int(res_completo.status)
            linha['message_completo'] = str(res_completo.message)
            linha['nit_completo'] = int(res_completo.nit)
            linha['nfev_completo'] = int(res_completo.nfev)
            linha['crps_final_treino_completo'] = crps_final_treino_completo

            linha['success_d0'] = bool(res_d0.success)
            linha['status_opt_d0'] = int(res_d0.status)
            linha['message_d0'] = str(res_d0.message)
            linha['nit_d0'] = int(res_d0.nit)
            linha['nfev_d0'] = int(res_d0.nfev)
            linha['crps_final_treino_d0'] = crps_final_treino_d0

            if not res_completo.success:
                linha['status_emos_completo'] = STATUS_NAO_CONVERGIU
            elif not _sanidade_completo(res_completo.x, erro_sd_t, spread_rel_t,
                                         crps_final_treino_completo):
                linha['status_emos_completo'] = STATUS_INVALIDO
            else:
                a, b, gamma_c, d = res_completo.x
                c = float(np.exp(gamma_c))
                mu_latente = float(row['climatologia_observada'] + a + b * row['anom_ensemble'])
                sigma = float(row['erro_clim_sd_mes'] * np.sqrt(c + d * row['spread_relativo'] ** 2))
                prob_zero_v = float(prob_zero(mu_latente, sigma))
                media_censurada_v = float(media_preditiva_censurada(mu_latente, sigma))
                mediana_v = float(quantil_censurado(0.5, mu_latente, sigma))
                crps_emos_v = float(crps_normal_censurada(row['observacao'], mu_latente, sigma))
                # sanidade numérica da PRÓPRIA LINHA AVALIADA (fora de
                # amostra) — distinta da sanidade do ajuste sobre o
                # treino acima; a auditoria externa identificou que a
                # implementação original só verificava as linhas de
                # treino, nunca esta.
                if not _sanidade_linha_avaliada(mu_latente, sigma, prob_zero_v, media_censurada_v,
                                                 mediana_v, crps_emos_v):
                    linha['status_emos_completo'] = STATUS_INVALIDO
                else:
                    linha['status_emos_completo'] = STATUS_OK
                    linha.update({
                        'a': float(a), 'b': float(b), 'gamma_c': float(gamma_c), 'c': c,
                        'd': float(d), 'mu_latente': mu_latente, 'sigma': sigma,
                        'prob_zero': prob_zero_v, 'media_preditiva_censurada': media_censurada_v,
                        'mediana_preditiva': mediana_v, 'crps_emos': crps_emos_v,
                    })

            if not res_d0.success:
                linha['status_emos_d0'] = STATUS_NAO_CONVERGIU
            elif not _sanidade_d0(res_d0.x, erro_sd_t, crps_final_treino_d0):
                linha['status_emos_d0'] = STATUS_INVALIDO
            else:
                a_d0, b_d0, gamma_c_d0 = res_d0.x
                c_d0 = float(np.exp(gamma_c_d0))
                mu_latente_d0 = float(row['climatologia_observada'] + a_d0 + b_d0 * row['anom_ensemble'])
                sigma_d0 = float(row['erro_clim_sd_mes'] * np.sqrt(c_d0))
                prob_zero_d0_v = float(prob_zero(mu_latente_d0, sigma_d0))
                media_censurada_d0_v = float(media_preditiva_censurada(mu_latente_d0, sigma_d0))
                mediana_d0_v = float(quantil_censurado(0.5, mu_latente_d0, sigma_d0))
                crps_d0_v = float(crps_normal_censurada(row['observacao'], mu_latente_d0, sigma_d0))
                if not _sanidade_linha_avaliada(mu_latente_d0, sigma_d0, prob_zero_d0_v,
                                                 media_censurada_d0_v, mediana_d0_v, crps_d0_v):
                    linha['status_emos_d0'] = STATUS_INVALIDO
                else:
                    linha['status_emos_d0'] = STATUS_OK
                    linha.update({
                        'a_d0': float(a_d0), 'b_d0': float(b_d0), 'gamma_c_d0': float(gamma_c_d0),
                        'c_d0': c_d0, 'mu_latente_d0': mu_latente_d0, 'sigma_d0': sigma_d0,
                        'crps_d0': crps_d0_v,
                    })

            if linha['status_emos_completo'] == STATUS_OK and linha['status_emos_d0'] == STATUS_OK:
                linha['status_emos'] = STATUS_OK
                linha['crps_raw'] = float(v.crps_amostral(row['membros'], row['observacao']))
                linha['crps_climatologia'] = (
                    float(v.crps_amostral(row['anos_hist_climatologia'], row['observacao']))
                    if len(row['anos_hist_climatologia']) >= 2 else None)
            else:
                # prioridade de rótulo: não-convergência antes de inválido,
                # completo antes de d0 — nunca escondido, os dois campos
                # individuais acima já registram a causa exata de cada modelo.
                for candidato in (STATUS_NAO_CONVERGIU, STATUS_INVALIDO):
                    if linha['status_emos_completo'] == candidato or linha['status_emos_d0'] == candidato:
                        linha['status_emos'] = candidato
                        break

        linhas.append(linha)

        if row['valido']:
            clim_obs_hist.append(row['climatologia_observada'])
            anom_hist.append(row['anom_ensemble'])
            erro_sd_hist.append(row['erro_clim_sd_mes'])
            spread_rel_hist.append(row['spread_relativo'])
            y_hist.append(row['observacao'])
            inits_hist_p.append(avaliada_p)
            targets_hist_p.append(v._periodo(row['target_month']))

    tabela = pd.DataFrame(linhas)
    tabela = tabela.assign(_p=pd.PeriodIndex(tabela['init_date'], freq='M')).sort_values(
        '_p').drop(columns='_p').reset_index(drop=True)
    return tabela


# ══════════════════════════════════════════════════════════════════════════
# Auditorias defensivas — STOP-ON-FAILURE
# ══════════════════════════════════════════════════════════════════════════

def _verificar_nenhum_leakage(tabela):
    problemas = []
    ok = tabela[tabela['status_emos'] == STATUS_OK]
    for _, row in ok.iterrows():
        avaliada_p = v._periodo(row['init_date'])
        if row['max_target_month_treino'] is None:
            problemas.append(f"{row['init_date']}: status=ok mas max_target_month_treino ausente")
            continue
        if not (v._periodo(row['max_target_month_treino']) < avaliada_p):
            problemas.append(f"{row['init_date']}: max_target_month_treino="
                              f"{row['max_target_month_treino']} >= init_date avaliada")
        if not (v._periodo(row['max_init_date_treino']) < avaliada_p):
            problemas.append(f"{row['init_date']}: max_init_date_treino="
                              f"{row['max_init_date_treino']} >= init_date avaliada")
    return {'ok': len(problemas) == 0, 'n_problemas': len(problemas), 'problemas': problemas[:20]}


def _verificar_falhas_de_convergencia(tabela):
    falhas = tabela[tabela['status_emos'].isin((STATUS_NAO_CONVERGIU, STATUS_INVALIDO))]
    return {'ok': len(falhas) == 0, 'n_falhas': int(len(falhas)),
            'datas': falhas['init_date'].tolist()[:20]}


# ══════════════════════════════════════════════════════════════════════════
# Bootstrap (protocolo, seção 21 — sem refit, blocos por target_ano)
# ══════════════════════════════════════════════════════════════════════════

def bootstrap_crpss_por_target_ano(tabela_ok, n_resamples=500, seed=20261001):
    """Protocolo, seção 21 — bootstrap em blocos por `target_ano`, SEM
    refit (reamostra só os forecasts já produzidos pela sequência
    causal expanding). Auditoria externa, item 4 — rastreabilidade
    explícita: cada reamostra sorteia os anos UMA VEZ e usa o MESMO
    `amostra` resultante para as 5 métricas (`_crpss` sempre lê os
    dois lados — modelo e referência — da mesma `amostra`, nunca de
    sorteios separados), e o número de reamostras EFETIVAMENTE usadas
    por métrica é contado e comparado a `n_resamples` — uma reamostra
    só seria descartada de uma métrica se `crps_ref==0` nela (nunca
    observado com CRPS real de precipitação, mas verificado, nunca
    assumido)."""
    rng = np.random.default_rng(seed)
    anos = np.array(sorted(tabela_ok['target_ano'].unique()))
    por_ano = {ano: tabela_ok[tabela_ok['target_ano'] == ano] for ano in anos}

    def _crpss(amostra, crps_mod_col, crps_ref_col):
        crps_mod = amostra[crps_mod_col].mean()
        crps_ref = amostra[crps_ref_col].mean()
        return float(1 - crps_mod / crps_ref) if crps_ref else None

    boot_vs_raw, boot_vs_clim, boot_spread_dinamico, boot_d0_vs_raw, boot_d0_vs_clim = [], [], [], [], []
    for _ in range(n_resamples):
        anos_sorteados = rng.choice(anos, size=len(anos), replace=True)
        amostra = pd.concat([por_ano[a] for a in anos_sorteados], ignore_index=True)
        v1 = _crpss(amostra, 'crps_emos', 'crps_raw')
        v2 = _crpss(amostra, 'crps_emos', 'crps_climatologia')
        v3 = _crpss(amostra, 'crps_emos', 'crps_d0')
        v4 = _crpss(amostra, 'crps_d0', 'crps_raw')
        v5 = _crpss(amostra, 'crps_d0', 'crps_climatologia')
        if v1 is not None:
            boot_vs_raw.append(v1)
        if v2 is not None:
            boot_vs_clim.append(v2)
        if v3 is not None:
            boot_spread_dinamico.append(v3)
        if v4 is not None:
            boot_d0_vs_raw.append(v4)
        if v5 is not None:
            boot_d0_vs_clim.append(v5)

    pontual_vs_raw = _crpss(tabela_ok, 'crps_emos', 'crps_raw')
    pontual_vs_clim = _crpss(tabela_ok, 'crps_emos', 'crps_climatologia')
    pontual_spread_dinamico = _crpss(tabela_ok, 'crps_emos', 'crps_d0')
    pontual_d0_vs_raw = _crpss(tabela_ok, 'crps_d0', 'crps_raw')
    pontual_d0_vs_clim = _crpss(tabela_ok, 'crps_d0', 'crps_climatologia')

    listas_boot = {
        'CRPSS_vs_raw': boot_vs_raw, 'CRPSS_vs_climatologia': boot_vs_clim,
        'CRPSS_spread_dinamico': boot_spread_dinamico,
        'CRPSS_d0_vs_raw': boot_d0_vs_raw, 'CRPSS_d0_vs_climatologia': boot_d0_vs_clim,
    }
    n_efetivos_por_metrica = {nome: len(lst) for nome, lst in listas_boot.items()}
    nenhuma_reamostra_descartada = all(n == n_resamples for n in n_efetivos_por_metrica.values())

    def _rotulo(nome, pontual, boot):
        r = v._resumo_bootstrap(pontual, boot)
        r['ic_classificacao'] = v._classificar_ic_relativo_a_zero(r['ic95_lo'], r['ic95_hi'])
        r['metrica'] = nome
        # precisão explícita adicional — distingue um ganho EXATAMENTE
        # nulo (ou algebricamente garantido perto de zero, como quando
        # d converge a 0 em toda a amostra) de um ganho numericamente
        # muito pequeno mas não-nulo (auditoria externa, item 4).
        r['estimativa_notacao_cientifica'] = f'{pontual:.6e}' if pontual is not None else None
        r['n_resamples_efetivos'] = n_efetivos_por_metrica[nome]
        return r

    return {
        'n_anos_distintos': int(len(anos)), 'n_resamples': n_resamples, 'seed': seed,
        'metodo': 'bootstrap em blocos por target_ano, sem refit — EMOS completo/d0/RAW/'
                  'climatologia usam os MESMOS blocos de ano sorteados em cada reamostra',
        'nenhuma_reamostra_descartada': nenhuma_reamostra_descartada,
        'n_resamples_efetivos_por_metrica': n_efetivos_por_metrica,
        'CRPSS_vs_raw': _rotulo('CRPSS_vs_raw', pontual_vs_raw, boot_vs_raw),
        'CRPSS_vs_climatologia': _rotulo('CRPSS_vs_climatologia', pontual_vs_clim, boot_vs_clim),
        'CRPSS_spread_dinamico': _rotulo('CRPSS_spread_dinamico', pontual_spread_dinamico,
                                          boot_spread_dinamico),
        'CRPSS_d0_vs_raw': _rotulo('CRPSS_d0_vs_raw', pontual_d0_vs_raw, boot_d0_vs_raw),
        'CRPSS_d0_vs_climatologia': _rotulo('CRPSS_d0_vs_climatologia', pontual_d0_vs_clim,
                                             boot_d0_vs_clim),
    }


# ══════════════════════════════════════════════════════════════════════════
# Métricas determinísticas — tercis, Brier/BSS, cobertura, PIT, bias
# ══════════════════════════════════════════════════════════════════════════

def _probabilidades_tercil(mu_latente, sigma, t33, t67):
    """Protocolo, seção 19 — P(seco)=F_Y(t33), P(umido)=1-F_Y(t67),
    P(normal)=1-P(seco)-P(umido); nunca complementos independentes."""
    p_seco = float(cdf_censurada(t33, mu_latente, sigma))
    p_umido = float(1.0 - cdf_censurada(t67, mu_latente, sigma))
    p_normal = 1.0 - p_seco - p_umido
    return p_seco, p_normal, p_umido


def metricas_tercil_brier(tabela_ok):
    probs = {'seco': [], 'normal': [], 'umido': []}
    obs_ind = {'seco': [], 'normal': [], 'umido': []}
    for _, row in tabela_ok.iterrows():
        t33, t67 = row['tercil_33'], row['tercil_67']
        p_seco, p_normal, p_umido = _probabilidades_tercil(row['mu_latente'], row['sigma'], t33, t67)
        cat_obs = v.categoria_tercil(row['observacao'], t33, t67)
        probs['seco'].append(p_seco); probs['normal'].append(p_normal); probs['umido'].append(p_umido)
        for cat in ('seco', 'normal', 'umido'):
            obs_ind[cat].append(1.0 if cat_obs == cat else 0.0)

    bs, bss, bs_ref = {}, {}, {}
    soma_probs = np.array(probs['seco']) + np.array(probs['normal']) + np.array(probs['umido'])
    for cat in ('seco', 'normal', 'umido'):
        p = np.array(probs[cat]); o = np.array(obs_ind[cat])
        bs[cat] = float(np.mean((p - o) ** 2))
        bs_ref_nom = float(np.mean((1 / 3 - o) ** 2))
        bs_ref[cat] = bs_ref_nom
        bss[cat] = float(1 - bs[cat] / bs_ref_nom) if bs_ref_nom > 0 else None
    return {
        'brier_score_por_categoria': bs,
        'brier_referencia_nominal_por_categoria': bs_ref,
        'bss_por_categoria': bss,
        'verificacao_probabilidades_somam_um': {
            'max_desvio_abs': float(np.max(np.abs(soma_probs - 1.0))),
            'ok': bool(np.max(np.abs(soma_probs - 1.0)) < 1e-9),
        },
    }


def metricas_cobertura_intervalos(tabela_ok):
    niveis = {50: (25, 75), 80: (10, 90), 90: (5, 95)}
    resultado = {}
    obs = tabela_ok['observacao'].values
    mu = tabela_ok['mu_latente'].values
    sig = tabela_ok['sigma'].values
    for nivel, (p_lo, p_hi) in niveis.items():
        lo = quantil_censurado(p_lo / 100, mu, sig)
        hi = quantil_censurado(p_hi / 100, mu, sig)
        dentro = (obs >= lo) & (obs <= hi)
        resultado[nivel] = {
            'cobertura_empirica': float(np.mean(dentro)),
            'cobertura_nominal': nivel / 100,
            'largura_media': float(np.mean(hi - lo)),
        }
    return resultado


def metricas_cobertura_raw(tabela_ok):
    """Cobertura empírica do ensemble RAW (percentis dos 24 membros,
    mesma convenção já usada no gate — `_INTERVALOS_NOMINAIS`), nos
    MESMOS 95 casos do EMOS — protocolo, seção 19/20: comparação
    principal de calibração é contra o RAW."""
    niveis = g._INTERVALOS_NOMINAIS
    resultado = {}
    for nivel, (p_lo, p_hi) in niveis.items():
        dentro, larguras = [], []
        for membros, obs in zip(tabela_ok['membros'], tabela_ok['observacao']):
            lo = np.percentile(membros, p_lo)
            hi = np.percentile(membros, p_hi)
            dentro.append(1.0 if lo <= obs <= hi else 0.0)
            larguras.append(float(hi - lo))
        resultado[nivel] = {
            'cobertura_empirica': float(np.mean(dentro)), 'cobertura_nominal': nivel / 100,
            'largura_media': float(np.mean(larguras)),
        }
    return resultado


def metricas_pit(tabela_ok):
    """Protocolo, seção 19 — mid-PIT. Auditoria externa, item 3 —
    acrescenta a concentração no último decil (`[0.9,1.0]`) e uma nota
    explícita de limitação: como a distribuição é MISTA (massa
    discreta em `Y=0` via `F_Y(0)/2`, seção 19 do protocolo), o PIT
    nunca pode ser comparado à uniforme contínua do mesmo jeito que
    numa distribuição puramente contínua — valores de PIT abaixo de
    `F_Y(0)` nunca ocorrem por construção (a massa em `Y=0` é mapeada
    toda para o ponto único `F_Y(0)/2`, não distribuída no intervalo
    `[0, F_Y(0)]`), então um histograma de PIT desta família SEMPRE
    terá uma concentração artificial no bin que contém `F_Y(0)/2`
    mesmo sob calibração perfeita — isso não é, por si só, evidência
    de mau ajuste."""
    pit = mid_pit(tabela_ok['observacao'].values, tabela_ok['mu_latente'].values,
                   tabela_ok['sigma'].values)
    bins = np.linspace(0, 1, 11)
    contagens, _ = np.histogram(pit, bins=bins)
    n = int(len(pit))
    n_ultimo_decil = int(contagens[-1])
    return {
        'media': float(np.mean(pit)), 'variancia': float(np.var(pit)),
        'bins': [float(b) for b in bins],
        'contagens_por_bin': [int(c) for c in contagens],
        'n': n,
        'n_ultimo_decil': n_ultimo_decil,
        'fracao_ultimo_decil': float(n_ultimo_decil / n) if n else None,
        'fracao_ultimo_decil_esperada_sob_uniformidade': 0.1,
        'nota_limitacao': ('PIT de distribuição MISTA (massa discreta em Y=0) não é comparável '
                            'à uniforme contínua do mesmo jeito que um PIT de distribuição '
                            'puramente contínua — a massa em Y=0 concentra-se no ponto único '
                            'F_Y(0)/2 em vez de se espalhar pelo intervalo [0, F_Y(0)], então '
                            'algum desvio da uniformidade é estruturalmente esperado mesmo sob '
                            'calibração perfeita. Nunca usado como critério único de aprovação '
                            '(protocolo, seção 19, último parágrafo).'),
    }


def metricas_bias(tabela_ok):
    obs = tabela_ok['observacao'].values
    mu = tabela_ok['mu_latente'].values
    e_y = tabela_ok['media_preditiva_censurada'].values
    return {
        'bias_mu_latente': float(np.mean(mu - obs)),
        'bias_media_preditiva_censurada': float(np.mean(e_y - obs)),
        'nota': 'bias_media_preditiva_censurada (usa E[Y]) é a métrica PRINCIPAL de bias da '
                'previsão final — bias_mu_latente é só diagnóstico do parâmetro latente '
                '(protocolo, seção 19).',
    }


def _stats_resumo(serie):
    s = np.asarray(serie, dtype=float)
    s = s[np.isfinite(s)]
    if len(s) == 0:
        return {'n': 0}
    return {'n': int(len(s)), 'minimo': float(s.min()), 'p10': float(np.percentile(s, 10)),
            'mediana': float(np.median(s)), 'media': float(s.mean()),
            'p90': float(np.percentile(s, 90)), 'maximo': float(s.max())}


def diagnostico_parametros(tabela_ok):
    campos = ['a', 'b', 'c', 'd', 'a_d0', 'b_d0', 'c_d0']
    resultado = {campo: _stats_resumo(tabela_ok[campo]) for campo in campos}
    resultado['destaques'] = {
        'n_d_proximo_de_zero': int((tabela_ok['d'].abs() < 1e-6).sum()),
        'n_d_no_bound_inferior': int((tabela_ok['d'] <= 1e-12).sum()),
        'n_gamma_c_no_bound': int(((tabela_ok['gamma_c'] <= GAMMA_C_LO + 1e-9)
                                    | (tabela_ok['gamma_c'] >= GAMMA_C_HI - 1e-9)).sum()),
        'n_gamma_c_d0_no_bound': int(((tabela_ok['gamma_c_d0'] <= GAMMA_C_LO + 1e-9)
                                       | (tabela_ok['gamma_c_d0'] >= GAMMA_C_HI - 1e-9)).sum()),
        'n_b_negativo': int((tabela_ok['b'] < 0).sum()),
        'n_b_d0_negativo': int((tabela_ok['b_d0'] < 0).sum()),
    }
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# Orquestração
# ══════════════════════════════════════════════════════════════════════════

def executar_emos_h2(n_resamples_bootstrap=500):
    auditoria = v.executar_auditoria()
    if not auditoria['auditoria_aprovada']:
        return {'STOP_ON_FAILURE': True, 'motivo': 'auditoria da base RAW (2C.3C) reprovada'}, None

    df_raw = v.carregar_cfsv2_raw()
    chirps_df = v.carregar_chirps_v3_historico()
    base = v.construir_base_pareada(df_raw, chirps_df)
    if not v.validar_nenhum_mes_alvo_ausente(base):
        return {'STOP_ON_FAILURE': True, 'motivo': 'pareamento com mês-alvo ausente'}, None

    tabela_ensemble = g.construir_tabela_ensemble(base)
    auditoria_membros = g._verificar_24_membros(tabela_ensemble)
    if not auditoria_membros['ok']:
        return {'STOP_ON_FAILURE': True, 'motivo': 'auditoria de 24 membros reprovada'}, None

    base_enriquecida = v._enriquecer_com_climatologia(base, chirps_df)
    obs_dict = v._obs_dict(chirps_df)

    pares = construir_pares_h2_emos(tabela_ensemble, base_enriquecida, obs_dict)
    tabela = construir_emos_h2_expanding(pares)

    leakage = _verificar_nenhum_leakage(tabela)
    if not leakage['ok']:
        return {'STOP_ON_FAILURE': True, 'motivo': 'leakage observacional detectado',
                'detalhe': leakage}, tabela

    convergencia = _verificar_falhas_de_convergencia(tabela)
    if not convergencia['ok']:
        return {'STOP_ON_FAILURE': True,
                'motivo': 'falha de convergência/sanidade do otimizador em pelo menos uma data '
                          '— nenhum CRPS/skill calculado antes desta checagem (protocolo, '
                          'seção 13/16.4/16.5)',
                'detalhe': convergencia}, tabela

    tabela_ok = tabela[tabela['status_emos'] == STATUS_OK].copy()
    n_final = len(tabela_ok)

    chaves_ok = {'n_final': n_final, 'esperado_estrutural': 95,
                 'bate_com_esperado': n_final == 95}
    if n_final == 0:
        return {'STOP_ON_FAILURE': True, 'motivo': 'nenhuma previsão avaliável — N=0'}, tabela

    # benchmarks precisam estar disponíveis em TODOS os casos OK (item 13)
    if tabela_ok['crps_raw'].isna().any() or tabela_ok['crps_climatologia'].isna().any():
        return {'STOP_ON_FAILURE': True,
                'motivo': 'benchmark RAW/climatologia ausente em algum caso avaliável — '
                          'amostras precisam ser idênticas (protocolo, seção 13)'}, tabela

    nan_inf_check = {
        'ok': bool(np.isfinite(tabela_ok[['crps_emos', 'crps_d0', 'crps_raw',
                                           'crps_climatologia']].values).all()),
    }
    if not nan_inf_check['ok']:
        return {'STOP_ON_FAILURE': True, 'motivo': 'NaN/Inf inesperado em CRPS calculado'}, tabela

    boot = bootstrap_crpss_por_target_ano(tabela_ok, n_resamples_bootstrap)
    if not boot['nenhuma_reamostra_descartada']:
        return {'STOP_ON_FAILURE': True,
                'motivo': 'alguma reamostra do bootstrap foi descartada silenciosamente em pelo '
                          'menos uma métrica (auditoria externa, item 4) — nunca esperado com '
                          'CRPS real de precipitação',
                'detalhe': boot['n_resamples_efetivos_por_metrica']}, tabela

    tercil = metricas_tercil_brier(tabela_ok)
    if not tercil['verificacao_probabilidades_somam_um']['ok']:
        return {'STOP_ON_FAILURE': True,
                'motivo': 'probabilidades de tercil não somam 1 em algum caso',
                'detalhe': tercil['verificacao_probabilidades_somam_um']}, tabela

    cobertura = metricas_cobertura_intervalos(tabela_ok)
    cobertura_raw = metricas_cobertura_raw(tabela_ok)
    pit = metricas_pit(tabela_ok)
    bias = metricas_bias(tabela_ok)
    diagnostico = diagnostico_parametros(tabela_ok)
    crps_final_treino_resumo = {
        'completo': _stats_resumo(tabela_ok['crps_final_treino_completo']),
        'd0': _stats_resumo(tabela_ok['crps_final_treino_d0']),
        'nota': ('res.fun na solução — CRPS médio sobre a JANELA DE TREINO efetivamente '
                 'minimizada em cada data causal, distinto de crps_emos/crps_d0 (CRPS '
                 'retrospectivo da única observação avaliada, fora de amostra).'),
    }

    # Critério de aprovação pré-registrado (protocolo, seção 20) —
    # mantido integralmente, nunca alterado após ver os resultados.
    cond1 = boot['CRPSS_spread_dinamico']['ic_classificacao'] == 'ic_totalmente_acima_de_zero'
    cond2 = boot['CRPSS_vs_climatologia']['ic_classificacao'] == 'ic_totalmente_acima_de_zero'

    # Critério 3 — "ausência de degradação grave de Brier/BSS" (protocolo,
    # seção 20, item 3) não define um limiar numérico. A implementação usa
    # BSS > -0.10 como limiar operacional — mas esse limiar foi introduzido
    # NESTA implementação (mesmo commit que produziu os primeiros resultados
    # reais), não existe um artefato de pré-registro datado e independente
    # que o fixasse ANTES de qualquer ajuste real do EMOS H2. Auditoria
    # externa (2ª rodada) — correto NÃO afirmar que o limiar foi
    # pré-registrado sem essa evidência documental verificável. Por isso o
    # critério 3 é reportado como DIAGNÓSTICO condicionado a um limiar não
    # pré-registrado (`criterio_3_classificacao`), nunca como aprovação
    # certificada — o valor calculado (`cond3`) é preservado sem alteração
    # para rastreabilidade (`criterio_3_bss_dentro_do_limiar_calculado`).
    # BSS mede a fração de melhora/degradação do Brier Score em relação à
    # referência nominal (BSS = 1 - BS/BS_ref); o valor observado mais
    # próximo do limiar é úmido = -0.0898, um caso LIMÍTROFE.
    LIMIAR_BSS_DEGRADACAO_GRAVE = -0.10
    bss_vals = [val for val in tercil['bss_por_categoria'].values() if val is not None]
    cond3 = all(val > LIMIAR_BSS_DEGRADACAO_GRAVE for val in bss_vals) if bss_vals else False

    # Critério 4 — o protocolo (seção 20, item 4) pede "melhora substancial
    # na calibração de cobertura/PIT frente ao RAW" (calibração E cobertura
    # E PIT, conjuntamente); a implementação abaixo avalia SÓ cobertura (3
    # níveis nominais), nunca o PIT. Auditoria externa (2ª rodada) —
    # avaliação formalmente PARCIAL do critério não pode ser reportada como
    # aprovação integral. Reportado como `nao_integralmente_verificado`
    # (`criterio_4_classificacao`) SEMPRE, independente do resultado da
    # cobertura isolada — o valor calculado da cobertura isolada é
    # preservado sem alteração para rastreabilidade
    # (`criterio_4_cobertura_dentro_do_esperado_vs_raw`). O PIT é calculado,
    # reportado e discutido integralmente (seção `pit`), mas nunca decide
    # este critério.
    cobertura_melhor_que_raw = all(
        abs(cobertura[nivel]['cobertura_empirica'] - cobertura[nivel]['cobertura_nominal'])
        <= abs(cobertura_raw[nivel]['cobertura_empirica'] - cobertura_raw[nivel]['cobertura_nominal'])
        for nivel in cobertura)
    cond4 = cobertura_melhor_que_raw

    # Decisão de aprovação: o protocolo (seção 20) exige os 4 critérios
    # SIMULTANEAMENTE para APROVAR — fórmula mantida sem alteração (ainda
    # resulta em False, pois cond1/cond2 já são False). A NÃO aprovação,
    # porém, já está decidida só pelos critérios 1 e 2 (ambos booleanos,
    # pré-registrados sem ressalva, e ambos False) — critérios 3/4 são
    # diagnósticos complementares que nunca mudariam essa conclusão.
    aprovado = bool(cond1 and cond2 and cond3 and cond4)
    motivos_suficientes_para_nao_aprovacao = []
    if not cond1:
        motivos_suficientes_para_nao_aprovacao.append(
            'IC95% do ganho em relação ao EMOS d=0 (CRPSS_spread_dinamico) inclui zero')
    if not cond2:
        motivos_suficientes_para_nao_aprovacao.append(
            'EMOS não supera a climatologia probabilística causal (IC95% de CRPSS vs. '
            'climatologia inclui zero)')

    decisao = {
        'criterio_1_crpss_spread_dinamico_ic_acima_de_zero': cond1,
        'criterio_2_crpss_vs_climatologia_ic_acima_de_zero': cond2,
        'criterio_3_sem_degradacao_grave_brier_bss': cond3,
        'criterio_3_bss_dentro_do_limiar_calculado': cond3,
        'criterio_3_classificacao': 'diagnostico_condicionado_a_limiar_nao_pre_registrado',
        'criterio_3_limiar_nao_pre_registrado': True,
        'criterio_4_cobertura_melhor_ou_igual_ao_raw_nos_3_niveis': cond4,
        'criterio_4_cobertura_dentro_do_esperado_vs_raw': cond4,
        'criterio_4_classificacao': 'nao_integralmente_verificado',
        'aprovado_componente_dinamico_de_spread': aprovado,
        'motivos_suficientes_para_nao_aprovacao': motivos_suficientes_para_nao_aprovacao,
        'limiar_bss_degradacao_grave': LIMIAR_BSS_DEGRADACAO_GRAVE,
        'bss_valor_mais_proximo_do_limiar': (min(bss_vals, key=lambda x: abs(x - LIMIAR_BSS_DEGRADACAO_GRAVE))
                                              if bss_vals else None),
        'criterio_3_limitacao': ('O limiar BSS > -0,10 não tem artefato de pré-registro datado '
                                  'independente dos resultados reais — foi introduzido no mesmo '
                                  'commit que produziu os primeiros resultados do EMOS H2. '
                                  'Reportado como diagnóstico condicionado, nunca como critério '
                                  'certificadamente pré-registrado.'),
        'criterio_4_limitacao': ('O protocolo (seção 20, item 4) pede melhora de calibração/'
                                  'cobertura/PIT; esta implementação avalia formalmente só '
                                  'cobertura (3 níveis) — avaliação PARCIAL do critério, nunca '
                                  'reportada como aprovação integral. Não afeta a decisão '
                                  'final (critérios 1/2 já reprovam, isoladamente suficientes).'),
        'nota': ('O protocolo (seção 20) exige os 4 critérios SIMULTANEAMENTE para aprovar. A '
                 'NÃO aprovação do componente dinâmico de spread já está decidida pelos '
                 'critérios 1 e 2 (ambos pré-registrados sem ressalva, ambos False) — ver '
                 'motivos_suficientes_para_nao_aprovacao. Critérios 3/4 são diagnósticos '
                 'complementares (classificação, não aprovação binária certificada) e nunca '
                 'mudariam essa conclusão. Superar só o RAW sem superar a climatologia NÃO '
                 'basta (seção 20, "se o EMOS só superar o RAW mas não a climatologia: não '
                 'aprovar").'),
    }

    resultado = {
        'STOP_ON_FAILURE': False,
        'metodo': 'emos_h2_normal_censurada_zero_crps_minimizacao',
        'n_treino_minimo_emos': N_TREINO_MINIMO_EMOS,
        'leakage_check': leakage,
        'verificacao_falhas_convergencia': convergencia,
        'n_casos': chaves_ok,
        'crps_medio': {
            'emos_completo': float(tabela_ok['crps_emos'].mean()),
            'emos_d0': float(tabela_ok['crps_d0'].mean()),
            'raw': float(tabela_ok['crps_raw'].mean()),
            'climatologia': float(tabela_ok['crps_climatologia'].mean()),
        },
        'bootstrap_crpss': boot,
        'brier_bss': tercil,
        'cobertura_intervalos': cobertura,
        'cobertura_intervalos_raw': cobertura_raw,
        'pit': pit,
        'bias': bias,
        'diagnostico_parametros': diagnostico,
        'crps_final_treino_resumo': crps_final_treino_resumo,
        'decisao_criterio_pre_registrado': decisao,
        'primeira_init_date_avaliavel': tabela_ok.sort_values('init_date').iloc[0]['init_date'],
        'nenhum_pipeline_operacional_alterado': True,
        'nenhum_dashboard_alterado': True,
        'data_geracao_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    return resultado, tabela


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--executar', action='store_true')
    ap.add_argument('--gerar-relatorio', action='store_true')
    args = ap.parse_args()

    if args.executar:
        resultado, tabela = executar_emos_h2()
        DIRETORIO_SAIDA.mkdir(parents=True, exist_ok=True)
        CAMINHO_METRICAS_JSON.write_text(json.dumps(resultado, indent=2, ensure_ascii=False, default=str))
        print(f"  ✅ {CAMINHO_METRICAS_JSON.relative_to(ROOT)}")
        if resultado.get('STOP_ON_FAILURE'):
            print(f"\n❌ STOP_ON_FAILURE: {resultado.get('motivo')}")
            return
        colunas_csv = [c for c in tabela.columns if c not in ('membros',)]
        tabela[colunas_csv].to_csv(CAMINHO_TABELA_EXPANDING, index=False)
        print(f"  ✅ {CAMINHO_TABELA_EXPANDING.relative_to(ROOT)}")
        print(f"  N final = {resultado['n_casos']['n_final']}")
        return

    if args.gerar_relatorio:
        import cfsv2_relatorio_emos_h2 as rel
        rel.gerar_e_escrever()
        return

    ap.print_help()


if __name__ == '__main__':
    main()
