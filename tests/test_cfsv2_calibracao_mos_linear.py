#!/usr/bin/env python3
"""
tests/test_cfsv2_calibracao_mos_linear.py — Fase 2C.3D, Método 3.4
(MOS linear causal no espaço de anomalias).

Item 8 do pedido — foco em: nenhuma linha de treino com init_date >=
avaliada; própria linha nunca entra no OLS; outro lead nunca entra no
treino; alterar observação/forecast/climatologia futuros não muda
alpha/beta passado nem as anomalias históricas já usadas; linhas sem
par válido nunca contam para n_treino_mos; nenhuma linha NaN/Inf entra
no OLS; e um teste sintético deliberadamente leaky que demonstra o
ganho artificial bloqueado pela implementação real.

Dados SINTÉTICOS para a lógica central (nenhuma rede necessária); as
classes *ComDadosReais* leem os arquivos já aprovados do repositório
(sem rede, pulam se ausentes).

Roda com:
    python -m unittest tests.test_cfsv2_calibracao_mos_linear -v
"""

import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import cfsv2_calibracao_aditiva as a  # noqa: E402
import cfsv2_calibracao_mos_linear as mos  # noqa: E402
import cfsv2_validacao_cientifica as v  # noqa: E402


def _linha(init_date, lead, target_mes=None, forecast=100.0, obs=80.0,
           clim_media=None, clim_modelo=None):
    target_p = v._periodo(init_date) + (lead - 1)
    return {
        'init_date': init_date, 'target_month': str(target_p), 'target_ano': target_p.year,
        'target_mes': target_mes if target_mes is not None else target_p.month,
        'lead': lead, 'member': 1, 'forecast_prec_mm': forecast, 'obs_prec_mm': obs,
        'clim_media': clim_media, 'clim_modelo_media': clim_modelo,
    }


def _serie_valida(n, lead=1, mes_inicial=1, ano_inicial=1990, forecast_fn=None, obs_fn=None,
                   clim_media=70.0, clim_modelo=90.0):
    """Monta `n` linhas mensais consecutivas (pooling entre meses),
    todas com climatologia causal disponível — par_anomalia_valido=True
    em todas, por construção."""
    forecast_fn = forecast_fn or (lambda i: 100.0 + i)
    obs_fn = obs_fn or (lambda i: 80.0 + 0.3 * i)
    linhas = []
    for i in range(n):
        mes = ((mes_inicial - 1 + i) % 12) + 1
        ano = ano_inicial + (mes_inicial - 1 + i) // 12
        linhas.append(_linha(f'{ano}-{mes:02d}', lead, mes, forecast=forecast_fn(i),
                              obs=obs_fn(i), clim_media=clim_media, clim_modelo=clim_modelo))
    return linhas


class ParAnomaliaValidoTestCase(unittest.TestCase):
    """Item 3/8 do pedido — linhas sem par válido nunca contam para
    n_treino_mos."""

    def test_a_linha_sem_climatologia_modelo_e_invalida(self):
        linhas = _serie_valida(130)
        linhas[5]['clim_modelo_media'] = None  # climatologia do modelo indisponível
        base = pd.DataFrame(linhas)
        tabela = mos.construir_tabela_mos_linear(base)
        linha_invalida = tabela.iloc[5]
        self.assertFalse(linha_invalida['par_anomalia_valido'])
        self.assertEqual(linha_invalida['status_mos'], mos.STATUS_ANOMALIA_INDISPONIVEL)
        # colunas numéricas com None viram NaN ao passar por um DataFrame
        # (mesmo padrão já usado nos testes da aditiva/multiplicativa) —
        # pd.isna, nunca assertIsNone, é o jeito correto de checar isso.
        self.assertTrue(pd.isna(linha_invalida['forecast_mos']))

    def test_b_linha_invalida_nao_e_contada_no_n_treino_mos_de_linhas_posteriores(self):
        linhas = _serie_valida(130)
        linhas[5]['clim_modelo_media'] = None
        base = pd.DataFrame(linhas)
        tabela = mos.construir_tabela_mos_linear(base)
        # posição 6 (0-indexed) tem 5 pares válidos anteriores (posições
        # 0-4), NÃO 6 (a linha 5 inválida não conta).
        self.assertEqual(tabela.iloc[6]['n_treino_mos'], 5)

    def test_c_nunca_preenche_nan_nem_usa_zero_como_substituto(self):
        """climatologia_modelo_raw indisponível invalida anom_modelo_raw
        (e, por extensão, par_anomalia_valido) — mas NUNCA é preenchida
        com zero/interpolada; anom_observada, que depende só de
        climatologia_observada (ainda disponível aqui), permanece
        corretamente calculável e não é descartada por engano."""
        linhas = _serie_valida(5)
        linhas[2]['clim_modelo_media'] = None
        base = pd.DataFrame(linhas)
        tabela = mos.construir_tabela_mos_linear(base)
        linha = tabela.iloc[2]
        self.assertTrue(pd.isna(linha['anom_modelo_raw']))
        self.assertFalse(linha['par_anomalia_valido'])
        self.assertFalse(pd.isna(linha['anom_observada']))
        self.assertNotEqual(linha['anom_modelo_raw'], 0.0)


