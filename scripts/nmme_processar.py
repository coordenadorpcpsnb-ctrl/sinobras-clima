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


# ══════════════════════════════════════════════════════════════════════════
# Fase 2C.1b (primeiro POC real, CFSv2) — Seção 6: mapeamento temporal
# NUNCA assumido a partir só da lógica C3S. `avaliar_mapeamento_temporal`
# tenta confirmar a semântica L<->mês-alvo a partir dos METADADOS do
# próprio dataset aberto (nunca por suposição) — só marca 'OK' quando há
# justificativa objetiva encontrada no arquivo; caso contrário
# 'UNCONFIRMED' (ou 'MISMATCH' se os metadados contradisserem a
# hipótese) — o POC deve ser tratado como cientificamente incompleto
# nesses dois últimos casos, mesmo com download bem-sucedido (Seção 6).
# Função pura, sem efeito colateral — quem decide reprovar o POC por
# isso é o guardrail (nmme_poc.avaliar_aprovacao_poc), não esta função.
# ══════════════════════════════════════════════════════════════════════════

TERMOS_CONFIRMATORIOS_L = ('forecast_period', 'lead time', 'lead_time', 'target', 'valid_time',
                            'months since', 'forecastmonth')
NOMES_VARIAVEL_ALVO_CANDIDATOS = ('target', 'valid_time', 'target_month', 'forecast_time')

# ══════════════════════════════════════════════════════════════════════════
# Revisão pós-execução #1 (Seção 1/2/7) — modo de decodificação temporal
# REALMENTE usado para abrir o dataset. CF_DATETIME é o caminho normal
# (decode_times=True, cftime instalado decodifica qualquer calendário CF
# incluindo 360_day); RAW_NUMERIC_CF é o fallback controlado
# (decode_times=False) acionado só quando a decodificação falha por um
# motivo ESPECIFICAMENTE temporal (nmme_poc.abrir_dataset_com_fallback_
# temporal) — nesse modo os valores de tempo continuam numéricos crus,
# e avaliar_mapeamento_temporal() abaixo NUNCA tenta interpretá-los como
# data (Seção 2/8 — a barreira de confirmação não pode ser afrouxada
# só porque o dataset abriu).
# ══════════════════════════════════════════════════════════════════════════

TIME_DECODE_MODE_CF_DATETIME = 'CF_DATETIME'
TIME_DECODE_MODE_RAW_NUMERIC_CF = 'RAW_NUMERIC_CF'
# Execução real #2 (run 35888809240) — o dataset real trouxe
# calendar='360' (sem sufixo), alias legado da convenção CF pré-
# padronização ("all years are 360 days divided into 30 day months");
# o nome padronizado moderno é '360_day'. TIME_DECODE_MODE_CF_DATETIME_
# NORMALIZED_ALIAS marca quando a decodificação só funcionou depois de
# normalizar esse alias numa CÓPIA em memória (nunca no arquivo
# original) — distinto de CF_DATETIME (decodificou de primeira, sem
# nenhuma normalização) e de RAW_NUMERIC_CF (nem a normalização
# resolveu, ou o calendário não é um alias conhecido).
TIME_DECODE_MODE_CF_DATETIME_NORMALIZED_ALIAS = 'CF_DATETIME_NORMALIZED_ALIAS'

# Seção 2 (revisão temporal) — SÓ aliases documentados e evidenciados
# contra um caso real (nunca "por analogia"). '360' -> '360_day' é a
# única correspondência com evidência concreta (execução #2, run
# 35888809240) até agora; não adicionar outra entrada sem o mesmo nível
# de evidência.
CALENDAR_ALIASES_CF = {
    '360': '360_day',
}


def normalizar_calendar_cf(valor):
    """Seção 2 — traduz um alias de calendário CF LEGADO e DOCUMENTADO
    para o nome padronizado moderno; nunca inventa correspondência para
    um valor fora de `CALENDAR_ALIASES_CF`. Devolve
    (calendar_normalized, calendar_normalization_applied)."""
    if valor in CALENDAR_ALIASES_CF:
        return CALENDAR_ALIASES_CF[valor], True
    return valor, False


def inspecionar_metadata_temporal(ds, init_dimension):
    """Seção 7 (revisão pós-execução #1) — calendário/unidades de tempo
    REALMENTE presentes no dataset aberto, lidos da coordenada de
    inicialização (`init_dimension`, ex.: 'S'), nunca assumidos como
    gregoriano por omissão e nunca convertidos silenciosamente. Quando
    decode_times=True decodifica com sucesso, xarray move os atributos
    `units`/`calendar` originais de `.attrs` para `.encoding` na
    coordenada já decodificada — por isso `.encoding` é checado
    primeiro, caindo para `.attrs` no modo RAW_NUMERIC_CF (onde eles
    continuam brutos, sem decodificação)."""
    calendar_observed = time_units_observed = dtype_observed = None
    if init_dimension and hasattr(ds, 'variables') and init_dimension in ds.variables:
        s = ds[init_dimension]
        calendar_observed = s.encoding.get('calendar') or s.attrs.get('calendar')
        time_units_observed = s.encoding.get('units') or s.attrs.get('units')
        dtype_observed = str(s.dtype)
    return {
        'calendar_observed': calendar_observed or 'UNCONFIRMED',
        'time_units_observed': time_units_observed or 'UNCONFIRMED',
        'S_dtype_observed': dtype_observed or 'UNCONFIRMED',
    }


# ══════════════════════════════════════════════════════════════════════════
# Execução real #2 (Seção 4) — Método B de confirmação temporal: semântica
# CF/IRI documentada da coordenada forecast_period, usada só quando NÃO
# há variável auxiliar de data-alvo (Método A tem precedência — Seção
# 4, teste #10). Isso NÃO é inferência livre a partir do padrão
# numérico de L: os 7 requisitos exigem identificação objetiva via
# atributos REAIS do dataset (standard_name/units) MAIS uma rota cujo
# catálogo já documenta essa semântica (`forecast_period_semantics_
# documented`, nmme_catalogo.RotaMemberLevel) — nunca "L é 0.5,1.5..."
# sozinho (Seção 6).
# ══════════════════════════════════════════════════════════════════════════

