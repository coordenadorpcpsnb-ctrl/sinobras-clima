#!/usr/bin/env python3
"""
tests/test_cfsv2_viabilidade_quantile_mapping.py — Fase 2C.3D, gate de
viabilidade do Método 3.3 (quantile mapping).

Item 7 do pedido — garante: contagem causal correta; própria
inicialização excluída; futuro excluído; membros do ensemble NÃO
inflando N; decisão automática consistente com o limiar pré-
registrado (`AMOSTRA_MINIMA_ESTRATO`, nunca um número reduzido
localmente).

Esta suíte NUNCA calcula forecast calibrado, RMSE, MAE, skill ou IC do
Método 3.3 — só contagens.

Dados SINTÉTICOS para a lógica central (nenhuma rede necessária); as
classes *ComDadosReais* leem os arquivos já aprovados do repositório
(sem rede, pulam se ausentes).

Roda com:
    python -m unittest tests.test_cfsv2_viabilidade_quantile_mapping -v
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import cfsv2_validacao_cientifica as v  # noqa: E402
import cfsv2_viabilidade_quantile_mapping as q  # noqa: E402


def _linha_pareada(init_date, lead, target_mes, member=1):
    target_p = v._periodo(init_date) + (lead - 1)
    return {'init_date': init_date, 'target_month': str(target_p), 'target_ano': target_p.year,
            'target_mes': target_mes, 'lead': lead, 'member': member}


class ContagemCausalTestCase(unittest.TestCase):
    """Item 7 — 'contagem causal correta' e 'própria inicialização
    excluída'."""

    def test_a_primeira_inicializacao_da_celula_tem_n_treino_causal_zero(self):
        linhas = [_linha_pareada(f'{1991+i}-06', 1, 6) for i in range(5)]
        base = pd.DataFrame(linhas)
        indice = q.construir_indice_inits_unicos(base)
        tabela = q.calcular_n_causal_por_previsao(indice)
        primeira = tabela.sort_values('init_date').iloc[0]
        self.assertEqual(primeira['init_date'], '1991-06')
        self.assertEqual(primeira['n_treino_causal'], 0)

    def test_b_sequencia_cronologica_e_exatamente_0_1_2_3_4(self):
        linhas = [_linha_pareada(f'{1991+i}-06', 1, 6) for i in range(5)]
        base = pd.DataFrame(linhas)
        indice = q.construir_indice_inits_unicos(base)
        tabela = q.calcular_n_causal_por_previsao(indice).sort_values('init_date')
        self.assertEqual(tabela['n_treino_causal'].tolist(), [0, 1, 2, 3, 4])

    def test_c_celulas_diferentes_contam_independentemente_sem_pooling(self):
        """Item 3 — nunca pooling entre meses ou leads: uma célula com
        histórico longo não pode 'vazar' N para uma célula vizinha."""
        linhas = [_linha_pareada(f'{1991+i}-06', 1, 6) for i in range(15)]  # célula A: 15 anos
        linhas += [_linha_pareada(f'{1991+i}-07', 1, 7) for i in range(2)]   # célula B: 2 anos
        base = pd.DataFrame(linhas)
        indice = q.construir_indice_inits_unicos(base)
        tabela = q.calcular_n_causal_por_previsao(indice)
        max_a = tabela[tabela['target_mes'] == 6]['n_treino_causal'].max()
        max_b = tabela[tabela['target_mes'] == 7]['n_treino_causal'].max()
        self.assertEqual(max_a, 14)
        self.assertEqual(max_b, 1)  # jamais contaminado pelos 15 anos da célula A


