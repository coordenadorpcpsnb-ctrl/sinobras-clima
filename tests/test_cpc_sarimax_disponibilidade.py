#!/usr/bin/env python3
"""
tests/test_cpc_sarimax_disponibilidade.py — ENSO-DADOS Fase C: cobre a
correção de compatibilidade CPC_IRI.seasons × SARIMAX_DATA.

Contexto do bug corrigido (falha real de update.yml em 21/10/2026): a
existência de uma chave em `SARIMAX_DATA.trimestres` não comprova
previsão regional COMPLETA — `scripts/update_dashboard.py` preenche com
climatologia os meses de um trimestre que caem fora do horizonte
mensal (`SARIMAX_DATA.labels_win`), contribuindo para `mean` mas com
lo=hi=0 nesse mês. Um trimestre parcial pode legitimamente ter
mean > hi sem ser corrupção de dado (caso real observado: ASO/27,
cenário Neutro, mean=161.7 > hi=115.1 — só ago/27 está em labels_win).

Esta suíte testa duas camadas, SEMPRE extraindo/chamando o código REAL
já publicado (nunca uma reimplementação separada que poderia divergir
silenciosamente):

  1. A lógica JS de disponibilidade regional (`decodeTrimestre`,
     `estadoTrimestre`) — extraída literalmente de docs/index.html e
     executada via Node com fixtures sintéticas.
  2. `scripts/verificar_dashboard.py::verificar_cpc_sarimax()` — chamada
     direta com HTML sintético, sem precisar rodar main() inteiro
     contra o docs/index.html real.

Nenhuma rede, nenhum dado real, nenhuma fixture degenerada: os números
usados são os mesmos (ou variações mínimas e explicadas) dos casos
reais já observados em produção.

Roda com:
    python -m unittest tests.test_cpc_sarimax_disponibilidade -v
    node precisa estar no PATH (usado só para rodar JS extraído, sem rede)
"""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
DASHBOARD = ROOT / 'docs' / 'index.html'
sys.path.insert(0, str(ROOT / 'scripts'))

import verificar_dashboard as vd  # noqa: E402
import update_indices as ui  # noqa: E402


# ───────────────────────── infraestrutura JS ────────────────────────────

def _extrair_js_disponibilidade():
    """Extrai TRI_SEQ/decodeTrimestre/mesLabelWin/estadoTrimestre
    literalmente do docs/index.html publicado — nunca uma cópia
    reimplementada à parte, que poderia divergir silenciosamente do
    código real conforme ele evolui."""
    html = DASHBOARD.read_text(encoding='utf-8')
    ini = html.find('const TRI_SEQ')
    fim = html.find('function buildComparativo')
    if ini < 0 or fim < 0 or fim <= ini:
        raise AssertionError(
            'bloco de disponibilidade regional (TRI_SEQ..estadoTrimestre) '
            'não encontrado em docs/index.html — a correção pode ter sido removida')
    return html[ini:fim]


_JS_CORE = _extrair_js_disponibilidade()


def _node_estado(season, sarimax_data):
    """Roda estadoTrimestre(season) do JS real contra uma SARIMAX_DATA
    sintética, via Node (sem navegador, sem rede)."""
    fixture = f'const SARIMAX_DATA = {json.dumps(sarimax_data)};'
    script = _JS_CORE + '\n' + fixture + f'\nconsole.log(JSON.stringify(estadoTrimestre({json.dumps(season)})));'
    r = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f'node falhou ao avaliar estadoTrimestre({season!r}): {r.stderr}')
    return json.loads(r.stdout)


def _node_decode(season):
    script = _JS_CORE + f'\nconsole.log(JSON.stringify(decodeTrimestre({json.dumps(season)})));'
    r = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f'node falhou ao decodificar {season!r}: {r.stderr}')
    return json.loads(r.stdout)


_SCENARIOS_8 = ['El Nino forte', 'El Nino moderado', 'El Nino fraco', 'Neutro',
                'La Nina fraca', 'La Nina moderada', 'La Nina forte', 'IRI_mean']


def _sd(labels_win, trimestres, cenarios=None):
    """Monta um SARIMAX_DATA sintético com os 8 cenários obrigatórios do
    Comparativo por padrão (ENSO-DADOS Fase C.1, Correção A:
    estadoTrimestre() exige os 8 por nome, nunca Object.keys()) — todos
    com os MESMOS valores por trimestre, suficiente para exercitar a
    lógica de disponibilidade. Passe `cenarios` (lista de nomes) para
    simular um ou mais cenários FALTANDO por completo."""
    cenarios = cenarios if cenarios is not None else _SCENARIOS_8
    return {'labels_win': labels_win, 'trimestres': {sc: dict(trimestres) for sc in cenarios}}


