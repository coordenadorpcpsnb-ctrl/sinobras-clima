#!/usr/bin/env python3
"""
update_indices.py — Atualização automática de índices oceânicos
Sinobras Florestal · executado todo dia 21 às 13h BRT pelo GitHub Actions

Fontes PSL/NOAA (públicas, sem autenticação):
  CPC sstoi.indices  : https://www.cpc.ncep.noaa.gov/data/indices/sstoi.indices
  PSL nina34.data    : https://psl.noaa.gov/data/correlation/nina34.data
  PSL tsa.data       : https://psl.noaa.gov/data/correlation/tsa.data
  CPC wksst9120.for  : https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for
  CPC RONI.ascii.txt : https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt

Também roda no cron semanal/mensal-início (.github/workflows/indices_semanal.yml)
— ver CLAUDE.md armadilha 9 para a distinção RONI vs. ONI-aprox e o
motivo de não ter automatizado subsuperfície equatorial nem os
indicadores atmosféricos (SOI/ventos/convecção): a CPC publica esses
como ascii MENSAL (não semanal — confirmado no Readme.index.shtml,
"updated around the 10th of each month"), e subsuperfície só existe
como figura, sem ascii algum.
"""

import re, sys, shutil
import hashlib
import html as html_mod
from pathlib import Path
from datetime import date, datetime
import urllib.request
import pandas as pd

ROOT      = Path(__file__).parent.parent
DASHBOARD = ROOT / 'docs' / 'index.html'
MISSING   = -999.9

HEADERS = {
    'User-Agent': 'sinobras-clima/1.0 (github-actions)',
    'Accept'    : 'text/plain, */*',
}

# ══════════════════════════════════════════════════════
# DOWNLOAD
# ══════════════════════════════════════════════════════
def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='replace')


# ══════════════════════════════════════════════════════
# PARSERS
# ══════════════════════════════════════════════════════
def parse_sstoi(text):
    """
    CPC sstoi.indices — colunas fixas:
    YR MON NINO1+2 ANOM NINO3 ANOM NINO4 ANOM NINO3.4 ANOM34
    Retorna {(ano, mes): nino34_anomalia}
    """
    data = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 10:
            continue
        try:
            y, m = int(parts[0]), int(parts[1])
            v = float(parts[9])          # ANOM34
            # anomalia do Niño 3.4 nunca passa de ~3°C — abs(v) > 5 indica
            # coluna errada (ex.: SST absoluta em vez de anomalia)
            if 1950 <= y <= 2030 and abs(v - MISSING) > 1 and abs(v) <= 5:
                data[(y, m)] = round(v, 2)
        except (ValueError, IndexError):
            pass
    return data


# Sentinelas de dado ausente conhecidas nos arquivos de correlação do
# PSL — cada arquivo usa a sua própria convenção (ex.: tsa.data usa
# -99.99, pdo.data usa -9.90). Descartadas explicitamente por valor E
# pelo limite físico abaixo: a lista fixa sozinha é frágil — um
# sentinela novo dentro da faixa física passaria batido.
PSL_SENTINELS = (-99.99, -9.99, -9.90, -999.9)


def parse_psl_anual(text):
    """
    PSL nina34.data / tsa.data / pdo.data — formato real:
        anoIni anoFim         ← linha de cabeçalho (2 tokens, ignorada)
        YYYY v1 v2 ... v12    ← ano e os 12 valores mensais NA MESMA linha
    Descarta sentinelas de ausência conhecidas (PSL_SENTINELS) e, como
    segunda barreira, qualquer valor com abs(v) > 5 (anomalia física
    nunca chega nessa magnitude — pega sentinelas ainda não catalogadas).
    Retorna {(ano, mes): valor}
    """
    data = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 13:
            continue
        try:
            y = int(parts[0])
        except ValueError:
            continue
        if not (1900 <= y <= 2100):
            continue
        for m, vs in enumerate(parts[1:13], start=1):
            try:
                v = float(vs)
            except ValueError:
                continue
            if any(abs(v - s) < 0.01 for s in PSL_SENTINELS):
                continue
            if abs(v) > 5:
                continue
            data[(y, m)] = round(v, 2)
    return data


WKSST_REGIOES = ['nino12', 'nino3', 'nino34', 'nino4']
# Cada região ocupa um bloco de 8 caracteres: SST nos 4 primeiros,
# anomalia nos 4 seguintes — ver parse_wksst() para o motivo de usar
# posição fixa em vez de split().
_WKSST_COLS = [(15, 23), (28, 36), (41, 49), (54, 62)]


def parse_wksst(text):
    """
    CPC wksst9120.for — layout de COLUNA FIXA (FORTRAN), não separado de
    forma confiável por espaço. Testado ao vivo contra as 2.349 linhas
    de dado do arquivo (1981–2026): quando a anomalia é negativa, o
    layout gruda o sinal direto no número anterior, sem espaço —
    "20.6-0.1" é SST=20.6, anomalia=-0.1, não dois tokens.
    `line.split()` conta 5 tokens nessa linha (data + 4 blocos colados)
    em vez dos 9 esperados (data + 4×[SST,ANOM]) — e o parser antigo
    (`if len(parts) < 9: continue`) pulava a linha inteira. Isso não é
    hipotético: **73,6% das 2.349 linhas do arquivo têm essa
    concatenação em pelo menos uma das 4 regiões** (qualquer década com
    La Niña/anomalia negativa). Efeito em produção: sempre que a semana
    mais recente tivesse qualquer anomalia negativa em qualquer uma das
    4 regiões, a linha era pulada silenciosamente e a função devolvia o
    último valor de semanas atrás — sem aviso, sem erro, só um número
    desatualizado.

    Corrigido com slicing de coluna fixa (validado sem falha nas 2.349
    linhas): data em [1:10], cada região em `_WKSST_COLS` — bloco de 8
    chars, [0:4]=SST, [4:8]=anomalia (funciona com ou sem espaço, já
    que a posição não muda).

    Retorna (label_str, {regiao: {'sst': float, 'anom': float}, ...})
    do registro mais recente com as 4 regiões válidas, ou (None, None).
    """
    ultimo_lbl, ultimo_dados = None, None
    for line in text.splitlines():
        if len(line) < 62:
            continue
        data_str = line[1:10]
        try:
            datetime.strptime(data_str, '%d%b%Y')  # valida data
        except ValueError:
            continue

        dados, valido = {}, True
        for nome, (ini, fim) in zip(WKSST_REGIOES, _WKSST_COLS):
            bloco = line[ini:fim]
            try:
                sst  = float(bloco[0:4])
                anom = float(bloco[4:8])
            except ValueError:
                valido = False
                break
            # anomalia nunca passa de ~5°C e SST do Pacífico equatorial
            # nunca sai de 15-35°C — barreira física contra coluna
            # errada ou linha malformada (mesmo padrão dos outros
            # parsers do projeto).
            if abs(anom) > 5 or not (15 <= sst <= 35):
                valido = False
                break
            dados[nome] = {'sst': sst, 'anom': round(anom, 2)}

        if valido:
            ultimo_lbl, ultimo_dados = data_str, dados

    return ultimo_lbl, ultimo_dados


RONI_URL = 'https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt'

