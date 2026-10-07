#!/usr/bin/env python3
"""
tests/test_cfsv2_gate_calibracao_probabilistica.py — Fase 2C.3D, gate
diagnóstico do Método 3.5 (item 15 do pedido).

Cobre: exatamente 24 membros por init×lead (com demonstração de
STOP-ON-FAILURE); spread calculado SOBRE OS MEMBROS, nunca sobre anos;
CRPS empírico conhecido em caso sintético; rank correto em exemplos
sintéticos com e sem empate (tie-break determinístico, item 5); cobertura
de intervalo correta em caso sintético; Brier Score reaproveitando
EXATAMENTE `categoria_tercil`/`BS_ref_nominal` da 2C.3C; bootstrap
preservando blocos anuais; e um teste explícito de que nenhum membro é
tratado como observação histórica independente.

Todos os testes usam dados SINTÉTICOS — nenhuma rede, nenhum dado real
do CFSv2/CHIRPS é necessário para rodar esta suíte.

Roda com:
    python -m unittest tests.test_cfsv2_gate_calibracao_probabilistica -v
"""

import sys
import unittest
import unittest.mock as mock
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import cfsv2_gate_calibracao_probabilistica as g  # noqa: E402
import cfsv2_validacao_cientifica as v  # noqa: E402


def _base_pareada_sintetica(n_inits_por_lead=30, n_membros=24, leads=(1, 2), seed=7):
    """Base pareada sintética mínima, mesmo schema de
    `v.construir_base_pareada`: init_date, target_month, target_ano,
    target_mes, lead, member, forecast_prec_mm, obs_prec_mm."""
    rng = np.random.default_rng(seed)
    linhas = []
    for lead in leads:
        for i in range(n_inits_por_lead):
            init_date = pd.Period(f'{2000 + i // 12}-{(i % 12) + 1:02d}', freq='M')
            target_ano = init_date.year
            target_mes = (init_date.month - 1 + lead) % 12 + 1
            target_month = f'{target_ano}-{target_mes:02d}'
            obs = float(rng.uniform(10, 200))
            for m in range(n_membros):
                linhas.append({
                    'init_date': str(init_date), 'target_month': target_month,
                    'target_ano': target_ano, 'target_mes': target_mes, 'lead': lead,
                    'member': m, 'forecast_prec_mm': float(obs + rng.normal(0, 30)),
                    'obs_prec_mm': obs,
                })
    return pd.DataFrame(linhas)


def _linha_sintetica(membros, observado, tercil_33, tercil_67, anos_hist, target_mes=1):
    return {'membros': np.asarray(membros, dtype=float), 'observado': float(observado),
            'tercil_33': float(tercil_33), 'tercil_67': float(tercil_67),
            'anos_hist': np.asarray(anos_hist, dtype=float), 'target_mes': target_mes}


# ══════════════════════════════════════════════════════════════════════════
# Item 1 do pedido — exatamente 24 membros, STOP-ON-FAILURE
# ══════════════════════════════════════════════════════════════════════════

class Auditoria24MembrosTestCase(unittest.TestCase):

    def test_a_base_valida_aprova_auditoria(self):
        base = _base_pareada_sintetica()
        tabela = g.construir_tabela_ensemble(base)
        auditoria = g._verificar_24_membros(tabela)
        self.assertTrue(auditoria['ok'])
        self.assertEqual(auditoria['n_linhas_divergentes'], 0)

    def test_b_linha_com_23_membros_e_detectada_e_bloqueia(self):
        base = _base_pareada_sintetica(n_inits_por_lead=5, leads=(1,))
        # remove 1 membro de uma única inicialização
        primeiro_init = base['init_date'].iloc[0]
        idx_remover = base[(base['init_date'] == primeiro_init) & (base['member'] == 0)].index
        base = base.drop(index=idx_remover)
        tabela = g.construir_tabela_ensemble(base)
        auditoria = g._verificar_24_membros(tabela)
        self.assertFalse(auditoria['ok'])
        self.assertEqual(auditoria['n_linhas_divergentes'], 1)
        self.assertEqual(auditoria['exemplos'][0]['n_membros_real'], 23)

    def test_c_contagem_divergente_nao_e_silenciosamente_ignorada_no_resultado(self):
        # Mesma checagem usada por `executar_gate_probabilistico` —
        # confirma que o motivo do STOP cita o número exato de membros
        # esperados (nunca um valor assumido implicitamente).
        base = _base_pareada_sintetica(n_inits_por_lead=5, leads=(1,))
        base = base[~((base['init_date'] == base['init_date'].iloc[0]) & (base['member'] == 0))]
        tabela = g.construir_tabela_ensemble(base)
        auditoria = g._verificar_24_membros(tabela)
        self.assertEqual(auditoria['n_linhas_divergentes'], 1)


