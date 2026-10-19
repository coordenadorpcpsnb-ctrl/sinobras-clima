#!/usr/bin/env python3
"""
tests/test_update_indices_enso_auto.py — Fase ENSO-AUTO (19/10/2026):
cobre as três adições de scripts/update_indices.py:

  1. parse_cpc_diagnostic_discussion_metadata() / atualizar_..._no_html()
     — extração SÓ de metadados estruturais do Diagnostic Discussion
     (data de emissão, próxima emissão, status categórico do Alert
     System) — nunca a Synopsis (prosa, nunca interpretada). O
     fixture abaixo é um TRECHO REAL da página, baixado e verificado
     ao vivo em 19/10/2026 (HTTP 200 confirmado deste ambiente —
     cpc.ncep.noaa.gov não está bloqueado, diferente do IRI) — os
     valores esperados (8/out/2026, El Niño Advisory, 12/nov/2026)
     batem exatamente com o que já estava hand-curado no dashboard.

  2. Guarda contra regressão de emissão em
     atualizar_cpc_probabilidades_no_html() — Seção 6 da Fase
     ENSO-AUTO ("impedir sobrescrita de uma emissão mais recente por
     outra antiga"), achado real: a função não comparava a ORDEM
     cronológica da emissão buscada contra a já gravada, só se eram
     diferentes — um fetch de página em cache/atrasada com uma emissão
     mais antiga seria aceito.

  3. verificar_mudanca_pagina_iri() — mecanismo semiautomático de
     detecção de mudança (hash do texto normalizado, nunca extração de
     dado científico) para o IRI, já que o acesso de automação segura
     a probabilidades não foi considerado viável nesta fase (ver
     relatório da Fase ENSO-AUTO).

Sem rede — tudo roda contra fixtures locais.

Roda com:
    python -m unittest tests.test_update_indices_enso_auto -v
"""

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import update_indices as ui  # noqa: E402


# Trecho REAL da página do CPC ENSO Diagnostic Discussion
# (cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml),
# baixado e verificado ao vivo em 19/10/2026 — HTTP 200 confirmado
# deste ambiente (diferente do IRI, que está bloqueado). Preservado
# tal como veio, ASCII puro (entidades HTML cruas, ex. &ntilde;).
FIXTURE_ENSODISC_REAL = r'''
						<a name="contents"></a>
						<table border="0" cellPadding="2" cellSpacing="0" align="center" width="98%" >
							<tr>
								<td>
									<font face="Verdana,arial" size="1">
									ENSO Diagnostic Discussion
									</font>
								</td>
							</tr>
							<tr><td>&nbsp;</td></tr>
							<tr>
								<td align="center">
									<font face="verdana,arial,serif" size="5">
									<strong>EL NI&Ntilde;O/SOUTHERN OSCILLATION (ENSO)</strong>
									</font>
								</td>
							</tr>
							<tr>
								<td align="center">
									<font face="verdana,arial,serif" size="5">
									<strong>DIAGNOSTIC DISCUSSION</strong>
									</font>
								</td>
							</tr>
							<tr>
								<td align="center">
									<font face="verdana,arial,serif" size="3">
									issued by<br>
									CLIMATE PREDICTION CENTER/NCEP/NWS<br>
									</font>
								</td>
							</tr>
							<tr>
								<td align="center">
									<font face="verdana,arial,serif" size="4">
																		</font>
								</td>
							</tr>
							<tr>
								<td align="center">
									<font face="verdana,arial,serif" size="4">
									8 October 2026									</font>
								</td>
							</tr>
							<tr>
								<td>&nbsp;</td>
							</tr>
							<tr>
								<td>
									<p align="center">
<font face="verdana,arial,serif" size="3">
<strong>ENSO Alert System Status: </font>
<a href="./enso-alert-readme.shtml" class="homepagelinks">
<font face="verdana,arial,serif" size="2">
<span style="color:red">El Ni&ntilde;o Advisory</span>
</strong></font></a></p>
								</td>
							</tr>
							<tr><td>&nbsp;</td></tr>
							<tr>
								<td align="justify">
									<p align="justify"><font face="verdana,arial" size="2">
<u>Synopsis:</u>&nbsp;<strong>
El Ni&ntilde;o continues to strengthen, with a strong-to-very strong El Ni&ntilde;o likely through January-March 2027 (remaining greater than an 83&#37; chance).
</strong></font></p>
									<font face="verdana,arial" size="2">
									<p>El Ni&ntilde;o strengthened further last month.</p>
									<p>The next step is irrelevant to this parser.</p>
									<p align="justify">
									This discussion is a consolidated effort of NOAA. The next ENSO Diagnostics Discussion is scheduled for 12 November 2026.  <br><br>To receive an e-mail notification, send a message.
									</p>
									</font>
								</td>
							</tr>
							<tr><td>&nbsp;</td></tr>
'''


