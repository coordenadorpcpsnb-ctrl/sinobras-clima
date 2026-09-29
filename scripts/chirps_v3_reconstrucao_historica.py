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
    """Retomada (item 4) — reaproveita scripts/chirps_v3_piloto.py::
    meses_pendentes, parametrizada para o CSV separado desta tarefa."""
    return piloto.meses_pendentes(meses=meses, caminho_csv=CAMINHO_CSV)


def executar_lote(lote, max_requisicoes=None, rate_limit_segundos=piloto.RATE_LIMIT_SEGUNDOS):
    """Executa UM lote explícito (nunca o período completo de uma vez
    só) — reaproveita scripts/chirps_v3_piloto.py::executar_piloto
    (mesma validação por mês via _chirps_v3.py::extrair_pixel_mensal,
    já testada no piloto de 17 meses), gravando em CAMINHO_CSV
    (diretório separado). `max_requisicoes` default = o próprio
    tamanho do lote — nunca processa além do lote pedido numa
    chamada."""
    limite = max_requisicoes if max_requisicoes is not None else len(lote)
    return piloto.executar_piloto(meses=lote, max_requisicoes=limite,
                                   rate_limit_segundos=rate_limit_segundos,
                                   caminho_csv=CAMINHO_CSV)


def avaliar_qualidade_reconstrucao(resultados_df, meses_esperados=PERIODO_COMPLETO):
    """Validação individual de cada mês (item 4) — reaproveita
    scripts/chirps_v3_piloto.py::avaliar_qualidade_piloto (mesma
    distinção de 4 dimensões corrigida no item 3 desta revisão:
    disponibilidade no servidor, sucesso da extração, valor válido
    disponível, cobertura temporal completa)."""
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
                     help='Escreve o relatório do plano em docs/ — não executa rede.')
    args = ap.parse_args()

    plano = imprimir_plano()

    if args.gerar_relatorio:
        relatorio = gerar_relatorio_plano_markdown(plano)
        RELATORIO_PLANO_PATH.parent.mkdir(parents=True, exist_ok=True)
        RELATORIO_PLANO_PATH.write_text(relatorio)
        print(f"  ✅ {RELATORIO_PLANO_PATH.relative_to(ROOT)}")


if __name__ == '__main__':
    main()