MAPPING_METHOD_TARGET_VARIABLE = 'CONFIRMED_BY_TARGET_VARIABLE'
MAPPING_METHOD_FORECAST_PERIOD_SEMANTICS = 'CONFIRMED_BY_FORECAST_PERIOD_SEMANTICS'
MAPPING_METHOD_NONE = 'NONE'

STANDARD_NAME_S_FORECAST_REFERENCE_TIME = 'forecast_reference_time'
STANDARD_NAME_L_FORECAST_PERIOD = 'forecast_period'
LEAD_UNITS_MONTHS_ACEITAS = {'months', 'month'}

# ══════════════════════════════════════════════════════════════════════════
# Execução real #3 (run 35910675855, Seção 3/4/5) — bug real encontrado:
# a leitura da origem observada usava ds[dim_s].values.flat[0] do eixo S
# GLOBAL do Dataset (que pode preservar o eixo completo do catálogo-
# fonte, 1982-2010, mesmo depois de 'prec' já ter sido recortado para 1
# única origem) — o primeiro valor desse eixo global (1982-01) NÃO é
# evidência de nada sobre a origem de fato usada pela variável real.
# `_avaliar_selecao_inicializacao` corrige isso: inspeciona a coordenada
# S tal como associada à variável REAL de precipitação
# (rota.variable_name), nunca o eixo global do Dataset como um todo.
# ══════════════════════════════════════════════════════════════════════════

INIT_SELECTION_STATUS_OK_SCALAR = 'OK_SCALAR_COORD'
INIT_SELECTION_STATUS_OK_SINGLETON_DIM = 'OK_SINGLETON_DIM'
INIT_SELECTION_STATUS_FAIL_MULTIPLE = 'FAIL_MULTIPLE_INITIALIZATIONS'
INIT_SELECTION_STATUS_UNCONFIRMED_NO_COORD = 'UNCONFIRMED_NO_INIT_COORD'
# Revisão pós-execução #3 (risco residual, correção 2) — a documentação
# do operador Ingrid VALUE sozinha NÃO prova que o servidor de fato
# selecionou a inicialização pedida quando S é removido da variável.
# `UNCONFIRMED_VALUE_UNVERIFIED` é o status DEFAULT enquanto isso — só
# sobe para `OK_INGRID_VALUE_VERIFIED` quando uma CONFIRMAÇÃO DIRETA
# (nmme_poc.tentar_confirmar_origem_diretamente — seleção S/.../.../
# RANGEEDGES que preserva a dimensão, ou metadado confiável) observa a
# origem de fato, nunca a partir de comparação indireta de valores de
# precipitação (Seção 1/2 — "formatos diferentes não comprovam seleção
# correta; valores divergentes comprovam só que as respostas diferem;
# valores idênticos são um alerta, não prova definitiva"). A consulta
# de controle (nmme_poc.verificar_selecao_ingrid_value_por_consulta_
# controle) continua rodando como DIAGNÓSTICO complementar (Seção 3),
# mas nunca decide `init_selection_status` sozinha — seu resultado (um
# dos VERIFICATION_OUTCOME_* abaixo) só vai para os campos de auditoria
# `init_verification_*`.
INIT_SELECTION_STATUS_UNCONFIRMED_VALUE_UNVERIFIED = 'UNCONFIRMED_VALUE_UNVERIFIED'
INIT_SELECTION_STATUS_OK_INGRID_VALUE_VERIFIED = 'OK_INGRID_VALUE_VERIFIED'

# Revisão pós-execução #5 (RANGEEDGES como fonte principal) — os
# VERIFICATION_OUTCOME_* que viviam aqui (EXACT_ORIGIN_CONFIRMED,
# DIFFERENT_RESPONSES_ORIGIN_UNVERIFIED, IDENTICAL_RESPONSES_SUSPECT,
# INCOMPARABLE_RESPONSES, ORIGIN_MISMATCH, DATA_INCONSISTENT_WITH_VALUE)
# eram devolvidos exclusivamente por `nmme_poc.tentar_confirmar_origem_
# diretamente`/`verificar_selecao_ingrid_value_por_consulta_controle`,
# REMOVIDAS junto com toda a verificação de uma seleção via VALUE (a
# run real 36032400919 mostrou VALUE não ser confiável — Seção "não
# utilizar VALUE como fonte de dados"). Removidos por ficarem
# genuinamente inalcançáveis; histórico completo nos commits anteriores
# desta branch.

