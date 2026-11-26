#!/usr/bin/env python3
"""
roni_historico.py — série histórica oficial do RONI (Relative Oceanic
Niño Index), snapshots imutáveis e proveniência.

Fase ENSO-RONI-MIGRAÇÃO 2. Contexto e decisões (ver
docs/ENSO_RONI_MIGRACAO_FASE2.md e o relatório da Fase 1):

Fonte canônica — confirmada institucionalmente, não só por coincidência
de valores com uma tabela HTML:
  https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt
listada no catálogo oficial https://www.cpc.ncep.noaa.gov/data/indices/,
seção "Relative Sea Surface Temperature": "Seasonal Relative ERSSTv6
(1991-2020 base period) 3-month running average in Nino 3.4" → "Data
(Relative Oceanic Nino Index)" (href exato /data/indices/RONI.ascii.txt),
e citada nominalmente no NWS Public Information Statement 26-05 (lido
por completo nesta fase, PDF extraído localmente) como "the following is
a text file of the RONI".

Distinto de `update_indices.parse_roni()` (NUNCA modificado por este
módulo): aquele é o parser tolerante legado — varre linha a linha e
devolve só o último registro válido, tolerando linhas malformadas
isoladas. Mantém seu contrato porque ainda tem consumidor (seus próprios
testes em tests/test_update_indices.py). Este módulo é o VALIDADOR
ESTRITO da série completa que será persistida: rejeita o documento
inteiro ante qualquer inconsistência estrutural (cabeçalho errado,
lacuna interna, duplicata divergente, valor não numérico/infinito/
implausível) — nunca aceita parcialmente uma série corrompida. A
tolerância do parser legado nunca é usada para promover a série
histórica (Seção 6 do prompt da Fase 2).

Convenção de ano/trimestre (confirmada ao vivo nesta fase, pelo
alinhamento dos picos históricos de El Niño/La Niña na própria série —
o arquivo não documenta a convenção explicitamente): a coluna YR do
RONI.ascii.txt é o ano do MÊS CENTRAL do trimestre, nunca do mês inicial
nem final. DJF/AAAA = dez(AAAA-1)-jan(AAAA)-fev(AAAA); NDJ/AAAA =
nov(AAAA)-dez(AAAA)-jan(AAAA+1). Ver `_mes_inicial_final()`.

Arquitetura de persistência (decisão aprovada na Fase 2 — REJEITA
explicitamente a alternativa de manter só uma série normalizada com
manifesto de hashes, "porque hashes identificam conteúdos, mas não
permitem recuperar conteúdos descartados"):
  - data/roni_snapshots/<sha256>.txt — snapshot IMUTÁVEL do conteúdo
    bruto de cada aquisição distinta já observada. Nunca sobrescrito;
    um novo snapshot só é criado se o hash ainda não existir.
  - data/roni_proveniencia.csv — log append-only (upsert só por
    aquisicao_id, nunca por conteúdo) de toda aquisição processada,
    aceita ou rejeitada — a série normalizada é só o PRODUTO DERIVADO
    da aquisição mais recente promovida; o snapshot é a fonte de
    reconstrução.
  - data/roni_historico.csv — série normalizada, reconstruível
    integralmente a partir do snapshot referenciado pela última
    aquisição promovida (ver `serie_ativa_corresponde_ao_snapshot()`).

Nenhum destes 3 arquivos existia antes desta fase — "a criação dos
novos arquivos RONI é autorizada nesta fase" (Seção 15). Criar o
primeiro snapshot aqui NÃO reconstrói vintages anteriores à
implementação: ele representa só a versão efetivamente observada na
data desta aquisição.
"""
import hashlib
import math
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
DATA = ROOT / 'data'
HISTORICO_PATH = DATA / 'roni_historico.csv'
PROVENIENCIA_PATH = DATA / 'roni_proveniencia.csv'
SNAPSHOTS_DIR = DATA / 'roni_snapshots'

RONI_URL = 'https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt'
VERSAO_METODOLOGICA = 'ERSSTv6'
INSTITUICAO = 'NOAA/NWS/CPC'

