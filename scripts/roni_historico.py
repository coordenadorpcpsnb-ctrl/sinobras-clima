#!/usr/bin/env python3
"""
roni_historico.py — série histórica oficial do RONI (Relative Oceanic
Niño Index), snapshots imutáveis e proveniência.

Fases ENSO-RONI-MIGRAÇÃO 2/2.1/2.2. Contexto e decisões (ver
docs/ENSO_RONI_MIGRACAO_FASE2.md e os relatórios das fases anteriores):

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
lacuna interna, QUALQUER duplicidade — idêntica ou divergente — valor
não numérico/infinito/implausível) — nunca aceita parcialmente uma série
corrompida, e nunca escolhe arbitrariamente entre linhas duplicadas.

Convenção de ano/trimestre (confirmada ao vivo, pelo alinhamento dos
picos históricos de El Niño/La Niña na própria série — o arquivo não
documenta a convenção explicitamente): a coluna YR do RONI.ascii.txt é
o ano do MÊS CENTRAL do trimestre, nunca do mês inicial nem final.
DJF/AAAA = dez(AAAA-1)-jan(AAAA)-fev(AAAA); NDJ/AAAA =
nov(AAAA)-dez(AAAA)-jan(AAAA+1). Ver `_mes_inicial_final()`.

Arquitetura de persistência (decisão aprovada na Fase 2 — REJEITA
explicitamente a alternativa de manter só uma série normalizada com
manifesto de hashes, "porque hashes identificam conteúdos, mas não
permitem recuperar conteúdos descartados"):
  - data/roni_snapshots/<sha256>.txt — snapshot IMUTÁVEL do conteúdo
    bruto de cada aquisição distinta já observada. Nunca sobrescrito;
    um novo snapshot só é criado se o hash ainda não existir.
  - data/roni_proveniencia.csv — registro de aquisições CONCLUÍDAS,
    tratado como evidência histórica imutável (Fase 2.2): reprocessar
    a MESMA aquisição (mesmo aquisicao_id) nunca altera o registro
    original (timestamp, resultado, estado) — é um no-op idempotente.
    O mesmo id associado a fatos incompatíveis (hash/URL/estado
    diferentes) é um CONFLITO explícito, nunca uma sobrescrita
    silenciosa. Uma nova coleta real sempre recebe um novo id.
  - data/roni_historico.csv — série normalizada, reconstruível
    integralmente a partir do ÚNICO snapshot que a própria série
    referencia em sua coluna `snapshot_sha256` (ver
    `serie_ativa_corresponde_ao_snapshot()`) — nunca inferido por
    "qual é a linha mais recente do manifesto", para não confundir uma
    observação textual sem mudança de valor com uma promoção real
    (Fase 2.2, Correção 2).

Nenhum destes 3 arquivos existia antes da Fase 2. Criar o primeiro
snapshot NÃO reconstrói vintages anteriores à implementação: ele
representa só a versão efetivamente observada na data da aquisição.
"""
import hashlib
import math
import re
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
# initial 'real time' value is posted." — contada a partir da data de
# PUBLICAÇÃO INICIAL do trimestre (ver `_referencia_disponibilidade`),
# nunca do mês central (achado da Fase 2.2, Correção 1: mês central,
# mês final, publicação inicial e primeira observação pelo sistema são
# eventos distintos).
JANELA_REVISAO_RECENTE_MESES = 2

_HASH_RE = re.compile(r'^[0-9a-f]{64}$')

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

# Estados que representam uma aquisição ACEITA (nunca uma rejeição) —
# usados tanto para `resultado_validacao` quanto para localizar, no
# manifesto, aquisições cuja evidência (snapshot) deve estar íntegra.
_ESTADOS_ACEITOS = ('promovida', 'reaproveitada_sem_mudanca',
                    'observada_texto_diferente_valor_identico')

# Todo `estado_promocao` que o módulo é capaz de produzir — usado só
# para detectar um valor NÃO reconhecido no manifesto (Seção 7), nunca
# para inferir comportamento a partir dele.
_ESTADOS_RECONHECIDOS = _ESTADOS_ACEITOS + (
    'rejeitada_base_corrompida', 'rejeitada_cobertura_reduzida',
    'rejeitada_conflito_aquisicao', 'rejeitada_estado_existente_inconsistente',
    'rejeitada_estrutural', 'rejeitada_falha_coleta',
    'rejeitada_inconsistencia_pos_escrita', 'rejeitada_manifesto_perdido',
    'rejeitada_manifesto_problema', 'rejeitada_revisao_historica_inesperada',
    'rejeitada_serie_ausente_com_manifesto_integro', 'rejeitada_snapshot_corrompido',
)

_CAMPOS_OBRIGATORIOS_PROVENIENCIA = ('aquisicao_id', 'coletado_em_utc', 'url', 'estado_promocao')


class SerieRejeitada(Exception):
    """Uso interno — nunca propagada para fora de `processar_aquisicao()`."""


class BaseCorrompida(Exception):
    """Levantada quando um artefato EXISTE mas não pôde ser lido/
    interpretado — nunca confundida com "ainda não existe" (tratar os
    dois casos como a mesma coisa permitiria reinicializar
    silenciosamente sobre uma base corrompida, descartando evidência de
    que havia algo ali antes). Convertida por `processar_aquisicao()`
    num estado de rejeição explícito — nunca propagada ao chamador
    externo, e nunca tratada como "nada a comparar, segue em frente"."""


class ConflitoDeAquisicao(Exception):
    """Levantada quando o mesmo `aquisicao_id` é reenviado com hash,
    URL ou estado de promoção incompatível com o registro já existente
    no manifesto (Fase 2.2, Correção 5) — nunca silenciosamente
    sobrescrito. Reprocessar a MESMA aquisição com os MESMOS fatos é um
    no-op idempotente, não um conflito."""


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


