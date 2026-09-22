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

Origem preferencial (Seção 17): 2015-01. Só usada para um modelo se o
catálogo tiver hindcast_start/hindcast_end CONFIRMADOS (evidence !=
UNCONFIRMED) cobrindo 2015 — nunca assumida coberta por omissão. Onde a
cobertura ficou UNCONFIRMED nesta sessão (a maioria dos candidatos, ver
nmme_catalogo.py), a decisão de usar 2015-01 mesmo assim fica registrada
explicitamente como pendência a confirmar no POC real (Seção 17: "se
não, usar uma origem comum documentada... e registrar a decisão" — não
há origem alternativa mais documentada que 2015-01 nesta investigação,
então ela permanece a escolha, com a pendência registrada em vez de
trocada por outra igualmente incerta).
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
POC_ORIGEM = (2015, 1)       # Seção 17.

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
    """Seção 13 (correção pós-revisão) — o POC real só pode rodar se
    pelo menos 1 sistema tiver data_access_status=CONFIRMED (endpoint +
    variável de precipitação + dimensões confirmados, Seção 7/8). NÃO
    exige 7/7 — só que a lista executável não esteja vazia. Levanta
    RuntimeError explícito caso contrário — nunca inventa acesso para
    poder seguir adiante."""
    sistemas = sistemas if sistemas is not None else ncat.CATALOGO
    executaveis = ncat.sistemas_poc_executaveis(sistemas)
    if not executaveis:
        raise RuntimeError(
            "SISTEMAS_POC_EXECUTAVEIS está vazio — nenhum modelo do catálogo tem "
            "data_access_status=CONFIRMED (endpoint do hindcast + variável de precipitação + "
            "dimensões, todos confirmados ao mesmo tempo — Seção 7/8). O POC real não pode rodar "
            "sobre um endpoint adivinhado (Seção 13). Investigar/confirmar pelo menos 1 endpoint "
            "antes de tentar executar.")
    return executaveis


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
    cp = ncat.common_period_json(sistemas)
    return {
        'origem_poc': _origem_str(ano, mes), 'leads': list(leads), 'municipio': MUNICIPIO,
        'n_modelos_candidatos_documentados': n_candidatos,
        'n_modelos_poc_executaveis': len(executaveis),
        'modelos_poc_executaveis': [f'{s.centre}/{s.model_name}' for s in executaveis],
        'modelos_poc_nao_executaveis': [
            {'sistema': f'{s.centre}/{s.model_name}', 'motivo': s.data_access_status} for s in nao_executaveis
        ],
        'periodo_comum_documentado': f"{cp['common_start']}-{cp['common_end']}" if cp['common_start']
        else 'UNCONFIRMED',
        'requests_previstos': len(executaveis),
        'modelos': info, 'artifacts_esperados': ARTIFACT_FILENAMES,
        'aviso': 'POC de infraestrutura (Seção 18/35-S) — nunca calcula skill. Só valida acesso/'
                 'modelo/versão/membros/variável/unidade/grade/leads/target month/parsing/conversão. '
                 'Lista executável pode legitimamente vir vazia nesta etapa (Seção 13) — não é erro.',
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
        elif chave == 'modelos_poc_nao_executaveis':
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
                             leads=LEADS, municipio=MUNICIPIO, source_url='', source_type='NetCDF/IRIDL'):
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
    if sistema.hindcast_members is not None and n_membros != sistema.hindcast_members:
        raise RuntimeError(f"[{sistema.centre}/{sistema.model_name} {_origem_str(ano, mes)}] "
                            f"nº de membros = {n_membros}, documented_expected "
                            f"{sistema.hindcast_members} (barreira A — nunca aceitar silenciosamente "
                            f"um nº diferente do documentado, Seção 8).")

    raw_linhas, temporal_linhas = [], []
    for lead in leads:
        target_month = nproc.leadtime_para_mes_alvo_nmme(init_date, lead, esquema_temporal)
        fatia_lead = ponto.sel(L=lead) if 'L' in ponto.dims else ponto
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
            source_lead_coordinate='L (ingrid)' if 'L' in ponto.dims else 'desconhecida',
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

    metadata_origem = {'n_membros': n_membros, 'lat_grade': selected_lat, 'lon_grade': selected_lon,
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
    cp = ncat.common_period_json(sistemas)
    r = resultado_poc or {}
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
        'data_execucao': datetime.now(timezone.utc).isoformat(),
        'nota': 'Nenhum download real ocorreu nesta tarefa (Seção 38/50) — infraestrutura só. '
                'ECMWF deliberadamente excluído (Seção 5): fonte precisa ser independente do C3S. '
                'n_models_poc_executable=0 é um resultado honesto desta etapa — falta confirmar '
                'endpoint+variável+dimensões por modelo, não indica erro (Seção 8/13).',
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

    linhas += ["", "## Confirmado empiricamente", "",
               "Nenhum campo desta entrega tem status EMPIRICALLY_CONFIRMED ou "
               "DOCUMENTED_AND_CONFIRMED — nenhum arquivo de dado NMME foi aberto nesta sessão "
               "(só páginas de documentação HTML/texto, dentro do permitido pela Seção 38/50). "
               "O primeiro POC real é que vai gerar as primeiras confirmações empíricas."]

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
    linhas += ["", "## Catálogo científico vs. lista executável do POC (Seção 8)", "",
               f"- Candidatos científicos documentados: {len(sistemas)}/7",
               f"- Executáveis no POC (data_access_status=CONFIRMED): {len(executaveis)}",
               "", "### Não executáveis (motivo = data_access_status)", ""]
    for s in nao_executaveis:
        linhas.append(f"- {s.centre}/{s.model_name}: {s.data_access_status}")
    linhas += ["", "Nenhum modelo sai do catálogo científico por faltar acesso — as duas listas são "
                    "conceitos ortogonais (Seção 8). n_models_poc_executable=0 é o resultado honesto "
                    "desta etapa, não um erro."]

    cfsv2 = ncat.sistema_por_nome('NOAA_NCEP', 'CFSv2')
    linhas += ["", "## Investigação CPC/CPT (Rodada 3) — CFSv2", "",
               "Rota oficial `monthly_nmme_hindcast_in_cpt_format/` (NOAA CPC FTP) priorizada para "
               "CFSv2. Padrão de nome de arquivo e formato CPT v10 agora DOCUMENTED/confirmados "
               "(ver scripts/nmme_cpc_cpt.py e a nota da Rodada 3 em nmme_catalogo.py) — "
               f"data_access_status subiu de UNCONFIRMED para {cfsv2.data_access_status}. Continua "
               "abaixo de CONFIRMED: nenhum byte de um arquivo CFSv2/MENSAL real foi lido nesta sessão "
               "(ftp.cpc.ncep.noaa.gov bloqueado), e a única fixture real do MESMO formato "
               "(CanCM4i/SAZONAL, lida via github.com/iri-pycpt/pycpt) não tem dimensão de membro — "
               "risco real, não hipotético, de o CPT-format do CPC ser ensemble-mean-only. "
               "scripts/nmme_cpc_cpt.py já implementa o parser e as barreiras (unidade obrigatória, "
               "membro obrigatório para uso por-membro, contagem de membros, target month nunca só "
               "pelo nome do arquivo) para quando um arquivo real puder ser aberto."]

    linhas += ["", "## Próxima etapa", "",
               "Revisão humana deste catálogo → confirmar pelo menos 1 endpoint+variável+dimensões "
               "(Seção 7/8) → primeiro POC real controlado (1 origem, "
               f"{_origem_str(*POC_ORIGEM)}, só sobre SISTEMAS_POC_EXECUTAVEIS, H1-H6) → só então "
               "considerar a Fase 2C.2 (calibração/skill), fora do escopo desta entrega."]
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
