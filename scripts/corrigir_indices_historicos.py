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
    python scripts/corrigir_indices_historicos.py                  # dry-run (padrão)
    python scripts/corrigir_indices_historicos.py --dry-run        # idem, explícito
    python scripts/corrigir_indices_historicos.py --aplicar        # escreve de fato
    python scripts/corrigir_indices_historicos.py --rollback       # reverte a última transação concluída
    python scripts/corrigir_indices_historicos.py --recuperar-falha  # recupera uma transação INCOMPLETA

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
  - Fase ENSO-INTEGRIDADE 3A.3 (recuperação pós-falha): os dois CSVs
    E a proveniência são preparados e validados em memória ANTES de
    qualquer substituição real; backup de TODOS os três (proveniência
    só se já existia — a ausência prévia é registrada, não perdida)
    antes de qualquer escrita; substituição real registrada passo a
    passo num manifesto, nunca apagado se a transação falhar no meio
    — `recuperar_falha()` usa esse manifesto para restaurar o conjunto
    completo e é idempotente (no-op se não houver transação pendente).
    `rollback()` agora também restaura (ou remove, se nunca existiu) a
    proveniência, usando o manifesto da última transação concluída.
    Cada os.replace() individual é atômico; o CONJUNTO dos três
    arquivos nunca é tratado como se fosse — é exatamente por isso que
    o manifesto e a recuperação existem.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
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
# Recuperação pós-falha (Fase ENSO-INTEGRIDADE 3A.3) — manifesto
# ══════════════════════════════════════════════════════════════════
# IMPORTANTE: cada os.replace() individual (um por arquivo) É atômico
# na mesma partição — mas isso NÃO torna a operação como um todo
# atômica entre os três arquivos (master_monthly.csv, serie_subst.csv
# e a proveniência). Se o processo morrer entre duas substituições, o
# conjunto fica num estado intermediário real no disco. O manifesto
# abaixo não finge que essa janela não existe: ele registra, passo a
# passo, o que já foi de fato substituído, para que uma falha deixe
# rastro verificável e recuperável — nunca um estado "ou tudo ou
# nada" automático (isso exigiria um mecanismo transacional que este
# projeto não tem e não finge ter).
MANIFESTO_NOME = '.corrigir_indices_historicos.ativo.json'

_CAMPOS_OBRIGATORIOS_MANIFESTO = {'status', 'iniciado_em', 'arquivos'}


class ManifestoInvalido(Exception):
    """Levantada quando um manifesto EXISTE no disco mas está
    malformado (JSON truncado/corrompido) ou estruturalmente inválido
    (campos obrigatórios ausentes). Nunca tratada como "nenhuma
    transação pendente" — isso mascararia uma transação real cujo
    estado não pode ser confiavelmente lido, abrindo caminho para
    `aplicar()` começar uma transação nova por cima de um estado
    desconhecido, ou para `recuperar_falha()`/`rollback()` tentarem
    uma recuperação "destrutiva às cegas" sem saber o que de fato foi
    substituído. Os backups .bak no mesmo diretório nunca são tocados
    quando esta exceção é levantada — ficam preservados para
    recuperação manual supervisionada."""


def _manifesto_path(caminhos):
    return Path(caminhos['master_monthly.csv']).parent / MANIFESTO_NOME


def _validar_manifesto(dados, caminho):
    """Validação estrutural explícita — nunca assume que um JSON que
    parseou com sucesso tem o formato esperado."""
    if not isinstance(dados, dict):
        raise ManifestoInvalido(f"{caminho}: conteúdo não é um objeto JSON (manifesto corrompido)")
    faltando = _CAMPOS_OBRIGATORIOS_MANIFESTO - set(dados.keys())
    if faltando:
        raise ManifestoInvalido(
            f"{caminho}: campo(s) obrigatório(s) ausente(s) {sorted(faltando)} "
            f"(manifesto estruturalmente inválido)")
    if not isinstance(dados['arquivos'], dict) or not dados['arquivos']:
        raise ManifestoInvalido(f"{caminho}: campo 'arquivos' ausente, vazio ou não é um objeto")
    for arquivo, info in dados['arquivos'].items():
        if not isinstance(info, dict) or 'caminho' not in info or 'substituido' not in info:
            raise ManifestoInvalido(
                f"{caminho}: entrada 'arquivos.{arquivo}' malformada (faltam 'caminho'/'substituido')")
    return dados


