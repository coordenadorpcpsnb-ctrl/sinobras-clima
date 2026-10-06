#!/usr/bin/env python3
"""
tests/test_cfsv2_calibracao_aditiva.py — Fase 2C.3D, Método 3.1
(correção aditiva causal por lead × mês-alvo).

Foco principal (item 4 do pedido): testes de CONTROLE DE LEAKAGE — cada
um tem que FALHAR se a implementação deixasse a própria inicialização,
uma inicialização futura, outro lead ou outro mês-alvo entrar no cálculo
do bias. Inclui também o teste sintético deliberadamente leaky exigido
(demonstra que a implementação correta BLOQUEIA o ganho artificial que
uma versão leaky produziria).

Todos os testes usam dados SINTÉTICOS — nenhuma rede, nenhum dado real
do CFSv2/CHIRPS é necessário para rodar esta suíte (embora as classes
*ComDadosReais* leiam os arquivos já aprovados do repositório, sem rede).

Roda com:
    python -m unittest tests.test_cfsv2_calibracao_aditiva -v
"""

import sys
import unittest
import unittest.mock as mock
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import cfsv2_calibracao_aditiva as a  # noqa: E402
import cfsv2_validacao_cientifica as v  # noqa: E402


def _linha(init_date, lead, target_mes=None, forecast=100.0, obs=80.0,
           clim_media=None, clim_modelo=None):
    """Monta 1 linha de base_enriquecida (já agregada por ensemble mean
    — 1 'membro' é suficiente para testar a lógica de calibração, que
    opera sobre a média do ensemble, nunca sobre membros individuais)."""
    target_p = v._periodo(init_date) + (lead - 1)
    return {
        'init_date': init_date, 'target_month': str(target_p), 'target_ano': target_p.year,
        'target_mes': target_mes if target_mes is not None else target_p.month,
        'lead': lead, 'member': 1, 'forecast_prec_mm': forecast, 'obs_prec_mm': obs,
        'clim_media': clim_media, 'clim_modelo_media': clim_modelo,
    }


# Frases ASSERTIVAS (nunca as afirmações em si) — o relatório PODE
# mencionar essas frases como exemplo do que NÃO dizer (ex.: "nunca
# chamando o modelo de... pronto para produção"), mas nunca pode
# AFIRMÁ-las como conclusão. Por isso o padrão exige a forma afirmativa
# completa (com "está"/"é"), não a substring nua.
_FRASES_PROIBIDAS = ('o modelo está validado', 'está pronto para produção',
                      'está pronto para o dashboard', 'é um método aprovado',
                      'tem boa habilidade')


def _assert_nunca_declara_conclusao_isolada(testcase, texto):
    baixo = texto.lower()
    for frase in _FRASES_PROIBIDAS:
        testcase.assertNotIn(frase, baixo, f"texto afirma diretamente: {frase!r}")