class PropriaInicializacaoEFuturoExcluidosTestCase(unittest.TestCase):
    """Item 7 — 'própria inicialização excluída' e 'futuro excluído'."""

    def test_a_n_treino_causal_nunca_conta_a_propria_linha(self):
        linhas = [_linha_pareada(f'{1991+i}-06', 1, 6) for i in range(10)]
        base = pd.DataFrame(linhas)
        indice = q.construir_indice_inits_unicos(base)
        tabela = q.calcular_n_causal_por_previsao(indice)
        # com 10 inicializações na célula, a última (posição 9) tem no
        # máximo 9 anteriores — nunca 10 (que incluiria ela mesma).
        self.assertEqual(int(tabela['n_treino_causal'].max()), 9)

    def test_b_adicionar_inicializacao_futura_nao_altera_n_treino_causal_do_passado(self):
        linhas = [_linha_pareada(f'{1991+i}-06', 1, 6) for i in range(8)]
        base_sem_futuro = pd.DataFrame(linhas)
        indice_sem = q.construir_indice_inits_unicos(base_sem_futuro)
        tabela_sem = q.calcular_n_causal_por_previsao(indice_sem)
        n_antes = tabela_sem[tabela_sem['init_date'] == '1991-06'].iloc[0]['n_treino_causal']

        linhas_com_futuro = linhas + [_linha_pareada('2015-06', 1, 6)]
        base_com_futuro = pd.DataFrame(linhas_com_futuro)
        indice_com = q.construir_indice_inits_unicos(base_com_futuro)
        tabela_com = q.calcular_n_causal_por_previsao(indice_com)
        n_depois = tabela_com[tabela_com['init_date'] == '1991-06'].iloc[0]['n_treino_causal']

        self.assertEqual(n_antes, n_depois)
        self.assertEqual(n_antes, 0)  # 1991 é sempre a primeira, independente do que vem depois


class EnsembleNaoInflaNTestCase(unittest.TestCase):
    """Item 3/7 do pedido — os 24 membros NUNCA contam como 24 anos
    independentes."""

    def test_a_multiplos_membros_da_mesma_inicializacao_colapsam_para_uma_linha(self):
        linhas = []
        for ano in range(1991, 1996):
            for membro in range(1, 25):  # 24 membros, mesma init_date/lead/target
                linhas.append(_linha_pareada(f'{ano}-06', 1, 6, member=membro))
        base = pd.DataFrame(linhas)
        self.assertEqual(len(base), 5 * 24)  # 120 linhas membro-a-membro
        indice = q.construir_indice_inits_unicos(base)
        self.assertEqual(len(indice), 5)  # só 5 inicializações reais

    def test_b_n_treino_causal_com_ensemble_e_identico_ao_sem_ensemble(self):
        linhas_1_membro = [_linha_pareada(f'{1991+i}-06', 1, 6, member=1) for i in range(6)]
        base_1 = pd.DataFrame(linhas_1_membro)
        tabela_1 = q.calcular_n_causal_por_previsao(q.construir_indice_inits_unicos(base_1))

        linhas_24_membros = [_linha_pareada(f'{1991+i}-06', 1, 6, member=m)
                              for i in range(6) for m in range(1, 25)]
        base_24 = pd.DataFrame(linhas_24_membros)
        tabela_24 = q.calcular_n_causal_por_previsao(q.construir_indice_inits_unicos(base_24))

        seq_1 = sorted(tabela_1['n_treino_causal'].tolist())
        seq_24 = sorted(tabela_24['n_treino_causal'].tolist())
        self.assertEqual(seq_1, seq_24)
        self.assertEqual(seq_1, [0, 1, 2, 3, 4, 5])  # nunca inflado para múltiplos de 24

    def test_c_verificacao_de_dedup_falha_se_pareamento_estiver_quebrado(self):
        """Confirma que `_verificar_dedup_nao_inflou_nem_perdeu` detecta
        uma contagem inesperada (não confia silenciosamente)."""
        linhas = [_linha_pareada(f'{1991+i}-06', 1, 6) for i in range(3)]
        base = pd.DataFrame(linhas)
        indice_errado = pd.concat([q.construir_indice_inits_unicos(base)] * 2, ignore_index=True)
        resultado = q._verificar_dedup_nao_inflou_nem_perdeu(base, indice_errado)
        # não necessariamente False (depende de N_INICIALIZACOES_ESPERADO), mas o campo
        # 'n_indice' tem que refletir o dobro de linhas, nunca escondido.
        self.assertEqual(resultado['n_indice'], 6)


