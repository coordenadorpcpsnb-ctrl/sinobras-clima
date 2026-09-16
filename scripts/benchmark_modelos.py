#!/usr/bin/env python3
"""
scripts/benchmark_modelos.py — Fase 1.2: benchmark de especificação

Pergunta: antes de adicionar informação climática nova (RONI/TNA/NMME/
C3S — nenhuma delas é tocada aqui), existe uma especificação estatística
do MESMO conjunto de dados atual (mesma prec/nino34/tsa/pdo) que supera
de forma robusta a climatologia? A Fase 1.1 mostrou que o SARIMAX atual
não tem essa evidência (IC95% do skill inclui zero).

Reaproveita scripts/backtest.py por IMPORT direto — backtest.py não tem
efeito colateral de import (diferente de update_dashboard.py, que roda o
pipeline inteiro só de ser importado), então importar é seguro e evita
duplicar as regras anti-leakage já endurecidas/testadas nas Fases 1/1.1.
Decisão: não foi criado scripts/_backtest_utils.py — a extração não
reduziria duplicação real, bastou importar backtest.py.

Reaproveita também os resultados JÁ COMPUTADOS da Fase 1.1 em STEP=1 para
os modelos de referência (Climatologia, SARIMA_sem_exog, SARIMAX_atual,
XGBoost_atual, SeasonalNaive) em vez de recalculá-los — mesma série,
mesmo desenho temporal, resultado idêntico por construção; recomputar
seria ~23 minutos de CPU sem nenhum ganho de informação. Ver
`carregar_referencia_fase11()`.

Screening vs confirmação (Seção 14 da tarefa): a grade de candidatos
novos é grande demais para rodar STEP=1 completo (357 origens) em todos
de uma vez num tempo de sessão razoável. Por isso:
  1. SCREENING (`--screening`): todos os candidatos novos rodam num
     subconjunto mais espaçado de origens (`--step-screening`, default 6).
  2. CONFIRMAÇÃO (`--confirmacao --modelos "..."`): só os candidatos que
     pareceram promissores no screening são re-rodados no STEP=1 completo.
  3. MERGE (`--merge`): junta screening + confirmação + referência da
     Fase 1.1 num único par de arquivos finais, com a coluna `fase`
     dizendo exatamente a proveniência de cada linha — nunca reportado
     como avaliação STEP=1 completa quando na verdade é só screening.

Rode com:
    python scripts/benchmark_modelos.py --screening
    python scripts/benchmark_modelos.py --confirmacao --modelos "SARIMAX_anom_E2_exog,Ridge_anom"
    python scripts/benchmark_modelos.py --merge
"""

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.linear_model import RidgeCV, ElasticNetCV
from sklearn.model_selection import TimeSeriesSplit

sys.path.insert(0, str(Path(__file__).parent))
import backtest as bt  # noqa: E402 — reaproveita funções leakage-safe, ver docstring

warnings.filterwarnings('ignore')

ROOT = bt.ROOT
DATA = bt.DATA

# ══════════════════════════════════════════════════════════════════════════
# Convergência (Seção 9 da tarefa): maxiter=200 só neste módulo de
# diagnóstico/backtest — nunca em produção. A Fase 1.1 mostrou que isso
# resolve a convergência sem mudar o RMSE de forma material.
# ══════════════════════════════════════════════════════════════════════════
MAXITER_PADRAO = 200

# ══════════════════════════════════════════════════════════════════════════
# Grades pequenas e fixas (Seção 3/4 da tarefa) — não expandir automaticamente
# ══════════════════════════════════════════════════════════════════════════
GRADE_ARIMA_ANOMALIA = [
    ('E1', (1, 0, 1), (0, 0, 0, 0)),
    ('E2', (1, 0, 2), (0, 0, 0, 0)),
    ('E3', (1, 0, 1), (1, 0, 0, 12)),
    ('E4', (1, 0, 1), (0, 0, 1, 12)),
]
GRADE_HARMONICO = [('harm1', 1), ('harm2', 2)]
ARMA_ORDER_HARMONICO = (1, 0, 1)

FEATURES_LINEAR = ['alvo_l1', 'alvo_l2', 'alvo_l3', 'alvo_l6', 'alvo_l12',
                    'n34_l23', 'tsa_l23', 'pdo_l23', 'mes_sin', 'mes_cos']

# Piso de segurança para o desvio-padrão mensal usado no z-score: 1mm é
# pequeno frente a qualquer desvio mensal observado na série real (mesmo
# jun-ago, os meses mais secos, têm desvio de vários mm em qualquer janela
# de treino com >=15 anos) — só ativa em casos degenerados (ex.: poucos
# valores idênticos numa janela de treino muito curta), sem alterar o
# cálculo normal.
DESVIO_MINIMO_MM = 1.0

