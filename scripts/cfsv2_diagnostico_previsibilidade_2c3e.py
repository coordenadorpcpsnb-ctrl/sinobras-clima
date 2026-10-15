#!/usr/bin/env python3
"""
cfsv2_diagnostico_previsibilidade_2c3e.py — Fase 2C.3E: diagnóstico
integrado da habilidade preditiva regional do CFSv2, consolidando
evidência já aprovada das Fases 2C.3C/2C.3D (RAW, Métodos 3.1
aditivo, 3.2 multiplicativo, 3.3 gate QM, 3.4 MOS linear, 3.5 EMOS
H2/gate probabilístico/robustez H2).

Papel desta atividade: AUDITORIA e SÍNTESE, não desenvolvimento de
modelo. Nenhum método é ajustado, recalibrado, selecionado ou
promovido aqui. Toda métrica numérica deste módulo é lida diretamente
dos artefatos já aprovados das fases anteriores (nunca recomputada
com uma fórmula paralela) — a única computação nova feita aqui é a
INTERSECÇÃO de chaves (`init_date`, `lead`) entre os CSVs de previsão
por método já aprovados, necessária para a auditoria de
comparabilidade de amostra (Seção C do pedido), e que não altera
nenhuma métrica científica já registrada.

CFSv2 RAW, CHIRPS v3, dashboard, pipeline operacional e os protocolos
já aprovados dos Métodos 3.1–3.5 não são tocados — leitura exclusiva.

Roda com:
    python scripts/cfsv2_diagnostico_previsibilidade_2c3e.py --executar
    python -m unittest tests.test_cfsv2_diagnostico_previsibilidade_2c3e -v
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

DIRETORIO_SAIDA = ROOT / 'data' / 'cfsv2_diagnostico_2c3e'
CAMINHO_INVENTARIO = DIRETORIO_SAIDA / 'inventario_metodos.json'
CAMINHO_COMPARABILIDADE = DIRETORIO_SAIDA / 'comparabilidade_amostras.csv'
CAMINHO_DIAGNOSTICO = DIRETORIO_SAIDA / 'diagnostico_habilidade.json'

# Fontes já aprovadas — SÓ LEITURA, nunca escritas por este módulo.
CAMINHO_2C3C_METRICAS = ROOT / 'data' / 'cfsv2_validacao_2c3c' / 'metricas_2c3c.json'
CAMINHO_2C3C_BASE = ROOT / 'data' / 'cfsv2_validacao_2c3c' / 'base_pareada_cfsv2_chirps_v3.csv'

DIR_2C3D = ROOT / 'data' / 'cfsv2_calibracao_2c3d'
CAMINHO_ADITIVA_METRICAS = DIR_2C3D / 'metricas_aditiva_2c3d.json'
CAMINHO_ADITIVA_CSV = DIR_2C3D / 'aditiva_expanding.csv'
CAMINHO_MULT_METRICAS = DIR_2C3D / 'metricas_multiplicativa_2c3d.json'
CAMINHO_MULT_CSV = DIR_2C3D / 'multiplicativa_expanding.csv'
CAMINHO_QM_VIABILIDADE = DIR_2C3D / 'viabilidade_quantile_mapping.json'
CAMINHO_MOS_METRICAS = DIR_2C3D / 'metricas_mos_linear_2c3d.json'
CAMINHO_MOS_CSV = DIR_2C3D / 'mos_linear_expanding.csv'
CAMINHO_MOS_AUDITORIA = DIR_2C3D / 'auditoria_disponibilidade_mos_2c3d.json'
CAMINHO_GATE_METRICAS = DIR_2C3D / 'gate_calibracao_probabilistica_2c3d.json'
CAMINHO_ROBUSTEZ_H2 = DIR_2C3D / 'robustez_h2_spread_2c3d.json'
CAMINHO_EMOS_METRICAS = DIR_2C3D / 'metricas_emos_h2_2c3d.json'
CAMINHO_EMOS_CSV = DIR_2C3D / 'emos_h2_expanding.csv'

HORIZONTES = [1, 2, 3, 4, 5, 6]
LEAD_H2 = 2

# Formulação consolidada da decisão científica desta fase (2ª rodada de
# auditoria, item 3) — usada literalmente no relatório, nunca reformulada
# como ausência absoluta de informação preditiva. Mantida como constante
# única para permitir teste de consistência relatório↔script.
DECISAO_CONSOLIDADA_FASE_2C3E = (
    'Nenhum dos métodos de calibração avaliados satisfez integralmente os '
    'respectivos critérios pré-registrados de aprovação operacional.'
)


def _carregar_json(caminho):
    if not caminho.exists():
        raise FileNotFoundError(f'Fonte já aprovada ausente — STOP_ON_FAILURE: {caminho}')
    with open(caminho) as f:
        return json.load(f)


def _carregar_csv(caminho):
    if not caminho.exists():
        raise FileNotFoundError(f'Fonte já aprovada ausente — STOP_ON_FAILURE: {caminho}')
    return pd.read_csv(caminho)


def _ic_bloco(d):
    """Extrai {estimativa, ic95_lo, ic95_hi} de um bloco de IC já aprovado,
    sem recalcular nada — repassa os números exatamente como registrados."""
    if d is None:
        return None
    return {'estimativa': d.get('estimativa'), 'ic95_lo': d.get('ic95_lo'), 'ic95_hi': d.get('ic95_hi')}


# ══════════════════════════════════════════════════════════════════════════
# Seção B — inventário de métodos
# ══════════════════════════════════════════════════════════════════════════

def construir_inventario_metodos():
    c3c = _carregar_json(CAMINHO_2C3C_METRICAS)
    adit = _carregar_json(CAMINHO_ADITIVA_METRICAS)
    mult = _carregar_json(CAMINHO_MULT_METRICAS)
    qm = _carregar_json(CAMINHO_QM_VIABILIDADE)
    mos = _carregar_json(CAMINHO_MOS_METRICAS)
    mos_aud = _carregar_json(CAMINHO_MOS_AUDITORIA)
    gate = _carregar_json(CAMINHO_GATE_METRICAS)
    robustez = _carregar_json(CAMINHO_ROBUSTEZ_H2)
    emos = _carregar_json(CAMINHO_EMOS_METRICAS)

    inventario = {}

    # --- CFSv2 RAW (2C.3C) ------------------------------------------------
    eos_c3c = c3c['expanding_operational_simulation']
    det_c3c = eos_c3c['deterministico_por_horizonte']
    ic_skill_c3c = eos_c3c['intervalos_confianca_skill_scores_por_horizonte']
    inventario['raw_cfsv2_2c3c'] = {
        'nome': 'CFSv2 RAW (validação 2C.3C)',
        'objetivo_variavel': 'Precipitação mensal bruta do ensemble CFSv2 (24 membros), sem calibração — serve de referência estrutural para todos os métodos de calibração (3.1–3.5).',
        'horizontes_avaliados': HORIZONTES,
        'amostra': {
            'n_total_registros_membro': c3c['auditoria']['n_raw_total'],
            'n_inicializacoes_distintas': c3c['auditoria']['n_inicializacoes_distintas'],
            'n_por_horizonte_sem_filtro_warmup': {str(h): det_c3c[str(h)]['n'] for h in HORIZONTES},
        },
        'regra_causal': 'Nenhum warm-up aplicável (RAW não é ajustado) — auditoria de leakage cobre só alinhamento de datas/membros (ver auditoria_aprovada).',
        'referencias_usadas': ['climatologia observada causal', 'climatologia probabilística causal (CRPS/BSS)'],
        'metricas_principais_por_horizonte': {
            str(h): {
                'rmsess_absoluto': _ic_bloco(ic_skill_c3c[str(h)]['rmsess']),
                'rmsess_absoluto_ic_classificacao': ic_skill_c3c[str(h)]['rmsess_ic_classificacao'],
                'rmsess_anomalia_corrigida': _ic_bloco(
                    eos_c3c['intervalos_confianca_rmsess_anomalia_corrigida_por_horizonte'][str(h)]['rmsess_anomalia_corrigida']
                ),
                'rmsess_anomalia_corrigida_ic_classificacao':
                    eos_c3c['intervalos_confianca_rmsess_anomalia_corrigida_por_horizonte'][str(h)]['rmsess_anomalia_corrigida_ic_classificacao'],
                'crpss': _ic_bloco(ic_skill_c3c[str(h)]['crpss']),
                'crpss_ic_classificacao': ic_skill_c3c[str(h)]['crpss_ic_classificacao'],
                'corr_absoluta': det_c3c[str(h)]['absoluto']['corr'],
                'corr_anomalia_corrigida': det_c3c[str(h)]['anomalia_corrigida_climatologia_propria_modelo']['corr'],
            }
            for h in HORIZONTES
        },
        'decisao_cientifica_registrada': 'Auditoria estrutural APROVADA (auditoria_aprovada=%s); nenhuma skill é exibida no dashboard a partir deste artefato.' % c3c['auditoria']['auditoria_aprovada'],
        'limitacoes_status_operacional': 'RMSESS/CRPSS absolutos negativos com IC abaixo de zero em todos os horizontes (skill RAW ruim); RMSESS de anomalia corrigida indeterminado (IC inclui zero) — leitura DIFERENTE e independente, nunca combinada com a absoluta. Nenhuma correção aplicada em produção.',
    }

    # --- Método 3.1 aditivo ----------------------------------------------
    eos_a = adit['expanding_operational_simulation']
    ic_a = eos_a['intervalos_confianca_skills_por_horizonte']
    det_a = eos_a['deterministico_por_horizonte']
    inventario['metodo_3_1_aditivo'] = {
        'nome': 'Método 3.1 — correção aditiva',
        'objetivo_variavel': 'Precipitação mensal calibrada por bias aditivo (forecast_raw + bias médio causal por lead).',
        'horizontes_avaliados': HORIZONTES,
        'amostra': {
            'n_treino_minimo': adit['n_treino_minimo'],
            'n_elegivel_por_horizonte': {str(h): det_a[str(h)]['n_elegivel'] for h in HORIZONTES},
        },
        'regra_causal': 'init_date_treino < init_date_avaliada; N_TREINO_MINIMO=%s pares válidos contados após filtro causal.' % adit['n_treino_minimo'],
        'referencias_usadas': ['RAW', 'climatologia observada causal', 'benchmark_anomalia_reconstruida'],
        'metricas_principais_por_horizonte': {
            str(h): {
                'skill_vs_raw': _ic_bloco(ic_a[str(h)]['skill_vs_raw']),
                'skill_vs_raw_ic_classificacao': ic_a[str(h)]['skill_vs_raw_ic_classificacao'],
                'RMSESS_climatologia': _ic_bloco(ic_a[str(h)]['RMSESS_climatologia']),
                'RMSESS_climatologia_ic_classificacao': ic_a[str(h)]['RMSESS_climatologia_ic_classificacao'],
                'skill_vs_anomalia_reconstruida': _ic_bloco(ic_a[str(h)]['skill_vs_anomalia_reconstruida']),
                'skill_vs_anomalia_reconstruida_ic_classificacao': ic_a[str(h)]['skill_vs_anomalia_reconstruida_ic_classificacao'],
            }
            for h in HORIZONTES
        },
        'decisao_cientifica_registrada': 'Critério pré-registrado (IC95 de skill_vs_anomalia_reconstruida E RMSESS_climatologia simultaneamente acima de zero) não satisfeito em nenhum horizonte H1–H6.',
        'limitacoes_status_operacional': 'skill_vs_raw IC95% acima de zero em todos os horizontes, mas isto isoladamente não é o critério de aprovação. Nenhuma correção aplicada em produção.',
    }

    # --- Método 3.2 multiplicativo ----------------------------------------
    eos_m = mult['expanding_operational_simulation']
    ic_m = eos_m['intervalos_confianca_skills_por_horizonte']
    det_m = eos_m['deterministico_por_horizonte']
    inventario['metodo_3_2_multiplicativo'] = {
        'nome': 'Método 3.2 — correção multiplicativa',
        'objetivo_variavel': 'Precipitação mensal calibrada por razão multiplicativa causal (forecast_raw × razão média obs/modelo no treino), só em meses com denominador seguro.',
        'horizontes_avaliados': HORIZONTES,
        'amostra': {
            'n_treino_minimo': mult['n_treino_minimo'],
            'piso_denominador_mm': mult['piso_denominador_mm'],
            'n_elegivel_por_horizonte': {str(h): det_m[str(h)]['n_elegivel'] for h in HORIZONTES},
        },
        'regra_causal': 'Igual ao 3.1 (init_date_treino < init_date_avaliada); exclui estruturalmente jun–set por denominador abaixo do piso (%.1f mm).' % mult['piso_denominador_mm'],
        'referencias_usadas': ['RAW', 'climatologia observada causal', 'benchmark_anomalia_reconstruida', 'Método 3.1 (amostra pareada)'],
        'metricas_principais_por_horizonte': {
            str(h): {
                'skill_vs_raw': _ic_bloco(ic_m[str(h)]['skill_vs_raw']),
                'skill_vs_raw_ic_classificacao': ic_m[str(h)]['skill_vs_raw_ic_classificacao'],
                'RMSESS_climatologia': _ic_bloco(ic_m[str(h)]['RMSESS_climatologia']),
                'RMSESS_climatologia_ic_classificacao': ic_m[str(h)]['RMSESS_climatologia_ic_classificacao'],
                'skill_vs_anomalia_reconstruida': _ic_bloco(ic_m[str(h)]['skill_vs_anomalia_reconstruida']),
                'skill_vs_anomalia_reconstruida_ic_classificacao': ic_m[str(h)]['skill_vs_anomalia_reconstruida_ic_classificacao'],
                'skill_multiplicativo_vs_aditivo': _ic_bloco(ic_m[str(h)]['skill_multiplicativo_vs_aditivo']),
                'skill_multiplicativo_vs_aditivo_ic_classificacao': ic_m[str(h)]['skill_multiplicativo_vs_aditivo_ic_classificacao'],
            }
            for h in HORIZONTES
        },
        'decisao_cientifica_registrada': 'Critério pré-registrado não satisfeito em nenhum horizonte; skill_multiplicativo_vs_aditivo com IC95% incluindo zero em todos os horizontes (sem diferença distinguível do aditivo).',
        'limitacoes_status_operacional': 'jun–set nunca reportados como desempenho anual (exclusão estrutural por piso de denominador). Nenhuma correção aplicada em produção.',
    }

    # --- Método 3.3 gate QM (não testável) --------------------------------
    inventario['metodo_3_3_gate_qm'] = {
        'nome': 'Método 3.3 — gate de viabilidade do quantile mapping',
        'objetivo_variavel': 'Avaliar se o hindcast CFSv2 tem amostra suficiente por estrato (lead × mês) para quantile mapping — não é um método de correção.',
        'horizontes_avaliados': HORIZONTES,
        'amostra': {
            'hindcast_fixo_anos': 20,
            'limiar_minimo_quantile_mapping': qm['avaliacao']['limiar_minimo_quantile_mapping'],
            'maximo_n_causal_observado_geral': qm['avaliacao']['maximo_n_causal_observado_geral'],
        },
        'regra_causal': 'Hindcast FIXO em 1991–2010 (20 anos); N causal máximo por célula = 19, sempre abaixo do mínimo exigido.',
        'referencias_usadas': [],
        'metricas_principais_por_horizonte': {},
        'decisao_cientifica_registrada': qm['avaliacao']['metodo_3_3_status'],
        'limitacoes_status_operacional': f"NÃO TESTÁVEL por limitação estrutural do hindcast disponível (não é resultado negativo nem falha de pipeline). Próximo método elegível: {qm['proximo_metodo_elegivel_se_inviavel']}.",
    }

    # --- Método 3.4 MOS linear (pós-correção causal) ----------------------
    eos_mos = mos['expanding_operational_simulation']
    ic_mos = eos_mos['intervalos_confianca_skills_por_horizonte']
    det_mos = eos_mos['deterministico_por_horizonte']
    inventario['metodo_3_4_mos_linear'] = {
        'nome': 'Método 3.4 — MOS linear (pooled by lead, pós-correção causal)',
        'objetivo_variavel': 'anom_observada = alpha_lead + beta_lead * anom_modelo_raw, ajustado por OLS, pooling entre meses dentro de cada lead.',
        'horizontes_avaliados': HORIZONTES,
        'amostra': {
            'n_treino_minimo_mos': mos['n_treino_minimo_mos'],
            'n_elegivel_por_horizonte_pos_correcao': {str(h): det_mos[str(h)]['n'] for h in HORIZONTES},
            'n_elegivel_por_horizonte_pre_correcao': {
                str(h): mos_aud['resumo_por_horizonte'][str(h)]['n_previsoes_elegiveis_regra_antiga']
                for h in HORIZONTES
            },
        },
        'regra_causal': 'init_date_treino < init_date_avaliada E target_month_treino < init_date_avaliada (corrigida — ver auditoria de disponibilidade); H1 é controle negativo bit-idêntico antes/depois.',
        'referencias_usadas': ['RAW', 'climatologia observada causal', 'benchmark_anomalia_reconstruida', 'Método 3.1 (amostra pareada)'],
        'metricas_principais_por_horizonte': {
            str(h): {
                'skill_vs_raw': _ic_bloco(ic_mos[str(h)]['skill_vs_raw']),
                'skill_vs_raw_ic_classificacao': ic_mos[str(h)]['skill_vs_raw_ic_classificacao'],
                'RMSESS_climatologia': _ic_bloco(ic_mos[str(h)]['RMSESS_climatologia']),
                'RMSESS_climatologia_ic_classificacao': ic_mos[str(h)]['RMSESS_climatologia_ic_classificacao'],
                'skill_vs_anomalia_reconstruida': _ic_bloco(ic_mos[str(h)]['skill_vs_anomalia_reconstruida']),
                'skill_vs_anomalia_reconstruida_ic_classificacao': ic_mos[str(h)]['skill_vs_anomalia_reconstruida_ic_classificacao'],
                'skill_mos_vs_aditivo': _ic_bloco(ic_mos[str(h)]['skill_mos_vs_aditivo']),
                'skill_mos_vs_aditivo_ic_classificacao': ic_mos[str(h)]['skill_mos_vs_aditivo_ic_classificacao'],
            }
            for h in HORIZONTES
        },
        'decisao_cientifica_registrada': 'Critério pré-registrado não satisfeito em nenhum horizonte, antes ou depois da correção causal; skill_mos_vs_aditivo IC95% inclui zero em todos os horizontes.',
        'limitacoes_status_operacional': 'Correção de disponibilidade observacional (auditoria dedicada) não mudou a conclusão de aprovação, mas corrigiu leakage real de 1 a 5 meses em H2–H6; H1 confirmado bit-idêntico (controle negativo). Nenhuma correção aplicada em produção.',
    }

    # --- Método 3.5: gate probabilístico + robustez H2 + EMOS H2 ----------
    inventario['metodo_3_5_gate_probabilistico'] = {
        'nome': 'Método 3.5 — gate diagnóstico de calibração probabilística (dispersão do ensemble RAW)',
        'objetivo_variavel': 'Diagnosticar se a dispersão dos 24 membros do CFSv2 RAW contém informação útil sobre o erro — não é uma correção.',
        'horizontes_avaliados': HORIZONTES,
        'amostra': {'n_por_horizonte': {str(h): gate['spread_error_ratio_por_horizonte'][str(h)]['n'] for h in HORIZONTES}},
        'regra_causal': 'Mesma base pareada causal da 2C.3C; nenhum ajuste de parâmetro.',
        'referencias_usadas': ['climatologia causal (CRPS/BSS)'],
        'metricas_principais_por_horizonte': {
            str(h): {
                'classificacao_gate_controlada_por_mes': gate['classificacao_gate_por_horizonte'][str(h)]['classificacao'],
                'pearson_resid_ic95': _ic_bloco(gate['spread_skill_month_controlled_retrospective_por_horizonte'][str(h)]['pearson_std_resid_vs_erro_abs_resid']),
                'pearson_resid_ic_classificacao': gate['spread_skill_month_controlled_retrospective_por_horizonte'][str(h)]['pearson_std_resid_vs_erro_abs_resid_ic_classificacao'],
            }
            for h in HORIZONTES
        },
        'decisao_cientifica_registrada': 'resultado_misto_revisar_por_horizonte_antes_de_decidir (próximo passo recomendado: %s); nenhuma média/voto majoritário decide por si só; Método 3.5 NÃO declarado aprovado por este gate.' % gate.get('proximo_passo_recomendado'),
        'limitacoes_status_operacional': 'H2 único horizonte com IC95% acima de zero na correlação spread×erro controlada por mês — demais horizontes classificados como spread pouco informativo (H1,H3-H6) ou potencialmente calibrável só H2.',
    }

    inventario['metodo_3_5_robustez_h2'] = {
        'nome': 'Método 3.5 — robustez do sinal spread×erro em H2',
        'objetivo_variavel': 'Testar se a associação residual spread×erro de H2 é robusta a leave-one-month-out/leave-one-season-out.',
        'horizontes_avaliados': [LEAD_H2],
        'amostra': {'n_h2': gate['spread_error_ratio_por_horizonte'][str(LEAD_H2)]['n']},
        'regra_causal': 'Mesma base causal do gate; nenhum refit de EMOS.',
        'referencias_usadas': ['gate probabilístico (congelado)'],
        'metricas_principais_por_horizonte': {
            str(LEAD_H2): {
                'classificacao_robustez': robustez['classificacao_robustez_h2'],
                'decisao_proximo_passo': robustez['decisao_final_emos_h2'],
            }
        },
        'decisao_cientifica_registrada': 'sinal_h2_robusto — recomendado prosseguir para o protocolo EMOS H2, nunca tratado como "modelo validado".',
        'limitacoes_status_operacional': 'Achado exploratório entre 6 horizontes testados, sem correção formal de multiplicidade (Bonferroni/FDR); robustez interna exigida antes de justificar novo modelo, não substitui essa correção.',
    }

    crps_medio = emos['crps_medio']
    boot = emos['bootstrap_crpss']
    dec = emos['decisao_criterio_pre_registrado']
    inventario['metodo_3_5_emos_h2'] = {
        'nome': 'Método 3.5 — EMOS H2 (Normal censurada em zero, componente dinâmico de spread)',
        'objetivo_variavel': 'Calibração probabilística dinâmica (média e variância) de H2 via EMOS, Z~N(mu,sigma²), Y=max(0,Z).',
        'horizontes_avaliados': [LEAD_H2],
        'amostra': {
            'n_treino_minimo': emos['n_treino_minimo_emos'],
            'n_final_avaliavel': emos['n_casos']['n_final'],
        },
        'regra_causal': 'init_date_treino < init_date_avaliada E target_month_treino < init_date_avaliada (mesma regra corrigida do 3.4, implementada independentemente).',
        'referencias_usadas': ['RAW (CRPS)', 'climatologia probabilística causal (CRPS)', 'EMOS d=0 (spread constante)'],
        'metricas_principais_por_horizonte': {
            str(LEAD_H2): {
                'crps_medio_emos_completo': crps_medio['emos_completo'],
                'crps_medio_emos_d0': crps_medio['emos_d0'],
                'crps_medio_raw': crps_medio['raw'],
                'crps_medio_climatologia': crps_medio['climatologia'],
                'CRPSS_vs_raw': _ic_bloco(boot['CRPSS_vs_raw']),
                'CRPSS_vs_climatologia': _ic_bloco(boot['CRPSS_vs_climatologia']),
                'CRPSS_spread_dinamico': _ic_bloco(boot['CRPSS_spread_dinamico']),
            }
        },
        'decisao_cientifica_registrada': dec,
        'limitacoes_status_operacional': 'Componente dinâmico de spread NÃO APROVADO: IC95% de CRPSS_spread_dinamico inclui zero E EMOS não supera a climatologia causal (IC95% de CRPSS_vs_climatologia inclui zero). EMOS supera o RAW (IC95% acima de zero), mas isso não é o critério de aprovação do protocolo. Método estritamente experimental — não promovido à operação.',
    }

    # Ressalva explícita (2ª rodada de auditoria, item 3) — preservada com
    # o valor exato lido da fonte, nunca reclassificada para esconder o
    # resultado isolado favorável nem para inflá-lo além do que o critério
    # conjunto já aprovado permite.
    skill_h1 = inventario['metodo_3_1_aditivo']['metricas_principais_por_horizonte']['1']['skill_vs_anomalia_reconstruida']
    inventario['metodo_3_1_aditivo']['ressalva_parcial_h1'] = {
        'classificacao': 'parcialmente_favoravel_isolado',
        'descricao': (
            'skill_vs_anomalia_reconstruida isolado em H1 tem IC95% totalmente acima de zero — '
            'resultado parcialmente favorável isolado, preservado explicitamente. Não satisfaz o '
            'critério conjunto de aprovação (que exige também RMSESS_climatologia simultaneamente '
            'acima de zero) — não é uma aprovação do Método 3.1 em H1, é um componente isolado do '
            'critério satisfeito.'
        ),
        'skill_vs_anomalia_reconstruida_h1': skill_h1,
    }

    inventario['decisao_consolidada_fase_2c3e'] = DECISAO_CONSOLIDADA_FASE_2C3E

    return inventario


# ══════════════════════════════════════════════════════════════════════════
# Seção C — comparabilidade de amostras
# ══════════════════════════════════════════════════════════════════════════

CLASSE_JA_AVALIADO = 'comparavel_e_ja_avaliado'
CLASSE_EM_PRINCIPIO_NAO_AVALIADO = 'comparavel_em_principio_mas_nao_avaliado'
CLASSE_NAO_COMPARAVEL_METRICA = 'nao_comparavel_diretamente_por_metrica_ou_variavel'
CLASSE_NAO_COMPARAVEL_DADOS = 'nao_comparavel_por_dados_ou_amostra'

CLASSIFICACOES_COMPARABILIDADE_VALIDAS = {
    CLASSE_JA_AVALIADO, CLASSE_EM_PRINCIPIO_NAO_AVALIADO,
    CLASSE_NAO_COMPARAVEL_METRICA, CLASSE_NAO_COMPARAVEL_DADOS,
}


def construir_comparabilidade_amostras():
    """Classifica cada par de métodos em uma de 4 categorias — nunca um
    booleano único. A classificação NUNCA depende do valor da interseção
    calculada (nenhum limiar escolhido a partir do resultado); depende só
    de (a) se já existe uma métrica pareada aprovada sobre essa amostra
    exata nos documentos 2C.3D, e (b) se os dois métodos produzem a MESMA
    família de métrica (determinística vs. probabilística) sobre a MESMA
    variável. Nenhum teste comparativo novo é calculado aqui — só a
    contagem de interseção de chaves, preservada sem transformação."""
    adit = _carregar_csv(CAMINHO_ADITIVA_CSV)
    mult = _carregar_csv(CAMINHO_MULT_CSV)
    mos = _carregar_csv(CAMINHO_MOS_CSV)
    emos = _carregar_csv(CAMINHO_EMOS_CSV)

    adit_ok = adit[adit['status_calibracao'] == 'ok']
    mult_ok = mult[mult['status_multiplicativo'] == 'ok']
    mos_ok = mos[mos['status_mos'] == 'ok']
    emos_ok = emos[emos['status_emos'] == 'ok']

    linhas = []

    # Pares com comparação pareada JÁ APROVADA internamente (skill_X_vs_Y
    # calculado sobre a amostra pareada exata nos documentos 2C.3D).
    PARES_JA_AVALIADOS = {
        ('aditivo', 'multiplicativo'): 'skill_multiplicativo_vs_aditivo (Método 3.2, seções 6/7/11)',
        ('aditivo', 'mos_linear'): 'skill_mos_vs_aditivo (Método 3.4, seções 10/11)',
    }
    # Pares deterministicos/mesma variável SEM comparação pareada já
    # aprovada — comparáveis EM PRINCÍPIO (mesma família de métrica,
    # observações comuns, previsões determinísticas), mas a comparação
    # pareada em si ainda não foi executada em nenhum documento aprovado.
    PARES_EM_PRINCIPIO_NAO_AVALIADOS = {
        ('mos_linear', 'multiplicativo'),
    }

    def _registrar(lead, nome_a, set_a, nome_b, set_b):
        inter = set_a & set_b
        chave = tuple(sorted((nome_a, nome_b)))
        if chave in PARES_JA_AVALIADOS:
            classificacao = CLASSE_JA_AVALIADO
            motivo = f'comparação pareada já aprovada existe: {PARES_JA_AVALIADOS[chave]}'
        elif chave in PARES_EM_PRINCIPIO_NAO_AVALIADOS:
            classificacao = CLASSE_EM_PRINCIPIO_NAO_AVALIADO
            motivo = (
                f'{nome_a} e {nome_b} têm observações comuns e previsões determinísticas sobre a mesma '
                'variável (mesma família de métrica, RMSE/skill) — a comparação pareada EM PRINCÍPIO é '
                'válida, mas ainda não foi calculada em nenhum documento aprovado; calcular uma nova métrica '
                'pareada está fora do escopo desta fase (2C.3E não desenvolve/ajusta/avalia novos contrastes).'
            )
        else:
            classificacao = CLASSE_EM_PRINCIPIO_NAO_AVALIADO
            motivo = (
                f'nenhuma comparação pareada já aprovada entre {nome_a} e {nome_b} nesta amostra; '
                'calcular uma nova métrica pareada está fora do escopo desta fase.'
            )
        linhas.append({
            'lead': lead,
            'metodo_a': nome_a,
            'n_a': len(set_a),
            'metodo_b': nome_b,
            'n_b': len(set_b),
            'n_intersecao': len(inter),
            'fracao_intersecao_sobre_menor': round(len(inter) / min(len(set_a), len(set_b)), 4) if min(len(set_a), len(set_b)) > 0 else None,
            'classificacao_comparabilidade': classificacao,
            'motivo': motivo,
        })

    for h in HORIZONTES:
        a = set(adit_ok[adit_ok['lead'] == h]['init_date'])
        m = set(mult_ok[mult_ok['lead'] == h]['init_date'])
        mo = set(mos_ok[mos_ok['lead'] == h]['init_date'])
        _registrar(h, 'aditivo', a, 'multiplicativo', m)
        _registrar(h, 'aditivo', a, 'mos_linear', mo)
        _registrar(h, 'multiplicativo', m, 'mos_linear', mo)

    # H2: EMOS H2 (probabilístico, CRPS) vs os três métodos determinísticos
    # (RMSE) — famílias de métrica diferentes sobre a mesma variável.
    # Classificado como NÃO COMPARÁVEL DIRETAMENTE POR MÉTRICA, nunca como
    # "impossível de comparar em princípio": CRPS e RMSE não são
    # diretamente intercambiáveis nos dados hoje calculados, mas isso não
    # afirma que os dois sistemas preditivos sejam incomparáveis sob uma
    # métrica comum adequadamente definida (ex.: CRPS determinístico
    # equivalente, ou pinball loss comum) — tal métrica comum não foi
    # calculada em nenhuma fase até aqui.
    e = set(emos_ok['init_date'])
    a2 = set(adit_ok[adit_ok['lead'] == LEAD_H2]['init_date'])
    m2 = set(mult_ok[mult_ok['lead'] == LEAD_H2]['init_date'])
    mo2 = set(mos_ok[mos_ok['lead'] == LEAD_H2]['init_date'])
    for nome_det, set_det in (('aditivo', a2), ('multiplicativo', m2), ('mos_linear', mo2)):
        inter = e & set_det
        linhas.append({
            'lead': LEAD_H2,
            'metodo_a': 'emos_h2',
            'n_a': len(e),
            'metodo_b': nome_det,
            'n_b': len(set_det),
            'n_intersecao': len(inter),
            'fracao_intersecao_sobre_menor': round(len(inter) / min(len(e), len(set_det)), 4) if min(len(e), len(set_det)) > 0 else None,
            'classificacao_comparabilidade': CLASSE_NAO_COMPARAVEL_METRICA,
            'motivo': (
                f'EMOS H2 reporta CRPS (probabilístico) e {nome_det} reporta RMSE (determinístico) sobre a '
                'mesma variável — métricas não diretamente intercambiáveis nos dados hoje calculados; isso '
                'NÃO afirma que os dois sistemas sejam incomparáveis em princípio sob uma métrica comum '
                'adequadamente definida, só que tal métrica comum não foi calculada em nenhuma fase até '
                'aqui; nenhuma comparação pareada já aprovada existe, e calcular uma nova está fora do '
                'escopo desta fase.'
            ),
        })

    return pd.DataFrame(linhas)


# ══════════════════════════════════════════════════════════════════════════
# Seção D — diagnóstico de habilidade preditiva H1–H6
# ══════════════════════════════════════════════════════════════════════════

def construir_diagnostico_habilidade(inventario):
    raw = inventario['raw_cfsv2_2c3c']['metricas_principais_por_horizonte']
    adit = inventario['metodo_3_1_aditivo']['metricas_principais_por_horizonte']
    mult = inventario['metodo_3_2_multiplicativo']['metricas_principais_por_horizonte']
    mos = inventario['metodo_3_4_mos_linear']['metricas_principais_por_horizonte']
    gate = inventario['metodo_3_5_gate_probabilistico']['metricas_principais_por_horizonte']

    diagnostico = {'por_horizonte': {}, 'nota_metodologica': (
        'RMSESS e CRPSS NUNCA combinados numa única classificação — são famílias de skill score '
        'distintas (determinística vs. probabilística). Precipitação absoluta e anomalia corrigida '
        'são leituras independentes (ver RAW 2C.3C, Seção 8 do protocolo). Amostra plena (RAW, N=240) '
        'e amostra comum/elegível (métodos calibrados, N menor por warm-up) nunca misturadas na mesma linha.'
    )}

    for h in HORIZONTES:
        hs = str(h)
        diagnostico['por_horizonte'][hs] = {
            'raw_rmsess_absoluto': raw[hs]['rmsess_absoluto'],
            'raw_rmsess_absoluto_ic_classificacao': raw[hs]['rmsess_absoluto_ic_classificacao'],
            'raw_rmsess_anomalia_corrigida': raw[hs]['rmsess_anomalia_corrigida'],
            'raw_rmsess_anomalia_corrigida_ic_classificacao': raw[hs]['rmsess_anomalia_corrigida_ic_classificacao'],
            'raw_crpss': raw[hs]['crpss'],
            'raw_crpss_ic_classificacao': raw[hs]['crpss_ic_classificacao'],
            'aditivo_skill_vs_anomalia_reconstruida': adit[hs]['skill_vs_anomalia_reconstruida'],
            'aditivo_skill_vs_anomalia_reconstruida_ic_classificacao': adit[hs]['skill_vs_anomalia_reconstruida_ic_classificacao'],
            'multiplicativo_skill_vs_anomalia_reconstruida': mult[hs]['skill_vs_anomalia_reconstruida'],
            'multiplicativo_skill_vs_anomalia_reconstruida_ic_classificacao': mult[hs]['skill_vs_anomalia_reconstruida_ic_classificacao'],
            'mos_linear_skill_vs_anomalia_reconstruida': mos[hs]['skill_vs_anomalia_reconstruida'],
            'mos_linear_skill_vs_anomalia_reconstruida_ic_classificacao': mos[hs]['skill_vs_anomalia_reconstruida_ic_classificacao'],
            'gate_classificacao_spread': gate[hs]['classificacao_gate_controlada_por_mes'],
        }

    # H2 recebe campos adicionais do EMOS (único horizonte com implementação
    # probabilística dinâmica completa).
    emos_m = inventario['metodo_3_5_emos_h2']['metricas_principais_por_horizonte'][str(LEAD_H2)]
    diagnostico['por_horizonte'][str(LEAD_H2)]['emos_h2_CRPSS_vs_raw'] = emos_m['CRPSS_vs_raw']
    diagnostico['por_horizonte'][str(LEAD_H2)]['emos_h2_CRPSS_vs_climatologia'] = emos_m['CRPSS_vs_climatologia']
    diagnostico['por_horizonte'][str(LEAD_H2)]['emos_h2_CRPSS_spread_dinamico'] = emos_m['CRPSS_spread_dinamico']

    # Leitura de lead-vs-perda-de-skill: só DESCRITIVA, nunca um teste
    # formal — compara RMSESS_absoluto do RAW entre H1 e H6 (mesma
    # métrica, mesma definição, amostra plena N=240 nos dois).
    diagnostico['leitura_lead_vs_skill_raw_absoluto'] = {
        'nota': 'Descritivo — compara RMSESS absoluto do RAW entre H1 e H6 (mesma métrica/definição/amostra plena); nunca um teste de significância sobre a diferença.',
        'rmsess_absoluto_h1': raw['1']['rmsess_absoluto']['estimativa'] if raw['1']['rmsess_absoluto'] else None,
        'rmsess_absoluto_h6': raw['6']['rmsess_absoluto']['estimativa'] if raw['6']['rmsess_absoluto'] else None,
    }

    return diagnostico


# ══════════════════════════════════════════════════════════════════════════
# Execução
# ══════════════════════════════════════════════════════════════════════════

def executar_diagnostico_2c3e():
    resultado = {'STOP_ON_FAILURE': False}

    inventario = construir_inventario_metodos()
    comparabilidade = construir_comparabilidade_amostras()
    diagnostico = construir_diagnostico_habilidade(inventario)

    # Sanidade mínima antes de gravar — nenhum artefato parcial é escrito
    # se algo essencial estiver ausente.
    metodos_esperados = {
        'raw_cfsv2_2c3c', 'metodo_3_1_aditivo', 'metodo_3_2_multiplicativo',
        'metodo_3_3_gate_qm', 'metodo_3_4_mos_linear',
        'metodo_3_5_gate_probabilistico', 'metodo_3_5_robustez_h2', 'metodo_3_5_emos_h2',
        'decisao_consolidada_fase_2c3e',
    }
    if set(inventario.keys()) != metodos_esperados:
        resultado['STOP_ON_FAILURE'] = True
        resultado['motivo'] = f'inventário incompleto: {set(inventario.keys()) ^ metodos_esperados}'
        return resultado

    if comparabilidade.empty or (comparabilidade['n_intersecao'] < 0).any():
        resultado['STOP_ON_FAILURE'] = True
        resultado['motivo'] = 'tabela de comparabilidade vazia ou com interseção negativa'
        return resultado

    if set(diagnostico['por_horizonte'].keys()) != {str(h) for h in HORIZONTES}:
        resultado['STOP_ON_FAILURE'] = True
        resultado['motivo'] = 'diagnóstico de habilidade não cobre H1-H6'
        return resultado

    DIRETORIO_SAIDA.mkdir(parents=True, exist_ok=True)

    inventario['data_geracao_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    with open(CAMINHO_INVENTARIO, 'w') as f:
        json.dump(inventario, f, ensure_ascii=False, indent=2)

    comparabilidade.to_csv(CAMINHO_COMPARABILIDADE, index=False)

    diagnostico['data_geracao_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    with open(CAMINHO_DIAGNOSTICO, 'w') as f:
        json.dump(diagnostico, f, ensure_ascii=False, indent=2)

    resultado['inventario_metodos'] = inventario
    resultado['comparabilidade_amostras_n_linhas'] = len(comparabilidade)
    resultado['diagnostico_habilidade'] = diagnostico
    return resultado


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--executar', action='store_true')
    args = parser.parse_args()

    if args.executar:
        resultado = executar_diagnostico_2c3e()
        if resultado['STOP_ON_FAILURE']:
            print(f"STOP_ON_FAILURE: {resultado.get('motivo')}")
            sys.exit(1)
        print(f'OK — artefatos gravados em {DIRETORIO_SAIDA}')
        print(f'  {CAMINHO_INVENTARIO.name}')
        print(f'  {CAMINHO_COMPARABILIDADE.name} ({resultado["comparabilidade_amostras_n_linhas"]} linhas)')
        print(f'  {CAMINHO_DIAGNOSTICO.name}')
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
