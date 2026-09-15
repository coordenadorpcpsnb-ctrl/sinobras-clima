#!/usr/bin/env python3
"""
backtest.py — Fase 1 + Fase 1.1: infraestrutura de validação temporal e
robustez metodológica (backtesting)

Mede a capacidade preditiva real do pipeline atual via expanding-window /
rolling-origin, ANTES de qualquer variável nova entrar em produção
(RONI-no-modelo, TNA, gradiente TNA-TSA, NMME, C3S, espacialização, ETP
dinâmica — nenhuma dessas é tocada aqui).

Isolado da produção por desenho:
  - NUNCA importa update_dashboard.py (esse módulo roda o pipeline inteiro
    e grava docs/index.html/serie_subst.csv só de ser importado — não tem
    guard de __main__). Toda a lógica relevante (SARIMAX, XGBoost, lags,
    cenário ENSO) é REPLICADA aqui, com os mesmos hiperparâmetros literais.
  - `tests/test_backtest.py::SincroniaComProducaoTestCase` lê o texto-fonte
    de update_dashboard.py (sem importar) e falha se os hiperparâmetros
    aqui declarados (SARIMAX_ORDER, SARIMAX_SEASONAL_ORDER, XGB_PARAMS)
    divergirem — para produção e backtest nunca divergirem em silêncio.
  - Nunca lê nem escreve docs/index.html, serie_subst.csv,
    master_monthly.csv, bh_final.json, fc_results_best.json,
    sarimax_data_best.json. Só LÊ data/serie_subst.csv e ESCREVE
    data/backtest_results_step{1,3}.json e data/backtest_predictions_step{1,3}.csv
    (mais data/backtest_optimizer_experiment.json quando pedido).
    Os artefatos originais da Fase 1 (data/backtest_results.json e
    data/backtest_predictions.csv, sem sufixo) NÃO são regravados por este
    módulo desde a Fase 1.1 — ficam como registro histórico daquela
    execução, com o schema antigo (sem SeasonalNaive, sem mes_alvo, com o
    modo chamado 'operacional'). Rodar de novo com STEP=3 usando o código
    da Fase 1.1 produz um schema DIFERENTE (novos modelos/campos) — por
    isso vai para um arquivo com nome explícito (_step3), nunca por cima
    do artefato antigo.

Desenho temporal (Seção 1): expanding window. Duas configurações de passo
entre origens — STEP_TRIMESTRAL=3 (Fase 1, mantida) e STEP_MENSAL=1 (Fase
1.1, resultado principal de robustez) — mesmo horizonte H=12, mesmo
mínimo de 15 anos de treino, mesmas regras de leakage.

Nomenclatura dos modos (Fase 1.1, Seção 8): renomeado de 'operacional'
para 'operacional_simulado' em TODAS as saídas — o backtest não
reconstrói um hindcast histórico real de NMME/IRI/CPC; o futuro exógeno é
sintético (forma Gaussiana + persistência), computado só com informação
disponível até a origem. 'oracle_exog' continua sendo o modo que usa
nino34/tsa/pdo REAIS do horizonte de teste — não é desempenho
operacional, só diagnóstico de teto de melhoria.

Rode com:
    python scripts/backtest.py --step 3             # rolling-origin trimestral
    python scripts/backtest.py --step 1             # rolling-origin mensal (robustez)
    python scripts/backtest.py --smoke --step 1      # 2 origens, sem gravar
    python scripts/backtest.py --optimizer-experiment  # Seção 6, subamostra
"""

import argparse
import json
import subprocess
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.stats.diagnostic import acorr_ljungbox

warnings.filterwarnings('ignore')   # ruído genérico (pandas/numpy); ConvergenceWarning
                                     # do SARIMAX é capturado à parte, ver _fit_sarimax_diag

ROOT = Path(__file__).parent.parent
DATA = ROOT / 'data'
SERIE_PATH = DATA / 'serie_subst.csv'
UPDATE_DASHBOARD_PATH = ROOT / 'scripts' / 'update_dashboard.py'

# ══════════════════════════════════════════════════════════════════════════
# Hiperparâmetros — DEVEM bater com update_dashboard.py literal.
# tests/test_backtest.py::SincroniaComProducaoTestCase valida isso lendo o
# texto-fonte de update_dashboard.py (nunca importando).
# ══════════════════════════════════════════════════════════════════════════
SARIMAX_ORDER = (1, 0, 2)
SARIMAX_SEASONAL_ORDER = (1, 1, 1, 12)
XGB_PARAMS = dict(
    n_estimators=300, max_depth=4, learning_rate=0.05,
    subsample=0.8, colsample_bytree=0.8,
    min_child_weight=3, gamma=0.1,
    random_state=42, n_jobs=-1, verbosity=0,
    objective='reg:squarederror',
)

# ── Desenho temporal (Seção 1) ──────────────────────────────────────────
MIN_TRAIN_MONTHS = 15 * 12   # 180 — mínimo de 15 anos completos antes da 1ª origem
HORIZON = 12                  # meses — mandatório, nunca alterar sem revisar Seção 1
STEP_TRIMESTRAL = 3           # Fase 1 — origens trimestrais
STEP_MENSAL = 1               # Fase 1.1 — origens mensais, resultado principal de robustez
STEP = STEP_TRIMESTRAL        # default histórico, mantido por compatibilidade

# ── Nomenclatura dos modos (Fase 1.1, Seção 8) ──────────────────────────
MODO_OPERACIONAL = 'operacional_simulado'
MODO_ORACLE = 'oracle_exog'

# ── Regime ENSO na origem (Seção 8 da Fase 1) — classificado pelo Niño
#    3.4 BRUTO, nunca por ONI (que é média móvel trimestral centrada e
#    exigiria 1 mês de dado além da origem — vazamento sutil evitado).
ENSO_LA_NINA_MAX = -0.5
ENSO_EL_NINO_MIN = 0.5

# ── Amostra mínima para não tirar conclusão forte (ENSO / mês-alvo /
#    lead×mês-alvo) ──────────────────────────────────────────────────────
AMOSTRA_MINIMA = 8

# ── Seção 6: limiar de "mudança material" na previsão entre configurações
#    de otimizador — 5mm, o mesmo exemplo dado na especificação da tarefa.
#    Justificativa: é ~metade do desvio-padrão típico de erro de um mês
#    seco (jun-ago, climatologia < 20mm) e bem abaixo do RMSE observado do
#    modelo (~60mm) — um limiar menor capturaria só ruído de ponto
#    flutuante do otimizador, não uma mudança de previsão que importa.
MATERIALMENTE_DIFERENTE_MM = 5.0

MODELOS = ['Climatologia', 'SeasonalNaive', 'SARIMA_sem_exog', 'SARIMAX_atual', 'XGBoost_atual']
MODELOS_COM_ORACLE = ['SARIMAX_atual', 'XGBoost_atual']   # únicos que usam exógenas


# ══════════════════════════════════════════════════════════════════════════
# 1. CARGA E CORTE TEMPORAL — a única porta de entrada dos dados
# ══════════════════════════════════════════════════════════════════════════

def carregar_serie():
    """Lê data/serie_subst.csv (somente leitura) e adiciona a coluna 'ym'
    (pandas.Period mensal), usada como eixo de corte temporal."""
    serie = pd.read_csv(SERIE_PATH)
    serie['ym'] = pd.PeriodIndex(
        pd.to_datetime(dict(year=serie['ano'], month=serie['mes'], day=1)),
        freq='M')
    return serie.sort_values('ym').reset_index(drop=True)


