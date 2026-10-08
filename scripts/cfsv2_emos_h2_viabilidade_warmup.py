#!/usr/bin/env python3
"""
cfsv2_emos_h2_viabilidade_warmup.py — Fase 2C.3D: protocolo técnico do
EMOS para H2 (Método 3.5, item 10/6 do pedido de protocolo).

Calcula SOMENTE a viabilidade ESTRUTURAL do warm-up proposto
(`N_TREINO_MINIMO_EMOS = 120` pares válidos) e o gate de viabilidade
da escala (item 6): quantos pares H2 válidos existem ao longo do
tempo, a primeira `init_date` que alcançaria 120 pares de treino
causal, e o número final de previsões avaliáveis. NÃO ajusta `a/b/c/d`,
NÃO calcula CRPS/skill do EMOS, NÃO produz probabilidades calibradas —
ver docs/nmme-fase2c3d-protocolo-emos-h2.md.

Um "par H2 válido" exige, na própria `init_date` (tudo causal):
    - `climatologia_modelo_raw` (clim_modelo_media) disponível;
    - `climatologia_observada` (clim_media) disponível;
    - `spread_clim_modelo_mes` disponível e > 0 (climatologia EXPANSÍVEL
      do próprio `ensemble_std`, mesmo padrão causal de
      `v.climatologia_modelo_expansivel`, mas sobre o spread);
    - `erro_clim_sd_mes` disponível e > 0 (desvio-padrão EXPANSÍVEL
      causal de `erro_assinado`, mesmo padrão, usado como escala base
      da dispersão — item 5 do protocolo).

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
            'init_date': init_date, 'target_mes': int(row['target_mes']),
            'target_ano': int(row['target_ano']),
            'clim_modelo_media_disponivel': bool(pd.notna(clim_modelo_media)),
            'clim_media_disponivel': bool(pd.notna(clim_media)),
            'spread_clim_modelo_mes': spread_clim_modelo_mes,
            'erro_clim_sd_mes': erro_clim_sd_mes,
            'valido': bool(valido),
        })
    return pd.DataFrame(linhas)


def viabilidade_estrutural_h2(pares, n_treino_minimo=N_TREINO_MINIMO_EMOS):
    """Item 10 do protocolo — SOMENTE contagens estruturais: n_treino
    disponível (pares válidos ANTES de cada linha, nunca incluindo a
    própria linha), primeira `init_date` que alcança o warm-up, e
    quantas previsões seriam avaliáveis a partir daí (precisam
    TAMBÉM ser válidas na própria linha — mesma exigência do Método
    3.4). Nenhum CRPS/skill é calculado aqui."""
    n_treino_disponivel = pares['valido'].shift(1, fill_value=False).astype(int).cumsum()
    pares = pares.assign(n_treino_disponivel=n_treino_disponivel)

    elegiveis = pares[pares['n_treino_disponivel'] >= n_treino_minimo]
    primeira = elegiveis.iloc[0] if len(elegiveis) else None
    avaliaveis = elegiveis[elegiveis['valido']]

    return {
        'n_treino_minimo_emos': n_treino_minimo,
        'n_total_inicializacoes_h2': int(len(pares)),
        'n_pares_validos_total': int(pares['valido'].sum()),
        'primeira_init_date_elegivel': primeira['init_date'] if primeira is not None else None,
        'n_treino_disponivel_nessa_data': (int(primeira['n_treino_disponivel'])
                                            if primeira is not None else None),
        'n_previsoes_avaliaveis_final': int(len(avaliaveis)),
        'nota': 'Contagem puramente estrutural — nenhum CRPS/skill do EMOS foi calculado '
                '(item 10 do protocolo). Warm-up NÃO foi reduzido automaticamente mesmo que '
                'encurte a avaliação — qualquer ajuste exige revisão (item 10).',
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

    resultado = {
        'STOP_ON_FAILURE': False,
        'metodo': 'protocolo_emos_h2_viabilidade_estrutural_metodo_3_5',
        'viabilidade_estrutural_warmup': viabilidade_estrutural_h2(pares),
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
