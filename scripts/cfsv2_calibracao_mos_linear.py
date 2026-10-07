#!/usr/bin/env python3
"""
cfsv2_calibracao_mos_linear.py — Fase 2C.3D: implementação do Método
3.4 (MOS linear causal no espaço de anomalias), seguindo exatamente o
protocolo revisado (`docs/nmme-fase2c3d-protocolo-mos-linear-cfsv2.md`).
Nenhuma extensão do modelo pré-registrado é implementada aqui (sem
dummy mensal, interação, ENSO, tendência, termo quadrático,
regularização ou seleção automática).

    anom_modelo_raw  = forecast_raw - climatologia_modelo_raw
    anom_observada   = observacao   - climatologia_observada
    anom_observada    = alpha_lead + beta_lead * anom_modelo_raw + erro   (OLS, por lead)
    forecast_mos      = climatologia_observada + alpha_lead + beta_lead * anom_modelo_raw

`climatologia_modelo_raw`/`climatologia_observada` são os MESMOS campos
causais já aprovados da 2C.3C (`climatologia_modelo_expansivel`/
`climatologia_expansivel`, via `v._enriquecer_com_climatologia`) — nunca
reconstruídos retrospectivamente aqui. Completamente separado do sistema
operacional e dos Métodos 3.1/3.2/gate do 3.3 já aprovados: nunca altera
dashboard, SARIMAX, XGBoost, pipeline operacional, CFSv2 RAW, CHIRPS v3
histórico, `aditiva_expanding.csv`, `multiplicativa_expanding.csv` nem
`viabilidade_quantile_mapping.json` (todos só LIDOS quando necessário,
nunca reescritos).

`par_anomalia_valido` (item 3 do pedido) — uma linha só entra em
`n_treino_mos` se TODAS as seis condições valerem simultaneamente:
`forecast_raw`, `observacao`, `climatologia_modelo_raw`,
`climatologia_observada`, `anom_modelo_raw` e `anom_observada` finitos.
Nunca preenchido com NaN nem substituído por zero.

Unidade de treinamento: por `lead`, agregando TODOS os meses (pooling
deliberado entre meses — nunca entre leads). Warm-up pré-registrado:
`N_TREINO_MINIMO_MOS = 120` PARES VÁLIDOS (nunca 120 inicializações).

Roda com:
    python scripts/cfsv2_calibracao_mos_linear.py --executar
    python scripts/cfsv2_calibracao_mos_linear.py --gerar-relatorio
"""

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import cfsv2_calibracao_aditiva as a  # noqa: E402
import cfsv2_validacao_cientifica as v  # noqa: E402

DIRETORIO_SAIDA = a.DIRETORIO_SAIDA
CAMINHO_TABELA_EXPANDING = DIRETORIO_SAIDA / 'mos_linear_expanding.csv'
CAMINHO_TABELA_LOYO = DIRETORIO_SAIDA / 'mos_linear_loyo.csv'
CAMINHO_METRICAS_JSON = DIRETORIO_SAIDA / 'metricas_mos_linear_2c3d.json'
RELATORIO_PATH = ROOT / 'docs' / 'nmme-fase2c3d-mos-linear-cfsv2.md'

# Pré-registrado — PARES VÁLIDOS, nunca inicializações simplesmente
# contadas (protocolo, Seção 5, revisão). Nunca ajustado depois de
# observar resultados.
N_TREINO_MINIMO_MOS = 120

# Critério numérico explícito de variância praticamente zero —
# definido ANTES de qualquer ajuste real, nunca escolhido observando
# qual valor produz melhor skill (protocolo, Seção 7).
VARIANCIA_MINIMA_ANOM_MODELO = 1e-6

STATUS_OK = 'ok'
STATUS_WARMUP = 'warmup_amostra_insuficiente'
STATUS_ANOMALIA_INDISPONIVEL = 'anomalia_indisponivel_para_linha_avaliada'
STATUS_DEGENERADA = 'erro_regressao_degenerada'
STATUS_COEF_INVALIDO = 'erro_coeficientes_nao_finitos'

_STATUS_SEM_FORECAST = (STATUS_WARMUP, STATUS_ANOMALIA_INDISPONIVEL, STATUS_DEGENERADA,
                         STATUS_COEF_INVALIDO)

NOMES_MES = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']

COLUNAS_TABELA_EXPANDING = [
    'init_date', 'target_month', 'target_ano', 'target_mes', 'lead',
    'forecast_raw', 'observacao', 'climatologia_modelo_raw', 'climatologia_observada',
    'anom_modelo_raw', 'anom_observada', 'par_anomalia_valido',
    'n_treino_mos', 'periodo_treino_inicio', 'periodo_treino_fim',
    'alpha', 'beta', 'r2_treino', 'condicao_numerica', 'forecast_mos', 'anom_mos',
    'benchmark_anomalia_reconstruida', 'status_mos',
]


# ══════════════════════════════════════════════════════════════════════════
# Núcleo — par de anomalia válido, OLS causal por lead (pooling entre meses)
# ══════════════════════════════════════════════════════════════════════════

def _finito(valor):
    return valor is not None and pd.notna(valor) and np.isfinite(valor)


