#!/usr/bin/env python3
"""
chirps_v3_reconstrucao_historica.py — Fase 2C.3B: PLANO de
reconstrução histórica completa da referência CHIRPS v3.0 Final
(jan/1981 a mai/2011, 365 meses).

Este módulo só PLANEJA — não inicia a extração dos 365 meses
automaticamente (restrição explícita do item 4 da revisão). Ele
reaproveita a mesma lógica já testada e validada no piloto de 17 meses
(scripts/chirps_v3_piloto.py::executar_piloto/meses_pendentes/
_carregar_resultados_persistidos — retomada, limite de requisições,
validação por mês via scripts/_chirps_v3.py::extrair_pixel_mensal),
parametrizada para gravar num diretório SEPARADO
(data/chirps_v3_historico/) — nunca data/chirps_v3_piloto.csv (os 17
registros originais do piloto são preservados intactos) nem os
arquivos de produção (data/chirps_1981_2025.csv, data/serie_subst.csv).

Período (item 4): o início em jan/1981 é deliberado — é o começo da
disponibilidade real do CHIRPS (já confirmado, data/chirps_1981_2025.csv
cobre 1981-2025), necessário para construir uma CLIMATOLOGIA anterior
às previsões históricas do CFSv2 (jan/1991 em diante). O fim em
mai/2011 é o mês-alvo do último horizonte (H6) da última inicialização
já aprovada do CFSv2 (dez/2010 + H6). O período completo se divide em:

    1981-01 a 1990-12 (120 meses) — climatologia retrospectiva
    1991-01 a 2011-05 (245 meses) — período de verificação das
                                     previsões históricas do CFSv2
    ────────────────────────────────
    365 meses no total

Roda com:
    python scripts/chirps_v3_reconstrucao_historica.py --dry-run-plan
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import chirps_v3_piloto as piloto  # noqa: E402

DIRETORIO_SAIDA = ROOT / 'data' / 'chirps_v3_historico'
CAMINHO_CSV = DIRETORIO_SAIDA / 'chirps_v3_1981_2011.csv'
CAMINHO_METADATA_JSON = DIRETORIO_SAIDA / 'chirps_v3_1981_2011_metadata.json'
RELATORIO_PLANO_PATH = ROOT / 'docs' / 'nmme-fase2c3b-plano-reconstrucao-historica.md'
RELATORIO_LOTE_PATH = ROOT / 'docs' / 'nmme-fase2c3b-primeiro-lote-historico.md'

# Confirma explicitamente, em tempo de import, que este módulo NUNCA
# aponta para os mesmos arquivos do piloto ou da produção — ver
# NuncaReusaArquivosDeProducaoOuDoPilotoTestCase.
assert CAMINHO_CSV != piloto.DATA_PILOTO_CSV
assert CAMINHO_CSV != piloto.CHIRPS_V2_PONTO_PATH
assert CAMINHO_CSV != piloto.SERIE_PRODUCAO_PATH


def _meses_entre(inicio, fim):
    """inicio/fim são tuplas (ano, mes), inclusive nos dois lados."""
    (a_ini, m_ini), (a_fim, m_fim) = inicio, fim
    meses = []
    ano, mes = a_ini, m_ini
    while (ano, mes) <= (a_fim, m_fim):
        meses.append((ano, mes))
        mes += 1
        if mes > 12:
            mes = 1
            ano += 1
    return meses


PERIODO_CLIMATOLOGIA = _meses_entre((1981, 1), (1990, 12))       # 120 meses
PERIODO_VERIFICACAO = _meses_entre((1991, 1), (2011, 5))         # 245 meses
PERIODO_COMPLETO = PERIODO_CLIMATOLOGIA + PERIODO_VERIFICACAO    # 365 meses

TAMANHO_LOTE = 24   # 2 anos por lote — pequeno o bastante para um lote
                     # incompleto não desperdiçar muito trabalho ao
                     # falhar, grande o bastante para não gerar
                     # centenas de lotes de 1 mês só


def definir_lotes(meses=PERIODO_COMPLETO, tamanho_lote=TAMANHO_LOTE):
    """Processamento em lotes (item 4) — divide o período completo em
    blocos sequenciais de `tamanho_lote` meses. Cada lote é uma
    unidade de trabalho independente: `executar_lote` só chama a rede
    para os meses PENDENTES daquele lote (retomada), então um lote já
    concluído é essencialmente gratuito de re-executar."""
    return [meses[i:i + tamanho_lote] for i in range(0, len(meses), tamanho_lote)]


LOTES_HISTORICOS = definir_lotes()


def meses_pendentes_reconstrucao(meses=PERIODO_COMPLETO):
    """Retomada (item 4/Fase 2C.3A) — reaproveita scripts/chirps_v3_
    piloto.py::meses_pendentes, parametrizada para o CSV separado
    desta tarefa."""
    return piloto.meses_pendentes(meses=meses, caminho_csv=CAMINHO_CSV)


# ══════════════════════════════════════════════════════════════════════════
# Fase 2C.3B, item 3 — interface de execução por lote: selecionar
# explicitamente, verificar estado, consultar pendentes
# ══════════════════════════════════════════════════════════════════════════

def obter_lote(indice_ou_lote):
    """Aceita um ÍNDICE (int, 0-based, em LOTES_HISTORICOS) OU uma
    lista explícita de (ano,mes) já pronta — nunca aceita 'o período
    inteiro' por engano: um índice fora da faixa levanta ValueError
    em vez de silenciosamente processar tudo."""
    if isinstance(indice_ou_lote, int):
        if not (0 <= indice_ou_lote < len(LOTES_HISTORICOS)):
            raise ValueError(f"índice de lote inválido: {indice_ou_lote} "
                              f"(válido: 0 a {len(LOTES_HISTORICOS) - 1})")
        return LOTES_HISTORICOS[indice_ou_lote]
    return list(indice_ou_lote)


def listar_lotes():
    """Item 3 — 'selecionar explicitamente um lote': lista índice,
    período e tamanho de cada lote, para escolha explícita antes de
    executar."""
    return [{'indice': i, 'inicio': f'{lote[0][0]}-{lote[0][1]:02d}',
             'fim': f'{lote[-1][0]}-{lote[-1][1]:02d}', 'n_meses': len(lote)}
            for i, lote in enumerate(LOTES_HISTORICOS)]


def meses_pendentes_lote(indice_ou_lote):
    """Item 3 — 'consultar os meses pendentes' de UM lote específico."""
    lote = obter_lote(indice_ou_lote)
    return meses_pendentes_reconstrucao(meses=lote)


def estado_lote(indice_ou_lote, caminho_csv=None):
    """Item 3 — 'verificar seu estado': avalia a qualidade (4
    dimensões, scripts/chirps_v3_piloto.py::avaliar_qualidade_piloto,
    já corrigido no item 1b desta revisão para nunca contar meses de
    OUTROS lotes) exclusivamente sobre os meses DESTE lote — mesmo que
    CAMINHO_CSV já tenha registros de outros lotes acumulados."""
    lote = obter_lote(indice_ou_lote)
    if caminho_csv is None:
        caminho_csv = CAMINHO_CSV
    resultados_df = piloto._carregar_resultados_persistidos(caminho_csv)
    return piloto.avaliar_qualidade_piloto(resultados_df, meses_esperados=lote)


def executar_lote(indice_ou_lote, max_requisicoes=None,
                   rate_limit_segundos=piloto.RATE_LIMIT_SEGUNDOS):
    """Executa UM lote explícito (nunca o período completo de uma vez
    só, nunca os demais lotes automaticamente — item 3) — reaproveita
    scripts/chirps_v3_piloto.py::executar_piloto (mesma validação por
    mês via _chirps_v3.py::extrair_pixel_mensal, já testada no piloto
    de 17 meses), gravando em CAMINHO_CSV (diretório separado).
    `max_requisicoes` default = o próprio tamanho do lote — nunca
    processa além do lote pedido numa chamada."""
    lote = obter_lote(indice_ou_lote)
    limite = max_requisicoes if max_requisicoes is not None else len(lote)
    return piloto.executar_piloto(meses=lote, max_requisicoes=limite,
                                   rate_limit_segundos=rate_limit_segundos,
                                   caminho_csv=CAMINHO_CSV)


def avaliar_qualidade_reconstrucao(resultados_df, meses_esperados=PERIODO_COMPLETO):
    """Validação individual de cada mês (item 4/Fase 2C.3A) —
    reaproveita scripts/chirps_v3_piloto.py::avaliar_qualidade_piloto
    (mesma distinção de 4 dimensões, corrigida no item 1b desta
    revisão para nunca contar meses fora de `meses_esperados`)."""
    return piloto.avaliar_qualidade_piloto(resultados_df, meses_esperados=meses_esperados)


def montar_plano_reconstrucao():
    """Item 4 — o PLANO em si, estruturado. Nenhuma extração real é
    disparada por esta função."""
    return {
        'periodo_completo': {
            'inicio': '1981-01', 'fim': '2011-05', 'n_meses': len(PERIODO_COMPLETO),
        },
        'periodo_climatologia': {
            'inicio': '1981-01', 'fim': '1990-12', 'n_meses': len(PERIODO_CLIMATOLOGIA),
            'proposito': 'climatologia retrospectiva — período anterior às previsões '
                         'históricas do CFSv2 (jan/1991 em diante), necessário para uma '
                         'climatologia de referência que nunca usa os valores do período '
                         'avaliado (ver docs/nmme-fase2c3a-protocolo-cfsv2.md, Seção 4).',
        },
        'periodo_verificacao': {
            'inicio': '1991-01', 'fim': '2011-05', 'n_meses': len(PERIODO_VERIFICACAO),
            'proposito': 'período de verificação das previsões históricas do CFSv2 — 240 '
                         'inicializações jan/1991-dez/2010 (scripts/nmme_extracao_historica.py, '
                         'já aprovado) + mai/2011 como mês-alvo do último horizonte (H6) da '
                         'última inicialização (dez/2010).',
        },
        'soma_bate_com_periodo_completo': (
            len(PERIODO_CLIMATOLOGIA) + len(PERIODO_VERIFICACAO) == len(PERIODO_COMPLETO)),
        'processamento_em_lotes': {
            'tamanho_lote_meses': TAMANHO_LOTE,
            'n_lotes': len(LOTES_HISTORICOS),
            'mecanismo': 'scripts/chirps_v3_reconstrucao_historica.py::executar_lote — reusa '
                         'scripts/chirps_v3_piloto.py::executar_piloto (mesma lógica testada '
                         'no piloto de 17 meses), um lote por chamada, nunca o período '
                         'completo de uma vez.',
        },
        'retomada': (
            'meses_pendentes_reconstrucao() reusa scripts/chirps_v3_piloto.py::'
            'meses_pendentes — um mês com resultado já RESOLVIDO (ok/zero_real/'
            'nodata_sentinela/mes_ausente) nunca é reprocessado; falha real é retentada na '
            'próxima execução do mesmo lote.'
        ),
        'validacao_individual_por_mes': (
            'Cada mês passa pelas mesmas verificações do piloto (scripts/_chirps_v3.py::'
            'verificar_grade + classificar_valor) — nenhum mês é aceito sem validação própria, '
            'nenhuma extrapolação de "um mês passou, os vizinhos devem estar OK também".'
        ),
        'armazenamento_separado': {
            'diretorio': str(DIRETORIO_SAIDA.relative_to(ROOT)),
            'nunca_reutiliza': [str(piloto.DATA_PILOTO_CSV.relative_to(ROOT)),
                                 str(piloto.CHIRPS_V2_PONTO_PATH.relative_to(ROOT)),
                                 str(piloto.SERIE_PRODUCAO_PATH.relative_to(ROOT))],
        },
        'os_17_registros_do_piloto_preservados': True,
        'extracao_dos_365_meses_iniciada_nesta_tarefa': False,
        'proximos_passos_apos_aprovacao_explicita': [
            "Rodar executar_lote() lote a lote (LOTES_HISTORICOS), verificando "
            "avaliar_qualidade_reconstrucao() após cada lote antes de prosseguir para o "
            "próximo — nunca encadear todos os lotes sem checar o anterior.",
            "Ao final dos 365 meses, rodar avaliar_qualidade_reconstrucao() sobre o conjunto "
            "completo — só prosseguir para a Fase 2C.3C se cobertura_temporal_completa=True.",
            "Gerar relatório final da reconstrução (mesmo padrão do relatório do piloto, "
            "docs/nmme-fase2c3a-piloto-chirps-v3.md) antes de qualquer uso na Fase 2C.3C.",
        ],
    }


# ══════════════════════════════════════════════════════════════════════════
# Item 4 — relatório com os resultados do primeiro lote, a análise de
# sensibilidade espacial (referenciada, não duplicada) e o estado geral
# da reconstrução histórica
# ══════════════════════════════════════════════════════════════════════════

def montar_relatorio_lote(indice):
    """Item 3/4 — dados do lote pedido (qualidade + comparação
    descritiva) e o estado GERAL da reconstrução (quantos lotes têm
    cobertura completa) — nunca dispara execução de outros lotes, só
    lê o que já está persistido."""
    lote = obter_lote(indice)
    resultados_df = piloto._carregar_resultados_persistidos(CAMINHO_CSV)
    if resultados_df.empty:
        df_lote = resultados_df
    else:
        lote_set = set(lote)
        df_lote = resultados_df[
            resultados_df.apply(lambda r: (int(r['ano']), int(r['mes'])) in lote_set, axis=1)]

    qualidade = estado_lote(indice, caminho_csv=CAMINHO_CSV)
    comparacao = piloto.comparar_com_dados_existentes(df_lote)

    estado_geral = []
    for i in range(len(LOTES_HISTORICOS)):
        q = estado_lote(i, caminho_csv=CAMINHO_CSV)
        estado_geral.append({
            'indice': i, 'periodo': f"{LOTES_HISTORICOS[i][0][0]}-{LOTES_HISTORICOS[i][0][1]:02d} "
                                     f"a {LOTES_HISTORICOS[i][-1][0]}-{LOTES_HISTORICOS[i][-1][1]:02d}",
            'cobertura_temporal_completa': q['cobertura_temporal_completa'],
            'n_meses_com_valor_valido': q['n_meses_com_valor_valido'],
            'n_meses_esperados': q['n_meses_esperados'],
        })
    n_lotes_completos = sum(1 for e in estado_geral if e['cobertura_temporal_completa'])

    return {
        'indice_lote': indice,
        'periodo_lote': f"{lote[0][0]}-{lote[0][1]:02d} a {lote[-1][0]}-{lote[-1][1]:02d}",
        'n_meses_lote': len(lote),
        'qualidade_lote': qualidade,
        'comparacao_lote': comparacao,
        'estado_geral_reconstrucao': {
            'n_lotes_total': len(LOTES_HISTORICOS),
            'n_lotes_completos': n_lotes_completos,
            'lotes': estado_geral,
        },
        'sensibilidade_espacial_referencia': {
            'relatorio': str(sens_relatorio_relpath()),
            'nota': 'Análise de sensibilidade espacial (item 2) apresentada SEPARADAMENTE — '
                    'ver o relatório dedicado, não duplicada aqui.',
        },
    }


def sens_relatorio_relpath():
    import chirps_v3_sensibilidade_espacial as sens
    return sens.RELATORIO_SENSIBILIDADE_PATH.relative_to(ROOT)


def gerar_relatorio_lote_markdown(dados):
    q = dados['qualidade_lote']
    comp = dados['comparacao_lote']
    estado = dados['estado_geral_reconstrucao']
    linhas = [
        f"# Primeiro lote histórico CHIRPS v3.0 — lote {dados['indice_lote']} "
        f"({dados['periodo_lote']}) — Fase 2C.3B",
        "",
        "**Relatório técnico — não substitui dados operacionais, não calcula skill, não "
        "altera SARIMAX/XGBoost/dashboard/previsões históricas do CFSv2.**",
        "",
        "## 1. Resultados do lote",
        "",
        f"- Período: {dados['periodo_lote']} ({dados['n_meses_lote']} meses).",
        f"- Veredito: **{'APROVADO' if q['aprovado'] else 'REPROVADO'}**.",
        f"- {q['interpretacao']}",
        "",
        "### Quatro dimensões",
        "",
        f"1. Disponibilidade no servidor: {q['n_meses_disponiveis_no_servidor']}/"
        f"{q['n_meses_esperados']}.",
        f"2. Extração bem-sucedida: {q['n_meses_com_extracao_bem_sucedida']}/"
        f"{q['n_meses_esperados']}.",
        f"3. Valor válido disponível: {q['n_meses_com_valor_valido']}/{q['n_meses_esperados']}.",
        f"4. Cobertura temporal completa: "
        f"{'SIM' if q['cobertura_temporal_completa'] else 'NÃO'}.",
        "",
        "## 2. Comparação com os dados existentes (descritiva)",
        "",
        f"- {comp.get('interpretacao', 'Sem meses válidos para comparar.')}",
        "",
        "## 3. Análise de sensibilidade espacial",
        "",
        f"- {dados['sensibilidade_espacial_referencia']['nota']} Ver "
        f"`{dados['sensibilidade_espacial_referencia']['relatorio']}`.",
        "",
        "## 4. Estado geral da reconstrução histórica",
        "",
        f"- Lotes com cobertura temporal completa: {estado['n_lotes_completos']}/"
        f"{estado['n_lotes_total']}.",
        "",
        "| Lote | Período | Cobertura completa | Meses válidos |",
        "|---|---|---|---|",
    ]
    for e in estado['lotes']:
        linhas.append(f"| {e['indice']} | {e['periodo']} | "
                       f"{'SIM' if e['cobertura_temporal_completa'] else 'não'} | "
                       f"{e['n_meses_com_valor_valido']}/{e['n_meses_esperados']} |")
    linhas += [
        "",
        "## Restrições respeitadas",
        "",
        "- Nenhum dado operacional foi substituído.",
        "- SARIMAX, XGBoost, dashboard e as previsões históricas do CFSv2 não foram alterados.",
        "- Nenhum indicador de habilidade preditiva foi calculado.",
        "- Os demais lotes NÃO foram iniciados automaticamente.",
    ]
    return '\n'.join(linhas) + '\n'


def gerar_relatorio_plano_markdown(plano):
    linhas = [
        "# Plano de reconstrução histórica — CHIRPS v3.0 Final (Fase 2C.3B)",
        "",
        "**Plano — nenhuma extração dos 365 meses foi iniciada por este documento nem pelo "
        "script que o gera.**",
        "",
        "## Período",
        "",
        f"- Completo: {plano['periodo_completo']['inicio']} a "
        f"{plano['periodo_completo']['fim']} — {plano['periodo_completo']['n_meses']} meses.",
        f"- Climatologia: {plano['periodo_climatologia']['inicio']} a "
        f"{plano['periodo_climatologia']['fim']} — "
        f"{plano['periodo_climatologia']['n_meses']} meses. "
        f"{plano['periodo_climatologia']['proposito']}",
        f"- Verificação: {plano['periodo_verificacao']['inicio']} a "
        f"{plano['periodo_verificacao']['fim']} — "
        f"{plano['periodo_verificacao']['n_meses']} meses. "
        f"{plano['periodo_verificacao']['proposito']}",
        f"- Soma dos dois períodos bate com o completo: "
        f"{plano['soma_bate_com_periodo_completo']}.",
        "",
        "## Processamento em lotes",
        "",
        f"- Tamanho do lote: {plano['processamento_em_lotes']['tamanho_lote_meses']} meses.",
        f"- Número de lotes: {plano['processamento_em_lotes']['n_lotes']}.",
        f"- Mecanismo: {plano['processamento_em_lotes']['mecanismo']}",
        "",
        "## Retomada",
        "",
        f"- {plano['retomada']}",
        "",
        "## Validação individual por mês",
        "",
        f"- {plano['validacao_individual_por_mes']}",
        "",
        "## Armazenamento",
        "",
        f"- Diretório: `{plano['armazenamento_separado']['diretorio']}`.",
        f"- Nunca reutiliza: "
        f"{', '.join(f'`{p}`' for p in plano['armazenamento_separado']['nunca_reutiliza'])}.",
        f"- Os 17 registros originais do piloto (data/chirps_v3_piloto.csv) preservados: "
        f"{plano['os_17_registros_do_piloto_preservados']}.",
        "",
        "## Status desta tarefa",
        "",
        f"- Extração dos 365 meses iniciada nesta tarefa: "
        f"{plano['extracao_dos_365_meses_iniciada_nesta_tarefa']}.",
        "",
        "## Próximos passos (após aprovação explícita, fora desta tarefa)",
        "",
    ]
    for i, passo in enumerate(plano['proximos_passos_apos_aprovacao_explicita'], 1):
        linhas.append(f"{i}. {passo}")
    linhas.append("")
    return '\n'.join(linhas) + '\n'


def imprimir_plano():
    plano = montar_plano_reconstrucao()
    print("=== Plano de reconstrução histórica CHIRPS v3.0 — Fase 2C.3B — DRY RUN PLAN ===")
    print(f"  período completo: {plano['periodo_completo']['n_meses']} meses "
          f"({plano['periodo_completo']['inicio']} a {plano['periodo_completo']['fim']})")
    print(f"  climatologia: {plano['periodo_climatologia']['n_meses']} meses, "
          f"verificação: {plano['periodo_verificacao']['n_meses']} meses")
    print(f"  lotes: {plano['processamento_em_lotes']['n_lotes']} de "
          f"{plano['processamento_em_lotes']['tamanho_lote_meses']} meses cada")
    print(f"  saída: {DIRETORIO_SAIDA.relative_to(ROOT)}/ (separado do piloto e da produção)")
    print("\n✅ Plano gerado — nenhuma extração dos 365 meses iniciada.")
    return plano


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run-plan', action='store_true')
    ap.add_argument('--gerar-relatorio', action='store_true',
                     help='Escreve o relatório do PLANO geral em docs/ — não executa rede.')
    ap.add_argument('--listar-lotes', action='store_true',
                     help='Lista todos os lotes (índice, período, tamanho) — não executa rede.')
    ap.add_argument('--lote', type=int, default=None,
                     help='Seleciona explicitamente um lote por índice (0-based) para as ações '
                          'abaixo. Item 3 da revisão: "selecionar explicitamente um lote".')
    ap.add_argument('--estado', action='store_true',
                     help='Com --lote N: mostra o estado atual do lote N (não executa rede).')
    ap.add_argument('--meses-pendentes', action='store_true',
                     help='Com --lote N: lista os meses pendentes do lote N (não executa rede).')
    ap.add_argument('--executar-lote-real', action='store_true',
                     help='Com --lote N: executa REALMENTE (rede) o lote N — só esse lote, '
                          'nunca os demais automaticamente.')
    ap.add_argument('--gerar-relatorio-lote', action='store_true',
                     help='Com --lote N: gera o relatório do lote N + estado geral da '
                          'reconstrução (não executa rede).')
    args = ap.parse_args()

    if args.listar_lotes:
        for l in listar_lotes():
            print(f"  lote {l['indice']}: {l['inicio']} a {l['fim']} ({l['n_meses']} meses)")
        return

    if args.lote is not None:
        if args.estado:
            q = estado_lote(args.lote)
            print(f"=== Estado do lote {args.lote} ===")
            print(f"  aprovado={q['aprovado']} cobertura_temporal_completa="
                  f"{q['cobertura_temporal_completa']}")
            print(f"  {q['interpretacao']}")
            return
        if args.meses_pendentes:
            pendentes = meses_pendentes_lote(args.lote)
            print(f"=== Meses pendentes do lote {args.lote} ===")
            print(f"  {len(pendentes)} pendentes: "
                  f"{', '.join(f'{a}-{m:02d}' for a, m in pendentes)}")
            return
        if args.executar_lote_real:
            lote = obter_lote(args.lote)
            print(f"=== Executando lote {args.lote} ({len(lote)} meses) — REDE ===")
            resultado_df = executar_lote(args.lote)
            qualidade = estado_lote(args.lote)
            print(f"\naprovado={qualidade['aprovado']}")
            return
        if args.gerar_relatorio_lote:
            dados = montar_relatorio_lote(args.lote)
            relatorio = gerar_relatorio_lote_markdown(dados)
            RELATORIO_LOTE_PATH.parent.mkdir(parents=True, exist_ok=True)
            RELATORIO_LOTE_PATH.write_text(relatorio)
            print(f"  ✅ {RELATORIO_LOTE_PATH.relative_to(ROOT)}")
            return
        print(f"--lote {args.lote} selecionado — use --estado, --meses-pendentes, "
              "--executar-lote-real ou --gerar-relatorio-lote.")
        return

    plano = imprimir_plano()

    if args.gerar_relatorio:
        relatorio = gerar_relatorio_plano_markdown(plano)
        RELATORIO_PLANO_PATH.parent.mkdir(parents=True, exist_ok=True)
        RELATORIO_PLANO_PATH.write_text(relatorio)
        print(f"  ✅ {RELATORIO_PLANO_PATH.relative_to(ROOT)}")


if __name__ == '__main__':
    main()
