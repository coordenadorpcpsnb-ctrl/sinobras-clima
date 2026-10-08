#!/usr/bin/env python3
"""
tests/test_cfsv2_robustez_h2_spread.py — Fase 2C.3D, robustez do sinal
spread×erro controlado por mês em H2 (item 13 do pedido de robustez).

Cobre: mês removido realmente ausente da reamostra; residualização
recalculada sobre os dados restantes (nunca reaproveitando resíduos da
análise completa); bootstrap continua resampleando `target_ano`; cenário
sintético robusto permanece positivo ao remover qualquer mês; cenário
sintético dependente de um único mês é corretamente identificado como
frágil; métricas congeladas do gate (CRPS/CRPSS/Brier/BSS/cobertura/
ranks/dependência de membros) permanecem inalteradas.

Todos os testes usam dados SINTÉTICOS — nenhuma rede, nenhum dado real
do CFSv2/CHIRPS é necessário para rodar esta suíte.

Roda com:
    python -m unittest tests.test_cfsv2_robustez_h2_spread -v
"""

import json
import subprocess
import sys
import unittest
import unittest.mock as mock
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import cfsv2_gate_calibracao_probabilistica as g  # noqa: E402
import cfsv2_robustez_h2_spread as r  # noqa: E402
import cfsv2_validacao_cientifica as v  # noqa: E402

COMMIT_ANTERIOR = '8ed49e653ddef0ad9cfd82470f221435161edd9c'


def _tabela_h2(linhas):
    return pd.DataFrame(linhas)


def _tabela_h2_robusta_sintetica(n_anos=20, seed=21):
    """Relação spread×erro POSITIVA e consistente em TODOS os 12
    meses — leave-one-month-out deve permanecer positivo em qualquer
    exclusão."""
    rng = np.random.default_rng(seed)
    linhas = []
    for ano in range(2000, 2000 + n_anos):
        for mes in range(1, 13):
            nivel = 40.0 if mes <= 6 else 15.0
            eps_s = rng.normal(0, 5)
            spread = max(0.1, nivel + eps_s)
            erro_abs = max(0.0, nivel + 0.7 * eps_s + rng.normal(0, 2))
            linhas.append({'lead': 2, 'target_ano': ano, 'target_mes': mes,
                            'ensemble_std': spread, 'erro_abs': erro_abs,
                            'ensemble_variance': spread ** 2, 'erro_quadratico': erro_abs ** 2})
    return _tabela_h2(linhas)


def _tabela_h2_dependente_de_um_mes_sintetica(n_anos=20, seed=22, mes_especial=7):
    """O sinal POOLED positivo vem quase inteiramente de um único mês
    (variância de spread muito maior, relação fortemente positiva);
    nos outros 11 meses a relação real é NEGATIVA — excluir o mês
    especial deve inverter fortemente o sinal."""
    rng = np.random.default_rng(seed)
    linhas = []
    for ano in range(2000, 2000 + n_anos):
        for mes in range(1, 13):
            nivel = 40.0 if mes <= 6 else 15.0
            if mes == mes_especial:
                eps_s = rng.normal(0, 18)
                spread = max(0.1, nivel + eps_s)
                erro_abs = max(0.0, nivel + 2.5 * eps_s + rng.normal(0, 3))
            else:
                eps_s = rng.normal(0, 5)
                spread = max(0.1, nivel + eps_s)
                erro_abs = max(0.0, nivel - 0.6 * eps_s + rng.normal(0, 2))
            linhas.append({'lead': 2, 'target_ano': ano, 'target_mes': mes,
                            'ensemble_std': spread, 'erro_abs': erro_abs,
                            'ensemble_variance': spread ** 2, 'erro_quadratico': erro_abs ** 2})
    return _tabela_h2(linhas)


class MesRemovidoRealmenteAusenteTestCase(unittest.TestCase):

    def test_a_cada_exclusao_remove_integralmente_o_mes(self):
        tabela = _tabela_h2_robusta_sintetica()
        lomo = r.leave_one_month_out_h2(tabela, n_resamples=10, seed=1)
        sub_h2 = tabela[tabela['lead'] == 2]
        for mes in range(1, 13):
            n_esperado = len(sub_h2[sub_h2['target_mes'] != mes])
            self.assertEqual(lomo[mes]['n'], n_esperado,
                              f"N da exclusão do mês {mes} não bate com filtrar target_mes != {mes}")


