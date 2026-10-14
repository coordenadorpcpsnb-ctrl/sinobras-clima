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

Roda com:
    python -m unittest tests.test_cfsv2_emos_h2_implementacao -v
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
from scipy.integrate import quad

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import cfsv2_calibracao_mos_linear as mos  # noqa: E402
import cfsv2_emos_h2_implementacao as emos  # noqa: E402
import cfsv2_validacao_cientifica as v  # noqa: E402


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


class MutacaoObservacaoFuturaTestCase(unittest.TestCase):
    """Protocolo, seção 23 (item 14 do pedido de implementação) —
    alterar drasticamente a OBSERVAÇÃO de uma linha com
    `target_month >= init_date_avaliada` não pode mudar nada
    (parâmetros, forecast/distribuição, CRPS) de uma avaliação
    passada."""

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
        linhas = self._pares(125)
        tabela_antes = emos.construir_emos_h2_expanding(pd.DataFrame(linhas))
        avaliacao_antes = tabela_antes.sort_values('init_date').iloc[-1].copy()
        self.assertEqual(avaliacao_antes['status_emos'], emos.STATUS_OK)

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
        self.assertFalse(emos._sanidade_completo(theta_invalido, erro_sd, spread_rel))

    def test_c_solucao_numericamente_invalida_d_negativo(self):
        theta_invalido = np.array([0.0, 1.0, 0.0, -0.5])
        erro_sd = np.full(5, 20.0)
        spread_rel = np.ones(5)
        self.assertFalse(emos._sanidade_completo(theta_invalido, erro_sd, spread_rel))

    def test_d_sanidade_d0_gamma_c_fora_do_bound(self):
        theta_invalido = np.array([0.0, 1.0, -999.0])
        erro_sd = np.full(5, 20.0)
        self.assertFalse(emos._sanidade_d0(theta_invalido, erro_sd))

    def test_e_sanidade_ok_em_caso_valido(self):
        theta_valido = np.array([0.0, 1.0, 0.0, 0.1])
        erro_sd = np.full(5, 20.0)
        spread_rel = np.ones(5)
        self.assertTrue(emos._sanidade_completo(theta_valido, erro_sd, spread_rel))


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

    def test_g_probabilidades_tercil_somam_um(self):
        self.assertTrue(self.resultado['brier_bss']['verificacao_probabilidades_somam_um']['ok'])

    def test_h_metodos_3_1_a_3_4_e_dashboard_nao_tocados(self):
        import subprocess
        import cfsv2_calibracao_aditiva as a
        import cfsv2_calibracao_mos_linear as mos_mod
        for caminho in (a.CAMINHO_TABELA_EXPANDING, mos_mod.CAMINHO_TABELA_EXPANDING):
            resultado_git = subprocess.run(
                ['git', 'diff', '--quiet', 'HEAD', '--', str(caminho.relative_to(a.ROOT))],
                cwd=a.ROOT, capture_output=True)
            self.assertEqual(resultado_git.returncode, 0, f"{caminho} divergiu do HEAD commitado")


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
