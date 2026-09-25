#!/usr/bin/env python3
"""
nmme_extracao_historica.py — Fase 2C.2, extração histórica completa do
CFSv2 (240 inicializações mensais, 1991-2010), em LOTES independentes
com retomada.

Contexto: o piloto de 16 inicializações (scripts/nmme_piloto_historico.py)
rodou de verdade e foi aprovado (GitHub Actions run 36145108571,
16/16 origens, rota IRIDL_LEGACY/NMME_HARMONIZED_MONTHLY exclusiva,
24 membros/lead, integridade das origens confirmada). Este módulo
prepara a extração completa (240 origens) SEM executá-la
automaticamente — cada lote precisa ser disparado explicitamente.

Reaproveita, sem modificar, TODA a orquestração já testada do piloto
(scripts/nmme_piloto_historico.py::executar_piloto_historico/
avaliar_aprovacao_piloto/montar_resumo_por_origem) — este módulo só
adiciona: divisão em lotes, armazenamento permanente (commitado em
data/, não só artifact do GitHub Actions — retenção de 30 dias é
insuficiente para um histórico de 20 anos), retomada (uma origem já
com poc_status=APROVADO persistida NUNCA é reconsultada) e
consolidação final.

Nunca calcula skill, nunca modifica o dashboard, nunca promove
nenhuma rota/representação/sistema no catálogo (scripts/nmme_catalogo.py
nunca é importado por escrita aqui).

Roda com:
    python scripts/nmme_extracao_historica.py --dry-run-plan
    python scripts/nmme_extracao_historica.py --executar-lote 1991-1994
    python scripts/nmme_extracao_historica.py --consolidar
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import nmme_piloto_historico as pilo  # noqa: E402

# Armazenamento PERMANENTE — commitado no repositório (mesma convenção
# de data/serie_subst.csv), nunca dependente só do artifact do GitHub
# Actions (retention-days: 30, insuficiente para um histórico de 20
# anos que não deve precisar ser reprocessado do zero a cada mês).
DIRETORIO_HISTORICO = ROOT / 'data' / 'nmme_historico'

# 1991-2010, 12 meses/ano = 240 inicializações (Seção 1 da tarefa).
PERIODO_ANOS = tuple(range(1991, 2011))
ORIGENS_HISTORICAS = tuple((ano, mes) for ano in PERIODO_ANOS for mes in range(1, 13))
assert len(ORIGENS_HISTORICAS) == 240

TAMANHO_LOTE_MAX = 48   # Seção 1 — "preferencialmente até 48 inicializações"
N_RAW_ESPERADO_TOTAL = 240 * 6 * 24   # 34.560 — só se as 240 origens estiverem APROVADO


@dataclass(frozen=True)
class LoteHistorico:
    """Um lote é identificado pelo intervalo de anos que cobre — 240/48
    = exatamente 5 lotes de 4 anos (48 origens) cada, sem precisar de
    lógica de particionamento mais elaborada."""
    lote_id: str
    origens: tuple


def definir_lotes(origens=ORIGENS_HISTORICAS, tamanho_lote=TAMANHO_LOTE_MAX):
    """Particiona as origens em lotes cronológicos de até `tamanho_lote`
    — nunca reordena, nunca embaralha (a ordem cronológica é a mais
    fácil de auditar manualmente)."""
    lotes = []
    for i in range(0, len(origens), tamanho_lote):
        bloco = origens[i:i + tamanho_lote]
        anos_bloco = sorted({ano for ano, _ in bloco})
        lote_id = f"{anos_bloco[0]}-{anos_bloco[-1]}" if len(anos_bloco) > 1 else str(anos_bloco[0])
        lotes.append(LoteHistorico(lote_id=lote_id, origens=tuple(bloco)))
    return tuple(lotes)


LOTES_HISTORICOS = definir_lotes()
assert sum(len(lote.origens) for lote in LOTES_HISTORICOS) == 240
assert len(LOTES_HISTORICOS) == 5


def _caminho_lote(lote_id, sufixo, diretorio=DIRETORIO_HISTORICO):
    return diretorio / f"lote_{lote_id}_{sufixo}"


def _carregar_resumo_persistido(lote_id, diretorio=DIRETORIO_HISTORICO):
    """Devolve o resumo por origem já persistido para este lote, ou um
    DataFrame vazio (com as colunas certas) se o lote nunca rodou —
    nunca lança erro por arquivo ausente, isso é o estado normal de um
    lote ainda não iniciado."""
    caminho = _caminho_lote(lote_id, 'resumo_por_origem.csv', diretorio)
    if not caminho.exists():
        return pd.DataFrame(columns=['ano', 'mes', 'init_date', 'poc_status', 'backend_used',
                                       'backend_diferente_da_validada', 'dataset_representation_used',
                                       'representacao_diferente_da_validada',
                                       'inicializacao_selecao_status', 'n_raw',
                                       'member_count_per_lead_ok', 'temporal_mapping_confirmado',
                                       'unidade_confirmada', 'grade_confirmada', 'erro_inesperado'])
    return pd.read_csv(caminho)


def origens_pendentes(lote, diretorio=DIRETORIO_HISTORICO):
    """Seção 1 da tarefa — "possibilidade de retomada sem repetir
    desnecessariamente as consultas concluídas". Uma origem CONCLUÍDA
    é uma origem já persistida com `poc_status=APROVADO` — essa nunca é
    requisitada de novo. Qualquer outra situação (nunca tentada,
    reprovada, erro inesperado) fica pendente e É retentada — uma
    reprovação anterior pode ter sido um problema transitório de rede,
    nunca assumido permanente sem tentar de novo."""
    resumo = _carregar_resumo_persistido(lote.lote_id, diretorio)
    if not len(resumo):
        return lote.origens
    aprovadas = {(int(r['ano']), int(r['mes'])) for _, r in resumo.iterrows()
                  if r['poc_status'] == 'APROVADO'}
    return tuple(o for o in lote.origens if o not in aprovadas)


def _resultado_minimo_da_linha_resumo(row):
    """Reconstrói um dict no formato de `nmme_piloto_historico.
    executar_piloto_historico` a partir de 1 linha JÁ PERSISTIDA —
    usado para recompor o lote inteiro (origens novas + origens
    reaproveitadas do disco) antes de rodar `avaliar_aprovacao_piloto`,
    sem precisar reconsultar a rede para as que já estão prontas.
    Contém só os campos que os guardrails de agregação realmente
    leem (poc_status/backend_used/dataset_representation_used) — nunca
    finge ter o RAW/temporal_audit completos aqui (esses continuam só
    nos CSVs persistidos, concatenados à parte)."""
    erro = row.get('erro_inesperado')
    return {
        'ano': int(row['ano']), 'mes': int(row['mes']), 'origem': (int(row['ano']), int(row['mes'])),
        'resultado': {
            'poc_status': row['poc_status'], 'backend_used': row.get('backend_used'),
            'dataset_representation_used': row.get('dataset_representation_used'),
            'checklist': {
                'member_count_per_lead_ok': row.get('member_count_per_lead_ok'),
                'temporal_mapping_confirmado': row.get('temporal_mapping_confirmado'),
                'unidade_confirmada': row.get('unidade_confirmada'),
                'grade_confirmada': row.get('grade_confirmada'),
            },
            'raw_df': pd.DataFrame(), 'temporal_audit_df': pd.DataFrame(),
            'access_audit_df': pd.DataFrame(),
        },
        'erro': erro if isinstance(erro, str) and erro else None,
    }


def executar_lote(lote, baixar_fn=None, abrir_fn=None, resolver_fns=None,
                    diretorio=DIRETORIO_HISTORICO, sistema=None):
    """Roda só as origens PENDENTES deste lote (retomada — Seção 1),
    reaproveitando `nmme_piloto_historico.executar_piloto_historico`
    sem modificação para o isolamento de falha por origem. Mescla o
    resultado novo com o que já estava persistido, escreve de volta em
    `data/nmme_historico/` (armazenamento permanente) e devolve a
    aprovação do LOTE INTEIRO (`nmme_piloto_historico.
    avaliar_aprovacao_piloto`, reaproveitada sem modificação — mesmos
    critérios: todas aprovadas, nenhum erro inesperado, rota validada
    exclusiva, integridade das origens do lote)."""
    diretorio.mkdir(parents=True, exist_ok=True)
    pendentes = origens_pendentes(lote, diretorio)

    resultados_novos = []
    if pendentes:
        resultados_novos = pilo.executar_piloto_historico(
            origens=pendentes, sistema=sistema, baixar_fn=baixar_fn, abrir_fn=abrir_fn,
            resolver_fns=resolver_fns)

    resumo_persistido = _carregar_resumo_persistido(lote.lote_id, diretorio)
    origens_novas = {item['origem'] for item in resultados_novos}
    resultados_reaproveitados = [
        _resultado_minimo_da_linha_resumo(row) for _, row in resumo_persistido.iterrows()
        if (int(row['ano']), int(row['mes'])) not in origens_novas
    ]
    resultados_completos = resultados_reaproveitados + resultados_novos
    # Nunca perde a ordem cronológica do lote, mesmo misturando
    # reaproveitado + novo.
    resultados_completos.sort(key=lambda item: item['origem'])

    raw_novo, temporal_novo, access_novo = pilo.concatenar_dataframes_piloto(resultados_novos)
    raw_persistido = _ler_csv_ou_vazio(_caminho_lote(lote.lote_id, 'raw.csv', diretorio))
    temporal_persistido = _ler_csv_ou_vazio(_caminho_lote(lote.lote_id, 'temporal_audit.csv', diretorio))
    access_persistido = _ler_csv_ou_vazio(_caminho_lote(lote.lote_id, 'access_audit.csv', diretorio))

    origens_novas_str = {f'{a}-{m:02d}' for a, m in origens_novas}
    raw_final = _substituir_origens(raw_persistido, raw_novo, origens_novas_str)
    temporal_final = _substituir_origens(temporal_persistido, temporal_novo, origens_novas_str)
    access_final = _substituir_origens(access_persistido, access_novo, origens_novas_str)

    resumo_final = pilo.montar_resumo_por_origem(resultados_completos)
    # `resultados_completos` mistura resultados frescos (com raw_df
    # real) e reaproveitados do disco (_resultado_minimo_da_linha_resumo
    # deliberadamente NÃO recarrega o RAW inteiro, só o suficiente para
    # os critérios de aprovação) — por isso `n_raw` de
    # montar_resumo_por_origem ficaria 0 para toda origem reaproveitada.
    # Corrigido aqui contando direto no `raw_final` já mesclado, que é
    # a fonte de verdade real independente de a origem ser nova ou
    # reaproveitada.
    if len(raw_final) and 'origem_piloto' in raw_final.columns:
        contagem_raw = raw_final.groupby('origem_piloto').size()
        resumo_final['n_raw'] = resumo_final['init_date'].map(contagem_raw).fillna(0).astype(int)
    else:
        resumo_final['n_raw'] = 0

    raw_final.to_csv(_caminho_lote(lote.lote_id, 'raw.csv', diretorio), index=False)
    temporal_final.to_csv(_caminho_lote(lote.lote_id, 'temporal_audit.csv', diretorio), index=False)
    access_final.to_csv(_caminho_lote(lote.lote_id, 'access_audit.csv', diretorio), index=False)
    resumo_final.to_csv(_caminho_lote(lote.lote_id, 'resumo_por_origem.csv', diretorio), index=False)

    aprovacao = pilo.avaliar_aprovacao_piloto(resultados_completos, origens_esperadas=lote.origens)
    metadata_lote = {
        'lote_id': lote.lote_id, 'n_origens': len(lote.origens),
        'n_origens_pendentes_nesta_execucao': len(pendentes),
        'n_origens_reaproveitadas_do_disco': len(resultados_reaproveitados),
        'lote_status': aprovacao['piloto_status'], 'criterios': aprovacao['criterios'],
        'n_origens_aprovadas': aprovacao['n_origens_aprovadas'],
        'origens_com_rota_diferente': aprovacao['origens_com_rota_diferente'],
        'integridade_origens': aprovacao['integridade_origens'],
        'n_raw': len(raw_final), 'n_raw_esperado': len(lote.origens) * 6 * 24,
    }
    (_caminho_lote(lote.lote_id, 'metadata.json', diretorio)).write_text(
        json.dumps(metadata_lote, indent=2, ensure_ascii=False, default=str))
    return metadata_lote


def _ler_csv_ou_vazio(caminho):
    """Nunca lança por arquivo ausente OU vazio — um lote cuja primeira
    tentativa reprova em TODAS as origens (ex.: rede fora naquele dia)
    persiste um CSV de 0 linhas/0 colunas por construção
    (`concatenar_dataframes_piloto` devolve `pd.DataFrame()` quando
    nada teve sucesso); `pd.read_csv` levanta `EmptyDataError` nesse
    caso mesmo com o arquivo existindo — achado ao testar exatamente
    esse cenário (lote de 1 origem que falha na primeira execução)."""
    if not caminho.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(caminho)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _substituir_origens(df_persistido, df_novo, origens_novas_str):
    """Concatena o que já estava no disco com o resultado novo,
    removendo do lado persistido qualquer linha das origens que acabam
    de ser reprocessadas (nunca duplica — a versão nova sempre
    substitui a antiga para a mesma origem, mesmo que a antiga já
    estivesse aprovada, porque só origens NÃO aprovadas voltam a ser
    processadas — `origens_pendentes`)."""
    if len(df_persistido) and 'origem_piloto' in df_persistido.columns:
        df_persistido = df_persistido[~df_persistido['origem_piloto'].isin(origens_novas_str)]
    partes = [d for d in (df_persistido, df_novo) if len(d)]
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()


def consolidar_extracao_completa(lotes=LOTES_HISTORICOS, diretorio=DIRETORIO_HISTORICO):
    """Seção 1 da tarefa — depois que os lotes rodarem (não necessariamente
    todos ainda), verifica as 240 origens x 6 leads x 24 membros
    (34.560 registros RAW) SE E SOMENTE SE todas as 240 estiverem
    aprovadas. Nunca finge completude parcial como total — reporta o
    estado real (quantos lotes/origens realmente concluídos) mesmo
    quando incompleto, o que é o estado esperado até que todos os 5
    lotes sejam explicitamente disparados."""
    resultados_todos = []
    n_raw_total = 0
    lotes_status = {}
    for lote in lotes:
        resumo = _carregar_resumo_persistido(lote.lote_id, diretorio)
        raw_lote = _ler_csv_ou_vazio(_caminho_lote(lote.lote_id, 'raw.csv', diretorio))
        n_raw_total += len(raw_lote)
        if len(resumo):
            resultados_todos.extend(_resultado_minimo_da_linha_resumo(row)
                                      for _, row in resumo.iterrows())
            n_aprovadas = int((resumo['poc_status'] == 'APROVADO').sum())
        else:
            n_aprovadas = 0
        lotes_status[lote.lote_id] = {'n_origens': len(lote.origens), 'n_aprovadas': n_aprovadas,
                                        'iniciado': len(resumo) > 0}

    todas_origens_esperadas = tuple(o for lote in lotes for o in lote.origens)
    if resultados_todos:
        aprovacao_geral = pilo.avaliar_aprovacao_piloto(resultados_todos,
                                                           origens_esperadas=todas_origens_esperadas)
    else:
        aprovacao_geral = {'piloto_status': 'REPROVADO', 'n_origens_aprovadas': 0,
                             'n_origens_total': 0, 'criterios': {}, 'origens_com_rota_diferente': [],
                             'integridade_origens': {'ok': False}}

    completo = (aprovacao_geral['n_origens_aprovadas'] == len(todas_origens_esperadas)
                and aprovacao_geral['piloto_status'] == 'APROVADO')
    # Calculado a partir de `lotes` (não do valor fixo N_RAW_ESPERADO_
    # TOTAL) — `lotes` é parametrizável (default é o conjunto real de 5
    # lotes/240 origens, mas a função aceita qualquer subconjunto, ex.:
    # testes). Com o total fixo, um subconjunto completo e aprovado
    # reportaria `n_raw_bate_com_esperado=False` por comparar contra o
    # total de 240 origens em vez do total do que foi realmente pedido
    # — o mesmo tipo de completude fingida que este módulo existe para
    # nunca fazer. Para o uso real (`lotes=LOTES_HISTORICOS`), o valor
    # coincide exatamente com N_RAW_ESPERADO_TOTAL (240*6*24=34.560).
    n_raw_esperado = len(todas_origens_esperadas) * 6 * 24
    consolidado = {
        'n_lotes': len(lotes), 'n_origens_esperadas_total': len(todas_origens_esperadas),
        'n_origens_aprovadas_total': aprovacao_geral['n_origens_aprovadas'],
        'extracao_completa_e_aprovada': completo,
        'n_raw_total': n_raw_total,
        'n_raw_esperado_se_completo': n_raw_esperado,
        'n_raw_bate_com_esperado': (n_raw_total == n_raw_esperado) if completo else None,
        'criterios_agregados': aprovacao_geral['criterios'],
        'origens_com_rota_diferente': aprovacao_geral['origens_com_rota_diferente'],
        'integridade_origens': aprovacao_geral['integridade_origens'],
        'lotes_status': lotes_status,
        'nenhuma_skill_calculada': True, 'nenhum_dashboard_alterado': True,
    }
    return consolidado


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def imprimir_plano():
    print("=== NMME Extração Histórica CFSv2 (Fase 2C.2) — DRY RUN PLAN "
          "(nenhum acesso à rede NMME) ===")
    print(f"  periodo: {PERIODO_ANOS[0]}-{PERIODO_ANOS[-1]}")
    print(f"  n_origens_total: {len(ORIGENS_HISTORICAS)}")
    print(f"  n_lotes: {len(LOTES_HISTORICOS)} (até {TAMANHO_LOTE_MAX} origens cada)")
    print(f"  n_raw_esperado_se_tudo_aprovado: {N_RAW_ESPERADO_TOTAL}")
    print("  armazenamento: data/nmme_historico/ (commitado no repositório, "
          "NUNCA depende só do artifact do GitHub Actions — retenção 30 dias)")
    for lote in LOTES_HISTORICOS:
        pendentes = origens_pendentes(lote)
        print(f"  - lote {lote.lote_id}: {len(lote.origens)} origens, "
              f"{len(pendentes)} pendentes (retomada automática)")
    print("\n✅ Plano da extração histórica gerado (infraestrutura só — nenhum download real).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run-plan', action='store_true',
                     help='Nunca acessa a rede NMME — só mostra o plano dos 5 lotes.')
    ap.add_argument('--executar-lote', metavar='LOTE_ID', default=None,
                     help='Roda só o lote informado (ex.: 1991-1994) — acessa a rede de verdade. '
                          'Nunca roda mais de 1 lote por invocação.')
    ap.add_argument('--consolidar', action='store_true',
                     help='Só lê os lotes já persistidos em data/nmme_historico/ e reporta o estado '
                          'consolidado — nunca acessa a rede.')
    args = ap.parse_args()

    if args.consolidar:
        consolidado = consolidar_extracao_completa()
        print(json.dumps(consolidado, indent=2, ensure_ascii=False, default=str))
        return

    if args.executar_lote:
        lotes_por_id = {lote.lote_id: lote for lote in LOTES_HISTORICOS}
        if args.executar_lote not in lotes_por_id:
            raise SystemExit(f"lote_id {args.executar_lote!r} desconhecido — "
                              f"válidos: {sorted(lotes_por_id)}")
        imprimir_plano()
        metadata_lote = executar_lote(lotes_por_id[args.executar_lote])
        print(f"\nlote_status={metadata_lote['lote_status']} "
              f"({metadata_lote['n_origens_aprovadas']}/{metadata_lote['n_origens']} origens aprovadas)")
        for k, v in metadata_lote['criterios'].items():
            print(f"  - {k}: {v}")
        if metadata_lote['lote_status'] != 'APROVADO':
            raise SystemExit(f"Lote {args.executar_lote} REPROVADO — ver "
                              f"data/nmme_historico/lote_{args.executar_lote}_resumo_por_origem.csv")
        print(f"\n✅ Lote {args.executar_lote} APROVADO — persistido em data/nmme_historico/")
        return

    imprimir_plano()


if __name__ == '__main__':
    main()