_HEADERS = {
    'User-Agent': 'sinobras-clima/1.0 (github-actions)',
    'Accept': 'text/plain, */*',
}

SEASONS_RONI_VALIDAS = (
    'DJF', 'JFM', 'FMA', 'MAM', 'AMJ', 'MJJ',
    'JJA', 'JAS', 'ASO', 'SON', 'OND', 'NDJ',
)
# Mês CENTRAL de cada temporada — mesma convenção de
# update_indices._MES_CENTRAL_PARA_SIGLA, indexada pela sigla.
_SEAS_PARA_MES_CENTRAL = {s: i + 1 for i, s in enumerate(SEASONS_RONI_VALIDAS)}

# Janela de revisão "recente" declarada pelo próprio CPC na página
# oficial do RONI: "RONI values may change up to two months after the
# initial 'real time' value is posted." Contada em meses a partir do
# mês CENTRAL do trimestre revisado até o mês de execução.
JANELA_REVISAO_RECENTE_MESES = 2

PROVENIENCIA_COLUNAS = [
    'aquisicao_id', 'coletado_em_utc', 'url', 'instituicao', 'versao_metodologica',
    'hash_sha256', 'representacao_hash', 'caminho_snapshot',
    'primeiro_trimestre', 'ultimo_trimestre', 'n_observacoes', 'parser',
    'resultado_validacao', 'alterou_texto', 'alterou_valores',
    'estado_promocao', 'motivo_rejeicao',
]

HISTORICO_COLUNAS = [
    'temporada', 'ano', 'mes_inicial', 'mes_central', 'mes_final',
    'valor', 'versao_metodologica', 'snapshot_sha256',
]


class SerieRejeitada(Exception):
    """Uso interno — nunca propagada para fora de `processar_aquisicao()`."""


# ══════════════════════════════════════════════════════
# AQUISIÇÃO (bytes brutos — nunca a via decode(errors='replace') do
# fetch() legado de update_indices.py, que perderia a fidelidade dos
# bytes originais para fins de hash/snapshot).
# ══════════════════════════════════════════════════════
def buscar_bytes_brutos(url=RONI_URL, timeout=20):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def calcular_hash(conteudo_bytes):
    return hashlib.sha256(conteudo_bytes).hexdigest()


# ══════════════════════════════════════════════════════
# VALIDADOR ESTRITO DA SÉRIE COMPLETA
# ══════════════════════════════════════════════════════
def validar_cabecalho(texto):
    """True só se a primeira linha não vazia for exatamente o cabeçalho
    oficial 'SEAS YR ANOM' (tolera variação de espaçamento, nunca de
    conteúdo). Texto vazio/None ou que pareça HTML (tag '<' nos
    primeiros 200 caracteres) reprova imediatamente."""
    if not texto or '<' in texto[:200]:
        return False
    for linha in texto.splitlines():
        if linha.strip():
            return linha.split() == ['SEAS', 'YR', 'ANOM']
    return False


def _mes_inicial_final(mes_central, ano_central):
    """Deriva (ano,mes) inicial e final a partir do (ano,mes) CENTRAL —
    ver convenção documentada no docstring do módulo."""
    ini = (ano_central - 1, 12) if mes_central == 1 else (ano_central, mes_central - 1)
    fim = (ano_central + 1, 1) if mes_central == 12 else (ano_central, mes_central + 1)
    return ini, fim


