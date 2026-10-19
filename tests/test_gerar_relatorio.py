#!/usr/bin/env python3
"""
tests/test_gerar_relatorio.py — Fase ENSO-AUTO (19/10/2026): cobre a
correção do bug real em scripts/gerar_relatorio.py — a comparação
CPC × IRI usava zip() sobre duas listas filtradas de `null`
SEPARADAMENTE; se os dois centros tivessem `null` em POSIÇÕES
diferentes, a "divergência" comparava trimestres diferentes sem avisar.
Corrigido associando por chave 'SEAS/YY' (CPC_IRI.seasons) ANTES de
qualquer filtragem — ver probabilidades_el_nino_por_trimestre() e
resumo_divergencia_cpc_iri().

Sem rede, sem dependência de docs/index.html real para os testes
unitários (fixtures locais embutidas) — só os testes "ComDadosReais*"
precisam da árvore de trabalho real.

Roda com:
    python -m unittest tests.test_gerar_relatorio -v
"""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import gerar_relatorio as gr  # noqa: E402


def _html(seasons, cpc_en, iri_en):
    """Monta um trecho mínimo de docs/index.html só com o necessário
    para os extratores — mesmo padrão de fixture mínima usado em
    tests/test_update_indices.py."""
    def arr(vals):
        return ','.join('null' if v is None else str(v) for v in vals)
    seasons_str = ','.join(f"'{s}'" for s in seasons)
    return (
        f"const CPC_IRI = {{\n"
        f"  seasons: [{seasons_str}],\n"
        f"  cpc:{{ en:[{arr(cpc_en)}], neu:[{arr([0]*len(cpc_en))}], ln:[{arr([0]*len(cpc_en))}] }},\n"
        f"  iri:{{ en:[{arr(iri_en)}], neu:[{arr([0]*len(iri_en))}], ln:[{arr([0]*len(iri_en))}] }},\n"
        f"}};\n"
    )


class ProbabilidadesPorTrimestreTestCase(unittest.TestCase):

    def test_a_associa_por_chave_preserva_null_como_none(self):
        html = _html(['ASO/26', 'SON/26', 'OND/26'], [None, 80, 90], [70, None, 95])
        cpc = gr.probabilidades_el_nino_por_trimestre(html, 'cpc')
        iri = gr.probabilidades_el_nino_por_trimestre(html, 'iri')
        self.assertEqual(cpc, {'ASO/26': None, 'SON/26': 80, 'OND/26': 90})
        self.assertEqual(iri, {'ASO/26': 70, 'SON/26': None, 'OND/26': 95})

    def test_b_campo_ausente_retorna_vazio(self):
        html = "const CPC_IRI = { seasons: ['ASO/26'], cpc:{ en:[80] } };"
        self.assertEqual(gr.probabilidades_el_nino_por_trimestre(html, 'iri'), {})

    def test_c_seasons_ausente_retorna_vazio(self):
        html = "const CPC_IRI = { cpc:{ en:[80] } };"
        self.assertEqual(gr.probabilidades_el_nino_por_trimestre(html, 'cpc'), {})

    def test_d_tamanhos_diferentes_retorna_vazio_nunca_adivinha(self):
        html = "const CPC_IRI = { seasons: ['ASO/26','SON/26'], cpc:{ en:[80] } };"
        self.assertEqual(gr.probabilidades_el_nino_por_trimestre(html, 'cpc'), {})

    def test_e_valor_nao_numerico_e_nao_null_retorna_vazio(self):
        html = "const CPC_IRI = { seasons: ['ASO/26'], cpc:{ en:[abc] } };"
        self.assertEqual(gr.probabilidades_el_nino_por_trimestre(html, 'cpc'), {})

    def test_f_virada_de_ano_nos_rotulos_funciona_normalmente(self):
        html = _html(['NDJ/26', 'DJF/27', 'JFM/27'], [60, 70, 80], [55, 75, 85])
        cpc = gr.probabilidades_el_nino_por_trimestre(html, 'cpc')
        self.assertEqual(cpc, {'NDJ/26': 60, 'DJF/27': 70, 'JFM/27': 80})


