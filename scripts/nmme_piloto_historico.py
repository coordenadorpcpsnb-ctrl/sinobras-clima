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
  - Referência observacional do piloto: PONTO ÚNICO, o mesmo ponto de
    grade já usado pelo POC (São Bento do Tocantins) — nunca o zonal/
    envelope (Armadilha 8 do CLAUDE.md: zonal ainda não passou pela
    suíte de falha, promoção é decisão separada, não tomada aqui).
    IMPORTANTE (revisão pontual pré-execução real): essa referência
    (`data/serie_subst.csv`) NÃO é CHIRPS para o período do piloto — é
    reanálise MERRA-2 (1981-1995) e leitura das estações da própria
    Sinobras (1996-presente), README.md — e está a ~198 km do ponto de
    São Bento do Tocantins usado pelo CFSv2 (centroide das fazendas,
    não o mesmo ponto — ver `distancia_fazendas_ate_municipio_km` e
    `docs/nmme-fase2c2-piloto-cobertura-observacional.md`). As
    coordenadas usadas pelo POC/CFSv2 em si (São Bento) NÃO são
    alteradas por esta revisão — só a forma como a referência
    observacional é descrita e avaliada.
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
aqui. Qualquer origem que use uma `dataset_representation_used`
diferente de NMME_HARMONIZED_MONTHLY (fallback documentado do próprio
`nmme_download.ordem_tentativa_member_level`) é registrada
explicitamente (`montar_resumo_por_origem`/metadata) — NUNCA tratada
como equivalente à rota EMPIRICALLY_CONFIRMED (revisão pontual, Seção 4
da tarefa).

Nunca calcula skill. A APROVAÇÃO DE INFRAESTRUTURA do piloto
(`avaliar_aprovacao_piloto` — acesso, seleção temporal, membros,
horizontes, integridade do RAW) é mantida SEPARADA da APTIDÃO DA
REFERÊNCIA OBSERVACIONAL para uma avaliação científica futura
(`avaliar_aptidao_referencia_observacional` — procedência, qualidade
verificada, correspondência espacial): a insuficiência da segunda NUNCA
é reportada como falha da primeira (revisão pontual, Seção 3 da
tarefa). `verificar_cobertura_observacional` separa 3 conceitos que a
primeira versão deste módulo confundia num único rótulo
"OBSERVACAO_CONFIRMADA": (1) disponibilidade do registro (o mês está na
série?), (2) procedência DOCUMENTAL (o que README.md/fetch_monthly_
data.py dizem sobre a origem do valor — nunca inventada), e (3)
qualidade EFETIVAMENTE VERIFICADA do registro (ausência de NaN,
duplicata, valor fisicamente implausível — checagens computadas, não
inferidas da fonte).

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

import c3s_poc as cpoc  # noqa: E402
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
# usados como observação real nesta verificação de cobertura — mesmo
# que o valor numérico esteja presente.
FONTES_NAO_CONFIRMADAS = {'CHC-Preliminar', 'OpenMeteo-ERA5'}

# Seção 1 (revisão pontual) — procedência DOCUMENTAL de cada registro,
# nunca uma afirmação de qualidade individual (isso é
# `qualidade_verificada_status`, calculado à parte). Mapeamento de
# `fonte` bruta -> descrição; para `fonte` vazia, o ano decide entre os
# dois trechos do baseline histórico (README.md: "Série histórica
# (MERRA-2 1981-1995 + Sinobras 1996-hoje)").
ANO_FIM_MERRA2 = 1995   # README.md — 1981-1995 MERRA-2, 1996+ Sinobras
PROCEDENCIA_MERRA2 = 'MERRA-2 (reanálise NASA, README.md: baseline 1981-1995)'
PROCEDENCIA_ESTACAO_SINOBRAS = 'Estação Sinobras (leitura direta de campo, README.md: baseline 1996-presente)'
PROCEDENCIA_CHIRPS_FINAL = 'CHIRPS Final (fonte=CHIRPS, fetch_monthly_data.py)'
PROCEDENCIA_CHC_PRELIMINAR = 'CHC Preliminary (fonte=CHC-Preliminar, fetch_monthly_data.py — preliminar/estimado)'
PROCEDENCIA_ERA5 = 'Open-Meteo ERA5-Land (fonte=OpenMeteo-ERA5, fetch_monthly_data.py — fallback final/estimado)'
PROCEDENCIA_DESCONHECIDA = 'DESCONHECIDA (fonte não catalogada por este módulo)'

