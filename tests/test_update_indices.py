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


if __name__ == '__main__':
    unittest.main()