class DataEnParaPtTestCase(unittest.TestCase):

    def test_a_formato_padrao(self):
        self.assertEqual(ui._data_en_para_pt('8 October 2026'), '8/out/2026')

    def test_b_dia_de_dois_digitos(self):
        self.assertEqual(ui._data_en_para_pt('12 November 2026'), '12/nov/2026')

    def test_c_mes_nao_reconhecido_retorna_none(self):
        self.assertIsNone(ui._data_en_para_pt('8 Octubre 2026'))

    def test_d_texto_vazio_retorna_none(self):
        self.assertIsNone(ui._data_en_para_pt(''))


class ParseCpcDiagnosticDiscussionMetadataTestCase(unittest.TestCase):

    def test_a_extrai_os_3_campos_do_fixture_real(self):
        meta = ui.parse_cpc_diagnostic_discussion_metadata(FIXTURE_ENSODISC_REAL)
        self.assertEqual(meta.get('emissao'), '8/out/2026')
        self.assertEqual(meta.get('proxima'), '12/nov/2026')
        self.assertEqual(meta.get('alert_status'), 'El Niño Advisory')

    def test_b_decodifica_entidade_html_do_status(self):
        meta = ui.parse_cpc_diagnostic_discussion_metadata(FIXTURE_ENSODISC_REAL)
        self.assertNotIn('&ntilde;', meta['alert_status'])
        self.assertIn('ñ', meta['alert_status'])

    def test_c_nunca_extrai_a_synopsis(self):
        meta = ui.parse_cpc_diagnostic_discussion_metadata(FIXTURE_ENSODISC_REAL)
        texto_completo = ' '.join(str(v) for v in meta.values())
        self.assertNotIn('strengthen', texto_completo)
        self.assertNotIn('83', texto_completo)

    def test_d_pagina_vazia_retorna_vazio(self):
        self.assertEqual(ui.parse_cpc_diagnostic_discussion_metadata(''), {})

    def test_e_estrutura_mudou_cada_campo_falha_separadamente(self):
        html = '<html><body>nada reconhecível aqui</body></html>'
        self.assertEqual(ui.parse_cpc_diagnostic_discussion_metadata(html), {})

    def test_f_so_emissao_presente_data_quebrada_nos_outros(self):
        html = (
            'CLIMATE PREDICTION CENTER/NCEP/NWS<br>'
            '<font size="4">8 October 2026</font>'
        )
        meta = ui.parse_cpc_diagnostic_discussion_metadata(html)
        self.assertEqual(meta.get('emissao'), '8/out/2026')
        self.assertNotIn('proxima', meta)
        self.assertNotIn('alert_status', meta)


class DataPtParaDateTestCase(unittest.TestCase):

    def test_a_formato_padrao(self):
        self.assertEqual(ui._data_pt_para_date('8/out/2026'), date(2026, 10, 8))

    def test_b_none_para_texto_vazio(self):
        self.assertIsNone(ui._data_pt_para_date(''))
        self.assertIsNone(ui._data_pt_para_date(None))

    def test_c_mes_nao_reconhecido(self):
        self.assertIsNone(ui._data_pt_para_date('8/xyz/2026'))

    def test_d_dia_invalido_para_o_mes(self):
        self.assertIsNone(ui._data_pt_para_date('31/fev/2026'))


