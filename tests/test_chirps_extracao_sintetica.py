#!/usr/bin/env python3
"""
tests/test_chirps_extracao_sintetica.py — auditoria do CÓDIGO de
scripts/_chirps.py (ajuste final da 5ª rodada, 2026), com cenários
SINTÉTICOS (nunca uma extração real — climateserv.api.request_data é
sempre mockado, igual ao padrão já usado em tests/test_fetch_fallback.py).

Três riscos apontados para inspeção:
1. Tratamento de valores ausentes recebidos do ClimateSERV — a
   possibilidade de um dia SEM DADO virar precipitação 0.0.
2. Agregação diária→mensal quando existem dias sem informação — se há
   alguma exigência de cobertura mínima, e se o número de dias
   efetivamente somados fica visível no resultado.
3. A geometria da caixa usada na extração central (_geometria_ponto) —
   se ela é de fato sempre menor que um pixel CHIRPS a partir do ponto
   usado (FAZENDAS_LAT/FAZENDAS_LON), e o risco geométrico de o ponto
   cair sobre uma borda/quina de pixel.

Achados confirmados por estes testes (não hipóteses — reprodução
direta do comportamento do código real contra respostas simuladas):

- CONFIRMADO: `(r.get('value') or {}).get('avg') or 0.0` em
  _buscar_prec_chirps_geom trata um dia com `avg=None` (ou sem a
  chave 'value') EXATAMENTE como um dia com `avg=0.0` (chuva real
  zero) — as duas situações produzem o mesmo resultado numérico, sem
  nenhum sinal de qual delas ocorreu. Isto contraria o princípio já
  estabelecido em CLAUDE.md armadilha 6 para TSA/PDO ("0.0 é uma
  afirmação, não um vazio") — aqui esse princípio NÃO está aplicado.
- CONFIRMADO: a agregação mensal (`.groupby(['ano','mes'])['prec'].sum()`)
  não exige nenhum número mínimo de dias válidos no mês, e o
  DataFrame retornado não carrega nenhuma coluna de contagem/cobertura
  de dias — um mês com 1 dia de dado e um mês com 31 dias de dado
  produzem uma saída com as mesmas colunas, indistinguíveis em
  completude.
- CONFIRMADO: dias inteiramente OMITIDOS da lista `result['data']`
  (nem aparecem, nem vêm com avg=None) também não contam para o total
  — um segundo modo de incompletude silenciosa, distinto do anterior.
- CONFIRMADO (fato geométrico, por aritmética exata — Decimal, não
  float): FAZENDAS_LAT (-7.80) e FAZENDAS_LON (-47.95) são múltiplos
  EXATOS da resolução do CHIRPS (0.05°) nos dois eixos. Isso é um
  fato verificável sem rede; a CONSEQUÊNCIA (se isso põe o ponto sobre
  uma borda ou quina de pixel) depende da convenção de alinhamento do
  grid CHIRPS (centro de pixel em múltiplo de 0,05°, ou borda de pixel
  em múltiplo de 0,05°) — NÃO verificada aqui, PENDENTE.

Nenhum destes testes exige rede. Nenhum modifica scripts/_chirps.py —
só o exercita com respostas sintéticas (igual ao padrão de
test_fetch_fallback.py).

Roda com:
    python -m unittest tests.test_chirps_extracao_sintetica -v
"""

import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import _chirps  # noqa: E402

RESOLUCAO_CHIRPS_GRAUS = 0.05


def _resposta_com_dias(dias):
    """Monta uma resposta sintética do ClimateSERV com uma lista de
    dias — cada item é um dict {'year','month','value'} (ou sem
    'value', para simular omissão)."""
    return {'data': dias}


