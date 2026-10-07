#!/usr/bin/env python3
"""
cfsv2_gate_calibracao_probabilistica.py — Fase 2C.3D: GATE DIAGNÓSTICO
do Método 3.5 (calibração probabilística do ensemble). NUNCA ajusta
EMOS, nunca recalibra membros, nunca aplica dressing, nunca executa
quantile mapping probabilístico, nunca altera probabilidades
operacionais nem o dashboard. O único objetivo é responder, com os
fatos primeiro, se a dispersão dos 24 membros do CFSv2 contém
informação útil sobre a incerteza/erro da previsão.

Unidade de análise: 1 linha por (init_date, lead), com os 24 membros
mantidos SÓ para estatísticas internas do ensemble — nunca tratados
como 24 anos/observações históricas independentes (nenhum bootstrap
deste módulo resample membros; todos resample ANOS, em blocos, mesmo
padrão já usado em `cfsv2_validacao_cientifica.bootstrap_blocos_por_
ano`).

Reaproveita integralmente as definições já aprovadas da 2C.3C para
CRPS (`crps_amostral`) e tercis (`categoria_tercil`) — nunca uma
segunda fórmula paralela. `avaliar_probabilistico_por_horizonte`
(2C.3C) seria reaproveitada diretamente para H1-H6, mas as
decomposições por mês/grupo sazonal (item 10 do pedido) exigem filtrar
as mesmas `linhas` por `target_mes` — por isso este módulo expõe
`_resumo_probabilistico` como o núcleo ÚNICO compartilhado entre
horizonte completo, mês×lead e grupo sazonal×lead.

Única exceção ao reuso literal: o rank histogram (item 5) usa
`_rank_observacao_determinístico`, próprio deste módulo, porque o
pedido exige tie-break explícito e determinístico — `v.rank_
observacao` (2C.3C) resolve empates por sorteio seedado, reprodutível
mas não determinístico no sentido de regra fixa. Ver nota na seção
correspondente.

Roda com:
    python scripts/cfsv2_gate_calibracao_probabilistica.py --executar
    python scripts/cfsv2_gate_calibracao_probabilistica.py --gerar-relatorio
"""

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sstats

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import cfsv2_calibracao_aditiva as a  # noqa: E402
import cfsv2_validacao_cientifica as v  # noqa: E402

DIRETORIO_SAIDA = a.DIRETORIO_SAIDA
CAMINHO_METRICAS_JSON = DIRETORIO_SAIDA / 'gate_calibracao_probabilistica_2c3d.json'
RELATORIO_PATH = ROOT / 'docs' / 'nmme-fase2c3d-gate-calibracao-probabilistica-cfsv2.md'

NOMES_MES = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']

CLASSIFICACAO_INFORMATIVO = 'spread_informativo'
CLASSIFICACAO_POUCO_INFORMATIVO = 'spread_pouco_informativo'
CLASSIFICACAO_MAL_CALIBRADO_POTENCIAL = 'ensemble_mal_calibrado_mas_potencialmente_calibravel'


# ══════════════════════════════════════════════════════════════════════════
# Item 1 do pedido — unidade de análise: 1 linha por (init_date, lead)
# ══════════════════════════════════════════════════════════════════════════

def construir_tabela_ensemble(base_pareada):
    """Para cada (init_date, lead), calcula estatísticas do ensemble
    SOBRE OS MEMBROS (nunca entre inicializações): ensemble_mean,
    ensemble_median, ensemble_std (ddof=1 — convenção explícita, nunca
    ambígua), ensemble_variance (= ensemble_std²), ensemble_iqr (p75-
    p25), ensemble_min/max/range, e `n_membros_real`. Os 24 valores
    brutos são preservados em `membros` (lista), usados só para CRPS/
    rank histogram/cobertura — NUNCA como 24 observações históricas
    independentes em nenhum bootstrap deste módulo."""
    linhas = []
    for (init_date, target_month, target_ano, target_mes, lead), grupo in base_pareada.groupby(
            ['init_date', 'target_month', 'target_ano', 'target_mes', 'lead']):
        membros = np.asarray(grupo['forecast_prec_mm'].values, dtype=float)
        obs = float(grupo['obs_prec_mm'].iloc[0])
        n_membros_real = len(membros)
        ensemble_mean = float(membros.mean())
        linhas.append({
            'init_date': init_date, 'target_month': target_month,
            'target_ano': int(target_ano), 'target_mes': int(target_mes), 'lead': int(lead),
            'n_membros_real': n_membros_real,
            'ensemble_mean': ensemble_mean,
            'ensemble_median': float(np.median(membros)),
            'ensemble_std': float(np.std(membros, ddof=1)) if n_membros_real > 1 else None,
            'ensemble_variance': float(np.var(membros, ddof=1)) if n_membros_real > 1 else None,
            'ensemble_iqr': float(np.percentile(membros, 75) - np.percentile(membros, 25)),
            'ensemble_min': float(membros.min()), 'ensemble_max': float(membros.max()),
            'ensemble_range': float(membros.max() - membros.min()),
            'observacao': obs,
            'erro_abs': float(abs(ensemble_mean - obs)),
            'erro_quadratico': float((ensemble_mean - obs) ** 2),
            'erro_assinado': float(ensemble_mean - obs),
            'membros': membros,
        })
    tabela = pd.DataFrame(linhas)
    tabela = tabela.assign(_p=pd.PeriodIndex(tabela['init_date'], freq='M')).sort_values(
        ['lead', '_p']).drop(columns='_p').reset_index(drop=True)
    return tabela