class ResumoDivergenciaCpcIriTestCase(unittest.TestCase):

    def test_a_null_em_posicoes_diferentes_nunca_cruza_trimestres(self):
        """O bug real: CPC tem null em ASO/26, IRI tem null em OND/26 —
        um zip() sobre listas filtradas separadamente combinaria
        CPC[SON/26]=80 com IRI[OND/26]=95 (ambos 'segundo item da lista
        filtrada'), produzindo uma divergência de trimestres DIFERENTES
        sem avisar. A versão corrigida só compara ASO/26 nem entra (CPC
        null), SON/26 entra (80 vs None do IRI? não — IRI[SON/26]=70,
        ambos presentes) e OND/26 não entra (IRI null)."""
        cpc = {'ASO/26': None, 'SON/26': 80, 'OND/26': 90}
        iri = {'ASO/26': 70, 'SON/26': 70, 'OND/26': None}
        r = gr.resumo_divergencia_cpc_iri(cpc, iri)
        # único trimestre com os dois valores presentes é SON/26: |80-70|=10
        self.assertEqual(r['trimestre_divergencia_max'], 'SON/26')
        self.assertEqual(r['divergencia_max'], 10)

    def test_b_cpc_max_e_iri_max_nunca_cruzam_trimestres(self):
        cpc = {'ASO/26': None, 'SON/26': 80}
        iri = {'ASO/26': 95, 'SON/26': None}
        r = gr.resumo_divergencia_cpc_iri(cpc, iri)
        self.assertEqual(r['cpc_max'], 80)
        self.assertEqual(r['iri_max'], 95)
        # nenhum trimestre tem os dois valores — divergência não calculada
        self.assertIsNone(r['divergencia_max'])
        self.assertIsNone(r['trimestre_divergencia_max'])

    def test_c_fonte_cpc_inteiramente_indisponivel(self):
        cpc = {'ASO/26': None, 'SON/26': None}
        iri = {'ASO/26': 70, 'SON/26': 80}
        r = gr.resumo_divergencia_cpc_iri(cpc, iri)
        self.assertIsNone(r['cpc_max'])
        self.assertEqual(r['iri_max'], 80)
        self.assertIsNone(r['divergencia_max'])

    def test_d_fonte_iri_inteiramente_indisponivel(self):
        cpc = {'ASO/26': 70}
        iri = {'ASO/26': None}
        r = gr.resumo_divergencia_cpc_iri(cpc, iri)
        self.assertEqual(r['cpc_max'], 70)
        self.assertIsNone(r['iri_max'])
        self.assertIsNone(r['divergencia_max'])

    def test_e_ambas_fontes_vazias_nunca_calcula_sobre_serie_vazia(self):
        r = gr.resumo_divergencia_cpc_iri({}, {})
        self.assertIsNone(r['cpc_max'])
        self.assertIsNone(r['iri_max'])
        self.assertIsNone(r['divergencia_max'])
        self.assertIsNone(r['trimestre_divergencia_max'])

    def test_f_null_nunca_convertido_em_zero(self):
        """Se null fosse tratado como 0, SON/26 entraria na divergência
        como |0-90|=90 — a versão corrigida exclui esse trimestre
        inteiramente."""
        cpc = {'ASO/26': 50, 'SON/26': None}
        iri = {'ASO/26': 50, 'SON/26': 90}
        r = gr.resumo_divergencia_cpc_iri(cpc, iri)
        self.assertEqual(r['divergencia_max'], 0)  # só ASO/26 conta: |50-50|
        self.assertEqual(r['trimestre_divergencia_max'], 'ASO/26')

    def test_g_informa_o_trimestre_da_maior_divergencia(self):
        cpc = {'ASO/26': 50, 'SON/26': 90, 'OND/26': 60}
        iri = {'ASO/26': 55, 'SON/26': 40, 'OND/26': 62}
        r = gr.resumo_divergencia_cpc_iri(cpc, iri)
        self.assertEqual(r['trimestre_divergencia_max'], 'SON/26')
        self.assertEqual(r['divergencia_max'], 50)

    def test_h_virada_de_ano_na_comparacao(self):
        cpc = {'NDJ/26': 90, 'DJF/27': 95}
        iri = {'NDJ/26': 80, 'DJF/27': 60}
        r = gr.resumo_divergencia_cpc_iri(cpc, iri)
        self.assertEqual(r['trimestre_divergencia_max'], 'DJF/27')
        self.assertEqual(r['divergencia_max'], 35)


class ComDadosReaisTestCase(unittest.TestCase):
    """Usa a árvore de trabalho real — mesma convenção das outras
    suítes ComDadosReais* do projeto. Confirma que a correção não
    quebrou o pipeline real de ponta a ponta."""

    @classmethod
    def setUpClass(cls):
        necessarios = [gr.DATA / 'scen12_best.csv', gr.DATA / 'bh_final.json',
                        gr.DATA / 'fc_results_best.json', gr.DATA / 'serie_subst.csv',
                        gr.DOCS / 'index.html']
        if not all(p.exists() for p in necessarios):
            raise unittest.SkipTest('dados reais não disponíveis nesta árvore de trabalho')

    def test_a_carregar_nao_lanca_e_devolve_divergencia_estruturada(self):
        d = gr.carregar()
        self.assertIn('divergencia', d)
        for chave in ('cpc_max', 'iri_max', 'divergencia_max', 'trimestre_divergencia_max'):
            self.assertIn(chave, d['divergencia'])

    def test_b_montar_gera_documento_sem_lancar(self):
        d = gr.carregar()
        doc = gr.montar(d)
        self.assertIsNotNone(doc)

    def test_c_main_roda_de_ponta_a_ponta(self):
        resultado = subprocess.run(
            [sys.executable, str(ROOT / 'scripts' / 'gerar_relatorio.py')],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        self.assertIn('gerado', resultado.stdout)


if __name__ == '__main__':
    unittest.main()