# ══════════════════════════════════════════════════════
# CPC — probabilidades de fase ENSO por trimestre
# ══════════════════════════════════════════════════════
# Fase ENSO-DADOS (auditoria 15/10/2026): até aqui, CPC_IRI.cpc (as
# probabilidades por trimestre que alimentam a aba Comparativo) era
# 100% curado à mão — CLAUDE.md armadilha 4 documentava que "o CPC só
# publica figura" para essa tabela. Investigação ao vivo (15/10/2026)
# encontrou que esta página ESPECÍFICA publica a tabela em HTML real
# (não figura, não precisa de OCR), com uma linha <tr> por trimestre e
# 3 <td> em ordem fixa (La Niña, Neutro, El Niño) — confirmado
# estruturalmente contra o HTML bruto antes de escrever este parser,
# nunca assumido. Fonte DIFERENTE do ENSO Diagnostic Discussion (que
# continua prosa/figura, sem parser — lembrete_cpc_thursday.yml
# continua existindo pra essa parte). Mantido só pra esta tabela
# específica; o resto do CPC_IRI (status textual, synopsis, narrativa)
# continua manual.
CPC_PROBABILIDADES_URL = 'https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/probabilities/'
# Duas etapas deliberadas — NUNCA um regex só cruzando `<tr>`: um regex
# único com `.*?` entre o fechamento de <abbr> e o primeiro <td> pode
# "vazar" para a PRÓXIMA linha da tabela se a linha atual tiver um
# valor que não bate no padrão esperado (ex.: um `<td>` com conteúdo
# inesperado) — o `.*?` lazy só precisa achar ALGUM `</abbr></th>`
# seguido de `<td>` mais adiante, e o mais próximo seguinte é o da
# PRÓXIMA linha, gerando um trimestre com o rótulo de uma linha e os
# valores de outra. Confirmado testando deliberadamente contra uma
# linha corrompida antes de finalizar este parser (ver
# tests/test_update_indices.py). Isolar cada `<tr>...</tr>` PRIMEiro
# elimina essa classe de bug: nenhum regex de linha pode ver além da
# sua própria `</tr>`.
_CPC_PROB_LINHA_TR_RE = re.compile(r'<tr>.*?</tr>', re.DOTALL)
_CPC_PROB_SEAS_RE = re.compile(r'<abbr>([A-Z]{3})\b')
_CPC_PROB_TD_RE = re.compile(r'<td>([^<]*)</td>')
# "Issued October 2026" — único lugar da página que identifica a ano/mês
# da emissão; sem ele, nenhuma linha da tabela pode ser associada a um
# ano com segurança (ver _alinhar_seasons_com_ano abaixo).
_CPC_PROB_EMISSAO_RE = re.compile(
    r'Issued\s+(January|February|March|April|May|June|July|August|September|'
    r'October|November|December)\s+(\d{4})', re.IGNORECASE,
)
_MESES_EN = {'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
             'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12}
# Trimestre (centrado no mês do meio) -> sigla de 3 letras, convenção
# CPC já usada em todo o projeto (ver update_dashboard.py, _tri_nome).
_MES_CENTRAL_PARA_SIGLA = {
    1: 'DJF', 2: 'JFM', 3: 'FMA', 4: 'MAM', 5: 'AMJ', 6: 'MJJ',
    7: 'JJA', 8: 'JAS', 9: 'ASO', 10: 'SON', 11: 'OND', 12: 'NDJ',
}


def _alinhar_seasons_com_ano(html, linhas_brutas):
    """
    Associa cada linha (sigla de 3 letras + probabilidades) a um ANO
    específico — nunca pela sigla isolada (duas siglas iguais podem
    cair em anos diferentes se o horizonte cruzar a virada do ano).

    Âncora: o cabeçalho "Issued <Mês> <Ano>" da própria página — único
    dado, nesta fonte, que identifica o ano sem ambiguidade. A partir
    dele, deriva o mês central de CADA linha andando sequencialmente
    (+1 mês por linha, carregando o ano na virada dez→jan) — a página
    descreve explicitamente "9 upcoming, overlapping 3-month seasons"
    em ORDEM cronológica, confirmado contra a página real: a primeira
    linha (centrada no mês da própria emissão) sempre bate com a sigla
    publicada. Cada mês central derivado é VALIDADO de volta contra a
    sigla de 3 letras que a página realmente publicou nessa linha
    (`_MES_CENTRAL_PARA_SIGLA`) — se não bater em NENHUMA linha, a
    suposição de ordem sequencial está errada pra esta emissão e a
    função recusa alinhar (retorna {}), nunca adivinha.

    Retorna {'SEAS/YY': {...}, ...} (mesmo formato de `CPC_IRI.seasons`)
    ou {} se a emissão não puder ser identificada com segurança — NUNCA
    associa uma sigla a um ano por suposição.
    """
    m_emissao = _CPC_PROB_EMISSAO_RE.search(html)
    if not m_emissao:
        return {}
    mes_emissao = _MESES_EN.get(m_emissao.group(1).lower())
    ano_emissao = int(m_emissao.group(2))
    if mes_emissao is None:
        return {}

    resultado = {}
    mes_atual, ano_atual = mes_emissao, ano_emissao
    for sigla, valores in linhas_brutas:
        sigla_esperada = _MES_CENTRAL_PARA_SIGLA[mes_atual]
        if sigla != sigla_esperada:
            # ordem sequencial assumida não bate com o que a página
            # publicou — não arrisca associar ano por adivinhação.
            return {}
        if valores is not None:
            resultado[f'{sigla}/{str(ano_atual)[2:]}'] = valores
        mes_atual += 1
        if mes_atual > 12:
            mes_atual, ano_atual = 1, ano_atual + 1
    return resultado


def parse_cpc_probabilidades(html):
    """
    Tabela HTML real (não figura) de probabilidade de fase ENSO por
    trimestre, em <th><abbr>SEAS</abbr></th><td>ln</td><td>neu</td><td>en</td>
    — ordem de colunas confirmada contra o HTML bruto (La Niña, Neutro,
    El Niño), nunca assumida de memória. Barreira física: cada linha
    tem que ter exatamente 3 <td>, somar ~100 (±1, tolerância de
    arredondamento) e cada valor tem que estar em [0,100] — linha que
    falha é DESCARTADA (não gera dado parcial/inventado), nunca
    derruba as demais.

    Cada trimestre só entra no resultado com o ANO alinhado contra o
    cabeçalho "Issued <Mês> <Ano>" da página (ver
    `_alinhar_seasons_com_ano`) — nunca pela sigla de 3 letras isolada,
    que se repete todo ano e seria ambígua perto da virada do ano.

    Retorna {'SEAS/YY': {'ln': float, 'neu': float, 'en': float}, ...}
    — dict vazio se a página não tiver nenhuma linha válida OU se o
    ano de emissão não puder ser identificado/validado com segurança
    (ex.: CPC trocou a estrutura da página) — nunca lança exceção.
    """
    # IMPORTANTE: a posição de cada linha na tabela (não só as que
    # passam no filtro de valores) é o que ancora o alinhamento de ano
    # em _alinhar_seasons_com_ano — uma linha com valores inválidos
    # ainda OCUPA sua posição sequencial (`valores=None`), senão
    # descartá-la deslocaria o ano de todas as linhas seguintes (ex.:
    # se a 8ª linha falhar na soma ~100, a 9ª não pode "herdar" a
    # posição da 8ª).
    linhas_brutas = []
    for tr in _CPC_PROB_LINHA_TR_RE.finditer(html):
        linha = tr.group(0)
        m_seas = _CPC_PROB_SEAS_RE.search(linha)
        if not m_seas:
            continue
        tds = _CPC_PROB_TD_RE.findall(linha)
        valores = None
        if len(tds) == 3:
            try:
                ln, neu, en = (float(v) for v in tds)
                candidato = (ln, neu, en)
                if all(0 <= v <= 100 for v in candidato) and abs(sum(candidato) - 100) <= 1:
                    valores = {'ln': ln, 'neu': neu, 'en': en}
            except ValueError:
                pass
        linhas_brutas.append((m_seas.group(1), valores))

    if not linhas_brutas:
        return {}
    return _alinhar_seasons_com_ano(html, linhas_brutas)


# ══════════════════════════════════════════════════════
# CPC — metadados do ENSO Diagnostic Discussion (data de emissão,
# próxima emissão, status categórico do Alert System)
# ══════════════════════════════════════════════════════
# Fase ENSO-AUTO (19/10/2026): a página do Diagnostic Discussion é
# PROSA (Synopsis — nunca parseada nem interpretada, CLAUDE.md
# armadilha 9), mas tem 3 metadados ESTRUTURAIS extraíveis sem
# interpretar ciência nenhuma — confirmado contra a página real (HTTP
# 200 deste ambiente; diferente do IRI, cpc.ncep.noaa.gov não está
# bloqueado) em 19/10/2026, batendo exatamente com o que já estava
# hand-curado para a emissão de 8/out/2026:
#   1. Data de emissão — bloco <font size="4"> isolado logo depois de
#      "issued by<br>CLIMATE PREDICTION CENTER/NCEP/NWS<br>".
#   2. Status do ENSO Alert System — <span style="color:...">TEXTO</span>
#      dentro do link para enso-alert-readme.shtml: rótulo CATEGÓRICO
#      fixo que a própria CPC usa (Advisory/Watch/etc.), não uma
#      interpretação nossa do texto.
#   3. Próxima emissão — "scheduled for <data>", frase fixa que sempre
#      acompanha o aviso de periodicidade mensal.
# NUNCA toca `_meta.cpc_status` (a frase mais longa, com probabilidade
# e janela temporal, curada manualmente a partir da Synopsis) — grava
# só em `cpc_alert_status` (novo campo, categórico) e em
# `cpc_emissao`/`cpc_proxima` (datas). Qualquer um dos 3 campos que não
# for encontrado fica de fora do dict — nunca inventado.
CPC_DIAGNOSTIC_DISCUSSION_URL = (
    'https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml'
)
_CPC_DD_DATA_EMISSAO_RE = re.compile(
    r'CLIMATE PREDICTION CENTER/NCEP/NWS\s*<br>.*?size="4">\s*(\d{1,2}\s+'
    r'(?:January|February|March|April|May|June|July|August|September|'
    r'October|November|December)\s+\d{4})', re.DOTALL | re.IGNORECASE,
)
_CPC_DD_PROXIMA_RE = re.compile(
    r'scheduled for\s+(\d{1,2}\s+(?:January|February|March|April|May|June|July|'
    r'August|September|October|November|December)\s+\d{4})', re.IGNORECASE,
)
_CPC_DD_STATUS_RE = re.compile(
    r'ENSO Alert System Status.*?<span[^>]*>([^<]+)</span>', re.DOTALL | re.IGNORECASE,
)
_NOMES_MESES_PT = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun',
                   'jul', 'ago', 'set', 'out', 'nov', 'dez']