def _hash_valido(h):
    return isinstance(h, str) and bool(_HASH_RE.match(h))


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
    implausível (|RONI|>5°C), QUALQUER duplicidade da chave ano/
    temporada — valor idêntico, divergente, ou coincidente só após
    arredondamento (Fase 2.2, Correção 4: nenhuma duplicidade é
    tolerada na série oficial; o documento candidato inteiro é
    rejeitado, nunca se escolhe arbitrariamente uma das linhas) — ou
    lacuna interna na sequência cronológica (uma lacuna só no FINAL da
    série — trimestre mais recente ainda não publicado — não é lacuna
    interna e não reprova nada, pois simplesmente não aparece na
    série).

    Esta função valida só a CONSISTÊNCIA ESTRUTURAL do documento
    recebido — nunca a cobertura em relação a uma série ativa ou a uma
    data de início "oficial" hardcoded (isso seria inadequado tanto
    para séries sintéticas de teste quanto para a fonte real, cujo
    início poderia um dia ser estendido). A política de "não aceitar
    cobertura reduzida em relação ao que já está ativo" é
    responsabilidade de `comparar_series`/`decidir_promocao`, que
    comparam contra o estado já persistido — nunca deste validador.

    Retorna (lista_ordenada, avisos):
      - lista_ordenada: lista de dicts com temporada/ano/mes_inicial/
        mes_central/mes_final (strings 'AAAA-MM')/valor, ordenada
        cronologicamente — ou None se o documento foi rejeitado.
      - avisos: avisos não impeditivos quando aceita, ou a lista de
        motivos da rejeição quando lista_ordenada is None.
    """
    if not validar_cabecalho(texto):
        return None, ['cabeçalho ausente/inválido, resposta vazia ou HTML — documento inteiro rejeitado']

    linhas = [l for l in texto.splitlines() if l.strip()]
    dados = linhas[1:]
    if not dados:
        return None, ['nenhuma linha de dado após o cabeçalho — documento rejeitado']

    registros = {}
    ordem = []
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
            return None, [f'linha {n}: {seas}/{ano} duplicado (valor anterior '
                           f'{registros[chave]}, agora {val}) — qualquer duplicidade reprova o '
                           f'documento inteiro, mesmo com valores idênticos ou coincidentes só '
                           f'após arredondamento — nunca se escolhe uma das linhas']
        registros[chave] = val
        ordem.append(chave)

    def _chave_ordenacao(c):
        ano, seas = c
        return (ano, _SEAS_PARA_MES_CENTRAL[seas])

    ordenados = sorted(ordem, key=_chave_ordenacao)
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

    return resultado, []


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
    ativa é de fato reconstruível a partir do snapshot que a originou.

    Fase 2.2, Correção 3: antes de usar o conteúdo, RECALCULA o SHA-256
    dos bytes efetivamente lidos e confirma que corresponde ao
    `hash_sha256` pedido (nome do arquivo) — nunca confia no nome do
    arquivo por si só. Um snapshot cujo conteúdo foi adulterado
    (inclusive adulteração só de espaços/quebras de linha, que não
    mudaria os valores climáticos mas MUDA o hash) é detectado aqui,
    mesmo que ainda resulte numa série estruturalmente válida."""
    caminho = caminho_snapshot(hash_sha256)
    if not caminho.exists():
        return None, [f'snapshot {hash_sha256} não encontrado em {SNAPSHOTS_DIR}']
    conteudo_bytes = caminho.read_bytes()
    hash_real = calcular_hash(conteudo_bytes)
    if hash_real != hash_sha256:
        return None, [f'snapshot em {caminho} está CORROMPIDO: hash do conteúdo atual '
                       f'({hash_real}) não corresponde ao nome do arquivo ({hash_sha256}) — '
                       f'nunca utilizado para reconstrução']
    try:
        texto = conteudo_bytes.decode('utf-8')
    except UnicodeDecodeError:
        return None, [f'snapshot {hash_sha256} não é UTF-8 válido']
    return parse_roni_serie_completa(texto)


