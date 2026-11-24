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

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import gerar_relatorio as gr  # noqa: E402


# ══════════════════════════════════════════════════════════════════
# Fase ENSO-INTEGRIDADE 3B.8A.3 — correção do falso positivo de
# test_f_null_nunca_aparece_como_zero_no_texto_real: a regex antiga
# `(?<!\d)0%[,.]` buscava "0%" não precedido por um dígito, pensando
# em excluir só o caso "100%" (onde o '0' de '0%' É precedido por
# outro '0', um dígito) — mas um percentual decimal em notação pt-BR
# como "81,0%" tem uma VÍRGULA antes do '0' de '0%', não um dígito, e
# a vírgula não é dígito: o lookbehind deixa passar, "0%," bate dentro
# de "81,0%,", e um valor real (81,0%) era sinalizado como "zero
# fabricado". Achado confirmado reproduzindo contra a baseline antes
# desta correção — não é regressão desta fase.
#
# Corrigido para reconhecer o TOKEN NUMÉRICO COMPLETO antes do '%'
# (dígitos + opcionalmente ',' + dígitos, delimitado por não-dígito/
# não-vírgula dos dois lados) e só then avaliar se o VALOR do token é
# zero — "81,0%" tokeniza como "81,0" (valor 81.0, não zero, nunca
# soa alarme); um "0%"/"0,0%" isolado tokeniza com valor 0.0 e
# continua detectado.
#
# O que esta checagem NUNCA pretende provar: que todo "0%" no texto é
# necessariamente fabricado — um 0% real, comprovado pela fonte (ex.:
# CPC publicando 0% de probabilidade de La Niña num trimestre de El
# Niño forte), é um valor legítimo e não deveria ser proibido de
# aparecer. A garantia de que null nunca é CALCULADO como zero já é
# feita na camada de dados, não na de texto — ver
# ResumoDivergenciaCpcIriTestCase.test_f_null_nunca_convertido_em_zero
# (`resumo_divergencia_cpc_iri()`, que descarta null ANTES de max()/
# comparação, nunca o trata como 0.0) — esta checagem aqui é só uma
# rede de segurança textual sobre o DOCX já gerado, não a fonte de
# verdade sobre proveniência de um zero específico.
_RE_PERCENTUAL_COMPLETO = re.compile(r'(?<![\d,])(\d+(?:,\d+)?)%')


def contem_percentual_zero_fabricado(texto):
    """True se `texto` contém algum percentual COMPLETO cujo valor é
    exatamente zero ('0%', '0,0%', ...) — nunca confunde com a cauda
    de um decimal maior ('81,0%' tokeniza como 81.0, não dispara)."""
    for tok in _RE_PERCENTUAL_COMPLETO.findall(texto):
        if float(tok.replace(',', '.')) == 0.0:
            return True
    return False


