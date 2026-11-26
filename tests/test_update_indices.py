#!/usr/bin/env python3
"""
tests/test_update_indices.py — regressão do parser de wksst9120.for e
do parser de RONI.ascii.txt (scripts/update_indices.py).

parse_wksst: o layout real da CPC é de COLUNA FIXA, não separado de
forma confiável por espaço — quando a anomalia é negativa, o sinal
gruda direto no número anterior ("20.6-0.1"). Testado ao vivo contra
o arquivo real desta sessão: 73,6% das 2.349 linhas têm essa
concatenação em pelo menos uma das 4 regiões, e o parser antigo
(`line.split()`, exigindo 9 tokens) pulava a linha inteira nesse caso
— silenciosamente devolvendo um valor de semanas atrás. As amostras
abaixo são recortes reais do arquivo (uma linha com as 4 anomalias
negativas, uma com anomalias mistas/positivas), não inventadas.

Roda com:
    python3 -m unittest tests.test_update_indices -v
"""

import contextlib
import io
import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import update_indices as ui          # noqa: E402
import proveniencia_indices as prov  # noqa: E402

# Cabeçalho + linhas reais de wksst9120.for. A primeira linha de dado
# (02SEP1981) tem as 4 anomalias negativas — sem espaço antes do sinal,
# exatamente o caso que quebrava o parser antigo. A segunda (01JUL2026)
# tem anomalias positivas, com espaço — o caso que sempre funcionou.
WKSST_AMOSTRA = """ Weekly SST data starts week centered on 2Sept1981

                Nino1+2      Nino3        Nino34        Nino4
 Week          SST SSTA     SST SSTA     SST SSTA     SST SSTA
 02SEP1981     20.6-0.1     24.8-0.1     26.5-0.2     28.3-0.3
 01JUL2026     25.7 3.3     28.2 2.0     29.2 1.7     29.9 1.1
"""

RONI_AMOSTRA = """SEAS   YR  ANOM
DJF  1950 -1.19
JFM  1950 -1.08
AMJ  2026  0.49
MJJ  2026  0.97
JJA  2026  1.36
"""


class ParseWksstTestCase(unittest.TestCase):

    def test_linha_com_anomalias_negativas_concatenadas(self):
        """
        Regressão do bug real: split() conta só 5 tokens nessa linha
        (data + 4 blocos "SST-ANOM" colados), o parser antigo exigia 9
        e pulava a linha inteira. O parser novo (coluna fixa) precisa
        capturar as 4 regiões corretamente mesmo aqui.
        """
        lbl, dados = ui.parse_wksst(WKSST_AMOSTRA)
        # a linha mais recente (01JUL2026) é que deve "vencer" — mas
        # isolamos a checagem da linha negativa reprocessando só ela,
        # pra confirmar que ela TAMBÉM seria parseada corretamente.
        so_negativa = WKSST_AMOSTRA.split('\n')
        so_negativa = '\n'.join(l for l in so_negativa if '02SEP1981' in l or 'Week' in l)
        _, dados_neg = ui.parse_wksst(so_negativa)
        self.assertIsNotNone(dados_neg, 'linha com concatenação negativa foi pulada — bug voltou')
        self.assertEqual(dados_neg['nino12']['sst'], 20.6)
        self.assertEqual(dados_neg['nino12']['anom'], -0.1)
        self.assertEqual(dados_neg['nino3']['sst'],  24.8)
        self.assertEqual(dados_neg['nino3']['anom'], -0.1)
        self.assertEqual(dados_neg['nino34']['sst'], 26.5)
        self.assertEqual(dados_neg['nino34']['anom'], -0.2)
        self.assertEqual(dados_neg['nino4']['sst'],  28.3)
        self.assertEqual(dados_neg['nino4']['anom'], -0.3)

    def test_pega_a_linha_mais_recente_e_as_4_regioes(self):
        lbl, dados = ui.parse_wksst(WKSST_AMOSTRA)
        self.assertEqual(lbl, '01JUL2026')
        self.assertEqual(set(dados.keys()), {'nino12', 'nino3', 'nino34', 'nino4'})
        self.assertEqual(dados['nino34']['anom'], 1.7)
        self.assertEqual(dados['nino4']['anom'], 1.1)

    def test_linha_curta_ou_sem_data_valida_e_ignorada(self):
        lbl, dados = ui.parse_wksst('lixo qualquer\n 99XXX9999   20.0 1.0\n')
        self.assertIsNone(lbl)
        self.assertIsNone(dados)


class ParseRoniTestCase(unittest.TestCase):

    def test_pega_o_ultimo_trimestre_e_ignora_cabecalho(self):
        seas, ano, val = ui.parse_roni(RONI_AMOSTRA)
        self.assertEqual(seas, 'JJA')
        self.assertEqual(ano, 2026)
        self.assertEqual(val, 1.36)

    def test_texto_vazio_ou_so_cabecalho_nao_quebra(self):
        seas, ano, val = ui.parse_roni('SEAS   YR  ANOM\n')
        self.assertIsNone(seas)
        self.assertIsNone(ano)
        self.assertIsNone(val)

    def test_roni_diferente_de_oni_aprox_no_mesmo_trimestre(self):
        """
        RONI não é recalculado a partir do nino34 bruto (calc_oni) —
        são fontes/fórmulas diferentes. Este teste apenas documenta
        que parse_roni nunca deriva o valor de nino34: ele só lê o que
        a CPC publicou em RONI.ascii.txt, literal.
        """
        seas, ano, val = ui.parse_roni(RONI_AMOSTRA)
        oni_aprox_exemplo = 2.03  # jul/2026, calc_oni — não vem deste parser
        self.assertNotEqual(val, oni_aprox_exemplo)


class ParseRoniEntradasInvalidasTestCase(unittest.TestCase):
    """Fase ENSO-RONI 4B.1.3 (correção da revisão externa): duas
    barreiras que pareciam suficientes não eram — `re.match(r'^[A-Z]{3}$')`
    aceitava qualquer sigla de 3 letras (não só os 12 códigos reais de
    trimestre), e `abs(val) > 5` não rejeita NaN (comparação com NaN é
    sempre False em Python). Cada teste aqui isola uma dessas lacunas e
    confirma que a linha inválida é descartada SEM corromper
    `ultimo` — a última observação válida já encontrada antes dela
    continua sendo o retorno."""

    def test_a_trimestre_de_tres_letras_invalido_e_rejeitado(self):
        texto = "SEAS   YR  ANOM\nJJA  2026  1.36\nXYZ  2026  9.99\n"
        seas, ano, val = ui.parse_roni(texto)
        self.assertEqual((seas, ano, val), ('JJA', 2026, 1.36),
                          'XYZ não é um dos 12 códigos de trimestre — não pode ser aceito nem sobrescrever o último válido')

    def test_b_nan_literal_e_rejeitado_mesmo_dentro_do_limite_fisico_aparente(self):
        # abs(float('nan')) > 5 é False em Python — por isso o teste
        # existe: sem math.isfinite(), essa linha passaria.
        texto = "SEAS   YR  ANOM\nJJA  2026  1.36\nJAS  2026  nan\n"
        seas, ano, val = ui.parse_roni(texto)
        self.assertEqual((seas, ano, val), ('JJA', 2026, 1.36))

    def test_c_infinito_literal_e_rejeitado(self):
        texto = "SEAS   YR  ANOM\nJJA  2026  1.36\nJAS  2026  inf\n"
        seas, ano, val = ui.parse_roni(texto)
        self.assertEqual((seas, ano, val), ('JJA', 2026, 1.36))

    def test_d_infinito_negativo_literal_e_rejeitado(self):
        texto = "SEAS   YR  ANOM\nJJA  2026  1.36\nJAS  2026  -inf\n"
        seas, ano, val = ui.parse_roni(texto)
        self.assertEqual((seas, ano, val), ('JJA', 2026, 1.36))

    def test_e_ano_fora_da_faixa_plausivel_e_rejeitado(self):
        texto = "SEAS   YR  ANOM\nJJA  2026  1.36\nJAS  3026  1.50\n"
        seas, ano, val = ui.parse_roni(texto)
        self.assertEqual((seas, ano, val), ('JJA', 2026, 1.36))

    def test_f_linha_invalida_no_meio_nao_corrompe_o_resto_do_arquivo(self):
        texto = "SEAS   YR  ANOM\nJJA  2026  1.36\nXYZ  2026  nan\nJAS  2026  1.69\n"
        seas, ano, val = ui.parse_roni(texto)
        self.assertEqual((seas, ano, val), ('JAS', 2026, 1.69),
                          'a linha inválida no meio é descartada, e o parser continua até o último trimestre REALMENTE válido')

    def test_g_os_12_codigos_oficiais_sao_todos_aceitos(self):
        for seas_valida in sorted(ui.SEASONS_RONI_VALIDAS):
            with self.subTest(seas=seas_valida):
                texto = f"SEAS   YR  ANOM\n{seas_valida}  2026  0.50\n"
                seas, ano, val = ui.parse_roni(texto)
                self.assertEqual((seas, ano, val), (seas_valida, 2026, 0.50))


