#!/usr/bin/env python3
"""
tests/test_cfsv2_diagnostico_multiplicativo.py — Fase 2C.3D, diagnóstico
PRÉVIO ao Método 3.2 (correção multiplicativa).

Esta suíte NUNCA testa um skill multiplicativo (nenhum existe). Foco:
(1) a população elegível carregada é EXATAMENTE a mesma do Método 3.1
(status_calibracao='ok', N=720=120×6 leads) — regra fixa do protocolo;
(2) o piso proposto cai num gap vazio, sem fragmentar nenhum (lead, mês);
(3) a razão nunca é computada como negativa nos dados reais aprovados;
(4) o relatório gerado nunca afirma um skill/conclusão de desempenho do
método multiplicativo, porque nenhum foi calculado.

Usa o arquivo JÁ APROVADO (`aditiva_expanding.csv`, Método 3.1) como
único dado real — lido, nunca escrito. Nenhuma rede é necessária.

Roda com:
    python -m unittest tests.test_cfsv2_diagnostico_multiplicativo -v
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import cfsv2_diagnostico_multiplicativo as d  # noqa: E402
import cfsv2_relatorio_diagnostico_multiplicativo as rel  # noqa: E402
import cfsv2_validacao_cientifica as v  # noqa: E402


# Frases que afirmariam uma conclusão de desempenho do método
# multiplicativo — nenhum skill foi calculado, então o relatório nunca
# pode conter nada parecido com isto.
_FRASES_PROIBIDAS = ('o método multiplicativo é melhor', 'supera o método aditivo',
                      'está pronto para produção', 'está validado')


class _BaseComArquivoAprovadoTestCase(unittest.TestCase):
    """Garante que o arquivo do Método 3.1 existe antes de qualquer
    teste desta classe — se não existir, os testes seriam falsos
    positivos silenciosos (puleriam tudo sem avisar)."""

    @classmethod
    def setUpClass(cls):
        if not d.CAMINHO_TABELA_ADITIVA_APROVADA.exists():
            raise unittest.SkipTest(
                f"{d.CAMINHO_TABELA_ADITIVA_APROVADA} não existe — Método 3.1 precisa "
                "estar presente no checkout para este diagnóstico ler (read-only).")
        cls.ok = d.carregar_base_elegivel()


class CarregarBaseElegivelTestCase(_BaseComArquivoAprovadoTestCase):

    def test_a_populacao_e_exatamente_a_do_metodo_aditivo(self):
        """Regra fixa do protocolo: 'avaliação principal nos mesmos
        casos elegíveis do método aditivo' — N=720=120×6 leads."""
        self.assertEqual(len(self.ok), 720)
        self.assertEqual(set(self.ok['status_calibracao'].unique()), {'ok'})
        self.assertEqual(self.ok.groupby('lead').size().to_dict(),
                          {lead: 120 for lead in v.LEADS_ESPERADOS})

    def test_b_climatologias_sao_as_ja_aprovadas_sem_recalculo(self):
        """climatologia_observada/climatologia_modelo_raw devem vir
        intactas da tabela já aprovada — esta função nunca recalcula
        nenhuma climatologia, só lê."""
        for col in ('climatologia_observada', 'climatologia_modelo_raw'):
            self.assertIn(col, self.ok.columns)
            self.assertTrue((self.ok[col] > 0).all(), f"{col} tem valor <= 0")

    def test_c_razao_e_a_divisao_direta_sem_nenhum_ajuste(self):
        amostra = self.ok.iloc[0]
        esperado = amostra['climatologia_observada'] / amostra['climatologia_modelo_raw']
        self.assertAlmostEqual(amostra['razao'], esperado, places=9)

    def test_d_grupo_sazonal_cobre_todos_os_12_meses(self):
        self.assertEqual(set(self.ok['target_mes'].unique()), set(range(1, 13)))
        self.assertEqual(set(self.ok['grupo_sazonal'].unique()), {'chuvosa', 'transicao', 'seca'})


class PisoPropostoTestCase(_BaseComArquivoAprovadoTestCase):
    """O piso tem que cair num GAP VAZIO — nunca escolhido por skill
    (nenhum skill é calculado nesta suíte nem na implementação)."""

    def test_a_piso_proposto_nao_fragmenta_nenhum_mes_em_nenhum_lead(self):
        resultado = d.avaliar_candidatos_piso(self.ok)
        self.assertEqual(resultado['meses_fragmentados_pelo_piso'], [])

    def test_b_gap_seguro_contem_o_piso_proposto(self):
        resultado = d.avaliar_candidatos_piso(self.ok)
        baixo, alto = resultado['gap_seguro_mm']
        self.assertLess(baixo, d.PISO_PROPOSTO_MM)
        self.assertLessEqual(d.PISO_PROPOSTO_MM, alto)

    def test_c_meses_abaixo_sao_exatamente_jun_a_set(self):
        resultado = d.avaliar_candidatos_piso(self.ok)
        self.assertEqual(resultado['meses_inteiramente_abaixo_do_piso'], [6, 7, 8, 9])

    def test_d_exclusao_no_piso_proposto_bate_com_jun_set_x_6_leads_x_10_anos(self):
        resultado = d.avaliar_candidatos_piso(self.ok)
        self.assertEqual(resultado['n_excluido_no_piso_proposto'], 240)


