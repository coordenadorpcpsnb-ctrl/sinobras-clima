#!/usr/bin/env python3
"""
c3s_multimodel.py — Fase 2B.1: combinação multi-modelo por EQUAL MODEL
WEIGHTING (Seção 9/10/26 da tarefa).

Cada modelo (sistema C3S) pode ter um número de membros diferente
(ECMWF 25, METFR 25, DWD 30, CMCC 40 nos candidatos desta fase — ver
c3s_multimodel_catalogo.py). Concatenar todos os membros de todos os
modelos e tratar como um único ensemble daria peso maior aos modelos
com mais membros — por isso NUNCA fazemos isso.

Regra (Seção 9/10): primeiro calcula-se a estatística de cada modelo
isoladamente (ensemble mean RAW/BC; probabilidades RAW/BC pelos
mesmos tercis leakage-safe) — só DEPOIS os resultados por modelo são
combinados por MÉDIA SIMPLES entre modelos (peso 1/N_modelos,
independente de quantos membros cada um tinha internamente).

NUNCA nesta fase (Seção 26): ranquear modelos, escolher vencedor,
descartar modelo por RMSE local, pesos por skill, otimização de pesos,
ML, stacking, Bayesian model averaging. Primeiro baseline é sempre
equal weighting.
"""

import numpy as np
import pandas as pd

MODELO_AUSENTE_STATUS = 'INCOMPLETE_MODEL_SET'
MODELO_COMPLETO_STATUS = 'OK'


def variantes_comparacao(sistemas):
    """Seção 11 — nomes das variantes que o pipeline deve poder
    produzir: CLIM, <CENTRO>_RAW/<CENTRO>_BC por modelo, e MME_RAW/
    MME_BC no final."""
    variantes = ['CLIM']
    for s in sistemas:
        variantes.append(f'{s.centro}_RAW')
        variantes.append(f'{s.centro}_BC')
    variantes += ['MME_RAW', 'MME_BC']
    return variantes


def mme_deterministico(valores_por_modelo, allow_missing=True):
    """Seção 9 — MME_RAW/MME_BC = média SIMPLES dos ensemble means dos
    modelos (cada modelo pesa 1/N_modelos, nunca ponderado pelo nº de
    membros internos). `valores_por_modelo`: dict {chave_modelo: valor
    (float ou None/NaN/inf)}.

    `allow_missing` (correção pós-run real 35437819463, Seção 5):
      - True (default, uso normal para BC) — valores None/NaN/inf são
        EXCLUÍDOS da média (não é a barreira de 'modelo ausente bloqueia
        MME' — essa é tratada em separado por quem orquestra, Seção 25,
        comparando contra o conjunto de modelos CONFIGURADOS, não contra
        o que sobrou aqui). BC pode legitimamente faltar por falta de
        histórico — Seção 23/24, nunca um bug.
      - False (uso para RAW, quando os modelos já estão confirmados
        presentes) — um valor None/NaN/inf de QUALQUER modelo levanta
        ValueError em vez de ser silenciosamente descartado. RAW nunca
        deveria ser não-finito quando o modelo está disponível (a
        barreira F de processar_origem_modelo já garante c3s_prec_mm
        finito) — um RAW não-finito aqui é inconsistência do pipeline,
        não falta de histórico, e mascarar isso calculando um MME com
        os modelos restantes esconderia um bug real.

    Devolve None se nenhum modelo tiver valor válido (só possível com
    allow_missing=True — com allow_missing=False, qualquer ausência já
    levanta ValueError antes de chegar nesse caso)."""
    invalidos = {m: v for m, v in valores_por_modelo.items()
                 if v is None or not np.isfinite(v)}
    if invalidos and not allow_missing:
        raise ValueError(f"valor(es) não finito(s)/ausente(s) onde todos os modelos deveriam ter "
                          f"RAW válido (allow_missing=False): {invalidos}")
    validos = [v for v in valores_por_modelo.values() if v is not None and np.isfinite(v)]
    if not validos:
        return None
    return float(np.mean(validos))