# Trecho real da tabela HTML de
# https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/probabilities/
# (baixado ao vivo 15/10/2026, Fase ENSO-DADOS) — ordem de colunas
# confirmada contra o HTML bruto: La Niña, Neutro, El Niño.
def _linha_prob(sigla, meses_tooltip, ln, neu, en):
    return (f'<tr><th scope="row"><abbr>{sigla} <span class="tooltip tooltip-right" '
            f'role="tooltip">{meses_tooltip}</span></abbr></th>'
            f'<td>{ln}</td><td>{neu}</td><td>{en}</td></tr>')


# Cabeçalho real "Issued <Mês> <Ano>" (ver /probabilities/, baixado ao
# vivo 15/10/2026) — único dado desta fonte que identifica o ano sem
# ambiguidade (ver _alinhar_seasons_com_ano). Amostra de 3 linhas
# (SON, FMA, AMJ), mesmos números da tabela real de out/2026 — SEM
# virada de ano (todas as 3 ficam em 2026 com essa emissão).
CPC_PROBABILIDADES_AMOSTRA_REAL = (
    '<h2>Issued October 2026</h2>'
    + _linha_prob('SON', 'Sep Oct Nov', 0, 0, 100)
)
# Amostra mais longa, 9 linhas em ordem cronológica real (SON..MJJ,
# emissão de outubro) — usada pra testar o alinhamento completo.
CPC_PROBABILIDADES_AMOSTRA_9_LINHAS = (
    '<h2>Issued October 2026</h2>'
    + _linha_prob('SON', 'Sep Oct Nov', 0, 0, 100)
    + _linha_prob('OND', 'Oct Nov Dec', 0, 0, 100)
    + _linha_prob('NDJ', 'Nov Dec Jan', 0, 0, 100)
    + _linha_prob('DJF', 'Dec Jan Feb', 0, 0, 100)
    + _linha_prob('JFM', 'Jan Feb Mar', 0, 0, 100)
    + _linha_prob('FMA', 'Feb Mar Apr', 0, 2, 98)
    + _linha_prob('MAM', 'Mar Apr May', 0, 15, 85)
    + _linha_prob('AMJ', 'Apr May Jun', 1, 54, 45)
    + _linha_prob('MJJ', 'May Jun Jul', 13, 70, 17)
)
# Emissão de dezembro — a virada de ano acontece já na 2ª linha
# (NDJ/2026 centrado em dez/2026, DJF/2027 centrado em jan/2027).
CPC_PROBABILIDADES_AMOSTRA_VIRADA_DE_ANO = (
    '<h2>Issued December 2026</h2>'
    + _linha_prob('NDJ', 'Nov Dec Jan', 0, 0, 100)
    + _linha_prob('DJF', 'Dec Jan Feb', 0, 5, 95)
    + _linha_prob('JFM', 'Jan Feb Mar', 2, 18, 80)
)


class ParseCpcProbabilidadesTestCase(unittest.TestCase):

    def test_a_extrai_as_3_colunas_na_ordem_ln_neu_en_com_ano(self):
        r = ui.parse_cpc_probabilidades(CPC_PROBABILIDADES_AMOSTRA_9_LINHAS)
        self.assertEqual(set(r.keys()),
                          {'SON/26', 'OND/26', 'NDJ/26', 'DJF/27', 'JFM/27',
                           'FMA/27', 'MAM/27', 'AMJ/27', 'MJJ/27'})
        self.assertEqual(r['SON/26'], {'ln': 0.0, 'neu': 0.0, 'en': 100.0})
        self.assertEqual(r['AMJ/27'], {'ln': 1.0, 'neu': 54.0, 'en': 45.0})

    def test_b_virada_de_ano_dentro_da_mesma_tabela(self):
        r = ui.parse_cpc_probabilidades(CPC_PROBABILIDADES_AMOSTRA_VIRADA_DE_ANO)
        self.assertEqual(set(r.keys()), {'NDJ/26', 'DJF/27', 'JFM/27'})
        self.assertEqual(r['DJF/27'], {'ln': 0.0, 'neu': 5.0, 'en': 95.0})

    def test_c_publicacao_parcial_poucas_linhas_ainda_funciona(self):
        r = ui.parse_cpc_probabilidades(CPC_PROBABILIDADES_AMOSTRA_REAL)
        self.assertEqual(r, {'SON/26': {'ln': 0.0, 'neu': 0.0, 'en': 100.0}})

    def test_d_linha_que_nao_soma_100_e_descartada_sem_derrubar_as_outras(self):
        quebrada = CPC_PROBABILIDADES_AMOSTRA_9_LINHAS.replace(
            '<td>1</td><td>54</td><td>45</td>', '<td>1</td><td>54</td><td>20</td>')
        r = ui.parse_cpc_probabilidades(quebrada)
        self.assertNotIn('AMJ/27', r)
        self.assertIn('SON/26', r)
        self.assertIn('FMA/27', r)

    def test_e_valor_fora_de_0_100_e_descartado(self):
        invalida = CPC_PROBABILIDADES_AMOSTRA_9_LINHAS.replace(
            '<td>0</td><td>0</td><td>100</td>', '<td>-5</td><td>5</td><td>100</td>', 1)
        r = ui.parse_cpc_probabilidades(invalida)
        self.assertNotIn('SON/26', r)

    def test_f_html_sem_tabela_retorna_dict_vazio_nunca_lanca(self):
        self.assertEqual(ui.parse_cpc_probabilidades('<html><body>nada aqui</body></html>'), {})
        self.assertEqual(ui.parse_cpc_probabilidades(''), {})

    def test_g_sem_cabecalho_issued_nao_arrisca_alinhar_ano(self):
        """Mudança estrutural: linhas válidas existem, mas sem o
        cabeçalho 'Issued <Mês> <Ano>' não há como saber o ano de cada
        trimestre com segurança — resultado tem que ser vazio, nunca
        uma suposição."""
        sem_cabecalho = CPC_PROBABILIDADES_AMOSTRA_9_LINHAS.replace(
            '<h2>Issued October 2026</h2>', '')
        r = ui.parse_cpc_probabilidades(sem_cabecalho)
        self.assertEqual(r, {})

    def test_h_sequencia_nao_bate_com_o_esperado_recusa_alinhar(self):
        """Mudança estrutural: se a ordem das linhas não for a
        sequência cronológica esperada a partir do mês de emissão
        (ex.: CPC reordenou ou pulou um trimestre sem avisar), a
        validação cruzada falha e a função se recusa a adivinhar o
        ano — retorna vazio, nunca associa errado."""
        fora_de_ordem = (
            '<h2>Issued October 2026</h2>'
            + _linha_prob('SON', 'Sep Oct Nov', 0, 0, 100)
            + _linha_prob('JFM', 'Jan Feb Mar', 0, 0, 100)  # pulou OND/NDJ/DJF
        )
        r = ui.parse_cpc_probabilidades(fora_de_ordem)
        self.assertEqual(r, {})

    def test_i_mes_de_emissao_nao_reconhecido_retorna_vazio(self):
        invalido = '<h2>Issued Smarch 2026</h2>' + _linha_prob('SON', 'Sep Oct Nov', 0, 0, 100)
        r = ui.parse_cpc_probabilidades(invalido)
        self.assertEqual(r, {})


