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

# Fase 2C.3B, item 1a — mes_ausente/nodata_sentinela são tratados como
# STATUS_RESOLVIDOS por padrão (meses_pendentes/executar_piloto NUNCA
# os retenta sozinhos, para não martelar o servidor à toa quando a
# ausência é real). reprocessar_ausentes_ou_nodata() é o mecanismo
# EXPLÍCITO e CONTROLADO para dar a esses meses uma nova chance —
# nunca automático, sempre com este teto rígido de tentativas.
#
# CORREÇÃO (auditoria independente, revisão) — a versão anterior só
# incrementava COLUNA_TENTATIVAS_REPROCESSAMENTO quando o resultado
# CONFIRMAVA ausente/nodata de novo; uma falha de rede/extração
# (status diferente de ok/zero_real/mes_ausente/nodata_sentinela)
# caía no `else` e (a) não incrementava o contador — então uma
# sequência de falhas de rede nunca atingia o teto, tentativas
# efetivamente indefinidas apesar do nome da variável — E (b)
# sobrescrevia a linha persistida inteira com o resultado da falha,
# apagando a classificação anterior (mes_ausente/nodata_sentinela)
# do CSV. Agora três contadores distintos, nunca confundidos:
#   COLUNA_TENTATIVAS_REPROCESSAMENTO    — toda chamada REAL feita a
#       extrair_pixel_mensal por este mecanismo conta 1, não importa o
#       desfecho (confirmação, resolução ou falha) — é este que define
#       o teto (`max_tentativas`), então "tentativas" agora corresponde
#       de fato a tentativas.
#   COLUNA_CONFIRMACOES_REPROCESSAMENTO  — subconjunto das tentativas
#       em que o resultado confirmou o MESMO tipo (ausente/nodata) de
#       novo.
#   COLUNA_FALHAS_REPROCESSAMENTO        — subconjunto das tentativas
#       em que houve falha de rede/extração (nem confirmação, nem
#       resolução) — nessas, a linha persistida NUNCA é sobrescrita: a
#       classificação anterior (status/valor_mm/etc.) é preservada
#       intacta, só os contadores e o histórico de diagnóstico mudam.
# COLUNA_HISTORICO_FALHAS_REPROCESSAMENTO guarda um log compacto
# (status + timestamp de cada falha, concatenados) para diagnosticar
# sem precisar reprocessar de novo.
MAX_TENTATIVAS_REPROCESSAMENTO_AUSENTE_OU_NODATA = 3
COLUNA_TENTATIVAS_REPROCESSAMENTO = 'tentativas_reprocessamento_ausente_ou_nodata'
COLUNA_CONFIRMACOES_REPROCESSAMENTO = 'confirmacoes_reprocessamento_ausente_ou_nodata'
COLUNA_FALHAS_REPROCESSAMENTO = 'falhas_reprocessamento_ausente_ou_nodata'
COLUNA_HISTORICO_FALHAS_REPROCESSAMENTO = 'historico_falhas_reprocessamento_ausente_ou_nodata'

# Desfechos de extrair_pixel_mensal() que NÃO são confirmação de
# ausente/nodata nem resolução (ok/zero_real) — falha de rede/extração
# durante a TENTATIVA de reprocessamento (scripts/_chirps_v3.py::
# extrair_pixel_mensal nunca levanta exceção, sempre devolve um destes
# status em vez de propagar o erro).
STATUS_FALHA_REPROCESSAMENTO = {
    'erro_verificacao_disponibilidade', 'grade_inesperada', 'leitura_de_pixel_falhou',
    'arquivo_corrompido_ou_incompleto', 'erro_inesperado',
}


# ══════════════════════════════════════════════════════════════════════════
# Item 4 — extração-piloto, com retomada e limitação de downloads
# ══════════════════════════════════════════════════════════════════════════

def _carregar_resultados_persistidos(caminho_csv=None):
    """`caminho_csv` é parametrizável (item 4 da revisão, Fase 2C.3B) —
    permite reaproveitar esta mesma lógica de retomada/persistência
    para a reconstrução histórica (scripts/chirps_v3_reconstrucao_
    historica.py), gravando num arquivo SEPARADO, nunca
    data/chirps_v3_piloto.csv nem os arquivos de produção. `None`
    (padrão) usa o módulo-global DATA_PILOTO_CSV NO MOMENTO DA
    CHAMADA — nunca um valor padrão fixado em tempo de definição da
    função, que ficaria surdo a monkeypatch de teste
    (patch.object(piloto, 'DATA_PILOTO_CSV', ...))."""
    if caminho_csv is None:
        caminho_csv = DATA_PILOTO_CSV
    if not caminho_csv.exists():
        return pd.DataFrame(columns=['ano', 'mes', 'status'])
    return pd.read_csv(caminho_csv)


def meses_pendentes(meses=MESES_PILOTO, caminho_csv=None):
    """Retomada (item 4) — só reprocessa meses que NUNCA tiveram um
    resultado resolvido persistido (STATUS_RESOLVIDOS). Um mês com
    falha de rede/arquivo corrompido é retentado na próxima execução;
    um mês já 'ok'/'zero_real'/'nodata_sentinela'/'mes_ausente' não é
    reprocessado — evita repetir requisições desnecessárias."""
    persistidos = _carregar_resultados_persistidos(caminho_csv)
    ja_resolvidos = set()
    if not persistidos.empty:
        resolvidos_df = persistidos[persistidos['status'].isin(STATUS_RESOLVIDOS)]
        ja_resolvidos = set(zip(resolvidos_df['ano'], resolvidos_df['mes']))
    return [(a, m) for a, m in meses if (a, m) not in ja_resolvidos]