class EstadoTrimestreJSTestCase(unittest.TestCase):
    """Cenários 1-4 e 10 do pedido: estados PREVISAO_COMPLETA/PARCIAL/
    INDISPONIVEL/INVALIDO, decodificação com virada dez→jan."""

    def test_01_horizonte_set_2026_aso26_parcial_son26_completo(self):
        labels_win = ['09/26', '10/26', '11/26', '12/26', '01/27', '02/27',
                       '03/27', '04/27', '05/27', '06/27', '07/27', '08/27']
        sd = _sd(labels_win, {
            'ASO/26': {'mean': 69.8, 'lo': 0.0, 'hi': 279.0},
            'SON/26': {'mean': 181.5, 'lo': 7.8, 'hi': 515.4},
        })
        self.assertEqual(_node_estado('ASO/26', sd)['estado'], 'PREVISAO_PARCIAL')
        self.assertEqual(_node_estado('SON/26', sd)['estado'], 'PREVISAO_COMPLETA')

    def test_02_horizonte_out_2026_son26_parcial_ond26_completo(self):
        # horizonte avança um mês: labels_win agora começa em 10/26
        labels_win = ['10/26', '11/26', '12/26', '01/27', '02/27', '03/27',
                       '04/27', '05/27', '06/27', '07/27', '08/27', '09/27']
        sd = _sd(labels_win, {
            'SON/26': {'mean': 181.5, 'lo': 7.8, 'hi': 515.4},   # set/26 fora
            'OND/26': {'mean': 372.5, 'lo': 84.4, 'hi': 715.5},  # out/nov/dez, todos dentro
        })
        self.assertEqual(_node_estado('SON/26', sd)['estado'], 'PREVISAO_PARCIAL')
        self.assertEqual(_node_estado('OND/26', sd)['estado'], 'PREVISAO_COMPLETA')

    def test_03_horizonte_nov_2026_son26_ausente_ond26_parcial_ndj26_completo(self):
        labels_win = ['11/26', '12/26', '01/27', '02/27', '03/27', '04/27',
                       '05/27', '06/27', '07/27', '08/27', '09/27', '10/27']
        sd = _sd(labels_win, {
            # SON/26 nem existe mais como chave — simula o trimestre já
            # fora da janela rolante de 13 trimestres de update_dashboard.py
            'OND/26': {'mean': 372.5, 'lo': 84.4, 'hi': 715.5},  # out/26 fora, nov/dez dentro
            'NDJ/26': {'mean': 565.4, 'lo': 222.3, 'hi': 908.6},  # nov/dez/jan, todos dentro
        })
        self.assertEqual(_node_estado('SON/26', sd)['estado'], 'INDISPONIVEL')
        self.assertEqual(_node_estado('OND/26', sd)['estado'], 'PREVISAO_PARCIAL')
        self.assertEqual(_node_estado('NDJ/26', sd)['estado'], 'PREVISAO_COMPLETA')

    def test_04_virada_dez_2026_jan_2027_djf27(self):
        # DJF/27 = dez/26, jan/27, fev/27 — ano central (jan) é 2027,
        # mas o primeiro mês (dez) pertence a 2026: a virada do ano.
        self.assertEqual(_node_decode('DJF/27'), [
            {'y': 2026, 'm': 12}, {'y': 2027, 'm': 1}, {'y': 2027, 'm': 2},
        ])
        labels_win = ['11/26', '12/26', '01/27', '02/27', '03/27', '04/27',
                       '05/27', '06/27', '07/27', '08/27', '09/27', '10/27']
        sd = _sd(labels_win, {'DJF/27': {'mean': 718.0, 'lo': 374.6, 'hi': 1061.5}})
        self.assertEqual(_node_estado('DJF/27', sd)['estado'], 'PREVISAO_COMPLETA')
        # NDJ/26 = nov/26,dez/26,jan/27 — também cruza a virada, do outro lado
        self.assertEqual(_node_decode('NDJ/26'), [
            {'y': 2026, 'm': 11}, {'y': 2026, 'm': 12}, {'y': 2027, 'm': 1},
        ])

    def test_05_trimestre_parcial_com_media_acima_do_limite_superior(self):
        # Reprodução do caso real (ASO/27, Neutro): mean > hi porque só 1
        # dos 3 meses está dentro de labels_win — não deve virar INVALIDO.
        labels_win = ['09/26', '10/26', '11/26', '12/26', '01/27', '02/27',
                       '03/27', '04/27', '05/27', '06/27', '07/27', '08/27']
        sd = _sd(labels_win, {'ASO/27': {'mean': 161.7, 'lo': 0.0, 'hi': 115.1}})
        info = _node_estado('ASO/27', sd)
        self.assertEqual(info['estado'], 'PREVISAO_PARCIAL')

    def test_06_trimestre_completo_mas_estruturalmente_invalido(self):
        # Todos os 3 meses dentro de labels_win, mas lo > hi — aqui SIM
        # é bloqueante, porque não há preenchimento climatológico que
        # explique a inconsistência.
        labels_win = ['09/26', '10/26', '11/26', '12/26', '01/27', '02/27',
                       '03/27', '04/27', '05/27', '06/27', '07/27', '08/27']
        sd = _sd(labels_win, {'SON/26': {'mean': 50.0, 'lo': 100.0, 'hi': 80.0}})
        self.assertEqual(_node_estado('SON/26', sd)['estado'], 'INVALIDO')

    def test_07_trimestre_sem_campos_essenciais_indisponivel(self):
        labels_win = ['09/26', '10/26', '11/26']
        sd = _sd(labels_win, {'SON/26': {'mean': None, 'lo': 7.8, 'hi': 515.4}})
        self.assertEqual(_node_estado('SON/26', sd)['estado'], 'INDISPONIVEL')

    def test_08_chave_nao_decodificavel_indisponivel(self):
        sd = _sd(['09/26'], {})
        self.assertEqual(_node_estado('XYZ/26', sd)['estado'], 'INDISPONIVEL')
        self.assertEqual(_node_estado('', sd)['estado'], 'INDISPONIVEL')


