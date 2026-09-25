#!/usr/bin/env python3
"""
nmme_piloto_historico.py — Fase 2C.2, piloto de 16 inicializações
históricas do CFSv2 (scripts/nmme_poc.py::executar_poc_real_cfsv2
chamado 16 vezes, uma por origem, nunca em lote/RANGEEDGES amplo).

Decisões técnicas adotadas (encerramento da Fase 2C.1b,
docs/nmme-fase2c1b-encerramento.md e docs/nmme-fase2c2-especificacao.md):
  - Período: 1991-2010 (dentro do período nativo confirmado da rota
    EMPIRICALLY_CONFIRMED — S 1982-01 a 2010-12, catálogo).
  - Inicializações: mensais, 4 anos representativos (início/meio/fim +
    o ano já empiricamente validado em produção) x 4 meses (jan/abr/
    jul/out, 1 por trimestre hidrológico) = 16 origens.
  - Horizontes: H1-H6, sem alteração.
  - Representação: NMME_HARMONIZED_MONTHLY (a rota EMPIRICALLY_CONFIRMED
    — nunca a Representação A/RAW_NATIVE_ENSEMBLE, nunca CCSR_BETA).
  - Membros: exatamente 24 válidos por horizonte — política já
    implementada em nmme_poc.py (`axis_ok = axis_observed ==
    axis_expected == 24`), reaproveitada sem alteração.
  - CHIRPS de referência do piloto: PONTO ÚNICO, o mesmo ponto de grade
    já usado pelo POC (São Bento do Tocantins) — nunca o zonal/envelope
    (Armadilha 8 do CLAUDE.md: zonal ainda não passou pela suíte de
    falha, promoção é decisão separada, não tomada aqui).
  - Status do catálogo: SistemaNMME.data_access_status do CFSv2
    permanece POC_READY_DOCUMENTED (decisão explícita — não promovido
    nesta tarefa); EMPIRICALLY_CONFIRMED continua exclusivo da rota já
    validada (scripts/nmme_catalogo.py) — este módulo NUNCA escreve no
    catálogo.

Cada origem é processada de forma ISOLADA: uma falha/exceção numa
origem nunca interrompe as demais (Seção 2, item 7 da tarefa — "registrar
individualmente qualquer falha"). Todos os guardrails de integridade já
implementados e testados em nmme_poc.py/nmme_processar.py são
reaproveitados SEM MODIFICAÇÃO — este módulo só orquestra 16 chamadas e
agrega o resultado; nenhuma lógica de seleção temporal, conversão de
unidade, contagem de membros ou mapeamento L<->mês é reimplementada
aqui.

Nunca calcula skill, nunca compara com CHIRPS de forma científica
(isso é Fase 2C.2 completa, depois do piloto aprovado) — este módulo só
verifica PROCEDÊNCIA e COBERTURA da série observacional usada como
referência (Seção 3 da tarefa), nunca a métrica de habilidade.

Roda com:
    python scripts/nmme_piloto_historico.py --dry-run-plan
    python scripts/nmme_piloto_historico.py --executar-piloto-real
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import nmme_catalogo as ncat  # noqa: E402
import nmme_poc as npoc  # noqa: E402
import nmme_processar as nproc  # noqa: E402

ARTIFACTS_DIR = ROOT / 'artifacts' / 'nmme_piloto_historico'
SERIE_OBSERVACIONAL_PATH = ROOT / 'data' / 'serie_subst.csv'

# Seção 1 da tarefa — decisões técnicas adotadas, não reabertas aqui.
PILOTO_ANOS = (1991, 1998, 2005, 2010)
PILOTO_MESES = (1, 4, 7, 10)
PILOTO_ORIGENS = tuple((ano, mes) for ano in PILOTO_ANOS for mes in PILOTO_MESES)   # 16
assert len(PILOTO_ORIGENS) == 16

# Seção 3 — valores com esta `fonte` em data/serie_subst.csv são
# explicitamente marcados como PRELIMINARES/estimados pela cascata de
# scripts/fetch_monthly_data.py (CLAUDE.md, armadilha 6): "gravado com
# fonte própria... quando o Final publicar esse mês depois, o valor
# Preliminary já gravado não é substituído automaticamente". Nunca
# tratados como observação real confirmada nesta verificação de
# cobertura — mesmo que o valor numérico esteja presente.
FONTES_NAO_CONFIRMADAS = {'CHC-Preliminar', 'OpenMeteo-ERA5'}

# Seção 3 — a série observacional de produção (data/serie_subst.csv)
# representa o CENTROIDE DAS FAZENDAS (scripts/_chirps.py::FAZENDAS_LAT/
# FAZENDAS_LON = -7.80/-47.95), README.md: "MERRA-2 1981-1995 + Sinobras
# 1996-hoje" — NÃO é CHIRPS para a maior parte da série (achado desta
# tarefa, ver docs/nmme-fase2c2-piloto-cobertura-observacional.md).
# O ponto usado pelo POC/piloto do CFSv2 é são bento do tocantins
# (scripts/_c3s_utils.py::MUNICIPIOS), herdado das fases C3S (Seção 15
# do catálogo) — os dois pontos NÃO coincidem; a distância é computada
# abaixo, uma vez, reaproveitando a mesma função já usada para a
# distância grade-CFSv2<->ponto-pedido (nunca uma fórmula nova).
FAZENDAS_LAT, FAZENDAS_LON = -7.80, -47.95


def distancia_fazendas_ate_municipio_km(municipio=npoc.MUNICIPIO):
    """Distância (km) entre o centroide das fazendas (referência real
    de data/serie_subst.csv) e o ponto do município usado pelo POC/
    piloto do CFSv2 — Seção 3, "verificar a correspondência espacial
    entre a referência observacional e a grade do CFSv2"."""
    from _c3s_utils import MUNICIPIOS
    info = MUNICIPIOS[municipio]
    return nproc.distancia_km_aprox(FAZENDAS_LAT, FAZENDAS_LON, info['lat'], info['lon'])