class AtualizarCpcDiagnosticDiscussionMetadataNoHtmlTestCase(unittest.TestCase):

    def _html_base(self, cpc_emissao='8/out/2026', proxima='12/nov/2026',
                   alert_status='El Niño Advisory'):
        return (
            "const CPC_IRI = {\n"
            "  _meta: {\n"
            f"    cpc_emissao:   '{cpc_emissao}',\n"
            f"    cpc_proxima:   '{proxima}',\n"
            f"    cpc_alert_status: '{alert_status}',\n"
            "    cpc_status:    'El Niño Advisory — frase manual rica',\n"
            "  },\n"
            "  seasons: ['ASO/26'],\n"
            "};\n"
        )

    def test_a_grava_quando_nao_ha_emissao_anterior(self):
        html = "const CPC_IRI = {\n  _meta: {\n  },\n};\n"
        novo, mudou = ui.atualizar_cpc_diagnostic_discussion_metadata_no_html(
            html, {'emissao': '8/out/2026', 'proxima': '12/nov/2026', 'alert_status': 'El Niño Advisory'})
        self.assertTrue(mudou)
        self.assertIn("cpc_emissao: '8/out/2026'", novo)
        self.assertIn("cpc_proxima: '12/nov/2026'", novo)
        self.assertIn("cpc_alert_status: 'El Niño Advisory'", novo)

    def test_b_idempotente_mesma_emissao_nao_reescreve(self):
        html = self._html_base()
        novo, mudou = ui.atualizar_cpc_diagnostic_discussion_metadata_no_html(
            html, {'emissao': '8/out/2026', 'proxima': '12/nov/2026', 'alert_status': 'El Niño Advisory'})
        self.assertFalse(mudou)

    def test_b2_mesma_emissao_mas_campos_novos_ainda_ausentes_grava(self):
        """Achado real: emissão já bate, mas cpc_alert_status/cpc_proxima
        (novos nesta fase) nunca foram gravados — não pode ficar
        ausente indefinidamente só porque a emissão não avançou."""
        html = (
            "const CPC_IRI = {\n  _meta: {\n"
            "    cpc_emissao:   '8/out/2026',\n"
            "  },\n  seasons: ['ASO/26'],\n};\n"
        )
        novo, mudou = ui.atualizar_cpc_diagnostic_discussion_metadata_no_html(
            html, {'emissao': '8/out/2026', 'proxima': '12/nov/2026', 'alert_status': 'El Niño Advisory'})
        self.assertTrue(mudou)
        self.assertIn("cpc_alert_status: 'El Niño Advisory'", novo)
        self.assertIn("cpc_proxima: '12/nov/2026'", novo)

    def test_c_avanca_para_emissao_mais_nova(self):
        html = self._html_base()
        novo, mudou = ui.atualizar_cpc_diagnostic_discussion_metadata_no_html(
            html, {'emissao': '12/nov/2026', 'proxima': '10/dez/2026', 'alert_status': 'El Niño Watch'})
        self.assertTrue(mudou)
        self.assertIn("cpc_emissao: '12/nov/2026'", novo)

    def test_d_nunca_regride_para_emissao_mais_antiga(self):
        html = self._html_base()  # já em 8/out/2026
        novo, mudou = ui.atualizar_cpc_diagnostic_discussion_metadata_no_html(
            html, {'emissao': '8/set/2026', 'proxima': '8/out/2026', 'alert_status': 'El Niño Watch'})
        self.assertFalse(mudou)
        self.assertEqual(novo, html)

    def test_e_nunca_toca_cpc_status_a_frase_manual_rica(self):
        html = self._html_base()
        novo, mudou = ui.atualizar_cpc_diagnostic_discussion_metadata_no_html(
            html, {'emissao': '12/nov/2026', 'alert_status': 'El Niño Watch'})
        self.assertIn("cpc_status:    'El Niño Advisory — frase manual rica'", novo)

    def test_f_sem_emissao_no_dict_nao_faz_nada(self):
        html = self._html_base()
        novo, mudou = ui.atualizar_cpc_diagnostic_discussion_metadata_no_html(
            html, {'alert_status': 'El Niño Watch'})
        self.assertFalse(mudou)
        self.assertEqual(novo, html)

    def test_g_dict_vazio_nao_faz_nada(self):
        html = self._html_base()
        novo, mudou = ui.atualizar_cpc_diagnostic_discussion_metadata_no_html(html, {})
        self.assertFalse(mudou)