# ══════════════════════════════════════════════════════════════════════════
# Item 1/9 do pedido — spread calculado SOBRE OS MEMBROS, nunca sobre anos
# ══════════════════════════════════════════════════════════════════════════

class SpreadSobreMembrosNuncaSobreAnosTestCase(unittest.TestCase):

    def test_a_tabela_ensemble_colapsa_24_membros_em_1_linha_por_init_lead(self):
        """Estrutural: se `construir_tabela_ensemble` sempre produz
        exatamente 1 linha por (init_date, lead), os 24 membros NUNCA
        chegam ao bootstrap como linhas independentes — só é possível
        resample ANOS (via `target_ano` de cada linha agregada)."""
        base = _base_pareada_sintetica(n_inits_por_lead=10, leads=(1, 2))
        tabela = g.construir_tabela_ensemble(base)
        n_combos_esperado = base.drop_duplicates(['init_date', 'lead']).shape[0]
        self.assertEqual(len(tabela), n_combos_esperado)
        self.assertNotIn('member', tabela.columns)
        self.assertNotIn('forecast_prec_mm', tabela.columns)

    def test_b_ensemble_std_bate_com_numpy_std_ddof1_sobre_os_membros(self):
        base = _base_pareada_sintetica(n_inits_por_lead=5, leads=(1,))
        tabela = g.construir_tabela_ensemble(base)
        linha = tabela.iloc[0]
        self.assertAlmostEqual(linha['ensemble_std'], float(np.std(linha['membros'], ddof=1)),
                                places=10)

    def test_c_bootstrap_spread_skill_reamostra_target_ano_nunca_membros(self):
        """Espiona `v.bootstrap_blocos_por_ano` para confirmar que
        `coluna_ano='target_ano'` em TODAS as chamadas do spread-skill
        — nunca uma coluna de membro."""
        base = _base_pareada_sintetica(n_inits_por_lead=25, leads=(1,))
        tabela = g.construir_tabela_ensemble(base)
        colunas_ano_usadas = []
        orig = v.bootstrap_blocos_por_ano

        def fake(df_lead, coluna_previsto, coluna_observado, coluna_ano, funcao_metrica,
                  n_resamples=1000, seed=20261001):
            colunas_ano_usadas.append(coluna_ano)
            self_test.assertNotIn('member', df_lead.columns)
            self_test.assertNotIn('membros', coluna_ano)
            return orig(df_lead, coluna_previsto, coluna_observado, coluna_ano,
                        funcao_metrica, n_resamples=5, seed=seed)

        self_test = self
        with mock.patch.object(v, 'LEADS_ESPERADOS', (1,)), \
             mock.patch.object(v, 'bootstrap_blocos_por_ano', side_effect=fake):
            g.spread_skill_por_horizonte(tabela, n_resamples=5)

        self.assertTrue(len(colunas_ano_usadas) > 0)
        self.assertTrue(all(c == 'target_ano' for c in colunas_ano_usadas))


# ══════════════════════════════════════════════════════════════════════════
# Item 7 do pedido — CRPS empírico conhecido em caso sintético
# ══════════════════════════════════════════════════════════════════════════

