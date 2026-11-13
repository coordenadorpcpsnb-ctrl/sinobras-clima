#!/usr/bin/env python3
"""
validar_correcao_historica_tsa.py — Fase ENSO-INTEGRIDADE 3B.0.

Valida se o diff de uma PR, entre a base e o HEAD, corresponde
EXATAMENTE à correção histórica de TSA autorizada em
corrigir_indices_historicos.PLANO_BASE (+ a célula condicional de
outubro) — nunca uma lista própria e divergente (fonte única).

Usado por .github/workflows/ci.yml (Job B) para decidir se a
sub-checagem de continuidade temporal de serie_subst.csv (item 9 de
verificar_dashboard.py) pode ser pulada quando data/serie_subst.csv
FOI tocado por uma PR: hoje "tocado" sempre força a checagem cheia —
o que reprovaria a própria correção de TSA por uma lacuna de
calendário pré-existente (set/out ainda ausentes de serie_subst.csv
até o fetch real do dia 21), nada relacionado à correção em si.

Esta exceção NUNCA é uma liberação genérica: qualquer mudança em
data/serie_subst.csv, data/master_monthly.csv ou
data/indices_proveniencia.csv que não seja EXATAMENTE uma das células
do plano fechado (arquivo, ano, mês, coluna, valor antigo E valor novo
idênticos) reprova a validação — e a CI volta a exigir a checagem
completa de continuidade. Nunca consulta a NOAA nem nenhuma rede: só
compara texto já commitado (base vs HEAD) com o plano estático do
módulo.

Restrito, pela chamada em ci.yml, ao job acionado por `pull_request`
— nunca usado por update.yml/indices_semanal.yml (ambos continuam
exigindo continuidade completa, sem excecão, por não importarem nem
chamarem este módulo).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import corrigir_indices_historicos as cih  # noqa: E402
import proveniencia_indices as prov  # noqa: E402

ROOT = Path(__file__).parent.parent

CAMINHO_PROVENIENCIA = 'data/indices_proveniencia.csv'


def celulas_autorizadas():
    """Fonte única dos valores autorizados: o plano fechado de
    corrigir_indices_historicos.py. A célula de outubro é incluída
    aqui mesmo sendo 'condicional' na ferramenta de aplicação — aqui
    ela é só mais uma entrada de uma lista fechada, e continua exigindo
    casamento exato de valor_antigo/valor_novo como qualquer outra;
    "condicional" decide SE a ferramenta aplica, não se a CI reconhece
    a célula quando ela aparecer."""
    return list(cih.PLANO_BASE) + [cih.CELULA_OUTUBRO_CONDICIONAL]


def _git_show(ref, caminho_relativo):
    """Devolve o texto do arquivo em `ref` (relativo à raiz do repo),
    ou None se o arquivo não existir nesse ref (ex.: arquivo novo ou
    ainda inexistente, como data/indices_proveniencia.csv hoje)."""
    r = subprocess.run(['git', 'show', f'{ref}:{caminho_relativo}'],
                        cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return r.stdout


def _carregar_csv(texto, colunas_default=None):
    if texto is None:
        return pd.DataFrame(columns=colunas_default) if colunas_default else None
    return pd.read_csv(StringIO(texto))


def _valores_iguais(a, b):
    a_vazio, b_vazio = pd.isna(a), pd.isna(b)
    if a_vazio or b_vazio:
        return bool(a_vazio) and bool(b_vazio)
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return a == b


def _linhas_por_chave(df, chave_cols):
    """Agrupa por chave — devolve (dict chave->linha, lista de chaves
    duplicadas). Uma chave duplicada em QUALQUER lado (base ou head) é
    motivo de reprovação; o plano nunca presume uma unicidade que não
    foi verificada de fato."""
    contagem = df.groupby(list(chave_cols)).size()
    duplicadas = [k if isinstance(k, tuple) else (k,) for k in contagem[contagem > 1].index]
    linhas = {}
    for _, row in df.iterrows():
        chave = tuple(row[c] for c in chave_cols)
        linhas[chave] = row
    return linhas, duplicadas


def comparar_arquivo_textos(nome_arquivo, texto_base, texto_head):
    """
    Versão pura (sem git): compara o conteúdo de `data/{nome_arquivo}`
    (master_monthly.csv ou serie_subst.csv) dado já como texto —
    testável com fixtures sintéticas, sem precisar de um repositório
    git real. Nunca levanta exceção para "arquivo não mudou" — isso é
    só relatado via alterado=False.
    """
    if texto_base == texto_head:
        return {'alterado': False, 'violacoes': [], 'celulas_mudadas': []}

    if texto_base is None or texto_head is None:
        return {'alterado': True,
                'violacoes': [f'{nome_arquivo}: arquivo criado ou removido entre base e HEAD — '
                              f'fora do plano fechado (nunca autorizado)'],
                'celulas_mudadas': []}

    df_base, df_head = _carregar_csv(texto_base), _carregar_csv(texto_head)
    chave_cols = cih.COLUNA_POR_ARQUIVO[nome_arquivo]
    violacoes = []

    if set(df_base.columns) != set(df_head.columns):
        violacoes.append(f'{nome_arquivo}: colunas mudaram '
                          f'({sorted(df_base.columns)} -> {sorted(df_head.columns)})')
        return {'alterado': True, 'violacoes': violacoes, 'celulas_mudadas': []}

    linhas_base, dup_base = _linhas_por_chave(df_base, chave_cols)
    linhas_head, dup_head = _linhas_por_chave(df_head, chave_cols)
    if dup_base or dup_head:
        violacoes.append(f'{nome_arquivo}: chave duplicada (base={dup_base}, head={dup_head})')

    chaves_base, chaves_head = set(linhas_base), set(linhas_head)
    incluidas, excluidas = chaves_head - chaves_base, chaves_base - chaves_head
    if incluidas:
        violacoes.append(f'{nome_arquivo}: mês(es) incluído(s) {sorted(incluidas)} — '
                          f'correção histórica nunca adiciona mês')
    if excluidas:
        violacoes.append(f'{nome_arquivo}: mês(es) excluído(s) {sorted(excluidas)} — '
                          f'correção histórica nunca remove mês')

    celulas_mudadas = []
    for chave in chaves_base & chaves_head:
        linha_base, linha_head = linhas_base[chave], linhas_head[chave]
        for coluna in df_base.columns:
            if coluna in chave_cols:
                continue
            v_base, v_head = linha_base[coluna], linha_head[coluna]
            if not _valores_iguais(v_base, v_head):
                ano, mes = chave
                celulas_mudadas.append({'arquivo': nome_arquivo, 'ano': int(ano), 'mes': int(mes),
                                         'coluna': coluna, 'valor_antigo': v_base, 'valor_novo': v_head})

    return {'alterado': True, 'violacoes': violacoes, 'celulas_mudadas': celulas_mudadas}


def _bate_com_plano(mudanca, autorizadas):
    for cel in autorizadas:
        if (cel['arquivo'] == mudanca['arquivo'] and cel['ano'] == mudanca['ano'] and
                cel['mes'] == mudanca['mes'] and cel['coluna'] == mudanca['coluna']):
            return (_valores_iguais(mudanca['valor_antigo'], cel['valor_antigo_esperado']) and
                    _valores_iguais(mudanca['valor_novo'], cel['valor_novo']))
    return False


def comparar_proveniencia_textos(texto_base, texto_head, celulas_autorizadas_tsa):
    """
    Versão pura (sem git): data/indices_proveniencia.csv não tem
    chave (ano,mes) única — a chave real é (arquivo,ano,mes,indice).
    Só mudanças nas linhas que correspondem exatamente a uma célula de
    TSA do plano, com a classificação exigida pelo PRÓPRIO plano
    (nunca inferida aqui), são autorizadas. Qualquer outra linha
    tocada, criada ou removida reprova.
    """
    if texto_base == texto_head:
        return {'alterado': False, 'violacoes': []}

    df_base = _carregar_csv(texto_base, prov.COLUNAS)
    df_head = _carregar_csv(texto_head, prov.COLUNAS)
    chave_cols = ('arquivo', 'ano', 'mes', 'indice')
    linhas_base, dup_base = _linhas_por_chave(df_base, chave_cols) if not df_base.empty else ({}, [])
    linhas_head, dup_head = _linhas_por_chave(df_head, chave_cols) if not df_head.empty else ({}, [])

    violacoes = []
    if dup_base or dup_head:
        violacoes.append(f'{CAMINHO_PROVENIENCIA}: chave duplicada (base={dup_base}, head={dup_head})')

    chaves_autorizadas = {(c['arquivo'], c['ano'], c['mes'], 'tsa'): c for c in celulas_autorizadas_tsa}

    for chave in set(linhas_base) | set(linhas_head):
        antes, depois = linhas_base.get(chave), linhas_head.get(chave)
        if antes is not None and depois is not None and antes.equals(depois):
            continue
        if chave not in chaves_autorizadas:
            violacoes.append(f'{CAMINHO_PROVENIENCIA}: linha fora do plano foi tocada {chave}')
            continue
        if depois is None:
            violacoes.append(f'{CAMINHO_PROVENIENCIA}: proveniência removida para célula autorizada {chave}')
            continue
        cel = chaves_autorizadas[chave]
        if str(depois.get('classificacao')) != cel['classificacao']:
            violacoes.append(f'{CAMINHO_PROVENIENCIA}: classificação inesperada para {chave} '
                              f'(esperado {cel["classificacao"]!r}, obtido {depois.get("classificacao")!r})')

    return {'alterado': True, 'violacoes': violacoes}


def validar_textos(texto_master_base, texto_master_head,
                    texto_subst_base, texto_subst_head,
                    texto_prov_base, texto_prov_head):
    """
    Versão pura (sem git): recebe os textos de base/HEAD dos 3
    arquivos já carregados e devolve (autorizado: bool, relatorio:
    dict). autorizado=True SOMENTE quando toda mudança encontrada nos
    3 arquivos bate exatamente com uma célula do plano fechado — nunca
    por ausência de verificação, e nunca quando nada mudou nos CSVs de
    dados (essa exceção serve só para a correção histórica real).
    """
    autorizadas = celulas_autorizadas()
    autorizadas_tsa = [c for c in autorizadas if c['coluna'] == 'tsa']
    relatorio = {'violacoes': [], 'celulas_mudadas': {}}

    r_master = comparar_arquivo_textos('master_monthly.csv', texto_master_base, texto_master_head)
    r_subst = comparar_arquivo_textos('serie_subst.csv', texto_subst_base, texto_subst_head)
    relatorio['violacoes'] += r_master['violacoes'] + r_subst['violacoes']
    relatorio['celulas_mudadas']['master_monthly.csv'] = r_master['celulas_mudadas']
    relatorio['celulas_mudadas']['serie_subst.csv'] = r_subst['celulas_mudadas']

    for mudanca in r_master['celulas_mudadas'] + r_subst['celulas_mudadas']:
        if not _bate_com_plano(mudanca, autorizadas):
            relatorio['violacoes'].append(
                f"{mudanca['arquivo']}: célula fora do plano ou com valor divergente "
                f"({mudanca['ano']}-{mudanca['mes']:02d}.{mudanca['coluna']}: "
                f"{mudanca['valor_antigo']!r} -> {mudanca['valor_novo']!r})")

    r_prov = comparar_proveniencia_textos(texto_prov_base, texto_prov_head, autorizadas_tsa)
    relatorio['violacoes'] += r_prov['violacoes']

    if not (r_master['alterado'] or r_subst['alterado']):
        relatorio['violacoes'].append(
            'nenhuma alteração em master_monthly.csv/serie_subst.csv — a exceção de correção '
            'histórica de TSA não se aplica (ci.yml já trata o caso "nada mudou" separadamente)')

    autorizado = not relatorio['violacoes']
    return autorizado, relatorio


def validar(base_ref, head_ref='HEAD'):
    """Camada fina com git: busca os textos de base_ref/head_ref dos 3
    arquivos relevantes (via `git show`) e delega a validar_textos()."""
    return validar_textos(
        _git_show(base_ref, 'data/master_monthly.csv'), _git_show(head_ref, 'data/master_monthly.csv'),
        _git_show(base_ref, 'data/serie_subst.csv'), _git_show(head_ref, 'data/serie_subst.csv'),
        _git_show(base_ref, CAMINHO_PROVENIENCIA), _git_show(head_ref, CAMINHO_PROVENIENCIA))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('base_ref', help='ref git da base da PR (ex.: github.event.pull_request.base.sha)')
    ap.add_argument('head_ref', nargs='?', default='HEAD')
    args = ap.parse_args()

    autorizado, relatorio = validar(args.base_ref, args.head_ref)
    if autorizado:
        print('AUTORIZADO: diff corresponde exatamente ao plano fechado de correção histórica de TSA.')
        sys.exit(0)
    print('NÃO AUTORIZADO — diff não corresponde ao plano fechado de correção de TSA:')
    for v in relatorio['violacoes']:
        print(f'  - {v}')
    sys.exit(1)


if __name__ == '__main__':
    main()