class MesAnoPtParaTuplaTestCase(unittest.TestCase):

    def test_a_formato_padrao(self):
        self.assertEqual(ui._mes_ano_pt_para_tupla('out/2026'), (2026, 10))

    def test_b_none_para_vazio(self):
        self.assertIsNone(ui._mes_ano_pt_para_tupla(''))
        self.assertIsNone(ui._mes_ano_pt_para_tupla(None))

    def test_c_mes_nao_reconhecido(self):
        self.assertIsNone(ui._mes_ano_pt_para_tupla('xyz/2026'))

    def test_d_comparacao_cronologica_funciona(self):
        self.assertLess(ui._mes_ano_pt_para_tupla('out/2026'), ui._mes_ano_pt_para_tupla('nov/2026'))
        self.assertLess(ui._mes_ano_pt_para_tupla('dez/2026'), ui._mes_ano_pt_para_tupla('jan/2027'))


class RegressaoEmissaoCpcProbabilidadesTestCase(unittest.TestCase):
    """Seção 6 da Fase ENSO-AUTO: achado real — a função aceitava
    qualquer emissão DIFERENTE da já gravada, sem checar se era mais
    recente ou mais antiga."""

    def _html_base(self):
        return (
            "const CPC_IRI = {\n"
            "  _meta: {\n"
            "    cpc_probabilidades_emissao: 'nov/2026',\n"
            "  },\n"
            "  seasons: ['ASO/26','SON/26'],\n"
            "  cpc:{ en:[80.0,90.0], neu:[10.0,5.0], ln:[10.0,5.0] },\n"
            "};\n"
        )

    def test_a_emissao_mais_antiga_e_rejeitada(self):
        html = self._html_base()
        probs = {'ASO/26': {'en': 70, 'neu': 20, 'ln': 10},
                 'SON/26': {'en': 85, 'neu': 10, 'ln': 5}}
        novo, mudou = ui.atualizar_cpc_probabilidades_no_html(html, probs, emissao='out/2026')
        self.assertFalse(mudou)
        self.assertEqual(novo, html)

    def test_b_emissao_mais_nova_e_aceita(self):
        html = self._html_base()
        probs = {'ASO/26': {'en': 60, 'neu': 20, 'ln': 20},
                 'SON/26': {'en': 75, 'neu': 15, 'ln': 10}}
        novo, mudou = ui.atualizar_cpc_probabilidades_no_html(html, probs, emissao='dez/2026')
        self.assertTrue(mudou)
        self.assertIn("cpc_probabilidades_emissao: 'dez/2026'", novo)

    def test_c_mesma_emissao_com_valores_iguais_e_idempotente(self):
        html = self._html_base()
        probs = {'ASO/26': {'en': 80.0, 'neu': 10.0, 'ln': 10.0},
                 'SON/26': {'en': 90.0, 'neu': 5.0, 'ln': 5.0}}
        novo, mudou = ui.atualizar_cpc_probabilidades_no_html(html, probs, emissao='nov/2026')
        self.assertFalse(mudou)

    def test_d_sem_emissao_anterior_gravada_qualquer_emissao_e_aceita(self):
        html = (
            "const CPC_IRI = {\n  _meta: {\n  },\n"
            "  seasons: ['ASO/26'],\n  cpc:{ en:[80], neu:[10], ln:[10] },\n};\n"
        )
        probs = {'ASO/26': {'en': 70, 'neu': 20, 'ln': 10}}
        novo, mudou = ui.atualizar_cpc_probabilidades_no_html(html, probs, emissao='jan/2020')
        self.assertTrue(mudou)


