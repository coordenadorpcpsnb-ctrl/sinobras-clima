#!/usr/bin/env python3
"""
backtest.py — Fase 1: infraestrutura de validação temporal (backtesting)

Mede a capacidade preditiva real do pipeline atual via expanding-window /
rolling-origin, ANTES de qualquer variável nova entrar em produção
(RONI-no-modelo, TNA, NMME, C3S, espacialização, ETP dinâmica — nenhuma
dessas é tocada aqui).

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
    data/backtest_results.json e data/backtest_predictions.csv.

Desenho temporal (Seção 1): expanding window, origem trimestral (step=3
meses), horizonte fixo H=12. Mínimo de 15 anos completos de histórico
antes da primeira origem — ver `gerar_origens()`.

Vazamento (Seção 3): dois modos, nunca misturados nos resultados:
  - operacional: em T, nenhuma observação com data > T é usada — nem de
    precipitação, nem de nino34/tsa/pdo. O futuro exógeno é SIMULADO com
    a mesma lógica de forma/persistência do pipeline, computada só com
    dados <= T.
  - oracle_exog: usa nino34/tsa/pdo REAIS observados no horizonte de
    teste (não a precipitação — essa nunca é dado real em nenhum modo,
    por definição de previsão). Serve só para responder "sabendo o
    exógeno perfeitamente, quão bem o modelo previria?" — não é
    desempenho operacional.

Rode com:
    python scripts/backtest.py                  # backtest completo
    python scripts/backtest.py --smoke           # 2 origens, sem gravar
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

warnings.filterwarnings('ignore')

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
STEP = 3                      # origens trimestrais — mantém o runtime razoável

# ── Regime ENSO na origem (Seção 8) — classificado pelo Niño 3.4 BRUTO,
#    nunca por ONI (que é média móvel trimestral centrada e exigiria 1 mês
#    de dado além da origem — vazamento sutil evitado por desenho).
ENSO_LA_NINA_MAX = -0.5
ENSO_EL_NINO_MIN = 0.5
ENSO_AMOSTRA_MINIMA = 8   # abaixo disso, sinaliza "amostra insuficiente"

MODELOS = ['Climatologia', 'SARIMA_sem_exog', 'SARIMAX_atual', 'XGBoost_atual']
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


def gerar_origens(serie):
    """Origens trimestrais em expanding window. Primeira origem: primeiro
    mês da série + (MIN_TRAIN_MONTHS - 1), garantindo >=15 anos completos
    de treino. Última origem: último mês da série - HORIZON, garantindo
    12 meses reais de teste para toda origem."""
    primeiro_mes = serie['ym'].min()
    ultimo_mes = serie['ym'].max()
    primeira_origem = primeiro_mes + (MIN_TRAIN_MONTHS - 1)
    ultima_origem = ultimo_mes - HORIZON
    origens = []
    o = primeira_origem
    while o <= ultima_origem:
        origens.append(o)
        o = o + STEP
    return origens


# ══════════════════════════════════════════════════════════════════════════
# 2. FEATURE ENGINEERING (lags) — réplica exata de update_dashboard.py
#    linhas 184-194, aplicada só sobre a série JÁ cortada (Seção 4).
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
# 4. MODELO B — SARIMA SEM EXÓGENAS (mesma ordem do produtivo)
# ══════════════════════════════════════════════════════════════════════════

def prever_sarima_sem_exog(serie_cortada, origem):
    endog = pd.Series(serie_cortada['prec'].values, index=serie_cortada['ym'])
    res = SARIMAX(endog, order=SARIMAX_ORDER, seasonal_order=SARIMAX_SEASONAL_ORDER,
                  enforce_stationarity=False).fit(disp=False)
    fc = res.get_forecast(steps=HORIZON)
    return np.clip(fc.predicted_mean.values, 0, None)


# ══════════════════════════════════════════════════════════════════════════
# 5. FUTURO DAS EXÓGENAS — operacional vs oracle (Seções 3 e 4)
#
# Operacional: réplica do build_n34_path/gtsa/gpdo de update_dashboard.py
# (linhas 394-417), mas com duas divergências deliberadas e documentadas:
#   1. A amplitude do Gaussiano de Niño 3.4 usa persistência do último
#      valor REAL <= origem (produção usa o rótulo de cenário ENSO/IRI,
#      que não foi arquivado historicamente e não é reconstruível para
#      origens passadas).
#   2. TSA e PDO futuros usam persistência verdadeira (último valor real
#      para TSA; média dos últimos 3 meses para PDO — regra documentada
#      na armadilha 6 do CLAUDE.md) em vez da constante travada 0.44 que
#      o gerador de cenário de produção usa para TSA. A instrução da
#      tarefa pede "a mesma regra de fallback/persistência vigente no
#      pipeline" — lida aqui como a regra documentada/testada de
#      persistência (fetch_monthly_data.py/update_indices.py), não o
#      literal de update_dashboard.py::gtsa(). Divergência assumida e
#      reportada no item M da resposta final.
# Nota sobre dados: serie_subst.csv não guarda gap (NaN) para tsa/pdo —
# a persistência já é aplicada rio acima antes de chegar neste arquivo.
# Não há como distinguir aqui "real" de "já persistido" — por isso a
# "persistência" operacional deste módulo é, na prática, reler o último
# valor já gravado, e o "média dos últimos 3 meses" do PDO opera sobre
# esses mesmos valores (que podem já conter persistência anterior).
#
# Oracle: usa nino34/tsa/pdo REAIS da série COMPLETA (não da série
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

    modo='operacional': só enxerga serie_cortada (dado <= origem).
    modo='oracle_exog': usa nino34/tsa/pdo REAIS de serie_completa — só
    essas 3 colunas, nunca 'prec'.
    """
    horiz = pd.period_range(origem + 1, periods=HORIZON, freq='M')
    # Precisa de exógenas até p-2 do último mês do horizonte (para os
    # lags 2/3), o que pode alcançar até origem+10 — dentro dos meses
    # reais da série completa por construção de gerar_origens().
    if modo == 'operacional':
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

    elif modo == 'oracle_exog':
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
# 6. MODELO C — SARIMAX ATUAL (N34+TSA+PDO), estrutura idêntica à produção
# ══════════════════════════════════════════════════════════════════════════

