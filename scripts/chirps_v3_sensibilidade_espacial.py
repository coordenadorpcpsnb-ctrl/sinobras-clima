#!/usr/bin/env python3
"""
chirps_v3_sensibilidade_espacial.py — Fase 2C.3B, item 2: análise de
sensibilidade espacial do piloto de 17 meses (Fase 2C.3A) — compara o
pixel de referência (`CHIRPS_v3_ponto_centroide`) com seus 8 vizinhos
(scripts/_chirps_v3.py::comparar_pixel_com_vizinhos), para os MESMOS
17 meses já extraídos no piloto.

Contexto: a rodada anterior (correção da auditoria independente)
confirmou que o ponto de referência (lat=-7.80, lon=-47.95) fica
classificado como 'proximo_de_borda' nos DOIS eixos — a cerca de
0,1-0,2m de duas bordas do pixel selecionado (não exatamente sobre
elas). Isso significa que os vizinhos LESTE (L), SUL (S) e SUDESTE
(SL) são os candidatos mais próximos a uma escolha alternativa de
pixel sob uma convenção de arredondamento ligeiramente diferente — os
outros 5 vizinhos (N, O, NO, NL, SO) estão tão longe do ponto quanto
qualquer vizinho de um pixel comum, sem relação especial com a
proximidade de borda observada.

Este módulo NUNCA substitui o pixel de referência automaticamente
(item 2 da tarefa, explícito) — só produz estatísticas DESCRITIVAS das
diferenças, para apoiar uma decisão metodológica humana antes da
reconstrução completa (Fase 2C.3B). Os resultados são apresentados
SEPARADAMENTE do relatório do primeiro lote histórico (item 2 da
tarefa: "para permitir uma decisão metodológica antes da reconstrução
completa").

Roda com:
    python scripts/chirps_v3_sensibilidade_espacial.py --dry-run-plan
    python scripts/chirps_v3_sensibilidade_espacial.py --executar-analise-real
    python scripts/chirps_v3_sensibilidade_espacial.py --gerar-relatorio
"""

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import _chirps_v3 as v3  # noqa: E402
import chirps_v3_piloto as piloto  # noqa: E402

DATA_SENSIBILIDADE_CSV = ROOT / 'data' / 'chirps_v3_sensibilidade_piloto.csv'
DATA_SENSIBILIDADE_METADATA_JSON = ROOT / 'data' / 'chirps_v3_sensibilidade_piloto_metadata.json'
RELATORIO_SENSIBILIDADE_PATH = ROOT / 'docs' / 'nmme-fase2c3b-sensibilidade-espacial.md'

RATE_LIMIT_SEGUNDOS = 1.0
MAX_REQUISICOES_POR_EXECUCAO = 30   # o piloto tem 17 meses — nunca a série completa

# Vizinhos mais próximos de uma escolha alternativa de pixel, dado o
# achado confirmado de que o ponto está 'proximo_de_borda' no eixo
# leste (lon) e no eixo sul (lat) — ver docstring do módulo. Os outros
# 5 vizinhos (N, O, NO, NL, SO) não têm relação especial com essa
# proximidade — reportados por completude, não por serem candidatos
# plausíveis de seleção alternativa.
VIZINHOS_RELEVANTES_PARA_BORDA_CONHECIDA = ('L', 'S', 'SL')


# ══════════════════════════════════════════════════════════════════════════
# Execução real — reabre cada raster já usado no piloto, lê o pixel de
# referência + 8 vizinhos
# ══════════════════════════════════════════════════════════════════════════

def executar_analise_sensibilidade(meses=None, lat=v3.FAZENDAS_LAT, lon=v3.FAZENDAS_LON,
                                    formato='cog', max_requisicoes=MAX_REQUISICOES_POR_EXECUCAO,
                                    rate_limit_segundos=RATE_LIMIT_SEGUNDOS, abrir_fn=None):
    """Para cada mês, reabre o raster REAL (rede) já usado no piloto e
    lê o pixel de referência + 8 vizinhos (scripts/_chirps_v3.py::
    comparar_pixel_com_vizinhos) — NUNCA altera qual pixel é a
    referência oficial do projeto. `meses=None` usa
    scripts/chirps_v3_piloto.py::MESES_PILOTO (os mesmos 17 meses do
    piloto, item 2 da tarefa é explícito sobre isso).

    `abrir_fn`, se fornecido, substitui a abertura real por rede
    (injeção de dependência para teste sintético, nunca usado em
    produção real) — mesma função para todos os meses, recebe
    (ano, mes, formato)."""
    if meses is None:
        meses = piloto.MESES_PILOTO
    meses = meses[:max_requisicoes]

    resultados = []
    for i, (ano, mes) in enumerate(meses):
        if i > 0:
            time.sleep(rate_limit_segundos)
        entrada = {'ano': ano, 'mes': mes}
        try:
            abrir = (abrir_fn(ano, mes, formato) if abrir_fn
                     else v3.abrir_dataset_remoto(ano, mes, formato))
            with abrir as ds:
                grade = v3.verificar_grade(ds)
                if not grade['grade_ok']:
                    entrada['status'] = 'grade_inesperada'
                    entrada['comparacao'] = None
                    resultados.append(entrada)
                    print(f"  [{i+1}/{len(meses)}] {ano}-{mes:02d}: grade_inesperada")
                    continue
                comparacao = v3.comparar_pixel_com_vizinhos(ds, lat=lat, lon=lon)
            entrada['status'] = 'ok'
            entrada['comparacao'] = comparacao
        except Exception as e:
            entrada['status'] = 'erro'
            entrada['comparacao'] = None
            entrada['erro'] = str(e)
        resultados.append(entrada)
        print(f"  [{i+1}/{len(meses)}] {ano}-{mes:02d}: status={entrada['status']}")
    return resultados