class CalcularBiasAditivoSemLeakageTestCase(unittest.TestCase):
    """Item 4 do pedido — garantias anti-leakage do bias aditivo."""

    def test_a_nunca_usa_inicializacao_igual_ou_posterior(self):
        linhas = [_linha(f'{1990+i}-06', 1, 6, forecast=100.0 + i, obs=80.0) for i in range(12)]
        base = pd.DataFrame(linhas)
        tabela = a.construir_tabela_calibracao_aditiva(base)
        ultima = tabela[tabela['init_date'] == '2001-06'].iloc[0]
        if ultima['status_calibracao'] == a.STATUS_OK:
            self.assertLess(v._periodo(ultima['periodo_treino_fim']), v._periodo(ultima['init_date']))

    def test_b_warmup_antes_de_dez_observacoes(self):
        linhas = [_linha(f'{1990+i}-06', 1, 6, forecast=100.0, obs=80.0) for i in range(15)]
        base = pd.DataFrame(linhas)
        tabela = a.construir_tabela_calibracao_aditiva(base).sort_values('init_date')
        primeiras_dez = tabela.iloc[:10]
        self.assertTrue((primeiras_dez['status_calibracao'] == a.STATUS_WARMUP).all())
        self.assertTrue((primeiras_dez['n_treino'] < a.N_TREINO_MINIMO).all())
        self.assertEqual(tabela.iloc[10]['status_calibracao'], a.STATUS_OK)
        self.assertEqual(tabela.iloc[10]['n_treino'], 10)

    def test_c_propria_inicializacao_nunca_entra_no_proprio_bias(self):
        linhas = [_linha(f'{1990+i}-06', 1, 6, forecast=100.0, obs=90.0) for i in range(10)]
        linhas.append(_linha('2000-06', 1, 6, forecast=100.0, obs=-99999.0))
        base = pd.DataFrame(linhas)
        tabela = a.construir_tabela_calibracao_aditiva(base)
        linha_avaliada = tabela[tabela['init_date'] == '2000-06'].iloc[0]
        self.assertEqual(linha_avaliada['status_calibracao'], a.STATUS_OK)
        self.assertAlmostEqual(linha_avaliada['bias_aditivo'], 10.0, places=6)

    def test_d_combinacao_de_outro_lead_nunca_entra_no_treino(self):
        linhas = [_linha(f'{1990+i}-06', 1, 6, forecast=100.0, obs=80.0) for i in range(10)]
        linhas += [_linha(f'{1990+i}-07', 2, 6, forecast=500.0, obs=0.0) for i in range(10)]
        linhas.append(_linha('2000-06', 1, 6, forecast=100.0, obs=80.0))
        base = pd.DataFrame(linhas)
        tabela = a.construir_tabela_calibracao_aditiva(base)
        linha = tabela[(tabela['init_date'] == '2000-06') & (tabela['lead'] == 1)].iloc[0]
        self.assertAlmostEqual(linha['bias_aditivo'], 20.0, places=6)

    def test_e_combinacao_de_outro_mes_alvo_nunca_entra_no_treino(self):
        linhas = [_linha(f'{1990+i}-06', 1, 6, forecast=100.0, obs=80.0) for i in range(10)]
        linhas += [_linha(f'{1990+i}-01', 1, 1, forecast=900.0, obs=0.0) for i in range(10)]
        linhas.append(_linha('2000-06', 1, 6, forecast=100.0, obs=80.0))
        base = pd.DataFrame(linhas)
        tabela = a.construir_tabela_calibracao_aditiva(base)
        linha = tabela[(tabela['init_date'] == '2000-06') & (tabela['target_mes'] == 6)].iloc[0]
        self.assertAlmostEqual(linha['bias_aditivo'], 20.0, places=6)

    def test_f_alterar_observacao_futura_nao_modifica_previsao_calibrada_passada(self):
        linhas = [_linha(f'{1990+i}-06', 1, 6, forecast=100.0, obs=80.0) for i in range(12)]
        base = pd.DataFrame(linhas)
        tabela_antes = a.construir_tabela_calibracao_aditiva(base)
        linha_passada_antes = tabela_antes[tabela_antes['init_date'] == '2000-06'].iloc[0].copy()

        base_mutada = base.copy()
        idx_futura = base_mutada[base_mutada['init_date'] == '2001-06'].index
        base_mutada.loc[idx_futura, 'obs_prec_mm'] = -123456.0
        tabela_depois = a.construir_tabela_calibracao_aditiva(base_mutada)
        linha_passada_depois = tabela_depois[tabela_depois['init_date'] == '2000-06'].iloc[0]

        self.assertEqual(linha_passada_antes['status_calibracao'], linha_passada_depois['status_calibracao'])
        self.assertEqual(linha_passada_antes['status_calibracao'], a.STATUS_OK)
        self.assertAlmostEqual(linha_passada_antes['bias_aditivo'], linha_passada_depois['bias_aditivo'],
                                places=9)
        self.assertAlmostEqual(linha_passada_antes['forecast_calibrado'],
                                linha_passada_depois['forecast_calibrado'], places=9)


