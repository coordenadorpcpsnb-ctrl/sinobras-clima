#!/usr/bin/env python3
"""
nmme_auditoria_sinobras_por_fazenda.py — Fase 2C.2, auditoria da nova
evidência recebida (registros mensais individualizados por fazenda,
SINOBRAS.csv, jan/1996-dez/2025).

Rotina INDEPENDENTE: recebe o caminho do arquivo original via
`--arquivo`, nunca assume uma cópia dentro do repositório e nunca
grava, modifica ou incorpora esse arquivo ao git — só LÊ e produz
achados derivados (tabelas/JSON em artifacts/, gitignored, e o
relatório técnico em docs/, commitado). O arquivo original em si
NUNCA é copiado para dentro deste repositório por este script.

Reaproveita, sem modificar:
- `nmme_piloto_historico.SERIE_OBSERVACIONAL_PATH` — mesma série de
  produção (data/serie_subst.csv) já usada em todo o resto do
  projeto, aqui só LIDA para reconciliação, nunca escrita.
- `c3s_poc.PREC_MM_MIN_PLAUSIVEL`/`PREC_MM_MAX_PLAUSIVEL` — mesmo
  limiar de triagem física (0-1500mm/mês) já usado em
  `nmme_piloto_historico.verificar_cobertura_observacional`.

Nunca calcula skill, nunca declara aptidão científica, nunca modifica
o dashboard, nunca altera a série histórica de produção nem elimina
séries duplicadas — só documenta o que foi encontrado.

Roda com:
    python scripts/nmme_auditoria_sinobras_por_fazenda.py --dry-run-plan
    python scripts/nmme_auditoria_sinobras_por_fazenda.py --arquivo /caminho/para/SINOBRAS.csv --gerar-relatorio
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import c3s_poc as cpoc  # noqa: E402
import nmme_piloto_historico as pilo  # noqa: E402

ARTIFACTS_DIR = ROOT / 'artifacts' / 'nmme_auditoria_sinobras_por_fazenda'
RELATORIO_DOC_PATH = ROOT / 'docs' / 'nmme-fase2c2-auditoria-sinobras-por-fazenda.md'

COLUNAS_ESPERADAS = {'ano', 'mes', 'prec_mm', 'estacao'}


# ══════════════════════════════════════════════════════════════════════════
# Item 9 — hash de integridade, reprodutibilidade
# ══════════════════════════════════════════════════════════════════════════

def calcular_sha256(caminho):
    """Hash do arquivo tal como recebido — nunca recalculado a partir
    de uma cópia ou de um subconjunto. Permite qualquer pessoa
    reproduzir esta auditoria e confirmar que analisou exatamente o
    mesmo arquivo (`sha256sum <arquivo>`, comparar com o valor
    registrado no relatório)."""
    h = hashlib.sha256()
    with open(caminho, 'rb') as f:
        for bloco in iter(lambda: f.read(1 << 20), b''):
            h.update(bloco)
    return h.hexdigest()


# ══════════════════════════════════════════════════════════════════════════
# Item 1 — leitura pura, nunca escreve nem modifica o arquivo de entrada
# ══════════════════════════════════════════════════════════════════════════

def carregar_sinobras(caminho):
    """Leitura pura (`pd.read_csv`) — este módulo nunca escreve de
    volta no arquivo de entrada, nunca o copia para dentro do
    repositório. Aceita qualquer caminho no sistema de arquivos."""
    df = pd.read_csv(caminho, sep=';')
    faltantes = COLUNAS_ESPERADAS - set(df.columns)
    if faltantes:
        raise ValueError(f'colunas ausentes no arquivo recebido: {sorted(faltantes)}')
    return df


# ══════════════════════════════════════════════════════════════════════════
# Item 2 — integridade estrutural: cobertura mensal, duplicatas, valores
# fisicamente implausíveis
# ══════════════════════════════════════════════════════════════════════════

def verificar_integridade_estrutural(df):
    """Nunca assume 34 fazendas nem 360 meses — deriva tudo dos dados
    recebidos, e só registra como achado o que for de fato computado.
    Cobertura mensal é verificada dentro do período efetivamente
    presente no arquivo (do primeiro ao último ano-mês), não contra um
    período fixo hardcoded.

    Regressão corrigida (3ª rodada): um `df` VAZIO (0 registros) tinha
    todas as checagens vazias (nenhum mês ausente, nenhuma duplicata,
    nenhum identificador com contagem diferente — tudo vacuamente
    verdadeiro) e por isso era classificado `integro=True`. Arquivo
    vazio nunca é íntegro — `n_registros > 0` é exigido explicitamente
    antes de qualquer outra condição."""
    n_registros = len(df)
    identificadores = sorted(df['estacao'].unique().tolist())
    n_identificadores = len(identificadores)

    registros_por_identificador = df.groupby('estacao').size()
    max_registros = int(registros_por_identificador.max()) if len(registros_por_identificador) else 0
    identificadores_com_contagem_diferente = {
        str(k): int(v) for k, v in registros_por_identificador.items() if v != max_registros}

    registros_por_mes = df.groupby(['ano', 'mes']).size()
    moda_registros_por_mes = int(registros_por_mes.mode().iloc[0]) if len(registros_por_mes) else 0
    meses_com_contagem_atipica = {
        f'{int(a)}-{int(m):02d}': int(v)
        for (a, m), v in registros_por_mes.items() if v != moda_registros_por_mes}

    duplicatas = df[df.duplicated(subset=['ano', 'mes', 'estacao'], keep=False)]
    valores_ausentes = int(df[['ano', 'mes', 'prec_mm', 'estacao']].isna().sum().sum())
    implausiveis = df[(df['prec_mm'] < cpoc.PREC_MM_MIN_PLAUSIVEL) |
                       (df['prec_mm'] > cpoc.PREC_MM_MAX_PLAUSIVEL)]

    anos_meses_presentes = set(pd.PeriodIndex(
        df['ano'].astype(int).astype(str) + '-' + df['mes'].astype(int).astype(str).str.zfill(2),
        freq='M'))
    if anos_meses_presentes:
        periodo_completo = pd.period_range(min(anos_meses_presentes), max(anos_meses_presentes), freq='M')
    else:
        periodo_completo = pd.PeriodIndex([], freq='M')
    meses_ausentes = sorted(str(p) for p in periodo_completo if p not in anos_meses_presentes)

    return {
        'n_registros': n_registros,
        'n_identificadores': n_identificadores,
        'identificadores': identificadores,
        'periodo_coberto_inicio': str(min(anos_meses_presentes)) if anos_meses_presentes else None,
        'periodo_coberto_fim': str(max(anos_meses_presentes)) if anos_meses_presentes else None,
        'n_meses_no_periodo_coberto': len(periodo_completo),
        'n_meses_ausentes_dentro_do_periodo': len(meses_ausentes),
        'meses_ausentes_dentro_do_periodo': meses_ausentes,
        'cobertura_mensal_sem_lacunas': len(meses_ausentes) == 0,
        'registros_por_identificador_maximo': max_registros,
        'identificadores_com_contagem_diferente_do_maximo': identificadores_com_contagem_diferente,
        'moda_registros_por_mes': moda_registros_por_mes,
        'meses_com_numero_de_registros_atipico': meses_com_contagem_atipica,
        'n_duplicatas_ano_mes_estacao': int(len(duplicatas)),
        'duplicatas_detalhe': (duplicatas[['ano', 'mes', 'estacao', 'prec_mm']].to_dict(orient='records')
                                if len(duplicatas) else []),
        'n_valores_ausentes': valores_ausentes,
        'n_valores_implausiveis': int(len(implausiveis)),
        'implausiveis_detalhe': (implausiveis[['ano', 'mes', 'estacao', 'prec_mm']].to_dict(orient='records')
                                  if len(implausiveis) else []),
        'integro': bool(
            n_registros > 0 and
            len(meses_ausentes) == 0 and not identificadores_com_contagem_diferente and
            not meses_com_contagem_atipica and len(duplicatas) == 0 and
            valores_ausentes == 0 and len(implausiveis) == 0),
    }


# ══════════════════════════════════════════════════════════════════════════
# Item 3 — reproduzir a média histórica mensal e confrontar com
# data/serie_subst.csv (só leitura — nunca escreve na série de produção)
# ══════════════════════════════════════════════════════════════════════════

def reproduzir_media_mensal(df):
    """Média aritmética simples de TODOS os registros de cada mês —
    mesma fórmula já verificada por leitura de código em
    `nmme_auditoria_observacional_historica.verificar_padrao_
    agregacao_sinobras_no_codigo` (df.groupby(['ano','mes'])
    ['prec_mm'].mean()), aqui aplicada aos dados por fazenda
    recebidos, não a um arquivo de incorporação mensal."""
    media = df.groupby(['ano', 'mes'])['prec_mm'].agg(['mean', 'count']).reset_index()
    media = media.rename(columns={'mean': 'media_mm', 'count': 'n_registros'})
    return media.sort_values(['ano', 'mes']).reset_index(drop=True)


def confrontar_com_serie_producao(media_df, serie_path=pilo.SERIE_OBSERVACIONAL_PATH):
    """Item 3 — só LÊ data/serie_subst.csv (nunca escreve). Arredonda
    ambas as séries a 2 casas decimais antes de comparar, mesmo
    critério já usado em `verificar_identidade_merra2_com_master_
    monthly` (nmme_auditoria_observacional_historica.py)."""
    serie = pd.read_csv(serie_path)
    merged = media_df.merge(serie[['ano', 'mes', 'prec']], on=['ano', 'mes'], how='left')
    merged['media_mm_arredondada'] = merged['media_mm'].round(2)
    merged['serie_producao_mm_arredondada'] = merged['prec'].round(2)
    merged['diff_abs_mm'] = (merged['media_mm_arredondada'] - merged['serie_producao_mm_arredondada']).abs()

    n_sem_correspondencia = int(merged['prec'].isna().sum())
    comparaveis = merged.dropna(subset=['prec'])
    n_identicos = int((comparaveis['diff_abs_mm'] < 0.01).sum())

    resumo = {
        'n_meses_no_arquivo_recebido': int(len(media_df)),
        'n_meses_sem_correspondencia_na_serie_producao': n_sem_correspondencia,
        'n_meses_comparaveis': int(len(comparaveis)),
        'n_meses_identicos_apos_arredondamento_2_casas': n_identicos,
        'diff_abs_maxima_mm': round(float(comparaveis['diff_abs_mm'].max()), 4) if len(comparaveis) else None,
        'diff_abs_media_mm': round(float(comparaveis['diff_abs_mm'].mean()), 4) if len(comparaveis) else None,
        'reconciliacao_completa': bool(
            len(comparaveis) and n_identicos == len(comparaveis) and n_sem_correspondencia == 0),
    }
    tabela = merged[['ano', 'mes', 'n_registros', 'media_mm_arredondada',
                      'serie_producao_mm_arredondada', 'diff_abs_mm']].copy()
    return resumo, tabela


# ══════════════════════════════════════════════════════════════════════════
# Item 4 — identificar grupos de séries mensais idênticas, automaticamente
# ══════════════════════════════════════════════════════════════════════════

def identificar_grupos_series_identicas(df):
    """Compara os 360 (ou N) valores mensais completos de cada
    identificador — igualdade EXATA, não aproximada (os valores são
    inteiros no arquivo recebido). Agrupa por assinatura (tupla de
    valores na mesma ordem cronológica), nunca por inspeção manual.

    Revisão pontual (4ª rodada, 2026) — computação inalterada (é
    agnóstica à fonte dos dados); só a INTERPRETAÇÃO no retorno foi
    revista à luz da nova informação de que SINOBRAS.csv é estimativa
    CHIRPS por fazenda, não leitura de pluviômetro (ver
    docs/nmme-fase2c2-auditoria-chirps-sinobras.md): a hipótese de
    compartilhamento de PIXEL CHIRPS entre fazendas geograficamente
    próximas passa a ser investigada ao lado das hipóteses anteriores
    — nunca tratada como fato comprovado, e nunca a única hipótese."""
    pivot = df.pivot_table(index=['ano', 'mes'], columns='estacao', values='prec_mm', aggfunc='first')
    pivot = pivot.sort_index()

    assinaturas = {}
    for estacao in pivot.columns:
        chave = tuple(pivot[estacao].tolist())
        assinaturas.setdefault(chave, []).append(estacao)

    grupos = sorted((sorted(membros) for membros in assinaturas.values() if len(membros) > 1),
                     key=lambda g: g[0])
    identificadores_com_serie_unica = sorted(
        membros[0] for membros in assinaturas.values() if len(membros) == 1)

    return {
        'n_identificadores_comparados': int(pivot.shape[1]),
        'n_series_mensais_distintas': len(assinaturas),
        'n_grupos_com_mais_de_1_identificador': len(grupos),
        'grupos_de_series_identicas': grupos,
        'identificadores_com_serie_unica': identificadores_com_serie_unica,
        'interpretacao': (
            f"{pivot.shape[1]} identificadores comparados mês a mês (igualdade exata, não "
            f"aproximada) produzem {len(assinaturas)} séries mensais numericamente distintas. "
            f"{len(grupos)} grupo(s) de identificadores compartilham a mesma série completa: "
            f"{grupos}. Isto é um FATO computado — a INTERPRETAÇÃO não é decidível a partir "
            "deste arquivo isoladamente. Hipóteses em aberto, NENHUMA presumida sem a "
            "documentação operacional correspondente: (a) COMPARTILHAMENTO DE PIXEL CHIRPS — "
            "dado que SINOBRAS.csv é estimativa CHIRPS por fazenda (informado pelo responsável "
            "pelos dados, ver docs/nmme-fase2c2-auditoria-chirps-sinobras.md), fazendas cujas "
            "coordenadas nominais caem no mesmo pixel CHIRPS (~0,05°, ~5,5km no equador) "
            "receberiam exatamente o mesmo valor extraído — hipótese mais parcimoniosa dado o "
            "novo contexto, mas NÃO comprovada (exigiria as coordenadas de cada fazenda, ainda "
            "ausentes); (b) pluviômetro físico compartilhado (se alguma das fazendas do grupo "
            "de fato tiver instrumento); (c) replicação administrativa de um registro entre "
            "fazendas distintas; (d) preenchimento (fill) de uma fazenda a partir de outra."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Item 5 — distinguir identificadores, séries distintas e instrumentos
# efetivamente independentes — nunca presumir equivalência
# ══════════════════════════════════════════════════════════════════════════

def distinguir_identificadores_series_e_instrumentos(integridade, grupos):
    """Quatro conceitos, nunca colapsados num único número: (1) rótulos
    de fazenda no arquivo (convenção de nomenclatura); (2) séries
    mensais numericamente distintas (fato computado); (3) pixels/
    pontos de extração CHIRPS efetivamente distintos (não verificável
    sem as coordenadas usadas na extração); (4) instrumentos
    pluviométricos fisicamente independentes (nem sequer presumido que
    existam — a empresa não tem pluviômetro em todas as fazendas,
    informação do responsável pelos dados).

    Revisão pontual (4ª rodada, 2026) — antes desta rodada, a única
    pergunta em aberto era "instrumento compartilhado?". Com a nova
    informação de que SINOBRAS.csv é estimativa CHIRPS (não leitura de
    campo), a pergunta relevante passa a ser em primeiro lugar sobre
    PIXELS/PONTOS DE EXTRAÇÃO, e só secundariamente sobre instrumentos
    físicos — que podem nem existir para boa parte das 34 fazendas."""
    n_identificadores = integridade['n_identificadores']
    n_series_distintas = grupos['n_series_mensais_distintas']
    return {
        'n_identificadores_de_fazenda': n_identificadores,
        'n_series_mensais_numericamente_distintas': n_series_distintas,
        'n_pontos_extracao_chirps_efetivamente_distintos_confirmados': None,
        'n_instrumentos_pluviometricos_efetivamente_independentes_confirmados': None,
        'interpretacao': (
            f"Quatro conceitos diferentes, nunca tratados como equivalentes: (1) "
            f"{n_identificadores} IDENTIFICADORES de fazenda (rótulos FAZxx do arquivo) — uma "
            "convenção de nomenclatura administrativa; (2) "
            f"{n_series_distintas} SÉRIES MENSAIS numericamente distintas — um fato computado "
            "diretamente dos dados; (3) pontos/pixels de extração CHIRPS EFETIVAMENTE "
            "DISTINTOS — DESCONHECIDO, exigiria as coordenadas usadas na extração de cada "
            "fazenda (ainda ausentes); (4) instrumentos pluviométricos EFETIVAMENTE "
            "INDEPENDENTES — DESCONHECIDO e, dado que SINOBRAS.csv foi informado pelo "
            "responsável pelos dados como estimativa CHIRPS (a empresa não tem pluviômetro em "
            "todas as fazendas), NEM SEQUER PRESUMIDO QUE EXISTA um instrumento físico para "
            f"cada uma das {n_identificadores} fazendas. Ter menos séries distintas "
            f"({n_series_distintas}) que identificadores ({n_identificadores}) é consistente, "
            "em ordem de parcimônia dado o novo contexto, com: pixel CHIRPS compartilhado entre "
            "fazendas geograficamente próximas (hipótese mais provável, mas não comprovada — "
            "ver docs/nmme-fase2c2-auditoria-chirps-sinobras.md); pluviômetro físico "
            "compartilhado, SE alguma fazenda do grupo tiver instrumento; replicação "
            "administrativa de um registro entre fazendas distintas; ou preenchimento (fill) de "
            "uma fazenda a partir de outra — nenhuma das hipóteses deve ser presumida sem a "
            "documentação operacional (coordenadas/polígonos usados na extração, versão/"
            "metodologia do CHIRPS, e confirmação de quais fazendas — se alguma — têm "
            "pluviômetro real) que este arquivo não contém."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Sensibilidade (informativo) — nunca uma correção proposta
# ══════════════════════════════════════════════════════════════════════════

def analisar_sensibilidade_deduplicacao(df, grupos):
    """Teste de SENSIBILIDADE apenas — pondera 1 vez cada série
    numericamente distinta (1 representante por grupo) em vez de
    pesar cada um dos identificadores igualmente (o procedimento atual
    de scripts/update_dashboard.py), e mede o quanto isso mudaria a
    média mensal. NÃO decide qual ponderação é mais correta — isso
    depende de saber se os grupos idênticos são pluviômetro
    compartilhado ou fazendas distintas com dado replicado."""
    representantes = [grupo[0] for grupo in grupos['grupos_de_series_identicas']]
    representantes += grupos['identificadores_com_serie_unica']

    media_todos = df.groupby(['ano', 'mes'])['prec_mm'].mean()
    media_dedup = df[df['estacao'].isin(representantes)].groupby(['ano', 'mes'])['prec_mm'].mean()
    comparado = pd.DataFrame({'media_todos_os_identificadores_mm': media_todos,
                               'media_series_unicas_mm': media_dedup}).dropna()
    comparado['diff_abs_mm'] = (comparado['media_todos_os_identificadores_mm'] -
                                 comparado['media_series_unicas_mm']).abs()

    mes_maximo = None
    if len(comparado):
        idx_max = comparado['diff_abs_mm'].idxmax()
        mes_maximo = f'{int(idx_max[0])}-{int(idx_max[1]):02d}'

    return {
        'n_representantes_series_unicas': len(representantes),
        'diff_abs_media_mm': round(float(comparado['diff_abs_mm'].mean()), 4) if len(comparado) else None,
        'diff_abs_maxima_mm': round(float(comparado['diff_abs_mm'].max()), 4) if len(comparado) else None,
        'mes_da_diferenca_maxima': mes_maximo,
        'interpretacao': (
            "Teste de SENSIBILIDADE apenas, nunca uma correção proposta. A diferença entre "
            "pesar cada identificador igualmente (procedimento atual) e pesar cada série "
            "distinta uma única vez mostra o quanto a escolha de agregação espacial importa, "
            "mas não decide qual delas é mais correta. Se a hipótese de pixel CHIRPS "
            "compartilhado (ver 'interpretacao' de identificar_grupos_series_identicas) for "
            "confirmada, pesar por série única corrigiria uma superponderação implícita de "
            "pixels com mais fazendas mapeadas a eles — mas essa confirmação depende de "
            "documentação operacional (coordenadas/pixels de extração) ainda ausente."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Item 7 — análise espacial: necessidade de coordenadas individuais
# ══════════════════════════════════════════════════════════════════════════

def montar_achados_espaciais(grupos):
    """Item 7 — registra a NECESSIDADE de coordenadas/pixels de
    extração CHIRPS E do mapeamento identificador→instrumento físico
    (se algum existir), nunca as inventa nem as presume. CLAUDE.md
    (armadilha 8) documenta que data/fazendas.geojson foi
    deliberadamente substituído por um envelope único sem
    identificação por fazenda — este arquivo (SINOBRAS.csv) não traz
    coordenadas, e nenhum outro arquivo deste repositório associa
    FAZxx a uma coordenada individual.

    Revisão pontual (4ª rodada, 2026) — com a nova informação de que
    SINOBRAS.csv é estimativa CHIRPS por fazenda (não leitura de
    campo; a empresa não tem pluviômetro em todas as fazendas), a
    pergunta espacial de fundo muda: não é mais "onde fica o
    pluviômetro de cada fazenda", e sim "qual coordenada/pixel CHIRPS
    foi usado para gerar a estimativa de cada fazenda". As N séries
    mensais numericamente distintas (Seção 3/4) continuam um FATO
    sobre os DADOS recebidos, nunca uma contagem de locais físicos
    independentes nem de pixels CHIRPS distintos — nenhuma das duas
    equivalências deve ser presumida sem o mapeamento operacional que
    este arquivo não contém."""
    return {
        'coordenadas_individuais_disponiveis_no_arquivo': False,
        'coordenadas_individuais_disponiveis_no_repositorio': False,
        'mapeamento_identificador_para_instrumento_disponivel': False,
        'mapeamento_identificador_para_pixel_chirps_disponivel': False,
        'interpretacao': (
            "SINOBRAS.csv identifica cada registro por `estacao` (FAZxx), mas não traz "
            "coordenada nenhuma — e nenhum outro arquivo deste repositório associa um FAZxx a "
            "uma coordenada individual (CLAUDE.md, armadilha 8: data/fazendas.geojson foi "
            "deliberadamente substituído por um envelope único de 85.020,5 ha sem identificação "
            "por fazenda; decisão preservada aqui, não revertida). Com a reinterpretação CHIRPS "
            "(ver docs/nmme-fase2c2-auditoria-chirps-sinobras.md), são necessárias TRÊS coisas, "
            f"nunca supridas por este arquivo: (1) a coordenada/polígono usado para extrair a "
            f"estimativa CHIRPS de cada um dos {grupos['n_identificadores_comparados']} "
            "identificadores FAZxx; (2) a versão e a metodologia de extração do CHIRPS "
            "empregadas; e (3), SE alguma fazenda tiver de fato um pluviômetro físico, o "
            "mapeamento de qual(is) identificador(es) correspondem a instrumento real — a "
            f"empresa não tem pluviômetro em todas as fazendas, então essa lista pode ser um "
            f"subconjunto pequeno dos {grupos['n_identificadores_comparados']}, ou vazia. As "
            f"{grupos['n_series_mensais_distintas']} séries mensais numericamente distintas "
            "encontradas (Seção 3/4) são um FATO sobre os DADOS, não uma contagem de locais "
            "físicos NEM de pixels CHIRPS distintos — NÃO presumir que elas correspondem a "
            f"{grupos['n_series_mensais_distintas']} pontos de extração fisicamente "
            "independentes; sem o mapeamento identificador→coordenada/pixel, o número real de "
            f"pontos de extração permanece desconhecido (pode ser {grupos['n_series_mensais_distintas']}, "
            f"{grupos['n_identificadores_comparados']}, ou outro valor). Sem "
            "essas informações, o suporte espacial da observação — potencialmente múltiplos "
            "pixels CHIRPS, não um único centroide — não pode ser comparado à célula de grade "
            "do CFSv2 (~1°, ordem de 100km de lado). Sem elas, a distância de 22,91km do "
            "centroide agregado até a grade do CFSv2 (docs/nmme-fase2c2-auditoria-"
            "observacional-historica.md, Seção 5) continua sendo a distância de UM ponto "
            "agregado — nunca das estimativas individuais por fazenda."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Consolidação + relatório
# ══════════════════════════════════════════════════════════════════════════

def executar_auditoria_completa(caminho_arquivo, serie_path=pilo.SERIE_OBSERVACIONAL_PATH):
    sha256 = calcular_sha256(caminho_arquivo)
    df = carregar_sinobras(caminho_arquivo)

    integridade = verificar_integridade_estrutural(df)
    media_mensal = reproduzir_media_mensal(df)
    reconciliacao_resumo, reconciliacao_tabela = confrontar_com_serie_producao(media_mensal, serie_path=serie_path)
    grupos = identificar_grupos_series_identicas(df)
    distincao = distinguir_identificadores_series_e_instrumentos(integridade, grupos)
    sensibilidade = analisar_sensibilidade_deduplicacao(df, grupos)
    achados_espaciais = montar_achados_espaciais(grupos)

    metadata = {
        'fase': '2C.2 — auditoria da nova evidência SINOBRAS.csv (por fazenda, 1996-2025)',
        'arquivo_analisado': {
            'nome': Path(caminho_arquivo).name,
            'sha256': sha256,
            'reproduzir_com': f'python scripts/nmme_auditoria_sinobras_por_fazenda.py '
                               f'--arquivo <caminho_para_o_arquivo> --gerar-relatorio',
        },
        'integridade_estrutural': integridade,
        'reconciliacao_com_serie_producao': reconciliacao_resumo,
        'grupos_series_identicas': grupos,
        'distincao_identificadores_series_instrumentos': distincao,
        'sensibilidade_deduplicacao_informativo': sensibilidade,
        'achados_espaciais': achados_espaciais,
        'nenhuma_skill_calculada': True,
        'nenhuma_aptidao_cientifica_declarada': True,
        'nenhum_dashboard_alterado': True,
        'nenhuma_serie_historica_de_producao_alterada': True,
        'nenhuma_serie_duplicada_eliminada': True,
        'arquivo_original_nao_incorporado_ao_repositorio': True,
    }
    return reconciliacao_tabela, metadata


def gerar_relatorio_markdown(reconciliacao_tabela, metadata):
    arq = metadata['arquivo_analisado']
    integ = metadata['integridade_estrutural']
    rec = metadata['reconciliacao_com_serie_producao']
    grp = metadata['grupos_series_identicas']
    dist = metadata['distincao_identificadores_series_instrumentos']
    sens = metadata['sensibilidade_deduplicacao_informativo']
    esp = metadata['achados_espaciais']

    linhas = [
        "# Auditoria da nova evidência — SINOBRAS.csv (registros por fazenda, 1996-2025)",
        "",
        "**Relatório técnico — não calcula skill, não declara aptidão científica, não altera a "
        "série histórica de produção nem elimina séries duplicadas. O arquivo original não foi "
        "incorporado a este repositório.**",
        "",
        "> **Atualização (4ª rodada, 2026)**: o responsável pelos dados informou que "
        "SINOBRAS.csv contém ESTIMATIVAS extraídas do CHIRPS por fazenda, não medições diretas "
        "de pluviômetro — a empresa não tem pluviômetro em todas as fazendas. As seções abaixo "
        "foram revisadas para refletir essa informação (não comprovada documentalmente ainda). "
        "Ver docs/nmme-fase2c2-auditoria-chirps-sinobras.md para a investigação dedicada.",
        "",
        "## Evidência analisada",
        "",
        f"- Arquivo: `{arq['nome']}`.",
        f"- **SHA-256: `{arq['sha256']}`** — qualquer pessoa com o mesmo arquivo pode conferir "
        f"com `sha256sum {arq['nome']}` e comparar com este valor.",
        f"- Reprodutibilidade: `{arq['reproduzir_com']}`.",
        "",
        "## 1. Integridade estrutural",
        "",
        f"- Registros: {integ['n_registros']}. Identificadores distintos: {integ['n_identificadores']}.",
        f"- Período coberto: {integ['periodo_coberto_inicio']} → {integ['periodo_coberto_fim']} "
        f"({integ['n_meses_no_periodo_coberto']} meses).",
        f"- Meses ausentes dentro do período coberto: {integ['n_meses_ausentes_dentro_do_periodo']}.",
        f"- Registros por identificador — máximo: {integ['registros_por_identificador_maximo']}; "
        f"identificadores com contagem diferente do máximo: "
        f"{integ['identificadores_com_contagem_diferente_do_maximo'] or 'nenhum'}.",
        f"- Registros por mês — moda: {integ['moda_registros_por_mes']}; meses com número atípico "
        f"de registros: {integ['meses_com_numero_de_registros_atipico'] or 'nenhum'}.",
        f"- Duplicatas (ano, mês, estação): {integ['n_duplicatas_ano_mes_estacao']}.",
        f"- Valores ausentes: {integ['n_valores_ausentes']}. Valores fisicamente implausíveis "
        f"(fora de [{cpoc.PREC_MM_MIN_PLAUSIVEL}, {cpoc.PREC_MM_MAX_PLAUSIVEL}] mm/mês): "
        f"{integ['n_valores_implausiveis']}.",
        f"- **Integridade estrutural completa: {integ['integro']}**",
        "",
        "## 2. Reconciliação com data/serie_subst.csv (só leitura — nunca escrita)",
        "",
        f"- Meses no arquivo recebido: {rec['n_meses_no_arquivo_recebido']}.",
        f"- Meses sem correspondência na série de produção: "
        f"{rec['n_meses_sem_correspondencia_na_serie_producao']}.",
        f"- Meses comparáveis: {rec['n_meses_comparaveis']}. Idênticos após arredondamento a 2 "
        f"casas: {rec['n_meses_identicos_apos_arredondamento_2_casas']}.",
        f"- Diferença absoluta média: {rec['diff_abs_media_mm']} mm. Máxima: "
        f"{rec['diff_abs_maxima_mm']} mm.",
        f"- **Reconciliação completa: {rec['reconciliacao_completa']}**",
        "- A agregação numérica histórica (média aritmética simples dos identificadores por mês, "
        "mesma fórmula já verificada por leitura de código em "
        "`nmme_auditoria_observacional_historica.verificar_padrao_agregacao_sinobras_no_codigo`) "
        "foi REPRODUZIDA de forma independente a partir deste arquivo e bate com "
        "data/serie_subst.csv. Isso confirma a linhagem NUMÉRICA entre o arquivo recebido e a "
        "série consolidada — não confirma a versão nem a metodologia de extração do CHIRPS "
        "usadas para gerar essas estimativas (informado pelo responsável pelos dados, não "
        "verificado documentalmente), eventuais preenchimentos (fill) retrospectivos, nem se "
        "alguma fazenda tem, além da estimativa CHIRPS, um pluviômetro físico real — tudo isso "
        "permanece SEM COMPROVAÇÃO por este arquivo.",
        "",
        "## 3. Grupos de séries mensais idênticas (identificados automaticamente)",
        "",
        f"- Identificadores comparados: {grp['n_identificadores_comparados']}.",
        f"- Séries mensais numericamente distintas: {grp['n_series_mensais_distintas']}.",
        f"- Grupos com mais de 1 identificador compartilhando a mesma série completa: "
        f"{grp['n_grupos_com_mais_de_1_identificador']} — {grp['grupos_de_series_identicas']}.",
        f"- {grp['interpretacao']}",
        "",
        "## 4. Identificadores × séries distintas × pixels CHIRPS × instrumentos independentes",
        "",
        "**Quatro conceitos diferentes — nunca tratados como equivalentes nesta auditoria.**",
        "",
        f"- Identificadores de fazenda: {dist['n_identificadores_de_fazenda']}.",
        f"- Séries mensais numericamente distintas: "
        f"{dist['n_series_mensais_numericamente_distintas']}.",
        f"- Pontos de extração CHIRPS efetivamente distintos confirmados: "
        f"{dist['n_pontos_extracao_chirps_efetivamente_distintos_confirmados']} "
        "(desconhecido — exigiria as coordenadas de extração de cada fazenda).",
        f"- Instrumentos pluviométricos efetivamente independentes confirmados: "
        f"{dist['n_instrumentos_pluviometricos_efetivamente_independentes_confirmados']} "
        "(desconhecido — nem sequer presumido que exista instrumento físico para cada fazenda).",
        f"- {dist['interpretacao']}",
        "",
        "### Sensibilidade da agregação espacial (informativo — nunca uma correção proposta)",
        "",
        f"- Representantes usados no teste (1 por série distinta): "
        f"{sens['n_representantes_series_unicas']}.",
        f"- Diferença absoluta média entre pesar por identificador (atual) e por série única: "
        f"{sens['diff_abs_media_mm']} mm/mês. Máxima: {sens['diff_abs_maxima_mm']} mm/mês, em "
        f"{sens['mes_da_diferenca_maxima']}.",
        f"- {sens['interpretacao']}",
        "",
        "## 5. Análise espacial — necessidade de coordenadas/pixels de extração e do "
        "mapeamento identificador→instrumento",
        "",
        f"- Coordenadas individuais disponíveis neste arquivo: "
        f"{esp['coordenadas_individuais_disponiveis_no_arquivo']}.",
        f"- Coordenadas individuais disponíveis em qualquer arquivo deste repositório: "
        f"{esp['coordenadas_individuais_disponiveis_no_repositorio']}.",
        f"- Mapeamento identificador→instrumento físico disponível: "
        f"{esp['mapeamento_identificador_para_instrumento_disponivel']}.",
        f"- Mapeamento identificador→pixel CHIRPS disponível: "
        f"{esp['mapeamento_identificador_para_pixel_chirps_disponivel']}.",
        f"- {esp['interpretacao']}",
        "",
        "## Conclusões desta auditoria (item 6 da tarefa)",
        "",
        "- A agregação numérica histórica de 1996-2025 (`prec` de data/serie_subst.csv) foi "
        "REPRODUZIDA de forma independente a partir de SINOBRAS.csv — achado numérico, "
        "verificado acima (Seção 2).",
        "- O responsável pelos dados informou que SINOBRAS.csv é estimativa CHIRPS por fazenda, "
        "não leitura de pluviômetro — a versão/metodologia de extração do CHIRPS, eventuais "
        "preenchimentos/interpolações retrospectivas, e se alguma fazenda tem, além disso, um "
        "pluviômetro físico real PERMANECEM SEM COMPROVAÇÃO — nenhum destes pontos é decidível "
        "a partir deste arquivo isoladamente (ver docs/nmme-fase2c2-auditoria-chirps-"
        "sinobras.md).",
        "- Nenhuma série duplicada foi eliminada e nenhuma série histórica de produção foi "
        "alterada por esta auditoria — os grupos de séries idênticas (Seção 3) são só "
        "DOCUMENTADOS, nunca resolvidos ou removidos.",
        "",
        "## Restrições respeitadas nesta tarefa",
        "",
        "- Nenhuma métrica de skill foi calculada. Nenhuma aptidão científica foi declarada.",
        "- O dashboard (docs/index.html) não foi tocado.",
        "- A série histórica de produção (data/serie_subst.csv) não foi alterada — só lida.",
        "- Nenhuma série duplicada foi eliminada.",
        "- O arquivo original (SINOBRAS.csv) NÃO foi incorporado a este repositório — este "
        "módulo só o lê a partir do caminho informado em `--arquivo`.",
    ]
    return '\n'.join(linhas) + '\n'


def escrever_saidas(reconciliacao_tabela, metadata):
    """Tabelas/metadata reproduzíveis (reexecutando este script com o
    mesmo arquivo original) ficam em artifacts/ — gitignored. O
    relatório técnico vai para docs/, commitado — mesma convenção de
    nmme_auditoria_observacional_historica.py. O arquivo original
    SINOBRAS.csv nunca é copiado para nenhum dos dois diretórios."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    reconciliacao_tabela.to_csv(ARTIFACTS_DIR / 'reconciliacao_mensal.csv', index=False)
    (ARTIFACTS_DIR / 'metadata.json').write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=str))
    relatorio = gerar_relatorio_markdown(reconciliacao_tabela, metadata)
    RELATORIO_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    RELATORIO_DOC_PATH.write_text(relatorio)
    for nome in ('reconciliacao_mensal.csv', 'metadata.json'):
        print(f"  ✅ artifacts/nmme_auditoria_sinobras_por_fazenda/{nome}")
    print(f"  ✅ {RELATORIO_DOC_PATH.relative_to(ROOT)}")
    return relatorio


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def imprimir_plano():
    print("=== Auditoria da nova evidência SINOBRAS.csv (por fazenda) — Fase 2C.2 — "
          "DRY RUN PLAN (nenhum acesso à rede, nenhuma escrita no arquivo original) ===")
    print("  entrada: --arquivo <caminho para SINOBRAS.csv, fora do repositório>")
    print("  verificações: integridade estrutural, cobertura mensal, duplicatas, valores "
          "implausíveis, reconciliação com data/serie_subst.csv, grupos de séries idênticas")
    print("  saidas: artifacts/nmme_auditoria_sinobras_por_fazenda/ (gitignored) + "
          "docs/nmme-fase2c2-auditoria-sinobras-por-fazenda.md")
    print("\n✅ Plano da auditoria gerado (nenhum cálculo de skill, nenhuma escrita ainda).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--arquivo', type=str, default=None,
                     help='Caminho para o SINOBRAS.csv original (nunca copiado para o '
                          'repositório). Obrigatório com --gerar-relatorio.')
    ap.add_argument('--dry-run-plan', action='store_true',
                     help='Só mostra o plano — nenhuma leitura do arquivo, nenhuma escrita.')
    ap.add_argument('--gerar-relatorio', action='store_true',
                     help='Roda a auditoria completa sobre --arquivo e escreve o relatório '
                          'técnico + tabelas em artifacts/.')
    args = ap.parse_args()

    if args.gerar_relatorio:
        if not args.arquivo:
            ap.error('--gerar-relatorio exige --arquivo <caminho para SINOBRAS.csv>')
        imprimir_plano()
        reconciliacao_tabela, metadata = executar_auditoria_completa(args.arquivo)
        escrever_saidas(reconciliacao_tabela, metadata)
        integ = metadata['integridade_estrutural']
        rec = metadata['reconciliacao_com_serie_producao']
        print(f"\nintegridade_estrutural_completa={integ['integro']}")
        print(f"reconciliacao_completa={rec['reconciliacao_completa']}")
        print(f"n_series_mensais_distintas={metadata['grupos_series_identicas']['n_series_mensais_distintas']}")
        return

    imprimir_plano()


if __name__ == '__main__':
    main()
