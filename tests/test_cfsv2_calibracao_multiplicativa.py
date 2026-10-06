#!/usr/bin/env python3
"""
tests/test_cfsv2_calibracao_multiplicativa.py — Fase 2C.3D, Método 3.2
(correção multiplicativa causal por lead × mês-alvo).

Item 16 do pedido — foco em: warm-up=10; ausência de leakage;
numerador/denominador sobre os MESMOS anos históricos; piso de 10mm
aplicado exatamente (sem fragmentar mês, sem cap de razão acima do
piso); outubro (razão alta) nunca truncado; nenhuma razão/forecast
negativa; N esperado 480/80; aditivo matched e multiplicativo com as
MESMAS chaves; bootstrap usando os mesmos blocos para multiplicativo e
aditivo; benchmarks na mesma amostra; arquivos do Método 3.1 intactos.

Dados SINTÉTICOS para a lógica central (nenhuma rede necessária); as
classes *ComDadosReais* leem os arquivos já aprovados do repositório
(sem rede, pulam se ausentes).

Roda com:
    python -m unittest tests.test_cfsv2_calibracao_multiplicativa -v
"""

import subprocess
import sys
import unittest
import unittest.mock as mock
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import cfsv2_calibracao_aditiva as a  # noqa: E402
import cfsv2_calibracao_multiplicativa as m  # noqa: E402
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


class WarmupETreinoCausalTestCase(unittest.TestCase):
    """Item 16 — 'warm-up = 10' e 'ausência de leakage'."""

    def test_a_warmup_antes_de_dez_observacoes(self):
        linhas = [_linha(f'{1990+i}-06', 1, 6, forecast=100.0, obs=80.0) for i in range(15)]
        base = pd.DataFrame(linhas)
        tabela, _ = m.construir_tabela_calibracao_multiplicativa(base)
        tabela = tabela.sort_values('init_date')
        primeiras_dez = tabela.iloc[:10]
        self.assertTrue((primeiras_dez['status_multiplicativo'] == m.STATUS_WARMUP).all())
        self.assertTrue((primeiras_dez['n_treino'] < m.N_TREINO_MINIMO).all())
        self.assertEqual(tabela.iloc[10]['n_treino'], 10)

    def test_b_treino_estritamente_anterior_a_avaliada(self):
        linhas = [_linha(f'{1990+i}-06', 1, 6, forecast=200.0, obs=100.0) for i in range(15)]
        base = pd.DataFrame(linhas)
        tabela, _ = m.construir_tabela_calibracao_multiplicativa(base)
        elegiveis = tabela[tabela['status_multiplicativo'] == m.STATUS_OK]
        for _, row in elegiveis.iterrows():
            self.assertLess(v._periodo(row['periodo_treino_fim']), v._periodo(row['init_date']))

    def test_c_propria_inicializacao_nunca_entra_no_proprio_treino(self):
        linhas = [_linha(f'{1990+i}-06', 1, 6, forecast=200.0, obs=100.0) for i in range(10)]
        linhas.append(_linha('2000-06', 1, 6, forecast=200.0, obs=-99999.0))
        base = pd.DataFrame(linhas)
        tabela, _ = m.construir_tabela_calibracao_multiplicativa(base)
        linha = tabela[tabela['init_date'] == '2000-06'].iloc[0]
        self.assertEqual(linha['status_multiplicativo'], m.STATUS_OK)
        # se a observação absurda da própria linha tivesse entrado no
        # treino, media_obs_treino ficaria extremamente negativa.
        self.assertAlmostEqual(linha['media_obs_treino'], 100.0, places=6)
        self.assertAlmostEqual(linha['razao_multiplicativa'], 0.5, places=6)

    def test_d_nenhum_leakage_detectado_em_tabela_sintetica(self):
        linhas = [_linha(f'{1990+i}-06', 1, 6, forecast=150.0 + i, obs=90.0 + 0.3 * i)
                  for i in range(20)]
        base = pd.DataFrame(linhas)
        tabela, _ = m.construir_tabela_calibracao_multiplicativa(base)
        resultado = m._verificar_nenhum_leakage_na_tabela_multiplicativa(tabela)
        self.assertTrue(resultado['ok'], resultado['problemas'])