def _data_en_para_pt(texto):
    """'8 October 2026' -> '8/out/2026'. None se o mês não for
    reconhecido — nunca inventa uma data a partir de texto ambíguo."""
    m = re.match(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})', texto.strip())
    if not m:
        return None
    dia, mes_en, ano = m.groups()
    mes_num = _MESES_EN.get(mes_en.lower())
    if mes_num is None:
        return None
    return f'{int(dia)}/{_NOMES_MESES_PT[mes_num - 1]}/{ano}'


def parse_cpc_diagnostic_discussion_metadata(html):
    """
    Extrai só os 3 metadados estruturais do Diagnostic Discussion (ver
    comentário acima) — nunca a Synopsis. Cada campo é validado e falha
    SEPARADAMENTE (data com mês não reconhecido, status vazio) sem
    derrubar os outros dois. Decodifica entidades HTML (`&ntilde;` etc.)
    do status com `html.unescape`, nunca deixando entidade crua no
    dashboard.

    Retorna {'emissao': 'D/mmm/AAAA', 'proxima': 'D/mmm/AAAA',
    'alert_status': str} só com as chaves extraídas com segurança —
    {} se a página não tiver NENHUMA reconhecível (estrutura mudou).
    """
    resultado = {}

    m = _CPC_DD_DATA_EMISSAO_RE.search(html)
    if m:
        d = _data_en_para_pt(m.group(1))
        if d:
            resultado['emissao'] = d

    m = _CPC_DD_PROXIMA_RE.search(html)
    if m:
        d = _data_en_para_pt(m.group(1))
        if d:
            resultado['proxima'] = d

    m = _CPC_DD_STATUS_RE.search(html)
    if m:
        status = html_mod.unescape(m.group(1)).strip()
        if status:
            resultado['alert_status'] = status

    return resultado


def _data_pt_para_date(texto):
    """'8/out/2026' -> date(2026,10,8). None se não reconhecer."""
    if not texto:
        return None
    m = re.match(r'(\d{1,2})/([a-zç]{3})/(\d{4})', texto.strip().lower())
    if not m:
        return None
    dia, mes_abv, ano = m.groups()
    mes_num = _MESES_PT_PARA_NUM.get(mes_abv)
    if mes_num is None:
        return None
    try:
        return date(int(ano), mes_num, int(dia))
    except ValueError:
        return None


_MESES_PT_PARA_NUM = {nome: i + 1 for i, nome in enumerate(_NOMES_MESES_PT)}


def _mes_ano_pt_para_tupla(texto):
    """'out/2026' -> (2026, 10). None se não reconhecer — usado só para
    COMPARAR ordem cronológica entre emissões (Seção 6: nunca
    sobrescrever uma emissão mais recente por outra antiga), nunca para
    decidir alinhamento de trimestre (isso é _alinhar_seasons_com_ano)."""
    if not texto:
        return None
    m = re.match(r'([a-zç]{3})/(\d{4})', texto.strip().lower())
    if not m:
        return None
    mes_num = _MESES_PT_PARA_NUM.get(m.group(1))
    if mes_num is None:
        return None
    return (int(m.group(2)), mes_num)


def atualizar_cpc_diagnostic_discussion_metadata_no_html(html, metadados):
    """
    Grava `metadados` (saída de `parse_cpc_diagnostic_discussion_metadata`)
    em `CPC_IRI._meta.cpc_emissao` / `cpc_proxima` / `cpc_alert_status` —
    IDEMPOTENTE (via `_upsert_campo_meta`) e com uma barreira de
    segurança explícita (Seção 6 da Fase ENSO-AUTO): nunca sobrescreve
    `cpc_emissao` com uma data mais ANTIGA do que a já gravada — uma
    emissão mais nova nunca é substituída por uma mais velha, mesmo que
    o fetch desta execução tenha vindo de uma página em cache/atrasada.
    `cpc_proxima`/`cpc_alert_status` seguem a mesma decisão de
    `cpc_emissao` (só gravam quando ele avança ou quando ainda não
    existe) — os 3 campos descrevem a MESMA emissão, nunca ficam de
    emissões diferentes entre si.

    Nunca toca `_meta.cpc_status` (frase manual, mais rica, derivada da
    Synopsis) nem `CPC_IRI.cpc.{en,neu,ln}` (outra função, outra fonte).

    Retorna (html, mudou: bool).
    """
    if not metadados or 'emissao' not in metadados:
        return html, False

    ini = html.find('const CPC_IRI = {')
    if ini < 0:
        return html, False
    fim = html.find('\n};', ini)
    if fim < 0:
        return html, False
    fim += 3
    bloco = html[ini:fim]

    m_atual = re.search(r"cpc_emissao:\s*'([^']*)'", bloco)
    emissao_atual_str = m_atual.group(1) if m_atual else None
    emissao_atual = _data_pt_para_date(emissao_atual_str)
    emissao_nova = _data_pt_para_date(metadados['emissao'])
    if emissao_nova is None:
        return html, False
    if emissao_atual is not None and emissao_nova < emissao_atual:
        # emissão buscada é mais ANTIGA que a já gravada — nunca
        # regride (Seção 6: "impedir sobrescrita de uma emissão mais
        # recente por outra antiga").
        return html, False

    # Idempotente de verdade: só "nada a fazer" quando os 3 campos JÁ
    # BATEM com o que seria gravado — não só quando a emissão é igual.
    # Achado real (Fase ENSO-AUTO): uma checagem baseada só em
    # `emissao_atual == emissao_nova` nunca grava `cpc_alert_status`/
    # `cpc_proxima` na primeira execução em que a emissão já estava
    # certa mas esses dois campos (novos nesta fase) ainda não
    # existiam — ficariam ausentes indefinidamente até a PRÓXIMA
    # emissão avançar.
    m_status_atual = re.search(r"cpc_alert_status:\s*'([^']*)'", bloco)
    status_atual = m_status_atual.group(1) if m_status_atual else None
    m_proxima_atual = re.search(r"cpc_proxima:\s*'([^']*)'", bloco)
    proxima_atual = m_proxima_atual.group(1) if m_proxima_atual else None

    nada_mudou = (
        emissao_atual == emissao_nova
        and metadados.get('alert_status', status_atual) == status_atual
        and metadados.get('proxima', proxima_atual) == proxima_atual
    )
    if nada_mudou:
        return html, False

    bloco_novo = _upsert_campo_meta(bloco, 'cpc_emissao', metadados['emissao'])
    if 'proxima' in metadados:
        bloco_novo = _upsert_campo_meta(bloco_novo, 'cpc_proxima', metadados['proxima'])
    if 'alert_status' in metadados:
        bloco_novo = _upsert_campo_meta(bloco_novo, 'cpc_alert_status', metadados['alert_status'])
    bloco_novo = _upsert_campo_meta(
        bloco_novo, 'cpc_discussion_coleta', date.today().strftime('%d/%m/%Y'))

    return html[:ini] + bloco_novo + html[fim:], True