# Revisão pós-execução #4 (investigação da run 36028568952) — até aqui
# a confirmação DIRETA via RANGEEDGES só disparava quando S estava
# AUSENTE da variável (UNCONFIRMED_VALUE_UNVERIFIED). A execução real
# encontrou um caso NOVO: S PRESENTE na variável, com 1 único valor,
# mas esse valor (1982-01) diverge da origem pedida (2005-01) — a
# consulta VALUE original devolveu, aparentemente, o início do arquivo-
# fonte inteiro (o hindcast do CFSv2 começa em 1982), não a origem
# pedida. `_avaliar_semantica_forecast_period` já classifica isso como
# MISMATCH corretamente (Seção E, `periodo_observado != init_date`) —
# essa classificação NUNCA muda por causa do diagnóstico abaixo (Seção
# 1/9 desta investigação: nenhuma aprovação automática nova). O que
# faltava era executar TAMBÉM a confirmação direta nesse caso, só para
# fins de diagnóstico/auditoria — nunca para promover o status. Os 5
# outcomes abaixo classificam objetivamente o que a consulta RANGEEDGES
# de diagnóstico observou, distinguindo (item 7 da investigação):
# falha de sintaxe (o servidor rejeitou o request, HTTP 4xx — evidência
# de que a URL construída é malformada, não uma hipótese sobre a
# semântica do operador); seleção ignorada pelo servidor (o request foi
# aceito, mas o valor observado continua sendo o mesmo problema da
# consulta VALUE original, ou outra origem não pedida — evidência de
# que o servidor não aplicou a restrição); problema de interpretação de
# coordenadas (a resposta não pôde ser lida/parseada do nosso lado —
# não é evidência sobre o servidor, é uma lacuna nossa); e, só quando a
# origem observada bate exatamente com a pedida, confirmação exata via
# RANGEEDGES apesar do VALUE ter divergido (o achado mais interessante
# possível — mostra que RANGEEDGES e VALUE se comportam diferente para
# a mesma origem, mas mesmo assim NUNCA aprova o POC sozinho).
S_DIVERGENTE_DIAGNOSTICO_SYNTAX_ERROR = 'SYNTAX_ERROR'
S_DIVERGENTE_DIAGNOSTICO_SELECTION_IGNORED_BY_SERVER = 'SELECTION_IGNORED_BY_SERVER'
S_DIVERGENTE_DIAGNOSTICO_COORD_INTERPRETATION_ISSUE = 'COORD_INTERPRETATION_ISSUE'
S_DIVERGENTE_DIAGNOSTICO_EXACT_MATCH_DESPITE_VALUE_MISMATCH = 'EXACT_MATCH_DESPITE_VALUE_MISMATCH'
S_DIVERGENTE_DIAGNOSTICO_INCONCLUSIVE = 'INCONCLUSIVE'
S_DIVERGENTE_DIAGNOSTICO_NAO_EXECUTADO = 'NAO_EXECUTADO'
# Revisão pós-execução #5 (item 10, correção da run real 36032400919) —
# a execução real mostrou que RANGEEDGES com limites idênticos devolve
# uma JANELA (ex.: janeiro E fevereiro de 2005), não necessariamente 1
# único ponto. `diagnosticar_origem_s_divergente` tratava isso como
# SELECTION_IGNORED_BY_SERVER sempre que via >1 valor — errado quando a
# origem PEDIDA está entre os valores devolvidos: nesse caso o servidor
# não ignorou nada, só devolveu uma janela que CONTÉM a origem certa,
# junto de um vizinho. `SELECTION_IGNORED_BY_SERVER` fica reservado
# para quando a origem pedida está ausente entre os múltiplos valores
# (aí sim evidência de que a seleção não funcionou).
S_DIVERGENTE_DIAGNOSTICO_RANGE_WINDOW_MULTIPLE_INITIALIZATIONS = 'RANGE_WINDOW_MULTIPLE_INITIALIZATIONS'

INIT_SELECTION_METHOD_SCALAR_COORD = 'SCALAR_COORD_ON_VARIABLE'
INIT_SELECTION_METHOD_SINGLETON_DIM = 'SINGLETON_DIM_ON_VARIABLE'
# Seção 2 (revisão pós-execução #3) — rótulo documental (nunca
# empírico) para quando S foi removido da variável e a rota documenta a
# semântica de seleção-única do operador Ingrid VALUE. Por si só NUNCA
# confirma — só descreve a HIPÓTESE que a verificação de controle
# tentará corroborar ou refutar objetivamente.
INIT_SELECTION_METHOD_REQUEST_CONFIRMED_SELECTION = 'REQUEST_CONFIRMED_SELECTION'
INIT_SELECTION_METHOD_NONE = 'NONE'

# ══════════════════════════════════════════════════════════════════════════
# Revisão pós-execução #5 (RANGEEDGES como fonte principal) — a run real
# 36032400919 confirmou empiricamente que RANGEEDGES com limites
# idênticos (S/(Jan 2005)/(Jan 2005)/RANGEEDGES) devolve uma JANELA
# pequena (observado: jan+fev/2005), não garante 1 único ponto — e que a
# origem pedida ESTAVA presente nessa janela, ao contrário do VALUE
# (que devolveu 1982-01, o início do arquivo inteiro). Isso torna
# RANGEEDGES + seleção EXPLÍCITA em Python (por coordenada observada,
# nunca por posição/índice/proximidade) uma fonte mais confiável que
# VALUE — `selecionar_inicializacao_por_coordenada` é essa seleção.
# ══════════════════════════════════════════════════════════════════════════

INIT_SELECTION_METHOD_RANGEEDGES_WINDOW_COORDINATE_MATCH = 'RANGEEDGES_WINDOW_COORDINATE_MATCH'

INIT_SELECTION_STATUS_RANGEEDGES_OK = 'RANGEEDGES_OK'
# Item 2/3 — a origem pedida não apareceu NENHUMA vez entre os valores
# de S observados na janela RANGEEDGES.
INIT_SELECTION_STATUS_RANGEEDGES_FAIL_AUSENTE = 'RANGEEDGES_FAIL_AUSENTE'
# Item 3 — a origem pedida apareceu MAIS de uma vez (2 valores S
# distintos, ambos dentro do mês pedido) — o subset de origem não
# ocorreu de fato, dado ambíguo, nunca escolhido por posição.
INIT_SELECTION_STATUS_RANGEEDGES_FAIL_DUPLICADO = 'RANGEEDGES_FAIL_DUPLICADO'
# Item 5 — defesa adicional, redundante com FAIL_DUPLICADO na prática:
# mesmo quando exatamente 1 valor de S bateu a origem pedida ANTES da
# seleção, se a seleção por coordenada EXATA (`.sel`, nunca
# `method='nearest'`) devolver mais de 1 ponto depois, reprova — nunca
# assume que o primeiro resultado é o certo.
INIT_SELECTION_STATUS_RANGEEDGES_FAIL_MULTIPLA_APOS_SELECAO = 'RANGEEDGES_FAIL_MULTIPLA_APOS_SELECAO'
# Defesa final — depois de selecionar por coordenada exata, o valor
# resultante ainda diverge do mês pedido (não deveria acontecer se a
# seleção por coordenada foi implementada corretamente, mas nunca
# assumido sem checar).
INIT_SELECTION_STATUS_RANGEEDGES_FAIL_DIVERGENTE_APOS_SELECAO = 'RANGEEDGES_FAIL_DIVERGENTE_APOS_SELECAO'
# S presente mas com valores que não puderam ser interpretados como
# data (parsing falhou) — lacuna nossa, nunca contornada com adivinhação.
INIT_SELECTION_STATUS_RANGEEDGES_FAIL_NAO_INTERPRETAVEL = 'RANGEEDGES_FAIL_NAO_INTERPRETAVEL'
# S ausente da variável mesmo na janela RANGEEDGES (nenhum valor de S
# associado a 'prec' — cenário diferente de FAIL_AUSENTE, que é "S
# presente mas sem o mês pedido").
INIT_SELECTION_STATUS_RANGEEDGES_FAIL_SEM_COORDENADA = 'RANGEEDGES_FAIL_SEM_COORDENADA'