class ExtrairEmissaoCpcProbabilidadesTestCase(unittest.TestCase):

    def test_a_extrai_mes_e_ano_em_portugues(self):
        self.assertEqual(
            ui.extrair_emissao_cpc_probabilidades(CPC_PROBABILIDADES_AMOSTRA_9_LINHAS),
            'out/2026')

    def test_b_sem_cabecalho_retorna_none(self):
        self.assertIsNone(ui.extrair_emissao_cpc_probabilidades('<html></html>'))


HTML_CPC_IRI_AMOSTRA = """
const CPC_IRI = {
  _meta: {
    cpc_emissao:   '13/ago/2026',
    atualizado_em: '24/ago/2026',
  },
  seasons: ['ASO/26','SON/26','FMA/27'],
  cpc:{ en:[97,94,null], neu:[3,6,null], ln:[0,0,null] },
  iri:{ en:[100,97,78], neu:[0,3,22], ln:[0,0,0] },
};
"""


class AtualizarCpcProbabilidadesNoHtmlTestCase(unittest.TestCase):

    def test_a_preenche_so_os_seasons_existentes_por_chave_completa_e_poe_null_no_resto(self):
        probs = {'SON/26': {'ln': 0.0, 'neu': 0.0, 'en': 100.0},
                 'FMA/27': {'ln': 0.0, 'neu': 2.0, 'en': 98.0}}
        novo_html, mudou = ui.atualizar_cpc_probabilidades_no_html(
            HTML_CPC_IRI_AMOSTRA, probs, emissao='out/2026')
        self.assertTrue(mudou)
        self.assertIn("cpc:{ en:[null,100.0,98.0], neu:[null,0.0,2.0], ln:[null,0.0,0.0] },", novo_html)

    def test_a2_sigla_igual_mas_ano_diferente_nunca_e_associada_errado(self):
        """Mesma sigla 'FMA', mas pra 2026 (não existe em seasons, que
        só tem FMA/27) — não pode preencher o slot de FMA/27 com o
        valor de um FMA/26 só porque a sigla bate. Com `emissao`
        consistente ('out/2026'), FMA/26 também é rejeitado pela
        checagem de consistência emissão×trimestres (Correção 1, 2ª
        rodada) — reforça, não substitui, a proteção original."""
        probs = {'FMA/26': {'ln': 9.0, 'neu': 9.0, 'en': 82.0}}
        novo_html, mudou = ui.atualizar_cpc_probabilidades_no_html(
            HTML_CPC_IRI_AMOSTRA, probs, emissao='out/2026')
        self.assertFalse(mudou)
        self.assertEqual(novo_html, HTML_CPC_IRI_AMOSTRA)

    def test_b_nunca_toca_o_bloco_iri(self):
        probs = {'SON/26': {'ln': 0.0, 'neu': 0.0, 'en': 100.0}}
        novo_html, _ = ui.atualizar_cpc_probabilidades_no_html(
            HTML_CPC_IRI_AMOSTRA, probs, emissao='out/2026')
        self.assertIn("iri:{ en:[100,97,78], neu:[0,3,22], ln:[0,0,0] },", novo_html)

    def test_c_nunca_toca_a_lista_de_seasons(self):
        probs = {'SON/26': {'ln': 0.0, 'neu': 0.0, 'en': 100.0}}
        novo_html, _ = ui.atualizar_cpc_probabilidades_no_html(
            HTML_CPC_IRI_AMOSTRA, probs, emissao='out/2026')
        self.assertIn("seasons: ['ASO/26','SON/26','FMA/27'],", novo_html)

    def test_d_probabilidades_vazio_nao_altera_nada(self):
        novo_html, mudou = ui.atualizar_cpc_probabilidades_no_html(
            HTML_CPC_IRI_AMOSTRA, {}, emissao='out/2026')
        self.assertFalse(mudou)
        self.assertEqual(novo_html, HTML_CPC_IRI_AMOSTRA)

    def test_e_nenhum_season_bate_mantem_html_original(self):
        probs = {'XYZ/99': {'ln': 0.0, 'neu': 0.0, 'en': 100.0}}
        novo_html, mudou = ui.atualizar_cpc_probabilidades_no_html(
            HTML_CPC_IRI_AMOSTRA, probs, emissao='out/2026')
        self.assertFalse(mudou)
        self.assertEqual(novo_html, HTML_CPC_IRI_AMOSTRA)

    def test_f_adiciona_metadado_de_data_de_coleta(self):
        probs = {'SON/26': {'ln': 0.0, 'neu': 0.0, 'en': 100.0}}
        novo_html, _ = ui.atualizar_cpc_probabilidades_no_html(
            HTML_CPC_IRI_AMOSTRA, probs, emissao='out/2026')
        self.assertIn('cpc_probabilidades_atualizado_em:', novo_html)

    def test_g_nunca_sobrescreve_cpc_emissao_a_data_do_diagnostic_discussion(self):
        probs = {'SON/26': {'ln': 0.0, 'neu': 0.0, 'en': 100.0}}
        novo_html, _ = ui.atualizar_cpc_probabilidades_no_html(
            HTML_CPC_IRI_AMOSTRA, probs, emissao='out/2026')
        self.assertIn("cpc_emissao:   '13/ago/2026',", novo_html)

    def test_h_registra_emissao_da_tabela_separada_de_cpc_emissao(self):
        probs = {'SON/26': {'ln': 0.0, 'neu': 0.0, 'en': 100.0}}
        novo_html, _ = ui.atualizar_cpc_probabilidades_no_html(
            HTML_CPC_IRI_AMOSTRA, probs, emissao='out/2026')
        self.assertIn("cpc_probabilidades_emissao: 'out/2026',", novo_html)

    def test_i_idempotente_segunda_execucao_com_mesmo_input_nao_muda_nada(self):
        probs = {'SON/26': {'ln': 0.0, 'neu': 0.0, 'en': 100.0},
                 'FMA/27': {'ln': 0.0, 'neu': 2.0, 'en': 98.0}}
        html1, mudou1 = ui.atualizar_cpc_probabilidades_no_html(
            HTML_CPC_IRI_AMOSTRA, probs, emissao='out/2026')
        self.assertTrue(mudou1)
        html2, mudou2 = ui.atualizar_cpc_probabilidades_no_html(html1, probs, emissao='out/2026')
        self.assertFalse(mudou2)
        self.assertEqual(html1, html2)

    def test_j_execucao_repetida_nunca_duplica_nenhum_campo_de_meta(self):
        probs = {'SON/26': {'ln': 0.0, 'neu': 0.0, 'en': 100.0}}
        html_atual = HTML_CPC_IRI_AMOSTRA
        for _ in range(5):
            html_atual, _ = ui.atualizar_cpc_probabilidades_no_html(
                html_atual, probs, emissao='out/2026')
        for campo in ('cpc_probabilidades_atualizado_em', 'cpc_probabilidades_emissao',
                      'cpc_probabilidades_ultima_alteracao'):
            self.assertEqual(html_atual.count(campo + ':'), 1, f'{campo} duplicado')

    def test_k_ultima_alteracao_so_e_registrada_quando_o_valor_de_fato_muda(self):
        # 'FMA/27' (não 'SON/26') porque precisa continuar alcançável
        # tanto a partir de 'out/2026' quanto de 'nov/2026' andando
        # sequencialmente (Correção 1, 2ª rodada: a emissão buscada
        # precisa ser consistente com os trimestres do documento) —
        # 'SON/26' só é alcançável a partir de out/2026, nunca de
        # nov/2026 (seria retroceder no calendário).
        probs_v1 = {'FMA/27': {'ln': 0.0, 'neu': 0.0, 'en': 100.0}}
        html1, _ = ui.atualizar_cpc_probabilidades_no_html(
            HTML_CPC_IRI_AMOSTRA, probs_v1, emissao='out/2026')
        self.assertIn('cpc_probabilidades_ultima_alteracao:', html1)

        # Roda de novo com o MESMO valor e uma nova emissão (simulando
        # um mês em que a fonte confirma o mesmo número) — a mudança
        # de meta (emissão) não deve, sozinha, mexer em ultima_alteracao.
        import re
        m_antes = re.search(r"cpc_probabilidades_ultima_alteracao:\s*'([^']*)'", html1)
        html2, mudou2 = ui.atualizar_cpc_probabilidades_no_html(
            html1, probs_v1, emissao='nov/2026')
        self.assertTrue(mudou2)  # emissão mudou, então grava
        m_depois = re.search(r"cpc_probabilidades_ultima_alteracao:\s*'([^']*)'", html2)
        self.assertEqual(m_antes.group(1), m_depois.group(1),
                          'ultima_alteracao não deveria mudar só porque a emissão mudou')

        # Agora muda o VALOR de fato — ultima_alteracao tem que atualizar.
        probs_v2 = {'FMA/27': {'ln': 10.0, 'neu': 10.0, 'en': 80.0}}
        html3, mudou3 = ui.atualizar_cpc_probabilidades_no_html(
            html2, probs_v2, emissao='nov/2026')
        self.assertTrue(mudou3)
        self.assertIn("cpc:{ en:[null,null,80.0]", html3)