def parse_roni_serie_completa(texto):
    """
    Validador ESTRITO: rejeita o documento INTEIRO (devolve
    (None, [motivo])) ante qualquer inconsistência estrutural —
    cabeçalho inválido, resposta vazia/HTML/truncada, temporada ou ano
    não reconhecidos, valor não numérico/infinito/fisicamente
    implausível (|RONI|>5°C, mesmo limite físico já usado em
    `update_indices.parse_roni`/`parse_psl_anual`), duplicata com valor
    divergente, ou lacuna interna na sequência cronológica (uma lacuna
    só no FINAL da série — trimestre mais recente ainda não publicado —
    não é lacuna interna e não reprova nada, pois simplesmente não
    aparece na série).

    Retorna (lista_ordenada, avisos):
      - lista_ordenada: lista de dicts com temporada/ano/mes_inicial/
        mes_central/mes_final (strings 'AAAA-MM')/valor, ordenada
        cronologicamente — ou None se o documento foi rejeitado.
      - avisos: avisos não impeditivos (ex.: duplicata idêntica
        colapsada) quando aceita, ou a lista de motivos da rejeição
        quando lista_ordenada is None.
    """
    if not validar_cabecalho(texto):
        return None, ['cabeçalho ausente/inválido, resposta vazia ou HTML — documento inteiro rejeitado']

    linhas = [l for l in texto.splitlines() if l.strip()]
    dados = linhas[1:]
    if not dados:
        return None, ['nenhuma linha de dado após o cabeçalho — documento rejeitado']

    avisos = []
    registros = {}
    ordem_bruta = []
    for n, linha in enumerate(dados, start=2):
        partes = linha.split()
        if len(partes) != 3:
            return None, [f'linha {n}: esperado 3 campos (SEAS YR ANOM); '
                           f'encontrado {len(partes)} — documento rejeitado']
        seas, ano_s, val_s = partes
        if seas not in SEASONS_RONI_VALIDAS:
            return None, [f'linha {n}: temporada {seas!r} não reconhecida — documento rejeitado']
        try:
            ano = int(ano_s)
        except ValueError:
            return None, [f'linha {n}: ano {ano_s!r} não numérico — documento rejeitado']
        if not (1900 <= ano <= 2100):
            return None, [f'linha {n}: ano {ano} fora da faixa plausível — documento rejeitado']
        try:
            val = float(val_s)
        except ValueError:
            return None, [f'linha {n}: valor {val_s!r} não numérico — documento rejeitado']
        if not math.isfinite(val):
            return None, [f'linha {n}: valor não finito (NaN/±inf) — documento rejeitado']
        if abs(val) > 5:
            return None, [f'linha {n}: valor {val} fisicamente implausível (|RONI|>5°C) — documento rejeitado']

        chave = (ano, seas)
        if chave in registros:
            if round(registros[chave], 2) != round(val, 2):
                return None, [f'linha {n}: duplicata de {seas}/{ano} com valor divergente '
                               f'({registros[chave]} vs {val}) — documento rejeitado (ambíguo)']
            avisos.append(f'{seas}/{ano}: linha duplicada com valor idêntico — mantido um único registro')
            continue
        registros[chave] = val
        ordem_bruta.append(chave)

    def _chave_ordenacao(c):
        ano, seas = c
        return (ano, _SEAS_PARA_MES_CENTRAL[seas])

    ordenados = sorted(set(ordem_bruta), key=_chave_ordenacao)
    resultado = []
    mes_esperado, ano_esperado = None, None
    for (ano, seas) in ordenados:
        mes_central = _SEAS_PARA_MES_CENTRAL[seas]
        if mes_esperado is not None and (ano, mes_central) != (ano_esperado, mes_esperado):
            return None, [f'lacuna interna inesperada na sequência cronológica antes de '
                           f'{seas}/{ano} (esperava mês central {mes_esperado:02d}/{ano_esperado}) '
                           f'— documento rejeitado']
        (ai, mi), (af, mf) = _mes_inicial_final(mes_central, ano)
        resultado.append({
            'temporada': seas, 'ano': ano,
            'mes_inicial': f'{ai}-{mi:02d}',
            'mes_central': f'{ano}-{mes_central:02d}',
            'mes_final': f'{af}-{mf:02d}',
            'valor': registros[(ano, seas)],
        })
        mes_esperado, ano_esperado = mes_central + 1, ano
        if mes_esperado > 12:
            mes_esperado, ano_esperado = 1, ano + 1

    return resultado, avisos


def ultimo_da_lista(lista):
    """Último trimestre (cronologicamente) de uma lista já validada por
    `parse_roni_serie_completa` — lista já vem ordenada, mas não
    presume isso de quem chamar de fora deste módulo."""
    if not lista:
        return None
    r = max(lista, key=lambda d: d['mes_central'])
    return {'seas': r['temporada'], 'ano': r['ano'], 'valor': r['valor']}


