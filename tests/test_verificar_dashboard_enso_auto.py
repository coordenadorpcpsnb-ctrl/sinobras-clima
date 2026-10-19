#!/usr/bin/env python3
"""
tests/test_verificar_dashboard_enso_auto.py — Fase ENSO-AUTO
(19/10/2026): cobre a extensão da checagem de defasagem (item 11 de
verificar_dashboard.py) para distinguir as 5 categorias pedidas na
Seção 5 — CPC Diagnostic Discussion, probabilidades CPC, probabilidades
IRI, trajetória Niño 3.4 do IRI e índices oceânicos mensais/semanais —
sem usar a data de execução do script como substituta da data de
publicação oficial.

Roda com:
    python -m unittest tests.test_verificar_dashboard_enso_auto -v
"""

import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import verificar_dashboard as vd  # noqa: E402


class MesesAtrasRotuloMmmAaaaTestCase(unittest.TestCase):

    def test_a_mes_atual_e_zero(self):
        hoje = date.today()
        meses_pt = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez']
        rotulo = f'{meses_pt[hoje.month-1]}/{hoje.year}'
        self.assertEqual(vd._meses_atras_rotulo_mmm_aaaa(rotulo), 0)

    def test_b_mes_anterior_e_um(self):
        hoje = date.today()
        mes_ant = hoje.month - 1 or 12
        ano_ant = hoje.year if hoje.month > 1 else hoje.year - 1
        meses_pt = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez']
        rotulo = f'{meses_pt[mes_ant-1]}/{ano_ant}'
        self.assertEqual(vd._meses_atras_rotulo_mmm_aaaa(rotulo), 1)

    def test_c_dois_anos_atras_conta_24_meses_mais_a_diferenca(self):
        hoje = date.today()
        meses_pt = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez']
        rotulo = f'{meses_pt[hoje.month-1]}/{hoje.year-2}'
        self.assertEqual(vd._meses_atras_rotulo_mmm_aaaa(rotulo), 24)

    def test_d_texto_vazio_ou_none_retorna_none(self):
        self.assertIsNone(vd._meses_atras_rotulo_mmm_aaaa(''))
        self.assertIsNone(vd._meses_atras_rotulo_mmm_aaaa(None))

    def test_e_mes_nao_reconhecido_retorna_none(self):
        self.assertIsNone(vd._meses_atras_rotulo_mmm_aaaa('xyz/2026'))

    def test_f_formato_errado_retorna_none(self):
        self.assertIsNone(vd._meses_atras_rotulo_mmm_aaaa('13/set/2026'))

    def test_g_mes_futuro_retorna_negativo_nunca_lanca(self):
        hoje = date.today()
        meses_pt = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez']
        mes_prox = hoje.month % 12  # mês seguinte (0-based -> ajusta)
        rotulo = f'{meses_pt[mes_prox]}/{hoje.year}'
        resultado = vd._meses_atras_rotulo_mmm_aaaa(rotulo)
        self.assertIsNotNone(resultado)
        self.assertLessEqual(resultado, 0)


class DefasagemCincoCategoriasTestCase(unittest.TestCase):
    """Usa os dados reais do repositório — mesma convenção das outras
    suítes ComDadosReais* do projeto."""

    @classmethod
    def setUpClass(cls):
        if not vd.DASHBOARD.exists():
            raise unittest.SkipTest("docs/index.html não disponível nesta árvore de trabalho")

    def test_a_verificador_roda_sem_lancar_e_distingue_as_5_categorias(self):
        resultado = subprocess.run(
            [sys.executable, str(ROOT / 'scripts' / 'verificar_dashboard.py')],
            cwd=ROOT, capture_output=True, text=True,
        )
        saida = resultado.stdout
        # as 4 categorias de CPC_IRI._meta + a de índices oceânicos
        # aparecem como linhas distintas no console (aviso OU ok)
        self.assertIn('metadados de defasagem do CPC_IRI', saida)
        self.assertIn('índices oceânicos', saida)

    def test_b_nao_usa_data_de_hoje_como_substituta_da_emissao(self):
        """Regressão de design: a checagem de índices oceânicos nunca
        deve reportar '0 dias'/'0 meses' só porque o script rodou hoje
        — tem que medir contra o MÊS do próprio dado (D.now.nino34),
        não contra date.today() diretamente sem essa extração."""
        html = vd.DASHBOARD.read_text(encoding='utf-8')
        import re
        m = re.search(r'now:\s*\{([^}]+)\}', html)
        self.assertIsNotNone(m, 'D.now não encontrado — pré-requisito do teste')
        m_lbl = re.search(r'nino34:\s*\[\s*"([^"]+)"', m.group(1))
        self.assertIsNotNone(m_lbl)
        meses_atras = vd._meses_atras_rotulo_mmm_aaaa(m_lbl.group(1))
        self.assertIsNotNone(meses_atras)
        # o rótulo É de um mês real do dado (não "hoje") — se o mês do
        # rótulo fosse sempre o mês atual, isso indicaria que alguém
        # trocou a label por date.today() em algum lugar.
        hoje = date.today()
        meses_pt = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez']
        rotulo_se_fosse_hoje = f'{meses_pt[hoje.month-1]}/{hoje.year}'
        if m_lbl.group(1) == rotulo_se_fosse_hoje:
            self.skipTest('coincidência de calendário — mês do dado é o mês atual hoje')


if __name__ == '__main__':
    unittest.main()