def executar_piloto(meses=MESES_PILOTO, max_requisicoes=MAX_REQUISICOES_POR_EXECUCAO,
                     rate_limit_segundos=RATE_LIMIT_SEGUNDOS, caminho_csv=None):
    """Executa a extração REAL (rede) — só os meses PENDENTES
    (retomada), até max_requisicoes por execução (limitação de
    downloads, item 4), com um intervalo mínimo entre requisições
    (gentileza com o servidor do CHC). NUNCA baixa a série completa —
    `meses` é sempre um subconjunto explícito, nunca 1981-presente.

    `caminho_csv=None` (item 4 da revisão) usa DATA_PILOTO_CSV no
    momento da chamada (mesmo motivo documentado em
    _carregar_resultados_persistidos) — permite reaproveitar esta
    função para a reconstrução histórica (Fase 2C.3B), gravando num
    arquivo separado do piloto — ver scripts/chirps_v3_reconstrucao_
    historica.py."""
    if caminho_csv is None:
        caminho_csv = DATA_PILOTO_CSV
    pendentes = meses_pendentes(meses, caminho_csv=caminho_csv)[:max_requisicoes]
    persistidos = _carregar_resultados_persistidos(caminho_csv)
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

    caminho_csv.parent.mkdir(parents=True, exist_ok=True)
    combinado.to_csv(caminho_csv, index=False)
    return combinado


# ══════════════════════════════════════════════════════════════════════════
# Fase 2C.3B, item 1a — reprocessamento CONTROLADO de ausente/NoData,
# com teto rígido de tentativas (nunca automático, nunca indefinido)
# ══════════════════════════════════════════════════════════════════════════

def reprocessar_ausentes_ou_nodata(meses=None, max_tentativas=MAX_TENTATIVAS_REPROCESSAMENTO_AUSENTE_OU_NODATA,
                                    rate_limit_segundos=RATE_LIMIT_SEGUNDOS, caminho_csv=None):
    """Mecanismo EXPLÍCITO (precisa ser chamado deliberadamente — nunca
    invocado por dentro de executar_piloto/meses_pendentes, que tratam
    mes_ausente/nodata_sentinela como resolvidos por padrão) para dar
    aos meses classificados como AUSENTES ou NODATA uma nova chance —
    útil quando o CHIRPS Final publica um mês atrasado, ou quando um
    NoData pontual foi transitório do lado do servidor.

    Nunca tentativas indefinidas: cada mês carrega um contador
    persistido (COLUNA_TENTATIVAS_REPROCESSAMENTO) que conta toda
    TENTATIVA REAL (toda chamada a extrair_pixel_mensal feita por este
    mecanismo para aquele mês) — não importa se o desfecho foi
    confirmação do mesmo status, resolução, ou falha de rede/extração.
    Ao atingir `max_tentativas`, o mês para de ser candidato,
    permanentemente, até intervenção manual (não há reset automático).

    CORREÇÃO (auditoria independente) — a versão anterior só contava
    como "tentativa" um resultado que CONFIRMASSE ausente/nodata de
    novo; uma falha de rede/extração nem incrementava o contador (o
    teto de 3 nunca era atingido por uma sequência de falhas — tentativa
    indefinida de fato) nem preservava a classificação anterior (a
    linha era sobrescrita pelo resultado da falha, apagando
    mes_ausente/nodata_sentinela do CSV). Agora:
    - COLUNA_TENTATIVAS_REPROCESSAMENTO sobe em toda chamada real — é
      o contador que define o teto, e por isso corresponde de fato a
      tentativas (nunca mais preso a "só quando confirma").
    - COLUNA_CONFIRMACOES_REPROCESSAMENTO sobe só quando o resultado
      confirma o mesmo tipo (ausente/nodata) de novo — diagnóstico
      separado, nunca usado para o teto.
    - COLUNA_FALHAS_REPROCESSAMENTO sobe quando a tentativa falha por
      rede/extração (`STATUS_FALHA_REPROCESSAMENTO`); nesse caso a
      linha persistida NUNCA é sobrescrita — a classificação anterior
      (status/valor_mm/proveniência) é preservada intacta, só os três
      contadores e COLUNA_HISTORICO_FALHAS_REPROCESSAMENTO (log
      compacto status@timestamp, concatenado, nunca substituído) mudam.
      Isso cobre "preservar o histórico necessário para diagnosticar
      falhas e evitar que um erro de rede apague indevidamente a
      classificação anterior".

    Se o reprocessamento resolver o mês (status vira ok/zero_real), o
    mês sai da lista de candidatos porque o status mudou — os
    contadores continuam persistidos, só para diagnóstico.

    `meses`, se fornecido, restringe ainda mais os candidatos a um
    subconjunto explícito (ex.: só os meses de um lote específico) —
    nunca reprocessa nada fora de STATUS a reprocessar E (se `meses`
    fornecido) fora dessa lista."""
    if caminho_csv is None:
        caminho_csv = DATA_PILOTO_CSV
    persistidos = _carregar_resultados_persistidos(caminho_csv)
    if persistidos.empty:
        return persistidos

    for coluna in (COLUNA_TENTATIVAS_REPROCESSAMENTO, COLUNA_CONFIRMACOES_REPROCESSAMENTO,
                   COLUNA_FALHAS_REPROCESSAMENTO):
        if coluna not in persistidos.columns:
            persistidos[coluna] = 0
        persistidos[coluna] = persistidos[coluna].fillna(0).astype(int)
    if COLUNA_HISTORICO_FALHAS_REPROCESSAMENTO not in persistidos.columns:
        persistidos[COLUNA_HISTORICO_FALHAS_REPROCESSAMENTO] = ''
    persistidos[COLUNA_HISTORICO_FALHAS_REPROCESSAMENTO] = (
        persistidos[COLUNA_HISTORICO_FALHAS_REPROCESSAMENTO].fillna(''))

    elegivel = (persistidos['status'].isin({'mes_ausente', 'nodata_sentinela'})
                & (persistidos[COLUNA_TENTATIVAS_REPROCESSAMENTO] < max_tentativas))
    if meses is not None:
        meses_set = set(meses)
        elegivel &= persistidos.apply(
            lambda r: (int(r['ano']), int(r['mes'])) in meses_set, axis=1)
    candidatos = persistidos[elegivel]

    if candidatos.empty:
        return persistidos

    novos = []
    for i, (_, row) in enumerate(candidatos.iterrows()):
        ano, mes = int(row['ano']), int(row['mes'])
        tentativas_ja_feitas = int(row[COLUNA_TENTATIVAS_REPROCESSAMENTO])
        confirmacoes_ja_feitas = int(row[COLUNA_CONFIRMACOES_REPROCESSAMENTO])
        falhas_ja_feitas = int(row[COLUNA_FALHAS_REPROCESSAMENTO])
        historico_ja_feito = row[COLUNA_HISTORICO_FALHAS_REPROCESSAMENTO] or ''
        if i > 0:
            time.sleep(rate_limit_segundos)
        resultado_bruto = v3.extrair_pixel_mensal(ano, mes)
        status_novo = resultado_bruto['status']
        tentativas_novas = tentativas_ja_feitas + 1   # toda chamada real conta 1 tentativa

        if status_novo in STATUS_FALHA_REPROCESSAMENTO:
            # Falha de rede/extração — NUNCA sobrescreve a classificação
            # anterior. Preserva a linha persistida inteira, só atualiza
            # os contadores de diagnóstico e o log de falhas.
            resultado = row.to_dict()
            entrada_log = f"{status_novo}@{resultado_bruto.get('data_extracao_utc', '')}"
            resultado[COLUNA_HISTORICO_FALHAS_REPROCESSAMENTO] = (
                f"{historico_ja_feito};{entrada_log}" if historico_ja_feito else entrada_log)
            resultado[COLUNA_TENTATIVAS_REPROCESSAMENTO] = tentativas_novas
            resultado[COLUNA_CONFIRMACOES_REPROCESSAMENTO] = confirmacoes_ja_feitas
            resultado[COLUNA_FALHAS_REPROCESSAMENTO] = falhas_ja_feitas + 1
        else:
            # Confirmação (ausente/nodata de novo) ou resolução
            # (ok/zero_real) — usa o resultado novo integralmente.
            resultado = resultado_bruto
            resultado[COLUNA_TENTATIVAS_REPROCESSAMENTO] = tentativas_novas
            resultado[COLUNA_CONFIRMACOES_REPROCESSAMENTO] = (
                confirmacoes_ja_feitas + 1 if status_novo in {'mes_ausente', 'nodata_sentinela'}
                else confirmacoes_ja_feitas)
            resultado[COLUNA_FALHAS_REPROCESSAMENTO] = falhas_ja_feitas
            resultado[COLUNA_HISTORICO_FALHAS_REPROCESSAMENTO] = historico_ja_feito

        novos.append(resultado)
        rotulo_tentativa = (f"FALHA({status_novo}) — status anterior preservado: {resultado['status']}"
                             if status_novo in STATUS_FALHA_REPROCESSAMENTO else f"status={status_novo}")
        print(f"  [reprocessamento {i+1}/{len(candidatos)}] {ano}-{mes:02d}: {rotulo_tentativa} "
              f"tentativas={resultado[COLUNA_TENTATIVAS_REPROCESSAMENTO]}/{max_tentativas} "
              f"confirmacoes={resultado[COLUNA_CONFIRMACOES_REPROCESSAMENTO]} "
              f"falhas={resultado[COLUNA_FALHAS_REPROCESSAMENTO]}")

    novos_df = pd.json_normalize(novos, sep='__')
    combinado = pd.concat([persistidos, novos_df], ignore_index=True)
    combinado = combinado.drop_duplicates(subset=['ano', 'mes'], keep='last')
    combinado = combinado.sort_values(['ano', 'mes']).reset_index(drop=True)

    caminho_csv.parent.mkdir(parents=True, exist_ok=True)
    combinado.to_csv(caminho_csv, index=False)
    return combinado