# ══════════════════════════════════════════════════════
# SÉRIE NORMALIZADA (produto derivado do snapshot promovido)
# ══════════════════════════════════════════════════════
def _ler_serie_persistida():
    """`None` = legitimamente ainda não existe (primeira aquisição).
    Lança `BaseCorrompida` se o arquivo EXISTE mas não pôde ser lido —
    nunca devolve `None` nesse caso."""
    if not HISTORICO_PATH.exists():
        return None
    try:
        return pd.read_csv(HISTORICO_PATH, dtype={'temporada': str})
    except Exception as e:
        raise BaseCorrompida(f'{HISTORICO_PATH} existe mas não pôde ser lido: {e}')


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
    card RONI do dashboard. Base corrompida devolve `None` aqui (não há
    valor confiável a entregar)."""
    try:
        df = _ler_serie_persistida()
    except BaseCorrompida:
        return None
    if df is None or df.empty:
        return None
    r = df.sort_values('mes_central').iloc[-1]
    return {'seas': r['temporada'], 'ano': int(r['ano']), 'valor': float(r['valor'])}


def serie_ativa_corresponde_ao_snapshot():
    """True se `data/roni_historico.csv` for idêntico ao que
    `reconstruir_da_snapshot()` produz a partir do ÚNICO snapshot que a
    PRÓPRIA série referencia em sua coluna `snapshot_sha256` (Fase 2.2,
    Correção 2: a âncora de reconstrução é lida diretamente da série,
    nunca inferida escaneando "qual é a linha mais recente aceita no
    manifesto" — essa inferência confundia uma observação textual sem
    mudança de valor, que nunca reescreve a série, com uma promoção
    real). Garante que a série normalizada nunca é um produto que só
    existe 'no papel', divorciado do snapshot que a gerou — e, como
    `reconstruir_da_snapshot` agora recalcula o hash (Correção 3),
    também detecta adulteração do próprio snapshot ativo."""
    try:
        df_ativa = _ler_serie_persistida()
    except BaseCorrompida as e:
        return False, [str(e)]
    if df_ativa is None or df_ativa.empty:
        return True, []

    hashes_ativos = df_ativa['snapshot_sha256'].unique()
    if len(hashes_ativos) != 1:
        return False, [f'série ativa referencia {len(hashes_ativos)} snapshot(s) distintos — '
                        f'esperado exatamente 1 (toda a série deve derivar do mesmo snapshot)']
    hash_ativo = hashes_ativos[0]
    if not _hash_valido(hash_ativo):
        return False, [f'hash referenciado pela série ativa tem formato inválido: {hash_ativo!r}']

    lista, avisos = reconstruir_da_snapshot(hash_ativo)
    if lista is None:
        return False, [f'snapshot ativo ({hash_ativo}) referenciado pela série não pôde ser '
                        f'reconstruído: {avisos}']
    for d in lista:
        d['versao_metodologica'] = VERSAO_METODOLOGICA
        d['snapshot_sha256'] = hash_ativo
    reconstruida = _serie_para_dataframe(lista).reset_index(drop=True)
    ativa_comp = df_ativa[HISTORICO_COLUNAS].reset_index(drop=True)
    iguais = ativa_comp.equals(reconstruida)
    return iguais, [] if iguais else ['série ativa difere da reconstrução a partir do seu '
                                       'próprio snapshot referenciado']


def reconstruir_serie_a_partir_do_manifesto():
    """
    Recuperação do Cenário B (Fase 2.2, Seção 8.3): `data/roni_historico.csv`
    está AUSENTE ou corrompido, mas o manifesto e o snapshot referenciado
    pela última promoção estão íntegros — a série pode ser reconstruída
    DETERMINISTICAMENTE a partir dessas evidências preservadas, sem
    inventar nada.

    Não é chamada automaticamente por `processar_aquisicao()` — é uma
    operação de recuperação explícita (ex.: workflow operacional ou
    operador, antes de retomar a atualização normal). Localiza a última
    aquisição com `estado_promocao == 'promovida'` no manifesto (o
    único evento que de fato reescreve a série — uma observação textual
    sem mudança de valor nunca conta), confirma a integridade do hash
    (via `reconstruir_da_snapshot`, que recalcula o SHA-256) e só então
    grava `data/roni_historico.csv`.

    Nunca usada para os Cenários C/D (manifesto ou snapshot ativo
    ausentes/corrompidos) — nesses casos não há evidência suficiente
    para uma recuperação inequívoca, e esta função falha explicitamente
    (retorna `ok=False`) em vez de inventar qualquer coisa.

    Retorna (ok: bool, mensagens: [str]).
    """
    prov, avisos_leitura = ler_proveniencia_seguro()
    if avisos_leitura:
        return False, avisos_leitura + ['manifesto corrompido — recuperação não é segura']
    if prov.empty:
        return False, ['manifesto ausente ou vazio — impossível reconstruir sem inventar dados']
    ultima = _ultima_promocao_valida(prov)
    if ultima is None:
        return False, ['nenhuma promoção registrada no manifesto — impossível reconstruir']
    h = ultima['hash_sha256']
    if not _hash_valido(h):
        return False, [f'hash registrado para a última promoção é inválido: {h!r}']
    lista, avisos_parse = reconstruir_da_snapshot(h)
    if lista is None:
        return False, avisos_parse + ['snapshot da última promoção não pôde ser reconstruído — '
                                       'recuperação não é segura']
    for d in lista:
        d['versao_metodologica'] = VERSAO_METODOLOGICA
        d['snapshot_sha256'] = h
    _gravar_serie_historico(lista)
    return True, [f'série reconstruída a partir do snapshot {h} '
                  f'(última promoção: {ultima["aquisicao_id"]})']


# ══════════════════════════════════════════════════════
# PROVENIÊNCIA — evidência histórica imutável
# ══════════════════════════════════════════════════════
def _validar_estrutura_manifesto(prov):
    """
    Validação ESTRUTURAL mínima do manifesto (Fase 2.2A, Seção 7) —
    "lido sem lançar exceção" nunca é interpretado como "íntegro".
    Confirma: colunas obrigatórias presentes; `aquisicao_id` único
    (duplicata é rejeitada MESMO quando os registros são idênticos —
    nunca escolhe arbitrariamente a primeira ou a última linha; isso só
    pode ter sido produzido por edição externa, já que o fluxo normal
    de `_registrar_proveniencia` trata id repetido como no-op/conflito
    ANTES de escrever); nenhum campo obrigatório ausente/vazio;
    `estado_promocao` reconhecido.

    Retorna lista de problemas (vazia == estrutura válida). Não
    reverifica hash/caminho de snapshot aqui — isso é
    `verificar_integridade_roni()`, para não duplicar essa lógica.
    """
    if prov is None or prov.empty:
        return []

    faltantes = [c for c in PROVENIENCIA_COLUNAS if c not in prov.columns]
    if faltantes:
        return [f'manifesto sem a(s) coluna(s) obrigatória(s): {faltantes}']

    problemas = []
    duplicados = sorted(prov['aquisicao_id'][prov['aquisicao_id'].duplicated()].unique().tolist())
    if duplicados:
        problemas.append(f'aquisicao_id duplicado no manifesto (mesmo id em mais de uma linha, '
                          f'rejeitado mesmo se os registros forem idênticos): {duplicados}')

    for campo in _CAMPOS_OBRIGATORIOS_PROVENIENCIA:
        vazios = prov[prov[campo].isna() | (prov[campo].astype(str).str.strip() == '')]
        if not vazios.empty:
            problemas.append(f"campo obrigatório {campo!r} ausente/vazio em {len(vazios)} "
                              f"linha(s) do manifesto")

    desconhecidos = sorted(set(prov['estado_promocao'].astype(str).unique())
                            - set(_ESTADOS_RECONHECIDOS))
    if desconhecidos:
        problemas.append(f'estado_promocao não reconhecido no manifesto: {desconhecidos}')

    return problemas


def ler_proveniencia_seguro():
    """Lê `roni_proveniencia.csv`. Retorna (df, avisos) — `avisos`
    NUNCA vazio quando alguma linha teve que ser descartada por
    corrupção estrutural OU quando a estrutura do manifesto falha a
    validação mínima da Seção 7 (nunca silenciosamente ignorado pelo
    chamador: tanto `_registrar_proveniencia` quanto
    `verificar_integridade_roni` tratam `avisos` não-vazio como falha
    explícita, nunca como mero aviso informativo — Fase 2.2, Correção
    5: "não descartar silenciosamente linhas malformadas")."""
    if not PROVENIENCIA_PATH.exists():
        return pd.DataFrame(columns=PROVENIENCIA_COLUNAS), []
    try:
        df = pd.read_csv(PROVENIENCIA_PATH)
        avisos = []
    except Exception:
        df = pd.read_csv(PROVENIENCIA_PATH, engine='python', on_bad_lines='skip')
        avisos = ['roni_proveniencia.csv continha linha(s) malformada(s) (possível '
                  'interrupção durante gravação anterior) — descartada(s) apenas nesta '
                  'leitura diagnóstica, NUNCA reescritas no arquivo']
    return df, avisos + _validar_estrutura_manifesto(df)


def _ultima_promocao_valida(prov):
    """Fonte de verdade ÚNICA para "qual é a versão ativa, segundo o
    manifesto" (Fase 2.2A, Seção 5) — reutilizada por
    `verificar_integridade_roni()`, `processar_aquisicao()` e
    `reconstruir_serie_a_partir_do_manifesto()`, para nunca ter 3
    implementações independentes da mesma regra. Ordem inequívoca e
    documentada: entre as linhas com `estado_promocao == 'promovida'`
    (o único evento que de fato reescreve `roni_historico.csv` — uma
    observação textual sem mudança de valor ou uma aquisição rejeitada
    NUNCA contam, mesmo que aceitas), a mais recente por
    `coletado_em_utc`. Retorna a linha (Series do pandas) ou `None` se
    não houver nenhuma promoção."""
    if prov is None or prov.empty:
        return None
    promovidas = prov[prov['estado_promocao'] == 'promovida']
    if promovidas.empty:
        return None
    return promovidas.sort_values('coletado_em_utc').iloc[-1]


def _registrar_proveniencia(aquisicao_id, coletado_em_utc, url, hash_sha256, primeiro, ultimo,
                             n_observacoes, estado_promocao, motivo_rejeicao,
                             alterou_texto, alterou_valores):
    """
    Trata aquisições concluídas como evidência histórica IMUTÁVEL
    (Fase 2.2, Correção 5):
      - `aquisicao_id` novo → insere (append).
      - `aquisicao_id` já existente, com os MESMOS fatos de identidade
        (url/hash/estado_promocao/resultado_validacao) → reprocessamento
        idempotente: NO-OP — o registro original, inclusive seu
        `coletado_em_utc` ORIGINAL, permanece exatamente como está.
      - `aquisicao_id` já existente, com fatos DIFERENTES → conflito
        explícito (`ConflitoDeAquisicao`) — nunca sobrescrito.

    `coletado_em_utc` é recebido como parâmetro (capturado por
    `processar_aquisicao` no início da execução, próximo do momento em
    que a resposta foi obtida) — esta função nunca gera seu próprio
    timestamp "no instante da persistência", que seria um substituto
    silencioso da data real da coleta.

    Nunca lê com `on_bad_lines='skip'` para decidir se pode escrever:
    se `ler_proveniencia_seguro()` sinalizar corrupção, esta função
    recusa a escrita (levanta `BaseCorrompida`) em vez de reescrever o
    arquivo descartando as linhas malformadas.
    """
    df_existente, avisos_leitura = ler_proveniencia_seguro()
    if avisos_leitura:
        raise BaseCorrompida(
            f'{PROVENIENCIA_PATH} contém linha(s) malformada(s) — recusando registrar nova '
            f'aquisição para não reescrever o manifesto descartando evidência: {avisos_leitura}')

    linha_nova = {
        'aquisicao_id': aquisicao_id,
        'coletado_em_utc': coletado_em_utc,
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
        'resultado_validacao': 'aceita' if estado_promocao in _ESTADOS_ACEITOS else 'rejeitada',
        'alterou_texto': alterou_texto,
        'alterou_valores': alterou_valores,
        'estado_promocao': estado_promocao,
        'motivo_rejeicao': motivo_rejeicao or '',
    }

    if not df_existente.empty:
        ja_existe = df_existente[df_existente['aquisicao_id'] == aquisicao_id]
        if not ja_existe.empty:
            existente = ja_existe.iloc[0]
            campos_identidade = ('url', 'hash_sha256', 'estado_promocao', 'resultado_validacao')
            conflito = [c for c in campos_identidade if str(existente[c]) != str(linha_nova[c])]
            if conflito:
                raise ConflitoDeAquisicao(
                    f'aquisicao_id {aquisicao_id!r} já registrado com dados incompatíveis em '
                    f'{conflito} — registro original preservado, nunca sobrescrito')
            # Reprocessamento idempotente: registro original intacto.
            return

    novo = pd.concat([df_existente, pd.DataFrame([linha_nova], columns=PROVENIENCIA_COLUNAS)],
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
    decide promoção aqui. `trimestres_removidos`/`cobertura_reduzida`
    não vazios são exatamente o mecanismo que impede uma aquisição
    revisora de "encolher" silenciosamente o início ou qualquer parte
    já coberta da série ativa (Fase 2.2, Correção 4) — aplica-se a
    QUALQUER aquisição após a primeira; a primeira aquisição em si não
    tem base de comparação."""
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