class TreinoCausalTestCase(unittest.TestCase):
    """Itens 1, 2, 3 (lista de testes do item 8) — nenhuma linha de
    treino com init_date >= avaliada; própria linha nunca entra no
    OLS; outro lead nunca entra no treino."""

    def test_a_periodo_treino_fim_sempre_estritamente_anterior(self):
        linhas = _serie_valida(130)
        base = pd.DataFrame(linhas)
        tabela = mos.construir_tabela_mos_linear(base)
        ok = tabela[tabela['status_mos'] == mos.STATUS_OK]
        for _, row in ok.iterrows():
            self.assertLess(v._periodo(row['periodo_treino_fim']), v._periodo(row['init_date']))

    def test_b_propria_linha_nunca_entra_no_proprio_ols(self):
        linhas = _serie_valida(120, forecast_fn=lambda i: 100.0 + i, obs_fn=lambda i: 80.0 + 0.5 * i)
        linhas.append(_linha('2000-01', 1, 1, forecast=100.0, obs=-99999.0,
                              clim_media=70.0, clim_modelo=90.0))
        base = pd.DataFrame(linhas)
        tabela = mos.construir_tabela_mos_linear(base)
        ultima = tabela.sort_values('init_date').iloc[-1]
        self.assertEqual(ultima['status_mos'], mos.STATUS_OK)
        # se a observação absurda da própria linha tivesse entrado no
        # treino, alpha teria disparado para um valor extremo negativo.
        self.assertGreater(ultima['alpha'], -1000.0)

    def test_c_outro_lead_nunca_entra_no_treino(self):
        linhas_lead1 = _serie_valida(130, lead=1, forecast_fn=lambda i: 100.0,
                                      obs_fn=lambda i: 80.0)
        linhas_lead2_contaminantes = _serie_valida(130, lead=2, forecast_fn=lambda i: 500.0,
                                                     obs_fn=lambda i: 0.0)
        base = pd.DataFrame(linhas_lead1 + linhas_lead2_contaminantes)
        tabela = mos.construir_tabela_mos_linear(base)
        tabela_lead1 = tabela[tabela['lead'] == 1]
        resultado = mos._verificar_outro_lead_nunca_contaminou_treino(tabela)
        self.assertTrue(resultado['ok'], resultado['problemas'])
        # o alpha do lead 1 não pode refletir a observação=0/forecast=500 do lead 2
        ok_lead1 = tabela_lead1[tabela_lead1['status_mos'] == mos.STATUS_OK]
        if len(ok_lead1) > 0:
            self.assertLess(ok_lead1.iloc[-1]['alpha'], 100.0)