def selecionar_inicializacao_por_coordenada(da, rota, ano, mes, ds=None):
    """Seleção EXPLÍCITA e validada da inicialização a partir de uma
    resposta Ingrid RANGEEDGES (item 1-5 da correção RANGEEDGES-fonte-
    principal). `da` é a DataArray da variável de precipitação já
    aberta (ex.: `ds[var_encontrada]`), possivelmente com MAIS de 1
    valor de S (RANGEEDGES devolve uma janela, não um ponto — Seção
    acima). Nunca seleciona por posição, índice zero ou proximidade
    temporal (`method='nearest'`) — só por igualdade EXATA com a
    coordenada S observada que corresponde à origem pedida.

    Algoritmo:
    1. Lê TODOS os valores de S associados a `da` (antes de qualquer
       seleção) — se S estiver ausente, FAIL_SEM_COORDENADA.
    2. Tenta interpretar cada valor como período mensal — se algum não
       for interpretável, FAIL_NAO_INTERPRETAVEL (nunca ignora
       silenciosamente um valor que não conseguiu ler).
    3. Conta quantos valores correspondem à origem pedida (ano-mês):
       0 -> FAIL_AUSENTE; >1 -> FAIL_DUPLICADO (dado ambíguo, nunca
       escolhe o primeiro).
    4. Com exatamente 1 correspondência, seleciona por
       `.sel({S: <valor observado>})` (a dimensão S some do resultado
       quando S é uma dimensão real; quando já é escalar/singleton,
       nada precisa ser filtrado).
    5. Defesa pós-seleção: se o resultado ainda tiver mais de 1 valor
       de S, FAIL_MULTIPLA_APOS_SELECAO; se o valor final não bater a
       origem pedida, FAIL_DIVERGENTE_APOS_SELECAO.

    `ds`, quando informado, é o Dataset INTEIRO de onde `da` veio (ex.:
    o próprio dataset aberto do RANGEEDGES, com TODAS as variáveis —
    inclusive uma eventual variável auxiliar de data-alvo como
    `target`/`valid_time`, que não é coordenada de `da` e por isso não
    seria filtrada só por filtrar `da`). Quando a seleção é bem-sucedida,
    a MESMA coordenada `valor_alvo` escolhida para `da` é aplicada ao
    `ds` inteiro (`ds.sel({S: valor_alvo})`), devolvida como
    `ds_selecionado` — para que nenhuma validação temporal posterior
    (`avaliar_mapeamento_temporal`, incluindo o Método A de variável
    auxiliar) possa ler um valor associado a uma inicialização diferente
    da selecionada. `.sel()` preserva os atributos de todas as
    coordenadas não filtradas (inclusive S e L) sem precisar copiá-los
    à mão. Sem `ds` (uso direto da função pura, ex. em testes), fica
    `None` — o chamador decide o que fazer.

    Devolve dict com `status`, `s_values_before` (lista de strings, TODOS
    os valores observados antes da seleção, nunca só o escolhido),
    `s_values_after` (lista após a seleção, esperado 1 elemento quando
    status==RANGEEDGES_OK), `da_selecionado` (só quando OK),
    `ds_selecionado` (só quando OK e `ds` foi informado) e `evidencia`."""
    dim_s = getattr(rota, 'init_dimension', None) or 'S'
    origem = pd.Period(f'{ano:04d}-{mes:02d}', 'M')

    if dim_s not in getattr(da, 'coords', {}):
        return {'status': INIT_SELECTION_STATUS_RANGEEDGES_FAIL_SEM_COORDENADA,
                's_values_before': [], 's_values_after': [], 'da_selecionado': None,
                'ds_selecionado': None,
                'evidencia': f"coordenada {dim_s!r} ausente da variável — RANGEEDGES não preservou "
                              f"nenhum valor de S associado a ela."}

    valores_brutos = np.atleast_1d(np.asarray(da.coords[dim_s].values))
    s_values_before = [str(v) for v in valores_brutos]

    try:
        periodos = [pd.Period(str(v)[:7], 'M') for v in valores_brutos]
    except Exception as e:
        return {'status': INIT_SELECTION_STATUS_RANGEEDGES_FAIL_NAO_INTERPRETAVEL,
                's_values_before': s_values_before, 's_values_after': [], 'da_selecionado': None,
                'ds_selecionado': None,
                'evidencia': f"não foi possível interpretar 1+ valores de S observados "
                              f"({s_values_before!r}) como período mensal ({type(e).__name__}: {e})."}

    indices_match = [i for i, p in enumerate(periodos) if p == origem]
    if not indices_match:
        return {'status': INIT_SELECTION_STATUS_RANGEEDGES_FAIL_AUSENTE,
                's_values_before': s_values_before, 's_values_after': [], 'da_selecionado': None,
                'ds_selecionado': None,
                'evidencia': f"origem pedida ({origem}) não está entre os valores de S observados "
                              f"na janela RANGEEDGES ({s_values_before!r})."}
    if len(indices_match) > 1:
        return {'status': INIT_SELECTION_STATUS_RANGEEDGES_FAIL_DUPLICADO,
                's_values_before': s_values_before, 's_values_after': [], 'da_selecionado': None,
                'ds_selecionado': None,
                'evidencia': f"origem pedida ({origem}) aparece {len(indices_match)} vezes entre os "
                              f"valores de S observados ({s_values_before!r}) — dado ambíguo, nunca "
                              f"escolhida por posição."}

    valor_alvo = valores_brutos[indices_match[0]]
    # Item 4 — seleção EXCLUSIVA pela coordenada observada, nunca por
    # índice/posição nem por proximidade (sem method='nearest').
    da_selecionado = da.sel({dim_s: valor_alvo}) if dim_s in da.dims else da

    if dim_s in getattr(da_selecionado, 'coords', {}):
        valores_pos = np.atleast_1d(np.asarray(da_selecionado.coords[dim_s].values))
    else:
        valores_pos = np.atleast_1d(valor_alvo)
    s_values_after = [str(v) for v in valores_pos]

    if valores_pos.size > 1:
        return {'status': INIT_SELECTION_STATUS_RANGEEDGES_FAIL_MULTIPLA_APOS_SELECAO,
                's_values_before': s_values_before, 's_values_after': s_values_after, 'da_selecionado': None,
                'ds_selecionado': None,
                'evidencia': f"seleção por coordenada exata ainda devolveu {valores_pos.size} valores "
                              f"de S ({s_values_after!r}) — nunca assume o primeiro como correto."}

    periodo_pos = pd.Period(str(valores_pos[0])[:7], 'M')
    if periodo_pos != origem:
        return {'status': INIT_SELECTION_STATUS_RANGEEDGES_FAIL_DIVERGENTE_APOS_SELECAO,
                's_values_before': s_values_before, 's_values_after': s_values_after, 'da_selecionado': None,
                'ds_selecionado': None,
                'evidencia': f"após a seleção por coordenada exata, o valor observado ({periodo_pos}) "
                              f"diverge da origem pedida ({origem})."}

    # Item novo (revisão de acompanhamento) — a MESMA coordenada exata
    # usada para filtrar `da` é aplicada ao `ds` inteiro, quando
    # informado, para que qualquer variável auxiliar (ex.: `target`)
    # também fique restrita à inicialização selecionada antes de
    # qualquer validação temporal downstream (nunca só `da`/`prec`,
    # que não inclui variáveis auxiliares como coordenadas próprias).
    if ds is not None:
        ds_selecionado = ds.sel({dim_s: valor_alvo}) if dim_s in getattr(ds, 'dims', ()) else ds
    else:
        ds_selecionado = None

    return {'status': INIT_SELECTION_STATUS_RANGEEDGES_OK,
            's_values_before': s_values_before, 's_values_after': s_values_after,
            'da_selecionado': da_selecionado, 'ds_selecionado': ds_selecionado,
            'evidencia': f"origem {origem} selecionada por coordenada exata (RANGEEDGES devolveu "
                          f"{len(s_values_before)} valor(es) na janela: {s_values_before!r}; "
                          f"selecionado exclusivamente {s_values_after!r})."}