# ══════════════════════════════════════════════════════
# IRI — mecanismo semiautomático de detecção de mudança (Fase ENSO-AUTO)
# ══════════════════════════════════════════════════════
# iri.columbia.edu está bloqueado do ambiente Claude Code (403 no
# proxy desta sessão, confirmado na Fase ENSO-IRI) — não confirmado
# bloqueado do runner do GitHub Actions (ver
# .github/workflows/diagnostico_acesso_iri.yml, testável só depois do
# merge). Decisão desta fase: NÃO automatizar a LEITURA de
# probabilidades do IRI (proibido inferir de imagem; proibido
# converter El Niño em Neutro/La Niña por suposição; a página não
# publica mais arquivo de dados — ver Fase ENSO-IRI). Em vez disso,
# mecanismo semiautomático best-effort: a cada execução, SE a página
# for alcançável, calcula um hash do TEXTO normalizado (sem tags, sem
# espaço redundante) e compara com o último hash gravado — "mudou" é
# só um sinal de que algo mudou (provavelmente nova emissão), nunca
# uma extração de dado científico. Falha de rede é tratada como "sem
# informação nova" — nunca sobrescreve o hash gravado, nunca gera
# falso positivo (mesma disciplina de persistência de TSA/PDO/RONI).
IRI_URL = 'https://iri.columbia.edu/our-expertise/climate/forecasts/enso/current/'
IRI_HASH_PATH = ROOT / 'data' / '.iri_pagina_hash'
_TAMANHO_MINIMO_PAGINA_IRI = 1000  # chars de texto normalizado — abaixo disso é página de erro/truncada