def executar_piloto_historico(origens=PILOTO_ORIGENS, leads=npoc.LEADS, municipio=npoc.MUNICIPIO,
                                 sistema=None, esquema_temporal='lead1_igual_mes_inicializacao',
                                 baixar_fn=None, abrir_fn=None, resolver_fns=None):
    """Roda `nmme_poc.executar_poc_real_cfsv2` uma vez por origem,
    isolando falhas: uma exceção inesperada numa origem NUNCA interrompe
    as demais (Seção 2, item 7 — "registrar individualmente qualquer
    falha"). Nenhum guardrail é reimplementado — cada origem passa
    pelos mesmos guardrails já testados do POC de infraestrutura.

    `resolver_fns`, quando informado, é uma função `(ano, mes) ->
    (baixar_fn, abrir_fn)` usada para injetar um cenário DIFERENTE por
    origem em testes (ex.: uma origem que falha, as outras que não) —
    tem precedência sobre `baixar_fn`/`abrir_fn` quando presente para
    aquela origem específica.

    Devolve uma lista de 16 dicts (1 por origem, na ordem de `origens`)
    com `ano`, `mes`, `origem`, `resultado` (o dict devolvido por
    executar_poc_real_cfsv2, já com poc_status/checklist da avaliação)
    e `erro` (None, ou a mensagem da exceção que impediu até a
    avaliação — nunca deixado de registrar)."""
    sistema = sistema or ncat.sistema_por_nome('NOAA_NCEP', 'CFSv2')
    resultados = []
    for origem in origens:
        ano, mes = origem
        try:
            # `resolver_fns` fica DENTRO do try — uma falha ao resolver
            # a dependência para esta origem (ex.: bug num teste, ou
            # falha de preparação específica desta origem) é isolada
            # exatamente como uma falha do próprio download, nunca
            # derruba as outras 15 (achado de teste: a primeira versão
            # deste laço deixava essa chamada fora do try e um erro aqui
            # escapava sem isolamento).
            baixar_fn_origem, abrir_fn_origem = baixar_fn, abrir_fn
            if resolver_fns is not None:
                baixar_fn_origem, abrir_fn_origem = resolver_fns(ano, mes)
            r = npoc.executar_poc_real_cfsv2(
                origem=origem, leads=leads, municipio=municipio, sistema=sistema,
                esquema_temporal=esquema_temporal,
                baixar_fn=baixar_fn_origem, abrir_fn=abrir_fn_origem)
            aprovacao = npoc.avaliar_aprovacao_poc(r)
            r = {**r, 'poc_status': aprovacao['poc_status'], 'checklist': aprovacao['checklist']}
            erro = None
        except Exception as e:   # nunca deixa uma origem derrubar as outras 15
            r = {'poc_status': f'ERRO_INESPERADO_{type(e).__name__}', 'checklist': {},
                 'raw_df': pd.DataFrame(), 'temporal_audit_df': pd.DataFrame(),
                 'access_audit_df': pd.DataFrame(), 'model': f'{sistema.centre}/{sistema.model_name}',
                 'init_date': npoc._origem_str(ano, mes)}
            erro = f'{type(e).__name__}: {e}'
        resultados.append({'ano': ano, 'mes': mes, 'origem': origem, 'resultado': r, 'erro': erro})
    return resultados