def escrever_resultados_brutos(resultados, caminho_csv=DATA_SENSIBILIDADE_CSV):
    """Achata resultados em 1 linha por (ano, mes, vizinho) — nunca
    sobrescreve data/chirps_v3_piloto.csv (arquivo separado, item 8 da
    Fase 2C.3A, preservado)."""
    linhas = []
    for entrada in resultados:
        if entrada['status'] != 'ok' or entrada['comparacao'] is None:
            linhas.append({'ano': entrada['ano'], 'mes': entrada['mes'],
                            'vizinho': None, 'status_entrada': entrada['status']})
            continue
        comp = entrada['comparacao']
        for rotulo, v in comp['vizinhos'].items():
            linha = {'ano': entrada['ano'], 'mes': entrada['mes'], 'vizinho': rotulo,
                      'status_entrada': 'ok', 'dentro_do_raster': v.get('dentro_do_raster')}
            if v.get('dentro_do_raster'):
                linha['status_pixel'] = v.get('status')
                linha['valor_mm'] = v.get('valor_mm')
                linha['row'] = v.get('row')
                linha['col'] = v.get('col')
            linhas.append(linha)
    df = pd.DataFrame(linhas)
    caminho_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(caminho_csv, index=False)
    return df


def carregar_resultados_brutos(caminho_csv=DATA_SENSIBILIDADE_CSV):
    if not caminho_csv.exists():
        return pd.DataFrame(columns=['ano', 'mes', 'vizinho'])
    return pd.read_csv(caminho_csv)


# ══════════════════════════════════════════════════════════════════════════
# Estatísticas descritivas das diferenças — nunca troca a referência
# ══════════════════════════════════════════════════════════════════════════