class FuturoNaoAlteraPassadoTestCase(unittest.TestCase):
    """Itens 4, 5, 6 da lista do item 8 — alterar observação/forecast/
    climatologia futuros não muda alpha/beta passado nem as anomalias
    históricas já usadas."""

    def _tabela_base(self):
        return _serie_valida(130, forecast_fn=lambda i: 100.0 + 0.5 * i,
                              obs_fn=lambda i: 80.0 + 0.3 * i)

    def test_a_alterar_observacao_futura_nao_muda_alpha_beta_passado(self):
        linhas = self._tabela_base()
        base_antes = pd.DataFrame(linhas)
        tabela_antes = mos.construir_tabela_mos_linear(base_antes)
        linha_passada_antes = tabela_antes[
            tabela_antes['status_mos'] == mos.STATUS_OK].sort_values('init_date').iloc[0].copy()

        linhas_mutadas = [dict(linha) for linha in linhas]
        linhas_mutadas[-1]['obs_prec_mm'] = -999999.0
        base_depois = pd.DataFrame(linhas_mutadas)
        tabela_depois = mos.construir_tabela_mos_linear(base_depois)
        linha_passada_depois = tabela_depois[
            tabela_depois['init_date'] == linha_passada_antes['init_date']].iloc[0]

        self.assertAlmostEqual(linha_passada_antes['alpha'], linha_passada_depois['alpha'], places=9)
        self.assertAlmostEqual(linha_passada_antes['beta'], linha_passada_depois['beta'], places=9)

    def test_b_alterar_forecast_futuro_nao_muda_alpha_beta_passado(self):
        linhas = self._tabela_base()
        base_antes = pd.DataFrame(linhas)
        tabela_antes = mos.construir_tabela_mos_linear(base_antes)
        linha_passada_antes = tabela_antes[
            tabela_antes['status_mos'] == mos.STATUS_OK].sort_values('init_date').iloc[0].copy()

        linhas_mutadas = [dict(linha) for linha in linhas]
        linhas_mutadas[-1]['forecast_prec_mm'] = 999999.0
        base_depois = pd.DataFrame(linhas_mutadas)
        tabela_depois = mos.construir_tabela_mos_linear(base_depois)
        linha_passada_depois = tabela_depois[
            tabela_depois['init_date'] == linha_passada_antes['init_date']].iloc[0]

        self.assertAlmostEqual(linha_passada_antes['alpha'], linha_passada_depois['alpha'], places=9)
        self.assertAlmostEqual(linha_passada_antes['beta'], linha_passada_depois['beta'], places=9)

    def test_c_alterar_climatologia_futura_nao_muda_anomalias_historicas_ja_usadas(self):
        linhas = self._tabela_base()
        base_antes = pd.DataFrame(linhas)
        tabela_antes = mos.construir_tabela_mos_linear(base_antes)
        linha_passada_antes = tabela_antes[
            tabela_antes['status_mos'] == mos.STATUS_OK].sort_values('init_date').iloc[0].copy()

        linhas_mutadas = [dict(linha) for linha in linhas]
        linhas_mutadas[-1]['clim_media'] = 12345.0
        linhas_mutadas[-1]['clim_modelo_media'] = 54321.0
        base_depois = pd.DataFrame(linhas_mutadas)
        tabela_depois = mos.construir_tabela_mos_linear(base_depois)
        linha_passada_depois = tabela_depois[
            tabela_depois['init_date'] == linha_passada_antes['init_date']].iloc[0]

        self.assertAlmostEqual(linha_passada_antes['anom_modelo_raw'],
                                linha_passada_depois['anom_modelo_raw'], places=9)
        self.assertAlmostEqual(linha_passada_antes['anom_observada'],
                                linha_passada_depois['anom_observada'], places=9)
        self.assertAlmostEqual(linha_passada_antes['alpha'], linha_passada_depois['alpha'], places=9)
        self.assertAlmostEqual(linha_passada_antes['beta'], linha_passada_depois['beta'], places=9)


class ProtecoesNumericasTestCase(unittest.TestCase):
    """Item 7/8 — nenhuma linha NaN/Inf entra no OLS; proteções contra
    matriz degenerada e variância quase zero."""

    def test_a_variancia_quase_zero_produz_status_degenerado(self):
        linhas = _serie_valida(130, forecast_fn=lambda i: 100.0, obs_fn=lambda i: 80.0 + 0.1 * i)
        base = pd.DataFrame(linhas)
        tabela = mos.construir_tabela_mos_linear(base)
        ultima = tabela.sort_values('init_date').iloc[-1]
        # forecast_raw constante -> anom_modelo_raw constante no treino -> degenerado
        self.assertEqual(ultima['status_mos'], mos.STATUS_DEGENERADA)
        self.assertIsNone(ultima['alpha'])
        self.assertIsNone(ultima['beta'])
        self.assertIsNone(ultima['forecast_mos'])

    def test_b_ajuste_ols_nunca_recebe_nan_inf(self):
        x = [1.0, 2.0, 3.0, 4.0, 5.0] * 30
        y = [2.0, 4.0, 6.0, 8.0, 10.0] * 30
        alpha, beta, r2, cond, status = mos._ajustar_ols_simples(x, y)
        self.assertEqual(status, mos.STATUS_OK)
        self.assertTrue(np.isfinite(alpha))
        self.assertTrue(np.isfinite(beta))

    def test_c_variancia_minima_e_fixa_nao_escolhida_por_skill(self):
        self.assertEqual(mos.VARIANCIA_MINIMA_ANOM_MODELO, 1e-6)


