#!/usr/bin/env python3
"""
cfsv2_validacao_cientifica.py — Fase 2C.3C: avaliação científica
retrospectiva do CFSv2 contra a referência observacional CHIRPS v3.0
Final (`data/chirps_v3_historico/chirps_v3_1981_2011.csv`, 365 meses
aprovados, Fase 2C.3B). Completamente separado do sistema
operacional — não altera dashboard, SARIMAX, XGBoost, pipeline
operacional, série de produção nem os dados RAW do CFSv2.

Fonte dos dados CFSv2: `data/nmme_historico_fazendas/lote_*_raw.csv`
(5 lotes, já extraídos e aprovados por scripts/nmme_extracao_
historica.py — 240 inicializações jan/1991-dez/2010, 24 membros,
H1-H6, 34.560 registros RAW). Este módulo NUNCA reextrai nem
reinterpreta esses dados — só lê, audita e usa o campo `target_month`
já persistido (nunca reconstruído).

Roda com:
    python scripts/cfsv2_validacao_cientifica.py --auditar
    python scripts/cfsv2_validacao_cientifica.py --executar-metricas
    python scripts/cfsv2_validacao_cientifica.py --gerar-relatorio
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

DIRETORIO_CFSV2_RAW = ROOT / 'data' / 'nmme_historico_fazendas'
LOTES_RAW = ('1991-1994', '1995-1998', '1999-2002', '2003-2006', '2007-2010')
CAMINHO_CHIRPS_V3_HISTORICO = ROOT / 'data' / 'chirps_v3_historico' / 'chirps_v3_1981_2011.csv'

DIRETORIO_SAIDA = ROOT / 'data' / 'cfsv2_validacao_2c3c'
CAMINHO_BASE_PAREADA = DIRETORIO_SAIDA / 'base_pareada_cfsv2_chirps_v3.csv'
CAMINHO_METRICAS_JSON = DIRETORIO_SAIDA / 'metricas_2c3c.json'
RELATORIO_PATH = ROOT / 'docs' / 'nmme-fase2c3c-validacao-cfsv2.md'

N_MEMBROS_ESPERADO = 24
LEADS_ESPERADOS = (1, 2, 3, 4, 5, 6)
N_INICIALIZACOES_ESPERADO = 240
N_RAW_ESPERADO = N_INICIALIZACOES_ESPERADO * len(LEADS_ESPERADOS) * N_MEMBROS_ESPERADO  # 34.560

# Rótulos EXPLÍCITOS dos horizontes — H1 nunca agregado com H2-H6 numa
# única métrica principal (item 3 da tarefa).
ROTULO_HORIZONTE = {
    1: 'H1 — previsão do mês corrente',
    2: 'H2 — horizonte futuro (+1 mês)',
    3: 'H3 — horizonte futuro (+2 meses)',
    4: 'H4 — horizonte futuro (+3 meses)',
    5: 'H5 — horizonte futuro (+4 meses)',
    6: 'H6 — horizonte futuro (+5 meses)',
}

# Agrupamento sazonal regional (CLAUDE.md: chuva concentrada out-abr,
# seca bem marcada jun-ago) — usado só se a amostra mensal for
# instável (item 10 da tarefa), nunca substitui a quebra por mês.
GRUPO_SAZONAL_POR_MES = {
    1: 'chuvosa', 2: 'chuvosa', 3: 'chuvosa', 4: 'chuvosa',
    5: 'transicao',
    6: 'seca', 7: 'seca', 8: 'seca',
    9: 'transicao',
    10: 'chuvosa', 11: 'chuvosa', 12: 'chuvosa',
}

AMOSTRA_MINIMA_ESTRATO = 20   # abaixo disso, registrar insuficiência em vez de estatística instável


# ══════════════════════════════════════════════════════════════════════════
# Carregamento — nunca reextrai, só lê o que já foi aprovado
# ══════════════════════════════════════════════════════════════════════════

def carregar_cfsv2_raw():
    """Consolida os 5 lotes RAW já extraídos e aprovados (Fazendas
    Sinobras Centroide) — nunca toca nos arquivos originais, nunca
    reinterpreta target_month (lido tal como persistido)."""
    partes = []
    for lote in LOTES_RAW:
        caminho = DIRETORIO_CFSV2_RAW / f'lote_{lote}_raw.csv'
        partes.append(pd.read_csv(caminho))
    df = pd.concat(partes, ignore_index=True)
    df['member'] = df['member'].astype(int)
    return df


def carregar_chirps_v3_historico():
    """Lê a referência observacional já aprovada (Fase 2C.3B, 365
    meses, 1981-01 a 2011-05) — nunca modificada por este módulo."""
    df = pd.read_csv(CAMINHO_CHIRPS_V3_HISTORICO)
    if not (df['status'].isin({'ok', 'zero_real'})).all():
        raise RuntimeError("CHIRPS v3 histórico tem status fora de ok/zero_real — referência "
                            "não está íntegra, abortando (nunca usar dado incompleto).")
    return df[['ano', 'mes', 'valor_mm']].copy()


def _obs_dict(chirps_df):
    """(ano,mes) -> valor_mm, para lookup O(1) na climatologia/pareamento."""
    return {(int(r['ano']), int(r['mes'])): float(r['valor_mm']) for _, r in chirps_df.iterrows()}


def _periodo(ano_mes_str):
    return pd.Period(ano_mes_str, freq='M')


# ══════════════════════════════════════════════════════════════════════════
# Seção 2 — Auditoria da base RAW (antes de qualquer métrica)
# ══════════════════════════════════════════════════════════════════════════

def auditar_base_raw(df_raw):
    """Audita a base RAW já extraída — NUNCA reconstrói/reinterpreta
    target_month, só valida o campo persistido contra init_date+lead-1
    (mesma semântica já confirmada em scripts/nmme_processar.py::
    leadtime_para_mes_alvo_nmme, esquema='lead1_igual_mes_inicializacao').
    Retorna um dict com cada critério separado — nunca um booleano
    único escondendo qual critério falhou."""
    problemas = []

    n_total = len(df_raw)
    if n_total != N_RAW_ESPERADO:
        problemas.append(f"n_raw_total={n_total}, esperado {N_RAW_ESPERADO}")

    # (1) Unicidade init_date x lead x member
    chaves = list(zip(df_raw['init_date'], df_raw['lead'], df_raw['member']))
    n_unicas = len(set(chaves))
    unicidade_ok = n_unicas == n_total
    if not unicidade_ok:
        problemas.append(f"combinações (init_date,lead,member) duplicadas: "
                          f"{n_total - n_unicas} duplicatas")

    # (2) Exatamente 24 membros por (init_date, lead)
    contagem_membros = df_raw.groupby(['init_date', 'lead']).size()
    combos_errados = contagem_membros[contagem_membros != N_MEMBROS_ESPERADO]
    membros_ok = len(combos_errados) == 0
    if not membros_ok:
        problemas.append(f"{len(combos_errados)} combinações (init_date,lead) sem exatamente "
                          f"{N_MEMBROS_ESPERADO} membros")

    # (3) Correspondência init_date + (lead-1) == target_month (VALIDAÇÃO, não reconstrução)
    init_p = pd.PeriodIndex(df_raw['init_date'], freq='M')
    target_p = pd.PeriodIndex(df_raw['target_month'], freq='M')
    esperado_p = init_p + (df_raw['lead'].values - 1)
    mismatch = (esperado_p != target_p)
    n_mismatch = int(mismatch.sum())
    target_month_ok = n_mismatch == 0
    if not target_month_ok:
        problemas.append(f"{n_mismatch} linhas com target_month divergente de init_date+(lead-1)")

    # H1 == init_date (mês corrente) — checagem adicional explícita
    h1 = df_raw[df_raw['lead'] == 1]
    h1_ok = bool((h1['target_month'] == h1['init_date']).all())
    if not h1_ok:
        problemas.append("existem linhas H1 cujo target_month difere do init_date")

    # (4) Ausência de valores faltantes nas colunas essenciais
    colunas_essenciais = ['init_date', 'target_month', 'lead', 'member', 'forecast_prec_mm']
    faltantes = {c: int(df_raw[c].isna().sum()) for c in colunas_essenciais}
    sem_faltantes = all(v == 0 for v in faltantes.values())
    if not sem_faltantes:
        problemas.append(f"valores faltantes: {faltantes}")

    # (5) Unidades — já convertido para mm/mês (mm/day * dias_do_mes),
    # nunca mm/day bruto chegando nas métricas
    unidades_originais = sorted(df_raw['units_original'].dropna().unique().tolist())
    unidades_ok = unidades_originais == ['mm/day']
    conversao_presente = bool(df_raw['conversion_applied'].notna().all())
    if not (unidades_ok and conversao_presente):
        problemas.append(f"unidades inesperadas: {unidades_originais} ou conversão ausente")

    # (6) Período de cobertura — 240 inicializações, jan/1991-dez/2010
    inits_distintos = sorted(df_raw['init_date'].unique())
    n_inits = len(inits_distintos)
    periodo_ok = (n_inits == N_INICIALIZACOES_ESPERADO
                  and inits_distintos[0] == '1991-01' and inits_distintos[-1] == '2010-12')
    if not periodo_ok:
        problemas.append(f"período de inicializações: {n_inits} inits, "
                          f"{inits_distintos[0] if inits_distintos else None} a "
                          f"{inits_distintos[-1] if inits_distintos else None}")

    # (7) Localização única (nunca misturar com São Bento)
    localizacoes = sorted(df_raw['localizacao'].dropna().unique().tolist())
    localizacao_ok = localizacoes == ['Fazendas_Sinobras_Centroide']
    if not localizacao_ok:
        problemas.append(f"localizações inesperadas: {localizacoes}")

    n_target_months_distintos = df_raw['target_month'].nunique()

    return {
        'n_raw_total': n_total,
        'n_raw_esperado': N_RAW_ESPERADO,
        'unicidade_init_lead_member_ok': unicidade_ok,
        'vinte_quatro_membros_por_init_lead_ok': membros_ok,
        'target_month_corresponde_a_init_mais_lead_ok': target_month_ok,
        'h1_igual_mes_corrente_ok': h1_ok,
        'sem_valores_faltantes_ok': sem_faltantes,
        'valores_faltantes_por_coluna': faltantes,
        'unidades_ok': unidades_ok and conversao_presente,
        'periodo_cobertura_ok': periodo_ok,
        'n_inicializacoes_distintas': n_inits,
        'localizacao_unica_ok': localizacao_ok,
        'n_meses_alvo_distintos': int(n_target_months_distintos),
        'problemas': problemas,
        'auditoria_aprovada': len(problemas) == 0,
    }


# ══════════════════════════════════════════════════════════════════════════
# Seção 4 — Pareamento CFSv2 x CHIRPS v3 (nunca serie_subst/chirps_1981_2025
# como referência principal)
# ══════════════════════════════════════════════════════════════════════════

def construir_base_pareada(df_raw=None, chirps_df=None):
    """Pareia cada registro RAW do CFSv2 (init_date, target_month,
    lead, member, forecast_prec_mm) com a observação CHIRPS v3
    correspondente ao MESMO target_month — join exclusivo por
    target_month, nunca por proximidade ou por outra referência."""
    if df_raw is None:
        df_raw = carregar_cfsv2_raw()
    if chirps_df is None:
        chirps_df = carregar_chirps_v3_historico()

    obs = _obs_dict(chirps_df)
    target_p = pd.PeriodIndex(df_raw['target_month'], freq='M')
    anos_alvo = target_p.year
    meses_alvo = target_p.month

    obs_valores = [obs.get((int(a), int(m))) for a, m in zip(anos_alvo, meses_alvo)]
    faltando = sum(1 for v in obs_valores if v is None)
    if faltando:
        metas_faltando = sorted({f'{a}-{m:02d}' for (a, m), v in
                                  zip(zip(anos_alvo, meses_alvo), obs_valores) if v is None})
        raise RuntimeError(f"{faltando} registros CFSv2 sem observação CHIRPS v3 correspondente "
                            f"— meses-alvo faltando: {metas_faltando}. NUNCA substituir por "
                            "serie_subst.csv/chirps_1981_2025.csv — corrigir a referência "
                            "primeiro (STOP-ON-FAILURE).")

    base = pd.DataFrame({
        'init_date': df_raw['init_date'].values,
        'target_month': df_raw['target_month'].values,
        'target_ano': anos_alvo.astype(int),
        'target_mes': meses_alvo.astype(int),
        'lead': df_raw['lead'].values,
        'member': df_raw['member'].values,
        'forecast_prec_mm': df_raw['forecast_prec_mm'].values,
        'obs_prec_mm': obs_valores,
    })
    return base


def validar_nenhum_mes_alvo_ausente(base_pareada):
    return int(base_pareada['obs_prec_mm'].isna().sum()) == 0


# ══════════════════════════════════════════════════════════════════════════
# Seção 5 — Climatologia EXPANSÍVEL sem leakage
# ══════════════════════════════════════════════════════════════════════════

def anos_climatologia_disponiveis(mes_alvo, init_date, chirps_df):
    """Anos (mesmo mês-do-ano `mes_alvo`) cuja observação tem data <
    init_date — NUNCA o mês/ano da própria inicialização ou posterior.
    A comparação é sempre por período completo (ano,mês), não só por
    ano — por isso jan/1991 (H1) usa 1981-1990 (10 anos: dez/1990
    também é < jan/1991, mas o que importa aqui é jan de cada ano
    anterior), e um H6 com init em jul/2010 (target dez/2010) usa
    dezembros até 2009 (dez/2010 ainda não ocorreu antes de jul/2010).
    Comparação feita com `pd.Period` (nunca string lexicográfica, que
    ordenaria errado meses de 1 dígito se existissem)."""
    init_p = _periodo(init_date)
    anos = sorted(int(a) for (a, m) in chirps_df if m == mes_alvo and _periodo(f'{a}-{m:02d}') < init_p)
    return anos


def climatologia_expansivel(mes_alvo, init_date, obs_dict):
    """Climatologia causal (nunca usa dado >= init_date) para o mês-do-
    ano `mes_alvo`. Retorna média, tercis (p33/p67) e metadados de
    quantos anos/qual período foi usado — nunca um número isolado sem
    a proveniência."""
    init_p = _periodo(init_date)
    anos_valores = [(a, obs_dict[(a, m)]) for (a, m) in obs_dict
                     if m == mes_alvo and _periodo(f'{a}-{m:02d}') < init_p]
    anos_valores.sort()
    anos = [a for a, _ in anos_valores]
    valores = np.array([v for _, v in anos_valores], dtype=float)
    if len(valores) == 0:
        return {'n_anos': 0, 'media': None, 'tercil_33': None, 'tercil_67': None,
                'anos_usados': [], 'periodo_usado': None}
    return {
        'n_anos': len(valores),
        'media': float(valores.mean()),
        'tercil_33': float(np.percentile(valores, 100 / 3)),
        'tercil_67': float(np.percentile(valores, 200 / 3)),
        'anos_usados': anos,
        'periodo_usado': f'{anos[0]}-{anos[-1]}' if anos else None,
    }


def categoria_tercil(valor, tercil_33, tercil_67):
    if valor <= tercil_33:
        return 'seco'
    if valor >= tercil_67:
        return 'umido'
    return 'normal'


# ══════════════════════════════════════════════════════════════════════════
# Revisão — climatologia PRÓPRIA do modelo (item 1): a versão anterior
# subtraía a MESMA climatologia observada da previsão e da observação,
# o que remove o ciclo sazonal comum mas NUNCA o viés sazonal
# sistemático do próprio CFSv2 (ex.: o modelo pode superestimar
# dezembro sistematicamente — isso não aparece como anomalia se a
# climatologia usada para "corrigir" a previsão é a da OBSERVAÇÃO).
# Agora a climatologia do modelo é construída separadamente, pelo
# ensemble mean de inicializações HISTÓRICAS do MESMO lead e do MESMO
# mês-calendário de inicialização (equivalente a "mesmo lead e mesmo
# mês-alvo", já que mês-alvo = mês de inicialização + lead - 1 é
# função determinística do mês de inicialização) — estritamente
# anteriores à inicialização avaliada, nunca usando uma inicialização
# >= init_date (nunca previsões futuras em relação à inicialização
# avaliada, mesmo que associadas a um target_month passado).
# ══════════════════════════════════════════════════════════════════════════

def construir_indice_previsoes_modelo(base_pareada):
    """Ensemble mean por (init_date, lead) — índice-base para a
    climatologia própria do modelo. Calculado uma vez, reaproveitado
    por todas as climatologias de todas as inicializações."""
    idx = base_pareada.groupby(['init_date', 'lead'], as_index=False)['forecast_prec_mm'].mean()
    return idx.rename(columns={'forecast_prec_mm': 'ensemble_mean'})


def climatologia_modelo_expansivel(lead, init_date, indice_previsoes):
    """Climatologia EXPANSÍVEL PRÓPRIA do modelo (nunca a observada).
    `indice_previsoes` é o retorno de construir_indice_previsoes_
    modelo(). Nunca usa uma inicialização >= init_date."""
    init_p = _periodo(init_date)
    sub = indice_previsoes[indice_previsoes['lead'] == lead]
    if sub.empty:
        return {'n_inits': 0, 'media': None, 'inits_usados': []}
    sub_p = pd.PeriodIndex(sub['init_date'], freq='M')
    mascara = (sub_p.month == init_p.month) & (sub_p < init_p)
    elegiveis = sub[mascara]
    if elegiveis.empty:
        return {'n_inits': 0, 'media': None, 'inits_usados': []}
    inits_usados = sorted(elegiveis['init_date'].tolist(), key=_periodo)
    return {
        'n_inits': len(elegiveis),
        'media': float(elegiveis['ensemble_mean'].mean()),
        'inits_usados': inits_usados,
    }


# ══════════════════════════════════════════════════════════════════════════
# Seção 13 — LOYO (retrospectivo complementar, NUNCA misturado com a
# climatologia expansível operacional)
# ══════════════════════════════════════════════════════════════════════════

def climatologia_loyo(mes_alvo, ano_excluido, obs_dict):
    """Leave-one-year-out: usa TODOS os anos (passado E futuro) exceto
    `ano_excluido` — deliberadamente NÃO causal, só para análise
    retrospectiva complementar (rótulo 'loyo_retrospective'), nunca
    como substituto da climatologia expansível operacional."""
    anos_valores = [(a, obs_dict[(a, m)]) for (a, m) in obs_dict if m == mes_alvo and a != ano_excluido]
    anos_valores.sort()
    valores = np.array([v for _, v in anos_valores], dtype=float)
    if len(valores) == 0:
        return {'n_anos': 0, 'media': None, 'tercil_33': None, 'tercil_67': None}
    return {
        'n_anos': len(valores),
        'media': float(valores.mean()),
        'tercil_33': float(np.percentile(valores, 100 / 3)),
        'tercil_67': float(np.percentile(valores, 200 / 3)),
    }


# ══════════════════════════════════════════════════════════════════════════
# Métricas determinísticas (Seção 6) + benchmark climatológico (Seção 7)
# ══════════════════════════════════════════════════════════════════════════

def _bias(previsto, observado):
    return float(np.mean(previsto - observado))


def _mae(previsto, observado):
    return float(np.mean(np.abs(previsto - observado)))


def _rmse(previsto, observado):
    return float(np.sqrt(np.mean((previsto - observado) ** 2)))


def _corr(previsto, observado):
    if len(previsto) < 2 or np.std(previsto) == 0 or np.std(observado) == 0:
        return None
    return float(np.corrcoef(previsto, observado)[0, 1])


def rmsess(rmse_modelo, rmse_climatologia):
    """Skill score de erro — fórmula documentada explicitamente:
    RMSESS = 1 - RMSE_modelo / RMSE_climatologia. Positivo = modelo
    erra menos que a climatologia; 0 = empate; negativo = modelo pior
    que simplesmente prever a climatologia. NUNCA interpretado como
    'bom' sem o intervalo de confiança (ver bootstrap, Seção 9)."""
    if rmse_climatologia is None or rmse_climatologia == 0:
        return None
    return float(1 - (rmse_modelo / rmse_climatologia))


def _enriquecer_com_climatologia(base_pareada, chirps_df):
    """Acrescenta, para cada linha: (1) a climatologia OBSERVADA
    expansível (média/tercis/n_anos) do mês-alvo, calculada uma vez
    por (mes_alvo, init_date); (2) a climatologia PRÓPRIA DO MODELO
    expansível (item 1 da revisão), calculada uma vez por (lead,
    init_date) — ambas cacheadas e reaproveitadas entre linhas que
    compartilham a mesma combinação, nunca recalculadas linha a linha
    com risco de inconsistência."""
    obs_dict = _obs_dict(chirps_df)
    indice_modelo = construir_indice_previsoes_modelo(base_pareada)
    cache_obs, cache_modelo = {}, {}
    medias, t33s, t67s, n_anoss = [], [], [], []
    medias_modelo, n_inits_modelo = [], []
    for mes_alvo, init_date, lead in zip(base_pareada['target_mes'], base_pareada['init_date'],
                                           base_pareada['lead']):
        chave_obs = (mes_alvo, init_date)
        if chave_obs not in cache_obs:
            cache_obs[chave_obs] = climatologia_expansivel(mes_alvo, init_date, obs_dict)
        co = cache_obs[chave_obs]
        medias.append(co['media'])
        t33s.append(co['tercil_33'])
        t67s.append(co['tercil_67'])
        n_anoss.append(co['n_anos'])

        chave_modelo = (lead, init_date)
        if chave_modelo not in cache_modelo:
            cache_modelo[chave_modelo] = climatologia_modelo_expansivel(lead, init_date, indice_modelo)
        cm = cache_modelo[chave_modelo]
        medias_modelo.append(cm['media'])
        n_inits_modelo.append(cm['n_inits'])

    base = base_pareada.copy()
    base['clim_media'] = medias
    base['clim_tercil_33'] = t33s
    base['clim_tercil_67'] = t67s
    base['clim_n_anos'] = n_anoss
    base['clim_modelo_media'] = medias_modelo
    base['clim_modelo_n_inits'] = n_inits_modelo
    return base


def metricas_deterministicas_por_horizonte(base_enriquecida):
    """Média dos 24 membros como previsão determinística (Seção 6).
    Calcula separadamente para cada H — NUNCA agrega H1 com H2-H6.

    CORREÇÃO (revisão, item 1) — a versão anterior subtraía a MESMA
    climatologia OBSERVADA da previsão e da observação
    ('anomalia_diagnostico_climatologia_observada' aqui, preservada só
    como diagnóstico) — isso nunca removia o viés sazonal sistemático
    do próprio CFSv2. A métrica PRINCIPAL agora é
    'anomalia_corrigida_climatologia_propria_modelo': previsão menos a
    climatologia PRÓPRIA do modelo (climatologia_modelo_expansivel),
    observação menos a climatologia observada — cada lado corrigido
    pela sua própria referência."""
    resultado = {}
    media_membros = base_enriquecida.groupby(
        ['init_date', 'target_month', 'lead'], as_index=False
    ).agg(previsto=('forecast_prec_mm', 'mean'),
          observado=('obs_prec_mm', 'first'),
          clim_media=('clim_media', 'first'),
          clim_n_anos=('clim_n_anos', 'first'),
          clim_modelo_media=('clim_modelo_media', 'first'),
          clim_modelo_n_inits=('clim_modelo_n_inits', 'first'))

    for lead in LEADS_ESPERADOS:
        sub = media_membros[media_membros['lead'] == lead].dropna(subset=['clim_media'])
        n = len(sub)
        if n == 0:
            resultado[lead] = {'n': 0, 'rotulo': ROTULO_HORIZONTE[lead]}
            continue
        prev = sub['previsto'].values
        obs = sub['observado'].values
        clim = sub['clim_media'].values
        clim_modelo = sub['clim_modelo_media'].values

        # Diagnóstico (versão anterior) — mesma climatologia OBSERVADA
        # nos dois lados.
        anom_prev_diag = prev - clim
        anom_obs = obs - clim

        rmse_modelo = _rmse(prev, obs)
        rmse_clim = _rmse(clim, obs)
        rmse_modelo_anom_diag = _rmse(anom_prev_diag, anom_obs)
        rmse_clim_anom = _rmse(np.zeros_like(anom_obs), anom_obs)   # climatologia prevê anomalia 0

        # Primária (item 1) — climatologia PRÓPRIA do modelo do lado
        # da previsão; só os casos com climatologia do modelo
        # disponível (todo init_date exceto, por mês, a primeira
        # ocorrência histórica daquele mês de inicialização).
        tem_clim_modelo = ~pd.isna(clim_modelo)
        n_com_clim_modelo = int(tem_clim_modelo.sum())
        if n_com_clim_modelo > 0:
            anom_modelo = prev[tem_clim_modelo] - clim_modelo[tem_clim_modelo]
            anom_obs_corrigida = obs[tem_clim_modelo] - clim[tem_clim_modelo]
            rmse_modelo_anom_corrigida = _rmse(anom_modelo, anom_obs_corrigida)
            rmse_clim_anom_corrigida = _rmse(np.zeros_like(anom_obs_corrigida), anom_obs_corrigida)
            anomalia_corrigida = {
                'bias': _bias(anom_modelo, anom_obs_corrigida),
                'mae': _mae(anom_modelo, anom_obs_corrigida),
                'rmse': rmse_modelo_anom_corrigida,
                'corr': _corr(anom_modelo, anom_obs_corrigida),
            }
            rmsess_anomalia_corrigida = rmsess(rmse_modelo_anom_corrigida, rmse_clim_anom_corrigida)
        else:
            anomalia_corrigida = {'nota': 'sem inicializações históricas suficientes para '
                                   'climatologia própria do modelo'}
            rmsess_anomalia_corrigida = None

        resultado[lead] = {
            'n': n,
            'rotulo': ROTULO_HORIZONTE[lead],
            'amostra_suficiente': n >= AMOSTRA_MINIMA_ESTRATO,
            'n_com_climatologia_modelo_disponivel': n_com_clim_modelo,
            'absoluto': {
                'bias': _bias(prev, obs), 'mae': _mae(prev, obs),
                'rmse': rmse_modelo, 'corr': _corr(prev, obs),
            },
            'anomalia_diagnostico_climatologia_observada': {
                'nota': "DIAGNÓSTICO — mesma climatologia OBSERVADA subtraída dos dois lados; "
                        "não remove o viés sazonal sistemático do próprio CFSv2. NÃO é a "
                        "anomaly correlation principal (ver anomalia_corrigida_... abaixo).",
                'bias': _bias(anom_prev_diag, anom_obs), 'mae': _mae(anom_prev_diag, anom_obs),
                'rmse': rmse_modelo_anom_diag, 'corr': _corr(anom_prev_diag, anom_obs),
            },
            'anomalia_corrigida_climatologia_propria_modelo': anomalia_corrigida,
            'benchmark_climatologico': {
                'bias': _bias(clim, obs), 'mae': _mae(clim, obs), 'rmse': rmse_clim,
            },
            'rmsess_absoluto': rmsess(rmse_modelo, rmse_clim),
            'rmsess_anomalia_diagnostico': rmsess(rmse_modelo_anom_diag, rmse_clim_anom),
            'rmsess_anomalia_corrigida': rmsess_anomalia_corrigida,
            'formula_rmsess': 'RMSESS = 1 - RMSE_modelo / RMSE_climatologia',
        }
    return resultado


def _metricas_de_subconjunto(sub):
    """Núcleo compartilhado por metricas_por_mes_do_ano (visão
    agregada descritiva) e pelas matrizes mes×lead / grupo_sazonal×lead
    (Seção 10, item 3 da revisão) — nunca duas fórmulas paralelas."""
    n = len(sub)
    if n == 0:
        return {'n': 0}
    prev = sub['previsto'].values
    obs = sub['observado'].values
    clim = sub['clim_media'].values
    clim_modelo = sub['clim_modelo_media'].values

    rmse_modelo = _rmse(prev, obs)
    rmse_clim = _rmse(clim, obs)

    tem_clim_modelo = ~pd.isna(clim_modelo)
    if tem_clim_modelo.sum() > 0:
        anom_modelo = prev[tem_clim_modelo] - clim_modelo[tem_clim_modelo]
        anom_obs_corrigida = obs[tem_clim_modelo] - clim[tem_clim_modelo]
        corr_anomalia = _corr(anom_modelo, anom_obs_corrigida)
    else:
        corr_anomalia = None

    return {
        'n': n,
        'amostra_suficiente': n >= AMOSTRA_MINIMA_ESTRATO,
        'bias': _bias(prev, obs), 'mae': _mae(prev, obs), 'rmse': rmse_modelo,
        'corr_absoluta': _corr(prev, obs),
        'corr_anomalia_climatologia_propria_modelo': corr_anomalia,
        'rmsess': rmsess(rmse_modelo, rmse_clim),
    }


def metricas_por_mes_do_ano(base_enriquecida):
    """Seção 10 — VISÃO AGREGADA DESCRITIVA por mês do ano (agrega
    H1-H6, N~120/mês). CORREÇÃO (item 3 da revisão): esta agregação
    escondia a dependência do horizonte — mantida só como visão
    descritiva secundária; a análise sazonal PRINCIPAL agora é a
    matriz target_month×lead (ver metricas_matriz_mes_lead)."""
    media_membros = base_enriquecida.groupby(
        ['init_date', 'target_month', 'target_mes', 'lead'], as_index=False
    ).agg(previsto=('forecast_prec_mm', 'mean'), observado=('obs_prec_mm', 'first'),
          clim_media=('clim_media', 'first'), clim_modelo_media=('clim_modelo_media', 'first'))

    resultado = {}
    for mes in range(1, 13):
        sub = media_membros[media_membros['target_mes'] == mes].dropna(subset=['clim_media'])
        m = _metricas_de_subconjunto(sub)
        m['grupo_sazonal'] = GRUPO_SAZONAL_POR_MES[mes]
        resultado[mes] = m

    por_grupo = {}
    for grupo in ('chuvosa', 'transicao', 'seca'):
        meses_grupo = [m for m, g in GRUPO_SAZONAL_POR_MES.items() if g == grupo]
        sub = media_membros[media_membros['target_mes'].isin(meses_grupo)].dropna(subset=['clim_media'])
        por_grupo[grupo] = _metricas_de_subconjunto(sub)
    return {'rotulo': 'visao_agregada_descritiva_H1_a_H6_combinados',
            'por_mes': resultado, 'por_grupo_sazonal': por_grupo}


def metricas_matriz_mes_lead(base_enriquecida):
    """Item 3 da revisão — análise sazonal PRINCIPAL: matriz
    target_month × lead (N esperado ~20/célula = 240 inits / 12
    meses). Amostra pequena por célula — NUNCA inferências fortes
    automáticas, só reporte descritivo (nenhum IC calculado aqui;
    para isso, ver o bootstrap por horizonte, que já opera sobre
    amostras maiores)."""
    media_membros = base_enriquecida.groupby(
        ['init_date', 'target_month', 'target_mes', 'lead'], as_index=False
    ).agg(previsto=('forecast_prec_mm', 'mean'), observado=('obs_prec_mm', 'first'),
          clim_media=('clim_media', 'first'), clim_modelo_media=('clim_modelo_media', 'first'))

    matriz = {}
    for mes in range(1, 13):
        matriz[mes] = {}
        for lead in LEADS_ESPERADOS:
            sub = media_membros[(media_membros['target_mes'] == mes)
                                 & (media_membros['lead'] == lead)].dropna(subset=['clim_media'])
            matriz[mes][lead] = _metricas_de_subconjunto(sub)
    return matriz


def metricas_matriz_grupo_sazonal_lead(base_enriquecida):
    """Item 3 da revisão — matriz resumida grupo_sazonal × lead
    (chuvosa/transição/seca), para responder operacionalmente se um
    horizonte funciona diferente na estação chuvosa vs. seca, com
    amostra maior que a matriz mês×lead."""
    media_membros = base_enriquecida.groupby(
        ['init_date', 'target_month', 'target_mes', 'lead'], as_index=False
    ).agg(previsto=('forecast_prec_mm', 'mean'), observado=('obs_prec_mm', 'first'),
          clim_media=('clim_media', 'first'), clim_modelo_media=('clim_modelo_media', 'first'))

    matriz = {}
    for grupo in ('chuvosa', 'transicao', 'seca'):
        meses_grupo = [m for m, g in GRUPO_SAZONAL_POR_MES.items() if g == grupo]
        matriz[grupo] = {}
        for lead in LEADS_ESPERADOS:
            sub = media_membros[(media_membros['target_mes'].isin(meses_grupo))
                                 & (media_membros['lead'] == lead)].dropna(subset=['clim_media'])
            matriz[grupo][lead] = _metricas_de_subconjunto(sub)
    return matriz


# ══════════════════════════════════════════════════════════════════════════
# Seção 8 — avaliação probabilística (24 membros)
# ══════════════════════════════════════════════════════════════════════════

def crps_amostral(membros, obs):
    """CRPS empírico "fair" (não-viesado para ensemble finito):
    CRPS = (1/M) sum_i |x_i - y| - 1/(2M(M-1)) sum_i sum_j |x_i - x_j|,
    i != j na segunda soma. Fórmula padrão (Ferro et al. 2008) —
    documentada aqui porque a versão "ingênua" (dividindo por M² em
    vez de M(M-1)) tem viés negativo conhecido para M pequeno."""
    x = np.asarray(membros, dtype=float)
    m = len(x)
    termo1 = np.mean(np.abs(x - obs))
    dif = np.abs(x[:, None] - x[None, :])
    termo2 = dif.sum() / (m * (m - 1))
    return float(termo1 - termo2 / 2)


def rank_observacao(membros, obs, rng):
    """Posição (1..M+1) da observação entre os M membros ordenados —
    para o rank histogram. Empates resolvidos com uma posição
    aleatória dentre as válidas (convenção padrão)."""
    x = np.sort(np.asarray(membros, dtype=float))
    menores = int(np.sum(x < obs))
    iguais = int(np.sum(x == obs))
    return menores + 1 + (rng.integers(0, iguais + 1) if iguais else 0)


def construir_linhas_avaliacao_por_lead(base_enriquecida, chirps_df, lead):
    """Monta, para um lead, 1 linha por (init_date, target_month) com
    tudo que as métricas probabilísticas (Seção 8) e o bootstrap de
    skill scores (Seção 9, item 2 da revisão) precisam: ensemble mean,
    observação, climatologia observada (média + tercis), os 24
    membros, e o conjunto de valores históricos ELEGÍVEIS da
    climatologia (nunca mais que o permitido pela Seção 5). Construído
    uma vez, reaproveitado por avaliar_probabilistico_por_horizonte e
    bootstrap_skill_scores_por_horizonte — nunca duas lógicas
    paralelas de climatologia que poderiam divergir."""
    obs_dict = _obs_dict(chirps_df)
    sub = base_enriquecida[base_enriquecida['lead'] == lead]
    linhas = []
    for (init_date, target_month, target_ano), grupo in sub.groupby(
            ['init_date', 'target_month', 'target_ano']):
        membros = grupo['forecast_prec_mm'].values
        if len(membros) != N_MEMBROS_ESPERADO:
            continue
        obs = float(grupo['obs_prec_mm'].iloc[0])
        mes_alvo = int(grupo['target_mes'].iloc[0])
        clim = climatologia_expansivel(mes_alvo, init_date, obs_dict)
        if clim['n_anos'] < 3:
            continue   # climatologia degenerada demais para servir de referência probabilística
        anos_hist = np.array([obs_dict[(a, mes_alvo)] for a in clim['anos_usados']])
        linhas.append({
            'init_date': init_date, 'target_ano': int(target_ano),
            'previsto': float(membros.mean()), 'observado': obs, 'membros': membros,
            'clim_media': clim['media'], 'anos_hist': anos_hist,
            'tercil_33': clim['tercil_33'], 'tercil_67': clim['tercil_67'],
        })
    return linhas


def avaliar_probabilistico_por_horizonte(base_enriquecida, chirps_df, seed=20261001):
    """CRPS, CRPSS (contra climatologia probabilística = conjunto dos
    anos históricos elegíveis), rank histogram e, para tercis, Brier
    Score/BSS — tudo com os limites de tercil calculados SOMENTE com o
    histórico permitido antes de cada inicialização (nunca com
    1981-2011 completo).

    Item 4 da revisão — preserva a referência NOMINAL de 1/3 como
    benchmark PRINCIPAL do BSS (nunca alterada silenciosamente), mas
    acrescenta: (a) a frequência OBSERVADA efetiva de cada categoria
    em cada horizonte (pode não ser exatamente 1/3 por tamanho de
    amostra finito e empates nos limiares); (b) uma versão de
    SENSIBILIDADE do BSS usando as probabilidades climatológicas
    EMPÍRICAS causais (fração dos anos elegíveis de CADA climatologia
    em cada categoria, que por construção fica perto de 1/3 mas não
    exatamente), claramente rotulada e separada do BSS nominal."""
    rng = np.random.default_rng(seed)
    resultado = {}

    for lead in LEADS_ESPERADOS:
        linhas = construir_linhas_avaliacao_por_lead(base_enriquecida, chirps_df, lead)
        n = len(linhas)
        if n < AMOSTRA_MINIMA_ESTRATO:
            resultado[lead] = {'n': n, 'amostra_suficiente': False,
                                'nota': 'amostra insuficiente — estatística não calculada'}
            continue

        crps_modelo_lista, crps_clim_lista, ranks = [], [], []
        prob_seco, prob_normal, prob_umido = [], [], []
        obs_cat_seco, obs_cat_normal, obs_cat_umido = [], [], []
        prob_clim_emp_seco, prob_clim_emp_normal, prob_clim_emp_umido = [], [], []

        for linha in linhas:
            membros, obs = linha['membros'], linha['observado']
            t33, t67 = linha['tercil_33'], linha['tercil_67']
            anos_hist = linha['anos_hist']

            crps_modelo_lista.append(crps_amostral(membros, obs))
            crps_clim_lista.append(crps_amostral(anos_hist, obs) if len(anos_hist) >= 2 else np.nan)
            ranks.append(rank_observacao(membros, obs, rng))

            p_seco = float(np.mean(membros <= t33))
            p_umido = float(np.mean(membros >= t67))
            p_normal = max(0.0, 1.0 - p_seco - p_umido)
            cat_obs = categoria_tercil(obs, t33, t67)
            prob_seco.append(p_seco); prob_normal.append(p_normal); prob_umido.append(p_umido)
            obs_cat_seco.append(1.0 if cat_obs == 'seco' else 0.0)
            obs_cat_normal.append(1.0 if cat_obs == 'normal' else 0.0)
            obs_cat_umido.append(1.0 if cat_obs == 'umido' else 0.0)

            # item 4 — probabilidade climatológica EMPÍRICA (causal):
            # fração dos próprios anos elegíveis desta climatologia em
            # cada categoria — por construção perto de 1/3, mas nunca
            # exatamente, por tamanho de amostra finito/empates.
            n_hist = len(anos_hist)
            if n_hist > 0:
                prob_clim_emp_seco.append(float(np.mean(anos_hist <= t33)))
                prob_clim_emp_umido.append(float(np.mean(anos_hist >= t67)))
                prob_clim_emp_normal.append(max(0.0, 1.0 - prob_clim_emp_seco[-1] - prob_clim_emp_umido[-1]))
            else:
                prob_clim_emp_seco.append(np.nan)
                prob_clim_emp_normal.append(np.nan)
                prob_clim_emp_umido.append(np.nan)

        crps_modelo = np.array(crps_modelo_lista)
        crps_clim = np.array(crps_clim_lista)
        validos = ~np.isnan(crps_clim)
        crps_medio_modelo = float(crps_modelo.mean())
        crps_medio_clim = float(crps_clim[validos].mean()) if validos.any() else None
        crpss = (1 - crps_medio_modelo / crps_medio_clim) if crps_medio_clim else None

        ranks_arr = np.array(ranks)
        hist_rank = {int(r): int((ranks_arr == r).sum()) for r in range(1, N_MEMBROS_ESPERADO + 2)}

        bs, bss = {}, {}
        bs_sensibilidade, bss_sensibilidade = {}, {}
        freq_observada = {}
        bs_referencia_nominal = 2 / 9   # p=1/3 climatológico: p*(1-p) = (1/3)(2/3) = 2/9
        mapa = {
            'seco': (np.array(prob_seco), np.array(obs_cat_seco), np.array(prob_clim_emp_seco)),
            'normal': (np.array(prob_normal), np.array(obs_cat_normal), np.array(prob_clim_emp_normal)),
            'umido': (np.array(prob_umido), np.array(obs_cat_umido), np.array(prob_clim_emp_umido)),
        }
        for cat, (p, o, p_clim_emp) in mapa.items():
            bs[cat] = float(np.mean((p - o) ** 2))
            bss[cat] = float(1 - bs[cat] / bs_referencia_nominal)
            freq_observada[cat] = float(o.mean())   # frequência OBSERVADA efetiva da categoria
            validos_emp = ~np.isnan(p_clim_emp)
            if validos_emp.any():
                bs_ref_emp = float(np.mean((p_clim_emp[validos_emp] - o[validos_emp]) ** 2))
                bs_sensibilidade[cat] = bs_ref_emp
                bss_sensibilidade[cat] = (float(1 - bs[cat] / bs_ref_emp) if bs_ref_emp > 0 else None)
            else:
                bs_sensibilidade[cat] = None
                bss_sensibilidade[cat] = None

        resultado[lead] = {
            'n': n, 'amostra_suficiente': True,
            'crps_medio_modelo': crps_medio_modelo,
            'crps_medio_climatologia': crps_medio_clim,
            'crpss': crpss,
            'formula_crpss': 'CRPSS = 1 - CRPS_modelo / CRPS_climatologia_probabilistica',
            'rank_histogram': hist_rank,
            'brier_score_por_categoria': bs,
            'bss_por_categoria': bss,
            'formula_bss': 'BSS = 1 - BS_modelo / BS_referencia_climatologica (p=1/3, BS_ref=2/9) '
                           '— REFERÊNCIA PRINCIPAL, nunca alterada silenciosamente.',
            'frequencia_observada_por_categoria': freq_observada,
            'nota_frequencia_observada': 'frequência OBSERVADA efetiva de cada categoria nesta '
                                           'amostra — pode não ser exatamente 1/3 por tamanho de '
                                           'amostra finito e empates nos limiares de tercil.',
            'bss_sensibilidade_climatologia_empirica_por_categoria': bss_sensibilidade,
            'brier_referencia_empirica_por_categoria': bs_sensibilidade,
            'nota_sensibilidade': 'BSS de SENSIBILIDADE usando probabilidade climatológica '
                                   'EMPÍRICA causal (fração dos anos elegíveis de cada '
                                   'climatologia em cada categoria) em vez do nominal 1/3 — '
                                   'NUNCA substitui a referência nominal, só complementa.',
        }
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# Seção 9 — dependência temporal: bootstrap em blocos por ANO do target
# ══════════════════════════════════════════════════════════════════════════

def bootstrap_blocos_por_ano(df_lead, coluna_previsto, coluna_observado, coluna_ano,
                               funcao_metrica, n_resamples=1000, seed=20261001):
    """IC 95% por reamostragem em BLOCOS de ano (nunca linha a linha —
    preserva a dependência temporal: o mesmo target_month aparece em
    vários horizontes/inicializações, então embaralhar linhas
    individualmente subestimaria a incerteza real). Cada reamostra
    sorteia ANOS com reposição e junta todas as linhas desses anos."""
    rng = np.random.default_rng(seed)
    anos = df_lead[coluna_ano].unique()
    if len(anos) < 3:
        return {'estimativa': None, 'ic95_lo': None, 'ic95_hi': None,
                'nota': 'menos de 3 anos distintos — bootstrap em blocos não é confiável'}
    estimativas = []
    for _ in range(n_resamples):
        anos_sorteados = rng.choice(anos, size=len(anos), replace=True)
        partes = [df_lead[df_lead[coluna_ano] == a] for a in anos_sorteados]
        amostra = pd.concat(partes, ignore_index=True)
        estimativas.append(funcao_metrica(amostra[coluna_previsto].values,
                                            amostra[coluna_observado].values))
    estimativas = np.array([e for e in estimativas if e is not None])
    valor_real = funcao_metrica(df_lead[coluna_previsto].values, df_lead[coluna_observado].values)
    return {
        'estimativa': valor_real,
        'ic95_lo': float(np.percentile(estimativas, 2.5)) if len(estimativas) else None,
        'ic95_hi': float(np.percentile(estimativas, 97.5)) if len(estimativas) else None,
        'n_anos_distintos': int(len(anos)), 'n_resamples': n_resamples,
        'metodo': 'bootstrap em blocos por ano do target_month (nunca linhas independentes)',
    }


def intervalos_confianca_por_horizonte(base_enriquecida, n_resamples=1000):
    media_membros = base_enriquecida.groupby(
        ['init_date', 'target_month', 'target_ano', 'lead'], as_index=False
    ).agg(previsto=('forecast_prec_mm', 'mean'), observado=('obs_prec_mm', 'first'))

    resultado = {}
    for lead in LEADS_ESPERADOS:
        sub = media_membros[media_membros['lead'] == lead]
        if len(sub) < AMOSTRA_MINIMA_ESTRATO:
            resultado[lead] = {'nota': 'amostra insuficiente'}
            continue
        resultado[lead] = {
            'bias': bootstrap_blocos_por_ano(sub, 'previsto', 'observado', 'target_ano',
                                               _bias, n_resamples),
            'mae': bootstrap_blocos_por_ano(sub, 'previsto', 'observado', 'target_ano',
                                              _mae, n_resamples),
            'rmse': bootstrap_blocos_por_ano(sub, 'previsto', 'observado', 'target_ano',
                                               _rmse, n_resamples),
        }
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# Revisão, item 2 — IC dos SKILL SCORES (não só das métricas cruas):
# RMSESS, CRPSS e BSS por categoria, com modelo e benchmark reamostrados
# nos MESMOS blocos de ano a cada iteração (nunca bootstraps separados,
# que invalidariam a razão entre numerador e denominador).
# ══════════════════════════════════════════════════════════════════════════

def _rmse_modelo_e_climatologia(linhas):
    prev = np.array([l['previsto'] for l in linhas])
    obs = np.array([l['observado'] for l in linhas])
    clim = np.array([l['clim_media'] for l in linhas])
    return _rmse(prev, obs), _rmse(clim, obs)


def _crps_medio_modelo_e_climatologia(linhas):
    crps_modelo = [crps_amostral(l['membros'], l['observado']) for l in linhas]
    crps_clim = [crps_amostral(l['anos_hist'], l['observado']) for l in linhas if len(l['anos_hist']) >= 2]
    media_modelo = float(np.mean(crps_modelo)) if crps_modelo else None
    media_clim = float(np.mean(crps_clim)) if crps_clim else None
    return media_modelo, media_clim


def _brier_score_categoria(linhas, categoria):
    probs, obs_ind = [], []
    for l in linhas:
        membros, t33, t67 = l['membros'], l['tercil_33'], l['tercil_67']
        p_seco = float(np.mean(membros <= t33))
        p_umido = float(np.mean(membros >= t67))
        p_normal = max(0.0, 1.0 - p_seco - p_umido)
        prob = {'seco': p_seco, 'normal': p_normal, 'umido': p_umido}[categoria]
        cat_obs = categoria_tercil(l['observado'], t33, t67)
        probs.append(prob)
        obs_ind.append(1.0 if cat_obs == categoria else 0.0)
    return float(np.mean((np.array(probs) - np.array(obs_ind)) ** 2))


def _classificar_ic_relativo_a_zero(ic_lo, ic_hi):
    """Rótulo EXPLÍCITO da posição do IC em relação a zero — nunca
    convertido automaticamente em 'bom'/'ruim' (item 2 da revisão)."""
    if ic_lo is None or ic_hi is None:
        return 'indeterminado'
    if ic_lo > 0:
        return 'ic_totalmente_acima_de_zero'
    if ic_hi < 0:
        return 'ic_totalmente_abaixo_de_zero'
    return 'ic_inclui_zero'


def _resumo_bootstrap(estimativa_pontual, valores_bootstrap):
    valores = np.array([v for v in valores_bootstrap if v is not None])
    if len(valores) == 0:
        return {'estimativa': estimativa_pontual, 'ic95_lo': None, 'ic95_hi': None}
    return {
        'estimativa': estimativa_pontual,
        'ic95_lo': float(np.percentile(valores, 2.5)),
        'ic95_hi': float(np.percentile(valores, 97.5)),
    }


def bootstrap_skill_scores_por_horizonte(base_enriquecida, chirps_df, n_resamples=500, seed=20261001):
    """Item 2 da revisão — estende o bootstrap em blocos por ano
    (Seção 9) para recalcular, DENTRO de cada reamostra: RMSE do
    CFSv2, RMSE da climatologia, RMSESS, CRPS do CFSv2, CRPS da
    climatologia probabilística, CRPSS, e BSS por categoria. Modelo e
    benchmark usam EXATAMENTE os mesmos blocos de ano sorteados em
    cada reamostra — nunca bootstraps independentes, que invalidariam
    a razão entre numerador e denominador. RMSESS/CRPSS vêm com um
    rótulo explícito da posição do IC (acima/abaixo/inclui zero) —
    NUNCA convertido automaticamente num rótulo 'bom'/'ruim'."""
    rng = np.random.default_rng(seed)
    resultado = {}

    for lead in LEADS_ESPERADOS:
        linhas = construir_linhas_avaliacao_por_lead(base_enriquecida, chirps_df, lead)
        n = len(linhas)
        if n < AMOSTRA_MINIMA_ESTRATO:
            resultado[lead] = {'n': n, 'amostra_suficiente': False,
                                'nota': 'amostra insuficiente — IC não calculado'}
            continue

        por_ano = {}
        for linha in linhas:
            por_ano.setdefault(linha['target_ano'], []).append(linha)
        anos = np.array(sorted(por_ano))
        if len(anos) < 3:
            resultado[lead] = {'n': n, 'amostra_suficiente': True,
                                'nota': 'menos de 3 anos distintos — bootstrap em blocos não é '
                                        'confiável'}
            continue

        rmse_modelo_boot, rmse_clim_boot, rmsess_boot = [], [], []
        crps_modelo_boot, crps_clim_boot, crpss_boot = [], [], []
        bss_boot = {'seco': [], 'normal': [], 'umido': []}

        for _ in range(n_resamples):
            anos_sorteados = rng.choice(anos, size=len(anos), replace=True)
            linhas_resample = [l for a in anos_sorteados for l in por_ano[a]]

            rm, rc = _rmse_modelo_e_climatologia(linhas_resample)
            rmse_modelo_boot.append(rm)
            rmse_clim_boot.append(rc)
            rs = rmsess(rm, rc)
            if rs is not None:
                rmsess_boot.append(rs)

            cm, cc = _crps_medio_modelo_e_climatologia(linhas_resample)
            if cm is not None:
                crps_modelo_boot.append(cm)
            if cc is not None:
                crps_clim_boot.append(cc)
            if cm is not None and cc:
                crpss_boot.append(1 - cm / cc)

            for cat in ('seco', 'normal', 'umido'):
                bs_resample = _brier_score_categoria(linhas_resample, cat)
                bss_boot[cat].append(1 - bs_resample / (2 / 9))

        rmse_modelo_pontual, rmse_clim_pontual = _rmse_modelo_e_climatologia(linhas)
        rmsess_pontual = rmsess(rmse_modelo_pontual, rmse_clim_pontual)
        crps_modelo_pontual, crps_clim_pontual = _crps_medio_modelo_e_climatologia(linhas)
        crpss_pontual = (1 - crps_modelo_pontual / crps_clim_pontual
                          if crps_modelo_pontual is not None and crps_clim_pontual else None)

        rmsess_resumo = _resumo_bootstrap(rmsess_pontual, rmsess_boot)
        crpss_resumo = _resumo_bootstrap(crpss_pontual, crpss_boot)
        bss_resumo = {}
        for cat in ('seco', 'normal', 'umido'):
            bss_pontual = 1 - _brier_score_categoria(linhas, cat) / (2 / 9)
            bss_resumo[cat] = _resumo_bootstrap(bss_pontual, bss_boot[cat])

        resultado[lead] = {
            'n': n, 'amostra_suficiente': True, 'n_anos_distintos': int(len(anos)),
            'n_resamples': n_resamples,
            'metodo': 'bootstrap em blocos por ano do target_month — modelo e benchmark usam '
                      'os MESMOS blocos sorteados em cada reamostra',
            'rmse_modelo': _resumo_bootstrap(rmse_modelo_pontual, rmse_modelo_boot),
            'rmse_climatologia': _resumo_bootstrap(rmse_clim_pontual, rmse_clim_boot),
            'rmsess': rmsess_resumo,
            'rmsess_ic_classificacao': _classificar_ic_relativo_a_zero(
                rmsess_resumo['ic95_lo'], rmsess_resumo['ic95_hi']),
            'crps_modelo': _resumo_bootstrap(crps_modelo_pontual, crps_modelo_boot),
            'crps_climatologia': _resumo_bootstrap(crps_clim_pontual, crps_clim_boot),
            'crpss': crpss_resumo,
            'crpss_ic_classificacao': _classificar_ic_relativo_a_zero(
                crpss_resumo['ic95_lo'], crpss_resumo['ic95_hi']),
            'bss_por_categoria': bss_resumo,
            'nota': "IC nunca convertido automaticamente em rótulo 'bom'/'ruim' — ver "
                    "*_ic_classificacao (ic_totalmente_acima_de_zero / ic_inclui_zero / "
                    "ic_totalmente_abaixo_de_zero).",
        }
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# Orquestração
# ══════════════════════════════════════════════════════════════════════════

def executar_auditoria():
    df_raw = carregar_cfsv2_raw()
    return auditar_base_raw(df_raw)


def executar_pareamento_e_salvar():
    df_raw = carregar_cfsv2_raw()
    chirps_df = carregar_chirps_v3_historico()
    base = construir_base_pareada(df_raw, chirps_df)
    if not validar_nenhum_mes_alvo_ausente(base):
        raise RuntimeError("base pareada com mês-alvo ausente — STOP-ON-FAILURE, não prosseguir.")
    DIRETORIO_SAIDA.mkdir(parents=True, exist_ok=True)
    base.to_csv(CAMINHO_BASE_PAREADA, index=False)
    return base


def _enriquecer_com_climatologia_loyo(base_pareada, chirps_df):
    """Análise RETROSPECTIVA complementar (Seção 13) — climatologia
    LOYO (usa todos os anos exceto o do próprio target, passado E
    futuro). Rotulada 'loyo_retrospective'; NUNCA substitui nem se
    mistura com a climatologia expansível operacional
    ('expanding_operational_simulation')."""
    obs_dict = _obs_dict(chirps_df)
    cache = {}
    medias, t33s, t67s, n_anoss = [], [], [], []
    for mes_alvo, ano_alvo in zip(base_pareada['target_mes'], base_pareada['target_ano']):
        chave = (mes_alvo, ano_alvo)
        if chave not in cache:
            cache[chave] = climatologia_loyo(mes_alvo, ano_alvo, obs_dict)
        c = cache[chave]
        medias.append(c['media'])
        t33s.append(c['tercil_33'])
        t67s.append(c['tercil_67'])
        n_anoss.append(c['n_anos'])
    base = base_pareada.copy()
    base['clim_media'] = medias
    base['clim_tercil_33'] = t33s
    base['clim_tercil_67'] = t67s
    base['clim_n_anos'] = n_anoss
    # LOYO é uma análise RETROSPECTIVA só da climatologia OBSERVADA
    # (item 13) — não tem uma climatologia própria do modelo
    # equivalente nesta revisão; colunas presentes como NaN só para
    # metricas_deterministicas_por_horizonte() aceitar o mesmo
    # formato de entrada (ela já trata ausência de climatologia do
    # modelo graciosamente, reportando 'anomalia_corrigida_...' como
    # indisponível em vez de falhar).
    base['clim_modelo_media'] = np.nan
    base['clim_modelo_n_inits'] = 0
    return base


def executar_loyo_retrospectivo(base_pareada=None, chirps_df=None):
    """Seção 13 — LOYO como análise RETROSPECTIVA complementar (NÃO
    causal — usa anos futuros também). Reusa as mesmas funções de
    métrica determinística, mas sobre a climatologia LOYO. Rotulado
    explicitamente 'loyo_retrospective' no retorno."""
    if base_pareada is None or chirps_df is None:
        df_raw = carregar_cfsv2_raw()
        chirps_df = carregar_chirps_v3_historico()
        base_pareada = construir_base_pareada(df_raw, chirps_df)
    base_loyo = _enriquecer_com_climatologia_loyo(base_pareada, chirps_df)
    return {
        'rotulo': 'loyo_retrospective',
        'aviso': 'NÃO simula uso em tempo real — usa anos futuros na climatologia. Análise '
                 'complementar apenas, nunca misturada com expanding_operational_simulation.',
        'deterministico_por_horizonte': metricas_deterministicas_por_horizonte(base_loyo),
    }


def executar_todas_metricas(n_resamples_bootstrap=1000, n_resamples_bootstrap_skill=500):
    auditoria = executar_auditoria()
    if not auditoria['auditoria_aprovada']:
        return {'auditoria': auditoria, 'STOP_ON_FAILURE': True,
                'motivo': 'auditoria da base RAW reprovada — métricas não calculadas',
                'problemas': auditoria['problemas']}

    df_raw = carregar_cfsv2_raw()
    chirps_df = carregar_chirps_v3_historico()
    base = construir_base_pareada(df_raw, chirps_df)
    if not validar_nenhum_mes_alvo_ausente(base):
        return {'auditoria': auditoria, 'STOP_ON_FAILURE': True,
                'motivo': 'pareamento com mês-alvo ausente'}

    base_enriquecida = _enriquecer_com_climatologia(base, chirps_df)

    expanding = {
        'rotulo': 'expanding_operational_simulation',
        'n_registros_pareados': len(base),
        'n_meses_alvo_distintos': int(base['target_month'].nunique()),
        'deterministico_por_horizonte': metricas_deterministicas_por_horizonte(base_enriquecida),
        'por_mes_do_ano': metricas_por_mes_do_ano(base_enriquecida),
        'matriz_mes_lead': metricas_matriz_mes_lead(base_enriquecida),
        'matriz_grupo_sazonal_lead': metricas_matriz_grupo_sazonal_lead(base_enriquecida),
        'probabilistico_por_horizonte': avaliar_probabilistico_por_horizonte(base_enriquecida, chirps_df),
        'intervalos_confianca_por_horizonte': intervalos_confianca_por_horizonte(
            base_enriquecida, n_resamples_bootstrap),
        'intervalos_confianca_skill_scores_por_horizonte': bootstrap_skill_scores_por_horizonte(
            base_enriquecida, chirps_df, n_resamples_bootstrap_skill),
    }
    loyo = executar_loyo_retrospectivo(base, chirps_df)

    resultado = {
        'auditoria': auditoria,
        'STOP_ON_FAILURE': False,
        'expanding_operational_simulation': expanding,
        'loyo_retrospective': loyo,
        'nenhuma_skill_apresentada_no_dashboard': True,
        'nenhum_dado_operacional_alterado': True,
        'data_geracao_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--auditar', action='store_true')
    ap.add_argument('--executar-metricas', action='store_true')
    ap.add_argument('--gerar-relatorio', action='store_true')
    args = ap.parse_args()

    if args.auditar:
        a = executar_auditoria()
        print(json.dumps(a, indent=2, ensure_ascii=False, default=str))
        return

    if args.executar_metricas:
        r = executar_todas_metricas()
        DIRETORIO_SAIDA.mkdir(parents=True, exist_ok=True)
        CAMINHO_METRICAS_JSON.write_text(json.dumps(r, indent=2, ensure_ascii=False, default=str))
        executar_pareamento_e_salvar()
        print(f"  ✅ {CAMINHO_METRICAS_JSON.relative_to(ROOT)}")
        print(f"  ✅ {CAMINHO_BASE_PAREADA.relative_to(ROOT)}")
        if r['STOP_ON_FAILURE']:
            print(f"\n❌ STOP_ON_FAILURE: {r['motivo']}")
        return

    if args.gerar_relatorio:
        import cfsv2_relatorio_2c3c as rel
        rel.gerar_e_escrever()
        return

    ap.print_help()


if __name__ == '__main__':
    main()