# Classificação operacional (Seção 7) a partir da climatologia de
# referência já documentada em CLAUDE.md (CLIM_JAN_DEZ, 1981-2025).
# Regra objetiva, com dois limiares que caem exatamente nos saltos
# naturais dos dados (não são cortes arbitrários):
#   seco: <20mm — jun(15.6)/jul(6.4)/ago(10.4); o próximo valor mais alto
#         é set(41.7), quase 3x maior.
#   chuvoso: >=150mm — a sequência CRONOLOGICAMENTE CONTÍGUA nov-dez-jan-
#         fev-mar-abr (159,200,267,282,308,220) fica toda acima; o mês
#         seguinte (mai=83,1) cai bem abaixo do limiar.
#   transição: os 3 meses restantes (mai, set, out), atribuídos por
#         adjacência cronológica ao bloco mais próximo — mai fica entre
#         abr(chuvoso) e jun(seco) => "chuva->seca"; set/out ficam entre
#         ago(seco) e nov(chuvoso) => "seca->chuva".
CLIM_JAN_DEZ = [267.3, 282.3, 308.4, 220.4, 83.1, 15.6, 6.4, 10.4, 41.7, 119.7, 159.2, 199.9]
LIMIAR_SECO_MM = 20.0
LIMIAR_CHUVOSO_MM = 150.0

MES_PARA_ESTACAO = {12: 'DJF', 1: 'DJF', 2: 'DJF', 3: 'MAM', 4: 'MAM', 5: 'MAM',
                     6: 'JJA', 7: 'JJA', 8: 'JJA', 9: 'SON', 10: 'SON', 11: 'SON'}


def classificar_periodo_operacional(mes):
    v = CLIM_JAN_DEZ[mes - 1]
    if v < LIMIAR_SECO_MM:
        return 'seco'
    if v >= LIMIAR_CHUVOSO_MM:
        return 'chuvoso'
    if mes in (9, 10):
        return 'transicao_seca_chuva'
    return 'transicao_chuva_seca'   # mai


# ══════════════════════════════════════════════════════════════════════════
# 1. REPRESENTAÇÕES DO TARGET (Seção 2) — climatologia SEMPRE recalculada
#    por origem, usando SÓ serie_cortada (dado <= origem). Nunca a
#    climatologia 1981-2025 inteira.
# ══════════════════════════════════════════════════════════════════════════

def climatologia_media_desvio(serie_cortada):
    g = serie_cortada.groupby('mes')['prec']
    media = g.mean()
    desvio = g.std(ddof=0)
    return media, desvio


def desvio_seguro(desvio_series):
    return desvio_series.clip(lower=DESVIO_MINIMO_MM)


def serie_para_anomalia(df, media):
    return (df['prec'] - df['mes'].map(media)).values


def serie_para_z(df, media, desvio_seg):
    anom = df['prec'] - df['mes'].map(media)
    return (anom / df['mes'].map(desvio_seg)).values


def transformar_de_volta(pred_transformado, meses_futuros, media, desvio_seg, representacao):
    """Clipping em zero SÓ depois da transformação inversa (Seção 2)."""
    media_futuro = media.reindex(meses_futuros).values
    if representacao == 'anom':
        preds_mm = pred_transformado + media_futuro
    elif representacao == 'z':
        desvio_futuro = desvio_seg.reindex(meses_futuros).values
        preds_mm = pred_transformado * desvio_futuro + media_futuro
    else:
        raise ValueError(f"representação inválida: {representacao}")
    return np.clip(preds_mm, 0, None)


# ══════════════════════════════════════════════════════════════════════════
# 2. MODELOS E/F — SARIMAX sobre anomalia / anomalia padronizada (Seção 3)
#    fit-once-forecast-once (só modo operacional_simulado nesta fase — ver
#    limitação registrada no relatório final, item S).
# ══════════════════════════════════════════════════════════════════════════

def treinar_sarimax_representacao(serie_cortada, d_cortado, order, seasonal_order,
                                   representacao, com_exog, maxiter=MAXITER_PADRAO):
    media, desvio = climatologia_media_desvio(serie_cortada)
    desvio_seg = desvio_seguro(desvio)
    base_df = d_cortado if com_exog else serie_cortada
    if representacao == 'anom':
        y = serie_para_anomalia(base_df, media)
    else:
        y = serie_para_z(base_df, media, desvio_seg)
    endog = pd.Series(y, index=pd.PeriodIndex(base_df['ym'], freq='M'))
    exog = None
    if com_exog:
        exog = pd.DataFrame({'n34_l23': d_cortado['n34_l23'].values,
                              'tsa_l23': d_cortado['tsa_l23'].values,
                              'pdo_l23': d_cortado['pdo_l23'].values}, index=endog.index)
    res, diag = bt._fit_sarimax_diag(endog, exog=exog, order=order, seasonal_order=seasonal_order,
                                      maxiter=maxiter)
    return res, diag, media, desvio_seg