class OlsSimplesTestCase(unittest.TestCase):
    """Confirma a fórmula explícita do OLS em caso conhecido."""

    def test_a_relacao_linear_perfeita_recupera_alpha_beta_exatos(self):
        rng = np.random.default_rng(0)
        x = rng.uniform(-50, 50, size=150)
        y = 3.0 + 2.0 * x  # relação exata, sem ruído
        alpha, beta, r2, cond, status = mos._ajustar_ols_simples(x, y)
        self.assertEqual(status, mos.STATUS_OK)
        self.assertAlmostEqual(alpha, 3.0, places=6)
        self.assertAlmostEqual(beta, 2.0, places=6)
        self.assertAlmostEqual(r2, 1.0, places=6)

    def test_b_r2_nunca_usado_como_skill_isoladamente(self):
        """Smoke test de documentação: confirma que a chave de skill
        nunca se chama 'r2' nem deriva skill do r2_treino — apenas
        reportado como estatística separada."""
        linhas = _serie_valida(130)
        base = pd.DataFrame(linhas)
        tabela = mos.construir_tabela_mos_linear(base)
        self.assertIn('r2_treino', tabela.columns)
        for coluna_proibida in ('skill_r2', 'r2_skill'):
            self.assertNotIn(coluna_proibida, tabela.columns)


class DemonstracaoLeakyBloqueadoTestCase(unittest.TestCase):
    """Item 8, último bullet — teste sintético DELIBERADAMENTE leaky:
    demonstra que, se a implementação permitisse a própria linha
    avaliada (ou dados futuros) entrar no treino, o ajuste seria
    artificialmente superior — e que a implementação real BLOQUEIA
    isso completamente via warm-up/corte causal."""

    def test_implementacao_leaky_hipotetica_daria_ajuste_perfeito_implementacao_correta_bloqueia(self):
        linha = _linha('1991-06', 1, 6, forecast=237.5, obs=42.0, clim_media=50.0, clim_modelo=100.0)
        base = pd.DataFrame([linha])
        tabela = mos.construir_tabela_mos_linear(base)
        resultado = tabela.iloc[0]

        # Hipótese LEAKY: se a própria linha pudesse entrar no seu
        # próprio treino (n=1), um ajuste com beta arbitrário conectando
        # 2 pontos idênticos reproduziria a observação perfeitamente —
        # pura memorização, nunca generalização real.
        anom_modelo_hipotetico = 237.5 - 100.0
        anom_obs_hipotetico = 42.0 - 50.0
        self.assertNotEqual(anom_modelo_hipotetico, 0.0,
                             msg="a hipótese leaky precisa de um x não nulo para a demonstração "
                                 "fazer sentido")

        # Implementação REAL: bloqueada por warm-up (n_treino_mos=0 < 120)
        # — nenhum ganho artificial, nenhum forecast_mos é produzido.
        self.assertEqual(resultado['status_mos'], mos.STATUS_WARMUP)
        self.assertEqual(resultado['n_treino_mos'], 0)
        self.assertIsNone(resultado['alpha'])
        self.assertIsNone(resultado['beta'])
        self.assertIsNone(resultado['forecast_mos'])

    def test_outlier_isolado_na_avaliada_nao_contamina_o_ajuste_mesmo_com_warmup_satisfeito(self):
        """Variante com warm-up satisfeito e treino NÃO degenerado: um
        valor absurdo presente SÓ na observação avaliada não pode
        mudar alpha/beta (que vêm só do histórico de pares válidos),
        diferente de uma implementação leaky que incluiria esse
        outlier no próprio ajuste."""
        linhas_sem_outlier = _serie_valida(121, forecast_fn=lambda i: 100.0 + i,
                                            obs_fn=lambda i: 80.0 + 0.5 * i)
        base_sem_outlier = pd.DataFrame(linhas_sem_outlier)
        tabela_sem_outlier = mos.construir_tabela_mos_linear(base_sem_outlier)
        ultima_sem_outlier = tabela_sem_outlier.sort_values('init_date').iloc[-1]
        self.assertEqual(ultima_sem_outlier['status_mos'], mos.STATUS_OK)

        linhas_com_outlier = list(linhas_sem_outlier)
        linhas_com_outlier.append(_linha('2000-01', 1, 1, forecast=100.0, obs=999999.0,
                                          clim_media=70.0, clim_modelo=90.0))
        base_com_outlier = pd.DataFrame(linhas_com_outlier)
        tabela_com_outlier = mos.construir_tabela_mos_linear(base_com_outlier)
        linha_treino_sem_outlier = tabela_com_outlier[
            tabela_com_outlier['init_date'] == ultima_sem_outlier['init_date']].iloc[0]

        # o outlier gigante está só na linha AVALIADA (2000-01, a mais
        # recente) — o alpha/beta da linha anterior (treinado ANTES do
        # outlier existir) tem que permanecer idêntico.
        self.assertAlmostEqual(ultima_sem_outlier['alpha'], linha_treino_sem_outlier['alpha'],
                                places=9)
        self.assertAlmostEqual(ultima_sem_outlier['beta'], linha_treino_sem_outlier['beta'],
                                places=9)