# ══════════════════════════════════════════════════════
# SNAPSHOTS IMUTÁVEIS
# ══════════════════════════════════════════════════════
def caminho_snapshot(hash_sha256):
    return SNAPSHOTS_DIR / f'{hash_sha256}.txt'


def gravar_snapshot(hash_sha256, conteudo_bytes):
    """Grava o snapshot se ainda não existir; se já existir, EXIGE que
    o conteúdo seja byte-a-byte igual (nunca sobrescreve um snapshot
    existente com conteúdo diferente sob o mesmo hash — isso só
    ocorreria por colisão de SHA-256 ou bug de quem chamou). Retorna
    'criado' ou 'reaproveitado'."""
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    caminho = caminho_snapshot(hash_sha256)
    if caminho.exists():
        if caminho.read_bytes() != conteudo_bytes:
            raise SerieRejeitada(
                f'snapshot {hash_sha256} já existe com conteúdo diferente do '
                f'recebido agora — nunca sobrescrito')
        return 'reaproveitado'
    tmp = caminho.with_suffix('.txt.tmp')
    tmp.write_bytes(conteudo_bytes)
    tmp.replace(caminho)
    return 'criado'


def reconstruir_da_snapshot(hash_sha256):
    """Reaplica o validador estrito sobre o snapshot imutável
    identificado por `hash_sha256` — usado para confirmar que a série
    ativa é de fato reconstruível a partir do snapshot que a originou."""
    caminho = caminho_snapshot(hash_sha256)
    if not caminho.exists():
        return None, [f'snapshot {hash_sha256} não encontrado em {SNAPSHOTS_DIR}']
    return parse_roni_serie_completa(caminho.read_text(encoding='utf-8'))


# ══════════════════════════════════════════════════════
# SÉRIE NORMALIZADA (produto derivado do snapshot promovido)
# ══════════════════════════════════════════════════════
def _ler_serie_persistida():
    if not HISTORICO_PATH.exists():
        return None
    return pd.read_csv(HISTORICO_PATH, dtype={'temporada': str})


def _serie_para_dataframe(lista):
    return pd.DataFrame(lista, columns=HISTORICO_COLUNAS)


def _gravar_serie_historico(lista):
    """Substituição atômica (escreve em arquivo temporário no mesmo
    diretório e troca com `Path.replace`, que é `os.rename` — atômico
    no mesmo filesystem) — nunca deixa `roni_historico.csv` num estado
    parcialmente escrito."""
    df = _serie_para_dataframe(lista)
    HISTORICO_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = HISTORICO_PATH.with_suffix('.csv.tmp')
    df.to_csv(tmp, index=False)
    tmp.replace(HISTORICO_PATH)


def ultimo_da_serie_ativa():
    """Último trimestre da série ATIVA (persistida) — é este valor,
    nunca um recém-buscado e ainda não promovido, que deve alimentar o
    card RONI do dashboard."""
    df = _ler_serie_persistida()
    if df is None or df.empty:
        return None
    r = df.sort_values('mes_central').iloc[-1]
    return {'seas': r['temporada'], 'ano': int(r['ano']), 'valor': float(r['valor'])}