def montar_resumo_por_origem(resultados_piloto):
    """1 linha por origem (Seção 2 — "registrar individualmente
    qualquer falha"), nunca só o agregado. Nenhuma origem é omitida
    mesmo quando reprovada/com erro inesperado."""
    linhas = []
    for item in resultados_piloto:
        r, erro = item['resultado'], item['erro']
        checklist = r.get('checklist', {})
        raw_df = r.get('raw_df', pd.DataFrame())
        linhas.append({
            'ano': item['ano'], 'mes': item['mes'],
            'init_date': f"{item['ano']}-{item['mes']:02d}",
            'poc_status': r.get('poc_status'),
            'backend_used': r.get('backend_used'),
            'dataset_representation_used': r.get('dataset_representation_used'),
            'inicializacao_selecao_status': r.get('inicializacao_selecao_status'),
            'n_raw': len(raw_df),
            'member_count_per_lead_ok': checklist.get('member_count_per_lead_ok'),
            'temporal_mapping_confirmado': checklist.get('temporal_mapping_confirmado'),
            'unidade_confirmada': checklist.get('unidade_confirmada'),
            'grade_confirmada': checklist.get('grade_confirmada'),
            'erro_inesperado': erro or '',
        })
    return pd.DataFrame(linhas)


def concatenar_dataframes_piloto(resultados_piloto):
    """Concatena raw_df/temporal_audit_df/access_audit_df das 16
    origens — cada linha já carrega `init_date` (raw/temporal) ou
    `backend`/`source_url` (access), suficiente para rastrear de qual
    origem ela veio sem precisar de 16 arquivos separados (Seção 6,
    "arquivos de auditoria por inicialização" — satisfeito por coluna
    de rastreio, não por 1 arquivo por origem, seguindo a convenção já
    usada em todo o resto do projeto: tabelas agregadas com coluna
    identificadora, nunca dezenas de arquivos soltos)."""
    raw_dfs, temporal_dfs, access_dfs = [], [], []
    for item in resultados_piloto:
        r = item['resultado']
        origem_str = f"{item['ano']}-{item['mes']:02d}"
        raw_df = r.get('raw_df', pd.DataFrame()).copy()
        if len(raw_df):
            raw_df.insert(0, 'origem_piloto', origem_str)
        raw_dfs.append(raw_df)
        temporal_df = r.get('temporal_audit_df', pd.DataFrame()).copy()
        if len(temporal_df):
            temporal_df.insert(0, 'origem_piloto', origem_str)
        temporal_dfs.append(temporal_df)
        access_df = r.get('access_audit_df', pd.DataFrame()).copy()
        if len(access_df):
            access_df.insert(0, 'origem_piloto', origem_str)
        access_dfs.append(access_df)
    raw_final = pd.concat(raw_dfs, ignore_index=True) if any(len(d) for d in raw_dfs) else pd.DataFrame()
    temporal_final = (pd.concat(temporal_dfs, ignore_index=True)
                       if any(len(d) for d in temporal_dfs) else pd.DataFrame())
    access_final = (pd.concat(access_dfs, ignore_index=True)
                     if any(len(d) for d in access_dfs) else pd.DataFrame())
    return raw_final, temporal_final, access_final


