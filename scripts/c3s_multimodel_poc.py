#!/usr/bin/env python3
"""
c3s_multimodel_poc.py — Fase 2B.1: POC real pequeno da infraestrutura
multi-modelo (download/parsing/normalização), reaproveitando a
infraestrutura já validada nas Fases 2A/2A.3/2A.3-correções. NÃO é
avaliação de skill (Seção 15) — o objetivo é só provar que download,
schemas, membros, unidade, mapeamento temporal, grade e combinação
multi-modelo funcionam para os 4 sistemas candidatos.

ARQUITETURA — reaproveita, não duplica:
  - c3s_download.py::montar_request_hindcast/baixar — já parametrizado
    por (centre, system), nenhuma mudança necessária.
  - c3s_validacao_multiorigem.py::_baixar_com_retry_e_cache — já agnóstico
    de modelo (recebe o request pronto).
  - c3s_poc.py::abrir_e_validar_grib — já valida schema temporal (Seção 16:
    fcmonth/step/valid_time/nominal start/target month, cross-checado
    contra leadtime_para_mes_alvo — falha explícita se algum sistema
    tiver semântica diferente) e unidade (contra UNIDADES_TPRATE_ACEITAS)
    sem assumir nº de membros — a barreira de membros específica por
    modelo (Seção 17) é adicionada aqui, não lá.
  - c3s_processar.py::extrair_ponto/dataset_para_tabela — já
    parametrizados por (centre, system) como rótulos, não hardcoded.
  - c3s_hindcast.py::estatisticas_ensemble/probabilidade_terciles —
    reaproveitados sem alteração.
  - c3s_calibracao.py::climatologia_leakage_safe/bias_leakage_safe —
    mesma metodologia CONGELADA da Fase 2A.3 (Seção 5/6), sem alteração.
  - c3s_hindcast_completo.py::intervalo_targets_necessario/
    buscar_chirps_consolidado — mesma cobertura observacional CHIRPS
    corrigida na Fase 2A.3 (Seção 7), reaproveitada sem reimplementar.
  - c3s_multimodel_catalogo.py — metadados/período comum dos sistemas.
  - c3s_multimodel.py — combinação MME por equal-model-weighting.

NÃO EXECUTAR décadas aqui (Seção 14): POC pequeno, 6 origens fixas ×
todos os modelos incluídos × leads 1-6. NÃO é avaliação de skill (Seção
15) — dados insuficientes para BC/climatologia na maioria das origens do
POC, isso é esperado e não deve ser preenchido artificialmente.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import c3s_download as dl  # noqa: E402
import c3s_processar as proc  # noqa: E402
import c3s_hindcast as hc  # noqa: E402
import c3s_poc as poc  # noqa: E402
import c3s_calibracao as calib  # noqa: E402
import c3s_multimodel as mm  # noqa: E402
import c3s_multimodel_catalogo as mcat  # noqa: E402
from c3s_validacao_multiorigem import _baixar_com_retry_e_cache  # noqa: E402
from c3s_hindcast_completo import intervalo_targets_necessario, buscar_chirps_consolidado  # noqa: E402
from _c3s_utils import MUNICIPIOS, leadtime_para_mes_alvo  # noqa: E402

ROOT = Path(__file__).parent.parent
ARTIFACTS_DIR = ROOT / 'artifacts' / 'c3s_multimodel_poc'

MUNICIPIO = 'Sao_Bento_do_Tocantins'
LEADS = [1, 2, 3, 4, 5, 6]
MIN_ANOS_TREINO = calib.MIN_ANOS_TREINO

# Seção 14/15 — POC pequeno, propósito é provar pipeline, não skill.
POC_ORIGENS = [(1995, 1), (1995, 7), (2005, 1), (2005, 7), (2015, 1), (2015, 7)]

ARTIFACT_FILENAMES = [
    'c3s_multimodel_catalog.csv', 'c3s_multimodel_common_period.json',
    'c3s_multimodel_raw.csv', 'c3s_multimodel_summary.csv', 'c3s_multimodel_mme.csv',
    'c3s_multimodel_temporal_audit.csv', 'metadata.json', 'RELATORIO.md',
]


def _origem_str(ano, mes):
    return f'{ano:04d}-{mes:02d}'


# ══════════════════════════════════════════════════════════════════════════
# Download + validação de 1 origem × 1 modelo — barreiras A-H (mesmo
# desenho de c3s_hindcast_completo.py::processar_origem_raw), mas com
# nº de membros esperado ESPECÍFICO por modelo (Seção 17 — nunca
# assumir 25) e registro explícito de unidade/conversão/grade
# (Seções 18/19/22).
# ══════════════════════════════════════════════════════════════════════════

def processar_origem_modelo(sistema, ano, mes, sleep_fn=time.sleep):
    origem = _origem_str(ano, mes)
    init_date = pd.Period(f'{ano}-{mes:02d}', 'M')
    info = MUNICIPIOS[MUNICIPIO]
    lat, lon = info['lat'], info['lon']

    area = [lat + poc.AREA_BUFFER_GRAUS, lon - poc.AREA_BUFFER_GRAUS,
            lat - poc.AREA_BUFFER_GRAUS, lon + poc.AREA_BUFFER_GRAUS]
    request = dl.montar_request_hindcast((sistema.originating_centre_cds, sistema.system_code),
                                          ano, mes, area, LEADS)

    caminho, cache_hit, retries = _baixar_com_retry_e_cache(request, sleep_fn=sleep_fn)

    # Seção 16 — abrir_e_validar_grib já prova fcmonth/step/valid_time/
    # nominal_start/target_month via extrair_mapeamento_temporal_grib
    # (eccodes, arquivo inteiro) e falha explicitamente (RuntimeError)
    # se a convenção "lead 1 = mês de inicialização" não bater — sem
    # ajuste silencioso, para QUALQUER sistema.
    ds, unidade, esquema, mapa_lead_alvo, diag_info, mapeamento_step_fcmonth = \
        poc.abrir_e_validar_grib(caminho, LEADS)

    # Seção 17 — nº de membros esperado é ESPECÍFICO do modelo, nunca 25 fixo.
    n_membros = int(ds.sizes['number'])
    if sistema.hindcast_members is not None and n_membros != sistema.hindcast_members:
        raise RuntimeError(f"[{sistema.centro}/{sistema.system_name} {origem}] número de membros = "
                            f"{n_membros}, esperado {sistema.hindcast_members} (barreira A, "
                            f"expected_hindcast_members por modelo — Seção 17).")

    leads_encontrados = sorted(mapa_lead_alvo)
    if leads_encontrados != LEADS:
        raise RuntimeError(f"[{sistema.centro}/{sistema.system_name} {origem}] leads encontrados "
                            f"{leads_encontrados} != esperados {LEADS} (barreira B).")

    alvos = [pd.Period(v, 'M') for v in mapa_lead_alvo.values()]
    if len(set(alvos)) != len(LEADS):
        raise RuntimeError(f"[{sistema.centro}/{sistema.system_name} {origem}] target months não são "
                            f"{len(LEADS)} distintos: {sorted(alvos)} (barreira C).")

    for lead, alvo_str in mapa_lead_alvo.items():
        esperado = leadtime_para_mes_alvo(init_date, lead)
        if pd.Period(alvo_str, 'M') != esperado:
            raise RuntimeError(f"[{sistema.centro}/{sistema.system_name} {origem}] lead {lead}: "
                                f"target_month {alvo_str} != esperado {esperado} (barreira D — "
                                f"'lead 1 = mês nominal da inicialização' não bateu para este sistema).")

    # Seção 18 — unidade validada por metadata (poc.abrir_e_validar_grib
    # já valida contra UNIDADES_TPRATE_ACEITAS e falha se 'tprate'
    # ausente; aqui só REGISTRAMOS a unidade original e a conversão
    # aplicada, nunca assumindo pelo nome da variável sozinho).
    unidades_equivalentes = {'m s**-1', 'm s-1', 'm/s'}
    if unidade not in unidades_equivalentes:
        raise RuntimeError(f"[{sistema.centro}/{sistema.system_name} {origem}] unidade tprate "
                            f"{unidade!r} fora do conjunto aceito {unidades_equivalentes} — FALHANDO "
                            f"(barreira E) em vez de assumir a conversão.")
    conversao_aplicada = 'tprate_m_s_para_mm_mes (x segundos_no_mes)'

    ponto = proc.extrair_ponto(ds, lat, lon)
    lat_grade, lon_grade = float(ponto['latitude']), float(ponto['longitude'])
    dist_km = poc.distancia_km_aprox(lat, lon, lat_grade, lon_grade)

    tabela = proc.dataset_para_tabela(ponto, local=MUNICIPIO, centre=sistema.centro,
                                       system=sistema.system_name,
                                       mapeamento_step_fcmonth=mapeamento_step_fcmonth)
    tabela = tabela.rename(columns={'forecast_prec_mm': 'c3s_prec_mm'})

    valores = tabela['c3s_prec_mm'].to_numpy(dtype=float)
    if not np.all(np.isfinite(valores)):
        raise RuntimeError(f"[{sistema.centro}/{sistema.system_name} {origem}] c3s_prec_mm contém "
                            f"NaN/infinito (barreira F).")
    if (valores < 0).any():
        raise RuntimeError(f"[{sistema.centro}/{sistema.system_name} {origem}] c3s_prec_mm contém "
                            f"precipitação negativa (barreira F).")

    fora = valores[(valores < poc.PREC_MM_MIN_PLAUSIVEL) | (valores > poc.PREC_MM_MAX_PLAUSIVEL)]
    if len(fora):
        raise RuntimeError(f"[{sistema.centro}/{sistema.system_name} {origem}] {len(fora)} valor(es) "
                            f"fora de [{poc.PREC_MM_MIN_PLAUSIVEL},{poc.PREC_MM_MAX_PLAUSIVEL}]mm "
                            f"(barreira G).")

    if len(tabela) != n_membros * len(LEADS):
        raise RuntimeError(f"[{sistema.centro}/{sistema.system_name} {origem}] {len(tabela)} linhas "
                            f"raw, esperado {n_membros * len(LEADS)} (barreira H).")

    # Seção 22 — colunas mínimas do raw.csv, além das já produzidas por dataset_para_tabela.
    tabela['system_code'] = sistema.system_code
    tabela = tabela.rename(columns={'system': 'system_name'})
    tabela['requested_lat'] = lat
    tabela['requested_lon'] = lon
    tabela['selected_lat'] = lat_grade
    tabela['selected_lon'] = lon_grade
    tabela['grid_distance_km'] = round(dist_km, 2)
    tabela['units_original'] = unidade
    tabela['conversion_applied'] = conversao_aplicada

    # Seção 16 — auditoria temporal: 1 linha por lead, com o mapeamento
    # já provado por extrair_mapeamento_temporal_grib (ou, no esquema
    # lead-pronto, pela própria checagem acima).
    linhas_temporais = []
    for lead in LEADS:
        target_month = pd.Period(mapa_lead_alvo[lead], 'M')
        entrada = None
        if mapeamento_step_fcmonth:
            entrada = next((e for e in mapeamento_step_fcmonth.values() if e['lead'] == lead), None)
        linhas_temporais.append({
            'centre': sistema.centro, 'system_name': sistema.system_name, 'init_date': str(init_date),
            'lead': lead, 'esquema_temporal': esquema,
            'fcmonth': entrada['fcmonth'] if entrada else lead,
            'target_month': str(target_month),
            'nominal_start_date': str(init_date),
            'lead1_e_mes_nominal_da_inicializacao': True,
        })
    temporal_audit = pd.DataFrame(linhas_temporais)

    metadata_origem = {
        'cache_hit': bool(cache_hit), 'retries': int(retries), 'n_membros': n_membros,
        'lat_grade': lat_grade, 'lon_grade': lon_grade, 'distancia_grade_km': round(dist_km, 2),
        'unidade': unidade, 'esquema_temporal': esquema,
    }
    return tabela, temporal_audit, metadata_origem


# ══════════════════════════════════════════════════════════════════════════
# Summary por modelo × origem × lead (Seção 23) — ensemble mean RAW
# sempre; BC só se houver histórico suficiente carregado NESTE POC
# (nunca buscar décadas só para preencher BC, Seção 23/24).
# ══════════════════════════════════════════════════════════════════════════

def construir_summary_modelo(raw_df, chirps_df, min_anos_treino=MIN_ANOS_TREINO):
    """raw_df: já com init_date/target_month como Period, 1 linha por
    (centre, system_name, init_date, lead, member). Uma linha de saída
    por (centre, system_name, init_date, lead)."""
    if raw_df.empty:
        return pd.DataFrame()
    chirps_por_target = chirps_df[['target_month', 'chirps_prec_mm']].drop_duplicates('target_month')

    linhas = []
    chaves = ['centre', 'system_name', 'system_code', 'init_date', 'lead']
    for chave, g in raw_df.groupby(chaves):
        centre, system_name, system_code, init_date, lead = chave
        v = g['c3s_prec_mm'].to_numpy(dtype=float)
        est = hc.estatisticas_ensemble(v)
        target_month = g['target_month'].iloc[0]
        mes_cal = target_month.month

        clim = calib.climatologia_leakage_safe(chirps_por_target, init_date, mes_cal, min_anos_treino)

        # Bias leakage-safe exige histórico de origens ANTERIORES do
        # MESMO modelo/lead/mês — no POC (6 origens isoladas, sem
        # histórico prévio carregado) isso normalmente não existe;
        # SEM_HISTORICO_SUFICIENTE aqui é o resultado ESPERADO, não um
        # bug (Seção 23: "não inventar... pode ser NaN/
        # SEM_HISTORICO_SUFICIENTE").
        ens_deste_modelo = raw_df[(raw_df['centre'] == centre) & (raw_df['system_name'] == system_name) &
                                   (raw_df['lead'] == lead)].groupby('init_date')['c3s_prec_mm'].mean()
        ens_df_modelo = pd.DataFrame({'init_date': ens_deste_modelo.index,
                                       'target_month': [i + (lead - 1) for i in ens_deste_modelo.index],
                                       'lead': lead, 'ens_mean_raw': ens_deste_modelo.values})
        bias = calib.bias_leakage_safe(ens_df_modelo, chirps_por_target, init_date, mes_cal, lead,
                                        min_anos_treino)

        chirps_obs = chirps_por_target[chirps_por_target['target_month'] == target_month]
        chirps_mm = float(chirps_obs['chirps_prec_mm'].iloc[0]) if not chirps_obs.empty else None

        ens_mean_bc = (round(est['mean'] - bias['bias_mm'], 3) if bias['bias_mm'] is not None else None)

        p33, p67 = clim.get('p33'), clim.get('p67')
        if p33 is not None and p67 is not None:
            pb_raw, pn_raw, pa_raw = hc.probabilidade_terciles(v, p33, p67)
        else:
            pb_raw = pn_raw = pa_raw = None
        if ens_mean_bc is not None and p33 is not None and p67 is not None:
            bc_vals = np.array([calib.aplicar_bias_a_membro(x, bias['bias_mm']) for x in v])
            pb_bc, pn_bc, pa_bc = hc.probabilidade_terciles(bc_vals, p33, p67)
        else:
            pb_bc = pn_bc = pa_bc = None

        linhas.append({
            'centre': centre, 'system_name': system_name, 'system_code': system_code,
            'init_date': init_date, 'target_month': target_month, 'lead': lead,
            'n_members': len(v), 'ens_mean_raw': est['mean'], 'ens_median_raw': est['median'],
            'ens_sd_raw': float(np.std(v)), 'chirps_prec_mm': chirps_mm,
            'clim_n': clim['n'], 'bias_training_n': bias['n'], 'bias_mm': bias['bias_mm'],
            'ens_mean_bc': ens_mean_bc,
            'prob_below_raw': pb_raw, 'prob_normal_raw': pn_raw, 'prob_above_raw': pa_raw,
            'prob_below_bc': pb_bc, 'prob_normal_bc': pn_bc, 'prob_above_bc': pa_bc,
        })
    return pd.DataFrame(linhas).sort_values(['init_date', 'lead', 'centre']).reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════
# Plano / dry-run — nunca acessa o CDS.
# ══════════════════════════════════════════════════════════════════════════

def plano_poc(sistemas=None, origens=None):
    sistemas = sistemas if sistemas is not None else mcat.CATALOGO
    origens = origens if origens is not None else POC_ORIGENS
    n_modelos = len(sistemas)
    n_origens = len(origens)
    common = mcat.periodo_comum_hindcast(sistemas)
    return {
        'origens': [_origem_str(a, m) for a, m in origens], 'n_origens': n_origens,
        'modelos': [f'{s.centro}/{s.system_name}' for s in sistemas], 'n_modelos': n_modelos,
        'leads': LEADS,
        'requests_cds_previstos': n_origens * n_modelos,
        'raw_rows_esperadas_por_modelo': {
            f'{s.centro}': (s.hindcast_members * len(LEADS) * n_origens) if s.hindcast_members else None
            for s in sistemas},
        'periodo_comum_hindcast': f"{common['common_start']}-{common['common_end']}",
        'variantes_comparacao': mm.variantes_comparacao(sistemas),
        'municipio': MUNICIPIO, 'artifacts_esperados': ARTIFACT_FILENAMES,
        'aviso': 'POC — não é avaliação de skill. Só valida pipeline (download/schema/membros/unidade/'
                 'mapeamento temporal/grade/combinação multi-modelo).',
    }


def imprimir_plano(plano):
    print("=== C3S Multi-Modelo POC — DRY RUN PLAN (nenhum acesso ao CDS) ===")
    for chave, valor in plano.items():
        print(f"  {chave}: {valor}")


# ══════════════════════════════════════════════════════════════════════════
# Orquestração do POC real.
# ══════════════════════════════════════════════════════════════════════════

def rodar_poc(sistemas=None, origens=None, sleep_fn=time.sleep, persistir_intermediarios=True):
    """`persistir_intermediarios` (correção pós-run real 35437819463,
    Seção 12): grava raw.csv e temporal_audit.csv assim que estão
    prontos — ANTES de buscar CHIRPS e construir summary/MME. No run
    real que motivou esta correção, o download dos 4 sistemas x 6
    origens funcionou por completo, mas o crash em mme_probabilistico
    (Seção 1) aconteceu depois disso, antes de qualquer escrever_saidas
    — só os 2 artifacts de catálogo (que não dependem do CDS) foram
    publicados, e os dados reais baixados foram perdidos. Nunca grava
    GRIB aqui — só os CSVs já tabulares."""
    sistemas = sistemas if sistemas is not None else mcat.CATALOGO
    origens = origens if origens is not None else POC_ORIGENS

    raws, temporais, falhas, metadados = [], [], {}, {}
    for sistema in sistemas:
        for ano, mes in origens:
            chave = f'{sistema.centro}/{sistema.system_name}/{_origem_str(ano, mes)}'
            print(f"\n=== {chave} ===")
            try:
                tabela, temporal_audit, meta = processar_origem_modelo(sistema, ano, mes, sleep_fn=sleep_fn)
            except Exception as e:
                print(f"  ❌ FALHOU: {e}")
                falhas[chave] = str(e)
                continue
            raws.append(tabela)
            temporais.append(temporal_audit)
            metadados[chave] = meta
            print(f"  ✅ {chave}: {len(tabela)} linhas raw")

    raw_df_str = pd.concat(raws, ignore_index=True) if raws else pd.DataFrame()
    raw_df = raw_df_str.copy()
    if not raw_df.empty:
        raw_df['init_date'] = raw_df['init_date'].apply(lambda s: pd.Period(s, 'M'))
        raw_df['target_month'] = raw_df['target_month'].apply(lambda s: pd.Period(s, 'M'))
    temporal_audit_df = pd.concat(temporais, ignore_index=True) if temporais else pd.DataFrame()

    if persistir_intermediarios:
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        raw_df_str.to_csv(ARTIFACTS_DIR / 'c3s_multimodel_raw.csv', index=False)
        temporal_audit_df.to_csv(ARTIFACTS_DIR / 'c3s_multimodel_temporal_audit.csv', index=False)
        print(f"\n  💾 intermediários persistidos ({len(raw_df_str)} linhas raw, "
              f"{len(temporal_audit_df)} linhas temporal_audit) — antes de CHIRPS/summary/MME "
              f"(Seção 12: sobrevive a uma falha nas etapas seguintes).")

    # Seção 11 — revisado (não implementado): buscar_chirps_consolidado já
    # busca em blocos ANUAIS (não mês a mês) e só o intervalo estritamente
    # necessário (intervalo_targets_necessario, derivado das origens/leads
    # pedidos) — para as 6 origens fixas do POC isso já é o mínimo de
    # chamadas sem introduzir cache persistente entre execuções (fora de
    # escopo desta correção; prioridade aqui foi a lógica NaN, Seção 3-5).
    target_ini, target_fim = intervalo_targets_necessario(origens, LEADS)
    print(f"\n=== buscando CHIRPS consolidado ({target_ini} a {target_fim}, em blocos anuais) ===")
    chirps_df = buscar_chirps_consolidado(target_ini, target_fim, sleep_fn=sleep_fn)
    print(f"  ✅ CHIRPS: {len(chirps_df)} meses válidos")

    summary_df = construir_summary_modelo(raw_df, chirps_df) if not raw_df.empty else pd.DataFrame()
    modelos_configurados = [s.centro for s in sistemas]
    mme_df = mm.construir_mme_por_origem_lead(summary_df, modelos_configurados) if not summary_df.empty \
        else pd.DataFrame()

    return {
        'raw_df': raw_df_str, 'summary_df': summary_df, 'mme_df': mme_df,
        'temporal_audit_df': temporal_audit_df, 'chirps_df': chirps_df,
        'falhas': falhas, 'metadados': metadados, 'sistemas': sistemas, 'origens': origens,
    }


def montar_metadata(resultado):
    r = resultado
    mme_df = r['mme_df']
    disponibilidade = None
    if not mme_df.empty and 'raw_available' in mme_df.columns:
        n = len(mme_df)
        disponibilidade = {
            'raw_available': f"{int(mme_df['raw_available'].sum())}/{n}",
            'bc_available': f"{int(mme_df['bc_available'].sum())}/{n}",
            'raw_prob_available': f"{int(mme_df['raw_prob_available'].sum())}/{n}",
            'bc_prob_available': f"{int(mme_df['bc_prob_available'].sum())}/{n}",
            'model_set_status_ok': f"{int((mme_df['model_set_status'] == mm.MODELO_COMPLETO_STATUS).sum())}/{n}",
        }
    return {
        'data_execucao': datetime.now(timezone.utc).isoformat(),
        'fase': '2B.1 — POC multi-modelo (infraestrutura, não avaliação de skill)',
        'municipio': MUNICIPIO, 'leads': LEADS,
        'modelos_incluidos': [f'{s.centro}/{s.system_name}' for s in r['sistemas']],
        'origens_pedidas': [f'{a:04d}-{m:02d}' for a, m in r['origens']],
        'n_falhas': len(r['falhas']), 'falhas': r['falhas'],
        'n_linhas_raw': len(r['raw_df']), 'n_linhas_summary': len(r['summary_df']),
        'n_linhas_mme': len(r['mme_df']),
        'n_meses_chirps': len(r['chirps_df']),
        # Disponibilidade por combinação origem×lead (Seção 7/9, correção pós-run real
        # 35437819463) — BC/probabilidades indisponíveis por falta de histórico são
        # ESPERADAS no POC e não bloqueiam a aprovação (Seção 13); RAW/model_set_status
        # disponíveis em 36/36 é que é obrigatório.
        'disponibilidade_mme': disponibilidade,
        'nota': 'Resultado NÃO é conclusão científica — POC de infraestrutura (Seção 15/34). Nenhum '
                'resultado desta fase deve entrar no dashboard operacional (Seção 34). BC/probabilidades '
                'indisponíveis por falta de histórico leakage-safe são esperadas neste POC (Seção 2/23) — '
                'não indicam falha.',
    }


def gerar_relatorio_markdown(resultado):
    r = resultado
    linhas = ["# POC Multi-Modelo C3S — Fase 2B.1", "",
              "**Este resultado NÃO é uma conclusão científica** — é um POC de infraestrutura "
              "(download/schema/membros/unidade/mapeamento temporal/grade/combinação multi-modelo).", "",
              f"- Modelos incluídos: {', '.join(f'{s.centro}/{s.system_name}' for s in r['sistemas'])}",
              f"- Origens: {', '.join(f'{a:04d}-{m:02d}' for a, m in r['origens'])}",
              f"- Linhas raw: {len(r['raw_df'])}", f"- Linhas summary: {len(r['summary_df'])}",
              f"- Linhas MME: {len(r['mme_df'])}", f"- Meses CHIRPS: {len(r['chirps_df'])}"]
    if r['falhas']:
        linhas += ["", "## Falhas", ""] + [f"- **{k}**: {v}" for k, v in r['falhas'].items()]
    if not r['mme_df'].empty and 'model_set_status' in r['mme_df'].columns:
        mme_df = r['mme_df']
        n = len(mme_df)
        incompletos = (mme_df['model_set_status'] == mm.MODELO_AUSENTE_STATUS).sum()
        linhas += ["", f"- Combinações origem×lead com INCOMPLETE_MODEL_SET: {incompletos}/{n}", "",
                   "## Disponibilidade por combinação origem×lead", "",
                   "BC e probabilidades indisponíveis por falta de histórico leakage-safe são "
                   "ESPERADAS neste POC (Seção 2/23) — não são falha, e não bloqueiam a aprovação "
                   "(Seção 13). `model_set_status=OK` é independente de BC estar disponível "
                   "(Seção 6).", "",
                   f"- RAW disponível: {int(mme_df['raw_available'].sum())}/{n}",
                   f"- BC disponível: {int(mme_df['bc_available'].sum())}/{n}",
                   f"- Probabilidades RAW disponíveis: {int(mme_df['raw_prob_available'].sum())}/{n}",
                   f"- Probabilidades BC disponíveis: {int(mme_df['bc_prob_available'].sum())}/{n}",
                   f"- model_set_status=OK: "
                   f"{int((mme_df['model_set_status'] == mm.MODELO_COMPLETO_STATUS).sum())}/{n}"]
        com_raw_error = mme_df[mme_df['raw_error'].notna()]
        if not com_raw_error.empty:
            linhas += ["", "### RAW com erro (inconsistência real do pipeline, nunca falta de "
                            "histórico — Seção 5/8-H)", ""]
            linhas += [f"- {row['init_date']} lead {row['lead']}: {row['raw_error']}"
                       for _, row in com_raw_error.iterrows()]
    linhas += ["", "---", "", "Nenhum resultado desta fase deve entrar no dashboard operacional (Seção 34)."]
    return '\n'.join(linhas) + '\n'


def validar_poc_aprovado(resultado, sistemas=None, origens=None):
    """Seção 13 (correção pós-run real 35437819463) — fail-fast final do
    POC, mesmo formato (aprovado: bool, motivos: list[str]) de
    validar_pilot_aprovado/validar_full_aprovado em
    c3s_hindcast_completo.py. Só aprova se:
      - 4 sistemas configurados;
      - 6/6 origens sem falha de download, por sistema;
      - nº de membros bate com o esperado por sistema (nunca 25 fixo);
      - leads 1-6 presentes no raw;
      - zero falhas de download;
      - temporal_audit com a contagem esperada e
        lead1_e_mes_nominal_da_inicializacao=True em 100% das linhas;
      - RAW disponível (raw_available=True, sem raw_error) em 100% das
        combinações origem×lead;
      - MME RAW presente (mme_df com a contagem esperada) em 36/36
        combinações;
      - model_set_status=OK em 36/36 combinações.

    NÃO exige (Seção 13): BC disponível, probabilidades RAW/BC
    disponíveis — indisponíveis por falta de histórico é esperado neste
    POC (Seção 2/23) — nem calcula skill (este POC nunca avalia skill,
    Seção 15)."""
    r = resultado
    sistemas = sistemas if sistemas is not None else r['sistemas']
    origens = origens if origens is not None else r['origens']
    motivos = []

    if len(sistemas) != 4:
        motivos.append(f"esperados 4 sistemas configurados, catálogo tem {len(sistemas)}")

    if r['falhas']:
        motivos.append(f"{len(r['falhas'])} falha(s) de download: {sorted(r['falhas'].keys())}")

    n_origens = len(origens)
    for sistema in sistemas:
        prefixo = f'{sistema.centro}/{sistema.system_name}/'
        chaves_sistema = [f'{prefixo}{_origem_str(a, m)}' for a, m in origens]
        n_ok = sum(1 for c in chaves_sistema if c not in r['falhas'])
        if n_ok != n_origens:
            motivos.append(f"{sistema.centro}/{sistema.system_name}: {n_ok}/{n_origens} origens ok")

        if sistema.hindcast_members is not None:
            for chave in chaves_sistema:
                meta = r['metadados'].get(chave)
                if meta is not None and meta['n_membros'] != sistema.hindcast_members:
                    motivos.append(f"{chave}: n_membros={meta['n_membros']}, "
                                    f"esperado {sistema.hindcast_members}")

    raw_df = r['raw_df']
    if raw_df.empty and not r['falhas']:
        motivos.append("raw_df vazio sem nenhuma falha registrada — inconsistência")
    elif not raw_df.empty:
        leads_encontrados = sorted(raw_df['lead'].unique())
        if leads_encontrados != LEADS:
            motivos.append(f"leads no raw {leads_encontrados} != esperados {LEADS}")

    temporal_audit_df = r['temporal_audit_df']
    n_temporal_esperado = len(sistemas) * n_origens * len(LEADS)
    if len(temporal_audit_df) != n_temporal_esperado:
        motivos.append(f"temporal_audit tem {len(temporal_audit_df)} linhas, "
                        f"esperado {n_temporal_esperado} (sistemas x origens x leads)")
    elif not temporal_audit_df.empty and \
            not temporal_audit_df['lead1_e_mes_nominal_da_inicializacao'].all():
        motivos.append("alguma linha do temporal_audit tem lead1_e_mes_nominal_da_inicializacao=False")

    mme_df = r['mme_df']
    n_mme_esperado = n_origens * len(LEADS)
    if len(mme_df) != n_mme_esperado:
        motivos.append(f"mme_df tem {len(mme_df)} linhas, esperado {n_mme_esperado} (origens x leads)")
    elif not mme_df.empty:
        if not mme_df['raw_available'].all():
            faltando = (~mme_df['raw_available']).sum()
            motivos.append(f"RAW indisponível em {faltando}/{n_mme_esperado} combinações "
                            f"(esperado 100% — modelos já confirmados presentes no POC)")
        com_erro = mme_df[mme_df['raw_error'].notna()]
        if not com_erro.empty:
            motivos.append(f"raw_error presente em {len(com_erro)}/{n_mme_esperado} combinações")
        n_status_ok = (mme_df['model_set_status'] == mm.MODELO_COMPLETO_STATUS).sum()
        if n_status_ok != n_mme_esperado:
            motivos.append(f"model_set_status=OK em {n_status_ok}/{n_mme_esperado}, "
                            f"esperado {n_mme_esperado}")

    return not motivos, motivos


def escrever_saidas(resultado, sistemas=None):
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    sistemas = sistemas if sistemas is not None else mcat.CATALOGO
    r = resultado

    mcat.tabela_catalogo(sistemas).to_csv(ARTIFACTS_DIR / 'c3s_multimodel_catalog.csv', index=False)
    (ARTIFACTS_DIR / 'c3s_multimodel_common_period.json').write_text(
        json.dumps(mcat.common_period_json(sistemas), indent=2, ensure_ascii=False, default=str))

    r['raw_df'].to_csv(ARTIFACTS_DIR / 'c3s_multimodel_raw.csv', index=False)
    r['summary_df'].to_csv(ARTIFACTS_DIR / 'c3s_multimodel_summary.csv', index=False)
    r['mme_df'].to_csv(ARTIFACTS_DIR / 'c3s_multimodel_mme.csv', index=False)
    r['temporal_audit_df'].to_csv(ARTIFACTS_DIR / 'c3s_multimodel_temporal_audit.csv', index=False)

    metadata = montar_metadata(r)
    (ARTIFACTS_DIR / 'metadata.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False, default=str))
    relatorio = gerar_relatorio_markdown(r)
    (ARTIFACTS_DIR / 'RELATORIO.md').write_text(relatorio)

    for nome in ARTIFACT_FILENAMES:
        print(f"  ✅ artifacts/c3s_multimodel_poc/{nome}")
    return metadata, relatorio


def escrever_catalogo_apenas(sistemas=None):
    """Usado pelo dry-run — catálogo/período comum não dependem do CDS,
    então podem ser gerados mesmo sem acesso real (Seção 31)."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    sistemas = sistemas if sistemas is not None else mcat.CATALOGO
    mcat.tabela_catalogo(sistemas).to_csv(ARTIFACTS_DIR / 'c3s_multimodel_catalog.csv', index=False)
    (ARTIFACTS_DIR / 'c3s_multimodel_common_period.json').write_text(
        json.dumps(mcat.common_period_json(sistemas), indent=2, ensure_ascii=False, default=str))


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run-plan', action='store_true',
                     help='Não acessa o CDS — só mostra catálogo/período comum/plano do POC.')
    ap.add_argument('--executar-poc-real', action='store_true',
                     help='Roda o POC real (6 origens fixas x modelos incluídos) — acessa o CDS.')
    args = ap.parse_args()

    if args.dry_run_plan or not args.executar_poc_real:
        escrever_catalogo_apenas()
        imprimir_plano(plano_poc())
        return

    status = dl.verificar_acesso(verbose=True)
    if not status['credenciais_configuradas']:
        raise SystemExit("CDS_API_KEY não configurado — FALHANDO. Nunca simulando resultado real.")
    if not status['pacote_cdsapi_instalado']:
        raise SystemExit("pacote cdsapi não instalado — rode `pip install -r requirements-c3s.txt`.")

    print(f"=== C3S Multi-Modelo POC — {len(POC_ORIGENS)} origens x {len(mcat.CATALOGO)} modelos ===")
    resultado = rodar_poc()
    escrever_saidas(resultado)

    aprovado, motivos = validar_poc_aprovado(resultado)
    if not aprovado:
        print("\n❌ POC REPROVADO — artifacts gravados para diagnóstico (raw/temporal_audit já "
              "persistidos antes do MME, Seção 12); encerrando com erro (correção pós-run real "
              "35437819463, Seção 13 — BC/probabilidades indisponíveis NÃO reprovam o POC, só "
              "download/schema/membros/leads/RAW/model_set_status):")
        for motivo in motivos:
            print(f"  - {motivo}")
        sys.exit(1)
    print("\n✅ POC APROVADO — download/schema/membros/leads/mapeamento temporal/RAW/"
          "model_set_status validados nas 36 combinações origem×lead (6 origens x 6 leads). "
          "BC/probabilidades podem estar indisponíveis por falta de histórico — isso é esperado "
          "e não bloqueia a aprovação (Seção 2/13/23).")
    print("   ver artifacts/c3s_multimodel_poc/RELATORIO.md (NÃO é conclusão científica, Seção 15).")


if __name__ == '__main__':
    main()