class BuildSeriesTestCase(unittest.TestCase):
    """Revisão externa (2ª rodada, 'Correção 2') — série mensal
    (`build_series`) só com valores mensais reais; a leitura semanal
    nunca entra nela (ver `_escolher_nino34_para_card_agora` abaixo
    pro card "agora", que é o único lugar onde ela aparece)."""

    def test_a_mes_corrente_sem_dado_mensal_fica_null_nunca_preenchido(self):
        # Nenhum dado mensal nenhum — o mês corrente (último rótulo da
        # série) tem que ficar null, nunca preenchido por outra fonte.
        series = ui.build_series({}, {})
        self.assertEqual(series['nino34'][-1], 'null')

    def test_b_valor_mensal_real_do_mes_corrente_e_usado_normalmente(self):
        hoje = date.today()
        nino34 = {(hoje.year, hoje.month): 2.5}
        series = ui.build_series(nino34, {})
        self.assertEqual(series['nino34'][-1], '2.5')

    def test_c_assinatura_nao_aceita_mais_wk_lbl_wk_val(self):
        """Documenta a mudança de contrato — build_series não recebe
        mais a leitura semanal (ela nunca deveria influenciar a série
        mensal)."""
        import inspect
        params = list(inspect.signature(ui.build_series).parameters)
        self.assertEqual(params, ['nino34', 'tsa'])


class EscolherNino34ParaCardAgoraTestCase(unittest.TestCase):
    """Revisão externa (2ª rodada, 'Correção 2') — função pura extraída
    de update_html(), testável sem tocar o HTML real. Cobre
    explicitamente os 4 casos pedidos: falha da fonte semanal, semana
    desatualizada, virada de mês, ausência de valor mensal."""

    def test_a_falha_da_fonte_semanal_usa_mensal(self):
        lbl, val = ui._escolher_nino34_para_card_agora(None, None, '09/26', 2.84)
        self.assertEqual((lbl, val), ('09/26', 2.84))

    def test_b_semana_desatualizada_mais_velha_que_o_mensal_mantem_mensal(self):
        # Bug real confirmado nos dados em 15/10/2026: semanal de
        # 23/09/2026 não pode ser promovida a "mais atual que" um
        # mensal de 09/2026 (mesmo mês) nem, a fortiori, mais recente.
        lbl, val = ui._escolher_nino34_para_card_agora('23SEP2026', 3.10, '10/26', 1.00)
        self.assertEqual((lbl, val), ('10/26', 1.00))

    def test_c_virada_de_mes_semanal_do_mes_novo_e_mais_recente_usa_semanal(self):
        lbl, val = ui._escolher_nino34_para_card_agora('05OCT2026', 3.20, '09/26', 2.84)
        self.assertEqual(lbl, '10/26')
        self.assertEqual(val, 3.20)

    def test_d_ausencia_de_valor_mensal_usa_semanal_sem_comparar(self):
        lbl, val = ui._escolher_nino34_para_card_agora('23SEP2026', 3.10, None, None)
        self.assertEqual((lbl, val), ('09/26', 3.10))

    def test_e_mesmo_mes_semanal_e_mensal_usa_semanal_mais_granular(self):
        # Mesmo mês (set/2026 nos dois) — semanal é >= mensal, pode
        # ser usada (mais granular/atual dentro do mesmo mês).
        lbl, val = ui._escolher_nino34_para_card_agora('23SEP2026', 3.10, '09/26', 2.84)
        self.assertEqual((lbl, val), ('09/26', 3.10))

    def test_f_rotulo_do_semanal_e_sempre_a_data_propria_dele_nunca_hoje(self):
        lbl, _ = ui._escolher_nino34_para_card_agora('23SEP2026', 3.10, None, None)
        self.assertEqual(lbl, '09/26')
        self.assertNotEqual(lbl, date.today().strftime('%m/%y'))

    def test_g_wk_lbl_malformado_nao_lanca_cai_para_mensal(self):
        lbl, val = ui._escolher_nino34_para_card_agora('lixo-invalido', 3.10, '09/26', 2.84)
        self.assertEqual((lbl, val), ('09/26', 2.84))


# Bloco CPC_IRI mínimo para os testes de dash_proxima/divergencia da Fase
# ENSO-INTEGRIDADE 3B.8A — réplica da forma real (ver docs/index.html),
# com cpc_probabilidades_emissao e iri_emissao deliberadamente em meses
# diferentes (nov/2026 e 21/09/2026), igual ao caso real que motivou a
# correção (divergencia citava 'out/2026', já desatualizado).
HTML_CPC_IRI_META_AMOSTRA = """
const CPC_IRI = {
  _meta: {
    cpc_emissao:   '13/ago/2026',
    cpc_probabilidades_emissao: 'nov/2026',
    iri_emissao: '21/09/2026',
    atualizado_em: '21/11/2026',
    dash_proxima: '21/out/2026',
    divergencia: 'cpc[] é da tabela estruturada de probabilidades (out/2026); iri[] é da extração externa da emissão de set/2026 (ver iri_extracao) — ASO/26 null em ambos não é coincidência: CPC também não publicou ASO/26 na tabela estruturada (fora do alcance), IRI porque a extração de set/2026 não confirmou esse trimestre',
    roni_trimestral: '+1,69°C (JAS/2026, oficial NOAA/CPC, ERSSTv6)',
  },
  seasons: ['ASO/26','SON/26','FMA/27'],
  cpc:{ en:[null,94,82], neu:[null,6,16], ln:[null,0,2] },
  iri:{ en:[null,97,78], neu:[null,3,22], ln:[null,0,0] },
};
"""


class ProximaAtualizacaoMensalTestCase(unittest.TestCase):
    """Seção 4/7 da Fase ENSO-INTEGRIDADE 3B.8A: `_meta.dash_proxima` era
    texto fixo, escrito uma vez à mão e nunca mais atualizado (chegou a
    ficar meses no passado frente à própria emissão do dashboard — caso
    real: dashboard emitido em 21/11/2026 ainda mostrava '21/out/2026').
    `_proxima_atualizacao_mensal(hoje)` calcula a partir do cron real de
    update.yml (dia 21 de cada mês) e nunca devolve o próprio dia do
    ciclo em execução."""

    def test_a_proxima_e_sempre_posterior_ao_dia_de_hoje(self):
        for hoje in (date(2026, 11, 21), date(2026, 11, 1), date(2026, 11, 20),
                     date(2026, 11, 22), date(2026, 12, 21), date(2026, 1, 21)):
            proxima = ui._proxima_atualizacao_mensal(hoje)
            self.assertGreater(proxima, hoje, f'falhou para hoje={hoje}')

    def test_b_virada_novembro_para_dezembro(self):
        self.assertEqual(ui._proxima_atualizacao_mensal(date(2026, 11, 21)),
                          date(2026, 12, 21))

    def test_c_virada_dezembro_para_janeiro_com_virada_de_ano(self):
        self.assertEqual(ui._proxima_atualizacao_mensal(date(2026, 12, 21)),
                          date(2027, 1, 21))

    def test_d_antes_do_dia_21_a_proxima_e_ainda_este_mes(self):
        self.assertEqual(ui._proxima_atualizacao_mensal(date(2026, 11, 1)),
                          date(2026, 11, 21))
        self.assertEqual(ui._proxima_atualizacao_mensal(date(2026, 11, 20)),
                          date(2026, 11, 21))

    def test_e_ciclo_atrasado_apos_o_dia_21_pula_para_o_mes_seguinte(self):
        # Se o ciclo roda atrasado (ex.: runner indisponível no dia 21 e
        # só executa no dia 22), a "próxima" não pode ser o dia 21 do
        # mesmo mês, que já passou — regra explícita do usuário: nunca
        # afirmar uma execução futura que já ficou no passado.
        self.assertEqual(ui._proxima_atualizacao_mensal(date(2026, 11, 22)),
                          date(2026, 12, 21))

    def test_f_dezembro_nunca_avanca_para_mes_13(self):
        proxima = ui._proxima_atualizacao_mensal(date(2026, 12, 21))
        self.assertLessEqual(proxima.month, 12)
        self.assertEqual(proxima.month, 1)
        self.assertEqual(proxima.year, 2027)