class NumeradorDenominadorMesmaBaseTestCase(unittest.TestCase):
    """Item 3/16 do pedido — numerador e denominador da razão usam
    EXATAMENTE os mesmos anos históricos."""

    def test_a_verificacao_independente_passa_em_dados_sinteticos(self):
        linhas = [_linha(f'{1990+i}-06', 1, 6, forecast=100.0 + i, obs=70.0 + 0.5 * i)
                  for i in range(15)]
        base = pd.DataFrame(linhas)
        tabela, media_membros = m.construir_tabela_calibracao_multiplicativa(base)
        resultado = m.verificar_numerador_denominador_mesma_base(tabela, media_membros)
        self.assertTrue(resultado['ok'], resultado['problemas'])

    def test_b_deteta_divergencia_proposital_entre_as_duas_medias(self):
        linhas = [_linha(f'{1990+i}-06', 1, 6, forecast=100.0, obs=80.0) for i in range(12)]
        base = pd.DataFrame(linhas)
        tabela, media_membros = m.construir_tabela_calibracao_multiplicativa(base)
        tabela_errada = tabela.copy()
        tabela_errada.loc[tabela_errada['status_multiplicativo'] == m.STATUS_OK,
                           'media_obs_treino'] += 999.0
        resultado = m.verificar_numerador_denominador_mesma_base(tabela_errada, media_membros)
        self.assertFalse(resultado['ok'])
        self.assertGreater(resultado['n_problemas'], 0)

    def test_c_media_prev_e_obs_treino_vem_da_mesma_lista_de_inits_por_construcao(self):
        """Confirma, nos próprios dados sintéticos, que os n_treino
        anos usados no numerador são idênticos aos do denominador —
        nunca duas listas que poderiam desalinhar."""
        linhas = [_linha(f'{1990+i}-06', 1, 6, forecast=100.0 + i, obs=80.0 - i)
                  for i in range(14)]
        base = pd.DataFrame(linhas)
        tabela, media_membros = m.construir_tabela_calibracao_multiplicativa(base)
        ultima = tabela[tabela['init_date'] == '2003-06'].iloc[0]
        mascara = ((media_membros['lead'] == 1) & (media_membros['target_mes'] == 6)
                   & (pd.PeriodIndex(media_membros['init_date'], freq='M') < v._periodo('2003-06')))
        historico = media_membros[mascara]
        self.assertEqual(len(historico), ultima['n_treino'])
        self.assertAlmostEqual(float(historico['forecast_raw'].mean()), ultima['media_prev_treino'],
                                places=9)
        self.assertAlmostEqual(float(historico['observacao'].mean()), ultima['media_obs_treino'],
                                places=9)