def _ler_manifesto(caminhos):
    """Lê e valida o manifesto ATIVO. Devolve None só quando o arquivo
    genuinamente não existe (nenhuma transação pendente) — nunca para
    um arquivo presente, mas ilegível/malformado, caso em que levanta
    ManifestoInvalido (erro acionável) em vez de mascarar o problema
    como ausência."""
    p = _manifesto_path(caminhos)
    if not p.exists():
        return None
    try:
        dados = json.loads(p.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        raise ManifestoInvalido(
            f"{p}: JSON malformado ({e}) — provável truncamento por interrupção durante a "
            f"própria escrita do manifesto. NÃO use para recuperação automática; inspecione "
            f"manualmente este arquivo e os backups .bak no mesmo diretório.")
    return _validar_manifesto(dados, p)


def _escrever_manifesto(caminhos, dados):
    """Escrita atômica: grava em .tmp no MESMO diretório, fsync antes
    do replace (quando o SO suporta — best effort, nunca falha a
    operação por isso) e só então substitui o arquivo final via
    os.replace(). Uma interrupção no meio desta função deixa, no
    máximo, um .tmp parcial — o manifesto ATIVO (o nome que
    _ler_manifesto procura) nunca fica truncado, porque só passa a
    existir com esse nome depois do replace atômico."""
    p = _manifesto_path(caminhos)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + '.tmp')
    texto = json.dumps(dados, indent=2, ensure_ascii=False)
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(texto)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass   # sistema de arquivos/ambiente sem suporte a fsync — best effort, não fatal
    tmp.replace(p)


def _remover_manifesto(caminhos):
    p = _manifesto_path(caminhos)
    if p.exists():
        p.unlink()


def _arquivar_manifesto_concluido(caminhos, dados):
    """Em vez de apagar o manifesto de uma transação concluída com
    sucesso, arquiva-o com nome timestamped — histórico necessário
    para que um rollback() manual, feito bem depois, ainda saiba se a
    proveniência existia antes daquela correção (sem isso, perder o
    manifesto perde a única forma confiável de saber se deve restaurar
    ou simplesmente apagar a proveniência numa reversão manual).
    Mesma disciplina de escrita atômica de _escrever_manifesto()."""
    ativo = _manifesto_path(caminhos)
    ts = dados['concluido_em'].replace(':', '-')
    historico = ativo.with_name(f'.corrigir_indices_historicos.{ts}.concluido.json')
    tmp = historico.with_name(historico.name + '.tmp')
    texto = json.dumps(dados, indent=2, ensure_ascii=False)
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(texto)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    tmp.replace(historico)
    if ativo.exists():
        ativo.unlink()
    return historico


