#!/usr/bin/env python3
"""
tests/test_ui_listener_orfao.py — ENSO-UI: cobre a correção do listener
JS órfão em docs/index.html.

Causa raiz (confirmada por leitura de código e reprodução real com
Playwright antes da correção): uma instrução de NÍVEL SUPERIOR do
script (fora de qualquer função ou listener) —
`document.getElementById('btn-download-template-full').addEventListener(...)`
— referenciava um elemento que não existe em nenhum lugar do HTML.
Nenhum elemento com esse id existe na marcação, a função
`buildTemplateCSV()` que o listener chamaria nem está definida no
arquivo, e `downloadCSV()` não tem nenhum outro chamador — confirma
funcionalidade descontinuada (botão + função removidos), não algo
"ainda previsto". Era o único uso desse id/função em todo o arquivo.

Por ser uma instrução de nível superior (não dentro de uma função só
chamada sob demanda, nem dentro de um listener), a exceção não tratada
interrompia a execução de TODO o restante daquele bloco `<script>`:
declarações de função continuam içadas (hoisting), mas:
  - `EMBEDDED_BUNDLE`/`STORAGE_KEY`/etc. (const) nunca eram
    inicializadas;
  - a IIFE `(async function initPersistence(){...})()` — uma CHAMADA,
    não uma declaração — nunca executava: `window._sinobrasBundle`
    nunca era definido, `showPersistenceStatus()` nunca rodava (o
    indicador `#persist-status` ficava preso no placeholder estático
    do HTML);
  - o registro do `DOMContentLoaded` que agenda `reloadBundleStatus`
    nunca acontecia;
  - a atualização dos rótulos `[data-periodo]` (`D.fc_labels[0]` até
    `D.fc_labels[last]`) nunca executava — CONFIRMADO: antes da
    correção, esses spans mostravam o texto estático "ago/26–jul/27",
    diferente do intervalo real "09/26–08/27".

Correção mínima: remover apenas o registro órfão do listener (3
linhas). `downloadCSV()` fica sem chamador (inofensivo, não lançado
nenhum erro) — não removida, para manter a alteração mínima.

Roda com:
    python -m unittest tests.test_ui_listener_orfao -v

Precisa de `node` com o módulo `playwright` instalado (ver
tests/_playwright_ui_smoke.js) — mesma política de CI=true das outras
suítes desta fase: fora de CI, sem node/playwright, pula; dentro de
CI, a ausência vira falha explícita, nunca um skip silencioso.
"""

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
DASHBOARD = ROOT / 'docs' / 'index.html'
RUNNER = Path(__file__).parent / '_playwright_ui_smoke.js'
TABS = ['monitor', 'previsao', 'comparativo', 'clima', 'balanco', 'plano']


def _node_playwright_disponivel():
    if shutil.which('node') is None:
        return False
    r = subprocess.run(['node', '-e', "require('playwright')"],
                        capture_output=True, text=True)
    return r.returncode == 0


_EM_CI = os.environ.get('CI', '').strip().lower() in ('1', 'true', 'yes')


def _run():
    r = subprocess.run(['node', str(RUNNER), str(DASHBOARD)],
                        capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f'playwright runner falhou: {r.stderr}')
    return json.loads(r.stdout)


class ListenerOrfaoAusenteTestCase(unittest.TestCase):
    """O id/função do listener removido não deve existir em nenhum
    lugar do HTML publicado — lógica pura, sem navegador."""

    def setUp(self):
        if not DASHBOARD.exists():
            self.skipTest('docs/index.html não encontrado')
        self.html = DASHBOARD.read_text(encoding='utf-8')

    def test_01_id_orfao_nao_existe_em_nenhum_elemento(self):
        self.assertNotIn('id="btn-download-template-full"', self.html)

    def test_02_listener_orfao_removido_do_script(self):
        self.assertNotIn("getElementById('btn-download-template-full')", self.html)

    def test_03_buildTemplateCSV_continua_inexistente_confirma_descontinuacao(self):
        # se esta função reaparecer um dia, a decisão de remover (em vez
        # de criar o botão) precisa ser reavaliada — este teste existe
        # para que isso nunca passe batido silenciosamente.
        self.assertNotIn('function buildTemplateCSV', self.html)