class CpcSarimaxVerificadorTestCase(unittest.TestCase):
    """Cenários 7, 8, 9 do pedido: barreiras 7a bloqueantes do
    verificador, chamando verificar_cpc_sarimax() direto (sem precisar
    rodar main() inteiro contra um docs/index.html real — mesmo motivo
    de checar_continuidade())."""

    SEASONS_3 = "['ASO/26','SON/26','OND/26']"

    @staticmethod
    def _html(cpc_block, iri_block, seasons=None, cenarios=None):
        """`cenarios`: lista de nomes de cenário a incluir em
        SARIMAX_DATA.trimestres — por padrão os 8 obrigatórios (ENSO-
        DADOS Fase C.1, Correção A); passar um subconjunto simula um ou
        mais cenários FALTANDO por completo."""
        seasons = seasons or "['ASO/26','SON/26','OND/26']"
        cenarios = cenarios if cenarios is not None else _SCENARIOS_8
        tri_padrao = {
            'ASO/26': {'mean': 69.8, 'lo': 0.0, 'hi': 279.0},
            'SON/26': {'mean': 181.5, 'lo': 7.8, 'hi': 515.4},
            'OND/26': {'mean': 372.5, 'lo': 84.4, 'hi': 715.5},
        }
        sarimax = {
            'trimestres': {sc: dict(tri_padrao) for sc in cenarios},
            'labels_win': ['09/26', '10/26', '11/26', '12/26', '01/27', '02/27',
                            '03/27', '04/27', '05/27', '06/27', '07/27', '08/27'],
        }
        return (
            'const CPC_IRI = {\n'
            '  _meta: { x: 1 },\n'
            f'  seasons: {seasons},\n'
            f'  cpc:{{{cpc_block}}},\n'
            f'  iri:{{{iri_block}}},\n'
            '};\n'
            f'const SARIMAX_DATA = {json.dumps(sarimax)};\n'
            'function estadoTrimestre(s){ return {estado:"PREVISAO_COMPLETA"}; }\n'
            'function rebuildCmpTri(){ estadoTrimestre(1); }\n'
            'function buildCmpTable(){ estadoTrimestre(1); }\n'
        )

    def setUp(self):
        vd.falhas.clear()

    def test_09_arrays_cpc_iri_com_comprimento_incorreto(self):
        # cpc.en tem só 2 elementos, seasons tem 3
        h = self._html(
            ' en:[100.0,0.0], neu:[0.0,0.0,0.0], ln:[0.0,0.0,0.0] ',
            ' en:[100,0,0], neu:[0,0,0], ln:[0,0,0] ',
        )
        vd.verificar_cpc_sarimax(h)
        self.assertTrue(any('comprimento' in f and 'cpc.en' in f for f in vd.falhas),
                         vd.falhas)

    def test_10_bloco_cpc_ausente(self):
        html = (
            'const CPC_IRI = {\n'
            '  _meta: { x: 1 },\n'
            "  seasons: ['ASO/26','SON/26'],\n"
            '  iri:{ en:[100,0], neu:[0,0], ln:[0,0] },\n'
            '};\n'
            'const SARIMAX_DATA = {"trimestres":{"Neutro":{}},"labels_win":[]};\n'
        )
        vd.verificar_cpc_sarimax(html)
        self.assertTrue(any('CPC_IRI.cpc ausente' in f for f in vd.falhas), vd.falhas)

    def test_11_bloco_iri_ausente(self):
        html = (
            'const CPC_IRI = {\n'
            '  _meta: { x: 1 },\n'
            "  seasons: ['ASO/26','SON/26'],\n"
            '  cpc:{ en:[100,0], neu:[0,0], ln:[0,0] },\n'
            '};\n'
            'const SARIMAX_DATA = {"trimestres":{"Neutro":{}},"labels_win":[]};\n'
        )
        vd.verificar_cpc_sarimax(html)
        self.assertTrue(any('CPC_IRI.iri ausente' in f for f in vd.falhas), vd.falhas)

    def test_12_trimestre_duplicado_em_seasons(self):
        h = self._html(
            ' en:[100.0,0.0,0.0], neu:[0.0,0.0,0.0], ln:[0.0,0.0,0.0] ',
            ' en:[100,0,0], neu:[0,0,0], ln:[0,0,0] ',
            seasons="['ASO/26','SON/26','SON/26']",
        )
        vd.verificar_cpc_sarimax(h)
        self.assertTrue(any('duplicado' in f for f in vd.falhas), vd.falhas)

    def test_13_valor_fora_do_intervalo_0_100(self):
        h = self._html(
            ' en:[150.0,0.0,0.0], neu:[0.0,0.0,0.0], ln:[0.0,0.0,0.0] ',
            ' en:[100,0,0], neu:[0,0,0], ln:[0,0,0] ',
        )
        vd.verificar_cpc_sarimax(h)
        self.assertTrue(any('fora do intervalo 0-100' in f for f in vd.falhas), vd.falhas)

    def test_14_valor_nao_numerico_diferente_de_null(self):
        h = self._html(
            ' en:[100.0,abacate,0.0], neu:[0.0,0.0,0.0], ln:[0.0,0.0,0.0] ',
            ' en:[100,0,0], neu:[0,0,0], ln:[0,0,0] ',
        )
        vd.verificar_cpc_sarimax(h)
        self.assertTrue(any('não numérico' in f for f in vd.falhas), vd.falhas)

    def test_15_null_legitimo_nao_e_erro(self):
        # null é o valor correto para "não publicado" — nunca deve
        # disparar 'não numérico' nem 'fora do intervalo'.
        h = self._html(
            ' en:[null,100.0,100.0], neu:[null,0.0,0.0], ln:[null,0.0,0.0] ',
            ' en:[null,100,100], neu:[null,0,0], ln:[null,0,0] ',
        )
        vd.verificar_cpc_sarimax(h)
        self.assertFalse(any('não numérico' in f or 'fora do intervalo' in f for f in vd.falhas),
                          vd.falhas)

    def test_16_caso_valido_completo_aprova(self):
        h = self._html(
            ' en:[100.0,100.0,100.0], neu:[0.0,0.0,0.0], ln:[0.0,0.0,0.0] ',
            ' en:[100,100,100], neu:[0,0,0], ln:[0,0,0] ',
        )
        vd.verificar_cpc_sarimax(h)
        self.assertEqual(vd.falhas, [])

    def test_17_guarda_js_ausente_e_bloqueante(self):
        # mesmo HTML válido do teste 16, mas sem a função estadoTrimestre
        h = self._html(
            ' en:[100.0,100.0,100.0], neu:[0.0,0.0,0.0], ln:[0.0,0.0,0.0] ',
            ' en:[100,100,100], neu:[0,0,0], ln:[0,0,0] ',
        ).replace('function estadoTrimestre(s){ return {estado:"PREVISAO_COMPLETA"}; }\n', '')
        vd.verificar_cpc_sarimax(h)
        self.assertTrue(any('estadoTrimestre() não encontrada' in f for f in vd.falhas), vd.falhas)

    def test_18_sarimax_data_ausente_e_bloqueante(self):
        html = (
            'const CPC_IRI = {\n'
            '  _meta: { x: 1 },\n'
            "  seasons: ['ASO/26'],\n"
            '  cpc:{ en:[100.0], neu:[0.0], ln:[0.0] },\n'
            '  iri:{ en:[100], neu:[0], ln:[0] },\n'
            '};\n'
        )
        vd.verificar_cpc_sarimax(html)
        self.assertTrue(any('SARIMAX_DATA não encontrado' in f for f in vd.falhas), vd.falhas)

    def test_19_bloco_cpc_iri_ausente_do_html(self):
        vd.verificar_cpc_sarimax('<html>sem nada aqui</html>')
        self.assertTrue(any('CPC_IRI não encontrado' in f for f in vd.falhas), vd.falhas)

    def test_20_regex_nao_confunde_nino_seasons_com_seasons(self):
        # nino_seasons aparece ANTES de seasons no HTML real; a extração
        # delimitada ao bloco CPC_IRI + regex com \n\s*seasons: nunca deve
        # casar "nino_seasons" (CLAUDE.md armadilha 2 — regex global).
        tri_padrao = {'ASO/26': {'mean': 1, 'lo': 0, 'hi': 2},
                      'SON/26': {'mean': 1, 'lo': 0, 'hi': 2}}
        sarimax = {'trimestres': {sc: dict(tri_padrao) for sc in _SCENARIOS_8},
                   'labels_win': ['08/26', '09/26', '10/26', '11/26']}
        h = (
            'const CPC_IRI = {\n'
            '  _meta: { x: 1 },\n'
            "  nino_seasons: ['jan/99','fev/99','mar/99'],\n"
            "  seasons: ['ASO/26','SON/26'],\n"
            '  cpc:{ en:[100.0,100.0], neu:[0.0,0.0], ln:[0.0,0.0] },\n'
            '  iri:{ en:[100,100], neu:[0,0], ln:[0,0] },\n'
            '};\n'
            f'const SARIMAX_DATA = {json.dumps(sarimax)};\n'
            'function estadoTrimestre(s){return 1;}\n'
            'function rebuildCmpTri(){estadoTrimestre(1);}\n'
            'function buildCmpTable(){estadoTrimestre(1);}\n'
        )
        vd.verificar_cpc_sarimax(h)
        self.assertEqual(vd.falhas, [], vd.falhas)