def _avaliar_selecao_inicializacao(ds, rota):
    """Seção 3/4/5 — nunca usa `ds[dim_s].values.flat[0]` de um eixo S
    GLOBAL como origem observada. Inspeciona a coordenada S tal como
    associada à variável REAL de precipitação (`rota.variable_name`):

    1/2/3. S presente em `da.coords` com exatamente 1 valor (scalar ou
       coordenada/dimensão singleton) -> lê esse único valor -> OK.
    4. S presente em `da.coords`/`da.dims` com MAIS de 1 valor -> o
       subset de origem não ocorreu de fato -> FAIL (contradição).
    5. S ausente de `da.coords` por completo (Ingrid VALUE pode ter
       removido a dimensão) -> registra REQUEST_CONFIRMED_SELECTION
       como evidência DOCUMENTAL apenas (nunca empírica) quando
       `rota.ingrid_value_init_selection_documented=True` — fica
       UNCONFIRMED_VALUE_UNVERIFIED até uma consulta de controle
       independente confirmar (Seção 3, chamada de fora desta função
       pura, que não tem acesso à rede); sem documentação nenhuma,
       UNCONFIRMED_NO_INIT_COORD — nunca cai para o eixo global como
       substituto."""
    dim_s = getattr(rota, 'init_dimension', None) or 'S'
    nome_var = getattr(rota, 'variable_name', None)
    da = ds[nome_var] if nome_var and hasattr(ds, 'variables') and nome_var in ds.variables else None
    # audit-only — nunca usado para decidir pass/fail (Seção 6, item A-E
    # atualizado não exige mais isso como requisito próprio).
    standard_name_s = (da.coords[dim_s].attrs.get('standard_name')
                        if da is not None and dim_s in getattr(da, 'coords', {}) else None)

    if da is None or dim_s not in getattr(da, 'coords', {}):
        if getattr(rota, 'ingrid_value_init_selection_documented', False):
            return {'init_selection_method': INIT_SELECTION_METHOD_REQUEST_CONFIRMED_SELECTION,
                    'init_value_observed_on_variable': None,
                    'init_axis_size_observed_on_variable': 0,
                    'init_selection_status': INIT_SELECTION_STATUS_UNCONFIRMED_VALUE_UNVERIFIED,
                    'init_periodo_observado': None, 'standard_name_s_observed': standard_name_s}
        return {'init_selection_method': INIT_SELECTION_METHOD_NONE,
                'init_value_observed_on_variable': None,
                'init_axis_size_observed_on_variable': 0,
                'init_selection_status': INIT_SELECTION_STATUS_UNCONFIRMED_NO_COORD,
                'init_periodo_observado': None, 'standard_name_s_observed': standard_name_s}

    s_coord = da.coords[dim_s]
    tamanho = int(s_coord.size)
    if tamanho > 1:
        # Revisão pós-execução #4 (investigação da run 36028568952,
        # item 5) — quando há mais de 1 inicialização, o diagnóstico
        # precisa dos VALORES observados (nunca só a contagem) para
        # nunca escolher o primeiro automaticamente. `str(v)[:7]` seria
        # ambíguo/perderia precisão para calendários não-padrão; guarda
        # a representação bruta de cada elemento do eixo, na ordem
        # observada, sem qualquer seleção implícita.
        try:
            valores_brutos_multiplos = [str(v) for v in np.asarray(s_coord.values).ravel().tolist()]
        except Exception:
            valores_brutos_multiplos = []
        return {'init_selection_method': INIT_SELECTION_METHOD_NONE,
                'init_value_observed_on_variable': None,
                'init_axis_size_observed_on_variable': tamanho,
                'init_selection_status': INIT_SELECTION_STATUS_FAIL_MULTIPLE,
                'init_periodo_observado': None, 'standard_name_s_observed': standard_name_s,
                'init_values_observed_on_variable_multiplos': valores_brutos_multiplos}

    try:
        bruto = np.asarray(s_coord.values).flat[0]
        periodo_observado = pd.Period(str(bruto)[:7], 'M')
    except Exception:
        return {'init_selection_method': INIT_SELECTION_METHOD_NONE,
                'init_value_observed_on_variable': None,
                'init_axis_size_observed_on_variable': tamanho,
                'init_selection_status': INIT_SELECTION_STATUS_UNCONFIRMED_NO_COORD,
                'standard_name_s_observed': standard_name_s,
                'init_periodo_observado': None}

    if dim_s in da.dims:
        metodo, status = INIT_SELECTION_METHOD_SINGLETON_DIM, INIT_SELECTION_STATUS_OK_SINGLETON_DIM
    else:
        metodo, status = INIT_SELECTION_METHOD_SCALAR_COORD, INIT_SELECTION_STATUS_OK_SCALAR
    return {'init_selection_method': metodo,
            'init_value_observed_on_variable': str(periodo_observado),
            'init_axis_size_observed_on_variable': tamanho,
            'init_selection_status': status,
            'standard_name_s_observed': standard_name_s,
            'init_periodo_observado': periodo_observado}