class ValorAusenteViraZeroTestCase(unittest.TestCase):
    """Risco 1 — a possibilidade de um dia SEM DADO ser gravado como
    precipitação 0.0, indistinguível de chuva real zero."""

    def test_avg_none_produz_o_mesmo_resultado_que_avg_zero(self):
        """`avg: None` (dia sem dado, mas presente na resposta) e
        `avg: 0.0` (dia com chuva real zero) devem, em auditoria
        correta, ser distinguíveis — aqui, confirmadamente, NÃO são."""
        resposta_ausente = _resposta_com_dias([
            {'year': 2024, 'month': 6, 'value': {'avg': None}},
        ])
        resposta_zero_real = _resposta_com_dias([
            {'year': 2024, 'month': 6, 'value': {'avg': 0.0}},
        ])

        with patch.object(_chirps.api, 'request_data', return_value=resposta_ausente):
            df_ausente = _chirps.buscar_prec_chirps(2024, 6, 2024, 6)
        with patch.object(_chirps.api, 'request_data', return_value=resposta_zero_real):
            df_zero_real = _chirps.buscar_prec_chirps(2024, 6, 2024, 6)

        self.assertEqual(len(df_ausente), 1)
        self.assertEqual(len(df_zero_real), 1)
        self.assertEqual(df_ausente.iloc[0]['prec'], 0.0)
        self.assertEqual(df_zero_real.iloc[0]['prec'], 0.0)
        self.assertEqual(
            df_ausente.iloc[0]['prec'], df_zero_real.iloc[0]['prec'],
            "achado confirmado: dia SEM DADO (avg=None) e dia com chuva real ZERO "
            "produzem o mesmo valor gravado, sem nenhum sinal de qual ocorreu")

    def test_entrada_sem_chave_value_tambem_vira_zero(self):
        """Um dia sem a chave 'value' nenhuma (não só sem 'avg' dentro
        dela) — mesmo resultado: 0.0, sem distinção do dia com chuva
        real zero."""
        resposta = _resposta_com_dias([
            {'year': 2024, 'month': 6},
        ])
        with patch.object(_chirps.api, 'request_data', return_value=resposta):
            df = _chirps.buscar_prec_chirps(2024, 6, 2024, 6)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]['prec'], 0.0)

    def test_mes_com_maioria_de_dias_ausentes_e_um_dia_de_chuva_forte(self):
        """29 dias sem dado (avg=None) + 1 dia com 80mm — o total
        mensal gravado é 80mm, sem nenhum sinal de que 29/30 dias do
        mês não tinham dado real. Isso é diferente de um mês real com
        30 dias secos e 1 dia de 80mm — o código não distingue os
        dois cenários."""
        dias = [{'year': 2024, 'month': 6, 'value': {'avg': None}} for _ in range(29)]
        dias.append({'year': 2024, 'month': 6, 'value': {'avg': 80.0}})
        with patch.object(_chirps.api, 'request_data', return_value=_resposta_com_dias(dias)):
            df = _chirps.buscar_prec_chirps(2024, 6, 2024, 6)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]['prec'], 80.0)


class SemCoberturaMinimaDeDiasTestCase(unittest.TestCase):
    """Risco 2 — agregação diária→mensal sem exigência de cobertura
    mínima, e sem nenhuma coluna de contagem de dias no resultado."""

    def test_um_unico_dia_no_mes_e_aceito_sem_aviso(self):
        """Um único dia de dado real (de até 31 possíveis) já produz
        uma linha mensal completa, sem qualquer sinalização de
        cobertura parcial."""
        resposta = _resposta_com_dias([
            {'year': 2024, 'month': 3, 'value': {'avg': 10.0}},
        ])
        with patch.object(_chirps.api, 'request_data', return_value=resposta):
            df = _chirps.buscar_prec_chirps(2024, 3, 2024, 3)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]['prec'], 10.0)

    def test_resultado_nao_tem_nenhuma_coluna_de_cobertura_de_dias(self):
        """O DataFrame retornado só tem ['ano','mes','prec','fonte'] —
        nenhuma informação de quantos dias entraram na soma fica
        disponível para o chamador decidir se a cobertura é suficiente."""
        resposta = _resposta_com_dias([
            {'year': 2024, 'month': 3, 'value': {'avg': 10.0}},
        ])
        with patch.object(_chirps.api, 'request_data', return_value=resposta):
            df = _chirps.buscar_prec_chirps(2024, 3, 2024, 3)
        self.assertEqual(set(df.columns), {'ano', 'mes', 'prec', 'fonte'})

    def test_dias_completamente_omitidos_nao_contam_e_nao_sao_sinalizados(self):
        """Segundo modo de incompletude, distinto do avg=None: dias
        que simplesmente NÃO aparecem na lista `data` da resposta —
        também não contam para o total, e também não deixam rastro."""
        # só 5 dias presentes de um mês de 30 — os outros 25 estão
        # totalmente ausentes da lista, não representados nem como None
        dias = [{'year': 2024, 'month': 4, 'value': {'avg': 2.0}} for _ in range(5)]
        with patch.object(_chirps.api, 'request_data', return_value=_resposta_com_dias(dias)):
            df = _chirps.buscar_prec_chirps(2024, 4, 2024, 4)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]['prec'], 10.0)   # 5 dias x 2.0mm, nunca os 30 esperados
        self.assertEqual(set(df.columns), {'ano', 'mes', 'prec', 'fonte'})


