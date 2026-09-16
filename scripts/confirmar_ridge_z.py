#!/usr/bin/env python3
"""
scripts/confirmar_ridge_z.py — Fase 1.3: confirmação pós-seleção do Ridge_z

PROBLEMA DE SELEÇÃO (Seção 1): a Fase 1.2 comparou 27 especificações nas
MESMAS 357 origens e escolheu Ridge_z como a mais promissora. O IC95% do
skill do Ridge_z relatado ali NÃO corrige o efeito de seleção — é o IC de
"o melhor entre 27", que é sistematicamente mais otimista que o IC de uma
hipótese única pré-registrada. Esta fase trata Ridge_z como hipótese
PRÉ-DEFINIDA e testa se o ganho sobrevive:
  (a) num período de confirmação nunca usado para escolher o modelo
      (2016-01 em diante — fronteira fixada ANTES de olhar qualquer
      resultado desta fase, ver FRONTEIRA_CONFIRMACAO);
  (b) com bootstrap temporal robusto a múltiplos tamanhos de bloco;
  (c) também no espaço padronizado (lacuna explícita da Fase 1.2).

ESPECIFICAÇÃO CONGELADA (Seção 2): todas as funções que definem o Ridge_z
em si (`climatologia_media_desvio`, `desvio_seguro`, `serie_para_z`,
`construir_features_lineares`, `treinar_ridge`, `prever_linear_recursivo`,
`transformar_de_volta`, `FEATURES_LINEAR`) são IMPORTADAS de
benchmark_modelos.py, nunca redefinidas aqui — não há como esta fase
divergir silenciosamente da Fase 1.2, porque literalmente reusa o mesmo
código-objeto. `tests/test_confirmar_ridge_z.py::EspecificacaoCongeladaTestCase`
verifica isso lendo o texto-fonte (não importando), no mesmo padrão da
checagem de sincronia produção/backtest das Fases 1/1.1.

target=anomalia padronizada (z) por mês-calendário, calculada só com
dado <= origem; features=alvo_l{1,2,3,6,12} (lags da própria série z),
n34_l23/tsa_l23/pdo_l23 (mesmas exógenas atuais), mes_sin/mes_cos;
regularização=RidgeCV, alphas=logspace(-2,2,9), alpha escolhido só via
TimeSeriesSplit(5) dentro do treino de cada origem; multi-step=recursivo
(mesma estrutura do XGBoost/SARIMAX atuais); exógena futura=mesma lógica
operacional_simulado/oracle_exog do backtest.py; clipping em zero só
depois da transformação inversa z->mm.

Reaproveita (sem recomputar) as previsões já geradas para Climatologia,
SARIMAX_atual e SARIMAX_anom_E2_exog (referência secundária) em
data/model_benchmark_predictions.csv — essas não mudam entre fases.

Ablação (Seção 8) e oracle_exog (Seção 9) são NOVOS cálculos desta fase
(não existiam na Fase 1.2), mas usam explicitamente a MESMA estrutura de
recursão e a MESMA climatologia por origem — só o conjunto de features ou
o modo de exógena futura muda. Nada disso promove um "novo vencedor":
são diagnósticos, não retunagem.

Rode com:
    python scripts/confirmar_ridge_z.py
    python scripts/confirmar_ridge_z.py --smoke
"""

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import RidgeCV
from sklearn.model_selection import TimeSeriesSplit

sys.path.insert(0, str(Path(__file__).parent))
import backtest as bt  # noqa: E402
import benchmark_modelos as bm  # noqa: E402
from benchmark_modelos import (  # noqa: E402 — ESPECIFICAÇÃO CONGELADA, ver docstring
    FEATURES_LINEAR, climatologia_media_desvio, desvio_seguro, construir_features_lineares,
    treinar_ridge, prever_linear_recursivo, transformar_de_volta,
    classificar_periodo_operacional, MES_PARA_ESTACAO, CLIM_JAN_DEZ,
)

