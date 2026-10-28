#!/usr/bin/env python3
"""
tests/test_cfsv2_emos_h2_implementacao.py — Fase 2C.3D: implementação
real do EMOS H2 (Método 3.5), seguindo
`docs/nmme-fase2c3d-protocolo-emos-h2.md`.

Cobre: CRPS analítico vs. integração numérica direta (protocolo, seção
8/24, 5 tipos de caso, tolerância 1e-6); propriedades algébricas da
distribuição (censura em zero, `E[Y]>=mu_latente`, `Q(p)>=0`); a
regra causal de treino (exemplo literal H2 2003-01, reaproveitando
`mos._indices_treino_causal`); anti-leakage por mutação de observação
futura; independência do ajuste `d=0` (estrutural e por construção de
cenário sintético); disparo de STOP-ON-FAILURE em não-convergência e
em solução numericamente inválida; e smoke test com dados reais.

RN-2B (estabilização científica da CI): os fixtures de
IndependenciaD0TestCase/MutacaoObservacaoFuturaTestCase passaram a usar
ruído determinístico (`_ruido_determinista`), eliminando o colapso de
resíduo/sigma que levava `gamma_c` ao limite inferior exato — ver
docs/enso-ci-emos-h2-auditoria-diagnostica.md. Esse regime extremo
continua coberto, com os fixtures ORIGINAIS intactos, em
`EstresseNumericoFronteiraGammaCTestCase`.

Roda com:
    python -m unittest tests.test_cfsv2_emos_h2_implementacao -v
"""

import hashlib
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import scipy
from scipy.integrate import quad

try:
    import threadpoolctl  # RN-2D — só diagnóstico, nunca decide nada (ver item 5)
except ImportError:
    threadpoolctl = None

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import cfsv2_calibracao_mos_linear as mos  # noqa: E402
import cfsv2_emos_h2_implementacao as emos  # noqa: E402
import cfsv2_validacao_cientifica as v  # noqa: E402


def _ruido_determinista(n, seed, escala):
    """RN-2B — ruído gaussiano determinístico (mesma seed => mesmo
    ruído sempre) para dar variância de resíduo genuína aos fixtures
    de propriedade (IndependenciaD0/MutacaoObservacaoFutura), evitando
    o colapso de sigma/gamma_c documentado em
    docs/enso-ci-emos-h2-auditoria-diagnostica.md. Nunca usado no
    fixture degenerado original, preservado intacto em
    EstresseNumericoFronteiraGammaCTestCase."""
    return np.random.default_rng(seed).normal(0.0, escala, n)


class CrpsAnaliticoTestCase(unittest.TestCase):
    """Protocolo, seção 8/24 — fórmula fechada do CRPS tem que
    concordar com integração numérica direta de
    `∫(F_Y(x) - 1{x>=y})² dx`, tolerância 1e-6, para os 5 tipos de caso
    pré-registrados."""

    def _crps_numerico(self, y, mu_latente, sigma):
        def integrando(x):
            fx = float(emos.cdf_censurada(np.array([x]), mu_latente, sigma)[0])
            indicador = 1.0 if x >= y else 0.0
            return (fx - indicador) ** 2
        limite_superior = mu_latente + 60 * sigma + 60
        valor, _ = quad(integrando, 0, limite_superior, limit=400)
        return valor

    def test_a_y_igual_zero(self):
        a = emos.crps_normal_censurada(0.0, 5.0, 10.0)
        b = self._crps_numerico(0.0, 5.0, 10.0)
        self.assertAlmostEqual(a, b, delta=1e-6)

    def test_b_mu_latente_negativo(self):
        a = emos.crps_normal_censurada(3.0, -8.0, 4.0)
        b = self._crps_numerico(3.0, -8.0, 4.0)
        self.assertAlmostEqual(a, b, delta=1e-6)

    def test_c_mu_latente_positivo(self):
        a = emos.crps_normal_censurada(15.0, 12.0, 6.0)
        b = self._crps_numerico(15.0, 12.0, 6.0)
        self.assertAlmostEqual(a, b, delta=1e-6)

    def test_d_sigma_pequeno(self):
        a = emos.crps_normal_censurada(5.0, 5.2, 0.3)
        b = self._crps_numerico(5.0, 5.2, 0.3)
        self.assertAlmostEqual(a, b, delta=1e-6)

    def test_e_sigma_grande(self):
        a = emos.crps_normal_censurada(50.0, 10.0, 80.0)
        b = self._crps_numerico(50.0, 10.0, 80.0)
        self.assertAlmostEqual(a, b, delta=1e-6)


class PropriedadesAlgebricasTestCase(unittest.TestCase):
    """Protocolo, seções 2/4/6 — propriedades que têm que valer SEMPRE,
    não só numericamente observadas em um caso."""

    def test_a_e_y_sempre_maior_ou_igual_mu_latente(self):
        rng = np.random.default_rng(0)
        for _ in range(200):
            mu = rng.uniform(-50, 50)
            sigma = rng.uniform(0.1, 50)
            e_y = emos.media_preditiva_censurada(mu, sigma)
            self.assertGreaterEqual(e_y, mu - 1e-12)

    def test_b_quantil_nunca_negativo(self):
        rng = np.random.default_rng(1)
        for _ in range(200):
            mu = rng.uniform(-50, 50)
            sigma = rng.uniform(0.1, 50)
            p = rng.uniform(0.0001, 0.9999)
            q = emos.quantil_censurado(p, mu, sigma)
            self.assertGreaterEqual(q, -1e-9)

    def test_c_prob_zero_e_f_y_de_zero_coincidem(self):
        mu, sigma = -3.0, 7.0
        self.assertAlmostEqual(emos.prob_zero(mu, sigma),
                                float(emos.cdf_censurada(np.array([0.0]), mu, sigma)[0]), places=12)

    def test_d_mid_pit_em_zero_e_metade_da_massa(self):
        mu, sigma = 2.0, 5.0
        pit0 = emos.mid_pit(np.array([0.0]), mu, sigma)[0]
        self.assertAlmostEqual(pit0, emos.prob_zero(mu, sigma) / 2.0, places=12)


class RegraCausalTreinoTestCase(unittest.TestCase):
    """Protocolo, seção 11/24 — exemplo literal H2 2003-01: init=2002-11
    (target=2002-12) permitido; init=2002-12 (target=2003-01) proibido.
    Testado diretamente sobre `construir_emos_h2_expanding`, reaproveitando
    a MESMA regra causal já usada no Método 3.4 (nunca uma segunda
    implementação)."""

    def _pares_sinteticos(self, n, mes_inicial=1, ano_inicial=1990):
        linhas = []
        for i in range(n):
            mes = ((mes_inicial - 1 + i) % 12) + 1
            ano = ano_inicial + (mes_inicial - 1 + i) // 12
            init_date = f'{ano}-{mes:02d}'
            target_p = v._periodo(init_date) + 1
            linhas.append({
                'init_date': init_date, 'target_month': str(target_p),
                'target_ano': target_p.year, 'target_mes': target_p.month,
                'observacao': 80.0 + 0.3 * i, 'ensemble_mean': 100.0 + 0.5 * i,
                'ensemble_std': 15.0, 'membros': np.full(24, 100.0 + 0.5 * i),
                'climatologia_modelo_raw': 90.0, 'climatologia_observada': 70.0,
                'anom_ensemble': (100.0 + 0.5 * i) - 90.0,
                'spread_clim_modelo_mes': 15.0, 'erro_clim_sd_mes': 20.0,
                'spread_relativo': 1.0,
                'tercil_33': 60.0, 'tercil_67': 90.0,
                'anos_hist_climatologia': np.linspace(50.0, 110.0, 25),
                'valido': True,
            })
        return pd.DataFrame(linhas)

    def test_a_exemplo_literal_2003_01(self):
        pares = self._pares_sinteticos(160)
        tabela = emos.construir_emos_h2_expanding(pares)
        linha_2003_01 = tabela[tabela['init_date'] == '2003-01'].iloc[0]
        self.assertEqual(linha_2003_01['status_emos'], emos.STATUS_OK)
        self.assertLess(v._periodo(linha_2003_01['max_target_month_treino']), v._periodo('2003-01'))
        # a linha de treino mais recente usada tem que ser 2002-11
        # (target=2002-12), nunca 2002-12 (target=2003-01)
        self.assertEqual(linha_2003_01['max_init_date_treino'], '2002-11')

    def test_b_n_treino_emos_bate_com_a_regra_corrigida(self):
        pares = self._pares_sinteticos(160)
        tabela = emos.construir_emos_h2_expanding(pares)
        linha_2003_01 = tabela[tabela['init_date'] == '2003-01'].iloc[0]
        # Em vez de fixar o número esperado de pares de treino, comparamos
        # com a contagem feita pela regra ANTIGA (só init_date_treino <
        # init_date_avaliada) menos a única linha cujo target_month ainda
        # não se qualificava (2002-12, target=2003-01).
        avaliada_p = v._periodo('2003-01')
        pares_validos = pares[pares['valido']]
        n_regra_antiga = int((pd.PeriodIndex(pares_validos['init_date'], freq='M') < avaliada_p).sum())
        self.assertEqual(linha_2003_01['n_treino_emos'], n_regra_antiga - 1,
                          "a regra corrigida exclui exatamente 1 linha (2002-12) que a regra "
                          "antiga indevidamente incluiria")


class CrpsFinalTreinoTestCase(unittest.TestCase):
    """Auditoria externa, item 1 — `crps_final_treino_completo`/`_d0`
    registrados para toda tentativa de ajuste (protocolo, seção 16.4),
    finitos quando a otimização converge, e numericamente iguais a
    `res.fun` (o valor da função objetivo na solução) — nunca
    confundidos com `crps_emos`/`crps_d0` (CRPS retrospectivo,
    calculado só sobre a observação avaliada, fora da amostra de
    treino que o otimizador de fato minimizou)."""

    def _pares(self, n):
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
                'ensemble_std': 15.0, 'membros': np.full(24, 100.0 + 0.5 * i),
                'climatologia_modelo_raw': 90.0, 'climatologia_observada': 70.0,
                'anom_ensemble': (100.0 + 0.5 * i) - 90.0,
                'spread_clim_modelo_mes': 15.0, 'erro_clim_sd_mes': 20.0,
                'spread_relativo': 1.0,
                'tercil_33': 60.0, 'tercil_67': 90.0,
                'anos_hist_climatologia': np.linspace(50.0, 110.0, 25),
                'valido': True,
            })
        return pd.DataFrame(linhas)

    def test_a_registrado_e_finito_para_avaliacao_ok(self):
        pares = self._pares(130)
        tabela = emos.construir_emos_h2_expanding(pares)
        ok = tabela[tabela['status_emos'] == emos.STATUS_OK]
        self.assertGreater(len(ok), 0)
        self.assertTrue(np.isfinite(ok['crps_final_treino_completo']).all())
        self.assertTrue(np.isfinite(ok['crps_final_treino_d0']).all())

    def test_b_registrado_mesmo_quando_fitting_e_tentado_mas_falha(self):
        """`crps_final_treino_*` precisa existir mesmo para ajustes que
        NÃO chegaram a status_emos_completo/d0=='ok' — o registro
        obrigatório da seção 16.4 do protocolo não é condicional a
        sucesso."""
        pares = self._pares(130)
        tabela = emos.construir_emos_h2_expanding(pares)
        tentativas = tabela[tabela['n_treino_emos'] >= emos.N_TREINO_MINIMO_EMOS]
        tentativas = tentativas[tentativas['status_emos'] != emos.STATUS_PAR_INVALIDO]
        self.assertGreater(len(tentativas), 0)
        self.assertEqual(int(tentativas['crps_final_treino_completo'].isna().sum()), 0,
                          "toda tentativa de ajuste completo precisa ter crps_final registrado, "
                          "mesmo quando o ajuste falha")
        self.assertEqual(int(tentativas['crps_final_treino_d0'].isna().sum()), 0)

    def test_c_crps_final_treino_e_numericamente_igual_a_res_fun(self):
        pares = self._pares(130)
        pares_p = pares.assign(_p=pd.PeriodIndex(pares['init_date'], freq='M')).sort_values('_p')
        tabela = emos.construir_emos_h2_expanding(pares)
        linha = tabela[tabela['status_emos'] == emos.STATUS_OK].sort_values('init_date').iloc[-1]
        avaliada_p = v._periodo(linha['init_date'])

        validos = pares_p[pares_p['_p'] < avaliada_p].copy()
        validos = validos.assign(
            _target_p=pd.PeriodIndex(validos['target_month'], freq='M'))
        validos = validos[validos['_target_p'] < avaliada_p]

        res_completo = emos.ajustar_emos_completo(
            validos['climatologia_observada'].to_numpy(dtype=float),
            validos['anom_ensemble'].to_numpy(dtype=float),
            validos['erro_clim_sd_mes'].to_numpy(dtype=float),
            validos['spread_relativo'].to_numpy(dtype=float),
            validos['observacao'].to_numpy(dtype=float))
        self.assertAlmostEqual(float(res_completo.fun), linha['crps_final_treino_completo'],
                                places=9)

    def test_d_crps_final_treino_e_diferente_de_crps_retrospectivo_da_avaliada(self):
        """Confirma que as duas quantidades são conceitualmente (e
        numericamente) DIFERENTES — se coincidissem sempre, seria sinal
        de que uma está lendo o valor da outra por engano. Precisa de
        ruído na série: a série sintética LINEAR SEM ruído de `_pares`
        tem ajuste quase perfeito em TODOS os pontos (resíduo ~0 em
        toda parte, inclusive na linha avaliada), o que faz as duas
        quantidades coincidirem por coincidência — não por engano. Com
        ruído, o resíduo da única linha avaliada passa a divergir do
        resíduo médio das dezenas de linhas de treino."""
        rng = np.random.default_rng(7)
        linhas = self._pares(130).to_dict('records')
        for i, linha in enumerate(linhas):
            linha['observacao'] = 80.0 + 0.3 * i + rng.normal(0, 8.0)
        pares = pd.DataFrame(linhas)
        tabela = emos.construir_emos_h2_expanding(pares)
        ok = tabela[tabela['status_emos'] == emos.STATUS_OK]
        self.assertGreater(len(ok), 0)
        # crps_final_treino é a MÉDIA do CRPS sobre decenas de linhas de
        # treino; crps_emos é o CRPS de 1 única observação avaliada — não
        # há razão estrutural para serem iguais, e de fato não são aqui.
        diffs = (ok['crps_final_treino_completo'] - ok['crps_emos']).abs()
        self.assertTrue((diffs > 1e-6).any())