def cortar_serie(serie, origem):
    """Corte leakage-safe: devolve SÓ as linhas com ym <= origem, como um
    novo DataFrame. Nenhuma função 'operacional' deste módulo deve receber
    a série completa — sempre este corte. É a garantia estrutural (não só
    lógica) contra vazamento: o dado posterior à origem nem está no objeto."""
    return serie.loc[serie['ym'] <= origem].reset_index(drop=True).copy()


def gerar_origens(serie, step=STEP_TRIMESTRAL):
    """Origens em expanding window, espaçadas por `step` meses. Primeira
    origem: primeiro mês da série + (MIN_TRAIN_MONTHS - 1), garantindo
    >=15 anos completos de treino. Última origem: último mês da série -
    HORIZON, garantindo 12 meses reais de teste para toda origem.

    step=STEP_TRIMESTRAL (3, Fase 1): 4 posições sazonais/ano — cada lead
    fica desbalanceado entre meses-calendário (ver metrics_by_target_month).
    step=STEP_MENSAL (1, Fase 1.1): todo mês é origem — cada lead cobre
    os 12 meses-calendário quase uniformemente, permitindo separar efeito
    de horizonte de efeito de mês-calendário.
    """
    primeiro_mes = serie['ym'].min()
    ultimo_mes = serie['ym'].max()
    primeira_origem = primeiro_mes + (MIN_TRAIN_MONTHS - 1)
    ultima_origem = ultimo_mes - HORIZON
    origens = []
    o = primeira_origem
    while o <= ultima_origem:
        origens.append(o)
        o = o + step
    return origens


# ══════════════════════════════════════════════════════════════════════════
# 2. FEATURE ENGINEERING (lags) — réplica exata de update_dashboard.py
#    linhas 184-194, aplicada só sobre a série JÁ cortada.
#    Nunca calcular o lag na série inteira e depois fatiar: o corte vem
#    PRIMEIRO (cortar_serie), o shift() roda DEPOIS, dentro da janela já
#    truncada — não há como o shift enxergar além de 'origem' porque essa
#    linha simplesmente não existe no DataFrame.
# ══════════════════════════════════════════════════════════════════════════

def construir_lags(serie_cortada):
    d = serie_cortada.copy()
    d['pdo'] = d['pdo'].ffill().fillna(0)
    for L in [2, 3]:
        d[f'n34_l{L}'] = d['nino34'].shift(L)
        d[f'tsa_l{L}'] = d['tsa'].shift(L)
        d[f'pdo_l{L}'] = d['pdo'].shift(L)
    d['n34_l23'] = (d['n34_l2'] + d['n34_l3']) / 2
    d['tsa_l23'] = (d['tsa_l2'] + d['tsa_l3']) / 2
    d['pdo_l23'] = (d['pdo_l2'] + d['pdo_l3']) / 2
    d = d.dropna(subset=['n34_l23', 'tsa_l23', 'pdo_l23']).reset_index(drop=True)
    return d


# ══════════════════════════════════════════════════════════════════════════
# 3. MODELO A — CLIMATOLOGIA MENSAL (só operacional; não consome exógenas)
# ══════════════════════════════════════════════════════════════════════════

def prever_climatologia(serie_cortada, origem):
    """Média histórica do mês-calendário, usando SÓ dados <= origem —
    nunca a climatologia 1981-2025 inteira (isso seria vazamento ao
    simular uma origem no passado)."""
    media_mes = serie_cortada.groupby('mes')['prec'].mean()
    preds = []
    for lead in range(1, HORIZON + 1):
        p = origem + lead
        preds.append(float(media_mes.get(p.month, serie_cortada['prec'].mean())))
    return np.array(preds)


# ══════════════════════════════════════════════════════════════════════════
# 3b. MODELO E — SEASONAL NAIVE (Fase 1.1, Seção 3)
#     previsão(M) = observado(M-12). Todo M-12 é <= origem por construção
#     (M vai de origem+1 a origem+12 ⇒ M-12 vai de origem-11 a origem,
#     sempre dentro do que já é conhecido em T) — nunca há recursão e
#     nunca há vazamento, não é preciso nem checar contra o corte.
# ══════════════════════════════════════════════════════════════════════════

def prever_seasonal_naive(serie_cortada, origem):
    prec_by_ym = serie_cortada.set_index('ym')['prec']
    preds = []
    for lead in range(1, HORIZON + 1):
        p = origem + lead
        p_ref = p - 12
        assert p_ref <= origem, "SeasonalNaive vazaria dado futuro — invariante quebrado"
        preds.append(float(prec_by_ym.get(p_ref, np.nan)))
    return np.array(preds)


# ══════════════════════════════════════════════════════════════════════════
# 4. AJUSTE SARIMA/SARIMAX COM DIAGNÓSTICO DE CONVERGÊNCIA (Fase 1.1, Seção 5)
#
# A Fase 1 relatou ConvergenceWarning sistemático com
# `warnings.filterwarnings('ignore')` global — inadequado para auditoria.
# Aqui, cada fit roda dentro de um `catch_warnings(record=True)` LOCAL, que
# temporariamente sobrepõe o filtro global só para esta chamada: a
# ConvergenceWarning é CAPTURADA (não escondida) e vira um registro
# estruturado (converged/iterations/optimizer/aic/llf), nunca só suprimida.
#
# maxiter=None/method=None reproduz exatamente `.fit(disp=False)` da
# produção (usa os defaults do statsmodels — otimizador 'lbfgs', maxiter
# default da biblioteca). É a configuração "A" da Seção 6.
# ══════════════════════════════════════════════════════════════════════════

def _fit_sarimax_diag(endog, exog=None, order=SARIMAX_ORDER, seasonal_order=SARIMAX_SEASONAL_ORDER,
                       maxiter=None, method=None):
    with warnings.catch_warnings(record=True) as wlist:
        warnings.simplefilter('always')
        kwargs = dict(order=order, seasonal_order=seasonal_order, enforce_stationarity=False)
        model = SARIMAX(endog, exog=exog, **kwargs) if exog is not None else SARIMAX(endog, **kwargs)
        fit_kwargs = {'disp': False}
        if maxiter is not None:
            fit_kwargs['maxiter'] = maxiter
        if method is not None:
            fit_kwargs['method'] = method
        res = model.fit(**fit_kwargs)

    teve_warning_convergencia = any('converg' in str(w.message).lower() for w in wlist)
    mle = getattr(res, 'mle_retvals', None) or {}
    if 'converged' in mle:
        converged = bool(mle['converged'])
    elif 'warnflag' in mle:
        converged = bool(mle['warnflag'] == 0)
    else:
        converged = not teve_warning_convergencia
    iterations = mle.get('iterations', mle.get('nit'))

    diag = {
        'converged': converged,
        'iterations': (int(iterations) if iterations is not None else None),
        'optimizer': method or 'lbfgs',
        'maxiter_config': maxiter,
        'warning_convergencia_emitido': teve_warning_convergencia,
        'aic': (float(res.aic) if hasattr(res, 'aic') and np.isfinite(res.aic) else None),
        'llf': (float(res.llf) if hasattr(res, 'llf') and np.isfinite(res.llf) else None),
    }
    return res, diag