def _montar_linha_base(row):
    """Item 3 do pedido — calcula anom_modelo_raw/anom_observada e
    `par_anomalia_valido` para UMA linha, a partir só dos seus próprios
    campos causais já aprovados (climatologia_modelo_raw/
    climatologia_observada vêm de `_enriquecer_com_climatologia`, 2C.3C
    — nunca reconstruídas aqui). Nunca preenche NaN, nunca usa zero
    como substituto de ausência: se qualquer campo faltar, as
    anomalias ficam `None` e `par_anomalia_valido=False`."""
    forecast_raw = row['forecast_raw']
    observacao = row['observacao']
    clim_mod = row['climatologia_modelo_raw']
    clim_obs = row['climatologia_observada']

    forecast_ok = _finito(forecast_raw)
    observacao_ok = _finito(observacao)
    clim_mod_ok = _finito(clim_mod)
    clim_obs_ok = _finito(clim_obs)

    anom_modelo_raw = float(forecast_raw - clim_mod) if (forecast_ok and clim_mod_ok) else None
    anom_observada = float(observacao - clim_obs) if (observacao_ok and clim_obs_ok) else None
    anom_modelo_valida = anom_modelo_raw is not None and np.isfinite(anom_modelo_raw)
    anom_observada_valida = anom_observada is not None and np.isfinite(anom_observada)

    par_valido = bool(forecast_ok and observacao_ok and clim_mod_ok and clim_obs_ok
                       and anom_modelo_valida and anom_observada_valida)

    bench3 = (float(clim_obs + anom_modelo_raw) if (clim_obs_ok and anom_modelo_valida) else None)

    return {
        'forecast_raw': float(forecast_raw) if forecast_ok else None,
        'observacao': float(observacao) if observacao_ok else None,
        'climatologia_modelo_raw': float(clim_mod) if clim_mod_ok else None,
        'climatologia_observada': float(clim_obs) if clim_obs_ok else None,
        'anom_modelo_raw': anom_modelo_raw,
        'anom_observada': anom_observada,
        'par_anomalia_valido': par_valido,
        'benchmark_anomalia_reconstruida': bench3,
    }


def _ajustar_ols_simples(x_historico, y_historico):
    """Item 6/7 do pedido — OLS simples, fórmula explícita (nunca uma
    biblioteca caixa-preta): `beta = cov(x,y)/var(x)`,
    `alpha = media(y) - beta*media(x)`. Proteções numéricas ANTES do
    ajuste: variância de x (critério fixo, Seção 7, nunca escolhido por
    skill) e rank da matriz de desenho `[1, x]`. Retorna
    (alpha, beta, r2_treino, condicao_numerica, status)."""
    x = np.asarray(x_historico, dtype=float)
    y = np.asarray(y_historico, dtype=float)
    n = len(x)

    design = np.column_stack([np.ones(n), x])
    try:
        condicao = float(np.linalg.cond(design))
    except (np.linalg.LinAlgError, ValueError):
        condicao = None
    rank = int(np.linalg.matrix_rank(design))
    variancia_x = float(np.var(x, ddof=0))

    if variancia_x < VARIANCIA_MINIMA_ANOM_MODELO or rank < 2:
        return None, None, None, condicao, STATUS_DEGENERADA

    media_x, media_y = float(x.mean()), float(y.mean())
    cov_xy = float(np.mean((x - media_x) * (y - media_y)))
    beta = cov_xy / variancia_x
    alpha = media_y - beta * media_x

    if not (np.isfinite(alpha) and np.isfinite(beta)):
        return None, None, None, condicao, STATUS_COEF_INVALIDO

    pred = alpha + beta * x
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - media_y) ** 2))
    r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else None

    return float(alpha), float(beta), r2, condicao, STATUS_OK


def construir_tabela_mos_linear(base_enriquecida):
    """Constrói, para cada (init_date, lead), a linha do Método 3.4 —
    expansão ordenada no tempo DENTRO DE CADA LEAD (pooling entre
    meses, nunca entre leads): o histórico de PARES VÁLIDOS só cresce
    DEPOIS de processar a linha atual, garantindo estruturalmente que
    ela nunca entra no seu próprio ajuste (mesma garantia anti-leakage
    já usada nos Métodos 3.1/3.2)."""
    media_membros = base_enriquecida.groupby(
        ['init_date', 'target_month', 'target_ano', 'target_mes', 'lead'], as_index=False
    ).agg(forecast_raw=('forecast_prec_mm', 'mean'),
          observacao=('obs_prec_mm', 'first'),
          climatologia_observada=('clim_media', 'first'),
          climatologia_modelo_raw=('clim_modelo_media', 'first'))

    linhas = []
    for lead, grupo in media_membros.groupby('lead'):
        grupo = grupo.assign(_p=pd.PeriodIndex(grupo['init_date'], freq='M')).sort_values('_p')
        x_pares_validos, y_pares_validos, inits_pares_validos = [], [], []

        for _, row in grupo.iterrows():
            base = _montar_linha_base(row)
            n_treino_mos = len(x_pares_validos)

            if not base['par_anomalia_valido']:
                status = STATUS_ANOMALIA_INDISPONIVEL
                alpha = beta = r2_treino = condicao = None
                forecast_mos = None
                periodo_inicio = periodo_fim = None
            elif n_treino_mos < N_TREINO_MINIMO_MOS:
                status = STATUS_WARMUP
                alpha = beta = r2_treino = condicao = None
                forecast_mos = None
                periodo_inicio = periodo_fim = None
            else:
                periodo_inicio = inits_pares_validos[0]
                periodo_fim = inits_pares_validos[-1]
                alpha, beta, r2_treino, condicao, status = _ajustar_ols_simples(
                    x_pares_validos, y_pares_validos)
                if status == STATUS_OK:
                    forecast_mos = float(base['climatologia_observada'] + alpha
                                          + beta * base['anom_modelo_raw'])
                else:
                    forecast_mos = None

            # anom_mos (correção desta revisão) — derivada UMA ÚNICA VEZ
            # aqui, a partir do forecast_mos já calculado, nunca
            # recalculada de outra forma em nenhuma métrica/diagnóstico
            # posterior (_metricas_de_subconjunto_mos lê esta coluna).
            anom_mos = (float(forecast_mos - base['climatologia_observada'])
                        if forecast_mos is not None else None)

            linhas.append({
                'init_date': row['init_date'], 'target_month': row['target_month'],
                'target_ano': int(row['target_ano']), 'target_mes': int(row['target_mes']),
                'lead': int(lead),
                'forecast_raw': base['forecast_raw'], 'observacao': base['observacao'],
                'climatologia_modelo_raw': base['climatologia_modelo_raw'],
                'climatologia_observada': base['climatologia_observada'],
                'anom_modelo_raw': base['anom_modelo_raw'],
                'anom_observada': base['anom_observada'],
                'par_anomalia_valido': base['par_anomalia_valido'],
                'n_treino_mos': n_treino_mos,
                'periodo_treino_inicio': periodo_inicio, 'periodo_treino_fim': periodo_fim,
                'alpha': alpha, 'beta': beta, 'r2_treino': r2_treino,
                'condicao_numerica': condicao, 'forecast_mos': forecast_mos, 'anom_mos': anom_mos,
                'benchmark_anomalia_reconstruida': base['benchmark_anomalia_reconstruida'],
                'status_mos': status,
            })

            # Histórico só cresce DEPOIS de processar a linha atual, e
            # só com PARES VÁLIDOS — mesma garantia anti-leakage, mais
            # a regra explícita do item 3 (nunca contar linha inválida).
            if base['par_anomalia_valido']:
                x_pares_validos.append(base['anom_modelo_raw'])
                y_pares_validos.append(base['anom_observada'])
                inits_pares_validos.append(row['init_date'])

    tabela = pd.DataFrame(linhas)[COLUNAS_TABELA_EXPANDING]
    tabela = tabela.assign(_p=pd.PeriodIndex(tabela['init_date'], freq='M')).sort_values(
        ['lead', '_p']).drop(columns='_p').reset_index(drop=True)
    return tabela