def meses_esgotados_reprocessamento(caminho_csv=None,
                                     max_tentativas=MAX_TENTATIVAS_REPROCESSAMENTO_AUSENTE_OU_NODATA):
    """Diagnóstico — lista os meses ausentes/NoData que já atingiram o
    teto de TENTATIVAS REAIS (não candidatos a reprocessar
    automaticamente nunca mais, sem intervenção manual). Usa
    COLUNA_TENTATIVAS_REPROCESSAMENTO (tentativas reais, confirmação ou
    falha) — não COLUNA_CONFIRMACOES_REPROCESSAMENTO, que sozinho
    poderia nunca atingir o teto numa sequência de falhas de rede."""
    if caminho_csv is None:
        caminho_csv = DATA_PILOTO_CSV
    persistidos = _carregar_resultados_persistidos(caminho_csv)
    if persistidos.empty or COLUNA_TENTATIVAS_REPROCESSAMENTO not in persistidos.columns:
        return []
    esgotados = persistidos[
        persistidos['status'].isin({'mes_ausente', 'nodata_sentinela'})
        & (persistidos[COLUNA_TENTATIVAS_REPROCESSAMENTO].fillna(0).astype(int) >= max_tentativas)]
    return [(int(r['ano']), int(r['mes'])) for _, r in esgotados.iterrows()]


# ══════════════════════════════════════════════════════════════════════════
# Item 5 — controle de qualidade: reprova o piloto se algo comprometer
# a integridade da referência
# ══════════════════════════════════════════════════════════════════════════