def _normalizar_texto_html(html):
    """Remove tags, scripts e espaço redundante — evita 'mudou' por
    reformatação cosmética (indentação, espaçamento) que não altera o
    conteúdo. Nunca usado para EXTRAIR dado, só para gerar a impressão
    digital do hash."""
    sem_script = re.sub(r'<script.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    sem_tags = re.sub(r'<[^>]+>', ' ', sem_script)
    return re.sub(r'\s+', ' ', sem_tags).strip()


def verificar_mudanca_pagina_iri(html, hash_anterior):
    """
    Compara o hash SHA-256 do texto normalizado de `html` (buscado
    agora) com `hash_anterior` (lido de IRI_HASH_PATH, ou None na
    primeira execução). Retorna (hash_novo_ou_hash_anterior, mudou:
    bool) — NUNCA extrai nem interpreta conteúdo, só detecta mudança.

    `html` vazio/None (fetch falhou) -> (hash_anterior, False) — nunca
    sobrescreve um hash bom por falha de fonte. Página menor que
    `_TAMANHO_MINIMO_PAGINA_IRI` (texto normalizado) é tratada como
    falha (provável página de erro/truncada), mesma barreira.
    Primeira execução (hash_anterior is None) grava o hash inicial mas
    NUNCA reporta como "mudança" — não há nada anterior para comparar.
    """
    if not html:
        return hash_anterior, False
    texto_norm = _normalizar_texto_html(html)
    if len(texto_norm) < _TAMANHO_MINIMO_PAGINA_IRI:
        return hash_anterior, False
    hash_novo = hashlib.sha256(texto_norm.encode('utf-8')).hexdigest()
    if hash_anterior is None:
        return hash_novo, False
    return hash_novo, hash_novo != hash_anterior


def _seasons_do_cpc_iri(html):
    """Lê `CPC_IRI.seasons` do HTML (ex.: ['ASO/26','SON/26',...]) —
    NUNCA escreve nessa lista, só lê a ordem/comprimento já curados à
    mão, pra alinhar `cpc.en/neu/ln` a ela. Retorna lista de strings
    'SEAS/YY', ou [] se o bloco não for encontrado."""
    m = re.search(r'CPC_IRI\s*=\s*\{.*?seasons:\s*\[([^\]]+)\]', html, re.DOTALL)
    if not m:
        return []
    return [s.strip().strip("'\"") for s in m.group(1).split(',') if s.strip()]


def _upsert_campo_meta(bloco, nome_campo, valor):
    """Insere ou substitui UM campo dentro de `_meta: {...}` — nunca
    duplica: se o campo já existe (de uma execução anterior), substitui
    o valor no lugar; se não existe, insere logo após a abertura de
    `_meta: {`. Nunca toca em nenhum outro campo do bloco. Correção
    (revisão externa, 2ª rodada, item "Correção 1"): a versão anterior
    inseria `cpc_probabilidades_atualizado_em` incondicionalmente a
    cada execução, duplicando a linha a cada rodada repetida."""
    padrao_existente = re.compile(rf"\n(\s*){nome_campo}:\s*'[^']*',")
    nova_linha = f"\n    {nome_campo}: '{valor}',"
    if padrao_existente.search(bloco):
        return padrao_existente.sub(nova_linha, bloco, count=1)
    return re.sub(r'(_meta:\s*\{)', r'\1' + nova_linha, bloco, count=1)


def atualizar_cpc_probabilidades_no_html(html, probabilidades, emissao=None):
    """
    Preenche `CPC_IRI.cpc.{en,neu,ln}` a partir de `probabilidades`
    (saída de parse_cpc_probabilidades — chaves já no formato
    'SEAS/YY', ano incluído, NUNCA casadas pela sigla de 3 letras
    isolada), alinhado à ordem/comprimento já existente de
    `CPC_IRI.seasons` — NUNCA muda a lista de seasons em si (é
    compartilhada com CPC_IRI.iri, que continua manual; mudar o
    comprimento de um sem o outro quebraria o gráfico).

    `emissao` (opcional): string 'mmm/AAAA' do cabeçalho "Issued" da
    página de origem (ver `extrair_emissao_cpc_probabilidades`) — vira
    `_meta.cpc_probabilidades_emissao`, SEPARADO da data de coleta
    (`cpc_probabilidades_atualizado_em`, sempre "hoje") e nunca
    confundido com `_meta.cpc_emissao` (a data do Diagnostic
    Discussion, que esta função nunca toca).

    Trimestre de `seasons` sem equivalente em `probabilidades` (ex.:
    ASO/26 já em curso, o CPC não publica mais previsão pra ele) vira
    `null` — nunca estimado, nunca herdado do valor antigo (herdar
    misturaria um valor de uma emissão antiga com os de uma nova, sem
    como saber depois qual é qual).

    Se `probabilidades` vier vazio (fetch falhou, parsing falhou, ou o
    ano de cada trimestre não pôde ser identificado com segurança —
    ver parse_cpc_probabilidades), não mexe em nada — devolve
    (html, False) — mesma disciplina de persistência de
    TSA/PDO/CHC-Preliminar: nunca sobrescrever um dado bom só porque a
    fonte falhou desta vez.

    IDEMPOTENTE e sem reescritas desnecessárias (revisão externa, 2ª
    rodada, item "Correção 1"): se os valores de `cpc[]` calculados
    agora forem byte-a-byte IGUAIS aos já gravados, e a emissão
    reportada também não mudou, a função não reescreve nada — devolve
    (html, False). `_meta.cpc_probabilidades_ultima_alteracao` só é
    tocado quando os valores de fato mudam (nunca a cada execução).

    Opera só dentro do bloco `const CPC_IRI = {...};` já localizado —
    nunca um re.sub global (CLAUDE.md armadilha 2).
    """
    if not probabilidades:
        return html, False

    ini = html.find('const CPC_IRI = {')
    if ini < 0:
        print('  ⚠ const CPC_IRI não encontrado — probabilidades CPC não atualizadas')
        return html, False
    fim = html.find('\n};', ini)
    if fim < 0:
        print('  ⚠ fechamento de CPC_IRI não encontrado — probabilidades CPC não atualizadas')
        return html, False
    fim += 3
    bloco = html[ini:fim]

    seasons = _seasons_do_cpc_iri(bloco)
    if not seasons:
        print('  ⚠ CPC_IRI.seasons vazio/não encontrado — probabilidades CPC não atualizadas')
        return html, False

    en, neu, ln, n_preenchidos = [], [], [], 0
    for s in seasons:
        p = probabilidades.get(s)  # casamento pela chave COMPLETA 'SEAS/YY', nunca a sigla isolada
        if p is None:
            en.append('null'); neu.append('null'); ln.append('null')
        else:
            en.append(str(p['en'])); neu.append(str(p['neu'])); ln.append(str(p['ln']))
            n_preenchidos += 1

    if n_preenchidos == 0:
        print('  ⚠ nenhum trimestre de CPC_IRI.seasons encontrado na tabela CPC — '
              'probabilidades CPC não atualizadas (fonte pode ter mudado de estrutura, '
              'ou o ano não pôde ser alinhado com segurança)')
        return html, False

    m_emissao_atual = re.search(r"cpc_probabilidades_emissao:\s*'([^']*)'", bloco)
    emissao_atual = m_emissao_atual.group(1) if m_emissao_atual else None

    # Seção 6 da Fase ENSO-AUTO: nunca sobrescrever uma emissão mais
    # recente já gravada por uma mais ANTIGA buscada agora (ex.: página
    # servida de cache/CDN atrasado). Comparação por (ano, mês), não
    # por igualdade de string — "out/2026" teria passado pela checagem
    # antiga mesmo sendo mais nova que "nov/2026" se alguém rodasse o
    # script fora de ordem.
    tup_atual = _mes_ano_pt_para_tupla(emissao_atual)
    tup_novo = _mes_ano_pt_para_tupla(emissao)
    if tup_atual is not None and tup_novo is not None and tup_novo < tup_atual:
        print(f'  ⚠ tabela de probabilidades CPC buscada ({emissao}) é mais antiga que '
              f'a já gravada ({emissao_atual}) — ignorada, nunca regride uma emissão')
        return html, False

    nova_cpc_linha = (
        f"\n  cpc:{{ en:[{','.join(en)}], neu:[{','.join(neu)}], ln:[{','.join(ln)}] }},"
    )
    m_cpc_atual = re.search(r'\n  cpc:\{[^}]*\},', bloco)
    cpc_mudou = (m_cpc_atual is None) or (m_cpc_atual.group(0) != nova_cpc_linha)
    emissao_mudou = emissao is not None and emissao != emissao_atual

    if not cpc_mudou and not emissao_mudou:
        # Nada mudou de fato — nunca reescrever só para bater uma nova
        # data de coleta sem conteúdo novo nenhum (evita commit vazio).
        return html, False

    bloco_novo = bloco
    if cpc_mudou:
        if m_cpc_atual is not None:
            bloco_novo = bloco_novo[:m_cpc_atual.start()] + nova_cpc_linha + bloco_novo[m_cpc_atual.end():]
        else:
            bloco_novo = re.sub(r'\n  cpc:\{[^}]*\},', nova_cpc_linha, bloco_novo, count=1)
        bloco_novo = _upsert_campo_meta(
            bloco_novo, 'cpc_probabilidades_ultima_alteracao', date.today().strftime('%d/%m/%Y'))

    bloco_novo = _upsert_campo_meta(
        bloco_novo, 'cpc_probabilidades_atualizado_em', date.today().strftime('%d/%m/%Y'))
    if emissao is not None:
        bloco_novo = _upsert_campo_meta(bloco_novo, 'cpc_probabilidades_emissao', emissao)

    print(f'  ✅ CPC_IRI.cpc: {n_preenchidos}/{len(seasons)} trimestres '
          f'{"atualizados" if cpc_mudou else "confirmados (sem mudança de valor)"} '
          f'da tabela oficial ({CPC_PROBABILIDADES_URL})')
    return html[:ini] + bloco_novo + html[fim:], True


def extrair_emissao_cpc_probabilidades(html):
    """Retorna 'mmm/AAAA' (ex.: 'out/2026') do cabeçalho "Issued <Mês>
    <Ano>" da página de probabilidades CPC, ou None se não encontrado
    — mesmo texto usado por `_alinhar_seasons_com_ano` para alinhar o
    ano de cada trimestre, exposto aqui separadamente só para registrar
    em `_meta.cpc_probabilidades_emissao` (nunca para decidir alinhamento
    de novo — essa decisão já foi tomada dentro de parse_cpc_probabilidades)."""
    m = _CPC_PROB_EMISSAO_RE.search(html)
    if not m:
        return None
    mes_num = _MESES_EN.get(m.group(1).lower())
    if mes_num is None:
        return None
    nomes_pt = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
    return f'{nomes_pt[mes_num - 1]}/{m.group(2)}'


def parse_roni(text):
    """
    CPC RONI.ascii.txt — cabeçalho 'SEAS YR ANOM', uma linha por
    trimestre: 'JJA  2026  1.36'. Formato confirmado ao vivo (920
    linhas, 1950–presente, sem sentinela de ausência visível — o
    arquivo simplesmente termina no último trimestre publicado).

    RONI **não é** o mesmo índice que nosso ONI-aprox (calc_oni, média
    móvel de 3 meses do Niño 3.4 bruto): RONI é o índice oficial do
    CPC, calculado subtraindo a tendência de aquecimento tropical
    global do Niño 3.4 antes de padronizar — por isso roda
    sistematicamente mais baixo que o ONI-aprox no mesmo trimestre
    (ver CLAUDE.md, armadilha 9). Os dois precisam de rótulo que os
    distinga claramente sempre que aparecerem juntos.

    Retorna (temporada, ano, valor) do último registro válido, ou
    (None, None, None).
    """
    ultimo = (None, None, None)
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        seas, yr_s, val_s = parts
        if not re.match(r'^[A-Z]{3}$', seas):
            continue
        try:
            yr  = int(yr_s)
            val = float(val_s)
        except ValueError:
            continue
        if not (1900 <= yr <= 2100) or abs(val) > 5:
            continue
        ultimo = (seas, yr, round(val, 2))
    return ultimo


# ══════════════════════════════════════════════════════
# ONI
# ══════════════════════════════════════════════════════
def calc_oni(nino34):
    """Média móvel de 3 meses centrada no mês do meio."""
    oni = {}
    for (y, m), v in nino34.items():
        ym1 = (y - 1, 12) if m == 1  else (y, m - 1)
        yp1 = (y + 1,  1) if m == 12 else (y, m + 1)
        if ym1 in nino34 and yp1 in nino34:
            oni[(y, m)] = round((nino34[ym1] + v + nino34[yp1]) / 3, 2)
    return oni


# ══════════════════════════════════════════════════════
# MONTAR ARRAYS PARA O DASHBOARD
# ══════════════════════════════════════════════════════
def build_series(nino34, tsa):
    """
    Série MENSAL — SOMENTE valores mensais reais de `nino34`/`tsa` (e
    `oni`, derivado deles por `calc_oni`). Mês sem dado mensal real
    ainda (tipicamente o mês corrente, que a CPC só publica depois) é
    `null`, nunca preenchido com a leitura semanal.

    Correção (revisão externa, 2ª rodada, item "Correção 2"): a versão
    anterior preenchia o mês corrente com `wk_val` (a leitura semanal
    mais recente) sempre que faltava dado mensal — sem checar de QUE
    mês a própria leitura semanal era. Bug real confirmado nos dados:
    em 15/10/2026, a semana mais recente válida de wksst9120.for
    estava centrada em 23/09/2026 (set/2026, não out/2026) — a leitura
    foi inserida no ponto de out/2026 do eixo mensal, rotulando um
    valor de setembro como se fosse outubro (visível no gráfico do
    Monitor ENSO: um "salto" fantasma em out/26 criado só pela
    promoção indevida da leitura semanal). A leitura semanal continua
    disponível — só não mistura mais nesta série; ver `wk_lbl`/`wk_val`
    em `update_html()`, usados só no card D.now, com a DATA PRÓPRIA
    da leitura semanal, nunca a de "hoje".
    """
    TODAY = date.today()
    oni   = calc_oni(nino34)

    # Jan/2023 até mês atual inclusive
    labels_o, n34_o, oni_o, tsa_o = [], [], [], []
    y, m = 2023, 1
    while (y, m) <= (TODAY.year, TODAY.month):
        lbl = f'"{m:02d}/{str(y)[2:]}"'
        n34 = nino34.get((y, m))
        o   = oni.get((y, m))
        t   = tsa.get((y, m))

        labels_o.append(lbl)
        n34_o.append(str(n34) if n34 is not None else 'null')
        oni_o.append(str(o)   if o   is not None else 'null')
        tsa_o.append(str(t)   if t   is not None else 'null')

        m += 1
        if m > 12:
            y, m = y + 1, 1

    return {'labels': labels_o, 'nino34': n34_o, 'oni': oni_o, 'tsa': tsa_o}


def latest_non_null(series, key):
    for lbl, v in zip(reversed(series['labels']), reversed(series[key])):
        if v != 'null':
            return lbl.strip('"'), float(v)
    return None, None


def label_fmt(lbl):
    """'06/26' → 'jun/2026'"""
    meses = ['jan','fev','mar','abr','mai','jun',
             'jul','ago','set','out','nov','dez']
    try:
        mm, yy = lbl.split('/')
        return f"{meses[int(mm)-1]}/20{yy}"
    except Exception:
        return lbl


def _escolher_nino34_para_card_agora(wk_lbl, wk_val, lbl_mensal, val_mensal):
    """
    Decide o par (rótulo, valor) de Niño 3.4 pro card "agora" (D.now)
    — função pura, testável sem tocar o HTML. Prefere a leitura
    SEMANAL só quando ela for do mesmo mês do último valor MENSAL real
    disponível, ou mais recente — nunca promove uma leitura semanal
    desatualizada (de um mês anterior ao último mensal já publicado)
    ao card "agora". O rótulo final sempre reflete a DATA PRÓPRIA do
    valor escolhido (nunca "hoje", nunca o mês corrente do calendário).

    Correção (revisão externa, 2ª rodada, item "Correção 2") — casos
    cobertos explicitamente em teste: falha da fonte semanal (`wk_val`
    None → usa mensal), ausência de valor mensal (`lbl_mensal` None →
    usa semanal, não há com o que comparar), semana desatualizada
    (semanal mais velha que o último mensal → mantém o mensal), virada
    de mês (semanal do mês novo, mensal ainda do mês velho → usa
    semanal, é mais recente).
    """
    if wk_val is None or wk_lbl is None:
        return lbl_mensal, val_mensal
    try:
        dt_semanal = datetime.strptime(wk_lbl, '%d%b%Y')
    except Exception:
        return lbl_mensal, val_mensal

    if lbl_mensal is not None:
        mm_s, yy_s = dt_semanal.month, dt_semanal.year
        mm_m, yy_m = int(lbl_mensal.split('/')[0]), int('20' + lbl_mensal.split('/')[1])
        if (yy_s, mm_s) < (yy_m, mm_m):
            return lbl_mensal, val_mensal

    return dt_semanal.strftime('%m/%y'), wk_val


# ══════════════════════════════════════════════════════
# ATUALIZAR HTML
# ══════════════════════════════════════════════════════
def update_html(series, wk_lbl, wk_val, roni=None):
    html = DASHBOARD.read_text(encoding='utf-8')
    original = html

    # ── Séries do Monitor ENSO ──────────────────────────────────────────
    # ATENÇÃO: operar SOMENTE dentro do bloco `indices:{...}`.
    # Um re.sub global em 'labels:[...]' também casaria dentro de
    # 'fc_labels:[...]' e de 'clim: { labels: [...] }', destruindo o eixo X
    # dos gráficos de previsão e de balanço hídrico.
    ini = html.find('indices:')
    if ini < 0:
        print('  ⚠ bloco indices: não encontrado — séries não atualizadas')
        return False
    fim = html.find('fc_labels:', ini)          # o bloco termina antes disto
    if fim < 0:
        fim = ini + 20000
    bloco = html[ini:fim]

    bloco = re.sub(r'labels:\[[^\]]+\]',
                   f'labels:[{",".join(series["labels"])}]', bloco, count=1)
    bloco = re.sub(r'nino34:\[[^\]]+\]',
                   f'nino34:[{",".join(series["nino34"])}]', bloco, count=1)
    bloco = re.sub(r'oni:\s*\[[^\]]+\]',
                   f'oni:   [{",".join(series["oni"])}]', bloco, count=1)
    bloco = re.sub(r'tsa:\s*\[[^\]]+\]',
                   f'tsa:   [{",".join(series["tsa"])}]', bloco, count=1)

    html = html[:ini] + bloco + html[fim:]

    # D.now — cards do Monitor ENSO
    lbl_n, val_n = latest_non_null(series, 'nino34')
    lbl_o, val_o = latest_non_null(series, 'oni')
    lbl_t, val_t = latest_non_null(series, 'tsa')

    lbl_n, val_n = _escolher_nino34_para_card_agora(wk_lbl, wk_val, lbl_n, val_n)

    TODAY = date.today()
    if val_n is not None and val_o is not None:
        new_now = (
            'now: {\n'
            f'    nino34: ["{label_fmt(lbl_n)}", {val_n}],  '
            f'// Atualizado {TODAY.strftime("%d/%m/%Y")} — PSL/NOAA\n'
            f'    oni:    ["{label_fmt(lbl_o)}", {val_o}],  '
            f'// ONI (média 3m)\n'
            f'    tsa:    ["{label_fmt(lbl_t) if lbl_t else "—"}", '
            f'{val_t if val_t is not None else 0}]  '
            f'// TSA mensal\n'
            '  }'
        )
        old_now = re.search(r'now:\s*\{[^}]+\}', html)
        if old_now:
            html = html[:old_now.start()] + new_now + html[old_now.end():]

    # RONI — objeto próprio, separado de `now:{...}`, deliberadamente:
    # é um trimestre (não um mês), atualiza numa cadência diferente
    # (~mensal, checado no cron dia 1-5), e misturar os dois campos num
    # só regex frágil (ver armadilha 2 do CLAUDE.md) arrisca corromper
    # ambos. Rótulo 'RONI (oficial NOAA)' — ver CLAUDE.md armadilha 9,
    # nunca confundir com `oni` acima ('ONI-aprox').
    # Se o fetch desta execução falhou (roni is None), NÃO mexe na
    # linha existente — preserva o último valor real, igual à
    # persistência de TSA/PDO/CHC-Preliminar (nunca grava null/zero
    # por cima de um dado bom só porque a fonte ficou fora do ar).
    if roni is not None:
        new_roni = (
            f"const RONI = {{ seas: '{roni['seas']}', ano: {roni['ano']}, "
            f"valor: {roni['valor']}, atualizado: '{TODAY.strftime('%d/%m/%Y')}' }};"
        )
        old_roni = re.search(r"const RONI = \{[^}]*\};", html)
        if old_roni:
            html = html[:old_roni.start()] + new_roni + html[old_roni.end():]
        else:
            print('  ⚠ const RONI não encontrado no HTML — card RONI '
                  'precisa ser adicionado manualmente uma vez (ver CLAUDE.md armadilha 9)')

    # Data de atualização
    dt_str = TODAY.strftime('%d/%m/%Y')
    html = re.sub(r"data:\s*'[\d/]+'",       f"data:       '{dt_str}'", html)
    html = re.sub(r"atualizado_em:\s*'[\d/]+'",
                  f"atualizado_em: '{dt_str}'", html)

    changed = html != original
    if changed:
        DASHBOARD.write_text(html, encoding='utf-8')
    return changed


# ══════════════════════════════════════════════════════
# HISTÓRICO — master_monthly.csv e serie_subst.csv
# ══════════════════════════════════════════════════════
MASTER_PATH = ROOT / 'data' / 'master_monthly.csv'
SUBST_PATH  = ROOT / 'data' / 'serie_subst.csv'


def backup_csv(path):
    """Cópia .bak antes de qualquer escrita — sobrescreve o backup anterior."""
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + '.bak'))