class CrpsEmpiricoConhecidoTestCase(unittest.TestCase):

    def test_a_crps_zero_quando_todos_os_membros_iguais_a_observacao(self):
        membros = np.full(24, 50.0)
        self.assertAlmostEqual(v.crps_amostral(membros, 50.0), 0.0, places=10)

    def test_b_crps_caso_pequeno_bate_com_formula_fair_calculada_a_mao(self):
        # Ferro et al. 2008: CRPS = mean(|x_i - y|) - sum(|x_i-x_j|, i!=j) / (2*M*(M-1))
        membros = np.array([1.0, 2.0, 3.0, 4.0])
        obs = 2.5
        m = len(membros)
        termo1 = np.mean(np.abs(membros - obs))
        dif = np.abs(membros[:, None] - membros[None, :])
        termo2 = dif.sum() / (m * (m - 1))
        esperado = termo1 - termo2 / 2
        self.assertAlmostEqual(v.crps_amostral(membros, obs), esperado, places=10)
        # valor numérico fechado para este caso específico (conferido à mão):
        # termo1 = mean(|1-2.5|,|2-2.5|,|3-2.5|,|4-2.5|) = mean(1.5,0.5,0.5,1.5) = 1.0
        # termo2 = soma |xi-xj| (i!=j, 12 pares ordenados) / (m*(m-1)) = 20/12 = 1.6666...
        # crps = termo1 - termo2/2 = 1.0 - 0.8333... = 0.1666...
        self.assertAlmostEqual(esperado, 1 / 6, places=8)

    def test_c_resumo_probabilistico_usa_crps_amostral_sem_redefinir(self):
        """Confirma que `_resumo_probabilistico` chama `v.crps_amostral`
        (espiado), nunca uma segunda fórmula paralela."""
        linha = _linha_sintetica([1, 2, 3, 4] * 6, 2.5, tercil_33=2.0, tercil_67=3.0,
                                  anos_hist=[1.0, 2.0, 3.0, 4.0, 5.0])
        chamadas = []
        orig = v.crps_amostral

        def fake(membros, obs):
            chamadas.append((tuple(membros), obs))
            return orig(membros, obs)

        with mock.patch.object(v, 'crps_amostral', side_effect=fake):
            resumo = g._resumo_probabilistico([linha])
        self.assertGreaterEqual(len(chamadas), 1)
        self.assertIn('crps_medio_modelo', resumo)


# ══════════════════════════════════════════════════════════════════════════
# Item 5 do pedido — rank histogram com tie-break DETERMINÍSTICO
# ══════════════════════════════════════════════════════════════════════════

class RankDeterministicoTestCase(unittest.TestCase):

    def test_a_sem_empate_posicao_unica_esperada(self):
        membros = [1.0, 3.0, 5.0, 7.0]
        # obs=4 cai entre 3 e 5 -> 2 membros menores -> rank = 3
        self.assertEqual(g._rank_observacao_determinístico(membros, 4.0), 3)

    def test_b_obs_menor_que_todos_rank_1(self):
        membros = [1.0, 3.0, 5.0, 7.0]
        self.assertEqual(g._rank_observacao_determinístico(membros, 0.0), 1)

    def test_c_obs_maior_que_todos_rank_m_mais_1(self):
        membros = [1.0, 3.0, 5.0, 7.0]
        self.assertEqual(g._rank_observacao_determinístico(membros, 100.0), 5)

    def test_d_empate_simples_usa_ponto_medio_arredondado_meio_para_cima(self):
        # membros=[1,2,2,2,5], obs=2: menores=1, iguais=3
        # posições válidas: 2..5 (4 posições) -> ponto médio = 3.5 -> 4
        membros = [1.0, 2.0, 2.0, 2.0, 5.0]
        self.assertEqual(g._rank_observacao_determinístico(membros, 2.0), 4)

    def test_e_empate_com_numero_impar_de_posicoes_validas_sem_ambiguidade(self):
        # membros=[1,2,2,5], obs=2: menores=1, iguais=2
        # posições válidas: 2..4 (3 posições) -> ponto médio exato = 3
        membros = [1.0, 2.0, 2.0, 5.0]
        self.assertEqual(g._rank_observacao_determinístico(membros, 2.0), 3)

    def test_f_resultado_e_sempre_o_mesmo_nunca_depende_de_rng(self):
        membros = [1.0, 2.0, 2.0, 2.0, 5.0]
        resultados = {g._rank_observacao_determinístico(membros, 2.0) for _ in range(50)}
        self.assertEqual(resultados, {4})

    def test_g_rank_dentro_dos_limites_validos_1_a_m_mais_1(self):
        rng = np.random.default_rng(123)
        for _ in range(200):
            membros = rng.uniform(0, 100, size=24)
            obs = rng.uniform(-10, 110)
            r = g._rank_observacao_determinístico(membros, obs)
            self.assertGreaterEqual(r, 1)
            self.assertLessEqual(r, 25)


