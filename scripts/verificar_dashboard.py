#!/usr/bin/env python3
"""
verificar_dashboard.py — Verificação de integridade antes de publicar
Sinobras Florestal · executado pelo GitHub Actions após os scripts de atualização

Falha (exit 1) se encontrar inconsistência, impedindo que um dashboard
quebrado chegue ao ar. Checa:

  1. Sintaxe: balanço de chaves do objeto D
  2. Comprimento: todas as séries do horizonte têm 12 elementos
  3. Alinhamento: climatologia e ETP batem com o mês de cada rótulo do eixo X
  4. Coerência física: o balanço hídrico é reprodutível a partir da
     precipitação projetada no mesmo eixo
  5. Monitor ENSO: labels e séries de índices com o mesmo comprimento
  6. Plausibilidade física: nino34/oni/tsa (D.now e série completa) não
     excedem ~5°C em módulo — acima disso é SST absoluta, não anomalia
  7. Continuidade: data/serie_subst.csv não pode ter mês faltando entre
     o primeiro registro e o mês anterior ao atual — um buraco vira erro
     silencioso de alinhamento assim que algum código usar .shift()
     posicional sobre a série (o regressor de um mês passa a vir de
     outro mês). Checa até o mês anterior ao atual, não só até o último
     registro existente — uma lacuna que fica "pendurada" no fim da
     série (a série simplesmente parou de crescer) é tão perigosa
     quanto um buraco no meio, e ficaria invisível se só olhássemos
     entre primeiro e último registro.
  8. RONI vs ONI-aprox: se o card RONI existir no dashboard, os rótulos
     precisam deixar claro que é uma métrica diferente do ONI-aprox
     (média 3m do Niño 3.4 bruto) — reprova se o card ONI ficar com
     rótulo ambíguo ("ONI" puro) ao lado do RONI (ver CLAUDE.md
     armadilha 9).
"""

import re, sys, json
from datetime import date
from pathlib import Path
import numpy as np
import pandas as pd

import proveniencia_indices as prov

ROOT      = Path(__file__).parent.parent
DASHBOARD = ROOT / 'docs' / 'index.html'
SERIE_SUBST = ROOT / 'data' / 'serie_subst.csv'

CLIM = {1:267.3, 2:282.3, 3:308.4, 4:220.4, 5:83.1,  6:15.6,
        7:6.4,   8:10.4,  9:41.7, 10:119.7, 11:159.2, 12:199.9}
ETP  = {1:116, 2:110, 3:115, 4:118, 5:125, 6:112,
        7:107, 8:120, 9:138, 10:145, 11:138, 12:122}
MESES_CAP = {'Jan':1,'Fev':2,'Mar':3,'Abr':4,'Mai':5,'Jun':6,
             'Jul':7,'Ago':8,'Set':9,'Out':10,'Nov':11,'Dez':12}
CAD = 100

falhas = []


def erro(msg):
    falhas.append(msg)
    print(f'  ❌ {msg}')


def ok(msg):
    print(f'  ✅ {msg}')


_MESES_PT = {'jan': 1, 'fev': 2, 'mar': 3, 'abr': 4, 'mai': 5, 'jun': 6,
             'jul': 7, 'ago': 8, 'set': 9, 'out': 10, 'nov': 11, 'dez': 12}


def _dias_desde_data_pt(texto):
    """Extrai 'DD/mmm' (mês abreviado em pt-BR, 3 letras) de um texto
    livre e um ano de 4 dígitos (em qualquer posição do mesmo texto —
    cobre tanto 'DD/mmm/AAAA' quanto 'mmm/AAAA (DD/mmm)', os dois
    formatos já usados em CPC_IRI._meta) e retorna quantos dias se
    passaram até hoje, ou None se não conseguir extrair com confiança.
    Nunca lança exceção — defasagem é só aviso, nunca motivo de STOP."""
    m_dia_mes = re.search(r'(\d{1,2})/([a-zç]{3})\b', texto.lower())
    m_ano = re.search(r'(20\d{2})', texto)
    if not m_dia_mes or not m_ano:
        return None
    dia = int(m_dia_mes.group(1))
    mes = _MESES_PT.get(m_dia_mes.group(2))
    ano = int(m_ano.group(1))
    if mes is None:
        return None
    try:
        data = date(ano, mes, dia)
    except ValueError:
        return None
    return (date.today() - data).days


def _meses_atras_rotulo_mmm_aaaa(texto):
    """Extrai 'mmm/AAAA' (ex.: 'set/2026', formato de D.now.*[0] gerado
    por update_indices.py::label_fmt) e retorna quantos meses de
    calendário atrás esse mês está do mês atual (0 = mês atual, 1 = mês
    anterior, etc.) — nunca lança exceção. Medir em MESES DE CALENDÁRIO,
    não em dias: os índices mensais do CPC/PSL publicam o valor do mês
    M só no início do mês M+1 — "1 mês atrás" é o estado NORMAL durante
    quase todo o mês corrente, não uma defasagem real; só >=2 meses
    indica falha recorrente do workflow (ex.: o bug real de 01-12/
    out/2026, achado na Fase ENSO-DADOS)."""
    if not texto:
        return None
    m = re.match(r'([a-zç]{3})/(\d{4})$', texto.strip().lower())
    if not m:
        return None
    mes = _MESES_PT.get(m.group(1))
    if mes is None:
        return None
    ano = int(m.group(2))
    hoje = date.today()
    return (hoje.year - ano) * 12 + (hoje.month - mes)