def prever_sarimax_representacao(res, media, desvio_seg, origem, representacao, com_exog, exog_futuro=None):
    if com_exog:
        fc = res.get_forecast(steps=bt.HORIZON, exog=exog_futuro[['n34_l23', 'tsa_l23', 'pdo_l23']].values)
    else:
        fc = res.get_forecast(steps=bt.HORIZON)
    horiz = pd.period_range(origem + 1, periods=bt.HORIZON, freq='M')
    meses_futuros = np.array([p.month for p in horiz])
    return transformar_de_volta(fc.predicted_mean.values, meses_futuros, media, desvio_seg, representacao)


# ══════════════════════════════════════════════════════════════════════════
# 3. MODELO HARMÔNICO + ARMA (Seção 4) — sazonalidade suave via
#    sin/cos(mês) como exógena determinística (SEMPRE conhecida, nunca
#    precisa de simulação — não há vazamento possível aqui), erro ARMA(1,0,1)
#    fixo, seasonal_order=(0,0,0,0). Roda sobre prec RAW (não anomalia): é
#    uma forma alternativa de tratar sazonalidade, não uma composição com
#    a transformação de anomalia.
# ══════════════════════════════════════════════════════════════════════════

def features_harmonicas(meses, n_harm):
    cols = {}
    for h in range(1, n_harm + 1):
        cols[f'sin{h}'] = np.sin(2 * np.pi * h * meses / 12)
        cols[f'cos{h}'] = np.cos(2 * np.pi * h * meses / 12)
    return pd.DataFrame(cols)


def treinar_harmonico(serie_cortada, n_harm, maxiter=MAXITER_PADRAO):
    meses = serie_cortada['mes'].values
    idx = pd.PeriodIndex(serie_cortada['ym'], freq='M')
    exog = features_harmonicas(meses, n_harm)
    exog.index = idx
    endog = pd.Series(serie_cortada['prec'].values, index=idx)
    res, diag = bt._fit_sarimax_diag(endog, exog=exog, order=ARMA_ORDER_HARMONICO,
                                      seasonal_order=(0, 0, 0, 0), maxiter=maxiter)
    return res, diag


def prever_harmonico(res, origem, n_harm):
    horiz = pd.period_range(origem + 1, periods=bt.HORIZON, freq='M')
    meses_futuros = np.array([p.month for p in horiz])
    exog_futuro = features_harmonicas(meses_futuros, n_harm)
    fc = res.get_forecast(steps=bt.HORIZON, exog=exog_futuro.values)
    return np.clip(fc.predicted_mean.values, 0, None)


# ══════════════════════════════════════════════════════════════════════════
# 4. MODELO G — RIDGE / ELASTIC NET (Seção 3) — recursivo (mesma estrutura
#    do XGBoost atual, só troca a família de modelo), para comparação
#    direta "família recursiva" entre um modelo linear regularizado e o
#    XGBoost atual. alpha (e l1_ratio) escolhidos só dentro do treino via
#    CV temporal (TimeSeriesSplit) — nunca toca no horizonte de teste.
# ══════════════════════════════════════════════════════════════════════════

def construir_features_lineares(serie_cortada, d_cortado, representacao):
    media, desvio = climatologia_media_desvio(serie_cortada)
    desvio_seg = desvio_seguro(desvio)
    d = d_cortado.copy()
    if representacao == 'anom':
        d['alvo'] = d['prec'] - d['mes'].map(media)
    else:
        d['alvo'] = (d['prec'] - d['mes'].map(media)) / d['mes'].map(desvio_seg)
    for L in [1, 2, 3, 6, 12]:
        d[f'alvo_l{L}'] = d['alvo'].shift(L)
    d['mes_sin'] = np.sin(2 * np.pi * d['mes'] / 12)
    d['mes_cos'] = np.cos(2 * np.pi * d['mes'] / 12)
    d = d.dropna(subset=[f'alvo_l{L}' for L in [1, 2, 3, 6, 12]]).reset_index(drop=True)
    return d, media, desvio_seg


