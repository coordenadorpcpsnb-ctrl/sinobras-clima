#!/usr/bin/env python3
"""
Fase RN-1B — worker de captura, roda SEMPRE num processo Python isolado
(nunca importado por outro processo já com numpy/scipy carregados), para
que variáveis de ambiente (OPENBLAS_CORETYPE, OPENBLAS_NUM_THREADS)
definidas pelo processo pai tenham efeito ANTES do import de numpy/scipy.

NÃO modifica nenhuma fórmula, bound, tolerância ou critério do EMOS H2 —
só chama scripts/cfsv2_emos_h2_implementacao.py (produção, intocado) com
os MESMOS dois fixtures sintéticos dos testes que reprovaram no Job C,
copiados literalmente de tests/test_cfsv2_emos_h2_implementacao.py
(IndependenciaD0TestCase.test_d_sigma_d0_identico_ao_variar_ensemble_std_das_linhas_de_treino
e MutacaoObservacaoFuturaTestCase.test_a_mutar_observacao_da_linha_imediatamente_anterior_nao_afeta_avaliacao_mais_recente),
para poder capturar os campos ricos (res.success/status/message/fun/x/jac/
nit/nfev) que `python -m unittest` por si só não exporia — os testes
originais continuam existindo e passíveis de serem rodados normalmente,
sem nenhuma alteração.

Imprime UM objeto JSON por linha em stdout — o processo pai (driver) só
precisa ler stdout, nunca precisa importar numpy/scipy ele mesmo.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd
import threadpoolctl

import cfsv2_emos_h2_implementacao as emos
import cfsv2_validacao_cientifica as v


def _info_blas():
    infos = []
    for d in threadpoolctl.threadpool_info():
        if d.get('user_api') == 'blas':
            infos.append({k: d.get(k) for k in ('prefix', 'version', 'architecture', 'num_threads')})
    return infos


def _cpu_model():
    try:
        with open('/proc/cpuinfo') as fh:
            for linha in fh:
                if linha.startswith('model name'):
                    return linha.split(':', 1)[1].strip()
    except OSError:
        pass
    return None


def _info_ambiente():
    # aquecimento mínimo — só para forçar o carregamento preguiçoso do
    # BLAS antes de ler threadpoolctl, igual ao padrão já usado em
    # ci.yml; não tem efeito sobre nenhum cálculo real do EMOS H2
    # (já demonstrado na Fase ENSO-CI, BackendBlasEfetivoTestCase).
    _ = np.dot(np.ones(8), np.ones(8))
    return {
        'python': sys.version.split()[0],
        'numpy': np.__version__,
        'scipy': __import__('scipy').__version__,
        'cpu_model': _cpu_model(),
        'blas_libs': _info_blas(),
    }


# ───────────────────────────────────────────────────────────────────────
# Fixtures copiados literalmente dos testes reais (nenhum valor alterado)
# ───────────────────────────────────────────────────────────────────────

def _pares_independencia_d0(spread_fn):
    linhas = []
    for i in range(125):
        mes = (i % 12) + 1
        ano = 1990 + i // 12
        init_date = f'{ano}-{mes:02d}'
        target_p = v._periodo(init_date) + 1
        linhas.append({
            'init_date': init_date, 'target_month': str(target_p),
            'target_ano': target_p.year, 'target_mes': target_p.month,
            'observacao': 80.0 + 0.3 * i, 'ensemble_mean': 100.0 + 0.5 * i,
            'ensemble_std': spread_fn(i), 'membros': np.full(24, 100.0 + 0.5 * i),
            'climatologia_modelo_raw': 90.0, 'climatologia_observada': 70.0,
            'anom_ensemble': (100.0 + 0.5 * i) - 90.0,
            'spread_clim_modelo_mes': 15.0, 'erro_clim_sd_mes': 20.0,
            'spread_relativo': spread_fn(i) / 15.0,
            'tercil_33': 60.0, 'tercil_67': 90.0,
            'anos_hist_climatologia': np.linspace(50.0, 110.0, 25),
            'valido': True,
        })
    return pd.DataFrame(linhas)


def _pares_mutacao(n):
    linhas = []
    for i in range(n):
        mes = (i % 12) + 1
        ano = 1990 + i // 12
        init_date = f'{ano}-{mes:02d}'
        target_p = v._periodo(init_date) + 1
        linhas.append({
            'init_date': init_date, 'target_month': str(target_p),
            'target_ano': target_p.year, 'target_mes': target_p.month,
            'observacao': 80.0 + 0.3 * i, 'ensemble_mean': 100.0 + 0.5 * i,
            'ensemble_std': 15.0 + 0.1 * (i % 7), 'membros': np.full(24, 100.0 + 0.5 * i),
            'climatologia_modelo_raw': 90.0, 'climatologia_observada': 70.0,
            'anom_ensemble': (100.0 + 0.5 * i) - 90.0,
            'spread_clim_modelo_mes': 15.0, 'erro_clim_sd_mes': 20.0,
            'spread_relativo': (15.0 + 0.1 * (i % 7)) / 15.0,
            'tercil_33': 60.0, 'tercil_67': 90.0,
            'anos_hist_climatologia': np.linspace(50.0, 110.0, 25),
            'valido': True,
        })
    return linhas


def _linha_para_dict(linha, campos_extra):
    d = {c: linha.get(c) for c in campos_extra}
    for k, val in d.items():
        if isinstance(val, (np.floating, np.integer)):
            d[k] = val.item()
    return d


_CAMPOS_RICOS = (
    'status_emos', 'status_emos_completo', 'status_emos_d0',
    'success_completo', 'status_opt_completo', 'message_completo',
    'nit_completo', 'nfev_completo', 'crps_final_treino_completo',
    'a', 'b', 'gamma_c', 'd',
    'success_d0', 'status_opt_d0', 'message_d0',
    'nit_d0', 'nfev_d0', 'crps_final_treino_d0',
    'a_d0', 'b_d0', 'gamma_c_d0', 'sigma_d0', 'crps_d0',
)


def rodar_teste_independencia_d0():
    tabela_a = emos.construir_emos_h2_expanding(_pares_independencia_d0(lambda i: 15.0))
    tabela_b = emos.construir_emos_h2_expanding(_pares_independencia_d0(lambda i: 5.0 + 3.0 * (i % 11)))
    linha_a = tabela_a.sort_values('init_date').iloc[-1]
    linha_b = tabela_b.sort_values('init_date').iloc[-1]

    passou = (linha_a['status_emos_d0'] == emos.STATUS_OK
              and linha_b['status_emos_d0'] == emos.STATUS_OK)
    if passou:
        for campo in ('a_d0', 'b_d0', 'gamma_c_d0', 'c_d0', 'sigma_d0', 'mu_latente_d0', 'crps_d0'):
            if abs(float(linha_a[campo]) - float(linha_b[campo])) > 1e-6:
                passou = False
                break

    return {
        'teste': 'IndependenciaD0.test_d_sigma_d0_identico',
        'passou': bool(passou),
        'serie_a': _linha_para_dict(linha_a, _CAMPOS_RICOS),
        'serie_b': _linha_para_dict(linha_b, _CAMPOS_RICOS),
    }


def rodar_teste_mutacao_observacao_futura():
    linhas = _pares_mutacao(125)
    tabela_antes = emos.construir_emos_h2_expanding(pd.DataFrame(linhas))
    avaliacao_antes = tabela_antes.sort_values('init_date').iloc[-1].copy()

    linhas_mutadas = [dict(linha) for linha in linhas]
    linhas_mutadas[-2]['observacao'] = -999999.0
    tabela_depois = emos.construir_emos_h2_expanding(pd.DataFrame(linhas_mutadas))
    avaliacao_depois = tabela_depois[
        tabela_depois['init_date'] == avaliacao_antes['init_date']].iloc[0]

    passou = (avaliacao_antes['status_emos'] == emos.STATUS_OK
              and avaliacao_depois['status_emos'] == emos.STATUS_OK)
    if passou:
        for campo in ('a', 'b', 'gamma_c', 'd', 'a_d0', 'b_d0', 'gamma_c_d0',
                      'mu_latente', 'sigma', 'crps_emos', 'crps_d0'):
            if abs(float(avaliacao_antes[campo]) - float(avaliacao_depois[campo])) > 1e-6:
                passou = False
                break

    return {
        'teste': 'MutacaoObservacaoFutura.test_a_mutar_observacao',
        'passou': bool(passou),
        'avaliacao_antes': _linha_para_dict(avaliacao_antes, _CAMPOS_RICOS),
        'avaliacao_depois': _linha_para_dict(avaliacao_depois, _CAMPOS_RICOS),
    }


def main():
    resultado = {
        'ambiente': _info_ambiente(),
        'resultados': [
            rodar_teste_independencia_d0(),
            rodar_teste_mutacao_observacao_futura(),
        ],
    }
    print(json.dumps(resultado, ensure_ascii=False))


if __name__ == '__main__':
    main()