def _mes_publicacao_estimada(mes_final_str):
    """Estimativa do mês em que o CPC provavelmente publicou o
    trimestre pela primeira vez: mês FINAL do trimestre + 1 mês (a
    média de 3 meses só pode ser calculada depois que o último mês
    termina), coerente com a atualização "by the 5th of each month" já
    confirmada na página oficial do RONI
    (https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/).
    Rotulada explicitamente como ESTIMATIVA pelo chamador — o arquivo
    RONI.ascii.txt não documenta datas de publicação reais."""
    ano_f, mes_f = (int(x) for x in mes_final_str.split('-'))
    mes_f += 1
    ano_pub = ano_f
    if mes_f > 12:
        mes_f, ano_pub = 1, ano_f + 1
    return ano_pub, mes_f


def _referencia_disponibilidade(ano, seas, mes_final_str, datas_publicacao_informadas=None):
    """
    Política determinística de 2 níveis (Fase 2.2, Correção 1 —
    Seção 4.3):
      1. Data de publicação inicial EFETIVAMENTE conhecida, passada
         explicitamente via `datas_publicacao_informadas` (dict
         {(ano,seas): (ano_pub,mes_pub)}) — nunca inventada por esta
         função; só usada quando o chamador já a comprovou por algum
         meio externo (ex.: metadado real do CPC, quando existir).
      2. Na ausência de (1): estimativa pelo calendário de publicação
         do CPC (mês final + 1), coerente e documentada como tal.

    Devolve (ano, mes, origem) onde `origem` é 'informada' ou
    'estimada' — nunca omitido, para que o chamador possa reportar a
    procedência de cada decisão."""
    if datas_publicacao_informadas:
        info = datas_publicacao_informadas.get((ano, seas))
        if info is not None:
            return info[0], info[1], 'informada'
    ano_pub, mes_pub = _mes_publicacao_estimada(mes_final_str)
    return ano_pub, mes_pub, 'estimada'