class RiscoNegativoOuExplosivoTestCase(_BaseComArquivoAprovadoTestCase):

    def test_a_razao_nunca_e_negativa_nos_dados_aprovados(self):
        risco = d.verificar_risco_negativo_ou_explosivo(self.ok)
        self.assertFalse(risco['razao_pode_ser_negativa'])
        self.assertEqual(risco['climatologia_observada_nao_positiva_n'], 0)
        self.assertEqual(risco['climatologia_modelo_raw_nao_positiva_n'], 0)
        self.assertEqual(risco['forecast_raw_negativo_n'], 0)

    def test_b_razao_apos_piso_e_sempre_positiva(self):
        risco = d.verificar_risco_negativo_ou_explosivo(self.ok)
        self.assertGreater(risco['razao_minima_apos_piso'], 0)


class DiagnosticarDenominadorERazaoTestCase(_BaseComArquivoAprovadoTestCase):

    def test_a_stats_tem_as_9_estatisticas_pedidas(self):
        s = d._stats(self.ok['climatologia_modelo_raw'])
        for chave in ('minimo', 'p05', 'p10', 'p25', 'mediana', 'media', 'p75', 'p90', 'maximo'):
            self.assertIn(chave, s)
        self.assertLessEqual(s['minimo'], s['p05'])
        self.assertLessEqual(s['p90'], s['maximo'])

    def test_b_celulas_de_risco_sistematico_tem_denominador_acima_do_piso(self):
        """Seção 5.2 — achado de risco sistemático SEM denominador
        pequeno; essas células, por definição, não são as que o piso
        já exclui."""
        razao_diag = d.diagnosticar_razao(self.ok)
        for celula in razao_diag['celulas_risco_sistematico_acima_do_piso']:
            self.assertGreaterEqual(celula['denom_min'], d.PISO_PROPOSTO_MM)

    def test_c_outubro_aparece_entre_as_celulas_de_risco_sistematico(self):
        """Achado específico desta sessão — outubro tem razão mediana
        alta em todos os leads mesmo com denominador seguro; se essa
        asserção falhar, o achado documentado na Seção 5.2 do relatório
        mudou e o texto precisa ser revisto junto com o código."""
        razao_diag = d.diagnosticar_razao(self.ok)
        meses_em_risco = {c['mes'] for c in razao_diag['celulas_risco_sistematico_acima_do_piso']}
        self.assertIn(10, meses_em_risco)


class RelatorioMarkdownTestCase(_BaseComArquivoAprovadoTestCase):
    """Testa gerar_relatorio_markdown() diretamente, sem tocar em
    nenhum arquivo real (nem o JSON de diagnóstico, nem o .md) —
    gerar_e_escrever() grava nos caminhos reais e não é chamado aqui."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.resultados = d.executar_diagnostico()

    def test_a_relatorio_cobre_as_7_secoes_pedidas(self):
        texto = rel.gerar_relatorio_markdown(self.resultados)
        for titulo in ('## 1. Distribuição histórica', '## 2. Proposta objetiva do piso',
                       '## 3. Quantidade de casos que seriam excluídos',
                       '## 4. Distribuição das razões resultantes',
                       '## 5. Risco específico na estação seca',
                       '## 6. Regra para impedir previsão negativa ou explosiva',
                       '## 7. Confirmação de que nenhum skill multiplicativo foi calculado'):
            self.assertIn(titulo, texto)

    def test_b_relatorio_nunca_afirma_conclusao_de_desempenho_do_metodo(self):
        texto = rel.gerar_relatorio_markdown(self.resultados)
        baixo = texto.lower()
        for frase in _FRASES_PROIBIDAS:
            self.assertNotIn(frase, baixo, f"relatório afirma: {frase!r}")

    def test_c_relatorio_confirma_explicitamente_que_nenhum_skill_foi_calculado(self):
        texto = rel.gerar_relatorio_markdown(self.resultados)
        self.assertIn('nenhum_skill_multiplicativo_calculado`: True', texto)
        self.assertIn('nenhum_forecast_calibrado_multiplicativo_calculado`: True', texto)

    def test_d_tabela_de_candidatos_marca_o_piso_proposto(self):
        texto = rel.gerar_relatorio_markdown(self.resultados)
        self.assertIn('10.0 **(proposto)**', texto)


if __name__ == '__main__':
    unittest.main()