warnings.filterwarnings('ignore')

ROOT = bt.ROOT
DATA = bt.DATA

# ══════════════════════════════════════════════════════════════════════════
# Fronteira temporal (Seção 3) — fixada ANTES de rodar qualquer análise
# desta fase, nunca ajustada depois de ver resultado.
# ══════════════════════════════════════════════════════════════════════════
FRONTEIRA_CONFIRMACAO = pd.Period('2016-01', 'M')   # origens >= isso: confirmação

MODELO_RIDGE_Z = 'Ridge_z_congelado'
COMPARADORES_PRINCIPAIS = ['Climatologia', 'SARIMAX_atual', MODELO_RIDGE_Z]
REFERENCIA_SECUNDARIA = 'SARIMAX_anom_E2_exog'

# ══════════════════════════════════════════════════════════════════════════
# Ablação (Seção 8) — variantes de feature set, reaproveitando
# construir_features_lineares (que já gera TODAS as colunas candidatas;
# a ablação só SELECIONA um subconjunto, nunca cria feature nova).
# ══════════════════════════════════════════════════════════════════════════
FEATURES_COMPLETO = list(FEATURES_LINEAR)
FEATURES_SEM_OCEANO = ['alvo_l1', 'alvo_l2', 'alvo_l3', 'alvo_l6', 'alvo_l12', 'mes_sin', 'mes_cos']
FEATURES_SO_OCEANO_SAZONAL = ['n34_l23', 'tsa_l23', 'pdo_l23', 'mes_sin', 'mes_cos']

MODELO_SEM_OCEANO = 'Ridge_z_sem_oceano'
MODELO_SO_OCEANO = 'Ridge_z_so_oceano_sazonal'

# ══════════════════════════════════════════════════════════════════════════
# Critério de confirmação (Seção 14) — definido ANTES da execução.
# ══════════════════════════════════════════════════════════════════════════
CRITERIOS_CONFIRMACAO = [
    'skill_rmse_mm_positivo_periodo_recente',
    'ic95_skill_mm_nao_inclui_zero',
    'skill_z_positivo_periodo_recente',
    'ic95_skill_z_nao_inclui_zero',
    'sem_degradacao_operacional_relevante_em_meses_criticos',
    'resultado_nao_depende_de_um_unico_ano',
]


def treinar_ridge_generico(d_feat, features, alphas=None):
    """Generalização de bm.treinar_ridge para um subconjunto arbitrário de
    features — só usada para as variantes de ABLAÇÃO (Seção 8). O Ridge_z
    "de verdade" continua vindo de bm.treinar_ridge, nunca desta função."""
    alphas = alphas if alphas is not None else np.logspace(-2, 2, 9)
    X, y = d_feat[features].values, d_feat['alvo'].values
    n_splits = min(5, len(d_feat) - 1)
    modelo = RidgeCV(alphas=alphas, cv=TimeSeriesSplit(n_splits=n_splits))
    modelo.fit(X, y)
    return modelo