# ══════════════════════════════════════════════════════════════════════════
# Auditorias defensivas — STOP-ON-FAILURE (item 21 do pedido)
# ══════════════════════════════════════════════════════════════════════════

def _verificar_nenhum_leakage_na_tabela_mos(tabela):
    problemas = []
    ok = tabela[tabela['status_mos'] == STATUS_OK]
    for _, row in ok.iterrows():
        if row['periodo_treino_fim'] is None:
            problemas.append(f"{row['init_date']} lead={row['lead']}: status=ok mas "
                              "periodo_treino_fim ausente")
            continue
        fim_p = v._periodo(row['periodo_treino_fim'])
        avaliada_p = v._periodo(row['init_date'])
        if not (fim_p < avaliada_p):
            problemas.append(f"{row['init_date']} lead={row['lead']}: periodo_treino_fim="
                              f"{row['periodo_treino_fim']} >= init_date avaliada")
    return {'ok': len(problemas) == 0, 'n_problemas': len(problemas), 'problemas': problemas[:20]}


def _verificar_outro_lead_nunca_contaminou_treino(tabela):
    """Item 8/21 do pedido — checagem defensiva adicional: todo
    `n_treino_mos` reportado tem que ser reproduzível filtrando SÓ pelo
    mesmo lead e por pares válidos estritamente anteriores — nunca
    maior do que isso (o que indicaria contaminação de outro lead)."""
    problemas = []
    ok_e_degenerada = tabela[tabela['status_mos'].isin(
        (STATUS_OK, STATUS_DEGENERADA, STATUS_COEF_INVALIDO))]
    for lead, grupo_lead in tabela.groupby('lead'):
        pares_validos_lead = grupo_lead[grupo_lead['par_anomalia_valido']]
        sub = ok_e_degenerada[ok_e_degenerada['lead'] == lead]
        for _, row in sub.iterrows():
            avaliada_p = v._periodo(row['init_date'])
            esperado = int((pd.PeriodIndex(pares_validos_lead['init_date'], freq='M')
                             < avaliada_p).sum())
            if esperado != row['n_treino_mos']:
                problemas.append(f"{row['init_date']} lead={row['lead']}: n_treino_mos="
                                  f"{row['n_treino_mos']}, recalculado só com o mesmo lead="
                                  f"{esperado}")
    return {'ok': len(problemas) == 0, 'n_problemas': len(problemas), 'problemas': problemas[:20]}


def _verificar_contagem_total(tabela):
    esperado = v.N_INICIALIZACOES_ESPERADO * len(v.LEADS_ESPERADOS)
    return {'ok': len(tabela) == esperado, 'n_tabela': len(tabela), 'n_esperado': esperado}


def _primeira_inicializacao_elegivel_por_lead(tabela):
    """Item 5 do pedido — derivado PROGRAMATICAMENTE, nunca assumido
    como 2001. Também informa, por H1-H6: n_treino_mos exatamente
    nessa data, e quantas linhas anteriores foram descartadas por
    anomalia indisponível (nunca escondido atrás da contagem simples
    de inicializações)."""
    resultado = {}
    for lead in v.LEADS_ESPERADOS:
        sub = tabela[tabela['lead'] == lead].assign(
            _p=pd.PeriodIndex(tabela[tabela['lead'] == lead]['init_date'], freq='M')
        ).sort_values('_p')
        ok = sub[sub['status_mos'] == STATUS_OK]
        if len(ok) == 0:
            resultado[int(lead)] = {
                'primeira_init_date_elegivel': None, 'n_treino_mos_nessa_data': None,
                'n_linhas_descartadas_por_anomalia_indisponivel_antes_dessa_data': None,
                'rotulo': v.ROTULO_HORIZONTE[lead],
            }
            continue
        primeira = ok.sort_values('_p').iloc[0] if '_p' in ok.columns else \
            ok.assign(_p=pd.PeriodIndex(ok['init_date'], freq='M')).sort_values('_p').iloc[0]
        primeira_p = v._periodo(primeira['init_date'])
        anteriores = sub[pd.PeriodIndex(sub['init_date'], freq='M') < primeira_p]
        n_descartadas = int((~anteriores['par_anomalia_valido']).sum())
        resultado[int(lead)] = {
            'primeira_init_date_elegivel': primeira['init_date'],
            'n_treino_mos_nessa_data': int(primeira['n_treino_mos']),
            'n_linhas_descartadas_por_anomalia_indisponivel_antes_dessa_data': n_descartadas,
            'n_linhas_anteriores_totais': int(len(anteriores)),
            'rotulo': v.ROTULO_HORIZONTE[lead],
        }
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# Comparação pareada com o Método 3.1 (item 12 do pedido)
# ══════════════════════════════════════════════════════════════════════════

def construir_tabela_aditiva_matched_mos(tabela_aditiva, tabela_mos):
    """'aditiva_matched_mos_sample' — mesma lógica já usada em
    `aditiva_matched_multiplicativo_sample` (Método 3.2): restringe a
    tabela aditiva JÁ APROVADA (lida, nunca reescrita) às chaves
    (init_date, lead) elegíveis do MOS."""
    chaves = tabela_mos[tabela_mos['status_mos'] == STATUS_OK][
        ['init_date', 'lead']].drop_duplicates()
    return tabela_aditiva.merge(chaves, on=['init_date', 'lead'], how='inner')