def avaliar_aprovacao_piloto(resultados_piloto, cobertura_df=None,
                                cobertura_minima=0.90):
    """Critérios objetivos de aprovação do PILOTO (distintos da
    aprovação de cada origem isolada — docs/nmme-fase2c2-especificacao.md,
    Seção G): (1) todas as 16 origens com poc_status=APROVADO; (2)
    nenhum erro inesperado (fora do vocabulário de status já conhecido
    do POC); (3) cobertura observacional >= 90% das 16xlen(leads)
    combinações origem x lead, contando só observações CONFIRMADAS
    (nunca substituídas/estimadas — Seção 3). `cobertura_df`, quando
    informado, é o resultado de `verificar_cobertura_observacional`;
    sem ele, o critério de cobertura fica marcado como NAO_AVALIADO
    (nunca assumido implicitamente aprovado)."""
    status_por_origem = [item['resultado'].get('poc_status') for item in resultados_piloto]
    n_total = len(resultados_piloto)
    n_aprovadas = sum(1 for s in status_por_origem if s == 'APROVADO')
    todas_aprovadas = n_aprovadas == n_total
    nenhum_erro_inesperado = not any(item['erro'] for item in resultados_piloto)

    if cobertura_df is not None and len(cobertura_df):
        n_confirmadas = int((cobertura_df['classificacao'] == 'OBSERVACAO_CONFIRMADA').sum())
        cobertura_fracao = n_confirmadas / len(cobertura_df)
        cobertura_ok = cobertura_fracao >= cobertura_minima
    else:
        cobertura_fracao = None
        cobertura_ok = None

    criterios = {
        'todas_origens_aprovadas': todas_aprovadas,
        'nenhum_erro_inesperado': nenhum_erro_inesperado,
        'cobertura_observacional_ok': cobertura_ok,
    }
    aprovado = todas_aprovadas and nenhum_erro_inesperado and (cobertura_ok is True)
    return {
        'piloto_status': 'APROVADO' if aprovado else 'REPROVADO',
        'n_origens_aprovadas': n_aprovadas, 'n_origens_total': n_total,
        'cobertura_observacional_fracao': cobertura_fracao,
        'criterios': criterios,
    }


def _com_coluna_target_month(df):
    """Deriva `target_month` (Period mensal) a partir de `ano`/`mes` —
    aplicado tanto ao arquivo real quanto a qualquer `serie_df` injetado
    em teste, para que os dois caminhos usem exatamente a mesma
    normalização (nunca um teste passando por uma checagem diferente da
    execução real)."""
    df = df.copy()
    df['target_month'] = pd.to_datetime(df[['ano', 'mes']].assign(dia=1)
                                          .rename(columns={'dia': 'day', 'mes': 'month', 'ano': 'year'})
                                          ).dt.to_period('M')
    return df


def _carregar_serie_observacional(caminho=SERIE_OBSERVACIONAL_PATH):
    return _com_coluna_target_month(pd.read_csv(caminho))


def verificar_cobertura_observacional(resultados_piloto, serie_df=None):
    """Seção 3 da tarefa — para cada combinação origem x lead
    efetivamente processada, verifica se o mês-alvo tem observação na
    série de produção (data/serie_subst.csv) e classifica a
    procedência:
      - OBSERVACAO_CONFIRMADA: mês presente, `fonte` vazia (baseline
        histórico MERRA-2 1981-1995 / estação Sinobras 1996-presente,
        README.md) OU `fonte='CHIRPS'` (CHIRPS Final, a fonte primária
        documentada de fetch_monthly_data.py) — usável como observação
        real.
      - VALOR_SUBSTITUIDO_NAO_USAR: mês presente mas `fonte` em
        FONTES_NAO_CONFIRMADAS (CHC-Preliminar/OpenMeteo-ERA5) — dado
        real, mas preliminar/estimado; a tarefa pede explicitamente
        para NUNCA tratar como observação real na avaliação científica.
      - MES_AUSENTE: mês-alvo não está na série.

    Nunca usa o RAW do CFSv2 para decidir isso — só a série
    observacional, independente de o POC daquela origem ter sido
    aprovado ou não (a cobertura é uma propriedade da OBSERVAÇÃO, não
    da previsão)."""
    if serie_df is None:
        serie_df = _carregar_serie_observacional()
    elif 'target_month' not in serie_df.columns:
        serie_df = _com_coluna_target_month(serie_df)
    linhas = []
    for item in resultados_piloto:
        ano, mes = item['ano'], item['mes']
        origem_str = f'{ano}-{mes:02d}'
        init_date = pd.Period(origem_str, 'M')
        for lead in npoc.LEADS:
            target_month = nproc.leadtime_para_mes_alvo_nmme(init_date, lead,
                                                                'lead1_igual_mes_inicializacao')
            match = serie_df[serie_df['target_month'] == target_month]
            if not len(match):
                classificacao, fonte_observada = 'MES_AUSENTE', None
            else:
                fonte_bruta = match.iloc[0]['fonte']
                fonte_observada = None if pd.isna(fonte_bruta) else str(fonte_bruta)
                if fonte_observada in FONTES_NAO_CONFIRMADAS:
                    classificacao = 'VALOR_SUBSTITUIDO_NAO_USAR'
                else:
                    classificacao = 'OBSERVACAO_CONFIRMADA'
            linhas.append({'origem_piloto': origem_str, 'H_lead': lead,
                             'target_month': str(target_month),
                             'fonte_observada': fonte_observada or '(baseline MERRA-2/Sinobras)',
                             'classificacao': classificacao})
    return pd.DataFrame(linhas)