def prever_sarima_sem_exog(serie_cortada, origem, maxiter=None, method=None):
    endog = pd.Series(serie_cortada['prec'].values, index=serie_cortada['ym'])
    res, diag = _fit_sarimax_diag(endog, exog=None, maxiter=maxiter, method=method)
    fc = res.get_forecast(steps=HORIZON)
    preds = np.clip(fc.predicted_mean.values, 0, None)
    return preds, diag


def treinar_sarimax_exog(d_cortado, maxiter=None, method=None):
    endog = pd.Series(d_cortado['prec'].values, index=d_cortado['ym'])
    exog = pd.DataFrame({'n34_l23': d_cortado['n34_l23'].values,
                          'tsa_l23': d_cortado['tsa_l23'].values,
                          'pdo_l23': d_cortado['pdo_l23'].values}, index=endog.index)
    res, diag = _fit_sarimax_diag(endog, exog=exog, maxiter=maxiter, method=method)
    return res, diag


def prever_sarimax_exog(res, exog_futuro):
    fc = res.get_forecast(steps=HORIZON, exog=exog_futuro[['n34_l23', 'tsa_l23', 'pdo_l23']].values)
    return np.clip(fc.predicted_mean.values, 0, None)


# ══════════════════════════════════════════════════════════════════════════
# 5. FUTURO DAS EXÓGENAS — operacional_simulado vs oracle_exog
#
# operacional_simulado: réplica do build_n34_path/gtsa/gpdo de
# update_dashboard.py (linhas 394-417), mas com duas divergências
# deliberadas e documentadas (herdadas da Fase 1):
#   1. A amplitude do Gaussiano de Niño 3.4 usa persistência do último
#      valor REAL <= origem (produção usa o rótulo de cenário ENSO/IRI,
#      que não foi arquivado historicamente e não é reconstruível para
#      origens passadas).
#   2. TSA e PDO futuros usam persistência verdadeira (último valor real
#      para TSA; média dos últimos 3 meses para PDO — regra documentada
#      na armadilha 6 do CLAUDE.md) em vez da constante travada 0.44 que
#      o gerador de cenário de produção usa para TSA.
# O nome 'operacional_simulado' (Fase 1.1, Seção 8) existe exatamente
# para deixar essa natureza sintética explícita: não é um hindcast
# histórico real de NMME/IRI/CPC arquivado, é uma simulação com a mesma
# forma/regra de persistência do pipeline, usando só dado <= origem.
#
# oracle_exog: usa nino34/tsa/pdo REAIS da série COMPLETA (não da série
# cortada) para os meses do horizonte — nunca a precipitação.
# ══════════════════════════════════════════════════════════════════════════

def _construir_path_n34_operacional(serie_cortada, origem):
    n34_hist = pd.Series(serie_cortada['nino34'].values, index=serie_cortada['ym'])
    A = float(n34_hist.iloc[-1]) if len(n34_hist) else 0.0
    ano_base = origem.year
    peak = pd.Period(f'{ano_base + 1}-01', 'M').ordinal
    # Janela ampliada em torno da ORIGEM (produção usa TODAY fixo; aqui a
    # origem varia por rodada, então a janela precisa acompanhar a origem
    # para sempre cobrir os lags -2/-3 de todo o horizonte). Adaptação
    # documentada — mesma matemática do Gaussiano, range recalculado.
    ext = pd.period_range(origem - 14, origem + 26, freq='M')
    path = {}
    for p in ext:
        k = (p.year, p.month)
        if p <= origem and p in n34_hist.index:
            v = float(n34_hist[p])
            if not np.isnan(v):
                path[k] = v
                continue
        dt = p.ordinal - peak
        v = A * np.exp(-(dt ** 2) / (2 * 3.5 ** 2)) if -8 <= dt <= 9 else 0.0
        path[k] = round(v, 3)
    return path


def _tsa_persistente(serie_cortada):
    return float(serie_cortada['tsa'].iloc[-1]) if len(serie_cortada) else 0.44


def _pdo_persistente(serie_cortada):
    if len(serie_cortada) == 0:
        return 0.0
    ultimos3 = serie_cortada['pdo'].iloc[-3:]
    return float(ultimos3.mean())


def montar_exog_futuro(serie_cortada, serie_completa, origem, modo):
    """Devolve DataFrame indexado pelos 12 meses do horizonte
    (origem+1 .. origem+12) com colunas n34_l23/tsa_l23/pdo_l23.

    modo=MODO_OPERACIONAL: só enxerga serie_cortada (dado <= origem).
    modo=MODO_ORACLE: usa nino34/tsa/pdo REAIS de serie_completa — só
    essas 3 colunas, nunca 'prec'.
    """
    horiz = pd.period_range(origem + 1, periods=HORIZON, freq='M')
    if modo == MODO_OPERACIONAL:
        path = _construir_path_n34_operacional(serie_cortada, origem)
        tsa_pers = _tsa_persistente(serie_cortada)
        pdo_pers = _pdo_persistente(serie_cortada)
        tsa_hist = pd.Series(serie_cortada['tsa'].values, index=serie_cortada['ym'])
        pdo_hist = pd.Series(serie_cortada['pdo'].values, index=serie_cortada['ym'])

        def gn34(p):
            return path.get((p.year, p.month), 0.0)

        def gtsa(p):
            if p <= origem and p in tsa_hist.index:
                v = float(tsa_hist[p])
                if not np.isnan(v):
                    return v
            return tsa_pers

        def gpdo(p):
            if p <= origem and p in pdo_hist.index:
                v = float(pdo_hist[p])
                if not np.isnan(v):
                    return v
            return pdo_pers

    elif modo == MODO_ORACLE:
        n34_real = pd.Series(serie_completa['nino34'].values, index=serie_completa['ym'])
        tsa_real = pd.Series(serie_completa['tsa'].values, index=serie_completa['ym'])
        pdo_real = pd.Series(serie_completa['pdo'].values, index=serie_completa['ym'])

        def gn34(p):
            return float(n34_real[p]) if p in n34_real.index else 0.0

        def gtsa(p):
            return float(tsa_real[p]) if p in tsa_real.index else 0.44

        def gpdo(p):
            return float(pdo_real[p]) if p in pdo_real.index else 0.0
    else:
        raise ValueError(f"modo inválido: {modo}")

    n34_l23 = [(gn34(p - 2) + gn34(p - 3)) / 2 for p in horiz]
    tsa_l23 = [(gtsa(p - 2) + gtsa(p - 3)) / 2 for p in horiz]
    pdo_l23 = [(gpdo(p - 2) + gpdo(p - 3)) / 2 for p in horiz]

    return pd.DataFrame({'n34_l23': n34_l23, 'tsa_l23': tsa_l23, 'pdo_l23': pdo_l23},
                         index=horiz)


# ══════════════════════════════════════════════════════════════════════════
# 6. MODELO D — XGBOOST ATUAL — mesmas features/hiperparâmetros da produção
#    Multi-step recursivo: M+1 pode usar prec observada <= T; M+2..M+12
#    usam a PREVISÃO do passo anterior, nunca a prec real (que nem está
#    disponível — o horizonte é sempre > origem).
# ══════════════════════════════════════════════════════════════════════════