class PisoDenominadorTestCase(unittest.TestCase):
    """Item 1/2/16 do pedido — piso aplicado exatamente, sem cap de
    razão acima do piso, sem fallback para a correção aditiva."""

    def test_a_abaixo_do_piso_nunca_produz_previsao_calibrada(self):
        linhas = [_linha(f'{1990+i}-07', 1, 7, forecast=2.0, obs=0.3) for i in range(15)]
        base = pd.DataFrame(linhas)
        tabela, _ = m.construir_tabela_calibracao_multiplicativa(base)
        elegiveis = tabela[tabela['n_treino'] >= m.N_TREINO_MINIMO]
        self.assertTrue((elegiveis['media_prev_treino'] < m.PISO_DENOMINADOR_MM).all())
        self.assertTrue((elegiveis['status_multiplicativo'] == m.STATUS_PISO).all())
        self.assertTrue(elegiveis['forecast_multiplicativo'].isna().all())
        self.assertTrue(elegiveis['razao_multiplicativa'].isna().all())

    def test_b_piso_e_exatamente_dez_milimetros_na_fronteira(self):
        # denominador construído para ficar bem perto do piso dos dois lados.
        linhas_abaixo = [_linha(f'{1990+i}-07', 1, 7, forecast=9.9, obs=5.0) for i in range(12)]
        base_abaixo = pd.DataFrame(linhas_abaixo)
        tabela_abaixo, _ = m.construir_tabela_calibracao_multiplicativa(base_abaixo)
        elegivel_abaixo = tabela_abaixo[tabela_abaixo['n_treino'] >= m.N_TREINO_MINIMO].iloc[0]
        self.assertEqual(elegivel_abaixo['status_multiplicativo'], m.STATUS_PISO)

        linhas_acima = [_linha(f'{1990+i}-07', 1, 7, forecast=10.1, obs=5.0) for i in range(12)]
        base_acima = pd.DataFrame(linhas_acima)
        tabela_acima, _ = m.construir_tabela_calibracao_multiplicativa(base_acima)
        elegivel_acima = tabela_acima[tabela_acima['n_treino'] >= m.N_TREINO_MINIMO].iloc[0]
        self.assertEqual(elegivel_acima['status_multiplicativo'], m.STATUS_OK)

    def test_c_acima_do_piso_razao_alta_nao_sofre_cap(self):
        """Simula o achado de outubro: denominador seguro, razão > 4 —
        tem que passar INTACTA, nunca truncada para um teto como
        min(razao, 3)/min(razao, 4)."""
        linhas = [_linha(f'{1990+i}-10', 1, 10, forecast=20.0, obs=100.0) for i in range(12)]
        base = pd.DataFrame(linhas)
        tabela, _ = m.construir_tabela_calibracao_multiplicativa(base)
        elegivel = tabela[tabela['n_treino'] >= m.N_TREINO_MINIMO].iloc[0]
        self.assertEqual(elegivel['status_multiplicativo'], m.STATUS_OK)
        self.assertAlmostEqual(elegivel['razao_multiplicativa'], 5.0, places=6)
        self.assertAlmostEqual(elegivel['forecast_multiplicativo'], 100.0, places=6)

    def test_d_nenhuma_razao_ou_forecast_negativo_em_amostra_sintetica_variada(self):
        rng = np.random.default_rng(42)
        linhas = []
        for i in range(30):
            linhas.append(_linha(f'{1985+i}-11', 1, 11, forecast=float(rng.uniform(5, 300)),
                                  obs=float(rng.uniform(1, 300))))
        base = pd.DataFrame(linhas)
        tabela, _ = m.construir_tabela_calibracao_multiplicativa(base)
        ok = tabela[tabela['status_multiplicativo'] == m.STATUS_OK]
        self.assertTrue((ok['razao_multiplicativa'] > 0).all())
        self.assertTrue((ok['forecast_multiplicativo'] >= 0).all())
        self.assertEqual(int((tabela['status_multiplicativo'] == m.STATUS_RAZAO_INVALIDA).sum()), 0)
        self.assertEqual(int((tabela['status_multiplicativo'] == m.STATUS_FORECAST_INVALIDO).sum()), 0)

    def test_e_denominador_exatamente_no_piso_e_elegivel_piso_e_inclusivo(self):
        """`_avaliar_razao_e_forecast` usa `< PISO`, não `<=` — o valor
        exatamente igual ao piso é elegível (regra escrita no código,
        confirmada aqui para nunca mudar silenciosamente)."""
        razao, forecast_mult, status = m._avaliar_razao_e_forecast(
            forecast_raw=10.0, media_prev_treino=10.0, media_obs_treino=5.0)
        self.assertEqual(status, m.STATUS_OK)
        self.assertAlmostEqual(razao, 0.5, places=9)


class LeituraEMetadadosLoyoTestCase(unittest.TestCase):

    def test_a_loyo_usa_todos_os_outros_anos_nunca_so_o_passado(self):
        linhas = [_linha(f'{1990+i}-07', 1, 7, forecast=200.0 + i, obs=100.0) for i in range(15)]
        base = pd.DataFrame(linhas)
        tabela_loyo = m.construir_tabela_calibracao_multiplicativa_loyo(base, pd.DataFrame())
        linha_meio = tabela_loyo[tabela_loyo['init_date'] == '1997-07'].iloc[0]
        # com 15 anos no grupo, excluir só o próprio ano ainda deixa 14
        # >= N_TREINO_MINIMO=10 — elegível mesmo sendo a 8ª posição
        # cronológica (o que seria warm-up no desenho causal).
        self.assertEqual(linha_meio['n_treino'], 14)