def construir_tabela_comparacao(tabela_mos, tabela_aditiva):
    """Tabela única usada por TODAS as métricas principais do MOS —
    cada linha tem, lado a lado, forecast_mos E forecast_calibrado
    (Método 3.1) para a MESMA (init_date, lead)."""
    ok_mos = tabela_mos[tabela_mos['status_mos'] == STATUS_OK].dropna(
        subset=['benchmark_anomalia_reconstruida'])
    aditivo_sel = tabela_aditiva[tabela_aditiva['status_calibracao'] == a.STATUS_OK][
        ['init_date', 'lead', 'forecast_calibrado']
    ].rename(columns={'forecast_calibrado': 'forecast_calibrado_aditivo'})
    comparacao = ok_mos.merge(aditivo_sel, on=['init_date', 'lead'], how='inner')
    return comparacao


# ══════════════════════════════════════════════════════════════════════════
# Métricas (itens 11-14, 16-19 do pedido)
# ══════════════════════════════════════════════════════════════════════════

def _stats_coeficiente(serie):
    s = np.asarray(serie, dtype=float)
    s = s[np.isfinite(s)]
    if len(s) == 0:
        return {'n': 0}
    return {
        'n': int(len(s)), 'minimo': float(s.min()), 'p10': float(np.percentile(s, 10)),
        'mediana': float(np.median(s)), 'media': float(s.mean()),
        'p90': float(np.percentile(s, 90)), 'maximo': float(s.max()),
    }


def _metricas_de_subconjunto_mos(sub_comparacao):
    """Núcleo compartilhado por TODAS as agregações do MOS (por
    horizonte, matriz mês×lead, grupo sazonal) — nunca duas fórmulas
    paralelas. `sub_comparacao` precisa vir de `construir_tabela_
    comparacao` (precisa de forecast_calibrado_aditivo)."""
    n = len(sub_comparacao)
    if n == 0:
        return {'n': 0}
    resultado = a._calcular_skills_tres_benchmarks(
        sub_comparacao, 'forecast_mos', 'observacao', 'forecast_raw',
        'climatologia_observada', 'benchmark_anomalia_reconstruida')
    resultado['n'] = n
    resultado['amostra_suficiente'] = n >= v.AMOSTRA_MINIMA_ESTRATO
    # Correção desta revisão: a correlação de anomalia do MÉTODO 3.4
    # precisa usar anom_mos (= forecast_mos - climatologia_observada),
    # nunca a anomalia BRUTA do CFSv2 — corr(anom_modelo_raw,
    # anom_observada) mede o preditor de entrada do OLS, não o
    # resultado do ajuste. As duas são mantidas, com nomes
    # inequívocos; `corr_anomalia_mos` é a métrica PRINCIPAL do
    # Método 3.4.
    resultado['corr_anomalia_raw'] = v._corr(sub_comparacao['anom_modelo_raw'].values,
                                              sub_comparacao['anom_observada'].values)
    resultado['corr_anomalia_mos'] = v._corr(sub_comparacao['anom_mos'].values,
                                              sub_comparacao['anom_observada'].values)

    rmse_mos = resultado['rmse']
    rmse_adit = v._rmse(sub_comparacao['forecast_calibrado_aditivo'].values,
                         sub_comparacao['observacao'].values)
    resultado['rmse_aditivo_matched'] = rmse_adit
    resultado['skill_mos_vs_aditivo'] = v.rmsess(rmse_mos, rmse_adit)

    resultado['alpha'] = _stats_coeficiente(sub_comparacao['alpha'])
    resultado['beta'] = _stats_coeficiente(sub_comparacao['beta'])
    resultado['r2_treino'] = _stats_coeficiente(sub_comparacao['r2_treino'])
    # 'Não usar R² de treino como evidência de skill' — nunca presente
    # numa chave de skill, só reportado isoladamente acima.
    return resultado


def metricas_deterministicas_mos_por_horizonte(comparacao):
    resultado = {}
    for lead in v.LEADS_ESPERADOS:
        sub = comparacao[comparacao['lead'] == lead]
        m = _metricas_de_subconjunto_mos(sub)
        m['rotulo'] = v.ROTULO_HORIZONTE[lead]
        resultado[lead] = m
    return resultado


def matriz_mes_lead_mos(comparacao):
    """Item 18 do pedido — todos os 12 meses (MOS pool entre meses, não
    há meses excluídos por desenho como no Método 3.2) — diagnóstico de
    heterogeneidade, nunca 72 testes de significância."""
    matriz = {}
    for mes in range(1, 13):
        matriz[mes] = {}
        for lead in v.LEADS_ESPERADOS:
            sub = comparacao[(comparacao['target_mes'] == mes) & (comparacao['lead'] == lead)]
            matriz[mes][lead] = _metricas_de_subconjunto_mos(sub)
    return matriz


def matriz_grupo_sazonal_lead_mos(comparacao):
    """Item 19 do pedido — chuvosa/transição/seca × lead, só
    diagnóstico complementar."""
    matriz = {}
    for grupo in ('chuvosa', 'transicao', 'seca'):
        meses_grupo = [m for m, g in v.GRUPO_SAZONAL_POR_MES.items() if g == grupo]
        matriz[grupo] = {}
        for lead in v.LEADS_ESPERADOS:
            sub = comparacao[(comparacao['target_mes'].isin(meses_grupo))
                              & (comparacao['lead'] == lead)]
            matriz[grupo][lead] = _metricas_de_subconjunto_mos(sub)
    return matriz


