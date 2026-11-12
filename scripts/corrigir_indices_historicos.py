#!/usr/bin/env python3
"""
corrigir_indices_historicos.py — correção controlada, célula a célula,
de valores de TSA já gravados em data/master_monthly.csv e/ou
data/serie_subst.csv, com registro de proveniência obrigatório.

Fase ENSO-INTEGRIDADE (Fase 2 revisada, confirmada por simulação na
Fase 3A): corrigir só setembro/2026 no master NÃO protege o lag 2-3
meses que alimentará o próprio set/out quando forem adicionados a
serie_subst.csv no ciclo de 21/11 — esse lag vem de jul/ago já
gravados em serie_subst.csv. Por isso o plano cobre as duas pontas.

Uso:
    python scripts/corrigir_indices_historicos.py               # dry-run (padrão)
    python scripts/corrigir_indices_historicos.py --dry-run     # idem, explícito
    python scripts/corrigir_indices_historicos.py --aplicar     # escreve de fato
    python scripts/corrigir_indices_historicos.py --rollback    # restaura do .bak mais recente

Design (pedidos explícitos da revisão externa):
  - PLANO é uma lista FECHADA de células — o script só sabe iterar
    essa lista; não existe caminho de código para alterar qualquer
    outra célula.
  - Cada célula tem um valor_antigo_esperado: se o valor atual não for
    nem o antigo esperado nem o novo (já aplicado), a correção daquela
    célula é abortada (estado inesperado, precisa de revisão humana) —
    nunca sobrescreve algo que não é o que o plano presume que é.
  - Idempotente: se o valor atual já é o valor_novo, a célula é
    marcada 'já aplicado' e nada é escrito.
  - A célula de outubro é condicional: só entra no plano REAL se uma
    consulta ao vivo (só leitura) ao PSL tsa.data confirmar que
    outubro/2026 ainda não tem observação real. Se a consulta
    encontrar um valor real, ou se a consulta falhar (rede
    indisponível), a célula de outubro é removida do plano por
    precaução e sinalizada para revisão manual — nunca aplicada às
    cegas.
  - Backup .bak timestamped antes de qualquer escrita real; rollback
    verifica hash SHA-256 contra o backup.
  - Escrita e proveniência são preparadas e validadas ANTES de
    qualquer substituição real do arquivo em disco — se a validação
    falhar para qualquer um dos dois, nenhum dos dois é escrito
    (nunca um arquivo atualizado sem o outro).
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import proveniencia_indices as prov

ROOT = Path(__file__).parent.parent
MASTER_PATH = ROOT / 'data' / 'master_monthly.csv'
SUBST_PATH = ROOT / 'data' / 'serie_subst.csv'
# Fase ENSO-INTEGRIDADE 3A.1: nenhuma constante de módulo captura
# proveniencia_indices.CAMINHO_PADRAO em tempo de import — aplicar()
# resolve o caminho da proveniência em tempo de CHAMADA (derivado de
# MASTER_PATH, ou do que `caminhos` explicitamente informar), mesma
# disciplina usada em fetch_monthly_data.py/update_indices.py/
# update_dashboard.py.

COLUNA_POR_ARQUIVO = {'master_monthly.csv': ('year', 'month'),
                      'serie_subst.csv': ('ano', 'mes')}

# ══════════════════════════════════════════════════════════════════
# Plano fechado — Fase 2 revisada / Fase 3A
# ══════════════════════════════════════════════════════════════════
PLANO_BASE = [
    {'arquivo': 'master_monthly.csv', 'ano': 2026, 'mes': 7, 'coluna': 'tsa',
     'valor_antigo_esperado': 0.20, 'valor_novo': 0.12, 'classificacao': 'observado',
     'meses_base': ['2026-07'], 'fonte': 'PSL tsa.data (verificado ao vivo)',
     'metodo': 'observacao_direta'},
    {'arquivo': 'master_monthly.csv', 'ano': 2026, 'mes': 8, 'coluna': 'tsa',
     'valor_antigo_esperado': 0.20, 'valor_novo': 0.42, 'classificacao': 'observado',
     'meses_base': ['2026-08'], 'fonte': 'PSL tsa.data (verificado ao vivo)',
     'metodo': 'observacao_direta'},
    {'arquivo': 'master_monthly.csv', 'ano': 2026, 'mes': 9, 'coluna': 'tsa',
     'valor_antigo_esperado': 0.12, 'valor_novo': 0.57, 'classificacao': 'observado',
     'meses_base': ['2026-09'], 'fonte': 'PSL tsa.data (verificado ao vivo)',
     'metodo': 'observacao_direta'},
    {'arquivo': 'serie_subst.csv', 'ano': 2026, 'mes': 7, 'coluna': 'tsa',
     'valor_antigo_esperado': 0.20, 'valor_novo': 0.12, 'classificacao': 'observado',
     'meses_base': ['2026-07'], 'fonte': 'PSL tsa.data (verificado ao vivo)',
     'metodo': 'observacao_direta'},
    {'arquivo': 'serie_subst.csv', 'ano': 2026, 'mes': 8, 'coluna': 'tsa',
     'valor_antigo_esperado': 0.20, 'valor_novo': 0.42, 'classificacao': 'observado',
     'meses_base': ['2026-08'], 'fonte': 'PSL tsa.data (verificado ao vivo)',
     'metodo': 'observacao_direta'},
]

CELULA_OUTUBRO_CONDICIONAL = {
    'arquivo': 'master_monthly.csv', 'ano': 2026, 'mes': 10, 'coluna': 'tsa',
    'valor_antigo_esperado': 0.12, 'valor_novo': 0.57, 'classificacao': 'persistido',
    'meses_base': ['2026-09'],
    'fonte': 'PSL tsa.data (verificado ao vivo) — persistência de set/2026, NÃO observação de outubro',
    'metodo': 'persistencia_ultimo_real',
}


def outubro_2026_tem_observacao_real(timeout=15):
    """
    Consulta ao vivo (só leitura, PSL — fora da lista de fontes vedadas
    nesta fase, que é CHIRPS/ClimateSERV/Open-Meteo) para confirmar se
    outubro/2026 já tem TSA real publicada. Devolve True/False/None
    (None = não foi possível confirmar — rede indisponível ou formato
    inesperado; tratado como "não aplicar", nunca como "aplicar às
    cegas").
    """
    try:
        req = urllib.request.Request(
            'https://psl.noaa.gov/data/correlation/tsa.data',
            headers={'User-Agent': 'sinobras-clima/1.0 (auditoria-enso-integridade)'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            texto = r.read().decode('utf-8', errors='replace')
        for linha in texto.splitlines():
            partes = linha.split()
            if len(partes) == 13 and partes[0] == '2026':
                valor_out = float(partes[10])   # col 0=ano, 1..12=jan..dez
                return abs(valor_out - (-99.99)) > 1e-6
        return None
    except Exception as e:
        print(f"  ⚠ não foi possível confirmar outubro/2026 ao vivo ({e}) — "
              f"célula de outubro removida do plano por precaução")
        return None


def montar_plano(incluir_outubro=True):
    """Monta o plano efetivo desta execução — outubro só entra se a
    consulta ao vivo confirmar ausência de observação real."""
    plano = list(PLANO_BASE)
    if not incluir_outubro:
        return plano, 'outubro omitido por instrução explícita'
    tem_real = outubro_2026_tem_observacao_real()
    if tem_real is True:
        return plano, ('outubro/2026 JÁ TEM observação real publicada — célula '
                        'removida do plano, requer revisão manual (o valor real '
                        'pode não ser 0.57; não presumir)')
    if tem_real is None:
        return plano, ('não foi possível confirmar o estado de outubro/2026 — '
                        'célula removida do plano por precaução')
    plano.append(CELULA_OUTUBRO_CONDICIONAL)
    return plano, 'outubro/2026 confirmado sem observação real — persistência de set/2026 incluída'


# ══════════════════════════════════════════════════════════════════
# Mecânica de leitura/escrita/validação
# ══════════════════════════════════════════════════════════════════
def sha256_arquivo(caminho):
    caminho = Path(caminho)
    if not caminho.exists():
        return None
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def _localizar_linha(df, chave_cols, ano, mes):
    a, m = chave_cols
    sel = df[(df[a].astype('Int64') == ano) & (df[m].astype('Int64') == mes)]
    if sel.empty:
        return None
    return sel.index[0]


def avaliar_celula(item, caminhos):
    """
    Lê o valor ATUAL da célula e classifica o status, sem escrever
    nada: 'pendente' (precisa mudar), 'ja_aplicado' (idempotente, nada
    a fazer), 'linha_ausente' (ano/mes não existe no arquivo) ou
    'inesperado' (valor atual não é nem o antigo esperado nem o novo —
    aborta por segurança, não decide por conta própria).
    """
    caminho = caminhos[item['arquivo']]
    chave_cols = COLUNA_POR_ARQUIVO[item['arquivo']]
    df = pd.read_csv(caminho)
    idx = _localizar_linha(df, chave_cols, item['ano'], item['mes'])
    if idx is None:
        return {'status': 'linha_ausente', 'valor_atual': None}

    valor_atual = df.at[idx, item['coluna']]
    if pd.isna(valor_atual):
        valor_atual = None
    else:
        valor_atual = float(valor_atual)

    if valor_atual is not None and abs(valor_atual - item['valor_novo']) < 1e-9:
        return {'status': 'ja_aplicado', 'valor_atual': valor_atual}
    if valor_atual is not None and abs(valor_atual - item['valor_antigo_esperado']) < 1e-9:
        return {'status': 'pendente', 'valor_atual': valor_atual}
    return {'status': 'inesperado', 'valor_atual': valor_atual}


def relatorio_dry_run(plano, caminhos):
    """Sempre seguro de chamar — nunca escreve nada. Devolve a lista de
    avaliações, uma por célula do plano."""
    relatorio = []
    for item in plano:
        avaliacao = avaliar_celula(item, caminhos)
        relatorio.append({**item, **avaliacao})
    return relatorio


def _linhas_diferentes(texto_antes, texto_depois):
    la = texto_antes.splitlines()
    lb = texto_depois.splitlines()
    return [i for i, (a, b) in enumerate(zip(la, lb)) if a != b] if len(la) == len(lb) else None


def _validar_so_coluna_alvo_mudou(caminho, texto_antes, texto_depois, celulas_tocadas, chave_cols):
    """
    Confere, por TEXTO (não só por lógica do pandas), que: (1) o número
    de linhas não mudou; (2) o número de linhas diferentes é EXATAMENTE
    o número de células tocadas; (3) em cada linha diferente, só o
    campo-alvo mudou — todos os outros campos daquela linha, idênticos.
    Levanta AssertionError (nunca silencioso) se qualquer uma falhar.
    """
    idx_dif = _linhas_diferentes(texto_antes, texto_depois)
    if idx_dif is None:
        raise AssertionError(f"{caminho}: número de linhas mudou — reformatação inesperada")
    if len(idx_dif) != len(celulas_tocadas):
        raise AssertionError(
            f"{caminho}: {len(idx_dif)} linha(s) diferente(s), esperado exatamente "
            f"{len(celulas_tocadas)} (uma por célula tocada)")

    cabecalho = texto_antes.splitlines()[0].split(',')
    for i in idx_dif:
        campos_antes = texto_antes.splitlines()[i].split(',')
        campos_depois = texto_depois.splitlines()[i].split(',')
        divergentes = [c for c, va, vd in zip(cabecalho, campos_antes, campos_depois) if va != vd]
        if len(divergentes) != 1:
            raise AssertionError(
                f"{caminho}, linha {i+1}: {len(divergentes)} coluna(s) mudaram "
                f"({divergentes}) — esperado exatamente 1")


def aplicar(plano, caminhos=None, confirmar_outubro_mensagem=None):
    """
    Executa de fato o plano (modo --aplicar). `caminhos` por padrão
    aponta para os arquivos REAIS do repositório — em teste, SEMPRE
    sobrescrever com cópias isoladas em tmpdir.

    Passos (nessa ordem, nunca escreve o arquivo real antes de validar
    tudo): avaliar cada célula -> abortar tudo se qualquer uma for
    'inesperado' ou 'linha_ausente' -> para cada arquivo tocado,
    backup .bak -> escrever em .tmp -> validar .tmp por texto (só a(s)
    coluna(s) certa(s) mudou(aram)) -> só then os.replace -> registrar
    proveniência -> checar consistência final.

    Devolve um relatório dict; nunca deixa um arquivo parcialmente
    escrito (se a validação falhar para qualquer arquivo, nenhum dos
    arquivos tocados nesta chamada é substituído).
    """
    caminhos = caminhos or {'master_monthly.csv': MASTER_PATH, 'serie_subst.csv': SUBST_PATH}
    prov_path = caminhos.get('_proveniencia') or (
        Path(caminhos['master_monthly.csv']).parent / 'indices_proveniencia.csv')

    avaliacoes = relatorio_dry_run(plano, caminhos)
    bloqueantes = [a for a in avaliacoes if a['status'] in ('inesperado', 'linha_ausente')]
    if bloqueantes:
        return {'aplicado': False, 'motivo': 'celulas_inesperadas', 'detalhe': bloqueantes,
                'avaliacoes': avaliacoes}

    pendentes = [a for a in avaliacoes if a['status'] == 'pendente']
    if not pendentes:
        return {'aplicado': True, 'motivo': 'nada_a_fazer_idempotente', 'avaliacoes': avaliacoes}

    por_arquivo = {}
    for item in pendentes:
        por_arquivo.setdefault(item['arquivo'], []).append(item)

    textos_antes, textos_depois, hashes_antes, backups = {}, {}, {}, {}
    try:
        for arquivo, itens in por_arquivo.items():
            caminho = Path(caminhos[arquivo])
            texto_antes = caminho.read_text(encoding='utf-8')
            hashes_antes[arquivo] = hashlib.sha256(texto_antes.encode('utf-8')).hexdigest()

            df = pd.read_csv(caminho)
            chave_cols = COLUNA_POR_ARQUIVO[arquivo]
            for item in itens:
                idx = _localizar_linha(df, chave_cols, item['ano'], item['mes'])
                df.at[idx, item['coluna']] = item['valor_novo']

            tmp = caminho.with_suffix(caminho.suffix + '.tmp')
            df.to_csv(tmp, index=False)
            texto_depois = tmp.read_text(encoding='utf-8')
            _validar_so_coluna_alvo_mudou(caminho, texto_antes, texto_depois, itens, chave_cols)

            textos_antes[arquivo] = texto_antes
            textos_depois[arquivo] = texto_depois
    except Exception as e:
        # nada foi substituído ainda (só .tmp, que descartamos) —
        # arquivos reais permanecem intocados.
        for arquivo in por_arquivo:
            tmp = Path(caminhos[arquivo]).with_suffix('.csv.tmp')
            if tmp.exists():
                tmp.unlink()
        return {'aplicado': False, 'motivo': f'validacao_falhou: {e}', 'avaliacoes': avaliacoes}

    agora = datetime.now(timezone.utc).isoformat()
    for arquivo, itens in por_arquivo.items():
        caminho = Path(caminhos[arquivo])
        backup = caminho.with_name(caminho.stem + f'.{agora.replace(":", "-")}.bak')
        shutil.copy2(caminho, backup)
        backups[arquivo] = str(backup)
        tmp = caminho.with_suffix(caminho.suffix + '.tmp')
        tmp.replace(caminho)

    for arquivo, itens in por_arquivo.items():
        for item in itens:
            prov.registrar(arquivo, item['ano'], item['mes'], item['coluna'],
                            item['valor_novo'], item['classificacao'], item['meses_base'],
                            item['fonte'], item['metodo'], verificado_em=agora, caminho=prov_path)

    divergencias = []
    for arquivo in por_arquivo:
        df_final = pd.read_csv(caminhos[arquivo])
        chave_cols = COLUNA_POR_ARQUIVO[arquivo]
        linhas_dado = [{'ano': int(r[chave_cols[0]]), 'mes': int(r[chave_cols[1]]),
                         'indice': 'tsa', 'valor': float(r['tsa'])}
                       for _, r in df_final.iterrows()
                       if (int(r[chave_cols[0]]), int(r[chave_cols[1]])) in
                          {(it['ano'], it['mes']) for it in por_arquivo[arquivo]}]
        divergencias += prov.verificar_consistencia(arquivo, linhas_dado, prov_path)

    return {'aplicado': True, 'motivo': 'ok', 'avaliacoes': avaliacoes,
            'backups': backups, 'hashes_antes': hashes_antes,
            'divergencias_pos_escrita': divergencias}


def rollback(caminhos=None):
    """Restaura cada arquivo a partir do .bak mais recente encontrado
    no mesmo diretório, verificando hash após a restauração."""
    caminhos = caminhos or {'master_monthly.csv': MASTER_PATH, 'serie_subst.csv': SUBST_PATH}
    resultado = {}
    for arquivo, caminho in caminhos.items():
        if arquivo == '_proveniencia':
            continue
        caminho = Path(caminho)
        candidatos = sorted(caminho.parent.glob(f'{caminho.stem}.*.bak'))
        if not candidatos:
            resultado[arquivo] = {'restaurado': False, 'motivo': 'nenhum .bak encontrado'}
            continue
        mais_recente = candidatos[-1]
        hash_bak = sha256_arquivo(mais_recente)
        shutil.copy2(mais_recente, caminho)
        hash_depois = sha256_arquivo(caminho)
        resultado[arquivo] = {'restaurado': hash_depois == hash_bak,
                               'backup_usado': str(mais_recente)}
    return resultado


def _cli():
    p = argparse.ArgumentParser(description=__doc__)
    modo = p.add_mutually_exclusive_group()
    modo.add_argument('--dry-run', action='store_true', help='(padrão) só mostra o que mudaria')
    modo.add_argument('--aplicar', action='store_true', help='escreve de fato nos arquivos reais')
    modo.add_argument('--rollback', action='store_true', help='restaura do .bak mais recente')
    p.add_argument('--sem-outubro', action='store_true',
                    help='não incluir a célula condicional de outubro/2026 no plano')
    args = p.parse_args()

    caminhos = {'master_monthly.csv': MASTER_PATH, 'serie_subst.csv': SUBST_PATH}

    if args.rollback:
        resultado = rollback(caminhos)
        for arquivo, r in resultado.items():
            print(f"{arquivo}: {r}")
        return 0

    plano, motivo_outubro = montar_plano(incluir_outubro=not args.sem_outubro)
    print(f"Plano desta execução ({len(plano)} célula(s)) — outubro/2026: {motivo_outubro}\n")

    if args.aplicar:
        resultado = aplicar(plano, caminhos)
        print(resultado)
        return 0 if resultado['aplicado'] else 1

    for a in relatorio_dry_run(plano, caminhos):
        print(f"  [{a['status']:>12}] {a['arquivo']} {a['ano']}/{a['mes']:02d} "
              f"{a['coluna']}: atual={a['valor_atual']} -> novo={a['valor_novo']} "
              f"({a['classificacao']}, base={a['meses_base']})")
    return 0


if __name__ == '__main__':
    sys.exit(_cli())