def prever_generico_recursivo(modelo, d_feat, features, media, desvio_seg, origem, representacao, exog_futuro):
    """Generalização de bm.prever_linear_recursivo para um subconjunto
    arbitrário de features (por nome, não por posição fixa) — usada só
    pela ablação. Com features=FEATURES_COMPLETO reproduz exatamente
    bm.prever_linear_recursivo (ver teste de equivalência)."""
    alvo_buf = list(d_feat['alvo'].values)
    horiz = exog_futuro.index
    preds = []
    for p, row in zip(horiz, exog_futuro.itertuples()):
        valores = {
            'alvo_l1': alvo_buf[-1] if len(alvo_buf) >= 1 else 0,
            'alvo_l2': alvo_buf[-2] if len(alvo_buf) >= 2 else 0,
            'alvo_l3': alvo_buf[-3] if len(alvo_buf) >= 3 else 0,
            'alvo_l6': alvo_buf[-6] if len(alvo_buf) >= 6 else 0,
            'alvo_l12': alvo_buf[-12] if len(alvo_buf) >= 12 else 0,
            'n34_l23': row.n34_l23, 'tsa_l23': row.tsa_l23, 'pdo_l23': row.pdo_l23,
            'mes_sin': np.sin(2 * np.pi * p.month / 12), 'mes_cos': np.cos(2 * np.pi * p.month / 12),
        }
        X_step = np.array([[valores[f] for f in features]])
        pred = float(modelo.predict(X_step)[0])
        preds.append(pred)
        alvo_buf.append(pred)
    meses_futuros = np.array([p.month for p in horiz])
    return transformar_de_volta(np.array(preds), meses_futuros, media, desvio_seg, representacao)


# ══════════════════════════════════════════════════════════════════════════
# Uma origem: Ridge_z congelado (operacional + oracle) + 2 ablações +
# coeficientes do modelo completo.
# ══════════════════════════════════════════════════════════════════════════

def rodar_origem_confirmacao(serie, origem):
    t0 = time.time()
    serie_cortada = bt.cortar_serie(serie, origem)
    d_cortado = bt.construir_lags(serie_cortada)
    d_feat, media, desvio_seg = construir_features_lineares(serie_cortada, d_cortado, 'z')

    horiz = pd.period_range(origem + 1, periods=bt.HORIZON, freq='M')
    observado = {p: serie.loc[serie['ym'] == p, 'prec'] for p in horiz}
    observado = {p: (float(v.iloc[0]) if len(v) else None) for p, v in observado.items()}
    nino34_origem = float(serie_cortada['nino34'].iloc[-1])
    classe_enso = bt.classificar_enso(nino34_origem)

    registros = []

    def registrar(modelo, modo, preds):
        for lead, p in enumerate(horiz, start=1):
            obs = observado[p]
            prev = float(preds[lead - 1])
            registros.append({
                'origem': str(origem), 'data_prevista': str(p), 'lead': lead, 'mes_alvo': p.month,
                'observado': obs, 'modelo': modelo, 'modo': modo, 'previsto': round(prev, 3),
                'erro': (round(prev - obs, 3) if obs is not None else None),
                'nino34_origem': round(nino34_origem, 3), 'classe_enso_origem': classe_enso,
                'clim_media_mes': round(float(media.get(p.month, np.nan)), 3),
                'clim_desvio_mes': round(float(desvio_seg.get(p.month, np.nan)), 3),
                'estacao': MES_PARA_ESTACAO[p.month],
                'periodo_operacional': classificar_periodo_operacional(p.month),
            })

    # ── Ridge_z congelado: 1 fit, 2 forecasts (operacional / oracle) ──
    modelo_full = treinar_ridge(d_feat)   # bm.treinar_ridge, ESPECIFICAÇÃO CONGELADA
    exog_op = bt.montar_exog_futuro(serie_cortada, serie, origem, bt.MODO_OPERACIONAL)
    exog_or = bt.montar_exog_futuro(serie_cortada, serie, origem, bt.MODO_ORACLE)
    preds_op = prever_linear_recursivo(modelo_full, d_feat, media, desvio_seg, origem, 'z', exog_op)
    preds_or = prever_linear_recursivo(modelo_full, d_feat, media, desvio_seg, origem, 'z', exog_or)
    registrar(MODELO_RIDGE_Z, bt.MODO_OPERACIONAL, preds_op)
    registrar(MODELO_RIDGE_Z, bt.MODO_ORACLE, preds_or)

    coef_row = {
        'origem': str(origem), 'alpha_selecionado': float(modelo_full.alpha_),
        'intercept': float(modelo_full.intercept_),
        **{f'coef_{f}': float(c) for f, c in zip(FEATURES_COMPLETO, modelo_full.coef_)},
    }

    # ── Ablação (Seção 8) — só operacional_simulado ──
    modelo_semoc = treinar_ridge_generico(d_feat, FEATURES_SEM_OCEANO)
    preds_semoc = prever_generico_recursivo(modelo_semoc, d_feat, FEATURES_SEM_OCEANO,
                                             media, desvio_seg, origem, 'z', exog_op)
    registrar(MODELO_SEM_OCEANO, bt.MODO_OPERACIONAL, preds_semoc)

    modelo_sooc = treinar_ridge_generico(d_feat, FEATURES_SO_OCEANO_SAZONAL)
    preds_sooc = prever_generico_recursivo(modelo_sooc, d_feat, FEATURES_SO_OCEANO_SAZONAL,
                                            media, desvio_seg, origem, 'z', exog_op)
    registrar(MODELO_SO_OCEANO, bt.MODO_OPERACIONAL, preds_sooc)

    return registros, coef_row, time.time() - t0