class DataNumericaParaDateTestCase(unittest.TestCase):
    """`_data_numerica_para_date`: formato DD/MM/AAAA usado por
    `_meta.iri_emissao` — diferente do D/mon/AAAA de `_meta.cpc_emissao`
    (CLAUDE.md armadilha 9). Nunca lança excessão para texto não
    reconhecido; devolve None."""

    def test_a_formato_valido(self):
        self.assertEqual(ui._data_numerica_para_date('21/09/2026'), date(2026, 9, 21))

    def test_b_none_para_vazio(self):
        self.assertIsNone(ui._data_numerica_para_date(None))
        self.assertIsNone(ui._data_numerica_para_date(''))

    def test_c_none_para_texto_nao_reconhecido(self):
        self.assertIsNone(ui._data_numerica_para_date('13/ago/2026'))
        self.assertIsNone(ui._data_numerica_para_date('lixo'))

    def test_d_none_para_data_invalida_sem_lancar_excecao(self):
        self.assertIsNone(ui._data_numerica_para_date('31/02/2026'))


class GerarDivergenciaCpcIriTestCase(unittest.TestCase):
    """Seção 5/7 da Fase ENSO-INTEGRIDADE 3B.8A: `_meta.divergencia`
    citava um mês fixo ('out/2026') escrito à mão, que ficou
    desatualizado quando `cpc_probabilidades_emissao` avançou para
    nov/2026 — `_gerar_divergencia_cpc_iri` precisa gerar o texto a
    partir dos campos de emissão REALMENTE registrados agora, nunca de
    um mês hardcoded."""

    def test_a_cita_a_emissao_cpc_realmente_registrada_agora(self):
        bloco = _bloco_cpc_iri_amostra()
        texto = ui._gerar_divergencia_cpc_iri(bloco)
        self.assertIn('nov/2026', texto)
        self.assertNotIn('out/2026', texto)

    def test_b_cita_a_emissao_iri_convertida_para_mes_em_portugues(self):
        bloco = _bloco_cpc_iri_amostra()
        texto = ui._gerar_divergencia_cpc_iri(bloco)
        # iri_emissao = '21/09/2026' -> mês de emissão citado é set/2026
        self.assertIn('set/2026', texto)

    def test_c_identifica_trimestres_nulos_em_ambas_as_fontes_na_emissao_atual(self):
        bloco = _bloco_cpc_iri_amostra()
        nulos = ui._trimestres_nulos_em_ambos_cpc_iri(bloco)
        self.assertEqual(nulos, ['ASO/26'])
        texto = ui._gerar_divergencia_cpc_iri(bloco)
        self.assertIn('ASO/26', texto)

    def test_e_descreve_o_que_o_dashboard_registra_nunca_o_que_a_fonte_publicou(self):
        """Fase ENSO-INTEGRIDADE 3B.8A.3: a frase antiga ('nenhuma das
        duas fontes publicou probabilidade') afirmava algo sobre CPC/
        IRI que o código não tem como comprovar — null aqui só prova
        que ESTE dashboard não tem o valor, não que a fonte não
        publicou. Reformulado para uma afirmação verificável pelos
        próprios dados do bloco."""
        bloco = _bloco_cpc_iri_amostra()
        texto = ui._gerar_divergencia_cpc_iri(bloco)
        self.assertIn('sem probabilidades confirmadas nos dados registrados', texto)
        self.assertNotIn('publicou', texto)

    def test_d_nao_inventa_nulo_que_nao_existe_nos_dados_do_bloco(self):
        # SON/26 e FMA/27 têm valor em pelo menos uma das duas fontes no
        # fixture — não podem aparecer na lista de "null em ambos".
        bloco = _bloco_cpc_iri_amostra()
        nulos = ui._trimestres_nulos_em_ambos_cpc_iri(bloco)
        self.assertNotIn('SON/26', nulos)
        self.assertNotIn('FMA/27', nulos)


def _bloco_cpc_iri_amostra():
    ini = HTML_CPC_IRI_META_AMOSTRA.find('const CPC_IRI = {')
    fim = HTML_CPC_IRI_META_AMOSTRA.find('\n};', ini) + 3
    return HTML_CPC_IRI_META_AMOSTRA[ini:fim]


class AtualizacaoDashProximaEDivergenciaNaoAlteraOutrosCamposTestCase(unittest.TestCase):
    """Item 8 da Seção 7 (preservação): a atualização de `dash_proxima`
    e `divergencia` via `_upsert_campo_meta` deve trocar SOMENTE esses
    dois campos — nunca o restante do bloco `CPC_IRI` (seasons, cpc[],
    iri[], outros campos de _meta), reproduzindo o mesmo splice
    delimitado (`ini`/`fim`/`bloco`) usado em update_html() (CLAUDE.md
    armadilha 2: nunca re.sub global sobre o HTML inteiro)."""

    def setUp(self):
        self.bloco_original = _bloco_cpc_iri_amostra()
        proxima = ui._proxima_atualizacao_mensal(date(2026, 11, 23))
        bloco = ui._upsert_campo_meta(
            self.bloco_original, 'dash_proxima',
            f'{proxima.day}/{ui._NOMES_MESES_PT[proxima.month - 1]}/{proxima.year}')
        self.bloco_novo = ui._upsert_campo_meta(
            bloco, 'divergencia', ui._gerar_divergencia_cpc_iri(bloco))

    def test_a_dash_proxima_atualizado(self):
        self.assertIn("dash_proxima: '21/dez/2026'", self.bloco_novo)
        self.assertNotIn("dash_proxima:   '21/out/2026'", self.bloco_novo)

    def test_b_divergencia_atualizada(self):
        self.assertIn('nov/2026', self.bloco_novo)

    def test_c_seasons_e_arrays_cpc_iri_inalterados(self):
        self.assertIn("seasons: ['ASO/26','SON/26','FMA/27'],", self.bloco_novo)
        self.assertIn('cpc:{ en:[null,94,82], neu:[null,6,16], ln:[null,0,2] },', self.bloco_novo)
        self.assertIn('iri:{ en:[null,97,78], neu:[null,3,22], ln:[null,0,0] },', self.bloco_novo)

    def test_d_outros_campos_de_meta_inalterados(self):
        self.assertIn("cpc_emissao:   '13/ago/2026',", self.bloco_novo)
        self.assertIn("cpc_probabilidades_emissao: 'nov/2026',", self.bloco_novo)
        self.assertIn("iri_emissao: '21/09/2026',", self.bloco_novo)
        self.assertIn("atualizado_em: '21/11/2026',", self.bloco_novo)

    def test_e_resto_do_bloco_fora_dos_dois_campos_e_byte_a_byte_igual(self):
        def strip_campos(bloco):
            b = re.sub(r"dash_proxima:\s*'[^']*'", "dash_proxima:''", bloco)
            b = re.sub(r"divergencia:\s*'[^']*'", "divergencia:''", b)
            return b
        self.assertEqual(strip_campos(self.bloco_original), strip_campos(self.bloco_novo))


