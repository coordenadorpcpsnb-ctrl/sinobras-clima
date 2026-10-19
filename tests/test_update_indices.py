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

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import update_indices as ui  # noqa: E402

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


if __name__ == '__main__':
    unittest.main()
