#!/usr/bin/env python3
"""
proveniencia_indices.py — registro complementar de proveniência dos
índices oceânicos (Niño 3.4, TSA, PDO) gravados em master_monthly.csv
e serie_subst.csv.

Fase ENSO-INTEGRIDADE (auditoria de integridade/rastreabilidade,
11-12/11/2026): nenhum dos dois CSVs guarda, por si só, se um valor é
observação real, persistência do último mês real, estimativa (média
de meses) ou de origem desconhecida — `enso_indices()` (antes desta
fase) rotulava qualquer linha encontrada no master como 'master',
colapsando essa distinção. Este módulo é o registro complementar que
resolve isso SEM adicionar colunas aos CSVs atuais (Estratégia 2 da
especificação da Fase 2: menor risco para os consumidores existentes,
que continuam lendo os CSVs exatamente como são hoje).

Formato: CSV simples em `data/indices_proveniencia.csv`, uma linha por
(arquivo, ano, mes, indice) — chave única. Nunca duplica essa chave:
`registrar()` faz upsert (sobrescreve a linha existente se os fatos
mudarem; não toca no arquivo se os fatos já registrados forem
idênticos aos novos — execuções repetidas são sempre idempotentes).

Regra central (pedida explicitamente pela revisão externa): NUNCA
classificar uma linha histórica como 'observado' só porque ela está
presente no master. Só quem grava o valor, no momento em que sabe de
onde ele veio (update_indices.py/fetch_monthly_data.py), pode chamar
`registrar()`. Uma linha histórica sem registro correspondente é
'desconhecida' por ausência — nunca inferida.
"""
from __future__ import annotations

import csv
import io
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
CAMINHO_PADRAO = ROOT / 'data' / 'indices_proveniencia.csv'

COLUNAS = ['arquivo', 'ano', 'mes', 'indice', 'valor', 'classificacao',
           'meses_base', 'fonte', 'metodo', 'verificado_em']

CLASSIFICACOES_VALIDAS = {'observado', 'persistido', 'estimado', 'desconhecido'}


class InconsistenciaProveniencia(Exception):
    """Levantada quando o valor atual de uma célula do CSV de dado
    diverge do valor registrado na proveniência para a mesma chave —
    nunca ignorada em silêncio pelo chamador."""


def _chave(linha):
    return (linha['arquivo'], int(linha['ano']), int(linha['mes']), linha['indice'])