class MutacaoObservacaoFuturaTestCase(unittest.TestCase):
    """Protocolo, seção 23 (item 14 do pedido de implementação) —
    alterar drasticamente a OBSERVAÇÃO de uma linha com
    `target_month >= init_date_avaliada` não pode mudar nada
    (parâmetros, forecast/distribuição, CRPS) de uma avaliação
    passada.

    RN-2B: fixture com ruído determinístico (`_ruido_determinista`) em
    vez da série perfeitamente linear original, que colapsava
    resíduos/`sigma` e levava `gamma_c` ao limite inferior exato (ver
    docs/enso-ci-emos-h2-auditoria-diagnostica.md). O fixture
    degenerado original continua coberto, intacto, em
    EstresseNumericoFronteiraGammaCTestCase."""

    def _pares(self, n, ruido):
        linhas = []
        for i in range(n):
            mes = (i % 12) + 1
            ano = 1990 + i // 12
            init_date = f'{ano}-{mes:02d}'
            target_p = v._periodo(init_date) + 1
            linhas.append({
                'init_date': init_date, 'target_month': str(target_p),
                'target_ano': target_p.year, 'target_mes': target_p.month,
                'observacao': max(0.0, 80.0 + 0.3 * i + ruido[i]),
                'ensemble_mean': 100.0 + 0.5 * i,
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

    def test_a_mutar_observacao_da_linha_imediatamente_anterior_nao_afeta_avaliacao_mais_recente(self):
        ruido = _ruido_determinista(125, seed=20261028, escala=10.0)
        linhas = self._pares(125, ruido)
        tabela_antes = emos.construir_emos_h2_expanding(pd.DataFrame(linhas))
        avaliacao_antes = tabela_antes.sort_values('init_date').iloc[-1].copy()
        self.assertEqual(avaliacao_antes['status_emos'], emos.STATUS_OK)

        # RN-2B — verificação independente de que a linha mutada
        # (linhas[-2]) está genuinamente inelegível para o treino desta
        # avaliação pela condição `target_month_treino < init_date_avaliada`
        # (ela viola essa condição por IGUALDADE — target_month de
        # linhas[-2] é exatamente o init_date da avaliação — não por
        # acaso), e de que há treinamento efetivo não trivial cuja
        # linha mais recente de fato usada é a imediatamente anterior
        # à mutada (linhas[-3]). Sem isto, o teste abaixo passaria
        # mesmo se a regra causal estivesse quebrada e não houvesse
        # treinamento nenhum, ou se linhas[-2] fosse incluída por erro
        # mas coincidisse em não alterar o resultado.
        self.assertGreater(avaliacao_antes['n_treino_emos'], 0,
                            'treinamento vazio tornaria a verificação de não-vazamento trivial')
        self.assertFalse(
            v._periodo(linhas[-2]['target_month']) < v._periodo(avaliacao_antes['init_date']),
            'linha -2 deveria estar na fronteira exata de inelegibilidade '
            '(target_month_treino == init_date_avaliada, nunca <) — se isto falhar, o '
            'fixture não está mais testando o caso que este teste pretende cobrir')
        self.assertEqual(avaliacao_antes['max_init_date_treino'], linhas[-3]['init_date'],
                          'a linha de treino mais recente efetivamente usada deveria ser '
                          'linhas[-3] — prova de que linhas[-2] (a mutada) foi excluída pela '
                          'condição de causalidade, nunca por coincidência de amostra')
        self.assertNotEqual(avaliacao_antes['max_init_date_treino'], linhas[-2]['init_date'])

        linhas_mutadas = [dict(linha) for linha in linhas]
        linhas_mutadas[-2]['observacao'] = -999999.0
        tabela_depois = emos.construir_emos_h2_expanding(pd.DataFrame(linhas_mutadas))
        avaliacao_depois = tabela_depois[
            tabela_depois['init_date'] == avaliacao_antes['init_date']].iloc[0]

        self.assertEqual(avaliacao_depois['status_emos'], emos.STATUS_OK)
        for campo in ('a', 'b', 'gamma_c', 'd', 'a_d0', 'b_d0', 'gamma_c_d0',
                      'mu_latente', 'sigma', 'crps_emos', 'crps_d0'):
            self.assertAlmostEqual(avaliacao_antes[campo], avaliacao_depois[campo], places=6,
                                    msg=f'{campo} mudou com a mutação de uma observação futura')


class IndependenciaD0TestCase(unittest.TestCase):
    """Protocolo, seção 17/24 — `d` não entra no vetor `theta_d0`;
    `sigma_d0` não depende de `ensemble_std` do caso; `a_d0,b_d0,c_d0`
    são ajustados independentemente e PODEM divergir de `a,b,c` do
    modelo completo."""

    def test_a_d_nao_esta_no_vetor_d0(self):
        self.assertEqual(len(emos.THETA0_D0), 3)
        self.assertEqual(len(emos.BOUNDS_D0), 3)

    def test_b_sigma_d0_nao_depende_de_spread_relativo(self):
        clim_obs = np.full(10, 70.0)
        anom = np.linspace(-5, 5, 10)
        erro_sd = np.full(10, 20.0)
        y = 70.0 + 0.5 * anom
        theta_d0 = [0.0, 1.0, 0.0]
        obj1 = emos._objetivo_d0(theta_d0, clim_obs, anom, erro_sd, y)
        # variar só o spread_relativo (não usado em _objetivo_d0 — a
        # assinatura da função nem recebe esse argumento, confirmando
        # estruturalmente a independência)
        import inspect
        assinatura = inspect.signature(emos._objetivo_d0)
        self.assertNotIn('spread', ' '.join(assinatura.parameters.keys()))

    def test_d_sigma_d0_identico_ao_variar_ensemble_std_das_linhas_de_treino(self):
        """Behavioral (não só estrutural): duas séries sintéticas
        idênticas EXCETO em `ensemble_std`/`spread_relativo` — o ajuste
        `d=0` (parâmetros, sigma_d0, crps_d0) da mesma avaliação tem
        que ser EXATAMENTE igual nas duas, provando que `sigma_d0` não
        usa essa informação para nenhuma linha (nem de treino, nem a
        avaliada).

        RN-2B: `observacao` recebe o MESMO ruído gaussiano
        determinístico nas duas séries (só `ensemble_std`/
        `spread_relativo` diferem, preservando a condição do teste) em
        vez da série perfeitamente linear original, que colapsava
        resíduos de treino a ~1e-6 e `sigma`/`c` a valores quase nulos
        (ver docs/enso-ci-emos-h2-auditoria-diagnostica.md). O regime
        degenerado original continua coberto, intacto, em
        EstresseNumericoFronteiraGammaCTestCase."""
        ruido = _ruido_determinista(125, seed=20261027, escala=10.0)

        def _pares(spread_fn):
            linhas = []
            for i in range(125):
                mes = (i % 12) + 1
                ano = 1990 + i // 12
                init_date = f'{ano}-{mes:02d}'
                target_p = v._periodo(init_date) + 1
                linhas.append({
                    'init_date': init_date, 'target_month': str(target_p),
                    'target_ano': target_p.year, 'target_mes': target_p.month,
                    'observacao': max(0.0, 80.0 + 0.3 * i + ruido[i]),
                    'ensemble_mean': 100.0 + 0.5 * i,
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

        tabela_a = emos.construir_emos_h2_expanding(_pares(lambda i: 15.0))
        tabela_b = emos.construir_emos_h2_expanding(_pares(lambda i: 5.0 + 3.0 * (i % 11)))

        linha_a = tabela_a.sort_values('init_date').iloc[-1]
        linha_b = tabela_b.sort_values('init_date').iloc[-1]
        # só o ajuste d0 precisa ter convergido nas duas séries para este
        # teste — o modelo COMPLETO é irrelevante aqui (ele pode, inclusive,
        # ter dificuldade numérica diferente em cada série sintética, já
        # que SEU objetivo depende de spread_relativo; isso não tem nada a
        # ver com a independência do d0 que este teste verifica).
        self.assertEqual(linha_a['status_emos_d0'], emos.STATUS_OK)
        self.assertEqual(linha_b['status_emos_d0'], emos.STATUS_OK)
        # RN-2B — reforço (não substitui o anterior): com o fixture não
        # degenerado, o modelo COMPLETO também deveria convergir
        # normalmente nas duas séries, confirmando que o novo fixture
        # não reproduz o regime de fronteira — documentando a mudança,
        # nunca ocultando-a.
        self.assertEqual(linha_a['status_emos_completo'], emos.STATUS_OK)
        self.assertEqual(linha_b['status_emos_completo'], emos.STATUS_OK)

        for campo in ('a_d0', 'b_d0', 'gamma_c_d0', 'c_d0', 'sigma_d0', 'mu_latente_d0', 'crps_d0'):
            self.assertAlmostEqual(linha_a[campo], linha_b[campo], places=6,
                                    msg=f'{campo} mudou ao variar só ensemble_std/spread_relativo')

    def test_c_parametros_completo_e_d0_podem_divergir_em_cenario_com_sinal_real_de_spread(self):
        """Cenário sintético ONDE o spread relativo realmente modula o
        erro (d verdadeiro > 0) — construído para que o ajuste completo
        tenha incentivo genuíno a usar d>0, diferente do que se observa
        na base real (onde d converge a 0 em todas as 95 avaliações,
        um resultado legítimo, não um sinal de refit malfeito)."""
        rng = np.random.default_rng(42)
        n = 200
        clim_obs = np.full(n, 70.0)
        anom = rng.normal(0, 10, n)
        erro_sd = np.full(n, 15.0)
        spread_rel = rng.uniform(0.3, 3.0, n)
        mu_verdadeiro = clim_obs + 0.0 + 1.0 * anom
        sigma_verdadeiro = erro_sd * np.sqrt(0.3 + 2.0 * spread_rel ** 2)
        y = rng.normal(mu_verdadeiro, sigma_verdadeiro, n)
        y = np.maximum(y, 0.0)

        res_completo = emos.ajustar_emos_completo(clim_obs, anom, erro_sd, spread_rel, y)
        res_d0 = emos.ajustar_emos_d0(clim_obs, anom, erro_sd, y)
        self.assertTrue(res_completo.success)
        self.assertTrue(res_d0.success)

        a, b, gamma_c, d = res_completo.x
        a_d0, b_d0, gamma_c_d0 = res_d0.x
        self.assertGreater(d, 0.05, "neste cenário sintético com sinal real de spread, d "
                                     "deveria se afastar de 0")
        # c (completo) e c_d0 precisam ser GENUINAMENTE diferentes aqui —
        # se fossem idênticos, seria sinal de que d0 não foi reajustado
        # de forma independente.
        self.assertNotAlmostEqual(np.exp(gamma_c), np.exp(gamma_c_d0), places=2)


class EstresseNumericoFronteiraGammaCTestCase(unittest.TestCase):
    """RN-2B — cobertura dedicada do regime numérico extremo que os
    fixtures ORIGINAIS de IndependenciaD0TestCase/
    MutacaoObservacaoFuturaTestCase produziam antes da revisão RN-2B:
    séries sintéticas perfeitamente lineares, sem ruído, que colapsam
    resíduos de treino a ~1e-6 e `sigma`/`c` a valores quase nulos,
    levando `gamma_c`/`gamma_c_d0` ao limite inferior exato — ver
    docs/enso-ci-emos-h2-auditoria-diagnostica.md (seções 8-10) e
    docs/enso-ci-emos-h2-proposta-robustez-numerica.md. Os dois
    fixtures abaixo são preservados INTACTOS (idênticos aos usados
    pelos testes de propriedade antes da RN-2B) — só a classe que os
    hospeda e o contrato de verificação mudaram, nunca os dados.

    Contrato de aprovação, revisado (RN-2B, 3ª rodada — nunca aprova
    ABNORMAL automaticamente, nunca ignora falha de convergência
    genuína, nunca usa skip/xfail, nunca distingue por CPU; aceita
    estados numéricos diferentes conforme o ambiente, mas só com
    verificação explícita e independente em cada um). Dividido em duas
    partes deliberadamente separadas:

    A) `_verificar_qualidade_geral` — SEMPRE exigida, independente de
       `res.success`:
       1. Dimensões de `x`/`jac`/`bounds` consistentes.
       2. `x`, `jac` e `fun` finitos.
       3. `x` respeita os bounds (com folga numérica).
       4. Quando a função objetivo original e os dados causais estão
          disponíveis: a avaliação direta `objetivo_fn(x, *args)`
          precisa ser finita (uma avaliação inicial não finita NUNCA
          pode ser aprovada só porque nenhum vizinho apareceu "melhor"
          — comparar com NaN é sempre False em Python, um loophole
          silencioso que esta verificação fecha explicitamente) e
          precisa ser consistente com `fun` (tolerância relativa
          documentada).
       5. `fun` não pode ser superado por nenhum vizinho determinístico
          amostrado diretamente da MESMA função objetivo (nunca
          chamando `minimize` de novo — isso seria não
          determinístico/dependente de kernel BLAS) além de uma
          tolerância relativa documentada.

    B) `_diagnostico_fronteira_benigna` — só exigida quando
       `res.success=False`, e só DEPOIS de A) já ter sido aprovada:
       1. A classificação "fronteira benigna" só se aplica à
          assinatura EXATA já documentada na auditoria (`status=2`,
          `message` iniciando com `'ABNORMAL: '`) — qualquer outro
          status/mensagem é tratado como desconhecido e nunca aprovado
          por este caminho.
       2. No(s) parâmetro(s) no bound, o SINAL do gradiente precisa
          ser consistente com a condição de KKT de um mínimo de
          fronteira (não pode apontar para uma direção de melhoria
          viável).
       3. O gradiente dos parâmetros LIVRES precisa ser pequeno (<
          LIMIAR_GRADIENTE_LIVRE).

    Uma solução com `success=True` nunca precisa da assinatura
    ABNORMAL nem do limiar heurístico de gradiente livre — só da
    qualidade geral (A). Todo resultado observado é impresso
    explicitamente (diagnóstico separado da condição de aprovação).
    """

    STATUS_ABNORMAL_CONHECIDO = 2
    MENSAGEM_ABNORMAL_CONHECIDA = 'ABNORMAL: '

    LIMIAR_GRADIENTE_LIVRE = 0.05  # ver docstring — margem ampla entre o
    # exemplo benigno (~0,0015) e o mal otimizado (~0,67-18,9) da auditoria
    # (docs/enso-ci-emos-h2-auditoria-diagnostica.md, seções 8/10).

    TOL_BOUND = 1e-6
    TOL_SINAL_KKT = 1e-3
    # Tolerância de qualidade local: 1% de diferença relativa. Fundamentada
    # nos dois extremos conhecidos da auditoria — o caso benigno difere do
    # ótimo vizinho por ~1e-11 relativo (ruído de ponto flutuante, seção 8:
    # "diferença ~1,3e-11"); o caso genuinamente mal otimizado difere por
    # 97,5x = 9650% relativo (seção 10). 1% é 8 ordens de magnitude maior
    # que o ruído de ponto flutuante típico e 4 ordens de magnitude menor
    # que a assinatura de solução ruim — não foi escolhida para fazer
    # nenhum teste específico passar.
    TOL_QUALIDADE_RELATIVA = 0.01
    # Tolerância de consistência entre `fun` (valor registrado por
    # `OptimizeResult`) e a reavaliação direta `objetivo_fn(x, *args)`:
    # 1e-6 relativo. O ruído de ponto flutuante típico de float64 é
    # ~2,2e-16 (epsilon da máquina); somando/multiplicando algumas
    # centenas de termos (o tamanho típico das janelas de treino aqui),
    # o erro acumulado esperado fica em torno de sqrt(n)*epsilon ou
    # n*epsilon, várias ordens de magnitude abaixo de 1e-6 — qualquer
    # diferença real (ex.: argumentos na ordem errada, função errada)
    # produz divergências muito maiores que isso.
    TOL_CONSISTENCIA_FUN_RELATIVA = 1e-6

    # Passos deterministas para a varredura de vizinhança (nunca usa RNG,
    # nunca chama minimize) — combina passos relativos à magnitude atual
    # do parâmetro (resolução fina perto de x) com passos absolutos fixos
    # (alcance maior, cobre o intervalo típico de gamma_c [-20,20] e
    # distâncias grandes como a do exemplo mal otimizado da auditoria,
    # onde a=0 vs a≈4 e b=1 vs b≈0,6 — diferenças de poucas unidades).
    FRACOES_RELATIVAS = (0.01, 0.1, 1.0)
    PASSOS_ABSOLUTOS = (0.001, 0.01, 0.1, 1.0, 5.0, 15.0)

    @staticmethod
    def _melhor_vizinho_deterministico(x, bounds, objetivo_fn, args_objetivo):
        """Amostra vizinhos DETERMINÍSTICOS de `x` (sem RNG, sem chamar
        `minimize`) avaliando a MESMA função objetivo com os MESMOS
        dados causais — nunca depende de kernel BLAS/CPU, porque não
        envolve o L-BFGS-B (só as operações elementares de
        numpy/scipy.stats que `_objetivo_completo`/`_objetivo_d0` já
        fazem, idênticas em qualquer plataforma dentro da precisão de
        float64). Retorna (valor_inicial, melhor_valor, melhor_ponto) —
        `valor_inicial` é exposto separadamente para que o chamador
        possa rejeitar explicitamente uma avaliação não finita, nunca
        aprovar por "nenhum vizinho encontrado melhor" (comparação com
        NaN é sempre False em Python)."""
        x = np.asarray(x, dtype=float)
        valor_inicial = float(objetivo_fn(x, *args_objetivo))
        melhor_valor = valor_inicial
        melhor_ponto = x.copy()
        if not np.isfinite(valor_inicial):
            return valor_inicial, melhor_valor, melhor_ponto.tolist()
        passos_por_dim = []
        for xi in x:
            passos = {abs(xi) * f for f in EstresseNumericoFronteiraGammaCTestCase.FRACOES_RELATIVAS}
            passos |= set(EstresseNumericoFronteiraGammaCTestCase.PASSOS_ABSOLUTOS)
            passos_por_dim.append(sorted(p for p in passos if p > 0))
        for i, (lo, hi) in enumerate(bounds):
            for passo in passos_por_dim[i]:
                for sinal in (+1.0, -1.0):
                    candidato = x.copy()
                    candidato[i] = x[i] + sinal * passo
                    if lo is not None and candidato[i] < lo:
                        continue
                    if hi is not None and candidato[i] > hi:
                        continue
                    valor = float(objetivo_fn(candidato, *args_objetivo))
                    if np.isfinite(valor) and valor < melhor_valor:
                        melhor_valor = valor
                        melhor_ponto = candidato
        return valor_inicial, melhor_valor, melhor_ponto.tolist()

    @staticmethod
    def _verificar_qualidade_geral(x, jac, bounds, fun, objetivo_fn=None, args_objetivo=None,
                                    tol_bound=TOL_BOUND,
                                    tol_qualidade_relativa=TOL_QUALIDADE_RELATIVA,
                                    tol_consistencia_fun_relativa=TOL_CONSISTENCIA_FUN_RELATIVA):
        """Verificações de qualidade SEMPRE exigidas, independente de
        `success` — dimensões, finitude, bounds, consistência entre
        `fun` e a reavaliação direta da função objetivo, e ausência de
        vizinho determinístico melhor. Nunca reimplementa o otimizador,
        nunca chama `minimize`."""
        x = np.asarray(x, dtype=float)
        jac = np.asarray(jac, dtype=float)

        if len(x) != len(jac) or len(x) != len(bounds):
            return {'aceitavel': False,
                    'motivo': f'dimensões incompatíveis: len(x)={len(x)} len(jac)={len(jac)} '
                              f'len(bounds)={len(bounds)}'}
        if not np.all(np.isfinite(x)):
            return {'aceitavel': False, 'motivo': f'parâmetros não finitos: x={x.tolist()}'}
        if not np.all(np.isfinite(jac)):
            return {'aceitavel': False, 'motivo': f'gradiente não finito: jac={jac.tolist()}'}
        if fun is not None and not np.isfinite(fun):
            return {'aceitavel': False, 'motivo': f'fun não finito: {fun!r}'}

        for i, (xi, (lo, hi)) in enumerate(zip(x, bounds)):
            if lo is not None and xi < lo - tol_bound:
                return {'aceitavel': False, 'motivo': f'x[{i}]={xi} viola o limite inferior {lo}'}
            if hi is not None and xi > hi + tol_bound:
                return {'aceitavel': False, 'motivo': f'x[{i}]={xi} viola o limite superior {hi}'}

        no_bound = [
            (lo is not None and abs(xi - lo) < tol_bound) or
            (hi is not None and abs(xi - hi) < tol_bound)
            for xi, (lo, hi) in zip(x, bounds)
        ]

        if objetivo_fn is not None and args_objetivo is not None:
            valor_inicial, melhor_vizinho, ponto_vizinho = EstresseNumericoFronteiraGammaCTestCase \
                ._melhor_vizinho_deterministico(x, bounds, objetivo_fn, args_objetivo)

            if not np.isfinite(valor_inicial):
                return {'aceitavel': False, 'no_bound': no_bound,
                        'motivo': f'objetivo_fn(x, *args) não é finito ({valor_inicial!r}) — nunca '
                                  'aprovado por ausência de vizinhos melhores (comparação com '
                                  'valor não finito nunca é confiável)'}

            if fun is not None:
                diff_rel_fun = abs(fun - valor_inicial) / max(abs(fun), abs(valor_inicial), 1e-12)
                if diff_rel_fun > tol_consistencia_fun_relativa:
                    return {'aceitavel': False, 'no_bound': no_bound,
                            'motivo': f'fun={fun:.6g} inconsistente com objetivo_fn(x, *args)='
                                      f'{valor_inicial:.6g} (diferença relativa {diff_rel_fun:.4%} '
                                      f'> tolerância {tol_consistencia_fun_relativa:.1%})'}

            fun_base = fun if fun is not None else valor_inicial
            tolerancia_abs = tol_qualidade_relativa * max(abs(fun_base), 1e-12)
            if melhor_vizinho < fun_base - tolerancia_abs:
                diff_rel = (fun_base - melhor_vizinho) / max(abs(fun_base), 1e-12)
                return {'aceitavel': False, 'no_bound': no_bound,
                        'motivo': f'fun={fun_base:.6g} é superado por um vizinho determinístico '
                                  f'fun_vizinho={melhor_vizinho:.6g} em x_vizinho={ponto_vizinho} '
                                  f'(diferença relativa {diff_rel:.4%} > tolerância '
                                  f'{tol_qualidade_relativa:.1%}) — solução genuinamente '
                                  'inadequada, independente de success'}

        motivo = 'dimensões/finitude/bounds OK' + (
            '; qualidade local confirmada contra vizinhos determinísticos (fun consistente com '
            'a reavaliação direta)' if objetivo_fn is not None else '')
        return {'aceitavel': True, 'no_bound': no_bound, 'motivo': motivo}

    @staticmethod
    def _diagnostico_fronteira_benigna(x, jac, bounds, status=None, message=None,
                                        tol_bound=TOL_BOUND,
                                        limiar_grad_livre=LIMIAR_GRADIENTE_LIVRE,
                                        tol_sinal_kkt=TOL_SINAL_KKT):
        """Discriminador só de DIAGNÓSTICO (vive no teste, nunca no
        código de produção) — PRESSUPÕE que `_verificar_qualidade_geral`
        já foi aprovada separadamente; esta função só cobre o que é
        ESPECÍFICO de uma falha de convergência (`success=False`):
        assinatura exata, sinal de KKT na fronteira, magnitude do
        gradiente livre. Nunca reimplementa nem substitui o critério
        `success` do scipy."""
        x = np.asarray(x, dtype=float)
        jac = np.asarray(jac, dtype=float)

        no_bound = [
            (lo is not None and abs(xi - lo) < tol_bound) or
            (hi is not None and abs(xi - hi) < tol_bound)
            for xi, (lo, hi) in zip(x, bounds)
        ]
        indices_livres = [i for i, no in enumerate(no_bound) if not no]

        if not any(no_bound):
            return {'aceitavel': False, 'no_bound': no_bound,
                    'motivo': 'nenhum parâmetro no bound — ABNORMAL sem fronteira ativa '
                              'não tem explicação benigna conhecida/testada'}

        if status is not None and status != EstresseNumericoFronteiraGammaCTestCase.STATUS_ABNORMAL_CONHECIDO:
            return {'aceitavel': False, 'no_bound': no_bound,
                    'motivo': f'status={status!r} não é o ABNORMAL conhecido '
                              f'({EstresseNumericoFronteiraGammaCTestCase.STATUS_ABNORMAL_CONHECIDO}) '
                              '— falha de otimizador de tipo desconhecido, nunca aprovada '
                              'automaticamente'}
        if message is not None and not str(message).startswith(
                EstresseNumericoFronteiraGammaCTestCase.MENSAGEM_ABNORMAL_CONHECIDA):
            return {'aceitavel': False, 'no_bound': no_bound,
                    'motivo': f'message={message!r} não é a ABNORMAL conhecida — falha de '
                              'otimizador de tipo desconhecido, nunca aprovada automaticamente'}

        # KKT de fronteira: no limite ATIVO, a única direção viável é
        # para DENTRO da região viável — o gradiente não pode apontar
        # para uma direção de melhoria dentro dela. Violação aqui
        # significa que HÁ uma direção viável que reduz o objetivo —
        # não é fronteira benigna, é não convergência real.
        for i, (xi, (lo, hi)) in enumerate(zip(x, bounds)):
            if not no_bound[i]:
                continue
            no_lo = lo is not None and abs(xi - lo) < tol_bound
            if no_lo and jac[i] < -tol_sinal_kkt:
                return {'aceitavel': False, 'no_bound': no_bound,
                        'motivo': f'x[{i}]={xi} no limite inferior {lo}, mas jac[{i}]={jac[i]:.6g} '
                                  f'< -{tol_sinal_kkt} — gradiente aponta para direção de melhoria '
                                  'viável (aumentar x[i] reduziria o objetivo); não é mínimo de '
                                  'fronteira genuíno, é não convergência real'}
            no_hi = hi is not None and abs(xi - hi) < tol_bound
            if no_hi and jac[i] > tol_sinal_kkt:
                return {'aceitavel': False, 'no_bound': no_bound,
                        'motivo': f'x[{i}]={xi} no limite superior {hi}, mas jac[{i}]={jac[i]:.6g} '
                                  f'> {tol_sinal_kkt} — gradiente aponta para direção de melhoria '
                                  'viável (diminuir x[i] reduziria o objetivo); não é mínimo de '
                                  'fronteira genuíno, é não convergência real'}

        grad_livre_max = float(np.max(np.abs(jac[indices_livres]))) if indices_livres else 0.0
        if grad_livre_max >= limiar_grad_livre:
            return {'aceitavel': False, 'no_bound': no_bound, 'grad_livre_max': grad_livre_max,
                    'motivo': f'gradiente livre máximo={grad_livre_max:.6g} >= '
                              f'limiar={limiar_grad_livre} — magnitude consistente com otimização '
                              'genuinamente ruim, não com fronteira benigna (auditoria: caso mal '
                              'otimizado tem 0,67-18,9)'}

        motivo = (f'gradiente livre máximo={grad_livre_max:.6g} < limiar={limiar_grad_livre}; '
                  'sinal KKT consistente com mínimo de fronteira; status/message compatíveis '
                  'com ABNORMAL conhecido')
        return {'aceitavel': True, 'no_bound': no_bound, 'grad_livre_max': grad_livre_max,
                'motivo': motivo}

    @staticmethod
    def _verificar_resultado_otimizador(res, bounds, objetivo_fn, args_objetivo):
        """Combina as duas partes do contrato (A: qualidade geral,
        sempre; B: fronteira benigna, só quando `res.success=False`)
        sobre um `OptimizeResult` real OU simulado (`mock.Mock` com os
        mesmos atributos) — usado pelos testes k/l (fixtures reais) e
        pelos testes de regressão que simulam `success=True`."""
        diag_geral = EstresseNumericoFronteiraGammaCTestCase._verificar_qualidade_geral(
            res.x, res.jac, bounds, res.fun, objetivo_fn=objetivo_fn, args_objetivo=args_objetivo)
        if not diag_geral['aceitavel']:
            return False, f'qualidade geral reprovada: {diag_geral["motivo"]}'
        if res.success:
            return True, f'convergência normal (status={res.status}, message={res.message!r}); {diag_geral["motivo"]}'
        diag_fronteira = EstresseNumericoFronteiraGammaCTestCase._diagnostico_fronteira_benigna(
            res.x, res.jac, bounds, status=res.status, message=res.message)
        if not diag_fronteira['aceitavel']:
            return False, f'status={res.status} message={res.message!r} — {diag_fronteira["motivo"]}'
        return True, (f'ABNORMAL aceito como fronteira benigna (status={res.status}, '
                      f'message={res.message!r}) — {diag_fronteira["motivo"]}; {diag_geral["motivo"]}')

    # ── RN-2D — instrumentação de observação pura ───────────────────────
    # Objetivo: testar (não presumir) se chamadas idênticas a `minimize`
    # produzem resultados diferentes dentro do mesmo processo/ambiente, e
    # se isso está associado a paralelismo do OpenBLAS. Nunca decide
    # aprovação/rejeição, nunca altera argumento/resultado/critério, e
    # roda sempre ANTES de qualquer assertTrue/assertFalse — uma falha de
    # asserção nunca pode impedir a captura da evidência.

    _AMBIENTE_NUMERICO_LOGADO = False

    @classmethod
    def _log_ambiente_numerico(cls):
        """Log incondicional, uma vez por processo, do ambiente numérico
        efetivo — nunca presume que dois runs com o mesmo kernel nominal
        (ex.: 'Haswell') têm o mesmo comportamento interno; só registra o
        que threadpoolctl e o SO reportam DESTE processo."""
        if cls._AMBIENTE_NUMERICO_LOGADO:
            return
        cls._AMBIENTE_NUMERICO_LOGADO = True

        cpu_model = 'NAO_DISPONIVEL'
        try:
            with open('/proc/cpuinfo') as fh:
                for linha_cpu in fh:
                    if linha_cpu.startswith('model name'):
                        cpu_model = linha_cpu.split(':', 1)[1].strip()
                        break
        except OSError:
            pass

        if threadpoolctl is not None:
            # threadpool_info() devolve [] se nenhuma operação BLAS real
            # já rodou neste processo — força o carregamento preguiçoso
            # do backend antes de perguntar.
            _ = np.zeros((8, 8)) @ np.zeros((8, 8))
            info_blas = threadpoolctl.threadpool_info()
        else:
            info_blas = 'NAO_DISPONIVEL (pacote threadpoolctl ausente)'

        env_vars = {var: os.environ.get(var, 'NAO_DEFINIDA') for var in (
            'OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
            'NUMEXPR_NUM_THREADS', 'OPENBLAS_CORETYPE', 'GOTO_NUM_THREADS',
            'OPENBLAS_VERBOSE')}

        registro = {
            'python': sys.version.split()[0],
            'numpy': np.__version__,
            'scipy': scipy.__version__,
            'cpu_model_name': cpu_model,
            'threadpoolctl': info_blas,
            'env_blas_openmp': env_vars,
        }
        print('[RN-2D/Ambiente] ' + json.dumps(registro, sort_keys=True, default=str))

    @staticmethod
    def _fingerprint_arrays(args_objetivo):
        """Hash sha256 determinístico de cada array de treino,
        preservando ordem/dtype/shape/conteúdo float64 — nunca só a
        contagem de linhas (RN-2D, item 4). `args_objetivo=None` ou
        vazio é registrado como tal, nunca estimado."""
        if not args_objetivo:
            return 'NAO_DISPONIVEL', []
        partes = []
        for i, arr in enumerate(args_objetivo):
            a = np.ascontiguousarray(np.asarray(arr, dtype=float))
            h = hashlib.sha256(a.tobytes()).hexdigest()
            partes.append(f'arr{i}(shape={a.shape},dtype={a.dtype})={h}')
        combinado = hashlib.sha256('|'.join(partes).encode()).hexdigest()
        return combinado, partes

    @staticmethod
    def _observar_chamadas_minimize():
        """RN-2D, item 3 — observa (sem alterar) todas as chamadas a
        `emos.minimize` feitas dentro do bloco `with` devolvido. A
        função científica original é sempre chamada sem modificação de
        argumentos, e o MESMO objeto de resultado que ela devolve é
        repassado ao chamador real (`ajustar_emos_completo`/
        `ajustar_emos_d0`) — o `side_effect` só registra e repassa,
        nunca substitui nem adiciona uma chamada extra a `minimize`.
        Restaurado automaticamente ao sair do `with` (`mock.patch.object`
        sem `wraps`, para controlar explicitamente a chamada real e
        capturar seu retorno exato)."""
        minimize_original = emos.minimize
        chamadas = []

        def _observador(*args, **kwargs):
            resultado = minimize_original(*args, **kwargs)
            chamadas.append({'args': args, 'kwargs': kwargs, 'resultado': resultado})
            return resultado

        gerenciador = mock.patch.object(emos, 'minimize', side_effect=_observador)
        return gerenciador, chamadas

    @classmethod
    def _log_chamada_otimizador(cls, test_id, chamada_id, submodelo, res, bounds,
                                 objetivo_fn, args_objetivo, theta0=None, options=None):
        """RN-2D — log incondicional de UMA chamada ao otimizador, ANTES
        de qualquer asserção. Nunca decide aprovação/rejeição — só
        registra o que `OptimizeResult`, a reavaliação direta e a busca
        de vizinho determinístico (já existente, reaproveitada, nunca
        chama `minimize`) mostram. Campo ausente é registrado
        explicitamente como tal, nunca estimado."""
        _AUSENTE = object()  # sentinela por identidade — nunca comparar array com '==' / '!='

        def _campo(nome, default='NAO_DISPONIVEL'):
            valor = getattr(res, nome, _AUSENTE)
            return default if valor is _AUSENTE or valor is None else valor

        x_raw = _campo('x', default=_AUSENTE)
        x = np.asarray(x_raw, dtype=float) if x_raw is not _AUSENTE else None
        jac_raw = _campo('jac', default=_AUSENTE)
        jac = np.asarray(jac_raw, dtype=float) if jac_raw is not _AUSENTE else None
        fun = _campo('fun')

        no_bound = 'NAO_DISPONIVEL'
        if x is not None and bounds is not None:
            no_bound = [
                bool((lo is not None and abs(xi - lo) < cls.TOL_BOUND) or
                     (hi is not None and abs(xi - hi) < cls.TOL_BOUND))
                for xi, (lo, hi) in zip(x, bounds)
            ]

        avaliacao_direta = 'NAO_DISPONIVEL'
        melhor_vizinho_valor = 'NAO_DISPONIVEL'
        melhor_vizinho_ponto = 'NAO_DISPONIVEL'
        if x is not None and bounds is not None and objetivo_fn is not None and args_objetivo:
            valor_inicial, melhor_valor, melhor_ponto = cls._melhor_vizinho_deterministico(
                x, bounds, objetivo_fn, args_objetivo)
            avaliacao_direta = valor_inicial
            melhor_vizinho_valor = melhor_valor
            melhor_vizinho_ponto = melhor_ponto

        fingerprint, partes_fingerprint = cls._fingerprint_arrays(args_objetivo)

        registro = {
            'teste': test_id,
            'chamada': chamada_id,
            'submodelo': submodelo,
            'success': _campo('success'),
            'status': _campo('status'),
            'message': str(_campo('message')),
            'x': x.tolist() if x is not None else 'NAO_DISPONIVEL',
            'jac': jac.tolist() if jac is not None else 'NAO_DISPONIVEL',
            'fun': fun,
            'nit': _campo('nit'),
            'nfev': _campo('nfev'),
            'bounds': bounds if bounds is not None else 'NAO_DISPONIVEL',
            'no_bound': no_bound,
            'theta0': (np.asarray(theta0).tolist() if theta0 is not None else 'NAO_DISPONIVEL'),
            'options': (dict(options) if options is not None else 'NAO_DISPONIVEL'),
            'avaliacao_direta_objetivo_fn': avaliacao_direta,
            'melhor_vizinho_valor': melhor_vizinho_valor,
            'melhor_vizinho_ponto': melhor_vizinho_ponto,
            'fingerprint_args': fingerprint,
            'fingerprint_args_detalhe': partes_fingerprint,
        }
        print('[RN-2D/Chamada] ' + json.dumps(registro, sort_keys=True, default=str))
        return registro

    # ── Regressão literal contra os exemplos da auditoria (parte B) ────

    def test_a_discriminador_aceita_o_exemplo_benigno_da_auditoria(self):
        """Regressão literal — auditoria, seção 8: chamada decisiva
        reproduzida identicamente em toda execução AMD+Haswell
        observada, fronteira em gamma_c (3º componente), gradiente
        livre pequeno, status/message exatamente os documentados."""
        x = np.array([4.0000012, 0.6, -20.0])
        jac = np.array([2.393306108216331e-05, 0.001515917621979863, 0.00010609730260496464])
        bounds = [(None, None), (None, None), (emos.GAMMA_C_LO, emos.GAMMA_C_HI)]
        diag = self._diagnostico_fronteira_benigna(x, jac, bounds, status=2, message='ABNORMAL: ')
        self.assertTrue(diag['aceitavel'], diag['motivo'])

    def test_b_discriminador_rejeita_o_exemplo_mal_otimizado_da_auditoria(self):
        """Regressão literal — auditoria, seção 10: a única chamada
        genuinamente mal otimizada observada (`fun` 97,5x pior que o
        cluster bom) tem gradiente livre 2-3 ordens de magnitude maior
        (jac[0]=0,67, jac[1]=18,9), mesmo com gamma_c também no bound
        (componente de fronteira ~0,0001061, igual ao caso benigno —
        a auditoria já havia confirmado que esse componente, isolado,
        não discrimina os dois casos)."""
        x = np.array([0.0, 1.0, -20.0])
        jac = np.array([0.67, 18.9, 0.0001061])
        bounds = [(None, None), (None, None), (emos.GAMMA_C_LO, emos.GAMMA_C_HI)]
        diag = self._diagnostico_fronteira_benigna(x, jac, bounds)
        self.assertFalse(diag['aceitavel'], diag['motivo'])

    def test_c_discriminador_rejeita_falha_sem_fronteira_ativa(self):
        x = np.array([4.0, 0.6, -5.0])  # nenhum parâmetro no bound
        jac = np.array([0.001, 0.001, 0.0001])
        bounds = [(None, None), (None, None), (emos.GAMMA_C_LO, emos.GAMMA_C_HI)]
        diag = self._diagnostico_fronteira_benigna(x, jac, bounds, status=2, message='ABNORMAL: ')
        self.assertFalse(diag['aceitavel'])
        self.assertIn('nenhum parâmetro no bound', diag['motivo'])

    def test_d_discriminador_rejeita_sinal_kkt_incompativel_com_minimo_de_fronteira(self):
        """O caso explícito pedido na revisão: uma solução no limite
        inferior com gradiente claramente NEGATIVO aponta para uma
        direção de melhoria viável (aumentar o parâmetro reduziria o
        objetivo) — isso é não convergência real, nunca fronteira
        benigna, mesmo com gradiente livre pequeno e status/message
        idênticos ao exemplo benigno."""
        x = np.array([4.0000012, 0.6, -20.0])
        jac = np.array([2.39e-05, 0.0015, -0.5])  # componente de fronteira NEGATIVA e grande
        bounds = [(None, None), (None, None), (emos.GAMMA_C_LO, emos.GAMMA_C_HI)]
        diag = self._diagnostico_fronteira_benigna(x, jac, bounds, status=2, message='ABNORMAL: ')
        self.assertFalse(diag['aceitavel'], diag['motivo'])
        self.assertIn('direção de melhoria viável', diag['motivo'])

    def test_e_discriminador_rejeita_status_ou_mensagem_diferente_do_abnormal_conhecido(self):
        x = np.array([4.0000012, 0.6, -20.0])
        jac = np.array([2.39e-05, 0.0015, 0.0001061])
        bounds = [(None, None), (None, None), (emos.GAMMA_C_LO, emos.GAMMA_C_HI)]

        diag_status = self._diagnostico_fronteira_benigna(x, jac, bounds, status=99,
                                                            message='ABNORMAL: ')
        self.assertFalse(diag_status['aceitavel'])
        self.assertIn('não é o ABNORMAL conhecido', diag_status['motivo'])

        diag_msg = self._diagnostico_fronteira_benigna(x, jac, bounds, status=2,
                                                         message='algo completamente diferente')
        self.assertFalse(diag_msg['aceitavel'])
        self.assertIn('não é a ABNORMAL conhecida', diag_msg['motivo'])

    # ── Regressão da qualidade geral (parte A — sempre exigida) ────────

    def test_f_qualidade_geral_rejeita_dimensoes_incompativeis(self):
        bounds = [(None, None), (None, None), (emos.GAMMA_C_LO, emos.GAMMA_C_HI)]
        diag = self._verificar_qualidade_geral(np.array([1.0, 2.0]), np.array([0.1, 0.1, 0.1]),
                                                 bounds, fun=1.0)
        self.assertFalse(diag['aceitavel'])
        self.assertIn('dimensões incompatíveis', diag['motivo'])

    def test_g_qualidade_geral_rejeita_parametros_gradiente_ou_fun_nao_finitos(self):
        bounds = [(None, None), (None, None), (emos.GAMMA_C_LO, emos.GAMMA_C_HI)]
        diag_x = self._verificar_qualidade_geral(np.array([np.nan, 0.6, -20.0]),
                                                   np.array([0.0, 0.001, 0.0001]), bounds, fun=1.0)
        self.assertFalse(diag_x['aceitavel'])
        self.assertIn('não finitos', diag_x['motivo'])

        diag_jac = self._verificar_qualidade_geral(np.array([4.0, 0.6, -20.0]),
                                                     np.array([0.0, np.inf, 0.0001]), bounds, fun=1.0)
        self.assertFalse(diag_jac['aceitavel'])
        self.assertIn('não finito', diag_jac['motivo'])

        diag_fun = self._verificar_qualidade_geral(np.array([4.0, 0.6, -20.0]),
                                                     np.array([0.0, 0.001, 0.0001]), bounds,
                                                     fun=np.nan)
        self.assertFalse(diag_fun['aceitavel'])
        self.assertIn('fun não finito', diag_fun['motivo'])

    def test_h_qualidade_geral_rejeita_violacao_de_bound(self):
        bounds = [(None, None), (None, None), (emos.GAMMA_C_LO, emos.GAMMA_C_HI)]
        diag = self._verificar_qualidade_geral(np.array([4.0, 0.6, -25.0]),
                                                 np.array([0.0, 0.001, 0.0001]), bounds, fun=1.0)
        self.assertFalse(diag['aceitavel'])
        self.assertIn('viola', diag['motivo'])

    def test_i_qualidade_geral_rejeita_solucao_com_qualidade_pior_que_vizinho_deterministico(self):
        """Mesmo com gradiente LIVRE pequeno, uma avaliação DIRETA da
        função objetivo num vizinho determinístico pode revelar que a
        solução está longe do mínimo — esta verificação nunca confia
        só no gradiente reportado e é independente de `success`.
        Função sintética simples (não o EMOS H2 real — esse é
        exercitado de novo nos testes k/l com dados causais reais),
        com mínimo verdadeiro conhecido em (5,3)."""
        def objetivo_simples(theta, *_args):
            return float((theta[0] - 5.0) ** 2 + (theta[1] - 3.0) ** 2)

        x_mal = np.array([0.0, 0.0, -20.0])
        jac_mal = np.array([0.001, 0.001, 0.0001061])
        bounds = [(None, None), (None, None), (emos.GAMMA_C_LO, emos.GAMMA_C_HI)]
        fun_mal = objetivo_simples(x_mal)

        diag = self._verificar_qualidade_geral(
            x_mal, jac_mal, bounds, fun=fun_mal,
            objetivo_fn=objetivo_simples, args_objetivo=())
        self.assertFalse(diag['aceitavel'], diag['motivo'])
        self.assertIn('vizinho determinístico', diag['motivo'])

    def test_j_qualidade_geral_aceita_quando_confirmada_localmente(self):
        """Mesma função sintética do teste anterior, agora avaliada NO
        mínimo verdadeiro (5,3) — nenhum vizinho determinístico deveria
        ser melhor (dentro da tolerância)."""
        def objetivo_simples(theta, *_args):
            return float((theta[0] - 5.0) ** 2 + (theta[1] - 3.0) ** 2)

        x_bom = np.array([5.0, 3.0, -20.0])
        jac_bom = np.array([0.0, 0.0, 0.0001061])
        bounds = [(None, None), (None, None), (emos.GAMMA_C_LO, emos.GAMMA_C_HI)]
        fun_bom = objetivo_simples(x_bom)

        diag = self._verificar_qualidade_geral(
            x_bom, jac_bom, bounds, fun=fun_bom,
            objetivo_fn=objetivo_simples, args_objetivo=())
        self.assertTrue(diag['aceitavel'], diag['motivo'])

    def test_k_qualidade_geral_rejeita_avaliacao_inicial_nao_finita_sem_aprovar_por_omissao(self):
        """RN-2B, 3ª rodada — item 2 explícito: se `objetivo_fn(x, *args)`
        não é finito, isso NUNCA pode ser aprovado por "nenhum vizinho
        encontrado melhor" (comparar com NaN/Inf é sempre False em
        Python — um loophole silencioso). `fun` passado é finito e
        plausível de propósito, para provar que é a avaliação DIRETA
        (não o `fun` já registrado) que está sendo checada aqui."""
        def objetivo_sempre_nan(theta, *_args):
            return float('nan')

        x = np.array([1.0, 1.0, -20.0])
        jac = np.array([0.001, 0.001, 0.0001061])
        bounds = [(None, None), (None, None), (emos.GAMMA_C_LO, emos.GAMMA_C_HI)]

        diag = self._verificar_qualidade_geral(
            x, jac, bounds, fun=3.0, objetivo_fn=objetivo_sempre_nan, args_objetivo=())
        self.assertFalse(diag['aceitavel'])
        self.assertIn('não é finito', diag['motivo'])

    def test_l_qualidade_geral_rejeita_fun_inconsistente_com_avaliacao_direta(self):
        """`fun` (o valor registrado no `OptimizeResult`) precisa ser
        consistente com uma reavaliação direta de `objetivo_fn(x,
        *args)` — uma divergência grande entre os dois (ex.: `fun` de
        uma chamada anterior, argumentos trocados) tem que ser
        rejeitada, mesmo que nenhum vizinho apareça melhor que o `fun`
        (errado) informado."""
        def objetivo_simples(theta, *_args):
            return float((theta[0] - 5.0) ** 2 + (theta[1] - 3.0) ** 2)

        x = np.array([5.0, 3.0, -20.0])  # no mínimo verdadeiro: objetivo real = 0.0
        jac = np.array([0.0, 0.0, 0.0001061])
        bounds = [(None, None), (None, None), (emos.GAMMA_C_LO, emos.GAMMA_C_HI)]

        diag = self._verificar_qualidade_geral(
            x, jac, bounds, fun=500.0,  # deliberadamente muito diferente do valor real (0.0)
            objetivo_fn=objetivo_simples, args_objetivo=())
        self.assertFalse(diag['aceitavel'])
        self.assertIn('inconsistente', diag['motivo'])

    def test_m_rejeita_quando_success_true_mas_qualidade_pior_que_vizinho_deterministico(self):
        """RN-2B, 3ª rodada — item 3 explícito: uma solução com
        `success=True` (simulado via `mock.Mock`, sem precisar rodar o
        otimizador real) mas significativamente pior que um vizinho
        determinístico tem que ser rejeitada pelo contrato completo
        (`_verificar_resultado_otimizador`) — qualidade geral nunca é
        dispensada só porque o otimizador reportou sucesso."""
        def objetivo_simples(theta, *_args):
            return float((theta[0] - 5.0) ** 2 + (theta[1] - 3.0) ** 2)

        x_mal = np.array([0.0, 0.0, -20.0])
        fun_mal = objetivo_simples(x_mal)
        res_mock = mock.Mock(success=True, status=0,
                              message='CONVERGENCE: RELATIVE REDUCTION OF F <= FACTR*EPSMCH',
                              x=x_mal, jac=np.array([0.001, 0.001, 0.0001061]), fun=fun_mal)
        bounds = [(None, None), (None, None), (emos.GAMMA_C_LO, emos.GAMMA_C_HI)]

        aceitavel, motivo = self._verificar_resultado_otimizador(
            res_mock, bounds, objetivo_simples, ())
        self.assertFalse(aceitavel, motivo)
        self.assertIn('qualidade geral reprovada', motivo)

    def test_n_aceita_quando_success_true_e_qualidade_confirmada(self):
        """Contraparte do teste anterior: `success=True` genuíno, no
        mínimo verdadeiro — tem que ser aceito, sem exigir nenhum dos
        critérios específicos de ABNORMAL (status/message/sinal KKT)."""
        def objetivo_simples(theta, *_args):
            return float((theta[0] - 5.0) ** 2 + (theta[1] - 3.0) ** 2)

        x_bom = np.array([5.0, 3.0, -20.0])
        fun_bom = objetivo_simples(x_bom)
        res_mock = mock.Mock(success=True, status=0,
                              message='CONVERGENCE: RELATIVE REDUCTION OF F <= FACTR*EPSMCH',
                              x=x_bom, jac=np.array([0.0, 0.0, 0.0001061]), fun=fun_bom)
        bounds = [(None, None), (None, None), (emos.GAMMA_C_LO, emos.GAMMA_C_HI)]

        aceitavel, motivo = self._verificar_resultado_otimizador(
            res_mock, bounds, objetivo_simples, ())
        self.assertTrue(aceitavel, motivo)

    # ── Fixtures reais degenerados (preservados intactos) ───────────────

    def _validos_causais(self, pares):
        pares_p = pares.assign(_p=pd.PeriodIndex(pares['init_date'], freq='M')).sort_values('_p')
        avaliada_p = pares_p['_p'].iloc[-1]
        validos = pares_p[pares_p['_p'] < avaliada_p].copy()
        validos = validos.assign(_target_p=pd.PeriodIndex(validos['target_month'], freq='M'))
        return validos[validos['_target_p'] < avaliada_p]

    @staticmethod
    def _pares_independencia_d0_degenerado(spread_fn):
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

    @staticmethod
    def _pares_mutacao_degenerado(n):
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
        return pd.DataFrame(linhas)

    def test_o_fronteira_submodelo_completo_fixture_degenerado_original_independencia_d0(self):
        """Fixture ORIGINAL da série B de IndependenciaD0TestCase
        (antes da RN-2B), preservado byte a byte — exercita
        diretamente `ajustar_emos_completo` (nunca reimplementado)
        sobre o conjunto de treino causal real da última avaliação,
        com o contrato completo (qualidade geral SEMPRE + fronteira
        benigna só se `success=False`)."""
        pares = self._pares_independencia_d0_degenerado(lambda i: 5.0 + 3.0 * (i % 11))
        validos = self._validos_causais(pares)
        self.assertGreaterEqual(len(validos), emos.N_TREINO_MINIMO_EMOS)

        args_objetivo = (
            validos['climatologia_observada'].to_numpy(dtype=float),
            validos['anom_ensemble'].to_numpy(dtype=float),
            validos['erro_clim_sd_mes'].to_numpy(dtype=float),
            validos['spread_relativo'].to_numpy(dtype=float),
            validos['observacao'].to_numpy(dtype=float),
        )
        res = emos.ajustar_emos_completo(*args_objetivo)

        self._log_ambiente_numerico()
        self._log_chamada_otimizador('test_o', 'A', 'completo', res, emos.BOUNDS_COMPLETO,
                                      emos._objetivo_completo, args_objetivo,
                                      theta0=emos.THETA0_COMPLETO, options=emos.OPCOES_OTIMIZADOR)

        aceitavel, motivo = self._verificar_resultado_otimizador(
            res, emos.BOUNDS_COMPLETO, emos._objetivo_completo, args_objetivo)
        self.assertTrue(aceitavel, motivo)
        print(f'[EstresseNumerico] completo (IndependenciaD0, série B): {motivo}')

    def test_p_fronteira_submodelo_d0_fixture_degenerado_original_mutacao(self):
        """Fixture ORIGINAL de MutacaoObservacaoFuturaTestCase (antes
        da RN-2B), preservado byte a byte — exercita diretamente
        `ajustar_emos_d0` (nunca reimplementado) sobre o conjunto de
        treino causal real da última avaliação, com o contrato
        completo."""
        pares = self._pares_mutacao_degenerado(125)
        validos = self._validos_causais(pares)
        self.assertGreaterEqual(len(validos), emos.N_TREINO_MINIMO_EMOS)

        args_objetivo = (
            validos['climatologia_observada'].to_numpy(dtype=float),
            validos['anom_ensemble'].to_numpy(dtype=float),
            validos['erro_clim_sd_mes'].to_numpy(dtype=float),
            validos['observacao'].to_numpy(dtype=float),
        )
        res = emos.ajustar_emos_d0(*args_objetivo)

        self._log_ambiente_numerico()
        self._log_chamada_otimizador('test_p', 'A', 'd0', res, emos.BOUNDS_D0,
                                      emos._objetivo_d0, args_objetivo,
                                      theta0=emos.THETA0_D0, options=emos.OPCOES_OTIMIZADOR)

        aceitavel, motivo = self._verificar_resultado_otimizador(
            res, emos.BOUNDS_D0, emos._objetivo_d0, args_objetivo)
        self.assertTrue(aceitavel, motivo)
        print(f'[EstresseNumerico] d0 (MutacaoObservacaoFutura): {motivo}')

    # ── Integração com STOP-ON-FAILURE (RN-2B, item 4) ──────────────────

    def test_q_stop_on_failure_integrado_quando_fixture_degenerado_nao_converge_independencia_d0(self):
        """Confirma, no pipeline REAL (`construir_emos_h2_expanding`,
        nunca reimplementado), que se o fixture degenerado desta
        classe realmente não convergir neste ambiente, a linha fica
        marcada `STATUS_NAO_CONVERGIU` (nunca `STATUS_OK`) e seus
        parâmetros não são publicados — nunca uma previsão inválida
        tratada como válida. Não modifica nenhum comportamento de
        produção, só verifica o que já existe."""
        pares = self._pares_independencia_d0_degenerado(lambda i: 5.0 + 3.0 * (i % 11))

        self._log_ambiente_numerico()
        gerenciador, chamadas = self._observar_chamadas_minimize()
        with gerenciador:
            tabela = emos.construir_emos_h2_expanding(pares)
        linha = tabela.sort_values('init_date').iloc[-1]

        # Chamada B — última avaliação elegível feita INTERNAMENTE pelo
        # pipeline real para o submodelo completo (RN-2D, item 3).
        chamadas_completo = [c for c in chamadas if c['args'][0] is emos._objetivo_completo]
        if chamadas_completo:
            c_b = chamadas_completo[-1]
            self._log_chamada_otimizador(
                'test_q', 'B', 'completo', c_b['resultado'],
                c_b['kwargs'].get('bounds'), emos._objetivo_completo,
                c_b['kwargs'].get('args'),
                theta0=c_b['args'][1] if len(c_b['args']) > 1 else None,
                options=c_b['kwargs'].get('options'))
        else:
            print('[RN-2D/Chamada] test_q chamada B: NAO_CAPTURADA — nenhuma chamada a minimize '
                  'para o submodelo completo ocorreu dentro de construir_emos_h2_expanding '
                  '(nenhuma linha atingiu N_TREINO_MINIMO_EMOS para este fixture) — campo '
                  'ausente, não estimado')

        # Chamada C — chamada direta, feita pelo próprio teste, depois do
        # pipeline, sobre o MESMO conjunto de treino causal (RN-2D, item 3).
        validos = self._validos_causais(pares)
        args_diretos = (
            validos['climatologia_observada'].to_numpy(dtype=float),
            validos['anom_ensemble'].to_numpy(dtype=float),
            validos['erro_clim_sd_mes'].to_numpy(dtype=float),
            validos['spread_relativo'].to_numpy(dtype=float),
            validos['observacao'].to_numpy(dtype=float))
        res_direto = emos.ajustar_emos_completo(*args_diretos)
        self._log_chamada_otimizador('test_q', 'C', 'completo', res_direto,
                                      emos.BOUNDS_COMPLETO, emos._objetivo_completo, args_diretos,
                                      theta0=emos.THETA0_COMPLETO, options=emos.OPCOES_OTIMIZADOR)

        if not res_direto.success:
            self.assertEqual(linha['status_emos_completo'], emos.STATUS_NAO_CONVERGIU)
            self.assertEqual(linha['status_emos'], emos.STATUS_NAO_CONVERGIU)
            self.assertTrue(pd.isna(linha['a']), 'parâmetro de ajuste não convergido não pode '
                                                   'ser publicado como previsão válida')
            print('[EstresseNumerico/StopOnFailure] completo não convergiu neste ambiente — '
                  'status_emos_completo=STATUS_NAO_CONVERGIU confirmado, nenhum parâmetro publicado')
        else:
            self.assertEqual(linha['status_emos_completo'], emos.STATUS_OK)
            print('[EstresseNumerico/StopOnFailure] completo convergiu normalmente neste ambiente '
                  '(regime degenerado não disparou aqui — ambiente-dependente, documentado)')

    def test_r_stop_on_failure_integrado_quando_fixture_degenerado_nao_converge_mutacao(self):
        """Mesma verificação do teste anterior, para o submodelo `d0`
        sobre o fixture degenerado de MutacaoObservacaoFuturaTestCase."""
        pares = self._pares_mutacao_degenerado(125)

        self._log_ambiente_numerico()
        gerenciador, chamadas = self._observar_chamadas_minimize()
        with gerenciador:
            tabela = emos.construir_emos_h2_expanding(pares)
        linha = tabela.sort_values('init_date').iloc[-1]

        # Chamada B — última avaliação elegível feita INTERNAMENTE pelo
        # pipeline real para o submodelo d0 (RN-2D, item 3).
        chamadas_d0 = [c for c in chamadas if c['args'][0] is emos._objetivo_d0]
        if chamadas_d0:
            c_b = chamadas_d0[-1]
            self._log_chamada_otimizador(
                'test_r', 'B', 'd0', c_b['resultado'],
                c_b['kwargs'].get('bounds'), emos._objetivo_d0,
                c_b['kwargs'].get('args'),
                theta0=c_b['args'][1] if len(c_b['args']) > 1 else None,
                options=c_b['kwargs'].get('options'))
        else:
            print('[RN-2D/Chamada] test_r chamada B: NAO_CAPTURADA — nenhuma chamada a minimize '
                  'para o submodelo d0 ocorreu dentro de construir_emos_h2_expanding (nenhuma '
                  'linha atingiu N_TREINO_MINIMO_EMOS para este fixture) — campo ausente, não '
                  'estimado')

        # Chamada C — chamada direta, feita pelo próprio teste, depois do
        # pipeline, sobre o MESMO conjunto de treino causal (RN-2D, item 3).
        validos = self._validos_causais(pares)
        args_diretos = (
            validos['climatologia_observada'].to_numpy(dtype=float),
            validos['anom_ensemble'].to_numpy(dtype=float),
            validos['erro_clim_sd_mes'].to_numpy(dtype=float),
            validos['observacao'].to_numpy(dtype=float))
        res_direto = emos.ajustar_emos_d0(*args_diretos)
        self._log_chamada_otimizador('test_r', 'C', 'd0', res_direto,
                                      emos.BOUNDS_D0, emos._objetivo_d0, args_diretos,
                                      theta0=emos.THETA0_D0, options=emos.OPCOES_OTIMIZADOR)

        if not res_direto.success:
            self.assertEqual(linha['status_emos_d0'], emos.STATUS_NAO_CONVERGIU)
            self.assertEqual(linha['status_emos'], emos.STATUS_NAO_CONVERGIU)
            self.assertTrue(pd.isna(linha['a_d0']), 'parâmetro de ajuste não convergido não pode '
                                                      'ser publicado como previsão válida')
            print('[EstresseNumerico/StopOnFailure] d0 não convergiu neste ambiente — '
                  'status_emos_d0=STATUS_NAO_CONVERGIU confirmado, nenhum parâmetro publicado')
        else:
            self.assertEqual(linha['status_emos_d0'], emos.STATUS_OK)
            print('[EstresseNumerico/StopOnFailure] d0 convergiu normalmente neste ambiente '
                  '(regime degenerado não disparou aqui — ambiente-dependente, documentado)')

    # ── RN-2E.2 — comparação diagnóstica de candidatos de ftol ──────────
    # Puramente observacional: nunca decide se o otimizador de produção
    # deve mudar (isso é decisão de revisão externa, fora deste teste) e
    # nunca altera emos.OPCOES_OTIMIZADOR permanentemente — cada chamada
    # usa sua própria cópia local do dict de opções.

    @classmethod
    def _comparar_ftol_candidatos(cls, rotulo_cenario, theta0, bounds, objetivo_fn, args_objetivo,
                                   submodelo):
        """Roda a MESMA otimização (mesmos dados causais, função
        objetivo, jacobiano numérico `jac=None`, bounds, `gtol`,
        `maxiter`, método L-BFGS-B) com `ftol` em {1e-10 (baseline,
        valor real de produção), 1e-12, 1e-14} — só `ftol` varia.
        Registra tudo incondicionalmente (`_log_chamada_otimizador`,
        já existente) ANTES de qualquer classificação, e classifica
        baseline-vs-candidato nos 4 cenários do RN-2E.2 (item 5) sem
        decidir nada por si."""
        resultados = {}
        for ftol in (1e-10, 1e-12, 1e-14):
            opcoes = dict(emos.OPCOES_OTIMIZADOR)
            opcoes['ftol'] = ftol
            res = emos.minimize(objetivo_fn, theta0, args=args_objetivo, method='L-BFGS-B',
                                 bounds=bounds, jac=None, options=opcoes)
            cls._log_chamada_otimizador(rotulo_cenario, f'ftol={ftol:g}', submodelo, res, bounds,
                                         objetivo_fn, args_objetivo, theta0=theta0, options=opcoes)
            aceitavel, motivo = cls._verificar_resultado_otimizador(
                res, bounds, objetivo_fn, args_objetivo)
            # Comportamento esperado do STOP-ON-FAILURE real
            # (construir_emos_h2_expanding): a gate de produção hoje
            # decide só por `res.success` (item 4 do protocolo deste
            # teste) — nunca pelo contrato de qualidade mais estrito
            # abaixo, que vive só nesta suíte.
            stop_on_failure_esperado = (
                'STATUS_OK (res.success=True — passaria à sanidade da linha avaliada)' if res.success
                else 'STATUS_NAO_CONVERGIU (res.success=False — parâmetro NUNCA publicado)')
            resultados[ftol] = {'res': res, 'aceitavel': aceitavel, 'motivo': motivo,
                                 'stop_on_failure_esperado': stop_on_failure_esperado}
            print(f'[RN-2E.2/{rotulo_cenario}] ftol={ftol:g}: aceitavel_rn2b={aceitavel}  '
                  f'success={res.success}  status={res.status}  fun={res.fun!r}')
            print(f'[RN-2E.2/{rotulo_cenario}]   motivo RN-2B: {motivo}')
            print(f'[RN-2E.2/{rotulo_cenario}]   STOP-ON-FAILURE esperado: {stop_on_failure_esperado}')

        base = resultados[1e-10]
        for ftol_cand in (1e-12, 1e-14):
            cand = resultados[ftol_cand]
            if not base['aceitavel'] and cand['aceitavel']:
                cenario = ('1 — baseline reprovada, candidato aprovado: evidência FAVORÁVEL à '
                           'eficácia do candidato neste ambiente')
            elif not base['aceitavel'] and not cand['aceitavel']:
                cenario = ('2 — baseline e candidato reprovados: candidato insuficiente (ou '
                           'problema adicional ainda não resolvido) neste ambiente')
            elif base['aceitavel'] and cand['aceitavel']:
                cenario = ('3 — baseline e candidato aprovados: INCONCLUSIVO quanto à '
                           'capacidade do candidato de corrigir a falha (regime problemático '
                           'não apareceu nesta execução — não é refutação)')
            else:
                cenario = '4 — baseline aprovada, candidato reprovado: evidência de REGRESSÃO'
            diff_rel_fun = abs(cand['res'].fun - base['res'].fun) / max(abs(base['res'].fun), 1e-12)
            print(f'[RN-2E.2/{rotulo_cenario}] CLASSIFICAÇÃO baseline(1e-10) vs '
                  f'ftol={ftol_cand:g}: CENÁRIO {cenario}')
            print(f'[RN-2E.2/{rotulo_cenario}]   diferença relativa de fun (qualidade) = '
                  f'{diff_rel_fun:.6e}')
        return resultados

    def test_s_comparacao_ftol_candidato_vs_baseline_mesma_execucao(self):
        """RN-2E.2 — compara, na MESMA execução/máquina desta CI,
        ftol=1e-10 (baseline, o valor real de produção) contra 1e-12
        e 1e-14 (candidatos), a partir do theta0 ORIGINAL — a
        trajetória operacional real — para os submodelos completo e
        d0, e SEPARADAMENTE (nunca confundido com a trajetória
        operacional) a partir do ponto subótimo real registrado na
        RN-2D (`x=[3.999800458117186, 0.60000412922862,
        -18.649803463229464, 0.0]`). Puramente diagnóstico: nunca
        altera `emos.OPCOES_OTIMIZADOR` permanentemente (cada chamada
        usa sua própria cópia local), nunca decide aprovação de
        produção por si — a única asserção aqui é uma checagem de
        finitude que não falha por causa do RESULTADO da comparação
        de ftol, e este teste nunca substitui, afrouxa nem desativa
        test_o/test_p/test_q/test_r."""
        self._log_ambiente_numerico()

        # ── Trajetória operacional real: sempre a partir do theta0 ──
        # original — nunca do ponto subótimo (isso vem depois, isolado).
        pares_completo = self._pares_independencia_d0_degenerado(lambda i: 5.0 + 3.0 * (i % 11))
        validos_completo = self._validos_causais(pares_completo)
        args_completo = (
            validos_completo['climatologia_observada'].to_numpy(dtype=float),
            validos_completo['anom_ensemble'].to_numpy(dtype=float),
            validos_completo['erro_clim_sd_mes'].to_numpy(dtype=float),
            validos_completo['spread_relativo'].to_numpy(dtype=float),
            validos_completo['observacao'].to_numpy(dtype=float))
        res_completo_theta0 = self._comparar_ftol_candidatos(
            'test_s_completo_theta0_original', emos.THETA0_COMPLETO, emos.BOUNDS_COMPLETO,
            emos._objetivo_completo, args_completo, 'completo')

        pares_d0 = self._pares_mutacao_degenerado(125)
        validos_d0 = self._validos_causais(pares_d0)
        args_d0 = (
            validos_d0['climatologia_observada'].to_numpy(dtype=float),
            validos_d0['anom_ensemble'].to_numpy(dtype=float),
            validos_d0['erro_clim_sd_mes'].to_numpy(dtype=float),
            validos_d0['observacao'].to_numpy(dtype=float))
        res_d0_theta0 = self._comparar_ftol_candidatos(
            'test_s_d0_theta0_original', emos.THETA0_D0, emos.BOUNDS_D0,
            emos._objetivo_d0, args_d0, 'd0')

        # ── Cenário DIAGNÓSTICO separado — reinício a partir do ponto ──
        # subótimo real da RN-2D. NUNCA é a trajetória operacional (que
        # está inteiramente acima, a partir de theta0 original); serve
        # só para observar se, exatamente nesse ponto, um ftol menor
        # ainda indica melhora disponível — não deve ser extrapolado
        # para a trajetória real sem a CI confirmar separadamente.
        print('[RN-2E.2] --- INÍCIO cenário de REINÍCIO DIAGNÓSTICO (ponto subótimo real da '
              'RN-2D) — NUNCA a trajetória operacional, que usa sempre theta0 original ---')
        x_subotimo_rn2d = np.array(
            [3.999800458117186, 0.60000412922862, -18.649803463229464, 0.0])
        res_completo_reinicio = self._comparar_ftol_candidatos(
            'test_s_completo_REINICIO_DIAGNOSTICO_ponto_rn2d', x_subotimo_rn2d,
            emos.BOUNDS_COMPLETO, emos._objetivo_completo, args_completo, 'completo')
        print('[RN-2E.2] --- FIM cenário de reinício diagnóstico ---')

        todos_finitos = all(
            np.all(np.isfinite(r['res'].x)) and np.isfinite(r['res'].fun)
            for bloco in (res_completo_theta0, res_d0_theta0, res_completo_reinicio)
            for r in bloco.values())
        self.assertTrue(todos_finitos, 'alguma das 9 chamadas de comparação de ftol produziu '
                                        'x/fun não finito nesta execução — isso não deveria '
                                        'acontecer em nenhum dos três ftol testados')


class StopOnFailureSinteticoTestCase(unittest.TestCase):
    """Protocolo, seção 16.4/16.5/25 — status_emos dispara corretamente
    em não-convergência e em solução numericamente inválida, em casos
    sintéticos construídos especificamente para cada um."""

    def test_a_nao_convergencia_simulada(self):
        with mock.patch.object(emos, 'minimize') as m:
            resultado_falso = mock.Mock(success=False, status=1, message='falhou', nit=5, nfev=10,
                                         x=np.array([0.0, 1.0, 0.0, 0.0]))
            m.return_value = resultado_falso
            res = emos.ajustar_emos_completo(np.full(5, 70.0), np.zeros(5), np.full(5, 20.0),
                                               np.ones(5), np.full(5, 70.0))
            self.assertFalse(res.success)

    def test_b_solucao_numericamente_invalida_gamma_c_fora_do_bound(self):
        theta_invalido = np.array([0.0, 1.0, 999.0, 0.0])  # gamma_c fora do bound [-20,20]
        erro_sd = np.full(5, 20.0)
        spread_rel = np.ones(5)
        self.assertFalse(emos._sanidade_completo(theta_invalido, erro_sd, spread_rel, 1.0))

    def test_c_solucao_numericamente_invalida_d_negativo(self):
        theta_invalido = np.array([0.0, 1.0, 0.0, -0.5])
        erro_sd = np.full(5, 20.0)
        spread_rel = np.ones(5)
        self.assertFalse(emos._sanidade_completo(theta_invalido, erro_sd, spread_rel, 1.0))

    def test_d_sanidade_d0_gamma_c_fora_do_bound(self):
        theta_invalido = np.array([0.0, 1.0, -999.0])
        erro_sd = np.full(5, 20.0)
        self.assertFalse(emos._sanidade_d0(theta_invalido, erro_sd, 1.0))

    def test_e_sanidade_ok_em_caso_valido(self):
        theta_valido = np.array([0.0, 1.0, 0.0, 0.1])
        erro_sd = np.full(5, 20.0)
        spread_rel = np.ones(5)
        self.assertTrue(emos._sanidade_completo(theta_valido, erro_sd, spread_rel, 1.0))

    def test_f_crps_final_nao_finito_invalida_a_solucao_completo(self):
        """Auditoria externa, item 1/2 — `crps_final` (res.fun) não
        finito tem que invalidar a solução mesmo com todo o resto
        numericamente correto (condição 6 da seção 16.5, ausente até
        esta revisão)."""
        theta_valido = np.array([0.0, 1.0, 0.0, 0.1])
        erro_sd = np.full(5, 20.0)
        spread_rel = np.ones(5)
        self.assertFalse(emos._sanidade_completo(theta_valido, erro_sd, spread_rel, np.inf))
        self.assertFalse(emos._sanidade_completo(theta_valido, erro_sd, spread_rel, np.nan))

    def test_g_crps_final_nao_finito_invalida_a_solucao_d0(self):
        theta_valido = np.array([0.0, 1.0, 0.0])
        erro_sd = np.full(5, 20.0)
        self.assertFalse(emos._sanidade_d0(theta_valido, erro_sd, np.inf))
        self.assertFalse(emos._sanidade_d0(theta_valido, erro_sd, np.nan))

    def test_h_sanidade_linha_avaliada_detecta_sigma_nao_finito(self):
        self.assertFalse(emos._sanidade_linha_avaliada(5.0, np.inf, 0.3, 6.0, 5.0, 2.0))
        self.assertFalse(emos._sanidade_linha_avaliada(5.0, 0.0, 0.3, 6.0, 5.0, 2.0))
        self.assertFalse(emos._sanidade_linha_avaliada(5.0, -1.0, 0.3, 6.0, 5.0, 2.0))

    def test_i_sanidade_linha_avaliada_detecta_campo_probabilistico_nao_finito(self):
        self.assertFalse(emos._sanidade_linha_avaliada(5.0, 10.0, np.nan, 6.0, 5.0, 2.0))
        self.assertFalse(emos._sanidade_linha_avaliada(5.0, 10.0, 0.3, np.inf, 5.0, 2.0))
        self.assertFalse(emos._sanidade_linha_avaliada(5.0, 10.0, 0.3, 6.0, np.nan, 2.0))
        self.assertFalse(emos._sanidade_linha_avaliada(5.0, 10.0, 0.3, 6.0, 5.0, np.inf))

    def test_j_sanidade_linha_avaliada_ok_em_caso_valido(self):
        self.assertTrue(emos._sanidade_linha_avaliada(5.0, 10.0, 0.3, 6.0, 5.0, 2.0))


class StopOnFailureIntegradoTestCase(unittest.TestCase):
    """Fase E/L do pedido de implementação real — STOP-ON-FAILURE
    precisa disparar de ponta a ponta na tabela expanding real (não só
    nas funções de sanidade isoladas): uma falha de convergência numa
    única avaliação tem que aparecer em `status_emos` daquela linha E
    ser detectada por `_verificar_falhas_de_convergencia` — nunca
    descartada silenciosamente, nunca contaminando outras avaliações."""

    def _pares(self, n):
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
                'ensemble_std': 15.0, 'membros': np.full(24, 100.0 + 0.5 * i),
                'climatologia_modelo_raw': 90.0, 'climatologia_observada': 70.0,
                'anom_ensemble': (100.0 + 0.5 * i) - 90.0,
                'spread_clim_modelo_mes': 15.0, 'erro_clim_sd_mes': 20.0,
                'spread_relativo': 1.0,
                'tercil_33': 60.0, 'tercil_67': 90.0,
                'anos_hist_climatologia': np.linspace(50.0, 110.0, 25),
                'valido': True,
            })
        return linhas

    def test_a_falha_de_convergencia_em_uma_unica_avaliacao_e_isolada_e_detectada(self):
        linhas = self._pares(130)
        pares = pd.DataFrame(linhas)
        avaliada_alvo = pares.sort_values('init_date').iloc[-1]['init_date']
        orig_minimize = emos.minimize

        # 1ª passada (sem forçar falha, só contando) — descobre quantas
        # vezes o objetivo COMPLETO é de fato chamado (1 tentativa de
        # ajuste por avaliação elegível, em ordem causal, independente de
        # sucesso ou falha natural); a avaliação-alvo (a última da série)
        # corresponde à ÚLTIMA dessas chamadas. Contar por tentativa (não
        # por `status_emos=='ok'`) é necessário porque dados sintéticos
        # perfeitamente lineares/sem ruído podem produzir falhas de
        # convergência NATURAIS em alguns ajustes — irrelevante para este
        # teste, que só precisa saber qual é a ÚLTIMA tentativa real.
        contagem = {'n': 0}

        def contar(fun, x0, args=(), **kwargs):
            res = orig_minimize(fun, x0, args=args, **kwargs)
            if fun is emos._objetivo_completo:
                contagem['n'] += 1
            return res

        with mock.patch.object(emos, 'minimize', side_effect=contar):
            emos.construir_emos_h2_expanding(pares)
        n_chamadas_completo = contagem['n']
        self.assertGreater(n_chamadas_completo, 0)

        contador = {'completo': 0}

        def minimize_falho_na_ultima_completo(fun, x0, args=(), **kwargs):
            res = orig_minimize(fun, x0, args=args, **kwargs)
            if fun is emos._objetivo_completo:
                contador['completo'] += 1
                if contador['completo'] == n_chamadas_completo:
                    res.success = False
                    res.status = 99
                    res.message = 'falha forçada pelo teste'
            return res

        with mock.patch.object(emos, 'minimize', side_effect=minimize_falho_na_ultima_completo):
            tabela = emos.construir_emos_h2_expanding(pares)

        linha_alvo = tabela[tabela['init_date'] == avaliada_alvo].iloc[0]
        self.assertEqual(linha_alvo['status_emos_completo'], emos.STATUS_NAO_CONVERGIU)
        self.assertEqual(linha_alvo['status_emos'], emos.STATUS_NAO_CONVERGIU)

        convergencia = emos._verificar_falhas_de_convergencia(tabela)
        self.assertFalse(convergencia['ok'])
        self.assertIn(avaliada_alvo, convergencia['datas'])

        # a tabela SEM a falha forçada (reconstruída de novo, sem mock)
        # serve de referência: nenhuma avaliação ALÉM da alvo pode ter
        # mudado de status.
        tabela_sem_falha = emos.construir_emos_h2_expanding(pares)
        outras = tabela[tabela['init_date'] != avaliada_alvo].set_index('init_date')['status_emos']
        outras_sem_falha = tabela_sem_falha[
            tabela_sem_falha['init_date'] != avaliada_alvo].set_index('init_date')['status_emos']
        pd.testing.assert_series_equal(outras.sort_index(), outras_sem_falha.sort_index(),
                                        check_names=False)


class ClimatologiaCausalTestCase(unittest.TestCase):
    """Fase E do pedido — confirma, na própria função usada pela
    implementação real (`construir_pares_h2_emos`, via
    `warm._indice_causal_por_mes` reaproveitada sem modificação), que
    nenhuma climatologia causal usa a própria linha avaliada ou o
    futuro, e que `spread_relativo` deriva só dessa climatologia
    causal — nunca de `ensemble_std` futuro."""

    def test_a_indice_causal_nunca_inclui_a_propria_linha_ou_futuro(self):
        import cfsv2_emos_h2_viabilidade_warmup as warm
        tabela = pd.DataFrame([
            {'init_date': '2000-01', 'lead': 2, 'ensemble_std': 999.0},  # "futuro" relativo a 1999
            {'init_date': '1999-01', 'lead': 2, 'ensemble_std': 10.0},
            {'init_date': '1998-01', 'lead': 2, 'ensemble_std': 5.0},
        ])
        calc = warm._indice_causal_por_mes(tabela, 2, 'ensemble_std')
        valores_1999 = calc('1999-01').tolist()
        self.assertEqual(valores_1999, [5.0], "só 1998-01 (estritamente anterior) deveria contar; "
                                               "nunca a própria linha de 1999-01 nem 2000-01 (futuro)")

    def test_b_spread_relativo_usa_so_climatologia_causal_na_construcao_real(self):
        import cfsv2_emos_h2_viabilidade_warmup as warm
        import cfsv2_validacao_cientifica as v_mod

        class _FakeTabelaEnsemble(pd.DataFrame):
            pass

        linhas_ensemble = []
        for i in range(6):
            init_date = f'1999-{i + 1:02d}'
            target_p = v_mod._periodo(init_date) + 1
            linhas_ensemble.append({
                'init_date': init_date, 'target_month': str(target_p), 'lead': 2,
                'target_ano': target_p.year, 'target_mes': target_p.month,
                'ensemble_mean': 100.0, 'ensemble_std': 10.0 + i,
                'observacao': 80.0, 'erro_assinado': 5.0,
                'membros': np.full(24, 100.0),
            })
        tabela_ensemble = pd.DataFrame(linhas_ensemble)

        calc_spread = warm._indice_causal_por_mes(tabela_ensemble, 2, 'ensemble_std')
        # avaliando a última linha (1999-06): só meses-calendário iguais
        # (junho) E estritamente anteriores entrariam — como cada linha
        # aqui é um mês-calendário diferente, NENHUM qualifica (mesma
        # garantia já testada na viabilidade estrutural).
        hist = calc_spread('1999-06')
        self.assertEqual(len(hist), 0, "nenhuma linha de outro mês-calendário deveria contar")


class ComDadosReaisTestCase(unittest.TestCase):
    """Smoke test contra os dados já aprovados do repositório (sem
    rede) — confirma N=95, ausência de leakage, nenhuma falha de
    convergência e que a decisão final foi computada."""

    def setUp(self):
        if not emos.g.DIRETORIO_SAIDA.exists():
            self.skipTest("dados reais da 2C.3C não disponíveis nesta árvore de trabalho")
        self.resultado, self.tabela = emos.executar_emos_h2(n_resamples_bootstrap=30)

    def test_a_sem_stop_on_failure(self):
        self.assertFalse(self.resultado.get('STOP_ON_FAILURE', True), self.resultado.get('motivo'))

    def test_b_n_final_e_95(self):
        self.assertEqual(self.resultado['n_casos']['n_final'], 95)
        self.assertTrue(self.resultado['n_casos']['bate_com_esperado'])

    def test_c_primeira_avaliacao_e_2003_02(self):
        self.assertEqual(self.resultado['primeira_init_date_avaliavel'], '2003-02')

    def test_d_sem_leakage(self):
        self.assertTrue(self.resultado['leakage_check']['ok'])

    def test_e_sem_falhas_de_convergencia(self):
        self.assertTrue(self.resultado['verificacao_falhas_convergencia']['ok'])

    def test_f_decisao_final_presente(self):
        self.assertIn('aprovado_componente_dinamico_de_spread',
                       self.resultado['decisao_criterio_pre_registrado'])

    def test_f2_criterios_3_e_4_reclassificados_como_diagnostico_nao_binario(self):
        """Auditoria externa, 3ª rodada — critérios 3/4 nunca podem ser
        reportados como aprovação binária certificada: critério 3 é
        diagnóstico condicionado a limiar não pré-registrado; critério 4
        é explicitamente não integralmente verificado (avalia só
        cobertura, nunca PIT). A decisão final (False) e os valores
        numéricos calculados (cond3/cond4) permanecem preservados.

        Usa o JSON já gerado por `--executar` (bootstrap com as 500
        reamostras de produção), NUNCA `self.resultado` desta classe —
        este teste usa só 30 reamostras (por velocidade), amostra
        pequena o bastante para o IC de CRPSS_spread_dinamico (ponto
        central ~1,5e-7, essencialmente zero) cruzar por acaso para o
        lado positivo, mudando cond1 sem nenhuma mudança real na
        ciência — não é a quantidade que este teste quer verificar."""
        if not emos.CAMINHO_METRICAS_JSON.exists():
            self.skipTest("métricas do EMOS H2 ainda não geradas nesta árvore de trabalho")
        import json
        resultado_producao = json.loads(emos.CAMINHO_METRICAS_JSON.read_text())
        decisao = resultado_producao['decisao_criterio_pre_registrado']
        self.assertEqual(decisao['criterio_3_classificacao'],
                          'diagnostico_condicionado_a_limiar_nao_pre_registrado')
        self.assertEqual(decisao['criterio_4_classificacao'], 'nao_integralmente_verificado')
        self.assertFalse(decisao['aprovado_componente_dinamico_de_spread'])
        self.assertEqual(len(decisao['motivos_suficientes_para_nao_aprovacao']), 2)
        # valores calculados preservados (rastreabilidade)
        self.assertIn('criterio_3_bss_dentro_do_limiar_calculado', decisao)
        self.assertIn('criterio_4_cobertura_dentro_do_esperado_vs_raw', decisao)

    def test_g_probabilidades_tercil_somam_um(self):
        self.assertTrue(self.resultado['brier_bss']['verificacao_probabilidades_somam_um']['ok'])

    def test_h_metodos_3_1_a_3_4_e_dashboard_nao_tocados(self):
        import subprocess
        import cfsv2_calibracao_aditiva as a
        import cfsv2_calibracao_mos_linear as mos_mod
        caminhos = [a.CAMINHO_TABELA_EXPANDING, mos_mod.CAMINHO_TABELA_EXPANDING,
                    emos.ROOT / 'docs' / 'index.html']
        for caminho in caminhos:
            resultado_git = subprocess.run(
                ['git', 'diff', '--quiet', 'HEAD', '--', str(caminho.relative_to(a.ROOT))],
                cwd=a.ROOT, capture_output=True)
            self.assertEqual(resultado_git.returncode, 0, f"{caminho} divergiu do HEAD commitado")

    def test_i_sigma_positivo_e_finito_em_todas_as_linhas_de_treino_de_uma_avaliacao_real(self):
        """Fase D/E do pedido — não só na linha avaliada: recalcula
        sigma (modelo completo) para CADA linha do conjunto de treino
        de uma avaliação OK real, usando os próprios parâmetros
        ajustados dessa avaliação."""
        ok = self.tabela[self.tabela['status_emos'] == emos.STATUS_OK]
        self.assertGreater(len(ok), 0)
        linha = ok.sort_values('init_date').iloc[-1]
        avaliada_p = v._periodo(linha['init_date'])

        pares = emos.construir_pares_h2_emos(
            emos.g.construir_tabela_ensemble(
                v.construir_base_pareada(v.carregar_cfsv2_raw(), v.carregar_chirps_v3_historico())),
            v._enriquecer_com_climatologia(
                v.construir_base_pareada(v.carregar_cfsv2_raw(), v.carregar_chirps_v3_historico()),
                v.carregar_chirps_v3_historico()),
            v._obs_dict(v.carregar_chirps_v3_historico()))
        pares = pares.assign(_p=pd.PeriodIndex(pares['init_date'], freq='M')).sort_values('_p')
        validos = pares[pares['valido'] & (pares['_p'] < avaliada_p)
                         & (pd.PeriodIndex(pares['target_month'], freq='M') < avaliada_p)]

        c = float(np.exp(linha['gamma_c']))
        sigma_treino = validos['erro_clim_sd_mes'].values * np.sqrt(
            c + linha['d'] * validos['spread_relativo'].values ** 2)
        self.assertTrue(np.all(np.isfinite(sigma_treino)))
        self.assertTrue(np.all(sigma_treino > 0))

    def test_j_benchmarks_disponiveis_em_todos_os_95_casos_sem_diferenca_de_amostra(self):
        ok = self.tabela[self.tabela['status_emos'] == emos.STATUS_OK]
        self.assertEqual(len(ok), 95)
        for coluna in ('crps_emos', 'crps_d0', 'crps_raw', 'crps_climatologia'):
            self.assertEqual(int(ok[coluna].isna().sum()), 0,
                              f"{coluna} ausente em algum dos 95 casos avaliáveis")


class RelatorioEmosH2TestCase(unittest.TestCase):
    """Smoke test do gerador de relatório — nunca recalcula, só
    formata; nunca declara o EMOS validado ou pronto para produção."""

    _FRASES_PROIBIDAS = ('o modelo está validado', 'está pronto para produção',
                          'é um método aprovado', 'nowcast')

    def _assert_nunca_declara_conclusao_isolada(self, texto):
        baixo = texto.lower()
        for frase in self._FRASES_PROIBIDAS:
            self.assertNotIn(frase, baixo, f"texto afirma/usa termo proibido: {frase!r}")

    def test_a_stop_on_failure_gera_relatorio_minimo(self):
        import cfsv2_relatorio_emos_h2 as rel
        resultados = {'STOP_ON_FAILURE': True, 'motivo': 'teste'}
        relatorio = rel.gerar_relatorio_markdown(resultados)
        self.assertIn('STOP-ON-FAILURE', relatorio)
        self._assert_nunca_declara_conclusao_isolada(relatorio)

    def test_b_relatorio_real_cobre_secoes_obrigatorias(self):
        if not emos.CAMINHO_METRICAS_JSON.exists():
            self.skipTest("métricas do EMOS H2 ainda não geradas nesta árvore de trabalho")
        import json
        import cfsv2_relatorio_emos_h2 as rel
        resultados = json.loads(emos.CAMINHO_METRICAS_JSON.read_text())
        relatorio = rel.gerar_relatorio_markdown(resultados)
        for secao in ('Amostra avaliada', 'CRPS médio', 'CRPSS', 'Brier', 'Cobertura', 'PIT',
                      'Bias', 'Diagnóstico de parâmetros', 'Decisão', 'Conclusão', 'Limitações'):
            self.assertIn(secao, relatorio)
        self._assert_nunca_declara_conclusao_isolada(relatorio)


if __name__ == '__main__':
    unittest.main()