def diagnostico_heterogeneidade_variancia(tabela_mos):
    """Item 5/6 da revisão — SÓ diagnóstico, sobre os PARES VÁLIDOS
    (independente de status_mos=='ok', porque descreve a população de
    treino em potencial, não a população avaliada). Nunca
    reponderação, padronização ou remoção de mês dominante.

    Métrica PRINCIPAL de influência sobre `beta_lead`: `Sxx`, não
    `sum(x²)`. Com intercepto no OLS, `beta = cov(x,y)/var(x)` e
    `var(x) = Sxx/n`, onde `Sxx = Σ(x_i - x̄_lead)²` — é essa
    quantidade centrada na média, não a soma bruta dos quadrados, que
    corresponde ao denominador efetivo da inclinação. `sum(x²)` é
    mantido como diagnóstico ADICIONAL (nunca a medida principal)."""
    validos = tabela_mos[tabela_mos['par_anomalia_valido']].copy()
    validos['anom_modelo_raw_quadrado'] = validos['anom_modelo_raw'] ** 2
    validos['erro_benchmark3'] = (validos['benchmark_anomalia_reconstruida']
                                   - validos['observacao'])

    x_bar_por_lead = validos.groupby('lead')['anom_modelo_raw'].mean()
    validos['x_bar_lead'] = validos['lead'].map(x_bar_por_lead)
    validos['sxx_contrib'] = (validos['anom_modelo_raw'] - validos['x_bar_lead']) ** 2

    resultado = {}
    soma_sxx_por_lead = validos.groupby('lead')['sxx_contrib'].sum()
    verificacao_soma_participacoes_sxx = {}

    for lead in v.LEADS_ESPERADOS:
        resultado[int(lead)] = {}
        sxx_total_lead = float(soma_sxx_por_lead.get(lead, 0.0))
        soma_participacoes_sxx = 0.0
        for mes in range(1, 13):
            sub = validos[(validos['lead'] == lead) & (validos['target_mes'] == mes)]
            n = len(sub)
            if n == 0:
                resultado[int(lead)][mes] = {'n': 0}
                continue
            sxx_mes = float(sub['sxx_contrib'].sum())
            participacao_sxx = (sxx_mes / sxx_total_lead) if sxx_total_lead > 0 else None
            if participacao_sxx is not None:
                soma_participacoes_sxx += participacao_sxx
            resultado[int(lead)][mes] = {
                'n': n,
                'desvio_padrao_anom_modelo_raw': float(sub['anom_modelo_raw'].std(ddof=0)),
                'desvio_padrao_anom_observada': float(sub['anom_observada'].std(ddof=0)),
                'rmse_benchmark3': float(np.sqrt(np.mean(sub['erro_benchmark3'] ** 2))),
                'sxx_mes': sxx_mes,
                'participacao_sxx_no_lead': participacao_sxx,
                'soma_anom_modelo_raw_quadrado': float(sub['anom_modelo_raw_quadrado'].sum()),
            }
        verificacao_soma_participacoes_sxx[int(lead)] = soma_participacoes_sxx

    ok = all(abs(s - 1.0) < 1e-6 for s in verificacao_soma_participacoes_sxx.values() if s > 0)
    return {
        'matriz': resultado,
        'x_bar_por_lead': {int(lead): float(media) for lead, media in x_bar_por_lead.items()},
        'verificacao_soma_participacoes_sxx_por_lead': verificacao_soma_participacoes_sxx,
        'verificacao_soma_participacoes_sxx_ok': ok,
        'nota': 'só diagnóstico — participação em Sxx (soma centrada na média do lead) é a '
                'métrica PRINCIPAL de influência sobre beta_lead; sum(x²) bruto é mantido só '
                'como diagnóstico adicional. Nenhuma reponderação do OLS, nenhuma '
                'padronização, nenhum mês dominante removido nesta versão do Método 3.4.',
    }


# ══════════════════════════════════════════════════════════════════════════
# Bootstrap — MOS vs. aditivo matched, mesmos blocos (item 13 do pedido)
# ══════════════════════════════════════════════════════════════════════════