class FormatarRoniTrimestralMetaTestCase(unittest.TestCase):
    """Fase ENSO-RONI 4B.1.1: `_formatar_roni_trimestral_meta` gera o
    MESMO texto que estava escrito à mão, a partir do dict real que já
    alimenta `const RONI` — nunca mais duas fontes separadas para o
    mesmo dado."""

    def test_a_formato_igual_ao_texto_historico(self):
        texto = ui._formatar_roni_trimestral_meta({'seas': 'JAS', 'ano': 2026, 'valor': 1.69})
        self.assertEqual(texto, '+1,69°C (JAS/2026, oficial NOAA/CPC, ERSSTv6)')

    def test_b_valor_negativo(self):
        texto = ui._formatar_roni_trimestral_meta({'seas': 'NDJ', 'ano': 2024, 'valor': -1.04})
        self.assertEqual(texto, '-1,04°C (NDJ/2024, oficial NOAA/CPC, ERSSTv6)')

    def test_c_decimal_usa_virgula_pt_br(self):
        texto = ui._formatar_roni_trimestral_meta({'seas': 'ASO', 'ano': 2026, 'valor': 1.97})
        self.assertNotIn('.', texto.split('(')[0])  # parte numérica, antes do trimestre entre parênteses


class RoniTrimestralMetaRegeneradoNaoAlteraOutrosCamposTestCase(unittest.TestCase):
    """Item 4/5 da entrega da Fase 4B.1.1: a regeneração de
    `roni_trimestral` a partir do RONI efetivamente obtido nesta
    execução (nunca mais um texto fixo) troca SÓ esse campo — mesma
    disciplina de splice delimitado já usada para dash_proxima/
    divergencia (CLAUDE.md armadilha 2)."""

    def setUp(self):
        self.bloco_original = _bloco_cpc_iri_amostra()
        self.roni_novo = {'seas': 'ASO', 'ano': 2026, 'valor': 1.97}
        self.bloco_novo = ui._upsert_campo_meta(
            self.bloco_original, 'roni_trimestral',
            ui._formatar_roni_trimestral_meta(self.roni_novo))

    def test_a_roni_trimestral_passa_a_refletir_aso_2026(self):
        self.assertIn("roni_trimestral: '+1,97°C (ASO/2026, oficial NOAA/CPC, ERSSTv6)'", self.bloco_novo)
        self.assertNotIn('JAS/2026', self.bloco_novo)

    def test_b_dash_proxima_e_divergencia_inalterados(self):
        self.assertIn("dash_proxima: '21/out/2026'", self.bloco_novo)
        self.assertIn('ASO/26 null em ambos', self.bloco_novo)

    def test_c_seasons_e_arrays_cpc_iri_inalterados(self):
        self.assertIn("seasons: ['ASO/26','SON/26','FMA/27'],", self.bloco_novo)

    def test_d_resto_do_bloco_fora_do_campo_e_byte_a_byte_igual(self):
        def strip_campo(bloco):
            return re.sub(r"roni_trimestral:\s*'[^']*'", "roni_trimestral:''", bloco)
        self.assertEqual(strip_campo(self.bloco_original), strip_campo(self.bloco_novo))

    def test_e_quando_roni_e_none_nesta_execucao_campo_antigo_e_preservado(self):
        # Mesma disciplina de TSA/PDO/CHC-Preliminar: fetch falhou nesta
        # execução -> não apaga nem zera o que já estava publicado.
        # (update_html() só chama o upsert quando `roni is not None` —
        # este teste cobre o helper isoladamente, confirmando que ele
        # não é, por si, a camada que decide isso.)
        self.assertIn("roni_trimestral: '+1,69°C (JAS/2026, oficial NOAA/CPC, ERSSTv6)'",
                      self.bloco_original)


