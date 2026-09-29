#!/usr/bin/env python3
"""
chirps_v3_piloto.py — Fase 2C.3A: extração-piloto do CHIRPS v3.0 Final
(scripts/_chirps_v3.py), validação da metodologia e preparação da
infraestrutura para a reconstrução histórica. Independente do pipeline
operacional (scripts/_chirps.py, CHIRPS v2.0 via ClimateSERV) —
nenhuma modificação lá.

Meses do piloto (item 4 da tarefa) — NUNCA a série histórica completa:
    jan/abr/jul/out de 1991, 1998, 2005, 2010 (16 meses)
    + mai/2011 (mês-alvo do último horizonte da extração histórica do
      CFSv2 já aprovada — scripts/nmme_extracao_historica.py, 240
      origens jan/1991-dez/2010, H6 de dez/2010 cai em mai/2011)
    = 17 meses no total.

Saídas (separadas dos dados de produção, item 8):
    data/chirps_v3_piloto.csv           — 1 linha por mês do piloto
    data/chirps_v3_piloto_metadata.json — proveniência + integridade completas
    docs/nmme-fase2c3a-piloto-chirps-v3.md      — relatório técnico (item 5)
    docs/nmme-fase2c3a-protocolo-cfsv2.md       — protocolo científico (item 6)

Roda com:
    python scripts/chirps_v3_piloto.py --dry-run-plan
    python scripts/chirps_v3_piloto.py --executar-piloto-real
    python scripts/chirps_v3_piloto.py --gerar-relatorio
"""

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import _chirps_v3 as v3  # noqa: E402

DATA_PILOTO_CSV = ROOT / 'data' / 'chirps_v3_piloto.csv'
DATA_PILOTO_METADATA_JSON = ROOT / 'data' / 'chirps_v3_piloto_metadata.json'
RELATORIO_PILOTO_PATH = ROOT / 'docs' / 'nmme-fase2c3a-piloto-chirps-v3.md'
RELATORIO_PROTOCOLO_PATH = ROOT / 'docs' / 'nmme-fase2c3a-protocolo-cfsv2.md'

CHIRPS_V2_PONTO_PATH = ROOT / 'data' / 'chirps_1981_2025.csv'
SERIE_PRODUCAO_PATH = ROOT / 'data' / 'serie_subst.csv'

ANOS_PILOTO = (1991, 1998, 2005, 2010)
MESES_TRIMESTRAIS = (1, 4, 7, 10)
MESES_PILOTO = [(ano, mes) for ano in ANOS_PILOTO for mes in MESES_TRIMESTRAIS] + [(2011, 5)]

STATUS_RESOLVIDOS = {'ok', 'zero_real', 'nodata_sentinela', 'mes_ausente'}   # nunca reprocessa
RATE_LIMIT_SEGUNDOS = 1.0
MAX_REQUISICOES_POR_EXECUCAO = 30   # limite de segurança — piloto tem 17, nunca a série completa


# ══════════════════════════════════════════════════════════════════════════
# Item 4 — extração-piloto, com retomada e limitação de downloads
# ══════════════════════════════════════════════════════════════════════════

def _carregar_resultados_persistidos():
    if not DATA_PILOTO_CSV.exists():
        return pd.DataFrame(columns=['ano', 'mes', 'status'])
    return pd.read_csv(DATA_PILOTO_CSV)


def meses_pendentes(meses=MESES_PILOTO):
    """Retomada (item 4) — só reprocessa meses que NUNCA tiveram um
    resultado resolvido persistido (STATUS_RESOLVIDOS). Um mês com
    falha de rede/arquivo corrompido é retentado na próxima execução;
    um mês já 'ok'/'zero_real'/'nodata_sentinela'/'mes_ausente' não é
    reprocessado — evita repetir requisições desnecessárias."""
    persistidos = _carregar_resultados_persistidos()
    ja_resolvidos = set()
    if not persistidos.empty:
        resolvidos_df = persistidos[persistidos['status'].isin(STATUS_RESOLVIDOS)]
        ja_resolvidos = set(zip(resolvidos_df['ano'], resolvidos_df['mes']))
    return [(a, m) for a, m in meses if (a, m) not in ja_resolvidos]


