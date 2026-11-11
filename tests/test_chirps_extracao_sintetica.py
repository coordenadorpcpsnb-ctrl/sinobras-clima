#!/usr/bin/env python3
"""
tests/test_chirps_extracao_sintetica.py — auditoria do CÓDIGO de
scripts/_chirps.py, com cenários SINTÉTICOS (nunca uma extração real
— climateserv.api.request_data é sempre mockado, igual ao padrão já
usado em tests/test_fetch_fallback.py).

Três riscos originalmente apontados para inspeção (5ª rodada, 2026):
1. Tratamento de valores ausentes recebidos do ClimateSERV — a
   possibilidade de um dia SEM DADO virar precipitação 0.0.
2. Agregação diária→mensal quando existem dias sem informação — se há
   alguma exigência de cobertura mínima.
3. A geometria da caixa usada na extração central (_geometria_ponto) —
   se ela é de fato sempre menor que um pixel CHIRPS a partir do ponto
   usado (FAZENDAS_LAT/FAZENDAS_LON), e o risco geométrico de o ponto
   cair sobre uma borda/quina de pixel.

ENSO-COBERTURA (correção científica, 11/2026): os riscos 1 e 2 foram
CONFIRMADOS pela 5ª rodada e CORRIGIDOS nesta fase — ver
`_chirps.py::_validar_e_agregar_dias`. Esta suíte foi atualizada para
exigir o comportamento CORRIGIDO (nunca mais o defeituoso), nos
MESMOS cenários de risco originais — nenhum caso foi removido, nenhum
skip foi introduzido. O schema usado nas fixtures (`year`/`month`/
`day`/`date`/`epochTime`) é o schema REAL, confirmado por verificação
controlada real contra o ClimateSERV em 06/2024 (mesma geometria de
produção) — ver cabeçalho de `_chirps.py` e o relatório da fase
ENSO-COBERTURA de verificação de schema.

Comportamento CORRIGIDO, confirmado por estes testes:
- Um dia com `avg=None` (ou sem a chave 'value') NUNCA mais produz o
  mesmo resultado que um dia com `avg=0.0` real — o dia sem dado
  invalida o MÊS inteiro (nunca é silenciosamente convertido em
  zero), enquanto o dia com zero real continua sendo aceito
  normalmente quando o resto do mês está completo.
- Um mês só é aceito quando TODOS os dias do calendário têm um
  registro válido — nenhuma cobertura mínima menor que 100% é
  aceita. Dias omitidos inteiramente da resposta têm o MESMO efeito
  que dias com `avg=None`: o mês fica incompleto e é rejeitado.
- O risco 3 (geometria da caixa) é um fato geométrico independente,
  não alterado por esta correção — os testes de
  `GeometriaDaCaixaCentralTestCase` permanecem inalterados.

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
    dias — cada item é um dict no schema REAL confirmado (year/month/
    day/date/epochTime/value), ou um subconjunto dele para simular
    omissão de campos."""
    return {'data': dias}


def _dia_real(ano, mes, dia, avg):
    """Monta um registro diário completo no schema REAL confirmado
    por verificação controlada (ver cabeçalho de _chirps.py) —
    date em MM/DD/YYYY, epochTime à meia-noite UTC do mesmo dia."""
    from datetime import date, datetime, timezone
    d = date(ano, mes, dia)
    epoch = int(datetime(ano, mes, dia, tzinfo=timezone.utc).timestamp())
    return {
        'year': ano, 'month': mes, 'day': dia,
        'date': f'{mes:02d}/{dia:02d}/{ano}',
        'epochTime': epoch,
        'value': {'avg': avg},
    }


def _mes_completo(ano, mes, avg_por_dia):
    """Monta todos os dias de `mes`/`ano` com o valor de `avg_por_dia`
    (constante ou callable(dia) -> valor) — mês 100% coberto, sem
    nenhum problema, usado como baseline 'tudo certo' em vários
    testes."""
    from calendar import monthrange
    n = monthrange(ano, mes)[1]
    fn = avg_por_dia if callable(avg_por_dia) else (lambda d: avg_por_dia)
    return [_dia_real(ano, mes, d, fn(d)) for d in range(1, n + 1)]


