#!/usr/bin/env python3
"""
cfsv2_emos_h2_viabilidade_warmup.py — Fase 2C.3D: protocolo técnico do
EMOS para H2 (Método 3.5, item 10/6 do pedido de protocolo).

Calcula SOMENTE a viabilidade ESTRUTURAL do warm-up proposto
(`N_TREINO_MINIMO_EMOS = 120` pares válidos) e o gate de viabilidade
da escala (item 6): quantos pares H2 válidos existem ao longo do
tempo, a primeira `init_date` que alcançaria 120 pares de treino
REALMENTE verificáveis, e o número final de previsões avaliáveis. NÃO
ajusta `a/b/c/d`, NÃO calcula CRPS/skill do EMOS, NÃO produz
probabilidades calibradas — ver docs/nmme-fase2c3d-protocolo-emos-h2.md.

Um "par H2 válido" exige, na própria `init_date` (tudo causal):
    - `climatologia_modelo_raw` (clim_modelo_media) disponível;
    - `climatologia_observada` (clim_media) disponível;
    - `spread_clim_modelo_mes` disponível e > 0 (climatologia EXPANSÍVEL
      do próprio `ensemble_std`, mesmo padrão causal de
      `v.climatologia_modelo_expansivel`, mas sobre o spread);
    - `erro_clim_sd_mes` disponível e > 0 (desvio-padrão EXPANSÍVEL
      causal de `erro_assinado`, mesmo padrão, usado como escala base
      da dispersão — item 5 do protocolo).

CORREÇÃO DE LEAKAGE OBSERVACIONAL (revisão pós-commit `be31da1`): como
H2 tem `target_month = init_date + 1 mês`, uma linha de treino com
`init_date_treino < init_date_avaliada` pode ainda assim ter
`target_month_treino >= init_date_avaliada` — ou seja, sua observação
(a variável resposta supervisionada: `obs_prec_mm`/`erro_assinado`,
nunca `ensemble_mean`/`ensemble_std`, que existem desde a própria
`init_date_treino`) não estaria verificada/disponível no momento da
inicialização avaliada. Usar essa linha no ajuste seria leakage de
verificação. Por isso, uma linha só entra no treino do EMOS se,
SIMULTANEAMENTE:
    1. `init_date_treino < init_date_avaliada`;
    2. `target_month_treino < init_date_avaliada` (condição PRINCIPAL —
       é a disponibilidade da observação verificada que importa para
       um ajuste supervisionado, não só a disponibilidade do forecast).
Nunca `target_month_treino <= init_date_avaliada` (ainda permitiria
usar a observação do próprio mês da inicialização avaliada — a data
exata de disponibilidade intramensal não foi demonstrada, então a
regra conservadora usa `<` estrito).

Roda com:
    python scripts/cfsv2_emos_h2_viabilidade_warmup.py --executar
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import cfsv2_gate_calibracao_probabilistica as g  # noqa: E402
import cfsv2_validacao_cientifica as v  # noqa: E402

DIRETORIO_SAIDA = g.DIRETORIO_SAIDA
CAMINHO_METRICAS_JSON = DIRETORIO_SAIDA / 'emos_h2_viabilidade_warmup_2c3d.json'

LEAD_H2 = 2
N_TREINO_MINIMO_EMOS = 120   # pré-registrado — ver item 10 do protocolo
NOMES_MES = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']


def _indice_causal_por_mes(tabela, lead, coluna):
    """Núcleo ÚNICO do padrão causal já usado em
    `v.climatologia_modelo_expansivel` (mesma inicialização NUNCA
    entra na própria climatologia; só meses-calendário iguais ao de
    `init_date`, estritamente anteriores) — generalizado para
    qualquer coluna numérica, reaproveitado para spread e para erro,
    nunca duas implementações paralelas do mesmo filtro causal."""
    sub = tabela[tabela['lead'] == lead][['init_date', coluna]].dropna(subset=[coluna])
    sub = sub.assign(_p=pd.PeriodIndex(sub['init_date'], freq='M'))

    def calcular(init_date):
        init_p = v._periodo(init_date)
        mascara = (sub['_p'].dt.month == init_p.month) & (sub['_p'] < init_p)
        elegiveis = sub[mascara]
        return elegiveis[coluna]

    return calcular


def construir_pares_h2_com_validade(tabela_ensemble, base_enriquecida):
    """1 linha por init_date de H2, em ordem causal, com a validade do
    par (item 1-6 do protocolo) — NUNCA ajusta nenhum parâmetro, só
    audita disponibilidade causal."""
    sub = tabela_ensemble[tabela_ensemble['lead'] == LEAD_H2].copy()
    sub = sub.assign(_p=pd.PeriodIndex(sub['init_date'], freq='M')).sort_values('_p').reset_index(drop=True)

    clim_por_init = base_enriquecida[base_enriquecida['lead'] == LEAD_H2].drop_duplicates(
        'init_date').set_index('init_date')[['clim_media', 'clim_modelo_media']]

    calc_spread = _indice_causal_por_mes(tabela_ensemble, LEAD_H2, 'ensemble_std')
    calc_erro = _indice_causal_por_mes(tabela_ensemble, LEAD_H2, 'erro_assinado')

    linhas = []
    for _, row in sub.iterrows():
        init_date = row['init_date']
        clim_modelo_media = clim_por_init['clim_modelo_media'].get(init_date)
        clim_media = clim_por_init['clim_media'].get(init_date)

        spread_hist = calc_spread(init_date)
        spread_clim_modelo_mes = float(spread_hist.mean()) if len(spread_hist) >= 1 else None

        erro_hist = calc_erro(init_date)
        erro_clim_sd_mes = float(erro_hist.std(ddof=1)) if len(erro_hist) >= 2 else None

        valido = (
            pd.notna(clim_modelo_media) and pd.notna(clim_media)
            and spread_clim_modelo_mes is not None and spread_clim_modelo_mes > 0
            and erro_clim_sd_mes is not None and erro_clim_sd_mes > 0
        )
        linhas.append({
            'init_date': init_date, 'target_month': row['target_month'],
            'target_mes': int(row['target_mes']), 'target_ano': int(row['target_ano']),
            'clim_modelo_media_disponivel': bool(pd.notna(clim_modelo_media)),
            'clim_media_disponivel': bool(pd.notna(clim_media)),
            'spread_clim_modelo_mes': spread_clim_modelo_mes,
            'erro_clim_sd_mes': erro_clim_sd_mes,
            'valido': bool(valido),
        })
    return pd.DataFrame(linhas)


def _contar_treino_emos_por_linha(pares):
    """Núcleo ÚNICO da regra causal corrigida (item 2/4 da revisão) —
    para cada `init_date_avaliada`, conta as linhas de treino válidas
    que satisfazem SIMULTANEAMENTE `init_date_treino <
    init_date_avaliada` E `target_month_treino < init_date_avaliada`
    (a condição de disponibilidade da OBSERVAÇÃO verificada, principal
    para um ajuste supervisionado — nunca só a disponibilidade do
    forecast). Implementado por comparação explícita de `Period`,
    nunca por deslocamento posicional (`shift`), que assumiria
    implicitamente uma defasagem fixa entre `init_date` e
    `target_month` sem checar."""
    p_init = pd.PeriodIndex(pares['init_date'], freq='M')
    p_target = pd.PeriodIndex(pares['target_month'], freq='M')
    valido = pares['valido'].to_numpy()

    n_treino_emos, max_init_treino, max_target_treino = [], [], []
    for i in range(len(pares)):
        avaliada = p_init[i]
        mascara = valido & (p_init < avaliada) & (p_target < avaliada)
        n_treino_emos.append(int(mascara.sum()))
        if mascara.any():
            max_init_treino.append(p_init[mascara].max())
            max_target_treino.append(p_target[mascara].max())
        else:
            max_init_treino.append(None)
            max_target_treino.append(None)

    return pares.assign(
        n_treino_emos=n_treino_emos,
        max_init_date_treino=[str(x) if x is not None else None for x in max_init_treino],
        max_target_month_treino=[str(x) if x is not None else None for x in max_target_treino],
        # auditoria estrutural REDUNDANTE (item 4) — nunca decide por si só,
        # só confirma que a condição mais fraca também se sustenta.
        _init_date_treino_ok_redundante=[
            (m is None) or (pd.Period(m, freq='M') < p_init[i]) for i, m in enumerate(max_init_treino)
        ],
    )


def _auditar_sem_leakage_observacional(pares_com_contagem):
    """Item 6 da revisão — para toda linha que entraria na avaliação
    principal (ver `viabilidade_estrutural_h2`), confirma
    `max_target_month_treino < init_date_avaliada`. Nunca assumido —
    verificado linha a linha; qualquer violação é STOP-ON-FAILURE."""
    violacoes = []
    p_init = pd.PeriodIndex(pares_com_contagem['init_date'], freq='M')
    for i, row in pares_com_contagem.reset_index(drop=True).iterrows():
        if row['max_target_month_treino'] is None:
            continue
        if not (pd.Period(row['max_target_month_treino'], freq='M') < p_init[i]):
            violacoes.append({'init_date_avaliada': row['init_date'],
                               'max_target_month_treino': row['max_target_month_treino']})
    return {'ok': len(violacoes) == 0, 'violacoes': violacoes}


def viabilidade_estrutural_h2(pares, n_treino_minimo=N_TREINO_MINIMO_EMOS):
    """Item 4/10 da revisão — SOMENTE contagens estruturais, com a
    regra causal CORRIGIDA: `n_treino_emos` exige
    `target_month_treino < init_date_avaliada` (disponibilidade da
    OBSERVAÇÃO verificada), não só `init_date_treino <
    init_date_avaliada` (disponibilidade do forecast — insuficiente
    para um ajuste supervisionado). Primeira `init_date` que alcança o
    warm-up, e quantas previsões seriam avaliáveis a partir daí
    (precisam TAMBÉM ser válidas na própria linha). Nenhum CRPS/skill
    é calculado aqui — e o número relatado NUNCA é assumido a priori,
    sempre recalculado programaticamente a partir da regra acima."""
    pares = _contar_treino_emos_por_linha(pares)

    elegiveis = pares[pares['n_treino_emos'] >= n_treino_minimo]
    primeira = elegiveis.iloc[0] if len(elegiveis) else None
    avaliaveis = elegiveis[elegiveis['valido']]

    auditoria_leakage = _auditar_sem_leakage_observacional(avaliaveis)

    # Diagnóstico comparativo (item 4 do pedido de revisão): quantas
    # linhas a regra ANTIGA (só init_date_treino < init_date_avaliada,
    # via posição imediatamente anterior) teria incluído indevidamente
    # — nunca usado para decidir nada, só para registrar o tamanho do
    # problema corrigido.
    p_init = pd.PeriodIndex(pares['init_date'], freq='M')
    p_target = pd.PeriodIndex(pares['target_month'], freq='M')
    valido = pares['valido'].to_numpy()
    n_linhas_indevidas_pela_regra_antiga = 0
    for i in range(len(pares)):
        avaliada = p_init[i]
        indevida = valido & (p_init < avaliada) & ~(p_target < avaliada)
        n_linhas_indevidas_pela_regra_antiga += int(indevida.sum())

    return {
        'n_treino_minimo_emos': n_treino_minimo,
        'n_total_inicializacoes_h2': int(len(pares)),
        'n_pares_validos_total': int(pares['valido'].sum()),
        'primeira_init_date_elegivel': primeira['init_date'] if primeira is not None else None,
        'n_treino_emos_nessa_data': (int(primeira['n_treino_emos'])
                                      if primeira is not None else None),
        'max_init_date_treino_nessa_data': (primeira['max_init_date_treino']
                                             if primeira is not None else None),
        'max_target_month_treino_nessa_data': (primeira['max_target_month_treino']
                                                if primeira is not None else None),
        'n_previsoes_avaliaveis_final': int(len(avaliaveis)),
        'auditoria_sem_leakage_observacional': auditoria_leakage,
        'n_linhas_indevidamente_incluidas_pela_regra_antiga_total': n_linhas_indevidas_pela_regra_antiga,
        'nota': 'Contagem puramente estrutural — nenhum CRPS/skill do EMOS foi calculado '
                '(item 10 do protocolo). Warm-up NÃO foi reduzido automaticamente mesmo que '
                'encurte a avaliação — qualquer ajuste exige revisão (item 10). Regra causal '
                'corrigida (revisão pós-be31da1): exige target_month_treino < '
                'init_date_avaliada, não só init_date_treino < init_date_avaliada.',
    }


def gate_viabilidade_escala(pares):
    """Item 6 do protocolo — confirma que `spread_clim_modelo_mes` e
    `erro_clim_sd_mes` são > 0 nos casos elegíveis, e reporta a
    distribuição por mês (SEM escolher nenhum piso baseado em
    desempenho — isso é proibido pelo item 6)."""
    validos = pares[pares['valido']]
    por_mes = {}
    for mes in range(1, 13):
        sub = validos[validos['target_mes'] == mes]
        if len(sub) == 0:
            por_mes[mes] = {'mes': mes, 'mes_nome': NOMES_MES[mes - 1], 'n': 0}
            continue
        por_mes[mes] = {
            'mes': mes, 'mes_nome': NOMES_MES[mes - 1], 'n': int(len(sub)),
            'spread_clim_modelo_mes_minimo': float(sub['spread_clim_modelo_mes'].min()),
            'spread_clim_modelo_mes_mediana': float(sub['spread_clim_modelo_mes'].median()),
            'erro_clim_sd_mes_minimo': float(sub['erro_clim_sd_mes'].min()),
            'erro_clim_sd_mes_mediana': float(sub['erro_clim_sd_mes'].median()),
        }
    return {
        'n_casos_validos_checados': int(len(validos)),
        'todos_spread_clim_modelo_mes_positivos': bool((validos['spread_clim_modelo_mes'] > 0).all()),
        'todos_erro_clim_sd_mes_positivos': bool((validos['erro_clim_sd_mes'] > 0).all()),
        'distribuicao_por_mes': por_mes,
        'nota': 'Nenhum piso numérico foi escolhido com base em desempenho (proibido pelo '
                'item 6 do protocolo) — só reporta a distribuição observada, para revisão.',
    }


def executar_viabilidade():
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
        return {'STOP_ON_FAILURE': True, 'motivo': 'auditoria de 24 membros reprovada'}

    base_enriquecida = v._enriquecer_com_climatologia(base, chirps_df)
    pares = construir_pares_h2_com_validade(tabela_ensemble, base_enriquecida)

    viabilidade = viabilidade_estrutural_h2(pares)
    if not viabilidade['auditoria_sem_leakage_observacional']['ok']:
        return {'STOP_ON_FAILURE': True,
                'motivo': 'leakage observacional detectado — alguma previsão avaliável tem '
                          'max_target_month_treino >= init_date_avaliada',
                'detalhe': viabilidade['auditoria_sem_leakage_observacional']}

    resultado = {
        'STOP_ON_FAILURE': False,
        'metodo': 'protocolo_emos_h2_viabilidade_estrutural_metodo_3_5',
        'viabilidade_estrutural_warmup': viabilidade,
        'gate_viabilidade_escala': gate_viabilidade_escala(pares),
        'nenhum_parametro_emos_ajustado': True,
        'nenhum_crps_emos_calculado': True,
        'nenhuma_probabilidade_calibrada_produzida': True,
        'data_geracao_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    return resultado


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--executar', action='store_true')
    args = ap.parse_args()
    if not args.executar:
        ap.print_help()
        return

    resultado = executar_viabilidade()
    DIRETORIO_SAIDA.mkdir(parents=True, exist_ok=True)
    CAMINHO_METRICAS_JSON.write_text(json.dumps(resultado, indent=2, ensure_ascii=False, default=str))
    print(f"  ✅ {CAMINHO_METRICAS_JSON.relative_to(ROOT)}")
    if resultado.get('STOP_ON_FAILURE'):
        print(f"\n❌ STOP_ON_FAILURE: {resultado.get('motivo')}")
        return
    v_ = resultado['viabilidade_estrutural_warmup']
    print(f"  primeira_init_date_elegivel = {v_['primeira_init_date_elegivel']}")
    print(f"  n_previsoes_avaliaveis_final = {v_['n_previsoes_avaliaveis_final']}")


if __name__ == '__main__':
    main()