class Benchmark3IdentidadeTestCase(unittest.TestCase):
    """Item 10 do pedido — validação numérica da identidade algébrica
    do benchmark_anomalia_reconstruida, reaproveitando `a.validar_
    identidade_benchmark3` (mesmas colunas, nunca uma segunda fórmula)."""

    def test_a_identidade_vale_em_dados_sinteticos(self):
        linhas = _serie_valida(130, clim_media=75.0, clim_modelo=90.0)
        base = pd.DataFrame(linhas)
        tabela = mos.construir_tabela_mos_linear(base)
        resultado = a.validar_identidade_benchmark3(tabela)
        self.assertTrue(resultado['identidade_ok'], resultado)
        self.assertGreater(resultado['n_verificado'], 0)

    def test_b_benchmark3_menos_observacao_e_a_diferenca_das_anomalias(self):
        linhas = _serie_valida(5, clim_media=75.0, clim_modelo=90.0)
        base = pd.DataFrame(linhas)
        tabela = mos.construir_tabela_mos_linear(base)
        for _, row in tabela.iterrows():
            lado_a = row['benchmark_anomalia_reconstruida'] - row['observacao']
            lado_b = row['anom_modelo_raw'] - row['anom_observada']
            self.assertAlmostEqual(lado_a, lado_b, places=9)


class CorrAnomaliaMosTestCase(unittest.TestCase):
    """Correção obrigatória desta revisão — `corr_anomalia_mos` tem
    que vir de `anom_mos = forecast_mos - climatologia_observada`,
    NUNCA da anomalia bruta do CFSv2 (`anom_modelo_raw`). Construído
    deliberadamente para que as duas correlações sejam NUMERICAMENTE
    DIFERENTES — `beta` varia por linha (mesmo padrão real: cada linha
    tem seu próprio ajuste causal expanding), então `anom_mos` NÃO é
    uma transformação afim única de `anom_modelo_raw` ao longo da
    amostra, e as duas correlações não podem coincidir por construção."""

    def test_a_corr_anomalia_mos_difere_de_corr_anomalia_raw_quando_beta_varia_por_linha(self):
        anom_modelo_raw = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        anom_observada = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])  # corr(raw, obs) = 1,0 exato
        beta_por_linha = np.array([1.0, 1.0, 1.0, -1.0, -1.0, -1.0])  # varia por linha
        anom_mos = beta_por_linha * anom_modelo_raw
        climatologia_observada = np.full(6, 50.0)
        observacao = climatologia_observada + anom_observada
        forecast_mos = climatologia_observada + anom_mos
        forecast_raw = climatologia_observada + anom_modelo_raw
        benchmark_anomalia_reconstruida = climatologia_observada + anom_modelo_raw
        forecast_calibrado_aditivo = observacao.copy()

        comparacao = pd.DataFrame({
            'anom_modelo_raw': anom_modelo_raw, 'anom_observada': anom_observada,
            'anom_mos': anom_mos, 'climatologia_observada': climatologia_observada,
            'observacao': observacao, 'forecast_mos': forecast_mos,
            'forecast_raw': forecast_raw,
            'benchmark_anomalia_reconstruida': benchmark_anomalia_reconstruida,
            'forecast_calibrado_aditivo': forecast_calibrado_aditivo,
            'alpha': np.full(6, 0.0), 'beta': beta_por_linha, 'r2_treino': np.full(6, 0.5),
        })

        resultado = mos._metricas_de_subconjunto_mos(comparacao)
        corr_raw_esperado = v._corr(anom_modelo_raw, anom_observada)
        corr_mos_esperado = v._corr(anom_mos, anom_observada)

        self.assertAlmostEqual(resultado['corr_anomalia_raw'], corr_raw_esperado, places=9)
        self.assertAlmostEqual(resultado['corr_anomalia_mos'], corr_mos_esperado, places=9)
        # Asserção central: as duas correlações NUNCA podem coincidir
        # neste teste — se coincidirem, a função está lendo a mesma
        # coluna para as duas métricas (o bug original).
        self.assertNotAlmostEqual(resultado['corr_anomalia_raw'], resultado['corr_anomalia_mos'],
                                   places=2)
        self.assertAlmostEqual(resultado['corr_anomalia_raw'], 1.0, places=9)
        self.assertLess(resultado['corr_anomalia_mos'], 0.9)

    def test_b_anom_mos_presente_na_tabela_real_e_consistente_com_forecast_mos(self):
        if not a.CAMINHO_TABELA_EXPANDING.exists() or not v.CAMINHO_METRICAS_JSON.parent.exists():
            self.skipTest("dados reais não disponíveis nesta árvore de trabalho")
        resultado, tabela, _ = mos.executar_mos_linear(n_resamples_bootstrap=1)
        self.assertFalse(resultado.get('STOP_ON_FAILURE', True))
        self.assertIn('anom_mos', tabela.columns)
        ok = tabela[tabela['status_mos'] == mos.STATUS_OK]
        diffs = (ok['anom_mos'] - (ok['forecast_mos'] - ok['climatologia_observada'])).abs()
        self.assertLess(diffs.max(), 1e-9)