class NormalizarTextoHtmlTestCase(unittest.TestCase):

    def test_a_remove_tags(self):
        self.assertEqual(ui._normalizar_texto_html('<p>oi <b>mundo</b></p>'), 'oi mundo')

    def test_b_colapsa_espaco_redundante(self):
        self.assertEqual(ui._normalizar_texto_html('a   \n\n  b'), 'a b')

    def test_c_remove_script(self):
        self.assertEqual(ui._normalizar_texto_html('<p>a</p><script>malicious()</script><p>b</p>'), 'a b')

    def test_d_reformatacao_cosmetica_produz_mesmo_resultado(self):
        a = ui._normalizar_texto_html('<div>  texto   aqui  </div>')
        b = ui._normalizar_texto_html('<div>\ntexto\naqui\n</div>')
        self.assertEqual(a, b)


class VerificarMudancaPaginaIriTestCase(unittest.TestCase):

    PAGINA_A = '<html><body>' + 'conteúdo da página versão A. ' * 60 + '</body></html>'
    PAGINA_B = '<html><body>' + 'conteúdo da página versão B diferente. ' * 60 + '</body></html>'

    def test_a_primeira_execucao_grava_hash_mas_nao_reporta_mudanca(self):
        hash_novo, mudou = ui.verificar_mudanca_pagina_iri(self.PAGINA_A, None)
        self.assertIsNotNone(hash_novo)
        self.assertFalse(mudou)

    def test_b_mesmo_conteudo_nao_reporta_mudanca(self):
        hash_a, _ = ui.verificar_mudanca_pagina_iri(self.PAGINA_A, None)
        hash_b, mudou = ui.verificar_mudanca_pagina_iri(self.PAGINA_A, hash_a)
        self.assertEqual(hash_a, hash_b)
        self.assertFalse(mudou)

    def test_c_conteudo_diferente_reporta_mudanca(self):
        hash_a, _ = ui.verificar_mudanca_pagina_iri(self.PAGINA_A, None)
        hash_b, mudou = ui.verificar_mudanca_pagina_iri(self.PAGINA_B, hash_a)
        self.assertNotEqual(hash_a, hash_b)
        self.assertTrue(mudou)

    def test_d_reformatacao_cosmetica_nao_conta_como_mudanca(self):
        hash_a, _ = ui.verificar_mudanca_pagina_iri(self.PAGINA_A, None)
        pagina_reformatada = self.PAGINA_A.replace(' ', '\n   ')
        hash_b, mudou = ui.verificar_mudanca_pagina_iri(pagina_reformatada, hash_a)
        self.assertFalse(mudou)

    def test_e_falha_de_rede_html_none_preserva_hash_sem_reportar_mudanca(self):
        hash_resultado, mudou = ui.verificar_mudanca_pagina_iri(None, 'hash-anterior-qualquer')
        self.assertEqual(hash_resultado, 'hash-anterior-qualquer')
        self.assertFalse(mudou)

    def test_f_pagina_vazia_tratada_como_falha(self):
        hash_resultado, mudou = ui.verificar_mudanca_pagina_iri('', 'hash-anterior')
        self.assertEqual(hash_resultado, 'hash-anterior')
        self.assertFalse(mudou)

    def test_g_pagina_truncada_abaixo_do_minimo_tratada_como_falha(self):
        pagina_curta = '<html>erro 503</html>'
        hash_resultado, mudou = ui.verificar_mudanca_pagina_iri(pagina_curta, 'hash-anterior')
        self.assertEqual(hash_resultado, 'hash-anterior')
        self.assertFalse(mudou)

    def test_h_nunca_extrai_nenhum_valor_numerico_so_hash(self):
        hash_novo, _ = ui.verificar_mudanca_pagina_iri(self.PAGINA_A, None)
        self.assertIsInstance(hash_novo, str)
        self.assertEqual(len(hash_novo), 64)  # sha256 hexdigest


if __name__ == '__main__':
    unittest.main()