@unittest.skipUnless(_EM_CI or _node_playwright_disponivel(),
                      'node com módulo playwright não disponível neste ambiente')
class UiSmokeTestCase(unittest.TestCase):

    def setUp(self):
        if _EM_CI and not _node_playwright_disponivel():
            self.fail(
                'CI=true mas node/playwright não está disponível — o job de CI '
                'deveria ter instalado Node.js + Playwright antes desta suíte; '
                'isto NÃO é um skip.')

    def test_01_sem_excecao_addEventListener_sobre_null(self):
        out = self._run_ok()
        for err in out['pageErrors']:
            self.assertNotIn("reading 'addEventListener'", err,
                              f'exceção do listener órfão ainda ocorre: {err}')
        self.assertEqual(out['pageErrors'], [])
        self.assertEqual(out['consoleErrors'], [])

    def test_02_inicializacao_do_modulo_de_persistencia(self):
        out = self._run_ok()
        self.assertTrue(out['estadoInicial']['embeddedBundleDefined'],
                         'initPersistence() não executou — window._sinobrasBundle indefinido')
        self.assertEqual(out['estadoInicial']['sinobrasSource'], 'embedded')

    def test_03_comportamento_controlado_sem_window_storage(self):
        out = self._run_ok()
        # este Chromium headless nunca define window.storage — é o
        # cenário real de "storage indisponível", não simulado.
        self.assertFalse(out['estadoInicial']['windowStorageExiste'])
        self.assertIn('Storage indisponível', out['estadoInicial']['persistStatusHTML'])

    def test_04_indicador_de_armazenamento_sem_travamento(self):
        out = self._run_ok()
        # nunca deve ficar preso no placeholder estático original
        self.assertNotIn('Verificando storage', out['estadoInicial']['persistStatusHTML'])

    def test_05_rotulos_temporais_atualizados(self):
        out = self._run_ok()
        esperado = out['estadoInicial']['fcLabelsRange']
        periodos = out['estadoInicial']['periodoEls']
        self.assertTrue(periodos, 'nenhum elemento [data-periodo] encontrado')
        for texto in periodos:
            self.assertEqual(texto, esperado)
        # nunca deve sobrar o texto estático antigo do HTML
        for texto in periodos:
            self.assertNotEqual(texto, 'ago/26–jul/27')

    def test_06_seis_abas_funcionam_sem_erro_novo(self):
        out = self._run_ok()
        tabs_vistas = [t['tab'] for t in out['tabResults']]
        self.assertEqual(tabs_vistas, TABS)
        for resultado in out['tabResults']:
            with self.subTest(tab=resultado['tab']):
                self.assertTrue(resultado['paneVisivel'],
                                 f"painel da aba {resultado['tab']} não ficou visível")
                self.assertEqual(resultado['novosErrosAposClique'], [],
                                  f"novo erro JS ao abrir a aba {resultado['tab']}")

    def test_07_aba_comparativo_preserva_correcao_pr65(self):
        out = self._run_ok()
        html = out['comparativoHTML']
        self.assertIsNotNone(html, 'tabela #t-cmp-full não encontrada')
        self.assertIn('parcial (clim.)', html)  # ASO/26, correção da PR #65
        for proibido in ('NaN', 'undefined', 'null%', 'mm mm', 'mm%'):
            self.assertNotIn(proibido, html)

    def test_08_ausencia_de_erros_js_novos_no_carregamento_completo(self):
        out = self._run_ok()
        self.assertEqual(out['pageErrors'], [])

    def _run_ok(self):
        try:
            return _run()
        except RuntimeError as ex:
            self.fail(str(ex))


if __name__ == '__main__':
    unittest.main()