def _classificar_tripla(tripla):
    """Correção pós-run real 35437819463 (Seção 1/3/4): classifica uma
    tripla (below, normal, above) usando np.isfinite — nunca só `is not
    None`, porque `np.nan is not None` é True e uma tripla (NaN, NaN,
    NaN) passava como "válida" antes desta correção, gerando
    `soma=nan`, `np.isclose(nan, 1.0)` False e um ValueError espúrio
    (BC/climatologia indisponível por falta de histórico não é erro —
    Seção 2).

    Devolve:
      - 'ausente' — os TRÊS valores são None/NaN/inf (indisponível,
        esperado quando não há histórico suficiente).
      - 'valida' — os TRÊS valores são finitos.
      - 'corrompida' — mistura dos dois (ex.: 0.4, NaN, 0.6) — NUNCA
        deveria acontecer; é inconsistência real do pipeline, não falta
        de histórico, e por isso levanta erro em vez de ser tratada
        como ausente ou válida."""
    ausentes = [v is None or not np.isfinite(v) for v in tripla]
    if all(ausentes):
        return 'ausente'
    if not any(ausentes):
        return 'valida'
    return 'corrompida'


def mme_probabilistico(probs_por_modelo, tolerancia=1e-6):
    """Seção 10 — MME_P_below/normal/above = média das probabilidades
    dos modelos (equal weighting), NUNCA misturando membros de modelos
    diferentes. `probs_por_modelo`: dict {chave_modelo: (below, normal,
    above) ou None}.

    Cada tripla é classificada por `_classificar_tripla` (correção
    pós-run real 35437819463): 'ausente' (todos None/NaN/inf, ou o
    próprio valor do dict é None) é EXCLUÍDA da média sem erro — falta
    de histórico é esperada, nunca bug; 'corrompida' (mistura de
    finito com None/NaN/inf) levanta ValueError imediatamente — isso
    sim é inconsistência real. Toda tripla 'valida' (e o resultado do
    MME) precisa somar 1 dentro da tolerância numérica — levanta
    ValueError explícito se não somar (nunca normaliza silenciosamente).
    Devolve (None, None, None) se nenhum modelo tiver tripla válida."""
    validos = []
    for modelo, tripla in probs_por_modelo.items():
        if tripla is None:
            continue
        classe = _classificar_tripla(tripla)
        if classe == 'ausente':
            continue
        if classe == 'corrompida':
            raise ValueError(f"tripla de probabilidade do modelo {modelo!r} parcialmente preenchida "
                              f"— mistura de valor(es) finito(s) com None/NaN/inf, nunca deveria "
                              f"acontecer: {tripla}")
        below, normal, above = tripla
        soma = below + normal + above
        if not np.isclose(soma, 1.0, atol=tolerancia):
            raise ValueError(f"probabilidades do modelo {modelo!r} não somam 1 (soma={soma}): "
                              f"below={below}, normal={normal}, above={above}")
        validos.append(tripla)

    if not validos:
        return None, None, None
    mme_below = float(np.mean([t[0] for t in validos]))
    mme_normal = float(np.mean([t[1] for t in validos]))
    mme_above = float(np.mean([t[2] for t in validos]))
    soma_mme = mme_below + mme_normal + mme_above
    if not np.isclose(soma_mme, 1.0, atol=tolerancia):
        raise ValueError(f"MME de probabilidades não soma 1 (soma={soma_mme}) — "
                          f"below={mme_below}, normal={mme_normal}, above={mme_above}")
    return mme_below, mme_normal, mme_above


def status_conjunto_modelos(modelos_configurados, modelos_disponiveis):
    """Seção 25 — MME só pode ser calculado se TODOS os modelos
    configurados para aquela comparação estiverem disponíveis. Se
    algum modelo configurado faltar (não excluído formalmente ANTES da
    execução — essa exclusão é decidida no catálogo, nunca aqui em
    tempo de execução), devolve INCOMPLETE_MODEL_SET; caso contrário
    OK. `modelos_configurados`/`modelos_disponiveis`: coleções de
    chaves de modelo (ex.: 'ECMWF', 'DWD')."""
    faltando = set(modelos_configurados) - set(modelos_disponiveis)
    if faltando:
        return MODELO_AUSENTE_STATUS, sorted(faltando)
    return MODELO_COMPLETO_STATUS, []


MME_COLUNAS = ['init_date', 'target_month', 'lead', 'n_models_available', 'models_used',
               'model_set_status', 'mme_mean_raw', 'mme_mean_bc',
               'prob_below_raw', 'prob_normal_raw', 'prob_above_raw',
               'prob_below_bc', 'prob_normal_bc', 'prob_above_bc',
               'raw_available', 'bc_available', 'raw_prob_available', 'bc_prob_available', 'raw_error']