def _tsa_persistido(tsa):
    """Último valor real de TSA disponível no dict, ou (None, None)."""
    chaves = sorted(tsa.keys())
    if not chaves:
        return None, None
    ult = chaves[-1]
    return tsa[ult], ult


def _pdo_estimado(pdo):
    """Média dos últimos 3 meses reais de PDO disponíveis no dict, ou None.
    Nunca o último valor isolado — um mês atípico não deve ser propagado
    como se fosse a característica do ano inteiro."""
    chaves = sorted(pdo.keys())
    if len(chaves) < 3:
        return None
    return round(sum(pdo[k] for k in chaves[-3:]) / 3, 2)


def atualizar_master_monthly(nino34, tsa, pdo):
    """
    Acrescenta a data/master_monthly.csv os meses com Niño 3.4 real
    disponível que ainda não constam na série. TSA/PDO ausentes usam
    persistência/estimativa (nunca zero), sinalizadas no log. Colunas
    que não vêm dessa fonte (estações, clim, anom, soi) ficam vazias —
    não inventadas.
    """
    df = pd.read_csv(MASTER_PATH)
    existentes = set(zip(df['year'].astype(int), df['month'].astype(int)))
    oni = calc_oni(nino34)

    tsa_val, tsa_key   = _tsa_persistido(tsa)
    pdo_media3         = _pdo_estimado(pdo)

    novas = []
    for (y, m) in sorted(nino34.keys()):
        if (y, m) in existentes:
            continue

        if (y, m) in tsa:
            t = tsa[(y, m)]
        elif tsa_val is not None:
            t = tsa_val
            print(f"  ⚠ master_monthly {m:02d}/{y}: TSA sem dado real — "
                  f"persistência de {tsa_key[1]:02d}/{tsa_key[0]} ({t})")
        else:
            t = None

        if (y, m) in pdo:
            p = pdo[(y, m)]
        elif pdo_media3 is not None:
            p = pdo_media3
            print(f"  ⚠ master_monthly {m:02d}/{y}: PDO sem dado real — "
                  f"estimativa (média 3m) = {p}")
        else:
            p = None

        novas.append({
            'year': y, 'month': m, 'date': f'{y}-{m:02d}-01',
            'nino34': nino34[(y, m)], 'oni': oni.get((y, m)),
            'tsa': t, 'pdo': p,
        })

    if not novas:
        return 0

    backup_csv(MASTER_PATH)
    df = pd.concat([df, pd.DataFrame(novas)], ignore_index=True, sort=False)
    df = df.sort_values(['year', 'month']).reset_index(drop=True)
    df.to_csv(MASTER_PATH, index=False)
    return len(novas)