def treinar_xgb(d_cortado):
    prec_all = d_cortado['prec'].values
    meses = np.array([p.month for p in d_cortado['ym']])
    X = pd.DataFrame({
        'mes': meses,
        'mes_sin': np.sin(2 * np.pi * meses / 12),
        'mes_cos': np.cos(2 * np.pi * meses / 12),
        'n34_l23': d_cortado['n34_l23'].values,
        'tsa_l23': d_cortado['tsa_l23'].values,
        'pdo_l23': d_cortado['pdo_l23'].values,
        'prec_l1': np.concatenate([[np.nan] * 1, prec_all[:-1]]) if len(prec_all) > 1 else np.array([np.nan] * len(prec_all)),
        'prec_l2': np.concatenate([[np.nan] * 2, prec_all[:-2]]) if len(prec_all) > 2 else np.array([np.nan] * len(prec_all)),
        'prec_l12': np.concatenate([[np.nan] * 12, prec_all[:-12]]) if len(prec_all) > 12 else np.array([np.nan] * len(prec_all)),
    })
    X = X.dropna().reset_index(drop=True)
    y = prec_all[len(prec_all) - len(X):]
    model = xgb.XGBRegressor(**XGB_PARAMS)
    model.fit(X, y)
    return model


def prever_xgb_recursivo(model, d_cortado, exog_futuro):
    """prec_buf começa com toda a prec REAL <= origem. A cada passo do
    horizonte, prec_l1/l2/l12 são lidos do buffer — que só recebe a
    PREVISÃO do passo anterior (nunca um valor observado, pois nenhum
    existe além da origem)."""
    prec_buf = list(d_cortado['prec'].values)
    preds = []
    for p, row in zip(exog_futuro.index, exog_futuro.itertuples()):
        X_step = pd.DataFrame([{
            'mes': p.month,
            'mes_sin': np.sin(2 * np.pi * p.month / 12),
            'mes_cos': np.cos(2 * np.pi * p.month / 12),
            'n34_l23': row.n34_l23,
            'tsa_l23': row.tsa_l23,
            'pdo_l23': row.pdo_l23,
            'prec_l1': prec_buf[-1] if len(prec_buf) >= 1 else 0,
            'prec_l2': prec_buf[-2] if len(prec_buf) >= 2 else 0,
            'prec_l12': prec_buf[-12] if len(prec_buf) >= 12 else 0,
        }])
        pred = float(max(0, model.predict(X_step)[0]))
        preds.append(pred)
        prec_buf.append(pred)
    return np.array(preds)


# ══════════════════════════════════════════════════════════════════════════
# 7. RESÍDUOS DO SARIMAX (Fase 1.1, Seção 7) — resumo por origem, sem
#    gerar centenas de gráficos. Usa os resíduos IN-SAMPLE do próprio fit
#    de treinar_sarimax_exog (nenhum ajuste extra).
# ══════════════════════════════════════════════════════════════════════════

def resumo_residuos_origem(res_sarimax, d_cortado, origem):
    resid = np.asarray(res_sarimax.resid, dtype=float)
    resid = resid[np.isfinite(resid)]
    row = {'origem': str(origem), 'n_resid': len(resid),
           'mean_resid': float(np.mean(resid)) if len(resid) else None,
           'autocorr_lag1': None, 'ljungbox_p_lag6': None, 'ljungbox_p_lag12': None}
    if len(resid) > 2:
        row['autocorr_lag1'] = float(np.corrcoef(resid[:-1], resid[1:])[0, 1])
    if len(resid) > 13:
        try:
            lb = acorr_ljungbox(resid, lags=[6, 12], return_df=True)
            row['ljungbox_p_lag6'] = float(lb['lb_pvalue'].iloc[0])
            row['ljungbox_p_lag12'] = float(lb['lb_pvalue'].iloc[1])
        except Exception:
            pass
    meses = d_cortado['mes'].values
    if len(meses) == len(np.asarray(res_sarimax.resid)):
        resid_full = np.asarray(res_sarimax.resid, dtype=float)
        for mm in range(1, 13):
            vals = resid_full[(meses == mm) & np.isfinite(resid_full)]
            row[f'resid_mes_{mm:02d}'] = float(np.mean(vals)) if len(vals) else None
    else:
        for mm in range(1, 13):
            row[f'resid_mes_{mm:02d}'] = None
    return row


def resumo_residuos(df_resid):
    if df_resid.empty:
        return {'n_origens': 0}
    resumo = {
        'n_origens': int(len(df_resid)),
        'media_dos_residuos_medios': round(float(df_resid['mean_resid'].mean()), 3),
        'media_autocorr_lag1': round(float(df_resid['autocorr_lag1'].dropna().mean()), 4),
        'pct_origens_ljungbox_lag12_rejeita_ruido_branco_p<0.05':
            round(float((df_resid['ljungbox_p_lag12'].dropna() < 0.05).mean() * 100), 1),
        'pct_origens_ljungbox_lag6_rejeita_ruido_branco_p<0.05':
            round(float((df_resid['ljungbox_p_lag6'].dropna() < 0.05).mean() * 100), 1),
        'resid_medio_por_mes_calendario': {
            f'{mm:02d}': round(float(df_resid[f'resid_mes_{mm:02d}'].dropna().mean()), 3)
            if df_resid[f'resid_mes_{mm:02d}'].notna().any() else None
            for mm in range(1, 13)
        },
    }
    return resumo


# ══════════════════════════════════════════════════════════════════════════
# 8. UMA ORIGEM — roda os 5 modelos, 2 modos (quando aplicável), mais
#    diagnóstico de convergência e resíduos.
# ══════════════════════════════════════════════════════════════════════════

def classificar_enso(nino34_origem):
    if nino34_origem <= ENSO_LA_NINA_MAX:
        return 'La Nina'
    if nino34_origem >= ENSO_EL_NINO_MIN:
        return 'El Nino'
    return 'Neutro'