STATUS_VALOR_VALIDO = {'ok', 'zero_real'}
# "Extração bem-sucedida" = conseguimos abrir o raster, confirmar a
# grade e ler/classificar UM valor de pixel — mesmo que esse valor,
# depois de classificado, não seja utilizável (ex.: implausível). Não
# inclui mes_ausente/erro_verificacao_disponibilidade (nunca chegou a
# tentar abrir o raster) nem grade_inesperada (abriu, mas a grade não
# bateu — deliberadamente não confiamos na localização do pixel nesse
# caso, então não conta como extração bem-sucedida para nossos fins).
STATUS_EXTRACAO_BEM_SUCEDIDA = STATUS_VALOR_VALIDO | {
    'nodata_sentinela', 'nodata_nan', 'valor_negativo_nao_e_sentinela_conhecida',
    'valor_implausivel_alto'}


def avaliar_qualidade_piloto(resultados_df, meses_esperados=MESES_PILOTO):
    """Correção (auditoria independente, item 3) — a versão anterior
    tratava 'mes_ausente' (404) como não-reprovante para um período
    OBRIGATÓRIO e fixo (os 17 meses do piloto são todos anteriores a
    hoje, o CHIRPS Final já deveria estar publicado para todos) — isso
    estava ERRADO: um período obrigatório não pode ser considerado
    integralmente aprovado quando QUALQUER mês está ausente, tem
    NoData, ou teve falha de extração. Agora distingue EXPLICITAMENTE
    quatro dimensões diferentes, nunca um único booleano cru:

    1. disponibilidade_no_servidor — o arquivo respondeu à checagem
       HEAD (identificacao_arquivo.disponivel).
    2. sucesso_da_extracao — conseguimos abrir o raster, a grade bateu,
       e um valor de pixel foi lido e classificado (mesmo que a
       classificação seja 'não utilizável', ex.: NoData) — ver
       STATUS_EXTRACAO_BEM_SUCEDIDA.
    3. valor_valido_disponivel — o valor classificado é uma
       precipitação REAL utilizável (status ok/zero_real) — ver
       STATUS_VALOR_VALIDO. NoData e valor implausível NÃO contam
       aqui, mesmo que a extração (dimensão 2) tenha "funcionado".
    4. cobertura_temporal_completa — TODOS os meses esperados têm
       valor_valido_disponivel=True. Esta é a condição de
       'aprovado' — um período obrigatório com qualquer lacuna (mês
       sem tentativa, ausente no servidor, NoData, ou falha de
       extração) NUNCA é aprovado como integralmente coberto.

    CORREÇÃO (Fase 2C.3B, item 1b) — a versão anterior calculava
    `n_meses_disponiveis_no_servidor` e `meses_com_falha` sobre TODO
    `resultados_df`, não só sobre `meses_esperados`. Isso é inofensivo
    quando `resultados_df` só tem os meses de UM período (como o
    piloto de 17 meses, sempre avaliado sozinho), mas quebra assim que
    o mesmo arquivo de resultados acumula VÁRIOS lotes da reconstrução
    histórica (Fase 2C.3B) — avaliar a qualidade de UM lote passando o
    CSV inteiro (com outros lotes já persistidos) inflaria/distorceria
    os indicadores com meses de fora do período pedido. Agora TODO
    cálculo desta função opera exclusivamente sobre o subconjunto de
    `resultados_df` cujos (ano,mes) estão em `meses_esperados` —
    `df_no_periodo`, filtrado logo abaixo, nunca `resultados_df` bruto
    depois deste ponto."""
    esperados = sorted(set(meses_esperados))
    esperados_set = set(esperados)
    n_esperados = len(esperados)

    if resultados_df.empty:
        df_no_periodo = resultados_df
        presentes_map = {}
    else:
        mask_no_periodo = resultados_df.apply(
            lambda r: (int(r['ano']), int(r['mes'])) in esperados_set, axis=1)
        df_no_periodo = resultados_df[mask_no_periodo]
        presentes_map = {(int(r['ano']), int(r['mes'])): r['status']
                          for _, r in df_no_periodo.iterrows()}

    faltando = [(a, m) for a, m in esperados if (a, m) not in presentes_map]

    def _contar(predicado):
        return sum(1 for (a, m) in esperados if (a, m) in presentes_map
                   and predicado(presentes_map[(a, m)]))

    n_disponivel_no_servidor = 0
    if not df_no_periodo.empty and 'identificacao_arquivo__disponivel' in df_no_periodo.columns:
        n_disponivel_no_servidor = int(df_no_periodo['identificacao_arquivo__disponivel']
                                        .fillna(False).astype(bool).sum())
    n_extracao_sucesso = _contar(lambda s: s in STATUS_EXTRACAO_BEM_SUCEDIDA)
    n_valor_valido = _contar(lambda s: s in STATUS_VALOR_VALIDO)
    n_mes_ausente = _contar(lambda s: s == 'mes_ausente')
    n_nodata = _contar(lambda s: s in {'nodata_sentinela', 'nodata_nan'})

    status_falha_extracao = {'erro_verificacao_disponibilidade', 'grade_inesperada',
                              'leitura_de_pixel_falhou', 'arquivo_corrompido_ou_incompleto',
                              'erro_inesperado', 'valor_negativo_nao_e_sentinela_conhecida',
                              'valor_implausivel_alto'}
    meses_com_falha = [(a, m) for (a, m), s in presentes_map.items() if s in status_falha_extracao]

    cobertura_temporal_completa = (len(faltando) == 0) and (n_valor_valido == n_esperados)
    aprovado = cobertura_temporal_completa   # única condição — ver docstring

    return {
        'aprovado': aprovado,
        'cobertura_temporal_completa': cobertura_temporal_completa,
        'n_meses_esperados': n_esperados,
        'n_meses_disponiveis_no_servidor': n_disponivel_no_servidor,
        'n_meses_com_extracao_bem_sucedida': n_extracao_sucesso,
        'n_meses_com_valor_valido': n_valor_valido,
        'n_meses_ausentes_no_servidor': n_mes_ausente,
        'n_meses_com_nodata': n_nodata,
        'meses_faltando_sem_nenhuma_tentativa': [f'{a}-{m:02d}' for a, m in faltando],
        'meses_com_falha': [f'{a}-{m:02d}' for a, m in sorted(meses_com_falha)],
        'interpretacao': (
            f"{'APROVADO — cobertura temporal completa' if aprovado else 'REPROVADO — cobertura temporal INCOMPLETA'}: "
            f"de {n_esperados} meses obrigatórios, {n_disponivel_no_servidor} estavam "
            f"disponíveis no servidor, {n_extracao_sucesso} tiveram extração bem-sucedida "
            f"(raster aberto, grade validada, pixel lido e classificado), mas só "
            f"{n_valor_valido} têm um VALOR VÁLIDO utilizável (ok/zero_real) — "
            f"{n_mes_ausente} ausentes no servidor e {n_nodata} com NoData NÃO contam como "
            "valor válido, mesmo sendo respostas 'esperadas' do servidor/produto. Um período "
            "obrigatório e fixo (como este — todos os meses já deveriam estar publicados) só "
            "é considerado com cobertura temporal completa quando TODOS os meses têm valor "
            "válido — mes_ausente/NoData/falha de extração em QUALQUER mês impede a aprovação "
            "plena, mesmo que sejam respostas 'legítimas' do servidor. Reprovação bloqueia o "
            "uso científico deste período até a causa raiz ser corrigida — nunca prosseguir "
            "com dado incompleto/corrompido/ausente tratado como se fosse íntegro."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Item 6 — comparação com os dados existentes (só estatística
# descritiva, nunca skill)
# ══════════════════════════════════════════════════════════════════════════

def comparar_com_dados_existentes(resultados_df):
    """Compara os meses extraídos (status ok/zero_real) com os mesmos
    meses de data/chirps_1981_2025.csv (extraído pelo ClimateSERV —
    a versão do CHIRPS usada NUNCA foi registrada por aquele pipeline,
    então NÃO é identificada aqui como "CHIRPS v2 confirmado"; ver
    achado em docs/nmme-fase2c2-auditoria-chirps-sinobras.md,
    METODOLOGIA_CHIRPS_PONTO_CONHECIDA) e data/serie_subst.csv (série
    consolidada de produção — combina procedência pré-1996 não
    comprovada com estimativas CHIRPS zonais por fazenda pós-1996).

    Reutilizada tanto para o piloto de 17 meses (Fase 2C.3A) quanto
    para os lotes de reconstrução histórica de tamanho arbitrário
    (Fase 2C.3B) — nenhum texto abaixo assume um tamanho de amostra
    fixo; todas as contagens usam len(comparacoes) dinamicamente.

    Só estatísticas DESCRITIVAS (diferença assinada, contagem de meses
    acima/abaixo/iguais, razão) — nenhum indicador de habilidade
    preditiva do CFSv2 é calculado aqui (item 6 da tarefa, explícito).

    Correção (auditoria independente) — a versão anterior afirmava
    "v3 tende a ser mais úmido" como se fosse o comportamento
    observado NESTA amostra. Isso confundia duas coisas diferentes:
    (a) o comportamento GERAL do produto, descrito na documentação
    oficial (README: "CHIRPS v3.0 is overall wetter compared to
    CHIRPS v2.0" — uma afirmação sobre o produto agregado/global); (b)
    o comportamento efetivamente observado nesta amostra REGIONAL, que
    esta função agora calcula e reporta explicitamente — as duas NÃO
    precisam coincidir numa amostra pequena e regional, e de fato não
    coincidem aqui (ver interpretacao)."""
    validos = resultados_df[resultados_df['status'].isin({'ok', 'zero_real'})].copy()
    if validos.empty:
        return {'n_meses_comparaveis': 0, 'comparacoes': [],
                'interpretacao': 'Nenhum mês válido para comparar — sem dado utilizável no período.'}

    validos['prec_v3'] = validos['valor_mm'].astype(float)
    chirps_existente = pd.read_csv(CHIRPS_V2_PONTO_PATH) if CHIRPS_V2_PONTO_PATH.exists() else \
        pd.DataFrame(columns=['ano', 'mes', 'prec'])
    serie_prod = pd.read_csv(SERIE_PRODUCAO_PATH) if SERIE_PRODUCAO_PATH.exists() else \
        pd.DataFrame(columns=['ano', 'mes', 'prec'])

    comparacoes = []
    for _, row in validos.iterrows():
        ano, mes, prec_v3 = int(row['ano']), int(row['mes']), row['prec_v3']
        linha_existente = chirps_existente[(chirps_existente['ano'] == ano)
                                            & (chirps_existente['mes'] == mes)]
        linha_prod = serie_prod[(serie_prod['ano'] == ano) & (serie_prod['mes'] == mes)]
        entrada = {'ano': ano, 'mes': mes, 'prec_v3_ponto_novo': round(prec_v3, 2)}
        if not linha_existente.empty:
            prec_existente = float(linha_existente.iloc[0]['prec'])
            entrada['prec_chirps_existente_versao_nao_confirmada'] = prec_existente
            entrada['diff_v3_menos_existente_mm'] = round(prec_v3 - prec_existente, 2)
            entrada['razao_v3_sobre_existente'] = round(prec_v3 / prec_existente, 3) \
                if prec_existente else None
        if not linha_prod.empty:
            prec_prod = float(linha_prod.iloc[0]['prec'])
            entrada['prec_serie_producao'] = prec_prod
            entrada['diff_v3_menos_producao_mm'] = round(prec_v3 - prec_prod, 2)
            entrada['razao_v3_sobre_producao'] = round(prec_v3 / prec_prod, 3) if prec_prod \
                else None
        comparacoes.append(entrada)

    diffs_existente = [c['diff_v3_menos_existente_mm'] for c in comparacoes
                        if 'diff_v3_menos_existente_mm' in c]
    diffs_prod = [c['diff_v3_menos_producao_mm'] for c in comparacoes
                  if 'diff_v3_menos_producao_mm' in c]
    n_superior = sum(1 for d in diffs_existente if d > 0)
    n_inferior = sum(1 for d in diffs_existente if d < 0)
    n_igual = sum(1 for d in diffs_existente if d == 0)
    diff_media_assinada = round(sum(diffs_existente) / len(diffs_existente), 2) \
        if diffs_existente else None
    diff_abs_media = round(sum(abs(d) for d in diffs_existente) / len(diffs_existente), 2) \
        if diffs_existente else None

    resumo = {
        'n_meses_comparaveis': len(comparacoes),
        'comparacoes': comparacoes,
        'n_meses_v3_superior_ao_existente': n_superior,
        'n_meses_v3_inferior_ao_existente': n_inferior,
        'n_meses_v3_igual_ao_existente': n_igual,
        'diff_media_assinada_vs_chirps_existente_mm': diff_media_assinada,
        'diff_abs_media_vs_chirps_existente_mm': diff_abs_media,
        'diff_abs_media_vs_serie_producao_mm': round(sum(abs(d) for d in diffs_prod) / len(diffs_prod), 2)
            if diffs_prod else None,
        'interpretacao': (
            f"{len(comparacoes)} meses comparados a três referências: (1) CHIRPS "
            "v3.0 Final, novo, ponto único no centroide, versão e metodologia CONTROLADAS "
            "(esta extração); (2) CHIRPS histórico existente (data/chirps_1981_2025.csv), "
            "extraído pelo ClimateSERV — a versão do CHIRPS usada NUNCA foi registrada por "
            "aquele pipeline, então NÃO é identificada aqui como 'CHIRPS v2 confirmado'; (3) "
            "série consolidada de produção (data/serie_subst.csv), que combina procedência "
            "pré-1996 não comprovada com estimativas CHIRPS ZONAIS por fazenda pós-1996 "
            "(metodologia diferente por desenho — zonal vs. ponto). "
            f"NESTA amostra de {len(comparacoes)} meses: {n_superior} meses com CHIRPS v3 "
            f"superior ao existente, {n_inferior} inferior, {n_igual} iguais — diferença média "
            f"assinada de {diff_media_assinada} mm (diferença absoluta média "
            f"{diff_abs_media} mm). Isto NÃO confirma nem contradiz, isoladamente, a afirmação "
            "geral do README oficial de que \"CHIRPS v3.0 is overall wetter compared to CHIRPS "
            "v2.0\" — aquela é uma caracterização do produto AGREGADO/GLOBAL; esta amostra é "
            f"REGIONAL (1 ponto, {len(comparacoes)} meses, região historicamente com viés "
            "conhecido em jun-ago e out-dez, CLAUDE.md armadilha 7) e pequena demais para "
            "generalizar. As duas coisas são distintas e não devem ser confundidas: "
            "comportamento documentado do produto vs. comportamento observado nesta amostra "
            "específica. Nenhum indicador de habilidade preditiva do CFSv2 foi calculado — só "
            "estatística descritiva de comparação entre referências (item 6 da tarefa)."
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
            'correcao_do_corte_temporal': (
                'CORREÇÃO (item 5, auditoria independente) — "climatologia expansível usando só '
                'anos ANTERIORES ao ano-alvo" ainda pode vazar informação POSTERIOR à data de '
                'emissão de uma previsão específica. Exemplo concreto: para o ano-alvo 2000, a '
                'regra "anos < 2000" inclui o ano de 1999 inteiro (jan-dez/1999) na '
                'climatologia — mas uma previsão inicializada em ago/1999 com H6 (mês-alvo '
                'jan/2000) foi EMITIDA antes de set-dez/1999 acontecerem; incluir esses 4 meses '
                'de 1999 na climatologia usada para avaliar essa previsão específica é '
                'look-ahead, mesmo que 1999 inteiro seja "um ano anterior ao ano-alvo". O corte '
                'correto NÃO é por ANO-ALVO — é pela DATA DE INICIALIZAÇÃO (init_date) de CADA '
                'previsão avaliada: o conjunto de treinamento da climatologia usada para avaliar '
                'uma previsão inicializada em init_date deve conter só observações CHIRPS com '
                'data <= o mês anterior a init_date, nunca observações posteriores — '
                'independentemente de em que ano-alvo a previsão caia.'
            ),
            'alternativa_a_janela_expansivel': (
                'Climatologia EXPANSÍVEL, corrigida: para CADA INICIALIZAÇÃO (init_date) '
                'avaliada — não para cada ano-alvo — a climatologia usa todas as observações '
                'CHIRPS disponíveis com data estritamente anterior a init_date (disponibilidade '
                'real do CHIRPS desde 1981, já confirmada — data/chirps_1981_2025.csv cobre '
                '1981-2025). Cresce ao longo do período avaliado, mas o corte acompanha o '
                'CALENDÁRIO REAL de cada inicialização, não um ano-alvo agregado — duas '
                'inicializações no mesmo ano-alvo mas em meses diferentes podem (e devem) usar '
                'climatologias de tamanho ligeiramente diferente. PROPOSTA INICIAL da tarefa '
                '(item 7), não a única.'
            ),
            'alternativa_b_leave_one_year_out': (
                'Climatologia LEAVE-ONE-YEAR-OUT retrospectiva: para o ano-alvo Y, a '
                'climatologia usa TODOS os anos do período de referência EXCETO Y (base fixa '
                'maior e simétrica em volta de Y, não só os anos anteriores). Metodologicamente '
                'DIFERENTE da expansível — não é uma variação menor dela. Por construção NÃO '
                'evita o mesmo tipo de look-ahead residual descrito acima dentro do próprio ano '
                'Y-1/Y+1 adjacente a Y — a mesma correção de corte por init_date, quando '
                'aplicável, deve ser considerada também aqui.'
            ),
            'regra_de_nao_mistura': (
                'As duas metodologias (a) e (b) NÃO DEVEM ser misturadas nos resultados de uma '
                'mesma avaliação — produzir e reportar os dois conjuntos de resultados '
                'SEPARADAMENTE, cada um com sua própria climatologia consistente ponta a ponta, '
                'nunca um indicador único que combine anos avaliados sob climatologias '
                'diferentes.'
            ),
            'distincao_de_simulacao_operacional_real': (
                'Esta é uma SIMULAÇÃO RETROSPECTIVA do que uma climatologia "sem look-ahead" '
                'teria sido, usando dados de HOJE — NÃO é uma reprodução estrita das condições '
                'operacionais históricas: o CHIRPS v3.0 não existia nos anos 1990 (lançado em '
                '2025-01-01, ver ressalva_retrospectiva_chirps_v3), então nenhuma climatologia '
                'baseada nele jamais esteve de fato disponível para um previsor operando naquela '
                'época, por mais rigoroso que seja o corte temporal aplicado aqui. O corte por '
                'init_date evita UM tipo de contaminação (look-ahead dentro desta simulação), '
                'não reconstrói a informação real disponível operacionalmente.'
            ),
            'h1_permanece_separado': (
                'A separação de H1 dos horizontes genuinamente futuros (ver semantica_de_h1) '
                'vale INDEPENDENTEMENTE do corte de climatologia escolhido: por construção, o '
                'mês-alvo de H1 é o mesmo mês de init_date, então nenhuma climatologia com corte '
                'em "antes de init_date" jamais incluiria a própria observação de H1 — mas H1 '
                'ainda deve ser reportado e avaliado separadamente dos demais horizontes (ver '
                'separacao_de_resultados), nunca agregado a eles como se fosse igualmente '
                '"futuro".'
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
# Item 2 da revisão — recalcula a classificação de proximidade de
# borda a partir dos limites JÁ PERSISTIDOS (sem reabrir raster, sem
# rede) — usa a mesma lógica corrigida de _chirps_v3.py
# ══════════════════════════════════════════════════════════════════════════

_CAMPOS_PIXEL_NECESSARIOS = ('pixel__pixel_bounds_lon_min', 'pixel__pixel_bounds_lon_max',
                             'pixel__pixel_bounds_lat_min', 'pixel__pixel_bounds_lat_max',
                             'pixel__ponto_consultado_lon', 'pixel__ponto_consultado_lat')


def recalcular_classificacao_pixel_persistida(resultados_df):
    """Item 2 — 'confrontar os resultados com os limites espaciais
    persistidos em data/chirps_v3_piloto.csv'. Recalcula a
    classificação de proximidade de borda de CADA mês a partir dos
    limites do pixel JÁ GRAVADOS na extração original (pixel__pixel_
    bounds_*, pixel__ponto_consultado_*) — nenhum raster é reaberto,
    nenhuma rede é usada, os 17 registros originais do piloto NÃO são
    alterados (esta função só LÊ o DataFrame, nunca escreve nele).

    Reaproveita _chirps_v3._classificar_proximidade (a mesma função
    que localizar_pixel() usa, já corrigida) — o resultado aqui é
    idêntico ao que uma nova extração produziria para o mesmo ponto/
    mesma grade, sem precisar reextrair."""
    linhas = []
    if resultados_df.empty:
        return linhas
    colunas_presentes = set(resultados_df.columns)
    if not set(_CAMPOS_PIXEL_NECESSARIOS).issubset(colunas_presentes):
        return linhas
    for _, row in resultados_df.iterrows():
        if any(pd.isna(row.get(c)) for c in _CAMPOS_PIXEL_NECESSARIOS):
            continue
        lon_min = row['pixel__pixel_bounds_lon_min']
        lon_max = row['pixel__pixel_bounds_lon_max']
        lat_min = row['pixel__pixel_bounds_lat_min']
        lat_max = row['pixel__pixel_bounds_lat_max']
        ponto_lon = row['pixel__ponto_consultado_lon']
        ponto_lat = row['pixel__ponto_consultado_lat']
        res_lon, res_lat = lon_max - lon_min, lat_max - lat_min
        if res_lon <= 0 or res_lat <= 0:
            continue
        frac_lon = (ponto_lon - lon_min) / res_lon
        frac_lat = (lat_max - ponto_lat) / res_lat
        linhas.append({
            'ano': int(row['ano']), 'mes': int(row['mes']),
            'classificacao_proximidade_lon': v3._classificar_proximidade(frac_lon),
            'classificacao_proximidade_lat': v3._classificar_proximidade(frac_lat),
            'distancia_borda_mais_proxima_lon_graus': min(frac_lon, 1 - frac_lon) * res_lon,
            'distancia_borda_mais_proxima_lat_graus': min(frac_lat, 1 - frac_lat) * res_lat,
        })
    return linhas


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
        'classificacao_pixel_recalculada_dos_limites_persistidos':
            recalcular_classificacao_pixel_persistida(resultados_df),
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
        "- **Achado empírico CORRIGIDO nesta revisão** (auditoria independente encontrou o "
        "erro): lat/lon são múltiplos EXATOS da resolução NOMINAL do CHIRPS (0,05°), mas os "
        "coeficientes REAIS da transformação do raster não são exatamente 0,05 "
        "(0,05000000074505806 — resíduo de precisão float32→float64, ver "
        "`scripts/_chirps_v3.py::RESOLUCAO_GRAUS_REAL_CONFIRMADA`). Usando os coeficientes "
        "reais (correção aplicada em `localizar_pixel()`), o ponto fica classificado como "
        "**`proximo_de_borda`** nos dois eixos — a cerca de 1-2 milionésimos de grau "
        "(~0,1-0,2m) de duas bordas do pixel selecionado — e não `sobre_borda_exata`. A "
        "versão anterior deste relatório usava a resolução NOMINAL (não os coeficientes "
        "reais) para essa checagem, o que produzia um falso positivo de \"exatamente sobre "
        "uma quina compartilhada por 4 pixels\". O pixel efetivamente selecionado usa a "
        "convenção padrão do GDAL/rasterio (`numpy.floor` na fração de pixel, calculada com "
        "os coeficientes reais do transform) — ver `data/chirps_v3_piloto.csv`, colunas "
        "`pixel__*`, para as coordenadas centrais e a extensão espacial exata do pixel "
        "selecionado, e a tabela abaixo (recalculada desses mesmos limites) para a "
        "classificação de proximidade de borda. Um teste de sensibilidade comparando o pixel "
        "selecionado com seus 8 vizinhos está disponível em `scripts/_chirps_v3.py::"
        "comparar_pixel_com_vizinhos()` — informativo, nunca troca automaticamente a "
        "referência do projeto.",
        "- Esta referência (`CHIRPS_v3_ponto_centroide`) é um PONTO ÚNICO — não é apresentada "
        "como equivalente à média zonal das 34 fazendas (SINOBRAS.csv/data/serie_subst.csv "
        "pós-1996) nem à média zonal do envelope único (`scripts/_chirps.py::"
        "buscar_prec_chirps_zonal`).",
        "",
        "### Classificação de proximidade de borda, recalculada dos limites persistidos",
        "",
        "Recalculada diretamente de `data/chirps_v3_piloto.csv` (pixel_bounds_*/ponto_"
        "consultado_*, já gravados na extração original) — nenhum raster reaberto, nenhuma "
        "rede usada, os 17 registros originais preservados.",
        "",
        "| Ano-mês | Classe (lon) | Classe (lat) | Dist. borda mais próxima (lon, °) | Dist. "
        "borda mais próxima (lat, °) |",
        "|---|---|---|---|---|",
    ]
    for c in metadata['classificacao_pixel_recalculada_dos_limites_persistidos']:
        linhas.append(
            f"| {c['ano']}-{c['mes']:02d} | {c['classificacao_proximidade_lon']} | "
            f"{c['classificacao_proximidade_lat']} | "
            f"{c['distancia_borda_mais_proxima_lon_graus']:.2e} | "
            f"{c['distancia_borda_mais_proxima_lat_graus']:.2e} |")
    linhas += [
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
        "",
        "### Quatro dimensões distintas (nunca um único booleano)",
        "",
        f"1. Disponibilidade no servidor: {qual['n_meses_disponiveis_no_servidor']}/"
        f"{qual['n_meses_esperados']}.",
        f"2. Sucesso da extração (raster aberto, grade validada, pixel lido/classificado): "
        f"{qual['n_meses_com_extracao_bem_sucedida']}/{qual['n_meses_esperados']}.",
        f"3. Valor de precipitação VÁLIDO disponível (ok/zero_real — NoData e ausência NÃO "
        f"contam): {qual['n_meses_com_valor_valido']}/{qual['n_meses_esperados']}.",
        f"4. Cobertura temporal completa do período (TODOS os meses com valor válido): "
        f"{'SIM' if qual['cobertura_temporal_completa'] else 'NÃO'}.",
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
        f"- Meses com CHIRPS v3 superior ao existente: "
        f"{comp.get('n_meses_v3_superior_ao_existente', '—')}. Inferior: "
        f"{comp.get('n_meses_v3_inferior_ao_existente', '—')}. Iguais: "
        f"{comp.get('n_meses_v3_igual_ao_existente', '—')}.",
        f"- Diferença média ASSINADA (v3 menos existente): "
        f"{comp.get('diff_media_assinada_vs_chirps_existente_mm', '—')} mm. Diferença absoluta "
        f"média: {comp.get('diff_abs_media_vs_chirps_existente_mm', '—')} mm.",
        "",
        "| Ano-mês | CHIRPS v3 (novo) | CHIRPS existente (versão não confirmada) | Série "
        "produção (consolidada) |",
        "|---|---|---|---|",
    ]
    for c in comp.get('comparacoes', []):
        linhas.append(
            f"| {c['ano']}-{c['mes']:02d} | {c.get('prec_v3_ponto_novo', '—')} | "
            f"{c.get('prec_chirps_existente_versao_nao_confirmada', '—')} (diff "
            f"{c.get('diff_v3_menos_existente_mm', '—')}) | "
            f"{c.get('prec_serie_producao', '—')} (diff "
            f"{c.get('diff_v3_menos_producao_mm', '—')}) |")
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
        f"- Correção do corte temporal (item 5): "
        f"{e['climatologia_de_referencia']['correcao_do_corte_temporal']}",
        f"- Alternativa (a) — janela expansível: "
        f"{e['climatologia_de_referencia']['alternativa_a_janela_expansivel']}",
        f"- Alternativa (b) — leave-one-year-out: "
        f"{e['climatologia_de_referencia']['alternativa_b_leave_one_year_out']}",
        f"- Regra: {e['climatologia_de_referencia']['regra_de_nao_mistura']}",
        f"- Distinção de simulação vs. operação real: "
        f"{e['climatologia_de_referencia']['distincao_de_simulacao_operacional_real']}",
        f"- H1 permanece separado: "
        f"{e['climatologia_de_referencia']['h1_permanece_separado']}",
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