def _verificar_24_membros(tabela_ensemble):
    """Item 1 do pedido — STOP-ON-FAILURE se uma inicialização
    esperada não tiver exatamente 24 membros, salvo condição JÁ
    documentada na base (nenhuma é conhecida no momento desta
    atividade — se a auditoria da 2C.3C mudar isso no futuro, esta
    checagem precisa ser revisada junto)."""
    divergentes = tabela_ensemble[tabela_ensemble['n_membros_real'] != v.N_MEMBROS_ESPERADO]
    return {
        'ok': len(divergentes) == 0,
        'n_linhas_divergentes': int(len(divergentes)),
        'exemplos': divergentes[['init_date', 'lead', 'n_membros_real']].head(20).to_dict('records'),
    }


# ══════════════════════════════════════════════════════════════════════════
# Item 3/4 do pedido — spread-skill e spread-error ratio
# ══════════════════════════════════════════════════════════════════════════

def _corr_spearman(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) < 2 or np.std(x) == 0 or np.std(y) == 0:
        return None
    rho = sstats.spearmanr(x, y).correlation
    return float(rho) if np.isfinite(rho) else None


def spread_skill_por_horizonte(tabela_ensemble, n_resamples=500, seed=20261001):
    """Item 3 do pedido — Pearson e Spearman entre `ensemble_std` e
    `erro_abs`, e Pearson entre `ensemble_variance` e `erro_
    quadratico`, por H1-H6, com IC 95% via bootstrap em BLOCOS DE ANO
    (`v.bootstrap_blocos_por_ano`, reaproveitado sem modificação —
    nunca um bootstrap que resample membros ou linhas individuais).
    Nunca declara relação útil só por correlação pontual positiva — a
    classificação fica para o gate (item 11), nunca aqui."""
    resultado = {}
    for lead in v.LEADS_ESPERADOS:
        sub = tabela_ensemble[tabela_ensemble['lead'] == lead].dropna(
            subset=['ensemble_std', 'ensemble_variance'])
        n = len(sub)
        if n < v.AMOSTRA_MINIMA_ESTRATO:
            resultado[lead] = {'n': n, 'amostra_suficiente': False,
                                'nota': 'amostra insuficiente — IC não calculado'}
            continue

        pearson_std_abs = v.bootstrap_blocos_por_ano(
            sub, 'ensemble_std', 'erro_abs', 'target_ano', v._corr, n_resamples, seed)
        spearman_std_abs = v.bootstrap_blocos_por_ano(
            sub, 'ensemble_std', 'erro_abs', 'target_ano', _corr_spearman, n_resamples, seed)
        pearson_var_quad = v.bootstrap_blocos_por_ano(
            sub, 'ensemble_variance', 'erro_quadratico', 'target_ano', v._corr, n_resamples, seed)

        resultado[lead] = {
            'n': n, 'amostra_suficiente': True,
            'pearson_std_vs_erro_abs': pearson_std_abs,
            'pearson_std_vs_erro_abs_ic_classificacao': v._classificar_ic_relativo_a_zero(
                pearson_std_abs['ic95_lo'], pearson_std_abs['ic95_hi']),
            'spearman_std_vs_erro_abs': spearman_std_abs,
            'spearman_std_vs_erro_abs_ic_classificacao': v._classificar_ic_relativo_a_zero(
                spearman_std_abs['ic95_lo'], spearman_std_abs['ic95_hi']),
            'pearson_variance_vs_erro_quadratico': pearson_var_quad,
            'pearson_variance_vs_erro_quadratico_ic_classificacao': v._classificar_ic_relativo_a_zero(
                pearson_var_quad['ic95_lo'], pearson_var_quad['ic95_hi']),
            'nota': 'IC nunca convertido automaticamente em "relação útil" — ver '
                    '*_ic_classificacao. Correlação pontual positiva isolada NUNCA é suficiente '
                    '(item 3 do pedido).',
        }
    return resultado