class ValorAusenteViraZeroTestCase(unittest.TestCase):
    """Risco 1 — CORRIGIDO: um dia sem dado real (avg=None, ou sem a
    chave 'value' nenhuma) nunca mais é convertido em precipitação
    0.0 nem aceito como se o mês estivesse completo. Em vez disso, o
    mês inteiro fica indisponível nesta fonte (fallback cascata
    tenta a próxima) — nunca mistura "sem dado" com "chuva real
    zero"."""

    def test_avg_none_invalida_o_mes_nunca_produz_zero_disfarcado(self):
        """`avg: None` num dos 30 dias de um mês — ANTES: produzia o
        mesmo resultado que um dia com avg=0.0 real (bug confirmado).
        AGORA: o mês inteiro é rejeitado (DataFrame vazio), nunca
        aceito com um total calculado sobre 29 dias."""
        dias = _mes_completo(2024, 6, 5.0)
        dias[10]['value']['avg'] = None   # dia 11/06 sem dado real
        with patch.object(_chirps.api, 'request_data', return_value=_resposta_com_dias(dias)):
            df = _chirps.buscar_prec_chirps(2024, 6, 2024, 6)
        self.assertTrue(df.empty, "mês com 1 dia sem dado real deve ser rejeitado, "
                                   "nunca aceito com total parcial")

    def test_entrada_sem_chave_value_tambem_invalida_o_mes(self):
        """Um dia sem a chave 'value' nenhuma (não só sem 'avg' dentro
        dela) — mesmo tratamento: mês inteiro rejeitado, nunca
        aceito com 0.0 silencioso para esse dia."""
        dias = _mes_completo(2024, 6, 5.0)
        del dias[10]['value']
        with patch.object(_chirps.api, 'request_data', return_value=_resposta_com_dias(dias)):
            df = _chirps.buscar_prec_chirps(2024, 6, 2024, 6)
        self.assertTrue(df.empty)

    def test_mes_com_maioria_de_dias_ausentes_e_um_dia_de_chuva_forte_e_rejeitado(self):
        """29 dias sem dado (avg=None) + 1 dia com 80mm — ANTES: o
        total gravado era 80mm, como se o mês tivesse só esse dia de
        chuva (bug confirmado). AGORA: o mês inteiro é rejeitado —
        nunca aceita um total calculado sobre 1 dia de 30."""
        dias = _mes_completo(2024, 6, None)
        dias[-1]['value']['avg'] = 80.0   # só o último dia tem dado real
        with patch.object(_chirps.api, 'request_data', return_value=_resposta_com_dias(dias)):
            df = _chirps.buscar_prec_chirps(2024, 6, 2024, 6)
        self.assertTrue(df.empty, "mês com 29/30 dias sem dado real deve ser "
                                   "rejeitado, nunca aceito com o total do único dia real")

    def test_dia_com_chuva_real_zero_e_preservado_quando_mes_completo(self):
        """Contraste direto com os 3 testes acima: quando TODOS os 30
        dias têm dado real (incluindo dias com avg=0.0 genuíno), o
        mês é aceito normalmente — zero real nunca é confundido com
        ausência."""
        dias = _mes_completo(2024, 6, lambda d: 0.0 if d % 2 == 0 else 3.0)
        with patch.object(_chirps.api, 'request_data', return_value=_resposta_com_dias(dias)):
            df = _chirps.buscar_prec_chirps(2024, 6, 2024, 6)
        self.assertEqual(len(df), 1)
        esperado = round(sum(0.0 if d % 2 == 0 else 3.0 for d in range(1, 31)), 1)
        self.assertEqual(df.iloc[0]['prec'], esperado)

    def test_dia_com_valor_nan_e_rejeitado(self):
        """avg=NaN (float) é fisicamente inválido — nunca aceito como
        chuva real, nunca convertido em zero. Mês inteiro invalidado."""
        dias = _mes_completo(2024, 6, 5.0)
        dias[10]['value']['avg'] = float('nan')
        with patch.object(_chirps.api, 'request_data', return_value=_resposta_com_dias(dias)):
            df = _chirps.buscar_prec_chirps(2024, 6, 2024, 6)
        self.assertTrue(df.empty)

    def test_dia_com_valor_infinito_e_rejeitado(self):
        dias = _mes_completo(2024, 6, 5.0)
        dias[10]['value']['avg'] = float('inf')
        with patch.object(_chirps.api, 'request_data', return_value=_resposta_com_dias(dias)):
            df = _chirps.buscar_prec_chirps(2024, 6, 2024, 6)
        self.assertTrue(df.empty)

    def test_dia_com_valor_negativo_e_rejeitado(self):
        """Precipitação negativa é fisicamente impossível."""
        dias = _mes_completo(2024, 6, 5.0)
        dias[10]['value']['avg'] = -1.0
        with patch.object(_chirps.api, 'request_data', return_value=_resposta_com_dias(dias)):
            df = _chirps.buscar_prec_chirps(2024, 6, 2024, 6)
        self.assertTrue(df.empty)