def corrigir_serie_subst(nino34, tsa, pdo):
    """
    Corrige em data/serie_subst.csv as linhas já existentes com
    nino34=tsa=pdo=0 — resíduo do bug em que um mês ausente no master
    era gravado como ENSO neutro. Atualiza os índices no lugar,
    preservando prec, date e fonte. É esta série que treina o SARIMAX.
    """
    df = pd.read_csv(SUBST_PATH)
    tsa_val, tsa_key = _tsa_persistido(tsa)
    pdo_media3       = _pdo_estimado(pdo)

    zeradas = df[(df['nino34'] == 0) & (df['tsa'] == 0) & (df['pdo'] == 0)]
    corrigidas = 0
    linhas_tocadas = []
    for idx, row in zeradas.iterrows():
        y, m = int(row['ano']), int(row['mes'])
        if (y, m) not in nino34:
            continue  # sem Niño 3.4 real tampouco — não mexe

        if (y, m) in tsa:
            t = tsa[(y, m)]
        elif tsa_val is not None:
            t = tsa_val
            print(f"  ⚠ serie_subst {m:02d}/{y}: TSA sem dado real — "
                  f"persistência de {tsa_key[1]:02d}/{tsa_key[0]} ({t})")
        else:
            t = row['tsa']

        if (y, m) in pdo:
            p = pdo[(y, m)]
        elif pdo_media3 is not None:
            p = pdo_media3
            print(f"  ⚠ serie_subst {m:02d}/{y}: PDO sem dado real — "
                  f"estimativa (média 3m) = {p}")
        else:
            p = row['pdo']

        df.at[idx, 'nino34'] = nino34[(y, m)]
        df.at[idx, 'tsa']    = t
        df.at[idx, 'pdo']    = p
        corrigidas += 1
        linhas_tocadas.append(f'{m:02d}/{y}')

    if corrigidas:
        backup_csv(SUBST_PATH)
        df.to_csv(SUBST_PATH, index=False)
        print(f"  ✅ serie_subst.csv: corrigidas {', '.join(linhas_tocadas)}")
    return corrigidas