def spread_error_ratio_por_horizonte(tabela_ensemble):
    """Item 4 do pedido — spread_error_ratio = mean(ensemble_std) /
    RMSE(ensemble_mean, observacao), por horizonte. Interpretação
    SEMPRE só como diagnóstico (nunca prova isolada de calibração)."""
    resultado = {}
    for lead in v.LEADS_ESPERADOS:
        sub = tabela_ensemble[tabela_ensemble['lead'] == lead].dropna(subset=['ensemble_std'])
        n = len(sub)
        if n == 0:
            resultado[lead] = {'n': 0}
            continue
        spread_medio = float(sub['ensemble_std'].mean())
        rmse_ensemble_mean = v._rmse(sub['ensemble_mean'].values, sub['observacao'].values)
        ratio = spread_medio / rmse_ensemble_mean if rmse_ensemble_mean else None
        if ratio is None:
            leitura = 'RMSE zero — ratio não aplicável'
        elif ratio < 0.8:
            leitura = 'muito abaixo de 1 — ensemble potencialmente UNDERdispersive'
        elif ratio > 1.2:
            leitura = 'muito acima de 1 — ensemble potencialmente OVERdispersive'
        else:
            leitura = 'próximo de 1 — dispersão média comparável ao erro'
        resultado[lead] = {
            'n': n, 'spread_medio': spread_medio, 'rmse_ensemble_mean': rmse_ensemble_mean,
            'spread_error_ratio': ratio, 'leitura_diagnostica': leitura,
            'nota': 'Nunca usado isoladamente como prova de calibração (item 4 do pedido).',
        }
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# Item 6 do pedido — cobertura de intervalos empíricos (membros RAW)
# ══════════════════════════════════════════════════════════════════════════

_INTERVALOS_NOMINAIS = {50: (25, 75), 80: (10, 90), 90: (5, 95)}


def cobertura_intervalos_por_horizonte(tabela_ensemble):
    """Item 6 do pedido — intervalos EMPÍRICOS (percentis dos 24
    membros RAW, nunca uma distribuição assumida), cobertura nominal
    vs. observada e largura média, por horizonte. NUNCA calibra os
    intervalos nesta etapa — só diagnostica."""
    resultado = {}
    for lead in v.LEADS_ESPERADOS:
        sub = tabela_ensemble[tabela_ensemble['lead'] == lead]
        n = len(sub)
        if n == 0:
            resultado[lead] = {'n': 0}
            continue
        por_intervalo = {}
        for nominal, (p_lo, p_hi) in _INTERVALOS_NOMINAIS.items():
            dentro, larguras = [], []
            for membros, obs in zip(sub['membros'], sub['observacao']):
                lo = np.percentile(membros, p_lo)
                hi = np.percentile(membros, p_hi)
                dentro.append(1.0 if lo <= obs <= hi else 0.0)
                larguras.append(float(hi - lo))
            cobertura_observada = float(np.mean(dentro))
            por_intervalo[nominal] = {
                'cobertura_nominal': nominal / 100.0,
                'cobertura_observada': cobertura_observada,
                'largura_media': float(np.mean(larguras)),
                'coverage_error': float(cobertura_observada - nominal / 100.0),
            }
        resultado[lead] = {'n': n, 'intervalos': por_intervalo}
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# Itens 5, 7, 8 do pedido — rank histogram, CRPS RAW e Brier/tercis,
# reaproveitando EXATAMENTE as definições já aprovadas da 2C.3C para
# CRPS (`crps_amostral`) e tercis (`categoria_tercil`) — núcleo único
# compartilhado entre horizonte completo, mês×lead e grupo sazonal×lead.
#
# Rank histogram É A ÚNICA EXCEÇÃO ao reaproveitamento literal: o item
# 5 do pedido exige tie-break "explícito e determinístico", e
# `v.rank_observacao` resolve empates por sorteio (`rng.integers`) —
# reprodutível com seed fixa, mas não determinístico no sentido de
# regra fixa (duas sessões com seeds diferentes dariam ranks
# diferentes para a mesma linha). Essa exigência é NOVA e específica
# deste gate (nenhum chamador anterior de `v.rank_observacao` precisou
# disso) — por isso `_rank_observacao_determinístico` abaixo, nunca
# reescrevendo `v.rank_observacao` em si (que continua servindo seus
# chamadores existentes da 2C.3C sem alteração).
# ══════════════════════════════════════════════════════════════════════════

def _rank_observacao_determinístico(membros, obs):
    """Posição (1..M+1) da observação entre os M membros — item 5 do
    pedido. Convenção EXPLÍCITA e DETERMINÍSTICA (nunca aleatória,
    mesmo com seed): sem empate, é a posição única de sempre
    (nº de membros menores + 1). Com empate, as posições válidas
    formam um intervalo contíguo [menores+1, menores+iguais+1]; a
    convenção fixa é sempre o PONTO MÉDIO desse intervalo,
    arredondado para o inteiro mais próximo com meio-para-cima em caso
    de 0,5 exato (`math.floor(x + 0.5)`) — mesma entrada sempre produz
    a mesma saída, sem RNG."""
    x = np.asarray(membros, dtype=float)
    menores = int(np.sum(x < obs))
    iguais = int(np.sum(x == obs))
    rank_min = menores + 1
    rank_max = menores + iguais + 1
    return int(math.floor((rank_min + rank_max) / 2.0 + 0.5))


