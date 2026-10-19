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
    recente ou mais antiga. 'FMA/27'/'MAM/27' (não 'ASO/26'/'SON/26')
    porque precisam continuar alcançáveis a partir de out/2026,
    nov/2026 E dez/2026 andando sequencialmente (Correção 1, 2ª
    rodada: emissão precisa ser consistente com os trimestres do
    documento) — confirmado com `ui._MES_CENTRAL_PARA_SIGLA` antes de
    escrever o fixture, não assumido."""

    def _html_base(self):
        return (
            "const CPC_IRI = {\n"
            "  _meta: {\n"
            "    cpc_probabilidades_emissao: 'nov/2026',\n"
            "  },\n"
            "  seasons: ['FMA/27','MAM/27'],\n"
            "  cpc:{ en:[80.0,90.0], neu:[10.0,5.0], ln:[10.0,5.0] },\n"
            "};\n"
        )

    def test_a_emissao_mais_antiga_e_rejeitada(self):
        html = self._html_base()
        probs = {'FMA/27': {'en': 70, 'neu': 20, 'ln': 10},
                 'MAM/27': {'en': 85, 'neu': 10, 'ln': 5}}
        novo, mudou = ui.atualizar_cpc_probabilidades_no_html(html, probs, emissao='out/2026')
        self.assertFalse(mudou)
        self.assertEqual(novo, html)

    def test_b_emissao_mais_nova_e_aceita(self):
        html = self._html_base()
        probs = {'FMA/27': {'en': 60, 'neu': 20, 'ln': 20},
                 'MAM/27': {'en': 75, 'neu': 15, 'ln': 10}}
        novo, mudou = ui.atualizar_cpc_probabilidades_no_html(html, probs, emissao='dez/2026')
        self.assertTrue(mudou)
        self.assertIn("cpc_probabilidades_emissao: 'dez/2026'", novo)

    def test_c_mesma_emissao_com_valores_iguais_e_idempotente(self):
        html = self._html_base()
        probs = {'FMA/27': {'en': 80.0, 'neu': 10.0, 'ln': 10.0},
                 'MAM/27': {'en': 90.0, 'neu': 5.0, 'ln': 5.0}}
        novo, mudou = ui.atualizar_cpc_probabilidades_no_html(html, probs, emissao='nov/2026')
        self.assertFalse(mudou)

    def test_d_sem_emissao_anterior_gravada_qualquer_emissao_consistente_e_aceita(self):
        html = (
            "const CPC_IRI = {\n  _meta: {\n  },\n"
            "  seasons: ['FMA/20'],\n  cpc:{ en:[80], neu:[10], ln:[10] },\n};\n"
        )
        probs = {'FMA/20': {'en': 70, 'neu': 20, 'ln': 10}}
        novo, mudou = ui.atualizar_cpc_probabilidades_no_html(html, probs, emissao='jan/2020')
        self.assertTrue(mudou)


class ValidacaoObrigatoriaEmissaoCpcTestCase(unittest.TestCase):
    """Correção 1 (revisão externa, 3ª rodada) — os 7 cenários
    explicitamente pedidos para `atualizar_cpc_probabilidades_no_html`.
    Comportamento fail-safe: em qualquer caso inconclusivo, preserva
    os valores anteriores (retorna (html, False))."""

    def _html_base(self, cpc_emissao_atual="'nov/2026'"):
        meta = f"    cpc_probabilidades_emissao: {cpc_emissao_atual},\n" if cpc_emissao_atual else ""
        return (
            "const CPC_IRI = {\n"
            f"  _meta: {{\n{meta}  }},\n"
            "  seasons: ['FMA/27','MAM/27'],\n"
            "  cpc:{ en:[80.0,90.0], neu:[10.0,5.0], ln:[10.0,5.0] },\n"
            "};\n"
        )

    def test_1_emissao_ausente_preserva_valores_anteriores(self):
        html = self._html_base()
        probs = {'FMA/27': {'en': 60, 'neu': 20, 'ln': 20}}
        novo, mudou = ui.atualizar_cpc_probabilidades_no_html(html, probs, emissao=None)
        self.assertFalse(mudou)
        self.assertEqual(novo, html)

    def test_2_emissao_invalida_preserva_valores_anteriores(self):
        html = self._html_base()
        probs = {'FMA/27': {'en': 60, 'neu': 20, 'ln': 20}}
        for emissao_invalida in ('', 'lixo', '32/2026', 'fev-2026', 'xyz/2026'):
            with self.subTest(emissao=emissao_invalida):
                novo, mudou = ui.atualizar_cpc_probabilidades_no_html(
                    html, probs, emissao=emissao_invalida)
                self.assertFalse(mudou)
                self.assertEqual(novo, html)

    def test_3_emissao_mais_antiga_preserva_valores_anteriores(self):
        html = self._html_base()
        probs = {'FMA/27': {'en': 60, 'neu': 20, 'ln': 20},
                 'MAM/27': {'en': 70, 'neu': 15, 'ln': 15}}
        novo, mudou = ui.atualizar_cpc_probabilidades_no_html(html, probs, emissao='out/2026')
        self.assertFalse(mudou)
        self.assertEqual(novo, html)

    def test_4_emissao_identica_mas_valor_diferente_atualiza_so_o_valor(self):
        html = self._html_base()
        probs = {'FMA/27': {'en': 99.0, 'neu': 1.0, 'ln': 0.0},
                 'MAM/27': {'en': 90.0, 'neu': 5.0, 'ln': 5.0}}
        novo, mudou = ui.atualizar_cpc_probabilidades_no_html(html, probs, emissao='nov/2026')
        self.assertTrue(mudou)
        self.assertIn("cpc_probabilidades_emissao: 'nov/2026'", novo)
        self.assertIn('99.0', novo)

    def test_5_emissao_nova_e_valida_atualiza(self):
        html = self._html_base()
        probs = {'FMA/27': {'en': 60, 'neu': 20, 'ln': 20},
                 'MAM/27': {'en': 70, 'neu': 15, 'ln': 15}}
        novo, mudou = ui.atualizar_cpc_probabilidades_no_html(html, probs, emissao='dez/2026')
        self.assertTrue(mudou)

    def test_6_dados_parciais_com_emissao_valida_sao_aceitos(self):
        """Só FMA/27 presente na tabela (MAM/27 ainda não publicado
        nesta emissão) — trimestre ausente vira null, documento inteiro
        não é rejeitado por isso."""
        html = self._html_base()
        probs = {'FMA/27': {'en': 60, 'neu': 20, 'ln': 20}}
        novo, mudou = ui.atualizar_cpc_probabilidades_no_html(html, probs, emissao='dez/2026')
        self.assertTrue(mudou)
        self.assertIn("cpc:{ en:[60,null]", novo)

    def test_7_falha_da_fonte_probabilidades_vazio_preserva(self):
        html = self._html_base()
        novo, mudou = ui.atualizar_cpc_probabilidades_no_html(html, {}, emissao='dez/2026')
        self.assertFalse(mudou)
        self.assertEqual(novo, html)

    def test_7b_alteracao_de_estrutura_sem_trimestre_reconhecivel_preserva(self):
        """'Alteração de estrutura' simulada: a tabela veio com uma
        sigla que não existe em `_MES_CENTRAL_PARA_SIGLA` (a função de
        parsing já teria descartado isso antes de chegar aqui — esta
        checagem é uma segunda barreira, nunca confiando que o dict
        recebido já está limpo)."""
        html = self._html_base()
        probs = {'XXX/27': {'en': 60, 'neu': 20, 'ln': 20}}
        novo, mudou = ui.atualizar_cpc_probabilidades_no_html(html, probs, emissao='dez/2026')
        self.assertFalse(mudou)
        self.assertEqual(novo, html)

    def test_8_emissao_atual_gravada_em_formato_invalido_e_inconclusivo(self):
        """Seção 6: 'não é possível determinar se a emissão é mais
        antiga que a armazenada' — campo corrompido/formato inesperado
        já gravado. Precisa ser tratado como inconclusivo (preserva),
        nunca como 'está ausente, aceita qualquer coisa'."""
        html = self._html_base(cpc_emissao_atual="'10-2026-corrompido'")
        probs = {'FMA/27': {'en': 60, 'neu': 20, 'ln': 20},
                 'MAM/27': {'en': 70, 'neu': 15, 'ln': 15}}
        novo, mudou = ui.atualizar_cpc_probabilidades_no_html(html, probs, emissao='dez/2026')
        self.assertFalse(mudou)
        self.assertEqual(novo, html)

    def test_9_sem_emissao_atual_gravada_nenhuma_e_diferente_de_formato_invalido(self):
        """Contraste direto com o teste anterior: campo AUSENTE (nunca
        gravado) é a primeira execução, legitimamente aceita — não deve
        ser tratado com a mesma suspeita de um campo CORROMPIDO."""
        html = self._html_base(cpc_emissao_atual=None)
        probs = {'FMA/27': {'en': 60, 'neu': 20, 'ln': 20},
                 'MAM/27': {'en': 70, 'neu': 15, 'ln': 15}}
        novo, mudou = ui.atualizar_cpc_probabilidades_no_html(html, probs, emissao='dez/2026')
        self.assertTrue(mudou)

    def test_10_inconsistencia_entre_emissao_e_trimestres_e_rejeitada(self):
        """Seção 6: 'o documento apresenta inconsistências entre a
        identificação de emissão e os períodos de previsão' — emissão
        'mar/2026' nunca alcança FMA/27/MAM/27 andando sequencialmente
        (eles ficariam no PASSADO relativo a essa emissão)."""
        html = self._html_base()
        probs = {'FMA/27': {'en': 60, 'neu': 20, 'ln': 20},
                 'MAM/27': {'en': 70, 'neu': 15, 'ln': 15}}
        novo, mudou = ui.atualizar_cpc_probabilidades_no_html(html, probs, emissao='mar/2026')
        self.assertFalse(mudou)
        self.assertEqual(novo, html)

    def test_11_funcao_consistencia_isolada(self):
        self.assertTrue(ui._emissao_e_trimestres_consistentes(
            'out/2026', {'SON/26': {}, 'FMA/27': {}}))
        # MAM/27 fica na 14ª posição a partir de mar/2026 — fora da
        # janela de 13 trimestres (confirmado via reachable() antes de
        # escrever este teste, não assumido de cabeça).
        self.assertFalse(ui._emissao_e_trimestres_consistentes(
            'mar/2026', {'MAM/27': {}}))
        self.assertFalse(ui._emissao_e_trimestres_consistentes('lixo', {'FMA/27': {}}))


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
    """Correção 2 (revisão externa 3ª rodada): `verificar_mudanca_pagina_iri`
    retorna um ESTADO EXPLÍCITO (`ui.ESTADOS_IRI`), nunca um booleano —
    o resultado científico/operacional vem direto da função Python,
    nunca precisa ser inferido de `git diff` pelo workflow."""

    PAGINA_A = '<html><body>' + 'conteúdo da página versão A. ' * 60 + '</body></html>'
    PAGINA_B = '<html><body>' + 'conteúdo da página versão B diferente. ' * 60 + '</body></html>'

    def test_a_primeira_coleta_e_initialized_nunca_changed(self):
        hash_novo, estado = ui.verificar_mudanca_pagina_iri(self.PAGINA_A, None)
        self.assertIsNotNone(hash_novo)
        self.assertEqual(estado, 'initialized')
        self.assertNotEqual(estado, 'changed')

    def test_b_segunda_coleta_sem_mudanca_e_unchanged(self):
        hash_a, _ = ui.verificar_mudanca_pagina_iri(self.PAGINA_A, None)
        hash_b, estado = ui.verificar_mudanca_pagina_iri(self.PAGINA_A, hash_a)
        self.assertEqual(hash_a, hash_b)
        self.assertEqual(estado, 'unchanged')

    def test_c_conteudo_alterado_e_changed(self):
        hash_a, _ = ui.verificar_mudanca_pagina_iri(self.PAGINA_A, None)
        hash_b, estado = ui.verificar_mudanca_pagina_iri(self.PAGINA_B, hash_a)
        self.assertNotEqual(hash_a, hash_b)
        self.assertEqual(estado, 'changed')

    def test_d_reformatacao_cosmetica_e_unchanged_nao_changed(self):
        hash_a, _ = ui.verificar_mudanca_pagina_iri(self.PAGINA_A, None)
        pagina_reformatada = self.PAGINA_A.replace(' ', '\n   ')
        hash_b, estado = ui.verificar_mudanca_pagina_iri(pagina_reformatada, hash_a)
        self.assertEqual(estado, 'unchanged')

    def test_e_falha_de_rede_html_none_e_unavailable_preserva_hash(self):
        hash_resultado, estado = ui.verificar_mudanca_pagina_iri(None, 'hash-anterior-qualquer')
        self.assertEqual(hash_resultado, 'hash-anterior-qualquer')
        self.assertEqual(estado, 'unavailable')

    def test_f_pagina_vazia_e_unavailable(self):
        hash_resultado, estado = ui.verificar_mudanca_pagina_iri('', 'hash-anterior')
        self.assertEqual(hash_resultado, 'hash-anterior')
        self.assertEqual(estado, 'unavailable')

    def test_g_html_incompleto_truncado_e_unavailable(self):
        pagina_curta = '<html>erro 503</html>'
        hash_resultado, estado = ui.verificar_mudanca_pagina_iri(pagina_curta, 'hash-anterior')
        self.assertEqual(hash_resultado, 'hash-anterior')
        self.assertEqual(estado, 'unavailable')

    def test_h_nunca_extrai_nenhum_valor_numerico_so_hash(self):
        hash_novo, _ = ui.verificar_mudanca_pagina_iri(self.PAGINA_A, None)
        self.assertIsInstance(hash_novo, str)
        self.assertEqual(len(hash_novo), 64)  # sha256 hexdigest

    def test_i_estado_e_sempre_um_dos_4_valores_documentados(self):
        casos = [
            (self.PAGINA_A, None),
            (self.PAGINA_A, 'hash-qualquer'),
            (None, 'hash-qualquer'),
            ('', None),
        ]
        for html, hash_ant in casos:
            with self.subTest(html=bool(html), hash_anterior=hash_ant):
                _, estado = ui.verificar_mudanca_pagina_iri(html, hash_ant)
                self.assertIn(estado, ui.ESTADOS_IRI)

    def test_j_unavailable_nunca_e_confundido_com_unchanged(self):
        """'Fonte indisponível' e 'conteúdo igual ao anterior' são
        estados semanticamente diferentes — uma falha de rede nunca
        deve ser lida como confirmação de que a página não mudou."""
        _, estado_falha = ui.verificar_mudanca_pagina_iri(None, 'hash-x')
        _, estado_igual = ui.verificar_mudanca_pagina_iri(self.PAGINA_A, None)
        hash_a, _ = ui.verificar_mudanca_pagina_iri(self.PAGINA_A, None)
        _, estado_igual = ui.verificar_mudanca_pagina_iri(self.PAGINA_A, hash_a)
        self.assertEqual(estado_falha, 'unavailable')
        self.assertEqual(estado_igual, 'unchanged')
        self.assertNotEqual(estado_falha, estado_igual)


class LerGravarHashIriTestCase(unittest.TestCase):
    """Correção 2: 'presença de arquivo hash já existente' e
    'persistência do hash entre execuções', testáveis isoladamente
    (sem rodar main() inteiro) via um caminho temporário."""

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self._caminho_original = ui.IRI_HASH_PATH
        ui.IRI_HASH_PATH = Path(self._tmpdir.name) / 'subpasta' / '.iri_pagina_hash'

    def tearDown(self):
        ui.IRI_HASH_PATH = self._caminho_original
        self._tmpdir.cleanup()

    def test_a_ler_sem_arquivo_retorna_none(self):
        self.assertFalse(ui.IRI_HASH_PATH.exists())
        self.assertIsNone(ui.ler_hash_iri())

    def test_b_gravar_e_depois_ler_persiste_entre_chamadas(self):
        self.assertTrue(ui.gravar_hash_iri('abc123'))
        self.assertTrue(ui.IRI_HASH_PATH.exists())
        self.assertEqual(ui.ler_hash_iri(), 'abc123')

    def test_c_presenca_de_arquivo_ja_existente_e_lida_corretamente(self):
        # simula uma execução anterior que já deixou o arquivo gravado
        ui.IRI_HASH_PATH.parent.mkdir(parents=True, exist_ok=True)
        ui.IRI_HASH_PATH.write_text('hash-de-execucao-anterior', encoding='utf-8')
        self.assertEqual(ui.ler_hash_iri(), 'hash-de-execucao-anterior')

    def test_d_gravar_substitui_o_valor_anterior(self):
        ui.gravar_hash_iri('valor-1')
        ui.gravar_hash_iri('valor-2')
        self.assertEqual(ui.ler_hash_iri(), 'valor-2')

    def test_e_arquivo_vazio_e_tratado_como_ausente(self):
        ui.IRI_HASH_PATH.parent.mkdir(parents=True, exist_ok=True)
        ui.IRI_HASH_PATH.write_text('', encoding='utf-8')
        self.assertIsNone(ui.ler_hash_iri())

    def test_f_ciclo_completo_persistencia_entre_execucoes_simuladas(self):
        """Simula 3 'execuções' sequenciais do mecanismo, cada uma
        lendo o hash da anterior — igual ao que main() faz de verdade."""
        pagina_v1 = '<html><body>' + 'texto da versão v1 ' * 100 + '</body></html>'
        pagina_v2 = '<html><body>' + 'texto da versão v2 diferente ' * 100 + '</body></html>'

        # execução 1 — primeira coleta
        hash_1, estado_1 = ui.verificar_mudanca_pagina_iri(pagina_v1, ui.ler_hash_iri())
        self.assertEqual(estado_1, 'initialized')
        ui.gravar_hash_iri(hash_1)

        # execução 2 — mesmo conteúdo
        hash_2, estado_2 = ui.verificar_mudanca_pagina_iri(pagina_v1, ui.ler_hash_iri())
        self.assertEqual(estado_2, 'unchanged')
        self.assertEqual(hash_2, hash_1)

        # execução 3 — conteúdo mudou
        hash_3, estado_3 = ui.verificar_mudanca_pagina_iri(pagina_v2, ui.ler_hash_iri())
        self.assertEqual(estado_3, 'changed')
        ui.gravar_hash_iri(hash_3)
        self.assertEqual(ui.ler_hash_iri(), hash_3)


class EmitirOutputGithubTestCase(unittest.TestCase):
    """`_emitir_output_github` é o canal pelo qual o estado do IRI
    chega ao workflow — Correção 2: 'o resultado deve vir da função
    Python, não ser inferido exclusivamente do diff do Git'."""

    def test_a_sem_github_output_no_ambiente_nao_lanca(self):
        import os
        old = os.environ.pop('GITHUB_OUTPUT', None)
        try:
            ui._emitir_output_github('iri_estado', 'changed')  # não deve lançar
        finally:
            if old is not None:
                os.environ['GITHUB_OUTPUT'] = old

    def test_b_com_github_output_escreve_no_arquivo(self):
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            caminho = f.name
        old = os.environ.get('GITHUB_OUTPUT')
        os.environ['GITHUB_OUTPUT'] = caminho
        try:
            ui._emitir_output_github('iri_estado', 'changed')
            conteudo = Path(caminho).read_text(encoding='utf-8')
            self.assertIn('iri_estado=changed', conteudo)
        finally:
            if old is not None:
                os.environ['GITHUB_OUTPUT'] = old
            else:
                os.environ.pop('GITHUB_OUTPUT', None)
            Path(caminho).unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