def rodar_origem(serie, serie_cortada, origem, coletar_residuos=True):
    """Devolve (registros_previsao, registros_diag_convergencia,
    registro_residuo_ou_None, tempo_gasto) para esta origem."""
    t0 = time.time()
    registros = []
    diag_registros = []

    horiz = pd.period_range(origem + 1, periods=HORIZON, freq='M')
    observado = {p: serie.loc[serie['ym'] == p, 'prec'] for p in horiz}
    observado = {p: (float(v.iloc[0]) if len(v) else None) for p, v in observado.items()}

    nino34_origem = float(serie_cortada['nino34'].iloc[-1])
    classe_enso = classificar_enso(nino34_origem)

    def registrar(modelo, modo, preds):
        for lead, p in enumerate(horiz, start=1):
            obs = observado[p]
            prev = float(preds[lead - 1])
            registros.append({
                'origem': str(origem), 'data_prevista': str(p), 'lead': lead,
                'mes_alvo': p.month,
                'observado': obs, 'modelo': modelo, 'modo': modo, 'previsto': round(prev, 3),
                'erro': (round(prev - obs, 3) if obs is not None else None),
                'nino34_origem': round(nino34_origem, 3), 'classe_enso_origem': classe_enso,
            })

    # A — climatologia
    registrar('Climatologia', MODO_OPERACIONAL, prever_climatologia(serie_cortada, origem))

    # E — seasonal naive (nunca é vazamento: usa só M-12, sempre <= origem)
    registrar('SeasonalNaive', MODO_OPERACIONAL, prever_seasonal_naive(serie_cortada, origem))

    # B — SARIMA sem exógenas
    preds_sarima, diag_sarima = prever_sarima_sem_exog(serie_cortada, origem)
    registrar('SARIMA_sem_exog', MODO_OPERACIONAL, preds_sarima)
    diag_registros.append({'modelo': 'SARIMA_sem_exog', 'origem': str(origem), **diag_sarima})

    # Lags — leakage-safe: shift() roda DEPOIS do corte (ver construir_lags)
    d_cortado = construir_lags(serie_cortada)

    # C — SARIMAX atual: 1 fit, 2 forecasts (operacional_simulado / oracle)
    res_sarimax, diag_sarimax = treinar_sarimax_exog(d_cortado)
    diag_registros.append({'modelo': 'SARIMAX_atual', 'origem': str(origem), **diag_sarimax})
    exog_op = montar_exog_futuro(serie_cortada, serie, origem, MODO_OPERACIONAL)
    exog_or = montar_exog_futuro(serie_cortada, serie, origem, MODO_ORACLE)
    registrar('SARIMAX_atual', MODO_OPERACIONAL, prever_sarimax_exog(res_sarimax, exog_op))
    registrar('SARIMAX_atual', MODO_ORACLE, prever_sarimax_exog(res_sarimax, exog_or))

    residuo_row = None
    if coletar_residuos:
        residuo_row = resumo_residuos_origem(res_sarimax, d_cortado, origem)

    # D — XGBoost atual: 1 fit, 2 previsões recursivas
    model_xgb = treinar_xgb(d_cortado)
    registrar('XGBoost_atual', MODO_OPERACIONAL, prever_xgb_recursivo(model_xgb, d_cortado, exog_op))
    registrar('XGBoost_atual', MODO_ORACLE, prever_xgb_recursivo(model_xgb, d_cortado, exog_or))

    return registros, diag_registros, residuo_row, time.time() - t0


# ══════════════════════════════════════════════════════════════════════════
# 9. MÉTRICAS
# ══════════════════════════════════════════════════════════════════════════

def _rmse(obs, prev):
    obs, prev = np.asarray(obs, dtype=float), np.asarray(prev, dtype=float)
    return float(np.sqrt(np.mean((obs - prev) ** 2)))


def _mae(obs, prev):
    obs, prev = np.asarray(obs, dtype=float), np.asarray(prev, dtype=float)
    return float(np.mean(np.abs(obs - prev)))


def _bias(obs, prev):
    obs, prev = np.asarray(obs, dtype=float), np.asarray(prev, dtype=float)
    return float(np.mean(prev - obs))


def _r2(obs, prev):
    obs, prev = np.asarray(obs, dtype=float), np.asarray(prev, dtype=float)
    ss_tot = np.sum((obs - obs.mean()) ** 2)
    if ss_tot <= 0:
        return None
    ss_res = np.sum((obs - prev) ** 2)
    return float(1 - ss_res / ss_tot)


def _metricas(obs, prev):
    n = len(obs)
    r2 = _r2(obs, prev) if n else None
    return {'n': n, 'rmse': round(_rmse(obs, prev), 2) if n else None,
            'mae': round(_mae(obs, prev), 2) if n else None,
            'bias': round(_bias(obs, prev), 2) if n else None,
            'r2': (round(r2, 4) if r2 is not None else None),
            'amostra_insuficiente': bool(n < AMOSTRA_MINIMA)}


BLOCOS = {'H1-3': range(1, 4), 'H4-6': range(4, 7), 'H7-9': range(7, 10),
          'H10-12': range(10, 13), 'H1-12': range(1, 13)}


def calcular_metricas(df):
    """df: predictions DataFrame com observado não-nulo apenas."""
    df = df.dropna(subset=['observado'])
    metrics_by_lead = {}
    metrics_by_block = {}
    for (modelo, modo), g in df.groupby(['modelo', 'modo']):
        metrics_by_lead.setdefault(modelo, {})[modo] = {
            str(lead): _metricas(gl['observado'], gl['previsto'])
            for lead, gl in g.groupby('lead')
        }
        metrics_by_block.setdefault(modelo, {})[modo] = {
            nome: _metricas(g[g['lead'].isin(leads)]['observado'], g[g['lead'].isin(leads)]['previsto'])
            for nome, leads in BLOCOS.items()
        }
    overall = {
        f'{modelo}|{modo}': _metricas(g['observado'], g['previsto'])
        for (modelo, modo), g in df.groupby(['modelo', 'modo'])
    }
    return metrics_by_lead, metrics_by_block, overall


def calcular_metricas_por_mes_alvo(df):
    """Fase 1.1, Seção 2: metrics_by_target_month. RMSE/MAE/bias por
    mes_alvo (1-12), separado por modelo/modo — responde se certos meses
    são intrinsecamente mais difíceis, independente do lead."""
    df = df.dropna(subset=['observado'])
    resultado = {}
    for (modelo, modo), g in df.groupby(['modelo', 'modo']):
        resultado.setdefault(modelo, {})[modo] = {
            str(mm): _metricas(gm['observado'], gm['previsto'])
            for mm, gm in g.groupby('mes_alvo')
        }
    return resultado


def calcular_metricas_por_lead_e_mes_alvo(df):
    """Fase 1.1, Seção 2: metrics_by_lead_and_target_month. Célula
    (modelo, modo, lead, mes_alvo) — a mais fina; sinaliza amostra
    insuficiente por célula (ver _metricas)."""
    df = df.dropna(subset=['observado'])
    resultado = {}
    for (modelo, modo), g in df.groupby(['modelo', 'modo']):
        por_lead = {}
        for lead, gl in g.groupby('lead'):
            por_lead[str(lead)] = {
                str(mm): _metricas(gm['observado'], gm['previsto'])
                for mm, gm in gl.groupby('mes_alvo')
            }
        resultado.setdefault(modelo, {})[modo] = por_lead
    return resultado


def calcular_skill(metrics_by_lead, metrics_by_block):
    """Skill_RMSE = 1 - RMSE_modelo / RMSE_climatologia. modo=MODO_OPERACIONAL
    só (climatologia e seasonal naive não têm oracle)."""
    clim_lead = metrics_by_lead.get('Climatologia', {}).get(MODO_OPERACIONAL, {})
    clim_block = metrics_by_block.get('Climatologia', {}).get(MODO_OPERACIONAL, {})
    skill = {}
    for modelo in MODELOS:
        if modelo == 'Climatologia':
            continue
        skill[modelo] = {}
        for modo in ([MODO_OPERACIONAL] if modelo not in MODELOS_COM_ORACLE else [MODO_OPERACIONAL, MODO_ORACLE]):
            por_lead = metrics_by_lead.get(modelo, {}).get(modo)
            if not por_lead:
                continue
            sk_lead = {}
            for lead, m in por_lead.items():
                rc = clim_lead.get(lead, {}).get('rmse')
                sk_lead[lead] = round(1 - m['rmse'] / rc, 4) if (rc and m['rmse'] is not None) else None
            por_bloco = metrics_by_block.get(modelo, {}).get(modo, {})
            sk_bloco = {}
            for nome, m in por_bloco.items():
                rc = clim_block.get(nome, {}).get('rmse')
                sk_bloco[nome] = round(1 - m['rmse'] / rc, 4) if (rc and m['rmse'] is not None) else None
            skill[modelo][modo] = {'por_lead': sk_lead, 'por_bloco': sk_bloco}
    return skill


