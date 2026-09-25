#!/usr/bin/env python3
"""
nmme_extracao_historica.py — Fase 2C.2, extração histórica completa do
CFSv2 (240 inicializações mensais, 1991-2010), em LOTES independentes
com retomada.

Contexto: o piloto de 16 inicializações (scripts/nmme_piloto_historico.py)
rodou de verdade e foi aprovado (GitHub Actions run 36145108571,
16/16 origens, rota IRIDL_LEGACY/NMME_HARMONIZED_MONTHLY exclusiva,
24 membros/lead, integridade das origens confirmada). Este módulo
prepara a extração completa (240 origens) SEM executá-la
automaticamente — cada lote precisa ser disparado explicitamente.

Reaproveita, sem modificar, TODA a orquestração já testada do piloto
(scripts/nmme_piloto_historico.py::executar_piloto_historico/
avaliar_aprovacao_piloto/montar_resumo_por_origem) — este módulo só
adiciona: divisão em lotes, armazenamento permanente (commitado em
data/, não só artifact do GitHub Actions — retenção de 30 dias é
insuficiente para um histórico de 20 anos), retomada (uma origem já
com poc_status=APROVADO persistida NUNCA é reconsultada) e
consolidação final.

Nunca calcula skill, nunca modifica o dashboard, nunca promove
nenhuma rota/representação/sistema no catálogo (scripts/nmme_catalogo.py
nunca é importado por escrita aqui).

Revisão pontual (3ª rodada) — este módulo agora prepara a extração
histórica para DUAS localidades independentes:

- São Bento do Tocantins (existente, `MUNICIPIOS`/`npoc.MUNICIPIO`,
  nunca alterado) — `data/nmme_historico/`.
- Centroide das fazendas (lat=-7,80, lon=-47,95, mesmo valor de
  `scripts/_chirps.py`/`scripts/nmme_poc_espacial_fazendas.py`) —
  `data/nmme_historico_fazendas/`, diretório PRÓPRIO, nunca
  compartilhado com o de São Bento.

O POC de infraestrutura para o centroide das fazendas já rodou de
verdade e foi aprovado (GitHub Actions run 36169942349 —
`scripts/nmme_poc_espacial_fazendas.py`, 144 registros RAW, 6
horizontes, 24 membros/horizonte, 6 auditorias temporais aprovadas,
rota IRIDL_LEGACY/NMME_HARMONIZED_MONTHLY exclusiva). Isso aprova a
INFRAESTRUTURA de acesso a este ponto — nunca promove automaticamente
o centroide das fazendas a localização "validada" nem declara aptidão
científica; ver `EVIDENCIA_POC_FAZENDAS` abaixo e
`scripts/nmme_poc_espacial_fazendas.py::montar_metadata_espacial`
(`localizacao_validada` sempre `False`, mesmo lá).

Roda com:
    python scripts/nmme_extracao_historica.py --dry-run-plan
    python scripts/nmme_extracao_historica.py --executar-lote 1991-1994 --localizacao sao_bento
    python scripts/nmme_extracao_historica.py --executar-lote 1991-1994 --localizacao fazendas
    python scripts/nmme_extracao_historica.py --consolidar --localizacao fazendas
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import nmme_piloto_historico as pilo  # noqa: E402

# Armazenamento PERMANENTE — commitado no repositório (mesma convenção
# de data/serie_subst.csv), nunca dependente só do artifact do GitHub
# Actions (retention-days: 30, insuficiente para um histórico de 20
# anos que não deve precisar ser reprocessado do zero a cada mês).
DIRETORIO_HISTORICO = ROOT / 'data' / 'nmme_historico'   # São Bento do Tocantins — caminho preservado

# Revisão pontual (3ª rodada) — diretório PRÓPRIO para o centroide das
# fazendas, nunca compartilhado nem misturado com o de São Bento
# (item 2 da revisão: "impedindo que registros das duas localidades
# sejam misturados").
DIRETORIO_HISTORICO_FAZENDAS = ROOT / 'data' / 'nmme_historico_fazendas'

# Identificadores de localização — usados para marcar toda linha
# persistida (resumo/raw/temporal/access) e para a verificação de
# integridade cruzada (item 5 da revisão), nunca só um par lat/lon
# solto sem rótulo auditável.
LOCALIZACAO_SAO_BENTO = 'Sao_Bento_do_Tocantins'
LOCALIZACAO_FAZENDAS = 'Fazendas_Sinobras_Centroide'
LOCALIZACOES_VALIDAS = (LOCALIZACAO_SAO_BENTO, LOCALIZACAO_FAZENDAS)

# Mesmo valor de scripts/_chirps.py::FAZENDAS_LAT/FAZENDAS_LON e
# scripts/nmme_poc_espacial_fazendas.py — nunca redefinido de forma
# diferente (Seção 2 da tarefa anterior: coordenada do centroide das
# fazendas).
FAZENDAS_LAT, FAZENDAS_LON = -7.80, -47.95

DIRETORIO_POR_LOCALIZACAO = {
    LOCALIZACAO_SAO_BENTO: DIRETORIO_HISTORICO,
    LOCALIZACAO_FAZENDAS: DIRETORIO_HISTORICO_FAZENDAS,
}

# Evidência formal do POC de infraestrutura aprovado para o centroide
# das fazendas (item 6 da revisão) — registrada aqui, citada na
# metadata de todo lote rodado para `LOCALIZACAO_FAZENDAS`. NUNCA
# promove automaticamente a localização nem declara aptidão científica
# — `aptidao_cientifica_declarada` fica sempre `False`, mesmo padrão já
# usado em scripts/nmme_poc_espacial_fazendas.py::montar_metadata_espacial
# (`localizacao_validada=False` sempre, mesmo com `poc_status=APROVADO`).
EVIDENCIA_POC_FAZENDAS = {
    'run_id': 36169942349,
    'workflow': 'nmme_poc_espacial_fazendas.yml',
    'poc_status': 'APROVADO',
    'localizacao_id': LOCALIZACAO_FAZENDAS,
    'localizacao_lat': FAZENDAS_LAT, 'localizacao_lon': FAZENDAS_LON,
    'auditoria_independente_confirmou': (
        '144 registros RAW, 6 horizontes (H1-H6), 24 membros por horizonte, '
        '6 auditorias temporais aprovadas, rota exclusiva IRIDL_LEGACY/'
        'NMME_HARMONIZED_MONTHLY.'
    ),
    'significado': 'Aprova a INFRAESTRUTURA de acesso a este ponto (mesmo tipo de '
                    'evidência já obtida para São Bento do Tocantins, run 36145108571) '
                    '— nunca a aptidão científica da localização.',
    'aptidao_cientifica_declarada': False,
    'outras_localizacoes_promovidas': False,
}

# 1991-2010, 12 meses/ano = 240 inicializações (Seção 1 da tarefa) —
# MESMO conjunto de origens/lotes para as duas localidades (item 4 da
# revisão: "preservar os cinco lotes de 48 inicializações"); só o
# diretório/coordenada mudam por localização, nunca a partição.
PERIODO_ANOS = tuple(range(1991, 2011))
ORIGENS_HISTORICAS = tuple((ano, mes) for ano in PERIODO_ANOS for mes in range(1, 13))
assert len(ORIGENS_HISTORICAS) == 240

TAMANHO_LOTE_MAX = 48   # Seção 1 — "preferencialmente até 48 inicializações"
N_RAW_ESPERADO_TOTAL = 240 * 6 * 24   # 34.560 — só se as 240 origens estiverem APROVADO
N_RAW_ESPERADO_POR_ORIGEM = 6 * 24   # 144 — 6 leads x 24 membros (revisão pontual, Seção 2/3)
LEADS_ESPERADOS = frozenset({1, 2, 3, 4, 5, 6})


def _validar_localizacao(localizacao):
    if localizacao not in LOCALIZACOES_VALIDAS:
        raise ValueError(f"localizacao {localizacao!r} desconhecida — válidas: {LOCALIZACOES_VALIDAS}")


def diretorio_padrao_para_localizacao(localizacao):
    """Item 2 da revisão — cada localização tem um diretório PRÓPRIO;
    nunca escolhido "na mão" pelo chamador, sempre derivado daqui, para
    reduzir o risco de apontar dado de uma localização para o
    diretório da outra por engano."""
    _validar_localizacao(localizacao)
    return DIRETORIO_POR_LOCALIZACAO[localizacao]


def lat_lon_para_localizacao(localizacao):
    """`None, None` para São Bento — preserva EXATAMENTE a resolução
    existente via `MUNICIPIOS`/`npoc.MUNICIPIO` (item 1 da revisão:
    "preservando integralmente a possibilidade de consultar São Bento
    do Tocantins"). Coordenadas explícitas só para o centroide das
    fazendas."""
    _validar_localizacao(localizacao)
    if localizacao == LOCALIZACAO_FAZENDAS:
        return FAZENDAS_LAT, FAZENDAS_LON
    return None, None


@dataclass(frozen=True)
class LoteHistorico:
    """Um lote é identificado pelo intervalo de anos que cobre — 240/48
    = exatamente 5 lotes de 4 anos (48 origens) cada, sem precisar de
    lógica de particionamento mais elaborada."""
    lote_id: str
    origens: tuple


def definir_lotes(origens=ORIGENS_HISTORICAS, tamanho_lote=TAMANHO_LOTE_MAX):
    """Particiona as origens em lotes cronológicos de até `tamanho_lote`
    — nunca reordena, nunca embaralha (a ordem cronológica é a mais
    fácil de auditar manualmente)."""
    lotes = []
    for i in range(0, len(origens), tamanho_lote):
        bloco = origens[i:i + tamanho_lote]
        anos_bloco = sorted({ano for ano, _ in bloco})
        lote_id = f"{anos_bloco[0]}-{anos_bloco[-1]}" if len(anos_bloco) > 1 else str(anos_bloco[0])
        lotes.append(LoteHistorico(lote_id=lote_id, origens=tuple(bloco)))
    return tuple(lotes)


LOTES_HISTORICOS = definir_lotes()
assert sum(len(lote.origens) for lote in LOTES_HISTORICOS) == 240
assert len(LOTES_HISTORICOS) == 5


def _caminho_lote(lote_id, sufixo, diretorio=DIRETORIO_HISTORICO):
    return diretorio / f"lote_{lote_id}_{sufixo}"


def _carregar_resumo_persistido(lote_id, diretorio=DIRETORIO_HISTORICO):
    """Devolve o resumo por origem já persistido para este lote, ou um
    DataFrame vazio (com as colunas certas) se o lote nunca rodou —
    nunca lança erro por arquivo ausente, isso é o estado normal de um
    lote ainda não iniciado."""
    caminho = _caminho_lote(lote_id, 'resumo_por_origem.csv', diretorio)
    if not caminho.exists():
        return pd.DataFrame(columns=['ano', 'mes', 'init_date', 'poc_status', 'backend_used',
                                       'backend_diferente_da_validada', 'dataset_representation_used',
                                       'representacao_diferente_da_validada',
                                       'inicializacao_selecao_status', 'n_raw',
                                       'member_count_per_lead_ok', 'temporal_mapping_confirmado',
                                       'unidade_confirmada', 'grade_confirmada', 'erro_inesperado'])
    return pd.read_csv(caminho)


def _verificar_integridade_origem(origem_str, linha_resumo, raw_df, temporal_df, localizacao_esperada=None):
    """Revisão pontual, Seção 2 — antes de considerar uma inicialização
    persistida como concluída, verifica TUDO isto, nunca só
    `poc_status=APROVADO` isolado (que pode estar certo no resumo mas
    já não bater mais com o que está de fato no raw.csv/
    temporal_audit.csv, ex.: arquivo truncado/editado/corrompido depois
    do fato — foi exatamente esse tipo de divergência silenciosa que o
    bug de n_raw=0 desta mesma extração já mostrou que é real, não
    hipotético):
    1. status APROVADO;
    2. backend e representação corretos (reaproveita as colunas já
       calculadas por `nmme_piloto_historico.montar_resumo_por_origem`
       — nunca reimplementa a comparação com o catálogo aqui);
    3. identificação correta da inicialização (`init_date` bate com o
       ano-mês esperado);
    4. exatamente 144 registros RAW (6 leads x 24 membros) para esta
       origem no raw.csv persistido;
    5. nenhuma duplicata de par (lead, member) nesses 144 registros;
    6. as 6 auditorias temporais (H1-H6) presentes, sem duplicata, no
       temporal_audit.csv persistido;
    7. (revisão pontual, 3ª rodada, item 5) quando `localizacao_esperada`
       é informado — identificação da localização também íntegra: o
       resumo E todas as linhas RAW/temporais desta origem (dentre as
       que casam por `origem_piloto`, ignorando localização) precisam
       estar marcadas com a MESMA localização esperada. Uma linha de
       outra localização "vazada" para dentro deste conjunto (mesmo
       ano-mês, localização diferente) é detectada aqui, mesmo que a
       contagem de 144 bata por coincidência.

    Devolve (integra: bool, motivos: list[str]) — NUNCA assume íntegra
    por ausência de dado (`linha_resumo=None` é o estado normal de uma
    origem nunca tentada, motivo 'origem_nao_persistida', não um erro
    silencioso)."""
    if linha_resumo is None:
        return False, ['origem_nao_persistida']

    motivos = []
    if linha_resumo.get('poc_status') != 'APROVADO':
        motivos.append('poc_status_nao_aprovado')
    if bool(linha_resumo.get('backend_diferente_da_validada', True)):
        motivos.append('backend_diferente_da_validada')
    if bool(linha_resumo.get('representacao_diferente_da_validada', True)):
        motivos.append('representacao_diferente_da_validada')
    if str(linha_resumo.get('init_date')) != origem_str:
        motivos.append('init_date_divergente')

    localizacao_ok = True
    if localizacao_esperada is not None and linha_resumo.get('localizacao') != localizacao_esperada:
        localizacao_ok = False

    if len(raw_df) and 'origem_piloto' in raw_df.columns:
        raw_mesma_origem = raw_df[raw_df['origem_piloto'] == origem_str]
    else:
        raw_mesma_origem = raw_df.iloc[0:0]
    if localizacao_esperada is not None and len(raw_mesma_origem):
        if 'localizacao' not in raw_mesma_origem.columns or not (
                raw_mesma_origem['localizacao'] == localizacao_esperada).all():
            localizacao_ok = False
        raw_origem = raw_mesma_origem[raw_mesma_origem.get('localizacao') == localizacao_esperada] \
            if 'localizacao' in raw_mesma_origem.columns else raw_mesma_origem.iloc[0:0]
    else:
        raw_origem = raw_mesma_origem
    if len(raw_origem) != N_RAW_ESPERADO_POR_ORIGEM:
        motivos.append('n_raw_diferente_de_144')
    elif {'lead', 'member'}.issubset(raw_origem.columns) and raw_origem.duplicated(subset=['lead', 'member']).any():
        motivos.append('duplicata_lead_member')

    if len(temporal_df) and 'origem_piloto' in temporal_df.columns:
        temporal_mesma_origem = temporal_df[temporal_df['origem_piloto'] == origem_str]
    else:
        temporal_mesma_origem = temporal_df.iloc[0:0]
    if localizacao_esperada is not None and len(temporal_mesma_origem):
        if 'localizacao' not in temporal_mesma_origem.columns or not (
                temporal_mesma_origem['localizacao'] == localizacao_esperada).all():
            localizacao_ok = False
        temporal_origem = temporal_mesma_origem[temporal_mesma_origem.get('localizacao') == localizacao_esperada] \
            if 'localizacao' in temporal_mesma_origem.columns else temporal_mesma_origem.iloc[0:0]
    else:
        temporal_origem = temporal_mesma_origem
    leads_presentes = list(temporal_origem['H_lead']) if 'H_lead' in temporal_origem.columns else []
    if set(leads_presentes) != LEADS_ESPERADOS or len(leads_presentes) != len(LEADS_ESPERADOS):
        motivos.append('auditorias_temporais_incompletas')

    if not localizacao_ok:
        motivos.append('localizacao_diferente_da_esperada')

    return (len(motivos) == 0), motivos


def _diagnosticar_origens(origens, resumo_df, raw_df, temporal_df, localizacao_esperada=None):
    """Roda `_verificar_integridade_origem` para cada origem de
    `origens`, cruzando com o que está persistido — usado tanto por
    `origens_pendentes` (retomada) quanto por `consolidar_extracao_
    completa` (aprovação final), garantindo o MESMO critério de
    integridade nas duas pontas."""
    resumo_por_origem = {}
    if len(resumo_df):
        for _, row in resumo_df.iterrows():
            resumo_por_origem[(int(row['ano']), int(row['mes']))] = row
    diagnostico = {}
    for ano, mes in origens:
        origem_str = f"{ano}-{mes:02d}"
        linha = resumo_por_origem.get((ano, mes))
        integra, motivos = _verificar_integridade_origem(
            origem_str, linha, raw_df, temporal_df, localizacao_esperada=localizacao_esperada)
        diagnostico[(ano, mes)] = {'concluida_e_integra': integra, 'motivos': motivos}
    return diagnostico


def diagnosticar_integridade_lote(lote, diretorio=DIRETORIO_HISTORICO, localizacao_esperada=None):
    """Wrapper de `_diagnosticar_origens` que carrega os 3 CSVs
    persistidos do lote do disco — usado pela CLI/depuração e por
    `origens_pendentes`."""
    resumo = _carregar_resumo_persistido(lote.lote_id, diretorio)
    raw = _ler_csv_ou_vazio(_caminho_lote(lote.lote_id, 'raw.csv', diretorio))
    temporal = _ler_csv_ou_vazio(_caminho_lote(lote.lote_id, 'temporal_audit.csv', diretorio))
    return _diagnosticar_origens(lote.origens, resumo, raw, temporal, localizacao_esperada=localizacao_esperada)


def origens_pendentes(lote, diretorio=DIRETORIO_HISTORICO, localizacao_esperada=None):
    """Seção 1 da tarefa — "possibilidade de retomada sem repetir
    desnecessariamente as consultas concluídas". Uma origem CONCLUÍDA é
    uma origem já persistida que passa em TODA a verificação de
    integridade de `_verificar_integridade_origem` (revisão pontual,
    Seção 2, e localização — Seção 5 da 3ª rodada) — não só
    `poc_status=APROVADO` isolado. Qualquer outra situação (nunca
    tentada, reprovada, erro inesperado, persistida mas com o raw.csv/
    temporal_audit.csv incompleto/inconsistente, ou com a localização
    divergente da esperada) fica pendente e É retentada — uma
    reprovação anterior pode ter sido um problema transitório de rede,
    nunca assumido permanente sem tentar de novo."""
    diagnostico = diagnosticar_integridade_lote(lote, diretorio, localizacao_esperada=localizacao_esperada)
    return tuple(o for o in lote.origens if not diagnostico[o]['concluida_e_integra'])


def _resultado_minimo_da_linha_resumo(row, raw_df, temporal_df, localizacao_esperada=None):
    """Reconstrói um dict no formato de `nmme_piloto_historico.
    executar_piloto_historico` a partir de 1 linha JÁ PERSISTIDA —
    usado para recompor o lote inteiro (origens novas + origens
    reaproveitadas do disco) antes de rodar `avaliar_aprovacao_piloto`,
    sem precisar reconsultar a rede para as que já estão prontas.
    Contém só os campos que os guardrails de agregação realmente leem
    (poc_status/backend_used/dataset_representation_used) — nunca finge
    ter o RAW/temporal_audit completos aqui (esses continuam só nos
    CSVs persistidos, concatenados à parte).

    Revisão pontual, Seção 2/3 — NUNCA repassa `poc_status=APROVADO`
    do resumo sem cruzar com `raw_df`/`temporal_df` primeiro
    (`_verificar_integridade_origem`, incluindo a localização —
    revisão 3ª rodada, item 5): uma origem cujo resumo diz APROVADO mas
    cujo raw.csv/temporal_audit.csv não bate mais (truncado, editado,
    corrompido, ou com a localização errada) é rebaixada aqui para
    `REPROVADO_INTEGRIDADE_PERSISTIDA` — isso é o que faz
    `avaliar_aprovacao_piloto` (reaproveitada sem modificação) reprovar
    o agregado quando a integridade persistida falha, tanto no nível do
    lote (`executar_lote`) quanto na consolidação final (Seção 3)."""
    ano, mes = int(row['ano']), int(row['mes'])
    origem_str = f"{ano}-{mes:02d}"
    integra, motivos = _verificar_integridade_origem(
        origem_str, row, raw_df, temporal_df, localizacao_esperada=localizacao_esperada)
    erro_persistido = row.get('erro_inesperado')
    erro_persistido = erro_persistido if isinstance(erro_persistido, str) and erro_persistido else None
    return {
        'ano': ano, 'mes': mes, 'origem': (ano, mes),
        'resultado': {
            'poc_status': row['poc_status'] if integra else 'REPROVADO_INTEGRIDADE_PERSISTIDA',
            'backend_used': row.get('backend_used'),
            'dataset_representation_used': row.get('dataset_representation_used'),
            'checklist': {
                'member_count_per_lead_ok': row.get('member_count_per_lead_ok'),
                'temporal_mapping_confirmado': row.get('temporal_mapping_confirmado'),
                'unidade_confirmada': row.get('unidade_confirmada'),
                'grade_confirmada': row.get('grade_confirmada'),
            },
            'raw_df': pd.DataFrame(), 'temporal_audit_df': pd.DataFrame(),
            'access_audit_df': pd.DataFrame(),
        },
        'erro': erro_persistido if integra else '; '.join(motivos),
    }


def executar_lote(lote, baixar_fn=None, abrir_fn=None, resolver_fns=None,
                    diretorio=None, sistema=None, localizacao=LOCALIZACAO_SAO_BENTO):
    """Roda só as origens PENDENTES deste lote (retomada — Seção 1),
    reaproveitando `nmme_piloto_historico.executar_piloto_historico`
    sem modificação para o isolamento de falha por origem. Mescla o
    resultado novo com o que já estava persistido, escreve de volta em
    `data/nmme_historico/` (armazenamento permanente) e devolve a
    aprovação do LOTE INTEIRO (`nmme_piloto_historico.
    avaliar_aprovacao_piloto`, reaproveitada sem modificação — mesmos
    critérios: todas aprovadas, nenhum erro inesperado, rota validada
    exclusiva, integridade das origens do lote).

    `localizacao` (revisão pontual, 3ª rodada) — `LOCALIZACAO_SAO_BENTO`
    por default, preservando INTEGRALMENTE o caminho existente (item 1
    da revisão): resolve `lat`/`lon` como `None, None`, que
    `nmme_piloto_historico.executar_piloto_historico`/`nmme_poc.
    executar_poc_real_cfsv2` já tratam como "resolver via MUNICIPIOS",
    exatamente como antes desta mudança. Para `LOCALIZACAO_FAZENDAS`,
    resolve `lat=FAZENDAS_LAT, lon=FAZENDAS_LON` e, quando `diretorio`
    não é informado explicitamente, usa `DIRETORIO_HISTORICO_FAZENDAS`
    (item 2 — diretório próprio, nunca compartilhado)."""
    if diretorio is None:
        diretorio = diretorio_padrao_para_localizacao(localizacao)
    lat, lon = lat_lon_para_localizacao(localizacao)
    diretorio.mkdir(parents=True, exist_ok=True)

    # Carrega o estado persistido UMA VEZ (resumo + raw + temporal +
    # access) — usado tanto para diagnosticar integridade/decidir
    # pendentes quanto para reconstruir as origens reaproveitadas
    # (revisão pontual, Seção 2: mesma fonte de verdade nas duas
    # pontas, nunca duas leituras que possam divergir entre si).
    resumo_persistido = _carregar_resumo_persistido(lote.lote_id, diretorio)
    raw_persistido = _ler_csv_ou_vazio(_caminho_lote(lote.lote_id, 'raw.csv', diretorio))
    temporal_persistido = _ler_csv_ou_vazio(_caminho_lote(lote.lote_id, 'temporal_audit.csv', diretorio))
    access_persistido = _ler_csv_ou_vazio(_caminho_lote(lote.lote_id, 'access_audit.csv', diretorio))

    diagnostico = _diagnosticar_origens(lote.origens, resumo_persistido, raw_persistido, temporal_persistido,
                                          localizacao_esperada=localizacao)
    pendentes = tuple(o for o in lote.origens if not diagnostico[o]['concluida_e_integra'])
    # Registra o problema ANTES de qualquer reprocessamento substituir
    # os dados antigos (Seção 2: "não perder os registros anteriores
    # sem antes identificar a inconsistência") — só entra aqui quem
    # tinha dado persistido que falhou na verificação (inclusive
    # localização divergente — item 5 da 3ª rodada), nunca quem
    # simplesmente nunca foi tentado (esse motivo sozinho não é uma
    # inconsistência, é o estado normal de um lote ainda não concluído).
    origens_com_inconsistencia_detectada = [
        {'origem': f'{a}-{m:02d}', 'motivos': diagnostico[(a, m)]['motivos']}
        for (a, m) in pendentes if diagnostico[(a, m)]['motivos'] != ['origem_nao_persistida']
    ]

    resultados_novos = []
    if pendentes:
        resultados_novos = pilo.executar_piloto_historico(
            origens=pendentes, sistema=sistema, baixar_fn=baixar_fn, abrir_fn=abrir_fn,
            resolver_fns=resolver_fns, lat=lat, lon=lon)

    origens_novas = {item['origem'] for item in resultados_novos}
    resultados_reaproveitados = [
        _resultado_minimo_da_linha_resumo(row, raw_persistido, temporal_persistido,
                                            localizacao_esperada=localizacao)
        for _, row in resumo_persistido.iterrows()
        if (int(row['ano']), int(row['mes'])) not in origens_novas
    ]
    resultados_completos = resultados_reaproveitados + resultados_novos
    # Nunca perde a ordem cronológica do lote, mesmo misturando
    # reaproveitado + novo.
    resultados_completos.sort(key=lambda item: item['origem'])

    raw_novo, temporal_novo, access_novo = pilo.concatenar_dataframes_piloto(resultados_novos)
    # Item 3/5 da revisão — toda linha nova grava a localização
    # explicitamente (além das coordenadas solicitada/selecionada, já
    # presentes por linha via requested_lat/requested_lon/selected_lat/
    # selected_lon — colunas de nmme_poc.executar_poc_real_cfsv2,
    # preservadas sem modificação). `concatenar_dataframes_piloto`
    # (reaproveitada sem modificação) só insere `origem_piloto`; a
    # coluna `localizacao` é adicionada aqui, só no que este módulo
    # escreve.
    for df_novo in (raw_novo, temporal_novo, access_novo):
        if len(df_novo):
            df_novo['localizacao'] = localizacao

    origens_novas_str = {f'{a}-{m:02d}' for a, m in origens_novas}
    raw_final = _substituir_origens(raw_persistido, raw_novo, origens_novas_str)
    temporal_final = _substituir_origens(temporal_persistido, temporal_novo, origens_novas_str)
    access_final = _substituir_origens(access_persistido, access_novo, origens_novas_str)

    resumo_final = pilo.montar_resumo_por_origem(resultados_completos)
    # `resultados_completos` mistura resultados frescos (com raw_df
    # real) e reaproveitados do disco (_resultado_minimo_da_linha_resumo
    # deliberadamente NÃO recarrega o RAW inteiro, só o suficiente para
    # os critérios de aprovação) — por isso `n_raw` de
    # montar_resumo_por_origem ficaria 0 para toda origem reaproveitada.
    # Corrigido aqui contando direto no `raw_final` já mesclado, que é
    # a fonte de verdade real independente de a origem ser nova ou
    # reaproveitada.
    if len(raw_final) and 'origem_piloto' in raw_final.columns:
        contagem_raw = raw_final.groupby('origem_piloto').size()
        resumo_final['n_raw'] = resumo_final['init_date'].map(contagem_raw).fillna(0).astype(int)
    else:
        resumo_final['n_raw'] = 0
    # O lote inteiro é de UMA localização só — coluna constante, mas
    # gravada em toda linha do resumo (item 5: identificação da
    # localização faz parte da integridade persistida, não só do RAW).
    resumo_final['localizacao'] = localizacao

    raw_final.to_csv(_caminho_lote(lote.lote_id, 'raw.csv', diretorio), index=False)
    temporal_final.to_csv(_caminho_lote(lote.lote_id, 'temporal_audit.csv', diretorio), index=False)
    access_final.to_csv(_caminho_lote(lote.lote_id, 'access_audit.csv', diretorio), index=False)
    resumo_final.to_csv(_caminho_lote(lote.lote_id, 'resumo_por_origem.csv', diretorio), index=False)

    aprovacao = pilo.avaliar_aprovacao_piloto(resultados_completos, origens_esperadas=lote.origens)
    metadata_lote = {
        'lote_id': lote.lote_id, 'localizacao': localizacao,
        'localizacao_lat': lat, 'localizacao_lon': lon,
        'n_origens': len(lote.origens),
        'n_origens_pendentes_nesta_execucao': len(pendentes),
        'n_origens_reaproveitadas_do_disco': len(resultados_reaproveitados),
        'lote_status': aprovacao['piloto_status'], 'criterios': aprovacao['criterios'],
        'n_origens_aprovadas': aprovacao['n_origens_aprovadas'],
        'origens_com_rota_diferente': aprovacao['origens_com_rota_diferente'],
        'integridade_origens': aprovacao['integridade_origens'],
        'origens_com_inconsistencia_detectada': origens_com_inconsistencia_detectada,
        'n_raw': len(raw_final), 'n_raw_esperado': len(lote.origens) * 6 * 24,
    }
    # Item 6 da revisão — cita a evidência do POC de infraestrutura já
    # aprovado para o centroide das fazendas em todo lote dessa
    # localização, sem nunca promover a localização automaticamente
    # (EVIDENCIA_POC_FAZENDAS['aptidao_cientifica_declarada'] é sempre
    # False, citado aqui, não reafirmado/recalculado).
    if localizacao == LOCALIZACAO_FAZENDAS:
        metadata_lote['evidencia_poc_localizacao'] = EVIDENCIA_POC_FAZENDAS
    (_caminho_lote(lote.lote_id, 'metadata.json', diretorio)).write_text(
        json.dumps(metadata_lote, indent=2, ensure_ascii=False, default=str))
    return metadata_lote


def _ler_csv_ou_vazio(caminho):
    """Nunca lança por arquivo ausente OU vazio — um lote cuja primeira
    tentativa reprova em TODAS as origens (ex.: rede fora naquele dia)
    persiste um CSV de 0 linhas/0 colunas por construção
    (`concatenar_dataframes_piloto` devolve `pd.DataFrame()` quando
    nada teve sucesso); `pd.read_csv` levanta `EmptyDataError` nesse
    caso mesmo com o arquivo existindo — achado ao testar exatamente
    esse cenário (lote de 1 origem que falha na primeira execução)."""
    if not caminho.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(caminho)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _substituir_origens(df_persistido, df_novo, origens_novas_str):
    """Concatena o que já estava no disco com o resultado novo,
    removendo do lado persistido qualquer linha das origens que acabam
    de ser reprocessadas (nunca duplica — a versão nova sempre
    substitui a antiga para a mesma origem, mesmo que a antiga já
    estivesse aprovada, porque só origens NÃO aprovadas voltam a ser
    processadas — `origens_pendentes`)."""
    if len(df_persistido) and 'origem_piloto' in df_persistido.columns:
        df_persistido = df_persistido[~df_persistido['origem_piloto'].isin(origens_novas_str)]
    partes = [d for d in (df_persistido, df_novo) if len(d)]
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()


def consolidar_extracao_completa(lotes=LOTES_HISTORICOS, diretorio=None, localizacao=LOCALIZACAO_SAO_BENTO):
    """Seção 1 da tarefa — depois que os lotes rodarem (não necessariamente
    todos ainda), verifica as 240 origens x 6 leads x 24 membros
    (34.560 registros RAW) SE E SOMENTE SE todas as 240 estiverem
    aprovadas. Nunca finge completude parcial como total — reporta o
    estado real (quantos lotes/origens realmente concluídos) mesmo
    quando incompleto, o que é o estado esperado até que todos os 5
    lotes sejam explicitamente disparados.

    Revisão pontual, Seção 3 — a aprovação final exige SIMULTANEAMENTE:
    (1) as 240 inicializações previstas; (2) todas individualmente
    aprovadas; (3) rota validada exclusiva; (4) exatamente 144 RAW por
    inicialização; (5) 34.560 RAW no total; (6) auditorias temporais
    completas. Os itens 1-3 já vêm de `avaliar_aprovacao_piloto`
    (reaproveitada sem modificação); os itens 4 e 6 são verificados por
    origem via `_verificar_integridade_origem`/`_resultado_minimo_da_
    linha_resumo` — a MESMA verificação usada em `origens_pendentes`,
    nunca uma segunda lógica paralela — e rebaixam o `poc_status`
    reconstruído quando falham, o que já faz o critério (2) reprovar;
    ficam também expostos aqui como campos próprios
    (`todas_origens_com_144_raw`/`todas_auditorias_temporais_completas`)
    para nunca depender de inferir isso indiretamente. UMA divergência
    em qualquer critério bloqueia `extracao_completa_e_aprovada`.

    `localizacao` (revisão pontual, 3ª rodada, item 5) — também exige
    que a identificação da localização bata em toda origem; quando
    `diretorio` não é informado, resolve o diretório próprio dessa
    localização (item 2)."""
    if diretorio is None:
        diretorio = diretorio_padrao_para_localizacao(localizacao)
    resultados_todos = []
    n_raw_total = 0
    lotes_status = {}
    todas_origens_com_144_raw = True
    todas_auditorias_temporais_completas = True
    for lote in lotes:
        resumo = _carregar_resumo_persistido(lote.lote_id, diretorio)
        raw_lote = _ler_csv_ou_vazio(_caminho_lote(lote.lote_id, 'raw.csv', diretorio))
        temporal_lote = _ler_csv_ou_vazio(_caminho_lote(lote.lote_id, 'temporal_audit.csv', diretorio))
        n_raw_total += len(raw_lote)

        diagnostico_lote = _diagnosticar_origens(lote.origens, resumo, raw_lote, temporal_lote,
                                                    localizacao_esperada=localizacao)
        for diag in diagnostico_lote.values():
            if 'n_raw_diferente_de_144' in diag['motivos']:
                todas_origens_com_144_raw = False
            if 'auditorias_temporais_incompletas' in diag['motivos']:
                todas_auditorias_temporais_completas = False

        if len(resumo):
            resultados_todos.extend(
                _resultado_minimo_da_linha_resumo(row, raw_lote, temporal_lote, localizacao_esperada=localizacao)
                for _, row in resumo.iterrows())
        n_aprovadas = sum(1 for diag in diagnostico_lote.values() if diag['concluida_e_integra'])
        lotes_status[lote.lote_id] = {'n_origens': len(lote.origens), 'n_aprovadas': n_aprovadas,
                                        'iniciado': len(resumo) > 0}

    todas_origens_esperadas = tuple(o for lote in lotes for o in lote.origens)
    if resultados_todos:
        aprovacao_geral = pilo.avaliar_aprovacao_piloto(resultados_todos,
                                                           origens_esperadas=todas_origens_esperadas)
    else:
        aprovacao_geral = {'piloto_status': 'REPROVADO', 'n_origens_aprovadas': 0,
                             'n_origens_total': 0, 'criterios': {}, 'origens_com_rota_diferente': [],
                             'integridade_origens': {'ok': False}}

    # Calculado a partir de `lotes` (não do valor fixo N_RAW_ESPERADO_
    # TOTAL) — `lotes` é parametrizável (default é o conjunto real de 5
    # lotes/240 origens, mas a função aceita qualquer subconjunto, ex.:
    # testes). Com o total fixo, um subconjunto completo e aprovado
    # reportaria `n_raw_bate_com_esperado=False` por comparar contra o
    # total de 240 origens em vez do total do que foi realmente pedido
    # — o mesmo tipo de completude fingida que este módulo existe para
    # nunca fazer. Para o uso real (`lotes=LOTES_HISTORICOS`), o valor
    # coincide exatamente com N_RAW_ESPERADO_TOTAL (240*6*24=34.560).
    n_raw_esperado = len(todas_origens_esperadas) * 6 * 24
    # Demais critérios, independentes da contagem RAW agregada — usado
    # para decidir se `n_raw_bate_com_esperado` é sequer significativo
    # de reportar (mantém a semântica original do campo: None enquanto
    # o resto ainda não bateu, não um False prematuro só porque nenhum
    # lote rodou ainda).
    demais_criterios_ok = (aprovacao_geral['n_origens_aprovadas'] == len(todas_origens_esperadas)
                            and aprovacao_geral['piloto_status'] == 'APROVADO'
                            and todas_origens_com_144_raw and todas_auditorias_temporais_completas)
    # Revisão pontual (2ª rodada) — `n_raw_total == n_raw_esperado`
    # entra EXPLICITAMENTE em `completo`, não só como campo informativo
    # à parte. `todas_origens_com_144_raw` só soma linhas das origens
    # PREVISTAS (`lote.origens`); um registro RAW extra associado a uma
    # origem INESPERADA (fora do plano — nunca deveria existir num
    # raw.csv persistido por este módulo, mas nada impede um arquivo
    # editado à mão ou uma migração futura de introduzir um) infla
    # `n_raw_total` sem que nenhuma origem prevista deixe de ter
    # exatamente 144 — só esta comparação agregada pega esse caso.
    n_raw_bate_com_esperado = (n_raw_total == n_raw_esperado) if demais_criterios_ok else None
    completo = demais_criterios_ok and bool(n_raw_bate_com_esperado)
    consolidado = {
        'localizacao': localizacao,
        'n_lotes': len(lotes), 'n_origens_esperadas_total': len(todas_origens_esperadas),
        'n_origens_aprovadas_total': aprovacao_geral['n_origens_aprovadas'],
        'extracao_completa_e_aprovada': completo,
        'n_raw_total': n_raw_total,
        'n_raw_esperado_se_completo': n_raw_esperado,
        'n_raw_bate_com_esperado': n_raw_bate_com_esperado,
        'todas_origens_com_144_raw': todas_origens_com_144_raw,
        'todas_auditorias_temporais_completas': todas_auditorias_temporais_completas,
        'criterios_agregados': aprovacao_geral['criterios'],
        'origens_com_rota_diferente': aprovacao_geral['origens_com_rota_diferente'],
        'integridade_origens': aprovacao_geral['integridade_origens'],
        'lotes_status': lotes_status,
        'nenhuma_skill_calculada': True, 'nenhum_dashboard_alterado': True,
    }
    if localizacao == LOCALIZACAO_FAZENDAS:
        consolidado['evidencia_poc_localizacao'] = EVIDENCIA_POC_FAZENDAS
    return consolidado


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

_LOCALIZACAO_CLI_PARA_INTERNA = {'sao_bento': LOCALIZACAO_SAO_BENTO, 'fazendas': LOCALIZACAO_FAZENDAS}


def _imprimir_plano_localizacao(localizacao):
    diretorio = diretorio_padrao_para_localizacao(localizacao)
    lat, lon = lat_lon_para_localizacao(localizacao)
    print(f"  localizacao: {localizacao} (lat={lat}, lon={lon})"
          if lat is not None else f"  localizacao: {localizacao} (resolvida via MUNICIPIOS)")
    print(f"  armazenamento: {diretorio.relative_to(ROOT)}/ (commitado no repositório, "
          "NUNCA depende só do artifact do GitHub Actions — retenção 30 dias; "
          "diretório próprio, nunca compartilhado com o de outra localização)")
    if localizacao == LOCALIZACAO_FAZENDAS:
        print(f"  evidencia_poc_infraestrutura: run {EVIDENCIA_POC_FAZENDAS['run_id']} "
              f"({EVIDENCIA_POC_FAZENDAS['poc_status']}) — nunca promove aptidão científica")
    for lote in LOTES_HISTORICOS:
        pendentes = origens_pendentes(lote, diretorio, localizacao_esperada=localizacao)
        print(f"  - lote {lote.lote_id}: {len(lote.origens)} origens, "
              f"{len(pendentes)} pendentes (retomada automática)")


def imprimir_plano():
    print("=== NMME Extração Histórica CFSv2 (Fase 2C.2) — DRY RUN PLAN "
          "(nenhum acesso à rede NMME) ===")
    print(f"  periodo: {PERIODO_ANOS[0]}-{PERIODO_ANOS[-1]}")
    print(f"  n_origens_total: {len(ORIGENS_HISTORICAS)} (mesmos 5 lotes de até "
          f"{TAMANHO_LOTE_MAX} origens para as duas localidades)")
    print(f"  n_raw_esperado_se_tudo_aprovado: {N_RAW_ESPERADO_TOTAL}")
    for localizacao in LOCALIZACOES_VALIDAS:
        print(f"\n--- {localizacao} ---")
        _imprimir_plano_localizacao(localizacao)
    print("\n✅ Plano da extração histórica gerado (infraestrutura só — nenhum download real).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run-plan', action='store_true',
                     help='Nunca acessa a rede NMME — só mostra o plano dos 5 lotes das duas localidades.')
    ap.add_argument('--executar-lote', metavar='LOTE_ID', default=None,
                     help='Roda só o lote informado (ex.: 1991-1994) — acessa a rede de verdade. '
                          'Nunca roda mais de 1 lote por invocação.')
    ap.add_argument('--consolidar', action='store_true',
                     help='Só lê os lotes já persistidos e reporta o estado consolidado — nunca acessa a rede.')
    ap.add_argument('--localizacao', choices=('sao_bento', 'fazendas'), default='sao_bento',
                     help="Localização alvo de --executar-lote/--consolidar — 'sao_bento' (default, "
                          "data/nmme_historico/) ou 'fazendas' (data/nmme_historico_fazendas/, "
                          "centroide das fazendas, lat=-7.80/lon=-47.95).")
    args = ap.parse_args()
    localizacao = _LOCALIZACAO_CLI_PARA_INTERNA[args.localizacao]

    if args.consolidar:
        consolidado = consolidar_extracao_completa(localizacao=localizacao)
        print(json.dumps(consolidado, indent=2, ensure_ascii=False, default=str))
        return

    if args.executar_lote:
        lotes_por_id = {lote.lote_id: lote for lote in LOTES_HISTORICOS}
        if args.executar_lote not in lotes_por_id:
            raise SystemExit(f"lote_id {args.executar_lote!r} desconhecido — "
                              f"válidos: {sorted(lotes_por_id)}")
        imprimir_plano()
        metadata_lote = executar_lote(lotes_por_id[args.executar_lote], localizacao=localizacao)
        print(f"\nlocalizacao={metadata_lote['localizacao']}")
        print(f"lote_status={metadata_lote['lote_status']} "
              f"({metadata_lote['n_origens_aprovadas']}/{metadata_lote['n_origens']} origens aprovadas)")
        for k, v in metadata_lote['criterios'].items():
            print(f"  - {k}: {v}")
        if metadata_lote['origens_com_inconsistencia_detectada']:
            print("\n⚠️  Inconsistência(s) detectada(s) em origem(ns) persistida(s) — reprocessada(s) nesta execução:")
            for item in metadata_lote['origens_com_inconsistencia_detectada']:
                print(f"  - {item['origem']}: {', '.join(item['motivos'])}")
        if metadata_lote['lote_status'] != 'APROVADO':
            raise SystemExit(f"Lote {args.executar_lote} ({localizacao}) REPROVADO — ver "
                              f"{diretorio_padrao_para_localizacao(localizacao).relative_to(ROOT)}/"
                              f"lote_{args.executar_lote}_resumo_por_origem.csv")
        print(f"\n✅ Lote {args.executar_lote} ({localizacao}) APROVADO — persistido em "
              f"{diretorio_padrao_para_localizacao(localizacao).relative_to(ROOT)}/")
        return

    imprimir_plano()


if __name__ == '__main__':
    main()