def montar_estatisticas_sensibilidade(df_bruto):
    """Compara cada vizinho contra o 'centro' (o pixel de referência)
    do MESMO mês — só estatística DESCRITIVA (diferença absoluta,
    relativa) — nunca decide qual pixel é 'melhor', nunca substitui a
    referência. Destaca separadamente os vizinhos L/S/SL (os
    candidatos mais próximos de uma escolha alternativa, dado o
    achado confirmado de proximidade de borda nesses dois eixos) dos
    outros 5 (sem relação especial com a borda observada)."""
    if df_bruto.empty:
        return {'n_meses_comparaveis': 0, 'por_vizinho': {}, 'interpretacao':
                'Nenhum resultado disponível para análise de sensibilidade.'}

    validos = df_bruto[df_bruto['status_entrada'] == 'ok'].copy()
    meses_validos = sorted(set(zip(validos['ano'], validos['mes'])))

    linhas_por_vizinho = []
    for ano, mes in meses_validos:
        sub = validos[(validos['ano'] == ano) & (validos['mes'] == mes)]
        centro = sub[sub['vizinho'] == 'centro']
        if centro.empty or centro.iloc[0].get('status_pixel') not in ('ok', 'zero_real'):
            continue
        valor_centro = float(centro.iloc[0]['valor_mm'])
        for _, row in sub.iterrows():
            if row['vizinho'] == 'centro':
                continue
            if not row.get('dentro_do_raster'):
                continue
            if row.get('status_pixel') not in ('ok', 'zero_real'):
                continue
            valor_vizinho = float(row['valor_mm'])
            diff_abs = valor_vizinho - valor_centro
            diff_rel_pct = (diff_abs / valor_centro * 100) if valor_centro else None
            linhas_por_vizinho.append({
                'ano': ano, 'mes': mes, 'vizinho': row['vizinho'],
                'valor_centro_mm': valor_centro, 'valor_vizinho_mm': valor_vizinho,
                'diff_abs_mm': diff_abs, 'diff_rel_pct': diff_rel_pct,
            })

    comp_df = pd.DataFrame(linhas_por_vizinho)
    por_vizinho = {}
    if not comp_df.empty:
        for rotulo, grupo in comp_df.groupby('vizinho'):
            por_vizinho[rotulo] = {
                'n_meses': int(len(grupo)),
                'diff_abs_media_mm': round(float(grupo['diff_abs_mm'].mean()), 3),
                'diff_abs_maxima_mm': round(float(grupo['diff_abs_mm'].abs().max()), 3),
                'diff_rel_media_pct': round(float(grupo['diff_rel_pct'].dropna().mean()), 2)
                    if grupo['diff_rel_pct'].notna().any() else None,
            }

    diffs_relevantes = comp_df[comp_df['vizinho'].isin(VIZINHOS_RELEVANTES_PARA_BORDA_CONHECIDA)] \
        if not comp_df.empty else comp_df
    diffs_demais = comp_df[~comp_df['vizinho'].isin(VIZINHOS_RELEVANTES_PARA_BORDA_CONHECIDA)] \
        if not comp_df.empty else comp_df

    diff_abs_media_relevantes = round(float(diffs_relevantes['diff_abs_mm'].abs().mean()), 3) \
        if not diffs_relevantes.empty else None
    diff_abs_media_demais = round(float(diffs_demais['diff_abs_mm'].abs().mean()), 3) \
        if not diffs_demais.empty else None

    return {
        'n_meses_comparaveis': len(meses_validos),
        'por_vizinho': por_vizinho,
        'vizinhos_relevantes_para_borda_conhecida': list(VIZINHOS_RELEVANTES_PARA_BORDA_CONHECIDA),
        'diff_abs_media_vizinhos_relevantes_mm': diff_abs_media_relevantes,
        'diff_abs_media_demais_vizinhos_mm': diff_abs_media_demais,
        'interpretacao': (
            f"{len(meses_validos)} meses comparáveis (dos 17 do piloto). Diferença absoluta "
            f"média entre o pixel de referência e os vizinhos L/S/SL (os candidatos mais "
            f"próximos de uma seleção alternativa, dada a proximidade de borda confirmada "
            f"nesses dois eixos): {diff_abs_media_relevantes} mm. Diferença absoluta média "
            f"para os outros 5 vizinhos (sem relação especial com a borda observada): "
            f"{diff_abs_media_demais} mm. "
            + (
                "A proximidade à borda NÃO parece ter influência prática relevante nos "
                "valores — a diferença para os vizinhos mais próximos da borda observada não é "
                "sistematicamente maior que para os demais."
                if (diff_abs_media_relevantes is not None and diff_abs_media_demais is not None
                    and diff_abs_media_relevantes <= diff_abs_media_demais * 1.5)
                else
                "A proximidade à borda PODE ter influência prática relevante — a diferença "
                "para os vizinhos mais próximos da borda observada é maior que para os "
                "demais, o que sustenta considerar essa sensibilidade explicitamente na "
                "reconstrução completa (Fase 2C.3B)."
            ) + " Esta é uma leitura DESCRITIVA da amostra de 17 meses — nenhuma alternativa "
            "de pixel foi adotada, nenhuma referência foi substituída."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Consolidação + relatório
# ══════════════════════════════════════════════════════════════════════════

def montar_metadata_sensibilidade(df_bruto):
    estatisticas = montar_estatisticas_sensibilidade(df_bruto)
    return {
        'fase': '2C.3B, item 2 — análise de sensibilidade espacial do piloto (2026)',
        'data_geracao_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'meses_analisados': piloto.MESES_PILOTO,
        'n_meses_analisados': len(piloto.MESES_PILOTO),
        'estatisticas': estatisticas,
        'pixel_de_referencia_alterado': False,
        'nenhuma_skill_calculada': True,
    }


def gerar_relatorio_sensibilidade_markdown(metadata):
    e = metadata['estatisticas']
    linhas = [
        "# Análise de sensibilidade espacial — piloto CHIRPS v3.0 (Fase 2C.3B, item 2)",
        "",
        "**Análise descritiva — NUNCA substitui automaticamente o pixel de referência do "
        "projeto (`CHIRPS_v3_ponto_centroide`). Resultados apresentados separadamente do "
        "relatório do primeiro lote histórico, para permitir decisão metodológica antes da "
        "reconstrução completa.**",
        "",
        "## Contexto",
        "",
        "O ponto de referência (lat=-7,80, lon=-47,95) fica classificado como "
        "`proximo_de_borda` nos dois eixos (achado confirmado na correção da auditoria "
        "independente, Fase 2C.3A) — a cerca de 0,1-0,2m de duas bordas do pixel selecionado. "
        "Os vizinhos LESTE (L), SUL (S) e SUDESTE (SL) são os candidatos mais próximos de uma "
        "escolha alternativa de pixel sob uma convenção de arredondamento ligeiramente "
        "diferente.",
        "",
        f"## Resultados ({metadata['n_meses_analisados']} meses do piloto)",
        "",
        f"- {e['interpretacao']}",
        "",
        "### Estatísticas por vizinho",
        "",
        "| Vizinho | Relevante p/ borda conhecida | N meses | Diff. abs. média (mm) | Diff. "
        "abs. máxima (mm) | Diff. relativa média (%) |",
        "|---|---|---|---|---|---|",
    ]
    for rotulo, stats in sorted(e.get('por_vizinho', {}).items()):
        relevante = "SIM" if rotulo in e.get('vizinhos_relevantes_para_borda_conhecida', []) \
            else "não"
        linhas.append(
            f"| {rotulo} | {relevante} | {stats['n_meses']} | {stats['diff_abs_media_mm']} | "
            f"{stats['diff_abs_maxima_mm']} | {stats['diff_rel_media_pct']} |")
    linhas += [
        "",
        "## Restrições respeitadas",
        "",
        "- Nenhuma alternativa de pixel foi adotada — `CHIRPS_v3_ponto_centroide` continua "
        "sendo definido por `scripts/_chirps_v3.py::localizar_pixel()`.",
        "- Nenhum indicador de habilidade preditiva foi calculado.",
        "- Resultados brutos (por mês/vizinho) em `data/chirps_v3_sensibilidade_piloto.csv`.",
    ]
    return '\n'.join(linhas) + '\n'


def escrever_saidas(resultados, caminho_csv=DATA_SENSIBILIDADE_CSV):
    df_bruto = escrever_resultados_brutos(resultados, caminho_csv=caminho_csv)
    metadata = montar_metadata_sensibilidade(df_bruto)
    DATA_SENSIBILIDADE_METADATA_JSON.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=str))
    relatorio = gerar_relatorio_sensibilidade_markdown(metadata)
    RELATORIO_SENSIBILIDADE_PATH.parent.mkdir(parents=True, exist_ok=True)
    RELATORIO_SENSIBILIDADE_PATH.write_text(relatorio)
    print(f"  ✅ {caminho_csv.relative_to(ROOT)}")
    print(f"  ✅ {DATA_SENSIBILIDADE_METADATA_JSON.relative_to(ROOT)}")
    print(f"  ✅ {RELATORIO_SENSIBILIDADE_PATH.relative_to(ROOT)}")
    return metadata, relatorio


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def imprimir_plano():
    print("=== Análise de sensibilidade espacial — piloto CHIRPS v3.0 — Fase 2C.3B, item 2 "
          "— DRY RUN PLAN ===")
    print(f"  meses analisados: {len(piloto.MESES_PILOTO)} (os mesmos do piloto)")
    print("  vizinhos comparados: 8 (Moore neighborhood) + centro (referência)")
    print(f"  saídas: {DATA_SENSIBILIDADE_CSV.relative_to(ROOT)}, "
          f"{DATA_SENSIBILIDADE_METADATA_JSON.relative_to(ROOT)}, "
          f"{RELATORIO_SENSIBILIDADE_PATH.relative_to(ROOT)}")
    print("\n✅ Plano gerado (nenhuma análise ainda, pixel de referência nunca é alterado).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run-plan', action='store_true')
    ap.add_argument('--executar-analise-real', action='store_true',
                     help='Roda a análise REAL (rede) sobre os 17 meses do piloto.')
    ap.add_argument('--gerar-relatorio', action='store_true',
                     help='Gera os relatórios a partir do que já estiver persistido (não '
                          'executa rede).')
    args = ap.parse_args()

    if args.executar_analise_real:
        imprimir_plano()
        resultados = executar_analise_sensibilidade()
        metadata, _ = escrever_saidas(resultados)
        print(f"\nn_meses_comparaveis={metadata['estatisticas']['n_meses_comparaveis']}")
        return

    if args.gerar_relatorio:
        df_bruto = carregar_resultados_brutos()
        metadata = montar_metadata_sensibilidade(df_bruto)
        DATA_SENSIBILIDADE_METADATA_JSON.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False, default=str))
        relatorio = gerar_relatorio_sensibilidade_markdown(metadata)
        RELATORIO_SENSIBILIDADE_PATH.parent.mkdir(parents=True, exist_ok=True)
        RELATORIO_SENSIBILIDADE_PATH.write_text(relatorio)
        print(f"  ✅ {RELATORIO_SENSIBILIDADE_PATH.relative_to(ROOT)}")
        return

    imprimir_plano()


if __name__ == '__main__':
    main()