def serie_ativa_corresponde_ao_snapshot():
    """True se `data/roni_historico.csv` for idêntico ao que
    `reconstruir_da_snapshot()` produz a partir do snapshot da última
    aquisição PROMOVIDA registrada no manifesto. Garante que a série
    normalizada nunca é um produto que só existe 'no papel', divorciado
    do snapshot que a gerou."""
    df_ativa = _ler_serie_persistida()
    if df_ativa is None or df_ativa.empty:
        return True, []
    prov, avisos_leitura = ler_proveniencia_seguro()
    # 'reaproveitada_sem_mudanca' também ancora a reconstrução: confirma
    # que o mesmo snapshot/hash continua correspondendo à série ativa,
    # mesmo quando essa observação específica não precisou regravar o
    # arquivo (nada mudou). Só rejeições nunca contam como âncora.
    validas = prov[prov['estado_promocao'].isin(['promovida', 'reaproveitada_sem_mudanca'])] \
        if not prov.empty else prov
    if validas.empty:
        return False, avisos_leitura + ['série ativa existe mas nenhuma aquisição promovida/'
                                         'reaproveitada está registrada no manifesto']
    ultima = validas.sort_values('coletado_em_utc').iloc[-1]
    lista, avisos = reconstruir_da_snapshot(ultima['hash_sha256'])
    if lista is None:
        return False, avisos_leitura + [f'snapshot da última promoção não reconstrói: {avisos}']
    for d in lista:
        d['versao_metodologica'] = VERSAO_METODOLOGICA
        d['snapshot_sha256'] = ultima['hash_sha256']
    reconstruida = _serie_para_dataframe(lista).reset_index(drop=True)
    ativa_comp = df_ativa[HISTORICO_COLUNAS].reset_index(drop=True)
    iguais = ativa_comp.equals(reconstruida)
    return iguais, avisos_leitura if iguais else avisos_leitura + [
        'série ativa difere da reconstrução a partir do snapshot da última promoção']


# ══════════════════════════════════════════════════════
# PROVENIÊNCIA (log append-only, upsert só por aquisicao_id)
# ══════════════════════════════════════════════════════
def ler_proveniencia_seguro():
    """Lê `roni_proveniencia.csv` tolerando uma linha final truncada
    (interrupção durante a gravação anterior) — nunca lança; relata a
    inconsistência em vez de propagar a exceção do parser."""
    if not PROVENIENCIA_PATH.exists():
        return pd.DataFrame(columns=PROVENIENCIA_COLUNAS), []
    try:
        return pd.read_csv(PROVENIENCIA_PATH), []
    except Exception:
        df = pd.read_csv(PROVENIENCIA_PATH, engine='python', on_bad_lines='skip')
        return df, ['roni_proveniencia.csv continha linha(s) malformada(s) (possível '
                    'interrupção durante gravação anterior) — descartada(s) na leitura']


def _registrar_proveniencia(aquisicao_id, url, hash_sha256, primeiro, ultimo,
                             n_observacoes, estado_promocao, motivo_rejeicao,
                             alterou_texto, alterou_valores):
    """Upsert por `aquisicao_id` (nunca por conteúdo) — reprocessar a
    MESMA aquisição (mesmo id) substitui sua própria linha; uma nova
    coleta real sempre recebe um novo id (timestamp), nunca
    sobrescrevendo o histórico de observações anteriores."""
    linha = {
        'aquisicao_id': aquisicao_id,
        'coletado_em_utc': datetime.now(timezone.utc).isoformat(),
        'url': url,
        'instituicao': INSTITUICAO,
        'versao_metodologica': VERSAO_METODOLOGICA,
        'hash_sha256': hash_sha256 or '',
        'representacao_hash': 'bytes_brutos_utf8',
        'caminho_snapshot': str(caminho_snapshot(hash_sha256).relative_to(ROOT)) if hash_sha256 else '',
        'primeiro_trimestre': f"{primeiro['temporada']}/{primeiro['ano']}" if primeiro else '',
        'ultimo_trimestre': f"{ultimo['temporada']}/{ultimo['ano']}" if ultimo else '',
        'n_observacoes': n_observacoes if n_observacoes is not None else '',
        'parser': 'roni_historico.parse_roni_serie_completa',
        'resultado_validacao': 'aceita' if estado_promocao in
            ('promovida', 'reaproveitada_sem_mudanca') else 'rejeitada',
        'alterou_texto': alterou_texto,
        'alterou_valores': alterou_valores,
        'estado_promocao': estado_promocao,
        'motivo_rejeicao': motivo_rejeicao or '',
    }
    df_existente, _ = ler_proveniencia_seguro()
    if not df_existente.empty:
        df_existente = df_existente[df_existente['aquisicao_id'] != aquisicao_id]
    novo = pd.concat([df_existente, pd.DataFrame([linha], columns=PROVENIENCIA_COLUNAS)],
                      ignore_index=True)
    PROVENIENCIA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROVENIENCIA_PATH.with_suffix('.csv.tmp')
    novo.to_csv(tmp, index=False)
    tmp.replace(PROVENIENCIA_PATH)