def calcular_metricas_enso(df):
    df = df.dropna(subset=['observado'])
    resultado = {}
    for classe, g_classe in df.groupby('classe_enso_origem'):
        n_origens = g_classe['origem'].nunique()
        resultado[classe] = {
            'n_origens': int(n_origens),
            'amostra_insuficiente': bool(n_origens < AMOSTRA_MINIMA),
            'metricas': {
                f'{modelo}|{modo}': _metricas(g['observado'], g['previsto'])
                for (modelo, modo), g in g_classe.groupby(['modelo', 'modo'])
            },
        }
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# 10. BLOCK BOOTSTRAP — incerteza da diferença de desempenho (Fase 1.1,
#     Seção 4). Bloco de reamostragem = ORIGEM: todas as 12 previsões
#     (lead 1..12) de uma origem viajam juntas em cada reamostragem, para
#     preservar a autocorrelação/sobreposição de horizonte entre leads da
#     mesma origem. Comparação pareada com a Climatologia na MESMA origem
#     (mesmo observado), reamostrando origens completas com reposição.
#     Reprodutível: seed fixa (default 42), n_boot fixo.
# ══════════════════════════════════════════════════════════════════════════

def bootstrap_ci_diff_rmse(df, modelo, climatologia='Climatologia', modo=MODO_OPERACIONAL,
                            leads=None, n_boot=2000, seed=42):
    leads = list(leads) if leads is not None else list(range(1, 13))
    sub = df[(df['modo'] == modo) & (df['lead'].isin(leads))].dropna(subset=['observado'])
    m = sub[sub['modelo'] == modelo][['origem', 'lead', 'observado', 'previsto']]
    c = sub[sub['modelo'] == climatologia][['origem', 'lead', 'previsto']].rename(
        columns={'previsto': 'previsto_clim'})
    merged = m.merge(c, on=['origem', 'lead'], how='inner')
    if merged.empty:
        return {'modelo': modelo, 'erro': 'sem previsões pareadas com a climatologia'}

    origens = merged['origem'].unique()
    blocos = {o: g[['observado', 'previsto', 'previsto_clim']].to_numpy()
              for o, g in merged.groupby('origem')}
    n = len(origens)
    rng = np.random.RandomState(seed)

    obs_all = merged['observado'].to_numpy(dtype=float)
    prev_all = merged['previsto'].to_numpy(dtype=float)
    clim_all = merged['previsto_clim'].to_numpy(dtype=float)
    rmse_m, rmse_c = _rmse(obs_all, prev_all), _rmse(obs_all, clim_all)
    mae_m, mae_c = _mae(obs_all, prev_all), _mae(obs_all, clim_all)
    skill_pt = (1 - rmse_m / rmse_c) if rmse_c else None

    diffs_rmse = np.empty(n_boot)
    diffs_mae = np.empty(n_boot)
    skills = np.empty(n_boot)
    for b in range(n_boot):
        escolha = rng.choice(origens, size=n, replace=True)
        arr = np.concatenate([blocos[o] for o in escolha], axis=0)
        obs_b, prev_b, clim_b = arr[:, 0], arr[:, 1], arr[:, 2]
        rm, rc = _rmse(obs_b, prev_b), _rmse(obs_b, clim_b)
        diffs_rmse[b] = rm - rc
        diffs_mae[b] = _mae(obs_b, prev_b) - _mae(obs_b, clim_b)
        skills[b] = (1 - rm / rc) if rc else np.nan

    def ic(a):
        a = a[np.isfinite(a)]
        if len(a) == 0:
            return [None, None]
        return [round(float(np.percentile(a, 2.5)), 4), round(float(np.percentile(a, 97.5)), 4)]

    return {
        'modelo': modelo, 'vs': climatologia, 'modo': modo, 'leads': [leads[0], leads[-1]],
        'n_origens': int(n), 'n_boot': n_boot, 'seed': seed,
        'bloco_de_reamostragem': 'origem (as 12 previsões lead 1..12 de cada origem reamostradas em conjunto)',
        'rmse_modelo': round(rmse_m, 3), 'rmse_climatologia': round(rmse_c, 3),
        'diff_rmse_pontual': round(rmse_m - rmse_c, 3), 'diff_rmse_ic95': ic(diffs_rmse),
        'mae_modelo': round(mae_m, 3), 'mae_climatologia': round(mae_c, 3),
        'diff_mae_pontual': round(mae_m - mae_c, 3), 'diff_mae_ic95': ic(diffs_mae),
        'skill_pontual': (round(skill_pt, 4) if skill_pt is not None else None), 'skill_ic95': ic(skills),
        'ic95_inclui_zero_no_diff_rmse': bool(ic(diffs_rmse)[0] is not None and ic(diffs_rmse)[0] <= 0 <= ic(diffs_rmse)[1]),
    }


def calcular_todos_bootstrap_ci(df, modelos=('SARIMAX_atual', 'SARIMA_sem_exog', 'XGBoost_atual', 'SeasonalNaive'),
                                 n_boot=2000, seed=42):
    return {modelo: bootstrap_ci_diff_rmse(df, modelo, modo=MODO_OPERACIONAL, n_boot=n_boot, seed=seed)
            for modelo in modelos}


# ══════════════════════════════════════════════════════════════════════════
# 11. DIAGNÓSTICO DE CONVERGÊNCIA — resumo (Fase 1.1, Seção 5)
# ══════════════════════════════════════════════════════════════════════════

def resumo_convergencia(df_diag, df_predictions):
    """% de fits convergentes por modelo, distribuição temporal das
    falhas (por ano de origem) e RMSE de origens convergentes vs não."""
    resultado = {}
    for modelo, g in df_diag.groupby('modelo'):
        total = len(g)
        conv = int(g['converged'].sum())
        g = g.copy()
        g['ano_origem'] = g['origem'].str.slice(0, 4).astype(int)
        falhas_por_ano = (
            g[~g['converged']].groupby('ano_origem').size().to_dict()
        )
        # RMSE por origem (H1-12, modo operacional_simulado) desse modelo
        preds_modelo = df_predictions[(df_predictions['modelo'] == modelo) &
                                       (df_predictions['modo'] == MODO_OPERACIONAL)].dropna(subset=['observado'])
        rmse_por_origem = preds_modelo.groupby('origem').apply(
            lambda gx: _rmse(gx['observado'], gx['previsto']), include_groups=False)
        origens_conv = set(g[g['converged']]['origem'])
        origens_nconv = set(g[~g['converged']]['origem'])
        rmse_conv = rmse_por_origem[rmse_por_origem.index.isin(origens_conv)]
        rmse_nconv = rmse_por_origem[rmse_por_origem.index.isin(origens_nconv)]
        resultado[modelo] = {
            'n_fits': total, 'n_convergentes': conv,
            'pct_convergente': round(conv / total * 100, 1) if total else None,
            'falhas_por_ano_origem': {str(k): int(v) for k, v in sorted(falhas_por_ano.items())},
            'rmse_medio_origens_convergentes': (round(float(rmse_conv.mean()), 2) if len(rmse_conv) else None),
            'rmse_medio_origens_nao_convergentes': (round(float(rmse_nconv.mean()), 2) if len(rmse_nconv) else None),
            'n_origens_nao_convergentes_com_previsao': len(rmse_nconv),
        }
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# 12. EXPERIMENTO OTIMIZADOR/MAXITER (Fase 1.1, Seção 6) — diagnóstico,
#     NÃO otimização de hiperparâmetros. Roda numa SUBAMOSTRA de origens
#     (não a lista inteira — "não faça busca massiva"), 3 configurações:
#       A. igual à produção (maxiter=None, method=None → default lbfgs)
#       B. maxiter aumentado (200), mesmo otimizador
#       C. otimizador diferente (Powell — livre de gradiente, classe de
#          algoritmo distinta do lbfgs quase-Newton da produção), maxiter
#          igualmente aumentado (200) para não confundir "otimizador
#          diferente" com "menos iterações"
# ══════════════════════════════════════════════════════════════════════════