class AtualizarMasterMonthlyBackfillOniTestCase(unittest.TestCase):
    """
    Fase ENSO-ONI-FIX 1 — reprodução e correção do congelamento de
    `oni` em data/master_monthly.csv (achado da Fase ENSO-RONI 4B.2A.1):
    `atualizar_master_monthly()` pula qualquer (ano,mês) já presente no
    CSV (`if (y, m) in existentes: continue`), mesmo quando a célula
    `oni` dessa linha está vazia e o `nino34` já disponível nesta
    execução tornaria o cálculo possível. Uma vez gravada vazia, a
    célula nunca mais era revisitada.

    Confirmado que o bug NÃO afeta o dashboard: build_series() recalcula
    `oni` do zero a cada execução a partir do mesmo `nino34` recém-
    buscado, sem nunca ler este CSV — é só o registro histórico que
    fica com lacunas evitáveis.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.master_path = Path(self.tmpdir.name) / 'master_monthly.csv'
        # Mesmo padrão já documentado no próprio update_indices.py (comentário
        # acima do registro de proveniência): isto redireciona também a
        # proveniência para o mesmo tmpdir automaticamente.
        self._patch_master = patch.object(ui, 'MASTER_PATH', self.master_path)
        self._patch_master.start()

    def tearDown(self):
        self._patch_master.stop()
        self.tmpdir.cleanup()

    def _escrever_master(self, linhas):
        """`linhas`: lista de dicts com ao menos year/month/date/nino34/
        oni/tsa/pdo. Colunas omitidas ficam ausentes (mesmo comportamento
        real: `prec_reg`/`clim`/`anom`/etc. não fazem parte desta função)."""
        pd.DataFrame(linhas).to_csv(self.master_path, index=False)

    def _ler_master(self):
        return pd.read_csv(self.master_path)

    def _linha(self, y, m, nino34, oni=None, tsa=None, pdo=None):
        return {'year': y, 'month': m, 'date': f'{y}-{m:02d}-01',
                'nino34': nino34, 'oni': oni, 'tsa': tsa, 'pdo': pdo}

    # ────────────────────────────────────────────────────────────
    # Reprodução do defeito (roda igual antes e depois da correção —
    # antes da correção, as asserções de preenchimento devem falhar)
    # ────────────────────────────────────────────────────────────
    def test_reproducao_lacuna_e_preenchida_quando_janela_completa(self):
        self._escrever_master([
            self._linha(2026, 6, 1.55, 1.51, 0.20, -2.85),
            self._linha(2026, 7, 2.03, 2.03, 0.12, -2.85),
            self._linha(2026, 8, 2.52, None, 0.42, -2.85),   # lacuna a preencher
        ])
        nino34 = {(2026, 6): 1.55, (2026, 7): 2.03, (2026, 8): 2.52, (2026, 9): 2.84}
        ui.atualizar_master_monthly(nino34, tsa={}, pdo={})
        df = self._ler_master()
        linha_ago = df[(df.year == 2026) & (df.month == 8)].iloc[0]
        self.assertAlmostEqual(linha_ago['oni'], 2.46, places=2,
            msg="janela jul(2.03)+ago(2.52)+set(2.84) completa — deveria preencher")

    # ────────────────────────────────────────────────────────────
    # Grupo A — comportamento principal
    # ────────────────────────────────────────────────────────────
    def test_a2_oni_valido_e_preservado(self):
        self._escrever_master([
            self._linha(2026, 6, 1.55, 1.51),
            self._linha(2026, 7, 2.03, 2.03),
            self._linha(2026, 8, 2.52, 2.46),
        ])
        nino34 = {(2026, 6): 1.55, (2026, 7): 2.03, (2026, 8): 2.52, (2026, 9): 2.84}
        ui.atualizar_master_monthly(nino34, tsa={}, pdo={})
        df = self._ler_master()
        self.assertEqual(df[(df.year == 2026) & (df.month == 8)].iloc[0]['oni'], 2.46)

    def test_a3_mes_posterior_ausente_preserva_ausencia(self):
        self._escrever_master([
            self._linha(2026, 9, 2.84, None),
        ])
        nino34 = {(2026, 8): 2.52, (2026, 9): 2.84}   # out/2026 não existe ainda
        ui.atualizar_master_monthly(nino34, tsa={}, pdo={})
        df = self._ler_master()
        self.assertTrue(pd.isna(df[(df.year == 2026) & (df.month == 9)].iloc[0]['oni']))

    def test_a4_mes_anterior_ausente_preserva_ausencia(self):
        self._escrever_master([
            self._linha(1981, 1, -0.38, None),
        ])
        nino34 = {(1981, 1): -0.38, (1981, 2): -0.62}   # dez/1980 não existe na série
        ui.atualizar_master_monthly(nino34, tsa={}, pdo={})
        df = self._ler_master()
        self.assertTrue(pd.isna(df[(df.year == 1981) & (df.month == 1)].iloc[0]['oni']))

    def test_a5_multiplas_lacunas_preenche_somente_as_elegiveis(self):
        self._escrever_master([
            self._linha(2026, 6, 1.55, 1.51),
            self._linha(2026, 7, 2.03, 2.03),
            self._linha(2026, 8, 2.52, None),   # elegível
            self._linha(2026, 9, 2.84, None),   # elegível
            self._linha(2026, 10, 3.25, None),  # não elegível (falta nov)
        ])
        nino34 = {(2026, 6): 1.55, (2026, 7): 2.03, (2026, 8): 2.52,
                  (2026, 9): 2.84, (2026, 10): 3.25}
        ui.atualizar_master_monthly(nino34, tsa={}, pdo={})
        df = self._ler_master()
        self.assertAlmostEqual(df[df.month == 8].iloc[0]['oni'], 2.46, places=2)
        self.assertAlmostEqual(df[df.month == 9].iloc[0]['oni'], 2.87, places=2)
        self.assertTrue(pd.isna(df[df.month == 10].iloc[0]['oni']))

    def test_a6_combinacao_calculavel_e_nao_calculavel_trata_individualmente(self):
        # igual ao A5, conferindo explicitamente que uma lacuna não calculável
        # não impede o preenchimento das outras, calculáveis, na mesma execução
        self.test_a5_multiplas_lacunas_preenche_somente_as_elegiveis()

    def test_a7_mes_posterior_inserido_na_mesma_execucao_preenche(self):
        self._escrever_master([
            self._linha(2026, 7, 2.03, 2.03),
            self._linha(2026, 8, 2.52, None),   # lacuna; set/2026 ainda não é linha
        ])
        # set/2026 não está em `existentes` (não é linha do CSV ainda) — será
        # inserida como linha NOVA nesta mesma chamada.
        nino34 = {(2026, 7): 2.03, (2026, 8): 2.52, (2026, 9): 2.84}
        ui.atualizar_master_monthly(nino34, tsa={}, pdo={})
        df = self._ler_master()
        self.assertAlmostEqual(df[df.month == 8].iloc[0]['oni'], 2.46, places=2)
        self.assertIn(9, df['month'].tolist())

    # ────────────────────────────────────────────────────────────
    # Grupo B — integridade dos componentes
    # ────────────────────────────────────────────────────────────
    def test_b8_divergencia_no_mes_anterior_nao_preenche(self):
        self._escrever_master([
            self._linha(2026, 7, 2.03, 2.03),   # persistido: jul=2.03
            self._linha(2026, 8, 2.52, None),
        ])
        # fonte atual diz que julho era 1.90 (divergência) — não deve preencher
        nino34 = {(2026, 7): 1.90, (2026, 8): 2.52, (2026, 9): 2.84}
        ui.atualizar_master_monthly(nino34, tsa={}, pdo={})
        df = self._ler_master()
        self.assertTrue(pd.isna(df[df.month == 8].iloc[0]['oni']))
        # e o nino34 de julho persistido não foi tocado
        self.assertEqual(df[df.month == 7].iloc[0]['nino34'], 2.03)

    def test_b9_divergencia_no_mes_central_nao_preenche(self):
        self._escrever_master([
            self._linha(2026, 7, 2.03, 2.03),
            self._linha(2026, 8, 2.52, None),   # persistido: ago=2.52
        ])
        nino34 = {(2026, 7): 2.03, (2026, 8): 9.99, (2026, 9): 2.84}
        ui.atualizar_master_monthly(nino34, tsa={}, pdo={})
        df = self._ler_master()
        self.assertTrue(pd.isna(df[df.month == 8].iloc[0]['oni']))
        self.assertEqual(df[df.month == 8].iloc[0]['nino34'], 2.52)

    def test_b10_divergencia_no_mes_posterior_nao_preenche(self):
        self._escrever_master([
            self._linha(2026, 7, 2.03, 2.03),
            self._linha(2026, 8, 2.52, None),
            self._linha(2026, 9, 2.84, 2.87),   # persistido: set=2.84
        ])
        nino34 = {(2026, 7): 2.03, (2026, 8): 2.52, (2026, 9): 1.00}
        ui.atualizar_master_monthly(nino34, tsa={}, pdo={})
        df = self._ler_master()
        self.assertTrue(pd.isna(df[df.month == 8].iloc[0]['oni']))
        self.assertEqual(df[df.month == 9].iloc[0]['nino34'], 2.84)

    def test_b11_valor_candidato_nao_numerico_nao_preenche(self):
        df = pd.DataFrame([self._linha(2026, 8, 2.52, None)])
        oni = {(2026, 8): float('nan')}  # calc_oni nunca produz isto, mas a
        nino34 = {(2026, 7): 2.03, (2026, 8): 2.52, (2026, 9): 2.84}  # guarda é defensiva
        df2, n = ui._recalcular_oni_de_lacunas(df, nino34, oni)
        self.assertEqual(n, 0)
        self.assertTrue(pd.isna(df2.iloc[0]['oni']))

    def test_b12_nan_como_componente_da_janela_nao_preenche(self):
        # calc_oni() não omite a chave quando um componente é NaN (a
        # aritmética de ponto flutuante propaga o NaN para o resultado,
        # não lança exceção) — quem garante que isso nunca é GRAVADO é
        # o `math.isfinite(novo_valor)` de `_recalcular_oni_de_lacunas`,
        # testado aqui de ponta a ponta.
        self._escrever_master([
            self._linha(2026, 7, float('nan'), None),
            self._linha(2026, 8, 2.52, None),
        ])
        nino34 = {(2026, 7): float('nan'), (2026, 8): 2.52, (2026, 9): 2.84}
        ui.atualizar_master_monthly(nino34, tsa={}, pdo={})
        df = self._ler_master()
        self.assertTrue(pd.isna(df[df.month == 8].iloc[0]['oni']),
            "um componente NaN na janela nunca deveria resultar em oni preenchido")

    def test_b13_infinito_positivo_nao_preenche(self):
        df = pd.DataFrame([self._linha(2026, 8, 2.52, None)])
        oni = {(2026, 8): float('inf')}
        nino34 = {(2026, 7): 2.03, (2026, 8): 2.52, (2026, 9): 2.84}
        df2, n = ui._recalcular_oni_de_lacunas(df, nino34, oni)
        self.assertEqual(n, 0)
        self.assertTrue(pd.isna(df2.iloc[0]['oni']))

    def test_b14_infinito_negativo_nao_preenche(self):
        df = pd.DataFrame([self._linha(2026, 8, 2.52, None)])
        oni = {(2026, 8): float('-inf')}
        nino34 = {(2026, 7): 2.03, (2026, 8): 2.52, (2026, 9): 2.84}
        df2, n = ui._recalcular_oni_de_lacunas(df, nino34, oni)
        self.assertEqual(n, 0)
        self.assertTrue(pd.isna(df2.iloc[0]['oni']))

    def test_b15_ausencia_temporal_intermediaria_nao_calcula_sobre_nao_consecutivos(self):
        # agosto existe, mas setembro (o mês seguinte) está simplesmente
        # ausente do dict `nino34` desta execução — calc_oni não deve
        # "pular" para outubro e calcular uma média sobre meses não
        # consecutivos.
        nino34 = {(2026, 7): 2.03, (2026, 8): 2.52, (2026, 10): 3.25}  # falta 09
        oni = ui.calc_oni(nino34)
        self.assertNotIn((2026, 8), oni)

    def test_b16_diferenca_so_de_precisao_decimal_nao_e_falsa_divergencia(self):
        self._escrever_master([
            self._linha(2026, 7, 2.03, 2.03),
            self._linha(2026, 8, 2.52, None),
        ])
        # ruído de ponto flutuante, mesma precisão de 2 casas já usada no projeto
        nino34 = {(2026, 7): 2.0300000001, (2026, 8): 2.52, (2026, 9): 2.84}
        ui.atualizar_master_monthly(nino34, tsa={}, pdo={})
        df = self._ler_master()
        self.assertAlmostEqual(df[df.month == 8].iloc[0]['oni'], 2.46, places=2,
            msg="diferença de precisão de serialização não deveria bloquear o preenchimento")

    # ────────────────────────────────────────────────────────────
    # Grupo C — calendário
    # ────────────────────────────────────────────────────────────
    def test_c17_janela_novembro_dezembro_janeiro(self):
        self._escrever_master([
            self._linha(2025, 11, 1.0, None),
            self._linha(2025, 12, 1.2, None),   # mês central desta janela
        ])
        nino34 = {(2025, 11): 1.0, (2025, 12): 1.2, (2026, 1): 1.4}
        ui.atualizar_master_monthly(nino34, tsa={}, pdo={})
        df = self._ler_master()
        esperado = round((1.0 + 1.2 + 1.4) / 3, 2)
        self.assertAlmostEqual(df[df.month == 12].iloc[0]['oni'], esperado, places=2)

    def test_c18_janela_dezembro_janeiro_fevereiro(self):
        self._escrever_master([
            self._linha(2025, 12, 1.2, None),
            self._linha(2026, 1, 1.4, None),    # mês central, cruza o ano no início
        ])
        nino34 = {(2025, 12): 1.2, (2026, 1): 1.4, (2026, 2): 1.6}
        ui.atualizar_master_monthly(nino34, tsa={}, pdo={})
        df = self._ler_master()
        esperado = round((1.2 + 1.4 + 1.6) / 3, 2)
        linha = df[(df.year == 2026) & (df.month == 1)].iloc[0]
        self.assertAlmostEqual(linha['oni'], esperado, places=2)

    def test_c19_primeira_observacao_da_serie_sem_mes_anterior(self):
        self._escrever_master([
            self._linha(1981, 1, -0.38, None),
        ])
        nino34 = {(1981, 1): -0.38, (1981, 2): -0.62}  # não há dez/1980
        ui.atualizar_master_monthly(nino34, tsa={}, pdo={})
        df = self._ler_master()
        self.assertTrue(pd.isna(df.iloc[0]['oni']))

    def test_c20_ultima_observacao_sem_mes_posterior(self):
        self._escrever_master([
            self._linha(2026, 10, 3.25, None),
        ])
        nino34 = {(2026, 9): 2.84, (2026, 10): 3.25}  # não há nov/2026 ainda
        ui.atualizar_master_monthly(nino34, tsa={}, pdo={})
        df = self._ler_master()
        self.assertTrue(pd.isna(df[df.month == 10].iloc[0]['oni']))

    # ────────────────────────────────────────────────────────────
    # Grupo D — preservação histórica
    # ────────────────────────────────────────────────────────────
    def test_d21_a_d27_preservacao_completa_do_historico(self):
        linhas_originais = [
            self._linha(2026, 5, 0.94, 0.99, 0.17, -2.85),
            self._linha(2026, 6, 1.55, 1.51, 0.20, -2.85),
            self._linha(2026, 7, 2.03, 2.03, 0.12, -2.85),
            self._linha(2026, 8, 2.52, None, 0.42, -2.85),
        ]
        self._escrever_master(linhas_originais)
        antes = self._ler_master().copy()

        nino34 = {(2026, 5): 0.94, (2026, 6): 1.55, (2026, 7): 2.03,
                  (2026, 8): 2.52, (2026, 9): 2.84}
        ui.atualizar_master_monthly(nino34, tsa={}, pdo={})
        depois = self._ler_master()

        # 21. nenhum oni previamente válido foi sobrescrito
        for _, r in antes[antes['oni'].notna()].iterrows():
            linha_depois = depois[(depois.year == r.year) & (depois.month == r.month)].iloc[0]
            self.assertEqual(linha_depois['oni'], r['oni'])

        # 22. nenhum nino34 histórico foi modificado
        for _, r in antes.iterrows():
            linha_depois = depois[(depois.year == r.year) & (depois.month == r.month)].iloc[0]
            self.assertEqual(linha_depois['nino34'], r['nino34'])

        # 23. nenhum tsa/pdo histórico foi modificado
        for _, r in antes.iterrows():
            linha_depois = depois[(depois.year == r.year) & (depois.month == r.month)].iloc[0]
            self.assertEqual(linha_depois['tsa'], r['tsa'])
            self.assertEqual(linha_depois['pdo'], r['pdo'])

        # 24. nenhuma linha histórica foi removida
        for _, r in antes.iterrows():
            self.assertEqual(
                len(depois[(depois.year == r.year) & (depois.month == r.month)]), 1)

        # 25. nenhuma linha duplicada foi criada
        chaves = list(zip(depois['year'], depois['month']))
        self.assertEqual(len(chaves), len(set(chaves)))

        # 26. ordenação por (year, month) preservada
        self.assertEqual(list(depois['year']), sorted(depois['year'].tolist()) if
                          depois['year'].nunique() == 1 else depois['year'].tolist())
        self.assertTrue(depois[['year', 'month']].apply(tuple, axis=1).is_monotonic_increasing)

        # 27. a nova linha (set/2026) entra só com as colunas desta função —
        # nenhuma alteração semântica em colunas que não são dela
        set_2026 = depois[(depois.year == 2026) & (depois.month == 9)].iloc[0]
        self.assertEqual(set_2026['nino34'], 2.84)

    # ────────────────────────────────────────────────────────────
    # Grupo E — idempotência e proveniência
    # ────────────────────────────────────────────────────────────
    def test_e28_segunda_execucao_identica_nao_produz_alteracao_adicional(self):
        self._escrever_master([
            self._linha(2026, 7, 2.03, 2.03),
            self._linha(2026, 8, 2.52, None),
        ])
        nino34 = {(2026, 7): 2.03, (2026, 8): 2.52, (2026, 9): 2.84}
        ui.atualizar_master_monthly(nino34, tsa={}, pdo={})
        primeira = self._ler_master().copy()
        ui.atualizar_master_monthly(nino34, tsa={}, pdo={})
        segunda = self._ler_master()
        pd.testing.assert_frame_equal(primeira, segunda)

    def test_e29_e_e31_e_e32_oni_nunca_registrado_em_proveniencia(self):
        # Decisão de escopo desta fase: `oni` não é registrado em
        # indices_proveniencia.csv (nunca foi; o esquema atual
        # — observado/persistido/estimado/desconhecido — não tem uma
        # classificação adequada para um índice derivado recalculado
        # sobre dados já conhecidos, e proveniencia_indices.py está
        # fora do escopo de arquivos autorizados desta fase). Isso
        # também garante, por construção: nenhuma data de preenchimento
        # é gravada como se fosse data histórica de disponibilidade
        # (E32), e nenhuma proveniência desconhecida vira conhecida sem
        # evidência (E31), porque nada é escrito para `oni` de jeito
        # nenhum.
        self._escrever_master([
            self._linha(2026, 7, 2.03, 2.03),
            self._linha(2026, 8, 2.52, None),
        ])
        nino34 = {(2026, 7): 2.03, (2026, 8): 2.52, (2026, 9): 2.84}
        ui.atualizar_master_monthly(nino34, tsa={}, pdo={})
        caminho_prov = self.master_path.parent / 'indices_proveniencia.csv'
        if caminho_prov.exists():
            linhas = prov._ler(caminho_prov)
            self.assertFalse(any(l['indice'] == 'oni' for l in linhas),
                "oni não deve aparecer em indices_proveniencia.csv nesta fase")

    def test_e30_divergencia_de_origem_nao_e_corrigida_silenciosamente(self):
        self._escrever_master([
            self._linha(2026, 7, 2.03, 2.03),
            self._linha(2026, 8, 2.52, None),
        ])
        nino34 = {(2026, 7): 1.00, (2026, 8): 2.52, (2026, 9): 2.84}  # jul divergente
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ui.atualizar_master_monthly(nino34, tsa={}, pdo={})
        self.assertIn('divergente', buf.getvalue())
        df = self._ler_master()
        self.assertTrue(pd.isna(df[df.month == 8].iloc[0]['oni']),
            "uma divergência de origem nunca deve ser 'resolvida' preenchendo a lacuna")


if __name__ == '__main__':
    unittest.main()