class ResultadosPrincipaisPermanecemIdenticosTestCase(unittest.TestCase):
    """Item 7 da revisão — teste de REGRESSÃO: os valores principais já
    aprovados (commit 319ad4c) precisam permanecer numericamente
    idênticos após a correção da correlação de anomalia e do
    diagnóstico Sxx (ambas são métricas novas/corrigidas, nunca tocam
    em RMSE/skills/ICs). Valores congelados a partir da execução já
    aprovada — nunca recalculados "de olho" no resultado atual."""

    _VALORES_CONGELADOS = {
        1: {'n': 108, 'bias': 0.29861978219443414, 'mae': 33.640044431916536,
            'rmse': 48.37809376788118, 'skill_vs_raw': 0.27358858812496545,
            'RMSESS_climatologia': 0.15492906707741694,
            'skill_vs_anomalia_reconstruida': 0.010367619059827526,
            'skill_mos_vs_aditivo': -0.023312715191458278},
        2: {'n': 108, 'bias': 0.1691699793659726, 'mae': 36.684840211292666,
            'rmse': 55.347836733406865, 'skill_vs_raw': 0.2274167130978053,
            'RMSESS_climatologia': 0.02158279287186038,
            'skill_vs_anomalia_reconstruida': -0.00137816479369679,
            'skill_mos_vs_aditivo': -0.03838756241123131},
        3: {'n': 108, 'bias': -0.9326125840071453, 'mae': 36.753250978636984,
            'rmse': 55.5940185588372, 'skill_vs_raw': 0.22947213784611775,
            'RMSESS_climatologia': 0.028483118328209045,
            'skill_vs_anomalia_reconstruida': -0.019069449645805703,
            'skill_mos_vs_aditivo': -0.04899980136087323},
        4: {'n': 108, 'bias': -1.0177726049878595, 'mae': 35.84617580232791,
            'rmse': 54.84860323680825, 'skill_vs_raw': 0.2710542498285702,
            'RMSESS_climatologia': 0.028774749101210695,
            'skill_vs_anomalia_reconstruida': 0.0009156702570436437,
            'skill_mos_vs_aditivo': -0.01949137065187001},
        5: {'n': 108, 'bias': -1.4317112949109503, 'mae': 35.33119681976383,
            'rmse': 54.87581660830699, 'skill_vs_raw': 0.2928582395903141,
            'RMSESS_climatologia': 0.01973782752234965,
            'skill_vs_anomalia_reconstruida': -0.008134980553572424,
            'skill_mos_vs_aditivo': -0.03510916648631124},
        6: {'n': 108, 'bias': -1.8218616434409294, 'mae': 36.01212831967383,
            'rmse': 56.03660331757259, 'skill_vs_raw': 0.31116131960981963,
            'RMSESS_climatologia': -0.0017516827606507412,
            'skill_vs_anomalia_reconstruida': 0.02743702488892097,
            'skill_mos_vs_aditivo': 0.0158222831390592},
    }

    def test_metricas_principais_permanecem_identicas_ao_commit_319ad4c(self):
        if not a.CAMINHO_TABELA_EXPANDING.exists() or not v.CAMINHO_METRICAS_JSON.parent.exists():
            self.skipTest("dados reais não disponíveis nesta árvore de trabalho")
        resultado, tabela, _ = mos.executar_mos_linear(n_resamples_bootstrap=50)
        self.assertFalse(resultado.get('STOP_ON_FAILURE', True), resultado.get('motivo'))
        det = resultado['expanding_operational_simulation']['deterministico_por_horizonte']
        for lead, esperado in self._VALORES_CONGELADOS.items():
            atual = det[lead]
            for campo, valor_esperado in esperado.items():
                self.assertAlmostEqual(atual[campo], valor_esperado, places=9,
                                        msg=f"H{lead}.{campo} mudou: {atual[campo]} != "
                                        f"{valor_esperado} (valor congelado do commit 319ad4c)")