def bootstrap_skills_mos_vs_aditivo_por_horizonte(comparacao, n_resamples=500, seed=20261001):
    """Mesmo desenho de `bootstrap_skills_multiplicativa_vs_aditiva_
    por_horizonte` (Método 3.2) — MOS, os três benchmarks E o aditivo
    matched usam os MESMOS blocos de ano sorteados em cada reamostra,
    nunca ICs derivados dividindo intervalos separados."""
    rng = np.random.default_rng(seed)
    resultado = {}

    for lead in v.LEADS_ESPERADOS:
        sub = comparacao[comparacao['lead'] == lead]
        n = len(sub)
        if n < v.AMOSTRA_MINIMA_ESTRATO:
            resultado[lead] = {'n': n, 'amostra_suficiente': False,
                                'nota': 'amostra insuficiente — IC não calculado'}
            continue

        anos = np.array(sorted(sub['target_ano'].unique()))
        if len(anos) < 3:
            resultado[lead] = {'n': n, 'amostra_suficiente': True,
                                'nota': 'menos de 3 anos distintos — bootstrap em blocos não é '
                                        'confiável'}
            continue

        por_ano = {ano: sub[sub['target_ano'] == ano] for ano in anos}

        boot_raw, boot_clim, boot_anom, boot_vs_aditivo = [], [], [], []
        for _ in range(n_resamples):
            anos_sorteados = rng.choice(anos, size=len(anos), replace=True)
            amostra = pd.concat([por_ano[ano] for ano in anos_sorteados], ignore_index=True)

            rmse_mos = v._rmse(amostra['forecast_mos'].values, amostra['observacao'].values)
            rmse_raw = v._rmse(amostra['forecast_raw'].values, amostra['observacao'].values)
            rmse_clim = v._rmse(amostra['climatologia_observada'].values, amostra['observacao'].values)
            rmse_bench3 = v._rmse(amostra['benchmark_anomalia_reconstruida'].values,
                                   amostra['observacao'].values)
            rmse_adit = v._rmse(amostra['forecast_calibrado_aditivo'].values, amostra['observacao'].values)

            s1 = v.rmsess(rmse_mos, rmse_raw)
            s2 = v.rmsess(rmse_mos, rmse_clim)
            s3 = v.rmsess(rmse_mos, rmse_bench3)
            s4 = v.rmsess(rmse_mos, rmse_adit)
            if s1 is not None:
                boot_raw.append(s1)
            if s2 is not None:
                boot_clim.append(s2)
            if s3 is not None:
                boot_anom.append(s3)
            if s4 is not None:
                boot_vs_aditivo.append(s4)

        rmse_mos_p = v._rmse(sub['forecast_mos'].values, sub['observacao'].values)
        rmse_raw_p = v._rmse(sub['forecast_raw'].values, sub['observacao'].values)
        rmse_clim_p = v._rmse(sub['climatologia_observada'].values, sub['observacao'].values)
        rmse_bench3_p = v._rmse(sub['benchmark_anomalia_reconstruida'].values, sub['observacao'].values)
        rmse_adit_p = v._rmse(sub['forecast_calibrado_aditivo'].values, sub['observacao'].values)

        resumo_raw = v._resumo_bootstrap(v.rmsess(rmse_mos_p, rmse_raw_p), boot_raw)
        resumo_clim = v._resumo_bootstrap(v.rmsess(rmse_mos_p, rmse_clim_p), boot_clim)
        resumo_anom = v._resumo_bootstrap(v.rmsess(rmse_mos_p, rmse_bench3_p), boot_anom)
        resumo_vs_aditivo = v._resumo_bootstrap(v.rmsess(rmse_mos_p, rmse_adit_p), boot_vs_aditivo)

        resultado[lead] = {
            'n': n, 'amostra_suficiente': True, 'n_anos_distintos': int(len(anos)),
            'n_resamples': n_resamples,
            'metodo': 'bootstrap em blocos por target_ano — MOS, os três benchmarks E o aditivo '
                      'matched usam os MESMOS blocos sorteados em cada reamostra',
            'skill_vs_raw': resumo_raw,
            'skill_vs_raw_ic_classificacao': v._classificar_ic_relativo_a_zero(
                resumo_raw['ic95_lo'], resumo_raw['ic95_hi']),
            'RMSESS_climatologia': resumo_clim,
            'RMSESS_climatologia_ic_classificacao': v._classificar_ic_relativo_a_zero(
                resumo_clim['ic95_lo'], resumo_clim['ic95_hi']),
            'skill_vs_anomalia_reconstruida': resumo_anom,
            'skill_vs_anomalia_reconstruida_ic_classificacao': v._classificar_ic_relativo_a_zero(
                resumo_anom['ic95_lo'], resumo_anom['ic95_hi']),
            'skill_mos_vs_aditivo': resumo_vs_aditivo,
            'skill_mos_vs_aditivo_ic_classificacao': v._classificar_ic_relativo_a_zero(
                resumo_vs_aditivo['ic95_lo'], resumo_vs_aditivo['ic95_hi']),
            'nota': "Critério de aprovação: IC 95% de skill_vs_anomalia_reconstruida E "
                    "RMSESS_climatologia totalmente acima de zero, SIMULTANEAMENTE. "
                    "skill_mos_vs_aditivo é reportado sempre, mas se seu IC incluir zero, não "
                    "afirmar superioridade do MOS sobre o aditivo.",
        }
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# LOYO (item 20 do pedido)
# ══════════════════════════════════════════════════════════════════════════

def construir_tabela_mos_linear_loyo(base_enriquecida):
    """`mos_loyo_retrospective` — treina por lead excluindo o ANO-ALVO
    INTEIRO (todos os 12 meses daquele ano, já que o MOS pool entre
    meses), usando passado E futuro. Deliberadamente NÃO causal, só
    retrospectivo descritivo, nunca operacional."""
    media_membros = base_enriquecida.groupby(
        ['init_date', 'target_month', 'target_ano', 'target_mes', 'lead'], as_index=False
    ).agg(forecast_raw=('forecast_prec_mm', 'mean'),
          observacao=('obs_prec_mm', 'first'),
          climatologia_observada=('clim_media', 'first'),
          climatologia_modelo_raw=('clim_modelo_media', 'first'))

    linhas = []
    for lead, grupo in media_membros.groupby('lead'):
        bases = {idx: _montar_linha_base(row) for idx, row in grupo.iterrows()}
        grupo = grupo.assign(par_anomalia_valido=[bases[i]['par_anomalia_valido'] for i in grupo.index])

        for idx, row in grupo.iterrows():
            base = bases[idx]
            outros = grupo[grupo['target_ano'] != row['target_ano']]
            outros_validos = outros[outros['par_anomalia_valido']]
            n_treino_loyo = len(outros_validos)

            if not base['par_anomalia_valido']:
                status = STATUS_ANOMALIA_INDISPONIVEL
                alpha = beta = r2_treino = condicao = None
                forecast_mos = None
            elif n_treino_loyo < N_TREINO_MINIMO_MOS:
                status = STATUS_WARMUP
                alpha = beta = r2_treino = condicao = None
                forecast_mos = None
            else:
                x_hist = [bases[i]['anom_modelo_raw'] for i in outros_validos.index]
                y_hist = [bases[i]['anom_observada'] for i in outros_validos.index]
                alpha, beta, r2_treino, condicao, status = _ajustar_ols_simples(x_hist, y_hist)
                if status == STATUS_OK:
                    forecast_mos = float(base['climatologia_observada'] + alpha
                                          + beta * base['anom_modelo_raw'])
                else:
                    forecast_mos = None

            linhas.append({
                'init_date': row['init_date'], 'target_month': row['target_month'],
                'target_ano': int(row['target_ano']), 'target_mes': int(row['target_mes']),
                'lead': int(lead),
                'forecast_raw': base['forecast_raw'], 'observacao': base['observacao'],
                'climatologia_modelo_raw': base['climatologia_modelo_raw'],
                'climatologia_observada': base['climatologia_observada'],
                'anom_modelo_raw': base['anom_modelo_raw'],
                'anom_observada': base['anom_observada'],
                'par_anomalia_valido': base['par_anomalia_valido'],
                'n_treino_mos': n_treino_loyo,
                'alpha': alpha, 'beta': beta, 'r2_treino': r2_treino,
                'condicao_numerica': condicao, 'forecast_mos': forecast_mos,
                'benchmark_anomalia_reconstruida': base['benchmark_anomalia_reconstruida'],
                'status_mos': status,
            })
    tabela = pd.DataFrame(linhas)
    tabela = tabela.assign(_p=pd.PeriodIndex(tabela['init_date'], freq='M')).sort_values(
        ['lead', '_p']).drop(columns='_p').reset_index(drop=True)
    return tabela


