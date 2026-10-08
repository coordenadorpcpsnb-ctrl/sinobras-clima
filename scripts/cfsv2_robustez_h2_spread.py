#!/usr/bin/env python3
"""
cfsv2_robustez_h2_spread.py — Fase 2C.3D: análise de ROBUSTEZ do sinal
spread×erro controlado por mês em H2 (único horizonte com IC 95% acima
de zero no gate do Método 3.5, commit 8ed49e6). NÃO implementa EMOS,
não recalibra membros, não aplica dressing, não altera probabilidades
operacionais nem o dashboard — é diagnóstico de robustez apenas.

Objetivo único: determinar se a associação residual
`spread_skill_month_controlled_retrospective` observada em H2 é
robusta ou depende excessivamente de poucos meses/estações (leave-one-
month-out e leave-one-season-out), nunca generalizar esse teste para
H1/H3-H6 (que já falharam no gate principal — só preservados aqui
como comparação congelada).

NÃO altera a metodologia do gate original: reaproveita literalmente
`cfsv2_gate_calibracao_probabilistica._bootstrap_residualizado_por_ano`
(mesma centralização por `target_mes`, recalculada em cada reamostra,
mesmo bootstrap em blocos por `target_ano`) — nunca uma segunda
fórmula paralela de residualização/bootstrap. Cada exclusão (mês ou
estação) refaz a transformação INTEIRA sobre os dados restantes —
nunca reaproveita resíduos já calculados na análise completa.

Roda com:
    python scripts/cfsv2_robustez_h2_spread.py --executar
    python scripts/cfsv2_robustez_h2_spread.py --gerar-relatorio
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import cfsv2_gate_calibracao_probabilistica as g  # noqa: E402
import cfsv2_validacao_cientifica as v  # noqa: E402

DIRETORIO_SAIDA = g.DIRETORIO_SAIDA
CAMINHO_METRICAS_JSON = DIRETORIO_SAIDA / 'robustez_h2_spread_2c3d.json'
RELATORIO_PATH = ROOT / 'docs' / 'nmme-fase2c3d-robustez-spread-h2.md'

LEAD_H2 = 2
NOMES_MES = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']

# ══════════════════════════════════════════════════════════════════════════
# Item 1 do pedido — resultado congelado do gate (commit 8ed49e6), nunca
# recalculado por esta atividade com outra fórmula. Comparado com teste
# de regressão contra o JSON real do gate, não apenas hardcoded aqui.
# ══════════════════════════════════════════════════════════════════════════

H2_PEARSON_RESIDUAL_CONGELADO = 0.154965
H2_PEARSON_IC95_CONGELADO = (0.042564, 0.256144)
H2_SPEARMAN_RESIDUAL_CONGELADO = 0.179941
H2_SPEARMAN_IC95_CONGELADO = (0.036391, 0.290664)

# Item 10 do pedido — resultados já existentes dos demais horizontes,
# só preservados para comparação, NUNCA recalculados aqui (já
# falharam no gate principal controlado por mês).
OUTROS_HORIZONTES_PEARSON_RESIDUAL_CONGELADO = {
    1: -0.023, 3: 0.115, 4: 0.011, 5: -0.069, 6: -0.046,
}

# ══════════════════════════════════════════════════════════════════════════
# Item 4 do pedido — critério de fragilidade PRÉ-REGISTRADO, fixado
# ANTES de rodar contra dados reais. Nunca ajustado depois de ver o
# resultado.
# ══════════════════════════════════════════════════════════════════════════

LIMIAR_INVERSAO_FORTE = -0.10   # uma única exclusão com estimativa abaixo disso conta como "inversão forte"
LIMIAR_MAIORIA_DE_12 = 7        # "maioria" das 12 exclusões mensais
LIMIAR_ROBUSTO_POSITIVO_DE_12 = 10   # item 4 do pedido, literal

CLASSIFICACAO_H2_ROBUSTO = 'sinal_h2_robusto'
CLASSIFICACAO_H2_PROMISSOR_FRAGIL = 'sinal_h2_promissor_mas_fragil'
CLASSIFICACAO_H2_DEPENDENTE_POUCOS_MESES = 'sinal_h2_dependente_de_poucos_meses'

DECISAO_PROSSEGUIR_EMOS = 'prosseguir_para_protocolo_emos_h2'
DECISAO_NAO_JUSTIFICAR_EMOS = 'nao_justificar_emos_dinamico_h2'
DECISAO_EVIDENCIA_INSUFICIENTE = 'h2_promissor_mas_evidencia_insuficiente'


# ══════════════════════════════════════════════════════════════════════════
# Item 2/3 do pedido — leave-one-month-out para H2, reaproveitando
# LITERALMENTE `g._bootstrap_residualizado_por_ano` (mesma centralização
# por target_mes recalculada a cada reamostra, mesmo bootstrap em
# blocos por target_ano) — nunca uma segunda fórmula paralela.
# ══════════════════════════════════════════════════════════════════════════

def leave_one_month_out_h2(tabela_ensemble, n_resamples=500, seed=20261001):
    """Para H2 exclusivamente: repete `spread_skill_month_controlled_
    retrospective` 12 vezes, excluindo integralmente um `target_mes`
    por vez. Cada rodada RECALCULA a transformação inteira (médias
    mensais dos meses restantes → resíduos → correlação → bootstrap)
    sobre os dados já filtrados — nunca reaproveita resíduos da
    análise completa, porque `g._bootstrap_residualizado_por_ano`
    sempre centraliza e residualiza o `df_lead` que recebe, de novo,
    do zero."""
    sub_h2 = tabela_ensemble[tabela_ensemble['lead'] == LEAD_H2].dropna(
        subset=['ensemble_std', 'ensemble_variance']).reset_index(drop=True)

    resultado = {}
    for mes_excluido in range(1, 13):
        sub_excl = sub_h2[sub_h2['target_mes'] != mes_excluido].reset_index(drop=True)
        n = len(sub_excl)
        if n < v.AMOSTRA_MINIMA_ESTRATO:
            resultado[mes_excluido] = {'mes_excluido': mes_excluido, 'n': n,
                                        'amostra_suficiente': False,
                                        'nota': 'amostra insuficiente após exclusão'}
            continue

        pearson = g._bootstrap_residualizado_por_ano(
            sub_excl, 'target_mes', 'target_ano', 'ensemble_std', 'erro_abs', v._corr,
            n_resamples, seed)
        spearman = g._bootstrap_residualizado_por_ano(
            sub_excl, 'target_mes', 'target_ano', 'ensemble_std', 'erro_abs', g._corr_spearman,
            n_resamples, seed)

        resultado[mes_excluido] = {
            'mes_excluido': mes_excluido, 'mes_excluido_nome': NOMES_MES[mes_excluido - 1],
            'n': n, 'amostra_suficiente': True,
            'pearson': pearson,
            'pearson_ic_classificacao': v._classificar_ic_relativo_a_zero(
                pearson['ic95_lo'], pearson['ic95_hi']),
            'spearman': spearman,
            'spearman_ic_classificacao': v._classificar_ic_relativo_a_zero(
                spearman['ic95_lo'], spearman['ic95_hi']),
        }
    return resultado


def resumo_leave_one_month_out(lomo):
    """Item 3 do pedido — min/max/mediana de Pearson e Spearman entre
    as 12 exclusões, e contagens de positividade/IC acima de zero."""
    validos = {m: d for m, d in lomo.items() if d.get('amostra_suficiente', False)}
    pearsons = [d['pearson']['estimativa'] for d in validos.values()]
    spearmans = [d['spearman']['estimativa'] for d in validos.values()]
    n_pearson_pos = sum(1 for p in pearsons if p is not None and p > 0)
    n_spearman_pos = sum(1 for s in spearmans if s is not None and s > 0)
    n_pearson_ic_pos = sum(1 for d in validos.values()
                            if d['pearson_ic_classificacao'] == 'ic_totalmente_acima_de_zero')
    n_spearman_ic_pos = sum(1 for d in validos.values()
                             if d['spearman_ic_classificacao'] == 'ic_totalmente_acima_de_zero')
    return {
        'n_exclusoes_validas': len(validos),
        'pearson_minimo': float(np.min(pearsons)) if pearsons else None,
        'pearson_maximo': float(np.max(pearsons)) if pearsons else None,
        'pearson_mediana': float(np.median(pearsons)) if pearsons else None,
        'spearman_minimo': float(np.min(spearmans)) if spearmans else None,
        'spearman_maximo': float(np.max(spearmans)) if spearmans else None,
        'spearman_mediana': float(np.median(spearmans)) if spearmans else None,
        'n_exclusoes_pearson_positivo': n_pearson_pos,
        'n_exclusoes_spearman_positivo': n_spearman_pos,
        'n_exclusoes_pearson_ic_acima_de_zero': n_pearson_ic_pos,
        'n_exclusoes_spearman_ic_acima_de_zero': n_spearman_ic_pos,
    }


# ══════════════════════════════════════════════════════════════════════════
# Item 4 do pedido — classificação de robustez, limiares PRÉ-REGISTRADOS
# (ver constantes no topo do módulo), nunca escolhidos depois de olhar
# o resultado real. NUNCA um teste de hipótese formal — síntese
# descritiva de robustez.
# ══════════════════════════════════════════════════════════════════════════

def classificar_robustez_h2(lomo, resumo):
    validos = {m: d for m, d in lomo.items() if d.get('amostra_suficiente', False)}
    inversao_forte = any(
        (d['pearson']['estimativa'] is not None and d['pearson']['estimativa'] < LIMIAR_INVERSAO_FORTE)
        or (d['spearman']['estimativa'] is not None and d['spearman']['estimativa'] < LIMIAR_INVERSAO_FORTE)
        for d in validos.values()
    )
    pelo_menos_uma_ic_maioria = (resumo['n_exclusoes_pearson_ic_acima_de_zero'] >= LIMIAR_MAIORIA_DE_12
                                  or resumo['n_exclusoes_spearman_ic_acima_de_zero'] >= LIMIAR_MAIORIA_DE_12)
    ambas_positivas_robusto = (resumo['n_exclusoes_pearson_positivo'] >= LIMIAR_ROBUSTO_POSITIVO_DE_12
                                and resumo['n_exclusoes_spearman_positivo'] >= LIMIAR_ROBUSTO_POSITIVO_DE_12)
    ambas_positivas_maioria = (resumo['n_exclusoes_pearson_positivo'] >= LIMIAR_MAIORIA_DE_12
                                and resumo['n_exclusoes_spearman_positivo'] >= LIMIAR_MAIORIA_DE_12)
    sinal_mediano_positivo = (resumo['pearson_mediana'] is not None and resumo['pearson_mediana'] > 0
                               and resumo['spearman_mediana'] is not None and resumo['spearman_mediana'] > 0)

    if ambas_positivas_robusto and pelo_menos_uma_ic_maioria and not inversao_forte:
        classificacao = CLASSIFICACAO_H2_ROBUSTO
        justificativa = (f'Pearson e Spearman positivos em >= {LIMIAR_ROBUSTO_POSITIVO_DE_12}/12 '
                          'exclusões, pelo menos uma métrica com IC 95% acima de zero na maioria '
                          f'(>= {LIMIAR_MAIORIA_DE_12}/12) das exclusões, e nenhuma exclusão '
                          f'produziu inversão forte (< {LIMIAR_INVERSAO_FORTE}).')
    elif sinal_mediano_positivo and ambas_positivas_maioria and not inversao_forte:
        classificacao = CLASSIFICACAO_H2_PROMISSOR_FRAGIL
        justificativa = ('Sinal mediano positivo e maioria das exclusões ainda positivas, mas '
                          'não atinge o limiar robusto de 10/12, ou o IC não fica acima de zero '
                          'na maioria das exclusões — promissor, mas não robusto.')
    else:
        classificacao = CLASSIFICACAO_H2_DEPENDENTE_POUCOS_MESES
        justificativa = ('Poucas exclusões mantêm o sinal positivo e/ou pelo menos uma exclusão '
                          f'produziu inversão forte (< {LIMIAR_INVERSAO_FORTE}) — o resultado '
                          'original parece sustentado por poucos meses específicos, não por um '
                          'padrão consistente.')

    return {
        'classificacao': classificacao, 'justificativa': justificativa,
        'sinais': {
            'inversao_forte_em_alguma_exclusao': inversao_forte,
            'pelo_menos_uma_ic_maioria': pelo_menos_uma_ic_maioria,
            'ambas_positivas_limiar_robusto': ambas_positivas_robusto,
            'ambas_positivas_maioria': ambas_positivas_maioria,
            'sinal_mediano_positivo': sinal_mediano_positivo,
        },
        'nota': 'Classificação pré-registrada (limiares fixados antes de olhar o resultado real) '
                '— síntese descritiva de robustez, NUNCA um teste de hipótese formal.',
    }


# ══════════════════════════════════════════════════════════════════════════
# Item 5 do pedido — leave-one-season-out para H2, mesmo reaproveitamento
# de `g._bootstrap_residualizado_por_ano`.
# ══════════════════════════════════════════════════════════════════════════

def leave_one_season_out_h2(tabela_ensemble, n_resamples=500, seed=20261001):
    sub_h2 = tabela_ensemble[tabela_ensemble['lead'] == LEAD_H2].dropna(
        subset=['ensemble_std', 'ensemble_variance']).reset_index(drop=True)

    resultado = {}
    for grupo in ('chuvosa', 'transicao', 'seca'):
        meses_grupo = {m for m, g_ in v.GRUPO_SAZONAL_POR_MES.items() if g_ == grupo}
        sub_excl = sub_h2[~sub_h2['target_mes'].isin(meses_grupo)].reset_index(drop=True)
        n = len(sub_excl)
        if n < v.AMOSTRA_MINIMA_ESTRATO:
            resultado[grupo] = {'grupo_excluido': grupo, 'n': n, 'amostra_suficiente': False,
                                 'nota': 'amostra insuficiente após exclusão'}
            continue

        pearson = g._bootstrap_residualizado_por_ano(
            sub_excl, 'target_mes', 'target_ano', 'ensemble_std', 'erro_abs', v._corr,
            n_resamples, seed)
        spearman = g._bootstrap_residualizado_por_ano(
            sub_excl, 'target_mes', 'target_ano', 'ensemble_std', 'erro_abs', g._corr_spearman,
            n_resamples, seed)

        resultado[grupo] = {
            'grupo_excluido': grupo, 'n': n, 'amostra_suficiente': True,
            'pearson': pearson,
            'pearson_ic_classificacao': v._classificar_ic_relativo_a_zero(
                pearson['ic95_lo'], pearson['ic95_hi']),
            'spearman': spearman,
            'spearman_ic_classificacao': v._classificar_ic_relativo_a_zero(
                spearman['ic95_lo'], spearman['ic95_hi']),
        }
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# Item 6 do pedido — diagnóstico complementar dos 12 meses (reaproveita
# `g.spread_skill_matriz_mes_lead`, já calculada pelo gate — NUNCA uma
# segunda fórmula paralela de correlação mês×lead).
# ══════════════════════════════════════════════════════════════════════════

def diagnostico_meses_h2(tabela_ensemble):
    matriz = g.spread_skill_matriz_mes_lead(tabela_ensemble)
    resultado = {}
    for mes in range(1, 13):
        cel = matriz.get(mes, {}).get(LEAD_H2, {})
        resultado[mes] = {'mes': mes, 'mes_nome': NOMES_MES[mes - 1], **cel}
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# Item 7 do pedido — análise de influência: H2 completo, sem março, sem
# o mês de maior Pearson observado, sem o mês de maior Spearman
# observado (nunca seleção de modelo — só sensibilidade).
# ══════════════════════════════════════════════════════════════════════════

MARCO = 3


def analise_influencia_h2(diagnostico_meses, lomo):
    """`diagnostico_meses` (item 6, valores BRUTOS por célula de 1 mês)
    identifica qual mês tem o maior Pearson/Spearman observado — a
    exclusão correspondente é simplesmente lida de `lomo` (item 2),
    nunca recalculada de outra forma."""
    meses_com_pearson = {m: d['pearson_std_vs_erro_abs'] for m, d in diagnostico_meses.items()
                          if d.get('pearson_std_vs_erro_abs') is not None}
    meses_com_spearman = {m: d['spearman_std_vs_erro_abs'] for m, d in diagnostico_meses.items()
                           if d.get('spearman_std_vs_erro_abs') is not None}
    mes_maior_pearson = max(meses_com_pearson, key=meses_com_pearson.get) if meses_com_pearson else None
    mes_maior_spearman = max(meses_com_spearman, key=meses_com_spearman.get) if meses_com_spearman else None

    return {
        'mes_maior_pearson_observado': mes_maior_pearson,
        'mes_maior_pearson_observado_nome': NOMES_MES[mes_maior_pearson - 1] if mes_maior_pearson else None,
        'mes_maior_spearman_observado': mes_maior_spearman,
        'mes_maior_spearman_observado_nome': NOMES_MES[mes_maior_spearman - 1] if mes_maior_spearman else None,
        'sem_marco': lomo.get(MARCO),
        'sem_mes_maior_pearson': lomo.get(mes_maior_pearson) if mes_maior_pearson else None,
        'sem_mes_maior_spearman': lomo.get(mes_maior_spearman) if mes_maior_spearman else None,
        'marco_e_o_mes_de_maior_pearson_e_spearman': (mes_maior_pearson == MARCO == mes_maior_spearman),
        'nota': 'Análise de INFLUÊNCIA, não seleção de modelo — nenhuma destas exclusões decide a '
                'metodologia final; servem só para checar se o resultado completo depende '
                'desproporcionalmente de um mês específico.',
    }


# ══════════════════════════════════════════════════════════════════════════
# Orquestração
# ══════════════════════════════════════════════════════════════════════════

def executar_robustez_h2(n_resamples_bootstrap=500):
    gate_json = g.CAMINHO_METRICAS_JSON
    if not gate_json.exists():
        return {'STOP_ON_FAILURE': True,
                'motivo': 'JSON do gate (Método 3.5) não encontrado — rode '
                          'cfsv2_gate_calibracao_probabilistica.py --executar primeiro'}
    gate_resultado = json.loads(gate_json.read_text())
    if gate_resultado.get('STOP_ON_FAILURE'):
        return {'STOP_ON_FAILURE': True, 'motivo': 'gate do Método 3.5 está em STOP_ON_FAILURE'}

    # Item 1 do pedido — congelar e CONFERIR o resultado atual contra os
    # valores pré-registrados (nunca silenciosamente confiar que não
    # mudou sem checar).
    h2_gate = gate_resultado['spread_skill_month_controlled_retrospective_por_horizonte'].get(
        str(LEAD_H2), gate_resultado['spread_skill_month_controlled_retrospective_por_horizonte'].get(LEAD_H2))
    h2_pearson_atual = h2_gate['pearson_std_resid_vs_erro_abs_resid']['estimativa']
    h2_spearman_atual = h2_gate['spearman_std_resid_vs_erro_abs_resid']['estimativa']
    congelamento_ok = (abs(h2_pearson_atual - H2_PEARSON_RESIDUAL_CONGELADO) < 1e-3
                        and abs(h2_spearman_atual - H2_SPEARMAN_RESIDUAL_CONGELADO) < 1e-3)
    if not congelamento_ok:
        return {'STOP_ON_FAILURE': True,
                'motivo': 'resultado atual do gate para H2 diverge do valor pré-registrado — a '
                          'referência congelada (item 1 do pedido) não é mais válida; revisar '
                          'antes de continuar a análise de robustez',
                'detalhe': {'h2_pearson_atual': h2_pearson_atual,
                            'h2_pearson_congelado': H2_PEARSON_RESIDUAL_CONGELADO,
                            'h2_spearman_atual': h2_spearman_atual,
                            'h2_spearman_congelado': H2_SPEARMAN_RESIDUAL_CONGELADO}}

    auditoria = v.executar_auditoria()
    if not auditoria['auditoria_aprovada']:
        return {'STOP_ON_FAILURE': True, 'motivo': 'auditoria da base RAW (2C.3C) reprovada'}
    df_raw = v.carregar_cfsv2_raw()
    chirps_df = v.carregar_chirps_v3_historico()
    base = v.construir_base_pareada(df_raw, chirps_df)
    if not v.validar_nenhum_mes_alvo_ausente(base):
        return {'STOP_ON_FAILURE': True, 'motivo': 'pareamento com mês-alvo ausente'}
    tabela_ensemble = g.construir_tabela_ensemble(base)
    auditoria_membros = g._verificar_24_membros(tabela_ensemble)
    if not auditoria_membros['ok']:
        return {'STOP_ON_FAILURE': True, 'motivo': 'auditoria de 24 membros reprovada',
                'detalhe': auditoria_membros}

    lomo = leave_one_month_out_h2(tabela_ensemble, n_resamples_bootstrap)
    resumo_lomo = resumo_leave_one_month_out(lomo)
    robustez = classificar_robustez_h2(lomo, resumo_lomo)
    loso = leave_one_season_out_h2(tabela_ensemble, n_resamples_bootstrap)
    diagnostico_meses = diagnostico_meses_h2(tabela_ensemble)
    influencia = analise_influencia_h2(diagnostico_meses, lomo)

    if robustez['classificacao'] == CLASSIFICACAO_H2_ROBUSTO:
        decisao = DECISAO_PROSSEGUIR_EMOS
    elif robustez['classificacao'] == CLASSIFICACAO_H2_DEPENDENTE_POUCOS_MESES:
        decisao = DECISAO_NAO_JUSTIFICAR_EMOS
    else:
        decisao = DECISAO_EVIDENCIA_INSUFICIENTE

    resultado = {
        'STOP_ON_FAILURE': False,
        'metodo': 'robustez_spread_skill_h2_metodo_3_5',
        'referencia_congelada_h2': {
            'pearson_residual': H2_PEARSON_RESIDUAL_CONGELADO,
            'pearson_ic95': list(H2_PEARSON_IC95_CONGELADO),
            'spearman_residual': H2_SPEARMAN_RESIDUAL_CONGELADO,
            'spearman_ic95': list(H2_SPEARMAN_IC95_CONGELADO),
            'congelamento_confirmado_contra_json_do_gate': congelamento_ok,
        },
        'outros_horizontes_congelado': OUTROS_HORIZONTES_PEARSON_RESIDUAL_CONGELADO,
        'leave_one_month_out': lomo,
        'resumo_leave_one_month_out': resumo_lomo,
        'classificacao_robustez_h2': robustez,
        'leave_one_season_out': loso,
        'diagnostico_meses_h2': diagnostico_meses,
        'analise_influencia': influencia,
        'multiplicidade_nota': (
            'Foram avaliados H1-H6 no gate principal controlado por mês e apenas H2 apresentou '
            'IC 95% totalmente acima de zero. Nenhuma correção formal de multiplicidade '
            '(Bonferroni/FDR) foi aplicada como novo critério de gate nesta atividade — mas um '
            'achado isolado entre seis horizontes é tratado aqui como evidência EXPLORATÓRIA que '
            'exige robustez interna (este documento) antes de justificar um novo modelo. H2 nunca '
            'é chamado de "validado".'
        ),
        'decisao_final_emos_h2': decisao,
        'nenhum_emos_ajustado': True,
        'nenhum_dressing_aplicado': True,
        'nenhuma_recalibracao_de_membros': True,
        'nenhuma_probabilidade_operacional_alterada': True,
        'data_geracao_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    return resultado


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--executar', action='store_true')
    ap.add_argument('--gerar-relatorio', action='store_true')
    args = ap.parse_args()

    if args.executar:
        resultado = executar_robustez_h2()
        DIRETORIO_SAIDA.mkdir(parents=True, exist_ok=True)
        CAMINHO_METRICAS_JSON.write_text(
            json.dumps(resultado, indent=2, ensure_ascii=False, default=str))
        print(f"  ✅ {CAMINHO_METRICAS_JSON.relative_to(ROOT)}")
        if resultado.get('STOP_ON_FAILURE'):
            print(f"\n❌ STOP_ON_FAILURE: {resultado.get('motivo')}")
            return
        print(f"  classificacao_robustez_h2 = {resultado['classificacao_robustez_h2']['classificacao']}")
        print(f"  decisao_final_emos_h2 = {resultado['decisao_final_emos_h2']}")
        return

    if args.gerar_relatorio:
        import cfsv2_relatorio_robustez_h2 as rel
        rel.gerar_e_escrever()
        return

    ap.print_help()


if __name__ == '__main__':
    main()