def treinar_ridge(d_feat, alphas=None):
    alphas = alphas if alphas is not None else np.logspace(-2, 2, 9)
    X, y = d_feat[FEATURES_LINEAR].values, d_feat['alvo'].values
    n_splits = min(5, len(d_feat) - 1)
    modelo = RidgeCV(alphas=alphas, cv=TimeSeriesSplit(n_splits=n_splits))
    modelo.fit(X, y)
    return modelo


def treinar_elasticnet(d_feat, l1_ratios=(0.1, 0.5, 0.9), n_alphas=10):
    X, y = d_feat[FEATURES_LINEAR].values, d_feat['alvo'].values
    n_splits = min(5, len(d_feat) - 1)
    modelo = ElasticNetCV(l1_ratio=list(l1_ratios), alphas=n_alphas, eps=1e-3,
                           max_iter=5000, cv=TimeSeriesSplit(n_splits=n_splits))
    modelo.fit(X, y)
    return modelo


def prever_linear_recursivo(modelo, d_feat, media, desvio_seg, origem, representacao, exog_futuro):
    alvo_buf = list(d_feat['alvo'].values)
    horiz = exog_futuro.index
    preds_transf = []
    for p, row in zip(horiz, exog_futuro.itertuples()):
        X_step = np.array([[
            alvo_buf[-1] if len(alvo_buf) >= 1 else 0,
            alvo_buf[-2] if len(alvo_buf) >= 2 else 0,
            alvo_buf[-3] if len(alvo_buf) >= 3 else 0,
            alvo_buf[-6] if len(alvo_buf) >= 6 else 0,
            alvo_buf[-12] if len(alvo_buf) >= 12 else 0,
            row.n34_l23, row.tsa_l23, row.pdo_l23,
            np.sin(2 * np.pi * p.month / 12), np.cos(2 * np.pi * p.month / 12),
        ]])
        pred = float(modelo.predict(X_step)[0])
        preds_transf.append(pred)
        alvo_buf.append(pred)
    meses_futuros = np.array([p.month for p in horiz])
    return transformar_de_volta(np.array(preds_transf), meses_futuros, media, desvio_seg, representacao)


# ══════════════════════════════════════════════════════════════════════════
# 5. MODELO H — XGBOOST DIRETO POR HORIZONTE (Seção 3) — um estimador
#    independente por lead (1..12). Desenho deliberado: todas as features
#    (inclusive n34_l23/tsa_l23/pdo_l23) são avaliadas NO PRÓPRIO INSTANTE
#    t de cada linha de treino — nunca "no futuro" — e a previsão real usa
#    o estado NA ORIGEM (t=origem) para prever origem+k diretamente. Isso
#    testa a recursão isoladamente: não precisa simular exógena futura
#    (diferente do XGBoost atual/SARIMAX, que precisam do path Gaussiano
#    simulado para leads >=3), porque o "preditor" nunca avança no tempo —
#    só a distância entre a feature (sempre em t=origem) e o alvo (t+k) é
#    que muda por modelo.
# ══════════════════════════════════════════════════════════════════════════

FEATURES_XGB_DIRETO = ['alvo_l1', 'alvo_l2', 'alvo_l3', 'alvo_l6', 'alvo_l12',
                        'n34_l23', 'tsa_l23', 'pdo_l23', 'mes_sin', 'mes_cos']
MIN_AMOSTRA_XGB_DIRETO = 24


def treinar_xgb_direto(serie_cortada, d_cortado, representacao='anom'):
    media, desvio = climatologia_media_desvio(serie_cortada)
    desvio_seg = desvio_seguro(desvio)
    d = d_cortado.copy()
    if representacao == 'anom':
        d['alvo'] = d['prec'] - d['mes'].map(media)
    else:
        d['alvo'] = (d['prec'] - d['mes'].map(media)) / d['mes'].map(desvio_seg)
    for L in [1, 2, 3, 6, 12]:
        d[f'alvo_l{L}'] = d['alvo'].shift(L)
    d['mes_sin'] = np.sin(2 * np.pi * d['mes'] / 12)
    d['mes_cos'] = np.cos(2 * np.pi * d['mes'] / 12)

    modelos = {}
    for k in range(1, bt.HORIZON + 1):
        d[f'alvo_fut_{k}'] = d['alvo'].shift(-k)
        treino = d.dropna(subset=FEATURES_XGB_DIRETO + [f'alvo_fut_{k}'])
        if len(treino) < MIN_AMOSTRA_XGB_DIRETO:
            modelos[k] = None
            continue
        X, y = treino[FEATURES_XGB_DIRETO].values, treino[f'alvo_fut_{k}'].values
        m = xgb.XGBRegressor(**bt.XGB_PARAMS)
        m.fit(X, y)
        modelos[k] = m

    ultima_linha = d.dropna(subset=FEATURES_XGB_DIRETO).iloc[[-1]]
    X_origem = ultima_linha[FEATURES_XGB_DIRETO].values
    return modelos, X_origem, media, desvio_seg


