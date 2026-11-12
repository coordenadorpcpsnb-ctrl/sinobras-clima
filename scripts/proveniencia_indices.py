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


def _escrever(linhas, caminho=None):
    caminho = Path(caminho if caminho is not None else CAMINHO_PADRAO)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(caminho.suffix + '.tmp')
    with open(tmp, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS)
        w.writeheader()
        for linha in linhas:
            w.writerow({c: linha.get(c, '') for c in COLUNAS})
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


def verificar_consistencia(arquivo, linhas_dado, caminho=None):
    """
    `linhas_dado`: iterável de dicts {'ano','mes','indice','valor'} —
    o estado ATUAL do CSV de dado (master_monthly.csv/serie_subst.csv).

    Para cada linha com registro de proveniência correspondente,
    compara o valor atual do CSV com o valor que a proveniência
    registrou. Devolve a lista de divergências encontradas (nunca
    lança por si só — o chamador decide se bloqueia ou só avisa).
    """
    divergencias = []
    for d in linhas_dado:
        reg = consultar(arquivo, d['ano'], d['mes'], d['indice'], caminho)
        if reg is None:
            continue
        if reg['valor'] is None:
            continue
        if abs(float(d['valor']) - reg['valor']) > 1e-9:
            divergencias.append({
                'arquivo': arquivo, 'ano': d['ano'], 'mes': d['mes'],
                'indice': d['indice'], 'valor_csv': d['valor'],
                'valor_proveniencia': reg['valor'],
            })
    return divergencias