def _historico_mais_recente(caminhos):
    """Lê e valida o manifesto arquivado mais recente. Mesma regra de
    _ler_manifesto(): um arquivo ausente devolve None (sem histórico
    ainda); um arquivo presente mas corrompido levanta
    ManifestoInvalido — nunca tratado como "sem histórico", o que
    faria rollback() cair silenciosamente no modo antigo (sem
    restaurar a proveniência) por um motivo errado (corrupção, não
    ausência genuína)."""
    base = _manifesto_path(caminhos).parent
    candidatos = sorted(base.glob('.corrigir_indices_historicos.*.concluido.json'))
    if not candidatos:
        return None
    p = candidatos[-1]
    try:
        dados = json.loads(p.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        raise ManifestoInvalido(
            f"{p}: JSON malformado ({e}) — manifesto histórico corrompido. "
            f"Inspecione manualmente antes de confiar em qualquer rollback automático.")
    return _validar_manifesto(dados, p)


def _substituir(tmp, destino):
    """Ponto único de substituição real (os.replace via Path.replace)
    — isolado numa função própria só para que testes de injeção de
    falha possam patchear exatamente este choke point, sem precisar
    mockar Path.replace globalmente (o que afetaria código não
    relacionado)."""
    tmp.replace(destino)


def _restaurar_pelo_manifesto(manifesto, caminhos):
    """
    Restaura o conjunto completo (os CSVs tocados + a proveniência) a
    partir dos backups registrados em `manifesto`, verificando hash
    após cada restauração. Usado tanto pela recuperação pós-falha
    (manifesto ainda ativo) quanto pelo rollback manual (manifesto
    arquivado de uma transação já concluída). Preserva a distinção
    entre "proveniência não existia antes" (remove, nunca deixa um
    arquivo criado por esta ferramenta sobrar após a reversão) e
    "proveniência existia com outro conteúdo" (restaura do backup).
    """
    resultado = {}
    for arquivo, info in manifesto['arquivos'].items():
        caminho = Path(info['caminho'])
        if arquivo == '_proveniencia' and not info.get('existia_antes', True):
            if caminho.exists():
                caminho.unlink()
            resultado[arquivo] = {'restaurado': True, 'acao': 'removido (não existia antes da transação)'}
            continue
        backup = info.get('backup')
        if not backup or not Path(backup).exists():
            resultado[arquivo] = {'restaurado': False, 'motivo': 'backup ausente ou não encontrado'}
            continue
        shutil.copy2(backup, caminho)
        hash_depois = sha256_arquivo(caminho)
        resultado[arquivo] = {'restaurado': hash_depois == info.get('hash_antes'),
                               'backup_usado': str(backup), 'hash_esperado': info.get('hash_antes'),
                               'hash_obtido': hash_depois}
    return resultado

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

    Passos, nesta ordem — nenhum arquivo REAL é tocado antes de TODO o
    conteúdo novo (dos dois CSVs e da proveniência) estar preparado e
    validado em memória:
      1. avaliar cada célula -> abortar tudo se qualquer uma for
         'inesperado' ou 'linha_ausente' (nenhum arquivo tocado).
      2. se não há pendentes -> idempotente, nenhum arquivo tocado.
      3. se já existe um manifesto de transação incompleta (uma
         chamada anterior falhou no meio) -> abortar e instruir a
         chamar recuperar_falha() primeiro — nunca tentar aplicar por
         cima de um estado não resolvido.
      4. preparar o texto novo dos CSVs tocados + o texto novo da
         proveniência (via prov.preparar_lote/renderizar_texto, SEM
         escrever nada) e validar tudo (_validar_so_coluna_alvo_mudou
         para os CSVs); qualquer falha aqui não deixa rastro em disco.
      5. backup de TODOS os arquivos tocados (os dois CSVs SEMPRE; a
         proveniência só se já existia — a ausência prévia é
         registrada explicitamente no manifesto, nunca perdida) ANTES
         de qualquer substituição real; grava o manifesto com o que
         foi preparado.
      6. substituir os arquivos reais, um a um, atualizando o
         manifesto a cada substituição concluída — uma falha aqui
         deixa o manifesto registrando exatamente o que já foi
         substituído, nunca um estado invisível.
      7. verificação final: hash de cada arquivo contra o esperado +
         prov.verificar_consistencia() (com as células recém-escritas
         marcadas como `indices_obrigatorios` — a proveniência dessas
         células específicas É obrigatória, por serem uma escrita
         nova do próprio mecanismo ENSO-INTEGRIDADE).
      8. manifesto arquivado (não apagado) como histórico — necessário
         para que um rollback() manual, feito bem depois, ainda saiba
         se deve restaurar ou remover a proveniência.

    Nunca afirma atomicidade transacional entre os três arquivos — só
    porque cada substituição individual (os.replace) é atômica não
    significa que o CONJUNTO é; é exatamente por isso que o manifesto
    e recuperar_falha() existem.
    """
    caminhos = caminhos or {'master_monthly.csv': MASTER_PATH, 'serie_subst.csv': SUBST_PATH}
    prov_path = Path(caminhos.get('_proveniencia') or (
        Path(caminhos['master_monthly.csv']).parent / 'indices_proveniencia.csv'))

    # Checado ANTES de tudo, inclusive do caminho idempotente — uma
    # transação incompleta anterior precisa ser resolvida mesmo que,
    # por coincidência, todas as células do plano atual já estejam no
    # valor novo (o que não garante que a proveniência/manifesto
    # daquela transação tenham sido corretamente arquivados).
    try:
        manifesto_pendente = _ler_manifesto(caminhos)
    except ManifestoInvalido as e:
        return {'aplicado': False, 'motivo': 'manifesto_corrompido', 'erro': str(e),
                'acao_requerida': 'manifesto malformado — não iniciar nova aplicação; inspecionar '
                                   'manualmente o arquivo e os backups .bak preservados no mesmo diretório'}
    if manifesto_pendente is not None:
        return {'aplicado': False, 'motivo': 'transacao_anterior_incompleta_detectada',
                'manifesto': manifesto_pendente,
                'acao_requerida': 'chamar recuperar_falha(caminhos) antes de tentar aplicar de novo'}

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

    # ── Fase 1: preparar e validar TUDO em memória, nada em disco real ──
    textos_antes, textos_depois = {}, {}
    try:
        for arquivo, itens in por_arquivo.items():
            caminho = Path(caminhos[arquivo])
            texto_antes = caminho.read_text(encoding='utf-8')

            df = pd.read_csv(caminho)
            chave_cols = COLUNA_POR_ARQUIVO[arquivo]
            for item in itens:
                idx = _localizar_linha(df, chave_cols, item['ano'], item['mes'])
                df.at[idx, item['coluna']] = item['valor_novo']
            texto_depois = df.to_csv(index=False)
            _validar_so_coluna_alvo_mudou(caminho, texto_antes, texto_depois, itens, chave_cols)

            textos_antes[arquivo] = texto_antes
            textos_depois[arquivo] = texto_depois

        entradas_prov = [
            {'arquivo': item['arquivo'], 'ano': item['ano'], 'mes': item['mes'],
             'indice': item['coluna'], 'valor': item['valor_novo'],
             'classificacao': item['classificacao'], 'meses_base': item['meses_base'],
             'fonte': item['fonte'], 'metodo': item['metodo']}
            for item in pendentes
        ]
        prov_existia_antes = prov_path.exists()
        if prov_existia_antes:
            # newline='' preserva o \r\n literal que csv.DictWriter já
            # grava na proveniência — Path.read_text() em modo texto
            # padrão traduziria \r\n -> \n (universal newlines),
            # produzindo um hash DIFERENTE do hash real do arquivo
            # (sha256_arquivo(), que lê bytes crus) e quebrando a
            # verificação de hash depois de uma restauração.
            with open(prov_path, 'r', newline='', encoding='utf-8') as f:
                texto_prov_antes = f.read()
        else:
            texto_prov_antes = None
        linhas_prov_novas, anteriores_prov = prov.preparar_lote(entradas_prov, caminho=prov_path)
        texto_prov_depois = prov.renderizar_texto(linhas_prov_novas)
    except Exception as e:
        return {'aplicado': False, 'motivo': f'preparacao_ou_validacao_falhou: {e}',
                'avaliacoes': avaliacoes}

    # sinalizar (nunca sobrescrever em silêncio) proveniência anterior
    # contraditória — um valor/classificação que já existia e diverge
    # do que está sendo gravado agora.
    contradicoes = []
    for (arq, ano, mes, indice), anterior in anteriores_prov.items():
        if anterior is None:
            continue
        novo = next(it for it in pendentes
                    if it['arquivo'] == arq and it['ano'] == ano and it['mes'] == mes
                    and it['coluna'] == indice)
        valor_anterior = float(anterior['valor']) if anterior.get('valor') not in ('', None) else None
        if (anterior.get('classificacao') != novo['classificacao']
                or valor_anterior is None or abs(valor_anterior - novo['valor_novo']) > 1e-9):
            contradicoes.append({'arquivo': arq, 'ano': ano, 'mes': mes, 'indice': indice,
                                  'classificacao_anterior': anterior.get('classificacao'),
                                  'valor_anterior': valor_anterior,
                                  'classificacao_nova': novo['classificacao'],
                                  'valor_novo': novo['valor_novo']})

    # ── Fase 2: backup de TUDO (dois CSVs + proveniência) ANTES de
    #            qualquer substituição real; grava o manifesto ──────────
    agora = datetime.now(timezone.utc).isoformat()
    sufixo_ts = agora.replace(':', '-')
    manifesto = {'status': 'backup_concluido', 'iniciado_em': agora, 'arquivos': {}}
    backups = {}
    for arquivo in por_arquivo:
        caminho = Path(caminhos[arquivo])
        backup = caminho.with_name(caminho.stem + f'.{sufixo_ts}.bak')
        shutil.copy2(caminho, backup)
        backups[arquivo] = str(backup)
        manifesto['arquivos'][arquivo] = {
            'caminho': str(caminho), 'backup': str(backup),
            'hash_antes': hashlib.sha256(textos_antes[arquivo].encode('utf-8')).hexdigest(),
            'hash_depois_esperado': hashlib.sha256(textos_depois[arquivo].encode('utf-8')).hexdigest(),
            'substituido': False,
        }

    if prov_existia_antes:
        backup_prov = prov_path.with_name(prov_path.stem + f'.{sufixo_ts}.bak')
        shutil.copy2(prov_path, backup_prov)
        manifesto['arquivos']['_proveniencia'] = {
            'caminho': str(prov_path), 'backup': str(backup_prov), 'existia_antes': True,
            'hash_antes': hashlib.sha256(texto_prov_antes.encode('utf-8')).hexdigest(),
            'hash_depois_esperado': hashlib.sha256(texto_prov_depois.encode('utf-8')).hexdigest(),
            'substituido': False,
        }
    else:
        manifesto['arquivos']['_proveniencia'] = {
            'caminho': str(prov_path), 'backup': None, 'existia_antes': False,
            'hash_antes': None,
            'hash_depois_esperado': hashlib.sha256(texto_prov_depois.encode('utf-8')).hexdigest(),
            'substituido': False,
        }
    _escrever_manifesto(caminhos, manifesto)

    # ── Fase 3: substituição real, uma a uma, manifesto atualizado a
    #            cada passo — uma falha aqui deixa rastro verificável ──
    try:
        for arquivo in por_arquivo:
            caminho = Path(caminhos[arquivo])
            tmp = caminho.with_suffix(caminho.suffix + '.tmp')
            tmp.write_text(textos_depois[arquivo], encoding='utf-8')
            _substituir(tmp, caminho)
            manifesto['arquivos'][arquivo]['substituido'] = True
            manifesto['status'] = 'aplicando'
            _escrever_manifesto(caminhos, manifesto)

        prov_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_prov = prov_path.with_suffix(prov_path.suffix + '.tmp')
        with open(tmp_prov, 'w', newline='', encoding='utf-8') as f:
            f.write(texto_prov_depois)
        _substituir(tmp_prov, prov_path)
        manifesto['arquivos']['_proveniencia']['substituido'] = True
        _escrever_manifesto(caminhos, manifesto)
    except Exception as e:
        # Estado parcialmente aplicado — o manifesto (ainda em disco,
        # NUNCA removido aqui) registra exatamente o que já foi
        # substituído. recuperar_falha() usa esse mesmo manifesto.
        return {'aplicado': False, 'motivo': f'escrita_falhou_estado_parcial: {e}',
                'avaliacoes': avaliacoes, 'manifesto': manifesto,
                'acao_requerida': 'chamar recuperar_falha(caminhos) para restaurar o estado anterior'}

    # ── Fase 4: verificação final (hash + consistência) ─────────────────
    hash_mismatch = []
    for arquivo, info in manifesto['arquivos'].items():
        h_real = sha256_arquivo(Path(info['caminho']))
        if h_real != info['hash_depois_esperado']:
            hash_mismatch.append(arquivo)

    divergencias = []
    for arquivo in por_arquivo:
        df_final = pd.read_csv(caminhos[arquivo])
        chave_cols = COLUNA_POR_ARQUIVO[arquivo]
        celulas_tocadas = {(it['ano'], it['mes'], it['coluna']) for it in por_arquivo[arquivo]}
        linhas_dado = [{'ano': int(r[chave_cols[0]]), 'mes': int(r[chave_cols[1]]),
                         'indice': it['coluna'], 'valor': float(r[it['coluna']])}
                       for _, r in df_final.iterrows()
                       for it in por_arquivo[arquivo]
                       if (int(r[chave_cols[0]]), int(r[chave_cols[1]])) == (it['ano'], it['mes'])]
        obrigatorios = {(arquivo, it['ano'], it['mes'], it['coluna']) for it in por_arquivo[arquivo]}
        divergencias += prov.verificar_consistencia(arquivo, linhas_dado, prov_path,
                                                      indices_obrigatorios=obrigatorios)

    # Fase ENSO-INTEGRIDADE 3A.5: hash divergente OU qualquer
    # inconsistência pós-escrita REPROVA a operação — nunca arquivar
    # a transação como concluída sem checar isso primeiro. Antes desta
    # correção, `hash_mismatch`/`divergencias` eram calculados mas a
    # função sempre devolvia aplicado=True e arquivava como concluída
    # de qualquer forma, descartando a única informação que permitiria
    # recuperar_falha() agir. O manifesto continua ATIVO (não
    # arquivado) quando isso acontece, exatamente como numa falha de
    # escrita — recuperar_falha() restaura os dois CSVs e a
    # proveniência a partir dele.
    if hash_mismatch or divergencias:
        manifesto['status'] = 'falhou_verificacao_pos_escrita'
        manifesto['hash_mismatch_pos_escrita'] = hash_mismatch
        manifesto['divergencias_pos_escrita'] = divergencias
        _escrever_manifesto(caminhos, manifesto)
        return {'aplicado': False, 'motivo': 'verificacao_pos_escrita_falhou',
                'avaliacoes': avaliacoes, 'backups': backups,
                'hash_mismatch_pos_escrita': hash_mismatch,
                'divergencias_pos_escrita': divergencias, 'manifesto': manifesto,
                'acao_requerida': 'chamar recuperar_falha(caminhos) para restaurar o estado anterior'}

    manifesto['status'] = 'concluido'
    manifesto['concluido_em'] = datetime.now(timezone.utc).isoformat()
    _arquivar_manifesto_concluido(caminhos, manifesto)

    return {'aplicado': True, 'motivo': 'ok', 'avaliacoes': avaliacoes,
            'backups': backups, 'divergencias_pos_escrita': divergencias,
            'hash_mismatch_pos_escrita': hash_mismatch,
            'contradicoes_proveniencia_anterior': contradicoes}


def recuperar_falha(caminhos=None):
    """
    Recuperação pós-falha: restaura o conjunto completo (os CSVs
    tocados + a proveniência) a partir do manifesto de uma transação
    que `aplicar()` deixou incompleta. Idempotente — se não houver
    manifesto ativo (nenhuma transação pendente de recuperação, ou já
    recuperada antes), devolve um no-op explícito em vez de tentar
    adivinhar o que fazer. Nunca toca em transações já concluídas
    (essas são responsabilidade de rollback(), não desta função).
    """
    caminhos = caminhos or {'master_monthly.csv': MASTER_PATH, 'serie_subst.csv': SUBST_PATH}
    try:
        manifesto = _ler_manifesto(caminhos)
    except ManifestoInvalido as e:
        # Nunca recuperação destrutiva às cegas: um manifesto corrompido
        # não é "nenhuma transação pendente" — é um estado desconhecido.
        # Os backups .bak permanecem intocados para inspeção manual.
        return {'recuperado': False, 'motivo': 'manifesto_corrompido', 'erro': str(e),
                'acao_requerida': 'inspecionar manualmente o manifesto e os backups .bak '
                                   'preservados no mesmo diretório'}
    if manifesto is None:
        return {'recuperado': False, 'motivo': 'nenhuma_transacao_incompleta_pendente'}

    resultado = _restaurar_pelo_manifesto(manifesto, caminhos)
    todos_ok = all(r.get('restaurado') for r in resultado.values())
    if todos_ok:
        _remover_manifesto(caminhos)
    return {'recuperado': todos_ok, 'detalhe': resultado}


def rollback(caminhos=None):
    """
    Reversão manual (CLI `--rollback`) do conjunto completo — os dois
    CSVs e a proveniência, não só os CSVs como antes desta fase.
    Ordem de resolução:
      1. Se há uma transação INCOMPLETA (manifesto ativo) -> essa é a
         prioridade; restaura a partir dela (mesma lógica de
         recuperar_falha()).
      2. Senão, usa o manifesto da transação CONCLUÍDA mais recente
         (arquivado por aplicar()) — é o que permite restaurar a
         proveniência corretamente (inclusive remover, se ela não
         existia antes daquela correção), não só os CSVs.
      3. Se não houver manifesto nenhum (correção aplicada antes desta
         fase, só com os .bak antigos) -> cai no comportamento antigo
         (glob do .bak mais recente por CSV) e AVISA explicitamente
         que a proveniência não pôde ser revertida por falta de
         registro — nunca finge que foi revertida.
    """
    caminhos = caminhos or {'master_monthly.csv': MASTER_PATH, 'serie_subst.csv': SUBST_PATH}

    try:
        manifesto_ativo = _ler_manifesto(caminhos)
    except ManifestoInvalido as e:
        # Nunca cair para o modo antigo (.bak sem manifesto) por causa
        # de corrupção — isso reverteria só os CSVs, silenciosamente
        # incompleto, por um motivo que não é "ausência genuína".
        return {'_origem': 'manifesto_corrompido', 'erro': str(e),
                'acao_requerida': 'inspecionar manualmente o manifesto ativo e os backups .bak '
                                   'preservados no mesmo diretório antes de qualquer reversão'}
    if manifesto_ativo is not None:
        resultado = _restaurar_pelo_manifesto(manifesto_ativo, caminhos)
        if all(r.get('restaurado') for r in resultado.values()):
            _remover_manifesto(caminhos)
        return {**resultado, '_origem': 'transacao_incompleta_recuperada'}

    try:
        manifesto_historico = _historico_mais_recente(caminhos)
    except ManifestoInvalido as e:
        return {'_origem': 'manifesto_historico_corrompido', 'erro': str(e),
                'acao_requerida': 'inspecionar manualmente o manifesto histórico mais recente e '
                                   'os backups .bak preservados antes de qualquer reversão'}
    if manifesto_historico is not None:
        resultado = _restaurar_pelo_manifesto(manifesto_historico, caminhos)
        return {**resultado, '_origem': 'manifesto_historico'}

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
    resultado['_proveniencia'] = {
        'restaurado': False,
        'motivo': 'nenhum manifesto encontrado — correção aplicada antes da Fase 3A.3 '
                   'ou sem registro; proveniência NÃO revertida automaticamente',
    }
    resultado['_origem'] = 'bak_sem_manifesto'
    return resultado


def _cli():
    p = argparse.ArgumentParser(description=__doc__)
    modo = p.add_mutually_exclusive_group()
    modo.add_argument('--dry-run', action='store_true', help='(padrão) só mostra o que mudaria')
    modo.add_argument('--aplicar', action='store_true', help='escreve de fato nos arquivos reais')
    modo.add_argument('--rollback', action='store_true',
                       help='reverte a última transação concluída (CSVs + proveniência)')
    modo.add_argument('--recuperar-falha', action='store_true', dest='recuperar_falha',
                       help='recupera uma transação INCOMPLETA (aplicar() interrompido no meio)')
    p.add_argument('--sem-outubro', action='store_true',
                    help='não incluir a célula condicional de outubro/2026 no plano')
    args = p.parse_args()

    caminhos = {'master_monthly.csv': MASTER_PATH, 'serie_subst.csv': SUBST_PATH}

    if args.recuperar_falha:
        resultado = recuperar_falha(caminhos)
        print(resultado)
        return 0 if resultado['recuperado'] else 1

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