class ResidualizacaoRecalculadaAposExclusaoTestCase(unittest.TestCase):

    def test_a_estimativa_pontual_bate_com_residuo_calculado_manualmente_sobre_dados_restantes(self):
        """A correlação pontual (fora do bootstrap) de cada exclusão
        deve ser idêntica a filtrar manualmente a tabela e
        residualizar com `g._residuo_centrado_por_mes` direto sobre os
        dados restantes — nunca reaproveitando resíduos já calculados
        na análise completa (que incluiria o mês excluído na
        centralização)."""
        tabela = _tabela_h2_robusta_sintetica()
        mes_excluido = 5
        lomo = r.leave_one_month_out_h2(tabela, n_resamples=10, seed=1)

        sub_h2 = tabela[tabela['lead'] == 2].reset_index(drop=True)
        sub_manual = sub_h2[sub_h2['target_mes'] != mes_excluido].reset_index(drop=True)
        resid_std = g._residuo_centrado_por_mes(sub_manual, 'target_mes', 'ensemble_std')
        resid_abs = g._residuo_centrado_por_mes(sub_manual, 'target_mes', 'erro_abs')
        pearson_manual = v._corr(resid_std, resid_abs)

        self.assertAlmostEqual(lomo[mes_excluido]['pearson']['estimativa'], pearson_manual, places=10)

    def test_b_residuo_calculado_sobre_dados_com_mes_excluido_difere_do_residuo_completo(self):
        """Confirma que a exclusão realmente muda a composição usada
        para montar os resíduos (nenhum atalho que ignore a
        exclusão)."""
        tabela = _tabela_h2_dependente_de_um_mes_sintetica()
        sub_h2 = tabela[tabela['lead'] == 2].reset_index(drop=True)
        resid_completo = g._residuo_centrado_por_mes(sub_h2, 'target_mes', 'erro_abs')

        sub_sem_mes7 = sub_h2[sub_h2['target_mes'] != 7].reset_index(drop=True)
        resid_sem_mes7 = g._residuo_centrado_por_mes(sub_sem_mes7, 'target_mes', 'erro_abs')

        # tamanhos diferentes já provam que a exclusão foi aplicada
        # antes da residualização, não depois
        self.assertNotEqual(len(resid_completo), len(resid_sem_mes7))
        self.assertEqual(len(resid_sem_mes7), len(sub_h2[sub_h2['target_mes'] != 7]))


class BootstrapContinuaPorTargetAnoTestCase(unittest.TestCase):

    def test_a_leave_one_month_out_chama_bootstrap_com_coluna_ano_target_ano(self):
        tabela = _tabela_h2_robusta_sintetica()
        colunas_ano_vistas = []
        orig = g._bootstrap_residualizado_por_ano

        def fake(df_lead, coluna_mes, coluna_ano, coluna_x, coluna_y, funcao_metrica,
                  n_resamples=500, seed=20261001):
            colunas_ano_vistas.append(coluna_ano)
            self.assertNotIn('member', df_lead.columns)
            return orig(df_lead, coluna_mes, coluna_ano, coluna_x, coluna_y, funcao_metrica,
                        n_resamples=5, seed=seed)

        with mock.patch.object(g, '_bootstrap_residualizado_por_ano', side_effect=fake):
            r.leave_one_month_out_h2(tabela, n_resamples=5, seed=2)

        self.assertTrue(len(colunas_ano_vistas) > 0)
        self.assertTrue(all(c == 'target_ano' for c in colunas_ano_vistas))

    def test_b_leave_one_season_out_chama_bootstrap_com_coluna_ano_target_ano(self):
        tabela = _tabela_h2_robusta_sintetica()
        colunas_ano_vistas = []
        orig = g._bootstrap_residualizado_por_ano

        def fake(df_lead, coluna_mes, coluna_ano, coluna_x, coluna_y, funcao_metrica,
                  n_resamples=500, seed=20261001):
            colunas_ano_vistas.append(coluna_ano)
            return orig(df_lead, coluna_mes, coluna_ano, coluna_x, coluna_y, funcao_metrica,
                        n_resamples=5, seed=seed)

        with mock.patch.object(g, '_bootstrap_residualizado_por_ano', side_effect=fake):
            r.leave_one_season_out_h2(tabela, n_resamples=5, seed=2)

        self.assertTrue(len(colunas_ano_vistas) > 0)
        self.assertTrue(all(c == 'target_ano' for c in colunas_ano_vistas))