class DemonstracaoLeakyBloqueadoTestCase(unittest.TestCase):
    """Item 4, último bullet — teste sintético DELIBERADAMENTE leaky:
    demonstra que, se a implementação permitisse a própria inicialização
    entrar no cálculo do seu bias (n_treino=0, único dado "disponível"
    seria ela mesma), o resultado seria um ajuste PERFEITO e artificial
    (forecast_calibrado == observação, pura memorização) — e que a
    implementação real BLOQUEIA isso completamente via warm-up."""

    def test_implementacao_leaky_hipotetica_daria_ajuste_perfeito_implementacao_correta_bloqueia(self):
        linha = _linha('1991-06', 1, 6, forecast=237.5, obs=42.0)
        base = pd.DataFrame([linha])
        tabela = a.construir_tabela_calibracao_aditiva(base)
        resultado = tabela.iloc[0]

        # Hipótese LEAKY: bias = erro da própria linha (forecast-obs),
        # porque seria o único dado "disponível" se a própria inicialização
        # pudesse entrar no seu cálculo.
        bias_leaky_hipotetico = 237.5 - 42.0
        forecast_calibrado_leaky_hipotetico = 237.5 - bias_leaky_hipotetico
        self.assertAlmostEqual(forecast_calibrado_leaky_hipotetico, 42.0, places=9,
                                msg="a hipótese leaky precisa produzir um ajuste suspeito/perfeito "
                                    "para a demonstração fazer sentido")

        # Implementação REAL: bloqueada por warm-up (n_treino=0 < 10) —
        # nenhum ganho artificial, nenhuma previsão calibrada é produzida.
        self.assertEqual(resultado['status_calibracao'], a.STATUS_WARMUP)
        self.assertEqual(resultado['n_treino'], 0)
        self.assertIsNone(resultado['bias_aditivo'])
        self.assertIsNone(resultado['forecast_calibrado'])

    def test_outlier_isolado_na_avaliada_nao_contamina_bias_mesmo_com_dez_anos_de_historico(self):
        """Variante com warm-up satisfeito: um erro gigante presente SÓ
        na inicialização avaliada não pode mudar o bias calculado (que
        vem só do histórico), diferente de uma implementação leaky que
        incluiria esse outlier na própria média."""
        linhas = [_linha(f'{1990+i}-06', 1, 6, forecast=100.0, obs=90.0) for i in range(10)]
        linhas.append(_linha('2000-06', 1, 6, forecast=1100.0, obs=90.0))  # erro real = 1010
        base = pd.DataFrame(linhas)
        tabela = a.construir_tabela_calibracao_aditiva(base)
        linha = tabela[tabela['init_date'] == '2000-06'].iloc[0]

        self.assertAlmostEqual(linha['bias_aditivo'], 10.0, places=6)
        self.assertAlmostEqual(linha['forecast_calibrado'], 1090.0, places=6)
        # se o outlier tivesse contaminado o bias (leaky), o resíduo
        # calibrado ficaria MUITO menor que 1000 — a implementação real
        # preserva o resíduo real completo.
        residuo_real = abs(linha['forecast_calibrado'] - linha['observacao'])
        self.assertAlmostEqual(residuo_real, 1000.0, places=6)


class Benchmark3IdentidadeTestCase(unittest.TestCase):
    """Item 6 do pedido — validação numérica programática da identidade
    algébrica do benchmark_anomalia_reconstruida."""

    def test_a_identidade_algebrica_vale_em_dados_sinteticos(self):
        linhas = [_linha(f'{1990+i}-06', 1, 6, forecast=100.0 + i, obs=80.0 + 0.5 * i,
                          clim_media=75.0 + 0.1 * i, clim_modelo=90.0 - 0.2 * i) for i in range(15)]
        base = pd.DataFrame(linhas)
        tabela = a.construir_tabela_calibracao_aditiva(base)
        resultado = a.validar_identidade_benchmark3(tabela)
        self.assertTrue(resultado['identidade_ok'], resultado)
        self.assertLess(resultado['max_diff_absoluto'], 1e-9)
        self.assertGreater(resultado['n_verificado'], 0)

    def test_b_identidade_quebrada_e_detectada_nunca_passa_silenciosamente(self):
        linhas = [_linha(f'{1990+i}-06', 1, 6, forecast=100.0, obs=80.0,
                          clim_media=75.0, clim_modelo=90.0) for i in range(12)]
        base = pd.DataFrame(linhas)
        tabela = a.construir_tabela_calibracao_aditiva(base)
        tabela_errada = tabela.copy()
        tabela_errada['benchmark_anomalia_reconstruida'] = (
            tabela_errada['benchmark_anomalia_reconstruida'] + 999.0)
        resultado = a.validar_identidade_benchmark3(tabela_errada)
        self.assertFalse(resultado['identidade_ok'])
        self.assertGreater(resultado['max_diff_absoluto'], 900.0)