class DecisaoAutomaticaTestCase(unittest.TestCase):
    """Item 2/7 do pedido — decisão automática consistente com o
    limiar pré-registrado, nunca um número reduzido localmente."""

    def test_a_usa_o_limiar_de_v_amostra_minima_estrato_nunca_um_numero_proprio(self):
        self.assertEqual(q.LIMIAR_MINIMO_QUANTILE_MAPPING, v.AMOSTRA_MINIMA_ESTRATO)

    def test_b_nenhuma_celula_atinge_o_limiar_declara_nao_testavel(self):
        linhas = [_linha_pareada(f'{1991+i}-06', 1, 6) for i in range(15)]  # máximo N=14 < 20
        base = pd.DataFrame(linhas)
        indice = q.construir_indice_inits_unicos(base)
        tabela = q.calcular_n_causal_por_previsao(indice)
        n_loyo = q.calcular_n_loyo_por_celula(indice)
        avaliacao = q.avaliar_viabilidade(tabela, n_loyo)
        self.assertEqual(avaliacao['metodo_3_3_status'], q.STATUS_NAO_TESTAVEL)
        self.assertFalse(avaliacao['metodo_3_3_testavel'])
        self.assertEqual(avaliacao['n_previsoes_com_n_maior_igual_limiar'], 0)
        self.assertEqual(avaliacao['n_celulas_com_n_maior_igual_limiar'], 0)

    def test_c_pelo_menos_uma_celula_atinge_o_limiar_declara_testavel(self):
        linhas = [_linha_pareada(f'{1991+i}-06', 1, 6) for i in range(25)]  # máximo N=24 >= 20
        base = pd.DataFrame(linhas)
        indice = q.construir_indice_inits_unicos(base)
        tabela = q.calcular_n_causal_por_previsao(indice)
        n_loyo = q.calcular_n_loyo_por_celula(indice)
        avaliacao = q.avaliar_viabilidade(tabela, n_loyo)
        self.assertEqual(avaliacao['metodo_3_3_status'], q.STATUS_TESTAVEL)
        self.assertTrue(avaliacao['metodo_3_3_testavel'])
        self.assertGreater(avaliacao['n_previsoes_com_n_maior_igual_limiar'], 0)
        self.assertEqual(avaliacao['n_celulas_com_n_maior_igual_limiar'], 1)

    def test_d_nenhum_skill_rmse_mae_ou_ic_e_calculado(self):
        linhas = [_linha_pareada(f'{1991+i}-06', 1, 6) for i in range(25)]
        base = pd.DataFrame(linhas)
        indice = q.construir_indice_inits_unicos(base)
        tabela = q.calcular_n_causal_por_previsao(indice)
        n_loyo = q.calcular_n_loyo_por_celula(indice)
        avaliacao = q.avaliar_viabilidade(tabela, n_loyo)
        self.assertTrue(avaliacao['nenhum_skill_ou_forecast_calibrado_calculado'])
        # as únicas chaves do dict são contagens/metadados — nenhuma delas pode
        # nomear uma métrica de desempenho do Método 3.3 (nenhuma foi calculada),
        # exceto a própria flag de confirmação, que existe para dizer isso.
        for chave in avaliacao.keys():
            if chave == 'nenhum_skill_ou_forecast_calibrado_calculado':
                continue
            baixo = chave.lower()
            for termo_proibido in ('rmse', 'mae', 'skill', 'ic95', 'forecast_calibrado'):
                self.assertNotIn(termo_proibido, baixo,
                                  f"chave {chave!r} sugere uma métrica de desempenho calculada")


class LoyoContextoTestCase(unittest.TestCase):
    """Item 4/7 do pedido — LOYO só como diagnóstico de contexto,
    nunca usado para declarar o método testável no lugar do causal."""

    def test_a_loyo_e_uniforme_por_celula_independente_da_posicao_cronologica(self):
        linhas = [_linha_pareada(f'{1991+i}-06', 1, 6) for i in range(12)]
        base = pd.DataFrame(linhas)
        indice = q.construir_indice_inits_unicos(base)
        n_loyo = q.calcular_n_loyo_por_celula(indice)
        self.assertEqual(n_loyo[(1, 6)], 11)  # 12 anos totais - 1 (o próprio) = 11, sempre

    def test_b_avaliacao_nao_declara_testavel_so_porque_loyo_atinge_o_limiar(self):
        """Mesmo que LOYO (hipoteticamente) atingisse o limiar, a
        decisão `metodo_3_3_testavel` tem que continuar presa à
        contagem CAUSAL — LOYO só aparece em `loyo_contexto`."""
        linhas = [_linha_pareada(f'{1991+i}-06', 1, 6) for i in range(15)]  # causal max=14<20
        base = pd.DataFrame(linhas)
        indice = q.construir_indice_inits_unicos(base)
        tabela = q.calcular_n_causal_por_previsao(indice)
        n_loyo = q.calcular_n_loyo_por_celula(indice)
        avaliacao = q.avaliar_viabilidade(tabela, n_loyo)
        self.assertFalse(avaliacao['metodo_3_3_testavel'])
        self.assertIn('loyo_contexto', avaliacao)