def decidir_promocao(comparacao, hoje, datas_publicacao_informadas=None):
    """
    Política de revisões:
      - Cobertura reduzida (qualquer trimestre da série ativa ausente
        na nova aquisição) → rejeitada, nunca promovida.
      - Valor revisado FORA da janela de 2 meses a partir da
        DISPONIBILIDADE INICIAL do trimestre (ver
        `_referencia_disponibilidade` — nunca do mês central: achado
        da Fase 2.2) → "revisão histórica inesperada": NÃO promovida
        automaticamente, mas também não tratada como erro científico
        definitivo — sinalizada para avaliação (a evidência já foi
        preservada em snapshot antes desta função ser chamada).
      - Valor revisado DENTRO da janela → aceito como revisão
        legítima.
      - Nada mudou → 'reaproveitada_sem_mudanca' (idempotente).
      - Caso contrário (trimestre novo e/ou revisão recente legítima,
        sem cobertura reduzida nem revisão inesperada) → 'promovida'.

    A aquisição inicial de uma série inteira (dados desde 1950, por
    exemplo) nunca passa por esta função comparando "revisão" para
    nenhum trimestre histórico antigo — nesse caso `comparacao['valores_
    revisados']` vem vazio por construção (não há série ativa prévia
    para comparar), então "a aquisição inicial conter dados antigos"
    nunca é, por si só, tratado como elegível para revisão recente.
    """
    if comparacao['cobertura_reduzida']:
        return ('rejeitada_cobertura_reduzida',
                f"trimestre(s) ausentes na nova aquisição: {comparacao['trimestres_removidos']}")

    inesperadas = []
    for (ano, seas), antigo, novo in comparacao['valores_revisados']:
        mes_central = _SEAS_PARA_MES_CENTRAL[seas]
        _, (af, mf) = _mes_inicial_final(mes_central, ano)
        mes_final_str = f'{af}-{mf:02d}'
        ano_pub, mes_pub, origem = _referencia_disponibilidade(
            ano, seas, mes_final_str, datas_publicacao_informadas)
        meses_decorridos = (hoje.year - ano_pub) * 12 + (hoje.month - mes_pub)
        if meses_decorridos > JANELA_REVISAO_RECENTE_MESES:
            inesperadas.append((seas, ano, antigo, novo, meses_decorridos, origem))
    if inesperadas:
        detalhe = '; '.join(f'{s}/{a}: {ant}->{nov} ({m} meses após publicação {o})'
                             for s, a, ant, nov, m, o in inesperadas)
        return 'rejeitada_revisao_historica_inesperada', f'revisão fora da janela de 2 meses: {detalhe}'

    if not comparacao['trimestres_novos'] and not comparacao['valores_revisados']:
        return 'reaproveitada_sem_mudanca', None

    return 'promovida', None


# ══════════════════════════════════════════════════════
# VERIFICAÇÃO SOMENTE LEITURA (usada por verificar_dashboard.py)
# ══════════════════════════════════════════════════════
def verificar_integridade_roni():
    """
    Verificação ESTRITAMENTE DE LEITURA dos artefatos RONI — nunca
    consulta a NOAA, nunca grava, recupera ou recalibra nada; nunca
    reimplementa o parser. Usada por `scripts/verificar_dashboard.py`
    como barreira antes de publicar — nunca compara o valor persistido
    aqui contra `docs/index.html` (`const RONI` pode legitimamente
    estar atrás da série mais recente por defasagem normal de
    publicação).

    Confirma, nesta ordem (Fase 2.2 estende a Fase 2.1):
      1. Existência dos artefatos (ausência total = nada a verificar).
      2. Manifesto legível (Correção 5: corrupção nunca é ignorada).
      3. Integridade de hash de TODOS os snapshots referenciados por
         aquisições ACEITAS no manifesto — não só o ativo (Correção 3).
      4. Série normalizada corresponde ao ÚNICO snapshot que ela mesma
         referencia (Correção 2/3).
      5. O hash ativo tem pelo menos uma promoção correspondente no
         manifesto (detecta interrupção entre a gravação da série e do
         manifesto — Cenário F da Seção 8.3).
      6. Identificação do último registro.

    Retorna (ok: bool, mensagens: [str]) — nunca lança, nunca modifica
    nenhum arquivo em disco.
    """
    msgs = []
    algum_artefato = (HISTORICO_PATH.exists() or PROVENIENCIA_PATH.exists()
                       or (SNAPSHOTS_DIR.exists() and any(SNAPSHOTS_DIR.iterdir())))
    if not algum_artefato:
        return True, ['artefatos RONI (histórico/proveniência/snapshots) ainda não '
                       'inicializados — nada a verificar nesta execução']

    try:
        df = _ler_serie_persistida()
    except BaseCorrompida as e:
        return False, [str(e)]

    # Série ausente/vazia mas há evidência de que algo existiu — nunca
    # tratado como primeira inicialização (Cenário C/F, Seção 8.3).
    if df is None or df.empty:
        if PROVENIENCIA_PATH.exists() or (SNAPSHOTS_DIR.exists() and any(SNAPSHOTS_DIR.iterdir())):
            return False, ['data/roni_historico.csv ausente/vazio, mas já há manifesto e/ou '
                            'snapshot registrado — estado inconsistente (não é primeira '
                            'inicialização); use reconstruir_serie_a_partir_do_manifesto() se '
                            'o manifesto e o snapshot ativo estiverem íntegros']
        return True, ['série histórica RONI ainda vazia — nada a verificar']

    prov, avisos_leitura = ler_proveniencia_seguro()
    if avisos_leitura:
        return False, avisos_leitura + ['não é seguro afirmar integridade com o manifesto '
                                         'corrompido']

    # Correção 3: confirma TODOS os snapshots de aquisições aceitas,
    # não só o ativo — um snapshot antigo adulterado/ausente também
    # reprova, mesmo que a série ativa hoje aponte para outro.
    aceitas = prov[prov['resultado_validacao'] == 'aceita'] if not prov.empty else prov
    for _, linha in aceitas.iterrows():
        h = linha['hash_sha256']
        if not h:
            continue
        if not _hash_valido(h):
            return False, msgs + [f'aquisição {linha["aquisicao_id"]}: hash_sha256 com formato '
                                   f'inválido no manifesto ({h!r})']
        caminho_esperado = str(caminho_snapshot(h).relative_to(ROOT))
        if linha.get('caminho_snapshot') and linha['caminho_snapshot'] != caminho_esperado:
            return False, msgs + [f'aquisição {linha["aquisicao_id"]}: caminho_snapshot '
                                   f'registrado ({linha["caminho_snapshot"]}) não corresponde à '
                                   f'estrutura aprovada ({caminho_esperado})']
        if not caminho_snapshot(h).exists():
            return False, msgs + [f'aquisição {linha["aquisicao_id"]}: snapshot referenciado '
                                   f'({h}) está ausente']
        conteudo = caminho_snapshot(h).read_bytes()
        if calcular_hash(conteudo) != h:
            return False, msgs + [f'aquisição {linha["aquisicao_id"]}: snapshot referenciado '
                                   f'({h}) está corrompido (hash não corresponde ao conteúdo)']

    ok_recon, avisos_recon = serie_ativa_corresponde_ao_snapshot()
    msgs.extend(avisos_recon)
    if not ok_recon:
        return False, msgs or ['série ativa não corresponde ao seu próprio snapshot referenciado']

    # Fase 2.2A, Seção 5: a série ativa precisa corresponder
    # EXATAMENTE à última promoção válida (ordem inequívoca por
    # `coletado_em_utc`, via `_ultima_promocao_valida` — a mesma função
    # usada por `processar_aquisicao()`/`reconstruir_serie_a_partir_
    # do_manifesto()`) — nunca "existe alguma promoção com esse hash em
    # algum ponto do histórico", que aceitaria incorretamente uma série
    # presa numa promoção antiga já superada.
    hash_ativo = df['snapshot_sha256'].iloc[-1]
    ultima_promocao = _ultima_promocao_valida(prov)
    if ultima_promocao is None:
        return False, msgs + [f'série ativa referencia o snapshot {hash_ativo}, mas o manifesto '
                               f'não registra nenhuma promoção — possível interrupção entre a '
                               f'gravação da série e do manifesto, ou manifesto perdido']
    if ultima_promocao['hash_sha256'] != hash_ativo:
        return False, msgs + [f'série ativa referencia o snapshot {hash_ativo}, mas a última '
                               f'promoção válida do manifesto aponta para '
                               f'{ultima_promocao["hash_sha256"]!r} — possível interrupção entre '
                               f'a gravação da série e do manifesto, ou série presa numa '
                               f'promoção já superada']

    primeiro = df.sort_values('mes_central').iloc[0]
    ultimo_real = ultimo_da_serie_ativa()
    msgs.append(f'série RONI íntegra: {len(df)} observações, {primeiro["temporada"]}/'
                f'{int(primeiro["ano"])} a {ultimo_real["seas"]}/{ultimo_real["ano"]}')
    return True, msgs