class ClimatologiaModeloCalibradoTestCase(unittest.TestCase):
    """Item 7 do pedido — a climatologia do modelo CALIBRADO usa só
    previsões calibradas históricas, nunca o bruto."""

    def test_usa_apenas_previsoes_calibradas_historicas_nunca_o_bruto(self):
        linhas = [_linha(f'{1990+i}-06', 1, 6, forecast=100.0, obs=80.0) for i in range(13)]
        base = pd.DataFrame(linhas)
        tabela = a.construir_tabela_calibracao_aditiva(base)
        tabela = a.adicionar_climatologia_modelo_calibrado(tabela)
        tabela = tabela.sort_values('init_date').reset_index(drop=True)

        # índices 0-9: warm-up -> nenhum histórico calibrado disponível
        self.assertEqual(tabela.iloc[9]['n_climatologia_modelo_calibrado'], 0)
        self.assertTrue(pd.isna(tabela.iloc[9]['climatologia_modelo_calibrado']))
        # índice 10: primeira linha OK -> climatologia calibrada ainda
        # não tem histórico calibrado (ela mesma é o primeiro)
        self.assertEqual(tabela.iloc[10]['n_climatologia_modelo_calibrado'], 0)
        # índice 11: já existe 1 histórico calibrado (o do índice 10)
        self.assertEqual(tabela.iloc[11]['n_climatologia_modelo_calibrado'], 1)
        self.assertAlmostEqual(tabela.iloc[11]['climatologia_modelo_calibrado'],
                                tabela.iloc[10]['forecast_calibrado'], places=9)

    def test_climatologia_calibrada_difere_da_climatologia_do_bruto_quando_ha_vies(self):
        """Se o bias aditivo remove um viés real, a climatologia do
        modelo calibrado tem que ser DIFERENTE (mais próxima de zero)
        da que seria obtida reutilizando a climatologia do bruto."""
        linhas = [_linha(f'{1990+i}-06', 1, 6, forecast=150.0, obs=80.0) for i in range(15)]
        base = pd.DataFrame(linhas)
        tabela = a.construir_tabela_calibracao_aditiva(base)
        tabela = a.adicionar_climatologia_modelo_calibrado(tabela)
        tabela = tabela.sort_values('init_date').reset_index(drop=True)
        ultima = tabela.iloc[-1]
        # climatologia do modelo calibrado deve estar perto de 80 (as
        # previsões calibradas corrigiram o viés de +70), nunca perto
        # de 150 (o que a climatologia do bruto diria).
        self.assertAlmostEqual(ultima['climatologia_modelo_calibrado'], 80.0, places=6)


class BootstrapMesmosBlocosAditivaTestCase(unittest.TestCase):
    """Item 9 do pedido — garante ESTRUTURALMENTE que o bootstrap usa os
    MESMOS blocos de ano para o método calibrado e os três benchmarks em
    cada reamostra."""

    def test_mesmas_linhas_alimentam_metodo_e_os_tres_benchmarks_na_mesma_reamostra(self):
        if not v.CAMINHO_METRICAS_JSON.parent.exists():
            self.skipTest("dados reais não disponíveis nesta árvore de trabalho")
        df_raw = v.carregar_cfsv2_raw()
        chirps = v.carregar_chirps_v3_historico()
        base = v.construir_base_pareada(df_raw, chirps)
        base_enr = v._enriquecer_com_climatologia(base, chirps)
        tabela = a.construir_tabela_calibracao_aditiva(base_enr)
        tabela = a.adicionar_climatologia_modelo_calibrado(tabela)

        observados_capturados = []
        orig_rmse = v._rmse

        def fake_rmse(previsto, observado):
            observados_capturados.append(tuple(np.asarray(observado, dtype=float)))
            return orig_rmse(previsto, observado)

        n_resamples = 5
        with mock.patch.object(v, '_rmse', side_effect=fake_rmse), \
             mock.patch.object(v, 'LEADS_ESPERADOS', (1,)):
            resultado = a.bootstrap_skills_aditiva_por_horizonte(tabela, n_resamples=n_resamples, seed=1)

        self.assertTrue(resultado[1]['amostra_suficiente'])
        # 4 chamadas por reamostra (cal, raw, clim, bench3) + 4 pontuais
        self.assertEqual(len(observados_capturados), 4 * (n_resamples + 1))
        for i in range(n_resamples):
            grupo = observados_capturados[4 * i:4 * i + 4]
            self.assertEqual(len(set(grupo)), 1,
                              f"reamostra {i}: método e benchmarks usaram observações DIFERENTES "
                              "— violaria a garantia de mesmos blocos")