def treinar_sarimax_exog(d_cortado):
    endog = pd.Series(d_cortado['prec'].values, index=d_cortado['ym'])
    exog = pd.DataFrame({'n34_l23': d_cortado['n34_l23'].values,
                          'tsa_l23': d_cortado['tsa_l23'].values,
                          'pdo_l23': d_cortado['pdo_l23'].values}, index=endog.index)
    res = SARIMAX(endog, exog=exog, order=SARIMAX_ORDER, seasonal_order=SARIMAX_SEASONAL_ORDER,
                  enforce_stationarity=False).fit(disp=False)
    return res


def prever_sarimax_exog(res, exog_futuro):
    fc = res.get_forecast(steps=HORIZON, exog=exog_futuro[['n34_l23', 'tsa_l23', 'pdo_l23']].values)
    return np.clip(fc.predicted_mean.values, 0, None)


# ══════════════════════════════════════════════════════════════════════════
# 7. MODELO D — XGBOOST ATUAL — mesmas features/hiperparâmetros da produção
#    Multi-step recursivo (Seção 5): M+1 pode usar prec observada <= T;
#    M+2..M+12 usam a PREVISÃO do passo anterior, nunca a prec real
#    (que nem está disponível — o horizonte é sempre > origem).
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
# 8. UMA ORIGEM — roda os 4 modelos, 2 modos (quando aplicável)
# ══════════════════════════════════════════════════════════════════════════

def classificar_enso(nino34_origem):
    if nino34_origem <= ENSO_LA_NINA_MAX:
        return 'La Nina'
    if nino34_origem >= ENSO_EL_NINO_MIN:
        return 'El Nino'
    return 'Neutro'


