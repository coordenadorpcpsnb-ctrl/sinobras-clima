#!/usr/bin/env python3
"""
nmme_processar.py — Fase 2C.1: parsing/normalização de dados NMME
(infraestrutura, Seção 27). Reaproveita utilitários genéricos já
validados nas Fases 2A-2B (distância ponto-grade, faixa de
plausibilidade física de precipitação) — não força as abstrações
específicas do C3S (GRIB, `tprate`, `leadtime_month`) onde o formato
NMME é estruturalmente diferente: NetCDF, nome/unidade de variável
variam por modelo, e a convenção temporal NUNCA é assumida igual ao
C3S sem validação explícita (Seção 13).
"""

import sys
from calendar import monthrange
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from c3s_poc import distancia_km_aprox, PREC_MM_MIN_PLAUSIVEL, PREC_MM_MAX_PLAUSIVEL  # noqa: E402
from _c3s_utils import MUNICIPIOS  # noqa: E402
import c3s_hindcast as hc  # noqa: E402

MUNICIPIO = 'Sao_Bento_do_Tocantins'   # mesma localização das Fases C3S (Seção 15) — nunca nova.

# Seção 11 — nomes aceitos de variável de precipitação (comparação
# case-insensitive); nunca decidido por posição/heurística.
NOMES_VARIAVEL_PRECIP_ACEITOS = {'prate', 'prec', 'precip', 'pr', 'precipitation'}

# Seção 12 — unidades reconhecidas; qualquer outra falha explicitamente
# em vez de assumir um fator de conversão.
UNIDADES_MM_DIA_ACEITAS = {'mm/day', 'mm day-1', 'mm/dia', 'mm day^-1', 'mm d-1'}
UNIDADES_KG_M2_S_ACEITAS = {'kg m-2 s-1', 'kg/m2/s', 'kg m**-2 s**-1', 'kg m-2 s-1 '}


# ══════════════════════════════════════════════════════════════════════════
# Seção 13 — convenção temporal NUNCA assumida idêntica ao C3S. A fórmula
# default replica a convenção C3S (lead 1 = mês de inicialização,
# confirmada em _c3s_utils.py) só como HIPÓTESE DE TRABALHO — o POC real
# tem que validar contra o metadata do arquivo baixado (coordenada L /
# valid_time, dependendo do dataset) antes de aceitar qualquer resultado
# baseado nela. `esquema` existe justamente para o POC poder trocar para
# 'lead1_mes_seguinte' se o arquivo real confirmar a outra convenção
# plausível, sem precisar reescrever a função.
# ══════════════════════════════════════════════════════════════════════════

def leadtime_para_mes_alvo_nmme(init_date, lead, esquema='lead1_igual_mes_inicializacao'):
    init_date = pd.Period(init_date, freq='M')
    if lead < 1:
        raise ValueError(f"lead deve ser >= 1 (não existe lead 0); recebido {lead}")
    if esquema == 'lead1_igual_mes_inicializacao':
        return init_date + (lead - 1)
    if esquema == 'lead1_mes_seguinte':
        return init_date + lead
    raise ValueError(f"esquema temporal NMME desconhecido: {esquema!r} — nunca decidido por suposição "
                      f"(Seção 13); use 'lead1_igual_mes_inicializacao' ou 'lead1_mes_seguinte'.")


def validar_variavel_precipitacao(nomes_variaveis_disponiveis):
    """Barreira (Seção 18/35-P): reprova explicitamente se nenhuma
    variável de precipitação reconhecida estiver no dataset."""
    disponiveis_lower = {str(v).lower(): v for v in nomes_variaveis_disponiveis}
    encontradas = sorted(set(disponiveis_lower) & NOMES_VARIAVEL_PRECIP_ACEITOS)
    if not encontradas:
        raise RuntimeError(f"nenhuma variável de precipitação reconhecida em "
                            f"{sorted(nomes_variaveis_disponiveis)} (aceitos: "
                            f"{sorted(NOMES_VARIAVEL_PRECIP_ACEITOS)}) — FALHANDO (Seção 18/35-P).")
    return disponiveis_lower[encontradas[0]]


def dias_no_mes(target_month):
    """calendar.monthrange trata fevereiro bissexto corretamente (Seção
    12, teste I) — nunca um valor fixo de 28/30/31."""
    p = pd.Period(target_month, freq='M')
    return monthrange(p.year, p.month)[1]