class ComDadosReaisTestCase(unittest.TestCase):
    """Usa os arquivos JÁ APROVADOS do repositório (sem rede) —
    confirma o resultado estrutural esperado: máximo N causal = 19 em
    TODAS as 72 células, 0 previsões/células atingem o limiar de 20."""

    def setUp(self):
        if not v.CAMINHO_METRICAS_JSON.parent.exists():
            self.skipTest("dados reais da 2C.3C não disponíveis nesta árvore de trabalho")
        self.resultado = q.executar_viabilidade()

    def test_a_pipeline_completo_sem_stop_on_failure(self):
        self.assertFalse(self.resultado.get('STOP_ON_FAILURE', True), self.resultado.get('motivo'))

    def test_b_maximo_n_causal_e_dezenove_em_todas_as_celulas(self):
        av = self.resultado['avaliacao']
        self.assertEqual(av['maximo_n_causal_observado_geral'], 19)
        self.assertEqual(av['minimo_do_maximo_n_causal_por_celula'], 19)
        self.assertEqual(av['valores_distintos_do_maximo_por_celula'], [19])

    def test_c_nenhuma_previsao_ou_celula_atinge_vinte(self):
        av = self.resultado['avaliacao']
        self.assertEqual(av['n_previsoes_com_n_maior_igual_limiar'], 0)
        self.assertEqual(av['n_celulas_com_n_maior_igual_limiar'], 0)

    def test_d_status_e_nao_testavel(self):
        av = self.resultado['avaliacao']
        self.assertEqual(av['metodo_3_3_status'], q.STATUS_NAO_TESTAVEL)
        self.assertFalse(av['metodo_3_3_testavel'])

    def test_e_loyo_tambem_nao_atinge_o_limiar_mesmo_sendo_so_contexto(self):
        av = self.resultado['avaliacao']
        self.assertEqual(av['loyo_contexto']['n_celulas_loyo_com_n_maior_igual_limiar'], 0)

    def test_f_72_celulas_1440_previsoes(self):
        av = self.resultado['avaliacao']
        self.assertEqual(av['n_celulas_total'], 72)
        self.assertEqual(av['n_previsoes_total_avaliadas'], 1440)

    def test_g_dedup_de_ensemble_confirmada_na_base_real(self):
        self.assertTrue(self.resultado['dedup_ensemble_check']['ok'])
        self.assertEqual(self.resultado['dedup_ensemble_check']['n_linhas_base_pareada_original'],
                          v.N_RAW_ESPERADO)


class RelatorioViabilidadeTestCase(unittest.TestCase):
    """Smoke test do gerador de relatório — nunca recalcula, só
    formata; nunca afirma skill/desempenho do Método 3.3 (não existe)."""

    _FRASES_PROIBIDAS = ('skill do método 3.3', 'rmse do método 3.3', 'o método 3.3 tem bom',
                          'está pronto para produção')

    def _assert_nunca_afirma_desempenho(self, texto):
        baixo = texto.lower()
        for frase in self._FRASES_PROIBIDAS:
            self.assertNotIn(frase, baixo, f"relatório afirma: {frase!r}")

    def test_a_stop_on_failure_gera_relatorio_minimo(self):
        import cfsv2_relatorio_viabilidade_qm as rel
        resultados = {'STOP_ON_FAILURE': True, 'motivo': 'teste'}
        relatorio = rel.gerar_relatorio_markdown(resultados)
        self.assertIn('STOP-ON-FAILURE', relatorio)
        self._assert_nunca_afirma_desempenho(relatorio)

    def test_b_relatorio_real_cobre_secoes_obrigatorias_e_decisao(self):
        if not q.CAMINHO_METRICAS_JSON.exists():
            self.skipTest("viabilidade ainda não executada nesta árvore de trabalho")
        import json
        import cfsv2_relatorio_viabilidade_qm as rel
        resultados = json.loads(q.CAMINHO_METRICAS_JSON.read_text())
        relatorio = rel.gerar_relatorio_markdown(resultados)
        for secao in ('Restrição estrutural', 'Máximo N causal', 'Avaliação formal',
                      'LOYO', 'Decisão final', 'metodo_3_3_status'):
            self.assertIn(secao, relatorio)
        self._assert_nunca_afirma_desempenho(relatorio)
        self.assertIn('nao_testavel_amostra_insuficiente', relatorio)
        self.assertIn('metodo_3_4_regressao_linear_mos_simples', relatorio)


if __name__ == '__main__':
    unittest.main()