class ClassificacaoDeRobustezSinteticaTestCase(unittest.TestCase):

    def test_a_cenario_robusto_permanece_positivo_ao_remover_qualquer_mes(self):
        tabela = _tabela_h2_robusta_sintetica()
        lomo = r.leave_one_month_out_h2(tabela, n_resamples=40, seed=3)
        resumo = r.resumo_leave_one_month_out(lomo)
        robustez = r.classificar_robustez_h2(lomo, resumo)

        self.assertEqual(resumo['n_exclusoes_pearson_positivo'], 12)
        self.assertEqual(resumo['n_exclusoes_spearman_positivo'], 12)
        self.assertEqual(robustez['classificacao'], r.CLASSIFICACAO_H2_ROBUSTO)
        self.assertFalse(robustez['sinais']['inversao_forte_em_alguma_exclusao'])

    def test_b_cenario_dependente_de_um_mes_e_identificado_como_fragil(self):
        tabela = _tabela_h2_dependente_de_um_mes_sintetica()
        lomo = r.leave_one_month_out_h2(tabela, n_resamples=40, seed=3)
        resumo = r.resumo_leave_one_month_out(lomo)
        robustez = r.classificar_robustez_h2(lomo, resumo)

        self.assertLess(lomo[7]['pearson']['estimativa'], r.LIMIAR_INVERSAO_FORTE,
                         "excluir o mês especial (7) deveria inverter fortemente o sinal")
        self.assertTrue(robustez['sinais']['inversao_forte_em_alguma_exclusao'])
        self.assertEqual(robustez['classificacao'], r.CLASSIFICACAO_H2_DEPENDENTE_POUCOS_MESES)
        self.assertNotEqual(robustez['classificacao'], r.CLASSIFICACAO_H2_ROBUSTO)