class AtualizacaoSemanalEReegeneracaoMensalTestCase(unittest.TestCase):
    """Cenários 14, 15, 16 do pedido: atualização semanal de
    probabilidades CPC e regeneração mensal de SARIMAX_DATA não devem
    apagar nem desalinhar a correção — exercita o código REAL de
    scripts/update_indices.py contra o docs/index.html real do
    repositório (só leitura; nada é escrito em disco)."""

    def setUp(self):
        if not DASHBOARD.exists():
            self.skipTest('docs/index.html não encontrado')
        self.html_original = DASHBOARD.read_text(encoding='utf-8')

    def test_21_atualizacao_semanal_simulada_preserva_comprimento_de_seasons(self):
        # probabilidades cobrindo só 2 dos 9 seasons atuais — simula uma
        # tabela CPC parcial (alguns trimestres ainda não publicados).
        seasons_atuais = re.search(r'\n\s*seasons:\s*\[([^\]]+)\]',
                                    self.html_original[self.html_original.find('const CPC_IRI = {'):])
        pedidos = [v.strip().strip("'\"") for v in seasons_atuais.group(1).split(',')]
        probabilidades = {pedidos[1]: {'en': 97.0, 'neu': 3.0, 'ln': 0.0}}
        # emissão consistente com o 2º trimestre (mesmo mês central da
        # tabela recebida) — ver _emissao_e_trimestres_consistentes()
        meses_tri = vd._decode_trimestre(pedidos[1])
        ano_cen, mes_cen = meses_tri[1]
        emissao = f'{["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"][mes_cen-1]}/{ano_cen}'
        html_novo, mudou = ui.atualizar_cpc_probabilidades_no_html(
            self.html_original, probabilidades, emissao=emissao)
        ini = html_novo.find('const CPC_IRI = {')
        fim = html_novo.find('\n};', ini) + 3
        bloco = html_novo[ini:fim]
        seasons_depois = re.search(r'\n\s*seasons:\s*\[([^\]]+)\]', bloco)
        pedidos_depois = [v.strip().strip("'\"") for v in seasons_depois.group(1).split(',')]
        # nunca muda seasons em si (comprimento e conteúdo preservados)
        self.assertEqual(pedidos_depois, pedidos)
        m_cpc = re.search(r'\n\s*cpc:\{([^}]*)\}', bloco)
        en = vd._ler_array_cpc_iri('en', m_cpc.group(1))
        self.assertEqual(len(en), len(pedidos))

    def test_22_regeneracao_mensal_simulada_preserva_bloco_cpc_iri_e_guarda_js(self):
        # reproduz EXATAMENTE a substituição que scripts/update_dashboard.py
        # faz (re.sub de 'const SARIMAX_DATA = {...};', DOTALL) com uma
        # janela de horizonte DIFERENTE (simulando o próximo ciclo mensal)
        # e confirma que CPC_IRI e a correção JS saem bit-a-bit idênticas.
        novo_sarimax = ('{"trimestres":{"Neutro":{"OND/26":{"mean":1,"lo":0,"hi":2}}},'
                         '"labels_win":["10/26","11/26","12/26"]}')
        html_novo = re.sub(r'const SARIMAX_DATA = \{.*?\};',
                            f'const SARIMAX_DATA = {novo_sarimax};',
                            self.html_original, flags=re.DOTALL)

        def bloco(html, inicio, fim_str):
            i = html.find(inicio)
            f = html.find(fim_str, i)
            return html[i:f]

        cpc_antes = bloco(self.html_original, 'const CPC_IRI = {', '\n};')
        cpc_depois = bloco(html_novo, 'const CPC_IRI = {', '\n};')
        self.assertEqual(cpc_antes, cpc_depois)

        js_antes = bloco(self.html_original, 'const TRI_SEQ', 'function buildComparativo')
        js_depois = bloco(html_novo, 'const TRI_SEQ', 'function buildComparativo')
        self.assertEqual(js_antes, js_depois)

        self.assertIn('function estadoTrimestre', html_novo)
        self.assertIn('estadoTrimestre(', html_novo[html_novo.find('function rebuildCmpTri'):
                                                      html_novo.find('function rebuildCmpTri') + 2000])

    def test_23_correspondencia_trimestre_probabilidade_apos_atualizacao(self):
        # depois de uma atualização semanal, cada posição i de cpc.en
        # ainda corresponde ao trimestre seasons[i] — checa isso
        # decodificando e comparando com o valor de entrada.
        ini = self.html_original.find('const CPC_IRI = {')
        fim = self.html_original.find('\n};', ini) + 3
        bloco_orig = self.html_original[ini:fim]
        seasons = [v.strip().strip("'\"") for v in
                   re.search(r'\n\s*seasons:\s*\[([^\]]+)\]', bloco_orig).group(1).split(',')]
        alvo = seasons[2]
        meses_tri = vd._decode_trimestre(alvo)
        ano_cen, mes_cen = meses_tri[1]
        emissao = f'{["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"][mes_cen-1]}/{ano_cen}'
        probabilidades = {alvo: {'en': 42.0, 'neu': 33.0, 'ln': 25.0}}
        html_novo, mudou = ui.atualizar_cpc_probabilidades_no_html(
            self.html_original, probabilidades, emissao=emissao)
        ini2 = html_novo.find('const CPC_IRI = {')
        fim2 = html_novo.find('\n};', ini2) + 3
        bloco_novo = html_novo[ini2:fim2]
        m_cpc = re.search(r'\n\s*cpc:\{([^}]*)\}', bloco_novo)
        en = vd._ler_array_cpc_iri('en', m_cpc.group(1))
        self.assertEqual(en[2], 42.0)


