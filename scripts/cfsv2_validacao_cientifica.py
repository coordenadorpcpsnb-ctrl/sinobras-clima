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
    """Acrescenta, para cada linha, a climatologia expansível (média/
    tercis/n_anos) do mês-alvo correspondente — calculada uma vez por
    (mes_alvo, init_date) e reaproveitada entre leads/membros que
    compartilham a mesma combinação, nunca recalculada linha a linha
    com risco de inconsistência."""
    obs_dict = _obs_dict(chirps_df)
    cache = {}
    medias, t33s, t67s, n_anoss = [], [], [], []
    for mes_alvo, init_date in zip(base_pareada['target_mes'], base_pareada['init_date']):
        chave = (mes_alvo, init_date)
        if chave not in cache:
            cache[chave] = climatologia_expansivel(mes_alvo, init_date, obs_dict)
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
    return base


def metricas_deterministicas_por_horizonte(base_enriquecida):
    """Média dos 24 membros como previsão determinística (Seção 6).
    Calcula separadamente para cada H — NUNCA agrega H1 com H2-H6.
    Reporta absoluto e anomalia (previsto-climatologia vs.
    observado-climatologia), e o benchmark/skill score da climatologia
    (Seção 7) no mesmo lugar, para leitura conjunta."""
    resultado = {}
    media_membros = base_enriquecida.groupby(
        ['init_date', 'target_month', 'lead'], as_index=False
    ).agg(previsto=('forecast_prec_mm', 'mean'),
          observado=('obs_prec_mm', 'first'),
          clim_media=('clim_media', 'first'),
          clim_n_anos=('clim_n_anos', 'first'))

    for lead in LEADS_ESPERADOS:
        sub = media_membros[media_membros['lead'] == lead].dropna(subset=['clim_media'])
        n = len(sub)
        if n == 0:
            resultado[lead] = {'n': 0, 'rotulo': ROTULO_HORIZONTE[lead]}
            continue
        prev = sub['previsto'].values
        obs = sub['observado'].values
        clim = sub['clim_media'].values
        anom_prev = prev - clim
        anom_obs = obs - clim

        rmse_modelo = _rmse(prev, obs)
        rmse_clim = _rmse(clim, obs)
        rmse_modelo_anom = _rmse(anom_prev, anom_obs)
        rmse_clim_anom = _rmse(np.zeros_like(anom_obs), anom_obs)   # climatologia prevê anomalia 0

        resultado[lead] = {
            'n': n,
            'rotulo': ROTULO_HORIZONTE[lead],
            'amostra_suficiente': n >= AMOSTRA_MINIMA_ESTRATO,
            'absoluto': {
                'bias': _bias(prev, obs), 'mae': _mae(prev, obs),
                'rmse': rmse_modelo, 'corr': _corr(prev, obs),
            },
            'anomalia': {
                'bias': _bias(anom_prev, anom_obs), 'mae': _mae(anom_prev, anom_obs),
                'rmse': rmse_modelo_anom, 'corr': _corr(anom_prev, anom_obs),
            },
            'benchmark_climatologico': {
                'bias': _bias(clim, obs), 'mae': _mae(clim, obs), 'rmse': rmse_clim,
            },
            'rmsess_absoluto': rmsess(rmse_modelo, rmse_clim),
            'rmsess_anomalia': rmsess(rmse_modelo_anom, rmse_clim_anom),
            'formula_rmsess': 'RMSESS = 1 - RMSE_modelo / RMSE_climatologia',
        }
    return resultado


def metricas_por_mes_do_ano(base_enriquecida):
    """Seção 10 — avaliação sazonal por mês do ano (nunca escondida
    numa média anual única). Usa a média dos membros, mesma lógica de
    metricas_deterministicas_por_horizonte, mas agrupando por mês-alvo
    em vez de por lead."""
    media_membros = base_enriquecida.groupby(
        ['init_date', 'target_month', 'target_mes', 'lead'], as_index=False
    ).agg(previsto=('forecast_prec_mm', 'mean'), observado=('obs_prec_mm', 'first'))

    resultado = {}
    for mes in range(1, 13):
        sub = media_membros[media_membros['target_mes'] == mes]
        n = len(sub)
        if n == 0:
            resultado[mes] = {'n': 0}
            continue
        prev, obs = sub['previsto'].values, sub['observado'].values
        resultado[mes] = {
            'n': n, 'grupo_sazonal': GRUPO_SAZONAL_POR_MES[mes],
            'amostra_suficiente': n >= AMOSTRA_MINIMA_ESTRATO,
            'bias': _bias(prev, obs), 'mae': _mae(prev, obs),
            'rmse': _rmse(prev, obs), 'corr': _corr(prev, obs),
        }

    por_grupo = {}
    for grupo in ('chuvosa', 'transicao', 'seca'):
        meses_grupo = [m for m, g in GRUPO_SAZONAL_POR_MES.items() if g == grupo]
        sub = media_membros[media_membros['target_mes'].isin(meses_grupo)]
        n = len(sub)
        if n == 0:
            por_grupo[grupo] = {'n': 0}
            continue
        prev, obs = sub['previsto'].values, sub['observado'].values
        por_grupo[grupo] = {
            'n': n, 'amostra_suficiente': n >= AMOSTRA_MINIMA_ESTRATO,
            'bias': _bias(prev, obs), 'mae': _mae(prev, obs),
            'rmse': _rmse(prev, obs), 'corr': _corr(prev, obs),
        }
    return {'por_mes': resultado, 'por_grupo_sazonal': por_grupo}


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