def construir_tabela_mos_loyo_matched(tabela_expanding, tabela_loyo):
    """`mos_loyo_matched_evaluation_period` — EXATAMENTE os mesmos
    casos (init_date, lead) usados no expanding (status_mos='ok'),
    mesma lógica de `a.construir_tabela_loyo_matched`."""
    chaves_expanding = tabela_expanding[
        tabela_expanding['status_mos'] == STATUS_OK
    ][['init_date', 'lead']].drop_duplicates()
    matched = tabela_loyo.merge(chaves_expanding, on=['init_date', 'lead'], how='inner')
    return matched


def metricas_deterministicas_loyo_por_horizonte(tabela_loyo, rotulo_coluna_bench3=None):
    """Três benchmarks em desenho LOYO (full ou matched) — reaproveita
    `a._calcular_skills_tres_benchmarks`, sem comparação com o aditivo
    (fora do escopo desta seção; a comparação vs. aditivo já existe no
    expanding, seção principal)."""
    resultado = {}
    for lead in v.LEADS_ESPERADOS:
        sub = tabela_loyo[(tabela_loyo['lead'] == lead)
                           & (tabela_loyo['status_mos'] == STATUS_OK)].dropna(
            subset=['benchmark_anomalia_reconstruida'])
        n = len(sub)
        if n == 0:
            resultado[lead] = {'n_elegivel': 0}
            continue
        base = a._calcular_skills_tres_benchmarks(
            sub, 'forecast_mos', 'observacao', 'forecast_raw',
            'climatologia_observada', 'benchmark_anomalia_reconstruida')
        base['alpha_mediano'] = float(np.median(sub['alpha']))
        base['beta_mediano'] = float(np.median(sub['beta']))
        resultado[lead] = base
    return resultado


def comparar_expanding_vs_loyo_matched_mos(det_expanding, det_loyo_matched):
    comparacao = {}
    for lead in v.LEADS_ESPERADOS:
        e = det_expanding.get(lead, {})
        m = det_loyo_matched.get(lead, {})
        deltas = {}
        for chave in ('skill_vs_raw', 'RMSESS_climatologia', 'skill_vs_anomalia_reconstruida'):
            ve = e.get(chave)
            vm = m.get(chave)
            deltas[f'delta_{chave}'] = float(vm - ve) if ve is not None and vm is not None else None
        comparacao[lead] = {
            'n_expanding': e.get('n', e.get('n_elegivel', 0)),
            'n_loyo_matched': m.get('n_elegivel', m.get('n', 0)),
            'rmse_expanding': e.get('rmse'), 'rmse_loyo_matched': m.get('rmse'),
            **deltas,
            'nota': 'MESMAS chaves (init_date×lead) nos dois lados — delta meramente '
                    'descritivo, nunca teste de significância automático.',
        }
    return comparacao


# ══════════════════════════════════════════════════════════════════════════
# Orquestração
# ══════════════════════════════════════════════════════════════════════════

def _verificar_nan_inf_inesperado(det, boot):
    problemas = []

    def checar(valor, caminho):
        if isinstance(valor, (int, float)) and not isinstance(valor, bool):
            if math.isnan(valor) or math.isinf(valor):
                problemas.append(caminho)

    for lead, dic in det.items():
        for k, val in dic.items():
            if isinstance(val, dict):
                continue
            checar(val, f'det[{lead}][{k}]')
    for lead, dic in boot.items():
        for k, val in dic.items():
            if isinstance(val, dict):
                for kk, vv in val.items():
                    checar(vv, f'boot[{lead}][{k}][{kk}]')
    return {'ok': len(problemas) == 0, 'campos_problema': problemas}