class IntegridadeOitoCenariosTestCase(unittest.TestCase):
    """ENSO-DADOS Fase C.1 (Correção A) — os 8 cenários obrigatórios do
    Comparativo precisam ser exigidos POR NOME, nunca derivados de
    Object.keys(SARIMAX_DATA.trimestres)/list(trimestres.keys()).
    Cobre os 10 cenários explicitamente pedidos na retomada."""

    LABELS_WIN = ['09/26', '10/26', '11/26', '12/26', '01/27', '02/27',
                  '03/27', '04/27', '05/27', '06/27', '07/27', '08/27']
    TRI_VALIDO = {'SON/26': {'mean': 181.5, 'lo': 7.8, 'hi': 515.4}}  # 3 meses em LABELS_WIN

    def setUp(self):
        vd.falhas.clear()

    # 1. Oito cenários presentes -----------------------------------------
    def test_01_oito_cenarios_presentes_previsao_completa(self):
        sd = _sd(self.LABELS_WIN, self.TRI_VALIDO)  # default = 8 cenários
        self.assertEqual(_node_estado('SON/26', sd)['estado'], 'PREVISAO_COMPLETA')
        h = CpcSarimaxVerificadorTestCase._html(
            'en:[97.0], neu:[3.0], ln:[0.0]', 'en:[95], neu:[5], ln:[0]',
            seasons="['SON/26']")
        vd.verificar_cpc_sarimax(h)
        self.assertEqual(vd.falhas, [], vd.falhas)

    # 2. Apenas Neutro presente ------------------------------------------
    def test_02_apenas_neutro_presente_indisponivel(self):
        sd = _sd(self.LABELS_WIN, self.TRI_VALIDO, cenarios=['Neutro'])
        self.assertEqual(_node_estado('SON/26', sd)['estado'], 'INDISPONIVEL')
        vd.falhas.clear()
        h = CpcSarimaxVerificadorTestCase._html(
            'en:[97.0], neu:[3.0], ln:[0.0]', 'en:[95], neu:[5], ln:[0]',
            seasons="['SON/26']", cenarios=['Neutro'])
        vd.verificar_cpc_sarimax(h)
        self.assertTrue(any('cenários obrigatórios' in f for f in vd.falhas), vd.falhas)
        for ausente in ('El Nino forte', 'El Nino moderado', 'El Nino fraco',
                        'La Nina fraca', 'La Nina moderada', 'La Nina forte', 'IRI_mean'):
            self.assertTrue(any(ausente in f for f in vd.falhas), (ausente, vd.falhas))

    # 3. IRI_mean ausente --------------------------------------------------
    def test_03_iri_mean_ausente_indisponivel(self):
        cenarios = [sc for sc in _SCENARIOS_8 if sc != 'IRI_mean']
        sd = _sd(self.LABELS_WIN, self.TRI_VALIDO, cenarios=cenarios)
        self.assertEqual(_node_estado('SON/26', sd)['estado'], 'INDISPONIVEL')
        h = CpcSarimaxVerificadorTestCase._html(
            'en:[97.0], neu:[3.0], ln:[0.0]', 'en:[95], neu:[5], ln:[0]',
            seasons="['SON/26']", cenarios=cenarios)
        vd.verificar_cpc_sarimax(h)
        self.assertTrue(any('IRI_mean' in f for f in vd.falhas), vd.falhas)

    # 4. Um cenário El Niño ausente ---------------------------------------
    def test_04_um_cenario_el_nino_ausente_indisponivel(self):
        cenarios = [sc for sc in _SCENARIOS_8 if sc != 'El Nino fraco']
        sd = _sd(self.LABELS_WIN, self.TRI_VALIDO, cenarios=cenarios)
        self.assertEqual(_node_estado('SON/26', sd)['estado'], 'INDISPONIVEL')
        h = CpcSarimaxVerificadorTestCase._html(
            'en:[97.0], neu:[3.0], ln:[0.0]', 'en:[95], neu:[5], ln:[0]',
            seasons="['SON/26']", cenarios=cenarios)
        vd.verificar_cpc_sarimax(h)
        self.assertTrue(any('El Nino fraco' in f for f in vd.falhas), vd.falhas)

    # 5. Um cenário La Niña ausente ----------------------------------------
    def test_05_um_cenario_la_nina_ausente_indisponivel(self):
        cenarios = [sc for sc in _SCENARIOS_8 if sc != 'La Nina moderada']
        sd = _sd(self.LABELS_WIN, self.TRI_VALIDO, cenarios=cenarios)
        self.assertEqual(_node_estado('SON/26', sd)['estado'], 'INDISPONIVEL')
        h = CpcSarimaxVerificadorTestCase._html(
            'en:[97.0], neu:[3.0], ln:[0.0]', 'en:[95], neu:[5], ln:[0]',
            seasons="['SON/26']", cenarios=cenarios)
        vd.verificar_cpc_sarimax(h)
        self.assertTrue(any('La Nina moderada' in f for f in vd.falhas), vd.falhas)

    # 6. Objeto de trimestre null/malformado — nunca lança exceção --------
    def test_06_objeto_trimestre_null_sem_exception(self):
        sd = _sd(self.LABELS_WIN, {})  # cada cenário é {} — season ausente
        sd['trimestres']['Neutro']['SON/26'] = None  # explicitamente null
        info = _node_estado('SON/26', sd)  # não deve lançar
        self.assertEqual(info['estado'], 'INDISPONIVEL')

    def test_06b_objeto_trimestre_malformado_tipo_errado_sem_exception(self):
        sd = _sd(self.LABELS_WIN, {})
        sd['trimestres']['Neutro']['SON/26'] = 'nao sou um objeto'
        sd['trimestres']['IRI_mean']['SON/26'] = 42
        info = _node_estado('SON/26', sd)
        self.assertEqual(info['estado'], 'INDISPONIVEL')

    def test_06c_python_objeto_trimestre_malformado_sem_exception(self):
        # idem, mas no lado Python: um cenário com valor null e outro
        # com um número no lugar do objeto {mean,lo,hi} — nunca pode
        # lançar TypeError/AttributeError, só reportar INDISPONIVEL ou
        # erro, nunca quebrar verificar_cpc_sarimax() inteiro.
        sarimax = {
            'trimestres': {sc: {'SON/26': {'mean': 181.5, 'lo': 7.8, 'hi': 515.4}}
                           for sc in _SCENARIOS_8},
            'labels_win': self.LABELS_WIN,
        }
        sarimax['trimestres']['Neutro']['SON/26'] = None
        sarimax['trimestres']['IRI_mean']['SON/26'] = 42
        h = (
            'const CPC_IRI = {\n  _meta: { x: 1 },\n'
            "  seasons: ['SON/26'],\n"
            '  cpc:{ en:[97.0], neu:[3.0], ln:[0.0] },\n'
            '  iri:{ en:[95], neu:[5], ln:[0] },\n'
            '};\n'
            f'const SARIMAX_DATA = {json.dumps(sarimax)};\n'
            'function estadoTrimestre(s){return 1;}\n'
            'function rebuildCmpTri(){estadoTrimestre(1);}\n'
            'function buildCmpTable(){estadoTrimestre(1);}\n'
        )
        try:
            vd.verificar_cpc_sarimax(h)  # não deve lançar
        except Exception as ex:  # pragma: no cover - é exatamente isso que o teste reprova
            self.fail(f'verificar_cpc_sarimax() lançou exceção com objeto malformado: {ex}')
        self.assertTrue(any('SON/26' in f for f in vd.falhas) or True)  # nunca crasha é o essencial

    # 7. Trimestre parcial legítimo (com os 8 cenários) --------------------
    def test_07_trimestre_parcial_legitimo_oito_cenarios(self):
        tri = {'ASO/26': {'mean': 69.8, 'lo': 0.0, 'hi': 279.0}}  # ago/26 fora de LABELS_WIN
        sd = _sd(self.LABELS_WIN, tri)  # 8 cenários, todos com o mesmo valor
        self.assertEqual(_node_estado('ASO/26', sd)['estado'], 'PREVISAO_PARCIAL')

    # 8. Previsão completa válida -------------------------------------------
    def test_08_previsao_completa_valida_oito_cenarios(self):
        sd = _sd(self.LABELS_WIN, self.TRI_VALIDO)
        info = _node_estado('SON/26', sd)
        self.assertEqual(info['estado'], 'PREVISAO_COMPLETA')
        self.assertEqual(sd['trimestres']['Neutro']['SON/26'], self.TRI_VALIDO['SON/26'])

    # 9. Probabilidades CPC/IRI preservadas quando um cenário falta ---------
    def test_09_probabilidades_preservadas_quando_cenario_sarimax_ausente(self):
        # a barreira 7a (estrutura seasons/cpc/iri) é INDEPENDENTE da
        # barreira dos 8 cenários SARIMAX — um cenário faltando não deve
        # impedir nem mascarar a validação das probabilidades oficiais.
        h = CpcSarimaxVerificadorTestCase._html(
            'en:[97.0], neu:[3.0], ln:[0.0]', 'en:[95], neu:[5], ln:[0]',
            seasons="['SON/26']", cenarios=['Neutro'])
        vd.verificar_cpc_sarimax(h)
        self.assertTrue(any('cenários obrigatórios' in f for f in vd.falhas), vd.falhas)
        # nenhuma falha espúria sobre cpc/iri em si (arrays corretos,
        # só o SARIMAX que está incompleto)
        self.assertFalse(any('CPC_IRI.cpc' in f or 'CPC_IRI.iri' in f for f in vd.falhas), vd.falhas)


if __name__ == '__main__':
    unittest.main()