def _avaliar_semantica_forecast_period(ds, rota, h_lead, L_val, init_date, selecao_init=None):
    """Método B (Seção 4/6) — os requisitos A-E são checados de forma
    INDEPENDENTE e objetiva. Distingue duas classes de falha: falta de
    EVIDÊNCIA (units/standard_name ausentes, rota sem documentação, S
    ausente da variável sem confirmação DIRETA concluída — vira
    UNCONFIRMED, nunca uma afirmação) de CONTRADIÇÃO objetiva (S
    observado na variável diverge da origem pedida, múltiplas
    inicializações presentes, ou a grade de L observada diverge da
    esperada — vira MISMATCH, o mesmo tratamento que o Método A já dava
    a uma variável auxiliar discordante).

    Revisão pós-execução #3 (correção 2, risco residual) — a
    comparação indireta de valores de precipitação entre origens
    (nmme_poc.verificar_selecao_ingrid_value_por_consulta_controle)
    NUNCA decide esta classificação sozinha, nem para confirmar nem
    para contradizer: "formatos diferentes não comprovam seleção
    correta; valores divergentes comprovam só que as respostas
    diferem; valores idênticos são um alerta, não prova definitiva"
    (Seção 1). Só uma confirmação DIRETA da origem
    (nmme_poc.tentar_confirmar_origem_diretamente — seleção S/.../.../
    RANGEEDGES que preserva a dimensão, ou metadado confiável) pode
    produzir `INIT_SELECTION_STATUS_OK_INGRID_VALUE_VERIFIED`.

    `selecao_init`, quando informado, é o resultado PRÉ-CALCULADO de
    `_avaliar_selecao_inicializacao` (mais a eventual confirmação
    direta/diagnóstico de controle, computados pelo chamador — que
    precisam de acesso à rede, fora do escopo desta função pura)."""
    dim_l = getattr(rota, 'lead_dimension', None) or 'L'
    insuficientes, contraditorias = [], []

    # E. Inicialização confirmada por coordenada S scalar/singleton
    # associada a 'prec', OU confirmação DIRETA da seleção Ingrid VALUE
    # (Seção 3/4/5/6-E, revisão pós-execução #3, correção 2) — NUNCA
    # pelo eixo S global do Dataset, e NUNCA só pela documentação do
    # operador VALUE ou por comparação indireta de valores.
    selecao_init = selecao_init if selecao_init is not None else _avaliar_selecao_inicializacao(ds, rota)
    status_init = selecao_init['init_selection_status']
    periodo_observado = selecao_init['init_periodo_observado']
    if status_init == INIT_SELECTION_STATUS_FAIL_MULTIPLE:
        contraditorias.append(f"variável {rota.variable_name!r} tem "
                                f"{selecao_init['init_axis_size_observed_on_variable']} valores de S "
                                f"associados — o subset de origem não ocorreu de fato")
    elif status_init in (INIT_SELECTION_STATUS_UNCONFIRMED_NO_COORD,
                          INIT_SELECTION_STATUS_UNCONFIRMED_VALUE_UNVERIFIED):
        if status_init == INIT_SELECTION_STATUS_UNCONFIRMED_VALUE_UNVERIFIED:
            resultado_verificacao = selecao_init.get('init_verification_result') or 'verificação não executada'
            insuficientes.append("S ausente da variável — nem a confirmação direta (RANGEEDGES/metadado) "
                                   "nem o diagnóstico de comparação indireta bastaram para confirmar "
                                   f"empiricamente a origem (Seção 1/2/3/4) — {resultado_verificacao}")
        else:
            insuficientes.append(f"S não pôde ser confirmado como associado à variável "
                                   f"{rota.variable_name!r} (nem scalar/singleton, nem via VALUE "
                                   f"documentado) — Seção 3/5")
    elif status_init == INIT_SELECTION_STATUS_OK_INGRID_VALUE_VERIFIED:
        pass   # confirmado empiricamente por confirmação DIRETA da origem — nada a comparar
    elif periodo_observado != init_date:
        contraditorias.append(f"S observado na variável {rota.variable_name!r} ({periodo_observado}) "
                                f"diverge da origem pedida ({init_date})")

    # 3/4. L identificado como forecast_period/forecast lead, com
    # unidade 'months'.
    l_attrs = dict(ds[dim_l].attrs) if dim_l in getattr(ds, 'coords', {}) else {}
    l_standard_name = l_attrs.get('standard_name')
    texto_l = ' '.join(str(v) for v in l_attrs.values()).lower()
    l_identificado = (l_standard_name == STANDARD_NAME_L_FORECAST_PERIOD
                       or any(t in texto_l for t in TERMOS_CONFIRMATORIOS_L))
    if not l_identificado:
        insuficientes.append(f"{dim_l}.standard_name={l_standard_name!r}/attrs={l_attrs!r} não "
                               f"identifica forecast_period/forecast lead")
    l_units_observado = l_attrs.get('units')
    if str(l_units_observado).strip().lower() not in LEAD_UNITS_MONTHS_ACEITAS:
        insuficientes.append(f"{dim_l}.units={l_units_observado!r} (esperado 'months')")

    # 5/6. Valores de L observados seguem a grade 0.5,1.5,2.5,... —
    # espaçamento de 1 mês já embutido na própria checagem da grade
    # (dataset mensal).
    try:
        valores_l = sorted(float(v) for v in ds[dim_l].values)
    except Exception:
        valores_l = []
    grade_esperada = [i + 0.5 for i in range(len(valores_l))]
    if not valores_l:
        insuficientes.append(f"não foi possível ler os valores observados de {dim_l}")
    elif valores_l != grade_esperada:
        contraditorias.append(f"grade {dim_l} observada {valores_l} diverge da sequência "
                                f"0.5,1.5,2.5,... esperada")

    # 7. Documentação oficial da coleção IRI/NMME desta ROTA registra
    # essa semântica (nunca aceito por padrão — precisa estar marcado
    # explicitamente no catálogo, com citação em rota.mapping_reference).
    doc_ok = bool(getattr(rota, 'forecast_period_semantics_documented', False))
    if not doc_ok:
        insuficientes.append("rota sem forecast_period_semantics_documented=True no catálogo — "
                               "sem citação de documentação oficial da coleção (Seção 4-#7)")

    if contraditorias:
        status = 'MISMATCH'
    elif insuficientes:
        status = 'UNCONFIRMED'
    else:
        status = 'OK'

    if status == 'OK':
        evidencia = (f"confirmado pela semântica documentada do eixo forecast_period (Método B, Seção "
                      f"4/6): inicialização confirmada via {selecao_init['init_selection_method']} "
                      f"(status={status_init}), {dim_l}.standard_name={l_standard_name!r}/"
                      f"units={l_units_observado!r}, grade {valores_l} mensal confirmada, rota com "
                      f"forecast_period_semantics_documented=True.")
    else:
        motivos = contraditorias + insuficientes
        evidencia = (f"Método B (semântica forecast_period) não confirmou H{h_lead}<->L={L_val}: "
                      + '; '.join(motivos) + '.')

    return {'status': status, 'evidence': evidencia,
            'forecast_reference_time_observed': selecao_init.get('standard_name_s_observed'),
            'lead_units_observed': l_units_observado,
            'lead_standard_name_observed': l_standard_name,
            'init_selection_method': selecao_init['init_selection_method'],
            'init_value_requested': str(init_date),
            'init_value_observed_on_variable': selecao_init['init_value_observed_on_variable'],
            'init_axis_size_observed_on_variable': selecao_init['init_axis_size_observed_on_variable'],
            'init_selection_status': status_init}