def construir_mme_por_origem_lead(summary_df, modelos_configurados, coluna_modelo='centre'):
    """Constrói 1 linha de MME por (init_date, lead) a partir de um
    summary_df já calculado por modelo (colunas mínimas: init_date,
    target_month, lead, <coluna_modelo>, ens_mean_raw, ens_mean_bc,
    prob_below_raw, prob_normal_raw, prob_above_raw, prob_below_bc,
    prob_normal_bc, prob_above_bc). RAW nunca é alterado pela
    combinação (Seção 26-L) — só lido, nunca modificado in-place.

    Se algum modelo de `modelos_configurados` estiver ausente para uma
    combinação (init_date, lead), a linha inteira vem com
    model_set_status=INCOMPLETE_MODEL_SET e mme_mean_raw/bc/probs=None
    — nunca calcula um MME parcial silenciosamente (Seção 25). Essa
    barreira é sobre PRESENÇA DE MODELO — nunca confundida com
    disponibilidade de BC (Seção 6 da correção pós-run real
    35437819463): os 4 modelos podem estar todos presentes
    (model_set_status=OK) mesmo com BC/probabilidades indisponíveis por
    falta de histórico, refletido nas colunas raw_available/
    bc_available/raw_prob_available/bc_prob_available (Seção 7).

    RAW determinístico usa allow_missing=False (Seção 5): um valor não
    finito nele, com o modelo presente, é inconsistência real do
    pipeline (nunca falta de histórico) — é capturado explicitamente e
    registrado em `raw_error`, nunca deixado mascarar um MME parcial
    silencioso (Seção 5/8-H)."""
    if summary_df.empty:
        return pd.DataFrame(columns=MME_COLUNAS)

    linhas = []
    for (init_date, lead), g in summary_df.groupby(['init_date', 'lead']):
        target_month = g['target_month'].iloc[0]
        modelos_disponiveis = sorted(g[coluna_modelo].unique())
        status, faltando = status_conjunto_modelos(modelos_configurados, modelos_disponiveis)

        valores_raw = dict(zip(g[coluna_modelo], g['ens_mean_raw']))
        valores_bc = dict(zip(g[coluna_modelo], g.get('ens_mean_bc', pd.Series(dtype=float))))
        probs_raw = {m: (r['prob_below_raw'], r['prob_normal_raw'], r['prob_above_raw'])
                     for m, r in zip(g[coluna_modelo], g.to_dict('records'))}
        probs_bc = {m: (r['prob_below_bc'], r['prob_normal_bc'], r['prob_above_bc'])
                    for m, r in zip(g[coluna_modelo], g.to_dict('records'))}

        if status == MODELO_AUSENTE_STATUS:
            linhas.append({
                'init_date': init_date, 'target_month': target_month, 'lead': lead,
                'n_models_available': len(modelos_disponiveis), 'models_used': ','.join(modelos_disponiveis),
                'model_set_status': status,
                'mme_mean_raw': None, 'mme_mean_bc': None,
                'prob_below_raw': None, 'prob_normal_raw': None, 'prob_above_raw': None,
                'prob_below_bc': None, 'prob_normal_bc': None, 'prob_above_bc': None,
                'raw_available': False, 'bc_available': False,
                'raw_prob_available': False, 'bc_prob_available': False,
                'raw_error': f'modelo(s) ausente(s): {faltando}',
            })
            continue

        raw_error = None
        try:
            mme_raw = mme_deterministico(valores_raw, allow_missing=False)
        except ValueError as e:
            mme_raw = None
            raw_error = str(e)
        mme_bc = mme_deterministico(valores_bc, allow_missing=True)
        pb_raw, pn_raw, pa_raw = mme_probabilistico(probs_raw)
        pb_bc, pn_bc, pa_bc = mme_probabilistico(probs_bc)

        linhas.append({
            'init_date': init_date, 'target_month': target_month, 'lead': lead,
            'n_models_available': len(modelos_disponiveis), 'models_used': ','.join(modelos_disponiveis),
            'model_set_status': status,
            'mme_mean_raw': mme_raw, 'mme_mean_bc': mme_bc,
            'prob_below_raw': pb_raw, 'prob_normal_raw': pn_raw, 'prob_above_raw': pa_raw,
            'prob_below_bc': pb_bc, 'prob_normal_bc': pn_bc, 'prob_above_bc': pa_bc,
            'raw_available': mme_raw is not None, 'bc_available': mme_bc is not None,
            'raw_prob_available': pb_raw is not None, 'bc_prob_available': pb_bc is not None,
            'raw_error': raw_error,
        })

    return pd.DataFrame(linhas).sort_values(['init_date', 'lead']).reset_index(drop=True)