def rodar_origem(serie, serie_cortada, origem):
    """Devolve lista de registros de previsão (um por lead/modelo/modo)
    para esta origem, mais o diagnóstico de tempo gasto."""
    t0 = time.time()
    registros = []

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
                'observado': obs, 'modelo': modelo, 'modo': modo, 'previsto': round(prev, 3),
                'erro': (round(prev - obs, 3) if obs is not None else None),
                'nino34_origem': round(nino34_origem, 3), 'classe_enso_origem': classe_enso,
            })

    # A — climatologia
    registrar('Climatologia', 'operacional', prever_climatologia(serie_cortada, origem))

    # B — SARIMA sem exógenas
    registrar('SARIMA_sem_exog', 'operacional', prever_sarima_sem_exog(serie_cortada, origem))

    # Lags — leakage-safe: shift() roda DEPOIS do corte (ver construir_lags)
    d_cortado = construir_lags(serie_cortada)

    # C — SARIMAX atual: 1 fit, 2 forecasts (operacional / oracle)
    res_sarimax = treinar_sarimax_exog(d_cortado)
    exog_op = montar_exog_futuro(serie_cortada, serie, origem, 'operacional')
    exog_or = montar_exog_futuro(serie_cortada, serie, origem, 'oracle_exog')
    registrar('SARIMAX_atual', 'operacional', prever_sarimax_exog(res_sarimax, exog_op))
    registrar('SARIMAX_atual', 'oracle_exog', prever_sarimax_exog(res_sarimax, exog_or))

    # D — XGBoost atual: 1 fit, 2 previsões recursivas
    model_xgb = treinar_xgb(d_cortado)
    registrar('XGBoost_atual', 'operacional', prever_xgb_recursivo(model_xgb, d_cortado, exog_op))
    registrar('XGBoost_atual', 'oracle_exog', prever_xgb_recursivo(model_xgb, d_cortado, exog_or))

    return registros, time.time() - t0


# ══════════════════════════════════════════════════════════════════════════
# 9. MÉTRICAS (Seções 6-8)
# ══════════════════════════════════════════════════════════════════════════

def _rmse(obs, prev):
    obs, prev = np.asarray(obs), np.asarray(prev)
    return float(np.sqrt(np.mean((obs - prev) ** 2)))


def _mae(obs, prev):
    obs, prev = np.asarray(obs), np.asarray(prev)
    return float(np.mean(np.abs(obs - prev)))


def _bias(obs, prev):
    obs, prev = np.asarray(obs), np.asarray(prev)
    return float(np.mean(prev - obs))


def _r2(obs, prev):
    obs, prev = np.asarray(obs), np.asarray(prev)
    ss_tot = np.sum((obs - obs.mean()) ** 2)
    if ss_tot <= 0:
        return None
    ss_res = np.sum((obs - prev) ** 2)
    return float(1 - ss_res / ss_tot)


def _metricas(obs, prev):
    return {'n': len(obs), 'rmse': round(_rmse(obs, prev), 2), 'mae': round(_mae(obs, prev), 2),
            'bias': round(_bias(obs, prev), 2), 'r2': (round(_r2(obs, prev), 4) if _r2(obs, prev) is not None else None)}


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


def calcular_skill(metrics_by_lead, metrics_by_block):
    """Skill_RMSE = 1 - RMSE_modelo / RMSE_climatologia. modo='operacional'
    só (climatologia não tem oracle)."""
    clim_lead = metrics_by_lead.get('Climatologia', {}).get('operacional', {})
    clim_block = metrics_by_block.get('Climatologia', {}).get('operacional', {})
    skill = {}
    for modelo in MODELOS:
        if modelo == 'Climatologia':
            continue
        skill[modelo] = {}
        for modo in (['operacional'] if modelo not in MODELOS_COM_ORACLE else ['operacional', 'oracle_exog']):
            por_lead = metrics_by_lead.get(modelo, {}).get(modo)
            if not por_lead:
                continue
            sk_lead = {}
            for lead, m in por_lead.items():
                rc = clim_lead.get(lead, {}).get('rmse')
                sk_lead[lead] = round(1 - m['rmse'] / rc, 4) if rc else None
            por_bloco = metrics_by_block.get(modelo, {}).get(modo, {})
            sk_bloco = {}
            for nome, m in por_bloco.items():
                rc = clim_block.get(nome, {}).get('rmse')
                sk_bloco[nome] = round(1 - m['rmse'] / rc, 4) if rc else None
            skill[modelo][modo] = {'por_lead': sk_lead, 'por_bloco': sk_bloco}
    return skill


def calcular_metricas_enso(df):
    df = df.dropna(subset=['observado'])
    resultado = {}
    for classe, g_classe in df.groupby('classe_enso_origem'):
        n_origens = g_classe['origem'].nunique()
        resultado[classe] = {
            'n_origens': int(n_origens),
            'amostra_insuficiente': bool(n_origens < ENSO_AMOSTRA_MINIMA),
            'metricas': {
                f'{modelo}|{modo}': _metricas(g['observado'], g['previsto'])
                for (modelo, modo), g in g_classe.groupby(['modelo', 'modo'])
            },
        }
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# 10. ORQUESTRAÇÃO
# ══════════════════════════════════════════════════════════════════════════