def prever_xgb_direto(modelos, X_origem, media, desvio_seg, origem, representacao):
    horiz = pd.period_range(origem + 1, periods=bt.HORIZON, freq='M')
    meses_futuros = np.array([p.month for p in horiz])
    preds_transf = np.array([
        float(modelos[k].predict(X_origem)[0]) if modelos[k] is not None else np.nan
        for k in range(1, bt.HORIZON + 1)
    ])
    return transformar_de_volta(preds_transf, meses_futuros, media, desvio_seg, representacao)


# ══════════════════════════════════════════════════════════════════════════
# 6. GRADE DE CANDIDATOS E ORQUESTRAÇÃO POR ORIGEM
# ══════════════════════════════════════════════════════════════════════════

def gerar_specs_candidatos():
    specs = []
    for cfg_name, order, seasonal_order in GRADE_ARIMA_ANOMALIA:
        for representacao in ['anom', 'z']:
            prefixo = 'SARIMAX_anom' if representacao == 'anom' else 'SARIMAX_z'
            for com_exog in [False, True]:
                nome = f"{prefixo}_{cfg_name}_{'exog' if com_exog else 'semexog'}"
                specs.append((nome, 'sarimax_repr', dict(order=order, seasonal_order=seasonal_order,
                                                          representacao=representacao, com_exog=com_exog)))
    for nome_h, n_harm in GRADE_HARMONICO:
        specs.append((f'Harmonico_{nome_h}', 'harmonico', dict(n_harm=n_harm)))
    specs.append(('Ridge_anom', 'linear', dict(representacao='anom', tipo_linear='ridge')))
    specs.append(('Ridge_z', 'linear', dict(representacao='z', tipo_linear='ridge')))
    specs.append(('ElasticNet_anom', 'linear', dict(representacao='anom', tipo_linear='elasticnet')))
    specs.append(('XGBoost_direto_anom', 'xgb_direto', dict(representacao='anom')))
    return specs


NOMES_TODOS_CANDIDATOS = [nome for nome, _, _ in gerar_specs_candidatos()]


def rodar_origem_benchmark(serie, origem, specs, maxiter=MAXITER_PADRAO):
    t0 = time.time()
    serie_cortada = bt.cortar_serie(serie, origem)
    d_cortado = bt.construir_lags(serie_cortada)
    media, desvio = climatologia_media_desvio(serie_cortada)
    desvio_seg = desvio_seguro(desvio)

    horiz = pd.period_range(origem + 1, periods=bt.HORIZON, freq='M')
    observado = {p: serie.loc[serie['ym'] == p, 'prec'] for p in horiz}
    observado = {p: (float(v.iloc[0]) if len(v) else None) for p, v in observado.items()}
    nino34_origem = float(serie_cortada['nino34'].iloc[-1])
    classe_enso = bt.classificar_enso(nino34_origem)

    exog_op = bt.montar_exog_futuro(serie_cortada, serie, origem, bt.MODO_OPERACIONAL)

    registros, diag_registros = [], []

    def registrar(modelo, preds):
        for lead, p in enumerate(horiz, start=1):
            obs = observado[p]
            v = preds[lead - 1]
            prev = float(v) if (v is not None and not (isinstance(v, float) and np.isnan(v))) else None
            registros.append({
                'origem': str(origem), 'data_prevista': str(p), 'lead': lead, 'mes_alvo': p.month,
                'observado': obs, 'modelo': modelo, 'modo': bt.MODO_OPERACIONAL,
                'previsto': (round(prev, 3) if prev is not None else None),
                'erro': (round(prev - obs, 3) if (prev is not None and obs is not None) else None),
                'nino34_origem': round(nino34_origem, 3), 'classe_enso_origem': classe_enso,
                'clim_media_mes': round(float(media.get(p.month, np.nan)), 3),
                'clim_desvio_mes': round(float(desvio_seg.get(p.month, np.nan)), 3),
                'estacao': MES_PARA_ESTACAO[p.month],
                'periodo_operacional': classificar_periodo_operacional(p.month),
            })

    for nome, tipo, params in specs:
        try:
            if tipo == 'sarimax_repr':
                res, diag, med, dsv = treinar_sarimax_representacao(
                    serie_cortada, d_cortado, params['order'], params['seasonal_order'],
                    params['representacao'], params['com_exog'], maxiter=maxiter)
                diag_registros.append({'modelo': nome, 'origem': str(origem), **diag})
                preds = prever_sarimax_representacao(
                    res, med, dsv, origem, params['representacao'], params['com_exog'],
                    exog_futuro=exog_op if params['com_exog'] else None)
                registrar(nome, preds)
            elif tipo == 'harmonico':
                res, diag = treinar_harmonico(serie_cortada, params['n_harm'], maxiter=maxiter)
                diag_registros.append({'modelo': nome, 'origem': str(origem), **diag})
                preds = prever_harmonico(res, origem, params['n_harm'])
                registrar(nome, preds)
            elif tipo == 'linear':
                d_feat, med, dsv = construir_features_lineares(serie_cortada, d_cortado, params['representacao'])
                treinar = treinar_ridge if params['tipo_linear'] == 'ridge' else treinar_elasticnet
                modelo = treinar(d_feat)
                preds = prever_linear_recursivo(modelo, d_feat, med, dsv, origem, params['representacao'], exog_op)
                registrar(nome, preds)
            elif tipo == 'xgb_direto':
                modelos12, X_origem, med, dsv = treinar_xgb_direto(serie_cortada, d_cortado, params['representacao'])
                preds = prever_xgb_direto(modelos12, X_origem, med, dsv, origem, params['representacao'])
                registrar(nome, preds)
        except Exception as e:
            registrar(nome, [np.nan] * bt.HORIZON)
            diag_registros.append({'modelo': nome, 'origem': str(origem), 'converged': False,
                                    'erro_execucao': str(e)[:200]})

    return registros, diag_registros, time.time() - t0