def converter_precip_para_mm_mes(valor, unidade_original, target_month):
    """Converte para mm/mês SÓ a partir da unidade lida do metadata
    (Seção 12 — nunca pela variável), considerando o nº de dias do
    mês-alvo. Levanta explicitamente para qualquer unidade não
    reconhecida — nunca adivinha fator de conversão."""
    n_dias = dias_no_mes(target_month)
    unidade_norm = str(unidade_original).strip().lower()
    if unidade_norm in {u.lower() for u in UNIDADES_MM_DIA_ACEITAS}:
        mm_mes = float(valor) * n_dias
        conversao = f'mm/day * {n_dias} dias ({pd.Period(target_month, "M")})'
    elif unidade_norm in {u.lower() for u in UNIDADES_KG_M2_S_ACEITAS}:
        # 1 kg de água / m² de área = 1 mm de lâmina d'água — kg m-2 s-1
        # já É mm/s numericamente; só falta multiplicar por segundos no mês.
        mm_mes = float(valor) * 86400.0 * n_dias
        conversao = f'kg m-2 s-1 * 86400 s/dia * {n_dias} dias ({pd.Period(target_month, "M")})'
    else:
        raise ValueError(f"unidade de precipitação NMME não reconhecida: {unidade_original!r} — "
                          f"FALHANDO em vez de assumir conversão (Seção 12).")
    return {'forecast_prec_mm_month': round(mm_mes, 3), 'conversion_applied': conversao,
            'units_original': unidade_original}


def validar_raw(valores):
    """Barreiras Q/R/plausibilidade (Seção 35): NaN/inf reprova;
    precipitação negativa reprova; fora da faixa física plausível
    reprova — mesma faixa de c3s_poc.py (0-1500mm/mês), reaproveitada
    porque é um limite físico, não algo C3S-específico."""
    v = np.asarray(valores, dtype=float)
    if not np.all(np.isfinite(v)):
        raise RuntimeError("raw NMME contém valor(es) não finito(s) (NaN/inf) — FALHANDO (Seção 35-Q).")
    if (v < 0).any():
        raise RuntimeError("raw NMME contém precipitação negativa — FALHANDO (Seção 35-R).")
    fora = v[(v < PREC_MM_MIN_PLAUSIVEL) | (v > PREC_MM_MAX_PLAUSIVEL)]
    if len(fora):
        raise RuntimeError(f"{len(fora)} valor(es) fora de [{PREC_MM_MIN_PLAUSIVEL},"
                            f"{PREC_MM_MAX_PLAUSIVEL}]mm — FALHANDO.")
    return True


def estatisticas_ensemble_modelo(valores_membros):
    """Equal-model weighting (Seção 24, teste O): a estatística de UM
    modelo nunca depende de quantos membros ele tem internamente —
    reaproveita c3s_hindcast.py::estatisticas_ensemble sem alteração
    (primitiva já agnóstica de fonte, usada nas Fases 2A-2B)."""
    return hc.estatisticas_ensemble(valores_membros)


def montar_linha_raw(sistema, init_date, target_month, lead, member, forecast_prec_mm,
                      requested_lat, requested_lon, selected_lat, selected_lon,
                      variable_original, units_original, conversion_applied,
                      source_url, source_type):
    """1 linha de nmme_poc_raw.csv (Seção 30) — só as colunas mínimas
    exigidas, nada a mais."""
    dist_km = distancia_km_aprox(requested_lat, requested_lon, selected_lat, selected_lon)
    return {
        'centre': sistema.centre, 'model_name': sistema.model_name, 'model_version': sistema.model_version,
        'init_date': str(pd.Period(init_date, 'M')), 'target_month': str(pd.Period(target_month, 'M')),
        'lead': int(lead), 'member': member, 'forecast_prec_mm': round(float(forecast_prec_mm), 3),
        'requested_lat': requested_lat, 'requested_lon': requested_lon,
        'selected_lat': selected_lat, 'selected_lon': selected_lon,
        'grid_distance_km': round(dist_km, 2),
        'variable_original': variable_original, 'units_original': units_original,
        'conversion_applied': conversion_applied, 'source_url': source_url, 'source_type': source_type,
    }


def montar_linha_temporal_audit(sistema, init_date, lead, target_month, initialization_reference,
                                 source_time_coordinate, source_lead_coordinate, mapping_status,
                                 notes=''):
    """1 linha de nmme_poc_temporal_audit.csv (Seção 31)."""
    return {
        'centre': sistema.centre, 'model_name': sistema.model_name,
        'init_date': str(pd.Period(init_date, 'M')), 'lead': int(lead),
        'target_month': str(pd.Period(target_month, 'M')),
        'initialization_reference': initialization_reference,
        'source_time_coordinate': source_time_coordinate, 'source_lead_coordinate': source_lead_coordinate,
        'mapping_status': mapping_status, 'notes': notes,
    }