def montar_metadata_piloto(resultados_piloto, cobertura_df, aprovacao):
    dist_km = distancia_fazendas_ate_municipio_km()
    return {
        'fase': '2C.2 — piloto histórico CFSv2 (16 inicializações)',
        'periodo': f'{min(PILOTO_ANOS)}-{max(PILOTO_ANOS)}', 'anos': list(PILOTO_ANOS),
        'meses': list(PILOTO_MESES), 'n_origens': len(PILOTO_ORIGENS), 'leads': list(npoc.LEADS),
        'representacao': ncat.REPR_NMME_HARMONIZED_MONTHLY, 'politica_membros': 'exatamente 24 por lead',
        'chirps_referencia': 'ponto único (mesmo ponto do POC — São Bento do Tocantins)',
        'distancia_fazendas_ate_ponto_poc_km': round(dist_km, 1),
        'piloto_status': aprovacao['piloto_status'],
        'n_origens_aprovadas': aprovacao['n_origens_aprovadas'],
        'n_origens_total': aprovacao['n_origens_total'],
        'cobertura_observacional_fracao': aprovacao['cobertura_observacional_fracao'],
        'criterios_aprovacao': aprovacao['criterios'],
        'nenhuma_skill_calculada': True, 'nenhum_dashboard_alterado': True,
        'status_cfsv2_data_access': 'POC_READY_DOCUMENTED (inalterado — decisão explícita)',
    }


def escrever_saidas_piloto(resultados_piloto, cobertura_df, aprovacao):
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    raw_df, temporal_df, access_df = concatenar_dataframes_piloto(resultados_piloto)
    resumo_df = montar_resumo_por_origem(resultados_piloto)
    raw_df.to_csv(ARTIFACTS_DIR / 'piloto_raw.csv', index=False)
    temporal_df.to_csv(ARTIFACTS_DIR / 'piloto_temporal_audit.csv', index=False)
    access_df.to_csv(ARTIFACTS_DIR / 'piloto_access_audit.csv', index=False)
    resumo_df.to_csv(ARTIFACTS_DIR / 'piloto_resumo_por_origem.csv', index=False)
    cobertura_df.to_csv(ARTIFACTS_DIR / 'piloto_cobertura_observacional.csv', index=False)

    metadata = montar_metadata_piloto(resultados_piloto, cobertura_df, aprovacao)
    (ARTIFACTS_DIR / 'metadata.json').write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=str))
    relatorio = gerar_relatorio_piloto_markdown(resultados_piloto, resumo_df, cobertura_df, aprovacao)
    (ARTIFACTS_DIR / 'RELATORIO.md').write_text(relatorio)

    for nome in ('piloto_raw.csv', 'piloto_temporal_audit.csv', 'piloto_access_audit.csv',
                  'piloto_resumo_por_origem.csv', 'piloto_cobertura_observacional.csv',
                  'metadata.json', 'RELATORIO.md'):
        print(f"  ✅ artifacts/nmme_piloto_historico/{nome}")
    return metadata, relatorio