def _ultimo_se_integro():
    """Fase 2.3, requisito 1: NENHUM caminho de retorno de
    `processar_aquisicao()` pode entregar como confiável um valor lido
    de uma base cuja integridade não foi comprovada — reaproveita
    `verificar_integridade_roni()` (a mesma barreira usada por
    `scripts/verificar_dashboard.py`) em vez de ler
    `ultimo_da_serie_ativa()` diretamente. Se a base ainda não foi
    inicializada (nada a verificar), `verificar_integridade_roni()`
    devolve `ok=True` e esta função se comporta como antes (devolve o
    que houver, tipicamente `None`). Se a base existe mas está
    inconsistente, devolve `None` — nunca o valor não comprovado."""
    ok, _ = verificar_integridade_roni()
    return ultimo_da_serie_ativa() if ok else None


# ══════════════════════════════════════════════════════
# PONTO DE ENTRADA ÚNICO
# ══════════════════════════════════════════════════════
def processar_aquisicao(url=RONI_URL, hoje=None, aquisicao_id=None, conteudo_bytes=None,
                         datas_publicacao_informadas=None,
                         autorizar_inicializacao_com_snapshot_orfao=False):
    """
    Busca a fonte (ou usa `conteudo_bytes` já obtido, para testes/
    reaproveitamento — nunca consulta a fonte de novo só para gerar o
    hash), valida estritamente, compara com a série ativa, decide
    promoção, grava snapshot/manifesto/série quando aplicável, e
    devolve o trimestre mais recente da série EFETIVAMENTE ativa após
    esta execução — o mesmo valor que deve alimentar `const RONI`.

    Ordem (Fase 2.2A, Seção 8 — nunca grava nada antes de validar):
      1. Identidade da aquisição (`aquisicao_id`) E saúde do estado já
         existente, ambas ANTES de decodificar/analisar o conteúdo
         novo. Um `aquisicao_id` repetido com os MESMOS fatos
         (url+hash) é reprocessamento idempotente — devolve o
         resultado ORIGINAL sem nenhuma escrita; com fatos
         incompatíveis, é conflito explícito, também sem nenhuma
         escrita (achado real da Fase 2.2A, Seção 4: a ordem antiga
         gravava a série ANTES de detectar o conflito).
      2. Validar/decidir a promoção sobre o conteúdo novo.
      3. Persistir o snapshot (imutável, verificado).
      4. Registrar atomicamente a promoção no manifesto.
      5. Gerar a série normalizada, só se `estado == 'promovida'`.
      6. Verificar a consistência COMPLETA (`verificar_integridade_roni()`,
         nunca apenas a série contra seu próprio snapshot) antes de
         devolver sucesso — aplicada a QUALQUER estado aceito, nunca só
         ao que de fato reescreveu a série (Fase 2.3, requisito 7).

    `datas_publicacao_informadas`: ver `_referencia_disponibilidade` —
    opcional, só repassado por um chamador que já comprovou uma data de
    publicação real; produção não passa nada aqui hoje (limitação
    documentada: a fonte não expõe essa data).

    `autorizar_inicializacao_com_snapshot_orfao` (Fase 2.3, requisitos
    4/5): por padrão, se NEM a série normalizada NEM o manifesto
    existem mas HÁ pelo menos um snapshot em `data/roni_snapshots/`,
    isso NÃO é tratado como primeira inicialização limpa — é um estado
    ambíguo (evidência de que algo já foi escrito antes, sem registro
    correspondente) e a aquisição é rejeitada. Só prossegue como
    inicialização se o chamador passar `True` explicitamente — uma
    decisão deliberada e controlada, nunca o comportamento padrão de
    uma atualização operacional automática.

    Nunca lança para o chamador em falha de rede, de estrutura ou de
    integridade do próprio histórico/manifesto — qualquer problema é
    reportado no dict de retorno; o card, nesse caso, recebe o último
    valor COMPROVADAMENTE válido já persistido (nunca None só porque
    esta aquisição falhou, mas também nunca um valor lido de uma base
    cuja integridade não foi confirmada — Fase 2.3, requisito 1: nenhum
    caminho de retorno entrega como confiável um RONI de base
    inconsistente; ver `_ultimo_se_integro()`).

    Retorna {'ultimo': {...} ou None, 'estado_promocao': str,
             'avisos': [...], 'aquisicao_id': str}.
    """
    coletado_em_utc = datetime.now(timezone.utc).isoformat()
    hoje = hoje or datetime.now(timezone.utc).date()
    aquisicao_id = aquisicao_id or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')

    if conteudo_bytes is None:
        try:
            conteudo_bytes = buscar_bytes_brutos(url)
        except Exception as e:
            return {'ultimo': _ultimo_se_integro(), 'estado_promocao': 'rejeitada_falha_coleta',
                    'avisos': [f'falha ao buscar {url}: {e}'], 'aquisicao_id': aquisicao_id}

    hash_sha256 = calcular_hash(conteudo_bytes)

    # Passo 1a: identidade da aquisição — ANTES de qualquer análise ou
    # gravação (Seção 4). O manifesto precisa estar legível para isso;
    # se não estiver, nada mais é tentado.
    prov, avisos_manifesto_leitura = ler_proveniencia_seguro()
    if avisos_manifesto_leitura:
        return {'ultimo': _ultimo_se_integro(), 'estado_promocao': 'rejeitada_manifesto_problema',
                'avisos': avisos_manifesto_leitura, 'aquisicao_id': aquisicao_id}

    if not prov.empty:
        ja_existe = prov[prov['aquisicao_id'] == aquisicao_id]
        if not ja_existe.empty:
            existente = ja_existe.iloc[0]
            if str(existente['url']) == str(url) and str(existente['hash_sha256']) == str(hash_sha256):
                # Reprocessamento idempotente de uma aquisição já
                # CONCLUÍDA: preserva o resultado histórico ORIGINAL
                # (`estado_promocao`), sem reclassificar como conflito
                # só porque a base já a incorporou, e sem nenhuma
                # escrita — mas só entrega o valor da série ATIVA se a
                # integridade dela estiver comprovada (Fase 2.3,
                # requisito 3); nunca restaura uma versão anterior nem
                # altera a versão ativa.
                return {'ultimo': _ultimo_se_integro(),
                        'estado_promocao': existente['estado_promocao'],
                        'avisos': [], 'aquisicao_id': aquisicao_id}
            return {'ultimo': _ultimo_se_integro(), 'estado_promocao': 'rejeitada_conflito_aquisicao',
                    'avisos': [f'aquisicao_id {aquisicao_id!r} já registrado com url/hash '
                               f'incompatíveis — registro original preservado, nenhuma escrita '
                               f'realizada por esta tentativa'],
                    'aquisicao_id': aquisicao_id}

    # Passo 1b (Seção 6): saúde do estado JÁ EXISTENTE, independente do
    # conteúdo desta aquisição — nunca usa uma base já inconsistente
    # como referência de comparação nem promove por cima dela. Cada
    # cenário (A-ambígua/B/C/D/E) tem seu próprio rótulo, nunca um
    # genérico só.
    try:
        antiga_df = _ler_serie_persistida()
    except BaseCorrompida as e:
        return {'ultimo': None, 'estado_promocao': 'rejeitada_base_corrompida',
                'avisos': [str(e)], 'aquisicao_id': aquisicao_id}

    serie_existe = antiga_df is not None and not antiga_df.empty

    # Cenário C: série presente mas manifesto ausente — nunca
    # confundido com primeira inicialização (os dois sempre nascem
    # juntos na primeira promoção).
    if serie_existe and not PROVENIENCIA_PATH.exists():
        return {'ultimo': _ultimo_se_integro(), 'estado_promocao': 'rejeitada_manifesto_perdido',
                'avisos': ['data/roni_historico.csv existe mas data/roni_proveniencia.csv '
                           'está ausente — evidência de aquisições anteriores foi perdida; '
                           'nunca reinicializado silenciosamente como se fosse a primeira '
                           'aquisição; use reconstruir_serie_a_partir_do_manifesto() só se o '
                           'manifesto for recuperado por outro meio'],
                'aquisicao_id': aquisicao_id}

    # Cenário A-ambígua (Fase 2.3, requisitos 4/5): nem série nem
    # manifesto existem, mas HÁ pelo menos um snapshot em disco —
    # evidência de que algo já foi escrito antes, sem o registro
    # correspondente no manifesto. Isso NÃO é a mesma coisa que uma
    # base totalmente virgem (Cenário A puro, sem nenhum artefato) e
    # nunca é interpretado silenciosamente como primeira inicialização
    # numa chamada operacional comum — só prossegue se o chamador
    # autorizar explicitamente uma inicialização controlada.
    if (not serie_existe and not PROVENIENCIA_PATH.exists()
            and SNAPSHOTS_DIR.exists() and any(SNAPSHOTS_DIR.iterdir())
            and not autorizar_inicializacao_com_snapshot_orfao):
        return {'ultimo': None, 'estado_promocao': 'rejeitada_snapshot_orfao_sem_autorizacao',
                'avisos': ['há snapshot(s) em data/roni_snapshots/ sem manifesto e sem série '
                           'normalizada correspondentes — não é uma primeira inicialização '
                           'limpa; nunca tratado silenciosamente como tal numa atualização '
                           'operacional comum; chame com '
                           'autorizar_inicializacao_com_snapshot_orfao=True, numa decisão '
                           'explícita e controlada, se esse estado for de fato intencional'],
                'aquisicao_id': aquisicao_id}

    # Cenário B: manifesto já com promoção registrada, mas série
    # normalizada ausente/vazia — nunca tratado como primeira
    # aquisição (perderia o histórico já promovido); a recuperação é
    # sempre explícita (reconstruir_serie_a_partir_do_manifesto()),
    # nunca automática dentro desta função.
    if not serie_existe and PROVENIENCIA_PATH.exists() and _ultima_promocao_valida(prov) is not None:
        return {'ultimo': None, 'estado_promocao': 'rejeitada_serie_ausente_com_manifesto_integro',
                'avisos': ['data/roni_historico.csv ausente/vazio mas o manifesto já registra '
                           'promoção(ões) anteriores — nunca tratado como primeira aquisição; '
                           'use reconstruir_serie_a_partir_do_manifesto() explicitamente'],
                'aquisicao_id': aquisicao_id}

    # Cenários D/E: com manifesto e série ambos presentes, confirma que
    # continuam íntegros e correspondentes ANTES de preparar esta
    # promoção — reaproveita a verificação completa já existente, sem
    # reimplementar a lógica de hash/correspondência aqui.
    if serie_existe and PROVENIENCIA_PATH.exists():
        ok_estado, avisos_estado = verificar_integridade_roni()
        if not ok_estado:
            return {'ultimo': None, 'estado_promocao': 'rejeitada_estado_existente_inconsistente',
                    'avisos': avisos_estado, 'aquisicao_id': aquisicao_id}

    try:
        texto = conteudo_bytes.decode('utf-8')
    except UnicodeDecodeError:
        _registrar_proveniencia(aquisicao_id, coletado_em_utc, url, hash_sha256, None, None, None,
                                 'rejeitada_estrutural', 'conteúdo não é UTF-8 válido',
                                 alterou_texto=None, alterou_valores=None)
        return {'ultimo': ultimo_da_serie_ativa(), 'estado_promocao': 'rejeitada_estrutural',
                'avisos': ['conteúdo não é UTF-8 válido — documento rejeitado'],
                'aquisicao_id': aquisicao_id}

    lista, avisos = parse_roni_serie_completa(texto)

    if lista is None:
        _registrar_proveniencia(aquisicao_id, coletado_em_utc, url, hash_sha256, None, None,
                                 None, 'rejeitada_estrutural', '; '.join(avisos),
                                 alterou_texto=None, alterou_valores=None)
        return {'ultimo': ultimo_da_serie_ativa(), 'estado_promocao': 'rejeitada_estrutural',
                'avisos': avisos, 'aquisicao_id': aquisicao_id}

    # `antiga_df` já foi lida e confirmada saudável no Passo 1b — nunca
    # relida aqui (conteúdo não muda entre os dois pontos dentro desta
    # mesma chamada).
    comparacao = comparar_series(antiga_df, lista)
    estado, motivo = decidir_promocao(comparacao, hoje, datas_publicacao_informadas)

    # Passo 3: persistir e verificar o snapshot — preserva a evidência
    # recebida de forma identificável mesmo em rejeição, nunca só
    # quando promovida. `gravar_snapshot` já confere byte a byte quando
    # reaproveita um arquivo existente; a escrita de um arquivo novo é
    # atômica (tmp + replace).
    try:
        gravar_snapshot(hash_sha256, conteudo_bytes)
    except SerieRejeitada as e:
        _registrar_proveniencia(aquisicao_id, coletado_em_utc, url, hash_sha256, lista[0],
                                 lista[-1], len(lista), 'rejeitada_snapshot_corrompido', str(e),
                                 alterou_texto=None, alterou_valores=None)
        return {'ultimo': ultimo_da_serie_ativa(), 'estado_promocao': 'rejeitada_snapshot_corrompido',
                'avisos': avisos + [str(e)], 'aquisicao_id': aquisicao_id}

    # Fonte de verdade ÚNICA para "qual é o hash ativo segundo o
    # manifesto" (Seção 5) — `_ultima_promocao_valida`, a mesma função
    # usada por `verificar_integridade_roni()` e
    # `reconstruir_serie_a_partir_do_manifesto()`. `prov` já foi lido no
    # Passo 1a — ainda válido aqui, nada escreveu no manifesto desde
    # então.
    ultima_promocao_antes = _ultima_promocao_valida(prov)
    hash_ativo_atual = ultima_promocao_antes['hash_sha256'] if ultima_promocao_antes is not None else None

    # Fase 2.2, Correção 2: "nada mudou" pode significar duas coisas
    # bem diferentes — mesmo hash reobservado vs. hash NOVO (texto
    # diferente) cujos valores batem com a série já ativa. O segundo
    # caso nunca deve se tornar a nova âncora sem reescrever a série de
    # fato — Alternativa B: registra a observação com seu próprio
    # snapshot imutável, sem trocar a referência ativa.
    if estado == 'reaproveitada_sem_mudanca' and hash_ativo_atual is not None \
            and hash_sha256 != hash_ativo_atual:
        estado = 'observada_texto_diferente_valor_identico'

    alterou_texto = (hash_sha256 != hash_ativo_atual)
    alterou_valores = bool(comparacao['valores_revisados']) or bool(comparacao['trimestres_novos'])

    for d in lista:
        d['versao_metodologica'] = VERSAO_METODOLOGICA
        d['snapshot_sha256'] = hash_sha256

    # Passo 4: registrar atomicamente a promoção no manifesto.
    try:
        _registrar_proveniencia(aquisicao_id, coletado_em_utc, url, hash_sha256, lista[0],
                                 lista[-1], len(lista), estado, motivo, alterou_texto, alterou_valores)
    except ConflitoDeAquisicao as e:
        return {'ultimo': ultimo_da_serie_ativa(), 'estado_promocao': 'rejeitada_conflito_aquisicao',
                'avisos': avisos + [str(e)], 'aquisicao_id': aquisicao_id}
    except BaseCorrompida as e:
        return {'ultimo': ultimo_da_serie_ativa(), 'estado_promocao': 'rejeitada_manifesto_problema',
                'avisos': avisos + [str(e)], 'aquisicao_id': aquisicao_id}

    # Passo 5: gerar a série normalizada — só depois do manifesto já
    # registrar a promoção (nunca antes: Seção 4). Se houver
    # interrupção exatamente aqui, o Cenário F já é detectável por
    # `verificar_integridade_roni()`/`reconstruir_serie_a_partir_do_
    # manifesto()` na próxima execução.
    if estado == 'promovida':
        _gravar_serie_historico(lista)

    # Passo 6 (Fase 2.3, requisito 7): verificação COMPLETA de
    # consistência antes de devolver sucesso — `verificar_integridade_
    # roni()`, nunca apenas `serie_ativa_corresponde_ao_snapshot()`
    # (que só confere a série contra seu próprio snapshot e não
    # detectaria, por exemplo, uma série presa numa promoção já
    # superada pelo manifesto). Aplicada a QUALQUER estado aceito
    # (promovida/reaproveitada_sem_mudanca/observada_texto_diferente_
    # valor_identico), não só ao que de fato reescreveu a série —
    # nenhum caminho de sucesso escapa dela.
    ok_final, avisos_final = verificar_integridade_roni()
    if not ok_final:
        return {'ultimo': None, 'estado_promocao': 'rejeitada_inconsistencia_pos_escrita',
                'avisos': avisos + avisos_final, 'aquisicao_id': aquisicao_id}

    return {'ultimo': ultimo_da_serie_ativa(), 'estado_promocao': estado,
            'avisos': avisos, 'aquisicao_id': aquisicao_id}