def _ler(caminho=None):
    """Lê o registro completo como lista de dicts. Arquivo ausente ou
    vazio devolve lista vazia — nunca lança exceção (ainda não existir
    proveniência nenhuma é um estado normal, não um erro).

    `caminho=None` (resolvido para CAMINHO_PADRAO DENTRO da função,
    não como valor padrão do parâmetro) é intencional: um argumento
    default é avaliado uma única vez, na definição da função — se
    fosse `caminho=CAMINHO_PADRAO` direto na assinatura, um teste que
    faça `patch.object(prov, 'CAMINHO_PADRAO', tmp)` NUNCA afetaria
    quem chama `registrar()`/`consultar()` sem passar `caminho=`
    explicitamente, arriscando tocar o arquivo real por engano."""
    caminho = caminho if caminho is not None else CAMINHO_PADRAO
    if not Path(caminho).exists():
        return []
    with open(caminho, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def renderizar_texto(linhas):
    """Devolve o texto CSV exato que `_escrever` gravaria para `linhas`,
    sem tocar em disco. Função pura — permite a quem chama (ex.:
    corrigir_indices_historicos.py) preparar e VALIDAR o conteúdo novo
    da proveniência antes de qualquer escrita real, mesma disciplina
    já aplicada aos dois CSVs de dado."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUNAS)
    w.writeheader()
    for linha in linhas:
        w.writerow({c: linha.get(c, '') for c in COLUNAS})
    return buf.getvalue()


def _escrever(linhas, caminho=None):
    caminho = Path(caminho if caminho is not None else CAMINHO_PADRAO)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(caminho.suffix + '.tmp')
    # newline='' preserva exatamente o \r\n que o csv.DictWriter já
    # emitiu dentro do texto — sem isso, write_text traduziria '\n'
    # outra vez (no-op em POSIX, mas evita qualquer diferença sutil).
    with open(tmp, 'w', newline='', encoding='utf-8') as f:
        f.write(renderizar_texto(linhas))
    tmp.replace(caminho)   # os.replace — atômico na mesma partição (POSIX)


def registrar(arquivo, ano, mes, indice, valor, classificacao, meses_base,
              fonte, metodo, verificado_em=None, caminho=None):
    """
    Upsert por (arquivo, ano, mes, indice). `meses_base` é uma lista de
    strings 'AAAA-MM' (0 para observação, 1 para persistência, até 3
    para a estimativa de PDO — nunca resumido a um único 'mes_fonte',
    por pedido explícito da revisão externa).

    Idempotente: se já existir um registro idêntico (mesmos valor,
    classificacao, meses_base, fonte, metodo), não reescreve o arquivo
    nem atualiza verificado_em — uma segunda execução com os mesmos
    fatos não produz nenhuma mudança. Se existir um registro
    DIFERENTE para a mesma chave, sobrescreve essa linha (nunca duplica
    a chave) e devolve o registro anterior, para o chamador decidir se
    deve avisar sobre a divergência.
    """
    if classificacao not in CLASSIFICACOES_VALIDAS:
        raise ValueError(f"classificacao inválida: {classificacao!r}")

    verificado_em = verificado_em or datetime.now(timezone.utc).isoformat()
    meses_base_str = ';'.join(meses_base) if meses_base else ''
    nova = {
        'arquivo': arquivo, 'ano': int(ano), 'mes': int(mes), 'indice': indice,
        'valor': '' if valor is None else repr(float(valor)),
        'classificacao': classificacao, 'meses_base': meses_base_str,
        'fonte': fonte, 'metodo': metodo, 'verificado_em': verificado_em,
    }

    linhas = _ler(caminho)
    chave_nova = (arquivo, int(ano), int(mes), indice)
    anterior = None
    substituido = False
    resultado = []
    for linha in linhas:
        if _chave(linha) == chave_nova:
            anterior = dict(linha)
            campos_fato = ('valor', 'classificacao', 'meses_base', 'fonte', 'metodo')
            if all(linha.get(c, '') == nova[c] for c in campos_fato):
                return anterior   # idêntico ao já registrado — no-op, idempotente
            resultado.append(nova)   # fatos mudaram — substitui esta linha
            substituido = True
        else:
            resultado.append(linha)
    if not substituido:
        resultado.append(nova)

    _escrever(resultado, caminho)
    return anterior


def preparar_lote(entradas, caminho=None):
    """
    Mescla uma lista de `entradas` (cada uma com os mesmos campos
    nomeados de `registrar()`: arquivo/ano/mes/indice/valor/
    classificacao/meses_base/fonte/metodo, mais `verificado_em`
    opcional) contra o conteúdo ATUAL do arquivo de proveniência —
    SEM escrever nada em disco. Devolve (linhas_resultantes,
    anteriores), onde `anteriores` é um dict chave->registro anterior
    (dict) ou None, para quem chama decidir se deve sinalizar uma
    contradição (ex.: proveniência anterior tinha classificação
    diferente da que está sendo gravada agora).

    Usado por corrigir_indices_historicos.py para preparar e VALIDAR
    (ex.: via renderizar_texto()) o conteúdo novo da proveniência
    ANTES de qualquer escrita real — mesma disciplina já aplicada aos
    dois CSVs de dado (nunca escrever um arquivo sem ter validado o
    outro primeiro). `registrar()` continua sendo o caminho normal
    para um único valor (usado em todo o resto do projeto); esta
    função é especificamente para quem precisa preparar várias
    entradas de uma vez sem tocar em disco a cada uma.
    """
    linhas = _ler(caminho)
    anteriores = {}
    resultado = list(linhas)
    for entrada in entradas:
        classificacao = entrada['classificacao']
        if classificacao not in CLASSIFICACOES_VALIDAS:
            raise ValueError(f"classificacao inválida: {classificacao!r}")

        verificado_em = entrada.get('verificado_em') or datetime.now(timezone.utc).isoformat()
        meses_base_str = ';'.join(entrada['meses_base']) if entrada['meses_base'] else ''
        valor = entrada['valor']
        nova = {
            'arquivo': entrada['arquivo'], 'ano': int(entrada['ano']), 'mes': int(entrada['mes']),
            'indice': entrada['indice'],
            'valor': '' if valor is None else repr(float(valor)),
            'classificacao': classificacao, 'meses_base': meses_base_str,
            'fonte': entrada['fonte'], 'metodo': entrada['metodo'], 'verificado_em': verificado_em,
        }
        chave_nova = (entrada['arquivo'], int(entrada['ano']), int(entrada['mes']), entrada['indice'])

        anterior = None
        substituido = False
        nova_resultado = []
        for linha in resultado:
            if _chave(linha) == chave_nova:
                anterior = dict(linha)
                nova_resultado.append(nova)
                substituido = True
            else:
                nova_resultado.append(linha)
        if not substituido:
            nova_resultado.append(nova)
        resultado = nova_resultado
        anteriores[chave_nova] = anterior

    return resultado, anteriores


def consultar(arquivo, ano, mes, indice, caminho=None):
    """Devolve o registro (dict) para a chave, ou None se não houver
    nenhum — nunca inferido, nunca default para 'observado'."""
    for linha in _ler(caminho):
        if _chave(linha) == (arquivo, int(ano), int(mes), indice):
            r = dict(linha)
            r['ano'] = int(r['ano'])
            r['mes'] = int(r['mes'])
            r['valor'] = float(r['valor']) if r['valor'] not in ('', None) else None
            r['meses_base'] = r['meses_base'].split(';') if r['meses_base'] else []
            return r
    return None


def verificar_consistencia(arquivo, linhas_dado, caminho=None, indices_obrigatorios=None):
    """
    `linhas_dado`: iterável de dicts {'ano','mes','indice','valor'} —
    o estado ATUAL do CSV de dado (master_monthly.csv/serie_subst.csv).
    Para a detecção de REGISTRO ÓRFÃO ter sentido, `linhas_dado` deve
    representar o conjunto COMPLETO de linhas/índices do arquivo que
    está sendo verificado — uma fatia parcial (ex.: só o mês mais
    recente) faria todo registro de outro mês parecer órfão por
    engano; quem chama com uma fatia parcial deve usar só os `tipo`s
    que fazem sentido para essa fatia (ex.: 'valor_divergente').

    `indices_obrigatorios`: conjunto opcional de chaves
    (arquivo, ano, mes, indice) que o CHAMADOR sabe que deveriam ter
    proveniência registrada (ex.: células que o próprio chamador
    acabou de escrever) — NUNCA inferido por ausência histórica comum;
    sem este parâmetro, ausência pura de registro nunca gera
    divergência (ela é "desconhecida por ausência", legítima para
    histórico legado, e quem chama decide separadamente se avisa).

    Devolve a lista de divergências, cada uma com uma chave 'tipo':
      - 'valor_divergente': o valor atual do CSV não bate com o valor
        registrado na proveniência para a mesma chave.
      - 'valor_invalido_no_registro': o registro tem classificação que
        NÃO é 'desconhecido' mas o valor é None/NaN/infinito — um
        registro que deveria ter um valor válido não tem.
      - 'registro_obrigatorio_ausente': a chave está em
        `indices_obrigatorios` e não há registro nenhum.
      - 'registro_orfao': existe registro de proveniência para esta
        chave, mas nenhuma linha correspondente aparece em
        `linhas_dado` (proveniência aponta para um dado que não existe
        mais, ou nunca existiu, nos dados verificados).
      - 'chave_duplicada': o próprio arquivo de proveniência tem mais
        de uma linha para a mesma chave (nunca deveria acontecer via
        `registrar()`/`preparar_lote()` — upsert é por chave única;
        sinaliza corrupção externa do arquivo).

    Nunca lança por si só — o chamador decide, por `tipo`, o que
    bloqueia e o que é só aviso.
    """
    divergencias = []
    linhas_prov = _ler(caminho)

    contagem_chave = {}
    for linha in linhas_prov:
        if linha['arquivo'] != arquivo:
            continue
        contagem_chave[_chave(linha)] = contagem_chave.get(_chave(linha), 0) + 1
    for chave, n in contagem_chave.items():
        if n > 1:
            divergencias.append({'tipo': 'chave_duplicada', 'arquivo': arquivo,
                                  'ano': chave[1], 'mes': chave[2], 'indice': chave[3],
                                  'ocorrencias': n})

    indices_obrigatorios = indices_obrigatorios or set()
    chaves_dado = set()
    for d in linhas_dado:
        chave = (arquivo, int(d['ano']), int(d['mes']), d['indice'])
        chaves_dado.add(chave)
        reg = consultar(arquivo, d['ano'], d['mes'], d['indice'], caminho)
        if reg is None:
            if chave in indices_obrigatorios:
                divergencias.append({'tipo': 'registro_obrigatorio_ausente', 'arquivo': arquivo,
                                      'ano': d['ano'], 'mes': d['mes'], 'indice': d['indice']})
            continue
        if reg['valor'] is None or not math.isfinite(reg['valor']):
            if reg['classificacao'] != 'desconhecido':
                divergencias.append({'tipo': 'valor_invalido_no_registro', 'arquivo': arquivo,
                                      'ano': d['ano'], 'mes': d['mes'], 'indice': d['indice'],
                                      'classificacao': reg['classificacao'],
                                      'valor_proveniencia': reg['valor']})
            continue
        if abs(float(d['valor']) - reg['valor']) > 1e-9:
            divergencias.append({'tipo': 'valor_divergente', 'arquivo': arquivo,
                                  'ano': d['ano'], 'mes': d['mes'], 'indice': d['indice'],
                                  'valor_csv': d['valor'], 'valor_proveniencia': reg['valor']})

    indices_presentes = {d['indice'] for d in linhas_dado}
    for linha in linhas_prov:
        if linha['arquivo'] != arquivo or linha['indice'] not in indices_presentes:
            continue
        chave = _chave(linha)
        if chave not in chaves_dado:
            divergencias.append({'tipo': 'registro_orfao', 'arquivo': arquivo,
                                  'ano': chave[1], 'mes': chave[2], 'indice': chave[3]})

    return divergencias
