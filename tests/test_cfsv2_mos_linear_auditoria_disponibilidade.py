#!/usr/bin/env python3
"""
tests/test_cfsv2_mos_linear_auditoria_disponibilidade.py — Fase 2C.3D:
auditoria e correção da disponibilidade observacional no treino do
Método 3.4 (MOS linear).

Cobre: (1) a função pura `_indices_treino_causal` com o exemplo literal
H2 e um exemplo H6 com vários empréstimos recentes todos excluídos;
(2) o teste de mutação por observação futura (item 14 do pedido) —
alterar a observação de uma linha com `target_month >= init_date_
avaliada` nunca pode mudar alpha/beta/forecast_mos de uma avaliação
passada; (3) a determinação explícita (nunca assumida) de que H1 não é
afetado pela correção — controle negativo da auditoria; (4) smoke test
do script de auditoria pura contra dados sintéticos e, se disponíveis,
reais.

Roda com:
    python -m unittest tests.test_cfsv2_mos_linear_auditoria_disponibilidade -v
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import cfsv2_auditoria_mos_disponibilidade as aud  # noqa: E402
import cfsv2_calibracao_mos_linear as mos  # noqa: E402
import cfsv2_validacao_cientifica as v  # noqa: E402


def _linha(init_date, lead, target_mes=None, forecast=100.0, obs=80.0,
           clim_media=70.0, clim_modelo=90.0):
    target_p = v._periodo(init_date) + (lead - 1)
    return {
        'init_date': init_date, 'target_month': str(target_p), 'target_ano': target_p.year,
        'target_mes': target_mes if target_mes is not None else target_p.month,
        'lead': lead, 'member': 1, 'forecast_prec_mm': forecast, 'obs_prec_mm': obs,
        'clim_media': clim_media, 'clim_modelo_media': clim_modelo,
    }


def _serie_valida(n, lead, mes_inicial=1, ano_inicial=1990, forecast_fn=None, obs_fn=None):
    forecast_fn = forecast_fn or (lambda i: 100.0 + i)
    obs_fn = obs_fn or (lambda i: 80.0 + 0.3 * i)
    linhas = []
    for i in range(n):
        mes = ((mes_inicial - 1 + i) % 12) + 1
        ano = ano_inicial + (mes_inicial - 1 + i) // 12
        linhas.append(_linha(f'{ano}-{mes:02d}', lead, mes, forecast=forecast_fn(i),
                              obs=obs_fn(i)))
    return linhas


class RegraCausalCorrigidaLiteralTestCase(unittest.TestCase):
    """Item 13 do pedido — exemplos literais, não derivados de dados
    reais, testando diretamente `mos._indices_treino_causal`."""

    def test_a_h2_2003_01_exemplo_literal_do_pedido(self):
        """H2, avaliando 2003-01: init=2002-11 (target=2002-12) é
        permitido; init=2002-12 (target=2003-01) é proibido (o próprio
        mês avaliado ainda não foi observado)."""
        inits_p = [v._periodo('2002-11'), v._periodo('2002-12')]
        targets_p = [v._periodo('2002-12'), v._periodo('2003-01')]
        avaliada_p = v._periodo('2003-01')
        idx = mos._indices_treino_causal(inits_p, targets_p, avaliada_p)
        self.assertEqual(idx, [0], "só o índice 0 (init=2002-11) deveria ser elegível")

    def test_b_h6_varios_empréstimos_recentes_todos_excluidos(self):
        """H6 (lead=6, target_month=init_date+5): avaliando 2010-06,
        os 5 inits mais recentes (2010-01 a 2010-05) têm todos
        target_month >= 2010-06 — devem ser TODOS excluídos — só o
        init de 2009-12 (target=2010-05, < avaliada) é elegível."""
        lead = 6
        inits = ['2009-12', '2010-01', '2010-02', '2010-03', '2010-04', '2010-05']
        inits_p = [v._periodo(d) for d in inits]
        targets_p = [v._periodo(d) + (lead - 1) for d in inits_p]
        avaliada_p = v._periodo('2010-06')

        # confirma, por construção, que os 5 mais recentes de fato têm
        # target_month >= avaliada (senão o teste não demonstraria nada)
        for ip, tp in list(zip(inits_p, targets_p))[1:]:
            self.assertGreaterEqual(tp, avaliada_p)
        self.assertLess(targets_p[0], avaliada_p)

        idx = mos._indices_treino_causal(inits_p, targets_p, avaliada_p)
        self.assertEqual(idx, [0], "só init=2009-12 deveria ser elegível para avaliar 2010-06 "
                                    "em H6 — os 5 inits mais recentes têm observação-alvo ainda "
                                    "não verificada")

    def test_c_regra_antiga_incluiria_indevidamente_os_mesmos_casos(self):
        """Confirma que a regra ANTIGA (só init_date_treino <
        avaliada, sem checar target_month) de fato incluiria as linhas
        que a regra corrigida exclui — a demonstração de que a
        correção muda o comportamento real, não só adiciona uma
        checagem inofensiva."""
        lead = 6
        inits = ['2009-12', '2010-01', '2010-02', '2010-03', '2010-04', '2010-05']
        inits_p = [v._periodo(d) for d in inits]
        avaliada_p = v._periodo('2010-06')
        idx_regra_antiga = [i for i, ip in enumerate(inits_p) if ip < avaliada_p]
        self.assertEqual(idx_regra_antiga, [0, 1, 2, 3, 4, 5],
                          "a regra antiga incluiria TODOS os 6 — a corrigida só o índice 0")


class MutacaoObservacaoFuturaTestCase(unittest.TestCase):
    """Item 14 do pedido — alterar drasticamente a observação de uma
    linha cujo target_month >= init_date_avaliada NUNCA pode mudar
    alpha/beta/forecast_mos de uma avaliação passada. Construído para
    que a linha mutada seja EXATAMENTE o tipo de linha que a regra
    antiga incluiria indevidamente (init_date_treino < avaliada, mas
    target_month_treino >= avaliada) — a demonstração mais direta
    possível do anti-leakage real."""

    def test_a_mutar_observacao_da_linha_imediatamente_anterior_nao_muda_avaliacao_mais_recente(self):
        lead = 2
        n = 125
        linhas = _serie_valida(n, lead=lead, forecast_fn=lambda i: 100.0 + 0.5 * i,
                                obs_fn=lambda i: 80.0 + 0.3 * i)
        base_antes = pd.DataFrame(linhas)
        tabela_antes = mos.construir_tabela_mos_linear(base_antes)
        # avaliação ESCOLHIDA: a última da série — sua janela de
        # treino (regra antiga) incluiria TODAS as 124 linhas
        # anteriores, entre elas a penúltima (índice n-2), cujo
        # target_month = init_date+1 == init_date desta própria
        # avaliação — "passado" só pela métrica errada (init_date),
        # nunca pela métrica certa (target_month).
        avaliacao_escolhida = tabela_antes.sort_values('init_date').iloc[-1].copy()
        self.assertEqual(avaliacao_escolhida['status_mos'], mos.STATUS_OK)
        self.assertEqual(avaliacao_escolhida['init_date'], linhas[-1]['init_date'])

        linhas_mutadas = [dict(linha) for linha in linhas]
        linhas_mutadas[-2]['obs_prec_mm'] = -999999.0
        base_depois = pd.DataFrame(linhas_mutadas)
        tabela_depois = mos.construir_tabela_mos_linear(base_depois)
        avaliacao_depois = tabela_depois[
            tabela_depois['init_date'] == avaliacao_escolhida['init_date']].iloc[0]

        self.assertEqual(avaliacao_depois['status_mos'], mos.STATUS_OK)
        self.assertAlmostEqual(avaliacao_escolhida['alpha'], avaliacao_depois['alpha'], places=9)
        self.assertAlmostEqual(avaliacao_escolhida['beta'], avaliacao_depois['beta'], places=9)
        self.assertAlmostEqual(avaliacao_escolhida['forecast_mos'], avaliacao_depois['forecast_mos'],
                                places=9)
        self.assertEqual(avaliacao_escolhida['n_treino_mos'], avaliacao_depois['n_treino_mos'])

    def test_b_regra_antiga_simulada_teria_sido_afetada_pela_mesma_mutacao(self):
        """Contraprova: reproduzindo a regra ANTIGA (sem exigir
        target_month) sobre os mesmos dados, a mesma mutação MUDA o
        treino da avaliação escolhida (a última da série) — prova que
        o teste `a` está de fato exercitando a correção, não uma
        situação onde a mutação nunca importaria por outro motivo."""
        lead = 2
        n = 125
        linhas = _serie_valida(n, lead=lead, forecast_fn=lambda i: 100.0 + 0.5 * i,
                                obs_fn=lambda i: 80.0 + 0.3 * i)

        def treino_regra_antiga(linhas_lista, idx_avaliada):
            avaliada_p = v._periodo(linhas_lista[idx_avaliada]['init_date'])
            xs, ys = [], []
            for linha in linhas_lista:
                ip = v._periodo(linha['init_date'])
                if ip < avaliada_p:
                    clim_mod, clim_obs = linha['clim_modelo_media'], linha['clim_media']
                    xs.append(linha['forecast_prec_mm'] - clim_mod)
                    ys.append(linha['obs_prec_mm'] - clim_obs)
            return xs, ys

        # a avaliação escolhida é a ÚLTIMA da série (mesma de `a`)
        idx_avaliada = n - 1
        xs_antes, ys_antes = treino_regra_antiga(linhas, idx_avaliada)

        linhas_mutadas = [dict(linha) for linha in linhas]
        linhas_mutadas[-2]['obs_prec_mm'] = -999999.0
        xs_depois, ys_depois = treino_regra_antiga(linhas_mutadas, idx_avaliada)

        self.assertEqual(xs_antes, xs_depois, "x não deveria mudar (só a observação foi mutada)")
        self.assertNotEqual(ys_antes, ys_depois, "a regra ANTIGA deveria ter incluído a linha "
                                                   "mutada no treino desta avaliação — se não "
                                                   "mudou, o teste não está comparando o que "
                                                   "deveria")


class H1NaoAfetadoTestCase(unittest.TestCase):
    """Item 15 do pedido — determinar EXPLICITAMENTE (nunca assumir)
    se H1 é afetado pela correção. Para lead=1, target_month ==
    init_date por construção (H1 — mês corrente), então as duas
    condições da regra corrigida colapsam numa só, idêntica à regra
    antiga — confirmado aqui tanto sinteticamente quanto (se
    disponível) na base real, e registrado como controle negativo útil
    da auditoria."""

    def test_a_sintetico_regra_antiga_e_corrigida_coincidem_em_h1(self):
        linhas = _serie_valida(130, lead=1, forecast_fn=lambda i: 100.0 + 0.5 * i,
                                obs_fn=lambda i: 80.0 + 0.3 * i)
        for linha in linhas:
            self.assertEqual(linha['target_month'], linha['init_date'],
                              "pré-condição do teste: H1 precisa ter target_month==init_date")
        base = pd.DataFrame(linhas)
        tabela = mos.construir_tabela_mos_linear(base)
        ok = tabela[tabela['status_mos'] == mos.STATUS_OK]
        self.assertGreater(len(ok), 0)
        for _, row in ok.iterrows():
            self.assertEqual(row['periodo_treino_fim'], row['max_target_month_treino'],
                              "em H1, o fim da janela de treino por init_date e por "
                              "target_month têm que coincidir exatamente")

    def test_b_dados_reais_auditoria_confirma_zero_inclusoes_indevidas_em_h1(self):
        if not aud.DIRETORIO_SAIDA.exists():
            self.skipTest("dados reais da 2C.3C não disponíveis nesta árvore de trabalho")
        resultado = aud.auditar_disponibilidade_observacional_mos()
        self.assertFalse(resultado.get('STOP_ON_FAILURE', True), resultado.get('motivo'))
        resumo_h1 = resultado['resumo_por_horizonte'][1]
        self.assertEqual(resumo_h1['inclusoes_indevidas_acumuladas_total'], 0)
        self.assertEqual(resumo_h1['n_previsoes_afetadas'], 0)
        self.assertEqual(resumo_h1['teto_esperado_por_avaliacao_lead_menos_1'], 0)


class AuditoriaPuraTestCase(unittest.TestCase):
    """Smoke test do script de auditoria (item 1-3 do pedido) — nunca
    escreve nenhum artefato do Método 3.4, só o próprio JSON de
    auditoria."""

    def test_a_auditoria_real_sem_stop_on_failure_e_dentro_do_teto_esperado(self):
        if not aud.DIRETORIO_SAIDA.exists():
            self.skipTest("dados reais da 2C.3C não disponíveis nesta árvore de trabalho")
        resultado = aud.auditar_disponibilidade_observacional_mos()
        self.assertFalse(resultado.get('STOP_ON_FAILURE', True), resultado.get('motivo'))
        for lead in v.LEADS_ESPERADOS:
            r = resultado['resumo_por_horizonte'][lead]
            self.assertTrue(r['dentro_do_teto_esperado'], r)
            self.assertLessEqual(r['inclusoes_indevidas_max_por_avaliacao'],
                                  aud.TETO_ESPERADO_POR_LEAD[lead])

    def test_b_padrao_estrutural_h1_a_h6_bate_com_a_expectativa_de_auditoria(self):
        """Item 3 do pedido — o padrão NÃO é hardcoded na implementação
        (só usado aqui, no teste, para comparar com o que a auditoria
        REALMENTE computou a partir dos dados)."""
        if not aud.DIRETORIO_SAIDA.exists():
            self.skipTest("dados reais da 2C.3C não disponíveis nesta árvore de trabalho")
        resultado = aud.auditar_disponibilidade_observacional_mos()
        self.assertFalse(resultado.get('STOP_ON_FAILURE', True), resultado.get('motivo'))
        resumo = resultado['resumo_por_horizonte']
        for lead in v.LEADS_ESPERADOS:
            teto = lead - 1
            self.assertEqual(resumo[lead]['teto_esperado_por_avaliacao_lead_menos_1'], teto)
            self.assertLessEqual(resumo[lead]['inclusoes_indevidas_max_por_avaliacao'], teto)


if __name__ == '__main__':
    unittest.main()
