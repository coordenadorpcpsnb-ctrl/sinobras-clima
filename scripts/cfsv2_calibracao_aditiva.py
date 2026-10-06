#!/usr/bin/env python3
"""
cfsv2_calibracao_aditiva.py — Fase 2C.3D: implementação do Método 3.1 do
protocolo (docs/nmme-fase2c3d-protocolo-calibracao-cfsv2.md) — correção
ADITIVA causal por lead × mês-alvo. ÚNICO método implementado nesta
atividade (nunca multiplicativa, quantile mapping, MOS ou calibração
probabilística — essas são fases futuras separadas, condicionadas à
aprovação deste método).

Completamente separado do sistema operacional e da Fase 2C.3C — nunca
altera dashboard, SARIMAX, XGBoost, pipeline operacional, série de
produção, dados RAW do CFSv2, CHIRPS v3 histórico nem a base pareada já
aprovada da 2C.3C (`data/cfsv2_validacao_2c3c/base_pareada_cfsv2_
chirps_v3.csv`, só LIDA, nunca reescrita).

Reaproveita integralmente a infraestrutura leakage-free já testada da
2C.3C (scripts/cfsv2_validacao_cientifica.py, importado aqui como `v`):
carregamento, auditoria, pareamento, climatologia observada e
climatologia própria do modelo bruto — nunca duas lógicas paralelas de
climatologia que poderiam divergir.

Warm-up pré-registrado (protocolo, Seção 5.1): N_TREINO_MINIMO=10
observações históricas elegíveis por combinação lead × mês-alvo antes de
aplicar qualquer bias — abaixo disso, status_calibracao=
'warmup_amostra_insuficiente', nunca substituído pela previsão bruta,
nunca imputado, nunca compartilhado entre meses.

Roda com:
    python scripts/cfsv2_calibracao_aditiva.py --executar
    python scripts/cfsv2_calibracao_aditiva.py --gerar-relatorio
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

import cfsv2_validacao_cientifica as v  # noqa: E402

DIRETORIO_SAIDA = ROOT / 'data' / 'cfsv2_calibracao_2c3d'
CAMINHO_TABELA_EXPANDING = DIRETORIO_SAIDA / 'aditiva_expanding.csv'
CAMINHO_TABELA_LOYO = DIRETORIO_SAIDA / 'aditiva_loyo.csv'
CAMINHO_METRICAS_JSON = DIRETORIO_SAIDA / 'metricas_aditiva_2c3d.json'
RELATORIO_PATH = ROOT / 'docs' / 'nmme-fase2c3d-correcao-aditiva-cfsv2.md'

# Pré-registrado no protocolo (Seção 5.1) — NUNCA ajustável depois de
# observar resultados, e NUNCA confundido com v.AMOSTRA_MINIMA_ESTRATO
# (=20, usada na 2C.3C para avisos de amostra pequena na agregação, não
# para decidir se um parâmetro de calibração pode ser treinado).
N_TREINO_MINIMO = 10

STATUS_OK = 'ok'
STATUS_WARMUP = 'warmup_amostra_insuficiente'

COLUNAS_TABELA_EXPANDING = [
    'init_date', 'target_month', 'target_ano', 'target_mes', 'lead',
    'forecast_raw', 'observacao', 'n_treino', 'periodo_treino_inicio',
    'periodo_treino_fim', 'bias_aditivo', 'forecast_calibrado',
    'climatologia_observada', 'climatologia_modelo_raw',
    'benchmark_anomalia_reconstruida', 'status_calibracao',
]


# ══════════════════════════════════════════════════════════════════════════
# Seção 2 do pedido — correção aditiva causal por lead × mês-alvo
# ══════════════════════════════════════════════════════════════════════════

def construir_tabela_calibracao_aditiva(base_enriquecida):
    """Constrói, para cada (init_date, lead), a previsão determinística
    (ensemble mean, mesma convenção da 2C.3C — nunca recalibra os 24
    membros individualmente nesta atividade) e aplica a correção
    ADITIVA causal: bias_aditivo(lead, mês-alvo, init_date) = média dos
    erros históricos (forecast_raw - observação) da MESMA combinação
    lead × mês-alvo, com init_date_treino ESTRITAMENTE anterior à
    avaliada — nunca <=, nunca de outro lead, nunca de outro mês-alvo.

    Implementação por expansão ORDENADA no tempo dentro de cada célula
    (lead, mês-alvo): o histórico é acumulado e só usado para calcular o
    bias da linha seguinte DEPOIS de processá-la — a própria linha
    avaliada nunca pode entrar no seu próprio cálculo, por construção,
    não por filtro a posteriori.

    Warm-up (protocolo, Seção 5.1): enquanto n_treino < N_TREINO_MINIMO,
    status_calibracao='warmup_amostra_insuficiente', bias_aditivo e
    forecast_calibrado ficam None — NUNCA substituídos pela previsão
    bruta, nunca imputados.

    benchmark_anomalia_reconstruida (protocolo, Seção 5.4) é calculado
    aqui também, reaproveitando as climatologias já causais da 2C.3C
    (clim_media/clim_modelo_media de `_enriquecer_com_climatologia`) —
    nunca recalculadas de outra forma."""
    media_membros = base_enriquecida.groupby(
        ['init_date', 'target_month', 'target_ano', 'target_mes', 'lead'], as_index=False
    ).agg(forecast_raw=('forecast_prec_mm', 'mean'),
          observacao=('obs_prec_mm', 'first'),
          climatologia_observada=('clim_media', 'first'),
          climatologia_modelo_raw=('clim_modelo_media', 'first'))
    media_membros['erro'] = media_membros['forecast_raw'] - media_membros['observacao']

    linhas = []
    for (lead, mes_alvo), grupo in media_membros.groupby(['lead', 'target_mes']):
        grupo = grupo.assign(_p=pd.PeriodIndex(grupo['init_date'], freq='M')).sort_values('_p')
        erros_historicos = []
        inits_historicos = []
        for _, row in grupo.iterrows():
            n_treino = len(erros_historicos)
            if n_treino >= N_TREINO_MINIMO:
                bias = float(np.mean(erros_historicos))
                status = STATUS_OK
                periodo_inicio = inits_historicos[0]
                periodo_fim = inits_historicos[-1]
                forecast_calibrado = float(row['forecast_raw'] - bias)
            else:
                bias = None
                status = STATUS_WARMUP
                periodo_inicio = None
                periodo_fim = None
                forecast_calibrado = None

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
                'bias_aditivo': bias, 'forecast_calibrado': forecast_calibrado,
                'climatologia_observada': float(clim_obs) if pd.notna(clim_obs) else None,
                'climatologia_modelo_raw': float(clim_mod) if pd.notna(clim_mod) else None,
                'benchmark_anomalia_reconstruida': bench3,
                'status_calibracao': status,
            })

            # Histórico só cresce DEPOIS de processar a linha atual —
            # garante estruturalmente que ela nunca entra no seu próprio
            # cálculo (não é um filtro aplicado depois, é a ordem das
            # operações).
            erros_historicos.append(float(row['erro']))
            inits_historicos.append(row['init_date'])

    tabela = pd.DataFrame(linhas)[COLUNAS_TABELA_EXPANDING]
    tabela = tabela.assign(_p=pd.PeriodIndex(tabela['init_date'], freq='M')).sort_values(
        ['lead', '_p']).drop(columns='_p').reset_index(drop=True)
    return tabela


def adicionar_climatologia_modelo_calibrado(tabela):
    """Seção 7 do pedido — climatologia PRÓPRIA do modelo CALIBRADO
    (nunca a do bruto): média causal dos `forecast_calibrado` históricos
    ELEGÍVEIS (status_calibracao='ok') da MESMA combinação lead ×
    mês-alvo, estritamente anteriores à inicialização avaliada. Como
    depende de forecast_calibrado já existir (que por sua vez exige
    n_treino>=N_TREINO_MINIMO), esta climatologia tem, por desenho,
    ainda MENOS histórico disponível que o bias aditivo — o número de
    casos efetivamente utilizáveis é registrado em
    `n_climatologia_modelo_calibrado` para cada linha, nunca escondido."""
    tabela = tabela.assign(_p=pd.PeriodIndex(tabela['init_date'], freq='M'))
    climatologias = pd.Series(np.nan, index=tabela.index, dtype='float64')
    n_usados = pd.Series(0, index=tabela.index, dtype='int64')

    for (lead, mes_alvo), grupo in tabela.groupby(['lead', 'target_mes']):
        grupo_ordenado = grupo.sort_values('_p')
        historicos_calibrados = []
        for idx, row in grupo_ordenado.iterrows():
            n = len(historicos_calibrados)
            if n > 0:
                climatologias.at[idx] = float(np.mean(historicos_calibrados))
            n_usados.at[idx] = n
            if row['status_calibracao'] == STATUS_OK:
                historicos_calibrados.append(row['forecast_calibrado'])

    resultado = tabela.drop(columns='_p').copy()
    resultado['climatologia_modelo_calibrado'] = climatologias
    resultado['n_climatologia_modelo_calibrado'] = n_usados
    return resultado


def validar_identidade_benchmark3(tabela):
    """Seção 6 do pedido — valida PROGRAMATICAMENTE a identidade
    algébrica: benchmark_anomalia_reconstruida - observacao ==
    (forecast_raw - climatologia_modelo_raw) - (observacao -
    climatologia_observada). Usada tanto como STOP-ON-FAILURE em tempo
    de execução quanto como teste automatizado — nunca assumida."""
    sub = tabela.dropna(subset=['benchmark_anomalia_reconstruida', 'climatologia_modelo_raw',
                                  'climatologia_observada'])
    if len(sub) == 0:
        return {'identidade_ok': True, 'max_diff_absoluto': 0.0, 'n_verificado': 0,
                'nota': 'nenhuma linha com benchmark3 disponível para verificar'}
    lado_a = sub['benchmark_anomalia_reconstruida'] - sub['observacao']
    lado_b = (sub['forecast_raw'] - sub['climatologia_modelo_raw']) - (
        sub['observacao'] - sub['climatologia_observada'])
    diff = (lado_a - lado_b).abs()
    max_diff = float(diff.max())
    return {'identidade_ok': bool(max_diff < 1e-9), 'max_diff_absoluto': max_diff,
            'n_verificado': int(len(sub))}


# ══════════════════════════════════════════════════════════════════════════
# Auditorias defensivas — STOP-ON-FAILURE (item 14 do pedido)
# ══════════════════════════════════════════════════════════════════════════

def _verificar_nenhum_leakage_na_tabela(tabela):
    """Checagem defensiva adicional (nunca confiar só na construção):
    para toda linha elegível (status_calibracao='ok'), periodo_treino_fim
    tem que ser ESTRITAMENTE anterior a init_date."""
    problemas = []
    ok = tabela[tabela['status_calibracao'] == STATUS_OK]
    for _, row in ok.iterrows():
        if row['periodo_treino_fim'] is None:
            problemas.append(f"{row['init_date']} lead={row['lead']}: status=ok mas periodo_treino_fim ausente")
            continue
        fim_p = v._periodo(row['periodo_treino_fim'])
        avaliada_p = v._periodo(row['init_date'])
        if not (fim_p < avaliada_p):
            problemas.append(f"{row['init_date']} lead={row['lead']}: periodo_treino_fim="
                              f"{row['periodo_treino_fim']} >= init_date avaliada")
    return {'ok': len(problemas) == 0, 'n_problemas': len(problemas), 'problemas': problemas[:20]}


def _verificar_nan_inf_inesperado(det, boot):
    """Varre os dicts de resultado procurando NaN/Inf não explicados —
    campos numéricos devem ser ou um valor finito, ou None (explicitamente
    'não disponível'), nunca NaN/Inf silencioso."""
    problemas = []

    def checar(valor, caminho):
        if isinstance(valor, (int, float)) and not isinstance(valor, bool):
            if math.isnan(valor) or math.isinf(valor):
                problemas.append(caminho)

    for lead, d in det.items():
        for k, val in d.items():
            checar(val, f'det[{lead}][{k}]')
    for lead, d in boot.items():
        for k, val in d.items():
            if isinstance(val, dict):
                for kk, vv in val.items():
                    checar(vv, f'boot[{lead}][{k}][{kk}]')
    return {'ok': len(problemas) == 0, 'campos_problema': problemas}


def _primeira_inicializacao_elegivel_por_celula(tabela):
    """Item 3 do pedido — 'ao final, informar qual foi a primeira
    inicialização elegível em cada lead × mês-alvo', derivada
    PROGRAMATICAMENTE da tabela real, nunca hardcoded."""
    resultado = {}
    ok = tabela[tabela['status_calibracao'] == STATUS_OK]
    for (lead, mes), grupo in ok.groupby(['lead', 'target_mes']):
        primeira = sorted(grupo['init_date'].tolist(), key=v._periodo)[0]
        resultado.setdefault(int(lead), {})[int(mes)] = primeira
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# Seção 7/8 do pedido — métricas determinísticas e os três skills
# ══════════════════════════════════════════════════════════════════════════

def metricas_deterministicas_aditiva_por_horizonte(tabela):
    """Seção 7/8 do pedido — por horizonte, somente sobre
    status_calibracao='ok' E benchmark_anomalia_reconstruida disponível
    (nunca o benchmark incluindo registros de warm-up excluídos do
    método). RMSE do método calibrado e dos três benchmarks sempre sobre
    EXATAMENTE os mesmos casos (numerador e denominador)."""
    resultado = {}
    for lead in v.LEADS_ESPERADOS:
        sub_lead = tabela[tabela['lead'] == lead]
        sub = sub_lead[sub_lead['status_calibracao'] == STATUS_OK].dropna(
            subset=['benchmark_anomalia_reconstruida'])
        n = len(sub)
        if n == 0:
            resultado[lead] = {'n_elegivel': 0, 'rotulo': v.ROTULO_HORIZONTE[lead]}
            continue

        calibrado = sub['forecast_calibrado'].values
        raw = sub['forecast_raw'].values
        obs = sub['observacao'].values
        clim = sub['climatologia_observada'].values
        bench3 = sub['benchmark_anomalia_reconstruida'].values
        # Garantia defensiva explícita (item 14 — "amostras diferentes
        # entre método e benchmark"): os quatro vêm da MESMA sub, então
        # os tamanhos são SEMPRE iguais por construção — verificado aqui
        # mesmo assim, nunca assumido silenciosamente.
        assert len(calibrado) == len(raw) == len(obs) == len(clim) == len(bench3) == n

        rmse_cal = v._rmse(calibrado, obs)
        rmse_raw = v._rmse(raw, obs)
        rmse_clim = v._rmse(clim, obs)
        rmse_bench3 = v._rmse(bench3, obs)

        sub_anom = sub.dropna(subset=['climatologia_modelo_calibrado'])
        n_anomalia = len(sub_anom)
        if n_anomalia >= 2:
            anom_modelo = (sub_anom['forecast_calibrado'].values
                            - sub_anom['climatologia_modelo_calibrado'].values)
            anom_obs = (sub_anom['observacao'].values
                        - sub_anom['climatologia_observada'].values)
            corr_anomalia = v._corr(anom_modelo, anom_obs)
        else:
            corr_anomalia = None

        resultado[lead] = {
            'n_elegivel': n,
            'amostra_suficiente': n >= v.AMOSTRA_MINIMA_ESTRATO,
            'rotulo': v.ROTULO_HORIZONTE[lead],
            'bias': v._bias(calibrado, obs), 'mae': v._mae(calibrado, obs), 'rmse': rmse_cal,
            'corr_absoluta': v._corr(calibrado, obs),
            'n_anomalia_disponivel': n_anomalia,
            'corr_anomalia_modelo_calibrado': corr_anomalia,
            'rmse_raw': rmse_raw, 'rmse_climatologia': rmse_clim,
            'rmse_benchmark_anomalia_reconstruida': rmse_bench3,
            'skill_vs_raw': v.rmsess(rmse_cal, rmse_raw),
            'RMSESS_climatologia': v.rmsess(rmse_cal, rmse_clim),
            'skill_vs_anomalia_reconstruida': v.rmsess(rmse_cal, rmse_bench3),
            'formula_skill': ('skill_vs_X = 1 - RMSE_calibrado / RMSE_X — numerador e denominador '
                               'sempre sobre os MESMOS casos elegíveis.'),
        }
    return resultado


def _metricas_de_subconjunto_aditiva(sub):
    """Núcleo compartilhado pelas matrizes mês×lead e grupo_sazonal×lead
    (Seção 10 do pedido) — nunca duas fórmulas paralelas."""
    n = len(sub)
    if n == 0:
        return {'n': 0}
    calibrado = sub['forecast_calibrado'].values
    raw = sub['forecast_raw'].values
    obs = sub['observacao'].values
    clim = sub['climatologia_observada'].values
    bench3 = sub['benchmark_anomalia_reconstruida'].values
    rmse_cal = v._rmse(calibrado, obs)

    resultado = {
        'n': n,
        'amostra_suficiente': n >= v.AMOSTRA_MINIMA_ESTRATO,
        'bias': v._bias(calibrado, obs), 'mae': v._mae(calibrado, obs), 'rmse': rmse_cal,
        'skill_vs_raw': v.rmsess(rmse_cal, v._rmse(raw, obs)),
        'RMSESS_climatologia': v.rmsess(rmse_cal, v._rmse(clim, obs)),
        'skill_vs_anomalia_reconstruida': v.rmsess(rmse_cal, v._rmse(bench3, obs)),
    }
    sub_anom = sub.dropna(subset=['climatologia_modelo_calibrado'])
    n_anom = len(sub_anom)
    resultado['n_anomalia_disponivel'] = n_anom
    if n_anom >= 2:
        anom_modelo = (sub_anom['forecast_calibrado'].values
                        - sub_anom['climatologia_modelo_calibrado'].values)
        anom_obs = sub_anom['observacao'].values - sub_anom['climatologia_observada'].values
        resultado['corr_anomalia_modelo_calibrado'] = v._corr(anom_modelo, anom_obs)
    else:
        resultado['corr_anomalia_modelo_calibrado'] = None
    return resultado


def matriz_mes_lead_aditiva(tabela):
    """Seção 10 do pedido — diagnóstico de heterogeneidade (protocolo,
    Seção 5.5), NUNCA critério de aprovação nem 72 testes de
    significância."""
    ok = tabela[tabela['status_calibracao'] == STATUS_OK].dropna(
        subset=['benchmark_anomalia_reconstruida'])
    matriz = {}
    for mes in range(1, 13):
        matriz[mes] = {}
        for lead in v.LEADS_ESPERADOS:
            sub = ok[(ok['target_mes'] == mes) & (ok['lead'] == lead)]
            matriz[mes][lead] = _metricas_de_subconjunto_aditiva(sub)
    return matriz


def matriz_grupo_sazonal_lead_aditiva(tabela):
    ok = tabela[tabela['status_calibracao'] == STATUS_OK].dropna(
        subset=['benchmark_anomalia_reconstruida'])
    matriz = {}
    for grupo in ('chuvosa', 'transicao', 'seca'):
        meses_grupo = [m for m, g in v.GRUPO_SAZONAL_POR_MES.items() if g == grupo]
        matriz[grupo] = {}
        for lead in v.LEADS_ESPERADOS:
            sub = ok[(ok['target_mes'].isin(meses_grupo)) & (ok['lead'] == lead)]
            matriz[grupo][lead] = _metricas_de_subconjunto_aditiva(sub)
    return matriz


# ══════════════════════════════════════════════════════════════════════════
# Seção 9 do pedido — bootstrap em blocos por target_ano
# ══════════════════════════════════════════════════════════════════════════

def bootstrap_skills_aditiva_por_horizonte(tabela, n_resamples=500, seed=20261001):
    """Seção 9 do pedido — IC 95% dos três skills via bootstrap em
    blocos por target_ano. Em cada reamostra, método calibrado e os três
    benchmarks são recalculados sobre EXATAMENTE a mesma `amostra`
    (mesmos blocos de ano sorteados) — nunca ICs derivados dividindo
    intervalos calculados separadamente."""
    rng = np.random.default_rng(seed)
    resultado = {}

    for lead in v.LEADS_ESPERADOS:
        sub_lead = tabela[tabela['lead'] == lead]
        sub = sub_lead[sub_lead['status_calibracao'] == STATUS_OK].dropna(
            subset=['benchmark_anomalia_reconstruida'])
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

        por_ano = {a: sub[sub['target_ano'] == a] for a in anos}

        skill_raw_boot, rmsess_clim_boot, skill_anom_boot = [], [], []
        for _ in range(n_resamples):
            anos_sorteados = rng.choice(anos, size=len(anos), replace=True)
            amostra = pd.concat([por_ano[a] for a in anos_sorteados], ignore_index=True)

            rmse_cal = v._rmse(amostra['forecast_calibrado'].values, amostra['observacao'].values)
            rmse_raw = v._rmse(amostra['forecast_raw'].values, amostra['observacao'].values)
            rmse_clim = v._rmse(amostra['climatologia_observada'].values, amostra['observacao'].values)
            rmse_bench3 = v._rmse(amostra['benchmark_anomalia_reconstruida'].values,
                                    amostra['observacao'].values)

            s1 = v.rmsess(rmse_cal, rmse_raw)
            s2 = v.rmsess(rmse_cal, rmse_clim)
            s3 = v.rmsess(rmse_cal, rmse_bench3)
            if s1 is not None:
                skill_raw_boot.append(s1)
            if s2 is not None:
                rmsess_clim_boot.append(s2)
            if s3 is not None:
                skill_anom_boot.append(s3)

        rmse_cal_p = v._rmse(sub['forecast_calibrado'].values, sub['observacao'].values)
        rmse_raw_p = v._rmse(sub['forecast_raw'].values, sub['observacao'].values)
        rmse_clim_p = v._rmse(sub['climatologia_observada'].values, sub['observacao'].values)
        rmse_bench3_p = v._rmse(sub['benchmark_anomalia_reconstruida'].values,
                                  sub['observacao'].values)

        resumo_raw = v._resumo_bootstrap(v.rmsess(rmse_cal_p, rmse_raw_p), skill_raw_boot)
        resumo_clim = v._resumo_bootstrap(v.rmsess(rmse_cal_p, rmse_clim_p), rmsess_clim_boot)
        resumo_anom = v._resumo_bootstrap(v.rmsess(rmse_cal_p, rmse_bench3_p), skill_anom_boot)

        resultado[lead] = {
            'n': n, 'amostra_suficiente': True, 'n_anos_distintos': int(len(anos)),
            'n_resamples': n_resamples,
            'metodo': 'bootstrap em blocos por target_ano — método calibrado e os três '
                      'benchmarks usam os MESMOS blocos sorteados em cada reamostra',
            'skill_vs_raw': resumo_raw,
            'skill_vs_raw_ic_classificacao': v._classificar_ic_relativo_a_zero(
                resumo_raw['ic95_lo'], resumo_raw['ic95_hi']),
            'RMSESS_climatologia': resumo_clim,
            'RMSESS_climatologia_ic_classificacao': v._classificar_ic_relativo_a_zero(
                resumo_clim['ic95_lo'], resumo_clim['ic95_hi']),
            'skill_vs_anomalia_reconstruida': resumo_anom,
            'skill_vs_anomalia_reconstruida_ic_classificacao': v._classificar_ic_relativo_a_zero(
                resumo_anom['ic95_lo'], resumo_anom['ic95_hi']),
            'nota': "IC nunca convertido automaticamente em rótulo 'bom'/'ruim' — ver "
                    "*_ic_classificacao. Critério pré-registrado: skill_vs_anomalia_reconstruida "
                    "é o ponto PRINCIPAL de aprovação (protocolo, Seção 6.2) — não "
                    "RMSESS_climatologia nem skill_vs_raw isoladamente.",
        }
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# Seção 11 do pedido — LOYO retrospectivo (complementar, nunca operacional)
# ══════════════════════════════════════════════════════════════════════════

def construir_tabela_calibracao_aditiva_loyo(base_pareada, chirps_df):
    """Versão LOYO do bias aditivo — usa TODOS os anos exceto o do
    próprio target_ano avaliado (passado E futuro), mesma combinação
    lead × mês-alvo. Deliberadamente NÃO causal — rotulada
    'aditiva_loyo_retrospective', nunca chamada de operacional, nunca
    misturada com a tabela expansível."""
    base_loyo = v._enriquecer_com_climatologia_loyo(base_pareada, chirps_df)
    media_membros = base_loyo.groupby(
        ['init_date', 'target_month', 'target_ano', 'target_mes', 'lead'], as_index=False
    ).agg(forecast_raw=('forecast_prec_mm', 'mean'),
          observacao=('obs_prec_mm', 'first'),
          climatologia_loyo_observada=('clim_media', 'first'))
    media_membros['erro'] = media_membros['forecast_raw'] - media_membros['observacao']

    linhas = []
    for (lead, mes_alvo), grupo in media_membros.groupby(['lead', 'target_mes']):
        for _, row in grupo.iterrows():
            outros = grupo[grupo['target_ano'] != row['target_ano']]
            n_treino = len(outros)
            if n_treino >= N_TREINO_MINIMO:
                bias = float(outros['erro'].mean())
                status = STATUS_OK
                forecast_calibrado = float(row['forecast_raw'] - bias)
            else:
                bias = None
                status = STATUS_WARMUP
                forecast_calibrado = None
            clim_loyo = row['climatologia_loyo_observada']
            linhas.append({
                'init_date': row['init_date'], 'target_month': row['target_month'],
                'target_ano': int(row['target_ano']), 'target_mes': int(row['target_mes']),
                'lead': int(lead), 'forecast_raw': float(row['forecast_raw']),
                'observacao': float(row['observacao']), 'n_treino': n_treino,
                'bias_aditivo_loyo': bias, 'forecast_calibrado_loyo': forecast_calibrado,
                'climatologia_loyo_observada': float(clim_loyo) if pd.notna(clim_loyo) else None,
                'status_calibracao': status,
            })
    tabela = pd.DataFrame(linhas)
    tabela = tabela.assign(_p=pd.PeriodIndex(tabela['init_date'], freq='M')).sort_values(
        ['lead', '_p']).drop(columns='_p').reset_index(drop=True)
    return tabela


def metricas_deterministicas_aditiva_loyo_por_horizonte(tabela_loyo):
    resultado = {}
    for lead in v.LEADS_ESPERADOS:
        sub_lead = tabela_loyo[tabela_loyo['lead'] == lead]
        sub = sub_lead[sub_lead['status_calibracao'] == STATUS_OK].dropna(
            subset=['climatologia_loyo_observada'])
        n = len(sub)
        if n == 0:
            resultado[lead] = {'n_elegivel': 0}
            continue
        calibrado = sub['forecast_calibrado_loyo'].values
        obs = sub['observacao'].values
        clim = sub['climatologia_loyo_observada'].values
        rmse_cal = v._rmse(calibrado, obs)
        resultado[lead] = {
            'n_elegivel': n, 'bias': v._bias(calibrado, obs), 'mae': v._mae(calibrado, obs),
            'rmse': rmse_cal, 'corr_absoluta': v._corr(calibrado, obs),
            'RMSESS_climatologia_loyo': v.rmsess(rmse_cal, v._rmse(clim, obs)),
        }
    return resultado


def comparar_expanding_vs_loyo(det_expanding, det_loyo):
    """Seção 11 do pedido — comparação EXPLÍCITA expanding vs LOYO,
    nunca escondendo divergência atrás do resultado mais favorável."""
    comparacao = {}
    for lead in v.LEADS_ESPERADOS:
        e = det_expanding.get(lead, {})
        l = det_loyo.get(lead, {})
        rmsess_e = e.get('RMSESS_climatologia')
        rmsess_l = l.get('RMSESS_climatologia_loyo')
        divergencia = (float(rmsess_l - rmsess_e)
                        if rmsess_e is not None and rmsess_l is not None else None)
        comparacao[lead] = {
            'n_expanding': e.get('n_elegivel', 0), 'n_loyo': l.get('n_elegivel', 0),
            'RMSESS_climatologia_expanding': rmsess_e,
            'RMSESS_climatologia_loyo': rmsess_l,
            'divergencia_loyo_menos_expanding': divergencia,
            'nota': 'LOYO usa anos passados E futuros (amostra maior, mais estável) — NUNCA '
                    'operacional. Divergência relevante (sinal oposto ou magnitude muito '
                    'diferente) é um achado a registrar, nunca escondido atrás do resultado '
                    'mais favorável.',
        }
    return comparacao


# ══════════════════════════════════════════════════════════════════════════
# Orquestração
# ══════════════════════════════════════════════════════════════════════════

def executar_calibracao_aditiva(n_resamples_bootstrap=500):
    """Orquestra a Fase 2C.3D (Método 3.1) com STOP-ON-FAILURE explícito
    em cada condição do item 14 do pedido — nunca corrige silenciosamente."""
    auditoria = v.executar_auditoria()
    if not auditoria['auditoria_aprovada']:
        return ({'STOP_ON_FAILURE': True,
                 'motivo': 'auditoria da base RAW (2C.3C) reprovada — inconsistência com a base '
                            'aprovada',
                 'problemas': auditoria['problemas']}, None, None)

    df_raw = v.carregar_cfsv2_raw()
    chirps_df = v.carregar_chirps_v3_historico()
    base = v.construir_base_pareada(df_raw, chirps_df)
    if not v.validar_nenhum_mes_alvo_ausente(base):
        return ({'STOP_ON_FAILURE': True,
                 'motivo': 'pareamento com mês-alvo ausente — inconsistência com a base 2C.3C'},
                None, None)

    base_enriquecida = v._enriquecer_com_climatologia(base, chirps_df)
    tabela = construir_tabela_calibracao_aditiva(base_enriquecida)

    n_esperado = v.N_INICIALIZACOES_ESPERADO * len(v.LEADS_ESPERADOS)
    if len(tabela) != n_esperado:
        return ({'STOP_ON_FAILURE': True,
                 'motivo': f'número inesperado de combinações init×lead: {len(tabela)}, '
                            f'esperado {n_esperado}'}, None, None)

    identidade = validar_identidade_benchmark3(tabela)
    if not identidade['identidade_ok']:
        return ({'STOP_ON_FAILURE': True,
                 'motivo': 'benchmark_anomalia_reconstruida não satisfaz a identidade algébrica '
                            'esperada', 'detalhe': identidade}, None, None)

    leakage = _verificar_nenhum_leakage_na_tabela(tabela)
    if not leakage['ok']:
        return ({'STOP_ON_FAILURE': True, 'motivo': 'leakage detectado na tabela de calibração '
                  'aditiva', 'detalhe': leakage}, None, None)

    tabela = adicionar_climatologia_modelo_calibrado(tabela)
    primeira_elegivel = _primeira_inicializacao_elegivel_por_celula(tabela)

    det = metricas_deterministicas_aditiva_por_horizonte(tabela)
    boot = bootstrap_skills_aditiva_por_horizonte(tabela, n_resamples_bootstrap)
    matriz_mes_lead = matriz_mes_lead_aditiva(tabela)
    matriz_grupo = matriz_grupo_sazonal_lead_aditiva(tabela)

    nan_check = _verificar_nan_inf_inesperado(det, boot)
    if not nan_check['ok']:
        return ({'STOP_ON_FAILURE': True, 'motivo': 'NaN/Inf não explicado nos resultados',
                  'detalhe': nan_check}, None, None)

    tabela_loyo = construir_tabela_calibracao_aditiva_loyo(base, chirps_df)
    det_loyo = metricas_deterministicas_aditiva_loyo_por_horizonte(tabela_loyo)
    comparacao = comparar_expanding_vs_loyo(det, det_loyo)

    resultado = {
        'STOP_ON_FAILURE': False,
        'metodo': 'correcao_aditiva_causal_por_lead_x_mes_alvo',
        'n_treino_minimo': N_TREINO_MINIMO,
        'identidade_benchmark3': identidade,
        'leakage_check': leakage,
        'primeira_inicializacao_elegivel_por_lead_e_mes': primeira_elegivel,
        'expanding_operational_simulation': {
            'rotulo': 'aditiva_expanding_operational_simulation',
            'n_total_combinacoes': len(tabela),
            'deterministico_por_horizonte': det,
            'intervalos_confianca_skills_por_horizonte': boot,
            'matriz_mes_lead': matriz_mes_lead,
            'matriz_grupo_sazonal_lead': matriz_grupo,
        },
        'loyo_retrospective': {
            'rotulo': 'aditiva_loyo_retrospective',
            'aviso': 'NÃO simula uso em tempo real — usa anos futuros no cálculo do bias. '
                     'Análise complementar apenas, nunca misturada com '
                     'expanding_operational_simulation nem chamada de operacional.',
            'deterministico_por_horizonte': det_loyo,
        },
        'comparacao_expanding_vs_loyo': comparacao,
        'nenhuma_calibracao_aplicada_em_producao': True,
        'nenhum_outro_metodo_de_calibracao_implementado': True,
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
        resultado, tabela, tabela_loyo = executar_calibracao_aditiva()
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
        import cfsv2_relatorio_aditiva_2c3d as rel
        rel.gerar_e_escrever()
        return

    ap.print_help()


if __name__ == '__main__':
    main()
