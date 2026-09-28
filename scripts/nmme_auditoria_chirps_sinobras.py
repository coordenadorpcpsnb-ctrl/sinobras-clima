#!/usr/bin/env python3
"""
nmme_auditoria_chirps_sinobras.py — Fase 2C.2, investigação dedicada
da reinterpretação CHIRPS (4ª rodada, 2026).

Contexto: o responsável pelos dados informou que SINOBRAS.csv
(registros por fazenda, 1996-2025, já auditado por
scripts/nmme_auditoria_sinobras_por_fazenda.py) contém ESTIMATIVAS
extraídas do CHIRPS por fazenda — não leituras diretas de pluviômetro.
A empresa não tem pluviômetro em todas as fazendas. A versão e a
metodologia de extração do CHIRPS usadas para produzir SINOBRAS.csv
ainda NÃO foram verificadas documentalmente.

Este módulo:
1. Compara `data/serie_subst.csv` (que reproduz SINOBRAS.csv para
   1996-2025, achado já verificado em rodada anterior) com
   `data/chirps_1981_2025.csv` — um CHIRPS de METODOLOGIA CONHECIDA
   (ClimateSERV, dataset 0, ponto único no centroide das fazendas,
   ~0,05° de resolução; ver scripts/backfill_chirps_historico.py),
   já extraído neste repositório para o MESMO ponto. Nunca presume
   que os dois vêm da mesma metodologia — só compara.
2. Lista as informações necessárias para reproduzir a extração de
   SINOBRAS.csv (versão do CHIRPS, coordenadas/polígonos por fazenda,
   resolução, agregação espacial, processamento temporal, unidades).
3. Avalia a viabilidade técnica de uma referência CHIRPS espacial e
   temporalmente consistente para 1991-2011, informada pelas
   capacidades JÁ EXISTENTES de scripts/_chirps.py (nunca executa uma
   nova extração — isso seria substituir a referência observacional
   atual, fora do escopo desta tarefa).

Nunca calcula skill, nunca recalcula previsões/indicadores de
desempenho, nunca substitui a referência observacional de produção,
nunca modifica dados históricos, nunca altera o dashboard ou os
modelos climáticos — só lê data/chirps_1981_2025.csv e
data/serie_subst.csv (ambos já no repositório) e escreve um relatório
técnico + tabelas de auditoria em artifacts/.

Roda com:
    python scripts/nmme_auditoria_chirps_sinobras.py --dry-run-plan
    python scripts/nmme_auditoria_chirps_sinobras.py --gerar-relatorio
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import nmme_piloto_historico as pilo  # noqa: E402

ARTIFACTS_DIR = ROOT / 'artifacts' / 'nmme_auditoria_chirps_sinobras'
RELATORIO_DOC_PATH = ROOT / 'docs' / 'nmme-fase2c2-auditoria-chirps-sinobras.md'

CHIRPS_PONTO_PATH = ROOT / 'data' / 'chirps_1981_2025.csv'
SERIE_PRODUCAO_PATH = pilo.SERIE_OBSERVACIONAL_PATH   # data/serie_subst.csv

ANO_FIM_MERRA2 = pilo.ANO_FIM_MERRA2   # 1995

# Metodologia do CHIRPS já extraído neste repositório (verificada por
# leitura de código em scripts/_chirps.py/backfill_chirps_historico.py
# — nunca assumida). Citada aqui como fato JÁ CONHECIDO, para contraste
# explícito com a metodologia de SINOBRAS.csv, que é DESCONHECIDA.
METODOLOGIA_CHIRPS_PONTO_CONHECIDA = {
    'fonte': 'CHIRPS (UCSB), via ClimateSERV, dataset 0',
    'geometria': 'ponto único no centroide das fazendas (lat=-7.80, lon=-47.95)',
    'resolucao_graus': 0.05,
    'script': 'scripts/_chirps.py::buscar_prec_chirps',
    'backfill_historico': 'scripts/backfill_chirps_historico.py (execução única, já rodada)',
    'versao_chirps_pinada': False,   # ClimateSERV serve a versão corrente — não travada/documentada
    'data_extracao_documentada': False,   # backfill_chirps_historico.py não grava a data de execução
}


# ══════════════════════════════════════════════════════════════════════════
# Item 5 — comparar data/chirps_1981_2025.csv com a série consolidada
# ══════════════════════════════════════════════════════════════════════════

def carregar_chirps_ponto(caminho=CHIRPS_PONTO_PATH):
    """Só leitura — nunca modifica data/chirps_1981_2025.csv."""
    return pd.read_csv(caminho)


def carregar_serie_producao(caminho=SERIE_PRODUCAO_PATH):
    """Só leitura — nunca modifica data/serie_subst.csv."""
    return pd.read_csv(caminho)


def comparar_chirps_ponto_com_serie_producao(chirps_df, serie_df):
    """Item 5 — compara os dois SEM presumir que vêm da mesma
    metodologia. `data/chirps_1981_2025.csv` é CHIRPS de metodologia
    CONHECIDA (ponto único, ClimateSERV); `data/serie_subst.csv`
    reproduz SINOBRAS.csv para 1996-2025 (achado já verificado por
    scripts/nmme_auditoria_sinobras_por_fazenda.py) e o backfill
    MERRA-2/3-municípios para <=1995. Separa a comparação por período
    — nunca um número agregado único que esconderia divergência de
    comportamento entre os dois trechos."""
    merged = serie_df.merge(chirps_df, on=['ano', 'mes'], suffixes=('_serie', '_chirps_ponto'),
                             how='inner')
    merged['diff_abs_mm'] = (merged['prec_serie'] - merged['prec_chirps_ponto']).abs()
    merged['razao_serie_sobre_chirps'] = (
        merged['prec_serie'] / merged['prec_chirps_ponto'].replace(0, pd.NA))

    def _resumo(sub):
        n = len(sub)
        if not n:
            return {'n_meses': 0, 'diff_abs_media_mm': None, 'diff_abs_maxima_mm': None,
                     'correlacao': None, 'razao_mediana': None,
                     'n_meses_identicos_diff_menor_0_01mm': 0}
        return {
            'n_meses': int(n),
            'diff_abs_media_mm': round(float(sub['diff_abs_mm'].mean()), 2),
            'diff_abs_maxima_mm': round(float(sub['diff_abs_mm'].max()), 2),
            'correlacao': round(float(sub['prec_serie'].corr(sub['prec_chirps_ponto'])), 4),
            'razao_mediana': round(float(sub['razao_serie_sobre_chirps'].median()), 3),
            'n_meses_identicos_diff_menor_0_01mm': int((sub['diff_abs_mm'] < 0.01).sum()),
        }

    pos_1996 = merged[merged['ano'] > ANO_FIM_MERRA2]
    pre_1996 = merged[merged['ano'] <= ANO_FIM_MERRA2]
    resumo_pos = _resumo(pos_1996)
    resumo_pre = _resumo(pre_1996)

    return {
        'n_meses_comparados_total': int(len(merged)),
        'periodo_pos_1996': resumo_pos,
        'periodo_pre_1996': resumo_pre,
        'interpretacao': (
            f"{len(merged)} meses comparáveis entre data/serie_subst.csv (que reproduz "
            "SINOBRAS.csv para 1996-2025) e data/chirps_1981_2025.csv (CHIRPS de metodologia "
            "CONHECIDA, ponto único no centroide das fazendas). Pós-1996: correlação "
            f"{resumo_pos['correlacao']}, razão mediana {resumo_pos['razao_mediana']}, mas só "
            f"{resumo_pos['n_meses_identicos_diff_menor_0_01mm']}/{len(pos_1996)} meses "
            "IDÊNTICOS — a correlação alta e a razão mediana próxima de 1 são CONSISTENTES com "
            "ambas as séries terem origem CHIRPS, mas a ausência de identidade numérica mês a "
            "mês mostra que NÃO são a mesma extração (ponto/pixel diferente, versão diferente do "
            "CHIRPS, ou agregação espacial diferente — todas possibilidades em aberto, nenhuma "
            "confirmada). Pré-1996: correlação "
            f"{resumo_pre['correlacao']} — mais alta ainda que pós-1996, um achado "
            "curioso que NÃO deve ser lido como prova de que o trecho MERRA-2/3-municípios "
            "também é CHIRPS (isso permanece não comprovado, item 7 da tarefa) — só registrado "
            "aqui como observação para investigação futura."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Item 4 — informações necessárias para reproduzir a extração de SINOBRAS.csv
# ══════════════════════════════════════════════════════════════════════════

def montar_lista_informacoes_necessarias_reproducao():
    """Item 4 — lista OBJETIVA (não computada) do que falta para
    reproduzir a extração que gerou SINOBRAS.csv. Cada item contrasta
    explicitamente com o que JÁ é conhecido para
    data/chirps_1981_2025.csv (METODOLOGIA_CHIRPS_PONTO_CONHECIDA),
    para deixar claro que ter UM CHIRPS no repositório não supre a
    necessidade de conhecer o OUTRO."""
    return [
        "Versão do produto CHIRPS usada para gerar SINOBRAS.csv (ex.: CHIRPS v2.0 Final vs. "
        "Preliminary) e a data de extração. Contraste: nem mesmo data/chirps_1981_2025.csv "
        "(extraído NESTE repositório) tem isso documentado — ClimateSERV serve a versão "
        "corrente, sem versionamento explícito registrado em "
        "scripts/backfill_chirps_historico.py.",
        "Coordenada ou polígono usado para extrair a estimativa de CADA uma das 34 fazendas — "
        "SINOBRAS.csv não traz coordenadas (achado de "
        "scripts/nmme_auditoria_sinobras_por_fazenda.py). Sem isso, não é possível saber se os "
        "grupos de séries idênticas (FAZ02/03/04/05/08/09/19 e FAZ07/FAZ15) correspondem a "
        "fazendas no mesmo pixel CHIRPS.",
        "Resolução espacial usada — CHIRPS nativo é 0,05° (~5,5km no equador); confirmar se a "
        "extração de SINOBRAS.csv usou essa resolução nativa (ponto único por fazenda, como "
        "scripts/_chirps.py::buscar_prec_chirps faz para o centroide) ou uma agregação sobre "
        "múltiplos pixels por fazenda (análogo a buscar_prec_chirps_zonal, mas por fazenda "
        "individual).",
        "Regra de agregação espacial — se mais de um pixel CHIRPS foi usado por fazenda, qual "
        "critério (média simples? ponderada pela área de sobreposição?) resume os valores.",
        "Processamento temporal — CHIRPS nativo é diário; confirmar a regra de agregação "
        "diária→mensal (soma simples do mês? exigência de cobertura mínima de dias válidos?).",
        "Unidades e arredondamento — SINOBRAS.csv está em mm/mês, valores inteiros; CHIRPS "
        "nativo é mm/dia. Confirmar se o arredondamento para inteiro foi feito na extração ou "
        "em uma etapa posterior (perda de precisão relevante para meses de chuva baixa, ex.: "
        "jul/ago, onde CLAUDE.md armadilha 7 já documenta viés conhecido de fontes de satélite).",
        "Ferramenta/serviço de extração usado (ClimateSERV, como este repositório usa? Google "
        "Earth Engine? download direto dos GeoTIFFs do CHIRPS?) — determina quais dos vieses "
        "conhecidos de ClimateSERV (CLAUDE.md armadilha 7, tabela ERA5/CHIRPS por mês) se "
        "aplicam ou não a SINOBRAS.csv.",
        "Confirmação de quais das 34 fazendas — se alguma — têm, além da estimativa CHIRPS, um "
        "pluviômetro físico real instalado; a empresa não tem pluviômetro em todas.",
    ]


# ══════════════════════════════════════════════════════════════════════════
# Item 6 — viabilidade de uma referência CHIRPS consistente para 1991-2011
# ══════════════════════════════════════════════════════════════════════════

def avaliar_viabilidade_referencia_chirps_1991_2011():
    """Item 6 — avaliação de VIABILIDADE TÉCNICA, nunca uma execução.
    Este módulo NUNCA chama o ClimateSERV nem qualquer rede — isso
    seria uma nova extração, fora do escopo desta tarefa (a referência
    observacional de produção não pode ser substituída
    automaticamente). Informada pelas capacidades JÁ EXISTENTES e já
    exercitadas de scripts/_chirps.py e
    scripts/backfill_chirps_historico.py."""
    ja_disponivel = CHIRPS_PONTO_PATH.exists()
    n_meses_1991_2011 = None
    if ja_disponivel:
        chirps_df = carregar_chirps_ponto()
        cobertos = chirps_df[(chirps_df['ano'] >= 1991) & (chirps_df['ano'] <= 2011)]
        n_meses_1991_2011 = int(len(cobertos))
    return {
        'data_chirps_1981_2025_ja_cobre_1991_2011': ja_disponivel,
        'n_meses_1991_2011_ja_extraidos': n_meses_1991_2011,
        'n_meses_1991_2011_esperados': 252,   # 21 anos completos x 12
        'ferramentas_ja_existentes': {
            'ponto_unico': 'scripts/_chirps.py::buscar_prec_chirps — já usado para gerar '
                            'data/chirps_1981_2025.csv',
            'zonal_envelope': 'scripts/_chirps.py::buscar_prec_chirps_zonal — existe, cobre o '
                               'envelope das 34 fazendas (CLAUDE.md armadilha 8), mas NUNCA '
                               'passou pela suíte de falha de tests/test_fetch_fallback.py — '
                               'promoção a primário é decisão separada, não tomada aqui nem '
                               'antes.',
            'quebra_em_blocos': 'scripts/backfill_chirps_historico.py já resolve a limitação de '
                                 'período (ClimateSERV rejeita ~45 anos numa chamada só) — o '
                                 'padrão de blocos de ~10 anos já está implementado e testado '
                                 'contra o servidor real.',
        },
        'interpretacao': (
            "TECNICAMENTE VIÁVEL, com ressalvas — nunca executado aqui. "
            f"data/chirps_1981_2025.csv JÁ COBRE 1991-2011 ({n_meses_1991_2011}/252 meses "
            "esperados) com metodologia conhecida (ponto único, centroide das fazendas, "
            "ClimateSERV) — tecnicamente, boa parte do trabalho de construir uma referência "
            "CHIRPS consistente para esse período JÁ FOI FEITO, não precisa ser refeito do "
            "zero. Ressalvas que impedem declarar isso 'pronto': (1) a VERSÃO do CHIRPS servida "
            "pelo ClimateSERV pode ter mudado desde a extração original (não versionada, não "
            "documentada — mesma lacuna que impede reproduzir SINOBRAS.csv, item 4 acima); "
            "reextrair hoje pode não bater byte a byte com o arquivo já salvo; (2) ponto único "
            "vs. zonal — o envelope de 34 fazendas tem ~85.020 ha, MUITO maior que 1 pixel "
            "CHIRPS (0,05°, ~30 km²); um ponto único no centroide é um proxy, não uma média "
            "representativa da área toda — buscar_prec_chirps_zonal existe mas não tem a "
            "cobertura de teste de falha exigida para promoção a primário; (3) ainda que uma "
            "referência CHIRPS ponto-único fosse aceita, ela SUBSTITUIRIA a referência "
            "observacional atual (MERRA-2/3-municípios pré-1996 + SINOBRAS.csv pós-1996) — "
            "decisão explícita que este módulo NÃO toma (restrição desta tarefa: não substituir "
            "automaticamente a referência observacional). Próximo passo recomendado, se essa "
            "substituição for aprovada no futuro: (a) reextrair 1991-2011 com "
            "buscar_prec_chirps e comparar contra o data/chirps_1981_2025.csv já salvo para "
            "confirmar estabilidade de versão; (b) rodar buscar_prec_chirps_zonal pela suíte de "
            "falha de tests/test_fetch_fallback.py antes de considerar promovê-lo."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Proposta de continuidade (exigida pelas restrições desta tarefa)
# ══════════════════════════════════════════════════════════════════════════

def montar_proposta_continuidade():
    """Restrição desta tarefa — "produzir... uma proposta de
    continuidade". Lista objetiva de próximos passos, em ordem de
    esforço crescente, nenhum executado aqui."""
    return [
        "Obter do responsável pelos dados um documento técnico (não apenas comunicação verbal) "
        "descrevendo a extração de SINOBRAS.csv: versão do CHIRPS, ferramenta, coordenadas/"
        "polígonos por fazenda, resolução, agregação espacial e temporal, unidades — ver "
        "montar_lista_informacoes_necessarias_reproducao() para a lista completa.",
        "Obter confirmação explícita de quais das 34 fazendas — se alguma — têm pluviômetro "
        "físico real, para não tratar nenhuma fazenda como instrumentada sem confirmação.",
        "Com as coordenadas/polígonos em mãos, verificar computacionalmente se os 2 grupos de "
        "séries idênticas (FAZ02/03/04/05/08/09/19 e FAZ07/FAZ15) correspondem a fazendas no "
        "mesmo pixel CHIRPS (0,05°) — isso confirmaria ou refutaria a hipótese de "
        "compartilhamento de pixel como explicação, sem precisar reextrair nada.",
        "Reextrair 1991-2011 com scripts/_chirps.py::buscar_prec_chirps (ponto único, já "
        "testado) e comparar contra data/chirps_1981_2025.csv já salvo — se os valores "
        "baterem, confirma estabilidade de versão do CHIRPS ao longo do tempo; se não baterem, "
        "documenta a divergência antes de qualquer uso científico.",
        "Rodar scripts/_chirps.py::buscar_prec_chirps_zonal pela suíte de falha de "
        "tests/test_fetch_fallback.py (hoje só cobre buscar_prec_chirps) antes de considerar "
        "promovê-lo a fonte primária para qualquer finalidade.",
        "Só depois de tudo acima: decisão EXPLÍCITA e documentada (não automática, fora do "
        "escopo desta tarefa) sobre se/como uma referência CHIRPS construída internamente "
        "substituiria, complementaria, ou seria reportada lado a lado com a referência "
        "observacional atual (MERRA-2/3-municípios pré-1996 + SINOBRAS.csv pós-1996) para fins "
        "de validação do CFSv2.",
    ]


# ══════════════════════════════════════════════════════════════════════════
# Consolidação + relatório
# ══════════════════════════════════════════════════════════════════════════

def executar_investigacao_completa():
    chirps_df = carregar_chirps_ponto()
    serie_df = carregar_serie_producao()
    comparacao = comparar_chirps_ponto_com_serie_producao(chirps_df, serie_df)
    informacoes_necessarias = montar_lista_informacoes_necessarias_reproducao()
    viabilidade = avaliar_viabilidade_referencia_chirps_1991_2011()
    proposta_continuidade = montar_proposta_continuidade()

    metadata = {
        'fase': '2C.2 — investigação dedicada da reinterpretação CHIRPS (4ª rodada, 2026)',
        'metodologia_chirps_ponto_conhecida': METODOLOGIA_CHIRPS_PONTO_CONHECIDA,
        'comparacao_chirps_ponto_vs_serie_producao': comparacao,
        'informacoes_necessarias_para_reproducao': informacoes_necessarias,
        'viabilidade_referencia_chirps_1991_2011': viabilidade,
        'proposta_de_continuidade': proposta_continuidade,
        'nenhuma_skill_calculada': True,
        'nenhuma_previsao_ou_indicador_recalculado': True,
        'nenhuma_referencia_observacional_substituida': True,
        'nenhum_dado_historico_modificado': True,
        'nenhum_dashboard_alterado': True,
        'nenhum_modelo_climatico_alterado': True,
        'nenhuma_extracao_nova_executada': True,
    }
    return metadata


def gerar_relatorio_markdown(metadata):
    meto = metadata['metodologia_chirps_ponto_conhecida']
    comp = metadata['comparacao_chirps_ponto_vs_serie_producao']
    viab = metadata['viabilidade_referencia_chirps_1991_2011']

    linhas = [
        "# Investigação CHIRPS — reinterpretação da referência observacional Sinobras",
        "",
        "**Relatório técnico — não calcula skill, não recalcula previsões/indicadores, não "
        "substitui a referência observacional atual, não altera dados históricos, dashboard "
        "nem modelos climáticos.**",
        "",
        "## Contexto",
        "",
        "O responsável pelos dados informou que SINOBRAS.csv (registros por fazenda, "
        "1996-2025, já auditado em docs/nmme-fase2c2-auditoria-sinobras-por-fazenda.md) contém "
        "ESTIMATIVAS extraídas do CHIRPS por fazenda — não leituras diretas de pluviômetro. A "
        "empresa não tem pluviômetro em todas as fazendas. A classificação em "
        "docs/nmme-fase2c2-auditoria-observacional-historica.md e em "
        "scripts/nmme_piloto_historico.py foi corrigida para refletir isso (achado "
        "'reinterpretacao_chirps') — este documento é a investigação dedicada.",
        "",
        "## 1. Metodologia do CHIRPS já extraído neste repositório (referência de contraste)",
        "",
        f"- Fonte: {meto['fonte']}.",
        f"- Geometria: {meto['geometria']}.",
        f"- Resolução: {meto['resolucao_graus']}° (~5,5km no equador).",
        f"- Script: `{meto['script']}`.",
        f"- Backfill histórico: `{meto['backfill_historico']}`.",
        f"- Versão do CHIRPS pinada/documentada: {meto['versao_chirps_pinada']}. Data de "
        f"extração documentada: {meto['data_extracao_documentada']}.",
        "- Esta metodologia é CONHECIDA (verificada por leitura de código) — serve de contraste "
        "explícito: mesmo este CHIRPS, extraído dentro deste repositório, tem lacunas de "
        "versionamento. A metodologia de SINOBRAS.csv é inteiramente DESCONHECIDA.",
        "",
        "## 2. Comparação: data/chirps_1981_2025.csv × data/serie_subst.csv",
        "",
        f"- Meses comparados no total: {comp['n_meses_comparados_total']}.",
        "",
        "### Período pós-1996 (SINOBRAS.csv, agora reinterpretado como CHIRPS)",
        "",
    ]
    pos = comp['periodo_pos_1996']
    linhas += [
        f"- Meses comparados: {pos['n_meses']}.",
        f"- Diferença absoluta média: {pos['diff_abs_media_mm']} mm. Máxima: "
        f"{pos['diff_abs_maxima_mm']} mm.",
        f"- Correlação: {pos['correlacao']}. Razão mediana (série/CHIRPS-ponto): "
        f"{pos['razao_mediana']}.",
        f"- Meses numericamente idênticos (diff < 0,01mm): "
        f"{pos['n_meses_identicos_diff_menor_0_01mm']}/{pos['n_meses']}.",
        "",
        "### Período pré-1996 (MERRA-2/3-municípios — procedência não comprovada, item 7)",
        "",
    ]
    pre = comp['periodo_pre_1996']
    linhas += [
        f"- Meses comparados: {pre['n_meses']}.",
        f"- Diferença absoluta média: {pre['diff_abs_media_mm']} mm. Máxima: "
        f"{pre['diff_abs_maxima_mm']} mm.",
        f"- Correlação: {pre['correlacao']}. Razão mediana (série/CHIRPS-ponto): "
        f"{pre['razao_mediana']}.",
        f"- Meses numericamente idênticos (diff < 0,01mm): "
        f"{pre['n_meses_identicos_diff_menor_0_01mm']}/{pre['n_meses']}.",
        "",
        f"- {comp['interpretacao']}",
        "",
        "## 3. Informações necessárias para reproduzir a extração de SINOBRAS.csv",
        "",
    ]
    for item in metadata['informacoes_necessarias_para_reproducao']:
        linhas.append(f"- {item}")
    linhas += [
        "",
        "## 4. Viabilidade de uma referência CHIRPS consistente para 1991-2011",
        "",
        f"- data/chirps_1981_2025.csv já cobre 1991-2011: "
        f"{viab['data_chirps_1981_2025_ja_cobre_1991_2011']} "
        f"({viab['n_meses_1991_2011_ja_extraidos']}/{viab['n_meses_1991_2011_esperados']} meses).",
        f"- {viab['interpretacao']}",
        "",
        "## 5. Proposta de continuidade",
        "",
    ]
    for i, item in enumerate(metadata['proposta_de_continuidade'], 1):
        linhas.append(f"{i}. {item}")
    linhas += [
        "",
        "## Restrições respeitadas nesta tarefa",
        "",
        "- Nenhuma métrica de skill foi calculada.",
        "- Nenhuma previsão ou indicador de desempenho foi recalculado.",
        "- A referência observacional de produção (data/serie_subst.csv) NÃO foi substituída — "
        "só lida para comparação.",
        "- Nenhum dado histórico foi modificado.",
        "- O dashboard (docs/index.html) não foi tocado. Nenhum modelo climático foi alterado.",
        "- Nenhuma nova extração do CHIRPS foi executada (nenhum acesso à rede/ClimateSERV "
        "nesta tarefa) — a comparação usa exclusivamente data/chirps_1981_2025.csv, já "
        "existente no repositório.",
    ]
    return '\n'.join(linhas) + '\n'


def escrever_saidas(metadata):
    """Tabelas/metadata reproduzíveis (reexecutando este script, que só "
    lê arquivos já commitados) ficam em artifacts/ — gitignored. O
    relatório técnico vai para docs/, commitado."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS_DIR / 'metadata.json').write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=str))
    relatorio = gerar_relatorio_markdown(metadata)
    RELATORIO_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    RELATORIO_DOC_PATH.write_text(relatorio)
    print("  ✅ artifacts/nmme_auditoria_chirps_sinobras/metadata.json")
    print(f"  ✅ {RELATORIO_DOC_PATH.relative_to(ROOT)}")
    return relatorio


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def imprimir_plano():
    print("=== Investigação CHIRPS — reinterpretação da referência observacional Sinobras — "
          "Fase 2C.2 — DRY RUN PLAN (só leitura de arquivos locais já commitados, nenhum "
          "acesso à rede) ===")
    print(f"  entrada: {CHIRPS_PONTO_PATH.relative_to(ROOT)} (já existente) + "
          f"{SERIE_PRODUCAO_PATH.relative_to(ROOT)} (já existente)")
    print("  verificações: comparação CHIRPS-ponto × série de produção, informações necessárias "
          "para reprodução, viabilidade de referência CHIRPS 1991-2011")
    print("  saidas: artifacts/nmme_auditoria_chirps_sinobras/ (gitignored) + "
          "docs/nmme-fase2c2-auditoria-chirps-sinobras.md")
    print("\n✅ Plano gerado (nenhuma extração nova, nenhum cálculo de skill, nenhuma escrita "
          "ainda).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run-plan', action='store_true',
                     help='Só mostra o plano — nenhuma leitura pesada, nenhuma escrita.')
    ap.add_argument('--gerar-relatorio', action='store_true',
                     help='Roda a investigação completa (só leitura de dados locais já '
                          'existentes) e escreve o relatório técnico + metadata em artifacts/.')
    args = ap.parse_args()

    if args.gerar_relatorio:
        imprimir_plano()
        metadata = executar_investigacao_completa()
        escrever_saidas(metadata)
        comp = metadata['comparacao_chirps_ponto_vs_serie_producao']
        print(f"\ncorrelacao_pos_1996={comp['periodo_pos_1996']['correlacao']}")
        print(f"correlacao_pre_1996={comp['periodo_pre_1996']['correlacao']}")
        return

    imprimir_plano()


if __name__ == '__main__':
    main()