# ══════════════════════════════════════════════════════════════════════════
# 7. REAPROVEITAMENTO DOS RESULTADOS DA FASE 1.1 (referência, não recomputado)
# ══════════════════════════════════════════════════════════════════════════

def carregar_referencia_fase11():
    caminho = DATA / 'backtest_predictions_step1.csv'
    if not caminho.exists():
        return pd.DataFrame()
    df = pd.read_csv(caminho)
    df = df[df['modo'] == bt.MODO_OPERACIONAL].copy()
    df['estacao'] = df['mes_alvo'].map(MES_PARA_ESTACAO)
    df['periodo_operacional'] = df['mes_alvo'].map(classificar_periodo_operacional)
    df['fase'] = 'referencia_fase11'
    # clim_media_mes / clim_desvio_mes recomputados por origem (não estavam
    # no CSV da Fase 1.1) — necessário para o RMSE padronizado da Seção 6.
    return df


def anexar_clim_media_desvio(df, serie):
    """Preenche clim_media_mes/clim_desvio_mes ausentes usando a
    climatologia da própria origem de cada linha (mesma regra leakage-safe:
    só dados <= origem)."""
    faltando = df['clim_media_mes'].isna() if 'clim_media_mes' in df.columns else pd.Series(True, index=df.index)
    if 'clim_media_mes' not in df.columns:
        df['clim_media_mes'] = np.nan
        df['clim_desvio_mes'] = np.nan
        faltando = pd.Series(True, index=df.index)
    origens_faltando = df.loc[faltando, 'origem'].unique()
    cache = {}
    for origem_str in origens_faltando:
        origem = pd.Period(origem_str, 'M')
        if origem not in cache:
            serie_cortada = bt.cortar_serie(serie, origem)
            media, desvio = climatologia_media_desvio(serie_cortada)
            cache[origem] = (media, desvio_seguro(desvio))
        media, desvio_seg = cache[origem]
        idx = df.index[faltando & (df['origem'] == origem_str)]
        df.loc[idx, 'clim_media_mes'] = df.loc[idx, 'mes_alvo'].map(media).values
        df.loc[idx, 'clim_desvio_mes'] = df.loc[idx, 'mes_alvo'].map(desvio_seg).values
    return df


# ══════════════════════════════════════════════════════════════════════════
# 8. MÉTRICAS (reaproveita bt._metricas/_rmse/_mae/BLOCOS/bootstrap)
# ══════════════════════════════════════════════════════════════════════════