# ══════════════════════════════════════════════════════════════════════════
# Métricas específicas desta fase
# ══════════════════════════════════════════════════════════════════════════

def bootstrap_ci_skill_z(df, modelo, climatologia='Climatologia', modo=bt.MODO_OPERACIONAL,
                          leads=None, n_boot=2000, seed=42):
    """IC95% do skill NO ESPAÇO PADRONIZADO (Seção 6) — reusa
    bt.bootstrap_ci_diff_rmse (frozen, já testado) aplicado a um
    DataFrame transformado onde 'previsto'=erro_z e 'observado'=0, de
    forma que RMSE(0, erro_z) = sqrt(mean(erro_z^2)) = RMSE_z. O bloco de
    reamostragem continua sendo a ORIGEM, igual à Seção 5."""
    leads = list(leads) if leads is not None else list(range(1, 13))
    d = df[(df['modo'] == modo) & (df['lead'].isin(leads))].dropna(
        subset=['observado', 'previsto', 'clim_desvio_mes']).copy()
    d = d[d['clim_desvio_mes'] > 0]
    d['erro_z'] = (d['previsto'] - d['observado']) / d['clim_desvio_mes']
    dt = d[['origem', 'lead', 'modelo', 'modo']].copy()
    dt['observado'] = 0.0
    dt['previsto'] = d['erro_z'].values
    resultado = bt.bootstrap_ci_diff_rmse(dt, modelo, climatologia=climatologia, modo=modo,
                                           leads=leads, n_boot=n_boot, seed=seed)
    resultado['metrica'] = 'RMSE_z (padronizado)'
    return resultado