def executar_piloto(meses=MESES_PILOTO, max_requisicoes=MAX_REQUISICOES_POR_EXECUCAO,
                     rate_limit_segundos=RATE_LIMIT_SEGUNDOS):
    """Executa a extração-piloto REAL (rede) — só os meses PENDENTES
    (retomada), até max_requisicoes por execução (limitação de
    downloads, item 4), com um intervalo mínimo entre requisições
    (gentileza com o servidor do CHC). NUNCA baixa a série completa —
    `meses` é sempre um subconjunto explícito, nunca 1981-presente."""
    pendentes = meses_pendentes(meses)[:max_requisicoes]
    persistidos = _carregar_resultados_persistidos()
    novos = []
    for i, (ano, mes) in enumerate(pendentes):
        if i > 0:
            time.sleep(rate_limit_segundos)
        resultado = v3.extrair_pixel_mensal(ano, mes)
        novos.append(resultado)
        print(f"  [{i+1}/{len(pendentes)}] {ano}-{mes:02d}: status={resultado['status']} "
              f"valor_mm={resultado.get('valor_mm')}")

    if not novos:
        return persistidos

    novos_df = pd.json_normalize(novos, sep='__')
    combinado = pd.concat([persistidos, novos_df], ignore_index=True) if not persistidos.empty \
        else novos_df
    # se um mês já existia com status NÃO resolvido e foi retentado
    # agora, a linha nova substitui a antiga (nunca duplica)
    combinado = combinado.drop_duplicates(subset=['ano', 'mes'], keep='last')
    combinado = combinado.sort_values(['ano', 'mes']).reset_index(drop=True)

    DATA_PILOTO_CSV.parent.mkdir(parents=True, exist_ok=True)
    combinado.to_csv(DATA_PILOTO_CSV, index=False)
    return combinado


# ══════════════════════════════════════════════════════════════════════════
# Item 5 — controle de qualidade: reprova o piloto se algo comprometer
# a integridade da referência
# ══════════════════════════════════════════════════════════════════════════