class ComDadosReaisTestCase(unittest.TestCase):
    """Usa os dados REAIS já aprovados (sem rede) — confirma contagens,
    identidade do benchmark3 e ausência de leakage na base real."""

    def setUp(self):
        if not v.CAMINHO_METRICAS_JSON.parent.exists():
            self.skipTest("dados reais não disponíveis nesta árvore de trabalho")
        df_raw = v.carregar_cfsv2_raw()
        chirps = v.carregar_chirps_v3_historico()
        base = v.construir_base_pareada(df_raw, chirps)
        self.base_enr = v._enriquecer_com_climatologia(base, chirps)
        self.tabela = a.construir_tabela_calibracao_aditiva(self.base_enr)

    def test_a_numero_total_de_combinacoes_e_o_esperado(self):
        self.assertEqual(len(self.tabela), v.N_INICIALIZACOES_ESPERADO * len(v.LEADS_ESPERADOS))

    def test_b_primeira_inicializacao_elegivel_e_2001_para_todas_as_celulas(self):
        """Derivado programaticamente — nunca hardcoded na implementação
        (ver CLAUDE do pedido); este teste confirma empiricamente que,
        com inits mensais desde 1991 e N_TREINO_MINIMO=10, a primeira
        inicialização elegível cai em 2001 para TODAS as 72 células,
        exatamente como o protocolo previu."""
        primeira = a._primeira_inicializacao_elegivel_por_celula(self.tabela)
        for lead in v.LEADS_ESPERADOS:
            for mes in range(1, 13):
                data = primeira[lead][mes]
                self.assertEqual(data.split('-')[0], '2001',
                                  f"lead={lead} mes={mes}: primeira elegível={data}, esperado ano 2001")

    def test_c_identidade_benchmark3_vale_na_base_real(self):
        resultado = a.validar_identidade_benchmark3(self.tabela)
        self.assertTrue(resultado['identidade_ok'], resultado)
        self.assertGreater(resultado['n_verificado'], 0)

    def test_d_nenhum_leakage_detectado_na_base_real(self):
        resultado = a._verificar_nenhum_leakage_na_tabela(self.tabela)
        self.assertTrue(resultado['ok'], resultado['problemas'])

    def test_e_n_elegivel_por_horizonte_bate_com_120_apos_warmup(self):
        """240 inicializações - 120 em warm-up (10 anos × 12 meses) =
        120 elegíveis por horizonte, uniformemente (mesma contagem para
        todos os H1-H6, já que o warm-up é por lead×mês-alvo e cada mês
        tem exatamente 1 inicialização/ano)."""
        ok = self.tabela[self.tabela['status_calibracao'] == a.STATUS_OK]
        for lead in v.LEADS_ESPERADOS:
            n = len(ok[ok['lead'] == lead])
            self.assertEqual(n, 120, f"lead={lead}: N elegível={n}, esperado 120")

    def test_f_pipeline_completo_sem_stop_on_failure(self):
        resultado, tabela, tabela_loyo = a.executar_calibracao_aditiva(n_resamples_bootstrap=50)
        self.assertFalse(resultado.get('STOP_ON_FAILURE', True), resultado.get('motivo'))
        self.assertEqual(resultado['n_treino_minimo'], 10)
        self.assertTrue(resultado['identidade_benchmark3']['identidade_ok'])
        self.assertTrue(resultado['leakage_check']['ok'])


