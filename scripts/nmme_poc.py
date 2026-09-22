#!/usr/bin/env python3
"""
nmme_poc.py — Fase 2C.1: orquestração do catálogo + POC controlado do
NMME (fonte dinâmica sazonal independente do C3S, Fase 2C). Esta
entrega é só INFRAESTRUTURA (Seção 38/50): monta catálogo, plano de
requests, artifacts documentais — o POC real (download de verdade) só
roda depois de revisão humana, fora desta tarefa.

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
    'nmme_poc_temporal_audit.csv', 'metadata.json', 'RELATORIO.md',
]


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
        'member_axis_observed': r.get('member_axis_observed', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'member_count_non_missing': r.get('member_count_non_missing', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'lead_axis_observed': r.get('lead_axis_observed', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'variable_observed': r.get('variable_observed', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'units_observed': r.get('units_observed', 'NAO_EXECUTADO_NESTA_TAREFA'),
        'legacy_service_expected_shutdown': ncat.LEGACY_SERVICE_EXPECTED_SHUTDOWN,
        'data_execucao': datetime.now(timezone.utc).isoformat(),
        'nota': 'Nenhum download real ocorreu nesta tarefa (Seção 38/50) — infraestrutura só. '
                'ECMWF deliberadamente excluído (Seção 5): fonte precisa ser independente do C3S. '
                'n_models_poc_executable=0 continua honesto (nenhum subset real foi de fato aberto). '
                'n_models_poc_ready_for_real_test=1 (CFSv2) — "pronto para testar" não é "já '
                'confirmado" (Seção 4). data_backend_used reflete a escolha operacional atual (Seção '
                f'6, Rodada 5) — IRIDL_LEGACY como fallback documentado enquanto forecast.ccsr '
                f'permanecer {ncat.ROUTE_STATUS_DISCOVERY_REQUIRED} (Seção 12); desligamento do IRIDL '
                f'legado esperado até {ncat.LEGACY_SERVICE_EXPECTED_SHUTDOWN} (aproximado).',
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
        'centre', 'model_name', 'init_date', 'lead', 'target_month', 'initialization_reference',
        'source_time_coordinate', 'source_lead_coordinate', 'mapping_status', 'notes']))
    raw_df.to_csv(ARTIFACTS_DIR / 'nmme_poc_raw.csv', index=False)
    temporal_df.to_csv(ARTIFACTS_DIR / 'nmme_poc_temporal_audit.csv', index=False)

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
                     help='NÃO IMPLEMENTADO nesta entrega (Seção 38/50) — falha explicitamente.')
    args = ap.parse_args()

    if args.executar_poc_real:
        # Seção 13 — mesmo antes de qualquer outra coisa, o POC real
        # nunca pode seguir sem pelo menos 1 sistema executável (nunca
        # inventa acesso). Esta checagem já fica ativa agora, mesmo com
        # a execução real ainda não implementada nesta entrega, para
        # que a regra esteja pronta/testada quando for implementada.
        validar_execucao_poc_possivel()
        raise SystemExit("--executar-poc-real não está implementado nesta entrega (Fase 2C.1, Seção "
                          "38/50 — só infraestrutura). Requer revisão humana e uma tarefa separada "
                          "antes de qualquer download real.")

    escrever_catalogo()
    imprimir_plano(plano_poc())
    escrever_saidas()
    print("\n✅ Catálogo + plano do POC NMME gerados — ver artifacts/nmme_poc/RELATORIO.md "
          "(infraestrutura só, Seção 38/50 — nenhum download real).")


if __name__ == '__main__':
    main()