def gerar_relatorio_piloto_markdown(resultados_piloto, resumo_df, cobertura_df, aprovacao):
    linhas = ["# NMME — Piloto histórico CFSv2 (Fase 2C.2)", "",
              "**Piloto de infraestrutura — 16 inicializações, nunca conclusão científica "
              "(Seção 4 da tarefa: 'não calcular conclusões científicas definitivas a partir "
              "do piloto de infraestrutura').**", "",
              f"## Resultado: {aprovacao['piloto_status']}", "",
              f"- Origens aprovadas: {aprovacao['n_origens_aprovadas']}/{aprovacao['n_origens_total']}",
              f"- Cobertura observacional confirmada: "
              f"{aprovacao['cobertura_observacional_fracao']}",
              "", "## Resumo por origem", "",
              "| Origem | Status | RAW | Membros/lead OK | Mapeamento temporal | Unidade | Grade | Erro |",
              "|---|---|---|---|---|---|---|---|"]
    for _, row in resumo_df.iterrows():
        linhas.append(f"| {row['init_date']} | {row['poc_status']} | {row['n_raw']} | "
                       f"{row['member_count_per_lead_ok']} | {row['temporal_mapping_confirmado']} | "
                       f"{row['unidade_confirmada']} | {row['grade_confirmada']} | {row['erro_inesperado']} |")
    linhas += ["", "## Cobertura observacional (CHIRPS/série de produção)", "",
               f"Total de combinações origem×lead avaliadas: {len(cobertura_df)}"]
    if len(cobertura_df):
        contagem = cobertura_df['classificacao'].value_counts()
        for classe, n in contagem.items():
            linhas.append(f"- `{classe}`: {n}")
    linhas += ["", "Ver docs/nmme-fase2c2-piloto-cobertura-observacional.md para a investigação "
                    "completa de procedência (MERRA-2/Sinobras/CHIRPS) e a distância espacial "
                    "entre a referência observacional e o ponto do CFSv2."]
    return '\n'.join(linhas) + '\n'


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def imprimir_plano():
    print("=== NMME Piloto Histórico CFSv2 (Fase 2C.2) — DRY RUN PLAN "
          "(nenhum acesso à rede NMME) ===")
    print(f"  periodo: {min(PILOTO_ANOS)}-{max(PILOTO_ANOS)}")
    print(f"  anos: {list(PILOTO_ANOS)}")
    print(f"  meses: {list(PILOTO_MESES)}")
    print(f"  n_origens: {len(PILOTO_ORIGENS)}")
    print(f"  origens: {[f'{a}-{m:02d}' for a, m in PILOTO_ORIGENS]}")
    print(f"  leads: {list(npoc.LEADS)}")
    print(f"  representacao: {ncat.REPR_NMME_HARMONIZED_MONTHLY}")
    print("  politica_membros: exatamente 24 por lead (guardrail existente, sem alteração)")
    print("  chirps_referencia: ponto único (mesmo ponto do POC — São Bento do Tocantins)")
    dist_km = distancia_fazendas_ate_municipio_km()
    print(f"  distancia_fazendas_ate_ponto_poc_km: {round(dist_km, 1)}")
    print("  status_cfsv2_data_access: POC_READY_DOCUMENTED (inalterado nesta tarefa)")
    print(f"  requests_previstos: {len(PILOTO_ORIGENS)} (1 por origem, nunca em lote)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run-plan', action='store_true',
                     help='Nunca acessa a rede NMME — só mostra o plano do piloto (16 origens).')
    ap.add_argument('--executar-piloto-real', action='store_true',
                     help='Roda o piloto real (16 inicializações, H1-H6, 24 membros) — acessa a rede de verdade.')
    args = ap.parse_args()

    if args.executar_piloto_real:
        imprimir_plano()
        resultados = executar_piloto_historico()
        cobertura_df = verificar_cobertura_observacional(resultados)
        aprovacao = avaliar_aprovacao_piloto(resultados, cobertura_df)
        escrever_saidas_piloto(resultados, cobertura_df, aprovacao)
        print(f"\npiloto_status={aprovacao['piloto_status']} "
              f"({aprovacao['n_origens_aprovadas']}/{aprovacao['n_origens_total']} origens aprovadas)")
        for k, v in aprovacao['criterios'].items():
            print(f"  - {k}: {v}")
        if aprovacao['piloto_status'] != 'APROVADO':
            raise SystemExit(f"Piloto histórico REPROVADO — ver "
                              f"artifacts/nmme_piloto_historico/piloto_resumo_por_origem.csv "
                              f"para o motivo por origem.")
        print("\n✅ Piloto histórico do CFSv2 APROVADO — ver artifacts/nmme_piloto_historico/RELATORIO.md")
        return

    imprimir_plano()
    print("\n✅ Plano do piloto histórico gerado (infraestrutura só — nenhum download real).")


if __name__ == '__main__':
    main()