CONFIGS_OTIMIZADOR = [
    ('A_producao', dict(maxiter=None, method=None)),
    ('B_maxiter_alto', dict(maxiter=200, method=None)),
    ('C_powell', dict(maxiter=200, method='powell')),
]


def rodar_experimento_optimizer(serie, origens_subset, configs=CONFIGS_OTIMIZADOR, verbose=True):
    resultados = {}   # config -> {'previsoes': [...], 'diag': [...], 'tempo_total':..}
    for nome_cfg, kwargs in configs:
        t0 = time.time()
        previsoes = []
        diags = []
        for origem in origens_subset:
            serie_cortada = cortar_serie(serie, origem)
            d_cortado = construir_lags(serie_cortada)

            preds_sarima, diag_sarima = prever_sarima_sem_exog(serie_cortada, origem, **kwargs)
            for lead, v in enumerate(preds_sarima, start=1):
                previsoes.append({'config': nome_cfg, 'modelo': 'SARIMA_sem_exog',
                                   'origem': str(origem), 'lead': lead, 'previsto': float(v)})
            diags.append({'config': nome_cfg, 'modelo': 'SARIMA_sem_exog', 'origem': str(origem), **diag_sarima})

            res_sarimax, diag_sarimax = treinar_sarimax_exog(d_cortado, **kwargs)
            exog_op = montar_exog_futuro(serie_cortada, serie, origem, MODO_OPERACIONAL)
            preds_sarimax = prever_sarimax_exog(res_sarimax, exog_op)
            for lead, v in enumerate(preds_sarimax, start=1):
                previsoes.append({'config': nome_cfg, 'modelo': 'SARIMAX_atual',
                                   'origem': str(origem), 'lead': lead, 'previsto': float(v)})
            diags.append({'config': nome_cfg, 'modelo': 'SARIMAX_atual', 'origem': str(origem), **diag_sarimax})

        tempo = time.time() - t0
        resultados[nome_cfg] = {'previsoes': pd.DataFrame(previsoes), 'diag': pd.DataFrame(diags), 'tempo': tempo}
        if verbose:
            n_conv = resultados[nome_cfg]['diag']['converged'].mean() * 100
            print(f"  [{nome_cfg}] {len(origens_subset)} origens em {tempo:.1f}s — {n_conv:.0f}% convergente")
    return resultados


def resumir_experimento_optimizer(serie, resultados, origens_subset, limiar_mm=MATERIALMENTE_DIFERENTE_MM):
    """Compara as configs entre si: taxa de convergência, RMSE/MAE/skill
    vs climatologia (computada uma vez, independe do otimizador), tempo
    relativo à config A, e nº de previsões que mudaram > limiar_mm."""
    # climatologia — mesma para todas as configs, calculada uma vez
    clim_rows = []
    obs_rows = []
    for origem in origens_subset:
        serie_cortada = cortar_serie(serie, origem)
        preds_clim = prever_climatologia(serie_cortada, origem)
        horiz = pd.period_range(origem + 1, periods=HORIZON, freq='M')
        for lead, (p, v) in enumerate(zip(horiz, preds_clim), start=1):
            obs = serie.loc[serie['ym'] == p, 'prec']
            obs = float(obs.iloc[0]) if len(obs) else None
            clim_rows.append({'origem': str(origem), 'lead': lead, 'previsto_clim': float(v)})
            obs_rows.append({'origem': str(origem), 'lead': lead, 'observado': obs})
    clim_df = pd.DataFrame(clim_rows)
    obs_df = pd.DataFrame(obs_rows)

    baseline_nome = CONFIGS_OTIMIZADOR[0][0]
    tempo_base = resultados[baseline_nome]['tempo']

    resumo = {}
    for nome_cfg, dados in resultados.items():
        prev_df = dados['previsoes'].merge(obs_df, on=['origem', 'lead']).merge(clim_df, on=['origem', 'lead'])
        prev_df = prev_df.dropna(subset=['observado'])
        por_modelo = {}
        for modelo, g in prev_df.groupby('modelo'):
            rmse_m = _rmse(g['observado'], g['previsto'])
            rmse_c = _rmse(g['observado'], g['previsto_clim'])
            mae_m = _mae(g['observado'], g['previsto'])
            skill = round(1 - rmse_m / rmse_c, 4) if rmse_c else None
            diag_m = dados['diag'][dados['diag']['modelo'] == modelo]
            por_modelo[modelo] = {
                'pct_convergente': round(float(diag_m['converged'].mean() * 100), 1),
                'rmse': round(rmse_m, 2), 'mae': round(mae_m, 2), 'skill_vs_climatologia': skill,
            }
        resumo[nome_cfg] = {
            'tempo_segundos': round(dados['tempo'], 1),
            'tempo_relativo_a_A': round(dados['tempo'] / tempo_base, 2) if tempo_base else None,
            'por_modelo': por_modelo,
        }

    # mudança material entre A e B, e A e C
    mudancas = {}
    base_prev = resultados[baseline_nome]['previsoes'].set_index(['modelo', 'origem', 'lead'])['previsto']
    for nome_cfg, dados in resultados.items():
        if nome_cfg == baseline_nome:
            continue
        outra_prev = dados['previsoes'].set_index(['modelo', 'origem', 'lead'])['previsto']
        comum = base_prev.index.intersection(outra_prev.index)
        diff = (base_prev.loc[comum] - outra_prev.loc[comum]).abs()
        mudancas[f'{baseline_nome}_vs_{nome_cfg}'] = {
            'n_previsoes_comparadas': int(len(comum)),
            'n_mudancas_materiais': int((diff > limiar_mm).sum()),
            'pct_mudancas_materiais': round(float((diff > limiar_mm).mean() * 100), 2),
            'diff_absoluta_media_mm': round(float(diff.mean()), 3),
            'diff_absoluta_max_mm': round(float(diff.max()), 3),
        }

    return {
        'limiar_materialmente_diferente_mm': limiar_mm,
        'n_origens_subamostra': len(origens_subset),
        'configs': resumo,
        'mudancas_materiais': mudancas,
    }


# ══════════════════════════════════════════════════════════════════════════
# 13. ORQUESTRAÇÃO
# ══════════════════════════════════════════════════════════════════════════