def avaliar_mapeamento_temporal(ds, h_lead, init_date, esquema='lead1_igual_mes_inicializacao',
                                  time_decode_mode=None, rota=None, selecao_init=None):
    """`selecao_init`, quando informado, é repassado para
    `_avaliar_semantica_forecast_period` (Seção 3, revisão pós-execução
    #3) — permite ao chamador computar a verificação de controle
    independente UMA VEZ por execução (não por lead, já que S não varia
    por lead) fora desta função pura."""
    sys.path.insert(0, str(Path(__file__).parent))
    import nmme_download as ndl
    L_val = ndl.h_lead_para_L_ingrid(h_lead)
    target_hipotese = leadtime_para_mes_alvo_nmme(init_date, h_lead, esquema)

    evidencia = []
    mapping_status = 'UNCONFIRMED'
    mapping_confirmation_method = MAPPING_METHOD_NONE
    forecast_reference_time_observed = lead_units_observed = lead_standard_name_observed = None
    init_selection_method = INIT_SELECTION_METHOD_NONE
    init_value_observed_on_variable = None
    init_axis_size_observed_on_variable = None
    init_selection_status = None

    # Seção 2/8 — em RAW_NUMERIC_CF (decode_times=False) os valores de
    # tempo do dataset são numéricos crus, sem decodificação de
    # calendário; tentar interpretá-los como data seria adivinhação, não
    # confirmação. Retorna UNCONFIRMED por DESENHO aqui, nunca por
    # acidente de um parse que falhou (a barreira preexistente não pode
    # depender de um efeito colateral de tipo).
    if time_decode_mode == TIME_DECODE_MODE_RAW_NUMERIC_CF:
        evidencia.append("dataset aberto em modo RAW_NUMERIC_CF (decode_times=False, fallback de "
                          "decodificação temporal — Seção 1/2) — valores de tempo permanecem "
                          "numéricos crus, sem decodificação de calendário; impossível confirmar "
                          "target_month a partir deles. Mapeamento permanece UNCONFIRMED por "
                          "desenho, nunca afrouxado (Seção 2/8).")
        return {'source_L': L_val, 'target_month': str(target_hipotese), 'mapping_status': 'UNCONFIRMED',
                'evidence': ' | '.join(evidencia),
                'mapping_confirmation_method': MAPPING_METHOD_NONE,
                'forecast_reference_time_observed': None, 'lead_units_observed': None,
                'lead_standard_name_observed': None,
                'init_selection_method': INIT_SELECTION_METHOD_NONE, 'init_value_requested': str(init_date),
                'init_value_observed_on_variable': None, 'init_axis_size_observed_on_variable': None,
                'init_selection_status': None}

    l_attrs = dict(ds['L'].attrs) if 'L' in getattr(ds, 'coords', {}) else {}
    texto_l = ' '.join(str(v) for v in l_attrs.values()).lower()
    pistas = [t for t in TERMOS_CONFIRMATORIOS_L if t in texto_l]
    if pistas:
        evidencia.append(f"L.attrs contém termo(s) {pistas} — indica semântica de lead/target, mas "
                          f"isso sozinho não confirma o valor exato de H{h_lead} sem uma variável "
                          f"auxiliar de data-alvo.")

    var_alvo = None
    for nome_candidato in NOMES_VARIAVEL_ALVO_CANDIDATOS:
        if hasattr(ds, 'variables') and nome_candidato in ds.variables:
            var_alvo = nome_candidato
            break

    if var_alvo is not None:
        # Método A — variável auxiliar tem PRECEDÊNCIA sobre o Método B
        # sempre que presente (Seção 4, teste #10): nunca consultamos a
        # semântica do eixo quando já existe uma variável de data-alvo
        # explícita para checar diretamente.
        try:
            da_alvo = ds[var_alvo]
            # Seleciona o valor NO L do lead atual, nunca o primeiro do
            # array às cegas (bug real encontrado ao testar: pegar
            # sempre .flat[0] fazia H1 "confirmar" por coincidência e
            # H2-H6 comparar contra o valor de H1, gerando MISMATCH
            # falso em vez de checar o valor correto de cada lead).
            valor_no_lead = da_alvo.sel(L=L_val) if 'L' in getattr(da_alvo, 'dims', ()) else da_alvo
            bruto = np.asarray(valor_no_lead.values).flat[0]
            alvo_real = pd.Period(str(bruto)[:7], 'M')
        except Exception as e:
            evidencia.append(f"variável auxiliar {var_alvo!r} presente mas não pôde ser interpretada "
                              f"como data ({e}) — mapeamento continua UNCONFIRMED.")
        else:
            if alvo_real == target_hipotese:
                mapping_status = 'OK'
                mapping_confirmation_method = MAPPING_METHOD_TARGET_VARIABLE
                evidencia.append(f"variável auxiliar {var_alvo!r} do dataset confirma "
                                  f"target_month={alvo_real}, igual à hipótese H{h_lead}<->L={L_val}.")
            else:
                mapping_status = 'MISMATCH'
                evidencia.append(f"variável auxiliar {var_alvo!r} do dataset indica "
                                  f"target_month={alvo_real}, DIFERENTE da hipótese ({target_hipotese}) "
                                  f"— hipótese H{h_lead}<->L={L_val} contradita pelos metadados.")
    else:
        evidencia.append(f"nenhuma variável auxiliar de data-alvo ({NOMES_VARIAVEL_ALVO_CANDIDATOS}) "
                          f"encontrada no dataset aberto — tentando Método B (semântica documentada "
                          f"do eixo forecast_period, Seção 4).")
        resultado_b = _avaliar_semantica_forecast_period(ds, rota, h_lead, L_val, init_date,
                                                            selecao_init=selecao_init)
        forecast_reference_time_observed = resultado_b['forecast_reference_time_observed']
        lead_units_observed = resultado_b['lead_units_observed']
        lead_standard_name_observed = resultado_b['lead_standard_name_observed']
        init_selection_method = resultado_b['init_selection_method']
        init_value_observed_on_variable = resultado_b['init_value_observed_on_variable']
        init_axis_size_observed_on_variable = resultado_b['init_axis_size_observed_on_variable']
        init_selection_status = resultado_b['init_selection_status']
        evidencia.append(resultado_b['evidence'])
        mapping_status = resultado_b['status']
        if mapping_status == 'OK':
            mapping_confirmation_method = MAPPING_METHOD_FORECAST_PERIOD_SEMANTICS

    return {'source_L': L_val, 'target_month': str(target_hipotese), 'mapping_status': mapping_status,
            'evidence': ' | '.join(evidencia),
            'mapping_confirmation_method': mapping_confirmation_method,
            'forecast_reference_time_observed': forecast_reference_time_observed,
            'lead_units_observed': lead_units_observed,
            'lead_standard_name_observed': lead_standard_name_observed,
            'init_selection_method': init_selection_method, 'init_value_requested': str(init_date),
            'init_value_observed_on_variable': init_value_observed_on_variable,
            'init_axis_size_observed_on_variable': init_axis_size_observed_on_variable,
            'init_selection_status': init_selection_status}