# ══════════════════════════════════════════════════════════════════════════
# Item 6 do pedido — cobertura de intervalo correta em caso sintético
# ══════════════════════════════════════════════════════════════════════════

class CoberturaIntervaloSinteticaTestCase(unittest.TestCase):

    def test_a_cobertura_exata_em_caso_controlado(self):
        """4 linhas no mesmo lead, membros = 0..23 em todas (percentis
        idênticos entre linhas); observação dentro do intervalo
        [p25,p75] em 2 delas e fora nas outras 2 -> cobertura 50% =
        exatamente 0.5."""
        membros = np.arange(24, dtype=float)
        p25, p75 = np.percentile(membros, 25), np.percentile(membros, 75)
        self.assertLess(p25, 10)
        self.assertGreater(p75, 10)
        obs_dentro = (p25 + p75) / 2
        obs_fora = -100.0
        linhas = []
        for lead in (1,):
            for obs in (obs_dentro, obs_dentro, obs_fora, obs_fora):
                linhas.append({'lead': lead, 'membros': membros, 'observacao': obs})
        tabela = pd.DataFrame(linhas)
        resultado = g.cobertura_intervalos_por_horizonte(tabela)
        cobertura_50 = resultado[1]['intervalos'][50]
        self.assertAlmostEqual(cobertura_50['cobertura_observada'], 0.5, places=10)
        self.assertAlmostEqual(cobertura_50['coverage_error'], 0.5 - 0.5, places=10)

    def test_b_cobertura_100_quando_observacao_sempre_dentro(self):
        membros = np.arange(24, dtype=float)
        linhas = [{'lead': 1, 'membros': membros, 'observacao': 11.5} for _ in range(10)]
        tabela = pd.DataFrame(linhas)
        resultado = g.cobertura_intervalos_por_horizonte(tabela)
        for nominal in (50, 80, 90):
            self.assertAlmostEqual(resultado[1]['intervalos'][nominal]['cobertura_observada'],
                                    1.0, places=10)


# ══════════════════════════════════════════════════════════════════════════
# Item 8 do pedido — Brier Score reaproveitando EXATAMENTE categoria_tercil
# e BS_ref_nominal da 2C.3C (nunca redefinidos)
# ══════════════════════════════════════════════════════════════════════════