class ComDadosReaisTestCase(unittest.TestCase):
    """Usa os arquivos JÁ APROVADOS do repositório (sem rede) — confirma
    N, ausência de leakage, piso sem fragmentação e a comparação
    pareada com o Método 3.1 na base real."""

    def setUp(self):
        if not a.CAMINHO_TABELA_EXPANDING.exists():
            self.skipTest("aditiva_expanding.csv (Método 3.1, aprovado) não encontrado nesta "
                           "árvore de trabalho")
        if not v.CAMINHO_METRICAS_JSON.parent.exists():
            self.skipTest("dados reais da 2C.3C não disponíveis nesta árvore de trabalho")
        self.resultado, self.tabela, self.tabela_loyo = m.executar_calibracao_multiplicativa(
            n_resamples_bootstrap=30)

    def test_a_pipeline_completo_sem_stop_on_failure(self):
        self.assertFalse(self.resultado.get('STOP_ON_FAILURE', True), self.resultado.get('motivo'))

    def test_b_n_total_elegivel_e_480_80_por_horizonte(self):
        contagem = self.resultado['verificacao_contagem_elegivel']
        self.assertEqual(contagem['n_total_elegivel'], 480)
        for lead in v.LEADS_ESPERADOS:
            self.assertEqual(contagem['contagem_real_por_horizonte'][lead], 80)

    def test_c_piso_nao_fragmenta_nenhum_mes_em_nenhum_lead(self):
        fragmentacao = self.resultado['verificacao_piso_nao_fragmenta_mes']
        self.assertTrue(fragmentacao['ok'], fragmentacao['meses_fragmentados'])
        self.assertEqual(fragmentacao['meses_inteiramente_ok'], list(m.MESES_ELEGIVEIS))
        self.assertEqual(fragmentacao['meses_inteiramente_piso'], list(m.MESES_EXCLUIDOS_PELO_PISO))

    def test_d_nenhum_leakage_na_base_real(self):
        self.assertTrue(self.resultado['leakage_check']['ok'])

    def test_e_numerador_denominador_mesma_base_na_real(self):
        self.assertTrue(self.resultado['verificacao_numerador_denominador_mesma_base']['ok'])

    def test_f_aditivo_matched_e_multiplicativo_tem_exatamente_as_mesmas_chaves(self):
        tabela_aditiva = pd.read_csv(a.CAMINHO_TABELA_EXPANDING)
        chaves_mult = set(map(tuple, self.tabela[
            self.tabela['status_multiplicativo'] == m.STATUS_OK
        ][['init_date', 'lead']].values.tolist()))
        comparacao = m.construir_tabela_comparacao(self.tabela, tabela_aditiva)
        chaves_comparacao = set(map(tuple, comparacao[['init_date', 'lead']].values.tolist()))
        self.assertEqual(chaves_mult, chaves_comparacao)
        self.assertEqual(len(chaves_mult), 480)

    def test_g_outubro_tem_razao_mediana_maior_que_quatro_e_nao_foi_truncado(self):
        """Confirma o achado do diagnóstico prévio sobrevive intacto na
        implementação real (H1 é o lead mais extremo, ~7x no
        diagnóstico)."""
        diagnostico = self.resultado['expanding_operational_simulation'][
            'diagnostico_maio_outubro_novembro']
        cel = diagnostico[10][1]
        self.assertGreater(cel['razao_mediana'], 4.0)

    def test_h_nenhum_mes_excluido_do_diagnostico_obrigatorio(self):
        diagnostico = self.resultado['expanding_operational_simulation'][
            'diagnostico_maio_outubro_novembro']
        for mes in m.MESES_DIAGNOSTICO_OBRIGATORIO:
            for lead in v.LEADS_ESPERADOS:
                self.assertGreater(diagnostico[mes][lead]['n'], 0,
                                    f"mês {mes} lead {lead} não deveria estar vazio/excluído")

    def test_i_skill_multiplicativo_vs_aditivo_presente_em_todos_os_horizontes(self):
        det = self.resultado['expanding_operational_simulation']['deterministico_por_horizonte']
        boot = self.resultado['expanding_operational_simulation'][
            'intervalos_confianca_skills_por_horizonte']
        for lead in v.LEADS_ESPERADOS:
            self.assertIn('skill_multiplicativo_vs_aditivo', det[lead])
            self.assertIn('skill_multiplicativo_vs_aditivo', boot[lead])

    def test_j_metodo_3_1_permanece_byte_identico_apos_rodar_o_metodo_3_2(self):
        """Item 17 do pedido — 'alteração dos artefatos aprovados do
        Método 3.1' é STOP-ON-FAILURE; aqui confirmamos via git que o
        arquivo não foi tocado por esta suíte nem pela execução acima."""
        resultado_git = subprocess.run(
            ['git', 'diff', '--quiet', 'HEAD', '--',
             str(a.CAMINHO_TABELA_EXPANDING.relative_to(a.ROOT))],
            cwd=a.ROOT, capture_output=True)
        self.assertEqual(resultado_git.returncode, 0,
                          f"{a.CAMINHO_TABELA_EXPANDING} divergiu do HEAD commitado")