# ══════════════════════════════════════════════════════
# POLÍTICA DE REVISÕES
# ══════════════════════════════════════════════════════
def comparar_series(antiga_df, nova_lista):
    """Compara a série ATIVA (antiga_df, pode ser None/vazia na
    primeira aquisição) com a nova série candidata (já validada por
    `parse_roni_serie_completa`). Só descreve a diferença — nunca
    decide promoção aqui."""
    nova_idx = {(d['ano'], d['temporada']): d['valor'] for d in nova_lista}
    if antiga_df is None or antiga_df.empty:
        return {'trimestres_novos': sorted(nova_idx.keys()),
                'trimestres_removidos': [], 'valores_revisados': [],
                'cobertura_reduzida': False}
    antiga_idx = {(int(r.ano), r.temporada): r.valor for r in antiga_df.itertuples()}
    novos = sorted(set(nova_idx) - set(antiga_idx))
    removidos = sorted(set(antiga_idx) - set(nova_idx))
    revisados = [(k, antiga_idx[k], nova_idx[k])
                 for k in sorted(set(antiga_idx) & set(nova_idx))
                 if round(antiga_idx[k], 2) != round(nova_idx[k], 2)]
    return {'trimestres_novos': novos, 'trimestres_removidos': removidos,
            'valores_revisados': revisados, 'cobertura_reduzida': bool(removidos)}


def decidir_promocao(comparacao, hoje):
    """
    Política de revisões (Seção 10):
      - Cobertura reduzida (qualquer trimestre da série ativa ausente
        na nova aquisição) → rejeitada, nunca promovida.
      - Valor revisado FORA da janela de 2 meses que o próprio CPC
        declara (ver JANELA_REVISAO_RECENTE_MESES) → "revisão histórica
        inesperada": NÃO promovida automaticamente, mas também não
        tratada como erro científico definitivo — sinalizada para
        avaliação (a evidência já foi preservada em snapshot antes
        desta função ser chamada).
      - Valor revisado DENTRO da janela de 2 meses → aceito como
        revisão legítima.
      - Nada mudou → 'reaproveitada_sem_mudanca' (idempotente).
      - Caso contrário (trimestre novo e/ou revisão recente legítima,
        sem cobertura reduzida nem revisão inesperada) → 'promovida'.
    """
    if comparacao['cobertura_reduzida']:
        return ('rejeitada_cobertura_reduzida',
                f"trimestre(s) ausentes na nova aquisição: {comparacao['trimestres_removidos']}")

    inesperadas = []
    for (ano, seas), antigo, novo in comparacao['valores_revisados']:
        mes_central = _SEAS_PARA_MES_CENTRAL[seas]
        meses_decorridos = (hoje.year - ano) * 12 + (hoje.month - mes_central)
        if meses_decorridos > JANELA_REVISAO_RECENTE_MESES:
            inesperadas.append((seas, ano, antigo, novo, meses_decorridos))
    if inesperadas:
        detalhe = '; '.join(f'{s}/{a}: {ant}->{nov} ({m} meses atrás)'
                             for s, a, ant, nov, m in inesperadas)
        return 'rejeitada_revisao_historica_inesperada', f'revisão fora da janela de 2 meses: {detalhe}'

    if not comparacao['trimestres_novos'] and not comparacao['valores_revisados']:
        return 'reaproveitada_sem_mudanca', None

    return 'promovida', None


