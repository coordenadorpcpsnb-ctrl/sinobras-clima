#!/usr/bin/env python3
"""
c3s_multimodel_hindcast.py — Fase 2B.2: infraestrutura do HINDCAST
MULTI-MODELO COMPLETO (1993-2016), avaliação de skill homogênea entre
CLIM / ECMWF_RAW/BC / METEO_FRANCE_RAW/BC / DWD_RAW/BC / CMCC_RAW/BC /
MME_RAW/BC, condicionada ao mesmo protocolo científico congelado desde
a Fase 2A.3 e reaproveitado sem alteração na Fase 2B.1 (POC, run real
35504621262 — 4 sistemas, 6/6 origens cada, zero falhas, membros/leads/
unidade/mapeamento temporal confirmados).

Pergunta científica (Seção 1): o ensemble multi-modelo melhora a
previsão de precipitação de São Bento do Tocantins em relação (1) à
climatologia, (2) ao ECMWF isolado, (3) aos demais modelos individuais?
Atenção especial a H2-H6, set-fev, e probabilidades tercílicas.

ESCOPO DESTA ENTREGA (Seção 50): só infraestrutura — orquestração de
chunk/consolidação/métricas/bootstrap/comparação pareada + testes +
workflow + dry-run. NÃO executa o pilot nem o hindcast completo real.

ARQUITETURA — reaproveita, não duplica:
  - c3s_multimodel_catalogo.py::CATALOGO/periodo_comum_hindcast — os 4
    sistemas CONGELADOS (Seção 3) e o período comum de avaliação
    (1993-2016), sempre DERIVADO do catálogo, nunca hardcoded (Seção 4).
  - c3s_multimodel_poc.py::processar_origem_modelo — download+validação
    por (sistema, origem), barreiras A-H já confirmadas em execução
    real para os 4 sistemas (run 35504621262). Reaproveitado sem
    alteração para CADA origem de CADA chunk (Seção 21).
  - c3s_multimodel.py — combinação MME por equal-model-weighting
    (mme_deterministico/mme_probabilistico/construir_mme_por_origem_lead),
    já com a correção NaN/BC-indisponível da Fase 2B.1 (run 35437819463).
  - c3s_calibracao.py — climatologia/bias leakage-safe, MESMA
    metodologia congelada desde a Fase 2A.3; bias calculado
    SEPARADAMENTE por modelo (Seção 10 — nunca usar erro de um modelo
    para corrigir outro).
  - c3s_hindcast.py / c3s_skill.py — estatísticas de ensemble,
    probabilidades por tercis, métricas determinísticas/
    probabilísticas, MSESS, bootstrap — reaproveitados sem reimplementar
    fórmula, só generalizados de RAW/BC (2 variantes) para N variantes
    (Seção 29).
  - c3s_hindcast_completo.py::intervalo_targets_necessario/
    buscar_chirps_consolidado — MESMA cobertura CHIRPS em blocos anuais
    corrigida na Fase 2A.3, reaproveitada sem reimplementar (o piso do
    intervalo, ANO_INICIO_HINDCAST=1981 daquele módulo, já é exatamente
    o warmup climatológico pedido pela Seção 8 desta fase — 1981-01 a
    2017-05, 437 meses, nunca hardcoded aqui).

NÃO FAZER (Seção 2): otimizar pesos, selecionar modelo por skill, ML,
stacking, regressão entre modelos, Bayesian Model Averaging, remover
sistema por RMSE, alterar bias correction. Baseline único: equal-model
weighting (congelado desde a Fase 2B.1).

CRPS (Seção 17): não incluído nas tabelas de skill desta entrega — a
primitiva `c3s_skill.crps_empirico` opera sobre UM ensemble de membros
por vez; para MME isso exigiria concatenar membros de modelos
diferentes, o que a Seção 18/19 proíbe explicitamente (equal-model
weighting nunca mistura membros). Mesmo precedente da Fase 2A.3: Brier/
BSS/RPS/RPSS entram nas tabelas de skill probabilístico, CRPS fica como
utilitário isolado, não wired nas tabelas principais.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import c3s_hindcast as hc  # noqa: E402
import c3s_calibracao as calib  # noqa: E402
import c3s_skill as skill  # noqa: E402
import c3s_multimodel as mm  # noqa: E402
import c3s_multimodel_catalogo as mcat  # noqa: E402
import c3s_multimodel_poc as mp  # noqa: E402
from c3s_hindcast_completo import (  # noqa: E402
    intervalo_targets_necessario, buscar_chirps_consolidado,
    ESTACOES_OPERACIONAIS, MESES_BLOCO_OPERACIONAL_PRIORITARIO, NOME_BLOCO_OPERACIONAL_PRIORITARIO,
)

ROOT = Path(__file__).parent.parent
ARTIFACTS_DIR = ROOT / 'artifacts' / 'c3s_multimodel_hindcast'
CHUNKS_DIR = ROOT / 'artifacts' / 'c3s_multimodel_hindcast_chunks'

MUNICIPIO = mp.MUNICIPIO
LEADS = mp.LEADS
MIN_ANOS_TREINO = calib.MIN_ANOS_TREINO

# Seção 3/4 — 4 sistemas CONGELADOS (mesmos da Fase 2B.1, confirmados
# em execução real run 35504621262: ECMWF/SEAS5 25 membros,
# METEO_FRANCE/System8 25, DWD/GCFS2.1 30, CMCC/SPS3.5 40). Período
# comum SEMPRE derivado do catálogo (Seção 4 exige "verificar
# dinamicamente"), nunca hardcoded.
SISTEMAS = mcat.CATALOGO
_COMUM = mcat.periodo_comum_hindcast(SISTEMAS)
ANO_INICIO_HINDCAST = _COMUM['common_start']    # 1993
ANO_FIM_HINDCAST = _COMUM['common_end']         # 2016
if ANO_INICIO_HINDCAST is None or ANO_FIM_HINDCAST is None:
    raise RuntimeError("período comum de hindcast não pôde ser derivado do catálogo multi-modelo "
                        f"(incompatibilidade: {_COMUM['incompatibilidade']}) — FALHANDO no import, "
                        "antes de qualquer uso.")

# Seção 11 — primeiro ano avaliável de BC: precisa de MIN_ANOS_TREINO
# anos ANTERIORES de hindcast do MESMO mês-calendário — derivado, nunca
# hardcoded (para o catálogo atual: 1993+10=2003).
AVALIACAO_ANO_INICIO = ANO_INICIO_HINDCAST + MIN_ANOS_TREINO
AVALIACAO_ANO_FIM = ANO_FIM_HINDCAST
WARMUP_ANO_INICIO = ANO_INICIO_HINDCAST
WARMUP_ANO_FIM = AVALIACAO_ANO_INICIO - 1

# Seção 14 — split development/temporal_validation, 7+7 anos. NUNCA
# renomear para "confirmação independente" (bias/climatologia
# continuam em janela expansiva) e nunca reajustar depois de ver
# resultado.
DEVELOPMENT_ANO_INICIO = AVALIACAO_ANO_INICIO
DEVELOPMENT_ANO_FIM = AVALIACAO_ANO_INICIO + 6
TEMPORAL_VALIDATION_ANO_INICIO = DEVELOPMENT_ANO_FIM + 1
TEMPORAL_VALIDATION_ANO_FIM = AVALIACAO_ANO_FIM

N_BOOTSTRAP = 2000
SEED_BOOTSTRAP = 42

# Seção 21/23 — chunking da aquisição: 4 modelos x 4 blocos de 6 anos =
# 16 jobs, max-parallel=2 (Seção 23 — não aumentar automaticamente).
TAMANHO_BLOCO_CHUNK_ANOS = 6
MAX_PARALLEL_CHUNKS = 2

# Seção 45 — pilot de INFRAESTRUTURA do workflow chunked (não repete a
# Fase 2B.1 inteira): 2 anos (24 origens/modelo), o bastante para
# exercitar matrix/artifact upload/download/consolidação sem skill.
PILOT_ANO_INICIO = ANO_INICIO_HINDCAST
PILOT_ANO_FIM = ANO_INICIO_HINDCAST + 1
PILOT_TAMANHO_BLOCO_ANOS = PILOT_ANO_FIM - PILOT_ANO_INICIO + 1

_ROTULO_ARTIFACT_CENTRO = {'ECMWF': 'ecmwf', 'METEO_FRANCE': 'metfr', 'DWD': 'dwd', 'CMCC': 'cmcc'}

VARIANTES = mm.variantes_comparacao(SISTEMAS)   # ['CLIM', 'ECMWF_RAW', ..., 'MME_RAW', 'MME_BC']

# Seção 5/27 — contagens FULL, todas DERIVADAS (nunca hardcoded), com
# os valores esperados documentados em comentário para conferência
# visual (Seção 51-C).
N_ORIGENS_POR_MODELO_FULL = (ANO_FIM_HINDCAST - ANO_INICIO_HINDCAST + 1) * 12          # 288
N_MODELO_ORIGEM_FULL = len(SISTEMAS) * N_ORIGENS_POR_MODELO_FULL                       # 1.152
N_RAW_ESPERADO_POR_MODELO_FULL = {s.centro: s.hindcast_members * N_ORIGENS_POR_MODELO_FULL * len(LEADS)
                                   for s in SISTEMAS}
N_RAW_ESPERADO_TOTAL_FULL = sum(N_RAW_ESPERADO_POR_MODELO_FULL.values())               # 207.360
N_SUMMARY_ESPERADO_FULL = len(SISTEMAS) * N_ORIGENS_POR_MODELO_FULL * len(LEADS)       # 6.912
N_MME_ESPERADO_FULL = N_ORIGENS_POR_MODELO_FULL * len(LEADS)                           # 1.728
N_TEMPORAL_AUDIT_ESPERADO_FULL = N_SUMMARY_ESPERADO_FULL                               # 6.912
N_AVALIACAO_PRINCIPAL_ESPERADO_FULL = (
    (AVALIACAO_ANO_FIM - AVALIACAO_ANO_INICIO + 1) * 12 * len(LEADS))                  # 1.008

# Seção 22 — contagens por CHUNK (72 origens = 1 bloco de 6 anos).
N_ORIGENS_POR_CHUNK = TAMANHO_BLOCO_CHUNK_ANOS * 12                                    # 72
N_RAW_ESPERADO_POR_CHUNK = {s.centro: s.hindcast_members * N_ORIGENS_POR_CHUNK * len(LEADS)
                             for s in SISTEMAS}
N_CHUNKS = len(SISTEMAS) * ((ANO_FIM_HINDCAST - ANO_INICIO_HINDCAST + 1) // TAMANHO_BLOCO_CHUNK_ANOS)  # 16

ARTIFACT_FILENAMES = [
    'c3s_multimodel_raw.csv', 'c3s_multimodel_summary.csv', 'c3s_multimodel_mme.csv',
    'c3s_multimodel_temporal_audit.csv', 'c3s_multimodel_leakage_audit.csv',
    'chirps_sao_bento_multimodel_targets.csv', 'skill_multimodel_overall.csv',
    'skill_multimodel_by_lead.csv', 'skill_multimodel_by_month.csv', 'skill_multimodel_by_month_lead.csv',
    'skill_multimodel_operational_seasons.csv', 'skill_multimodel_probabilistic_overall.csv',
    'skill_multimodel_probabilistic_by_lead.csv', 'skill_multimodel_probabilistic_by_month.csv',
    'skill_multimodel_temporal_validation.csv', 'bootstrap_multimodel_skill.csv',
    'paired_mme_vs_ecmwf.csv', 'paired_mme_vs_models.csv', 'metadata.json', 'RELATORIO.md',
]


def _origem_str(ano, mes):
    return f'{ano:04d}-{mes:02d}'


def montar_origens(ano_ini, ano_fim):
    return [(ano, mes) for ano in range(ano_ini, ano_fim + 1) for mes in range(1, 13)]


def _periodo_avaliacao(origem):
    ano = origem.year if isinstance(origem, pd.Period) else origem
    if ano < AVALIACAO_ANO_INICIO:
        return 'warmup'
    if ano <= DEVELOPMENT_ANO_FIM:
        return 'development'
    return 'temporal_validation'


def _com_periods(df, colunas=('init_date', 'target_month')):
    d = df.copy()
    for c in colunas:
        if c in d.columns:
            d[c] = d[c].apply(lambda s: s if isinstance(s, pd.Period) else pd.Period(s, 'M'))
    return d


# ══════════════════════════════════════════════════════════════════════════
# Seção 21-23 — chunking da aquisição (nunca um job único de 1.152
# combinações).
# ══════════════════════════════════════════════════════════════════════════

def construir_blocos_chunk(ano_ini=ANO_INICIO_HINDCAST, ano_fim=ANO_FIM_HINDCAST,
                            tamanho_anos=TAMANHO_BLOCO_CHUNK_ANOS):
    """Divide [ano_ini, ano_fim] em blocos consecutivos de `tamanho_anos`
    anos cada (Seção 21 — 4 blocos de 6 anos para 1993-2016: 1993-1998/
    1999-2004/2005-2010/2011-2016). Falha explicitamente se o intervalo
    não for múltiplo exato do tamanho do bloco — nunca um bloco final
    truncado silenciosamente."""
    n_anos = ano_fim - ano_ini + 1
    if n_anos % tamanho_anos != 0:
        raise ValueError(f"período {ano_ini}-{ano_fim} ({n_anos} anos) não é múltiplo exato de "
                          f"{tamanho_anos} anos — não é possível dividir em blocos iguais sem truncar.")
    return [(ini, ini + tamanho_anos - 1) for ini in range(ano_ini, ano_fim + 1, tamanho_anos)]


def nome_artifact_chunk(centro, ano_ini, ano_fim):
    """Seção 24 — nome único por chunk: c3s-mm-<rótulo>-<ini>-<fim>
    (ex.: c3s-mm-ecmwf-1993-1998, c3s-mm-metfr-1993-1998)."""
    rotulo = _ROTULO_ARTIFACT_CENTRO.get(centro, centro.lower())
    return f'c3s-mm-{rotulo}-{ano_ini}-{ano_fim}'


def construir_matriz_chunks(sistemas=SISTEMAS, ano_ini=ANO_INICIO_HINDCAST, ano_fim=ANO_FIM_HINDCAST,
                             tamanho_anos=TAMANHO_BLOCO_CHUNK_ANOS):
    """1 entrada por (modelo, bloco) — a matrix do workflow chunked
    (Seção 21). Cada entrada: centro, system_name, ano_ini/fim,
    n_origens, n_raw_esperado (membros do modelo x n_origens x leads),
    artifact_name."""
    blocos = construir_blocos_chunk(ano_ini, ano_fim, tamanho_anos)
    matriz = []
    for sistema in sistemas:
        for b_ini, b_fim in blocos:
            n_origens = (b_fim - b_ini + 1) * 12
            matriz.append({
                'centro': sistema.centro, 'system_name': sistema.system_name,
                'ano_ini': b_ini, 'ano_fim': b_fim, 'n_origens': n_origens,
                'n_raw_esperado': n_origens * sistema.hindcast_members * len(LEADS),
                'artifact_name': nome_artifact_chunk(sistema.centro, b_ini, b_fim),
            })
    return matriz


# ══════════════════════════════════════════════════════════════════════════
# Aquisição de UM chunk (1 modelo x 1 bloco de anos) — reaproveita
# processar_origem_modelo (barreiras A-H já confirmadas em execução
# real, Fase 2B.1) sem alteração.
# ══════════════════════════════════════════════════════════════════════════

def rodar_chunk(sistema, ano_ini, ano_fim, sleep_fn=time.sleep):
    """Baixa+valida TODAS as origens de UM (sistema, bloco) — nunca
    mistura modelos num mesmo chunk (Seção 21)."""
    origens = montar_origens(ano_ini, ano_fim)
    raws, temporais, metadados, falhas = [], [], {}, {}
    for ano, mes in origens:
        chave = _origem_str(ano, mes)
        print(f"\n=== {sistema.centro}/{sistema.system_name} {chave} ===")
        try:
            tabela, temporal_audit, meta = mp.processar_origem_modelo(sistema, ano, mes, sleep_fn=sleep_fn)
        except Exception as e:
            print(f"  ❌ FALHOU: {e}")
            falhas[chave] = str(e)
            continue
        raws.append(tabela)
        temporais.append(temporal_audit)
        metadados[chave] = meta
        print(f"  ✅ {chave}: {len(tabela)} linhas raw")

    raw_df = pd.concat(raws, ignore_index=True) if raws else pd.DataFrame()
    temporal_audit_df = pd.concat(temporais, ignore_index=True) if temporais else pd.DataFrame()
    return {
        'sistema': sistema, 'ano_ini': ano_ini, 'ano_fim': ano_fim, 'origens': origens,
        'raw_df': raw_df, 'temporal_audit_df': temporal_audit_df,
        'falhas': falhas, 'metadados': metadados,
    }


def validar_chunk_aprovado(resultado_chunk):
    """Seção 25 — fail-fast do chunk: 72/72 origens, membros esperados,
    leads 1-6, raw finito, não-negativo, mapeamento temporal aprovado,
    unidade aprovada, contagem raw exata, zero duplicatas. Retorna
    (aprovado: bool, motivos: list[str])."""
    r = resultado_chunk
    sistema = r['sistema']
    motivos = []
    n_origens_esperado = len(r['origens'])

    n_ok = n_origens_esperado - len(r['falhas'])
    if n_ok != n_origens_esperado:
        motivos.append(f"{n_ok}/{n_origens_esperado} origens processadas com sucesso: {sorted(r['falhas'])}")

    raw_df = r['raw_df']
    if raw_df.empty:
        motivos.append("raw_df vazio — impossível checar membros/leads/contagem")
        return (len(motivos) == 0, motivos)

    valores = raw_df['c3s_prec_mm'].to_numpy(dtype=float)
    if not np.all(np.isfinite(valores)):
        motivos.append("raw contém valor(es) não finito(s) (NaN/inf)")
    if (valores < 0).any():
        motivos.append("raw contém precipitação negativa")

    membros_por_origem = raw_df.groupby('init_date')['member'].nunique()
    if not (membros_por_origem == sistema.hindcast_members).all():
        motivos.append(f"nem todas as origens têm {sistema.hindcast_members} membros "
                        f"({sistema.centro}/{sistema.system_name})")

    leads_por_origem = raw_df.groupby('init_date')['lead'].nunique()
    if not (leads_por_origem == len(LEADS)).all():
        motivos.append(f"nem todas as origens têm {len(LEADS)} leads")

    n_raw_esperado = n_origens_esperado * sistema.hindcast_members * len(LEADS)
    if len(raw_df) != n_raw_esperado:
        motivos.append(f"{len(raw_df)} linhas raw, esperado {n_raw_esperado}")

    duplicatas = int(raw_df.duplicated(subset=['centre', 'system_name', 'init_date', 'lead', 'member']).sum())
    if duplicatas:
        motivos.append(f"{duplicatas} linha(s) duplicada(s) no raw")

    temporal_audit_df = r['temporal_audit_df']
    n_temporal_esperado = n_origens_esperado * len(LEADS)
    if len(temporal_audit_df) != n_temporal_esperado:
        motivos.append(f"temporal_audit tem {len(temporal_audit_df)} linhas, esperado {n_temporal_esperado}")
    elif not temporal_audit_df.empty and \
            not temporal_audit_df['lead1_e_mes_nominal_da_inicializacao'].all():
        motivos.append("alguma linha do temporal_audit tem lead1_e_mes_nominal_da_inicializacao=False")

    unidades = set(raw_df['units_original'].unique())
    if not unidades.issubset({'m s**-1', 'm s-1', 'm/s'}):
        motivos.append(f"unidade(s) fora do conjunto aceito: {sorted(unidades)}")

    return (len(motivos) == 0, motivos)


def escrever_saidas_chunk(resultado_chunk, diretorio_base=None):
    r = resultado_chunk
    sistema = r['sistema']
    diretorio_base = Path(diretorio_base) if diretorio_base else CHUNKS_DIR
    diretorio = diretorio_base / f'{sistema.centro}_{r["ano_ini"]}_{r["ano_fim"]}'
    diretorio.mkdir(parents=True, exist_ok=True)
    r['raw_df'].to_csv(diretorio / 'raw.csv', index=False)
    r['temporal_audit_df'].to_csv(diretorio / 'temporal_audit.csv', index=False)
    metadata_chunk = {
        'centro': sistema.centro, 'system_name': sistema.system_name, 'system_code': sistema.system_code,
        'ano_ini': r['ano_ini'], 'ano_fim': r['ano_fim'], 'n_origens': len(r['origens']),
        'n_falhas': len(r['falhas']), 'falhas': r['falhas'], 'n_linhas_raw': len(r['raw_df']),
    }
    (diretorio / 'metadata.json').write_text(json.dumps(metadata_chunk, indent=2, ensure_ascii=False, default=str))
    return diretorio, metadata_chunk


# ══════════════════════════════════════════════════════════════════════════
# Consolidação (Seção 26) — concatena os N chunks baixados, valida
# integridade GLOBAL antes de qualquer métrica (Seção 27).
# ══════════════════════════════════════════════════════════════════════════

def consolidar_chunks(diretorios):
    """Lê raw.csv/temporal_audit.csv de cada diretório de chunk baixado
    e concatena. Falha explícita se algum diretório não tiver os dois
    arquivos — nunca segue com chunk ausente/incompleto silenciosamente
    (Seção 26)."""
    raws, temporais = [], []
    for d in diretorios:
        d = Path(d)
        caminho_raw, caminho_temporal = d / 'raw.csv', d / 'temporal_audit.csv'
        if not caminho_raw.exists() or not caminho_temporal.exists():
            raise RuntimeError(f"chunk incompleto em {d} — raw.csv/temporal_audit.csv ausente(s).")
        raws.append(pd.read_csv(caminho_raw))
        temporais.append(pd.read_csv(caminho_temporal))
    raw_df = pd.concat(raws, ignore_index=True) if raws else pd.DataFrame()
    temporal_audit_df = pd.concat(temporais, ignore_index=True) if temporais else pd.DataFrame()
    return raw_df, temporal_audit_df


def validar_integridade_global(raw_df, temporal_audit_df, sistemas=SISTEMAS,
                                ano_ini=ANO_INICIO_HINDCAST, ano_fim=ANO_FIM_HINDCAST):
    """Seção 27 — antes de qualquer métrica: 4 modelos, N origens por
    modelo, N combinações modelo×origem, N raw total, temporal audit
    OK, zero duplicatas, zero modelo faltante. Retorna
    (aprovado: bool, motivos: list[str])."""
    motivos = []
    n_origens_esperado = (ano_fim - ano_ini + 1) * 12
    n_modelo_origem_esperado = len(sistemas) * n_origens_esperado
    n_raw_esperado_total = sum(s.hindcast_members * n_origens_esperado * len(LEADS) for s in sistemas)
    n_temporal_esperado = len(sistemas) * n_origens_esperado * len(LEADS)

    if len(sistemas) != 4:
        motivos.append(f"esperados 4 sistemas configurados, recebido {len(sistemas)}")

    if raw_df.empty:
        motivos.append("raw_df vazio")
        return (len(motivos) == 0, motivos)

    modelos_presentes = set(zip(raw_df['centre'], raw_df['system_name']))
    modelos_esperados = {(s.centro, s.system_name) for s in sistemas}
    faltando = modelos_esperados - modelos_presentes
    if faltando:
        motivos.append(f"modelo(s) ausente(s) no raw consolidado: {sorted(faltando)}")

    n_modelo_origem_real = 0
    for sistema in sistemas:
        sub = raw_df[(raw_df['centre'] == sistema.centro) & (raw_df['system_name'] == sistema.system_name)]
        n_origens_modelo = sub['init_date'].nunique()
        n_modelo_origem_real += n_origens_modelo
        if n_origens_modelo != n_origens_esperado:
            motivos.append(f"{sistema.centro}/{sistema.system_name}: {n_origens_modelo} origens, "
                            f"esperado {n_origens_esperado}")
        n_raw_modelo_esperado = n_origens_esperado * sistema.hindcast_members * len(LEADS)
        if len(sub) != n_raw_modelo_esperado:
            motivos.append(f"{sistema.centro}/{sistema.system_name}: {len(sub)} linhas raw, "
                            f"esperado {n_raw_modelo_esperado}")

    if n_modelo_origem_real != n_modelo_origem_esperado:
        motivos.append(f"combinações modelo×origem: {n_modelo_origem_real}, esperado {n_modelo_origem_esperado}")

    if len(raw_df) != n_raw_esperado_total:
        motivos.append(f"raw total: {len(raw_df)} linhas, esperado {n_raw_esperado_total}")

    duplicatas = int(raw_df.duplicated(subset=['centre', 'system_name', 'init_date', 'lead', 'member']).sum())
    if duplicatas:
        motivos.append(f"{duplicatas} linha(s) duplicada(s) no raw consolidado")

    if len(temporal_audit_df) != n_temporal_esperado:
        motivos.append(f"temporal_audit: {len(temporal_audit_df)} linhas, esperado {n_temporal_esperado}")
    elif not temporal_audit_df.empty and \
            not temporal_audit_df['lead1_e_mes_nominal_da_inicializacao'].all():
        motivos.append("alguma linha do temporal_audit tem lead1_e_mes_nominal_da_inicializacao=False")

    return (len(motivos) == 0, motivos)


# ══════════════════════════════════════════════════════════════════════════
# Summary multi-modelo (Seção 6/9/10) — 1 linha por modelo×origem×lead,
# bias SEMPRE separado por modelo.
# ══════════════════════════════════════════════════════════════════════════

def construir_ens_df_por_modelo(raw_df):
    """1 linha por (centre, system_name, system_code, init_date, lead)
    com estatísticas do ensemble RAW — groupby ÚNICO sobre o raw
    completo (eficiente em escala FULL: 207.360 linhas -> 6.912, uma só
    vez), reaproveitando c3s_hindcast.py::estatisticas_ensemble. Mesma
    metodologia de c3s_multimodel_poc.py::construir_summary_modelo
    (Fase 2B.1), só reestruturada para não refiltrar o raw completo a
    cada linha de summary (inviável em escala 6.912 x 207.360)."""
    linhas = []
    chaves = ['centre', 'system_name', 'system_code', 'init_date', 'lead']
    for chave, g in raw_df.groupby(chaves):
        centre, system_name, system_code, init_date, lead = chave
        v = g['c3s_prec_mm'].to_numpy(dtype=float)
        est = hc.estatisticas_ensemble(v)
        linhas.append({
            'centre': centre, 'system_name': system_name, 'system_code': system_code,
            'init_date': init_date, 'target_month': g['target_month'].iloc[0], 'lead': int(lead),
            'n_members': len(v), 'ens_mean_raw': est['mean'], 'ens_median_raw': est['median'],
            'ens_sd_raw': float(np.std(v)),
        })
    return pd.DataFrame(linhas)


def construir_summary_multimodelo(raw_df, chirps_df, min_anos_treino=MIN_ANOS_TREINO):
    """1 linha por (modelo, origem, lead) — ensemble mean RAW/BC,
    climatologia/bias leakage-safe, probabilidades RAW/BC. Bias SEMPRE
    calculado SEPARADAMENTE por modelo (Seção 10 — nunca usar erro de
    um modelo para corrigir outro): filtra ens_df (já agregado, 1 linha
    por combinação) pelo MESMO (centre, system_name, lead) antes de
    chamar calib.bias_leakage_safe. `status_historico` (OK/
    SEM_HISTORICO_SUFICIENTE) reflete climatologia E bias com
    >= min_anos_treino, mesma convenção de
    c3s_hindcast_completo.py::construir_summary_e_calibrado — usada
    depois para filtrar a avaliação principal (Seção 12)."""
    if raw_df.empty:
        return pd.DataFrame()
    raw_df = _com_periods(raw_df)
    chirps_por_target = chirps_df[['target_month', 'chirps_prec_mm']].drop_duplicates('target_month')
    ens_df = construir_ens_df_por_modelo(raw_df)

    raw_por_grupo = {chave: g['c3s_prec_mm'].to_numpy(dtype=float)
                      for chave, g in raw_df.groupby(['centre', 'system_name', 'init_date', 'lead'])}
    ens_por_modelo_lead = {chave: sub for chave, sub in ens_df.groupby(['centre', 'system_name', 'lead'])}

    linhas = []
    for _, row in ens_df.iterrows():
        centre, system_name, system_code = row['centre'], row['system_name'], row['system_code']
        init_date, lead, target_month = row['init_date'], int(row['lead']), row['target_month']
        mes_cal = target_month.month

        clim = calib.climatologia_leakage_safe(chirps_por_target, init_date, mes_cal, min_anos_treino)

        ens_deste_modelo = ens_por_modelo_lead.get((centre, system_name, lead))
        bias = calib.bias_leakage_safe(ens_deste_modelo, chirps_por_target, init_date, mes_cal, lead,
                                        min_anos_treino) if ens_deste_modelo is not None else \
            {'bias_mm': None, 'n': 0, 'status': calib.STATUS_SEM_HISTORICO}

        chirps_obs = chirps_por_target[chirps_por_target['target_month'] == target_month]
        chirps_mm = float(chirps_obs['chirps_prec_mm'].iloc[0]) if not chirps_obs.empty else None

        ens_mean_bc = (round(row['ens_mean_raw'] - bias['bias_mm'], 3)
                       if bias['bias_mm'] is not None else None)

        v = raw_por_grupo.get((centre, system_name, init_date, lead), np.array([]))
        p33, p67 = clim.get('p33'), clim.get('p67')
        if p33 is not None and p67 is not None and len(v):
            pb_raw, pn_raw, pa_raw = hc.probabilidade_terciles(v, p33, p67)
        else:
            pb_raw = pn_raw = pa_raw = None
        if ens_mean_bc is not None and p33 is not None and p67 is not None and len(v):
            bc_vals = np.array([calib.aplicar_bias_a_membro(x, bias['bias_mm']) for x in v])
            pb_bc, pn_bc, pa_bc = hc.probabilidade_terciles(bc_vals, p33, p67)
        else:
            pb_bc = pn_bc = pa_bc = None

        status_historico = (calib.STATUS_OK if (clim['status'] == calib.STATUS_OK and
                                                  bias['status'] == calib.STATUS_OK)
                             else calib.STATUS_SEM_HISTORICO)

        linhas.append({
            'centre': centre, 'system_name': system_name, 'system_code': system_code,
            'init_date': init_date, 'target_month': target_month, 'target_year': target_month.year,
            'target_calendar_month': mes_cal, 'lead': lead, 'init_year': init_date.year,
            'n_members': row['n_members'], 'ens_mean_raw': row['ens_mean_raw'],
            'ens_median_raw': row['ens_median_raw'], 'ens_sd_raw': row['ens_sd_raw'],
            'chirps_prec_mm': chirps_mm,
            'climatological_mean': clim['mean'], 'climatological_median': clim['median'],
            'clim_p33': clim['p33'], 'clim_p67': clim['p67'], 'clim_n': clim['n'],
            'bias_training_n': bias['n'], 'bias_mm': bias['bias_mm'], 'ens_mean_bc': ens_mean_bc,
            'prob_below_raw': pb_raw, 'prob_normal_raw': pn_raw, 'prob_above_raw': pa_raw,
            'prob_below_bc': pb_bc, 'prob_normal_bc': pn_bc, 'prob_above_bc': pa_bc,
            'status_historico': status_historico,
            'evaluation_period': _periodo_avaliacao(init_date),
        })
    return pd.DataFrame(linhas).sort_values(['init_date', 'lead', 'centre']).reset_index(drop=True)


def filtrar_avaliacao_principal(summary_df, periodos=('development', 'temporal_validation')):
    """Seção 12 — só development+temporal_validation (nunca warm-up) e
    só linhas com histórico suficiente (climatologia E bias, nunca
    completado com futuro) — mesma convenção de
    c3s_hindcast_completo.py::filtrar_avaliacao, generalizada para N
    modelos."""
    if summary_df.empty:
        return summary_df
    return summary_df[summary_df['evaluation_period'].isin(periodos) &
                       (summary_df['status_historico'] == calib.STATUS_OK)].copy()


# ══════════════════════════════════════════════════════════════════════════
# Seção 12/13 — tabela wide (1 linha por origem×lead, 1 coluna por
# variante) e amostra comum (mesma amostra para CLIM/individual BC/MME
# BC, nunca amostras diferentes por variante).
# ══════════════════════════════════════════════════════════════════════════

def construir_avaliacao_wide(summary_df, mme_df, sistemas=SISTEMAS):
    """Pivota o summary (1 linha por modelo×origem×lead) para 1 linha
    por (origem, lead) com uma coluna por variante. `summary_df` já
    deve estar filtrado pela avaliação principal
    (filtrar_avaliacao_principal). A climatologia é IDÊNTICA entre
    modelos para a mesma (origem, lead) — depende só de CHIRPS/mês-
    alvo, nunca do modelo — então é tomada de qualquer linha (a
    primeira)."""
    if summary_df.empty:
        return pd.DataFrame()

    base = summary_df.groupby(['init_date', 'lead']).agg(
        target_month=('target_month', 'first'), target_calendar_month=('target_calendar_month', 'first'),
        target_year=('target_year', 'first'), init_year=('init_year', 'first'),
        chirps_prec_mm=('chirps_prec_mm', 'first'), climatological_mean=('climatological_mean', 'first'),
        clim_p33=('clim_p33', 'first'), clim_p67=('clim_p67', 'first'), clim_n=('clim_n', 'first'),
        evaluation_period=('evaluation_period', 'first'), n_modelos_presentes=('centre', 'nunique'),
    ).reset_index()

    for sistema in sistemas:
        sub = summary_df[(summary_df['centre'] == sistema.centro) &
                          (summary_df['system_name'] == sistema.system_name)][
            ['init_date', 'lead', 'ens_mean_raw', 'ens_mean_bc',
             'prob_below_raw', 'prob_normal_raw', 'prob_above_raw',
             'prob_below_bc', 'prob_normal_bc', 'prob_above_bc']]
        sub = sub.rename(columns={
            'ens_mean_raw': f'{sistema.centro}_raw', 'ens_mean_bc': f'{sistema.centro}_bc',
            'prob_below_raw': f'{sistema.centro}_prob_below_raw',
            'prob_normal_raw': f'{sistema.centro}_prob_normal_raw',
            'prob_above_raw': f'{sistema.centro}_prob_above_raw',
            'prob_below_bc': f'{sistema.centro}_prob_below_bc',
            'prob_normal_bc': f'{sistema.centro}_prob_normal_bc',
            'prob_above_bc': f'{sistema.centro}_prob_above_bc',
        })
        base = base.merge(sub, on=['init_date', 'lead'], how='left')

    if mme_df is not None and not mme_df.empty:
        mme_sub = mme_df[['init_date', 'lead', 'model_set_status', 'mme_mean_raw', 'mme_mean_bc',
                           'prob_below_raw', 'prob_normal_raw', 'prob_above_raw',
                           'prob_below_bc', 'prob_normal_bc', 'prob_above_bc']]
        mme_sub = mme_sub.rename(columns={
            'mme_mean_raw': 'MME_raw', 'mme_mean_bc': 'MME_bc',
            'prob_below_raw': 'MME_prob_below_raw', 'prob_normal_raw': 'MME_prob_normal_raw',
            'prob_above_raw': 'MME_prob_above_raw', 'prob_below_bc': 'MME_prob_below_bc',
            'prob_normal_bc': 'MME_prob_normal_bc', 'prob_above_bc': 'MME_prob_above_bc',
        })
        base = base.merge(mme_sub, on=['init_date', 'lead'], how='left')

    return base.sort_values(['init_date', 'lead']).reset_index(drop=True)


def filtrar_amostra_comum(avaliacao_wide, sistemas=SISTEMAS):
    """Seção 12/13 — a tabela comparativa principal (CLIM vs individual
    BC vs MME BC) usa SOMENTE linhas onde TODAS as variantes
    necessárias têm valor finito: climatologia, BC de cada um dos 4
    modelos, e MME_BC. Nunca comparar métricas calculadas sobre
    amostras temporais diferentes."""
    if avaliacao_wide.empty:
        return avaliacao_wide
    colunas_obrigatorias = ['chirps_prec_mm', 'climatological_mean'] + \
        [f'{s.centro}_bc' for s in sistemas] + ['MME_bc']
    mask = np.ones(len(avaliacao_wide), dtype=bool)
    for c in colunas_obrigatorias:
        if c not in avaliacao_wide.columns:
            return avaliacao_wide.iloc[0:0]
        mask &= np.isfinite(avaliacao_wide[c].astype(float))
    return avaliacao_wide[mask].reset_index(drop=True)


def coluna_variante(variante):
    """Mapeia um nome de variante (Seção 29: 'CLIM', 'ECMWF_RAW', ...,
    'MME_BC') para a coluna correspondente na tabela wide."""
    if variante == 'CLIM':
        return 'climatological_mean'
    if variante == 'MME_RAW':
        return 'MME_raw'
    if variante == 'MME_BC':
        return 'MME_bc'
    centro, tipo = variante.rsplit('_', 1)
    return f'{centro}_{tipo.lower()}'


# ══════════════════════════════════════════════════════════════════════════
# Seções 16/29-33 — métricas determinísticas por variante (nunca
# reimplementa fórmula: reaproveita hc.metricas_deterministicas/
# c3s_skill.mse/msess/hc.skill_vs_climatologia).
# ══════════════════════════════════════════════════════════════════════════

def metricas_variante(df, coluna_previsto, coluna_observado='chirps_prec_mm',
                       coluna_clim='climatological_mean'):
    """Generaliza c3s_skill.tabela_skill_deterministico (que só
    comparava RAW/BC) para 1 variante qualquer (Seção 29 — 11
    variantes: CLIM + 4 modelos x RAW/BC + MME RAW/BC), sem
    reimplementar nenhuma fórmula."""
    d = df.dropna(subset=[coluna_observado, coluna_clim, coluna_previsto])
    if d.empty:
        return {'n': 0, 'rmse': None, 'mae': None, 'bias': None, 'correlation': None,
                'msess': None, 'rmsess': None}
    m = skill.metricas_vs_clim(d, coluna_observado, coluna_previsto)
    mse_clim = skill.mse(d[coluna_observado], d[coluna_clim])
    mse_var = skill.mse(d[coluna_observado], d[coluna_previsto])
    rmse_clim = float(np.sqrt(mse_clim)) if mse_clim else None
    return {
        'n': m['n'], 'rmse': m['rmse'], 'mae': m['mae'], 'bias': m['bias'], 'correlation': m['corr'],
        'msess': skill.msess(mse_var, mse_clim),
        'rmsess': hc.skill_vs_climatologia(m['rmse'], rmse_clim) if rmse_clim else None,
    }


def tabela_skill_variantes(df, sistemas=SISTEMAS):
    """Uma linha por variante (Seção 29-32) — nunca ranqueia
    automaticamente, só reporta variant/n/rmse/mae/bias/correlation/
    msess/rmsess."""
    linhas = []
    for variante in mm.variantes_comparacao(sistemas):
        coluna = coluna_variante(variante)
        if df.empty or coluna not in df.columns:
            linhas.append({'variant': variante, 'n': 0, 'rmse': None, 'mae': None, 'bias': None,
                            'correlation': None, 'msess': None, 'rmsess': None})
            continue
        linhas.append({'variant': variante, **metricas_variante(df, coluna)})
    return pd.DataFrame(linhas)


def tabela_skill_by(df, coluna_grupo, sistemas=SISTEMAS):
    """Seção 30/31 — by_lead/by_month: mesma tabela de variantes,
    repetida por grupo."""
    if df.empty:
        return pd.DataFrame()
    linhas = []
    for valor_grupo, g in df.groupby(coluna_grupo):
        tab = tabela_skill_variantes(g, sistemas)
        tab.insert(0, coluna_grupo, valor_grupo)
        linhas.append(tab)
    return pd.concat(linhas, ignore_index=True).sort_values([coluna_grupo, 'variant']).reset_index(drop=True)


def tabela_skill_by_month_lead(df, sistemas=SISTEMAS):
    """Seção 32 — diagnóstico detalhado mês-calendário x lead."""
    if df.empty:
        return pd.DataFrame()
    linhas = []
    for (mes, lead), g in df.groupby(['target_calendar_month', 'lead']):
        tab = tabela_skill_variantes(g, sistemas)
        tab.insert(0, 'lead', lead)
        tab.insert(0, 'target_calendar_month', mes)
        linhas.append(tab)
    return pd.concat(linhas, ignore_index=True) \
        .sort_values(['target_calendar_month', 'lead', 'variant']).reset_index(drop=True)


def tabela_skill_operational_seasons(df, sistemas=SISTEMAS):
    """Seção 33 — mesmos blocos da Fase 2A.3 (ESTACOES_OPERACIONAIS),
    incluindo explicitamente set-fev como bloco prioritário."""
    if df.empty:
        return pd.DataFrame()
    linhas = []
    for nome, meses in ESTACOES_OPERACIONAIS.items():
        g = df[df['target_calendar_month'].isin(meses)]
        tab = tabela_skill_variantes(g, sistemas)
        tab.insert(0, 'bloco', nome)
        linhas.append(tab)
    g_prioritario = df[df['target_calendar_month'].isin(MESES_BLOCO_OPERACIONAL_PRIORITARIO)]
    tab_prioritario = tabela_skill_variantes(g_prioritario, sistemas)
    tab_prioritario.insert(0, 'bloco', NOME_BLOCO_OPERACIONAL_PRIORITARIO)
    linhas.append(tab_prioritario)
    return pd.concat(linhas, ignore_index=True).reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════
# Seção 17/34 — métricas probabilísticas por variante (nunca
# reimplementa fórmula: reaproveita hc.brier_score/brier_skill_score/
# rps_uma_previsao/rpss/c3s_skill.categoria_tercil). Tercis sempre
# leakage-safe (clim_p33/p67 já vêm de climatologia_leakage_safe).
# ══════════════════════════════════════════════════════════════════════════

def variantes_probabilisticas(sistemas=SISTEMAS):
    """CLIM não entra — a probabilidade climatológica é sempre
    1/3-1/3-1/3, já usada como referência dentro da própria métrica
    (mesmo precedente de c3s_skill.tabela_skill_probabilistico, Fase
    2A.3)."""
    return [v for v in mm.variantes_comparacao(sistemas) if v != 'CLIM']


def tabela_skill_probabilistico_variante(df, variante, coluna_observado='chirps_prec_mm',
                                          coluna_p33='clim_p33', coluna_p67='clim_p67'):
    centro, tipo = variante.rsplit('_', 1)
    tipo = tipo.lower()
    col_below, col_normal, col_above = (f'{centro}_prob_below_{tipo}', f'{centro}_prob_normal_{tipo}',
                                         f'{centro}_prob_above_{tipo}')
    cols = [coluna_observado, coluna_p33, coluna_p67, col_below, col_normal, col_above]
    if df.empty or any(c not in df.columns for c in cols):
        return {'variant': variante, 'n': 0}
    d = df.dropna(subset=cols)
    if d.empty:
        return {'variant': variante, 'n': 0}

    evento_abaixo = (d[coluna_observado] < d[coluna_p33]).astype(float).to_numpy()
    evento_acima = (d[coluna_observado] > d[coluna_p67]).astype(float).to_numpy()
    clim_prob = np.full(len(d), 1 / 3)
    bs_clim_abaixo = hc.brier_score(clim_prob, evento_abaixo)
    bs_clim_acima = hc.brier_score(clim_prob, evento_acima)

    tercil_obs = [skill.categoria_tercil(v, p33, p67) for v, p33, p67 in
                  zip(d[coluna_observado], d[coluna_p33], d[coluna_p67])]
    probs_clim_rps = [[1 / 3, 1 / 3, 1 / 3]] * len(d)

    bs_abaixo = hc.brier_score(d[col_below], evento_abaixo)
    bs_acima = hc.brier_score(d[col_above], evento_acima)
    probs_modelo_rps = list(zip(d[col_below], d[col_normal], d[col_above]))

    return {
        'variant': variante, 'n': len(d),
        'bs_abaixo': round(bs_abaixo, 4), 'bs_acima': round(bs_acima, 4),
        'bss_abaixo': hc.brier_skill_score(bs_abaixo, bs_clim_abaixo),
        'bss_acima': hc.brier_skill_score(bs_acima, bs_clim_acima),
        'rps': round(float(np.mean([hc.rps_uma_previsao(p, o)
                                     for p, o in zip(probs_modelo_rps, tercil_obs)])), 4),
        'rpss': hc.rpss(probs_modelo_rps, tercil_obs, probs_clim_rps),
    }


def tabela_skill_probabilistico_overall(df, sistemas=SISTEMAS):
    return pd.DataFrame([tabela_skill_probabilistico_variante(df, v)
                          for v in variantes_probabilisticas(sistemas)])


def tabela_skill_probabilistico_by(df, coluna_grupo, sistemas=SISTEMAS):
    if df.empty:
        return pd.DataFrame()
    linhas = []
    for valor_grupo, g in df.groupby(coluna_grupo):
        tab = tabela_skill_probabilistico_overall(g, sistemas)
        tab.insert(0, coluna_grupo, valor_grupo)
        linhas.append(tab)
    return pd.concat(linhas, ignore_index=True).sort_values([coluna_grupo, 'variant']).reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════
# Seção 14/35 — split development/temporal_validation.
# ══════════════════════════════════════════════════════════════════════════

def tabela_skill_temporal_validation(avaliacao_df, sistemas=SISTEMAS, n_bootstrap=N_BOOTSTRAP,
                                      seed=SEED_BOOTSTRAP):
    """development (2003-2009) vs temporal_validation (2010-2016) —
    NUNCA renomeado 'confirmação independente' (bias/climatologia
    continuam em janela expansiva). Split fixo, nunca reajustado depois
    de ver resultado (Seção 14)."""
    periodos = {
        'development': avaliacao_df[avaliacao_df['evaluation_period'] == 'development'] if not
        avaliacao_df.empty else avaliacao_df,
        'temporal_validation': avaliacao_df[avaliacao_df['evaluation_period'] == 'temporal_validation'] if not
        avaliacao_df.empty else avaliacao_df,
    }
    linhas = []
    for nome_periodo, df_periodo in periodos.items():
        for variante in mm.variantes_comparacao(sistemas):
            coluna = coluna_variante(variante)
            if df_periodo.empty or coluna not in df_periodo.columns:
                linhas.append({'period': nome_periodo, 'variant': variante, 'n': 0, 'rmse': None,
                                'msess': None, 'ic95_inferior': None, 'ic95_superior': None,
                                'conclusivo': False})
                continue
            m = metricas_variante(df_periodo, coluna)
            bs = skill.bootstrap_skill(df_periodo, 'init_year', 'chirps_prec_mm', 'climatological_mean',
                                        coluna, n_replicacoes=n_bootstrap, seed=seed)
            linhas.append({'period': nome_periodo, 'variant': variante, 'n': m['n'], 'rmse': m['rmse'],
                            'msess': bs['estimativa'], 'ic95_inferior': bs['ic95_inferior'],
                            'ic95_superior': bs['ic95_superior'], 'conclusivo': bs['conclusivo']})
    return pd.DataFrame(linhas)


# ══════════════════════════════════════════════════════════════════════════
# Seção 15/36 — bootstrap por init_year (mesma metodologia da Fase
# 2A.3: c3s_skill.bootstrap_skill, generalizada de RAW/BC para as 8
# variantes de modelo + MME RAW/BC).
# ══════════════════════════════════════════════════════════════════════════

def montar_bootstrap_multimodel(avaliacao_df, sistemas=SISTEMAS, n_bootstrap=N_BOOTSTRAP,
                                 seed=SEED_BOOTSTRAP):
    """Inclui pelo menos os 4 *_BC + MME_BC (Seção 36); RAW também
    incluído como diagnóstico (Seção 13)."""
    periodos = {
        'total': avaliacao_df,
        'development': avaliacao_df[avaliacao_df['evaluation_period'] == 'development'] if not
        avaliacao_df.empty else avaliacao_df,
        'temporal_validation': avaliacao_df[avaliacao_df['evaluation_period'] == 'temporal_validation'] if not
        avaliacao_df.empty else avaliacao_df,
    }
    variantes = [v for v in mm.variantes_comparacao(sistemas) if v != 'CLIM']
    linhas = []
    for nome_periodo, df_periodo in periodos.items():
        for variante in variantes:
            coluna = coluna_variante(variante)
            if df_periodo.empty or coluna not in df_periodo.columns:
                continue
            r = skill.bootstrap_skill(df_periodo, 'init_year', 'chirps_prec_mm', 'climatological_mean',
                                       coluna, n_replicacoes=n_bootstrap, seed=seed)
            linhas.append({
                'variant': variante, 'period': nome_periodo, 'skill': r['estimativa'],
                'ci_low': r['ic95_inferior'], 'ci_high': r['ic95_superior'], 'n': r['n_anos'],
                'conclusivo': r['conclusivo'],
            })
    return pd.DataFrame(linhas)


# ══════════════════════════════════════════════════════════════════════════
# Seção 37/38 — comparação pareada MME_BC vs ECMWF_BC / vs cada modelo
# BC, sempre na MESMA amostra (avaliacao_df já filtrada pela amostra
# comum).
# ══════════════════════════════════════════════════════════════════════════

def _bootstrap_diferenca_pareada(df, coluna_ano, coluna_delta, n_replicacoes=N_BOOTSTRAP, seed=SEED_BOOTSTRAP):
    """Bootstrap por init_year da MÉDIA de uma diferença pareada
    (delta_mse = erro_quadrático_MME_BC - erro_quadrático_<modelo>_BC
    por forecast) — mesma metodologia de reamostragem por ano/seed/
    IC95% de c3s_skill.bootstrap_skill, aplicada à estatística 'média
    da diferença' (a diferença pareada já É a comparação, não precisa
    de uma climatologia de referência separada)."""
    d = df.dropna(subset=[coluna_delta])
    anos = np.sort(d[coluna_ano].unique())
    if len(anos) == 0:
        return {'n_anos': 0, 'estimativa': None, 'ic95_inferior': None, 'ic95_superior': None,
                'conclusivo': False, 'n_replicacoes': n_replicacoes, 'seed': seed}
    estimativa = float(d[coluna_delta].mean())
    rng = np.random.RandomState(seed)
    por_ano = {ano: d[d[coluna_ano] == ano] for ano in anos}
    replicas = []
    for _ in range(n_replicacoes):
        anos_amostrados = rng.choice(anos, size=len(anos), replace=True)
        amostra = pd.concat([por_ano[a] for a in anos_amostrados], ignore_index=True)
        replicas.append(float(amostra[coluna_delta].mean()))
    ic_inf, ic_sup = np.percentile(replicas, [2.5, 97.5])
    conclusivo = not (ic_inf <= 0 <= ic_sup)
    return {'n_anos': len(anos), 'estimativa': round(estimativa, 4),
            'ic95_inferior': round(float(ic_inf), 4), 'ic95_superior': round(float(ic_sup), 4),
            'conclusivo': bool(conclusivo), 'n_replicacoes': n_replicacoes, 'seed': seed}


def paired_mme_vs_ecmwf(avaliacao_df):
    """delta_mse = MSE_MME_BC - MSE_ECMWF_BC por forecast (erro
    quadrático individual, mesma amostra). delta<0 favorece MME —
    nunca transformado automaticamente em 'vencedor' (Seção 37)."""
    colunas = ['init_date', 'lead', 'init_year', 'se_mme_bc', 'se_ecmwf_bc', 'delta_mse']
    if avaliacao_df.empty or 'MME_bc' not in avaliacao_df.columns or 'ECMWF_bc' not in avaliacao_df.columns:
        return pd.DataFrame(columns=colunas)
    d = avaliacao_df.dropna(subset=['chirps_prec_mm', 'MME_bc', 'ECMWF_bc']).copy()
    if d.empty:
        return pd.DataFrame(columns=colunas)
    d['se_mme_bc'] = (d['MME_bc'] - d['chirps_prec_mm']) ** 2
    d['se_ecmwf_bc'] = (d['ECMWF_bc'] - d['chirps_prec_mm']) ** 2
    d['delta_mse'] = d['se_mme_bc'] - d['se_ecmwf_bc']
    return d[colunas].sort_values(['init_date', 'lead']).reset_index(drop=True)


def bootstrap_paired_mme_vs_ecmwf(paired_df, n_bootstrap=N_BOOTSTRAP, seed=SEED_BOOTSTRAP):
    r = _bootstrap_diferenca_pareada(paired_df, 'init_year', 'delta_mse', n_bootstrap, seed)
    return {'comparacao': 'MME_BC_vs_ECMWF_BC', **r}


def paired_mme_vs_models(avaliacao_df, sistemas=SISTEMAS):
    """MME_BC vs CADA modelo BC, sempre na MESMA amostra (Seção 38)."""
    colunas = ['modelo', 'init_date', 'lead', 'init_year', 'se_mme_bc', 'se_modelo_bc', 'delta_mse']
    linhas = []
    for sistema in sistemas:
        coluna_modelo = f'{sistema.centro}_bc'
        if avaliacao_df.empty or coluna_modelo not in avaliacao_df.columns or \
                'MME_bc' not in avaliacao_df.columns:
            continue
        d = avaliacao_df.dropna(subset=['chirps_prec_mm', 'MME_bc', coluna_modelo]).copy()
        if d.empty:
            continue
        d['modelo'] = sistema.centro
        d['se_mme_bc'] = (d['MME_bc'] - d['chirps_prec_mm']) ** 2
        d['se_modelo_bc'] = (d[coluna_modelo] - d['chirps_prec_mm']) ** 2
        d['delta_mse'] = d['se_mme_bc'] - d['se_modelo_bc']
        linhas.append(d[colunas])
    if not linhas:
        return pd.DataFrame(columns=colunas)
    return pd.concat(linhas, ignore_index=True).sort_values(['modelo', 'init_date', 'lead']).reset_index(drop=True)


def bootstrap_paired_mme_vs_models(paired_models_df, sistemas=SISTEMAS, n_bootstrap=N_BOOTSTRAP,
                                    seed=SEED_BOOTSTRAP):
    linhas = []
    for sistema in sistemas:
        if paired_models_df.empty:
            continue
        sub = paired_models_df[paired_models_df['modelo'] == sistema.centro]
        if sub.empty:
            continue
        r = _bootstrap_diferenca_pareada(sub, 'init_year', 'delta_mse', n_bootstrap, seed)
        linhas.append({'comparacao': f'MME_BC_vs_{sistema.centro}_BC', **r})
    return pd.DataFrame(linhas)


# ══════════════════════════════════════════════════════════════════════════
# Seção 39 — auditoria de leakage por modelo (reamostragem
# INDEPENDENTE do predicado usado em construir_summary_multimodelo,
# nunca reaproveita o resultado do pipeline — audita de verdade).
# ══════════════════════════════════════════════════════════════════════════

_COLUNAS_LEAKAGE = ['centre', 'system_name', 'init_date', 'target_month',
                     'max_obs_date_used_climatology', 'max_init_date_used_bias',
                     'max_target_month_used_bias', 'clim_n', 'bias_training_n', 'leakage_status']


def construir_leakage_audit_multimodelo(summary_df, ens_df, chirps_df):
    if summary_df.empty:
        return pd.DataFrame(columns=_COLUNAS_LEAKAGE)
    chirps_por_target = chirps_df[['target_month', 'chirps_prec_mm']].drop_duplicates('target_month')
    linhas = []
    for _, row in summary_df.iterrows():
        centre, system_name = row['centre'], row['system_name']
        origem, mes_cal, lead = row['init_date'], row['target_calendar_month'], row['lead']

        sub_clim = chirps_por_target[(chirps_por_target['target_month'] < origem) &
                                      (chirps_por_target['target_month'].apply(lambda p: p.month) == mes_cal)]
        max_obs = sub_clim['target_month'].max() if not sub_clim.empty else None

        f = ens_df[(ens_df['centre'] == centre) & (ens_df['system_name'] == system_name) &
                    (ens_df['lead'] == lead) & (ens_df['init_date'] < origem) &
                    (ens_df['target_month'] < origem) &
                    (ens_df['target_month'].apply(lambda p: p.month) == mes_cal)]
        max_init_bias = f['init_date'].max() if not f.empty else None
        max_target_bias = f['target_month'].max() if not f.empty else None

        violou = False
        if max_obs is not None and not (max_obs < origem):
            violou = True
        if max_init_bias is not None and not (max_init_bias < origem):
            violou = True
        if max_target_bias is not None and not (max_target_bias < origem):
            violou = True

        linhas.append({
            'centre': centre, 'system_name': system_name, 'init_date': str(origem),
            'target_month': str(row['target_month']),
            'max_obs_date_used_climatology': str(max_obs) if max_obs is not None else None,
            'max_init_date_used_bias': str(max_init_bias) if max_init_bias is not None else None,
            'max_target_month_used_bias': str(max_target_bias) if max_target_bias is not None else None,
            'clim_n': row['clim_n'], 'bias_training_n': row['bias_training_n'],
            'leakage_status': 'VIOLACAO' if violou else 'OK',
        })
    return pd.DataFrame(linhas)


# ══════════════════════════════════════════════════════════════════════════
# Seção 37/42 — classificação objetiva de IC95% (nunca otimiza nada
# com base nisso).
# ══════════════════════════════════════════════════════════════════════════

def classificar_ic95(ic_inf, ic_sup):
    if ic_inf is None or ic_sup is None:
        return 'indefinido'
    if ic_inf > 0:
        return 'IC95% totalmente >0'
    if ic_sup < 0:
        return 'IC95% totalmente <0'
    return 'IC95% cruza zero'


# ══════════════════════════════════════════════════════════════════════════
# Orquestração — dry-run-plan (Seção 46), pilot (Seção 45), consolidação
# oficial (Seção 26).
# ══════════════════════════════════════════════════════════════════════════

def plano_execucao(modo='PILOT'):
    if modo == 'PILOT':
        ano_ini, ano_fim, tamanho = PILOT_ANO_INICIO, PILOT_ANO_FIM, PILOT_TAMANHO_BLOCO_ANOS
    else:
        ano_ini, ano_fim, tamanho = ANO_INICIO_HINDCAST, ANO_FIM_HINDCAST, TAMANHO_BLOCO_CHUNK_ANOS
    matriz = construir_matriz_chunks(SISTEMAS, ano_ini, ano_fim, tamanho)
    n_origens_por_modelo = (ano_fim - ano_ini + 1) * 12
    n_raw_esperado = sum(s.hindcast_members * n_origens_por_modelo * len(LEADS) for s in SISTEMAS)
    return {
        'modo': modo, 'periodo': f'{ano_ini}-{ano_fim}', 'n_chunks': len(matriz),
        'max_parallel': MAX_PARALLEL_CHUNKS, 'tamanho_bloco_anos': tamanho,
        'n_origens_por_modelo': n_origens_por_modelo,
        'n_modelo_origem': len(SISTEMAS) * n_origens_por_modelo,
        'n_raw_esperado_total': n_raw_esperado,
        'n_summary_esperado': len(SISTEMAS) * n_origens_por_modelo * len(LEADS),
        'n_mme_esperado': n_origens_por_modelo * len(LEADS),
        'n_temporal_audit_esperado': len(SISTEMAS) * n_origens_por_modelo * len(LEADS),
        'periodo_comum_hindcast': f'{ANO_INICIO_HINDCAST}-{ANO_FIM_HINDCAST}',
        'periodo_avaliacao_principal': f'{AVALIACAO_ANO_INICIO}-{AVALIACAO_ANO_FIM}',
        'n_avaliacao_principal_esperado': N_AVALIACAO_PRINCIPAL_ESPERADO_FULL if modo != 'PILOT' else None,
        'development': f'{DEVELOPMENT_ANO_INICIO}-{DEVELOPMENT_ANO_FIM}',
        'temporal_validation': f'{TEMPORAL_VALIDATION_ANO_INICIO}-{TEMPORAL_VALIDATION_ANO_FIM}',
        'min_anos_treino': MIN_ANOS_TREINO, 'municipio': MUNICIPIO, 'leads': LEADS,
        'variantes': VARIANTES, 'artifacts_esperados': ARTIFACT_FILENAMES,
        'matriz_chunks': matriz,
        'aviso': 'Infraestrutura Fase 2B.2 — dry-run nunca acessa o CDS. PILOT valida só matrix/artifact/'
                 'consolidação, NUNCA skill (Seção 45).' if modo == 'PILOT' else
                 'Execução OFICIAL 1993-2016 — todas as tabelas de skill/bootstrap/comparação pareada só '
                 'são conclusivas com os 16 chunks completos e a consolidação aprovada (Seção 27/28).',
    }


def imprimir_plano(plano):
    print(f"=== C3S Multi-Modelo Hindcast — DRY RUN PLAN — MODO: {plano['modo']} "
          "(nenhum acesso ao CDS) ===")
    for chave, valor in plano.items():
        if chave == 'matriz_chunks':
            print(f"  {chave}: {len(valor)} chunks")
            for c in valor:
                print(f"    - {c['centro']} {c['ano_ini']}-{c['ano_fim']}: {c['n_origens']} origens, "
                      f"{c['n_raw_esperado']} raw esperado, artifact={c['artifact_name']}")
        else:
            print(f"  {chave}: {valor}")


def rodar_consolidacao(raw_df, temporal_audit_df, sistemas=SISTEMAS, ano_ini=ANO_INICIO_HINDCAST,
                        ano_fim=ANO_FIM_HINDCAST, sleep_fn=time.sleep, n_bootstrap=N_BOOTSTRAP,
                        seed=SEED_BOOTSTRAP):
    """Job `consolidate-and-evaluate` (Seção 26): valida integridade
    global, busca CHIRPS, calibra cada modelo (bias separado), constrói
    MME, calcula métricas, roda bootstrap, monta comparação pareada. Se
    a integridade global reprovar, levanta explicitamente — a
    consolidação NUNCA produz conclusão científica sobre dado
    incompleto/corrompido (Seção 26).

    `n_bootstrap`/`seed` default para N_BOOTSTRAP/SEED_BOOTSTRAP (Seção
    15 — 2.000 réplicas, seed 42) em qualquer execução real (pilot ou
    oficial); só existem como parâmetro para permitir testes rápidos
    com poucas réplicas sobre dado sintético pequeno, nunca para uso em
    produção."""
    aprovado_integridade, motivos_integridade = validar_integridade_global(
        raw_df, temporal_audit_df, sistemas, ano_ini, ano_fim)
    if not aprovado_integridade:
        raise RuntimeError("integridade global reprovada (Seção 27) — consolidação não deve produzir "
                            "conclusão científica: " + '; '.join(motivos_integridade))

    origens_periods = raw_df['init_date'].apply(lambda s: pd.Period(s, 'M'))
    origens = sorted(set(zip(origens_periods.apply(lambda p: p.year), origens_periods.apply(lambda p: p.month))))
    target_ini, target_fim = intervalo_targets_necessario(origens, LEADS)
    print(f"\n=== buscando CHIRPS consolidado ({target_ini} a {target_fim}, em blocos anuais) ===")
    chirps_df = buscar_chirps_consolidado(target_ini, target_fim, sleep_fn=sleep_fn)
    print(f"  ✅ CHIRPS: {len(chirps_df)} meses válidos")

    raw_df_periods = _com_periods(raw_df)
    summary_df = construir_summary_multimodelo(raw_df_periods, chirps_df, MIN_ANOS_TREINO)
    modelos_configurados = [s.centro for s in sistemas]
    mme_df = mm.construir_mme_por_origem_lead(summary_df, modelos_configurados) if not summary_df.empty \
        else pd.DataFrame()

    ens_df = construir_ens_df_por_modelo(raw_df_periods)
    leakage_df = construir_leakage_audit_multimodelo(summary_df, ens_df, chirps_df)
    leakage_aprovado = leakage_df.empty or (leakage_df['leakage_status'] == 'OK').all()

    avaliacao_principal_summary = filtrar_avaliacao_principal(summary_df)
    avaliacao_wide = construir_avaliacao_wide(avaliacao_principal_summary, mme_df, sistemas)
    avaliacao_comum = filtrar_amostra_comum(avaliacao_wide, sistemas)

    tabelas_skill = {
        'overall': tabela_skill_variantes(avaliacao_comum, sistemas),
        'by_lead': tabela_skill_by(avaliacao_comum, 'lead', sistemas),
        'by_month': tabela_skill_by(avaliacao_comum, 'target_calendar_month', sistemas),
        'by_month_lead': tabela_skill_by_month_lead(avaliacao_comum, sistemas),
        'operational_seasons': tabela_skill_operational_seasons(avaliacao_comum, sistemas),
        'prob_overall': tabela_skill_probabilistico_overall(avaliacao_comum, sistemas),
        'prob_by_lead': tabela_skill_probabilistico_by(avaliacao_comum, 'lead', sistemas),
        'prob_by_month': tabela_skill_probabilistico_by(avaliacao_comum, 'target_calendar_month', sistemas),
        'temporal_validation': tabela_skill_temporal_validation(avaliacao_comum, sistemas,
                                                                  n_bootstrap=n_bootstrap, seed=seed),
    }
    bootstrap_df = montar_bootstrap_multimodel(avaliacao_comum, sistemas, n_bootstrap=n_bootstrap, seed=seed)
    paired_ecmwf_df = paired_mme_vs_ecmwf(avaliacao_comum)
    paired_models_df = paired_mme_vs_models(avaliacao_comum, sistemas)
    bootstrap_paired_ecmwf = bootstrap_paired_mme_vs_ecmwf(paired_ecmwf_df, n_bootstrap=n_bootstrap, seed=seed)
    bootstrap_paired_models = bootstrap_paired_mme_vs_models(paired_models_df, sistemas,
                                                               n_bootstrap=n_bootstrap, seed=seed)

    return {
        'raw_df': raw_df, 'summary_df': summary_df, 'mme_df': mme_df, 'temporal_audit_df': temporal_audit_df,
        'leakage_df': leakage_df, 'leakage_aprovado': bool(leakage_aprovado), 'chirps_df': chirps_df,
        'avaliacao_wide': avaliacao_wide, 'avaliacao_comum': avaliacao_comum,
        'tabelas_skill': tabelas_skill, 'bootstrap_df': bootstrap_df,
        'paired_ecmwf_df': paired_ecmwf_df, 'paired_models_df': paired_models_df,
        'bootstrap_paired_ecmwf': bootstrap_paired_ecmwf, 'bootstrap_paired_models': bootstrap_paired_models,
        'sistemas': sistemas, 'integridade_aprovada': aprovado_integridade,
        'motivos_integridade': motivos_integridade,
    }


def montar_metadata(resultado, modo='FULL'):
    r = resultado
    n_raw_esperado = sum(s.hindcast_members * N_ORIGENS_POR_MODELO_FULL * len(LEADS) for s in r['sistemas'])
    return {
        'execution_mode': f'{"FULL_MULTIMODEL" if modo == "FULL" else "PILOT_MULTIMODEL"}_'
                           f'{ANO_INICIO_HINDCAST}_{ANO_FIM_HINDCAST}',
        'modelos': [f'{s.centro}/{s.system_name}' for s in r['sistemas']],
        'system_codes': {s.centro: s.system_code for s in r['sistemas']},
        'membros': {s.centro: s.hindcast_members for s in r['sistemas']},
        'common_start': ANO_INICIO_HINDCAST, 'common_end': ANO_FIM_HINDCAST,
        'warmup': [WARMUP_ANO_INICIO, WARMUP_ANO_FIM],
        'evaluation_start': AVALIACAO_ANO_INICIO, 'evaluation_end': AVALIACAO_ANO_FIM,
        'development': [DEVELOPMENT_ANO_INICIO, DEVELOPMENT_ANO_FIM],
        'temporal_validation': [TEMPORAL_VALIDATION_ANO_INICIO, TEMPORAL_VALIDATION_ANO_FIM],
        'n_raw_expected': n_raw_esperado, 'n_raw_actual': len(r['raw_df']),
        'n_summary': len(r['summary_df']), 'n_mme': len(r['mme_df']),
        'n_evaluation': len(r['avaliacao_comum']), 'n_chirps_months': len(r['chirps_df']),
        'leakage_status': 'OK' if r['leakage_aprovado'] else 'VIOLACAO',
        'bootstrap': {'n_replicacoes': N_BOOTSTRAP, 'seed': SEED_BOOTSTRAP, 'unidade_reamostragem': 'init_year'},
        'equal_model_weighting': True,
        'paired_bootstrap_mme_vs_ecmwf': r['bootstrap_paired_ecmwf'],
        'paired_bootstrap_mme_vs_models': (r['bootstrap_paired_models'].to_dict('records')
                                            if not r['bootstrap_paired_models'].empty else []),
        'data_execucao': datetime.now(timezone.utc).isoformat(),
        'nota': 'Nenhum resultado desta fase promove nenhum sistema/MME para o dashboard operacional sem '
                'revisão científica humana (Seção 43).',
    }


def gerar_relatorio_markdown(resultado, modo='FULL'):
    r = resultado
    linhas = ["# Hindcast Multi-Modelo C3S — São Bento do Tocantins — Fase 2B.2", "",
              f"- Modo: {modo}", f"- Período comum de hindcast: {ANO_INICIO_HINDCAST}-{ANO_FIM_HINDCAST}",
              f"- Avaliação principal: {AVALIACAO_ANO_INICIO}-{AVALIACAO_ANO_FIM}",
              f"- Development: {DEVELOPMENT_ANO_INICIO}-{DEVELOPMENT_ANO_FIM} / "
              f"Temporal validation: {TEMPORAL_VALIDATION_ANO_INICIO}-{TEMPORAL_VALIDATION_ANO_FIM}",
              f"- Linhas raw: {len(r['raw_df'])}", f"- Linhas summary: {len(r['summary_df'])}",
              f"- Linhas MME: {len(r['mme_df'])}",
              f"- Forecasts na avaliação principal (amostra comum a todas as variantes): "
              f"{len(r['avaliacao_comum'])}",
              f"- Auditoria de leakage: {'✅ APROVADA' if r['leakage_aprovado'] else '❌ REPROVADA'}",
              "", "## Skill overall (vs. climatologia)", "",
              r['tabelas_skill']['overall'].to_string(index=False)
              if not r['tabelas_skill']['overall'].empty else "(vazio)"]

    bpe = r.get('bootstrap_paired_ecmwf') or {}
    if bpe.get('estimativa') is not None:
        ic = classificar_ic95(bpe['ic95_inferior'], bpe['ic95_superior'])
        linhas += ["", "## MME_BC vs ECMWF_BC — comparação pareada (Seção 37)", "",
                   f"- delta_mse médio: {bpe['estimativa']}",
                   f"- IC95%: [{bpe['ic95_inferior']}, {bpe['ic95_superior']}] — {ic}",
                   "- delta<0 favorece MME. Interpretação automática limitada aos termos objetivos acima "
                   "— nenhuma otimização feita com base nisso."]

    linhas += ["", "## Fatos objetivos — nenhum vencedor selecionado automaticamente (Seção 42)", "",
               "Ver skill_multimodel_by_lead.csv (H1-H6), skill_multimodel_operational_seasons.csv "
               "(bloco SET_FEV_prioritario), skill_multimodel_probabilistic_overall.csv, "
               "skill_multimodel_temporal_validation.csv (development vs temporal_validation), "
               "bootstrap_multimodel_skill.csv e paired_mme_vs_ecmwf.csv/paired_mme_vs_models.csv."]

    linhas += ["", "---", "",
               "NÃO promover nenhum resultado desta fase para o dashboard operacional sem revisão "
               "científica humana (Seção 43)."]
    return '\n'.join(linhas) + '\n'


def escrever_saidas(resultado, modo='FULL'):
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    r = resultado

    r['raw_df'].to_csv(ARTIFACTS_DIR / 'c3s_multimodel_raw.csv', index=False)
    r['summary_df'].to_csv(ARTIFACTS_DIR / 'c3s_multimodel_summary.csv', index=False)
    r['mme_df'].to_csv(ARTIFACTS_DIR / 'c3s_multimodel_mme.csv', index=False)
    r['temporal_audit_df'].to_csv(ARTIFACTS_DIR / 'c3s_multimodel_temporal_audit.csv', index=False)
    r['leakage_df'].to_csv(ARTIFACTS_DIR / 'c3s_multimodel_leakage_audit.csv', index=False)
    r['chirps_df'].to_csv(ARTIFACTS_DIR / 'chirps_sao_bento_multimodel_targets.csv', index=False)

    ts = r['tabelas_skill']
    ts['overall'].to_csv(ARTIFACTS_DIR / 'skill_multimodel_overall.csv', index=False)
    ts['by_lead'].to_csv(ARTIFACTS_DIR / 'skill_multimodel_by_lead.csv', index=False)
    ts['by_month'].to_csv(ARTIFACTS_DIR / 'skill_multimodel_by_month.csv', index=False)
    ts['by_month_lead'].to_csv(ARTIFACTS_DIR / 'skill_multimodel_by_month_lead.csv', index=False)
    ts['operational_seasons'].to_csv(ARTIFACTS_DIR / 'skill_multimodel_operational_seasons.csv', index=False)
    ts['prob_overall'].to_csv(ARTIFACTS_DIR / 'skill_multimodel_probabilistic_overall.csv', index=False)
    ts['prob_by_lead'].to_csv(ARTIFACTS_DIR / 'skill_multimodel_probabilistic_by_lead.csv', index=False)
    ts['prob_by_month'].to_csv(ARTIFACTS_DIR / 'skill_multimodel_probabilistic_by_month.csv', index=False)
    ts['temporal_validation'].to_csv(ARTIFACTS_DIR / 'skill_multimodel_temporal_validation.csv', index=False)

    r['bootstrap_df'].to_csv(ARTIFACTS_DIR / 'bootstrap_multimodel_skill.csv', index=False)
    r['paired_ecmwf_df'].to_csv(ARTIFACTS_DIR / 'paired_mme_vs_ecmwf.csv', index=False)
    r['paired_models_df'].to_csv(ARTIFACTS_DIR / 'paired_mme_vs_models.csv', index=False)

    metadata = montar_metadata(r, modo)
    (ARTIFACTS_DIR / 'metadata.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False, default=str))

    relatorio = gerar_relatorio_markdown(r, modo)
    (ARTIFACTS_DIR / 'RELATORIO.md').write_text(relatorio)

    for nome in ARTIFACT_FILENAMES:
        print(f"  ✅ artifacts/c3s_multimodel_hindcast/{nome}")
    return metadata, relatorio


# ══════════════════════════════════════════════════════════════════════════
# Seção 45 — fail-fast do PILOT (só infraestrutura, nunca skill).
# ══════════════════════════════════════════════════════════════════════════

def validar_pilot_multimodel_aprovado(resultado, sistemas=SISTEMAS, ano_ini=PILOT_ANO_INICIO,
                                       ano_fim=PILOT_ANO_FIM):
    """O pilot pode legitimamente não ter os 10 anos de histórico de
    bias — avaliação principal pode ficar vazia, e isso NÃO reprova o
    pilot de infraestrutura (Seção 45: matrix/artifact upload/download/
    consolidação, nunca skill)."""
    r = resultado
    motivos = []
    aprovado_integ, motivos_integ = validar_integridade_global(r['raw_df'], r['temporal_audit_df'], sistemas,
                                                                 ano_ini, ano_fim)
    if not aprovado_integ:
        motivos += [f"integridade: {m}" for m in motivos_integ]
    if not r['leakage_aprovado']:
        motivos.append("auditoria de leakage reprovada")
    if r['mme_df'] is None:
        motivos.append("MME não foi construído")
    return (len(motivos) == 0, motivos)


# ══════════════════════════════════════════════════════════════════════════
# Seção 27/28 — fail-fast do HINDCAST MULTI-MODELO COMPLETO OFICIAL.
# ══════════════════════════════════════════════════════════════════════════

TABELAS_SKILL_OBRIGATORIAS = ['overall', 'by_lead', 'by_month', 'by_month_lead', 'operational_seasons',
                               'prob_overall', 'prob_by_lead', 'temporal_validation']


def validar_full_multimodel_aprovado(resultado, sistemas=SISTEMAS):
    r = resultado
    motivos = []
    if not r['integridade_aprovada']:
        motivos += [f"integridade global: {m}" for m in r['motivos_integridade']]
    if not r['leakage_aprovado']:
        motivos.append("auditoria de leakage reprovada")

    mme_df = r['mme_df']
    if len(mme_df) != N_MME_ESPERADO_FULL:
        motivos.append(f"MME: {len(mme_df)} linhas, esperado {N_MME_ESPERADO_FULL}")
    elif not mme_df.empty:
        n_status_ok = int((mme_df['model_set_status'] == mm.MODELO_COMPLETO_STATUS).sum())
        if n_status_ok != N_MME_ESPERADO_FULL:
            motivos.append(f"model_set_status=OK em {n_status_ok}/{N_MME_ESPERADO_FULL}, esperado "
                            f"{N_MME_ESPERADO_FULL} (Seção 20/27 — modelo faltante no FULL reprova)")

    avaliacao_comum = r['avaliacao_comum']
    if len(avaliacao_comum) != N_AVALIACAO_PRINCIPAL_ESPERADO_FULL:
        motivos.append(f"avaliação principal: {len(avaliacao_comum)} forecasts, esperado "
                        f"{N_AVALIACAO_PRINCIPAL_ESPERADO_FULL} (Seção 12/28)")
    elif not avaliacao_comum.empty:
        n_com_obs = int(np.isfinite(avaliacao_comum['chirps_prec_mm'].astype(float)).sum())
        if n_com_obs != len(avaliacao_comum):
            motivos.append(f"cobertura observacional: {n_com_obs}/{len(avaliacao_comum)} com CHIRPS finito "
                            f"(Seção 28)")

    for nome in TABELAS_SKILL_OBRIGATORIAS:
        tabela = r['tabelas_skill'].get(nome)
        if tabela is None or tabela.empty:
            motivos.append(f"tabela de skill obrigatória vazia: {nome}")

    if r['bootstrap_df'] is None or r['bootstrap_df'].empty:
        motivos.append("bootstrap_multimodel_skill vazio")

    return (len(motivos) == 0, motivos)


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--modo', choices=['PILOT', 'FULL'], default='PILOT')
    ap.add_argument('--dry-run-plan', action='store_true')
    ap.add_argument('--rodar-chunk', action='store_true', help='Baixa+valida 1 chunk (1 modelo x 1 bloco).')
    ap.add_argument('--centro')
    ap.add_argument('--system-name')
    ap.add_argument('--ano-ini', type=int)
    ap.add_argument('--ano-fim', type=int)
    ap.add_argument('--consolidar', action='store_true',
                     help='Lê chunks já baixados em --chunks-dir e roda a consolidação/avaliação.')
    ap.add_argument('--chunks-dir', default=None)
    args = ap.parse_args()

    if args.dry_run_plan or (not args.rodar_chunk and not args.consolidar):
        imprimir_plano(plano_execucao(args.modo))
        return

    if args.rodar_chunk:
        if not (args.centro and args.system_name and args.ano_ini and args.ano_fim):
            raise SystemExit("--rodar-chunk exige --centro --system-name --ano-ini --ano-fim")
        status = mp.dl.verificar_acesso(verbose=True)
        if not status['credenciais_configuradas']:
            raise SystemExit("CDS_API_KEY não configurado — FALHANDO. Nunca simulando resultado real.")
        if not status['pacote_cdsapi_instalado']:
            raise SystemExit("pacote cdsapi não instalado — rode `pip install -r requirements-c3s.txt`.")

        sistema = mcat.sistema_por_nome(args.centro, args.system_name)
        print(f"=== chunk {sistema.centro}/{sistema.system_name} {args.ano_ini}-{args.ano_fim} ===")
        resultado = rodar_chunk(sistema, args.ano_ini, args.ano_fim)
        diretorio, _ = escrever_saidas_chunk(resultado)
        aprovado, motivos = validar_chunk_aprovado(resultado)
        if not aprovado:
            print(f"\n❌ CHUNK REPROVADO ({diretorio}):")
            for m in motivos:
                print(f"  - {m}")
            sys.exit(1)
        print(f"\n✅ CHUNK APROVADO — {diretorio}")
        return

    if args.consolidar:
        chunks_dir = Path(args.chunks_dir) if args.chunks_dir else CHUNKS_DIR
        diretorios = sorted(p for p in chunks_dir.iterdir() if p.is_dir())
        raw_df, temporal_audit_df = consolidar_chunks(diretorios)
        ano_ini = PILOT_ANO_INICIO if args.modo == 'PILOT' else ANO_INICIO_HINDCAST
        ano_fim = PILOT_ANO_FIM if args.modo == 'PILOT' else ANO_FIM_HINDCAST
        resultado = rodar_consolidacao(raw_df, temporal_audit_df, SISTEMAS, ano_ini, ano_fim)
        escrever_saidas(resultado, args.modo)

        if args.modo == 'FULL':
            aprovado, motivos = validar_full_multimodel_aprovado(resultado)
            if not aprovado:
                print("\n❌ HINDCAST MULTI-MODELO COMPLETO REPROVADO — artifacts gravados para diagnóstico:")
                for m in motivos:
                    print(f"  - {m}")
                sys.exit(1)
            print(f"\n✅ HINDCAST MULTI-MODELO COMPLETO {ANO_INICIO_HINDCAST}-{ANO_FIM_HINDCAST} APROVADO — "
                  "integridade global confirmada, MME/leakage OK, avaliação principal completa — ver "
                  "artifacts/c3s_multimodel_hindcast/RELATORIO.md")
        else:
            aprovado, motivos = validar_pilot_multimodel_aprovado(resultado, ano_ini=ano_ini, ano_fim=ano_fim)
            if not aprovado:
                print("\n❌ PILOT REPROVADO (infraestrutura) — artifacts gravados para diagnóstico:")
                for m in motivos:
                    print(f"  - {m}")
                sys.exit(1)
            print("\n✅ PILOT APROVADO — infraestrutura validada (matrix/artifact upload/download/"
                  "consolidação). NÃO é conclusão de skill (Seção 45).")
        return


if __name__ == '__main__':
    main()
