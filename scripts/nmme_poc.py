#!/usr/bin/env python3
"""
nmme_poc.py — Fase 2C.1/2C.1b: orquestração do catálogo + POC do NMME
(fonte dinâmica sazonal independente do C3S, Fase 2C). `--dry-run-plan`
continua só INFRAESTRUTURA (Seção 38/50, nunca acessa rede).
`--executar-poc-real` (Fase 2C.1b) agora está IMPLEMENTADO de verdade
(executar_poc_real_cfsv2) — só para CFSv2, origem 2005-01, H1-H6 — mas
NÃO foi executado contra a rede real nesta tarefa (Seção 17: implementar
sem rodar); a primeira execução real fica para revisão humana, fora
desta tarefa.

O POC NÃO calcula skill (Seção 18/35-S) — só valida acesso, modelo/
versão corretos, membros, variável, unidade, grade, leads, target
month, parsing e conversão mm/mês. CHIRPS não entra nesta etapa (fica
reservado para a futura Fase 2C.2/2C.3, quando skill for calculada —
Seção 25/26).

Origem do POC (Seção 7, Rodada 4 — trocada de 2015-01 para 2005-01):
2005-01 está DENTRO do S grid nativo EMPIRICALLY_CONFIRMED da Rota B do
CFSv2 (IRI member-level, dez/1981 a mar/2011 — ver
nmme_download.origem_dentro_do_nativo_rota_b/S_NATIVO_INICIO/
S_NATIVO_FIM), diferente de 2015-01, que ficava fora desse período. Para
os outros 6 candidatos (ainda POC_READY_DOCUMENTED/UNCONFIRMED/PARTIAL,
não investigados nesta rodada — Seção 16 da tarefa), a cobertura de
2005-01 permanece pendência a confirmar no POC real, igual valia para
2015-01 antes.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import nmme_catalogo as ncat  # noqa: E402
import nmme_download as ndl  # noqa: E402
import nmme_processar as nproc  # noqa: E402

ROOT = Path(__file__).parent.parent
ARTIFACTS_DIR = ROOT / 'artifacts' / 'nmme_poc'

MUNICIPIO = nproc.MUNICIPIO
LEADS = (1, 2, 3, 4, 5, 6)   # Seção 13 — POC tenta exatamente H1-H6, mesma comparabilidade do C3S.
POC_ORIGEM = (2005, 1)       # Seção 7, Rodada 4 — dentro do S grid nativo da Rota B do CFSv2.

ARTIFACT_FILENAMES = [
    'nmme_model_catalog.csv', 'nmme_common_period.json', 'nmme_poc_raw.csv',
    'nmme_poc_temporal_audit.csv', 'nmme_poc_access_audit.csv', 'metadata.json', 'RELATORIO.md',
]   # Seção 12, Fase 2C.1b: nunca inclui NetCDF/GRIB bruto — só CSV/JSON/MD.


def _origem_str(ano, mes):
    return f'{ano:04d}-{mes:02d}'


def verificar_origem_no_hindcast(sistema, ano, mes):
    """Devolve True/False só quando hindcast_start/hindcast_end estão
    confirmados (evidence != UNCONFIRMED) no catálogo; None quando não
    dá para saber (Seção 17/19 — nunca assumir cobertura por omissão,
    nunca reprovar por omissão também: None é uma pendência explícita,
    diferente de False)."""
    status_ini = ncat.status_evidencia(sistema, 'hindcast_start')
    status_fim = ncat.status_evidencia(sistema, 'hindcast_end')
    if sistema.hindcast_start is None or sistema.hindcast_end is None or \
            status_ini == ncat.UNCONFIRMED or status_fim == ncat.UNCONFIRMED:
        return None
    return sistema.hindcast_start <= ano <= sistema.hindcast_end


def validar_execucao_poc_possivel(sistemas=None):
    """Seção 13 (correção pós-revisão; ampliada na Rodada 4/Seção 13) —
    o POC real só pode rodar se pelo menos 1 sistema tiver
    data_access_status em {CONFIRMED, POC_READY_DOCUMENTED} (endpoint +
    variável + TODAS as dimensões documentadas com evidência forte o
    bastante para um request auditável — Seção 4/7/8). NÃO exige 7/7 —
    só que a lista não esteja vazia. Levanta RuntimeError explícito caso
    contrário — nunca inventa acesso para poder seguir adiante. Nota:
    isto é mais permissivo que sistemas_poc_executaveis (CONFIRMED
    puro) de propósito — POC_READY_DOCUMENTED autoriza uma TENTATIVA
    real controlada, não afirma que ela vai ter sucesso (Seção 4)."""
    sistemas = sistemas if sistemas is not None else ncat.CATALOGO
    prontos = ncat.sistemas_poc_prontos_para_teste_real(sistemas)
    if not prontos:
        raise RuntimeError(
            "Nenhum sistema do catálogo está pronto para uma tentativa real — nenhum tem "
            "data_access_status em {CONFIRMED, POC_READY_DOCUMENTED} (endpoint + variável + todas as "
            "dimensões documentadas o bastante para um request auditável, Seção 4/7/8). O POC real "
            "não pode rodar sobre um endpoint adivinhado (Seção 13). Investigar/confirmar pelo menos 1 "
            "endpoint antes de tentar executar.")
    return prontos


# ══════════════════════════════════════════════════════════════════════════
# Seção 17/38 — plano do POC, nunca acessa rede.
# ══════════════════════════════════════════════════════════════════════════

def plano_poc(sistemas=None, origem=POC_ORIGEM, leads=LEADS):
    sistemas = sistemas if sistemas is not None else ncat.CATALOGO
    ano, mes = origem
    info = []
    for s in sistemas:
        cobertura = verificar_origem_no_hindcast(s, ano, mes)
        info.append({
            'centre': s.centre, 'model_name': s.model_name,
            'availability_status': s.availability_status,
            'data_access_status': s.data_access_status,
            'origem_dentro_do_hindcast_confirmado': cobertura,
            'hindcast_members_documentado': s.hindcast_members,
            'data_url_template_confirmado': s.data_url_template is not None,
            'precip_variable_confirmado': s.precip_variable is not None,
        })
    n_candidatos = len([s for s in sistemas if s.availability_status == ncat.STATUS_CANDIDATO])
    executaveis = ncat.sistemas_poc_executaveis(sistemas)
    nao_executaveis = ncat.sistemas_poc_nao_executaveis(sistemas)
    prontos_teste_real = ncat.sistemas_poc_prontos_para_teste_real(sistemas)
    nao_prontos_teste_real = [s for s in sistemas if s not in prontos_teste_real]
    cp = ncat.common_period_json(sistemas)
    return {
        'origem_poc': _origem_str(ano, mes), 'leads': list(leads), 'municipio': MUNICIPIO,
        'n_modelos_candidatos_documentados': n_candidatos,
        'n_modelos_poc_executaveis': len(executaveis),
        'modelos_poc_executaveis': [f'{s.centre}/{s.model_name}' for s in executaveis],
        'modelos_poc_nao_executaveis': [
            {'sistema': f'{s.centre}/{s.model_name}', 'motivo': s.data_access_status} for s in nao_executaveis
        ],
        # Seção 4/12/13, Rodada 4 — degrau de "pronto para uma tentativa
        # real controlada" (CONFIRMED ∪ POC_READY_DOCUMENTED), mais
        # amplo que modelos_poc_executaveis (CONFIRMED puro).
        'n_modelos_poc_prontos_para_teste_real': len(prontos_teste_real),
        'modelos_poc_prontos_para_teste_real': [f'{s.centre}/{s.model_name}' for s in prontos_teste_real],
        'modelos_poc_ainda_nao_prontos': [
            {'sistema': f'{s.centre}/{s.model_name}', 'motivo': s.data_access_status}
            for s in nao_prontos_teste_real
        ],
        'periodo_comum_documentado': f"{cp['common_start']}-{cp['common_end']}" if cp['common_start']
        else 'UNCONFIRMED',
        'requests_previstos': len(prontos_teste_real),
        'modelos': info, 'artifacts_esperados': ARTIFACT_FILENAMES,
        'aviso': 'POC de infraestrutura (Seção 18/35-S) — nunca calcula skill. Só valida acesso/'
                 'modelo/versão/membros/variável/unidade/grade/leads/target month/parsing/conversão. '
                 'Lista executável pode legitimamente vir vazia nesta etapa (Seção 13) — não é erro. '
                 'modelos_poc_prontos_para_teste_real != já empiricamente confirmado (Seção 4).',
    }


def imprimir_plano(plano):
    print("=== NMME Catálogo + POC (Fase 2C.1) — DRY RUN PLAN (nenhum acesso à rede NMME) ===")
    for chave, valor in plano.items():
        if chave == 'modelos':
            print(f"  {chave}:")
            for m in valor:
                print(f"    - {m['centre']}/{m['model_name']}: status={m['availability_status']}, "
                      f"data_access={m['data_access_status']}, "
                      f"origem_no_hindcast={m['origem_dentro_do_hindcast_confirmado']}, "
                      f"membros_doc={m['hindcast_members_documentado']}, "
                      f"url_confirmada={m['data_url_template_confirmado']}, "
                      f"variavel_confirmada={m['precip_variable_confirmado']}")
        elif chave in ('modelos_poc_nao_executaveis', 'modelos_poc_ainda_nao_prontos'):
            print(f"  {chave}:")
            for m in valor:
                print(f"    - {m['sistema']}: {m['motivo']}")
        else:
            print(f"  {chave}: {valor}")


# ══════════════════════════════════════════════════════════════════════════
# Processamento de 1 origem x 1 modelo — assume `ds` já aberto (xarray
# Dataset), para ser testável com dado sintético sem rede (Seção 38: o
# download real não acontece nesta tarefa). Convenção de dimensões
# X/Y/S/L/M é o padrão público "ingrid" da IRIDL (start/lead/member) —
# documentado publicamente, mas NÃO confirmado contra um arquivo NMME
# real nesta sessão (Seção 9/13). Barreiras explícitas em cada etapa —
# nunca segue adiante com suposição não verificável no próprio dataset.
# ══════════════════════════════════════════════════════════════════════════

def processar_origem_modelo(sistema, ano, mes, ds, esquema_temporal='lead1_igual_mes_inicializacao',
                             leads=LEADS, municipio=MUNICIPIO, source_url='', source_type='NetCDF/IRIDL',
                             mapa_lead_para_L=None, membros_esperados_min=None, membros_esperados_max=None):
    """`mapa_lead_para_L` (Seção 8, Rodada 4): callable opcional
    H-lead -> valor L real do grid da fonte (ex.:
    nmme_download.h_lead_para_L_ingrid, para a Rota B do CFSv2, cujo L
    nativo é 0.5/1.5/.../9.5, não 1/2/3...). None (default) mantém o
    comportamento original — `L=lead` direto — para fontes cujo L já é
    inteiro; NUNCA arredonda silenciosamente (Seção 8 da tarefa).

    `membros_esperados_min`/`max` (Seção 5, Rodada 4): quando ao menos
    um dos dois é informado, a contagem de membros é validada contra
    essa FAIXA em vez de exigir igualdade exata com
    sistema.hindcast_members — usado pela Rota B do CFSv2, cujo dado
    bruto pode legitimamente ter entre 24 e 28 membros conforme o
    período (nunca hardcodar um valor único para esse caso)."""
    from _c3s_utils import MUNICIPIOS
    info = MUNICIPIOS[municipio]
    lat, lon = info['lat'], info['lon']
    init_date = pd.Period(f'{ano}-{mes:02d}', 'M')

    var_precip = nproc.validar_variavel_precipitacao(list(ds.data_vars))
    da = ds[var_precip]
    unidade = da.attrs.get('units')
    if not unidade:
        raise RuntimeError(f"[{sistema.centre}/{sistema.model_name} {_origem_str(ano, mes)}] variável "
                            f"{var_precip!r} sem atributo 'units' no metadata — FALHANDO em vez de "
                            f"assumir (Seção 12).")

    if 'X' in da.dims and 'Y' in da.dims:
        ponto = da.sel(X=lon, Y=lat, method='nearest')
        selected_lon, selected_lat = float(ponto['X'].item()), float(ponto['Y'].item())
    elif 'lon' in da.dims and 'lat' in da.dims:
        ponto = da.sel(lon=lon, lat=lat, method='nearest')
        selected_lon, selected_lat = float(ponto['lon'].item()), float(ponto['lat'].item())
    else:
        raise RuntimeError(f"[{sistema.centre}/{sistema.model_name} {_origem_str(ano, mes)}] dataset "
                            f"sem dimensões espaciais reconhecidas (esperado X/Y ou lon/lat) — "
                            f"dims={list(da.dims)} — FALHANDO.")

    membros = list(ponto['M'].values) if 'M' in ponto.dims else [0]
    n_membros = len(membros)
    if membros_esperados_min is not None or membros_esperados_max is not None:
        lo = membros_esperados_min if membros_esperados_min is not None else membros_esperados_max
        hi = membros_esperados_max if membros_esperados_max is not None else membros_esperados_min
        if not (lo <= n_membros <= hi):
            raise RuntimeError(f"[{sistema.centre}/{sistema.model_name} {_origem_str(ano, mes)}] "
                                f"nº de membros = {n_membros}, fora da faixa aceita [{lo},{hi}] "
                                f"(barreira A — Seção 5, Rodada 4: faixa documentada, não um valor "
                                f"único hardcoded).")
    elif sistema.hindcast_members is not None and n_membros != sistema.hindcast_members:
        raise RuntimeError(f"[{sistema.centre}/{sistema.model_name} {_origem_str(ano, mes)}] "
                            f"nº de membros = {n_membros}, documented_expected "
                            f"{sistema.hindcast_members} (barreira A — nunca aceitar silenciosamente "
                            f"um nº diferente do documentado, Seção 8).")

    raw_linhas, temporal_linhas = [], []
    for lead in leads:
        target_month = nproc.leadtime_para_mes_alvo_nmme(init_date, lead, esquema_temporal)
        L_selecionado = mapa_lead_para_L(lead) if mapa_lead_para_L is not None else lead
        fatia_lead = ponto.sel(L=L_selecionado) if 'L' in ponto.dims else ponto
        for m in membros:
            fatia = fatia_lead.sel(M=m) if 'M' in fatia_lead.dims else fatia_lead
            valor_bruto = float(fatia.item())
            conv = nproc.converter_precip_para_mm_mes(valor_bruto, unidade, target_month)
            raw_linhas.append(nproc.montar_linha_raw(
                sistema, init_date, target_month, lead, m, conv['forecast_prec_mm_month'],
                lat, lon, selected_lat, selected_lon, var_precip, conv['units_original'],
                conv['conversion_applied'], source_url, source_type))
        temporal_linhas.append(nproc.montar_linha_temporal_audit(
            sistema, init_date, lead, target_month,
            initialization_reference=str(init_date),
            source_time_coordinate='S (ingrid)' if 'S' in ponto.dims else 'desconhecida',
            source_lead_coordinate=(f'L (ingrid, H{lead} mapeado para L={L_selecionado} — HIPÓTESE não '
                                     f'validada contra subset real, ver '
                                     f'nmme_download.h_lead_para_L_ingrid, Seção 8)'
                                     if mapa_lead_para_L is not None else
                                     ('L (ingrid)' if 'L' in ponto.dims else 'desconhecida')),
            mapping_status='ASSUMIDO_NAO_VALIDADO',
            notes=f"esquema={esquema_temporal} — convenção C3S replicada por padrão, NUNCA "
                  f"confirmada para NMME nesta sessão (Seção 13)."))

    tabela = pd.DataFrame(raw_linhas)
    nproc.validar_raw(tabela['forecast_prec_mm'].to_numpy(dtype=float))
    temporal_audit = pd.DataFrame(temporal_linhas)

    n_esperado = n_membros * len(leads)
    if len(tabela) != n_esperado:
        raise RuntimeError(f"[{sistema.centre}/{sistema.model_name} {_origem_str(ano, mes)}] "
                            f"{len(tabela)} linhas raw, esperado {n_esperado} (barreira H).")

    metadata_origem = {'n_membros': n_membros, 'n_members_observed': n_membros,
                        'lat_grade': selected_lat, 'lon_grade': selected_lon,
                        'unidade': unidade, 'variavel': var_precip}
    return tabela, temporal_audit, metadata_origem


# ══════════════════════════════════════════════════════════════════════════
# Fase 2C.1b — primeiro POC REAL, só CFSv2 (Seção 1-11). Implementado
# nesta tarefa mas NÃO executado contra a rede real (Seção 17) — testado
# só com baixar_fn/abrir_fn injetados; nenhum teste desta base de código
# toca requests/xarray reais para esta função.
# ══════════════════════════════════════════════════════════════════════════

GRID_DISTANCE_MAX_KM = 200.0   # sanidade de grade (Seção 9) — bem maior que a diagonal de uma célula
                                # 1° (~157km) ou da grade Gaussiana ~0,9375° (~147km), nunca um limite
                                # de skill/qualidade — só detecta erro grosseiro de seleção de ponto.


# ══════════════════════════════════════════════════════════════════════════
# Revisão final pré-execução (Seção 6) — access_audit não pode chamar
# TUDO de SERVICE_UNAVAILABLE. Cada estágio do acesso levanta um tipo
# específico (todos com um atributo .status), e o loop principal usa
# esse atributo para classificar a linha do audit — nunca um "qualquer
# exceção vira indisponibilidade de serviço" genérico.
# ══════════════════════════════════════════════════════════════════════════

class AcessoRotaError(RuntimeError):
    """Base — status default é SERVICE_UNAVAILABLE para qualquer
    exceção que NÃO seja uma das subclasses tipadas abaixo (ex.: erro
    inesperado, timeout genérico do baixar_fn)."""
    status = 'SERVICE_UNAVAILABLE'


class HttpErrorRota(AcessoRotaError):
    status = 'HTTP_ERROR'


class DatasetOpenErrorRota(AcessoRotaError):
    status = 'DATASET_OPEN_ERROR'


class FormatoInvalidoRota(AcessoRotaError):
    status = 'FORMAT_INVALID'


class VariavelInvalidaRota(AcessoRotaError):
    status = 'VARIABLE_INVALID'


class UnidadeInvalidaRota(AcessoRotaError):
    status = 'UNITS_INVALID'


class DimensoesInvalidasRota(AcessoRotaError):
    status = 'DIMS_INVALID'


# ══════════════════════════════════════════════════════════════════════════
# Revisão pós-execução #1 (Seção 1/2/6) — execução real encontrou
# DATASET_OPEN_ERROR nas duas representações do IRIDL_LEGACY:
# "unable to decode time units 'months since 1960-01-01' with calendar
# '360'. Try opening your dataset with decode_times=False or installing
# cftime". Isso NÃO é SERVICE_UNAVAILABLE — a URL respondeu, o NetCDF
# foi baixado, só a decodificação de tempo do xarray falhou (calendário
# 360_day sem cftime instalado). `cftime` foi adicionado a
# requirements-c3s.txt (Seção 1) — resolve a maioria dos casos na
# primeira tentativa. Esta função é a segunda linha de defesa: só cai
# para decode_times=False quando a falha for ESPECIFICAMENTE de
# decodificação temporal (nunca um catch-all — Seção 2/10-C).
# ══════════════════════════════════════════════════════════════════════════

def _e_erro_decode_temporal(exc):
    """Reconhece a assinatura do erro de decodificação temporal CF/
    calendar do xarray — a mensagem real observada na execução #1
    sugere explicitamente 'decode_times=False' como saída, e/ou fala em
    decodificar tempo e calendário juntos. Qualquer outro erro (arquivo
    corrompido, HTML de erro salvo como .nc, variável ausente, etc.)
    NÃO casa aqui e segue como DATASET_OPEN_ERROR comum, sem acionar o
    fallback (Seção 6/10-C — nunca um catch-all)."""
    texto = str(exc).lower()
    return 'decode_times=false' in texto or ('decode time' in texto and 'calendar' in texto)


_INFO_CALENDAR_VAZIA = {'calendar_original': None, 'calendar_normalized': None,
                          'calendar_normalization_applied': False}


def abrir_dataset_com_fallback_temporal(caminho, abrir_fn, init_dimension='S'):
    """Seção 1/2/3 (execução real #2, run 35888809240) — primeira
    tentativa é a normal (decode_times padrão, cftime instalado
    decodifica 360_day e outros calendários CF não-padrão de primeira).
    Se a falha for ESPECIFICAMENTE de decodificação temporal, abre de
    novo com decode_times=False só para INSPECIONAR o calendário bruto
    (nunca modifica o arquivo original em disco):

    - Se o calendário observado for um alias LEGADO DOCUMENTADO (Seção
      2, ex.: '360' -> '360_day' — o caso real da execução #2), tenta
      decodificar de novo a partir de uma CÓPIA em memória do dataset
      raw com o atributo `calendar` normalizado
      (`nmme_processar.normalizar_calendar_cf` + `xr.decode_cf`). Se
      funcionar: time_decode_mode=CF_DATETIME_NORMALIZED_ALIAS.
    - Se o calendário não for um alias conhecido, ou a normalização
      também falhar ao decodificar, mantém RAW_NUMERIC_CF (o dataset
      raw, sem decodificação) — nesse modo o mapeamento temporal L<->
      mês-alvo NUNCA é considerado confirmado (Seção 2/8,
      nmme_processar.avaliar_mapeamento_temporal recusa a tentar).

    Devolve (ds, time_decode_mode, info_calendar) — info_calendar traz
    calendar_original/calendar_normalized/calendar_normalization_applied
    SEMPRE que uma normalização foi ao menos tentada (dict vazio caso
    contrário — decodificação normal de primeira, nada para normalizar).
    Se a abertura original falhar por um erro que NÃO é de decodificação
    temporal, a exceção propaga normalmente (DATASET_OPEN_ERROR real no
    chamador, nunca mascarada)."""
    import xarray as xr

    try:
        return abrir_fn(caminho), nproc.TIME_DECODE_MODE_CF_DATETIME, dict(_INFO_CALENDAR_VAZIA)
    except Exception as e:
        if not _e_erro_decode_temporal(e):
            raise
        ds_raw = abrir_fn(caminho, decode_times=False)
        calendar_original = None
        if init_dimension and hasattr(ds_raw, 'variables') and init_dimension in ds_raw.variables:
            calendar_original = ds_raw[init_dimension].attrs.get('calendar')
        calendar_normalized, aplicado = nproc.normalizar_calendar_cf(calendar_original)
        info_calendar = {'calendar_original': calendar_original,
                          'calendar_normalized': calendar_normalized,
                          'calendar_normalization_applied': aplicado}
        if not aplicado:
            return ds_raw, nproc.TIME_DECODE_MODE_RAW_NUMERIC_CF, info_calendar
        # Seção 3 — normaliza numa CÓPIA em memória (nunca o arquivo
        # original): reatribui só o atributo 'calendar' da coordenada de
        # inicialização e tenta decodificar de novo com xr.decode_cf.
        ds_copia = ds_raw.copy(deep=False)
        ds_copia[init_dimension] = ds_copia[init_dimension].assign_attrs(calendar=calendar_normalized)
        try:
            ds_decodificado = xr.decode_cf(ds_copia)
        except Exception:
            return ds_raw, nproc.TIME_DECODE_MODE_RAW_NUMERIC_CF, info_calendar
        return ds_decodificado, nproc.TIME_DECODE_MODE_CF_DATETIME_NORMALIZED_ALIAS, info_calendar


# ══════════════════════════════════════════════════════════════════════════
# Revisão pós-execução #3 (risco residual) — a documentação do operador
# Ingrid VALUE, sozinha, NUNCA prova que o servidor de fato selecionou a
# inicialização pedida quando S é removido da variável 'prec' (só
# demonstra que o operador é DESENHADO para fazer isso). Quando
# `_avaliar_selecao_inicializacao` (nmme_processar.py) devolve
# UNCONFIRMED_VALUE_UNVERIFIED, esta função faz uma consulta de
# CONTROLE mínima — mesma rota, mesmo ponto, mesmos leads, origem
# DIFERENTE da pedida e historicamente disponível — e compara os dados
# retornados: se vierem IDÊNTICOS aos da consulta original, é evidência
# objetiva de que o servidor ignora a seleção de S (o mesmo padrão de
# falha da execução real #3, agora detectado em vez de aceito
# silenciosamente); se divergirem, é evidência objetiva de que o
# servidor de fato diferencia por S. Precisa de baixar_fn/abrir_fn (rede
# real ou dublês injetados nos testes) — por isso vive aqui, fora da
# função pura de avaliação (nmme_processar._avaliar_selecao_
# inicializacao), que só inspeciona um Dataset já aberto.
# ══════════════════════════════════════════════════════════════════════════

def verificar_selecao_ingrid_value_por_consulta_controle(ds_original, rota, sistema, ano, mes, lat, lon,
                                                             leads, baixar_fn, abrir_fn):
    """Nunca decide `poc_status` sozinha — só devolve um veredito
    objetivo (verificado/ignorado/inconclusivo) que
    nmme_processar._avaliar_semantica_forecast_period usa para
    classificar `init_selection_status`. Inconclusiva (consulta de
    controle falhou, sem origem de controle dentro do S grid nativo, ou
    sem valores finitos comparáveis) NUNCA vira confirmação — fica
    UNCONFIRMED_VALUE_UNVERIFIED (Seção 4)."""
    import numpy as np

    origens_tentadas = []
    url_controle = None
    for ano_controle in (ano - 1, ano + 1):
        try:
            url_controle = ndl.montar_url_para_rota(rota, ano_controle, mes, lat, lon, leads[0], leads[-1])
            break
        except ValueError:
            origens_tentadas.append(f'{ano_controle:04d}-{mes:02d}')
            url_controle = None
    if url_controle is None:
        return {'status': nproc.INIT_SELECTION_STATUS_UNCONFIRMED_VALUE_UNVERIFIED,
                'method': 'INGRID_VALUE_CONTROL_QUERY', 'control_url': '',
                'result': f'nenhuma origem de controle dentro do S grid nativo desta rota (tentativas: '
                          f'{origens_tentadas}) — verificação inconclusiva, nunca tratada como '
                          f'confirmação (Seção 4).'}

    destino_controle = ndl.caminho_cache(sistema, rota.data_backend, rota.dataset_representation,
                                            ano_controle, mes, url=url_controle)
    try:
        caminho_controle, _ = baixar_fn(url_controle, destino_controle)
        ds_controle, _, _ = abrir_dataset_com_fallback_temporal(caminho_controle, abrir_fn,
                                                                    rota.init_dimension)
    except Exception as e:
        return {'status': nproc.INIT_SELECTION_STATUS_UNCONFIRMED_VALUE_UNVERIFIED,
                'method': 'INGRID_VALUE_CONTROL_QUERY', 'control_url': url_controle,
                'result': f'consulta de controle falhou ({type(e).__name__}: {e}) — verificação '
                          f'inconclusiva, nunca tratada como confirmação (Seção 4).'}

    if rota.variable_name not in getattr(ds_controle, 'variables', {}):
        return {'status': nproc.INIT_SELECTION_STATUS_UNCONFIRMED_VALUE_UNVERIFIED,
                'method': 'INGRID_VALUE_CONTROL_QUERY', 'control_url': url_controle,
                'result': f'variável {rota.variable_name!r} ausente na resposta de controle — '
                          f'verificação inconclusiva.'}

    try:
        valores_original = np.asarray(ds_original[rota.variable_name].values, dtype=float)
        valores_controle = np.asarray(ds_controle[rota.variable_name].values, dtype=float)
        if valores_original.shape != valores_controle.shape:
            identicos = False   # formas diferentes já bastam como evidência de resposta distinta
        else:
            comparaveis = np.isfinite(valores_original) & np.isfinite(valores_controle)
            if not comparaveis.any():
                return {'status': nproc.INIT_SELECTION_STATUS_UNCONFIRMED_VALUE_UNVERIFIED,
                        'method': 'INGRID_VALUE_CONTROL_QUERY', 'control_url': url_controle,
                        'result': 'nenhum valor finito comparável entre as duas respostas — '
                                  'verificação inconclusiva.'}
            identicos = bool(np.allclose(valores_original[comparaveis], valores_controle[comparaveis]))
    except Exception as e:
        return {'status': nproc.INIT_SELECTION_STATUS_UNCONFIRMED_VALUE_UNVERIFIED,
                'method': 'INGRID_VALUE_CONTROL_QUERY', 'control_url': url_controle,
                'result': f'comparação entre as duas respostas falhou ({type(e).__name__}: {e}) — '
                          f'verificação inconclusiva.'}

    if identicos:
        return {'status': nproc.INIT_SELECTION_STATUS_FAIL_VALUE_IGNORED,
                'method': 'INGRID_VALUE_CONTROL_QUERY', 'control_url': url_controle,
                'result': f'dados da consulta de controle (origem {ano_controle:04d}-{mes:02d}) são '
                          f'IDÊNTICOS aos da consulta original (origem {ano:04d}-{mes:02d}) — '
                          f'evidência objetiva de que o servidor ignorou a seleção de S.'}
    return {'status': nproc.INIT_SELECTION_STATUS_OK_INGRID_VALUE_VERIFIED,
            'method': 'INGRID_VALUE_CONTROL_QUERY', 'control_url': url_controle,
            'result': f'dados da consulta de controle (origem {ano_controle:04d}-{mes:02d}) DIVERGEM '
                      f'dos da consulta original (origem {ano:04d}-{mes:02d}) — evidência objetiva de '
                      f'que o servidor respeita a seleção de S.'}


def validar_acesso_dataset_real(ds, rota):
    """Seção 5/6 — validação EMPÍRICA do dataset aberto de verdade
    contra o que a rota documentava: formato utilizável, variável
    existe, tem 'units' RECONHECIDA pelo conversor, as 5 dimensões
    (S/M/L/X/Y, pelos nomes registrados na rota) estão presentes. Cada
    falha levanta um tipo ESPECÍFICO (Seção 6) — nunca um RuntimeError
    genérico que o access_audit só saberia rotular como
    SERVICE_UNAVAILABLE."""
    try:
        nomes_disponiveis = list(ds.data_vars)
    except Exception as e:
        raise FormatoInvalidoRota(f"dataset aberto não tem a estrutura esperada (sem data_vars "
                                    f"utilizável) — {type(e).__name__}: {e}.") from e
    var_encontrada = next((c for c in (rota.variable_name, rota.variable_name.lower(),
                                        rota.variable_name.upper()) if c in nomes_disponiveis), None)
    if var_encontrada is None:
        raise VariavelInvalidaRota(f"variável {rota.variable_name!r} (documentada no catálogo para "
                                     f"esta rota) não encontrada no dataset real — disponíveis: "
                                     f"{nomes_disponiveis} (Seção 5).")
    da = ds[var_encontrada]
    units_observado = da.attrs.get('units')
    if not units_observado:
        raise UnidadeInvalidaRota(f"variável {var_encontrada!r} sem atributo 'units' no dataset real "
                                    f"— FALHANDO em vez de assumir (Seção 5/8).")
    dims_esperadas = {rota.member_dimension, rota.lead_dimension, rota.init_dimension,
                      rota.lat_dimension, rota.lon_dimension}
    presentes = set(da.dims) | set(ds.coords) | set(ds.variables)
    dims_faltando = dims_esperadas - presentes
    if dims_faltando:
        raise DimensoesInvalidasRota(f"dimensões esperadas {sorted(dims_esperadas)} não encontradas "
                                       f"no dataset real (faltando {sorted(dims_faltando)}, "
                                       f"disponíveis {sorted(presentes)}) — Seção 5.")
    # Seção 8 — só aceita unidade explicitamente reconhecida pelo
    # conversor; checado aqui (não só na conversão por lead) para que
    # uma unidade não reconhecida acione o MESMO fallback de rota que
    # qualquer outro problema de acesso/formato (Seção 3), em vez de
    # derrubar o processamento no meio de um lead.
    unidades_reconhecidas = ({u.lower() for u in nproc.UNIDADES_MM_DIA_ACEITAS} |
                              {u.lower() for u in nproc.UNIDADES_KG_M2_S_ACEITAS})
    if str(units_observado).strip().lower() not in unidades_reconhecidas:
        raise UnidadeInvalidaRota(f"unidade {units_observado!r} da variável {var_encontrada!r} não é "
                                    f"reconhecida pelo conversor (Seção 8) — aceitas: mm/day-like ou "
                                    f"kg m-2 s-1-like.")
    return {'variable_observed': var_encontrada, 'units_observed': units_observado,
            'dims_observed': sorted(set(da.dims))}


# ══════════════════════════════════════════════════════════════════════════
# Revisão final pré-execução (Seção 2) — política de validação de
# membros POR REPRESENTAÇÃO, nunca genérica. Substitui o antigo
# 'raw_df.member.nunique() > 0' (permissivo demais) e o
# raw_completo tautológico (RAW era construído dos próprios membros
# contados, então len(raw)==soma(contados) é verdade por construção e
# nunca prova completude do ensemble).
# ══════════════════════════════════════════════════════════════════════════

MEMBERS_POLICY_HARMONIZED = 'HARMONIZED_EXACT_24'
MEMBERS_POLICY_RAW_NATIVE = 'RAW_NATIVE_RANGE_24_28'
MEMBERS_POLICY_UNDEFINED = 'UNDEFINED_EXACT_AXIS'

MEMBERS_STATUS_OK = 'OK'
MEMBERS_STATUS_FAIL = 'FAIL'


def validar_membros_poc(rota, member_ids_axis, member_count_non_missing_por_lead,
                          member_ids_non_missing_by_lead):
    """Seção 2/3 (revisão final) — barreira de completude do ensemble
    INDEPENDENTE da contagem de linhas RAW: valida o eixo M observado
    contra o documentado e a contagem por lead contra a política da
    REPRESENTAÇÃO, antes de qualquer cálculo de n_raw_expected (Seção
    1 — 'primeiro validamos a completude mínima esperada da fonte;
    depois contamos linhas').

    NMME_HARMONIZED_MONTHLY: eixo esperado=documentado=24; eixo
    observado deve ser EXATAMENTE 24; cada lead deve ter EXATAMENTE 24
    membros não-missing — qualquer lead abaixo disso reprova.

    RAW_NATIVE_ENSEMBLE: eixo esperado=documentado=28; eixo observado
    deve ser EXATAMENTE 28; cada lead deve ter entre 24 e 28
    (inclusive) membros não-missing — nunca abaixo de 24, nunca exige
    28 fixo (Seção 7: 'historicamente podem existir 24-28 membros
    efetivos')."""
    axis_expected = rota.member_axis_size
    axis_observed = len(member_ids_axis)

    if rota.dataset_representation == ncat.REPR_NMME_HARMONIZED_MONTHLY:
        policy = MEMBERS_POLICY_HARMONIZED
        axis_ok = axis_observed == axis_expected == 24
        por_lead_ok = [n == 24 for n in member_count_non_missing_por_lead]
    elif rota.dataset_representation == ncat.REPR_RAW_NATIVE_ENSEMBLE:
        policy = MEMBERS_POLICY_RAW_NATIVE
        axis_ok = axis_observed == axis_expected == 28
        por_lead_ok = [24 <= n <= 28 for n in member_count_non_missing_por_lead]
    else:
        # Sem política específica documentada (ex.: uma futura rota
        # CCSR) — default conservador: exige igualdade exata com o
        # eixo declarado no catálogo em cada lead, nunca inventa uma
        # faixa de tolerância sem base documental.
        policy = MEMBERS_POLICY_UNDEFINED
        axis_ok = axis_observed == axis_expected
        por_lead_ok = [n == axis_expected for n in member_count_non_missing_por_lead]

    status = (MEMBERS_STATUS_OK if axis_ok and por_lead_ok and all(por_lead_ok)
              else MEMBERS_STATUS_FAIL)

    return {
        'member_axis_size_expected': axis_expected,
        'member_axis_size_observed': axis_observed,
        'member_count_non_missing_por_lead': list(member_count_non_missing_por_lead),
        'member_ids_axis': list(member_ids_axis),
        'member_ids_non_missing_by_lead': list(member_ids_non_missing_by_lead),
        'members_expected_policy': policy,
        'members_axis_size_ok': bool(axis_ok),
        'members_count_per_lead_ok': list(por_lead_ok),
        'members_status': status,
    }


def executar_poc_real_cfsv2(origem=POC_ORIGEM, leads=LEADS, municipio=MUNICIPIO, sistema=None,
                              esquema_temporal='lead1_igual_mes_inicializacao',
                              baixar_fn=None, abrir_fn=None):
    """Seção 1-11 (Fase 2C.1b) — primeiro POC REAL, só CFSv2, origem
    2005-01, H1-H6. Tenta as rotas na ordem de
    nmme_download.ordem_tentativa_member_level (CCSR se pronta;
    Representação B preferida; Representação A como fallback explícito
    se B falhar por acesso — Seção 2/3, NUNCA silencioso). Nunca
    calcula skill, nunca usa CHIRPS, nunca baixa série histórica
    completa nem o globo (Seção 4). Devolve um dict de resultado —
    nunca levanta por SERVICE_UNAVAILABLE (Seção 15: reprova o acesso
    explicitamente em vez de propagar uma exceção não tratada)."""
    from _c3s_utils import MUNICIPIOS
    import numpy as np

    sistema = sistema or ncat.sistema_por_nome('NOAA_NCEP', 'CFSv2')
    baixar_fn = baixar_fn or ndl.baixar_arquivo
    if abrir_fn is None:
        import xarray as xr
        abrir_fn = xr.open_dataset
    ano, mes = origem
    info_muni = MUNICIPIOS[municipio]
    lat, lon = info_muni['lat'], info_muni['lon']

    ordem = ndl.ordem_tentativa_member_level(sistema)
    backend_requested = ordem[0].data_backend
    representation_requested = ordem[0].dataset_representation

    access_audit_linhas = []
    ds = fatos = rota_usada = url_usada = None
    time_decode_mode_usada = calendar_observed_usada = time_units_observed_usada = ''
    calendar_original_usada = calendar_normalized_usada = None
    calendar_normalization_applied_usada = False
    for rota in ordem:
        url = destino = None
        cache_hit = False
        download_status = dataset_open_status = 'NAO_TENTADO'
        time_decode_mode = calendar_observed = time_units_observed = ''
        info_calendar = dict(_INFO_CALENDAR_VAZIA)
        try:
            if rota.data_backend == ncat.SOURCE_BACKEND_CCSR_BETA:
                raise AcessoRotaError(f"CCSR_BETA está {rota.status} — não tentado (Seção 12).")
            url = ndl.montar_url_para_rota(rota, ano, mes, lat, lon, leads[0], leads[-1])
            # Seção 3/4 (revisão pós-execução #1) — path de cache
            # INDEPENDENTE por backend+representação (nunca mais
            # compartilhado entre Representação A e B do mesmo mês, que
            # produzem dados diferentes), com hash da URL como defesa
            # extra.
            destino = ndl.caminho_cache(sistema, rota.data_backend, rota.dataset_representation,
                                          ano, mes, url=url)
            try:
                caminho, cache_hit = baixar_fn(url, destino)
                download_status = 'OK'
            except AcessoRotaError as e:
                download_status = e.status
                raise
            except Exception as e:
                download_status = 'HTTP_ERROR'
                raise HttpErrorRota(f"{type(e).__name__}: {e}") from e
            try:
                ds_tentativa, time_decode_mode, info_calendar = abrir_dataset_com_fallback_temporal(
                    caminho, abrir_fn, rota.init_dimension)
                dataset_open_status = 'OK'
            except AcessoRotaError as e:
                dataset_open_status = e.status
                raise
            except Exception as e:
                dataset_open_status = 'DATASET_OPEN_ERROR'
                raise DatasetOpenErrorRota(f"{type(e).__name__}: {e}") from e
            # Seção 7 — calendário/unidades de tempo REALMENTE
            # observados no dataset aberto, registrados ANTES de
            # qualquer validação subsequente poder reprovar a rota (nunca
            # perder essa informação de auditoria mesmo se a rota for
            # descartada por outro motivo abaixo).
            metadata_temporal = nproc.inspecionar_metadata_temporal(ds_tentativa, rota.init_dimension)
            calendar_observed = metadata_temporal['calendar_observed']
            time_units_observed = metadata_temporal['time_units_observed']
            fatos_tentativa = validar_acesso_dataset_real(ds_tentativa, rota)
        except Exception as e:
            status = getattr(e, 'status', 'SERVICE_UNAVAILABLE')
            access_audit_linhas.append({
                'backend': rota.data_backend, 'dataset_representation': rota.dataset_representation,
                'source_url': url or '', 'status': status, 'cache_hit': cache_hit,
                'cache_path': str(destino) if destino else '',
                'download_status': download_status, 'dataset_open_status': dataset_open_status,
                'time_decode_mode': time_decode_mode, 'calendar_observed': calendar_observed,
                'time_units_observed': time_units_observed,
                'calendar_original': info_calendar['calendar_original'],
                'calendar_normalized': info_calendar['calendar_normalized'],
                'calendar_normalization_applied': info_calendar['calendar_normalization_applied'],
                'motivo': f'{type(e).__name__}: {e}'})
            continue
        access_audit_linhas.append({
            'backend': rota.data_backend, 'dataset_representation': rota.dataset_representation,
            'source_url': url, 'status': 'OK', 'cache_hit': cache_hit,
            'cache_path': str(destino) if destino else '',
            'download_status': download_status, 'dataset_open_status': dataset_open_status,
            'time_decode_mode': time_decode_mode, 'calendar_observed': calendar_observed,
            'time_units_observed': time_units_observed,
            'calendar_original': info_calendar['calendar_original'],
            'calendar_normalized': info_calendar['calendar_normalized'],
            'calendar_normalization_applied': info_calendar['calendar_normalization_applied'],
            'motivo': ''})
        ds, fatos, rota_usada, url_usada = ds_tentativa, fatos_tentativa, rota, url
        time_decode_mode_usada = time_decode_mode
        calendar_observed_usada = calendar_observed
        time_units_observed_usada = time_units_observed
        calendar_original_usada = info_calendar['calendar_original']
        calendar_normalized_usada = info_calendar['calendar_normalized']
        calendar_normalization_applied_usada = info_calendar['calendar_normalization_applied']
        break

    access_audit_df = pd.DataFrame(access_audit_linhas)
    resultado_base = {
        'backend_requested': backend_requested, 'dataset_representation_requested': representation_requested,
        'access_audit_df': access_audit_df, 'model': f'{sistema.centre}/{sistema.model_name}',
        'init_date': _origem_str(ano, mes), 'lead_values_requested': list(leads),
    }

    if rota_usada is None:
        return {**resultado_base, 'poc_status': 'REPROVADO_ACESSO', 'backend_used': None,
                'dataset_representation_used': None, 'backend_fallback_ocorreu': len(ordem) > 1,
                'fallback_reason': 'SERVICE_UNAVAILABLE em todas as rotas tentadas — nunca contornado '
                                    'com scraping ou URL inventada (Seção 15).',
                'representation_changed': False, 'raw_df': pd.DataFrame(),
                'temporal_audit_df': pd.DataFrame(), 'checklist': {}}

    init_date = pd.Period(f'{ano}-{mes:02d}', 'M')
    var_encontrada, units_observado = fatos['variable_observed'], fatos['units_observed']
    da = ds[var_encontrada]

    ponto = da.sel({rota_usada.lon_dimension: lon, rota_usada.lat_dimension: lat}, method='nearest')
    selected_lon = float(ponto[rota_usada.lon_dimension].item())
    selected_lat = float(ponto[rota_usada.lat_dimension].item())
    dist_km = nproc.distancia_km_aprox(lat, lon, selected_lat, selected_lon)

    membros_eixo = (list(ponto[rota_usada.member_dimension].values)
                     if rota_usada.member_dimension in ponto.dims else [0])

    # Seção 3 (revisão pós-execução #3, risco residual) — S não varia
    # por lead, então a seleção de inicialização (e a eventual consulta
    # de controle, que acessa a rede) é computada UMA VEZ por execução,
    # nunca recalculada/reconsultada 6x. Só dispara a consulta de
    # controle quando a via documental (VALUE) não é, sozinha,
    # suficiente — nunca promove UNCONFIRMED_VALUE_UNVERIFIED para OK
    # sem essa verificação (Seção 4).
    selecao_init = nproc._avaliar_selecao_inicializacao(ds, rota_usada)
    if (time_decode_mode_usada != nproc.TIME_DECODE_MODE_RAW_NUMERIC_CF
            and selecao_init['init_selection_status']
            == nproc.INIT_SELECTION_STATUS_UNCONFIRMED_VALUE_UNVERIFIED):
        verificacao = verificar_selecao_ingrid_value_por_consulta_controle(
            ds, rota_usada, sistema, ano, mes, lat, lon, leads, baixar_fn, abrir_fn)
        selecao_init = {**selecao_init,
                         'init_selection_status': verificacao['status'],
                         'init_verification_method': verificacao['method'],
                         'init_verification_control_url': verificacao['control_url'],
                         'init_verification_result': verificacao['result']}

    raw_linhas, temporal_linhas = [], []
    n_validos_por_lead, ids_nao_missing_por_lead = [], []
    mapping_confirmation_methods = []
    forecast_reference_time_observed = lead_units_observed = lead_standard_name_observed = None
    init_selection_method = init_value_observed_on_variable = None
    init_axis_size_observed_on_variable = init_selection_status = None
    init_verification_method = init_verification_control_url = init_verification_result = None
    for lead in leads:
        target_month = nproc.leadtime_para_mes_alvo_nmme(init_date, lead, esquema_temporal)
        mapeamento = nproc.avaliar_mapeamento_temporal(ds, lead, init_date, esquema_temporal,
                                                          time_decode_mode=time_decode_mode_usada,
                                                          rota=rota_usada, selecao_init=selecao_init)
        mapping_confirmation_methods.append(mapeamento['mapping_confirmation_method'])
        if forecast_reference_time_observed is None:
            forecast_reference_time_observed = mapeamento['forecast_reference_time_observed']
        if lead_units_observed is None:
            lead_units_observed = mapeamento['lead_units_observed']
        if lead_standard_name_observed is None:
            lead_standard_name_observed = mapeamento['lead_standard_name_observed']
        if init_selection_method is None:
            init_selection_method = mapeamento['init_selection_method']
        if init_value_observed_on_variable is None:
            init_value_observed_on_variable = mapeamento['init_value_observed_on_variable']
        if init_axis_size_observed_on_variable is None:
            init_axis_size_observed_on_variable = mapeamento['init_axis_size_observed_on_variable']
        if init_selection_status is None:
            init_selection_status = mapeamento['init_selection_status']
        if not init_verification_method:
            init_verification_method = mapeamento['init_verification_method']
        if not init_verification_control_url:
            init_verification_control_url = mapeamento['init_verification_control_url']
        if not init_verification_result:
            init_verification_result = mapeamento['init_verification_result']
        L_sel = mapeamento['source_L']
        fatia_lead = (ponto.sel({rota_usada.lead_dimension: L_sel})
                       if rota_usada.lead_dimension in ponto.dims else ponto)
        valores_brutos = []
        for m in membros_eixo:
            fatia = (fatia_lead.sel({rota_usada.member_dimension: m})
                      if rota_usada.member_dimension in fatia_lead.dims else fatia_lead)
            valores_brutos.append(float(fatia.item()))
        n_validos_por_lead.append(nproc.contar_membros_nao_missing(valores_brutos))
        ids_nao_missing_por_lead.append([m for m, v in zip(membros_eixo, valores_brutos)
                                          if not np.isnan(v)])
        for m, valor_bruto in zip(membros_eixo, valores_brutos):
            if np.isnan(valor_bruto):
                continue   # membro missing nesta origem/lead — nunca vira linha RAW (Seção 7)
            conv = nproc.converter_precip_para_mm_mes(valor_bruto, units_observado, target_month)
            raw_linhas.append(nproc.montar_linha_raw(
                sistema, init_date, target_month, lead, m, conv['forecast_prec_mm_month'],
                lat, lon, selected_lat, selected_lon, var_encontrada, conv['units_original'],
                conv['conversion_applied'], url_usada, f'NetCDF/{rota_usada.data_backend}'))
        temporal_linhas.append({
            'centre': sistema.centre, 'model_name': sistema.model_name, 'init_date': str(init_date),
            'H_lead': int(lead), 'source_L': mapeamento['source_L'],
            'target_month': mapeamento['target_month'], 'mapping_status': mapeamento['mapping_status'],
            'evidence': mapeamento['evidence'],
            'mapping_confirmation_method': mapeamento['mapping_confirmation_method'],
            # Seção 7 (execução real #3) — auditoria da seleção de
            # inicialização por lead: qual método confirmou (ou não) que
            # a variável 'prec' de fato traz a origem pedida.
            'init_selection_method': mapeamento['init_selection_method'],
            'init_value_requested': mapeamento['init_value_requested'],
            'init_value_observed_on_variable': mapeamento['init_value_observed_on_variable'],
            'init_axis_size_observed_on_variable': mapeamento['init_axis_size_observed_on_variable'],
            'init_selection_status': mapeamento['init_selection_status'],
            # Seção 5 (revisão pós-execução #3) — método/URL/resultado
            # da verificação de controle independente (só preenchido
            # quando S foi removido da variável e a via documental por
            # si só não bastou).
            'init_verification_method': mapeamento['init_verification_method'],
            'init_verification_control_url': mapeamento['init_verification_control_url'],
            'init_verification_result': mapeamento['init_verification_result'],
            'notes': f'esquema={esquema_temporal}, representação={rota_usada.dataset_representation}'})

    raw_df = pd.DataFrame(raw_linhas)
    if len(raw_df):
        nproc.validar_raw(raw_df['forecast_prec_mm'].to_numpy(dtype=float))
    temporal_audit_df = pd.DataFrame(temporal_linhas)

    # Seção 2/3 — barreira de completude do ensemble INDEPENDENTE da
    # contagem de linhas RAW (primeiro valida a política da
    # representação; só DEPOIS calcula n_raw_expected — nunca o
    # contrário, senão a igualdade vira tautologia, Seção 1).
    validacao_membros = validar_membros_poc(rota_usada, membros_eixo, n_validos_por_lead,
                                              ids_nao_missing_por_lead)
    if rota_usada.dataset_representation == ncat.REPR_NMME_HARMONIZED_MONTHLY:
        # Seção 1 — DERIVADO de member_axis_size x leads, nunca 144 hardcoded.
        n_raw_expected = rota_usada.member_axis_size * len(leads)
    else:
        # Representação A (e qualquer outra sem política HARMONIZED): soma
        # das contagens observadas — só é uma afirmação de completude
        # porque validacao_membros já checou independentemente que cada
        # contagem está dentro da faixa aceita pela política (Seção 1).
        n_raw_expected = sum(n_validos_por_lead)
    raw_completo = len(raw_df) == n_raw_expected

    # Seção 4 — grade DOCUMENTADA (catálogo) nunca chamada de observada;
    # a forma OBSERVADA vem do subset de fato aberto (tipicamente 1x1,
    # já que o request recorta a 1 ponto).
    grid_shape_documented = rota_usada.grid_shape
    tam_x = ponto.sizes.get(rota_usada.lon_dimension, 1)
    tam_y = ponto.sizes.get(rota_usada.lat_dimension, 1)
    subset_grid_shape_observed = f'{tam_x}x{tam_y}'

    # Seção 5 — convenção de longitude detectada a partir da coordenada
    # REAL do dataset aberto (grade inteira, antes do recorte por
    # ponto, quando disponível) — nunca inventada quando o subset já
    # veio recortado a um único valor ambíguo.
    lon_dim = rota_usada.lon_dimension
    valores_lon_fonte = (da.coords[lon_dim].values if lon_dim in da.coords
                          else [selected_lon])
    longitude_convention = nproc.detectar_convencao_longitude_observada(valores_lon_fonte)

    # Seção 5 (execução real #2) — método de confirmação temporal
    # AGREGADO: quando todos os leads usaram o mesmo método, reporta
    # esse método; 'MIXED' se divergiram entre si (nunca esperado hoje,
    # já que Método A/B é decidido pela mesma presença/ausência de
    # variável auxiliar em TODOS os leads do mesmo dataset — mas nunca
    # assumido silenciosamente).
    metodos_unicos = set(mapping_confirmation_methods)
    mapping_confirmation_method_geral = (metodos_unicos.pop() if len(metodos_unicos) == 1
                                           else ('MIXED' if len(metodos_unicos) > 1
                                                 else nproc.MAPPING_METHOD_NONE))

    return {
        **resultado_base,
        'poc_status': 'PROCESSADO', 'backend_used': rota_usada.data_backend,
        'dataset_representation_used': rota_usada.dataset_representation,
        'backend_fallback_ocorreu': rota_usada.data_backend != backend_requested
                                     or rota_usada.dataset_representation != representation_requested,
        'fallback_reason': ('' if rota_usada.dataset_representation == representation_requested
                             else f'Representação {representation_requested} falhou por acesso — '
                                  f'trocada para {rota_usada.dataset_representation} (Seção 3, '
                                  f'nunca silencioso).'),
        'representation_changed': rota_usada.dataset_representation != representation_requested,
        'source_url': url_usada, 'source_lead_values_observed': sorted(set(
            row['source_L'] for row in temporal_linhas)),
        'member_axis_size': rota_usada.member_axis_size,
        'member_count_non_missing': (n_validos_por_lead[0] if n_validos_por_lead else 0),
        'member_count_non_missing_por_lead': n_validos_por_lead,
        'member_ids_axis': list(membros_eixo),
        'member_ids_non_missing_by_lead': ids_nao_missing_por_lead,
        'members_expected_policy': validacao_membros['members_expected_policy'],
        'members_axis_size_ok': validacao_membros['members_axis_size_ok'],
        'members_count_per_lead_ok': validacao_membros['members_count_per_lead_ok'],
        'members_status': validacao_membros['members_status'],
        'units_observed': units_observado, 'variable_observed': var_encontrada,
        'selected_lat': selected_lat, 'selected_lon': selected_lon, 'grid_distance_km': round(dist_km, 2),
        'grid_shape_documented': grid_shape_documented,
        'subset_grid_shape_observed': subset_grid_shape_observed,
        'longitude_convention': longitude_convention,
        # Seção 1/2/6/7/11 (revisão pós-execução #1) — modo de
        # decodificação temporal realmente usado para abrir o dataset
        # vencedor, e o calendário/unidades observados na coordenada de
        # inicialização. download_status/dataset_open_status ficam
        # 'OK'/'OK' aqui por construção (só chegam a este ponto do
        # código as rotas que abriram com sucesso) — a distinção entre
        # os dois importa no access_audit, por tentativa, inclusive nas
        # que falharam.
        'time_decode_mode': time_decode_mode_usada,
        'calendar_observed': calendar_observed_usada,
        'time_units_observed': time_units_observed_usada,
        'download_status': 'OK', 'dataset_open_status': 'OK',
        # Seção 2/5 (execução real #2, run 35888809240) — calendário
        # ORIGINAL do arquivo vs. NORMALIZADO (alias legado documentado,
        # ex.: '360' -> '360_day') — nunca sobrescreve a informação
        # original, os dois ficam auditáveis lado a lado.
        'calendar_original': calendar_original_usada,
        'calendar_normalized': calendar_normalized_usada,
        'calendar_normalization_applied': calendar_normalization_applied_usada,
        # Seção 4/5 — método de confirmação temporal (Método A por
        # variável auxiliar OU Método B por semântica documentada do
        # eixo forecast_period) e os fatos empíricos que o Método B
        # inspeciona, agregados pela primeira ocorrência não-nula entre
        # os leads (mesmo dataset, mesmos atributos S/L em todos eles).
        'mapping_confirmation_method': mapping_confirmation_method_geral,
        'forecast_reference_time_observed': forecast_reference_time_observed,
        'lead_units_observed': lead_units_observed,
        'lead_standard_name_observed': lead_standard_name_observed,
        # Seção 3/4/5/7 (execução real #3) — origem confirmada via a
        # coordenada S da variável REAL (nunca do eixo S global do
        # Dataset) ou via seleção Ingrid VALUE documentada.
        'init_selection_method': init_selection_method,
        'init_value_requested': _origem_str(ano, mes),
        'init_value_observed_on_variable': init_value_observed_on_variable,
        'init_axis_size_observed_on_variable': init_axis_size_observed_on_variable,
        'init_selection_status': init_selection_status,
        # Seção 3/5 (revisão pós-execução #3, risco residual) — método/
        # URL/resultado da verificação de controle independente que
        # corrobora ou refuta a documentação do operador Ingrid VALUE
        # quando S é removido da variável (nunca confirma só pela
        # documentação — Seção 2/3/4).
        'init_verification_method': init_verification_method,
        'init_verification_control_url': init_verification_control_url,
        'init_verification_result': init_verification_result,
        'mapping_reference': list(rota_usada.mapping_reference),
        'temporal_mapping_status': ('OK' if temporal_audit_df['mapping_status'].eq('OK').all()
                                     else 'UNCONFIRMED'),
        'n_raw_expected': n_raw_expected, 'n_raw': len(raw_df), 'raw_completo': raw_completo,
        'requests_realizados': 1,
        'raw_df': raw_df, 'temporal_audit_df': temporal_audit_df,
    }


def avaliar_aprovacao_poc(resultado):
    """Seção 11 — guardrail de aprovação do POC real. Só aprova se
    TODOS os critérios listados passarem; qualquer falha vira
    REPROVADO_<motivo> explícito, nunca um APROVADO silencioso."""
    import numpy as np
    if resultado.get('poc_status') == 'REPROVADO_ACESSO':
        return {'poc_status': 'REPROVADO_ACESSO',
                'checklist': {'download_bem_sucedido': False}}

    raw_df, temporal_df = resultado['raw_df'], resultado['temporal_audit_df']
    checklist = {
        'download_bem_sucedido': True,
        'um_modelo': True,    # por construção — a função só processa 1 sistema por chamada
        'uma_origem': True,   # idem — 1 origem por chamada
        'h1_a_h6_presentes': bool(len(temporal_df)) and set(temporal_df['H_lead']) == {1, 2, 3, 4, 5, 6},
        'members_status_ok': resultado.get('members_status') == MEMBERS_STATUS_OK,
        'member_axis_size_ok': bool(resultado.get('members_axis_size_ok', False)),
        'member_count_per_lead_ok': (bool(resultado.get('members_count_per_lead_ok'))
                                      and all(resultado.get('members_count_per_lead_ok', []))),
        'sem_duplicata': bool(len(raw_df)) and not raw_df.duplicated(subset=['lead', 'member']).any(),
        'valores_finitos': bool(len(raw_df)) and bool(np.isfinite(raw_df['forecast_prec_mm']).all()),
        'precipitacao_nao_negativa': bool(len(raw_df)) and bool((raw_df['forecast_prec_mm'] >= 0).all()),
        'unidade_confirmada': bool(len(raw_df)) and bool(raw_df['units_original'].notna().all()),
        'grade_confirmada': (bool(len(raw_df))
                              and bool((raw_df['grid_distance_km'] < GRID_DISTANCE_MAX_KM).all())),
        'temporal_mapping_confirmado': (bool(len(temporal_df))
                                          and bool((temporal_df['mapping_status'] == 'OK').all())),
        'raw_completo': bool(resultado.get('raw_completo', False)),
        'nenhum_skill_calculado': True,   # estrutural — este módulo nunca importa métricas de skill
    }
    reprovados = [k for k, v in checklist.items() if not v]
    if reprovados:
        return {'poc_status': f'REPROVADO_{reprovados[0].upper()}', 'motivos_reprovacao': reprovados,
                'checklist': checklist}
    return {'poc_status': 'APROVADO', 'checklist': checklist}


# ══════════════════════════════════════════════════════════════════════════
# Catálogo + metadata + relatório (Seção 32-34) — sempre gerável, nunca
# acessa a rede.
# ══════════════════════════════════════════════════════════════════════════

def escrever_catalogo(sistemas=None):
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    sistemas = sistemas if sistemas is not None else ncat.CATALOGO
    ncat.tabela_catalogo(sistemas).to_csv(ARTIFACTS_DIR / 'nmme_model_catalog.csv', index=False)
    (ARTIFACTS_DIR / 'nmme_common_period.json').write_text(
        json.dumps(ncat.common_period_json(sistemas), indent=2, ensure_ascii=False, default=str))


def montar_metadata(sistemas=None, resultado_poc=None):
    sistemas = sistemas if sistemas is not None else ncat.CATALOGO
    modelos_confirmados = [f'{s.centre}/{s.model_name}' for s in sistemas
                            if all(ncat.status_evidencia(s, c) != ncat.UNCONFIRMED
                                   for c in ('hindcast_start', 'hindcast_end', 'hindcast_members'))]
    modelos_documentados = [f'{s.centre}/{s.model_name}' for s in sistemas
                             if s.availability_status == ncat.STATUS_CANDIDATO]
    modelos_indisponiveis = [f'{s.centre}/{s.model_name}' for s in sistemas
                              if s.availability_status == ncat.STATUS_NAO_HOMOGENEO]
    executaveis = ncat.sistemas_poc_executaveis(sistemas)
    nao_executaveis = ncat.sistemas_poc_nao_executaveis(sistemas)
    prontos_teste_real = ncat.sistemas_poc_prontos_para_teste_real(sistemas)
    cp = ncat.common_period_json(sistemas)
    r = resultado_poc or {}

    # Seção 10, Rodada 5 (correção final) — qual backend/representação
    # SERIA usado (decisão catalog-driven, nunca depende de um POC real
    # ter rodado) vs. o que foi de fato OBSERVADO num subset real
    # (esses últimos ficam NAO_EXECUTADO_NESTA_TAREFA, igual aos outros
    # campos empíricos, até o primeiro POC real abrir um arquivo).
    cfsv2_candidatos = [s for s in sistemas if s.centre == 'NOAA_NCEP' and s.model_name == 'CFSv2']
    if cfsv2_candidatos and cfsv2_candidatos[0].member_level_routes:
        escolha = ndl.escolher_backend_member_level(cfsv2_candidatos[0])
        rota_escolhida = escolha['rota']
        data_backend_used = rota_escolhida.data_backend
        dataset_representation = rota_escolhida.dataset_representation
        legacy_or_current = ('legacy' if rota_escolhida.data_backend == ncat.SOURCE_BACKEND_IRIDL_LEGACY
                              else 'current')
        service_status = rota_escolhida.status
        backend_fallback_ocorreu = escolha['fallback_ocorreu']
        backend_fallback_motivo = escolha['motivo']
    else:
        data_backend_used = dataset_representation = legacy_or_current = service_status = 'NAO_APLICAVEL'
        backend_fallback_ocorreu = False
        backend_fallback_motivo = 'Nenhum sistema com member_level_routes no conjunto avaliado.'

    # Seção 13, Fase 2C.1b — quando um resultado_poc REAL é passado
    # (executar_poc_real_cfsv2 já rodou), os campos empíricos observados
    # substituem a decisão catalog-driven acima (que só descreve o que
    # SERIA usado antes de qualquer tentativa real).
    if 'backend_used' in r:
        data_backend_used = r.get('backend_used') or data_backend_used
        dataset_representation = r.get('dataset_representation_used') or dataset_representation
        legacy_or_current = ('legacy' if data_backend_used == ncat.SOURCE_BACKEND_IRIDL_LEGACY
                              else ('current' if data_backend_used == ncat.SOURCE_BACKEND_CCSR_BETA
                                    else legacy_or_current))
        backend_fallback_ocorreu = r.get('backend_fallback_ocorreu', backend_fallback_ocorreu)
        backend_fallback_motivo = r.get('fallback_reason') or backend_fallback_motivo

    return {
        'fase': '2C.1', 'purpose': 'infrastructure_validation',
        'scientific_evaluation_applicable': False,
        'modelos_documentados': modelos_documentados, 'modelos_confirmados': modelos_confirmados,
        'modelos_indisponiveis': modelos_indisponiveis,
        # Seção 14 (correção pós-revisão) — distinção explícita entre catálogo
        # científico (documentado) e lista executável do POC (acesso confirmado).
        'n_models_documented': len(modelos_documentados),
        'n_models_poc_executable': len(executaveis),
        'models_poc_executable': [f'{s.centre}/{s.model_name}' for s in executaveis],
        'models_data_access_unconfirmed': [f'{s.centre}/{s.model_name}' for s in nao_executaveis
                                            if s.data_access_status == ncat.DATA_ACCESS_UNCONFIRMED],
        'models_data_access_partial': [f'{s.centre}/{s.model_name}' for s in nao_executaveis
                                        if s.data_access_status == ncat.DATA_ACCESS_PARTIAL],
        # Seção 4/12, Rodada 4 — degrau "pronto para teste real"
        # (CONFIRMED ∪ POC_READY_DOCUMENTED), nunca confundido com
        # n_models_poc_executable (CONFIRMED puro, empiricamente aberto).
        'n_models_poc_ready_for_real_test': len(prontos_teste_real),
        'models_poc_ready_for_real_test': [f'{s.centre}/{s.model_name}' for s in prontos_teste_real],
        'models_data_access_poc_ready_documented': [
            f'{s.centre}/{s.model_name}' for s in sistemas
            if s.data_access_status == ncat.DATA_ACCESS_POC_READY_DOCUMENTED],
        'documented_common_period': (f"{cp['common_start']}-{cp['common_end']}"
                                      if cp['common_start'] else 'UNCONFIRMED'),
        'empirically_confirmed_common_period': ('UNCONFIRMED' if cp['n_empirically_confirmed_models'] == 0
                                                  else f"{cp['common_start']}-{cp['common_end']}"),
        'modelo_versions': {f'{s.centre}/{s.model_name}': s.model_version for s in sistemas},
        'current_operational_names': {f'{s.centre}/{s.model_name}': s.current_operational_name
                                       for s in sistemas},
        'periodo_comum': cp,
        'source_endpoints': sorted({s.data_source for s in sistemas}),
        'requests_realizados': r.get('requests_realizados', 0),
        'n_raw': r.get('n_raw', 0),
        'temporal_mapping_status': r.get('temporal_mapping_status', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'units_status': r.get('units_status', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'grid_status': r.get('grid_status', 'NAO_EXECUTADO_NESTA_TAREFA'),
        # Seção 10, Rodada 5 — decisão de backend/representação (catalog-
        # driven, sempre computável) vs. observações empíricas de um
        # subset real (só depois do primeiro POC real, Seção 38/50).
        'data_backend_used': data_backend_used,
        'dataset_representation': dataset_representation,
        'legacy_or_current': legacy_or_current,
        'service_status': service_status,
        'backend_fallback_ocorreu': backend_fallback_ocorreu,
        'backend_fallback_motivo': backend_fallback_motivo,
        'member_axis_observed': r.get('member_axis_size', r.get('member_axis_observed',
                                                                   'NAO_EXECUTADO_NESTA_TAREFA')),
        'member_count_non_missing': r.get('member_count_non_missing', 'NAO_EXECUTADO_NESTA_TAREFA'),
        # Seção 3 (revisão final) — auditabilidade por ID de membro: quais
        # posições do eixo M existem vs. quais têm valor não-missing por lead
        # (para detectar buracos, ex.: M=[1..24] vs. M=[1,2,3,5,...]).
        'member_ids_axis': r.get('member_ids_axis', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'member_ids_non_missing_by_lead': r.get('member_ids_non_missing_by_lead',
                                                  'NAO_EXECUTADO_NESTA_TAREFA'),
        'members_expected_policy': r.get('members_expected_policy', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'members_axis_size_ok': r.get('members_axis_size_ok', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'members_count_per_lead_ok': r.get('members_count_per_lead_ok', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'members_status': r.get('members_status', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'lead_axis_observed': r.get('source_lead_values_observed', r.get('lead_axis_observed',
                                                                            'NAO_EXECUTADO_NESTA_TAREFA')),
        'variable_observed': r.get('variable_observed', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'units_observed': r.get('units_observed', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'legacy_service_expected_shutdown': ncat.LEGACY_SERVICE_EXPECTED_SHUTDOWN,
        # Seção 13, Fase 2C.1b — campos restantes específicos do POC real.
        'backend_requested': r.get('backend_requested', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'fallback_reason': r.get('fallback_reason', backend_fallback_motivo),
        'source_url': r.get('source_url', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'model': r.get('model', 'NOAA_NCEP/CFSv2'),
        'init_date': r.get('init_date', _origem_str(*POC_ORIGEM)),
        'lead_values_requested': r.get('lead_values_requested', list(LEADS)),
        'selected_lat': r.get('selected_lat', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'selected_lon': r.get('selected_lon', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'grid_distance_km': r.get('grid_distance_km', 'NAO_EXECUTADO_NESTA_TAREFA'),
        # Seção 4/5 (revisão final) — grade DOCUMENTADA (catálogo/fonte) nunca
        # rotulada como observada; grade OBSERVADA é a do subset real aberto
        # (tipicamente "1x1" para um único ponto). Convenção de longitude só é
        # afirmada quando de fato desambiguável a partir do dado real.
        'grid_shape_documented': r.get('grid_shape_documented', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'subset_grid_shape_observed': r.get('subset_grid_shape_observed', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'longitude_convention': r.get('longitude_convention', 'NAO_EXECUTADO_NESTA_TAREFA'),
        # Seção 1/2/6/7/11 (revisão pós-execução #1) — modo de
        # decodificação temporal e calendário/unidades REALMENTE
        # observados na rota vencedora; download_status/
        # dataset_open_status distintos (a execução #1 provou
        # DOWNLOAD_SUCCESS/DATASET_OPEN_ERROR, nunca SERVICE_UNAVAILABLE
        # — perder essa distinção some com a informação de que o IRIDL
        # está funcional). O detalhe por TENTATIVA/rota (inclusive as
        # que falharam) fica em nmme_poc_access_audit.csv, não aqui.
        'time_decode_mode': r.get('time_decode_mode', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'calendar_observed': r.get('calendar_observed', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'time_units_observed': r.get('time_units_observed', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'download_status': r.get('download_status', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'dataset_open_status': r.get('dataset_open_status', 'NAO_EXECUTADO_NESTA_TAREFA'),
        # Seção 2/5 (execução real #2, run 35888809240) — calendário
        # original vs. normalizado (alias legado documentado), método de
        # confirmação temporal (variável auxiliar OU semântica
        # documentada do eixo forecast_period) e os fatos que o embasam.
        'calendar_original': r.get('calendar_original', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'calendar_normalized': r.get('calendar_normalized', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'calendar_normalization_applied': r.get('calendar_normalization_applied',
                                                   'NAO_EXECUTADO_NESTA_TAREFA'),
        'mapping_confirmation_method': r.get('mapping_confirmation_method', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'forecast_reference_time_observed': r.get('forecast_reference_time_observed',
                                                     'NAO_EXECUTADO_NESTA_TAREFA'),
        'lead_units_observed': r.get('lead_units_observed', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'lead_standard_name_observed': r.get('lead_standard_name_observed', 'NAO_EXECUTADO_NESTA_TAREFA'),
        # Seção 3/4/5/7 (execução real #3) — origem confirmada via a
        # coordenada S da variável REAL (nunca do eixo S global do
        # Dataset) ou via seleção Ingrid VALUE documentada.
        'init_selection_method': r.get('init_selection_method', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'init_value_requested': r.get('init_value_requested', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'init_value_observed_on_variable': r.get('init_value_observed_on_variable',
                                                    'NAO_EXECUTADO_NESTA_TAREFA'),
        'init_axis_size_observed_on_variable': r.get('init_axis_size_observed_on_variable',
                                                        'NAO_EXECUTADO_NESTA_TAREFA'),
        'init_selection_status': r.get('init_selection_status', 'NAO_EXECUTADO_NESTA_TAREFA'),
        # Seção 3/5 (revisão pós-execução #3, risco residual) — método/
        # URL/resultado da verificação de controle independente.
        'init_verification_method': r.get('init_verification_method', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'init_verification_control_url': r.get('init_verification_control_url',
                                                  'NAO_EXECUTADO_NESTA_TAREFA'),
        'init_verification_result': r.get('init_verification_result', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'mapping_reference': r.get('mapping_reference', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'poc_status': r.get('poc_status', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'data_execucao': datetime.now(timezone.utc).isoformat(),
        # Seção 8 (execução real #2) — a nota não pode mais dizer "nenhum
        # download real ocorreu" quando um POC real de fato rodou
        # (requests_realizados>0); nesse caso a nota abre com a frase
        # correta e só o restante (contexto de catálogo, ECMWF, etc.)
        # continua igual.
        'nota': (('POC real executado; nenhuma avaliação científica de skill realizada (Seção '
                   '18/35-S — este módulo nunca calcula skill, nunca usa CHIRPS). '
                   if r.get('requests_realizados', 0) > 0 else
                   'Nenhum download real ocorreu nesta tarefa (Seção 38/50) — infraestrutura só. ')
                + 'ECMWF deliberadamente excluído (Seção 5): fonte precisa ser independente do C3S. '
                'n_models_poc_executable=0 continua honesto (nenhum subset real foi de fato aberto). '
                'n_models_poc_ready_for_real_test=1 (CFSv2) — "pronto para testar" não é "já '
                'confirmado" (Seção 4). data_backend_used reflete a escolha operacional atual (Seção '
                f'6, Rodada 5) — IRIDL_LEGACY como fallback documentado enquanto forecast.ccsr '
                f'permanecer {ncat.ROUTE_STATUS_DISCOVERY_REQUIRED} (Seção 12); desligamento do IRIDL '
                f'legado esperado até {ncat.LEGACY_SERVICE_EXPECTED_SHUTDOWN} (aproximado).'),
    }


def gerar_relatorio_markdown(sistemas=None):
    sistemas = sistemas if sistemas is not None else ncat.CATALOGO
    cp = ncat.common_period_json(sistemas)
    linhas = ["# NMME — Catálogo + POC controlado (Fase 2C.1)", "",
              "**Este é só um catálogo de infraestrutura — nenhum download real ocorreu nesta tarefa "
              "(Seção 38/50).**", "",
              "## Documentado", ""]
    for s in sistemas:
        linhas.append(f"- **{s.centre}/{s.model_name}** ({s.availability_status}): "
                       f"hindcast_members={s.hindcast_members} "
                       f"[{ncat.status_evidencia(s, 'hindcast_members')}], "
                       f"hindcast={s.hindcast_start}-{s.hindcast_end} "
                       f"[{ncat.status_evidencia(s, 'hindcast_start')}/"
                       f"{ncat.status_evidencia(s, 'hindcast_end')}]")

    campos_empiricos = [(s, [c for c in ('hindcast_start', 'hindcast_end', 'hindcast_members',
                                          'grid_resolution', 'precip_variable', 'precip_units',
                                          'initialization_scheme', 'data_url_template')
                              if ncat.status_evidencia(s, c) in
                              (ncat.EMPIRICALLY_CONFIRMED, ncat.DOCUMENTED_AND_CONFIRMED)])
                         for s in sistemas]
    campos_empiricos = [(s, campos) for s, campos in campos_empiricos if campos]
    linhas += ["", "## Confirmado empiricamente", ""]
    if campos_empiricos:
        linhas.append("Nenhum ARQUIVO de dado NMME foi aberto nesta sessão (Seção 38/50) — mas alguns "
                       "campos de CATÁLOGO/METADADO foram lidos de primeira mão em fontes reais fora do "
                       "domínio bloqueado (github.com/iridl/dlentries, github.com/iri-pycpt/pycpt — "
                       "Rodadas 3/4), e por isso já carregam EMPIRICALLY_CONFIRMED:")
        for s, campos in campos_empiricos:
            linhas.append(f"- {s.centre}/{s.model_name}: {', '.join(campos)}")
    else:
        linhas.append("Nenhum campo desta entrega tem status EMPIRICALLY_CONFIRMED ou "
                       "DOCUMENTED_AND_CONFIRMED ainda.")
    linhas.append("O primeiro subset real aberto contra o servidor de dados (não só o catálogo-fonte) "
                   "é que vai gerar a primeira confirmação empírica do DADO em si.")

    linhas += ["", "## Ainda não confirmado", ""]
    for s in sistemas:
        pendentes = [c for c in ('hindcast_start', 'hindcast_end', 'hindcast_members', 'realtime_members',
                                  'grid_resolution', 'precip_variable', 'precip_units',
                                  'initialization_scheme')
                     if ncat.status_evidencia(s, c) == ncat.UNCONFIRMED]
        if pendentes:
            linhas.append(f"- {s.centre}/{s.model_name}: {', '.join(pendentes)}")

    linhas += ["", "## Modelos excluídos por disponibilidade/homogeneidade/independência", "",
               f"- **ECMWF**: {ncat.NAO_INCLUIDOS['ECMWF']['motivo']}"]
    for nome, info in ncat.PREDECESSORES_NAO_CONFUNDIR.items():
        linhas.append(f"- **{nome}** (predecessor de {info['substituido_por']}): {info['motivo']}")
    indisponiveis = [s for s in sistemas if s.availability_status == ncat.STATUS_NAO_HOMOGENEO]
    if indisponiveis:
        for s in indisponiveis:
            linhas.append(f"- **{s.centre}/{s.model_name}**: {s.notes}")
    else:
        linhas.append("- Nenhum dos 7 candidatos foi excluído por disponibilidade nesta etapa — todos "
                       "entram como CANDIDATE; a exclusão por homogeneidade real (Seção 19/22) só pode "
                       "ser decidida depois do POC real confirmar acesso.")

    linhas += ["", "## Período comum", "",
               f"common_start={cp['common_start']}, common_end={cp['common_end']} — "
               f"documented_common_period ({cp['n_documented_models']}/{cp['n_total']} sistemas com "
               f"hindcast_start/end DOCUMENTED). empirically_confirmed_common_period=UNCONFIRMED "
               f"({cp['n_empirically_confirmed_models']}/{cp['n_total']} confirmados empiricamente — "
               f"0 até o POC real abrir algum arquivo, Seção 2/14)."
               if cp['common_start'] else "UNCONFIRMED — nenhum sistema com período confirmado "
                                            "o bastante para calcular interseção."]

    executaveis = ncat.sistemas_poc_executaveis(sistemas)
    nao_executaveis = ncat.sistemas_poc_nao_executaveis(sistemas)
    prontos_teste_real = ncat.sistemas_poc_prontos_para_teste_real(sistemas)
    linhas += ["", "## Catálogo científico vs. lista executável do POC (Seção 8/4, Rodada 4)", "",
               f"- Candidatos científicos documentados: {len(sistemas)}/7",
               f"- Prontos para uma tentativa real controlada (CONFIRMED ∪ POC_READY_DOCUMENTED): "
               f"{len(prontos_teste_real)} ({', '.join(f'{s.centre}/{s.model_name}' for s in prontos_teste_real) or '—'})",
               f"- Executáveis/já confirmados empiricamente (data_access_status=CONFIRMED): "
               f"{len(executaveis)}",
               "", "### Ainda não prontos (motivo = data_access_status)", ""]
    for s in nao_executaveis:
        if s not in prontos_teste_real:
            linhas.append(f"- {s.centre}/{s.model_name}: {s.data_access_status}")
    linhas += ["", "Nenhum modelo sai do catálogo científico por faltar acesso — as três listas são "
                    "conceitos ortogonais (Seção 8). n_models_poc_executable=0 continua o resultado "
                    "honesto desta etapa (nenhum subset real foi de fato aberto) — "
                    "n_models_poc_ready_for_real_test autoriza uma TENTATIVA, nunca afirma sucesso "
                    "(Seção 4)."]

    cfsv2 = ncat.sistema_por_nome('NOAA_NCEP', 'CFSv2')
    linhas += ["", "## Investigação CFSv2 — Rota A (CPC/CPT, Rodada 3) vs. Rota B (IRI member-level, "
                    "Rodada 4)", "",
               "**Rota A** (`monthly_nmme_hindcast_in_cpt_format/`, NOAA CPC FTP): padrão de nome e "
               "formato CPT v10 DOCUMENTED/EMPIRICALLY_CONFIRMED ao nível de formato genérico (Rodada "
               "3), mas a única fixture real do MESMO formato (CanCM4i/SAZONAL, via "
               "github.com/iri-pycpt/pycpt) é ensemble-mean, sem dimensão de membro — risco real para "
               "o objetivo de POC por membro. Mantida em scripts/nmme_cpc_cpt.py para auditoria, "
               "NÃO é a rota priorizada para o POC por membro.",
               "",
               "**Rota B** (IRI Data Library, "
               f"`{cfsv2.member_level_dataset_path.split(' ')[0] if cfsv2.member_level_dataset_path else '?'}`"
               f"): PRIORITÁRIA para o POC por membro — mesma estrutura X/Y/L/M/S já usada nas Fases "
               "C3S, não ensemble-mean. Endpoint + variável (PRATE) + as 5 dimensões (S/M/L/X/Y) "
               "EMPIRICALLY_CONFIRMED via leitura direta do catálogo-fonte Ingrid real (github.com/"
               f"iridl/dlentries, não o servidor iridl.ldeo.columbia.edu, que segue bloqueado) — "
               f"data_access_status = **{cfsv2.data_access_status}**: documentado o bastante para "
               "montar um request real auditável (ver nmme_download.montar_url_iri_cfsv2_member_level), "
               "mas nenhum subset de fato foi aberto ainda, então não é CONFIRMED (Seção 4). "
               "Achados-chave: S nativo dez/1981-mar/2011 (passo de 5 dias, não mensal — a descrição "
               "\"monthly starts\" da IRI é uma agregação por cima do arquivo nativo, mecanismo exato "
               "não confirmado); L nativo 0.5-9.5 (passo 1 mês, H{h}↔L={h-0.5} é HIPÓTESE não validada "
               "contra subset real); M declarado com tamanho fixo 28 no catálogo (contagem real "
               "aceita a faixa observada 24-28, nunca um valor único); X 0-360°/384 pontos (0,9375°); "
               "Y grade Gaussiana de 190 pontos (não uniforme); PRATE em kg m-2 s-1. Risco operacional "
               "registrado: a página oficial \"Data Library Sunset\" da IRI (não aberta de primeira "
               "mão) diz que a IRIDL está prevista para parar de operar na forma atual a partir de "
               "abril/2026 por falta de financiamento — verificar se o serviço segue no ar deve ser o "
               "primeiro passo de qualquer tentativa real contra esta rota."]

    escolha_backend = ndl.escolher_backend_member_level(cfsv2)
    linhas += ["", "## Sunset do IRIDL e migração para forecast.ccsr (Rodada 5, correção final)", "",
               f"O IRIDL legado está em processo de desligamento — a IRI confirma (WebSearch, "
               f"corroborado de forma consistente em múltiplas buscas independentes; "
               f"iri.columbia.edu segue bloqueado para WebFetch direto) que o desligamento completo é "
               f"esperado até **{ncat.LEGACY_SERVICE_EXPECTED_SHUTDOWN}**, possivelmente antes — "
               "aproximado, não uma garantia contratual (Seção 7). A IRI está migrando NMME/SubX/S2S "
               "para **forecast.ccsr.columbia.edu** (Columbia Climate School/CCSR), em beta desde "
               "~dez/2025-jan/2026, hospedando inicialmente 4 dos 5 modelos NMME ativos — CFSv2 "
               "sendo adicionado gradualmente (\"early month samples\" já citado pela revisão "
               "externa). `forecast.ccsr.columbia.edu` segue BLOQUEADO para WebFetch direto nesta "
               "sessão — nenhum endpoint exato foi encontrado, e por isso a rota fica registrada "
               f"como **{ncat.ROUTE_STATUS_DISCOVERY_REQUIRED}** (Seção 12: nunca construir URL por "
               "tentativa de padrão).",
               "",
               "**Abstração de backend (Seção 4)**: `nmme_catalogo.RotaMemberLevel` separa "
               "`data_backend`/`dataset_representation`/`dataset_path`/`variable_name`/"
               "`units_expected`/as 5 dimensões — a lógica científica (POC_ORIGEM, H1-H6, sem skill) "
               "não depende da sintaxe Ingrid. `nmme_download.escolher_backend_member_level()` decide "
               f"a prioridade operacional (Seção 6): CFSv2 hoje usa **{escolha_backend['rota'].data_backend}"
               f"/{escolha_backend['rota'].dataset_representation}** "
               f"(fallback_ocorreu={escolha_backend['fallback_ocorreu']}) — {escolha_backend['motivo']}",
               "",
               "**Duas representações do CFSv2 legado, nunca reconciliadas (Seção 9)**: A) "
               "raw/native ensemble (M=28, grade 384×190 Gaussiana, variável PRATE) — a rota usada "
               "pelo downloader/testes; B) NMME harmonized/monthly sample (M=24, grade 360×181 "
               "regular 1°, variável prec) — mais próxima do produto NMME3 pooled documentado no "
               "manual, mas não confirmada como o mesmo dado. Todo uso real deve declarar "
               "explicitamente qual representação usou."]

    linhas += ["", "## Próxima etapa", "",
               f"CFSv2 está POC_READY_DOCUMENTED_LEGACY (Rota IRIDL_LEGACY/Representação A) — a "
               f"próxima etapa é uma tentativa real pequena e controlada (1 origem, "
               f"{_origem_str(*POC_ORIGEM)}, H1-H6, todos os membros, só o ponto de São Bento) para "
               "confirmar endpoint/variável/unidade/dimensões/acesso e então, só depois disso, "
               "considerar CFSv2 CONFIRMED (Seção 4). Em paralelo, acompanhar forecast.ccsr: assim "
               "que um endpoint real for documentado, promover a rota CCSR_BETA de DISCOVERY_REQUIRED "
               "para um status pronto para teste, dado que é a preferência operacional de longo prazo "
               f"(Seção 6) — o IRIDL legado tem desligamento esperado em "
               f"{ncat.LEGACY_SERVICE_EXPECTED_SHUTDOWN}. Os outros 6 candidatos permanecem como "
               "estavam — não investigados nesta rodada (Seção 16 da tarefa). Fase 2C.2 "
               "(calibração/skill) continua fora do escopo desta entrega."]
    return '\n'.join(linhas) + '\n'


def escrever_saidas(sistemas=None, resultado_poc=None):
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    sistemas = sistemas if sistemas is not None else ncat.CATALOGO
    escrever_catalogo(sistemas)

    r = resultado_poc or {}
    raw_df = r.get('raw_df', pd.DataFrame(columns=[
        'centre', 'model_name', 'model_version', 'init_date', 'target_month', 'lead', 'member',
        'forecast_prec_mm', 'requested_lat', 'requested_lon', 'selected_lat', 'selected_lon',
        'grid_distance_km', 'variable_original', 'units_original', 'conversion_applied',
        'source_url', 'source_type']))
    temporal_df = r.get('temporal_audit_df', pd.DataFrame(columns=[
        # Seção 6, Fase 2C.1b — colunas exatas pedidas para o POC real.
        # mapping_confirmation_method (Seção 5, execução real #2): qual
        # dos dois métodos (variável auxiliar OU semântica documentada
        # do eixo forecast_period) confirmou este lead, se algum.
        # init_selection_* (Seção 7, execução real #3): auditoria da
        # seleção de inicialização por lead, lida da coordenada S da
        # variável REAL, nunca do eixo S global do Dataset.
        # init_verification_* (revisão pós-execução #3, risco residual):
        # método/URL/resultado da verificação de controle independente
        # (só preenchido quando S foi removido da variável).
        'centre', 'model_name', 'init_date', 'H_lead', 'source_L', 'target_month',
        'mapping_status', 'evidence', 'mapping_confirmation_method',
        'init_selection_method', 'init_value_requested', 'init_value_observed_on_variable',
        'init_axis_size_observed_on_variable', 'init_selection_status',
        'init_verification_method', 'init_verification_control_url', 'init_verification_result',
        'notes']))
    access_audit_df = r.get('access_audit_df', pd.DataFrame(columns=[
        # Seção 11 (revisão pós-execução #1) — colunas de auditoria por
        # rota/tentativa: cache_path/cache_hit reais, download_status
        # distinto de dataset_open_status, modo de decodificação
        # temporal e calendário/unidades observados. calendar_original/
        # calendar_normalized/calendar_normalization_applied (Seção 2,
        # execução real #2): alias de calendário legado detectado e
        # normalizado, quando aplicável.
        'backend', 'dataset_representation', 'source_url', 'status', 'cache_hit', 'cache_path',
        'download_status', 'dataset_open_status', 'time_decode_mode', 'calendar_observed',
        'time_units_observed', 'calendar_original', 'calendar_normalized',
        'calendar_normalization_applied', 'motivo']))
    raw_df.to_csv(ARTIFACTS_DIR / 'nmme_poc_raw.csv', index=False)
    temporal_df.to_csv(ARTIFACTS_DIR / 'nmme_poc_temporal_audit.csv', index=False)
    access_audit_df.to_csv(ARTIFACTS_DIR / 'nmme_poc_access_audit.csv', index=False)

    metadata = montar_metadata(sistemas, resultado_poc)
    (ARTIFACTS_DIR / 'metadata.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False, default=str))
    relatorio = gerar_relatorio_markdown(sistemas)
    (ARTIFACTS_DIR / 'RELATORIO.md').write_text(relatorio)

    for nome in ARTIFACT_FILENAMES:
        print(f"  ✅ artifacts/nmme_poc/{nome}")
    return metadata, relatorio


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run-plan', action='store_true',
                     help='Nunca acessa a rede NMME — só mostra catálogo/plano do POC.')
    ap.add_argument('--executar-poc-real', action='store_true',
                     help='Roda o primeiro POC real (Fase 2C.1b) — só CFSv2, origem 2005-01, H1-H6, '
                          'todos os membros, sem skill/CHIRPS. Acessa a rede de verdade.')
    args = ap.parse_args()

    if args.executar_poc_real:
        # Seção 13 — mesmo antes de qualquer outra coisa, o POC real
        # nunca pode seguir sem pelo menos 1 sistema pronto para teste
        # (nunca inventa acesso).
        validar_execucao_poc_possivel()
        print("=== NMME POC REAL (Fase 2C.1b) — CFSv2, origem "
              f"{_origem_str(*POC_ORIGEM)}, H1-H6 ===")
        resultado = executar_poc_real_cfsv2()
        aprovacao = avaliar_aprovacao_poc(resultado)
        resultado['poc_status'] = aprovacao['poc_status']
        resultado['checklist'] = aprovacao['checklist']
        escrever_catalogo()
        escrever_saidas(resultado_poc=resultado)
        print(f"\nbackend_used={resultado.get('backend_used')} "
              f"dataset_representation_used={resultado.get('dataset_representation_used')} "
              f"backend_fallback_ocorreu={resultado.get('backend_fallback_ocorreu')}")
        print(f"poc_status={aprovacao['poc_status']}")
        for chave, valor in aprovacao['checklist'].items():
            print(f"  - {chave}: {valor}")
        if aprovacao['poc_status'] != 'APROVADO':
            raise SystemExit(f"POC real REPROVADO ({aprovacao['poc_status']}) — ver "
                              f"artifacts/nmme_poc/nmme_poc_access_audit.csv e "
                              f"nmme_poc_temporal_audit.csv para o motivo (Seção 11).")
        print("\n✅ POC real do CFSv2 APROVADO — ver artifacts/nmme_poc/RELATORIO.md")
        return

    escrever_catalogo()
    imprimir_plano(plano_poc())
    escrever_saidas()
    print("\n✅ Catálogo + plano do POC NMME gerados — ver artifacts/nmme_poc/RELATORIO.md "
          "(infraestrutura só, Seção 38/50 — nenhum download real).")


if __name__ == '__main__':
    main()