class BootstrapMesmosBlocosTestCase(unittest.TestCase):
    """Item 10/16 do pedido — garante ESTRUTURALMENTE que o bootstrap
    usa os MESMOS blocos de ano para multiplicativo, os três
    benchmarks E o aditivo matched em cada reamostra."""

    def test_mesmas_observacoes_alimentam_todas_as_cinco_series_na_mesma_reamostra(self):
        if not a.CAMINHO_TABELA_EXPANDING.exists() or not v.CAMINHO_METRICAS_JSON.parent.exists():
            self.skipTest("dados reais não disponíveis nesta árvore de trabalho")
        resultado, tabela, _ = m.executar_calibracao_multiplicativa(n_resamples_bootstrap=1)
        self.assertFalse(resultado.get('STOP_ON_FAILURE', True))
        tabela_aditiva = pd.read_csv(a.CAMINHO_TABELA_EXPANDING)
        comparacao = m.construir_tabela_comparacao(tabela, tabela_aditiva)

        observados_capturados = []
        orig_rmse = v._rmse

        def fake_rmse(previsto, observado):
            observados_capturados.append(tuple(np.asarray(observado, dtype=float)))
            return orig_rmse(previsto, observado)

        n_resamples = 5
        with mock.patch.object(v, '_rmse', side_effect=fake_rmse), \
             mock.patch.object(v, 'LEADS_ESPERADOS', (1,)):
            m.bootstrap_skills_multiplicativa_vs_aditiva_por_horizonte(
                comparacao, n_resamples=n_resamples, seed=1)

        # 5 chamadas por reamostra (mult, raw, clim, bench3, aditivo) + 5 pontuais
        self.assertEqual(len(observados_capturados), 5 * (n_resamples + 1))
        for i in range(n_resamples):
            grupo = observados_capturados[5 * i:5 * i + 5]
            self.assertEqual(len(set(grupo)), 1,
                              f"reamostra {i}: multiplicativo, benchmarks e aditivo usaram "
                              "observações DIFERENTES — violaria a garantia de mesmos blocos")


class RelatorioMultiplicativaTestCase(unittest.TestCase):
    """Smoke test do gerador de relatório — nunca recalcula métrica, só
    formata o que já foi calculado; nunca declara o método validado ou
    o multiplicativo superior ao aditivo sem o IC apoiar isso."""

    _FRASES_PROIBIDAS = ('o modelo está validado', 'está pronto para produção',
                          'está pronto para o dashboard', 'é um método aprovado',
                          'multiplicativo é melhor que o aditivo',
                          'supera o método aditivo')

    def _assert_nunca_declara_conclusao_isolada(self, texto):
        baixo = texto.lower()
        for frase in self._FRASES_PROIBIDAS:
            self.assertNotIn(frase, baixo, f"texto afirma diretamente: {frase!r}")

    def test_a_stop_on_failure_gera_relatorio_minimo(self):
        import cfsv2_relatorio_multiplicativa_2c3d as rel
        resultados = {'STOP_ON_FAILURE': True, 'motivo': 'teste'}
        relatorio = rel.gerar_relatorio_markdown(resultados)
        self.assertIn('STOP-ON-FAILURE', relatorio)
        self._assert_nunca_declara_conclusao_isolada(relatorio)

    def test_b_relatorio_real_cobre_secoes_obrigatorias(self):
        if not m.CAMINHO_METRICAS_JSON.exists():
            self.skipTest("métricas da calibração multiplicativa ainda não geradas nesta árvore")
        import json
        import cfsv2_relatorio_multiplicativa_2c3d as rel
        resultados = json.loads(m.CAMINHO_METRICAS_JSON.read_text())
        relatorio = rel.gerar_relatorio_markdown(resultados)
        for secao in ('Metodologia', 'Elegibilidade e piso', 'N elegível total', 'benchmarks',
                      'Comparação PRINCIPAL', 'Intervalos de confiança', 'Diagnóstico obrigatório',
                      'Mai', 'Out', 'Nov',
                      'Matriz mês-alvo', 'LOYO matched', 'Limitações', 'Conclusão restrita'):
            self.assertIn(secao, relatorio)
        self._assert_nunca_declara_conclusao_isolada(relatorio)

    def test_c_relatorio_nunca_afirma_jun_set_como_desempenho_anual(self):
        if not m.CAMINHO_METRICAS_JSON.exists():
            self.skipTest("métricas da calibração multiplicativa ainda não geradas nesta árvore")
        import json
        import cfsv2_relatorio_multiplicativa_2c3d as rel
        resultados = json.loads(m.CAMINHO_METRICAS_JSON.read_text())
        relatorio = rel.gerar_relatorio_markdown(resultados)
        self.assertIn('nunca reportar isto como', relatorio.lower())
        self.assertNotIn('desempenho anual do método 3.2 é', relatorio.lower())


if __name__ == '__main__':
    unittest.main()