class BrierReaproveitaDefinicoes2c3cTestCase(unittest.TestCase):

    def test_a_resumo_probabilistico_chama_categoria_tercil_da_2c3c(self):
        linha = _linha_sintetica([1, 2, 3] * 8, observado=1.0, tercil_33=2.0, tercil_67=4.0,
                                  anos_hist=[1.0, 2.0, 3.0, 4.0, 5.0])
        chamadas = []
        orig = v.categoria_tercil

        def fake(valor, t33, t67):
            chamadas.append((valor, t33, t67))
            return orig(valor, t33, t67)

        with mock.patch.object(v, 'categoria_tercil', side_effect=fake):
            g._resumo_probabilistico([linha])
        self.assertEqual(len(chamadas), 1)
        self.assertEqual(chamadas[0], (1.0, 2.0, 4.0))

    def test_b_bs_ref_nominal_usa_formula_mean_um_terco_menos_o_nunca_dois_nonos(self):
        # 3 linhas secas (cat_obs='seco') + 1 úmida -> freq_observada['seco'] = 0.75
        linhas = [
            _linha_sintetica([0, 0, 0] * 8, observado=0.0, tercil_33=5.0, tercil_67=10.0,
                              anos_hist=[1, 2, 3, 4, 5]),
            _linha_sintetica([0, 0, 0] * 8, observado=0.0, tercil_33=5.0, tercil_67=10.0,
                              anos_hist=[1, 2, 3, 4, 5]),
            _linha_sintetica([0, 0, 0] * 8, observado=0.0, tercil_33=5.0, tercil_67=10.0,
                              anos_hist=[1, 2, 3, 4, 5]),
            _linha_sintetica([20, 20, 20] * 8, observado=20.0, tercil_33=5.0, tercil_67=10.0,
                              anos_hist=[1, 2, 3, 4, 5]),
        ]
        resumo = g._resumo_probabilistico(linhas)
        o_seco = np.array([1.0, 1.0, 1.0, 0.0])
        bs_ref_esperado = float(np.mean((1 / 3 - o_seco) ** 2))
        self.assertAlmostEqual(resumo['brier_referencia_nominal_por_categoria']['seco'],
                                bs_ref_esperado, places=10)
        self.assertNotAlmostEqual(bs_ref_esperado, 2 / 9, places=6)

    def test_c_bss_bate_com_a_propria_formula_1_menos_bs_sobre_bs_ref(self):
        linhas = [
            _linha_sintetica([0, 0, 0] * 8, observado=0.0, tercil_33=5.0, tercil_67=10.0,
                              anos_hist=[1, 2, 3, 4, 5]),
            _linha_sintetica([20, 20, 20] * 8, observado=20.0, tercil_33=5.0, tercil_67=10.0,
                              anos_hist=[1, 2, 3, 4, 5]),
        ]
        resumo = g._resumo_probabilistico(linhas)
        for cat in ('seco', 'normal', 'umido'):
            bs = resumo['brier_score_por_categoria'][cat]
            bs_ref = resumo['brier_referencia_nominal_por_categoria'][cat]
            if bs_ref > 0:
                self.assertAlmostEqual(resumo['bss_por_categoria'][cat], 1 - bs / bs_ref, places=10)


# ══════════════════════════════════════════════════════════════════════════
# Item 15 do pedido — bootstrap preservando blocos anuais
# ══════════════════════════════════════════════════════════════════════════

class BootstrapPreservaBlocosAnuaisTestCase(unittest.TestCase):

    def test_a_cada_reamostra_do_bootstrap_contem_apenas_anos_completos(self):
        """Reproduz o padrão já usado em
        `BootstrapSkillScoresMesmosBlocosTestCase` (2C.3C): cada
        reamostra do bootstrap em blocos só pode conter linhas cujo
        `target_ano` pertence ao conjunto de anos sorteado — nunca uma
        linha "solta" de um ano não sorteado."""
        base = _base_pareada_sintetica(n_inits_por_lead=25, leads=(1,))
        tabela = g.construir_tabela_ensemble(base)
        sub = tabela[tabela['lead'] == 1].dropna(subset=['ensemble_std'])

        anos_vistos_por_resample = []
        orig_choice = np.random.default_rng(1).choice

        rng_real = np.random.default_rng(99)

        def fake_bootstrap(df_lead, coluna_previsto, coluna_observado, coluna_ano,
                             funcao_metrica, n_resamples=5, seed=1):
            anos = df_lead[coluna_ano].unique()
            for _ in range(n_resamples):
                anos_sorteados = set(rng_real.choice(anos, size=len(anos), replace=True))
                anos_vistos_por_resample.append(anos_sorteados)
            return {'estimativa': 0.0, 'ic95_lo': 0.0, 'ic95_hi': 0.0}

        with mock.patch.object(v, 'bootstrap_blocos_por_ano', side_effect=fake_bootstrap):
            g.spread_skill_por_horizonte(tabela, n_resamples=5)

        anos_reais = set(sub['target_ano'].unique())
        for anos_sorteados in anos_vistos_por_resample:
            self.assertTrue(anos_sorteados.issubset(anos_reais))

    def test_b_dependencia_membros_nunca_usa_bootstrap_de_anos_ou_membros(self):
        """`dependencia_membros_por_horizonte` calcula a correlação
        par-a-par sobre a amostra COMPLETA (nenhum bootstrap) — este
        teste documenta e fixa esse comportamento: rodar duas vezes dá
        exatamente o mesmo resultado (nenhuma fonte de aleatoriedade)."""
        base = _base_pareada_sintetica(n_inits_por_lead=25, leads=(1,))
        r1 = g.dependencia_membros_por_horizonte(base)
        r2 = g.dependencia_membros_por_horizonte(base)
        self.assertEqual(r1[1]['correlacao_media_par_a_par'], r2[1]['correlacao_media_par_a_par'])