def bootstrap_ci_bloco_temporal(df, modelo, climatologia='Climatologia', modo=bt.MODO_OPERACIONAL,
                                 tamanho_bloco_origens=1, n_boot=2000, seed=42):
    """Seção 13 — sensibilidade do IC ao tamanho do bloco. Bloco temporal
    MÓVEL de `tamanho_bloco_origens` origens CONSECUTIVAS (não
    individuais) — captura autocorrelação de erro entre origens vizinhas,
    além da autocorrelação entre leads de uma mesma origem que o bloco de
    tamanho 1 (Seção 5, mesmo método da Fase 1.1) já captura."""
    sub = df[(df['modo'] == modo)].dropna(subset=['observado'])
    m = sub[sub['modelo'] == modelo][['origem', 'lead', 'observado', 'previsto']]
    c = sub[sub['modelo'] == climatologia][['origem', 'lead', 'previsto']].rename(
        columns={'previsto': 'previsto_clim'})
    merged = m.merge(c, on=['origem', 'lead'], how='inner')

    origens_ordenadas = sorted(merged['origem'].unique(), key=lambda s: pd.Period(s, 'M'))
    blocos_por_origem = {o: g[['observado', 'previsto', 'previsto_clim']].to_numpy()
                          for o, g in merged.groupby('origem')}

    K = tamanho_bloco_origens
    if K <= 1:
        janelas = [[o] for o in origens_ordenadas]
    else:
        janelas = [origens_ordenadas[i:i + K] for i in range(len(origens_ordenadas) - K + 1)]
        if not janelas:
            janelas = [origens_ordenadas]

    n_origens = len(origens_ordenadas)
    n_janelas_por_amostra = max(1, -(-n_origens // K))   # ceil
    rng = np.random.RandomState(seed)

    def rmse_np(a, b):
        return float(np.sqrt(np.mean((a - b) ** 2)))

    obs_all = merged['observado'].to_numpy(dtype=float)
    prev_all = merged['previsto'].to_numpy(dtype=float)
    clim_all = merged['previsto_clim'].to_numpy(dtype=float)
    rmse_m, rmse_c = rmse_np(obs_all, prev_all), rmse_np(obs_all, clim_all)
    skill_pt = (1 - rmse_m / rmse_c) if rmse_c else None

    skills = np.empty(n_boot)
    diffs = np.empty(n_boot)
    for b in range(n_boot):
        idx_janelas = rng.randint(0, len(janelas), size=n_janelas_por_amostra)
        origens_amostra = [o for j in idx_janelas for o in janelas[j]][:n_origens]
        arr = np.concatenate([blocos_por_origem[o] for o in origens_amostra], axis=0)
        obs_b, prev_b, clim_b = arr[:, 0], arr[:, 1], arr[:, 2]
        rm, rc = rmse_np(obs_b, prev_b), rmse_np(obs_b, clim_b)
        diffs[b] = rm - rc
        skills[b] = (1 - rm / rc) if rc else np.nan

    def ic(a):
        a = a[np.isfinite(a)]
        return [round(float(np.percentile(a, 2.5)), 4), round(float(np.percentile(a, 97.5)), 4)] if len(a) else [None, None]

    return {
        'modelo': modelo, 'vs': climatologia, 'tamanho_bloco_origens': K,
        'n_janelas_disponiveis': len(janelas), 'n_origens': n_origens, 'n_boot': n_boot, 'seed': seed,
        'skill_pontual': round(skill_pt, 4) if skill_pt is not None else None,
        'skill_ic95': ic(skills), 'diff_rmse_ic95': ic(diffs),
        'ic95_inclui_zero': bool(ic(skills)[0] is not None and ic(skills)[0] <= 0 <= ic(skills)[1]),
    }


def resumir_coeficientes(df_coef):
    linhas = {}
    for col in [c for c in df_coef.columns if c.startswith('coef_')]:
        s = df_coef[col]
        linhas[col.replace('coef_', '')] = {
            'media': round(float(s.mean()), 4), 'mediana': round(float(s.median()), 4),
            'desvio_padrao': round(float(s.std()), 4),
            'p10': round(float(s.quantile(0.10)), 4), 'p90': round(float(s.quantile(0.90)), 4),
            'pct_positivo': round(float((s > 0).mean() * 100), 1),
            'pct_negativo': round(float((s < 0).mean() * 100), 1),
            'magnitude_media_absoluta': round(float(s.abs().mean()), 4),
        }
    linhas['alpha_selecionado'] = {
        'media': round(float(df_coef['alpha_selecionado'].mean()), 4),
        'mediana': round(float(df_coef['alpha_selecionado'].median()), 4),
        'p10': round(float(df_coef['alpha_selecionado'].quantile(0.10)), 4),
        'p90': round(float(df_coef['alpha_selecionado'].quantile(0.90)), 4),
    }
    return linhas


def metricas_erro_out_of_sample(df, modelo, modo=bt.MODO_OPERACIONAL):
    """Seção 10 — erro OUT-OF-SAMPLE (previsto-observado), nunca resíduo
    in-sample de ajuste. bias/MAE/RMSE por mês + erro padronizado por mês
    + ACF lag1/Ljung-Box calculados SÓ na série de erro do lead=1 (um
    valor por origem, aproximadamente não-sobreposto no tempo já que
    origens são mensais) — usar leads 1-12 juntos infla a autocorrelação
    de forma puramente mecânica (mesma origem contribui com 12 valores
    de horizontes sobrepostos), o que não é informativo sobre a
    qualidade do modelo."""
    d = df[(df['modelo'] == modelo) & (df['modo'] == modo)].dropna(subset=['observado'])
    por_mes = {}
    for mm, g in d.groupby('mes_alvo'):
        erro_pad = (g['previsto'] - g['observado']) / g['clim_desvio_mes'].replace(0, np.nan)
        por_mes[str(mm)] = {
            'n': len(g), 'bias': round(float((g['previsto'] - g['observado']).mean()), 2),
            'mae': round(float((g['previsto'] - g['observado']).abs().mean()), 2),
            'rmse': round(float(np.sqrt(((g['previsto'] - g['observado']) ** 2).mean())), 2),
            'erro_padronizado_medio': round(float(erro_pad.mean()), 4),
        }

    d1 = d[d['lead'] == 1].copy()
    d1['origem_p'] = d1['origem'].apply(lambda s: pd.Period(s, 'M'))
    d1 = d1.sort_values('origem_p')
    erro_lead1 = (d1['previsto'] - d1['observado']).to_numpy(dtype=float)
    autocorr_lag1 = float(np.corrcoef(erro_lead1[:-1], erro_lead1[1:])[0, 1]) if len(erro_lead1) > 2 else None
    ljungbox = None
    if len(erro_lead1) > 13:
        try:
            from statsmodels.stats.diagnostic import acorr_ljungbox
            lb = acorr_ljungbox(erro_lead1, lags=[12], return_df=True)
            ljungbox = float(lb['lb_pvalue'].iloc[0])
        except Exception:
            pass

    return {
        'por_mes': por_mes,
        'erro_lead1_serie_nao_sobreposta': {
            'n': len(erro_lead1), 'autocorr_lag1': (round(autocorr_lag1, 4) if autocorr_lag1 is not None else None),
            'ljungbox_p_lag12': (round(ljungbox, 6) if ljungbox is not None else None),
            'rejeita_ruido_branco_p<0.05': (bool(ljungbox < 0.05) if ljungbox is not None else None),
        },
    }


# ══════════════════════════════════════════════════════════════════════════
# Orquestração
# ══════════════════════════════════════════════════════════════════════════

def carregar_comparadores_referencia():
    caminho = DATA / 'model_benchmark_predictions.csv'
    df = pd.read_csv(caminho)
    df = df[(df['modo'] == bt.MODO_OPERACIONAL) &
            (df['modelo'].isin(COMPARADORES_PRINCIPAIS[:2] + [REFERENCIA_SECUNDARIA]))].copy()
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--smoke', action='store_true')
    args = ap.parse_args()

    serie = bt.carregar_serie()
    origens = bt.gerar_origens(serie, step=bt.STEP_MENSAL)
    if args.smoke:
        origens = origens[:3]

    print(f"Fase 1.3 — confirmação Ridge_z — {len(origens)} origens")
    t0 = time.time()
    todos_registros, todos_coef = [], []
    for i, origem in enumerate(origens):
        registros, coef_row, dt = rodar_origem_confirmacao(serie, origem)
        todos_registros.extend(registros)
        todos_coef.append(coef_row)
        if (i + 1) % 50 == 0 or i == len(origens) - 1:
            print(f"  [{i+1}/{len(origens)}] origem={origem}  ({dt:.3f}s)")
    tempo_total = time.time() - t0
    print(f"  Tempo total: {tempo_total:.1f}s")

    df_novo = pd.DataFrame(todos_registros)
    df_coef = pd.DataFrame(todos_coef)

    if args.smoke:
        print("(smoke test — nada gravado em disco)")
        return

    df_ref = carregar_comparadores_referencia()
    df = pd.concat([df_ref, df_novo], ignore_index=True)
    df['origem_p'] = df['origem'].apply(lambda s: pd.Period(s, 'M'))
    df['periodo_fase13'] = np.where(df['origem_p'] < FRONTEIRA_CONFIRMACAO, 'desenvolvimento', 'confirmacao_recente')
    df = df.drop(columns=['origem_p'])

    out_pred = DATA / 'ridge_z_confirmation_predictions.csv'
    out_coef = DATA / 'ridge_z_coefficients.csv'
    df.to_csv(out_pred, index=False)
    df_coef.to_csv(out_coef, index=False)
    print(f"✅ {out_pred.relative_to(ROOT)}")
    print(f"✅ {out_coef.relative_to(ROOT)}")

    # ── Resultado agregado dev/confirmação para os 3 comparadores principais + referência secundária
    n_dev = sum(1 for o in origens if o < FRONTEIRA_CONFIRMACAO)
    n_conf = len(origens) - n_dev
    resultado = {'metadata': {
        'data_execucao': pd.Timestamp.now().isoformat(), 'git_sha': bt._git_sha(),
        'fronteira_confirmacao': str(FRONTEIRA_CONFIRMACAO),
        'n_origens_total': len(origens), 'n_origens_desenvolvimento': n_dev, 'n_origens_confirmacao': n_conf,
        'criterios_confirmacao_predefinidos': CRITERIOS_CONFIRMACAO,
        'tempo_total_segundos': round(tempo_total, 1),
    }}

    for periodo in ['desenvolvimento', 'confirmacao_recente']:
        dsub = df[df['periodo_fase13'] == periodo]
        by_lead, by_block, overall = bt.calcular_metricas(dsub)
        skill = bm.calcular_skill_todos_modelos(by_lead, by_block, sorted(dsub['modelo'].unique()))
        resultado[periodo] = {
            'overall_metrics': overall, 'metrics_by_lead': by_lead,
            'metrics_by_horizon_block': by_block, 'skill_vs_climatology': skill,
            'metrics_by_estacao': bm.calcular_metricas_por_estacao(dsub),
            'metrics_by_periodo_operacional': bm.calcular_metricas_por_periodo_operacional(dsub),
            'metrics_padronizadas': bm.calcular_metricas_padronizadas(dsub),
        }

    dconf = df[df['periodo_fase13'] == 'confirmacao_recente']

    # walk-forward por ano (Seção 4)
    dconf = dconf.copy()
    dconf['ano_origem'] = dconf['origem'].str.slice(0, 4).astype(int)
    por_ano = {}
    for ano, g in dconf.groupby('ano_origem'):
        gc = g[(g['modelo'] == 'Climatologia') & (g['modo'] == bt.MODO_OPERACIONAL)].dropna(subset=['observado'])
        gr = g[(g['modelo'] == MODELO_RIDGE_Z) & (g['modo'] == bt.MODO_OPERACIONAL)].dropna(subset=['observado'])
        rmse_c = bt._rmse(gc['observado'], gc['previsto'])
        rmse_r = bt._rmse(gr['observado'], gr['previsto'])
        por_ano[str(ano)] = {
            'n_origens': int(g['origem'].nunique()),
            'rmse_climatologia': round(rmse_c, 2), 'rmse_ridge_z': round(rmse_r, 2),
            'diferenca': round(rmse_r - rmse_c, 2),
            'skill': round(1 - rmse_r / rmse_c, 4) if rmse_c else None,
            'mae_ridge_z': round(bt._mae(gr['observado'], gr['previsto']), 2),
            'bias_ridge_z': round(bt._bias(gr['observado'], gr['previsto']), 2),
        }
    resultado['walk_forward_por_ano'] = por_ano

    # IC95% no período de confirmação (Seção 5) — bloco=origem (mesmo método Fase 1.1)
    resultado['bootstrap_confirmacao_mm'] = {
        modelo: bt.bootstrap_ci_diff_rmse(dconf, modelo, modo=bt.MODO_OPERACIONAL, n_boot=2000, seed=42)
        for modelo in [MODELO_RIDGE_Z, 'SARIMAX_atual']
    }

    # RMSE_z + IC95 (Seção 6)
    resultado['bootstrap_confirmacao_z'] = {
        modelo: bootstrap_ci_skill_z(dconf, modelo, modo=bt.MODO_OPERACIONAL, n_boot=2000, seed=42)
        for modelo in [MODELO_RIDGE_Z, 'SARIMAX_atual']
    }

    # Sensibilidade ao tamanho do bloco (Seção 13)
    resultado['sensibilidade_bloco_bootstrap'] = {
        str(k): bootstrap_ci_bloco_temporal(dconf, MODELO_RIDGE_Z, tamanho_bloco_origens=k, n_boot=2000, seed=42)
        for k in [1, 3, 6, 12]
    }

    # Oracle vs operacional (Seção 9)
    d_ridge_conf = dconf[dconf['modelo'] == MODELO_RIDGE_Z]
    by_lead_r, by_block_r, overall_r = bt.calcular_metricas(d_ridge_conf)
    clim_block_conf = resultado['confirmacao_recente']['metrics_by_horizon_block']['Climatologia'][bt.MODO_OPERACIONAL]
    skill_por_modo = {}
    for modo in [bt.MODO_OPERACIONAL, bt.MODO_ORACLE]:
        sk = {}
        for nome in bt.BLOCOS:
            rmse_modelo = by_block_r.get(MODELO_RIDGE_Z, {}).get(modo, {}).get(nome, {}).get('rmse')
            rmse_clim = clim_block_conf.get(nome, {}).get('rmse')
            sk[nome] = round(1 - rmse_modelo / rmse_clim, 4) if (rmse_modelo is not None and rmse_clim) else None
        skill_por_modo[modo] = sk
    resultado['oracle_vs_operacional'] = {'overall': overall_r, 'skill_vs_climatologia_por_bloco': skill_por_modo}

    # Ablação (Seção 8)
    resultado['ablacao'] = {
        modelo: bt._metricas(
            dconf[(dconf['modelo'] == modelo) & (dconf['modo'] == bt.MODO_OPERACIONAL)].dropna(subset=['observado'])['observado'],
            dconf[(dconf['modelo'] == modelo) & (dconf['modo'] == bt.MODO_OPERACIONAL)].dropna(subset=['observado'])['previsto'])
        for modelo in [MODELO_RIDGE_Z, MODELO_SEM_OCEANO, MODELO_SO_OCEANO]
    }

    # Diagnóstico de erro out-of-sample (Seção 10)
    resultado['diagnostico_erro_out_of_sample'] = metricas_erro_out_of_sample(dconf, MODELO_RIDGE_Z)

    # Coeficientes (Seção 7)
    df_coef['origem_p'] = df_coef['origem'].apply(lambda s: pd.Period(s, 'M'))
    coef_conf = df_coef[df_coef['origem_p'] >= FRONTEIRA_CONFIRMACAO].drop(columns=['origem_p'])
    resultado['estabilidade_coeficientes'] = {
        'todas_origens': resumir_coeficientes(df_coef.drop(columns=['origem_p'], errors='ignore')),
        'periodo_confirmacao': resumir_coeficientes(coef_conf),
    }

    out_json = DATA / 'ridge_z_confirmation.json'
    out_json.write_text(json.dumps(resultado, ensure_ascii=False, indent=2, default=str))
    print(f"✅ {out_json.relative_to(ROOT)}")


if __name__ == '__main__':
    main()