class DeteccaoDeZeroFabricadoTestCase(unittest.TestCase):
    """Fixtures positivas/negativas puras para
    `contem_percentual_zero_fabricado()`, sem depender de dados reais
    nem da geração real do relatório — prova que a lógica em si
    distingue os casos antes de confiar nela sobre o DOCX real."""

    def test_a_zero_isolado_e_detectado(self):
        self.assertTrue(contem_percentual_zero_fabricado('El Niño: 0%, La Niña: 10%.'))

    def test_b_zero_virgula_zero_e_detectado(self):
        self.assertTrue(contem_percentual_zero_fabricado('probabilidade de 0,0% neste trimestre.'))

    def test_c_decimal_terminado_em_virgula_zero_nao_e_falso_positivo(self):
        """O bug real: '81,0%,' não pode disparar — é um percentual
        legítimo (81,0%), não um zero."""
        self.assertFalse(contem_percentual_zero_fabricado(
            'a probabilidade de ano seco de 89,8% para 81,0%, o que redefine...'))

    def test_d_cem_por_cento_nao_e_falso_positivo(self):
        self.assertFalse(contem_percentual_zero_fabricado('probabilidade de até 100% e 100%.'))

    def test_e_zero_legitimo_comprovado_na_fonte_tambem_e_detectado_pelo_padrao(self):
        """Esta checagem textual detecta QUALQUER '0%' isolado, mesmo
        um legítimo (comprovado pela fonte, ex. CPC). Ela não decide
        sozinha se é fabricado — só sinaliza o padrão para revisão. A
        garantia de que null nunca é calculado como 0.0 é feita na
        camada de dados (ResumoDivergenciaCpcIriTestCase), não aqui."""
        self.assertTrue(contem_percentual_zero_fabricado(
            'CPC: probabilidade de La Niña 0% (publicado, não é null).'))

    def test_f_nenhum_percentual_no_texto_nao_e_falso_positivo(self):
        self.assertFalse(contem_percentual_zero_fabricado('nenhum percentual neste trecho.'))


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

    def test_d_maximos_cpc_iri_sao_identificados_com_suas_emissoes(self):
        """Verificação explícita pedida na 3ª rodada de revisão
        externa: os máximos de probabilidade de CADA centro, no
        Sumário Executivo, precisam citar a PRÓPRIA emissão — a
        tabela de probabilidades CPC (`cpc_probabilidades_emissao`) é
        uma fonte separada do Diagnostic Discussion (`cpc_emissao`);
        nunca apresentar os dois números sem identificar de qual
        emissão cada um vem."""
        d = gr.carregar()
        self.assertIsNotNone(d['divergencia']['cpc_max'],
                              'pré-requisito do teste: cpc_max precisa existir nos dados reais')
        doc = gr.montar(d)
        texto_sumario = '\n'.join(p.text for p in doc.paragraphs[:8])
        self.assertIn(str(d['divergencia']['cpc_max']), texto_sumario)
        self.assertIn(d['meta'].get('cpc_probabilidades_emissao', ''), texto_sumario)
        self.assertIn(d['meta'].get('iri_emissao', ''), texto_sumario)
        # as duas emissões citadas no MESMO parágrafo que os máximos —
        # não em parágrafos desconectados do resto do documento.
        paragrafo_com_cpc_max = next(
            p.text for p in doc.paragraphs if str(d['divergencia']['cpc_max']) + '%' in p.text)
        self.assertIn(d['meta'].get('cpc_probabilidades_emissao', ''), paragrafo_com_cpc_max)
        self.assertIn(d['meta'].get('iri_emissao', ''), paragrafo_com_cpc_max)

    def test_e_trimestre_de_maior_divergencia_aparece_no_texto(self):
        d = gr.carregar()
        div = d['divergencia']
        if div['trimestre_divergencia_max'] is None:
            self.skipTest('nenhum trimestre comum nesta execução real — divergência não calculada')
        doc = gr.montar(d)
        texto_completo = '\n'.join(p.text for p in doc.paragraphs)
        self.assertIn(div['trimestre_divergencia_max'], texto_completo)

    def test_f_null_nunca_aparece_como_zero_no_texto_real(self):
        """Os dois centros podem ter trimestres sem valor (null) —
        confirma que a geração real não forjou um 0% em lugar nenhum
        por causa disso (o texto só menciona percentuais que vieram de
        d['divergencia'], nunca itera cpc[]/iri[] bruto).

        Fase ENSO-INTEGRIDADE 3B.8A.3: a regex antiga
        (`(?<!\\d)0%[,.]`) dava falso positivo em qualquer percentual
        decimal pt-BR terminado em ',0%' (ex. '81,0%,', um valor real,
        não um zero) — reproduzido e confirmado na baseline antes
        desta correção. `contem_percentual_zero_fabricado()` (definida
        acima, com fixtures próprias) tokeniza o número completo antes
        de avaliar se o valor é zero, então não confunde mais a cauda
        de um decimal maior com um '0%' isolado."""
        d = gr.carregar()
        doc = gr.montar(d)
        texto_completo = '\n'.join(p.text for p in doc.paragraphs)
        self.assertFalse(
            contem_percentual_zero_fabricado(texto_completo),
            'percentual "0%" isolado encontrado no texto real — revisar se é '
            'fabricado (null tratado como 0) ou um zero legítimo comprovado pela fonte')

    def test_g_trajetoria_iri_preservada_nao_e_chamada_de_nova_previsao(self):
        """A trajetória Niño 3.4 do IRI pode estar preservada de uma
        emissão anterior (ver Fase ENSO-IRI) — o relatório usa
        `iri_pico` (do array preservado) só como 'pico projetado',
        nunca rotulado como vindo da emissão atual do Quick Look."""
        d = gr.carregar()
        doc = gr.montar(d)
        texto_completo = '\n'.join(p.text for p in doc.paragraphs)
        self.assertNotIn('pico projetado de setembro', texto_completo.lower())
        self.assertNotIn('nova previsão do iri', texto_completo.lower())

    def test_h_nenhum_resultado_de_precipitacao_ou_bh_e_recalculado_por_este_script(self):
        """gerar_relatorio.py só LÊ data/scen12_best.csv e
        data/bh_final.json (saídas já calculadas por
        update_dashboard.py) — nunca invoca nenhuma rotina de cálculo
        de precipitação ou balanço hídrico. Confirmado estaticamente:
        o módulo não importa nem referencia nenhuma função de cálculo
        desse tipo."""
        fonte = (ROOT / 'scripts' / 'gerar_relatorio.py').read_text(encoding='utf-8')
        # chamadas de função reais (não menções a "SARIMAX"/"XGBoost"
        # em texto descritivo do relatório, que são esperadas e corretas)
        for termo_proibido in ('solve_bh(', '.fit(', '.predict('):
            self.assertNotIn(termo_proibido, fonte,
                              f'{termo_proibido!r} encontrado — gerar_relatorio.py não deveria calcular nada')


if __name__ == '__main__':
    unittest.main()
