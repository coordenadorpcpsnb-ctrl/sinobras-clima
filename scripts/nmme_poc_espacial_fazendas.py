#!/usr/bin/env python3
"""
nmme_poc_espacial_fazendas.py — Fase 2C.2, POC espacial INDEPENDENTE
para o centroide das fazendas (item 2 da tarefa de preparação da
extração histórica).

Objetivo: verificar se a mesma rota já EMPIRICALLY_CONFIRMED
(IRIDL_LEGACY/NMME_HARMONIZED_MONTHLY, Fase 2C.1b) responde igualmente
bem para o ponto que a série observacional de produção
(data/serie_subst.csv) realmente representa — o centroide das fazendas
(lat=-7.80, lon=-47.95, mesmo valor de scripts/_chirps.py::
FAZENDAS_LAT/FAZENDAS_LON e scripts/_openmeteo.py — nunca redefinido
de forma diferente) — que fica a ~198 km do ponto do POC original (São
Bento do Tocantins), achado documentado em
docs/nmme-fase2c2-piloto-cobertura-observacional.md.

NUNCA altera as coordenadas do POC já validado: `scripts/_c3s_utils.py::
MUNICIPIOS['Sao_Bento_do_Tocantins']` e `scripts/nmme_poc.py::MUNICIPIO/
POC_ORIGEM` continuam exatamente como estavam. Este módulo passa
`lat`/`lon` explícitos para `nmme_poc.executar_poc_real_cfsv2`
(parâmetro aditivo, Fase 2C.2 — quando informado, sobrepõe o lookup em
MUNICIPIOS sem tocar nele) — a mesma origem (2005-01, já validada em
produção) e os mesmos leads H1-H6, mudando só o ponto, para isolar o
efeito da localização de qualquer outra variável.

Reaproveita TODOS os guardrails já testados do POC original
(nmme_poc.executar_poc_real_cfsv2/avaliar_aprovacao_poc) sem
modificação — seleção temporal explícita por coordenada, membros,
horizontes, unidades, grade. Nenhuma lógica nova de integridade é
escrita aqui.

Esta localização NUNCA é tratada como validada só por rodar este
script (Seção 2 da tarefa: "não considerar a nova localização validada
antes de uma execução real aprovada") — mesmo com `poc_status=APROVADO`,
nenhum catálogo é promovido (scripts/nmme_catalogo.py nunca é
importado por escrita aqui), e o `localizacao_validada` do resultado
fica SEMPRE False nesta revisão, mesmo em caso de aprovação — uma
promoção formal exigiria decisão explícita separada.

Os conjuntos de dados das duas localidades ficam COMPLETAMENTE
separados: este módulo escreve em artifacts/nmme_poc_espacial_fazendas/,
nunca em artifacts/nmme_poc/ (São Bento) — nenhum arquivo é
compartilhado, nenhuma linha é concatenada entre as duas.

Roda com:
    python scripts/nmme_poc_espacial_fazendas.py --dry-run-plan
    python scripts/nmme_poc_espacial_fazendas.py --executar-poc-real
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import nmme_piloto_historico as pilo  # noqa: E402
import nmme_poc as npoc  # noqa: E402

ARTIFACTS_DIR = ROOT / 'artifacts' / 'nmme_poc_espacial_fazendas'

# Mesmo valor de scripts/_chirps.py::FAZENDAS_LAT/FAZENDAS_LON e
# scripts/_openmeteo.py — nunca redefinido de forma diferente (Seção 2
# da tarefa: coordenada do centroide das fazendas).
FAZENDAS_LAT, FAZENDAS_LON = -7.80, -47.95

LOCALIZACAO_ID = 'Fazendas_Sinobras_Centroide'


def executar_poc_espacial_fazendas(origem=None, leads=None, sistema=None,
                                      baixar_fn=None, abrir_fn=None):
    """Reaproveita nmme_poc.executar_poc_real_cfsv2 SEM modificação —
    só passa lat/lon explícitos (o parâmetro aditivo da Fase 2C.2) em
    vez de resolver por MUNICIPIOS. Default de origem/leads é
    EXATAMENTE o mesmo do POC de São Bento (POC_ORIGEM=2005-01,
    LEADS=H1-H6) — controla a origem/horizontes para isolar só o
    efeito da localização (Seção 2: "executar os mesmos controles de
    seleção temporal, membros, horizontes, unidades e grade")."""
    origem = origem or npoc.POC_ORIGEM
    leads = leads or npoc.LEADS
    resultado = npoc.executar_poc_real_cfsv2(
        origem=origem, leads=leads, sistema=sistema,
        lat=FAZENDAS_LAT, lon=FAZENDAS_LON,
        baixar_fn=baixar_fn, abrir_fn=abrir_fn)
    aprovacao = npoc.avaliar_aprovacao_poc(resultado)
    resultado = {**resultado, 'poc_status': aprovacao['poc_status'], 'checklist': aprovacao['checklist']}
    return resultado, aprovacao


def montar_metadata_espacial(resultado, aprovacao):
    from _c3s_utils import MUNICIPIOS
    sao_bento = MUNICIPIOS[npoc.MUNICIPIO]
    dist_km = pilo.nproc.distancia_km_aprox(FAZENDAS_LAT, FAZENDAS_LON,
                                               sao_bento['lat'], sao_bento['lon'])
    raw_df = resultado.get('raw_df', pd.DataFrame())
    return {
        'fase': '2C.2 — POC espacial independente (centroide das fazendas)',
        'localizacao_id': LOCALIZACAO_ID, 'localizacao_lat': FAZENDAS_LAT,
        'localizacao_lon': FAZENDAS_LON,
        # Seção 2 da tarefa — nunca considerado validado só por rodar
        # este script, mesmo com poc_status=APROVADO; promoção exige
        # decisão explícita separada, não tomada aqui.
        'localizacao_validada': False,
        'poc_sao_bento_ponto': npoc.MUNICIPIO,
        'poc_sao_bento_lat': sao_bento['lat'], 'poc_sao_bento_lon': sao_bento['lon'],
        'poc_sao_bento_coordenadas_alteradas': False,
        'distancia_ate_poc_sao_bento_km': round(dist_km, 1),
        'poc_status': resultado.get('poc_status'), 'checklist': resultado.get('checklist', {}),
        'n_raw': len(raw_df),
        'backend_used': resultado.get('backend_used'),
        'dataset_representation_used': resultado.get('dataset_representation_used'),
        'nenhuma_skill_calculada': True, 'nenhum_dashboard_alterado': True,
        'nenhuma_rota_ou_representacao_promovida': True,
        'dataset_separado_de_sao_bento': 'artifacts/nmme_poc_espacial_fazendas/ '
                                           '(nunca artifacts/nmme_poc/)',
    }


def gerar_relatorio_espacial_markdown(resultado, metadata):
    linhas = [
        "# NMME — POC espacial independente (centroide das fazendas, Fase 2C.2)", "",
        "**POC experimental — não considerar esta localização validada só por este "
        "resultado (Seção 2 da tarefa). Nunca conclusão científica; nunca calcula skill.**", "",
        f"## Resultado: {metadata['poc_status']}", "",
        f"- Localização: {metadata['localizacao_id']} "
        f"(lat={metadata['localizacao_lat']}, lon={metadata['localizacao_lon']})",
        f"- Comparação: São Bento do Tocantins (lat={metadata['poc_sao_bento_lat']}, "
        f"lon={metadata['poc_sao_bento_lon']}) — coordenadas do POC original, NÃO alteradas",
        f"- Distância entre os dois pontos: {metadata['distancia_ate_poc_sao_bento_km']} km",
        f"- Backend/representação usados: {metadata['backend_used']}/"
        f"{metadata['dataset_representation_used']}",
        f"- RAW: {metadata['n_raw']} registros", "",
        "## Checklist (mesmos guardrails do POC original, sem modificação)", ""]
    for k, v in metadata['checklist'].items():
        linhas.append(f"- `{k}`: {v}")
    linhas += ["", "## Separação de dados",
               "",
               f"Este POC escreve exclusivamente em "
               f"`{metadata['dataset_separado_de_sao_bento']}` — nenhum arquivo é "
               f"compartilhado ou concatenado com o RAW de São Bento do Tocantins "
               f"(`artifacts/nmme_poc/`).",
               "",
               "## Status de validação",
               "",
               f"`localizacao_validada={metadata['localizacao_validada']}` — esta localização "
               "NUNCA é tratada como validada automaticamente, mesmo com "
               f"`poc_status={metadata['poc_status']}`. Uma eventual promoção "
               "(ex.: usar este ponto no lugar de São Bento do Tocantins na extração "
               "histórica) exige decisão explícita separada, não tomada por este script."]
    return '\n'.join(linhas) + '\n'


def escrever_saidas_espacial(resultado, aprovacao):
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    raw_df = resultado.get('raw_df', pd.DataFrame())
    temporal_df = resultado.get('temporal_audit_df', pd.DataFrame())
    access_df = resultado.get('access_audit_df', pd.DataFrame())
    raw_df.to_csv(ARTIFACTS_DIR / 'poc_espacial_fazendas_raw.csv', index=False)
    temporal_df.to_csv(ARTIFACTS_DIR / 'poc_espacial_fazendas_temporal_audit.csv', index=False)
    access_df.to_csv(ARTIFACTS_DIR / 'poc_espacial_fazendas_access_audit.csv', index=False)

    metadata = montar_metadata_espacial(resultado, aprovacao)
    (ARTIFACTS_DIR / 'metadata.json').write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=str))
    relatorio = gerar_relatorio_espacial_markdown(resultado, metadata)
    (ARTIFACTS_DIR / 'RELATORIO.md').write_text(relatorio)

    for nome in ('poc_espacial_fazendas_raw.csv', 'poc_espacial_fazendas_temporal_audit.csv',
                  'poc_espacial_fazendas_access_audit.csv', 'metadata.json', 'RELATORIO.md'):
        print(f"  ✅ artifacts/nmme_poc_espacial_fazendas/{nome}")
    return metadata, relatorio


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def imprimir_plano():
    from _c3s_utils import MUNICIPIOS
    sao_bento = MUNICIPIOS[npoc.MUNICIPIO]
    dist_km = pilo.nproc.distancia_km_aprox(FAZENDAS_LAT, FAZENDAS_LON,
                                               sao_bento['lat'], sao_bento['lon'])
    print("=== NMME POC Espacial — Centroide das Fazendas (Fase 2C.2) — DRY RUN PLAN "
          "(nenhum acesso à rede NMME) ===")
    print(f"  localizacao_id: {LOCALIZACAO_ID}")
    print(f"  localizacao_lat_lon: ({FAZENDAS_LAT}, {FAZENDAS_LON})")
    print(f"  poc_sao_bento_lat_lon: ({sao_bento['lat']}, {sao_bento['lon']}) — NÃO alterado")
    print(f"  distancia_km: {round(dist_km, 1)}")
    print(f"  origem: {npoc._origem_str(*npoc.POC_ORIGEM)} (mesma origem já validada do POC de São Bento)")
    print(f"  leads: {list(npoc.LEADS)}")
    print("  representacao_esperada: NMME_HARMONIZED_MONTHLY (mesma rota EMPIRICALLY_CONFIRMED)")
    print("  localizacao_validada_apos_esta_execucao: False (nunca automático — Seção 2 da tarefa)")
    print("  armazenamento: artifacts/nmme_poc_espacial_fazendas/ "
          "(separado de artifacts/nmme_poc/, nunca compartilhado)")
    print("\n✅ Plano do POC espacial gerado (infraestrutura só — nenhum download real).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run-plan', action='store_true',
                     help='Nunca acessa a rede NMME — só mostra o plano do POC espacial.')
    ap.add_argument('--executar-poc-real', action='store_true',
                     help='Roda o POC real no centroide das fazendas — acessa a rede de verdade.')
    args = ap.parse_args()

    if args.executar_poc_real:
        imprimir_plano()
        resultado, aprovacao = executar_poc_espacial_fazendas()
        escrever_saidas_espacial(resultado, aprovacao)
        print(f"\npoc_status={resultado['poc_status']}")
        for k, v in resultado.get('checklist', {}).items():
            print(f"  - {k}: {v}")
        if resultado['poc_status'] != 'APROVADO':
            raise SystemExit(f"POC espacial REPROVADO — ver "
                              f"artifacts/nmme_poc_espacial_fazendas/RELATORIO.md para o motivo.")
        print("\n✅ POC espacial (centroide das fazendas) APROVADO — ver "
              "artifacts/nmme_poc_espacial_fazendas/RELATORIO.md")
        print("⚠️  Localização NÃO promovida automaticamente — localizacao_validada=False "
              "(decisão explícita separada necessária).")
        return

    imprimir_plano()


if __name__ == '__main__':
    main()