class LoyoMatchedTestCase(unittest.TestCase):
    """Segunda revisão, item 9 do pedido — LOYO matched evaluation
    period: mesmos casos do expanding, três benchmarks equivalentes em
    desenho LOYO, identidade algébrica e mesmos blocos no bootstrap."""

    def setUp(self):
        if not v.CAMINHO_METRICAS_JSON.parent.exists():
            self.skipTest("dados reais não disponíveis nesta árvore de trabalho")
        df_raw = v.carregar_cfsv2_raw()
        chirps = v.carregar_chirps_v3_historico()
        self.base = v.construir_base_pareada(df_raw, chirps)
        base_enr = v._enriquecer_com_climatologia(self.base, chirps)
        self.tabela_expanding = a.adicionar_climatologia_modelo_calibrado(
            a.construir_tabela_calibracao_aditiva(base_enr))
        self.tabela_loyo = a.construir_tabela_calibracao_aditiva_loyo(self.base, chirps)

    def test_a_climatologia_modelo_raw_loyo_exclui_o_proprio_ano(self):
        sub = self.tabela_loyo[(self.tabela_loyo['lead'] == 1) & (self.tabela_loyo['target_mes'] == 6)]
        linha = sub.iloc[0]
        media_incluindo_propria = sub['forecast_raw'].mean()
        # com ~20 anos na amostra, excluir 1 ano muda a média de forma
        # mensurável — não é coincidência numérica
        self.assertNotAlmostEqual(linha['climatologia_modelo_raw_loyo'],
                                   media_incluindo_propria, places=6)
        outros = sub[sub['target_ano'] != linha['target_ano']]
        self.assertAlmostEqual(linha['climatologia_modelo_raw_loyo'],
                                outros['forecast_raw'].mean(), places=9)

    def test_b_identidade_benchmark3_loyo_vale_na_base_real(self):
        resultado = a.validar_identidade_benchmark3_loyo(self.tabela_loyo)
        self.assertTrue(resultado['identidade_ok'], resultado)
        self.assertGreater(resultado['n_verificado'], 0)

    def test_c_identidade_benchmark3_loyo_quebrada_e_detectada(self):
        tabela_errada = self.tabela_loyo.copy()
        tabela_errada['benchmark_anomalia_reconstruida_loyo'] = (
            tabela_errada['benchmark_anomalia_reconstruida_loyo'] + 999.0)
        resultado = a.validar_identidade_benchmark3_loyo(tabela_errada)
        self.assertFalse(resultado['identidade_ok'])

    def test_d_loyo_matched_contem_exatamente_os_mesmos_casos_do_expanding(self):
        matched = a.construir_tabela_loyo_matched(self.tabela_expanding, self.tabela_loyo)
        chaves_expanding = set(map(tuple, self.tabela_expanding[
            (self.tabela_expanding['status_calibracao'] == a.STATUS_OK)
            & self.tabela_expanding['benchmark_anomalia_reconstruida'].notna()
        ][['init_date', 'lead']].values.tolist()))
        chaves_matched = set(map(tuple, matched[['init_date', 'lead']].values.tolist()))
        self.assertEqual(chaves_expanding, chaves_matched)

    def test_e_n_matched_igual_a_n_expanding_por_horizonte(self):
        matched = a.construir_tabela_loyo_matched(self.tabela_expanding, self.tabela_loyo)
        for lead in v.LEADS_ESPERADOS:
            n_exp = len(self.tabela_expanding[
                (self.tabela_expanding['lead'] == lead)
                & (self.tabela_expanding['status_calibracao'] == a.STATUS_OK)
                & self.tabela_expanding['benchmark_anomalia_reconstruida'].notna()])
            n_mat = len(matched[matched['lead'] == lead])
            self.assertEqual(n_exp, n_mat, f"lead={lead}")
            self.assertEqual(n_exp, 120, f"lead={lead}: esperado 120 após warm-up")

    def test_f_metodo_e_benchmark_usam_os_mesmos_casos_no_matched(self):
        matched = a.construir_tabela_loyo_matched(self.tabela_expanding, self.tabela_loyo)
        det_m = a.metricas_deterministicas_loyo_matched_por_horizonte(matched)
        for lead in v.LEADS_ESPERADOS:
            sub = matched[(matched['lead'] == lead)
                          & (matched['status_calibracao'] == a.STATUS_OK)].dropna(
                subset=['benchmark_anomalia_reconstruida_loyo'])
            self.assertEqual(det_m[lead]['n_elegivel'], len(sub))

    def test_g_bootstrap_loyo_matched_usa_os_mesmos_blocos(self):
        matched = a.construir_tabela_loyo_matched(self.tabela_expanding, self.tabela_loyo)
        observados_capturados = []
        orig_rmse = v._rmse

        def fake_rmse(previsto, observado):
            observados_capturados.append(tuple(np.asarray(observado, dtype=float)))
            return orig_rmse(previsto, observado)

        n_resamples = 5
        with mock.patch.object(v, '_rmse', side_effect=fake_rmse), \
             mock.patch.object(v, 'LEADS_ESPERADOS', (1,)):
            resultado = a.bootstrap_skills_loyo_matched_por_horizonte(
                matched, n_resamples=n_resamples, seed=1)

        self.assertTrue(resultado[1]['amostra_suficiente'])
        self.assertEqual(len(observados_capturados), 4 * (n_resamples + 1))
        for i in range(n_resamples):
            grupo = observados_capturados[4 * i:4 * i + 4]
            self.assertEqual(len(set(grupo)), 1,
                              f"reamostra {i}: método e benchmarks (LOYO matched) usaram "
                              "observações DIFERENTES")

    def test_h_pipeline_completo_inclui_loyo_matched_sem_stop_on_failure(self):
        resultado, tabela, tabela_loyo = a.executar_calibracao_aditiva(n_resamples_bootstrap=50)
        self.assertFalse(resultado.get('STOP_ON_FAILURE', True), resultado.get('motivo'))
        self.assertIn('loyo_matched_evaluation_period', resultado)
        self.assertIn('comparacao_expanding_vs_loyo_matched', resultado)
        self.assertTrue(
            resultado['loyo_matched_evaluation_period']['identidade_benchmark3_loyo']['identidade_ok'])