# Seção 1 (revisão pontual) — checagens de qualidade EFETIVAMENTE
# COMPUTADAS por registro (nunca inferidas da procedência): valor
# numérico ausente, registro duplicado (mesmo ano/mês aparecendo mais
# de 1 vez na série — problema de integridade da série, não do CFSv2),
# valor fora da faixa fisicamente plausível. Limites de plausibilidade
# REAPROVEITADOS de scripts/c3s_poc.py (PREC_MM_MIN/MAX_PLAUSIVEL,
# calibrados contra CHIRPS real da mesma região, Fase 2A) — nunca uma
# fórmula nova.
QUALIDADE_STATUS_OK = 'OK'
QUALIDADE_FLAG_VALOR_AUSENTE = 'VALOR_AUSENTE'
QUALIDADE_FLAG_REGISTRO_DUPLICADO = 'REGISTRO_DUPLICADO'
QUALIDADE_FLAG_VALOR_IMPLAUSIVEL = 'VALOR_FISICAMENTE_IMPLAUSIVEL'
QUALIDADE_STATUS_NAO_APLICAVEL_AUSENTE = 'NAO_APLICAVEL_MES_AUSENTE'
PREC_MM_MIN_PLAUSIVEL = cpoc.PREC_MM_MIN_PLAUSIVEL
PREC_MM_MAX_PLAUSIVEL = cpoc.PREC_MM_MAX_PLAUSIVEL

# Seção 2 — a série observacional de produção (data/serie_subst.csv)
# representa o CENTROIDE DAS FAZENDAS (scripts/_chirps.py::FAZENDAS_LAT/
# FAZENDAS_LON = -7.80/-47.95), README.md: "MERRA-2 1981-1995 + Sinobras
# 1996-hoje" — NÃO é CHIRPS para a maior parte da série (achado da
# tarefa anterior, ver docs/nmme-fase2c2-piloto-cobertura-observacional.md).
# O ponto usado pelo POC/piloto do CFSv2 é São Bento do Tocantins
# (scripts/_c3s_utils.py::MUNICIPIOS), herdado das fases C3S (Seção 15
# do catálogo) — os dois pontos NÃO coincidem; a distância é computada
# abaixo, uma vez, reaproveitando a mesma função já usada para a
# distância grade-CFSv2<->ponto-pedido (nunca uma fórmula nova). As
# coordenadas do POC/CFSv2 (São Bento) NÃO são alteradas por esta
# revisão (instrução explícita da tarefa).
FAZENDAS_LAT, FAZENDAS_LON = -7.80, -47.95


