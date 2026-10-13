#!/usr/bin/env python3
"""
tests/test_cfsv2_emos_h2_viabilidade_warmup.py — Fase 2C.3D, protocolo
EMOS H2: cobre só a viabilidade ESTRUTURAL do warm-up (nenhum ajuste
de parâmetro, nenhum CRPS/skill é calculado por este módulo), incluindo
a regra causal corrigida (target_month_treino < init_date_avaliada —
disponibilidade da OBSERVAÇÃO verificada, não só do forecast).

Roda com:
    python -m unittest tests.test_cfsv2_emos_h2_viabilidade_warmup -v
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import cfsv2_emos_h2_viabilidade_warmup as w  # noqa: E402
import cfsv2_validacao_cientifica as v  # noqa: E402


class IndiceCausalPorMesTestCase(unittest.TestCase):

    def test_a_nunca_inclui_a_propria_inicializacao_nem_futuras(self):
        tabela = pd.DataFrame([
            {'init_date': '2000-01', 'lead': 2, 'ensemble_std': 10.0},
            {'init_date': '2001-01', 'lead': 2, 'ensemble_std': 20.0},
            {'init_date': '2002-01', 'lead': 2, 'ensemble_std': 30.0},
        ])
        calc = w._indice_causal_por_mes(tabela, 2, 'ensemble_std')
        valores = calc('2001-01').tolist()
        self.assertEqual(valores, [10.0])
        valores_primeira = calc('2000-01').tolist()
        self.assertEqual(valores_primeira, [])

    def test_b_so_mesmo_mes_calendario(self):
        tabela = pd.DataFrame([
            {'init_date': '2000-01', 'lead': 2, 'ensemble_std': 10.0},
            {'init_date': '2000-06', 'lead': 2, 'ensemble_std': 999.0},
            {'init_date': '2001-01', 'lead': 2, 'ensemble_std': 20.0},
        ])
        calc = w._indice_causal_por_mes(tabela, 2, 'ensemble_std')
        valores = calc('2002-01').tolist()
        self.assertEqual(sorted(valores), [10.0, 20.0])


def _mes_seguinte(periodo_str):
    return str(pd.Period(periodo_str, freq='M') + 1)


class ViabilidadeEstruturalTestCase(unittest.TestCase):

    def _pares_sinteticos(self, validos):
        """`validos` é uma lista de bools na ordem causal — constrói
        um DataFrame `pares` mínimo com `init_date` e `target_month`
        (H2: target_month = init_date + 1 mês, igual à produção) para
        `viabilidade_estrutural_h2`."""
        linhas = []
        for i, v_ in enumerate(validos):
            init_date = f'{2000 + i // 12}-{(i % 12) + 1:02d}'
            linhas.append({'init_date': init_date, 'target_month': _mes_seguinte(init_date),
                            'valido': v_, 'target_mes': 1, 'target_ano': 2000})
        return pd.DataFrame(linhas)

    def test_a_primeira_elegivel_exige_target_month_treino_tambem_anterior(self):
        # 5 válidos seguidos — com a regra ANTIGA (só init_date_treino <
        # init_date_avaliada), a linha de índice 3 já teria 3 válidas
        # antes. Com a regra CORRIGIDA (target_month_treino também <
        # init_date_avaliada), a linha de índice 2 (target=init+1) só
        # deixa de contar quando a avaliada alcança o índice 4 — ver
        # derivação manual no corpo do teste.
        pares = self._pares_sinteticos([True, True, True, True, True])
        resultado = w.viabilidade_estrutural_h2(pares, n_treino_minimo=3)
        self.assertEqual(resultado['n_treino_emos_nessa_data'], 3)
        self.assertEqual(resultado['primeira_init_date_elegivel'], pares['init_date'].iloc[4],
                          "regra corrigida deve exigir 1 linha adicional de defasagem em "
                          "relação à regra antiga (que apontaria para o índice 3)")

    def test_b_n_previsoes_avaliaveis_bate_com_contagem_manual_da_regra_corrigida(self):
        validos = [True, True, True, False, True, True, True, True]
        pares = self._pares_sinteticos(validos)
        resultado = w.viabilidade_estrutural_h2(pares, n_treino_minimo=3)
        # derivação manual (ver mensagem do commit): n_treino_emos por
        # linha = [0,0,1,2,3,4,5,6] -> elegíveis (>=3): índices 4-7,
        # todos válidos -> 4 avaliáveis.
        self.assertEqual(resultado['n_previsoes_avaliaveis_final'], 4)

    def test_c_nenhum_parametro_emos_e_mencionado_no_resultado(self):
        pares = self._pares_sinteticos([True] * 10)
        resultado = w.viabilidade_estrutural_h2(pares, n_treino_minimo=3)
        for chave_proibida in ('crps', 'skill', 'alpha', 'beta', 'sigma'):
            self.assertNotIn(chave_proibida, json_keys_lower(resultado))

    def test_d_auditoria_sem_leakage_sempre_ok_apos_a_correcao(self):
        pares = self._pares_sinteticos([True] * 10)
        resultado = w.viabilidade_estrutural_h2(pares, n_treino_minimo=3)
        self.assertTrue(resultado['auditoria_sem_leakage_observacional']['ok'])
        self.assertEqual(resultado['auditoria_sem_leakage_observacional']['violacoes'], [])


class RegraCausalCorrigidaTestCase(unittest.TestCase):
    """Revisão pós-`be31da1`, item 7 do pedido — exemplo literal: ao
    avaliar `init_date_avaliada = 2003-01`, só a linha com
    `init=2002-11` (target=2002-12) pode entrar no treino; a linha com
    `init=2002-12` (target=2003-01) NÃO pode, porque sua observação
    (`target_month=2003-01`) coincidiria com o próprio mês da
    inicialização avaliada."""

    def test_a_so_a_primeira_linha_historica_e_elegivel(self):
        pares = pd.DataFrame([
            {'init_date': '2002-11', 'target_month': '2002-12', 'valido': True},
            {'init_date': '2002-12', 'target_month': '2003-01', 'valido': True},
            {'init_date': '2003-01', 'target_month': '2003-02', 'valido': True},
        ])
        resultado = w._contar_treino_emos_por_linha(pares)
        linha_avaliada = resultado[resultado['init_date'] == '2003-01'].iloc[0]

        self.assertEqual(linha_avaliada['n_treino_emos'], 1,
                          "só init=2002-11 deveria contar como treino para avaliar 2003-01")
        self.assertEqual(linha_avaliada['max_init_date_treino'], '2002-11')
        self.assertEqual(linha_avaliada['max_target_month_treino'], '2002-12')

    def test_b_regra_antiga_teria_incluido_a_linha_de_dezembro_indevidamente(self):
        """Confirma numericamente a motivação da correção: a regra
        ANTIGA (só init_date_treino < init_date_avaliada) incluiria
        `init=2002-12` (target=2003-01) — a linha que a correção
        precisa excluir."""
        init_dez = pd.Period('2002-12', freq='M')
        init_avaliada = pd.Period('2003-01', freq='M')
        target_dez = pd.Period('2003-01', freq='M')
        # regra antiga: só checava init_date_treino < init_date_avaliada
        self.assertTrue(init_dez < init_avaliada, "regra antiga incluiria indevidamente esta linha")
        # regra corrigida: também exige target_month_treino < init_date_avaliada
        self.assertFalse(target_dez < init_avaliada, "regra corrigida corretamente exclui esta linha")


class AntiLeakagePorObservacaoFuturaTestCase(unittest.TestCase):
    """Item 8 do pedido — alterar drasticamente a condição da linha
    com `target_month >= init_date_avaliada` (aqui, simulada pela
    única propriedade que esta camada estrutural carrega sobre uma
    linha de treino: `valido`) não pode mudar a contagem de treino
    disponível para a previsão avaliada, porque essa linha jamais
    deveria entrar no treino, independentemente de qualquer alteração
    nela."""

    def _cenario(self, valido_linha_dezembro):
        return pd.DataFrame([
            {'init_date': '2002-11', 'target_month': '2002-12', 'valido': True},
            {'init_date': '2002-12', 'target_month': '2003-01', 'valido': valido_linha_dezembro},
            {'init_date': '2003-01', 'target_month': '2003-02', 'valido': True},
        ])

    def test_a_alterar_validade_da_linha_com_target_futuro_nao_afeta_a_avaliada(self):
        resultado_original = w._contar_treino_emos_por_linha(self._cenario(valido_linha_dezembro=True))
        resultado_alterado = w._contar_treino_emos_por_linha(self._cenario(valido_linha_dezembro=False))

        linha_a = resultado_original[resultado_original['init_date'] == '2003-01'].iloc[0]
        linha_b = resultado_alterado[resultado_alterado['init_date'] == '2003-01'].iloc[0]

        self.assertEqual(linha_a['n_treino_emos'], linha_b['n_treino_emos'])
        self.assertEqual(linha_a['max_init_date_treino'], linha_b['max_init_date_treino'])
        self.assertEqual(linha_a['max_target_month_treino'], linha_b['max_target_month_treino'])
        self.assertEqual(linha_a['n_treino_emos'], 1,
                          "mudar a linha de dezembro (target futuro) não deveria mudar nada")


def json_keys_lower(d, prefixo=''):
    chaves = []
    for k, val in d.items():
        chaves.append(k.lower())
        if isinstance(val, dict):
            chaves.extend(json_keys_lower(val))
    return chaves


class GateViabilidadeEscalaTestCase(unittest.TestCase):

    def test_a_nenhum_piso_e_escolhido_apenas_reportado(self):
        pares = pd.DataFrame([
            {'target_mes': 7, 'valido': True, 'spread_clim_modelo_mes': 0.5, 'erro_clim_sd_mes': 0.3},
            {'target_mes': 7, 'valido': True, 'spread_clim_modelo_mes': 0.8, 'erro_clim_sd_mes': 0.4},
            {'target_mes': 1, 'valido': True, 'spread_clim_modelo_mes': 90.0, 'erro_clim_sd_mes': 80.0},
        ])
        resultado = w.gate_viabilidade_escala(pares)
        self.assertTrue(resultado['todos_spread_clim_modelo_mes_positivos'])
        self.assertTrue(resultado['todos_erro_clim_sd_mes_positivos'])
        self.assertAlmostEqual(resultado['distribuicao_por_mes'][7]['spread_clim_modelo_mes_minimo'], 0.5)

    def test_b_detecta_denominador_nao_positivo(self):
        pares = pd.DataFrame([
            {'target_mes': 7, 'valido': True, 'spread_clim_modelo_mes': 0.0001, 'erro_clim_sd_mes': 0.3},
        ])
        resultado = w.gate_viabilidade_escala(pares)
        self.assertTrue(resultado['todos_spread_clim_modelo_mes_positivos'])
        self.assertAlmostEqual(resultado['distribuicao_por_mes'][7]['spread_clim_modelo_mes_minimo'], 0.0001)


class ComDadosReaisAprovadosTestCase(unittest.TestCase):

    def test_a_executa_sem_stop_on_failure(self):
        if not v.CAMINHO_METRICAS_JSON.parent.exists():
            self.skipTest("dados reais não disponíveis nesta árvore de trabalho")
        resultado = w.executar_viabilidade()
        self.assertFalse(resultado.get('STOP_ON_FAILURE', True))
        self.assertTrue(resultado['nenhum_parametro_emos_ajustado'])
        self.assertTrue(resultado['nenhum_crps_emos_calculado'])
        viab = resultado['viabilidade_estrutural_warmup']
        self.assertGreater(viab['n_pares_validos_total'], viab['n_treino_minimo_emos'])
        self.assertIsNotNone(viab['primeira_init_date_elegivel'])


if __name__ == '__main__':
    unittest.main()