# ══════════════════════════════════════════════════════
# PONTO DE ENTRADA ÚNICO
# ══════════════════════════════════════════════════════
def processar_aquisicao(url=RONI_URL, hoje=None, aquisicao_id=None, conteudo_bytes=None):
    """
    Busca a fonte (ou usa `conteudo_bytes` já obtido, para testes/
    reaproveitamento — nunca consulta a fonte de novo só para gerar o
    hash), valida estritamente, compara com a série ativa, decide
    promoção, grava snapshot/manifesto/série quando aplicável, e
    devolve o trimestre mais recente da série EFETIVAMENTE ativa após
    esta execução — o mesmo valor que deve alimentar `const RONI`.

    Nunca lança para o chamador em falha de rede ou de estrutura —
    qualquer problema é reportado no dict de retorno; o card, nesse
    caso, recebe o último valor válido já persistido (nunca None só
    porque esta aquisição falhou, e nunca um valor rejeitado pelo
    mecanismo histórico).

    Retorna {'ultimo': {...} ou None, 'estado_promocao': str,
             'avisos': [...], 'aquisicao_id': str}.
    """
    hoje = hoje or datetime.now(timezone.utc).date()
    aquisicao_id = aquisicao_id or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')

    if conteudo_bytes is None:
        try:
            conteudo_bytes = buscar_bytes_brutos(url)
        except Exception as e:
            return {'ultimo': ultimo_da_serie_ativa(), 'estado_promocao': 'rejeitada_falha_coleta',
                    'avisos': [f'falha ao buscar {url}: {e}'], 'aquisicao_id': aquisicao_id}

    try:
        texto = conteudo_bytes.decode('utf-8')
    except UnicodeDecodeError:
        _registrar_proveniencia(aquisicao_id, url, calcular_hash(conteudo_bytes), None, None,
                                 None, 'rejeitada_estrutural', 'conteúdo não é UTF-8 válido',
                                 alterou_texto=None, alterou_valores=None)
        return {'ultimo': ultimo_da_serie_ativa(), 'estado_promocao': 'rejeitada_estrutural',
                'avisos': ['conteúdo não é UTF-8 válido — documento rejeitado'],
                'aquisicao_id': aquisicao_id}

    lista, avisos = parse_roni_serie_completa(texto)
    hash_sha256 = calcular_hash(conteudo_bytes)

    if lista is None:
        _registrar_proveniencia(aquisicao_id, url, hash_sha256, None, None, None,
                                 'rejeitada_estrutural', '; '.join(avisos),
                                 alterou_texto=None, alterou_valores=None)
        return {'ultimo': ultimo_da_serie_ativa(), 'estado_promocao': 'rejeitada_estrutural',
                'avisos': avisos, 'aquisicao_id': aquisicao_id}

    antiga_df = _ler_serie_persistida()
    comparacao = comparar_series(antiga_df, lista)
    estado, motivo = decidir_promocao(comparacao, hoje)

    # Snapshot sempre gravado/reaproveitado — preserva a evidência
    # recebida de forma identificável mesmo em rejeição (Seção 10),
    # nunca só quando promovida. `SerieRejeitada` aqui é uma condição
    # ESPERADA deste módulo (colisão de hash/snapshot corrompido no
    # disco) — nunca deixada escapar como exceção não tratada; vira
    # mais um estado de rejeição reportado, nunca interrompe
    # `update_indices.py`.
    try:
        status_snapshot = gravar_snapshot(hash_sha256, conteudo_bytes)
    except SerieRejeitada as e:
        _registrar_proveniencia(aquisicao_id, url, hash_sha256, lista[0], lista[-1], len(lista),
                                 'rejeitada_snapshot_corrompido', str(e),
                                 alterou_texto=None, alterou_valores=None)
        return {'ultimo': ultimo_da_serie_ativa(), 'estado_promocao': 'rejeitada_snapshot_corrompido',
                'avisos': avisos + [str(e)], 'aquisicao_id': aquisicao_id}
    alterou_texto = (status_snapshot == 'criado')
    alterou_valores = bool(comparacao['valores_revisados']) or bool(comparacao['trimestres_novos'])

    for d in lista:
        d['versao_metodologica'] = VERSAO_METODOLOGICA
        d['snapshot_sha256'] = hash_sha256

    if estado == 'promovida':
        _gravar_serie_historico(lista)

    _registrar_proveniencia(aquisicao_id, url, hash_sha256, lista[0], lista[-1], len(lista),
                             estado, motivo, alterou_texto, alterou_valores)

    return {'ultimo': ultimo_da_serie_ativa(), 'estado_promocao': estado,
            'avisos': avisos, 'aquisicao_id': aquisicao_id}