class ExpandingPermaneceInalteradoTestCase(unittest.TestCase):
    """Segunda revisão, item 6/9 do pedido — teste de REGRESSÃO: os
    valores expanding já aprovados (commit a001e85) precisam permanecer
    numericamente idênticos após as adições desta revisão (LOYO
    matched). Valores congelados a partir da execução já aprovada —
    nunca recalculados "de olho" no resultado atual."""

    _VALORES_CONGELADOS = {
        1: {'n_elegivel': 120, 'bias': 5.409589424122345, 'mae': 33.664908597080355,
            'rmse': 46.745833552517794, 'skill_vs_raw': 0.2903994247106899,
            'RMSESS_climatologia': 0.16150799319968867,
            'skill_vs_anomalia_reconstruida': 0.040294096718318184},
        2: {'n_elegivel': 120, 'bias': 2.318821466593777, 'mae': 35.65614796499275,
            'rmse': 52.351303555063794, 'skill_vs_raw': 0.2675528233409302,
            'RMSESS_climatologia': 0.05084014961710537,
            'skill_vs_anomalia_reconstruida': 0.03633969040165075},
        3: {'n_elegivel': 120, 'bias': -0.4057611256347123, 'mae': 34.64334266242499,
            'rmse': 51.62509176817765, 'skill_vs_raw': 0.27756463628629546,
            'RMSESS_climatologia': 0.06974635715389621,
            'skill_vs_anomalia_reconstruida': 0.02715970712687854},
        4: {'n_elegivel': 120, 'bias': -2.393741256770868, 'mae': 34.69086501944182,
            'rmse': 53.35016456110512, 'skill_vs_raw': 0.29819713816470517,
            'RMSESS_climatologia': 0.03838165793255155,
            'skill_vs_anomalia_reconstruida': 0.02180478348540482},
        5: {'n_elegivel': 120, 'bias': -1.7325685202702734, 'mae': 33.8830962777807,
            'rmse': 52.248903401540005, 'skill_vs_raw': 0.3399268702272126,
            'RMSESS_climatologia': 0.05844282846936999,
            'skill_vs_anomalia_reconstruida': 0.030182094449654362},
        6: {'n_elegivel': 120, 'bias': -4.547118107392417, 'mae': 33.764282018035416,
            'rmse': 54.73598682969854, 'skill_vs_raw': 0.32618878190483447,
            'RMSESS_climatologia': 0.007807285155130184,
            'skill_vs_anomalia_reconstruida': 0.01315280815723241},
    }

    def test_expanding_permanece_numericamente_identico_ao_commit_a001e85(self):
        if not v.CAMINHO_METRICAS_JSON.parent.exists():
            self.skipTest("dados reais não disponíveis nesta árvore de trabalho")
        resultado, tabela, tabela_loyo = a.executar_calibracao_aditiva(n_resamples_bootstrap=50)
        self.assertFalse(resultado.get('STOP_ON_FAILURE', True), resultado.get('motivo'))
        det = resultado['expanding_operational_simulation']['deterministico_por_horizonte']
        for lead, esperado in self._VALORES_CONGELADOS.items():
            atual = det[lead]
            for campo, valor_esperado in esperado.items():
                self.assertAlmostEqual(atual[campo], valor_esperado, places=9,
                                        msg=f"H{lead}.{campo} mudou: {atual[campo]} != "
                                        f"{valor_esperado} (valor congelado do commit a001e85)")


