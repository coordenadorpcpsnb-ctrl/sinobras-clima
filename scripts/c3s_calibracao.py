#!/usr/bin/env python3
"""
c3s_calibracao.py — Fase 2A.3: climatologia leakage-safe e correção de
viés (additive mean bias correction) para o hindcast completo SEAS5 /
São Bento.

Estende o desenho leakage-safe já validado em
c3s_hindcast.py::climatologia_ate_origem/bias_medio_ate_origem — mesmo
predicado central ("só entra observação/hindcast com data < origem",
nunca a própria origem nem dado futuro) — mas com mais estatísticas do
que aquelas funções expõem: climatologia aqui devolve também
mediana/p20/p33/p67/p80/n, e o bias devolve também `bias_training_n`
(nº de pares usados), necessário para a auditoria de leakage e para a
barreira MIN_ANOS_TREINO (Seção 4 da tarefa). Toda função aqui é pura
(DataFrame/valores -> dict) — não baixa nada, não abre GRIB.

MIN_ANOS_TREINO=10 (Seção 4): uma origem/lead só entra na avaliação
principal se tiver pelo menos este número de anos históricos válidos
tanto para climatologia quanto para o treino do bias. Nunca completado
com dado futuro — se faltar histórico, o status vem
SEM_HISTORICO_SUFICIENTE e quem orquestra decide excluir da avaliação
(nunca preencher com média global nem com dado posterior).
"""

import numpy as np
import pandas as pd

MIN_ANOS_TREINO = 10
STATUS_OK = 'OK'
STATUS_SEM_HISTORICO = 'SEM_HISTORICO_SUFICIENTE'


def climatologia_leakage_safe(chirps_df, origem, mes_alvo_calendario, min_anos_treino=MIN_ANOS_TREINO):
    """chirps_df: colunas [target_month (pandas.Period, freq='M'),
    chirps_prec_mm]. Usa SOMENTE linhas com target_month < origem e o
    MESMO mês calendário do alvo (Seção 10) — nunca o próprio mês-alvo
    nem qualquer observação posterior à origem, mesmo que já exista na
    série completa.

    Devolve dict: mean/median/p20/p33/p67/p80/n/status. Com n=0 (sem
    nenhum ano anterior — ex.: origem 1981-01, target jan/1981, não há
    nenhum janeiro anterior no hindcast) todas as estatísticas vêm None,
    nunca um valor inventado."""
    origem = pd.Period(origem, 'M')
    sub = chirps_df[(chirps_df['target_month'] < origem) &
                     (chirps_df['target_month'].apply(lambda p: p.month) == mes_alvo_calendario)]
    n = len(sub)
    if n == 0:
        return {'mean': None, 'median': None, 'p20': None, 'p33': None, 'p67': None, 'p80': None,
                'n': 0, 'status': STATUS_SEM_HISTORICO}
    v = sub['chirps_prec_mm'].to_numpy(dtype=float)
    return {
        'mean': float(np.mean(v)), 'median': float(np.median(v)),
        'p20': float(np.percentile(v, 20)), 'p33': float(np.percentile(v, 100 / 3)),
        'p67': float(np.percentile(v, 200 / 3)), 'p80': float(np.percentile(v, 80)),
        'n': n, 'status': STATUS_OK if n >= min_anos_treino else STATUS_SEM_HISTORICO,
    }


def bias_leakage_safe(ens_df, chirps_df, origem, mes_alvo_calendario, lead, min_anos_treino=MIN_ANOS_TREINO):
    """ens_df: colunas [init_date (Period), target_month (Period), lead,
    ens_mean_raw] — 1 linha por (origem, lead) já agregada (média dos 25
    membros). chirps_df: colunas [target_month, chirps_prec_mm].

    Mesma regra de c3s_hindcast.py::bias_medio_ate_origem — só pares com
    `init_date < origem` (a própria origem NUNCA entra — Seção 13) e
    mesmo lead/mês-calendário-alvo — mas também devolve `n` (nº de
    pares usados, exposto aqui como bias_training_n para a auditoria de
    leakage), que a função original não tinha.

    bias_mm = mean(ens_mean_raw_passado - chirps_observado_passado).
    corrected_member = max(0, raw_member - bias_mm) é aplicado depois,
    por quem orquestra (ver aplicar_bias_a_membro) — a um membro de
    cada vez, sempre o MESMO bias para todos os membros da origem
    naquele lead/mês (Seção 12)."""
    origem = pd.Period(origem, 'M')
    f = ens_df[(ens_df['lead'] == lead) & (ens_df['init_date'] < origem) &
               (ens_df['target_month'].apply(lambda p: p.month) == mes_alvo_calendario)]
    if f.empty:
        return {'bias_mm': None, 'n': 0, 'status': STATUS_SEM_HISTORICO}
    m = f.merge(chirps_df[['target_month', 'chirps_prec_mm']], on='target_month', how='inner')
    n = len(m)
    if n == 0:
        return {'bias_mm': None, 'n': 0, 'status': STATUS_SEM_HISTORICO}
    bias_mm = float((m['ens_mean_raw'] - m['chirps_prec_mm']).mean())
    return {'bias_mm': bias_mm, 'n': n, 'status': STATUS_OK if n >= min_anos_treino else STATUS_SEM_HISTORICO}


def aplicar_bias_a_membro(valor_raw_mm, bias_mm):
    """corrected_member = max(0, raw_member - bias) — precipitação
    negativa não é física (Seção 12). Aplicado membro a membro, sempre
    com o mesmo bias_mm (calculado uma vez por origem/lead)."""
    return max(0.0, float(valor_raw_mm) - float(bias_mm))