def contar_membros_nao_missing(valores_por_membro):
    """Seção 7 — nº de membros com valor válido (não NaN) NO SUBSET
    real aberto; nunca confundido com member_axis_size (tamanho
    declarado do eixo M no catálogo-fonte, que pode incluir posições
    preenchidas com missing/NaN — nunca inferir que M=28 significa 28
    membros válidos)."""
    v = np.asarray(valores_por_membro, dtype=float)
    return int(np.sum(~np.isnan(v)))


# ══════════════════════════════════════════════════════════════════════════
# Revisão final pré-execução (Seção 5) — convenção de longitude REALMENTE
# observada no dataset aberto, nunca copiada do catálogo. Um subset já
# recortado a 1 ponto normalmente não permite inferir a convenção da
# grade inteira (um valor positivo <=180 é ambíguo nas duas convenções)
# — nesse caso o resultado honesto é UNDETERMINED_FROM_POINT_SUBSET,
# nunca uma adivinhação. Só desambigua quando o próprio valor observado
# só é fisicamente possível numa convenção (>180 só existe em 0-360; <0
# só existe em -180/180).
# ══════════════════════════════════════════════════════════════════════════

LON_CONVENTION_0_360 = '0_360'
LON_CONVENTION_NEG180_180 = 'NEG180_180'
LON_CONVENTION_UNDETERMINED = 'UNDETERMINED_FROM_POINT_SUBSET'


def detectar_convencao_longitude_observada(valores_lon):
    """`valores_lon`: array-like com os valores REAIS da coordenada de
    longitude do dataset aberto (idealmente a grade inteira antes do
    subset por ponto; se só houver 1 valor — caso comum de subset já
    recortado — a desambiguação só é possível quando esse valor for
    fisicamente exclusivo de uma convenção)."""
    valores = np.atleast_1d(np.asarray(valores_lon, dtype=float))
    if valores.size == 0:
        return LON_CONVENTION_UNDETERMINED
    if valores.size > 1:
        tem_negativo, tem_maior_180 = bool(np.any(valores < 0)), bool(np.any(valores > 180))
        if tem_negativo and tem_maior_180:
            return LON_CONVENTION_UNDETERMINED   # grade ambígua/mista — nunca assumir
        if tem_negativo:
            return LON_CONVENTION_NEG180_180
        if tem_maior_180:
            return LON_CONVENTION_0_360
        return LON_CONVENTION_UNDETERMINED   # todos os valores em [0,180] — ambíguo nas duas convenções
    v = float(valores[0])
    if v > 180:
        return LON_CONVENTION_0_360
    if v < 0:
        return LON_CONVENTION_NEG180_180
    return LON_CONVENTION_UNDETERMINED   # ponto único em [0,180] — não dá para inferir a convenção