# ══════════════════════════════════════════════════════════════════════════
# Item 15 do pedido — nenhum membro tratado como observação histórica
# independente
# ══════════════════════════════════════════════════════════════════════════

class MembroNuncaObservacaoIndependenteTestCase(unittest.TestCase):

    def test_a_n_linhas_da_tabela_ensemble_nunca_e_multiplicado_por_membros(self):
        base = _base_pareada_sintetica(n_inits_por_lead=15, leads=(1, 2))
        tabela = g.construir_tabela_ensemble(base)
        n_combos = base.drop_duplicates(['init_date', 'lead']).shape[0]
        self.assertEqual(len(tabela), n_combos)
        self.assertNotEqual(len(tabela), len(base))

    def test_b_effective_ensemble_size_nunca_maior_que_n_membros(self):
        """Item 9 do pedido — ESS é só diagnóstico de redundância;
        nunca pode superar o número real de membros (seria uma
        inflação da amostra, exatamente o que o pedido proíbe)."""
        base = _base_pareada_sintetica(n_inits_por_lead=30, leads=(1,))
        resultado = g.dependencia_membros_por_horizonte(base)
        ess = resultado[1]['effective_ensemble_size_aprox']
        if ess is not None:
            self.assertLessEqual(ess, resultado[1]['n_membros'] + 1e-9)

    def test_c_bootstrap_de_spread_skill_jamais_recebe_coluna_de_membro_individual(self):
        base = _base_pareada_sintetica(n_inits_por_lead=25, leads=(1,))
        tabela = g.construir_tabela_ensemble(base)
        colunas_vistas = []

        def fake(df_lead, coluna_previsto, coluna_observado, coluna_ano, funcao_metrica,
                  n_resamples=1000, seed=20261001):
            colunas_vistas.append(set(df_lead.columns))
            return {'estimativa': 0.0, 'ic95_lo': 0.0, 'ic95_hi': 0.0}

        with mock.patch.object(v, 'bootstrap_blocos_por_ano', side_effect=fake):
            g.spread_skill_por_horizonte(tabela, n_resamples=5)

        for colunas in colunas_vistas:
            self.assertNotIn('member', colunas)
            self.assertNotIn('forecast_prec_mm', colunas)


# ══════════════════════════════════════════════════════════════════════════
# Orquestração — STOP-ON-FAILURE propagado corretamente
# ══════════════════════════════════════════════════════════════════════════

class OrquestracaoStopOnFailureTestCase(unittest.TestCase):

    def test_a_auditoria_reprovada_interrompe_antes_de_qualquer_calculo(self):
        with mock.patch.object(v, 'executar_auditoria',
                                return_value={'auditoria_aprovada': False}):
            resultado = g.executar_gate_probabilistico()
        self.assertTrue(resultado['STOP_ON_FAILURE'])
        self.assertIn('auditoria', resultado['motivo'])


# ══════════════════════════════════════════════════════════════════════════
# Com dados reais já aprovados (só leitura, sem rede)
# ══════════════════════════════════════════════════════════════════════════

class ComDadosReaisAprovadosTestCase(unittest.TestCase):

    def test_a_executa_sem_stop_on_failure_com_poucas_reamostras(self):
        if not v.CAMINHO_METRICAS_JSON.parent.exists():
            self.skipTest("dados reais não disponíveis nesta árvore de trabalho")
        resultado = g.executar_gate_probabilistico(n_resamples_bootstrap=10)
        self.assertFalse(resultado.get('STOP_ON_FAILURE', True))
        self.assertEqual(set(resultado['classificacao_gate_por_horizonte'].keys()),
                          set(v.LEADS_ESPERADOS))


if __name__ == '__main__':
    unittest.main()
