#!/usr/bin/env python3
"""
validar_correcao_historica_tsa.py — Fase ENSO-INTEGRIDADE 3B.0.

Valida se o diff de uma PR, entre a base e o HEAD, corresponde
EXATAMENTE à correção histórica de TSA autorizada em
corrigir_indices_historicos.PLANO_BASE (+ a célula condicional de
outubro) — nunca uma lista própria e divergente (fonte única).

Usado por scripts/decidir_continuidade_serie_subst.sh, chamado pelo
Job B de .github/workflows/ci.yml, para decidir se a sub-checagem de
continuidade temporal de serie_subst.csv (item 9 de
verificar_dashboard.py) pode ser pulada quando data/master_monthly.csv,
data/serie_subst.csv ou data/indices_proveniencia.csv FOREM tocados
por uma PR.

Classificação em três vias (Fase ENSO-INTEGRIDADE 3B.0.2 — corrige a
versão binária anterior da 3B.0, que só olhava serie_subst.csv e só
exigia consistência da proveniência QUANDO ela existia, nunca sua
presença):

- NAO_SE_APLICA (exit 10): nenhuma célula do plano fechado foi
  tocada — a mudança é de outra natureza; NUNCA tratada como
  "correção de TSA reprovada". O chamador preserva o comportamento
  ORDINÁRIO (decidido só por serie_subst.csv, igual a antes desta
  fase).
- AUTORIZADO (exit 0): ao menos uma célula do plano foi tocada, e
  tudo bate — valor antigo/novo exatos, nenhuma célula fora do plano,
  E proveniência completa (presente, com valor/classificacao/
  meses_base/fonte/metodo/verificado_em consistentes) para CADA
  célula efetivamente corrigida.
- TENTATIVA_INVALIDA (exit 1): ao menos uma célula do plano foi
  tocada, mas algo reprova — valor errado, mês incluído/excluído/
  duplicado, mudança não autorizada misturada, ou proveniência
  ausente/incompleta/inconsistente. Isso NUNCA deve ser interpretado
  como "a PR pode seguir com a checagem ordinária" — é uma tentativa
  de explorar a exceção da TSA que precisa reprovar explicitamente.

Esta exceção NUNCA é uma liberação genérica: qualquer mudança em
data/serie_subst.csv, data/master_monthly.csv ou
data/indices_proveniencia.csv que não seja EXATAMENTE uma das células
do plano fechado (arquivo, ano, mês, coluna, valor antigo E valor novo
idênticos, com proveniência completa) reprova a validação. Nunca
consulta a NOAA nem nenhuma rede: só compara texto já commitado (base
vs HEAD) com o plano estático do módulo.

Restrito, pela chamada em ci.yml, ao job acionado por `pull_request`
— nunca usado por update.yml/indices_semanal.yml (ambos continuam
exigindo continuidade completa, sem excecão, por não importarem nem
chamarem este módulo).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
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


def _git_show(ref, caminho_relativo, repo_root=None):
    """Devolve o texto do arquivo em `ref` (relativo à raiz do repo),
    ou None se o arquivo não existir nesse ref (ex.: arquivo novo ou
    ainda inexistente, como data/indices_proveniencia.csv hoje).

    `repo_root` (Fase ENSO-INTEGRIDADE 3B.0.2): por padrão usa o
    repositório real (ROOT), mas aceita um repositório git TEMPORÁRIO
    — usado só por testes que precisam exercitar esta função (e o
    acionamento real do ramo de ci.yml) sem tocar o histórico real do
    projeto."""
    r = subprocess.run(['git', 'show', f'{ref}:{caminho_relativo}'],
                        cwd=(repo_root if repo_root is not None else ROOT),
                        capture_output=True, text=True)
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


def _valor_celula(texto, nome_arquivo, ano, mes, coluna):
    """Lê o valor de uma célula específica (arquivo/ano/mes/coluna) a
    partir do texto CSV já carregado. Devolve None se o texto for
    None, a leitura falhar, a linha (ano,mes) não existir ou a coluna
    não existir — tratado como "ausente", nunca como erro fatal: a
    própria ausência já é informação suficiente para a classificação
    de `diff_toca_alguma_celula_do_plano`."""
    if texto is None:
        return None
    try:
        df = pd.read_csv(StringIO(texto))
    except Exception:
        return None
    ano_col, mes_col = cih.COLUNA_POR_ARQUIVO[nome_arquivo]
    if coluna not in df.columns:
        return None
    linha = df[(df[ano_col] == ano) & (df[mes_col] == mes)]
    if linha.empty:
        return None
    return linha.iloc[0][coluna]


def diff_toca_alguma_celula_do_plano(texto_master_base, texto_master_head,
                                      texto_subst_base, texto_subst_head,
                                      texto_prov_base, texto_prov_head,
                                      autorizadas):
    """
    True se QUALQUER célula do plano fechado (master_monthly.csv ou
    serie_subst.csv, coluna tsa) tiver valor diferente entre base e
    HEAD, OU se a linha de proveniência de alguma célula de TSA do
    plano tiver mudado — independente de bater ou não com o valor
    esperado pelo plano. Usado SÓ para CLASSIFICAR o diff como
    "tentativa de correção histórica de TSA" vs. "alteração legítima
    de outra natureza" — nunca para decidir autorização por si só (um
    valor errado numa célula do plano ainda classifica como
    "tentativa", mas reprova na validação completa de
    `validar_textos`).

    Esta distinção existe porque uma alteração que não toca nenhuma
    célula do plano (ex.: corrigir precipitação de uma fazenda, ou
    incluir um mês novo em serie_subst.csv pelo fluxo operacional
    normal) não deve ser forçada a passar pela validação estrita desta
    fase, nem deve perder o comportamento ORDINÁRIO já existente da
    checagem de continuidade (decidido só pela própria
    serie_subst.csv) — ver scripts/decidir_continuidade_serie_subst.sh.
    """
    textos_por_arquivo = {
        'master_monthly.csv': (texto_master_base, texto_master_head),
        'serie_subst.csv': (texto_subst_base, texto_subst_head),
    }
    for cel in autorizadas:
        texto_base, texto_head = textos_por_arquivo[cel['arquivo']]
        v_base = _valor_celula(texto_base, cel['arquivo'], cel['ano'], cel['mes'], cel['coluna'])
        v_head = _valor_celula(texto_head, cel['arquivo'], cel['ano'], cel['mes'], cel['coluna'])
        if not _valores_iguais(v_base, v_head):
            return True

    chaves_tsa = {(c['arquivo'], c['ano'], c['mes'], 'tsa') for c in autorizadas if c['coluna'] == 'tsa'}
    df_prov_base = _carregar_csv(texto_prov_base, prov.COLUNAS)
    df_prov_head = _carregar_csv(texto_prov_head, prov.COLUNAS)
    linhas_base = {} if df_prov_base.empty else _linhas_por_chave(df_prov_base, ('arquivo', 'ano', 'mes', 'indice'))[0]
    linhas_head = {} if df_prov_head.empty else _linhas_por_chave(df_prov_head, ('arquivo', 'ano', 'mes', 'indice'))[0]
    for chave in chaves_tsa:
        antes, depois = linhas_base.get(chave), linhas_head.get(chave)
        if antes is None and depois is None:
            continue
        if antes is not None and depois is not None and antes.equals(depois):
            continue
        return True
    return False


def _meses_base_str(meses_base):
    """Mesmo formato de serialização de proveniencia_indices.registrar()
    (';'.join) — fonte única, nunca reimplementado de forma divergente."""
    return ';'.join(meses_base) if meses_base else ''


def _verificado_em_valido(valor):
    """Só exige PRESENÇA e formato ISO 8601 válido — nunca um valor
    específico esperado (seria inventar a data/hora exata em que a
    correção real foi verificada, o que esta validação não pode
    saber)."""
    if not valor or not isinstance(valor, str):
        return False
    texto = valor[:-1] + '+00:00' if valor.endswith('Z') else valor
    try:
        datetime.fromisoformat(texto)
        return True
    except ValueError:
        return False


def _provenencia_bate_com_celula(linha_prov, celula):
    """Confere valor/classificacao/meses_base/fonte/metodo/verificado_em
    de uma linha REAL de proveniência contra os campos esperados pela
    PRÓPRIA entrada do plano fechado (fonte única — nunca um valor
    inventado aqui). Devolve a lista de incompatibilidades encontradas
    (lista vazia = tudo bate)."""
    problemas = []
    valor_prov = linha_prov.get('valor')
    try:
        valor_real = None if valor_prov in (None, '') else float(valor_prov)
    except (TypeError, ValueError):
        valor_real = None
    if valor_real is None:
        problemas.append(f'valor ausente ou não numérico na proveniência ({valor_prov!r})')
    elif not _valores_iguais(valor_real, celula['valor_novo']):
        problemas.append(f"valor {valor_real!r} na proveniência diverge do valor novo do plano "
                          f"{celula['valor_novo']!r}")

    if linha_prov.get('classificacao') != celula['classificacao']:
        problemas.append(f"classificacao {linha_prov.get('classificacao')!r} diverge do plano "
                          f"{celula['classificacao']!r}")

    esperado_meses = _meses_base_str(celula.get('meses_base'))
    if (linha_prov.get('meses_base') or '') != esperado_meses:
        problemas.append(f"meses_base {linha_prov.get('meses_base')!r} diverge do plano "
                          f"{esperado_meses!r}")

    if linha_prov.get('fonte') != celula.get('fonte'):
        problemas.append(f"fonte {linha_prov.get('fonte')!r} diverge do plano {celula.get('fonte')!r}")

    if linha_prov.get('metodo') != celula.get('metodo'):
        problemas.append(f"metodo {linha_prov.get('metodo')!r} diverge do plano {celula.get('metodo')!r}")

    if not _verificado_em_valido(linha_prov.get('verificado_em')):
        problemas.append(f"verificado_em ausente ou inválido: {linha_prov.get('verificado_em')!r}")

    return problemas


def _exigir_provenencia_completa(mudancas_autorizadas, texto_prov_head, celulas_autorizadas_tsa):
    """
    Para CADA célula de TSA já confirmada como batendo com o plano
    (mesma chave E mesmo valor antigo/novo — ver `_bate_com_plano`),
    exige no HEAD um registro de proveniência com a chave exata
    (arquivo, ano, mes, indice='tsa') e os campos descritos em
    `_provenencia_bate_com_celula`. Nunca infere proveniência ausente;
    só exige registro para as células EFETIVAMENTE corrigidas nesta
    operação (não para o histórico em geral).
    """
    if not mudancas_autorizadas:
        return []

    violacoes = []
    if texto_prov_head is None:
        for mudanca in mudancas_autorizadas:
            violacoes.append(
                f"proveniência obrigatória ausente ({CAMINHO_PROVENIENCIA} não existe no HEAD) para "
                f"célula corrigida ({mudanca['arquivo']}, {mudanca['ano']}, {mudanca['mes']}, 'tsa')")
        return violacoes

    df_head = _carregar_csv(texto_prov_head, prov.COLUNAS)
    linhas_head, dup_head = ({}, [])
    if not df_head.empty:
        linhas_head, dup_head = _linhas_por_chave(df_head, ('arquivo', 'ano', 'mes', 'indice'))
    if dup_head:
        violacoes.append(f'{CAMINHO_PROVENIENCIA}: chave duplicada no HEAD {dup_head}')

    chaves_por_cel = {(c['arquivo'], c['ano'], c['mes']): c for c in celulas_autorizadas_tsa}
    for mudanca in mudancas_autorizadas:
        cel = chaves_por_cel.get((mudanca['arquivo'], mudanca['ano'], mudanca['mes']))
        if cel is None:
            continue  # não deveria ocorrer — mudancas_autorizadas já veio filtrada pelo plano
        chave = (mudanca['arquivo'], mudanca['ano'], mudanca['mes'], 'tsa')
        linha = linhas_head.get(chave)
        if linha is None:
            violacoes.append(f'proveniência obrigatória ausente para célula corrigida {chave}')
            continue
        for problema in _provenencia_bate_com_celula(linha, cel):
            violacoes.append(f'proveniência da célula corrigida {chave}: {problema}')

    return violacoes


NAO_SE_APLICA = 'nao_se_aplica'
AUTORIZADO = 'autorizado'
TENTATIVA_INVALIDA = 'tentativa_invalida'


def validar_textos(texto_master_base, texto_master_head,
                    texto_subst_base, texto_subst_head,
                    texto_prov_base, texto_prov_head):
    """
    Versão pura (sem git): recebe os textos de base/HEAD dos 3
    arquivos já carregados e devolve (autorizado: bool, relatorio:
    dict). `relatorio['classificacao']` distingue três casos (Fase
    ENSO-INTEGRIDADE 3B.0.2):

    - NAO_SE_APLICA: nenhuma célula do plano fechado foi tocada (nem
      nos dados, nem na proveniência) — a mudança, se houver, é de
      outra natureza; esta validação não se aplica a ela (autorizado
      sempre False aqui, mas isso NUNCA deve ser lido como "tentativa
      de TSA reprovada" pelo chamador — ver
      scripts/decidir_continuidade_serie_subst.sh).
    - AUTORIZADO: pelo menos uma célula do plano foi tocada, e TUDO —
      valor antigo/novo, nenhuma outra célula fora do plano, e
      proveniência completa e consistente para cada célula
      efetivamente corrigida — bate exatamente com o plano fechado.
    - TENTATIVA_INVALIDA: pelo menos uma célula do plano foi tocada,
      mas algo não bate (valor errado, mês incluído/excluído/
      duplicado, mudança não autorizada misturada, proveniência
      ausente/incompleta/inconsistente).
    """
    autorizadas = celulas_autorizadas()
    autorizadas_tsa = [c for c in autorizadas if c['coluna'] == 'tsa']
    relatorio = {'violacoes': [], 'celulas_mudadas': {}, 'classificacao': None}

    toca_plano = diff_toca_alguma_celula_do_plano(
        texto_master_base, texto_master_head, texto_subst_base, texto_subst_head,
        texto_prov_base, texto_prov_head, autorizadas)

    if not toca_plano:
        relatorio['classificacao'] = NAO_SE_APLICA
        relatorio['violacoes'].append(
            'nenhuma célula do plano fechado de correção histórica de TSA foi tocada (nem nos '
            'dados, nem na proveniência) — não é uma tentativa de correção de TSA; esta '
            'validação não se aplica a esta mudança (se houver, segue a checagem ordinária, '
            'nunca esta validação)')
        return False, relatorio

    r_master = comparar_arquivo_textos('master_monthly.csv', texto_master_base, texto_master_head)
    r_subst = comparar_arquivo_textos('serie_subst.csv', texto_subst_base, texto_subst_head)
    relatorio['violacoes'] += r_master['violacoes'] + r_subst['violacoes']
    relatorio['celulas_mudadas']['master_monthly.csv'] = r_master['celulas_mudadas']
    relatorio['celulas_mudadas']['serie_subst.csv'] = r_subst['celulas_mudadas']

    mudancas_autorizadas = []
    for mudanca in r_master['celulas_mudadas'] + r_subst['celulas_mudadas']:
        if _bate_com_plano(mudanca, autorizadas):
            mudancas_autorizadas.append(mudanca)
        else:
            relatorio['violacoes'].append(
                f"{mudanca['arquivo']}: célula fora do plano ou com valor divergente "
                f"({mudanca['ano']}-{mudanca['mes']:02d}.{mudanca['coluna']}: "
                f"{mudanca['valor_antigo']!r} -> {mudanca['valor_novo']!r})")

    r_prov = comparar_proveniencia_textos(texto_prov_base, texto_prov_head, autorizadas_tsa)
    relatorio['violacoes'] += r_prov['violacoes']

    relatorio['violacoes'] += _exigir_provenencia_completa(
        mudancas_autorizadas, texto_prov_head, autorizadas_tsa)

    autorizado = not relatorio['violacoes']
    relatorio['classificacao'] = AUTORIZADO if autorizado else TENTATIVA_INVALIDA
    return autorizado, relatorio


def validar(base_ref, head_ref='HEAD', repo_root=None):
    """Camada fina com git: busca os textos de base_ref/head_ref dos 3
    arquivos relevantes (via `git show`) e delega a validar_textos().

    `repo_root` (Fase 3B.0.2): repositório a consultar — por padrão o
    repositório real; um repositório git temporário quando chamado
    por teste (ver item 14 dos testes obrigatórios da Fase 3B.0.2)."""
    return validar_textos(
        _git_show(base_ref, 'data/master_monthly.csv', repo_root),
        _git_show(head_ref, 'data/master_monthly.csv', repo_root),
        _git_show(base_ref, 'data/serie_subst.csv', repo_root),
        _git_show(head_ref, 'data/serie_subst.csv', repo_root),
        _git_show(base_ref, CAMINHO_PROVENIENCIA, repo_root),
        _git_show(head_ref, CAMINHO_PROVENIENCIA, repo_root))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('base_ref', help='ref git da base da PR (ex.: github.event.pull_request.base.sha)')
    ap.add_argument('head_ref', nargs='?', default='HEAD')
    ap.add_argument('--repo', default=None,
                     help='raiz do repositório git a consultar (padrão: este repositório)')
    args = ap.parse_args()

    autorizado, relatorio = validar(args.base_ref, args.head_ref, repo_root=args.repo)
    classificacao = relatorio.get('classificacao')

    if autorizado:
        print('AUTORIZADO: diff corresponde exatamente ao plano fechado de correção histórica de '
              'TSA, com proveniência completa e consistente.')
        sys.exit(0)

    if classificacao == NAO_SE_APLICA:
        print('NÃO SE APLICA: nenhuma célula do plano fechado de TSA foi tocada neste diff.')
        for v in relatorio['violacoes']:
            print(f'  - {v}')
        sys.exit(10)

    print('NÃO AUTORIZADO — tentativa de correção histórica de TSA detectada e reprovada:')
    for v in relatorio['violacoes']:
        print(f'  - {v}')
    sys.exit(1)


if __name__ == '__main__':
    main()
