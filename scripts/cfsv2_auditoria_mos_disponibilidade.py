#!/usr/bin/env python3
"""
cfsv2_auditoria_mos_disponibilidade.py — Fase 2C.3D: auditoria causal da
regra de treinamento do Método 3.4 (MOS linear, pooled-by-lead).

Problema auditado: a regra de treino em produção hoje
(`cfsv2_calibracao_mos_linear.construir_tabela_mos_linear`) exige só
`init_date_treino < init_date_avaliada` — a mesma lacuna já encontrada
e corrigida no protocolo EMOS H2 (branch `claude/fase2c3d-emos-h2-
protocolo`): essa condição garante que a PREVISÃO (ensemble_mean) da
linha de treino já existia, mas não garante que sua OBSERVAÇÃO-ALVO
(`target_month = init_date + (lead-1)`) já tinha sido verificada —
para lead>=2, uma linha de treino pode ter `init_date_treino <
init_date_avaliada` e ainda assim `target_month_treino >=
init_date_avaliada`.

Esta atividade é SÓ auditoria — nenhuma métrica do Método 3.4 é
alterada aqui. Recalcula, a partir da MESMA base causal já aprovada
(`cfsv2_validacao_cientifica`), para cada H1-H6 e cada previsão
atualmente elegível (regra antiga), o quanto a regra antiga incluiu
indevidamente, de forma 100% programática — nenhum número desta
auditoria é hardcoded.

Roda com:
    python scripts/cfsv2_auditoria_mos_disponibilidade.py --executar
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import cfsv2_calibracao_mos_linear as mos  # noqa: E402
import cfsv2_validacao_cientifica as v  # noqa: E402

DIRETORIO_SAIDA = ROOT / 'data' / 'cfsv2_calibracao_2c3d'
CAMINHO_AUDITORIA_JSON = DIRETORIO_SAIDA / 'auditoria_disponibilidade_mos_2c3d.json'

N_TREINO_MINIMO_MOS = mos.N_TREINO_MINIMO_MOS

# Expectativa de AUDITORIA (item 3 do pedido) — nunca usada para
# produzir os números abaixo (todos vêm só da base real), só para
# comparar o padrão estrutural observado com o que a aritmética de
# calendário prevê: para lead L, uma linha de treino com
# `target_month_treino = init_date_treino + (L-1)` só vira indevida
# quando `init_date_treino` está nos últimos (L-1) meses-calendário
# antes de `init_date_avaliada` — ou seja, no regime estacionário (sem
# lacunas de par válido), o teto de inclusões indevidas POR AVALIAÇÃO é
# exatamente (L-1).
TETO_ESPERADO_POR_LEAD = {lead: lead - 1 for lead in v.LEADS_ESPERADOS}


def _montar_series_por_lead(base_enriquecida):
    """Reconstrói, por lead, a sequência ordenada de pares (válidos ou
    não) com os campos necessários para comparar as duas regras —
    mesma agregação por membro já usada em
    `cfsv2_calibracao_mos_linear.construir_tabela_mos_linear` (nunca
    uma segunda forma de agregar)."""
    media_membros = base_enriquecida.groupby(
        ['init_date', 'target_month', 'target_ano', 'target_mes', 'lead'], as_index=False
    ).agg(forecast_raw=('forecast_prec_mm', 'mean'),
          observacao=('obs_prec_mm', 'first'),
          climatologia_observada=('clim_media', 'first'),
          climatologia_modelo_raw=('clim_modelo_media', 'first'))

    series = {}
    for lead, grupo in media_membros.groupby('lead'):
        grupo = grupo.assign(_p=pd.PeriodIndex(grupo['init_date'], freq='M')).sort_values('_p')
        linhas = []
        for _, row in grupo.iterrows():
            base = mos._montar_linha_base(row)
            linhas.append({
                'init_date': row['init_date'],
                'init_p': v._periodo(row['init_date']),
                'target_month': row['target_month'],
                'target_p': v._periodo(row['target_month']),
                'par_anomalia_valido': base['par_anomalia_valido'],
            })
        series[int(lead)] = linhas
    return series


def _indices_regra(linhas_validas, avaliada_p, exigir_target_month):
    """Índices (na lista `linhas_validas`, só pares válidos, já em
    ordem causal de init_date) que a regra em questão aceitaria para
    treinar a avaliação em `avaliada_p`."""
    idx = []
    for i, linha in enumerate(linhas_validas):
        if linha['init_p'] >= avaliada_p:
            continue
        if exigir_target_month and linha['target_p'] >= avaliada_p:
            continue
        idx.append(i)
    return idx


def auditar_disponibilidade_observacional_mos():
    """Item 1-3 do pedido — auditoria pura, sem escrever nenhum
    artefato do Método 3.4. Para cada H1-H6, para cada previsão
    atualmente elegível PELA REGRA ANTIGA (n_treino_regra_antiga >=
    120), computa a comparação linha a linha e agrega por horizonte."""
    df_raw = v.carregar_cfsv2_raw()
    chirps_df = v.carregar_chirps_v3_historico()
    base = v.construir_base_pareada(df_raw, chirps_df)
    if not v.validar_nenhum_mes_alvo_ausente(base):
        return {'STOP_ON_FAILURE': True, 'motivo': 'pareamento com mês-alvo ausente'}
    base_enriquecida = v._enriquecer_com_climatologia(base, chirps_df)

    series = _montar_series_por_lead(base_enriquecida)

    detalhe_por_lead = {}
    resumo_por_lead = {}

    for lead, linhas in series.items():
        linhas_validas = [ln for ln in linhas if ln['par_anomalia_valido']]
        registros = []

        for i, linha_avaliada in enumerate(linhas):
            avaliada_p = linha_avaliada['init_p']
            # Candidatos: só pares válidos que não sejam a própria linha —
            # como `linhas_validas` é a lista completa (inclui possivelmente
            # a própria linha se ela for válida), filtramos por init_p
            # estritamente anterior dentro de cada regra abaixo (garante
            # isso estruturalmente, sem depender de índice).
            idx_antiga = _indices_regra(linhas_validas, avaliada_p, exigir_target_month=False)
            idx_corrigida = _indices_regra(linhas_validas, avaliada_p, exigir_target_month=True)

            n_antiga = len(idx_antiga)
            n_corrigida = len(idx_corrigida)

            if n_antiga < N_TREINO_MINIMO_MOS:
                continue  # não elegível nem pela regra antiga — fora do escopo da auditoria

            max_init_antigo = linhas_validas[idx_antiga[-1]]['init_date'] if idx_antiga else None
            max_target_antigo = max((linhas_validas[i]['target_month'] for i in idx_antiga),
                                     default=None)
            max_init_corrigido = (linhas_validas[idx_corrigida[-1]]['init_date']
                                   if idx_corrigida else None)
            max_target_corrigido = max((linhas_validas[i]['target_month'] for i in idx_corrigida),
                                        default=None)

            indevidas = sorted(set(idx_antiga) - set(idx_corrigida))
            linhas_treino_indevidas = [linhas_validas[i]['init_date'] for i in indevidas]

            registros.append({
                'init_date_avaliada': linha_avaliada['init_date'],
                'n_treino_regra_antiga': n_antiga,
                'n_treino_regra_corrigida': n_corrigida,
                'n_linhas_nao_verificadas_incluidas': n_antiga - n_corrigida,
                'max_init_date_treino_antigo': max_init_antigo,
                'max_target_month_treino_antigo': max_target_antigo,
                'max_target_month_treino_corrigido': max_target_corrigido,
                'linhas_treino_indevidas': linhas_treino_indevidas,
            })

        detalhe_por_lead[lead] = registros

        n_previsoes_elegiveis_regra_antiga = len(registros)
        n_previsoes_afetadas = sum(1 for r in registros
                                    if r['n_linhas_nao_verificadas_incluidas'] > 0)
        inclusoes_por_avaliacao = [r['n_linhas_nao_verificadas_incluidas'] for r in registros]
        total_inclusoes_acumuladas = int(sum(inclusoes_por_avaliacao))
        max_por_avaliacao = int(max(inclusoes_por_avaliacao)) if inclusoes_por_avaliacao else 0
        media_por_avaliacao = (float(sum(inclusoes_por_avaliacao) / len(inclusoes_por_avaliacao))
                                if inclusoes_por_avaliacao else 0.0)

        linhas_historicas_unicas = set()
        for r in registros:
            linhas_historicas_unicas.update(r['linhas_treino_indevidas'])

        teto_esperado = TETO_ESPERADO_POR_LEAD[lead]
        dentro_do_teto_esperado = max_por_avaliacao <= teto_esperado

        resumo_por_lead[lead] = {
            'rotulo': v.ROTULO_HORIZONTE[lead],
            'n_previsoes_elegiveis_regra_antiga': n_previsoes_elegiveis_regra_antiga,
            'n_previsoes_afetadas': n_previsoes_afetadas,
            'inclusoes_indevidas_acumuladas_total': total_inclusoes_acumuladas,
            'inclusoes_indevidas_max_por_avaliacao': max_por_avaliacao,
            'inclusoes_indevidas_media_por_avaliacao': media_por_avaliacao,
            'linhas_historicas_unicas_indevidamente_incluidas_em_algum_momento':
                len(linhas_historicas_unicas),
            'teto_esperado_por_avaliacao_lead_menos_1': teto_esperado,
            'dentro_do_teto_esperado': dentro_do_teto_esperado,
        }

    diverge_sem_explicacao = [lead for lead, r in resumo_por_lead.items()
                               if not r['dentro_do_teto_esperado']]
    if diverge_sem_explicacao:
        return {
            'STOP_ON_FAILURE': True,
            'motivo': ('padrão estrutural observado excede o teto esperado (lead-1 por '
                       'avaliação) sem explicação — investigar antes de prosseguir'),
            'leads_divergentes': diverge_sem_explicacao,
            'resumo_por_horizonte': resumo_por_lead,
        }

    return {
        'STOP_ON_FAILURE': False,
        'metodo': 'auditoria_disponibilidade_observacional_metodo_3_4_mos_linear',
        'nota': ('Auditoria pura — nenhuma métrica do Método 3.4 foi recalculada ou '
                 'sobrescrita nesta atividade. "inclusões indevidas acumuladas" soma, por '
                 'horizonte, quantas vezes (ao longo de todas as avaliações elegíveis pela '
                 'regra antiga) uma linha de treino sem observação verificada entrou no '
                 'ajuste — a MESMA linha histórica pode ser contada várias vezes (uma por '
                 'avaliação em que indevidamente apareceu). "linhas históricas únicas" conta '
                 'cada linha de treino distinta só uma vez, independente de quantas '
                 'avaliações a incluíram indevidamente.'),
        'n_treino_minimo_mos': N_TREINO_MINIMO_MOS,
        'resumo_por_horizonte': resumo_por_lead,
        'detalhe_por_horizonte': detalhe_por_lead,
        'data_geracao_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--executar', action='store_true')
    args = ap.parse_args()

    if args.executar:
        resultado = auditar_disponibilidade_observacional_mos()
        DIRETORIO_SAIDA.mkdir(parents=True, exist_ok=True)
        CAMINHO_AUDITORIA_JSON.write_text(
            json.dumps(resultado, indent=2, ensure_ascii=False, default=str))
        print(f"  ✅ {CAMINHO_AUDITORIA_JSON.relative_to(ROOT)}")
        if resultado.get('STOP_ON_FAILURE'):
            print(f"\n❌ STOP_ON_FAILURE: {resultado.get('motivo')}")
            return
        print("\nResumo por horizonte:")
        for lead, r in resultado['resumo_por_horizonte'].items():
            print(f"  H{lead} ({r['rotulo']}): {r['n_previsoes_afetadas']}/"
                  f"{r['n_previsoes_elegiveis_regra_antiga']} previsões afetadas, "
                  f"{r['inclusoes_indevidas_acumuladas_total']} inclusões indevidas "
                  f"acumuladas, {r['linhas_historicas_unicas_indevidamente_incluidas_em_algum_momento']} "
                  f"linhas históricas únicas, máx/avaliação={r['inclusoes_indevidas_max_por_avaliacao']} "
                  f"(teto esperado {r['teto_esperado_por_avaliacao_lead_menos_1']})")
        return

    ap.print_help()


if __name__ == '__main__':
    main()