def avaliar_probabilistico_por_horizonte(base_enriquecida, chirps_df, seed=20261001):
    """CRPS, CRPSS (contra climatologia probabilística = conjunto dos
    anos históricos elegíveis), rank histogram e, para tercis, Brier
    Score/BSS — tudo com os limites de tercil calculados SOMENTE com o
    histórico permitido antes de cada inicialização (nunca com
    1981-2011 completo)."""
    obs_dict = _obs_dict(chirps_df)
    rng = np.random.default_rng(seed)
    resultado = {}

    grupos = base_enriquecida.groupby(['init_date', 'target_month', 'lead'])
    por_lead = {lead: {'crps_modelo': [], 'crps_clim': [], 'ranks': [],
                        'prob_seco': [], 'prob_normal': [], 'prob_umido': [],
                        'obs_cat_seco': [], 'obs_cat_normal': [], 'obs_cat_umido': []}
                for lead in LEADS_ESPERADOS}

    for (init_date, target_month, lead), grupo in grupos:
        membros = grupo['forecast_prec_mm'].values
        if len(membros) != N_MEMBROS_ESPERADO:
            continue
        obs = float(grupo['obs_prec_mm'].iloc[0])
        mes_alvo = int(grupo['target_mes'].iloc[0])
        clim = climatologia_expansivel(mes_alvo, init_date, obs_dict)
        if clim['n_anos'] < 3:
            continue   # climatologia degenerada demais para servir de referência probabilística

        anos_hist = [obs_dict[(a, mes_alvo)] for a in clim['anos_usados']]

        por_lead[lead]['crps_modelo'].append(crps_amostral(membros, obs))
        por_lead[lead]['crps_clim'].append(crps_amostral(anos_hist, obs) if len(anos_hist) >= 2 else np.nan)
        por_lead[lead]['ranks'].append(rank_observacao(membros, obs, rng))

        t33, t67 = clim['tercil_33'], clim['tercil_67']
        p_seco = float(np.mean(membros <= t33))
        p_umido = float(np.mean(membros >= t67))
        p_normal = max(0.0, 1.0 - p_seco - p_umido)
        cat_obs = categoria_tercil(obs, t33, t67)

        por_lead[lead]['prob_seco'].append(p_seco)
        por_lead[lead]['prob_normal'].append(p_normal)
        por_lead[lead]['prob_umido'].append(p_umido)
        por_lead[lead]['obs_cat_seco'].append(1.0 if cat_obs == 'seco' else 0.0)
        por_lead[lead]['obs_cat_normal'].append(1.0 if cat_obs == 'normal' else 0.0)
        por_lead[lead]['obs_cat_umido'].append(1.0 if cat_obs == 'umido' else 0.0)

    for lead in LEADS_ESPERADOS:
        d = por_lead[lead]
        n = len(d['crps_modelo'])
        if n < AMOSTRA_MINIMA_ESTRATO:
            resultado[lead] = {'n': n, 'amostra_suficiente': False,
                                'nota': 'amostra insuficiente — estatística não calculada'}
            continue

        crps_modelo = np.array(d['crps_modelo'])
        crps_clim = np.array(d['crps_clim'])
        validos = ~np.isnan(crps_clim)
        crps_medio_modelo = float(crps_modelo.mean())
        crps_medio_clim = float(crps_clim[validos].mean()) if validos.any() else None
        crpss = (1 - crps_medio_modelo / crps_medio_clim) if crps_medio_clim else None

        ranks = np.array(d['ranks'])
        hist_rank = {int(r): int((ranks == r).sum()) for r in range(1, N_MEMBROS_ESPERADO + 2)}

        bs = {}
        bss = {}
        bs_referencia = 2 / 9   # p=1/3 climatológico: p*(1-p) = (1/3)(2/3) = 2/9
        for cat, chave_prob, chave_obs in (('seco', 'prob_seco', 'obs_cat_seco'),
                                             ('normal', 'prob_normal', 'obs_cat_normal'),
                                             ('umido', 'prob_umido', 'obs_cat_umido')):
            p = np.array(d[chave_prob])
            o = np.array(d[chave_obs])
            bs[cat] = float(np.mean((p - o) ** 2))
            bss[cat] = float(1 - bs[cat] / bs_referencia)

        resultado[lead] = {
            'n': n, 'amostra_suficiente': True,
            'crps_medio_modelo': crps_medio_modelo,
            'crps_medio_climatologia': crps_medio_clim,
            'crpss': crpss,
            'formula_crpss': 'CRPSS = 1 - CRPS_modelo / CRPS_climatologia_probabilistica',
            'rank_histogram': hist_rank,
            'brier_score_por_categoria': bs,
            'bss_por_categoria': bss,
            'formula_bss': 'BSS = 1 - BS_modelo / BS_referencia_climatologica (p=1/3, BS_ref=2/9)',
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


def executar_todas_metricas(n_resamples_bootstrap=1000):
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
        'probabilistico_por_horizonte': avaliar_probabilistico_por_horizonte(base_enriquecida, chirps_df),
        'intervalos_confianca_por_horizonte': intervalos_confianca_por_horizonte(
            base_enriquecida, n_resamples_bootstrap),
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