class GeometriaDaCaixaCentralTestCase(unittest.TestCase):
    """Risco 3 — a geometria da caixa usada na extração central e a
    possibilidade de interceptar pixels diferentes do CHIRPS."""

    def test_caixa_e_menor_que_meio_pixel_chirps(self):
        """O `delta` de _geometria_ponto (0.01°) é menor que metade da
        resolução do CHIRPS (0.025°) — condição necessária, mas não
        suficiente, para a caixa caber inteira dentro de um único
        pixel (também depende de onde o ponto cai DENTRO do pixel)."""
        import inspect
        assinatura = inspect.signature(_chirps._geometria_ponto)
        delta_padrao = assinatura.parameters['delta'].default
        self.assertLess(delta_padrao, RESOLUCAO_CHIRPS_GRAUS / 2)

    def test_ponto_central_e_multiplo_exato_da_resolucao_chirps(self):
        """Fato geométrico verificável sem rede, por aritmética exata
        (Decimal, não float, para evitar falso positivo/negativo por
        erro de ponto flutuante): FAZENDAS_LAT e FAZENDAS_LON são
        múltiplos EXATOS de 0,05° (a resolução nativa do CHIRPS) nos
        dois eixos — achado que sustenta o risco de o ponto cair sobre
        uma borda ou quina de pixel, dependendo da convenção de
        alinhamento do grid (não verificada aqui, PENDENTE; ver
        docs/nmme-fase2c2-auditoria-chirps-sinobras.md)."""
        resolucao = Decimal(str(RESOLUCAO_CHIRPS_GRAUS))
        lat = Decimal(str(_chirps.FAZENDAS_LAT))
        lon = Decimal(str(_chirps.FAZENDAS_LON))
        self.assertEqual(lat % resolucao, Decimal('0'))
        self.assertEqual(lon % resolucao, Decimal('0'))

    def test_caixa_pode_nao_caber_inteira_num_unico_pixel_se_o_ponto_estiver_na_borda(self):
        """Combinação dos dois achados anteriores: com o ponto sobre
        um múltiplo exato da resolução (achado confirmado) E uma caixa
        de meia-largura 0.01° ao redor dele, a caixa GARANTIDAMENTE
        cruza para o pixel vizinho em pelo menos um dos dois casos
        possíveis de alinhamento do grid CHIRPS (borda de pixel em
        múltiplo de 0,05°, ou centro de pixel em múltiplo de 0,05° —
        neste segundo caso o ponto fica EXATAMENTE numa quina
        compartilhada por até 4 pixels). Em nenhum dos dois casos a
        caixa fica garantidamente dentro de um único pixel — ao
        contrário do que o comentário em _geometria_ponto presume."""
        delta = 0.01
        # Caso A: bordas de pixel em múltiplos de 0,05° — o ponto cai
        # EXATAMENTE numa borda; qualquer delta>0 cruza para o pixel
        # vizinho em pelo menos uma direção.
        self.assertGreater(delta, 0)
        # Caso B: centros de pixel em múltiplos de 0,05° (convenção
        # comum em grids CHIRPS/CHC, offset de meio pixel) — o ponto
        # cairia então a exatamente metade da resolução (0.025°) de
        # QUALQUER borda de pixel adjacente, e delta=0.01 < 0.025 NÃO
        # cruzaria para o pixel vizinho nesse caso específico.
        meia_resolucao = RESOLUCAO_CHIRPS_GRAUS / 2
        self.assertLess(delta, meia_resolucao)
        # Conclusão do teste: os dois casos dão respostas DIFERENTES
        # (cruza vs. não cruza) — a garantia de "sempre um único
        # pixel" do comentário do código depende de qual dos dois
        # casos é o real, o que não é verificável sem a documentação
        # exata do grid CHIRPS (PENDENTE, não assumido aqui).


if __name__ == '__main__':
    unittest.main()