def _procedencia_documental(ano, fonte_bruta):
    """Descreve de onde o registro VEM documentalmente — nunca uma
    afirmação sobre a qualidade individual desse valor (Seção 1,
    revisão pontual: "separar procedência documental de procedência e
    qualidade efetivamente verificadas")."""
    if fonte_bruta is not None:
        mapa = {'CHIRPS': PROCEDENCIA_CHIRPS_FINAL, 'CHC-Preliminar': PROCEDENCIA_CHC_PRELIMINAR,
                'OpenMeteo-ERA5': PROCEDENCIA_ERA5}
        return mapa.get(fonte_bruta, PROCEDENCIA_DESCONHECIDA)
    return PROCEDENCIA_MERRA2 if ano <= ANO_FIM_MERRA2 else PROCEDENCIA_ESTACAO_SINOBRAS


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
    mesmo quando reprovada/com erro inesperado.

    `representacao_diferente_da_validada` (Seção 4, revisão pontual) —
    True quando `dataset_representation_used` está preenchida e é
    DIFERENTE de NMME_HARMONIZED_MONTHLY (ex.: fallback documentado
    para a Representação A por `nmme_download.ordem_tentativa_
    member_level` quando B falha por acesso). Uma origem assim pode
    ainda estar `poc_status=APROVADO` (os guardrails de integridade não
    distinguem representação) — mas NUNCA deve ser lida como tendo
    usado a mesma rota EMPIRICALLY_CONFIRMED da Fase 2C.1b; esta coluna
    existe para que isso nunca fique implícito."""
    linhas = []
    for item in resultados_piloto:
        r, erro = item['resultado'], item['erro']
        checklist = r.get('checklist', {})
        raw_df = r.get('raw_df', pd.DataFrame())
        representacao_usada = r.get('dataset_representation_used')
        backend_usado = r.get('backend_used')
        linhas.append({
            'ano': item['ano'], 'mes': item['mes'],
            'init_date': f"{item['ano']}-{item['mes']:02d}",
            'poc_status': r.get('poc_status'),
            'backend_used': backend_usado,
            'backend_diferente_da_validada': bool(
                backend_usado is not None and backend_usado != ncat.SOURCE_BACKEND_IRIDL_LEGACY),
            'dataset_representation_used': representacao_usada,
            'representacao_diferente_da_validada': bool(
                representacao_usada is not None
                and representacao_usada != ncat.REPR_NMME_HARMONIZED_MONTHLY),
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


def _origens_aprovadas_com_rota_diferente(resultados_piloto):
    """Ajuste pontual (Seção 1 da tarefa) — para cada origem com
    `poc_status=APROVADO`, exige exatamente backend=IRIDL_LEGACY E
    representação=NMME_HARMONIZED_MONTHLY (a rota EMPIRICALLY_CONFIRMED
    da Fase 2C.1b). Isso NUNCA toca no mecanismo de fallback do POC
    original (`nmme_download.ordem_tentativa_member_level` continua
    tentando CCSR/Representação A exatamente como antes, e uma origem
    que caia para elas continua podendo ficar `poc_status=APROVADO`
    individualmente — os guardrails de integridade não distinguem
    representação) — só REGISTRA a ocorrência aqui, para a agregação do
    piloto poder reprovar por causa dela sem reescrever o que já existe
    no nível de 1 origem."""
    ocorrencias = []
    for item in resultados_piloto:
        r = item['resultado']
        if r.get('poc_status') != 'APROVADO':
            continue
        backend_usado = r.get('backend_used')
        representacao_usada = r.get('dataset_representation_used')
        rota_ok = (backend_usado == ncat.SOURCE_BACKEND_IRIDL_LEGACY
                   and representacao_usada == ncat.REPR_NMME_HARMONIZED_MONTHLY)
        if not rota_ok:
            ocorrencias.append({
                'origem': f"{item['ano']}-{item['mes']:02d}",
                'backend_used': backend_usado, 'dataset_representation_used': representacao_usada,
            })
    return ocorrencias


def _verificar_integridade_das_origens(resultados_piloto, origens_esperadas):
    """Seção 2 da tarefa — confirma que o agregado contém EXATAMENTE as
    origens previstas: sem duplicata (mesma origem processada 2 vezes)
    e sem ausência (uma origem prevista que nunca aparece no
    agregado)."""
    from collections import Counter
    origens_observadas = [item['origem'] for item in resultados_piloto]
    contagem = Counter(origens_observadas)
    duplicadas = sorted(o for o, n in contagem.items() if n > 1)
    esperadas = set(origens_esperadas)
    observadas = set(origens_observadas)
    ausentes = sorted(esperadas - observadas)
    inesperadas = sorted(observadas - esperadas)
    ok = not duplicadas and not ausentes and not inesperadas
    return {'ok': ok, 'origens_duplicadas': duplicadas, 'origens_ausentes': ausentes,
            'origens_inesperadas': inesperadas, 'n_esperadas': len(esperadas),
            'n_observadas': len(origens_observadas)}


def avaliar_aprovacao_piloto(resultados_piloto, origens_esperadas=PILOTO_ORIGENS):
    """Critérios objetivos de aprovação da INFRAESTRUTURA do PILOTO,
    distintos da aprovação de cada origem isolada
    (docs/nmme-fase2c2-especificacao.md, Seção G) e — revisão pontual,
    Seção 3 da tarefa anterior — deliberadamente SEPARADOS da aptidão da
    referência observacional (`avaliar_aptidao_referencia_
    observacional`, função à parte):
    1. todas as origens com poc_status=APROVADO;
    2. nenhum erro inesperado (fora do vocabulário de status já
       conhecido do POC);
    3. (ajuste pontual, Seção 1) toda origem APROVADA usou exatamente
       backend=IRIDL_LEGACY e representação=NMME_HARMONIZED_MONTHLY —
       um fallback para outra rota, mesmo que a origem em si passe nos
       guardrails de integridade, IMPEDE a aprovação AGREGADA do
       piloto (a ocorrência fica registrada em
       `origens_com_rota_diferente`, nunca escondida);
    4. (ajuste pontual, Seção 2) o agregado contém exatamente as
       origens esperadas — sem duplicata, sem ausência (detalhes em
       `integridade_origens`).

    A insuficiência/procedência da série observacional NUNCA entra
    aqui — isso seria confundir "o CFSv2 respondeu e passou nos
    guardrails de integridade" com "a observação de referência está
    pronta para comparação científica", exatamente o que a tarefa
    anterior pediu para nunca confundir."""
    status_por_origem = [item['resultado'].get('poc_status') for item in resultados_piloto]
    n_total = len(resultados_piloto)
    n_aprovadas = sum(1 for s in status_por_origem if s == 'APROVADO')
    todas_aprovadas = n_aprovadas == n_total
    nenhum_erro_inesperado = not any(item['erro'] for item in resultados_piloto)

    origens_com_rota_diferente = _origens_aprovadas_com_rota_diferente(resultados_piloto)
    rota_validada_ok = not origens_com_rota_diferente

    integridade_origens = _verificar_integridade_das_origens(resultados_piloto, origens_esperadas)

    criterios = {
        'todas_origens_aprovadas': todas_aprovadas,
        'nenhum_erro_inesperado': nenhum_erro_inesperado,
        'todas_aprovadas_usaram_rota_validada': rota_validada_ok,
        'integridade_das_origens_ok': integridade_origens['ok'],
    }
    aprovado = all(criterios.values())
    return {
        'piloto_status': 'APROVADO' if aprovado else 'REPROVADO',
        'n_origens_aprovadas': n_aprovadas, 'n_origens_total': n_total,
        'criterios': criterios,
        'origens_com_rota_diferente': origens_com_rota_diferente,
        'integridade_origens': integridade_origens,
    }


def avaliar_aptidao_referencia_observacional(cobertura_df):
    """Seção 3 da tarefa — verdito SEPARADO de `avaliar_aprovacao_
    piloto`: nunca reportado como falha de acesso ao CFSv2, e nunca
    combinado no mesmo `piloto_status`. Responde: "a referência
    observacional está pronta para uma avaliação científica (cálculo de
    skill) futura?".

    Bloqueios computados a partir de `cobertura_df`
    (`verificar_cobertura_observacional`): meses ausentes, registros
    com procedência substituída/estimada (CHC-Preliminar/ERA5), e
    qualquer flag de qualidade (`valor_ausente`, `registro_duplicado`,
    `valor_implausivel`) diferente de OK.

    Bloqueio ESTRUTURAL, sempre presente nesta revisão (Seção 2 da
    tarefa: "consequências para uma futura avaliação científica"): a
    correspondência espacial entre a referência observacional
    (centroide das fazendas) e o ponto usado pelo CFSv2 (São Bento do
    Tocantins) NÃO foi resolvida — 198 km de distância, ver
    `distancia_fazendas_ate_municipio_km` e
    `docs/nmme-fase2c2-piloto-cobertura-observacional.md`. Enquanto essa
    questão não for resolvida por decisão explícita, este módulo NUNCA
    declara aptidão para cálculo de skill, mesmo que toda a cobertura/
    qualidade dos dados esteja limpa."""
    bloqueios = []
    if cobertura_df is None or not len(cobertura_df):
        bloqueios.append('cobertura observacional não avaliada (cobertura_df ausente/vazia)')
        n_disponiveis = n_procedencia_nao_substituida = n_qualidade_ok = 0
        n_total = 0
    else:
        n_total = len(cobertura_df)
        n_ausentes = int((cobertura_df['disponibilidade'] == 'AUSENTE').sum())
        n_disponiveis = n_total - n_ausentes
        if n_ausentes:
            bloqueios.append(f'{n_ausentes}/{n_total} combinação(ões) origem×lead sem registro '
                              f'histórico disponível na série observacional')
        n_substituidos = int(cobertura_df['fonte_e_substituta_nao_usar'].sum())
        n_procedencia_nao_substituida = n_disponiveis - n_substituidos
        if n_substituidos:
            bloqueios.append(f'{n_substituidos}/{n_total} combinação(ões) com procedência '
                              f'preliminar/estimada (CHC-Preliminar/OpenMeteo-ERA5) — nunca usável '
                              f'como observação real')
        n_qualidade_ruim = int((cobertura_df['qualidade_verificada_status']
                                  .isin([QUALIDADE_FLAG_VALOR_AUSENTE, QUALIDADE_FLAG_REGISTRO_DUPLICADO,
                                          QUALIDADE_FLAG_VALOR_IMPLAUSIVEL])
                                  | cobertura_df['qualidade_verificada_status'].str.contains(';', na=False))
                                 .sum())
        n_qualidade_ok = n_total - n_qualidade_ruim
        if n_qualidade_ruim:
            bloqueios.append(f'{n_qualidade_ruim}/{n_total} combinação(ões) com flag de qualidade '
                              f'(valor ausente, registro duplicado ou fisicamente implausível)')

    # Bloqueio estrutural — sempre presente nesta revisão (não resolvido
    # aqui, só documentado). Ver docstring acima.
    dist_km = distancia_fazendas_ate_municipio_km()
    bloqueios.append(f'correspondência espacial não resolvida — {round(dist_km, 1)} km entre a '
                      f'referência observacional (centroide das fazendas) e o ponto do CFSv2 '
                      f'(São Bento do Tocantins); decisão explícita pendente '
                      f'(docs/nmme-fase2c2-piloto-cobertura-observacional.md)')

    return {
        'apto_para_avaliacao_cientifica': not bloqueios,
        'motivos_bloqueio': bloqueios,
        'n_combinacoes_total': n_total,
        'n_combinacoes_disponiveis': n_disponiveis,
        'n_combinacoes_procedencia_nao_substituida': n_procedencia_nao_substituida,
        'n_combinacoes_qualidade_ok': n_qualidade_ok,
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
    """Seção 1/3 da tarefa (revisão pontual) — para cada combinação
    origem x lead efetivamente processada, verifica o mês-alvo contra a
    série de produção (data/serie_subst.csv) e separa TRÊS conceitos
    (nunca colapsados num único rótulo "confirmado"):

    1. `disponibilidade` (PRESENTE/AUSENTE) — o mês-alvo tem QUALQUER
       registro na série, independente de procedência/qualidade.
    2. `procedencia_documental` — de onde o registro vem, segundo a
       documentação do próprio projeto (README.md/fetch_monthly_data.py):
       MERRA-2, Estação Sinobras, CHIRPS Final, CHC Preliminary, ERA5,
       ou DESCONHECIDA. Isso é uma descrição, nunca uma afirmação de
       qualidade.
    3. `qualidade_verificada_status` — checagens EFETIVAMENTE
       COMPUTADAS sobre o valor: `VALOR_AUSENTE` (NaN em `prec`),
       `REGISTRO_DUPLICADO` (mesmo ano/mês aparece mais de 1 vez na
       série — problema de integridade da própria série), e
       `VALOR_FISICAMENTE_IMPLAUSIVEL` (fora de [PREC_MM_MIN_PLAUSIVEL,
       PREC_MM_MAX_PLAUSIVEL], mm/mês) — `OK` quando nenhuma dispara;
       várias flags juntas ficam unidas por `;`.

    Além disso, `fonte_e_substituta_nao_usar` preserva o guardrail já
    existente: True quando `fonte` está em FONTES_NAO_CONFIRMADAS
    (CHC-Preliminar/OpenMeteo-ERA5) — a tarefa pede explicitamente para
    nunca tratar esses registros como observação real, mesmo que
    disponíveis e sem flag de qualidade.

    Este módulo NUNCA soma esses 3 conceitos num "% confirmado" único —
    quem precisar de um resumo agregado usa
    `avaliar_aptidao_referencia_observacional`, que também incorpora o
    bloqueio estrutural da correspondência espacial (Seção 2).

    Nunca usa o RAW do CFSv2 para decidir isso — só a série
    observacional, independente de o POC daquela origem ter sido
    aprovado ou não (a cobertura é uma propriedade da OBSERVAÇÃO, não
    da previsão)."""
    if serie_df is None:
        serie_df = _carregar_serie_observacional()
    elif 'target_month' not in serie_df.columns:
        serie_df = _com_coluna_target_month(serie_df)

    # Seção 1 — duplicata é uma propriedade da SÉRIE (mesmo ano/mês
    # aparecendo mais de 1 vez), calculada uma vez sobre o dataframe
    # inteiro, nunca por combinação isolada (senão um `match.iloc[0]`
    # ingênuo escondera a duplicata ao só olhar a primeira ocorrência).
    meses_duplicados = set(serie_df.loc[serie_df.duplicated(subset=['ano', 'mes'], keep=False),
                                          'target_month'])

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
                linhas.append({
                    'origem_piloto': origem_str, 'H_lead': lead, 'target_month': str(target_month),
                    'disponibilidade': 'AUSENTE', 'procedencia_documental': None,
                    'fonte_e_substituta_nao_usar': False,
                    'qualidade_verificada_status': QUALIDADE_STATUS_NAO_APLICAVEL_AUSENTE,
                })
                continue

            registro = match.iloc[0]
            fonte_bruta = None if pd.isna(registro['fonte']) else str(registro['fonte'])
            procedencia = _procedencia_documental(target_month.year, fonte_bruta)
            substituta_nao_usar = fonte_bruta in FONTES_NAO_CONFIRMADAS

            flags = []
            valor = registro['prec']
            if pd.isna(valor):
                flags.append(QUALIDADE_FLAG_VALOR_AUSENTE)
            else:
                if not (PREC_MM_MIN_PLAUSIVEL <= float(valor) <= PREC_MM_MAX_PLAUSIVEL):
                    flags.append(QUALIDADE_FLAG_VALOR_IMPLAUSIVEL)
            if target_month in meses_duplicados:
                flags.append(QUALIDADE_FLAG_REGISTRO_DUPLICADO)
            qualidade_status = ';'.join(flags) if flags else QUALIDADE_STATUS_OK

            linhas.append({
                'origem_piloto': origem_str, 'H_lead': lead, 'target_month': str(target_month),
                'disponibilidade': 'PRESENTE', 'procedencia_documental': procedencia,
                'fonte_e_substituta_nao_usar': substituta_nao_usar,
                'qualidade_verificada_status': qualidade_status,
            })
    return pd.DataFrame(linhas)


def montar_metadata_piloto(resultados_piloto, cobertura_df, aprovacao, aptidao):
    dist_km = distancia_fazendas_ate_municipio_km()
    from _c3s_utils import MUNICIPIOS
    info_municipio = MUNICIPIOS[npoc.MUNICIPIO]
    resumo_df = montar_resumo_por_origem(resultados_piloto)
    n_repr_diferente = int(resumo_df['representacao_diferente_da_validada'].sum())
    return {
        'fase': '2C.2 — piloto histórico CFSv2 (16 inicializações)',
        'periodo': f'{min(PILOTO_ANOS)}-{max(PILOTO_ANOS)}', 'anos': list(PILOTO_ANOS),
        'meses': list(PILOTO_MESES), 'n_origens': len(PILOTO_ORIGENS), 'leads': list(npoc.LEADS),
        'representacao': ncat.REPR_NMME_HARMONIZED_MONTHLY, 'politica_membros': 'exatamente 24 por lead',
        'n_origens_com_representacao_diferente_da_validada': n_repr_diferente,
        # Seção 2 da tarefa — coordenadas de cada lado, nunca só a
        # distância isolada, e nunca chamado de "CHIRPS" (não é).
        'previsao_cfsv2_ponto': npoc.MUNICIPIO,
        'previsao_cfsv2_lat': info_municipio['lat'], 'previsao_cfsv2_lon': info_municipio['lon'],
        'serie_observacional_ponto': 'centroide das fazendas',
        'serie_observacional_lat': FAZENDAS_LAT, 'serie_observacional_lon': FAZENDAS_LON,
        'serie_observacional_procedencia_documental': (
            'MERRA-2 (reanálise, 1981-1995) + Estação Sinobras (leitura direta, 1996-presente) — '
            'README.md; NÃO é CHIRPS para o período do piloto (1991-2010)'),
        'distancia_previsao_observacao_km': round(dist_km, 1),
        'consequencias_avaliacao_cientifica_futura': (
            'Distância de ~198 km entre a previsão do CFSv2 (São Bento do Tocantins) e a série '
            'observacional (centroide das fazendas) pode introduzir divergência puramente espacial '
            '(variabilidade convectiva local, CLAUDE.md armadilha 7) numa futura comparação de '
            'skill, independente da habilidade preditiva real do modelo — mesma limitação já '
            'presente nas comparações C3S/SEAS5 anteriores contra a mesma série, não introduzida '
            'por este piloto.'),
        'piloto_status': aprovacao['piloto_status'],
        'n_origens_aprovadas': aprovacao['n_origens_aprovadas'],
        'n_origens_total': aprovacao['n_origens_total'],
        'criterios_aprovacao_piloto': aprovacao['criterios'],
        # Ajuste pontual (Seção 1/2 da tarefa) — nunca escondido: se
        # alguma origem aprovada usou rota diferente da validada, ou se
        # o agregado não bate exatamente com as origens esperadas, a
        # ocorrência fica aqui mesmo quando NÃO derruba piloto_status
        # (o que não deveria acontecer, já que ambas são critérios
        # bloqueantes — mas exposto de qualquer forma para depuração).
        'origens_aprovadas_com_rota_diferente_da_validada': aprovacao['origens_com_rota_diferente'],
        'integridade_das_origens': aprovacao['integridade_origens'],
        # Seção 3 — verdito SEPARADO, nunca combinado com piloto_status.
        'referencia_observacional_apta_para_avaliacao_cientifica':
            aptidao['apto_para_avaliacao_cientifica'],
        'referencia_observacional_motivos_bloqueio': aptidao['motivos_bloqueio'],
        'referencia_observacional_cobertura': {
            'n_combinacoes_total': aptidao['n_combinacoes_total'],
            'n_combinacoes_disponiveis': aptidao['n_combinacoes_disponiveis'],
            'n_combinacoes_procedencia_nao_substituida': aptidao['n_combinacoes_procedencia_nao_substituida'],
            'n_combinacoes_qualidade_ok': aptidao['n_combinacoes_qualidade_ok'],
        },
        'nenhuma_skill_calculada': True, 'nenhum_dashboard_alterado': True,
        'status_cfsv2_data_access': 'POC_READY_DOCUMENTED (inalterado — decisão explícita)',
    }


def escrever_saidas_piloto(resultados_piloto, cobertura_df, aprovacao, aptidao):
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    raw_df, temporal_df, access_df = concatenar_dataframes_piloto(resultados_piloto)
    resumo_df = montar_resumo_por_origem(resultados_piloto)
    raw_df.to_csv(ARTIFACTS_DIR / 'piloto_raw.csv', index=False)
    temporal_df.to_csv(ARTIFACTS_DIR / 'piloto_temporal_audit.csv', index=False)
    access_df.to_csv(ARTIFACTS_DIR / 'piloto_access_audit.csv', index=False)
    resumo_df.to_csv(ARTIFACTS_DIR / 'piloto_resumo_por_origem.csv', index=False)
    cobertura_df.to_csv(ARTIFACTS_DIR / 'piloto_cobertura_observacional.csv', index=False)

    metadata = montar_metadata_piloto(resultados_piloto, cobertura_df, aprovacao, aptidao)
    (ARTIFACTS_DIR / 'metadata.json').write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=str))
    relatorio = gerar_relatorio_piloto_markdown(resultados_piloto, resumo_df, cobertura_df,
                                                   aprovacao, aptidao)
    (ARTIFACTS_DIR / 'RELATORIO.md').write_text(relatorio)

    for nome in ('piloto_raw.csv', 'piloto_temporal_audit.csv', 'piloto_access_audit.csv',
                  'piloto_resumo_por_origem.csv', 'piloto_cobertura_observacional.csv',
                  'metadata.json', 'RELATORIO.md'):
        print(f"  ✅ artifacts/nmme_piloto_historico/{nome}")
    return metadata, relatorio


def gerar_relatorio_piloto_markdown(resultados_piloto, resumo_df, cobertura_df, aprovacao, aptidao):
    linhas = ["# NMME — Piloto histórico CFSv2 (Fase 2C.2)", "",
              "**Piloto de infraestrutura — 16 inicializações, nunca conclusão científica "
              "(Seção 4 da tarefa: 'não calcular conclusões científicas definitivas a partir "
              "do piloto de infraestrutura').**", "",
              "## Dois resultados SEPARADOS (Seção 3, revisão pontual)", "",
              "Aprovação de infraestrutura (acesso/seleção temporal/membros/horizontes/RAW) e "
              "aptidão da referência observacional (procedência/qualidade/correspondência espacial) "
              "NUNCA são combinadas num único veredito — a insuficiência da segunda nunca é "
              "reportada como falha da primeira.", "",
              f"### Infraestrutura: {aprovacao['piloto_status']}", "",
              f"- Origens aprovadas: {aprovacao['n_origens_aprovadas']}/{aprovacao['n_origens_total']}"]
    for criterio, valor in aprovacao['criterios'].items():
        linhas.append(f"  - `{criterio}`: {valor}")
    n_repr_diferente = int(resumo_df['representacao_diferente_da_validada'].sum())
    n_backend_diferente = int(resumo_df['backend_diferente_da_validada'].sum())
    linhas.append(f"- Origens com representação DIFERENTE da rota EMPIRICALLY_CONFIRMED "
                   f"(NMME_HARMONIZED_MONTHLY): {n_repr_diferente} "
                   f"{'⚠️ ver coluna representacao_diferente_da_validada no resumo por origem' if n_repr_diferente else ''}")
    linhas.append(f"- Origens com backend DIFERENTE da rota EMPIRICALLY_CONFIRMED "
                   f"(IRIDL_LEGACY): {n_backend_diferente} "
                   f"{'⚠️ ver coluna backend_diferente_da_validada no resumo por origem' if n_backend_diferente else ''}")
    if aprovacao['origens_com_rota_diferente']:
        linhas.append("- ⚠️ Origens APROVADAS individualmente que usaram rota diferente da "
                       "validada (impede a aprovação AGREGADA do piloto, item 1 do ajuste pontual):")
        for oc in aprovacao['origens_com_rota_diferente']:
            linhas.append(f"  - {oc['origem']}: backend={oc['backend_used']}, "
                           f"representacao={oc['dataset_representation_used']}")
    integridade = aprovacao['integridade_origens']
    if not integridade['ok']:
        linhas.append("- ⚠️ Integridade das origens comprometida (item 2 do ajuste pontual):")
        if integridade['origens_duplicadas']:
            linhas.append(f"  - duplicadas: {integridade['origens_duplicadas']}")
        if integridade['origens_ausentes']:
            linhas.append(f"  - ausentes: {integridade['origens_ausentes']}")
        if integridade['origens_inesperadas']:
            linhas.append(f"  - inesperadas (fora do plano): {integridade['origens_inesperadas']}")
    linhas += ["",
               f"### Aptidão da referência observacional para avaliação científica: "
               f"{'APTA' if aptidao['apto_para_avaliacao_cientifica'] else 'NÃO APTA'}", ""]
    for motivo in aptidao['motivos_bloqueio']:
        linhas.append(f"- ❌ {motivo}")
    if not aptidao['motivos_bloqueio']:
        linhas.append("- (nenhum bloqueio identificado)")
    linhas += ["", "## Resumo por origem", "",
              "| Origem | Status | RAW | Backend | ≠ validada | Representação | ≠ validada | "
              "Membros/lead OK | Mapeamento temporal | Unidade | Grade | Erro |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, row in resumo_df.iterrows():
        linhas.append(f"| {row['init_date']} | {row['poc_status']} | {row['n_raw']} | "
                       f"{row['backend_used']} | {row['backend_diferente_da_validada']} | "
                       f"{row['dataset_representation_used']} | "
                       f"{row['representacao_diferente_da_validada']} | "
                       f"{row['member_count_per_lead_ok']} | {row['temporal_mapping_confirmado']} | "
                       f"{row['unidade_confirmada']} | {row['grade_confirmada']} | {row['erro_inesperado']} |")
    linhas += ["", "## Cobertura da série observacional (disponibilidade / procedência / qualidade)",
               "", "**Nunca resumida como \"% confirmado\" — os três conceitos são reportados "
               "separadamente (Seção 1, revisão pontual).**", "",
               f"Total de combinações origem×lead avaliadas: {len(cobertura_df)}"]
    if len(cobertura_df):
        linhas.append(f"- Disponibilidade: {(cobertura_df['disponibilidade'] == 'PRESENTE').sum()} "
                       f"presentes / {(cobertura_df['disponibilidade'] == 'AUSENTE').sum()} ausentes")
        linhas.append("- Procedência documental (entre os presentes):")
        for proc, n in cobertura_df['procedencia_documental'].value_counts().items():
            linhas.append(f"  - `{proc}`: {n}")
        linhas.append(f"- Procedência preliminar/estimada (nunca usar como observação real): "
                       f"{int(cobertura_df['fonte_e_substituta_nao_usar'].sum())}")
        linhas.append("- Qualidade efetivamente verificada:")
        for status, n in cobertura_df['qualidade_verificada_status'].value_counts().items():
            linhas.append(f"  - `{status}`: {n}")
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
    print(f"  representacao_validada: {ncat.REPR_NMME_HARMONIZED_MONTHLY} "
          f"(qualquer origem que usar outra é registrada explicitamente, nunca tratada como equivalente)")
    print("  politica_membros: exatamente 24 por lead (guardrail existente, sem alteração)")
    from _c3s_utils import MUNICIPIOS
    info_municipio = MUNICIPIOS[npoc.MUNICIPIO]
    print(f"  previsao_cfsv2_ponto: {npoc.MUNICIPIO} (lat={info_municipio['lat']}, "
          f"lon={info_municipio['lon']}) — coordenadas do POC, NÃO alteradas por esta revisão")
    print(f"  serie_observacional_ponto: centroide das fazendas "
          f"(lat={FAZENDAS_LAT}, lon={FAZENDAS_LON}) — NÃO é CHIRPS (MERRA-2 1981-1995 + "
          f"Estação Sinobras 1996-presente, README.md)")
    dist_km = distancia_fazendas_ate_municipio_km()
    print(f"  distancia_previsao_observacao_km: {round(dist_km, 1)}")
    print("  status_cfsv2_data_access: POC_READY_DOCUMENTED (inalterado nesta tarefa)")
    print(f"  requests_previstos: {len(PILOTO_ORIGENS)} (1 por origem, nunca em lote)")
    print("  aptidao_referencia_observacional_para_skill: sempre avaliada separadamente da "
          "aprovação de infraestrutura (nunca combinadas)")


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
        aprovacao = avaliar_aprovacao_piloto(resultados)
        aptidao = avaliar_aptidao_referencia_observacional(cobertura_df)
        escrever_saidas_piloto(resultados, cobertura_df, aprovacao, aptidao)
        print(f"\npiloto_status={aprovacao['piloto_status']} "
              f"({aprovacao['n_origens_aprovadas']}/{aprovacao['n_origens_total']} origens aprovadas)")
        for k, v in aprovacao['criterios'].items():
            print(f"  - {k}: {v}")
        for oc in aprovacao['origens_com_rota_diferente']:
            print(f"  - ⚠️ origem {oc['origem']} aprovada individualmente com rota diferente da "
                  f"validada: backend={oc['backend_used']}, representacao={oc['dataset_representation_used']}")
        integridade = aprovacao['integridade_origens']
        if not integridade['ok']:
            print(f"  - ⚠️ integridade das origens comprometida: "
                  f"duplicadas={integridade['origens_duplicadas']} "
                  f"ausentes={integridade['origens_ausentes']} "
                  f"inesperadas={integridade['origens_inesperadas']}")
        print(f"\nreferencia_observacional_apta_para_avaliacao_cientifica="
              f"{aptidao['apto_para_avaliacao_cientifica']}")
        for motivo in aptidao['motivos_bloqueio']:
            print(f"  - bloqueio: {motivo}")
        # Seção 3 — só a aprovação de INFRAESTRUTURA determina o exit
        # code; a aptidão da referência observacional é informativa,
        # nunca reportada como falha de acesso ao CFSv2.
        if aprovacao['piloto_status'] != 'APROVADO':
            raise SystemExit(f"Piloto histórico REPROVADO (infraestrutura) — ver "
                              f"artifacts/nmme_piloto_historico/piloto_resumo_por_origem.csv "
                              f"para o motivo por origem.")
        print("\n✅ Piloto histórico do CFSv2 APROVADO (infraestrutura) — ver "
              "artifacts/nmme_piloto_historico/RELATORIO.md")
        if not aptidao['apto_para_avaliacao_cientifica']:
            print("⚠️  Referência observacional AINDA NÃO apta para avaliação científica — "
                  "ver motivos de bloqueio acima e docs/nmme-fase2c2-piloto-cobertura-observacional.md.")
        return

    imprimir_plano()
    print("\n✅ Plano do piloto histórico gerado (infraestrutura só — nenhum download real).")


if __name__ == '__main__':
    main()