def executar_mos_linear(n_resamples_bootstrap=500):
    """Orquestra o Método 3.4 com STOP-ON-FAILURE explícito em cada
    condição do item 21 do pedido."""
    auditoria = v.executar_auditoria()
    if not auditoria['auditoria_aprovada']:
        return ({'STOP_ON_FAILURE': True,
                 'motivo': 'auditoria da base RAW (2C.3C) reprovada'}, None, None)

    if not a.CAMINHO_TABELA_EXPANDING.exists():
        return ({'STOP_ON_FAILURE': True,
                 'motivo': f'{a.CAMINHO_TABELA_EXPANDING} (Método 3.1, aprovado) não encontrado'},
                None, None)
    tabela_aditiva = pd.read_csv(a.CAMINHO_TABELA_EXPANDING)

    df_raw = v.carregar_cfsv2_raw()
    chirps_df = v.carregar_chirps_v3_historico()
    base = v.construir_base_pareada(df_raw, chirps_df)
    if not v.validar_nenhum_mes_alvo_ausente(base):
        return ({'STOP_ON_FAILURE': True, 'motivo': 'pareamento com mês-alvo ausente'}, None, None)

    base_enriquecida = v._enriquecer_com_climatologia(base, chirps_df)
    tabela = construir_tabela_mos_linear(base_enriquecida)

    contagem = _verificar_contagem_total(tabela)
    if not contagem['ok']:
        return ({'STOP_ON_FAILURE': True,
                 'motivo': f'contagem impossível de treino: {contagem}'}, None, None)

    identidade = a.validar_identidade_benchmark3(tabela)
    if not identidade['identidade_ok']:
        return ({'STOP_ON_FAILURE': True,
                 'motivo': 'benchmark_anomalia_reconstruida não satisfaz a identidade algébrica',
                 'detalhe': identidade}, None, None)

    leakage = _verificar_nenhum_leakage_na_tabela_mos(tabela)
    if not leakage['ok']:
        return ({'STOP_ON_FAILURE': True, 'motivo': 'leakage detectado na tabela MOS',
                 'detalhe': leakage}, None, None)

    contaminacao_lead = _verificar_outro_lead_nunca_contaminou_treino(tabela)
    if not contaminacao_lead['ok']:
        return ({'STOP_ON_FAILURE': True, 'motivo': 'outro lead contaminou o treino do MOS',
                 'detalhe': contaminacao_lead}, None, None)

    n_degenerada = int((tabela['status_mos'] == STATUS_DEGENERADA).sum())
    n_coef_invalido = int((tabela['status_mos'] == STATUS_COEF_INVALIDO).sum())
    if n_degenerada > 0 or n_coef_invalido > 0:
        return ({'STOP_ON_FAILURE': True,
                 'motivo': f'degeneração inesperada na base real: {n_degenerada} regressões '
                           f'degeneradas, {n_coef_invalido} com coeficientes não finitos — '
                           'nunca esperado nesta base, ver protocolo Seção 7'}, None, None)

    n_nan_em_ok = int(tabela[tabela['status_mos'] == STATUS_OK][['alpha', 'beta']].isna().any(
        axis=1).sum())
    if n_nan_em_ok > 0:
        return ({'STOP_ON_FAILURE': True,
                 'motivo': f'{n_nan_em_ok} linha(s) com status_mos=ok mas alpha/beta não '
                           'finitos'}, None, None)

    primeira_elegivel = _primeira_inicializacao_elegivel_por_lead(tabela)

    comparacao = construir_tabela_comparacao(tabela, tabela_aditiva)
    n_ok_mos = int((tabela['status_mos'] == STATUS_OK).sum())
    if len(comparacao) != n_ok_mos:
        return ({'STOP_ON_FAILURE': True,
                 'motivo': f'amostra de aditivo matched diferente da amostra MOS: MOS elegível='
                           f'{n_ok_mos}, após merge com aditivo={len(comparacao)}'}, None, None)

    det = metricas_deterministicas_mos_por_horizonte(comparacao)
    boot = bootstrap_skills_mos_vs_aditivo_por_horizonte(comparacao, n_resamples_bootstrap)
    matriz_mes_lead = matriz_mes_lead_mos(comparacao)
    matriz_grupo = matriz_grupo_sazonal_lead_mos(comparacao)
    heterogeneidade = diagnostico_heterogeneidade_variancia(tabela)

    nan_check = _verificar_nan_inf_inesperado(det, boot)
    if not nan_check['ok']:
        return ({'STOP_ON_FAILURE': True, 'motivo': 'NaN/Inf não explicado nos resultados',
                 'detalhe': nan_check}, None, None)

    # LOYO — item 20
    tabela_loyo = construir_tabela_mos_linear_loyo(base_enriquecida)
    det_loyo_full = metricas_deterministicas_loyo_por_horizonte(tabela_loyo)
    matched_loyo = construir_tabela_mos_loyo_matched(tabela, tabela_loyo)
    det_loyo_matched = metricas_deterministicas_loyo_por_horizonte(matched_loyo)
    comparacao_loyo_matched = comparar_expanding_vs_loyo_matched_mos(det, det_loyo_matched)

    resultado = {
        'STOP_ON_FAILURE': False,
        'metodo': 'mos_linear_causal_no_espaco_de_anomalias_por_lead',
        'n_treino_minimo_mos': N_TREINO_MINIMO_MOS,
        'variancia_minima_anom_modelo': VARIANCIA_MINIMA_ANOM_MODELO,
        'identidade_benchmark3': identidade,
        'leakage_check': leakage,
        'verificacao_outro_lead_nunca_contaminou_treino': contaminacao_lead,
        'primeira_inicializacao_elegivel_por_lead': primeira_elegivel,
        'expanding_operational_simulation': {
            'rotulo': 'mos_linear_expanding_operational_simulation',
            'n_total_elegivel': len(comparacao),
            'deterministico_por_horizonte': det,
            'intervalos_confianca_skills_por_horizonte': boot,
            'matriz_mes_lead': matriz_mes_lead,
            'matriz_grupo_sazonal_lead': matriz_grupo,
            'diagnostico_heterogeneidade_variancia': heterogeneidade,
        },
        'loyo_retrospective': {
            'rotulo': 'mos_loyo_retrospective',
            'aviso': 'NÃO simula uso em tempo real — usa anos futuros (e exclui o ano-alvo '
                     'INTEIRO, todos os 12 meses, do treino). Análise descritiva adicional, '
                     'nunca operacional, amostra DIFERENTE do expanding — nunca comparada '
                     'diretamente. Ver loyo_matched_evaluation_period para a comparação pareada.',
            'deterministico_por_horizonte': det_loyo_full,
        },
        'loyo_matched_evaluation_period': {
            'rotulo': 'mos_loyo_matched_evaluation_period',
            'deterministico_por_horizonte': det_loyo_matched,
            'comparacao_expanding_vs_loyo_matched': comparacao_loyo_matched,
        },
        'nenhuma_calibracao_aplicada_em_producao': True,
        'data_geracao_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    return resultado, tabela, tabela_loyo


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--executar', action='store_true')
    ap.add_argument('--gerar-relatorio', action='store_true')
    args = ap.parse_args()

    if args.executar:
        resultado, tabela, tabela_loyo = executar_mos_linear()
        DIRETORIO_SAIDA.mkdir(parents=True, exist_ok=True)
        CAMINHO_METRICAS_JSON.write_text(
            json.dumps(resultado, indent=2, ensure_ascii=False, default=str))
        print(f"  ✅ {CAMINHO_METRICAS_JSON.relative_to(ROOT)}")
        if resultado.get('STOP_ON_FAILURE'):
            print(f"\n❌ STOP_ON_FAILURE: {resultado.get('motivo')}")
            return
        tabela.to_csv(CAMINHO_TABELA_EXPANDING, index=False)
        print(f"  ✅ {CAMINHO_TABELA_EXPANDING.relative_to(ROOT)}")
        tabela_loyo.to_csv(CAMINHO_TABELA_LOYO, index=False)
        print(f"  ✅ {CAMINHO_TABELA_LOYO.relative_to(ROOT)}")
        return

    if args.gerar_relatorio:
        import cfsv2_relatorio_mos_linear_2c3d as rel
        rel.gerar_e_escrever()
        return

    ap.print_help()


if __name__ == '__main__':
    main()