def _linhas_com_mes(base_enriquecida, chirps_df, lead):
    """`v.construir_linhas_avaliacao_por_lead` (2C.3C, reaproveitada
    sem modificação) não inclui `target_mes` — item 10 do pedido exige
    decompor por mês/grupo sazonal, então esta função só ACRESCENTA
    `target_mes` a cada linha (de `base_enriquecida`, mesma fonte),
    nunca recalculando nenhuma climatologia/CRPS/rank por conta
    própria."""
    linhas = v.construir_linhas_avaliacao_por_lead(base_enriquecida, chirps_df, lead)
    mes_por_init = base_enriquecida[base_enriquecida['lead'] == lead].drop_duplicates(
        'init_date').set_index('init_date')['target_mes']
    for linha in linhas:
        linha['target_mes'] = int(mes_por_init[linha['init_date']])
    return linhas


def _resumo_probabilistico(linhas):
    """Núcleo ÚNICO (item 5/7/8 do pedido) — mesma lógica e MESMAS
    fórmulas do corpo de `v.avaliar_probabilistico_por_horizonte`
    (crps_amostral, categoria_tercil, BS_ref_nominal = mean((1/3-o)^2)),
    generalizada para qualquer lista `linhas` já filtrada (horizonte
    completo, 1 mês, 1 grupo sazonal) — nunca uma segunda fórmula
    paralela, só um reaproveitamento parametrizado. Único desvio
    deliberado: rank histogram usa `_rank_observacao_determinístico`
    (acima), não `v.rank_observacao` — ver nota da seção."""
    n = len(linhas)
    if n == 0:
        return {'n': 0}

    crps_modelo_lista, crps_clim_lista, ranks = [], [], []
    prob_seco, prob_normal, prob_umido = [], [], []
    obs_cat_seco, obs_cat_normal, obs_cat_umido = [], [], []

    for linha in linhas:
        membros, obs = linha['membros'], linha['observado']
        t33, t67 = linha['tercil_33'], linha['tercil_67']
        anos_hist = linha['anos_hist']

        crps_modelo_lista.append(v.crps_amostral(membros, obs))
        crps_clim_lista.append(v.crps_amostral(anos_hist, obs) if len(anos_hist) >= 2 else np.nan)
        ranks.append(_rank_observacao_determinístico(membros, obs))

        p_seco = float(np.mean(membros <= t33))
        p_umido = float(np.mean(membros >= t67))
        p_normal = max(0.0, 1.0 - p_seco - p_umido)
        cat_obs = v.categoria_tercil(obs, t33, t67)
        prob_seco.append(p_seco); prob_normal.append(p_normal); prob_umido.append(p_umido)
        obs_cat_seco.append(1.0 if cat_obs == 'seco' else 0.0)
        obs_cat_normal.append(1.0 if cat_obs == 'normal' else 0.0)
        obs_cat_umido.append(1.0 if cat_obs == 'umido' else 0.0)

    crps_modelo = np.array(crps_modelo_lista)
    crps_clim = np.array(crps_clim_lista)
    validos = ~np.isnan(crps_clim)
    crps_medio_modelo = float(crps_modelo.mean())
    crps_medio_clim = float(crps_clim[validos].mean()) if validos.any() else None
    crpss = (1 - crps_medio_modelo / crps_medio_clim) if crps_medio_clim else None

    n_membros = len(linhas[0]['membros'])
    ranks_arr = np.array(ranks)
    hist_rank = {int(r): int((ranks_arr == r).sum()) for r in range(1, n_membros + 2)}

    # Item 5 — diagnóstico derivado do histograma: frequência nos
    # ranks extremos (1 e M+1, o próprio rank mais baixo/mais alto
    # possível — U-shape = underdispersion), frequência central
    # (terço central dos ranks — concentração = overdispersion), e
    # desvio de uniformidade = soma dos desvios absolutos da
    # frequência esperada sob uniformidade (1/(M+1) cada), medida
    # simples e determinística, nunca um teste de hipótese formal.
    n_ranks = n_membros + 1
    freq_extrema = (hist_rank[1] + hist_rank[n_ranks]) / n if n > 0 else None
    tercio = max(1, n_ranks // 3)
    centro_ini = (n_ranks - tercio) // 2 + 1
    centro_fim = centro_ini + tercio - 1
    freq_central = sum(hist_rank.get(r, 0) for r in range(centro_ini, centro_fim + 1)) / n if n > 0 else None
    esperado_uniforme = n / n_ranks
    desvio_uniformidade = (sum(abs(hist_rank[r] - esperado_uniforme) for r in range(1, n_ranks + 1))
                            / n if n > 0 else None)

    bs, bss, bs_ref_nominal, freq_observada = {}, {}, {}, {}
    mapa = {'seco': (np.array(prob_seco), np.array(obs_cat_seco)),
            'normal': (np.array(prob_normal), np.array(obs_cat_normal)),
            'umido': (np.array(prob_umido), np.array(obs_cat_umido))}
    for cat, (p, o) in mapa.items():
        bs[cat] = float(np.mean((p - o) ** 2))
        bs_ref_nom = float(np.mean((1 / 3 - o) ** 2))
        bs_ref_nominal[cat] = bs_ref_nom
        bss[cat] = float(1 - bs[cat] / bs_ref_nom) if bs_ref_nom > 0 else None
        freq_observada[cat] = float(o.mean())

    return {
        'n': n,
        'crps_medio_modelo': crps_medio_modelo, 'crps_medio_climatologia': crps_medio_clim,
        'crpss': crpss,
        'rank_histogram': hist_rank,
        'rank_histogram_diagnostico': {
            'n_ranks_possiveis': n_ranks,
            'frequencia_ranks_extremos': freq_extrema,
            'frequencia_central': freq_central,
            'desvio_uniformidade': desvio_uniformidade,
            'esperado_sob_uniformidade_por_rank': esperado_uniforme,
            'nota': 'Medida simples e determinística — nunca um teste de hipótese sofisticado '
                    'como critério único (item 5 do pedido). freq_ranks_extremos alto sugere '
                    'underdispersion (formato em U); freq_central alto sugere overdispersion/'
                    'concentração; assimetria entre ranks baixos e altos sugere viés.',
        },
        'brier_score_por_categoria': bs,
        'brier_referencia_nominal_por_categoria': bs_ref_nominal,
        'bss_por_categoria': bss,
        'frequencia_observada_por_categoria': freq_observada,
        'formula_bss': 'BSS = 1 - BS_modelo / BS_referencia_nominal, BS_referencia_nominal = '
                       'mean((1/3 - o_i)^2) — mesma fórmula já aprovada na 2C.3C, nunca a '
                       'constante 2/9.',
    }


def probabilistico_por_horizonte(base_enriquecida, chirps_df):
    resultado = {}
    for lead in v.LEADS_ESPERADOS:
        linhas = _linhas_com_mes(base_enriquecida, chirps_df, lead)
        resultado[lead] = _resumo_probabilistico(linhas)
        resultado[lead]['rotulo'] = v.ROTULO_HORIZONTE[lead]
    return resultado


def probabilistico_matriz_mes_lead(base_enriquecida, chirps_df):
    """Item 10 do pedido — SÓ diagnóstico descritivo, nunca 72 testes
    independentes."""
    matriz = {}
    for lead in v.LEADS_ESPERADOS:
        linhas = _linhas_com_mes(base_enriquecida, chirps_df, lead)
        for mes in range(1, 13):
            linhas_mes = [l for l in linhas if l['target_mes'] == mes]
            matriz.setdefault(mes, {})[lead] = _resumo_probabilistico(linhas_mes)
    return matriz


def probabilistico_matriz_grupo_sazonal_lead(base_enriquecida, chirps_df):
    matriz = {}
    for lead in v.LEADS_ESPERADOS:
        linhas = _linhas_com_mes(base_enriquecida, chirps_df, lead)
        for grupo in ('chuvosa', 'transicao', 'seca'):
            meses_grupo = {m for m, g in v.GRUPO_SAZONAL_POR_MES.items() if g == grupo}
            linhas_grupo = [l for l in linhas if l['target_mes'] in meses_grupo]
            matriz.setdefault(grupo, {})[lead] = _resumo_probabilistico(linhas_grupo)
    return matriz


# ══════════════════════════════════════════════════════════════════════════
# Item 9 do pedido — dependência/diversidade entre membros
# ══════════════════════════════════════════════════════════════════════════

def dependencia_membros_por_horizonte(base_pareada):
    """Diagnostica quanto os 24 membros são realmente diversos ao
    longo do tempo (nunca usado para inflar N histórico — item 9).
    Para cada lead, monta a matriz (n_inits × 24 membros) e calcula a
    correlação de Pearson par-a-par entre as 24 SÉRIES TEMPORAIS de
    membro (cada membro como uma série ao longo das inicializações
    daquele lead) — a média das correlações fora da diagonal mede
    redundância: perto de 1 = membros quase idênticos (pouca
    diversidade real); perto de 0 = membros efetivamente
    independentes.

    `effective_ensemble_size` aproximado usa a formulação clássica de
    tamanho efetivo de amostra correlacionada (ex.: Bretherton et al.
    1999, adaptada): ESS = M / (1 + (M-1) * rho_media), onde M é o
    número de membros e rho_media a correlação par-a-par média — só
    um diagnóstico de quanto a dispersão aparente é redundante, NUNCA
    usado para expandir a amostra histórica de 240 inicializações."""
    resultado = {}
    for lead in v.LEADS_ESPERADOS:
        sub = base_pareada[base_pareada['lead'] == lead]
        pivot = sub.pivot_table(index='init_date', columns='member', values='forecast_prec_mm')
        pivot = pivot.dropna(axis=0, how='any')
        if pivot.shape[0] < 3 or pivot.shape[1] < 2:
            resultado[lead] = {'n_inits': int(pivot.shape[0]), 'n_membros': int(pivot.shape[1]),
                                'nota': 'amostra insuficiente para correlação par-a-par'}
            continue
        matriz_corr = pivot.corr().values
        m = matriz_corr.shape[0]
        mascara_fora_diagonal = ~np.eye(m, dtype=bool)
        correlacoes_fora_diagonal = matriz_corr[mascara_fora_diagonal]
        correlacoes_validas = correlacoes_fora_diagonal[np.isfinite(correlacoes_fora_diagonal)]
        rho_media = float(np.mean(correlacoes_validas)) if len(correlacoes_validas) else None
        ess = (m / (1 + (m - 1) * rho_media)) if rho_media is not None else None
        resultado[lead] = {
            'n_inits': int(pivot.shape[0]), 'n_membros': int(m),
            'correlacao_media_par_a_par': rho_media,
            'effective_ensemble_size_aprox': float(ess) if ess is not None else None,
            'formula_ess': 'ESS = M / (1 + (M-1) * rho_media_par_a_par) — diagnóstico de '
                           'redundância entre membros, NUNCA usado para inflar a amostra '
                           'histórica de 240 inicializações (item 9 do pedido).',
            'spread_std_por_mes': {
                int(mes): float(sub[sub['target_mes'] == mes].groupby('init_date')[
                    'forecast_prec_mm'].std(ddof=1).mean())
                for mes in sorted(sub['target_mes'].unique())
            },
        }
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# Item 11 do pedido — classificação qualitativa do gate
# ══════════════════════════════════════════════════════════════════════════

def classificar_gate_por_horizonte(spread_skill, spread_error_ratio, probabilistico):
    """Nunca usa um limiar numérico escolhido pós-hoc — todos os
    limiares abaixo (0,8/1,2 para o ratio, já usados em `spread_error_
    ratio_por_horizonte`; múltiplos simples sobre a frequência
    esperada do rank histogram) são fixados ANTES de olhar o
    resultado real, e a classificação é uma síntese CAUTELOSA dos
    fatos já calculados (correlações + IC, ratio, rank histogram),
    nunca o inverso.

    Correlação positiva isolada NUNCA basta para `spread_informativo`:
    esse rótulo também exige que ratio E rank histogram não
    demonstrem under/overdispersion — um ensemble pode ter spread
    correlacionado com o erro E ainda estar mal calibrado em
    magnitude (ex.: underdispersive em todos os horizontes), caso em
    que o rótulo correto é `ensemble_mal_calibrado_mas_potencialmente_
    calibravel`, não `spread_informativo`."""
    resultado = {}
    for lead in v.LEADS_ESPERADOS:
        ss = spread_skill.get(lead, {})
        ser = spread_error_ratio.get(lead, {})
        prob = probabilistico.get(lead, {})

        if not ss.get('amostra_suficiente', False):
            resultado[lead] = {'classificacao': 'amostra_insuficiente',
                                'justificativa': 'amostra insuficiente para avaliar spread-skill'}
            continue

        corr_pearson_acima_zero = (ss.get('pearson_std_vs_erro_abs_ic_classificacao')
                                    == 'ic_totalmente_acima_de_zero')
        corr_spearman_acima_zero = (ss.get('spearman_std_vs_erro_abs_ic_classificacao')
                                     == 'ic_totalmente_acima_de_zero')
        pelo_menos_uma_corr_acima_zero = corr_pearson_acima_zero or corr_spearman_acima_zero
        ambas_corr_acima_zero = corr_pearson_acima_zero and corr_spearman_acima_zero

        # Mesmos limiares 0,8/1,2 já usados em `spread_error_ratio_por_
        # horizonte` para a leitura "muito abaixo/acima de 1" — nunca
        # um segundo limiar paralelo para o mesmo julgamento. ratio
        # fora de [0,8; 1,2] já é sinal de dispersão mal calibrada;
        # <0,5 ou >2,0 é o caso extremo, que por si só barra
        # "informativo" mesmo com correlação forte.
        ratio = ser.get('spread_error_ratio')
        ratio_moderadamente_fora = ratio is not None and (ratio < 0.8 or ratio > 1.2)
        ratio_extremo = ratio is not None and (ratio < 0.5 or ratio > 2.0)

        rank_diag = prob.get('rank_histogram_diagnostico', {})
        n_ranks = rank_diag.get('n_ranks_possiveis')
        freq_extrema = rank_diag.get('frequencia_ranks_extremos')
        freq_central = rank_diag.get('frequencia_central')
        esperado = rank_diag.get('esperado_sob_uniformidade_por_rank')
        n_prob = prob.get('n', 0)
        rank_histogram_sinaliza_desvio = False
        if freq_extrema is not None and n_ranks and esperado:
            esperado_extrema = 2 * esperado / max(n_prob, 1) if n_prob else None
            if esperado_extrema and freq_extrema > 2 * esperado_extrema:
                rank_histogram_sinaliza_desvio = True
        if freq_central is not None and n_ranks and esperado and n_prob:
            tercio = max(1, n_ranks // 3)
            esperado_central = (tercio * esperado) / n_prob
            if freq_central > 1.5 * esperado_central:
                rank_histogram_sinaliza_desvio = True

        # under/overdispersion "demonstrada" (item 11) nunca depende só
        # do ratio OU só do rank histogram isolado — qualquer um dos
        # dois já é evidência de dispersão mal calibrada, mas a
        # classificação final (abaixo) sempre cruza isso com a
        # correlação spread×erro, nunca decide por um sinal isolado.
        under_overdispersion_demonstrada = ratio_moderadamente_fora or rank_histogram_sinaliza_desvio

        if ambas_corr_acima_zero and not under_overdispersion_demonstrada and not ratio_extremo:
            classificacao = CLASSIFICACAO_INFORMATIVO
            justificativa = ('correlações Pearson e Spearman spread×erro com IC 95% '
                              'totalmente acima de zero, E nenhum sinal de sob/overdispersão '
                              '(spread_error_ratio dentro de [0,8; 1,2] e rank histogram sem '
                              'desvio de uniformidade relevante) — dispersão do ensemble parece '
                              'bem calibrada E reage à dificuldade da previsão')
        elif pelo_menos_uma_corr_acima_zero and (under_overdispersion_demonstrada or ratio_extremo):
            classificacao = CLASSIFICACAO_MAL_CALIBRADO_POTENCIAL
            justificativa = ('pelo menos uma correlação spread×erro com IC 95% totalmente acima '
                              'de zero, MAS spread_error_ratio e/ou rank histogram demonstram '
                              'under/overdispersion — o ensemble bruto não está bem calibrado, '
                              'porém o spread ainda carrega alguma informação sobre o erro '
                              '(candidato a correção por EMOS ou equivalente, não a descarte)')
        else:
            classificacao = CLASSIFICACAO_POUCO_INFORMATIVO
            justificativa = ('nenhuma correlação spread×erro com IC 95% totalmente acima de '
                              'zero — sem padrão consistente de que a dispersão reage à '
                              'dificuldade da previsão, independentemente do estado de '
                              'calibração do ratio/rank histogram')

        resultado[lead] = {
            'classificacao': classificacao, 'justificativa': justificativa,
            'sinais': {
                'corr_pearson_ic_acima_zero': corr_pearson_acima_zero,
                'corr_spearman_ic_acima_zero': corr_spearman_acima_zero,
                'spread_error_ratio': ratio,
                'ratio_moderadamente_fora_de_1': ratio_moderadamente_fora,
                'ratio_extremo': ratio_extremo,
                'rank_histogram_sinaliza_desvio': rank_histogram_sinaliza_desvio,
            },
        }
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# Orquestração
# ══════════════════════════════════════════════════════════════════════════

def _verificar_nan_inf_inesperado_gate(spread_skill, spread_error_ratio):
    problemas = []

    def checar(valor, caminho):
        if isinstance(valor, (int, float)) and not isinstance(valor, bool):
            if math.isnan(valor) or math.isinf(valor):
                problemas.append(caminho)

    for lead, d in spread_error_ratio.items():
        for k, val in d.items():
            checar(val, f'spread_error_ratio[{lead}][{k}]')
    return {'ok': len(problemas) == 0, 'campos_problema': problemas}


def executar_gate_probabilistico(n_resamples_bootstrap=500):
    auditoria = v.executar_auditoria()
    if not auditoria['auditoria_aprovada']:
        return {'STOP_ON_FAILURE': True, 'motivo': 'auditoria da base RAW (2C.3C) reprovada'}

    df_raw = v.carregar_cfsv2_raw()
    chirps_df = v.carregar_chirps_v3_historico()
    base = v.construir_base_pareada(df_raw, chirps_df)
    if not v.validar_nenhum_mes_alvo_ausente(base):
        return {'STOP_ON_FAILURE': True, 'motivo': 'pareamento com mês-alvo ausente'}

    tabela_ensemble = construir_tabela_ensemble(base)
    auditoria_membros = _verificar_24_membros(tabela_ensemble)
    if not auditoria_membros['ok']:
        return {'STOP_ON_FAILURE': True,
                'motivo': f"{auditoria_membros['n_linhas_divergentes']} linha(s) sem exatamente "
                          f"{v.N_MEMBROS_ESPERADO} membros — nenhuma condição documentada "
                          "justifica isso nesta atividade",
                'detalhe': auditoria_membros}

    n_esperado = v.N_INICIALIZACOES_ESPERADO * len(v.LEADS_ESPERADOS)
    if len(tabela_ensemble) != n_esperado:
        return {'STOP_ON_FAILURE': True,
                'motivo': f'número inesperado de combinações init×lead: {len(tabela_ensemble)}, '
                          f'esperado {n_esperado}'}

    base_enriquecida = v._enriquecer_com_climatologia(base, chirps_df)

    spread_error_ratio = spread_error_ratio_por_horizonte(tabela_ensemble)
    nan_check = _verificar_nan_inf_inesperado_gate({}, spread_error_ratio)
    if not nan_check['ok']:
        return {'STOP_ON_FAILURE': True, 'motivo': 'NaN/Inf não explicado no spread_error_ratio',
                'detalhe': nan_check}

    spread_skill = spread_skill_por_horizonte(tabela_ensemble, n_resamples_bootstrap)
    cobertura = cobertura_intervalos_por_horizonte(tabela_ensemble)
    probabilistico = probabilistico_por_horizonte(base_enriquecida, chirps_df)
    matriz_mes_lead = probabilistico_matriz_mes_lead(base_enriquecida, chirps_df)
    matriz_grupo_sazonal = probabilistico_matriz_grupo_sazonal_lead(base_enriquecida, chirps_df)
    dependencia = dependencia_membros_por_horizonte(base)

    classificacao = classificar_gate_por_horizonte(spread_skill, spread_error_ratio, probabilistico)
    classificacoes_distintas = {c['classificacao'] for c in classificacao.values()
                                 if c['classificacao'] != 'amostra_insuficiente'}
    if classificacoes_distintas == {CLASSIFICACAO_INFORMATIVO}:
        sintese = (f'{CLASSIFICACAO_INFORMATIVO} em todos os horizontes avaliáveis — '
                   'recomenda-se protocolo de calibração probabilística simples (EMOS ou '
                   'equivalente parcimonioso).')
        proximo_passo = 'protocolo_calibracao_probabilistica_simples_recomendado'
    elif classificacoes_distintas == {CLASSIFICACAO_POUCO_INFORMATIVO}:
        sintese = (f'{CLASSIFICACAO_POUCO_INFORMATIVO} em todos os horizontes avaliáveis — não '
                   'avançar automaticamente para um modelo probabilístico complexo. Considerar '
                   'encerrar a calibração CFSv2 da Fase 2C.3D com a conclusão de que o bias '
                   'climatológico é corrigível, o skill interanual determinístico é fraco, e '
                   'o spread também não adiciona informação útil.')
        proximo_passo = 'nao_avancar_calibracao_probabilistica_considerar_encerrar_fase'
    elif classificacoes_distintas == {CLASSIFICACAO_MAL_CALIBRADO_POTENCIAL}:
        sintese = (f'{CLASSIFICACAO_MAL_CALIBRADO_POTENCIAL} em todos os horizontes avaliáveis '
                   '— o ensemble bruto está consistentemente mal calibrado em magnitude '
                   '(spread_error_ratio e/ou rank histogram fora do esperado em todos os '
                   'horizontes), mas o spread ainda carrega relação com o erro em todos eles '
                   '(correlação com IC 95% acima de zero). Não é "pouco informativo" — é um '
                   'candidato razoável a um protocolo de calibração probabilística simples '
                   '(EMOS ou equivalente parcimonioso), que corrige explicitamente a relação '
                   'spread-variância ao mesmo tempo em que usa o spread como preditor — mas '
                   'isso é uma recomendação de próximo passo, nunca uma aprovação do Método 3.5 '
                   'nesta atividade (item 11/13 do pedido).')
        proximo_passo = 'protocolo_calibracao_probabilistica_simples_recomendado_com_correcao_de_dispersao'
    else:
        sintese = ('resultado MISTO entre horizontes — ver classificação por horizonte antes '
                   'de qualquer decisão única; nenhuma média ou voto majoritário decide por '
                   'si só.')
        proximo_passo = 'resultado_misto_revisar_por_horizonte_antes_de_decidir'

    resultado = {
        'STOP_ON_FAILURE': False,
        'metodo': 'gate_diagnostico_calibracao_probabilistica_metodo_3_5',
        'n_membros_esperado': v.N_MEMBROS_ESPERADO,
        'auditoria_membros': auditoria_membros,
        'spread_error_ratio_por_horizonte': spread_error_ratio,
        'spread_skill_por_horizonte': spread_skill,
        'cobertura_intervalos_por_horizonte': cobertura,
        'probabilistico_por_horizonte': probabilistico,
        'matriz_mes_lead': matriz_mes_lead,
        'matriz_grupo_sazonal_lead': matriz_grupo_sazonal,
        'dependencia_membros_por_horizonte': dependencia,
        'classificacao_gate_por_horizonte': classificacao,
        'sintese_gate': sintese,
        'proximo_passo_recomendado': proximo_passo,
        'nenhuma_calibracao_probabilistica_implementada': True,
        'nenhum_emos_ajustado': True,
        'nenhum_dressing_aplicado': True,
        'nenhuma_probabilidade_operacional_alterada': True,
        'data_geracao_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--executar', action='store_true')
    ap.add_argument('--gerar-relatorio', action='store_true')
    args = ap.parse_args()

    if args.executar:
        resultado = executar_gate_probabilistico()
        DIRETORIO_SAIDA.mkdir(parents=True, exist_ok=True)
        CAMINHO_METRICAS_JSON.write_text(
            json.dumps(resultado, indent=2, ensure_ascii=False, default=str))
        print(f"  ✅ {CAMINHO_METRICAS_JSON.relative_to(ROOT)}")
        if resultado.get('STOP_ON_FAILURE'):
            print(f"\n❌ STOP_ON_FAILURE: {resultado.get('motivo')}")
            return
        print(f"  sintese_gate = {resultado['sintese_gate']}")
        return

    if args.gerar_relatorio:
        import cfsv2_relatorio_gate_probabilistico as rel
        rel.gerar_e_escrever()
        return

    ap.print_help()


if __name__ == '__main__':
    main()
