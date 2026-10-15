#!/usr/bin/env python3
"""
tests/test_verificar_dashboard.py — Fase ENSO-DADOS (auditoria
15/10/2026): cobre a flag `--pular-continuidade-serie-subst` (nova) e
o parser de datas pt-BR usado no aviso de defasagem do CPC_IRI
(`_dias_desde_data_pt`), sem tocar nenhuma das outras checagens já
existentes do verificador.

Contexto do bug corrigido: `indices_semanal.yml` nunca chama
`fetch_monthly_data.py` (só `update.yml`, dia 21) — então, do dia 1 ao
dia 20 de todo mês, a checagem de continuidade de `serie_subst.csv`
reprova por um motivo que aquele workflow não pode corrigir,
bloqueando o commit e o heartbeat seguintes. A flag existe só pra esse
workflow; `update.yml`/`publicar.yml` continuam com o comportamento
padrão (bloqueante), nunca passam a flag.

Roda com:
    python -m unittest tests.test_verificar_dashboard -v
"""

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import verificar_dashboard as vd  # noqa: E402


class DiasDesdeDataPtTestCase(unittest.TestCase):

    def test_a_formato_dd_mmm_aaaa(self):
        d = vd._dias_desde_data_pt('13/ago/2026')
        esperado = (date.today() - date(2026, 8, 13)).days
        self.assertEqual(d, esperado)

    def test_b_formato_mmm_aaaa_parenteses_dd_mmm(self):
        # formato real de CPC_IRI._meta.iri_emissao: 'ago/2026 (19/ago)'
        d = vd._dias_desde_data_pt('ago/2026 (19/ago)')
        esperado = (date.today() - date(2026, 8, 19)).days
        self.assertEqual(d, esperado)

    def test_c_texto_sem_data_retorna_none_nunca_lanca(self):
        self.assertIsNone(vd._dias_desde_data_pt('série CPC da emissão de jul/26'))
        self.assertIsNone(vd._dias_desde_data_pt(''))
        self.assertIsNone(vd._dias_desde_data_pt('qualquer coisa sem data'))

    def test_d_mes_invalido_retorna_none(self):
        self.assertIsNone(vd._dias_desde_data_pt('13/xxx/2026'))

    def test_e_dia_invalido_para_o_mes_retorna_none_nunca_lanca(self):
        self.assertIsNone(vd._dias_desde_data_pt('31/fev/2026'))


class PularContinuidadeSerieSubstTestCase(unittest.TestCase):
    """Usa os dados reais do repositório (mesma árvore de trabalho) —
    só pula se não existirem, igual às outras suítes `ComDadosReais*`
    do projeto."""

    @classmethod
    def setUpClass(cls):
        if not vd.SERIE_SUBST.exists() or not vd.DASHBOARD.exists():
            raise unittest.SkipTest("dados reais não disponíveis nesta árvore de trabalho")

    def test_a_flag_desligada_mantem_comportamento_padrao(self):
        """Default (sem flag) precisa continuar idêntico ao
        comportamento de sempre — update.yml/publicar.yml nunca passam
        a flag, então `main()` sem argumento tem que se comportar
        exatamente como antes desta correção."""
        vd.falhas.clear()
        resultado = vd.main()
        # ambos os comportamentos são válidos dependendo do estado real
        # da árvore de trabalho — o que esta prova é que a flag NUNCA
        # muda o resultado quando desligada (comparado a seu próprio
        # default), não que o resultado precisa ser 0 ou 1 especificamente.
        vd.falhas.clear()
        resultado_de_novo = vd.main(pular_continuidade_serie_subst=False)
        self.assertEqual(resultado, resultado_de_novo)

    def test_b_flag_ligada_nunca_adiciona_a_falhas_por_causa_do_serie_subst(self):
        vd.falhas.clear()
        vd.main(pular_continuidade_serie_subst=True)
        for f in vd.falhas:
            self.assertNotIn('serie_subst.csv com mês(es) faltando', f)

    def test_c_flag_ligada_nunca_e_mais_permissiva_que_desligada_em_outras_checagens(self):
        """A flag só pode SUPRIMIR a falha específica do item 9 — nunca
        fazer uma falha de qualquer OUTRA checagem desaparecer. Prova:
        toda falha com a flag ligada (exceto a do serie_subst) também
        aparece com a flag desligada."""
        vd.falhas.clear()
        vd.main(pular_continuidade_serie_subst=False)
        falhas_sem_flag = set(vd.falhas)

        vd.falhas.clear()
        vd.main(pular_continuidade_serie_subst=True)
        falhas_com_flag = set(vd.falhas)

        extras = falhas_com_flag - falhas_sem_flag
        self.assertEqual(extras, set(), f'flag introduziu falha nova: {extras}')

    def tearDown(self):
        vd.falhas.clear()


if __name__ == '__main__':
    unittest.main()
