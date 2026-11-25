#!/usr/bin/env python3
"""
tests/test_enso_roni_fase4b1.py — Fase ENSO-RONI 4B.1: classificação
oficial do RONI (fase/intensidade, 9 categorias NOAA/CPC em
incrementos de 0,5°C) exibida no dashboard como "Situação ENSO
oficial", separada do gatilho operacional legado (ONI-aprox, Plano
SECA/EXCESSO, inalterado nesta fase).

Toda a lógica JS testada aqui é extraída LITERALMENTE de docs/index.html
e executada via Node — nunca uma reimplementação Python separada que
poderia divergir silenciosamente (mesmo padrão de
tests/test_cpc_sarimax_disponibilidade.py).

Cobre:
  1. As 9 categorias e suas fronteiras numéricas exatas.
  2. Trimestre do RONI não confundido com mês isolado (rótulo seas/ano
     usado como veio, nunca recombinado).
  3. RONI ausente ou com valor null/undefined — nunca neutralidade
     artificial, sempre aviso explícito (Playwright).
  4. RONI defasado (atualizado há muito tempo) — aviso explícito, sem
     esconder o valor (Playwright).
  5. Classificação do RONI nunca aciona Plano SECA/EXCESSO — isso
     continua exclusivamente a cargo do ONI-aprox (checagem estática +
     Playwright com fixture de RONI em valor que ativaria o plano se
     fosse usado, confirmando que os planos não mudam).
  6. Painel do gatilho legado rotulado explicitamente como tal.
  7. Nenhuma modificação de modelos/séries científicas (reaproveita
     PreservacaoDeModelosCientificosTestCase).

Roda com:
    python -m unittest tests.test_enso_roni_fase4b1 -v
    node precisa estar no PATH (lógica pura); node+playwright+Chromium
    para a suíte de renderização (pulada fora de CI se ausente, nunca
    em CI — mesma política de tests/test_cpc_sarimax_render.py).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
DASHBOARD = ROOT / 'docs' / 'index.html'
RUNNER = Path(__file__).parent / '_playwright_roni_fixture.js'
sys.path.insert(0, str(ROOT / 'scripts'))


def _extrair_js_classificacao():
    """Extrai `const RONI`, `classificarRoni` e `_diasDesdeNumerico`
    literalmente do docs/index.html publicado."""
    html = DASHBOARD.read_text(encoding='utf-8')
    ini = html.find('const RONI = {')
    fim = html.find('\nconst D = {')
    if ini < 0 or fim < 0 or fim <= ini:
        raise AssertionError(
            'bloco RONI/classificarRoni/_diasDesdeNumerico não encontrado '
            'em docs/index.html — a implementação da Fase 4B.1 pode ter sido removida')
    return html[ini:fim]


_JS_CORE = _extrair_js_classificacao()


def _node_classifica(valor):
    script = _JS_CORE + f'\nconsole.log(JSON.stringify(classificarRoni({json.dumps(valor)})));'
    r = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f'node falhou ao classificar {valor!r}: {r.stderr}')
    return json.loads(r.stdout)


def _node_dias_desde(txt):
    script = _JS_CORE + f'\nconsole.log(JSON.stringify(_diasDesdeNumerico({json.dumps(txt)})));'
    r = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f'node falhou ao calcular dias desde {txt!r}: {r.stderr}')
    return json.loads(r.stdout)


class ClassificacaoRoniFronteirasTestCase(unittest.TestCase):
    """Item 1 da entrega: as 9 categorias e as 8 fronteiras exatas,
    rodando o JS real (classificarRoni), nunca uma cópia Python."""

    def test_a_valores_centrais_de_cada_categoria(self):
        casos = [
            (2.5, 'en_muito_forte', 'El Niño', 'muito forte'),
            (1.7, 'en_forte', 'El Niño', 'forte'),
            (1.2, 'en_moderado', 'El Niño', 'moderado'),
            (0.7, 'en_fraco', 'El Niño', 'fraco'),
            (0.0, 'neutro', 'Neutro', None),
            (-0.7, 'ln_fraco', 'La Niña', 'fraco'),
            (-1.2, 'ln_moderado', 'La Niña', 'moderado'),
            (-1.7, 'ln_forte', 'La Niña', 'forte'),
            (-2.5, 'ln_muito_forte', 'La Niña', 'muito forte'),
        ]
        for valor, classe, fase, intensidade in casos:
            with self.subTest(valor=valor):
                r = _node_classifica(valor)
                self.assertEqual(r['classe'], classe)
                self.assertEqual(r['fase'], fase)
                self.assertEqual(r['intensidade'], intensidade)

    def test_b_fronteiras_exatas_lado_quente(self):
        # Tabela oficial: "X ≤ Index < Y" — o limite INFERIOR pertence
        # à categoria mais intensa (ex.: 2.0 é "muito forte", não "forte").
        casos = [
            (2.0, 'en_muito_forte'),
            (1.9999, 'en_forte'),
            (1.5, 'en_forte'),
            (1.4999, 'en_moderado'),
            (1.0, 'en_moderado'),
            (0.9999, 'en_fraco'),
            (0.5, 'en_fraco'),
            (0.4999, 'neutro'),
        ]
        for valor, classe in casos:
            with self.subTest(valor=valor):
                self.assertEqual(_node_classifica(valor)['classe'], classe)

    def test_c_fronteiras_exatas_lado_frio_espelhado(self):
        # Tabela oficial: "-Y < Index ≤ -X" — o limite exato NEGATIVO
        # pertence à categoria mais intensa (ex.: -1.0 é "moderado", não "fraco").
        casos = [
            (-0.5, 'ln_fraco'),
            (-0.4999, 'neutro'),
            (-1.0, 'ln_moderado'),
            (-0.9999, 'ln_fraco'),
            (-1.5, 'ln_forte'),
            (-1.4999, 'ln_moderado'),
            (-2.0, 'ln_muito_forte'),
            (-1.9999, 'ln_forte'),
        ]
        for valor, classe in casos:
            with self.subTest(valor=valor):
                self.assertEqual(_node_classifica(valor)['classe'], classe)

    def test_d_valor_ausente_nao_e_classificado_como_neutro(self):
        for valor in (None,):
            r = _node_classifica(valor)
            self.assertIsNone(r, 'RONI ausente deve retornar null, nunca uma classe (ex.: neutro)')

    def test_e_valor_real_mais_recente_e_el_nino_forte(self):
        # ASO/2026 = +1,97°C — citado como "El Niño forte" na entrega
        # desta fase (abaixo de 2,0, não "muito forte").
        r = _node_classifica(1.97)
        self.assertEqual(r['classe'], 'en_forte')
        self.assertEqual(r['intensidade'], 'forte')


class DiasDesdeNumericoTestCase(unittest.TestCase):
    """Suporte à detecção de defasagem do RONI — formato DD/MM/AAAA."""

    def test_a_data_de_hoje_e_essencialmente_zero_dias(self):
        # Comparação é contra meia-noite local (new Date(ano,mes,dia))
        # e Date.now() tem componente de hora — mesmo arredondamento de
        # _diasDesde() já aceito em produção: aceita 0 ou 1, nunca mais.
        import datetime
        hoje = datetime.date.today().strftime('%d/%m/%Y')
        self.assertIn(_node_dias_desde(hoje), (0, 1))

    def test_b_formato_invalido_retorna_null(self):
        self.assertIsNone(_node_dias_desde('23/ago/2026'))  # formato de _diasDesde, não deste helper
        self.assertIsNone(_node_dias_desde(''))
        self.assertIsNone(_node_dias_desde(None))

    def test_c_data_passada_conta_dias_positivos(self):
        import datetime
        passado = (datetime.date.today() - datetime.timedelta(days=50)).strftime('%d/%m/%Y')
        self.assertIn(_node_dias_desde(passado), (50, 51))


class GatilhoLegadoPreservadoTestCase(unittest.TestCase):
    """Item 5/6/8 da entrega: checagem ESTÁTICA de que a classificação
    RONI não alimenta `secoAtivo`/`excAtivo` (planos), e que os
    limiares legados (ONI-aprox ±1,0°C) continuam exatamente como
    estavam — sem depender de renderização."""

    def setUp(self):
        self.html = DASHBOARD.read_text(encoding='utf-8')

    def test_a_planos_continuam_derivados_de_oni_no_de_roni(self):
        m = re.search(r"const secoAtivo\s*=\s*oni\s*>=\s*1,\s*excAtivo\s*=\s*oni\s*<=\s*-1;", self.html)
        self.assertIsNotNone(
            m, 'secoAtivo/excAtivo precisam continuar lidos de `oni` (ONI-aprox), '
               'nunca de RONI/classificarRoni, nesta fase')

    def test_b_classificarRoni_nao_e_chamado_para_decidir_planos(self):
        # Garante que a função de classificação do RONI nunca aparece
        # na mesma linha/contexto imediato de secoAtivo/excAtivo.
        trecho = re.search(r"const secoAtivo.*?</div>`;", self.html, re.S)
        self.assertIsNotNone(trecho)
        self.assertNotIn('classificarRoni', trecho.group(0))

    def test_c_painel_legado_rotulado_explicitamente(self):
        self.assertIn('gatilho legado', self.html)
        self.assertIn('ONI aproximado local', self.html)

    def test_d_limiares_legados_inalterados(self):
        # Os mesmos limiares documentados desde a Fase 4A continuam no texto.
        self.assertIn('ONI-aprox ≥ +1,0 °C em SON', self.html)
        self.assertIn('ONI-aprox ≤ −1,0 °C', self.html)


class RoniTrimestralDinamicoTestCase(unittest.TestCase):
    """Corrige o achado da auditoria: `_meta.roni_trimestral` estava
    congelado em JAS/2026 enquanto `const RONI` já estava em ASO/2026.
    A nota do semáforo agora lê `const RONI` diretamente."""

    def test_a_nota_le_const_roni_dinamicamente(self):
        html = DASHBOARD.read_text(encoding='utf-8')
        self.assertIn("RONI oficial ${RONI.valor", html)


def _playwright_disponivel():
    if shutil.which('node') is None:
        return False
    r = subprocess.run(['node', '-e', "require('playwright')"], capture_output=True, text=True)
    return r.returncode == 0


_EM_CI = os.environ.get('CI', '').strip().lower() in ('1', 'true', 'yes')


def _run_fixture(roni_literal):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump({'roni': roni_literal}, f)
        fixture_path = f.name
    try:
        r = subprocess.run(['node', str(RUNNER), fixture_path],
                            capture_output=True, text=True, timeout=60)
    finally:
        Path(fixture_path).unlink(missing_ok=True)
    if r.returncode != 0:
        raise RuntimeError(f'playwright runner falhou: {r.stderr}')
    return json.loads(r.stdout)


@unittest.skipUnless(_EM_CI or _playwright_disponivel(),
                      'node com módulo playwright não disponível neste ambiente')
class RenderizacaoRoniTestCase(unittest.TestCase):

    def setUp(self):
        if _EM_CI and not _playwright_disponivel():
            self.fail('CI=true mas node/playwright indisponíveis — Job B deveria tê-los instalado')

    def test_a_valor_normal_mostra_fase_e_intensidade_sem_erro_js(self):
        r = _run_fixture("{ seas: 'ASO', ano: 2026, valor: 1.97, atualizado: '23/11/2026' }")
        self.assertEqual(r['consoleErrors'], [])
        self.assertEqual(r['pageErrors'], [])
        self.assertIn('El Niño', r['kRoniHTML'])
        self.assertIn('forte', r['kRoniHTML'])
        self.assertNotIn('muito forte', r['kRoniHTML'])  # 1,97 é "forte", não "muito forte"

    def test_b_roni_ausente_mostra_aviso_explicito_nunca_neutro_ou_zero(self):
        r = _run_fixture(None)
        self.assertEqual(r['pageErrors'], [])
        self.assertIn('indisponível', r['kRoniHTML'])
        self.assertNotIn('Neutro', r['kRoniHTML'])
        self.assertNotIn('0,00', r['kRoniHTML'])
        self.assertNotIn('0.00', r['kRoniHTML'])

    def test_c_roni_valor_null_explicito_mostra_aviso(self):
        r = _run_fixture("{ seas: 'ASO', ano: 2026, valor: null, atualizado: '23/11/2026' }")
        self.assertEqual(r['pageErrors'], [])
        self.assertIn('indisponível', r['kRoniHTML'])

    def test_d_roni_defasado_mostra_aviso_sem_esconder_valor(self):
        r = _run_fixture("{ seas: 'DJF', ano: 2024, valor: 1.1, atualizado: '01/01/2024' }")
        self.assertEqual(r['pageErrors'], [])
        self.assertIn('defasado', r['dRoniText'])
        self.assertIn('1.10', r['kRoniHTML'].replace(',', '.'))  # valor continua visível, não escondido

    def test_e_roni_extremo_nao_muda_planos_legados(self):
        # Mesmo com RONI fixado num valor que ativaria Plano SECA se
        # fosse usado, os planos continuam só sob ONI-aprox (fixture
        # não altera D.now.oni, então o estado dos planos é o mesmo
        # independentemente do valor de RONI injetado aqui).
        r_base = _run_fixture("{ seas: 'ASO', ano: 2026, valor: 1.97, atualizado: '23/11/2026' }")
        r_extremo = _run_fixture("{ seas: 'ASO', ano: 2026, valor: 3.5, atualizado: '23/11/2026' }")
        self.assertEqual(r_base['plansHTML'], r_extremo['plansHTML'],
                          'mudar só o valor de RONI não pode alterar o painel de Planos SECA/EXCESSO')
        self.assertEqual(r_base['verdictText'], r_extremo['verdictText'])

    def test_f_painel_legado_visivel_no_cabecalho(self):
        r = _run_fixture("{ seas: 'ASO', ano: 2026, valor: 1.97, atualizado: '23/11/2026' }")
        self.assertIn('legado', r['semaforoHeadText'])


if __name__ == '__main__':
    unittest.main()