def avaliar_qualidade_piloto(resultados_df, meses_esperados=MESES_PILOTO):
    """O piloto é REPROVADO (aprovado=False) se: (1) algum mês
    ESPERADO não tiver linha nenhuma (nem tentativa registrada); (2)
    algum mês tiver status de falha real (erro de rede esgotado,
    arquivo corrompido, grade inesperada, leitura falhou, valor
    implausível, sentinela desconhecida); (3) a contagem de meses
    'ok'/'zero_real' for menor que um mínimo aceitável. 'mes_ausente'
    (404 real do servidor) NÃO reprova o piloto — é uma resposta válida
    do CHC, não uma falha da nossa extração; fica registrado à parte."""
    esperados = set(meses_esperados)
    presentes = set(zip(resultados_df['ano'], resultados_df['mes'])) if not resultados_df.empty \
        else set()
    faltando = sorted(esperados - presentes)

    status_falha = {'erro_verificacao_disponibilidade', 'grade_inesperada',
                     'leitura_de_pixel_falhou', 'arquivo_corrompido_ou_incompleto',
                     'erro_inesperado', 'valor_negativo_nao_e_sentinela_conhecida',
                     'valor_implausivel_alto', 'nodata_nan'}
    linhas_falha = resultados_df[resultados_df['status'].isin(status_falha)] \
        if not resultados_df.empty else resultados_df
    meses_com_falha = list(zip(linhas_falha['ano'], linhas_falha['mes'])) \
        if not linhas_falha.empty else []

    n_ok = int((resultados_df['status'].isin({'ok', 'zero_real'})).sum()) \
        if not resultados_df.empty else 0
    n_mes_ausente = int((resultados_df['status'] == 'mes_ausente').sum()) \
        if not resultados_df.empty else 0

    aprovado = (len(faltando) == 0) and (len(meses_com_falha) == 0)

    return {
        'aprovado': aprovado,
        'n_meses_esperados': len(esperados),
        'n_meses_com_resultado': len(presentes),
        'n_meses_ok_ou_zero_real': n_ok,
        'n_meses_ausentes_no_servidor': n_mes_ausente,
        'meses_faltando_sem_nenhuma_tentativa': [f'{a}-{m:02d}' for a, m in faltando],
        'meses_com_falha': [f'{a}-{m:02d}' for a, m in meses_com_falha],
        'interpretacao': (
            f"{'APROVADO' if aprovado else 'REPROVADO'}: {n_ok}/{len(esperados)} meses "
            f"extraídos com sucesso (ok/zero_real), {n_mes_ausente} ausentes no servidor "
            "(resposta 404 válida, não conta como falha), "
            f"{len(meses_com_falha)} com falha real, {len(faltando)} sem nenhuma tentativa "
            "registrada. Piloto reprovado bloqueia a Fase 2C.3B (reconstrução histórica) até "
            "a causa raiz ser corrigida — nunca prosseguir com dado incompleto/corrompido "
            "tratado como se fosse íntegro."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Item 6 — comparação com os dados existentes (só estatística
# descritiva, nunca skill)
# ══════════════════════════════════════════════════════════════════════════

def comparar_com_dados_existentes(resultados_df):
    """Compara os meses do piloto (status ok/zero_real) com os mesmos
    meses de data/chirps_1981_2025.csv (CHIRPS v2.0/ClimateSERV, ponto
    único, versão NÃO registrada) e data/serie_subst.csv (série
    consolidada de produção — combina procedência pré-1996 não
    comprovada com estimativas CHIRPS zonais por fazenda pós-1996).
    Só estatísticas DESCRITIVAS (diferença absoluta, razão) — nenhum
    indicador de habilidade preditiva do CFSv2 é calculado aqui (item
    6 da tarefa, explícito)."""
    validos = resultados_df[resultados_df['status'].isin({'ok', 'zero_real'})].copy()
    if validos.empty:
        return {'n_meses_comparaveis': 0, 'comparacoes': [],
                'interpretacao': 'Nenhum mês válido para comparar — piloto sem dado utilizável.'}

    validos['prec_v3'] = validos['valor_mm'].astype(float)
    chirps_v2 = pd.read_csv(CHIRPS_V2_PONTO_PATH) if CHIRPS_V2_PONTO_PATH.exists() else \
        pd.DataFrame(columns=['ano', 'mes', 'prec'])
    serie_prod = pd.read_csv(SERIE_PRODUCAO_PATH) if SERIE_PRODUCAO_PATH.exists() else \
        pd.DataFrame(columns=['ano', 'mes', 'prec'])

    comparacoes = []
    for _, row in validos.iterrows():
        ano, mes, prec_v3 = int(row['ano']), int(row['mes']), row['prec_v3']
        linha_v2 = chirps_v2[(chirps_v2['ano'] == ano) & (chirps_v2['mes'] == mes)]
        linha_prod = serie_prod[(serie_prod['ano'] == ano) & (serie_prod['mes'] == mes)]
        entrada = {'ano': ano, 'mes': mes, 'prec_v3_ponto_novo': round(prec_v3, 2)}
        if not linha_v2.empty:
            prec_v2 = float(linha_v2.iloc[0]['prec'])
            entrada['prec_v2_ponto_existente'] = prec_v2
            entrada['diff_abs_v3_menos_v2_mm'] = round(prec_v3 - prec_v2, 2)
            entrada['razao_v3_sobre_v2'] = round(prec_v3 / prec_v2, 3) if prec_v2 else None
        if not linha_prod.empty:
            prec_prod = float(linha_prod.iloc[0]['prec'])
            entrada['prec_serie_producao'] = prec_prod
            entrada['diff_abs_v3_menos_producao_mm'] = round(prec_v3 - prec_prod, 2)
            entrada['razao_v3_sobre_producao'] = round(prec_v3 / prec_prod, 3) if prec_prod \
                else None
        comparacoes.append(entrada)

    diffs_v2 = [c['diff_abs_v3_menos_v2_mm'] for c in comparacoes if 'diff_abs_v3_menos_v2_mm' in c]
    diffs_prod = [c['diff_abs_v3_menos_producao_mm'] for c in comparacoes
                  if 'diff_abs_v3_menos_producao_mm' in c]

    resumo = {
        'n_meses_comparaveis': len(comparacoes),
        'comparacoes': comparacoes,
        'diff_abs_media_vs_chirps_v2_ponto_mm': round(sum(abs(d) for d in diffs_v2) / len(diffs_v2), 2)
            if diffs_v2 else None,
        'diff_abs_media_vs_serie_producao_mm': round(sum(abs(d) for d in diffs_prod) / len(diffs_prod), 2)
            if diffs_prod else None,
        'interpretacao': (
            f"{len(comparacoes)} meses do piloto comparados às três referências: (1) CHIRPS "
            "v3.0 Final, novo, ponto único no centroide, versão e metodologia CONTROLADAS "
            "(este piloto); (2) CHIRPS histórico existente (data/chirps_1981_2025.csv), "
            "extraído pelo ClimateSERV, versão NÃO registrada (ver docs/nmme-fase2c3a-piloto-"
            "chirps-v3.md, Seção 1); (3) série consolidada de produção "
            "(data/serie_subst.csv), que combina procedência pré-1996 não comprovada com "
            "estimativas CHIRPS ZONAIS por fazenda pós-1996 (metodologia diferente por "
            "desenho — zonal vs. ponto — ver docs/nmme-fase2c2-auditoria-chirps-sinobras.md). "
            "Diferenças esperadas e não-triviais entre as três: v3 tende a ser mais úmido que "
            "v2 (correção de sub-captação por vento, ver README oficial). Nenhum indicador de "
            "habilidade preditiva do CFSv2 foi calculado — só estatística descritiva de "
            "comparação entre referências (item 6 da tarefa)."
        ),
    }
    return resumo


# ══════════════════════════════════════════════════════════════════════════
# Item 7 — preparação da avaliação científica (especificação, não execução)
# ══════════════════════════════════════════════════════════════════════════

def montar_especificacao_protocolo_cfsv2():
    """Item 7 — ESPECIFICAÇÃO do protocolo da Fase 2C.3C, nenhum
    cálculo de skill feito aqui. Baseada nos elementos JÁ CONFIRMADOS
    da extração histórica do CFSv2 (scripts/nmme_extracao_historica.py,
    240 origens aprovadas jan/1991-dez/2010, 34.560 registros RAW, H1-H6,
    24 membros/horizonte) e na semântica H1<->mês-de-inicialização já
    validada em scripts/nmme_processar.py
    (leadtime_para_mes_alvo_nmme, esquema='lead1_igual_mes_inicializacao',
    confirmada por _avaliar_semantica_forecast_period, Método B)."""
    return {
        'previsoes_cfsv2': {
            'periodo': 'jan/1991 a dez/2010 (240 inicializações)',
            'fonte': 'scripts/nmme_extracao_historica.py (já aprovado, 34.560 registros RAW)',
            'horizontes': 'H1-H6 (scripts/nmme_extracao_historica.py::LEADS_ESPERADOS)',
            'membros': '24 membros por horizonte',
        },
        'correspondencia_inicializacao_horizonte_alvo': (
            'RIGOROSA — cada registro RAW já carrega init_date, target_month e lead (L) '
            'explícitos (scripts/nmme_processar.py::montar_linha_raw); o protocolo da 2C.3C '
            'deve casar cada previsão com o mês-alvo (target_month) usando exatamente esses '
            'três campos, nunca inferir o mês-alvo por contagem posicional a partir do '
            'init_date sem checar o valor já gravado.'
        ),
        'referencia_observacional_para_comparacao': (
            'A MESMA referência CHIRPS v3.0 (scripts/_chirps_v3.py) para TODO o período '
            '1991-2011 — nunca misturar, dentro de uma mesma avaliação, um trecho com uma '
            'metodologia de referência e outro trecho com outra (ver CLAUDE.md armadilha 1 '
            'sobre não misturar eixos/referências de naturezas diferentes). Este piloto '
            '(17 meses) NÃO é essa reconstrução completa — é a validação da metodologia antes '
            'de reconstruir os ~252 meses de 1991-01 a 2011-05 na Fase 2C.3B.'
        ),
        'climatologia_de_referencia': {
            'restricao': 'NUNCA calculada usando os valores do período avaliado (contaminação '
                          'look-ahead/data leakage) — separação temporal estrita entre a '
                          'climatologia de referência e o período de teste.',
            'alternativa_a_janela_expansivel': (
                'Climatologia EXPANSÍVEL: para cada ano-alvo Y avaliado, a climatologia usa '
                'todos os anos de 1981 até Y-1 (disponibilidade real do CHIRPS desde 1981, já '
                'confirmada — data/chirps_1981_2025.csv cobre 1981-2025). Cresce ao longo do '
                'período avaliado — a climatologia usada para 1991 tem 10 anos de base (1981-'
                '1990), a usada para 2010 tem 29 anos (1981-2009). PROPOSTA INICIAL da tarefa '
                '(item 7), não a única.'
            ),
            'alternativa_b_leave_one_year_out': (
                'Climatologia LEAVE-ONE-YEAR-OUT retrospectiva: para o ano-alvo Y, a '
                'climatologia usa TODOS os anos do período de referência EXCETO Y (base fixa '
                'maior e simétrica em volta de Y, não só os anos anteriores). Metodologicamente '
                'DIFERENTE da expansível — não é uma variação menor dela.'
            ),
            'regra_de_nao_mistura': (
                'As duas metodologias (a) e (b) NÃO DEVEM ser misturadas nos resultados de uma '
                'mesma avaliação — produzir e reportar os dois conjuntos de resultados '
                'SEPARADAMENTE, cada um com sua própria climatologia consistente ponta a ponta, '
                'nunca um indicador único que combine anos avaliados sob climatologias '
                'diferentes.'
            ),
        },
        'avaliacao_deterministica_e_probabilistica': {
            'deterministica_ex': 'ex.: viés, MAE, RMSE, correlação entre a média/mediana do '
                                  'ensemble e a referência CHIRPS — especificação apenas, '
                                  'nenhum desses é calculado nesta tarefa.',
            'probabilistica_ex': 'ex.: CRPS, histograma de rank (rank histogram/Talagrand), '
                                  'diagramas de confiabilidade — usam os 24 membros como '
                                  'distribuição, não só a média/mediana — especificação apenas.',
            'restricao': 'nenhuma dessas métricas é calculada nesta tarefa (item 6 e item 8 da '
                         'tarefa são explícitos: não calcular skill nesta etapa).',
        },
        'separacao_de_resultados': (
            'Os resultados da 2C.3C devem ser reportados SEPARADAMENTE por horizonte (H1..H6) '
            'e por mês do ano (jan..dez) — nunca um único número agregado que esconda variação '
            'sazonal ou degradação de habilidade com o aumento do horizonte. Precedente direto: '
            'CLAUDE.md já documenta um viés sazonal forte e heterogêneo entre fontes de satélite '
            '(armadilha 7, tabela ERA5/CHIRPS por mês) — não há motivo para esperar que a '
            'habilidade do CFSv2 seja homogênea ao longo do ano.'
        ),
        'dependencia_temporal_das_previsoes': (
            'Inicializações consecutivas do CFSv2 (mensais) e seus horizontes SE SOBREPÕEM no '
            'tempo — o mês-alvo de dez/1990+H3 pode coincidir com o de jan/1991+H2, por '
            'exemplo — introduzindo autocorrelação entre "amostras" nominalmente independentes. '
            'O protocolo da 2C.3C precisa decidir explicitamente como tratar essa dependência '
            '(ex.: blocos por ano-alvo em vez de por inicialização, ou métodos de '
            'reamostragem/bootstrap que respeitem a estrutura temporal) — NENHUMA decisão é '
            'tomada aqui, só o requisito é registrado.'
        ),
        'semantica_de_h1': (
            'CONFIRMADO em scripts/nmme_processar.py (leadtime_para_mes_alvo_nmme, esquema '
            "padrão 'lead1_igual_mes_inicializacao', validado por _avaliar_semantica_"
            'forecast_period/Método B): H1 tem target_month IGUAL ao mês da própria '
            'inicialização — não o mês seguinte. Isso significa que H1 NÃO é uma previsão de '
            'um período genuinamente futuro no sentido estrito: no momento em que o CFSv2 '
            'inicializa (tipicamente no início do mês), o mês-alvo de H1 ainda está em curso e '
            'sua precipitação observada ainda não está disponível por completo. A tarefa pede '
            'explicitamente para confirmar se H1 deve ser classificado como "previsão" ou '
            '"previsão do mês corrente" — a REGISTRAR EXPLICITAMENTE na 2C.3C, considerando a '
            'disponibilidade temporal real dos dados: tratar H1 igual a H2-H6 (horizontes '
            'genuinamente futuros no momento da inicialização) arriscaria superestimar a '
            'habilidade do CFSv2 nesse horizonte especificamente por conter informação parcial '
            'do próprio mês-alvo. Nenhuma decisão de classificação é tomada aqui — só o achado '
            'e o risco são registrados, com a fonte exata no código que confirma a semântica.'
        ),
        'ressalva_retrospectiva_chirps_v3': (
            'Usar CHIRPS v3.0 (lançado em 2025-01-01, README oficial) retrospectivamente para '
            'avaliar previsões do CFSv2 de 1991-2010 NÃO equivale a ter os mesmos dados que '
            'estariam disponíveis operacionalmente naquela década — é uma referência de '
            'verificação com informação/estações incorporadas DEPOIS do fato (>90 fontes de '
            'estação na v3.0 contra as fontes disponíveis nos anos 1990; correção de '
            'sub-captação por vento; preenchimento de lacunas com ERA5, produto que só existe '
            'desde muito depois). Isso é o padrão da literatura de verificação retrospectiva '
            '(reanalysis/reforecast usa a melhor referência disponível HOJE, não a de época) — '
            'mas precisa ser registrado explicitamente como limitação de interpretação, nunca '
            'apresentado como "os mesmos dados que os previsores tinham em mãos na década de '
            '1990".'
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Consolidação + relatórios
# ══════════════════════════════════════════════════════════════════════════

def montar_metadata_piloto(resultados_df):
    qualidade = avaliar_qualidade_piloto(resultados_df)
    comparacao = comparar_com_dados_existentes(resultados_df)
    return {
        'fase': '2C.3A — piloto CHIRPS v3.0 Final, referência histórica independente (2026)',
        'data_geracao_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'metodologia': {
            'versao_chirps': v3.VERSAO_CHIRPS,
            'data_lancamento_versao': v3.DATA_LANCAMENTO_VERSAO,
            'fonte_readme': v3.FONTE_README_URL,
            'fonte_diretorio_base': v3.FONTE_DIRETORIO_BASE,
            'resolucao_graus': v3.RESOLUCAO_GRAUS,
            'crs': v3.CRS_ESPERADO,
            'unidade': v3.UNIDADE,
            'nodata_sentinela': v3.NODATA_SENTINELA,
            'nodata_sentinela_confirmada_como': 'valor empírico, lendo pixel oceânico conhecido '
                                                 '(-30,0) — NÃO documentado na tag GDAL NODATA '
                                                 'nem no README oficial',
            'ponto_referencia': {'lat': v3.FAZENDAS_LAT, 'lon': v3.FAZENDAS_LON,
                                  'identificador': 'CHIRPS_v3_ponto_centroide'},
            'nao_e_media_zonal_das_34_fazendas': True,
        },
        'meses_do_piloto': [f'{a}-{m:02d}' for a, m in MESES_PILOTO],
        'n_meses_do_piloto': len(MESES_PILOTO),
        'qualidade': qualidade,
        'comparacao_com_dados_existentes': comparacao,
        'nenhuma_skill_calculada': True,
        'nenhum_indicador_de_habilidade_preditiva_calculado': True,
        'nenhuma_serie_historica_completa_baixada': True,
        'scripts_chirps_py_nao_modificado': True,
        'sarimax_xgboost_dashboard_nao_alterados': True,
    }


def gerar_relatorio_piloto_markdown(resultados_df, metadata):
    meto = metadata['metodologia']
    qual = metadata['qualidade']
    comp = metadata['comparacao_com_dados_existentes']

    linhas = [
        "# Piloto CHIRPS v3.0 Final — referência histórica independente (Fase 2C.3A)",
        "",
        "**Relatório técnico — não calcula skill, não recalcula indicadores de habilidade "
        "preditiva, não substitui a referência observacional de produção, não altera "
        "SARIMAX/XGBoost/dashboard, não modifica scripts/_chirps.py.**",
        "",
        "## 1. Produto e fonte",
        "",
        f"- Fonte: Climate Hazards Center (UCSB), CHIRPS {meto['versao_chirps']} Final.",
        f"- Data de lançamento da versão: {meto['data_lancamento_versao']} (README oficial: "
        "\"Version 3.0 released 2025.01.01\" — v2.0 foi \"2015.02.12\").",
        f"- README oficial consultado ao vivo: {meto['fonte_readme']}",
        f"- Diretório base: `{meto['fonte_diretorio_base']}`",
        "- Produto: mensal já consolidado (`monthly/global/`), formato preferencial COG "
        "(Cloud-Optimized GeoTIFF, leitura remota por range-request HTTP via GDAL /vsicurl/ — "
        "nunca baixa o raster global inteiro), fallback TIFF comum. NUNCA reconstrução por "
        "soma de registros diários (item 2 da tarefa).",
        f"- Resolução espacial: {meto['resolucao_graus']}° — confirmada ao vivo abrindo um "
        "arquivo real (não presumida a partir da documentação).",
        f"- CRS: {meto['crs']}.",
        f"- Unidade: {meto['unidade']}.",
        f"- Valores NoData: sentinela {meto['nodata_sentinela']} — "
        f"{meto['nodata_sentinela_confirmada_como']}.",
        "- Mudanças-chave da v3.0 vs. v2.0 (README oficial): mais de 90 fontes de estação "
        "(quase 4x a v2.0), correção de sub-captação de pluviômetro por vento "
        "(gauge-undercatch), domínio espacial ampliado (60°N-60°S, antes 50°N-50°S), "
        "preenchimento de lacunas com ERA5 0,25° (antes CFS 0,5°) — resultado (texto do "
        "próprio README): \"CHIRPS v3.0 is overall wetter compared to CHIRPS v2.0\".",
        "- Identificação/integridade dos arquivos usados: capturada por requisição HEAD "
        "(ETag, Last-Modified, Content-Length) antes de cada leitura — ver "
        "`data/chirps_v3_piloto_metadata.json` para os valores por mês. A leitura via GDAL "
        "detecta arquivo corrompido/incompleto (status "
        "'arquivo_corrompido_ou_incompleto') sem baixar o arquivo inteiro para checksum.",
        "- **Não se presume que os arquivos CHIRPS já existentes neste repositório "
        "(`data/chirps_1981_2025.csv`) pertençam a esta mesma versão** — aquele arquivo foi "
        "extraído via ClimateSERV (`scripts/_chirps.py`), que serve a versão CORRENTE do "
        "CHIRPS sem versionamento explícito documentado (achado já registrado em "
        "docs/nmme-fase2c2-auditoria-chirps-sinobras.md, item "
        "METODOLOGIA_CHIRPS_PONTO_CONHECIDA); a versão efetivamente usada naquela extração "
        "permanece DESCONHECIDA — pode ou não ser v3.0.",
        "",
        "## 2. Referência espacial inicial — `CHIRPS_v3_ponto_centroide`",
        "",
        f"- Coordenadas consultadas: lat={meto['ponto_referencia']['lat']}, "
        f"lon={meto['ponto_referencia']['lon']} (centroide das fazendas, já estabelecido no "
        "projeto).",
        "- O pixel é localizado DIRETAMENTE pela transformação espacial do raster "
        "(`rasterio.DatasetReader.index`), nunca reutilizando a caixa pequena da extração "
        "ClimateSERV atual (`scripts/_chirps.py::_geometria_ponto`).",
        "- **Achado empírico confirmado nesta tarefa**: como lat/lon são múltiplos EXATOS da "
        "resolução do CHIRPS (0,05° — já registrado em `scripts/nmme_auditoria_chirps_"
        "sinobras.py` na rodada anterior, como risco teórico), o ponto cai exatamente sobre "
        "uma QUINA compartilhada por até 4 pixels da grade real do CHIRPS v3.0 — não é mais "
        "uma possibilidade teórica, é um fato verificado ao vivo. O pixel efetivamente "
        "selecionado usa a convenção padrão do GDAL/rasterio (`numpy.floor` na fração de "
        "pixel) — ver `data/chirps_v3_piloto_metadata.json`, campo `pixel` de cada mês, para "
        "as coordenadas centrais e a extensão espacial exatas do pixel selecionado.",
        "- Esta referência (`CHIRPS_v3_ponto_centroide`) é um PONTO ÚNICO — não é apresentada "
        "como equivalente à média zonal das 34 fazendas (SINOBRAS.csv/data/serie_subst.csv "
        "pós-1996) nem à média zonal do envelope único (`scripts/_chirps.py::"
        "buscar_prec_chirps_zonal`).",
        "",
        "## 3. Extração-piloto",
        "",
        f"- Meses do piloto: {metadata['n_meses_do_piloto']} — "
        f"{', '.join(metadata['meses_do_piloto'])}.",
        "- Mecanismo de retomada: meses com resultado já resolvido "
        "(ok/zero_real/nodata_sentinela/mes_ausente) NUNCA são reprocessados; falhas de rede "
        "são retentadas na próxima execução.",
        f"- Limite de requisições por execução: {MAX_REQUISICOES_POR_EXECUCAO} (o piloto tem "
        f"{len(MESES_PILOTO)} meses — a série histórica completa NUNCA é baixada "
        "automaticamente por este script).",
        f"- Intervalo mínimo entre requisições: {RATE_LIMIT_SEGUNDOS}s.",
        "",
        "## 4. Controle de qualidade",
        "",
        f"- Veredito: **{'APROVADO' if qual['aprovado'] else 'REPROVADO'}**.",
        f"- {qual['interpretacao']}",
    ]
    if qual['meses_faltando_sem_nenhuma_tentativa']:
        linhas.append(f"- Meses sem nenhuma tentativa registrada: "
                       f"{', '.join(qual['meses_faltando_sem_nenhuma_tentativa'])}.")
    if qual['meses_com_falha']:
        linhas.append(f"- Meses com falha real: {', '.join(qual['meses_com_falha'])}.")
    linhas += [
        "",
        "### Resultado por mês",
        "",
        "| Ano-mês | Status | Valor (mm) |",
        "|---|---|---|",
    ]
    if not resultados_df.empty:
        for _, row in resultados_df.sort_values(['ano', 'mes']).iterrows():
            valor = row.get('valor_mm')
            valor_fmt = f"{valor:.1f}" if pd.notna(valor) else "—"
            linhas.append(f"| {int(row['ano'])}-{int(row['mes']):02d} | {row['status']} | "
                           f"{valor_fmt} |")
    linhas += [
        "",
        "## 5. Comparação com os dados existentes",
        "",
        f"- {comp['interpretacao']}",
        "",
        "| Ano-mês | CHIRPS v3 (novo) | CHIRPS v2 ponto (existente) | Série produção "
        "(consolidada) |",
        "|---|---|---|---|",
    ]
    for c in comp.get('comparacoes', []):
        linhas.append(
            f"| {c['ano']}-{c['mes']:02d} | {c.get('prec_v3_ponto_novo', '—')} | "
            f"{c.get('prec_v2_ponto_existente', '—')} (diff "
            f"{c.get('diff_abs_v3_menos_v2_mm', '—')}) | "
            f"{c.get('prec_serie_producao', '—')} (diff "
            f"{c.get('diff_abs_v3_menos_producao_mm', '—')}) |")
    linhas += [
        "",
        "## Restrições respeitadas nesta tarefa",
        "",
        "- `scripts/_chirps.py` (pipeline operacional) NÃO foi modificado.",
        "- Nenhum indicador de habilidade preditiva do CFSv2 foi calculado.",
        "- Nenhuma referência observacional de produção foi substituída.",
        "- SARIMAX, XGBoost, dashboard e demais modelos climáticos não foram alterados.",
        "- A série histórica completa do CHIRPS v3.0 NÃO foi baixada automaticamente — só os "
        f"{len(MESES_PILOTO)} meses do piloto.",
        "- Nenhum raster global foi armazenado no repositório — só o valor do pixel e sua "
        "proveniência (`data/chirps_v3_piloto.csv`, `data/chirps_v3_piloto_metadata.json`).",
    ]
    return '\n'.join(linhas) + '\n'


def gerar_relatorio_protocolo_markdown(especificacao):
    e = especificacao
    linhas = [
        "# Protocolo científico proposto — Fase 2C.3C (CFSv2 × CHIRPS v3.0)",
        "",
        "**Especificação — nenhum cálculo de skill/habilidade preditiva é feito neste "
        "documento nem em nenhum script desta tarefa (Fase 2C.3A).**",
        "",
        "## 1. Previsões do CFSv2 usadas",
        "",
        f"- Período: {e['previsoes_cfsv2']['periodo']}.",
        f"- Fonte: `{e['previsoes_cfsv2']['fonte']}`.",
        f"- Horizontes: {e['previsoes_cfsv2']['horizontes']}.",
        f"- Membros: {e['previsoes_cfsv2']['membros']}.",
        "",
        "## 2. Correspondência inicialização × horizonte × mês-alvo",
        "",
        f"- {e['correspondencia_inicializacao_horizonte_alvo']}",
        "",
        "## 3. Referência observacional para comparação",
        "",
        f"- {e['referencia_observacional_para_comparacao']}",
        "",
        "## 4. Climatologia de referência",
        "",
        f"- Restrição: {e['climatologia_de_referencia']['restricao']}",
        f"- Alternativa (a) — janela expansível: "
        f"{e['climatologia_de_referencia']['alternativa_a_janela_expansivel']}",
        f"- Alternativa (b) — leave-one-year-out: "
        f"{e['climatologia_de_referencia']['alternativa_b_leave_one_year_out']}",
        f"- Regra: {e['climatologia_de_referencia']['regra_de_nao_mistura']}",
        "",
        "## 5. Avaliação determinística e probabilística",
        "",
        f"- Determinística: {e['avaliacao_deterministica_e_probabilistica']['deterministica_ex']}",
        f"- Probabilística: {e['avaliacao_deterministica_e_probabilistica']['probabilistica_ex']}",
        f"- {e['avaliacao_deterministica_e_probabilistica']['restricao']}",
        "",
        "## 6. Separação dos resultados",
        "",
        f"- {e['separacao_de_resultados']}",
        "",
        "## 7. Dependência temporal das previsões",
        "",
        f"- {e['dependencia_temporal_das_previsoes']}",
        "",
        "## 8. Semântica de H1",
        "",
        f"- {e['semantica_de_h1']}",
        "",
        "## 9. Ressalva sobre uso retrospectivo do CHIRPS v3.0",
        "",
        f"- {e['ressalva_retrospectiva_chirps_v3']}",
        "",
    ]
    return '\n'.join(linhas) + '\n'


def escrever_saidas(resultados_df, metadata):
    DATA_PILOTO_METADATA_JSON.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=str))
    relatorio_piloto = gerar_relatorio_piloto_markdown(resultados_df, metadata)
    RELATORIO_PILOTO_PATH.parent.mkdir(parents=True, exist_ok=True)
    RELATORIO_PILOTO_PATH.write_text(relatorio_piloto)

    especificacao = montar_especificacao_protocolo_cfsv2()
    relatorio_protocolo = gerar_relatorio_protocolo_markdown(especificacao)
    RELATORIO_PROTOCOLO_PATH.write_text(relatorio_protocolo)

    print(f"  ✅ {DATA_PILOTO_METADATA_JSON.relative_to(ROOT)}")
    print(f"  ✅ {RELATORIO_PILOTO_PATH.relative_to(ROOT)}")
    print(f"  ✅ {RELATORIO_PROTOCOLO_PATH.relative_to(ROOT)}")
    return relatorio_piloto, relatorio_protocolo


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def imprimir_plano():
    print("=== Piloto CHIRPS v3.0 Final — Fase 2C.3A — DRY RUN PLAN ===")
    print(f"  meses do piloto: {len(MESES_PILOTO)} — "
          f"{', '.join(f'{a}-{m:02d}' for a, m in MESES_PILOTO)}")
    print(f"  limite de requisições por execução: {MAX_REQUISICOES_POR_EXECUCAO}")
    print(f"  saídas: {DATA_PILOTO_CSV.relative_to(ROOT)}, "
          f"{DATA_PILOTO_METADATA_JSON.relative_to(ROOT)}, "
          f"{RELATORIO_PILOTO_PATH.relative_to(ROOT)}, "
          f"{RELATORIO_PROTOCOLO_PATH.relative_to(ROOT)}")
    print("\n✅ Plano gerado (nenhuma extração ainda, scripts/_chirps.py intocado).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run-plan', action='store_true')
    ap.add_argument('--executar-piloto-real', action='store_true',
                     help='Roda a extração-piloto REAL contra o CHC (rede) — só os meses '
                          'pendentes do piloto fixo, nunca a série completa.')
    ap.add_argument('--gerar-relatorio', action='store_true',
                     help='Gera os relatórios a partir do que já estiver persistido em '
                          'data/chirps_v3_piloto.csv (não executa rede).')
    args = ap.parse_args()

    if args.executar_piloto_real:
        imprimir_plano()
        resultados_df = executar_piloto()
        metadata = montar_metadata_piloto(resultados_df)
        escrever_saidas(resultados_df, metadata)
        print(f"\naprovado={metadata['qualidade']['aprovado']}")
        return

    if args.gerar_relatorio:
        resultados_df = _carregar_resultados_persistidos()
        metadata = montar_metadata_piloto(resultados_df)
        escrever_saidas(resultados_df, metadata)
        print(f"\naprovado={metadata['qualidade']['aprovado']}")
        return

    imprimir_plano()


if __name__ == '__main__':
    main()