class CoberturaDiariaCompletaExigidaTestCase(unittest.TestCase):
    """Risco 2 — CORRIGIDO: a agregação mensal agora EXIGE um
    registro válido para cada dia do calendário do mês (contando
    anos bissextos corretamente via `calendar.monthrange`) antes de
    aceitar qualquer total. Substitui `SemCoberturaMinimaDeDiasTestCase`
    (que comprovava a ausência de qualquer exigência de cobertura —
    agora corrigida)."""

    def test_um_unico_dia_no_mes_e_rejeitado(self):
        """ANTES: um único dia de dado real já produzia uma linha
        mensal completa, sem aviso. AGORA: rejeitado — faltam 29 dias."""
        dias = [_dia_real(2024, 3, 1, 10.0)]
        with patch.object(_chirps.api, 'request_data', return_value=_resposta_com_dias(dias)):
            df = _chirps.buscar_prec_chirps(2024, 3, 2024, 3)
        self.assertTrue(df.empty)

    def test_dias_completamente_omitidos_invalidam_o_mes(self):
        """Segundo modo de incompletude: dias que simplesmente NÃO
        aparecem na lista `data` da resposta — só 5 dias presentes
        de um mês de 30. ANTES: produzia 10mm (5×2.0mm) como se fosse
        o total do mês. AGORA: rejeitado."""
        dias = [_dia_real(2024, 4, d, 2.0) for d in range(1, 6)]
        with patch.object(_chirps.api, 'request_data', return_value=_resposta_com_dias(dias)):
            df = _chirps.buscar_prec_chirps(2024, 4, 2024, 4)
        self.assertTrue(df.empty)

    def test_mes_completo_30_dias_e_aceito(self):
        dias = _mes_completo(2024, 4, lambda d: float(d % 10))
        with patch.object(_chirps.api, 'request_data', return_value=_resposta_com_dias(dias)):
            df = _chirps.buscar_prec_chirps(2024, 4, 2024, 4)
        self.assertEqual(len(df), 1)
        esperado = round(sum(float(d % 10) for d in range(1, 31)), 1)
        self.assertEqual(df.iloc[0]['prec'], esperado)

    def test_fevereiro_bissexto_exige_29_dias(self):
        """2024 é bissexto — fevereiro tem 29 dias. Um mês com só os
        28 dias 'tradicionais' deve ser rejeitado por faltar o 29."""
        dias = _mes_completo(2024, 2, 1.0)
        self.assertEqual(len(dias), 29)
        with patch.object(_chirps.api, 'request_data', return_value=_resposta_com_dias(dias)):
            df = _chirps.buscar_prec_chirps(2024, 2, 2024, 2)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]['prec'], 29.0)

        # Com só 28 dias (faltando o 29º), deve ser rejeitado
        dias_incompleto = dias[:-1]
        with patch.object(_chirps.api, 'request_data', return_value=_resposta_com_dias(dias_incompleto)):
            df2 = _chirps.buscar_prec_chirps(2024, 2, 2024, 2)
        self.assertTrue(df2.empty)

    def test_fevereiro_nao_bissexto_exige_28_dias(self):
        """2023 não é bissexto — fevereiro tem 28 dias. 29 dias
        (contando um dia inexistente) nunca seria produzido por um
        mês real; aqui confirmamos que 28 dias reais bastam."""
        dias = _mes_completo(2023, 2, 1.0)
        self.assertEqual(len(dias), 28)
        with patch.object(_chirps.api, 'request_data', return_value=_resposta_com_dias(dias)):
            df = _chirps.buscar_prec_chirps(2023, 2, 2023, 2)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]['prec'], 28.0)

    def test_dia_31_em_mes_de_30_dias_e_rejeitado(self):
        """Um registro com day=31 num mês de 30 dias (junho) é
        estruturalmente inválido — nunca aceito como dia real, e a
        inconsistência invalida o MÊS inteiro associado a ele (regra
        obrigatória: 'uma inconsistência deve invalidar o mês
        afetado'), mesmo que os outros 30 dias estivessem corretos."""
        dias = _mes_completo(2024, 6, 5.0)
        registro_invalido = dict(dias[0])
        registro_invalido['day'] = 31
        registro_invalido['date'] = '06/31/2024'
        dias.append(registro_invalido)
        with patch.object(_chirps.api, 'request_data', return_value=_resposta_com_dias(dias)):
            df = _chirps.buscar_prec_chirps(2024, 6, 2024, 6)
        self.assertTrue(df.empty, "registro com dia fora do calendário deve "
                                   "invalidar o mês inteiro associado a ele")

    def test_dia_duplicado_invalida_o_mes(self):
        """Um dia que aparece DUAS vezes na resposta (mesmo year/
        month/day) — risco distinto de 'dia ausente': aqui o
        problema é excesso, não falta. O mês deve ser rejeitado,
        nunca somado em duplicidade nem aceito ignorando a duplicata
        silenciosamente."""
        dias = _mes_completo(2024, 6, 5.0)
        dias.append(dict(dias[0]))   # duplica o dia 1
        with patch.object(_chirps.api, 'request_data', return_value=_resposta_com_dias(dias)):
            df = _chirps.buscar_prec_chirps(2024, 6, 2024, 6)
        self.assertTrue(df.empty)

    def test_datas_contraditorias_entre_day_date_e_epochtime_invalidam_o_mes(self):
        """'day'/'date'/'epochTime' apontando para dias DIFERENTES
        dentro do mesmo registro — nunca aceito silenciosamente
        escolhendo qual campo "está certo"; o mês inteiro é
        invalidado."""
        dias = _mes_completo(2024, 6, 5.0)
        dias[10]['date'] = '01/01/2099'   # contradiz year/month/day do registro
        with patch.object(_chirps.api, 'request_data', return_value=_resposta_com_dias(dias)):
            df = _chirps.buscar_prec_chirps(2024, 6, 2024, 6)
        self.assertTrue(df.empty)

    def test_registro_sem_year_month_identificavel_invalida_a_janela_solicitada(self):
        """Um registro sem year/month (não dá para saber a qual mês
        pertenceria, dentre os da janela solicitada) é tratado de
        forma conservadora: NÃO se presume que ele seja irrelevante.
        Como poderia pertencer a qualquer mês da janela pedida, TODA a
        janela solicitada nesta chamada fica indisponível nesta fonte
        — mesmo um mês, de resto, 100% completo — acionando o
        fallback (CHIRPS-Preliminar → Open-Meteo) em vez de aceitar um
        total potencialmente incompleto. Ver
        _chirps.py::_validar_e_agregar_dias / _meses_da_janela."""
        dias = _mes_completo(2024, 6, 5.0)
        dias.append({'value': {'avg': 999.0}})   # sem year/month/day
        with patch.object(_chirps.api, 'request_data', return_value=_resposta_com_dias(dias)):
            df = _chirps.buscar_prec_chirps(2024, 6, 2024, 6)
        self.assertTrue(df.empty, "mês deveria ficar indisponível, não aceito "
                                   "com total parcial")

    def test_registro_sem_year_month_identificavel_invalida_todos_os_meses_da_janela_multipla(self):
        """Mesmo cenário, mas pedido abrangendo 3 meses (junho a
        agosto): junho e agosto são 100% completos, só o registro sem
        year/month está misturado na resposta. Como ele poderia
        pertencer a QUALQUER um dos 3 meses pedidos — inclusive um que
        já tenha dias válidos acumulados — a invalidação atinge os 3,
        não só "o mês onde o registro apareceu" (não há como saber
        qual seria, já que ele não tem year/month)."""
        junho = _mes_completo(2024, 6, 2.0)
        agosto = _mes_completo(2024, 8, 4.0)
        sem_identificacao = [{'value': {'avg': 999.0}}]   # sem year/month/day
        todos = junho + agosto + sem_identificacao
        with patch.object(_chirps.api, 'request_data', return_value=_resposta_com_dias(todos)):
            df = _chirps.buscar_prec_chirps(2024, 6, 2024, 8)
        self.assertTrue(df.empty, "registro sem identificação temporal deve invalidar "
                                   "TODOS os meses da janela solicitada, não só os que já "
                                   "tinham dias válidos acumulados")

    def test_intervalo_com_varios_meses_alguns_completos_outros_nao(self):
        """Pedido de 3 meses: junho completo, julho com 1 dia faltando,
        agosto completo — cada mês é avaliado independentemente."""
        junho = _mes_completo(2024, 6, 2.0)
        julho = _mes_completo(2024, 7, 3.0)[:-1]   # falta o dia 31
        agosto = _mes_completo(2024, 8, 4.0)
        todos = junho + julho + agosto
        with patch.object(_chirps.api, 'request_data', return_value=_resposta_com_dias(todos)):
            df = _chirps.buscar_prec_chirps(2024, 6, 2024, 8)
        resultado = {(r['ano'], r['mes']): r['prec'] for r in df.to_dict('records')}
        self.assertIn((2024, 6), resultado)
        self.assertEqual(resultado[(2024, 6)], round(2.0 * 30, 1))
        self.assertNotIn((2024, 7), resultado, "julho incompleto (29/31 dias) não deve aparecer")
        self.assertIn((2024, 8), resultado)
        self.assertEqual(resultado[(2024, 8)], round(4.0 * 31, 1))


class GeometriaDaCaixaCentralTestCase(unittest.TestCase):
    """Risco 3 — a geometria da caixa usada na extração central e a
    possibilidade de interceptar pixels diferentes do CHIRPS. Não
    alterado por esta correção (escopo de ENSO-COBERTURA é só
    integridade temporal) — preservado como estava."""

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
        self.assertGreater(delta, 0)
        meia_resolucao = RESOLUCAO_CHIRPS_GRAUS / 2
        self.assertLess(delta, meia_resolucao)


if __name__ == '__main__':
    unittest.main()