class ComDadosReaisTestCase(unittest.TestCase):
    """Usa os arquivos JÁ APROVADOS do repositório (sem rede) —
    confirma N, warm-up, ausência de leakage e a comparação pareada
    com o Método 3.1 na base real."""

    def setUp(self):
        if not a.CAMINHO_TABELA_EXPANDING.exists():
            self.skipTest("aditiva_expanding.csv (Método 3.1, aprovado) não encontrado nesta "
                           "árvore de trabalho")
        if not v.CAMINHO_METRICAS_JSON.parent.exists():
            self.skipTest("dados reais da 2C.3C não disponíveis nesta árvore de trabalho")
        self.resultado, self.tabela, self.tabela_loyo = mos.executar_mos_linear(
            n_resamples_bootstrap=30)

    def test_a_pipeline_completo_sem_stop_on_failure(self):
        self.assertFalse(self.resultado.get('STOP_ON_FAILURE', True), self.resultado.get('motivo'))

    def test_b_contagem_total_e_1440(self):
        self.assertEqual(len(self.tabela), v.N_INICIALIZACOES_ESPERADO * len(v.LEADS_ESPERADOS))

    def test_c_72_linhas_com_anomalia_indisponivel(self):
        """12 primeiras inicializações (1991, um ano) × 6 leads = 72 —
        a primeira ocorrência de cada mês-calendário não tem
        climatologia própria do modelo ainda."""
        n = int((self.tabela['status_mos'] == mos.STATUS_ANOMALIA_INDISPONIVEL).sum())
        self.assertEqual(n, 72)

    def test_d_primeira_elegibilidade_nunca_e_2001_hardcoded(self):
        """A correção do protocolo previu que a primeira elegibilidade
        real seria mais tarde que 2001 (por causa das 12 linhas
        descartadas por anomalia indisponível) — confirma isso na base
        real, nunca aceitando 2001 como premissa."""
        primeira = self.resultado['primeira_inicializacao_elegivel_por_lead']
        for lead in v.LEADS_ESPERADOS:
            data = primeira[lead]['primeira_init_date_elegivel']
            self.assertIsNotNone(data)
            self.assertEqual(primeira[lead]['n_treino_mos_nessa_data'], 120)
            self.assertGreater(primeira[lead]['n_linhas_descartadas_por_anomalia_indisponivel_antes_dessa_data'], 0)

    def test_e_nenhum_leakage_na_base_real(self):
        self.assertTrue(self.resultado['leakage_check']['ok'])

    def test_f_nenhuma_contaminacao_entre_leads_na_base_real(self):
        self.assertTrue(self.resultado['verificacao_outro_lead_nunca_contaminou_treino']['ok'])

    def test_g_identidade_benchmark3_vale_na_base_real(self):
        self.assertTrue(self.resultado['identidade_benchmark3']['identidade_ok'])

    def test_h_heterogeneidade_participacoes_sxx_somam_um_por_lead(self):
        het = self.resultado['expanding_operational_simulation']['diagnostico_heterogeneidade_variancia']
        self.assertTrue(het['verificacao_soma_participacoes_sxx_ok'],
                         het['verificacao_soma_participacoes_sxx_por_lead'])

    def test_i_skill_mos_vs_aditivo_presente_em_todos_os_horizontes(self):
        det = self.resultado['expanding_operational_simulation']['deterministico_por_horizonte']
        boot = self.resultado['expanding_operational_simulation'][
            'intervalos_confianca_skills_por_horizonte']
        for lead in v.LEADS_ESPERADOS:
            self.assertIn('skill_mos_vs_aditivo', det[lead])
            self.assertIn('skill_mos_vs_aditivo', boot[lead])

    def test_j_metodos_3_1_e_3_2_permanecem_byte_identicos(self):
        """Item 21/23 do pedido — artefatos dos Métodos 3.1/3.2 nunca
        alterados por esta atividade."""
        import cfsv2_calibracao_multiplicativa as m
        for caminho in (a.CAMINHO_TABELA_EXPANDING, m.CAMINHO_TABELA_EXPANDING):
            resultado_git = subprocess.run(
                ['git', 'diff', '--quiet', 'HEAD', '--', str(caminho.relative_to(a.ROOT))],
                cwd=a.ROOT, capture_output=True)
            self.assertEqual(resultado_git.returncode, 0, f"{caminho} divergiu do HEAD commitado")