class RelatorioAditivaTestCase(unittest.TestCase):
    """Smoke test do gerador de relatório — nunca recalcula métrica, só
    formata o que já foi calculado; nunca declara o método validado."""

    def test_a_stop_on_failure_gera_relatorio_minimo(self):
        import cfsv2_relatorio_aditiva_2c3d as rel
        resultados = {'STOP_ON_FAILURE': True, 'motivo': 'teste'}
        relatorio = rel.gerar_relatorio_markdown(resultados)
        self.assertIn('STOP-ON-FAILURE', relatorio)
        _assert_nunca_declara_conclusao_isolada(self, relatorio)

    def test_b_relatorio_real_cobre_secoes_obrigatorias(self):
        if not a.CAMINHO_METRICAS_JSON.exists():
            self.skipTest("métricas da calibração aditiva ainda não geradas nesta árvore")
        import json
        import cfsv2_relatorio_aditiva_2c3d as rel
        resultados = json.loads(a.CAMINHO_METRICAS_JSON.read_text())
        relatorio = rel.gerar_relatorio_markdown(resultados)
        for secao in ('Metodologia', 'warm-up', 'anti-leakage', 'H1', 'benchmark',
                      'Intervalos de confiança', 'mês', 'sazonais', 'LOYO', 'Limitações',
                      'Conclusão', 'critério de aprovação', 'LOYO matched', 'LOYO full',
                      'delta'):
            self.assertIn(secao, relatorio)
        _assert_nunca_declara_conclusao_isolada(self, relatorio)

    def test_c_relatorio_declara_explicitamente_que_nenhum_horizonte_atende_ao_criterio(self):
        """Segunda revisão, item 1 do pedido — o relatório tem que dizer
        isso de forma explícita, nunca deixar implícito."""
        if not a.CAMINHO_METRICAS_JSON.exists():
            self.skipTest("métricas da calibração aditiva ainda não geradas nesta árvore")
        import json
        import cfsv2_relatorio_aditiva_2c3d as rel
        resultados = json.loads(a.CAMINHO_METRICAS_JSON.read_text())
        relatorio = rel.gerar_relatorio_markdown(resultados)
        self.assertIn('nenhum horizonte h1-h6 satisfaz simultaneamente os dois critérios',
                       relatorio.lower())
        self.assertNotIn('h1 está aprovado', relatorio.lower())
        self.assertNotIn('h1 foi aprovado', relatorio.lower())


if __name__ == '__main__':
    unittest.main()