class MetricasCongeladasPermanecemInalteradasTestCase(unittest.TestCase):
    """Item 11 do pedido — CRPS, CRPSS, Brier, BSS, cobertura, ranks e
    dependência de membros permanecem congelados nesta atividade;
    comparados numericamente contra o JSON já publicado no commit
    anterior (`8ed49e6`)."""

    def test_a_metricas_identicas_ao_commit_anterior(self):
        if not v.CAMINHO_METRICAS_JSON.parent.exists():
            self.skipTest("dados reais não disponíveis nesta árvore de trabalho")
        try:
            saida = subprocess.run(
                ['git', 'show',
                 f'{COMMIT_ANTERIOR}:data/cfsv2_calibracao_2c3d/gate_calibracao_probabilistica_2c3d.json'],
                cwd=str(ROOT), capture_output=True, text=True, timeout=30, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            self.skipTest(f"commit {COMMIT_ANTERIOR} não disponível neste checkout")
        anterior = json.loads(saida.stdout)

        if not g.CAMINHO_METRICAS_JSON.exists():
            self.skipTest("JSON do gate não foi gerado nesta árvore de trabalho")
        atual = json.loads(g.CAMINHO_METRICAS_JSON.read_text())
        if atual.get('STOP_ON_FAILURE'):
            self.skipTest("gate atual está em STOP_ON_FAILURE")

        prob_atual = atual['probabilistico_por_horizonte']
        prob_anterior = anterior['probabilistico_por_horizonte']
        cov_atual = atual['cobertura_intervalos_por_horizonte']
        cov_anterior = anterior['cobertura_intervalos_por_horizonte']
        dep_atual = atual['dependencia_membros_por_horizonte']
        dep_anterior = anterior['dependencia_membros_por_horizonte']

        for lead_str in map(str, v.LEADS_ESPERADOS):
            pa = prob_atual.get(lead_str, prob_atual.get(int(lead_str)))
            pb = prob_anterior[lead_str]
            for campo in ('crps_medio_modelo', 'crps_medio_climatologia', 'crpss'):
                self.assertAlmostEqual(pa[campo], pb[campo], places=9,
                                        msg=f"{campo} mudou para H{lead_str}")
            for cat in ('seco', 'normal', 'umido'):
                self.assertAlmostEqual(pa['brier_score_por_categoria'][cat],
                                        pb['brier_score_por_categoria'][cat], places=9)
                self.assertAlmostEqual(pa['bss_por_categoria'][cat],
                                        pb['bss_por_categoria'][cat], places=9)
            rank_a = pa['rank_histogram_diagnostico']
            rank_b = pb['rank_histogram_diagnostico']
            self.assertAlmostEqual(rank_a['frequencia_rank_1'], rank_b['frequencia_rank_1'], places=9)
            self.assertAlmostEqual(rank_a['frequencia_rank_m_mais_1'],
                                    rank_b['frequencia_rank_m_mais_1'], places=9)

            ca = cov_atual.get(lead_str, cov_atual.get(int(lead_str)))
            cb = cov_anterior[lead_str]
            for nominal in ('50', '80', '90'):
                self.assertAlmostEqual(ca['intervalos'][nominal]['cobertura_observada'],
                                        cb['intervalos'][nominal]['cobertura_observada'], places=9)

            da = dep_atual.get(lead_str, dep_atual.get(int(lead_str)))
            db = dep_anterior[lead_str]
            self.assertAlmostEqual(da['correlacao_membros_raw'], db['correlacao_membros_raw'], places=9)
            self.assertAlmostEqual(da['correlacao_membros_anomalia_mensal'],
                                    db['correlacao_membros_anomalia_mensal'], places=9)


class ReferenciaCongeladaH2TestCase(unittest.TestCase):

    def test_a_congelamento_confere_com_json_real_do_gate(self):
        if not g.CAMINHO_METRICAS_JSON.exists():
            self.skipTest("JSON do gate não disponível nesta árvore de trabalho")
        gate_resultado = json.loads(g.CAMINHO_METRICAS_JSON.read_text())
        if gate_resultado.get('STOP_ON_FAILURE'):
            self.skipTest("gate atual está em STOP_ON_FAILURE")
        h2 = gate_resultado['spread_skill_month_controlled_retrospective_por_horizonte'].get(
            '2', gate_resultado['spread_skill_month_controlled_retrospective_por_horizonte'].get(2))
        pearson_atual = h2['pearson_std_resid_vs_erro_abs_resid']['estimativa']
        spearman_atual = h2['spearman_std_resid_vs_erro_abs_resid']['estimativa']
        self.assertAlmostEqual(pearson_atual, r.H2_PEARSON_RESIDUAL_CONGELADO, places=3)
        self.assertAlmostEqual(spearman_atual, r.H2_SPEARMAN_RESIDUAL_CONGELADO, places=3)


class OrquestracaoStopOnFailureTestCase(unittest.TestCase):

    def test_a_falha_se_json_do_gate_nao_existir(self):
        with mock.patch.object(r, 'CAMINHO_METRICAS_JSON', Path('/tmp/nao_existe_12345.json')), \
             mock.patch.object(g, 'CAMINHO_METRICAS_JSON', Path('/tmp/nao_existe_12345.json')):
            resultado = r.executar_robustez_h2()
        self.assertTrue(resultado['STOP_ON_FAILURE'])


class ComDadosReaisAprovadosTestCase(unittest.TestCase):

    def test_a_executa_sem_stop_on_failure_com_poucas_reamostras(self):
        if not g.CAMINHO_METRICAS_JSON.exists():
            self.skipTest("JSON do gate não disponível nesta árvore de trabalho")
        resultado = r.executar_robustez_h2(n_resamples_bootstrap=10)
        self.assertFalse(resultado.get('STOP_ON_FAILURE', True))
        self.assertIn(resultado['decisao_final_emos_h2'],
                       (r.DECISAO_PROSSEGUIR_EMOS, r.DECISAO_NAO_JUSTIFICAR_EMOS,
                        r.DECISAO_EVIDENCIA_INSUFICIENTE))


if __name__ == '__main__':
    unittest.main()