def calcular_metricas_padronizadas(df):
    """RMSE/MAE no espaço padronizado — erro / desvio climatológico do
    mês-alvo NAQUELA origem (Seção 6). Reduz a dominância dos meses
    chuvosos: distingue 'bom porque o mês é seco' de 'bom porque prevê
    bem a anomalia'."""
    d = df.dropna(subset=['observado', 'previsto', 'clim_desvio_mes'])
    d = d[d['clim_desvio_mes'] > 0]
    resultado = {}
    for (modelo, modo), g in d.groupby(['modelo', 'modo']):
        erro_norm = (g['previsto'] - g['observado']) / g['clim_desvio_mes']
        resultado.setdefault(modelo, {})[modo] = {
            'n': len(g),
            'rmse_padronizado': round(float(np.sqrt(np.mean(erro_norm ** 2))), 4),
            'mae_padronizado': round(float(np.mean(np.abs(erro_norm))), 4),
        }
    return resultado


def calcular_metricas_por_estacao(df):
    d = df.dropna(subset=['observado'])
    resultado = {}
    for (modelo, modo), g in d.groupby(['modelo', 'modo']):
        resultado.setdefault(modelo, {})[modo] = {
            estacao: bt._metricas(ge['observado'], ge['previsto'])
            for estacao, ge in g.groupby('estacao')
        }
    return resultado


def calcular_metricas_por_periodo_operacional(df):
    d = df.dropna(subset=['observado'])
    resultado = {}
    for (modelo, modo), g in d.groupby(['modelo', 'modo']):
        resultado.setdefault(modelo, {})[modo] = {
            periodo: bt._metricas(gp['observado'], gp['previsto'])
            for periodo, gp in g.groupby('periodo_operacional')
        }
    return resultado


def calcular_complexidade(especificacoes_relevantes):
    """especificacoes_relevantes: dict nome_modelo -> {'n_features':int,
    'n_parametros_aprox':int, 'descricao':str}. Preenchido manualmente por
    família (ver montar_relatorio_complexidade), não inferido em runtime."""
    return especificacoes_relevantes


# ══════════════════════════════════════════════════════════════════════════
# 9. ORQUESTRAÇÃO — screening / confirmação / merge
# ══════════════════════════════════════════════════════════════════════════

def rodar_lote(serie, origens, specs, maxiter=MAXITER_PADRAO, verbose=True):
    todos_registros, todos_diag, tempos = [], [], []
    for i, origem in enumerate(origens):
        registros, diag, dt = rodar_origem_benchmark(serie, origem, specs, maxiter=maxiter)
        todos_registros.extend(registros)
        todos_diag.extend(diag)
        tempos.append(dt)
        if verbose:
            print(f"  [{i+1}/{len(origens)}] origem={origem}  ({dt:.2f}s)")
    return pd.DataFrame(todos_registros), pd.DataFrame(todos_diag), tempos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--screening', action='store_true')
    ap.add_argument('--confirmacao', action='store_true')
    ap.add_argument('--merge', action='store_true')
    ap.add_argument('--modelos', type=str, default=None,
                     help='lista separada por vírgula de nomes de modelo (default: todos)')
    ap.add_argument('--step-screening', type=int, default=6)
    ap.add_argument('--smoke', action='store_true')
    ap.add_argument('--maxiter', type=int, default=MAXITER_PADRAO)
    args = ap.parse_args()

    if args.merge:
        merge_resultados()
        return

    serie = bt.carregar_serie()
    specs_todas = gerar_specs_candidatos()
    if args.modelos:
        nomes_pedidos = set(n.strip() for n in args.modelos.split(','))
        specs = [s for s in specs_todas if s[0] in nomes_pedidos]
        faltando = nomes_pedidos - {s[0] for s in specs}
        if faltando:
            raise SystemExit(f"Modelos não encontrados na grade: {faltando}")
    else:
        specs = specs_todas

    if args.confirmacao:
        origens = bt.gerar_origens(serie, step=bt.STEP_MENSAL)
        fase = 'confirmacao'
    else:
        origens = bt.gerar_origens(serie, step=args.step_screening)
        fase = 'screening'

    if args.smoke:
        origens = origens[:2]

    print(f"Fase 1.2 — {fase} — {len(specs)} candidatos x {len(origens)} origens")
    t0 = time.time()
    df, df_diag, tempos = rodar_lote(serie, origens, specs, maxiter=args.maxiter, verbose=True)
    tempo_total = time.time() - t0
    print(f"\n  Tempo total: {tempo_total:.1f}s  ({tempo_total/len(origens):.2f}s/origem)")

    df['fase'] = fase
    if args.smoke:
        print("\n  (smoke test — nada gravado em disco)")
        return

    sufixo = f'_{fase}'
    out_csv = DATA / f'model_benchmark_predictions{sufixo}.csv'
    out_diag = DATA / f'model_benchmark_convergence{sufixo}.csv'
    out_meta = DATA / f'model_benchmark_meta{sufixo}.json'
    df.to_csv(out_csv, index=False)
    df_diag.to_csv(out_diag, index=False)
    out_meta.write_text(json.dumps({
        'fase': fase, 'n_origens': len(origens), 'n_candidatos': len(specs),
        'candidatos': [s[0] for s in specs],
        'primeira_origem': str(origens[0]), 'ultima_origem': str(origens[-1]),
        'tempo_total_segundos': round(tempo_total, 1),
        'tempo_medio_por_origem_segundos': round(tempo_total / len(origens), 2),
        'maxiter': args.maxiter,
    }, indent=2, ensure_ascii=False))
    print(f"  ✅ {out_csv.relative_to(ROOT)}")
    print(f"  ✅ {out_diag.relative_to(ROOT)}")
    print(f"  ✅ {out_meta.relative_to(ROOT)}")


