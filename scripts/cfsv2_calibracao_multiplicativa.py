#!/usr/bin/env python3
"""
cfsv2_calibracao_multiplicativa.py — Fase 2C.3D: implementação do
Método 3.2 (correção MULTIPLICATIVA causal por lead × mês-alvo),
condicionada ao diagnóstico prévio já aprovado
(docs/nmme-fase2c3d-protocolo-multiplicativo-cfsv2.md) e ao Método 3.1
já mergeado (commit 7cf007b, `data/cfsv2_calibracao_2c3d/
aditiva_expanding.csv` — só LIDO aqui, nunca reescrito).

    razao = media(observacao_treino) / media(forecast_raw_treino)
    forecast_multiplicativo = forecast_raw * razao

Numerador e denominador vêm EXCLUSIVAMENTE do mesmo conjunto causal de
treinamento: a mesma lista de inicializações históricas (mesma
combinação lead × mês-alvo, estritamente anteriores à avaliada) que
alimenta `erros_historicos` no Método 3.1 — nunca as climatologias
expansíveis do 2C.3C (`climatologia_observada`/`climatologia_modelo_raw`,
que usam janelas de anos POTENCIALMENTE DIFERENTES entre observação e
modelo — a observada pode alcançar CHIRPS desde 1981, a do modelo só
alcança o início do CFSv2). Essas duas colunas continuam presentes na
tabela, mas usadas SOMENTE para o benchmark_anomalia_reconstruida
(idêntico ao Método 3.1, nunca recalculado de outra forma) — nunca para
a razão multiplicativa. `verificar_numerador_denominador_mesma_base`
confirma isso programaticamente.

PISO_DENOMINADOR_MM = 10.0 — fixado no diagnóstico prévio (gap vazio
[7,27mm, 16,62mm] no denominador, sem fragmentar nenhum mês em nenhum
lead). Abaixo do piso: status_multiplicativo='denominador_abaixo_do_piso',
excluído da avaliação principal — SEM fallback para a correção aditiva
(evitaria confundir o método). NENHUM teto de razão é aplicado no
método principal (razões altas de out/mai/nov são viés sistemático com
denominador seguro, não instabilidade — ver protocolo, Seção 5.2).

Roda com:
    python scripts/cfsv2_calibracao_multiplicativa.py --executar
    python scripts/cfsv2_calibracao_multiplicativa.py --gerar-relatorio
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
CAMINHO_TABELA_EXPANDING = DIRETORIO_SAIDA / 'multiplicativa_expanding.csv'
CAMINHO_TABELA_LOYO = DIRETORIO_SAIDA / 'multiplicativa_loyo.csv'
CAMINHO_METRICAS_JSON = DIRETORIO_SAIDA / 'metricas_multiplicativa_2c3d.json'
RELATORIO_PATH = ROOT / 'docs' / 'nmme-fase2c3d-correcao-multiplicativa-cfsv2.md'

# Mesmo warm-up do Método 3.1 — nunca um número diferente para o
# multiplicativo (regra fixa do protocolo revisado).
N_TREINO_MINIMO = a.N_TREINO_MINIMO

# Fixado no diagnóstico prévio (docs/nmme-fase2c3d-protocolo-
# multiplicativo-cfsv2.md, Seção 2) — gap vazio [7,2656mm, 16,6241mm],
# nenhum (lead,mês) fragmentado. NUNCA ajustado observando skill.
PISO_DENOMINADOR_MM = 10.0

STATUS_OK = 'ok'
STATUS_WARMUP = 'warmup_amostra_insuficiente'
STATUS_PISO = 'denominador_abaixo_do_piso'
STATUS_RAZAO_INVALIDA = 'erro_razao_invalida_nan_inf_ou_nao_positiva'
STATUS_FORECAST_INVALIDO = 'erro_forecast_multiplicativo_invalido_nan_inf_ou_negativo'

# Meses com denominador seguro (fora do gap excluído) — jun/jul/ago/set
# ficam de fora da população de inferência POR DESENHO (piso), nunca
# por recorte ad hoc feito depois de ver resultados.
MESES_ELEGIVEIS = (1, 2, 3, 4, 5, 10, 11, 12)
MESES_EXCLUIDOS_PELO_PISO = (6, 7, 8, 9)

# Meses com achado de viés sistemático mesmo acima do piso (protocolo,
# Seção 5.2) — diagnóstico obrigatório, nunca excluídos nem truncados.
MESES_DIAGNOSTICO_OBRIGATORIO = (5, 10, 11)

COLUNAS_TABELA_EXPANDING = [
    'init_date', 'target_month', 'target_ano', 'target_mes', 'lead',
    'forecast_raw', 'observacao', 'n_treino', 'periodo_treino_inicio',
    'periodo_treino_fim', 'media_prev_treino', 'media_obs_treino',
    'razao_multiplicativa', 'forecast_multiplicativo',
    'climatologia_observada', 'climatologia_modelo_raw',
    'benchmark_anomalia_reconstruida', 'status_multiplicativo',
]


# ══════════════════════════════════════════════════════════════════════════
# Núcleo — razão multiplicativa causal por lead × mês-alvo
# ══════════════════════════════════════════════════════════════════════════

def _avaliar_razao_e_forecast(forecast_raw, media_prev_treino, media_obs_treino):
    """Núcleo da regra de segurança (item 2/6 do pedido) — aplicado
    IDENTICAMENTE no expanding e no LOYO, nunca duplicado com lógica
    divergente. Retorna (razao, forecast_multiplicativo, status).
    Nenhum cap/truncamento de razão — só as quatro condições explícitas
    de parada (NaN, infinito, razão<=0, forecast<0)."""
    if media_prev_treino is None or media_prev_treino < PISO_DENOMINADOR_MM:
        return None, None, STATUS_PISO
    razao = media_obs_treino / media_prev_treino
    if not np.isfinite(razao) or razao <= 0:
        return None, None, STATUS_RAZAO_INVALIDA
    forecast_mult = float(forecast_raw * razao)
    if not np.isfinite(forecast_mult) or forecast_mult < 0:
        return float(razao), None, STATUS_FORECAST_INVALIDO
    return float(razao), forecast_mult, STATUS_OK


def construir_tabela_calibracao_multiplicativa(base_enriquecida):
    """Réplica estrutural de `a.construir_tabela_calibracao_aditiva`
    (expansão ordenada no tempo dentro de cada célula lead × mês-alvo,
    histórico só cresce DEPOIS de processar a linha — a própria
    inicialização nunca entra no seu próprio cálculo, por construção).
    Only difference: em vez de acumular `erros_historicos` (aditiva),
    acumula `forecasts_historicos` E `obs_historicos` em paralelo —
    media_prev_treino e media_obs_treino vêm SEMPRE do mesmo índice de
    posições dessas duas listas, logo dos MESMOS anos (ver
    `verificar_numerador_denominador_mesma_base`)."""
    media_membros = base_enriquecida.groupby(
        ['init_date', 'target_month', 'target_ano', 'target_mes', 'lead'], as_index=False
    ).agg(forecast_raw=('forecast_prec_mm', 'mean'),
          observacao=('obs_prec_mm', 'first'),
          climatologia_observada=('clim_media', 'first'),
          climatologia_modelo_raw=('clim_modelo_media', 'first'))

    linhas = []
    for (lead, mes_alvo), grupo in media_membros.groupby(['lead', 'target_mes']):
        grupo = grupo.assign(_p=pd.PeriodIndex(grupo['init_date'], freq='M')).sort_values('_p')
        forecasts_historicos, obs_historicos, inits_historicos = [], [], []
        for _, row in grupo.iterrows():
            n_treino = len(forecasts_historicos)
            if n_treino >= N_TREINO_MINIMO:
                media_prev_treino = float(np.mean(forecasts_historicos))
                media_obs_treino = float(np.mean(obs_historicos))
                periodo_inicio = inits_historicos[0]
                periodo_fim = inits_historicos[-1]
                razao, forecast_mult, status = _avaliar_razao_e_forecast(
                    row['forecast_raw'], media_prev_treino, media_obs_treino)
            else:
                media_prev_treino = None
                media_obs_treino = None
                periodo_inicio = None
                periodo_fim = None
                razao, forecast_mult, status = None, None, STATUS_WARMUP

            clim_obs = row['climatologia_observada']
            clim_mod = row['climatologia_modelo_raw']
            if pd.notna(clim_obs) and pd.notna(clim_mod):
                bench3 = float(clim_obs + (row['forecast_raw'] - clim_mod))
            else:
                bench3 = None

            linhas.append({
                'init_date': row['init_date'], 'target_month': row['target_month'],
                'target_ano': int(row['target_ano']), 'target_mes': int(row['target_mes']),
                'lead': int(lead), 'forecast_raw': float(row['forecast_raw']),
                'observacao': float(row['observacao']), 'n_treino': n_treino,
                'periodo_treino_inicio': periodo_inicio, 'periodo_treino_fim': periodo_fim,
                'media_prev_treino': media_prev_treino, 'media_obs_treino': media_obs_treino,
                'razao_multiplicativa': razao, 'forecast_multiplicativo': forecast_mult,
                'climatologia_observada': float(clim_obs) if pd.notna(clim_obs) else None,
                'climatologia_modelo_raw': float(clim_mod) if pd.notna(clim_mod) else None,
                'benchmark_anomalia_reconstruida': bench3,
                'status_multiplicativo': status,
            })

            # Histórico só cresce DEPOIS de processar a linha atual —
            # mesma garantia estrutural anti-leakage do Método 3.1.
            forecasts_historicos.append(float(row['forecast_raw']))
            obs_historicos.append(float(row['observacao']))
            inits_historicos.append(row['init_date'])

    tabela = pd.DataFrame(linhas)[COLUNAS_TABELA_EXPANDING]
    tabela = tabela.assign(_p=pd.PeriodIndex(tabela['init_date'], freq='M')).sort_values(
        ['lead', '_p']).drop(columns='_p').reset_index(drop=True)
    return tabela, media_membros


def verificar_numerador_denominador_mesma_base(tabela, media_membros):
    """Item 3 do pedido — verificação INDEPENDENTE (não só confiar na
    construção): para cada linha elegível, refiltra `media_membros`
    pela MESMA máscara causal (lead, mês-alvo, init_date estritamente
    anterior) usada na construção e recalcula média_prev/obs_treino a
    partir desse ÚNICO filtro — por definição, um único filtro produz
    numerador e denominador sobre o mesmo conjunto de linhas (mesmos
    anos). Compara contra os valores já gravados na tabela; qualquer
    divergência indicaria um bug onde as duas médias passaram a vir de
    listas desalinhadas."""
    problemas = []
    ok = tabela[tabela['status_multiplicativo'].isin((STATUS_OK, STATUS_RAZAO_INVALIDA,
                                                        STATUS_FORECAST_INVALIDO))]
    for _, row in ok.iterrows():
        avaliada_p = v._periodo(row['init_date'])
        mascara = ((media_membros['lead'] == row['lead'])
                   & (media_membros['target_mes'] == row['target_mes'])
                   & (pd.PeriodIndex(media_membros['init_date'], freq='M') < avaliada_p))
        historico = media_membros[mascara]
        if len(historico) != row['n_treino']:
            problemas.append(f"{row['init_date']} lead={row['lead']}: n_treino gravado="
                              f"{row['n_treino']}, recalculado independentemente={len(historico)}")
            continue
        media_prev_independente = float(historico['forecast_raw'].mean())
        media_obs_independente = float(historico['observacao'].mean())
        anos_do_filtro_unico = set(pd.PeriodIndex(historico['init_date'], freq='M').year.tolist())
        if abs(media_prev_independente - row['media_prev_treino']) > 1e-9:
            problemas.append(f"{row['init_date']} lead={row['lead']}: media_prev_treino gravado="
                              f"{row['media_prev_treino']}, recalculado={media_prev_independente}")
        if abs(media_obs_independente - row['media_obs_treino']) > 1e-9:
            problemas.append(f"{row['init_date']} lead={row['lead']}: media_obs_treino gravado="
                              f"{row['media_obs_treino']}, recalculado={media_obs_independente}")
        if len(anos_do_filtro_unico) != row['n_treino'] and row['n_treino'] > 0:
            # nada aqui além de uma verificação de sanidade — o filtro
            # único já garante por construção que ambos vêm dos mesmos
            # anos; isto só detectaria duplicata de ano no histórico.
            pass
    return {'ok': len(problemas) == 0, 'n_problemas': len(problemas), 'problemas': problemas[:20]}


def _verificar_nenhum_leakage_na_tabela_multiplicativa(tabela):
    """Mesma lógica de `a._verificar_nenhum_leakage_na_tabela`, com a
    coluna `status_multiplicativo` em vez de `status_calibracao` — por
    isso não reutilizada diretamente daquele módulo (nomes de coluna
    diferentes), mas a regra é idêntica."""
    problemas = []
    ok = tabela[tabela['status_multiplicativo'].isin((STATUS_OK, STATUS_RAZAO_INVALIDA,
                                                        STATUS_FORECAST_INVALIDO))]
    for _, row in ok.iterrows():
        if row['periodo_treino_fim'] is None:
            problemas.append(f"{row['init_date']} lead={row['lead']}: status elegível mas "
                              "periodo_treino_fim ausente")
            continue
        fim_p = v._periodo(row['periodo_treino_fim'])
        avaliada_p = v._periodo(row['init_date'])
        if not (fim_p < avaliada_p):
            problemas.append(f"{row['init_date']} lead={row['lead']}: periodo_treino_fim="
                              f"{row['periodo_treino_fim']} >= init_date avaliada")
    return {'ok': len(problemas) == 0, 'n_problemas': len(problemas), 'problemas': problemas[:20]}


def _verificar_piso_nao_fragmenta_mes_nenhum_lead(tabela):
    """Item 4/17 do pedido — STOP-ON-FAILURE se algum mês pós-warm-up
    tiver uma MISTURA de status 'ok'/'denominador_abaixo_do_piso' em
    qualquer lead (fragmentação) — o diagnóstico prévio confirmou um
    gap vazio sem fragmentação; se a contagem real divergir desse
    desenho sem explicação, para em vez de prosseguir silenciosamente."""
    pos_warmup = tabela[tabela['n_treino'] >= N_TREINO_MINIMO]
    meses_fragmentados = []
    meses_ok, meses_piso = set(), set()
    for mes, grupo in pos_warmup.groupby('target_mes'):
        status_unicos = set(grupo['status_multiplicativo'].unique())
        if status_unicos == {STATUS_OK}:
            meses_ok.add(int(mes))
        elif status_unicos == {STATUS_PISO}:
            meses_piso.add(int(mes))
        else:
            meses_fragmentados.append({'mes': int(mes), 'status_encontrados': sorted(status_unicos)})
    return {
        'ok': len(meses_fragmentados) == 0 and meses_ok == set(MESES_ELEGIVEIS)
        and meses_piso == set(MESES_EXCLUIDOS_PELO_PISO),
        'meses_fragmentados': meses_fragmentados,
        'meses_inteiramente_ok': sorted(meses_ok),
        'meses_inteiramente_piso': sorted(meses_piso),
        'esperado_meses_ok': list(MESES_ELEGIVEIS),
        'esperado_meses_piso': list(MESES_EXCLUIDOS_PELO_PISO),
    }


def _verificar_contagem_elegivel(tabela):
    """Item 4 do pedido — N elegível ~480 total / 80 por horizonte,
    DERIVADO programaticamente (nunca hardcoded 80): n_anos_elegiveis =
    total pós-warm-up / (12 meses × 6 leads); esperado_por_horizonte =
    len(MESES_ELEGIVEIS) × n_anos_elegiveis."""
    n_pos_warmup = int((tabela['n_treino'] >= N_TREINO_MINIMO).sum())
    denom = 12 * len(v.LEADS_ESPERADOS)
    n_anos_elegiveis = n_pos_warmup / denom if denom else 0
    esperado_por_horizonte = len(MESES_ELEGIVEIS) * n_anos_elegiveis
    contagem_real = {int(lead): int(((tabela['lead'] == lead)
                                      & (tabela['status_multiplicativo'] == STATUS_OK)).sum())
                      for lead in v.LEADS_ESPERADOS}
    ok = all(c == esperado_por_horizonte for c in contagem_real.values()) and n_anos_elegiveis == int(n_anos_elegiveis)
    return {'ok': bool(ok), 'n_pos_warmup_total': n_pos_warmup,
            'n_anos_elegiveis_derivado': n_anos_elegiveis,
            'esperado_por_horizonte': esperado_por_horizonte,
            'contagem_real_por_horizonte': contagem_real,
            'n_total_elegivel': int(sum(contagem_real.values()))}


# ══════════════════════════════════════════════════════════════════════════
# Comparação pareada com o Método 3.1 (item 5 do pedido) — nunca N
# diferentes comparados diretamente
# ══════════════════════════════════════════════════════════════════════════

def construir_tabela_aditiva_matched(tabela_aditiva, tabela_multiplicativa):
    """'aditiva_matched_multiplicativo_sample' — restringe a tabela
    aditiva JÁ APROVADA (lida, nunca reescrita) às chaves
    (init_date, lead) elegíveis do multiplicativo (status_multiplicativo
    ='ok'). Mantém todas as colunas originais da aditiva (inclusive
    status_calibracao, forecast_calibrado) para reaproveitar, sem
    alteração, `a.metricas_deterministicas_aditiva_por_horizonte` e
    `a.bootstrap_skills_aditiva_por_horizonte` — nunca uma segunda
    fórmula paralela para os mesmos skills."""
    chaves = tabela_multiplicativa[
        tabela_multiplicativa['status_multiplicativo'] == STATUS_OK
    ][['init_date', 'lead']].drop_duplicates()
    return tabela_aditiva.merge(chaves, on=['init_date', 'lead'], how='inner')


def construir_tabela_comparacao(tabela_multiplicativa, tabela_aditiva):
    """Tabela única usada por TODAS as métricas principais do
    multiplicativo (por horizonte, matriz mês×lead, diagnóstico de
    out/mai/nov) — cada linha tem, lado a lado, forecast_multiplicativo
    E forecast_calibrado_aditivo (Método 3.1) para a MESMA (init_date,
    lead), garantindo que `skill_multiplicativo_vs_aditivo` nunca
    compara amostras diferentes."""
    ok_mult = tabela_multiplicativa[
        tabela_multiplicativa['status_multiplicativo'] == STATUS_OK
    ].dropna(subset=['benchmark_anomalia_reconstruida'])
    aditivo_sel = tabela_aditiva[tabela_aditiva['status_calibracao'] == a.STATUS_OK][
        ['init_date', 'lead', 'forecast_calibrado']
    ].rename(columns={'forecast_calibrado': 'forecast_calibrado_aditivo'})
    comparacao = ok_mult.merge(aditivo_sel, on=['init_date', 'lead'], how='inner')
    return comparacao


# ══════════════════════════════════════════════════════════════════════════
# Métricas determinísticas + skills (itens 6-9 do pedido)
# ══════════════════════════════════════════════════════════════════════════

def _metricas_de_subconjunto_multiplicativa(sub_comparacao):
    """Núcleo compartilhado por TODAS as agregações do multiplicativo
    (por horizonte, matriz mês×lead, diagnóstico out/mai/nov) — nunca
    duas fórmulas paralelas. `sub_comparacao` tem que vir de
    `construir_tabela_comparacao` (precisa de forecast_calibrado_
    aditivo para skill_multiplicativo_vs_aditivo)."""
    n = len(sub_comparacao)
    if n == 0:
        return {'n': 0}
    resultado = a._calcular_skills_tres_benchmarks(
        sub_comparacao, 'forecast_multiplicativo', 'observacao', 'forecast_raw',
        'climatologia_observada', 'benchmark_anomalia_reconstruida')
    resultado['n'] = n
    resultado['amostra_suficiente'] = n >= v.AMOSTRA_MINIMA_ESTRATO
    resultado['razao_media'] = float(sub_comparacao['razao_multiplicativa'].mean())
    resultado['razao_mediana'] = float(sub_comparacao['razao_multiplicativa'].median())
    resultado['forecast_raw_medio'] = float(sub_comparacao['forecast_raw'].mean())
    resultado['forecast_multiplicativo_medio'] = float(sub_comparacao['forecast_multiplicativo'].mean())
    resultado['observado_medio'] = float(sub_comparacao['observacao'].mean())
    rmse_mult = resultado['rmse']
    rmse_adit = v._rmse(sub_comparacao['forecast_calibrado_aditivo'].values,
                         sub_comparacao['observacao'].values)
    resultado['rmse_aditivo_matched'] = rmse_adit
    resultado['skill_multiplicativo_vs_aditivo'] = v.rmsess(rmse_mult, rmse_adit)
    return resultado


def metricas_deterministicas_multiplicativa_por_horizonte(comparacao):
    resultado = {}
    for lead in v.LEADS_ESPERADOS:
        sub = comparacao[comparacao['lead'] == lead]
        m = _metricas_de_subconjunto_multiplicativa(sub)
        m['rotulo'] = v.ROTULO_HORIZONTE[lead]
        resultado[lead] = m
    return resultado


def matriz_mes_lead_multiplicativa(comparacao):
    """Item 13 do pedido — SOMENTE meses elegíveis (nunca jun-set, que
    saíram da população de inferência por desenho)."""
    matriz = {}
    for mes in MESES_ELEGIVEIS:
        matriz[mes] = {}
        for lead in v.LEADS_ESPERADOS:
            sub = comparacao[(comparacao['target_mes'] == mes) & (comparacao['lead'] == lead)]
            matriz[mes][lead] = _metricas_de_subconjunto_multiplicativa(sub)
    return matriz


def diagnostico_meses_especificos(comparacao, meses=MESES_DIAGNOSTICO_OBRIGATORIO):
    """Item 7 do pedido — maio/outubro/novembro NUNCA excluídos nem
    truncados: diagnóstico completo por lead, para decidir depois (não
    aqui, não pela magnitude isolada) se a razão alta corrige viés
    sistemático real ou sobrecorrige."""
    resultado = {}
    for mes in meses:
        resultado[mes] = {}
        for lead in v.LEADS_ESPERADOS:
            sub = comparacao[(comparacao['target_mes'] == mes) & (comparacao['lead'] == lead)]
            resultado[mes][lead] = _metricas_de_subconjunto_multiplicativa(sub)
    return resultado


def bootstrap_skills_multiplicativa_vs_aditiva_por_horizonte(comparacao, n_resamples=500,
                                                               seed=20261001):
    """Itens 8, 9 e 10 do pedido — bootstrap ÚNICO em blocos por
    target_ano: em cada reamostra, recalcula RMSE multiplicativo, RMSE
    bruto, RMSE climatologia, RMSE benchmark3 E RMSE aditivo matched —
    os MESMOS blocos alimentam todos os cinco, nunca ICs calculados
    separadamente e depois combinados. `skill_multiplicativo_vs_aditivo`
    é o teste PRINCIPAL para saber se o Método 3.2 acrescenta algo ao
    Método 3.1 (item 9)."""
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

            rmse_mult = v._rmse(amostra['forecast_multiplicativo'].values, amostra['observacao'].values)
            rmse_raw = v._rmse(amostra['forecast_raw'].values, amostra['observacao'].values)
            rmse_clim = v._rmse(amostra['climatologia_observada'].values, amostra['observacao'].values)
            rmse_bench3 = v._rmse(amostra['benchmark_anomalia_reconstruida'].values,
                                   amostra['observacao'].values)
            rmse_adit = v._rmse(amostra['forecast_calibrado_aditivo'].values, amostra['observacao'].values)

            s1 = v.rmsess(rmse_mult, rmse_raw)
            s2 = v.rmsess(rmse_mult, rmse_clim)
            s3 = v.rmsess(rmse_mult, rmse_bench3)
            s4 = v.rmsess(rmse_mult, rmse_adit)
            if s1 is not None:
                boot_raw.append(s1)
            if s2 is not None:
                boot_clim.append(s2)
            if s3 is not None:
                boot_anom.append(s3)
            if s4 is not None:
                boot_vs_aditivo.append(s4)

        rmse_mult_p = v._rmse(sub['forecast_multiplicativo'].values, sub['observacao'].values)
        rmse_raw_p = v._rmse(sub['forecast_raw'].values, sub['observacao'].values)
        rmse_clim_p = v._rmse(sub['climatologia_observada'].values, sub['observacao'].values)
        rmse_bench3_p = v._rmse(sub['benchmark_anomalia_reconstruida'].values, sub['observacao'].values)
        rmse_adit_p = v._rmse(sub['forecast_calibrado_aditivo'].values, sub['observacao'].values)

        resumo_raw = v._resumo_bootstrap(v.rmsess(rmse_mult_p, rmse_raw_p), boot_raw)
        resumo_clim = v._resumo_bootstrap(v.rmsess(rmse_mult_p, rmse_clim_p), boot_clim)
        resumo_anom = v._resumo_bootstrap(v.rmsess(rmse_mult_p, rmse_bench3_p), boot_anom)
        resumo_vs_aditivo = v._resumo_bootstrap(v.rmsess(rmse_mult_p, rmse_adit_p), boot_vs_aditivo)

        resultado[lead] = {
            'n': n, 'amostra_suficiente': True, 'n_anos_distintos': int(len(anos)),
            'n_resamples': n_resamples,
            'metodo': 'bootstrap em blocos por target_ano — multiplicativo, os três benchmarks E '
                      'o aditivo matched usam os MESMOS blocos sorteados em cada reamostra',
            'skill_vs_raw': resumo_raw,
            'skill_vs_raw_ic_classificacao': v._classificar_ic_relativo_a_zero(
                resumo_raw['ic95_lo'], resumo_raw['ic95_hi']),
            'RMSESS_climatologia': resumo_clim,
            'RMSESS_climatologia_ic_classificacao': v._classificar_ic_relativo_a_zero(
                resumo_clim['ic95_lo'], resumo_clim['ic95_hi']),
            'skill_vs_anomalia_reconstruida': resumo_anom,
            'skill_vs_anomalia_reconstruida_ic_classificacao': v._classificar_ic_relativo_a_zero(
                resumo_anom['ic95_lo'], resumo_anom['ic95_hi']),
            'skill_multiplicativo_vs_aditivo': resumo_vs_aditivo,
            'skill_multiplicativo_vs_aditivo_ic_classificacao': v._classificar_ic_relativo_a_zero(
                resumo_vs_aditivo['ic95_lo'], resumo_vs_aditivo['ic95_hi']),
            'nota': "Critério de aprovação (item 11): IC 95% de skill_vs_anomalia_reconstruida E "
                    "RMSESS_climatologia totalmente acima de zero, SIMULTANEAMENTE. "
                    "skill_multiplicativo_vs_aditivo é reportado sempre, mas NÃO decide por si só "
                    "a aprovação — se seu IC incluir zero, não há evidência de ganho "
                    "estatisticamente distinguível do multiplicativo sobre o aditivo nesta "
                    "amostra; o critério nunca é alterado depois de observar este resultado.",
        }
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# LOYO (item 14 do pedido) — mesma estrutura do Método 3.1
# ══════════════════════════════════════════════════════════════════════════

def construir_tabela_calibracao_multiplicativa_loyo(base_pareada, chirps_df):
    """Versão LOYO da razão multiplicativa — mesma regra do piso e das
    quatro condições de parada, treino = todos os outros anos (passado
    E futuro) da MESMA combinação lead × mês-alvo. Deliberadamente NÃO
    causal — só retrospectivo descritivo, nunca operacional."""
    base_loyo = v._enriquecer_com_climatologia_loyo(base_pareada, chirps_df)
    media_membros = base_loyo.groupby(
        ['init_date', 'target_month', 'target_ano', 'target_mes', 'lead'], as_index=False
    ).agg(forecast_raw=('forecast_prec_mm', 'mean'),
          observacao=('obs_prec_mm', 'first'),
          climatologia_loyo_observada=('clim_media', 'first'))

    linhas = []
    for (lead, mes_alvo), grupo in media_membros.groupby(['lead', 'target_mes']):
        for _, row in grupo.iterrows():
            outros = grupo[grupo['target_ano'] != row['target_ano']]
            n_treino = len(outros)
            if n_treino >= N_TREINO_MINIMO:
                media_prev_treino = float(outros['forecast_raw'].mean())
                media_obs_treino = float(outros['observacao'].mean())
                razao, forecast_mult, status = _avaliar_razao_e_forecast(
                    row['forecast_raw'], media_prev_treino, media_obs_treino)
            else:
                media_prev_treino, media_obs_treino = None, None
                razao, forecast_mult, status = None, None, STATUS_WARMUP

            # Climatologia PRÓPRIA do modelo bruto em desenho LOYO —
            # mesma combinação lead×mês-alvo, todos os outros anos.
            # Idêntica, por construção, a media_prev_treino quando
            # elegível (ambas vêm de `outros['forecast_raw'].mean()`) —
            # calculada sempre (mesmo em warm-up) só para o benchmark3.
            clim_modelo_raw_loyo = float(outros['forecast_raw'].mean()) if len(outros) > 0 else None
            clim_loyo = row['climatologia_loyo_observada']
            if clim_modelo_raw_loyo is not None and pd.notna(clim_loyo):
                bench3_loyo = float(clim_loyo + (row['forecast_raw'] - clim_modelo_raw_loyo))
            else:
                bench3_loyo = None

            linhas.append({
                'init_date': row['init_date'], 'target_month': row['target_month'],
                'target_ano': int(row['target_ano']), 'target_mes': int(row['target_mes']),
                'lead': int(lead), 'forecast_raw': float(row['forecast_raw']),
                'observacao': float(row['observacao']), 'n_treino': n_treino,
                'media_prev_treino': media_prev_treino, 'media_obs_treino': media_obs_treino,
                'razao_multiplicativa': razao, 'forecast_multiplicativo': forecast_mult,
                'climatologia_loyo_observada': float(clim_loyo) if pd.notna(clim_loyo) else None,
                'climatologia_modelo_raw_loyo': clim_modelo_raw_loyo,
                'benchmark_anomalia_reconstruida_loyo': bench3_loyo,
                'status_multiplicativo': status,
            })
    tabela = pd.DataFrame(linhas)
    tabela = tabela.assign(_p=pd.PeriodIndex(tabela['init_date'], freq='M')).sort_values(
        ['lead', '_p']).drop(columns='_p').reset_index(drop=True)
    return tabela


def construir_multiplicativa_loyo_matched_intersecao(tabela_expanding, tabela_loyo):
    """Item 14 do pedido — 'exigir exatamente os mesmos casos da versão
    expanding multiplicativa'. Se a elegibilidade (warm-up + piso)
    divergir entre expanding e LOYO para alguma chave, NÃO forçar a
    comparação sobre uma chave que o LOYO considera inelegível — a
    interseção explícita é construída e a diferença é documentada,
    nunca escondida."""
    chaves_expanding = set(map(tuple, tabela_expanding[
        tabela_expanding['status_multiplicativo'] == STATUS_OK
    ][['init_date', 'lead']].values.tolist()))
    chaves_loyo_ok = set(map(tuple, tabela_loyo[
        tabela_loyo['status_multiplicativo'] == STATUS_OK
    ][['init_date', 'lead']].values.tolist()))
    intersecao = chaves_expanding & chaves_loyo_ok
    diferenca = sorted(chaves_expanding - chaves_loyo_ok)

    chaves_df = pd.DataFrame(sorted(intersecao), columns=['init_date', 'lead'])
    matched = tabela_loyo.merge(chaves_df, on=['init_date', 'lead'], how='inner')
    relatorio_elegibilidade = {
        'n_elegivel_expanding': len(chaves_expanding),
        'n_elegivel_loyo_proprio': len(chaves_loyo_ok),
        'n_intersecao': len(intersecao),
        'n_diferenca_elegibilidade': len(diferenca),
        'exemplos_diferenca': [f'{d_}×H{l_}' for d_, l_ in diferenca[:20]],
        'nota': 'interseção explícita entre as chaves elegíveis do expanding e do LOYO — nunca '
                'forçada sobre uma chave que o LOYO considera inelegível (regra fixa do '
                'protocolo revisado, item 14).',
    }
    return matched, relatorio_elegibilidade


def metricas_deterministicas_multiplicativa_loyo_por_horizonte(tabela_loyo):
    """LOYO full (retrospectivo descritivo) — três benchmarks em
    desenho LOYO, sem comparação com o aditivo (fora do escopo desta
    atividade para o LOYO, item 14 só pede comparação com o expanding)."""
    resultado = {}
    for lead in v.LEADS_ESPERADOS:
        sub = tabela_loyo[(tabela_loyo['lead'] == lead)
                           & (tabela_loyo['status_multiplicativo'] == STATUS_OK)].dropna(
            subset=['benchmark_anomalia_reconstruida_loyo'])
        n = len(sub)
        if n == 0:
            resultado[lead] = {'n_elegivel': 0}
            continue
        base = a._calcular_skills_tres_benchmarks(
            sub, 'forecast_multiplicativo', 'observacao', 'forecast_raw',
            'climatologia_loyo_observada', 'benchmark_anomalia_reconstruida_loyo')
        base['razao_media'] = float(sub['razao_multiplicativa'].mean())
        base['razao_mediana'] = float(sub['razao_multiplicativa'].median())
        resultado[lead] = base
    return resultado


def comparar_expanding_vs_loyo_matched_multiplicativa(det_expanding, det_loyo_matched):
    """Comparação PRINCIPAL expanding × LOYO (item 14), mesma estrutura
    de `a.comparar_expanding_vs_loyo_matched` — mesmos casos, delta
    meramente descritivo, nunca teste de significância automático."""
    comparacao = {}
    for lead in v.LEADS_ESPERADOS:
        e = det_expanding.get(lead, {})
        m = det_loyo_matched.get(lead, {})
        deltas = {}
        for chave in ('skill_vs_raw', 'RMSESS_climatologia', 'skill_vs_anomalia_reconstruida'):
            ve, vm = e.get(chave), m.get(chave)
            deltas[f'delta_{chave}'] = float(vm - ve) if ve is not None and vm is not None else None
        comparacao[lead] = {
            'n_expanding': e.get('n', e.get('n_elegivel', 0)),
            'n_loyo_matched': m.get('n_elegivel', m.get('n', 0)),
            **deltas,
            'nota': 'mesmas chaves (init_date×lead) nos dois lados — ver '
                    'construir_multiplicativa_loyo_matched_intersecao para a elegibilidade.',
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
            checar(val, f'det[{lead}][{k}]')
    for lead, dic in boot.items():
        for k, val in dic.items():
            if isinstance(val, dict):
                for kk, vv in val.items():
                    checar(vv, f'boot[{lead}][{k}][{kk}]')
    return {'ok': len(problemas) == 0, 'campos_problema': problemas}


def executar_calibracao_multiplicativa(n_resamples_bootstrap=500):
    """Orquestra o Método 3.2 com STOP-ON-FAILURE explícito em cada
    condição do item 17 do pedido — nunca corrige silenciosamente."""
    auditoria = v.executar_auditoria()
    if not auditoria['auditoria_aprovada']:
        return ({'STOP_ON_FAILURE': True,
                 'motivo': 'auditoria da base RAW (2C.3C) reprovada'}, None, None)

    if not a.CAMINHO_TABELA_EXPANDING.exists():
        return ({'STOP_ON_FAILURE': True,
                 'motivo': f'{a.CAMINHO_TABELA_EXPANDING} (Método 3.1, aprovado) não encontrado — '
                           'não é possível construir a comparação pareada'}, None, None)
    tabela_aditiva = pd.read_csv(a.CAMINHO_TABELA_EXPANDING)

    df_raw = v.carregar_cfsv2_raw()
    chirps_df = v.carregar_chirps_v3_historico()
    base = v.construir_base_pareada(df_raw, chirps_df)
    if not v.validar_nenhum_mes_alvo_ausente(base):
        return ({'STOP_ON_FAILURE': True, 'motivo': 'pareamento com mês-alvo ausente'}, None, None)

    base_enriquecida = v._enriquecer_com_climatologia(base, chirps_df)
    tabela, media_membros = construir_tabela_calibracao_multiplicativa(base_enriquecida)

    n_esperado_total = v.N_INICIALIZACOES_ESPERADO * len(v.LEADS_ESPERADOS)
    if len(tabela) != n_esperado_total:
        return ({'STOP_ON_FAILURE': True,
                 'motivo': f'número inesperado de combinações init×lead: {len(tabela)}, '
                           f'esperado {n_esperado_total}'}, None, None)

    identidade = a.validar_identidade_benchmark3(tabela)
    if not identidade['identidade_ok']:
        return ({'STOP_ON_FAILURE': True,
                 'motivo': 'benchmark_anomalia_reconstruida não satisfaz a identidade algébrica',
                 'detalhe': identidade}, None, None)

    leakage = _verificar_nenhum_leakage_na_tabela_multiplicativa(tabela)
    if not leakage['ok']:
        return ({'STOP_ON_FAILURE': True, 'motivo': 'leakage detectado na tabela multiplicativa',
                 'detalhe': leakage}, None, None)

    verificacao_base_comum = verificar_numerador_denominador_mesma_base(tabela, media_membros)
    if not verificacao_base_comum['ok']:
        return ({'STOP_ON_FAILURE': True,
                 'motivo': 'numerador e denominador da razão NÃO vêm do mesmo conjunto causal '
                           'de anos históricos', 'detalhe': verificacao_base_comum}, None, None)

    n_razao_invalida = int((tabela['status_multiplicativo'] == STATUS_RAZAO_INVALIDA).sum())
    n_forecast_invalido = int((tabela['status_multiplicativo'] == STATUS_FORECAST_INVALIDO).sum())
    if n_razao_invalida > 0 or n_forecast_invalido > 0:
        return ({'STOP_ON_FAILURE': True,
                 'motivo': f'razão/forecast multiplicativo inválido detectado: '
                           f'{n_razao_invalida} razões NaN/inf/<=0, {n_forecast_invalido} '
                           'forecasts NaN/inf/negativos — nunca truncado silenciosamente'},
                None, None)

    n_piso_com_forecast = int((
        (tabela['status_multiplicativo'] == STATUS_PISO) & tabela['forecast_multiplicativo'].notna()
    ).sum())
    if n_piso_com_forecast > 0:
        return ({'STOP_ON_FAILURE': True,
                 'motivo': f'{n_piso_com_forecast} caso(s) abaixo do piso receberam previsão '
                           'multiplicativa — exclusão da avaliação principal violada'}, None, None)

    fragmentacao = _verificar_piso_nao_fragmenta_mes_nenhum_lead(tabela)
    if not fragmentacao['ok']:
        return ({'STOP_ON_FAILURE': True,
                 'motivo': 'piso fragmentou pelo menos um mês em pelo menos um lead — divergiu '
                           'do gap vazio confirmado no diagnóstico prévio sem explicação',
                 'detalhe': fragmentacao}, None, None)

    contagem = _verificar_contagem_elegivel(tabela)
    if not contagem['ok']:
        return ({'STOP_ON_FAILURE': True,
                 'motivo': 'contagem de elegíveis pós-piso divergiu do esperado derivado '
                           'programaticamente, sem explicação', 'detalhe': contagem}, None, None)

    comparacao = construir_tabela_comparacao(tabela, tabela_aditiva)
    n_ok_mult = int((tabela['status_multiplicativo'] == STATUS_OK).sum())
    if len(comparacao) != n_ok_mult:
        return ({'STOP_ON_FAILURE': True,
                 'motivo': f'amostra de aditivo matched diferente da amostra multiplicativa: '
                           f'multiplicativo elegível={n_ok_mult}, após merge com aditivo='
                           f'{len(comparacao)} — toda chave elegível do multiplicativo precisa '
                           'ter uma linha aditiva status_calibracao=\'ok\' correspondente'},
                None, None)

    det = metricas_deterministicas_multiplicativa_por_horizonte(comparacao)
    boot = bootstrap_skills_multiplicativa_vs_aditiva_por_horizonte(comparacao, n_resamples_bootstrap)
    matriz_mes_lead = matriz_mes_lead_multiplicativa(comparacao)
    diagnostico_especifico = diagnostico_meses_especificos(comparacao)

    nan_check = _verificar_nan_inf_inesperado(det, boot)
    if not nan_check['ok']:
        return ({'STOP_ON_FAILURE': True, 'motivo': 'NaN/Inf não explicado nos resultados',
                 'detalhe': nan_check}, None, None)

    for lead in v.LEADS_ESPERADOS:
        n_mult = det.get(lead, {}).get('n', 0)
        if n_mult != contagem['esperado_por_horizonte']:
            return ({'STOP_ON_FAILURE': True,
                     'motivo': f'n elegível em H{lead} ({n_mult}) difere do esperado por '
                               f'horizonte ({contagem["esperado_por_horizonte"]})'}, None, None)

    # LOYO — item 14
    tabela_loyo = construir_tabela_calibracao_multiplicativa_loyo(base, chirps_df)
    det_loyo_full = metricas_deterministicas_multiplicativa_loyo_por_horizonte(tabela_loyo)
    matched_loyo, elegibilidade_loyo = construir_multiplicativa_loyo_matched_intersecao(
        tabela, tabela_loyo)
    det_loyo_matched = metricas_deterministicas_multiplicativa_loyo_por_horizonte(matched_loyo)
    comparacao_loyo_matched = comparar_expanding_vs_loyo_matched_multiplicativa(det, det_loyo_matched)

    resultado = {
        'STOP_ON_FAILURE': False,
        'metodo': 'correcao_multiplicativa_causal_por_lead_x_mes_alvo',
        'n_treino_minimo': N_TREINO_MINIMO,
        'piso_denominador_mm': PISO_DENOMINADOR_MM,
        'identidade_benchmark3': identidade,
        'leakage_check': leakage,
        'verificacao_numerador_denominador_mesma_base': verificacao_base_comum,
        'verificacao_piso_nao_fragmenta_mes': fragmentacao,
        'verificacao_contagem_elegivel': contagem,
        'avaliacao_meses_com_denominador_seguro': {
            'meses_elegiveis': list(MESES_ELEGIVEIS),
            'meses_excluidos_por_piso': list(MESES_EXCLUIDOS_PELO_PISO),
            'nota': 'A avaliação principal (det/boot/matriz acima) é válida SOMENTE para os '
                    'meses elegíveis — jun-set foram excluídos da população de inferência POR '
                    'DESENHO (piso do denominador), nunca reportar isto como "desempenho anual" '
                    'do Método 3.2.',
        },
        'expanding_operational_simulation': {
            'rotulo': 'multiplicativa_expanding_operational_simulation',
            'n_total_elegivel': len(comparacao),
            'deterministico_por_horizonte': det,
            'intervalos_confianca_skills_por_horizonte': boot,
            'matriz_mes_lead_meses_elegiveis': matriz_mes_lead,
            'diagnostico_maio_outubro_novembro': diagnostico_especifico,
        },
        'loyo_retrospective': {
            'rotulo': 'multiplicativa_loyo_full_retrospective',
            'aviso': 'NÃO simula uso em tempo real — usa anos futuros no cálculo de média_prev/'
                     'obs_treino. Análise descritiva adicional, nunca operacional.',
            'deterministico_por_horizonte': det_loyo_full,
        },
        'loyo_matched_intersecao_elegibilidade': {
            'rotulo': 'multiplicativa_loyo_matched_intersecao',
            'elegibilidade': elegibilidade_loyo,
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
        resultado, tabela, tabela_loyo = executar_calibracao_multiplicativa()
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
        import cfsv2_relatorio_multiplicativa_2c3d as rel
        rel.gerar_e_escrever()
        return

    ap.print_help()


if __name__ == '__main__':
    main()