def checar_continuidade(serie, ate=None):
    """
    Retorna a lista de meses 'MM/AAAA' faltando entre o primeiro
    registro de `serie` (DataFrame com colunas 'ano'/'mes') e `ate`
    (tupla ano, mes) — por padrão, o mês anterior ao atual. Lista
    vazia = série contínua.

    Checar só até o ÚLTIMO REGISTRO EXISTENTE (em vez de até o mês
    anterior ao atual) deixaria passar batido uma lacuna "pendurada"
    no fim da série — ex.: CHIRPS cobre só parte de um pedido e o
    fallback falha para o resto, então a série simplesmente para de
    crescer sem nenhum registro "depois" para delimitar o buraco.
    Não tem como reproduzir esse caso testando só "entre primeiro e
    último" (ver tests/test_fetch_fallback.py, CoberturaParcialTestCase).

    Extraída para função própria para poder ser testada direto, sem
    precisar rodar main() inteiro contra um docs/index.html real.
    """
    if ate is None:
        hoje = date.today()
        ate = (hoje.year, hoje.month - 1) if hoje.month > 1 else (hoje.year - 1, 12)

    existentes = set(zip(serie['ano'].astype(int), serie['mes'].astype(int)))
    y, m = int(serie['ano'].iloc[0]), int(serie['mes'].iloc[0])
    y_fim, m_fim = ate
    lacunas = []
    while (y, m) <= (y_fim, m_fim):
        if (y, m) not in existentes:
            lacunas.append(f'{m:02d}/{y}')
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return lacunas


_TRI_SEQ = ['JFM', 'FMA', 'MAM', 'AMJ', 'MJJ', 'JJA', 'JAS', 'ASO', 'SON', 'OND', 'NDJ', 'DJF']

# Os 8 cenários que o Comparativo efetivamente lê (docs/index.html,
# rebuildCmpTri()/buildCmpTable(), mesma constante SARIMAX_SCENARIOS do
# JS) — EXIGIDOS por nome, nunca derivados de list(trimestres.keys()).
# Derivar da lista de chaves PRESENTES mascararia justamente o caso que
# mais importa (ENSO-DADOS Fase C.1, Correção A): se um cenário inteiro
# falta (ex.: só 'Neutro' existe, ou 'IRI_mean' nunca foi escrito),
# list(trimestres.keys()) devolveria só os cenários que sobraram, e o
# trimestre passaria "completo" avaliando um subconjunto incompleto.
_SARIMAX_SCENARIOS = ['El Nino forte', 'El Nino moderado', 'El Nino fraco', 'Neutro',
                       'La Nina fraca', 'La Nina moderada', 'La Nina forte', 'IRI_mean']


def _decode_trimestre(season):
    """
    Porta Python de decodeTrimestre() (docs/index.html) — mesma
    convenção de scripts/update_dashboard.py::_tri_nome() (ano do mês
    CENTRAL, virada dez→jan por wraparound). Os 12 códigos trimestrais
    do CPC (JFM..DJF) são uma bijeção com o mês inicial (1-12): nunca
    ambíguos mesmo com letras repetidas (J/M/A), pois a sequência de 3
    letras consecutivas já identifica o mês inicial de forma única.
    Retorna lista de 3 (ano, mês) ou None se a chave não for
    decodificável (nem 'SSS/AA' nem uma sigla trimestral reconhecida).
    """
    m = re.match(r'^([A-Za-z]{3})/(\d{2})$', (season or '').strip())
    if not m:
        return None
    try:
        i = _TRI_SEQ.index(m.group(1).upper())
    except ValueError:
        return None
    mes_ini = i + 1
    mes_cen = 1 if mes_ini == 12 else mes_ini + 1
    ano_cen = 2000 + int(m.group(2))
    ano_ini = ano_cen - 1 if mes_cen == 1 else ano_cen
    meses, y, mo = [], ano_ini, mes_ini
    for _ in range(3):
        meses.append((y, mo))
        mo += 1
        if mo > 12:
            mo, y = 1, y + 1
    return meses


def _ler_array_cpc_iri(nome_campo, texto_bloco):
    """
    Lê um array JS tipo 'en:[1.0,null,2.0]' de dentro de um bloco já
    delimitado (ex.: o conteúdo de `cpc:{...}` ou `iri:{...}`). Cada
    item vira float, ou None para o literal 'null' do JS, ou a própria
    string crua quando não é nem float nem 'null' (deixa o chamador
    decidir se isso é erro — nunca lança aqui). Retorna None se o campo
    não existir no bloco.
    """
    m = re.search(rf'{nome_campo}:\s*\[([^\]]*)\]', texto_bloco)
    if not m:
        return None
    crus = [v.strip() for v in m.group(1).split(',')] if m.group(1).strip() else []
    out = []
    for v in crus:
        if v == 'null':
            out.append(None)
        else:
            try:
                out.append(float(v))
            except ValueError:
                out.append(v)
    return out