class BootstrapMesmosBlocosTestCase(unittest.TestCase):
    """Item 13/21 do pedido — garante ESTRUTURALMENTE que o bootstrap
    usa os MESMOS blocos de ano para MOS, os três benchmarks E o
    aditivo matched em cada reamostra."""

    def test_mesmas_observacoes_alimentam_todas_as_cinco_series_na_mesma_reamostra(self):
        if not a.CAMINHO_TABELA_EXPANDING.exists() or not v.CAMINHO_METRICAS_JSON.parent.exists():
            self.skipTest("dados reais não disponíveis nesta árvore de trabalho")
        resultado, tabela, _ = mos.executar_mos_linear(n_resamples_bootstrap=1)
        self.assertFalse(resultado.get('STOP_ON_FAILURE', True))
        tabela_aditiva = pd.read_csv(a.CAMINHO_TABELA_EXPANDING)
        comparacao = mos.construir_tabela_comparacao(tabela, tabela_aditiva)

        observados_capturados = []
        orig_rmse = v._rmse

        def fake_rmse(previsto, observado):
            observados_capturados.append(tuple(np.asarray(observado, dtype=float)))
            return orig_rmse(previsto, observado)

        n_resamples = 5
        import unittest.mock as mock
        with mock.patch.object(v, '_rmse', side_effect=fake_rmse), \
             mock.patch.object(v, 'LEADS_ESPERADOS', (1,)):
            mos.bootstrap_skills_mos_vs_aditivo_por_horizonte(comparacao, n_resamples=n_resamples,
                                                               seed=1)

        self.assertEqual(len(observados_capturados), 5 * (n_resamples + 1))
        for i in range(n_resamples):
            grupo = observados_capturados[5 * i:5 * i + 5]
            self.assertEqual(len(set(grupo)), 1,
                              f"reamostra {i}: MOS, benchmarks e aditivo usaram observações "
                              "DIFERENTES — violaria a garantia de mesmos blocos")


class RelatorioMosLinearTestCase(unittest.TestCase):
    """Smoke test do gerador de relatório — nunca recalcula, só
    formata; nunca declara o método validado ou pronto para produção."""

    _FRASES_PROIBIDAS = ('o modelo está validado', 'está pronto para produção',
                          'é um método aprovado', 'nowcast')

    def _assert_nunca_declara_conclusao_isolada(self, texto):
        baixo = texto.lower()
        for frase in self._FRASES_PROIBIDAS:
            self.assertNotIn(frase, baixo, f"texto afirma/usa termo proibido: {frase!r}")

    def test_a_stop_on_failure_gera_relatorio_minimo(self):
        import cfsv2_relatorio_mos_linear_2c3d as rel
        resultados = {'STOP_ON_FAILURE': True, 'motivo': 'teste'}
        relatorio = rel.gerar_relatorio_markdown(resultados)
        self.assertIn('STOP-ON-FAILURE', relatorio)
        self._assert_nunca_declara_conclusao_isolada(relatorio)

    def test_b_relatorio_real_cobre_secoes_obrigatorias(self):
        if not mos.CAMINHO_METRICAS_JSON.exists():
            self.skipTest("métricas do MOS linear ainda não geradas nesta árvore de trabalho")
        import json
        import cfsv2_relatorio_mos_linear_2c3d as rel
        resultados = json.loads(mos.CAMINHO_METRICAS_JSON.read_text())
        relatorio = rel.gerar_relatorio_markdown(resultados)
        for secao in ('Metodologia', 'Pares válidos', 'warm-up', 'anti-leakage',
                      'elegibilidade', 'alpha', 'beta', 'estabilidade',
                      'Heterogeneidade', 'H1', 'benchmark', 'aditivo', 'Intervalos de confiança',
                      'mês', 'sazon', 'LOYO', 'Limitações', 'Conclusão'):
            self.assertIn(secao, relatorio)
        self._assert_nunca_declara_conclusao_isolada(relatorio)


if __name__ == '__main__':
    unittest.main()