def merge_resultados():
    """Junta screening + confirmação + referência Fase 1.1 nos arquivos
    finais nomeados pela tarefa (Seção 12): data/model_benchmark_results.json
    e data/model_benchmark_predictions.csv. A coluna 'fase' preserva a
    proveniência de cada linha o tempo todo."""
    serie = bt.carregar_serie()
    partes = []

    ref = carregar_referencia_fase11()
    if not ref.empty:
        ref = anexar_clim_media_desvio(ref, serie)
        partes.append(ref)

    for fase in ['screening', 'confirmacao']:
        caminho = DATA / f'model_benchmark_predictions_{fase}.csv'
        if caminho.exists():
            d = pd.read_csv(caminho)
            partes.append(d)

    if not partes:
        raise SystemExit("Nenhum resultado encontrado para merge — rode --screening/--confirmacao primeiro")

    df = pd.concat(partes, ignore_index=True)

    metrics_by_lead, metrics_by_block, overall = bt.calcular_metricas(df)
    por_mes_alvo = bt.calcular_metricas_por_mes_alvo(df)
    padronizadas = calcular_metricas_padronizadas(df)
    por_estacao = calcular_metricas_por_estacao(df)
    por_periodo_op = calcular_metricas_por_periodo_operacional(df)
    skill = bt.calcular_skill(metrics_by_lead, metrics_by_block)

    candidatos_bootstrap = ['SARIMAX_atual', 'SARIMA_sem_exog', 'XGBoost_atual', 'SeasonalNaive'] + \
        [m for m in df['modelo'].unique() if m not in
         ('Climatologia', 'SARIMAX_atual', 'SARIMA_sem_exog', 'XGBoost_atual', 'SeasonalNaive')]
    bootstrap = {}
    for modelo in candidatos_bootstrap:
        if modelo not in df['modelo'].values:
            continue
        r = bt.bootstrap_ci_diff_rmse(df, modelo, modo=bt.MODO_OPERACIONAL, n_boot=2000, seed=42)
        bootstrap[modelo] = r

    fases_presentes = df.groupby('modelo')['fase'].unique().apply(list).to_dict()
    n_origens_por_fase = df.groupby('fase')['origem'].nunique().to_dict()

    resultado = {
        'metadata': {
            'data_execucao': pd.Timestamp.now().isoformat(),
            'git_sha': bt._git_sha(),
            'n_origens_por_fase': {k: int(v) for k, v in n_origens_por_fase.items()},
            'fases_por_modelo': fases_presentes,
            'aviso': 'métricas de modelos presentes SÓ na fase screening são exploratórias — '
                     'nunca avaliação imparcial de STEP=1 completo. Ver metadata.fases_por_modelo.',
            'maxiter_usado_nesta_fase': MAXITER_PADRAO,
        },
        'overall_metrics': overall,
        'metrics_by_lead': metrics_by_lead,
        'metrics_by_horizon_block': metrics_by_block,
        'metrics_by_target_month': por_mes_alvo,
        'metrics_padronizadas': padronizadas,
        'metrics_by_estacao': por_estacao,
        'metrics_by_periodo_operacional': por_periodo_op,
        'skill_vs_climatology': skill,
        'bootstrap_ci_vs_climatology': bootstrap,
    }

    out_json = DATA / 'model_benchmark_results.json'
    out_csv = DATA / 'model_benchmark_predictions.csv'
    out_json.write_text(json.dumps(resultado, ensure_ascii=False, indent=2))
    df.to_csv(out_csv, index=False)
    print(f"✅ {out_json.relative_to(ROOT)}")
    print(f"✅ {out_csv.relative_to(ROOT)}")
    print(f"Modelos incluídos: {sorted(df['modelo'].unique())}")
    print(f"Origens por fase: {n_origens_por_fase}")


if __name__ == '__main__':
    main()