def verificar_cpc_sarimax(h):
    """
    Item 7 — compatibilidade CPC_IRI.seasons × SARIMAX_DATA (ENSO-DADOS
    Fase C). Dividido em 3 barreiras:

    7a (BLOQUEANTE) — integridade ESTRUTURAL de CPC_IRI, delimitada ao
    bloco `const CPC_IRI = {...};` (nunca regex global — CLAUDE.md
    armadilha 2; evita também casar "nino_seasons" por substring de
    "seasons", já que `nino_seasons` é outro array trimestral, não
    relacionado a esta checagem): bloco ausente/ilegível; `seasons`
    ausente/vazio/inválido/duplicado; arrays `cpc`/`iri` ausentes;
    comprimento diferente de `seasons`; valor não numérico e diferente
    de `null`; valor fora de 0-100.

    7b (INFORMATIVO) — cobertura regional (SARIMAX_DATA): a existência
    da chave do trimestre NÃO comprova previsão regional completa —
    scripts/update_dashboard.py preenche com climatologia os meses de
    um trimestre que caem fora de `SARIMAX_DATA.labels_win` (contribuem
    para `mean` mas com lo=hi=0 nesse mês), então um trimestre parcial
    pode legitimamente ter mean > hi sem ser corrupção de dado (caso
    real observado: ASO/27, cenário Neutro, mean=161.7 > hi=115.1 — só
    ago/27 está em labels_win). Por isso cobertura incompleta nunca é
    erro aqui, só aviso — a aba Comparativo (docs/index.html,
    estadoTrimestre()) já trata isso sem quebrar.

    7c (BLOQUEANTE) — o que ainda pode gerar exceção JS nos caminhos
    efetivamente exibidos: SARIMAX_DATA malformado; campos mean/lo/hi
    ausentes/não numéricos num trimestre que EXISTE; a função
    estadoTrimestre() (e seu uso em rebuildCmpTri()/buildCmpTable())
    ausente do HTML — sem ela, os avisos de 7b deixam de ser
    informativos e voltam a ser risco real de quebra; e valor
    estruturalmente inválido (lo/mean/hi) num trimestre cujos 3 meses
    estão TODOS em labels_win — aí, e só aí, não há explicação de
    preenchimento climatológico, então é bloqueante.

    Comprimentos iguais entre seasons/cpc/iri NÃO comprovam associação
    temporal correta (só integridade estrutural) — nunca afirmado como
    tal nas mensagens desta função.

    Extraída para função própria para poder ser testada direto, sem
    precisar rodar main() inteiro contra um docs/index.html real (mesmo
    motivo de checar_continuidade()).
    """
    ini_cpc = h.find('const CPC_IRI = {')
    fim_cpc = h.find('\n};', ini_cpc) + 3 if ini_cpc >= 0 else -1
    bloco_cpc = h[ini_cpc:fim_cpc] if ini_cpc >= 0 and fim_cpc > ini_cpc + 3 else ''

    if not bloco_cpc:
        erro('const CPC_IRI não encontrado ou ilegível no HTML')
        return

    m_seasons = re.search(r'\n\s*seasons:\s*\[([^\]]*)\]', bloco_cpc)
    pedidos = ([v.strip().strip("'\"") for v in m_seasons.group(1).split(',') if v.strip()]
               if m_seasons else [])

    if not pedidos:
        erro('CPC_IRI.seasons ausente, vazio ou ilegível')
        return
    if len(set(pedidos)) != len(pedidos):
        dup = sorted({x for x in pedidos if pedidos.count(x) > 1})
        erro('CPC_IRI.seasons com trimestre(s) duplicado(s): ' + ', '.join(dup))
        return
    invalidos_fmt = [s for s in pedidos if _decode_trimestre(s) is None]
    if invalidos_fmt:
        erro('CPC_IRI.seasons com trimestre(s) em formato inválido (não decodificável): '
             + ', '.join(invalidos_fmt))
        return

    # 7a — arrays cpc/iri: presença, comprimento, tipo, faixa 0-100
    m_cpc_blk = re.search(r'\n\s*cpc:\{([^}]*)\}', bloco_cpc)
    m_iri_blk = re.search(r'\n\s*iri:\{([^}]*)\}', bloco_cpc)
    arrays_ok = True
    for nome_grupo, m_blk in (('cpc', m_cpc_blk), ('iri', m_iri_blk)):
        if not m_blk:
            erro(f'CPC_IRI.{nome_grupo} ausente')
            arrays_ok = False
            continue
        for campo in ('en', 'neu', 'ln'):
            arr = _ler_array_cpc_iri(campo, m_blk.group(1))
            if arr is None:
                erro(f'CPC_IRI.{nome_grupo}.{campo} ausente')
                arrays_ok = False
                continue
            if len(arr) != len(pedidos):
                erro(f'CPC_IRI.{nome_grupo}.{campo} com comprimento {len(arr)} '
                     f'≠ seasons ({len(pedidos)}) — risco de probabilidade no trimestre errado')
                arrays_ok = False
            nao_numericos = [v for v in arr if v is not None and not isinstance(v, float)]
            if nao_numericos:
                erro(f'CPC_IRI.{nome_grupo}.{campo} com valor não numérico e diferente de '
                     f'null: {nao_numericos}')
                arrays_ok = False
            fora_de_faixa = [v for v in arr if isinstance(v, float) and not (0 <= v <= 100)]
            if fora_de_faixa:
                erro(f'CPC_IRI.{nome_grupo}.{campo} com valor fora do intervalo 0-100: '
                     f'{fora_de_faixa}')
                arrays_ok = False
    if arrays_ok:
        ok(f'CPC_IRI.seasons/cpc/iri estruturalmente consistentes ({len(pedidos)} '
           f'trimestres, sem duplicados, arrays com mesmo comprimento — isso NÃO garante '
           f'associação temporal correta, só integridade estrutural)')

    # 7c.1 — a correção JS precisa estar presente, senão 7b (abaixo) é só
    # um aviso sobre um risco que na verdade segue sem proteção nenhuma.
    guarda_presente = 'function estadoTrimestre' in h
    if not guarda_presente:
        erro('função estadoTrimestre() não encontrada no HTML — sem ela, '
             'rebuildCmpTri()/buildCmpTable() podem voltar a acessar SARIMAX_DATA sem '
             'proteção e quebrar a aba Comparativo com trimestre parcial/indisponível')
    else:
        for nome_fn in ('rebuildCmpTri', 'buildCmpTable'):
            ini_fn = h.find(f'function {nome_fn}(')
            fim_fn = h.find('\nfunction ', ini_fn + 1) if ini_fn >= 0 else -1
            corpo = h[ini_fn:fim_fn if fim_fn > ini_fn else ini_fn + 4000] if ini_fn >= 0 else None
            if corpo is None:
                erro(f'{nome_fn}() não encontrada no HTML')
            elif 'estadoTrimestre(' not in corpo:
                erro(f'{nome_fn}() não usa estadoTrimestre() — guarda de disponibilidade '
                     f'regional pode ter sido removida/contornada, risco de exceção JS com '
                     f'trimestre parcial/indisponível')

    # 7b/7c.2 — cobertura regional (SARIMAX_DATA)
    msd = re.search(r'const SARIMAX_DATA\s*=\s*(\{.*?\});\n', h, re.DOTALL)
    if not msd:
        erro('const SARIMAX_DATA não encontrado — não é possível avaliar cobertura '
             'regional (7c)')
        return
    try:
        sd = json.loads(msd.group(1))
        tri_por_cenario = sd['trimestres']
        labels_win = set(sd['labels_win'])
    except Exception as ex:
        erro(f'SARIMAX_DATA malformado: {ex}')
        return
    if not isinstance(tri_por_cenario, dict) or not labels_win:
        erro('SARIMAX_DATA malformado: trimestres ou labels_win vazio')
        return

    # Correção A (ENSO-DADOS Fase C.1) — BLOQUEANTE: os 8 cenários são
    # exigidos por nome. Um cenário inteiro ausente invalida a avaliação
    # de disponibilidade regional para TODOS os trimestres (o JS também
    # nunca classificaria nenhum como completo nesse caso — ver
    # SARIMAX_SCENARIOS em docs/index.html) — interrompe aqui, analisar
    # trimestre a trimestre sobre uma base incompleta não teria sentido.
    cenarios_ausentes = [sc for sc in _SARIMAX_SCENARIOS if sc not in tri_por_cenario]
    if cenarios_ausentes:
        erro('SARIMAX_DATA.trimestres sem os cenários obrigatórios do Comparativo: '
             + ', '.join(cenarios_ausentes) + ' — nenhum trimestre pode ser avaliado '
             'como previsão regional completa sem os 8 cenários')
        return
    cenarios = _SARIMAX_SCENARIOS

    def _trimestre_de(sc, s):
        """Acesso defensivo a tri_por_cenario[sc][s] — nunca lança
        mesmo com cenário/trimestre malformado (não-dict, null, tipo
        errado); devolve None quando não dá pra extrair um objeto
        válido, para o chamador decidir sem try/except espalhado."""
        dict_sc = tri_por_cenario.get(sc)
        if not isinstance(dict_sc, dict):
            return None
        v = dict_sc.get(s)
        return v if isinstance(v, dict) else None

    def _campo_numerico(v, campo):
        x = v.get(campo) if isinstance(v, dict) else None
        return isinstance(x, (int, float)) and not isinstance(x, bool)

    indisponiveis, parciais, invalidos = [], [], []
    for s in pedidos:
        meses = _decode_trimestre(s)  # já validado acima, nunca None aqui
        objetos = {sc: _trimestre_de(sc, s) for sc in cenarios}
        existe_em_todos = all(objetos[sc] is not None for sc in cenarios)
        if not existe_em_todos:
            indisponiveis.append(s)
            continue
        campos_ok = all(
            _campo_numerico(objetos[sc], 'mean')
            and _campo_numerico(objetos[sc], 'lo')
            and _campo_numerico(objetos[sc], 'hi')
            for sc in cenarios
        )
        if not campos_ok:
            erro(f'CPC_IRI.seasons "{s}" existe em SARIMAX_DATA.trimestres mas com campos '
                 f'mean/lo/hi ausentes, nulos ou não numéricos em ao menos um cenário — '
                 f'risco de exceção JS')
            invalidos.append(s)
            continue
        meses_lbl = [f'{m:02d}/{str(y)[2:]}' for y, m in meses]
        if any(lbl not in labels_win for lbl in meses_lbl):
            parciais.append(s)
            continue
        # candidato a PREVISAO_COMPLETA — só aqui violação estrutural é
        # bloqueante: não há preenchimento climatológico que a explique.
        estrutural_ok = all(
            objetos[sc]['lo'] >= 0
            and objetos[sc]['hi'] >= objetos[sc]['lo']
            and objetos[sc]['lo'] <= objetos[sc]['mean'] <= objetos[sc]['hi']
            for sc in cenarios
        )
        if not estrutural_ok:
            erro(f'CPC_IRI.seasons "{s}" classificado como previsão regional completa '
                 f'(todos os 3 meses em labels_win) mas com valores estruturalmente '
                 f'inválidos (lo/mean/hi) em ao menos um cenário — não explicado por '
                 f'preenchimento climatológico')
            invalidos.append(s)

    if indisponiveis:
        print('  ⚠ trimestre(s) de CPC_IRI.seasons sem previsão regional SARIMAX '
              '(ausentes de SARIMAX_DATA.trimestres): ' + ', '.join(indisponiveis))
    if parciais:
        print('  ⚠ trimestre(s) de CPC_IRI.seasons com previsão regional PARCIAL (ao '
              'menos um mês fora de labels_win, preenchido com climatologia): '
              + ', '.join(parciais))
    if not indisponiveis and not parciais and not invalidos:
        ok(f'trimestres do Comparativo com cobertura regional completa e '
           f'estruturalmente válida ({len(pedidos)} seasons)')
    elif not invalidos and guarda_presente:
        ok('cobertura regional parcial/indisponível tratada (ver avisos acima) — '
           'nenhuma inconsistência estrutural bloqueante')