def _git_sha():
    try:
        r = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def executar_backtest(origens=None, verbose=True):
    """Roda o backtest para a lista de origens dada (todas, se None).
    Não grava nada em disco — devolve (df_predictions, metadata_extra).
    Usado tanto pelo main() (grava depois) quanto pelos testes (não grava)."""
    serie = carregar_serie()
    if origens is None:
        origens = gerar_origens(serie)

    todos_registros = []
    tempos = []
    for i, origem in enumerate(origens):
        serie_cortada = cortar_serie(serie, origem)
        registros, dt = rodar_origem(serie, serie_cortada, origem)
        todos_registros.extend(registros)
        tempos.append(dt)
        if verbose:
            print(f"  [{i+1}/{len(origens)}] origem={origem}  ({dt:.2f}s)")

    df = pd.DataFrame(todos_registros)
    extra = {'tempos': tempos, 'origens': [str(o) for o in origens], 'serie': serie}
    return df, extra


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--smoke', action='store_true', help='roda só 2 origens, não grava em disco (checagem rápida)')
    args = ap.parse_args()

    serie = carregar_serie()
    todas_origens = gerar_origens(serie)
    origens = todas_origens[:2] if args.smoke else todas_origens

    print(f"Backtest — {len(origens)} origens ({'smoke test' if args.smoke else 'completo'})")
    print(f"  Primeira origem: {todas_origens[0]}   Última origem: {todas_origens[-1]}")
    print(f"  Total de origens (config completa): {len(todas_origens)}   Horizonte: {HORIZON}   Passo: {STEP}")
    print(f"  Mínimo de treino: {MIN_TRAIN_MONTHS} meses ({MIN_TRAIN_MONTHS/12:.0f} anos)")

    t0 = time.time()
    df, extra = executar_backtest(origens, verbose=True)
    tempo_total = time.time() - t0
    print(f"\n  Tempo total: {tempo_total:.1f}s  ({tempo_total/len(origens):.2f}s/origem)")

    metrics_by_lead, metrics_by_block, overall = calcular_metricas(df)
    skill = calcular_skill(metrics_by_lead, metrics_by_block)
    enso = calcular_metricas_enso(df)

    metadata = {
        'data_execucao': pd.Timestamp.now().isoformat(),
        'git_sha': _git_sha(),
        'primeira_origem': str(todas_origens[0]),
        'ultima_origem': str(todas_origens[-1]),
        'n_origens_config_completa': len(todas_origens),
        'n_origens_nesta_execucao': len(origens),
        'horizonte': HORIZON,
        'passo_meses': STEP,
        'min_treino_meses': MIN_TRAIN_MONTHS,
        'periodo_base_serie': f"{serie['ym'].min()} a {serie['ym'].max()}",
        'tempo_total_segundos': round(tempo_total, 1),
        'tempo_medio_por_origem_segundos': round(tempo_total / len(origens), 2),
        'metodologia': 'SARIMAX(1,0,2)(1,1,1,12) e XGBoost idênticos a update_dashboard.py '
                        '(hiperparâmetros replicados, não importados); expanding window, '
                        'origens trimestrais, horizonte 12 meses.',
        'smoke_test': args.smoke,
    }

    resultado = {
        'metadata': metadata,
        'models': MODELOS,
        'metrics_by_lead': metrics_by_lead,
        'metrics_by_horizon_block': metrics_by_block,
        'overall_metrics': overall,
        'skill_vs_climatology': skill,
        'enso_regime_metrics': enso,
    }

    if not args.smoke:
        out_json = DATA / 'backtest_results.json'
        out_csv = DATA / 'backtest_predictions.csv'
        out_json.write_text(json.dumps(resultado, ensure_ascii=False, indent=2))
        df.drop(columns=[]).to_csv(out_csv, index=False)
        print(f"\n  ✅ {out_json.relative_to(ROOT)}")
        print(f"  ✅ {out_csv.relative_to(ROOT)}")
    else:
        print("\n  (smoke test — nada gravado em disco)")

    print(json.dumps({k: v for k, v in overall.items()}, indent=2, ensure_ascii=False))
    return resultado, df


if __name__ == '__main__':
    main()