def _git_sha():
    try:
        r = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def executar_backtest(step=STEP_TRIMESTRAL, origens=None, coletar_residuos=True, verbose=True):
    """Roda o backtest para a lista de origens dada (todas do `step`, se
    None). Não grava nada em disco — devolve (df_predictions, df_diag,
    df_residuos, tempos)."""
    serie = carregar_serie()
    if origens is None:
        origens = gerar_origens(serie, step=step)

    todos_registros = []
    todos_diag = []
    todos_residuos = []
    tempos = []
    for i, origem in enumerate(origens):
        serie_cortada = cortar_serie(serie, origem)
        registros, diag, residuo, dt = rodar_origem(serie, serie_cortada, origem, coletar_residuos=coletar_residuos)
        todos_registros.extend(registros)
        todos_diag.extend(diag)
        if residuo is not None:
            todos_residuos.append(residuo)
        tempos.append(dt)
        if verbose:
            print(f"  [{i+1}/{len(origens)}] origem={origem}  ({dt:.2f}s)")

    df = pd.DataFrame(todos_registros)
    df_diag = pd.DataFrame(todos_diag)
    df_residuos = pd.DataFrame(todos_residuos)
    return df, df_diag, df_residuos, tempos, serie


def montar_resultado(df, df_diag, df_residuos, tempos, serie, origens, step, smoke=False):
    metrics_by_lead, metrics_by_block, overall = calcular_metricas(df)
    skill = calcular_skill(metrics_by_lead, metrics_by_block)
    enso = calcular_metricas_enso(df)
    por_mes_alvo = calcular_metricas_por_mes_alvo(df)
    por_lead_mes_alvo = calcular_metricas_por_lead_e_mes_alvo(df)
    convergencia = resumo_convergencia(df_diag, df) if not df_diag.empty else {}
    residuos = resumo_residuos(df_residuos) if not df_residuos.empty else {}
    bootstrap = calcular_todos_bootstrap_ci(df) if not smoke else {}

    metadata = {
        'data_execucao': pd.Timestamp.now().isoformat(),
        'git_sha': _git_sha(),
        'step': step,
        'primeira_origem': str(origens[0]), 'ultima_origem': str(origens[-1]),
        'n_origens': len(origens),
        'horizonte': HORIZON,
        'min_treino_meses': MIN_TRAIN_MONTHS,
        'periodo_base_serie': f"{serie['ym'].min()} a {serie['ym'].max()}",
        'tempo_total_segundos': round(sum(tempos), 1),
        'tempo_medio_por_origem_segundos': round(sum(tempos) / len(tempos), 2) if tempos else None,
        'amostra_minima_para_conclusao': AMOSTRA_MINIMA,
        'nomenclatura_modos': {
            MODO_OPERACIONAL: 'exógenas futuras SIMULADAS (forma Gaussiana + persistência), só com '
                               'informação <= origem. NÃO é um hindcast histórico real de NMME/IRI/CPC.',
            MODO_ORACLE: 'exógenas futuras REAIS observadas no horizonte de teste — diagnóstico de teto '
                         'de melhoria, nunca desempenho operacional.',
        },
        'metodologia': 'SARIMAX(1,0,2)(1,1,1,12) e XGBoost idênticos a update_dashboard.py '
                        '(hiperparâmetros replicados, não importados); expanding window, '
                        f'origens a cada {step} mes(es), horizonte 12 meses.',
        'smoke_test': smoke,
    }

    return {
        'metadata': metadata,
        'models': MODELOS,
        'metrics_by_lead': metrics_by_lead,
        'metrics_by_horizon_block': metrics_by_block,
        'overall_metrics': overall,
        'skill_vs_climatology': skill,
        'enso_regime_metrics': enso,
        'metrics_by_target_month': por_mes_alvo,
        'metrics_by_lead_and_target_month': por_lead_mes_alvo,
        'convergence_diagnostics': convergencia,
        'residual_diagnostics': residuos,
        'bootstrap_ci_vs_climatology': bootstrap,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--step', type=int, choices=[1, 3], default=3,
                     help='passo entre origens em meses (1=mensal/robustez, 3=trimestral/Fase 1)')
    ap.add_argument('--smoke', action='store_true', help='roda só 2 origens, não grava em disco')
    ap.add_argument('--optimizer-experiment', action='store_true',
                     help='roda o experimento de otimizador/maxiter (Seção 6) numa subamostra')
    ap.add_argument('--optimizer-subset-every', type=int, default=15,
                     help='usa 1 a cada N origens (do step=1) na subamostra do experimento')
    args = ap.parse_args()

    serie = carregar_serie()

    if args.optimizer_experiment:
        origens_completas = gerar_origens(serie, step=STEP_MENSAL)
        subset = origens_completas[::args.optimizer_subset_every]
        print(f"Experimento otimizador/maxiter — subamostra de {len(subset)} origens "
              f"(1 a cada {args.optimizer_subset_every} de {len(origens_completas)})")
        resultados = rodar_experimento_optimizer(serie, subset, verbose=True)
        resumo = resumir_experimento_optimizer(serie, resultados, subset)
        out = DATA / 'backtest_optimizer_experiment.json'
        out.write_text(json.dumps(resumo, ensure_ascii=False, indent=2))
        print(f"\n  ✅ {out.relative_to(ROOT)}")
        print(json.dumps(resumo['configs'], indent=2, ensure_ascii=False))
        return

    todas_origens = gerar_origens(serie, step=args.step)
    origens = todas_origens[:2] if args.smoke else todas_origens

    print(f"Backtest — step={args.step} — {len(origens)} origens ({'smoke test' if args.smoke else 'completo'})")
    print(f"  Primeira origem: {todas_origens[0]}   Última origem: {todas_origens[-1]}")
    print(f"  Total de origens (config completa): {len(todas_origens)}   Horizonte: {HORIZON}")
    print(f"  Mínimo de treino: {MIN_TRAIN_MONTHS} meses ({MIN_TRAIN_MONTHS/12:.0f} anos)")

    df, df_diag, df_residuos, tempos, serie = executar_backtest(
        step=args.step, origens=origens, coletar_residuos=True, verbose=True)
    print(f"\n  Tempo total: {sum(tempos):.1f}s  ({sum(tempos)/len(tempos):.2f}s/origem)")

    resultado = montar_resultado(df, df_diag, df_residuos, tempos, serie, origens, args.step, smoke=args.smoke)

    if not args.smoke:
        sufixo = f'_step{args.step}'
        out_json = DATA / f'backtest_results{sufixo}.json'
        out_csv = DATA / f'backtest_predictions{sufixo}.csv'
        out_diag = DATA / f'backtest_convergence{sufixo}.csv'
        out_resid = DATA / f'backtest_residuals{sufixo}.csv'
        out_json.write_text(json.dumps(resultado, ensure_ascii=False, indent=2))
        df.to_csv(out_csv, index=False)
        df_diag.to_csv(out_diag, index=False)
        df_residuos.to_csv(out_resid, index=False)
        print(f"\n  ✅ {out_json.relative_to(ROOT)}")
        print(f"  ✅ {out_csv.relative_to(ROOT)}")
        print(f"  ✅ {out_diag.relative_to(ROOT)}")
        print(f"  ✅ {out_resid.relative_to(ROOT)}")
    else:
        print("\n  (smoke test — nada gravado em disco)")

    print(json.dumps(resultado['overall_metrics'], indent=2, ensure_ascii=False))
    return resultado, df


if __name__ == '__main__':
    main()