def solve_bh(prec, etp, cad=CAD, tol=1e-3, it=200):
    arm = cad
    for _ in range(it):
        prev, res = arm, []
        for P, E in zip(prec, etp):
            a = min(cad, prev + P - E) if P >= E else max(0, prev * np.exp(-(E - P) / cad))
            res.append(round(a, 2)); prev = a
        if abs(res[-1] - arm) < tol:
            break
        arm = res[-1]
    return res


def main(pular_continuidade_serie_subst=False):
    print(f"\n{'='*58}")
    print('  VERIFICAÇÃO DE INTEGRIDADE DO DASHBOARD')
    print(f"{'='*58}\n")

    if not DASHBOARD.exists():
        print('  ❌ docs/index.html não encontrado')
        return 1
    h = DASHBOARD.read_text(encoding='utf-8')

    # ── 1. estrutura do objeto D ────────────────────────────────────────
    i = h.find('\nconst D = {')
    e = h.find('\n};', i) + 3
    if i < 0 or e < 3:
        erro('objeto D não encontrado')
        return 1
    D = h[i:e]
    if D.count('{') != D.count('}'):
        erro(f'chaves desequilibradas em D ({D.count("{")} abre, {D.count("}")} fecha)')
    else:
        ok('estrutura do objeto D íntegra')

    # ── 2. eixo X do horizonte ──────────────────────────────────────────
    m = re.search(r'fc_labels:\[([^\]]+)\]', h)
    if not m:
        erro('fc_labels ausente')
        return 1
    lbl = [v.strip().strip('"\'') for v in m.group(1).split(',')]
    if len(lbl) != 12:
        erro(f'fc_labels tem {len(lbl)} rótulos — deveria ter 12. '
             'Provável substituição indevida por outro script.')
        return 1
    ok(f'fc_labels com 12 rótulos ({lbl[0]} → {lbl[-1]})')

    try:
        mh = [int(x[:2]) for x in lbl]
    except ValueError:
        erro(f'fc_labels em formato inesperado: {lbl[:3]}')
        return 1
    esp_clim = [CLIM[x] for x in mh]
    esp_etp  = [ETP[x]  for x in mh]

    # ── 3. séries alinhadas ao eixo ─────────────────────────────────────
    def serie(pat, txt=h):
        mm = re.search(pat, txt, re.DOTALL)
        return [float(v.strip().strip('"\'')) for v in mm.group(1).split(',')] if mm else None

    i_ch = h.find('BH_CLIM_HYD = {')
    blk  = h[i_ch:i_ch + 900] if i_ch > 0 else ''

    for nome, vals, esperado in [
        ('fc_clim',         serie(r'fc_clim:\[([^\]]+)\]'),               esp_clim),
        ('CLIM_WIN',        serie(r'const CLIM_WIN\s*=\s*\[([^\]]+)\]'),  esp_clim),
        ('ETP do gráfico',  serie(r'const etp = \[([^\]]+)\];'),          esp_etp),
        ('BH_CLIM_HYD.p',   serie(r'p:\s*\[([^\]]+)\]', blk),             esp_clim),
        ('BH_CLIM_HYD.etp', serie(r'etp:\s*\[([^\]]+)\]', blk),           esp_etp),
    ]:
        if vals is None:
            erro(f'{nome}: não encontrado')
        elif len(vals) != 12:
            erro(f'{nome}: {len(vals)} elementos (esperado 12)')
        elif not all(abs(a - b) <= 0.6 for a, b in zip(vals, esperado)):
            erro(f'{nome}: desalinhado do eixo X')
        else:
            ok(f'{nome} alinhado ao eixo')

    # ── 4. coerência do balanço hídrico ─────────────────────────────────
    # Fase ENSO-CI — achado real: o delimitador buscado abaixo usava
    # '── BALANÇO HÍDRICO COMP' (traço simples), mas o cabeçalho real
    # no HTML é '══ BALANÇO HÍDRICO COMPARATIVO' (traço duplo — padrão
    # do projeto para headers de SEÇÃO principal: MONITOR/PREVISÃO/
    # CLIMA/PLANO usam o mesmo traço duplo; só headers de bloco LOCAL,
    # como "── CONSTANTES ──", usam traço simples). `.find()` com o
    # delimitador errado sempre retornava -1, e `h[bh_s:-1]` acabava
    # incluindo quase o arquivo inteiro (tudo menos o último caractere)
    # em `bh` — "funcionava por acidente" só porque os padrões buscados
    # depois (prec/arm por cenário, BH.clim) continuavam únicos dentro
    # dessa fatia enorme. Corrigido para o traço real (══), confirmado
    # contra o docs/index.html real: a fatia cai de ~127k para ~26k
    # caracteres (o bloco BH de verdade) e os mesmos padrões continuam
    # sendo encontrados — ver tests/test_regressao_cientifica_enso_ci.py.
    bh_s = h.find('const BH = {')
    bh_e = h.find('\n\n/* ══ BALANÇO HÍDRICO COMP', bh_s)
    bh   = h[bh_s:bh_e] if bh_s > 0 else ''
    etp_h = esp_etp

    cenarios = ['El Nino forte','El Nino moderado','El Nino fraco','Neutro',
                'La Nina fraca','La Nina moderada','La Nina forte']
    incoerentes = []
    for sc in cenarios:
        mp = re.search(rf'"{re.escape(sc)}":\{{prec:\[([^\]]+)\]', h)
        ma = re.search(rf"'{re.escape(sc)}':\s*\{{.*?arm:\s*(\[[^\]]+\])", bh, re.DOTALL)
        if not mp or not ma:
            erro(f'{sc}: prec ou arm ausente')
            continue
        prec = [float(v) for v in mp.group(1).split(',')]
        arm  = json.loads(ma.group(1))
        if len(prec) != 12 or len(arm) != 12:
            erro(f'{sc}: prec={len(prec)} arm={len(arm)} (esperado 12)')
            continue
        dif = max(abs(a - b) for a, b in zip(arm, solve_bh(prec, etp_h)))
        if dif > 1.0:
            incoerentes.append(f'{sc} ({dif:.0f} mm)')
    if incoerentes:
        erro('balanço hídrico não reproduz a precipitação: ' + ', '.join(incoerentes))
    else:
        ok(f'balanço hídrico coerente nos {len(cenarios)} cenários')

    # ── 5. climatologia da aba Clima ────────────────────────────────────
    ml = re.search(r"clim:.*?labels:\s*\[([^\]]+)\]", bh, re.DOTALL)
    mp = re.search(r'clim:.*?p:\s*(\[[^\]]+\])', bh, re.DOTALL)
    if ml and mp:
        lb = [v.strip().strip("'\"") for v in ml.group(1).split(',')]
        pv = json.loads(mp.group(1))
        if len(lb) != 12 or len(pv) != 12:
            erro(f'BH.clim: labels={len(lb)} p={len(pv)} (esperado 12)')
        elif not all(abs(a - CLIM[MESES_CAP[l]]) <= 0.6 for l, a in zip(lb, pv)):
            erro('BH.clim: precipitação desalinhada dos rótulos')
        else:
            ok('BH.clim alinhado (aba Clima)')

    # ── 6. Monitor ENSO ─────────────────────────────────────────────────
    ini = h.find('indices:')
    fim = h.find('fc_labels:', ini)
    blk_idx = h[ini:fim] if ini > 0 and fim > ini else ''
    mi = re.search(r'labels:\[([^\]]+)\]', blk_idx)
    if mi:
        n_lbl = len(mi.group(1).split(','))
        comp = {'labels': n_lbl}
        for nome in ['nino34', 'oni', 'tsa']:
            mm = re.search(rf'{nome}:\s*\[([^\]]+)\]', blk_idx)
            comp[nome] = len(mm.group(1).split(',')) if mm else 0
        if len(set(comp.values())) != 1:
            erro(f'Monitor ENSO com séries de tamanhos diferentes: {comp}')
        else:
            ok(f'Monitor ENSO consistente ({n_lbl} meses)')

    # ── 7. trimestres do Comparativo (CPC/IRI x SARIMAX) ────────────────
    # 7a/7b/7c — ver docstring de verificar_cpc_sarimax() (ENSO-DADOS Fase C).
    verificar_cpc_sarimax(h)

    # ── 8. plausibilidade física dos índices ENSO ───────────────────────
    # nino34/oni/tsa são anomalias (°C) — nunca ultrapassam ~3°C em módulo.
    # Um valor > 5°C indica bug de parsing (ex.: SST absoluta ~26-29°C
    # usada no lugar da anomalia).
    mnow = re.search(r'now:\s*\{([^}]+)\}', h)
    if mnow:
        bloco_now = mnow.group(1)
        implausiveis = []
        for nome in ['nino34', 'oni', 'tsa']:
            mv = re.search(rf'{nome}:\s*\[[^,]+,\s*(-?[\d.]+)\]', bloco_now)
            if mv:
                v = float(mv.group(1))
                if abs(v) > 5:
                    implausiveis.append(f'{nome}={v}')
        if implausiveis:
            erro('D.now com valor fisicamente implausível (anomalia > 5°C): '
                 + ', '.join(implausiveis))
        else:
            ok('D.now com índices ENSO fisicamente plausíveis')
    else:
        erro('D.now não encontrado para checagem de plausibilidade')

    mv = re.search(r'nino34:\s*\[([^\]]+)\]', blk_idx)
    if mv:
        fora = []
        for tok in mv.group(1).split(','):
            tok = tok.strip()
            if tok == 'null':
                continue
            try:
                v = float(tok)
            except ValueError:
                continue
            if abs(v) > 5:
                fora.append(v)
        if fora:
            erro(f'série nino34 com {len(fora)} valor(es) > 5°C em módulo (implausível): '
                 + ', '.join(f'{v:+.2f}' for v in fora[:5]))
        else:
            ok('série nino34 dentro da faixa física plausível (≤5°C)')

    # ── 9. continuidade de data/serie_subst.csv ──────────────────────────
    # .shift() em pandas opera por POSIÇÃO da linha, não por data — um mês
    # faltando desloca os lags de todo mundo depois dele sem erro visível.
    #
    # `pular_continuidade_serie_subst`: EXISTE SÓ para indices_semanal.yml
    # (Fase ENSO-DADOS, auditoria 15/10/2026) — esse workflow roda
    # update_indices.py isolado, que NUNCA toca serie_subst.csv com um mês
    # novo (só fetch_monthly_data.py faz isso, chamado só por update.yml no
    # dia 21). Por desenho, do dia 1 ao dia 20 de todo mês o "mês anterior
    # ao atual" fica estruturalmente ausente de serie_subst.csv até o
    # ciclo mensal rodar — essa checagem reprovava TODA execução de
    # indices_semanal.yml nessa janela (confirmado: 7 falhas seguidas,
    # 01-12/out/2026, runs #7-#13), o que pulava os passos de commit E de
    # heartbeat (ambos vêm depois no YAML, sem `if: always()`) — RONI,
    # wksst semanal e D.now ficaram presos no último commit que passou
    # (28/09/2026) até esta correção. Em update.yml a checagem continua
    # SEMPRE ativa (default False) — lá ela é legítima, porque
    # fetch_monthly_data.py já rodou antes e preencheu o mês antes desta
    # verificação.
    if not SERIE_SUBST.exists():
        erro('data/serie_subst.csv não encontrado')
    else:
        serie = pd.read_csv(SERIE_SUBST)
        lacunas = checar_continuidade(serie)
        m_ini, y_ini = int(serie['mes'].iloc[0]), int(serie['ano'].iloc[0])
        m_fim, y_fim = int(serie['mes'].iloc[-1]), int(serie['ano'].iloc[-1])
        if lacunas:
            msg = (f'serie_subst.csv com mês(es) faltando entre {m_ini:02d}/{y_ini} '
                   f'e o mês anterior ao atual (último registro real: '
                   f'{m_fim:02d}/{y_fim}): ' + ', '.join(lacunas))
            if pular_continuidade_serie_subst:
                print(f'  ⚠ {msg} — IGNORADO nesta execução '
                      f'(--pular-continuidade-serie-subst, só indices_semanal.yml; '
                      f'backfill real continua só no ciclo mensal do dia 21)')
            else:
                erro(msg)
        else:
            ok(f'serie_subst.csv contínua até o mês anterior ao atual '
               f'({len(serie)} meses, {m_ini:02d}/{y_ini} → {m_fim:02d}/{y_fim})')

    # ── 10. RONI vs ONI-aprox — rótulos precisam distinguir as métricas ──
    # RONI (CPC, oficial, trimestral, subtrai a tendência de aquecimento
    # tropical) e ONI-aprox (calc_oni: média 3m do Niño 3.4 bruto) são
    # números diferentes para o mesmo trimestre — se aparecerem juntos
    # sem rótulo que os diferencie, dá pra ler um pelo outro (ver
    # CLAUDE.md armadilha 9).
    tem_roni = re.search(r'const RONI\s*=', h) is not None
    if tem_roni:
        card_oni_ambiguo  = re.search(r'card-title">\s*ONI\s*<span', h) is not None
        card_roni_label   = re.search(r'card-title">\s*RONI\b', h) is not None
        card_oni_qualific = re.search(r'card-title">\s*ONI\s+aprox', h) is not None
        if card_oni_ambiguo or not (card_roni_label and card_oni_qualific):
            erro('RONI presente no dashboard mas os rótulos não distinguem '
                 'claramente RONI de ONI-aprox — risco de confundir as duas métricas')
        else:
            ok('RONI e ONI-aprox com rótulos distintos')

    # ── 11. defasagem do CPC_IRI e dos índices oceânicos (curados/
    #        coletados separadamente — só aviso, nunca bloqueia) ────────
    # CPC_IRI é majoritariamente manual (ver CLAUDE.md armadilhas 3/4);
    # partes automatizadas desde a Fase ENSO-DADOS/ENSO-AUTO continuam
    # tendo sua PRÓPRIA data de emissão, nunca confundida com "quando o
    # script rodou" — cada campo abaixo é a data que a FONTE publicou,
    # não a data de coleta. Bloquear a publicação por qualquer um deles
    # estar velho recriaria a mesma classe de bug corrigida no item 9
    # (um aviso legítimo de uma parte do dashboard travando a
    # publicação inteira) — por isso isto é SÓ aviso, nunca `erro()`.
    #
    # Fase ENSO-AUTO (19/10/2026): distingue as 5 categorias pedidas —
    # antes só CPC Diagnostic Discussion e IRI (campo único,
    # `iri_emissao`) eram checados; `cpc_probabilidades_emissao` e
    # `iri_trajetoria_emissao` existem desde as Fases ENSO-DADOS/
    # ENSO-IRI mas nunca tinham checagem de defasagem própria.
    m_meta = re.search(r'_meta:\s*\{([^}]*)\}', h)
    if m_meta:
        bloco_meta = m_meta.group(1)
        for campo, rotulo in (
            ('cpc_emissao', 'CPC Diagnostic Discussion'),
            ('cpc_probabilidades_emissao', 'Probabilidades CPC'),
            ('iri_emissao', 'Probabilidades IRI'),
            ('iri_trajetoria_emissao', 'Trajetória Niño 3.4 IRI'),
        ):
            m_campo = re.search(rf"{campo}:\s*'([^']*)'", bloco_meta)
            if m_campo:
                dias = _dias_desde_data_pt(m_campo.group(1))
                if dias is not None and dias > 35:
                    print(f'  ⚠ CPC_IRI._meta.{campo} ({rotulo}) tem {dias} dias '
                          f'— acima do ciclo mensal esperado (~30 dias), fonte '
                          f'possivelmente defasada')
        ok('metadados de defasagem do CPC_IRI verificados (só aviso, nunca bloqueia)')

    # Índices oceânicos mensais/semanais: cadência própria (mensal
    # publica com ~1 mês de defasagem por natureza; semanal é ~7 dias)
    # — comparado contra o MÊS do próprio dado mais recente (D.now,
    # rótulo real já atribuído pelo script, nunca "hoje"), não contra
    # a data de execução deste verificador.
    if mnow:
        m_n34_lbl = re.search(r"nino34:\s*\[\s*\"([^\"]+)\"", mnow.group(1))
        if m_n34_lbl:
            meses_atras = _meses_atras_rotulo_mmm_aaaa(m_n34_lbl.group(1))
            # >=2 meses: 1 mês atrás é o estado normal (o CPC só publica
            # o valor do mês corrente no início do mês seguinte) — só a
            # partir de 2 meses é sinal de falha recorrente do workflow.
            if meses_atras is not None and meses_atras >= 2:
                print(f'  ⚠ Índices oceânicos (D.now.nino34, {m_n34_lbl.group(1)}) '
                      f'estão {meses_atras} meses de calendário atrás — possível '
                      f'falha recorrente do workflow semanal/mensal')
            else:
                ok('defasagem dos índices oceânicos mensais dentro do esperado')

    # ── 12. defasagem de TSA/PDO via proveniência (nunca por constância
    #        do valor — só aviso, mesma disciplina do item 11) ──────────
    # Fase ENSO-INTEGRIDADE (12/11/2026): PDO não tinha NENHUMA checagem
    # até aqui (confirmado em auditoria — zero menções a "pdo" neste
    # arquivo antes desta fase). Um valor de PDO congelado por meses
    # (persistido/estimado) é indistinguível de uma observação real sem
    # consultar o registro complementar de proveniência — nunca inferido
    # pela constância do número (um PDO real também pode variar pouco
    # entre meses vizinhos; "mudou" não prova "é observação", e
    # "não mudou" não prova "é estimativa"). Sem limiar físico novo —
    # só compara a classificação registrada, nunca o valor em si.
    if SERIE_SUBST.exists():
        serie_check = pd.read_csv(SERIE_SUBST)
        if not serie_check.empty:
            ult = serie_check.sort_values(['ano', 'mes']).iloc[-1]
            y_ult, m_ult = int(ult['ano']), int(ult['mes'])
            for indice in ('tsa', 'pdo'):
                reg = prov.consultar('serie_subst.csv', y_ult, m_ult, indice)
                if reg is None:
                    print(f'  ⚠ proveniência DESCONHECIDA para {indice} do mês mais '
                          f'recente de serie_subst.csv ({m_ult:02d}/{y_ult}) — nenhum '
                          f'registro complementar encontrado; não presumir observação')
                elif reg['classificacao'] == 'observado':
                    ok(f'{indice} do mês mais recente ({m_ult:02d}/{y_ult}) registrado '
                       f'como observação real')
                elif reg['classificacao'] in ('persistido', 'estimado'):
                    meses_base = ', '.join(reg['meses_base']) if reg['meses_base'] else '?'
                    print(f'  ⚠ {indice} do mês mais recente ({m_ult:02d}/{y_ult}) é '
                          f'{reg["classificacao"]} (base: {meses_base}, método: '
                          f'{reg["metodo"]}) — não é observação real deste mês; '
                          f'aviso informativo, nunca bloqueia a publicação')
                else:
                    print(f'  ⚠ {indice} do mês mais recente ({m_ult:02d}/{y_ult}) com '
                          f'proveniência "{reg["classificacao"]}" — origem não '
                          f'comprovada, não presumir observação')

    # ── resultado ───────────────────────────────────────────────────────
    print(f"\n{'='*58}")
    if falhas:
        print(f'  REPROVADO — {len(falhas)} problema(s)')
        print('  A publicação deve ser interrompida.')
        print(f"{'='*58}\n")
        return 1
    print('  APROVADO — dashboard íntegro e consistente')
    print(f"{'='*58}\n")
    return 0


if __name__ == '__main__':
    _pular = '--pular-continuidade-serie-subst' in sys.argv
    sys.exit(main(pular_continuidade_serie_subst=_pular))
