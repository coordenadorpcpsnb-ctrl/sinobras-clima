#!/usr/bin/env python3
"""
tests/test_cpc_sarimax_render.py — ENSO-DADOS Fase C: cobre os
cenários de RENDERIZAÇÃO (DOM/navegador) da correção de
disponibilidade regional CPC_IRI.seasons × SARIMAX_DATA, que a suíte
`test_cpc_sarimax_disponibilidade.py` (lógica pura) não alcança:

  5. Probabilidade CPC/IRI não nula em trimestre SEM previsão regional
     completa — preservada na tabela, colunas SARIMAX substituídas por
     indicador de indisponibilidade.
  6. `null` legítimo em CPC/IRI (ex.: IRI não publicou uma categoria
     para um trimestre) — nunca convertido para zero nem para "null%".
  11. Trimestre com previsão regional completa e válida — números
      originais preservados sem alteração.
  12. Nenhum trimestre com PREVISAO_COMPLETA — estado vazio legível no
      gráfico, sem erro JavaScript.
  13. Ausência de "NaN", "undefined", "null%" e de "mm" duplicado em
      qualquer célula renderizada.
  17. Ausência de erros JavaScript no navegador (Playwright, Chromium
      headless já instalado neste ambiente — sem rede).

Carrega o docs/index.html REAL (nunca uma cópia reimplementada) com
SARIMAX_DATA/CPC_IRI substituídos por fixtures sintéticas, usando a
MESMA técnica de regex que scripts/update_dashboard.py e
scripts/update_indices.py usam em produção — ver
tests/_playwright_cmp_fixture.js.

Roda com:
    python -m unittest tests.test_cpc_sarimax_render -v

Precisa de `node` com o módulo `playwright` instalado — nenhum
caminho de binário é fixo (ver tests/_playwright_cmp_fixture.js: usa
PLAYWRIGHT_CHROMIUM_PATH se definido, senão a resolução padrão do
próprio Playwright). Fora de CI (variável de ambiente `CI` não
definida), se node/playwright não estiverem disponíveis, os testes
são pulados — nunca marcados como falha por limitação de um ambiente
de desenvolvimento qualquer. **Dentro da CI** (`CI=true`, como o
GitHub Actions já define), a ausência de node/playwright/Chromium
nunca é pulada em silêncio — vira FALHA explícita (ver `setUp`),
porque ".github/workflows/ci.yml" (Job B) é responsável por instalar
os três antes de rodar esta suíte (ENSO-DADOS Fase C.1, Correção B).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
DASHBOARD = ROOT / 'docs' / 'index.html'
RUNNER = Path(__file__).parent / '_playwright_cmp_fixture.js'

_SCENARIOS_8 = ['El Nino forte', 'El Nino moderado', 'El Nino fraco', 'Neutro',
                'La Nina fraca', 'La Nina moderada', 'La Nina forte', 'IRI_mean']


def _node_playwright_disponivel():
    if shutil.which('node') is None:
        return False
    r = subprocess.run(['node', '-e', "require('playwright')"],
                        capture_output=True, text=True)
    return r.returncode == 0


# GitHub Actions (e a maioria das CIs) sempre define CI=true — usado
# aqui só para decidir se a ausência de node/playwright é um "ambiente
# de dev sem isso" (pular, ok) ou "a CI deveria ter instalado e não
# instalou" (falhar, nunca pular em silêncio — ENSO-DADOS Fase C.1,
# Correção B: "Não aceitar testes de renderização silenciosamente
# ignorados como evidência de aprovação").
_EM_CI = os.environ.get('CI', '').strip().lower() in ('1', 'true', 'yes')


def _tri(mean, lo, hi):
    return {'mean': mean, 'lo': lo, 'hi': hi}


def _sarimax_8(labels_win, trimestres_por_chave, cenarios=None):
    """Monta SARIMAX_DATA com os 8 cenários usados por
    rebuildCmpNino()/rebuildCmpPrecMon()/rebuildCmpTri()/buildCmpTable()
    — todos com os MESMOS valores por trimestre/mês (suficiente para
    testar disponibilidade/renderização; o valor exato por cenário não
    é o que estes testes verificam). `monthly`/`n34` precisam existir
    com o comprimento de `labels_win` para as outras duas funções (que
    buildComparativo() chama ANTES de rebuildCmpTri()/buildCmpTable())
    não lançarem exceção e impedirem a tabela de ser construída.
    `cenarios`: subconjunto de _SCENARIOS_8 — passar menos de 8 simula
    um ou mais cenários SARIMAX faltando por completo (ENSO-DADOS Fase
    C.1, Correção A)."""
    cenarios = cenarios if cenarios is not None else _SCENARIOS_8
    n = len(labels_win)
    monthly_sc = {'prec': [0.0] * n, 'lo95': [0.0] * n, 'hi95': [0.0] * n,
                  'p5': [0.0] * n, 'p95': [0.0] * n}
    return {
        'trimestres': {sc: dict(trimestres_por_chave) for sc in cenarios},
        'monthly': {sc: dict(monthly_sc) for sc in cenarios},
        'labels_win': labels_win,
        'n34': {sc: [0.0] * n for sc in cenarios},
    }


# Bug PRÉ-EXISTENTE e fora do escopo autorizado desta correção (ENSO-DADOS
# Fase C só autoriza docs/index.html, scripts/verificar_dashboard.py e
# testes — não "outras alterações" não relacionadas a CPC_IRI×SARIMAX):
# `document.getElementById('btn-download-template-full')` (linha ~2728)
# referencia um id que NÃO existe em nenhum elemento do HTML — confirmado
# já presente, idêntico, em origin/main ANTES desta branch. Dispara em
# QUALQUER carregamento da página, independente de fixture ou aba — nunca
# causado por este fix. Filtrado aqui com justificativa, não corrigido
# (fora do escopo autorizado; reportado no relatório final desta fase).
_ERRO_PRE_EXISTENTE_FORA_DE_ESCOPO = "Cannot read properties of null (reading 'addEventListener')"


def _erros_do_fix(page_errors):
    return [e for e in page_errors if _ERRO_PRE_EXISTENTE_FORA_DE_ESCOPO not in e]


def _run(fixture):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(fixture, f)
        fixture_path = f.name
    try:
        r = subprocess.run(['node', str(RUNNER), fixture_path],
                            capture_output=True, text=True, timeout=60)
    finally:
        Path(fixture_path).unlink(missing_ok=True)
    if r.returncode != 0:
        raise RuntimeError(f'playwright runner falhou: {r.stderr}')
    return json.loads(r.stdout)


@unittest.skipUnless(_EM_CI or _node_playwright_disponivel(),
                      'node com módulo playwright não disponível neste ambiente')
class ComparativoRenderTestCase(unittest.TestCase):

    def setUp(self):
        # Em CI, a classe NUNCA é pulada na decoração acima (_EM_CI é
        # True) — se o ambiente ainda assim não tiver node/playwright,
        # isso é uma FALHA real (a CI deveria ter instalado — Correção
        # B), nunca um skip silencioso.
        if _EM_CI and not _node_playwright_disponivel():
            self.fail(
                'CI=true mas node/playwright não está disponível — Job B de '
                'ci.yml deveria ter instalado Node.js + Playwright antes desta '
                'suíte (ENSO-DADOS Fase C.1, Correção B); isto NÃO é um skip.')

    def test_05_06_11_13_probabilidade_sem_regional_null_legitimo_e_sem_lixo_textual(self):
        sd = _sarimax_8(['09/26', '10/26', '11/26'], {
            'ASO/26': _tri(69.8, 0.0, 279.0),   # ago/26 fora de labels_win -> PARCIAL
            'SON/26': _tri(181.5, 7.8, 515.4),  # set/out/nov/26, tudo dentro -> COMPLETA
        })
        cpc_iri = {
            '_meta': {},
            'seasons': ['ASO/26', 'SON/26'],
            # ASO/26: probabilidade oficial não-nula MESMO sem previsão
            # regional completa (cenário 5) — preservada na tabela.
            # SON/26: números completos e válidos (cenário 11).
            'cpc': {'en': [100.0, 45.0], 'neu': [0.0, 54.0], 'ln': [0.0, 1.0]},
            # iri.neu/ln de ASO/26 = null (cenário 6: não publicado —
            # nunca convertido para zero nem para "null%").
            'iri': {'en': [100, 45], 'neu': [None, 54], 'ln': [None, 1]},
            'nino_seasons': [], 'iri_nino_mean': [], 'iri_nino_p15': [], 'iri_nino_p85': [],
        }
        out = self._run_ok({'sarimax': sd, 'cpc_iri': cpc_iri})
        html = out['tbodyHTML']

        # cenário 5: probabilidade oficial preservada mesmo sem regional
        self.assertIn('100%', html)
        # cenário 6: null legítimo nunca é "null%" (e nunca aparece como
        # "0%" SÓ por causa do null — ASO/26.cpc.neu=0.0 É um 0% real e
        # legítimo, diferente de ASO/26.iri.neu=null, que deve virar "—")
        self.assertNotIn('null%', html)
        self.assertNotIn('nullmm', html.replace(' ', ''))
        # cenário 13: nunca NaN/undefined/null%% e nunca "mm" duplicado
        for proibido in ('NaN', 'undefined', 'null%', 'mm mm', 'mm%'):
            self.assertNotIn(proibido, html, f'texto proibido "{proibido}" encontrado na tabela')
        # cenário 11: trimestre completo preserva o número original
        # (Math.round(181.5) = 182, igual ao JS real do dashboard)
        self.assertIn('182 mm', html)

        # cenário 17: nenhum erro JS no navegador para este fixture
        # (exceto o bug pré-existente/fora de escopo documentado acima)
        self.assertEqual(out['consoleErrors'], [])
        self.assertEqual(_erros_do_fix(out['pageErrors']), [])

    def test_12_nenhum_trimestre_completo_estado_vazio_sem_erro_js(self):
        sd = _sarimax_8(['01/27'], {   # nada do horizonte real cai aqui
            'ASO/26': _tri(69.8, 0.0, 279.0),
        })
        cpc_iri = {
            '_meta': {},
            'seasons': ['ASO/26'],
            'cpc': {'en': [100.0], 'neu': [0.0], 'ln': [0.0]},
            'iri': {'en': [100], 'neu': [0], 'ln': [0]},
            'nino_seasons': [], 'iri_nino_mean': [], 'iri_nino_p15': [], 'iri_nino_p85': [],
        }
        out = self._run_ok({'sarimax': sd, 'cpc_iri': cpc_iri})

        self.assertTrue(out['emptyStateVisible'], 'estado vazio deveria estar visível')
        self.assertFalse(out['canvasVisible'], 'canvas do gráfico deveria estar oculto')
        self.assertEqual(out['consoleErrors'], [])
        self.assertEqual(_erros_do_fix(out['pageErrors']), [])
        # a probabilidade oficial continua na tabela mesmo com o gráfico vazio
        self.assertIn('100%', out['tbodyHTML'])

    def test_13_cenario_sarimax_ausente_renderiza_indisponivel_sem_erro_js(self):
        # ENSO-DADOS Fase C.1 (Correção A), item 10 da retomada:
        # 'Neutro' falta por completo em SARIMAX_DATA.trimestres — TODO
        # trimestre deve renderizar como indisponível (nunca crashar,
        # nunca ser confundido com PREVISAO_COMPLETA), e as
        # probabilidades CPC/IRI oficiais continuam na tabela.
        cenarios_sem_neutro = [sc for sc in _SCENARIOS_8 if sc != 'Neutro']
        sd = _sarimax_8(['09/26', '10/26', '11/26'],
                         {'SON/26': _tri(181.5, 7.8, 515.4)},
                         cenarios=cenarios_sem_neutro)
        cpc_iri = {
            '_meta': {},
            'seasons': ['SON/26'],
            'cpc': {'en': [97.0], 'neu': [3.0], 'ln': [0.0]},
            'iri': {'en': [95], 'neu': [5], 'ln': [0]},
            'nino_seasons': [], 'iri_nino_mean': [], 'iri_nino_p15': [], 'iri_nino_p85': [],
        }
        out = self._run_ok({'sarimax': sd, 'cpc_iri': cpc_iri})
        html = out['tbodyHTML']

        self.assertIn('97%', html)  # probabilidade oficial preservada
        self.assertIn('indisponível', html)  # coluna SARIMAX marcada, não crashada
        for proibido in ('NaN', 'undefined', 'null%', 'mm mm', 'mm%'):
            self.assertNotIn(proibido, html, f'texto proibido "{proibido}" encontrado na tabela')
        self.assertEqual(out['consoleErrors'], [])
        self.assertEqual(_erros_do_fix(out['pageErrors']), [])

    def _run_ok(self, fixture):
        try:
            return _run(fixture)
        except RuntimeError as ex:
            self.fail(str(ex))


if __name__ == '__main__':
    unittest.main()