# ══════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════
def main():
    TODAY = date.today()
    print(f"\n{'='*55}")
    print(f"  ÍNDICES OCEÂNICOS — {TODAY.strftime('%d/%m/%Y')}")
    print(f"{'='*55}")

    nino34, tsa, pdo = {}, {}, {}

    # 1. CPC sstoi.indices (fonte primária — formato simples)
    print("\n[1/6] CPC sstoi.indices (primário)…")
    try:
        text   = fetch('https://www.cpc.ncep.noaa.gov/data/indices/sstoi.indices')
        nino34 = parse_sstoi(text)
        last   = max(nino34)
        print(f"  ✅ Niño 3.4: {len(nino34)} meses | último: {last[1]:02d}/{last[0]}")
    except Exception as e:
        print(f"  ⚠ sstoi.indices falhou: {e} — tentando PSL…")
        try:
            text   = fetch('https://psl.noaa.gov/data/correlation/nina34.data')
            nino34 = parse_psl_anual(text)
            last   = max(nino34)
            print(f"  ✅ PSL nina34: {len(nino34)} meses | último: {last[1]:02d}/{last[0]}")
        except Exception as e2:
            print(f"  ❌ Ambas as fontes falharam: {e2}")

    # 2. PSL tsa.data
    print("\n[2/6] PSL tsa.data…")
    try:
        text = fetch('https://psl.noaa.gov/data/correlation/tsa.data')
        tsa  = parse_psl_anual(text)
        last_t = max(tsa)
        print(f"  ✅ TSA: {len(tsa)} meses | último: {last_t[1]:02d}/{last_t[0]}")
    except Exception as e:
        print(f"  ⚠ TSA indisponível (não crítico): {e}")

    if not nino34:
        print("\n❌ Sem dados de Niño 3.4 — abortando")
        return 1

    # 3. PSL pdo.data
    print("\n[3/6] PSL pdo.data…")
    try:
        text = fetch('https://psl.noaa.gov/data/correlation/pdo.data')
        pdo  = parse_psl_anual(text)
        last_p = max(pdo)
        print(f"  ✅ PDO: {len(pdo)} meses | último: {last_p[1]:02d}/{last_p[0]}")
    except Exception as e:
        print(f"  ⚠ PDO indisponível (não crítico): {e}")

    # 4. CPC semanal — 4 regiões (Niño1+2, Niño3, Niño3.4, Niño4)
    print("\n[4/6] CPC wksst9120.for (semanal, 4 regiões)…")
    wk_lbl, wk_regioes, wk_val = None, None, None
    try:
        text = fetch('https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for')
        wk_lbl, wk_regioes = parse_wksst(text)
        if wk_regioes is not None:
            wk_val = wk_regioes['nino34']['anom']
            resumo = ' | '.join(
                f"{r}={wk_regioes[r]['anom']:+.2f}°C" for r in WKSST_REGIOES)
            print(f"  ✅ Semanal ({wk_lbl}): {resumo}")
    except Exception as e:
        print(f"  ⚠ Semanal indisponível: {e}")

    # 5. CPC RONI (trimestral, índice oficial — distinto do ONI-aprox)
    print("\n[5/7] CPC RONI.ascii.txt…")
    roni = None
    try:
        text = fetch(RONI_URL)
        seas, yr, val = parse_roni(text)
        if val is not None:
            roni = {'seas': seas, 'ano': yr, 'valor': val}
            print(f"  ✅ RONI: {seas}/{yr} → {val:+.2f}°C "
                  f"(oficial NOAA — não é o mesmo número que nosso ONI-aprox)")
    except Exception as e:
        print(f"  ⚠ RONI indisponível: {e}")

    # 6. CPC — tabela oficial de probabilidades de fase ENSO por trimestre
    # (ver CPC_PROBABILIDADES_URL — já automatizada desde a Fase
    # ENSO-DADOS; synopsis/narrativa continuam manuais, ver
    # lembrete_cpc_thursday.yml/lembrete_iri_thursday.yml).
    print("\n[6/9] CPC — probabilidades de fase ENSO por trimestre…")
    cpc_probabilidades = {}
    cpc_prob_emissao = None
    try:
        text = fetch(CPC_PROBABILIDADES_URL)
        cpc_probabilidades = parse_cpc_probabilidades(text)
        cpc_prob_emissao = extrair_emissao_cpc_probabilidades(text)
        if cpc_probabilidades:
            print(f"  ✅ CPC probabilidades: {len(cpc_probabilidades)} trimestre(s) "
                  f"válido(s) na tabela oficial (emissão: {cpc_prob_emissao or '—'})")
        else:
            print("  ⚠ CPC probabilidades: página buscada, mas nenhuma linha válida "
                  "extraída, OU o ano de cada trimestre não pôde ser alinhado com "
                  "segurança (estrutura pode ter mudado) — CPC_IRI.cpc preservado")
    except Exception as e:
        print(f"  ⚠ CPC probabilidades indisponível: {e} — CPC_IRI.cpc preservado")

    # 7. CPC — metadados do Diagnostic Discussion (data de emissão, próxima
    # emissão, status categórico do Alert System — NUNCA a Synopsis, ver
    # comentário em parse_cpc_diagnostic_discussion_metadata). Nova nesta
    # fase (ENSO-AUTO, 19/10/2026) — verificado contra a página real.
    print("\n[7/9] CPC — metadados do Diagnostic Discussion (data/status)…")
    cpc_dd_metadados = {}
    try:
        text = fetch(CPC_DIAGNOSTIC_DISCUSSION_URL)
        cpc_dd_metadados = parse_cpc_diagnostic_discussion_metadata(text)
        if cpc_dd_metadados.get('emissao'):
            print(f"  ✅ Diagnostic Discussion: emissão {cpc_dd_metadados['emissao']} · "
                  f"status {cpc_dd_metadados.get('alert_status', '—')} · "
                  f"próxima {cpc_dd_metadados.get('proxima', '—')}")
        else:
            print("  ⚠ Diagnostic Discussion: data de emissão não encontrada "
                  "(estrutura da página pode ter mudado) — metadados preservados")
    except Exception as e:
        print(f"  ⚠ Diagnostic Discussion indisponível: {e} — metadados preservados")

    # 8. IRI — mecanismo semiautomático de detecção de mudança (best-effort,
    # nunca bloqueia o job, nunca extrai probabilidade — ver comentário em
    # verificar_mudanca_pagina_iri). Resultado é só um SINAL pro lembrete
    # mensal (lembrete_iri_thursday.yml), nunca substitui a extração manual.
    print("\n[8/9] IRI — verificação de mudança na página (best-effort)…")
    hash_anterior = None
    try:
        if IRI_HASH_PATH.exists():
            hash_anterior = IRI_HASH_PATH.read_text(encoding='utf-8').strip() or None
    except Exception:
        hash_anterior = None

    iri_html = None
    try:
        iri_html = fetch(IRI_URL, timeout=20)
    except Exception as e:
        print(f"  ⚠ IRI não alcançável deste runner: {e} — hash preservado, sem sinalização")

    hash_novo, iri_mudou = verificar_mudanca_pagina_iri(iri_html, hash_anterior)
    if hash_novo and hash_novo != hash_anterior:
        IRI_HASH_PATH.parent.mkdir(parents=True, exist_ok=True)
        IRI_HASH_PATH.write_text(hash_novo, encoding='utf-8')
    if iri_mudou:
        print("  🔔 Conteúdo da página do IRI mudou desde a última checagem — "
              "possível nova emissão; extração continua manual (ver Issue mensal)")
    elif iri_html and hash_anterior is None:
        print("  ℹ primeira checagem — hash inicial gravado, nada a comparar ainda")
    elif iri_html:
        print("  ✅ sem mudança detectada na página do IRI desde a última checagem")

    # 9. Histórico — master_monthly.csv e serie_subst.csv
    print("\n[9/9] Atualizando histórico (master_monthly.csv / serie_subst.csv)…")
    n_master = atualizar_master_monthly(nino34, tsa, pdo)
    n_serie  = corrigir_serie_subst(nino34, tsa, pdo)
    print(f"  master_monthly.csv: {n_master} mês(es) adicionados")
    print(f"  serie_subst.csv: {n_serie} linha(s) corrigidas")

    # Montar e atualizar
    series  = build_series(nino34, tsa)
    changed = update_html(series, wk_lbl, wk_val, roni)

    if cpc_probabilidades:
        html = DASHBOARD.read_text(encoding='utf-8')
        novo_html, mudou_cpc = atualizar_cpc_probabilidades_no_html(
            html, cpc_probabilidades, emissao=cpc_prob_emissao)
        if mudou_cpc:
            DASHBOARD.write_text(novo_html, encoding='utf-8')
            changed = True

    if cpc_dd_metadados.get('emissao'):
        html = DASHBOARD.read_text(encoding='utf-8')
        novo_html, mudou_dd = atualizar_cpc_diagnostic_discussion_metadata_no_html(
            html, cpc_dd_metadados)
        if mudou_dd:
            DASHBOARD.write_text(novo_html, encoding='utf-8')
            changed = True

    lbl_n, val_n = latest_non_null(series, 'nino34')
    lbl_o, val_o = latest_non_null(series, 'oni')
    lbl_t, val_t = latest_non_null(series, 'tsa')

    print(f"\n  Niño 3.4 : {val_n:+.2f}°C ({label_fmt(lbl_n)})")
    print(f"  ONI-aprox: {val_o:+.2f}°C ({label_fmt(lbl_o)}) — média 3m do Niño 3.4 bruto")
    if val_t:
        print(f"  TSA      : {val_t:+.2f}°C ({label_fmt(lbl_t)})")
    if wk_val:
        print(f"  Semanal  : {wk_val:+.2f}°C ({wk_lbl})")
    if roni:
        print(f"  RONI     : {roni['valor']:+.2f}°C ({roni['seas']}/{roni['ano']}) — oficial NOAA")

    print(f"\n  Alterações: {'sim' if changed else 'nenhuma'}")
    print(f"{'='*55}\n")
    return 0


if __name__ == '__main__':
    sys.exit(main())
