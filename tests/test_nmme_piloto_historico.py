#!/usr/bin/env python3
"""
tests/test_nmme_piloto_historico.py — regressão do piloto histórico
CFSv2 (Fase 2C.2): scripts/nmme_piloto_historico.py. Tudo offline —
baixar_fn/abrir_fn são sempre injetados (nunca requests/xarray reais);
os datasets usados são SINTÉTICOS, nunca um subset NMME real (a rede
real nunca é acessada nesta tarefa).

O piloto reaproveita nmme_poc.executar_poc_real_cfsv2/
avaliar_aprovacao_poc SEM modificação — os guardrails de integridade
(seleção temporal, membros, unidade, grade, mapeamento temporal) já têm
cobertura própria em tests/test_nmme_poc_real_cfsv2.py e não são
reexercitados em detalhe aqui. O que este arquivo testa é a
ORQUESTRAÇÃO específica do piloto: isolamento de falha por origem,
agregação das 16 origens, classificação de cobertura observacional, e
os critérios de aprovação do piloto (distintos dos critérios de
aprovação de cada origem isolada).

Roda com:
    python -m unittest tests.test_nmme_piloto_historico -v
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import nmme_catalogo as ncat  # noqa: E402
import nmme_piloto_historico as pilo  # noqa: E402
import nmme_poc as npoc  # noqa: E402
from _c3s_utils import MUNICIPIOS  # noqa: E402

SAO_BENTO = MUNICIPIOS['Sao_Bento_do_Tocantins']


def _ds_para_origem(ano, mes, n_membros=24, valor_base=5.0, escala=3.0):
    """Dataset sintético válido (Representação B) para 1 origem — S
    scalar/singleton com o valor exato pedido (nunca ambíguo), 24
    membros, H1-H6, unidade mm/day."""
    lon_sb_360 = SAO_BENTO['lon'] % 360.0
    lons = np.array([lon_sb_360 - 1.0, lon_sb_360, lon_sb_360 + 1.0])
    lats = np.array([SAO_BENTO['lat'] - 1.0, SAO_BENTO['lat'], SAO_BENTO['lat'] + 1.0])
    l_valores = (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)
    membros = np.arange(1, n_membros + 1)
    rng = np.random.RandomState(ano * 100 + mes)
    dados = valor_base + rng.rand(3, 3, len(l_valores), n_membros) * escala
    da_S = xr.DataArray([pd.Timestamp(f'{ano}-{mes:02d}-01')], dims=('S',),
                          attrs={'standard_name': 'forecast_reference_time'})
    da_L = xr.DataArray(np.array(l_valores), dims=('L',),
                          attrs={'units': 'months', 'standard_name': 'forecast_period'})
    prec = xr.DataArray(dados, dims=('X', 'Y', 'L', 'M'),
                          coords={'X': lons, 'Y': lats, 'L': da_L, 'M': membros, 'S': da_S.isel(S=0)})
    prec.attrs['units'] = 'mm/day'
    return xr.Dataset({'prec': prec})


def _baixar_ok(url, destino):
    return ('/tmp/fake-piloto-nmme.nc', False)


def _baixar_falha(url, destino):
    raise RuntimeError('rede indisponível simulada')


def _resolver_todas_ok(ano, mes):
    return _baixar_ok, (lambda c, ano=ano, mes=mes: _ds_para_origem(ano, mes))


def _resolver_com_uma_falha(origem_com_falha):
    def resolver(ano, mes):
        if (ano, mes) == origem_com_falha:
            return _baixar_falha, (lambda c: _ds_para_origem(ano, mes))
        return _baixar_ok, (lambda c, ano=ano, mes=mes: _ds_para_origem(ano, mes))
    return resolver


class PilotoOrigensTestCase(unittest.TestCase):
    """A — as 16 origens são exatamente 4 anos x 4 meses, decisão
    técnica adotada (Seção 1 da tarefa)."""

    def test_a_sao_16_origens(self):
        self.assertEqual(len(pilo.PILOTO_ORIGENS), 16)

    def test_a_anos_e_meses_esperados(self):
        self.assertEqual(pilo.PILOTO_ANOS, (1991, 1998, 2005, 2010))
        self.assertEqual(pilo.PILOTO_MESES, (1, 4, 7, 10))
        for ano in pilo.PILOTO_ANOS:
            for mes in pilo.PILOTO_MESES:
                self.assertIn((ano, mes), pilo.PILOTO_ORIGENS)

    def test_a_periodo_dentro_de_1991_2010(self):
        anos = [a for a, _ in pilo.PILOTO_ORIGENS]
        self.assertGreaterEqual(min(anos), 1991)
        self.assertLessEqual(max(anos), 2010)


class ExecucaoTodasOkTestCase(unittest.TestCase):
    """B — as 16 origens processadas com sucesso (fixture sintética
    válida em todas) resultam em 16 APROVADO."""

    def test_b_16_resultados_na_ordem_das_origens(self):
        resultados = pilo.executar_piloto_historico(resolver_fns=_resolver_todas_ok)
        self.assertEqual(len(resultados), 16)
        self.assertEqual([r['origem'] for r in resultados], list(pilo.PILOTO_ORIGENS))

    def test_b_todas_aprovadas(self):
        resultados = pilo.executar_piloto_historico(resolver_fns=_resolver_todas_ok)
        self.assertTrue(all(r['resultado']['poc_status'] == 'APROVADO' for r in resultados))
        self.assertTrue(all(r['erro'] is None for r in resultados))

    def test_b_representacao_usada_e_harmonizada(self):
        """Nunca a Representação A nem CCSR — a rota EMPIRICALLY_CONFIRMED
        (Fase 2C.1b) é a única esperada aqui, reaproveitada sem alteração."""
        resultados = pilo.executar_piloto_historico(resolver_fns=_resolver_todas_ok)
        for r in resultados:
            self.assertEqual(r['resultado']['dataset_representation_used'],
                              ncat.REPR_NMME_HARMONIZED_MONTHLY)

    def test_b_url_de_cada_origem_usa_rangeedges_nunca_value_em_s(self):
        """Regressão — o piloto reaproveita executar_poc_real_cfsv2 sem
        modificação; confirma que a arquitetura RANGEEDGES-fonte-
        principal (Fase 2C.1b) continua em vigor para cada uma das 16
        chamadas, não só para a origem única do POC."""
        chamadas = []

        def baixar_registra(url, destino):
            chamadas.append(url)
            return ('/tmp/fake.nc', False)

        def resolver(ano, mes):
            return baixar_registra, (lambda c, ano=ano, mes=mes: _ds_para_origem(ano, mes))

        pilo.executar_piloto_historico(origens=((1991, 1), (2010, 10)), resolver_fns=resolver)
        self.assertEqual(len(chamadas), 2)
        for url in chamadas:
            self.assertIn('RANGEEDGES/', url)
            self.assertNotIn('S/(Jan%201991)/VALUE/', url)


class IsolamentoDeFalhaTestCase(unittest.TestCase):
    """C — item 7 da tarefa: "registrar individualmente qualquer
    falha", nunca interromper as demais origens."""

    def test_c_uma_origem_com_falha_de_download_nao_derruba_as_outras(self):
        resultados = pilo.executar_piloto_historico(
            resolver_fns=_resolver_com_uma_falha((1998, 7)))
        self.assertEqual(len(resultados), 16)
        por_origem = {r['origem']: r for r in resultados}
        self.assertEqual(por_origem[(1998, 7)]['resultado']['poc_status'], 'REPROVADO_ACESSO')
        outras = [r for o, r in por_origem.items() if o != (1998, 7)]
        self.assertTrue(all(r['resultado']['poc_status'] == 'APROVADO' for r in outras))

    def test_c_excecao_inesperada_na_resolucao_de_dependencia_e_isolada(self):
        """Regressão de um bug real encontrado ao testar esta tarefa: a
        primeira versão de executar_piloto_historico chamava
        `resolver_fns(ano, mes)` FORA do bloco try/except — uma exceção
        aí escapava sem isolamento e derrubava o laço inteiro. Corrigido
        movendo a chamada para dentro do try; este teste prova que uma
        origem cuja PRÓPRIA preparação de dependência falha (não só o
        download) continua isolada das demais."""
        def resolver_quebrado(ano, mes):
            if (ano, mes) == (2005, 1):
                raise ValueError('bug simulado')
            return _resolver_todas_ok(ano, mes)

        resultados = pilo.executar_piloto_historico(
            origens=((2005, 1), (2005, 4)), resolver_fns=resolver_quebrado)
        por_origem = {r['origem']: r for r in resultados}
        self.assertTrue(por_origem[(2005, 1)]['resultado']['poc_status']
                          .startswith('ERRO_INESPERADO_'))
        self.assertIsNotNone(por_origem[(2005, 1)]['erro'])
        self.assertEqual(por_origem[(2005, 4)]['resultado']['poc_status'], 'APROVADO')
        self.assertIsNone(por_origem[(2005, 4)]['erro'])

    def test_c_resumo_por_origem_registra_a_falha_individualmente(self):
        resultados = pilo.executar_piloto_historico(
            resolver_fns=_resolver_com_uma_falha((2010, 4)))
        resumo = pilo.montar_resumo_por_origem(resultados)
        self.assertEqual(len(resumo), 16)
        linha_falha = resumo[(resumo['ano'] == 2010) & (resumo['mes'] == 4)].iloc[0]
        self.assertEqual(linha_falha['poc_status'], 'REPROVADO_ACESSO')
        linhas_ok = resumo[~((resumo['ano'] == 2010) & (resumo['mes'] == 4))]
        self.assertTrue((linhas_ok['poc_status'] == 'APROVADO').all())


class AgregacaoTestCase(unittest.TestCase):
    """D — concatenar_dataframes_piloto junta as 16 origens preservando
    rastreabilidade (coluna origem_piloto), sem perder/duplicar linhas."""

    def test_d_raw_tem_24_membros_x_6_leads_x_16_origens_quando_tudo_ok(self):
        resultados = pilo.executar_piloto_historico(resolver_fns=_resolver_todas_ok)
        raw_df, temporal_df, access_df = pilo.concatenar_dataframes_piloto(resultados)
        self.assertEqual(len(raw_df), 24 * 6 * 16)
        self.assertEqual(len(temporal_df), 6 * 16)
        self.assertEqual(set(raw_df['origem_piloto']), {f'{a}-{m:02d}' for a, m in pilo.PILOTO_ORIGENS})

    def test_d_origem_com_falha_de_acesso_nao_contribui_raw(self):
        resultados = pilo.executar_piloto_historico(
            resolver_fns=_resolver_com_uma_falha((1991, 10)))
        raw_df, _, _ = pilo.concatenar_dataframes_piloto(resultados)
        self.assertNotIn('1991-10', set(raw_df['origem_piloto']))
        self.assertEqual(len(raw_df), 24 * 6 * 15)


class CoberturaObservacionalTestCase(unittest.TestCase):
    """E — Seção 1 da tarefa (revisão pontual): separar disponibilidade,
    procedência documental e qualidade EFETIVAMENTE VERIFICADA — nunca
    colapsar num único "confirmado". Usa uma série FABRICADA (nunca o
    arquivo real) para determinismo — a cobertura contra o arquivo real
    é testada à parte (RealSerieObservacionalTestCase)."""

    @staticmethod
    def _serie_fabricada():
        linhas = []
        # mês com fonte vazia, ano <= 1995 -> procedência MERRA-2
        linhas.append({'ano': 1991, 'mes': 1, 'prec': 100.0, 'fonte': None})
        # mês com fonte vazia, ano > 1995 -> procedência Estação Sinobras
        linhas.append({'ano': 1998, 'mes': 6, 'prec': 40.0, 'fonte': None})
        # mês com fonte='CHIRPS' (CHIRPS Final)
        linhas.append({'ano': 1991, 'mes': 2, 'prec': 50.0, 'fonte': 'CHIRPS'})
        # mês com fonte preliminar -> nunca usar como observação real
        linhas.append({'ano': 1991, 'mes': 3, 'prec': 30.0, 'fonte': 'CHC-Preliminar'})
        # mês com fonte ERA5 (fallback final) -> idem, nunca usar
        linhas.append({'ano': 1991, 'mes': 4, 'prec': 10.0, 'fonte': 'OpenMeteo-ERA5'})
        # mês com valor ausente (NaN) mesmo com fonte vazia
        linhas.append({'ano': 1991, 'mes': 5, 'prec': np.nan, 'fonte': None})
        # mês com valor fisicamente implausível (negativo)
        linhas.append({'ano': 1991, 'mes': 6, 'prec': -5.0, 'fonte': None})
        # mês com valor fisicamente implausível (acima do limite)
        linhas.append({'ano': 1991, 'mes': 7, 'prec': 99999.0, 'fonte': None})
        # (1991-08 deliberadamente ausente -> AUSENTE)
        return pd.DataFrame(linhas)

    @staticmethod
    def _serie_com_duplicata():
        return pd.DataFrame([
            {'ano': 1991, 'mes': 1, 'prec': 100.0, 'fonte': None},
            {'ano': 1991, 'mes': 1, 'prec': 105.0, 'fonte': None},   # mesmo ano/mês de novo
        ])

    def _linha(self, cobertura, lead):
        return cobertura[(cobertura['origem_piloto'] == '1990-12') & (cobertura['H_lead'] == lead)].iloc[0]

    def test_e_fonte_vazia_ano_antigo_e_procedencia_merra2(self):
        # H2 de origem 1990-12 -> target 1991-01
        resultados = [{'ano': 1990, 'mes': 12, 'resultado': {}}]
        cobertura = pilo.verificar_cobertura_observacional(resultados, serie_df=self._serie_fabricada())
        linha = self._linha(cobertura, 2)
        self.assertEqual(linha['target_month'], '1991-01')
        self.assertEqual(linha['disponibilidade'], 'PRESENTE')
        self.assertEqual(linha['procedencia_documental'], pilo.PROCEDENCIA_MERRA2)
        self.assertEqual(linha['qualidade_verificada_status'], pilo.QUALIDADE_STATUS_OK)
        self.assertFalse(linha['fonte_e_substituta_nao_usar'])

    def test_e_fonte_vazia_ano_recente_e_procedencia_sinobras(self):
        # origem 1998-01, H6 -> target 1998-06
        resultados = [{'ano': 1998, 'mes': 1, 'resultado': {}}]
        cobertura = pilo.verificar_cobertura_observacional(resultados, serie_df=self._serie_fabricada())
        linha = cobertura[(cobertura['origem_piloto'] == '1998-01') & (cobertura['H_lead'] == 6)].iloc[0]
        self.assertEqual(linha['target_month'], '1998-06')
        self.assertEqual(linha['procedencia_documental'], pilo.PROCEDENCIA_ESTACAO_SINOBRAS)

    def test_e_fonte_chirps_procedencia_correta(self):
        resultados = [{'ano': 1990, 'mes': 12, 'resultado': {}}]
        cobertura = pilo.verificar_cobertura_observacional(resultados, serie_df=self._serie_fabricada())
        linha = self._linha(cobertura, 3)   # target 1991-02
        self.assertEqual(linha['procedencia_documental'], pilo.PROCEDENCIA_CHIRPS_FINAL)
        self.assertFalse(linha['fonte_e_substituta_nao_usar'])

    def test_e_fonte_preliminar_marcada_como_nao_usar(self):
        resultados = [{'ano': 1990, 'mes': 12, 'resultado': {}}]
        cobertura = pilo.verificar_cobertura_observacional(resultados, serie_df=self._serie_fabricada())
        linha = self._linha(cobertura, 4)   # target 1991-03
        self.assertEqual(linha['procedencia_documental'], pilo.PROCEDENCIA_CHC_PRELIMINAR)
        self.assertTrue(linha['fonte_e_substituta_nao_usar'])

    def test_e_fonte_era5_fallback_marcada_como_nao_usar(self):
        resultados = [{'ano': 1990, 'mes': 12, 'resultado': {}}]
        cobertura = pilo.verificar_cobertura_observacional(resultados, serie_df=self._serie_fabricada())
        linha = self._linha(cobertura, 5)   # target 1991-04
        self.assertEqual(linha['procedencia_documental'], pilo.PROCEDENCIA_ERA5)
        self.assertTrue(linha['fonte_e_substituta_nao_usar'])

    def test_e_mes_ausente_classificado_corretamente(self):
        # origem 1991-03, H6 -> target 1991-08 (fora do alcance de
        # 1990-12, cujo H6 máximo é 1991-05 — H_lead vai só até 6).
        resultados = [{'ano': 1991, 'mes': 3, 'resultado': {}}]
        cobertura = pilo.verificar_cobertura_observacional(resultados, serie_df=self._serie_fabricada())
        linha = cobertura[(cobertura['origem_piloto'] == '1991-03') & (cobertura['H_lead'] == 6)].iloc[0]
        self.assertEqual(linha['target_month'], '1991-08')
        self.assertEqual(linha['disponibilidade'], 'AUSENTE')
        self.assertTrue(pd.isna(linha['procedencia_documental']))
        self.assertEqual(linha['qualidade_verificada_status'],
                          pilo.QUALIDADE_STATUS_NAO_APLICAVEL_AUSENTE)

    def test_e_valor_ausente_na_serie_e_detectado(self):
        """Regressão — a versão anterior deste módulo NUNCA checava se
        `prec` era NaN quando o mês estava presente; um mês "disponível"
        podia ter valor numérico ausente e ainda assim ser chamado de
        observação confirmada."""
        resultados = [{'ano': 1990, 'mes': 12, 'resultado': {}}]
        cobertura = pilo.verificar_cobertura_observacional(resultados, serie_df=self._serie_fabricada())
        linha = self._linha(cobertura, 6)   # target 1991-05, prec=NaN
        self.assertEqual(linha['disponibilidade'], 'PRESENTE')
        self.assertIn(pilo.QUALIDADE_FLAG_VALOR_AUSENTE, linha['qualidade_verificada_status'])

    def test_e_valor_negativo_e_implausivel(self):
        # origem 1991-01, H6 -> target 1991-06
        resultados = [{'ano': 1991, 'mes': 1, 'resultado': {}}]
        cobertura = pilo.verificar_cobertura_observacional(resultados, serie_df=self._serie_fabricada())
        linha = cobertura[(cobertura['origem_piloto'] == '1991-01')
                            & (cobertura['target_month'] == '1991-06')].iloc[0]
        self.assertIn(pilo.QUALIDADE_FLAG_VALOR_IMPLAUSIVEL, linha['qualidade_verificada_status'])

    def test_e_valor_absurdamente_alto_e_implausivel(self):
        # origem 1991-02, H6 -> target 1991-07
        resultados = [{'ano': 1991, 'mes': 2, 'resultado': {}}]
        cobertura = pilo.verificar_cobertura_observacional(resultados, serie_df=self._serie_fabricada())
        linha = cobertura[(cobertura['origem_piloto'] == '1991-02')
                            & (cobertura['target_month'] == '1991-07')].iloc[0]
        self.assertIn(pilo.QUALIDADE_FLAG_VALOR_IMPLAUSIVEL, linha['qualidade_verificada_status'])

    def test_e_registro_duplicado_e_detectado(self):
        """Regressão — duplicata é uma propriedade da SÉRIE (mesmo
        ano/mês aparecendo mais de 1 vez), nunca escondida por um
        `.iloc[0]` que só olha a primeira ocorrência."""
        resultados = [{'ano': 1990, 'mes': 12, 'resultado': {}}]
        cobertura = pilo.verificar_cobertura_observacional(
            resultados, serie_df=self._serie_com_duplicata())
        linha = self._linha(cobertura, 2)   # target 1991-01
        self.assertIn(pilo.QUALIDADE_FLAG_REGISTRO_DUPLICADO, linha['qualidade_verificada_status'])

    def test_e_nunca_produz_uma_coluna_classificacao_unica(self):
        """Regressão explícita do achado desta revisão: a primeira
        versão tinha uma única coluna `classificacao` com o valor
        'OBSERVACAO_CONFIRMADA' atribuído automaticamente a qualquer
        mês com fonte vazia — isso superclamava verificação que não
        tinha sido feita. Essa coluna não deve mais existir."""
        resultados = [{'ano': 1990, 'mes': 12, 'resultado': {}}]
        cobertura = pilo.verificar_cobertura_observacional(resultados, serie_df=self._serie_fabricada())
        self.assertNotIn('classificacao', cobertura.columns)
        self.assertNotIn('OBSERVACAO_CONFIRMADA', cobertura.values.astype(str))


class RealSerieObservacionalTestCase(unittest.TestCase):
    """F — checagem contra o arquivo real data/serie_subst.csv (só
    leitura local, nunca rede) para as 16 origens efetivamente adotadas.
    Confirma separadamente disponibilidade (todos presentes), procedência
    documental (MERRA-2 para 1991, Estação Sinobras para 1998/2005/2010)
    e qualidade (nenhuma flag nos dados reais) — nunca um único
    "confirmado" agregando os três."""

    def test_f_96_combinacoes_todas_disponiveis_no_arquivo_real(self):
        resultados = [{'ano': ano, 'mes': mes, 'resultado': {}} for ano, mes in pilo.PILOTO_ORIGENS]
        cobertura = pilo.verificar_cobertura_observacional(resultados)
        self.assertEqual(len(cobertura), 16 * 6)
        self.assertTrue((cobertura['disponibilidade'] == 'PRESENTE').all(),
                          msg='pelo menos um mês-alvo do piloto não está disponível no arquivo real '
                              '(mudança em data/serie_subst.csv desde que este teste foi escrito?)')

    def test_f_nenhuma_procedencia_e_substituta(self):
        resultados = [{'ano': ano, 'mes': mes, 'resultado': {}} for ano, mes in pilo.PILOTO_ORIGENS]
        cobertura = pilo.verificar_cobertura_observacional(resultados)
        self.assertFalse(cobertura['fonte_e_substituta_nao_usar'].any())

    def test_f_qualidade_ok_em_todas_as_combinacoes_reais(self):
        resultados = [{'ano': ano, 'mes': mes, 'resultado': {}} for ano, mes in pilo.PILOTO_ORIGENS]
        cobertura = pilo.verificar_cobertura_observacional(resultados)
        self.assertTrue((cobertura['qualidade_verificada_status'] == pilo.QUALIDADE_STATUS_OK).all())

    def test_f_procedencia_documental_bate_com_o_corte_de_1995(self):
        resultados = [{'ano': ano, 'mes': mes, 'resultado': {}} for ano, mes in pilo.PILOTO_ORIGENS]
        cobertura = pilo.verificar_cobertura_observacional(resultados)
        de_1991 = cobertura[cobertura['origem_piloto'].str.startswith('1991')]
        # 1991-01 tem H1..H6 -> alvo até 1991-06, todos <= 1995 -> MERRA-2
        self.assertTrue((de_1991['procedencia_documental'] == pilo.PROCEDENCIA_MERRA2).all())
        de_2010 = cobertura[cobertura['origem_piloto'].str.startswith('2010')]
        self.assertTrue((de_2010['procedencia_documental'] == pilo.PROCEDENCIA_ESTACAO_SINOBRAS).all())


class AprovacaoPilotoTestCase(unittest.TestCase):
    """G — critérios de aprovação de INFRAESTRUTURA do piloto (Seção 3,
    revisão pontual): todas aprovadas + sem erro inesperado — a
    cobertura/procedência observacional NUNCA entra aqui (ver
    AptidaoReferenciaObservacionalTestCase para o verdito separado)."""

    def test_g_aprova_quando_tudo_ok(self):
        resultados = pilo.executar_piloto_historico(resolver_fns=_resolver_todas_ok)
        aprovacao = pilo.avaliar_aprovacao_piloto(resultados)
        self.assertEqual(aprovacao['piloto_status'], 'APROVADO')
        self.assertEqual(aprovacao['n_origens_aprovadas'], 16)
        self.assertTrue(all(aprovacao['criterios'].values()))

    def test_g_reprova_com_uma_origem_falhando(self):
        resultados = pilo.executar_piloto_historico(
            resolver_fns=_resolver_com_uma_falha((2005, 1)))
        aprovacao = pilo.avaliar_aprovacao_piloto(resultados)
        self.assertEqual(aprovacao['piloto_status'], 'REPROVADO')
        self.assertEqual(aprovacao['n_origens_aprovadas'], 15)
        self.assertFalse(aprovacao['criterios']['todas_origens_aprovadas'])

    def test_g_criterios_nunca_incluem_cobertura_observacional(self):
        """Regressão — a versão anterior misturava um critério de
        cobertura observacional na aprovação de infraestrutura; agora
        são funções completamente separadas."""
        resultados = pilo.executar_piloto_historico(resolver_fns=_resolver_todas_ok)
        aprovacao = pilo.avaliar_aprovacao_piloto(resultados)
        self.assertNotIn('cobertura_observacional_ok', aprovacao['criterios'])


class RotaValidadaNaAprovacaoTestCase(unittest.TestCase):
    """Ajuste pontual — Seção 1 da tarefa: `avaliar_aprovacao_piloto`
    exige que toda origem APROVADA tenha usado exatamente
    backend=IRIDL_LEGACY e representação=NMME_HARMONIZED_MONTHLY. Um
    fallback para outra rota nunca modifica o mecanismo de fallback do
    POC original (a origem em si pode continuar `poc_status=APROVADO`)
    — só impede a aprovação AGREGADA do piloto."""

    def test_todas_as_16_aprovadas_na_rota_correta_aprova_o_piloto(self):
        """Cenário obrigatório 1."""
        resultados = pilo.executar_piloto_historico(resolver_fns=_resolver_todas_ok)
        aprovacao = pilo.avaliar_aprovacao_piloto(resultados)
        self.assertEqual(aprovacao['piloto_status'], 'APROVADO')
        self.assertTrue(aprovacao['criterios']['todas_aprovadas_usaram_rota_validada'])
        self.assertEqual(aprovacao['origens_com_rota_diferente'], [])
        # Todas as 16 usaram de fato a rota esperada nesta fixture.
        for item in resultados:
            self.assertEqual(item['resultado']['backend_used'], ncat.SOURCE_BACKEND_IRIDL_LEGACY)
            self.assertEqual(item['resultado']['dataset_representation_used'],
                              ncat.REPR_NMME_HARMONIZED_MONTHLY)

    def test_origem_aprovada_com_representacao_diferente_reprova_o_agregado(self):
        """Cenário obrigatório 2 — a origem em si continua APROVADO
        individualmente (o guardrail de integridade do POC não
        distingue representação); só a aprovação AGREGADA do piloto é
        impedida."""
        resultados = pilo.executar_piloto_historico(
            origens=((2005, 1),), resolver_fns=_resolver_todas_ok)
        resultados[0]['resultado']['dataset_representation_used'] = ncat.REPR_RAW_NATIVE_ENSEMBLE
        aprovacao = pilo.avaliar_aprovacao_piloto(resultados, origens_esperadas=((2005, 1),))
        self.assertEqual(resultados[0]['resultado']['poc_status'], 'APROVADO',
                          msg='a origem individual nunca deve deixar de estar APROVADO só por '
                              'causa da representação — isso reescreveria o guardrail do POC')
        self.assertEqual(aprovacao['piloto_status'], 'REPROVADO')
        self.assertFalse(aprovacao['criterios']['todas_aprovadas_usaram_rota_validada'])
        self.assertEqual(len(aprovacao['origens_com_rota_diferente']), 1)
        self.assertEqual(aprovacao['origens_com_rota_diferente'][0]['origem'], '2005-01')
        self.assertEqual(aprovacao['origens_com_rota_diferente'][0]['dataset_representation_used'],
                          ncat.REPR_RAW_NATIVE_ENSEMBLE)

    def test_origem_aprovada_com_backend_diferente_reprova_o_agregado(self):
        """Cenário obrigatório 3."""
        resultados = pilo.executar_piloto_historico(
            origens=((2005, 1),), resolver_fns=_resolver_todas_ok)
        resultados[0]['resultado']['backend_used'] = ncat.SOURCE_BACKEND_CCSR_BETA
        aprovacao = pilo.avaliar_aprovacao_piloto(resultados, origens_esperadas=((2005, 1),))
        self.assertEqual(resultados[0]['resultado']['poc_status'], 'APROVADO')
        self.assertEqual(aprovacao['piloto_status'], 'REPROVADO')
        self.assertFalse(aprovacao['criterios']['todas_aprovadas_usaram_rota_validada'])
        self.assertEqual(aprovacao['origens_com_rota_diferente'][0]['backend_used'],
                          ncat.SOURCE_BACKEND_CCSR_BETA)

    def test_origem_reprovada_com_rota_diferente_nao_conta_como_ocorrencia(self):
        """Uma origem que já reprovou por outro motivo (não
        `poc_status=APROVADO`) não deve aparecer em
        `origens_com_rota_diferente` — essa lista é só sobre origens
        aprovadas com rota errada, não sobre reprovações genéricas
        (que já derrubam `todas_origens_aprovadas` por conta própria)."""
        resultados = pilo.executar_piloto_historico(
            origens=((2005, 1),), resolver_fns=_resolver_com_uma_falha((2005, 1)))
        resultados[0]['resultado']['dataset_representation_used'] = ncat.REPR_RAW_NATIVE_ENSEMBLE
        aprovacao = pilo.avaliar_aprovacao_piloto(resultados, origens_esperadas=((2005, 1),))
        self.assertEqual(aprovacao['origens_com_rota_diferente'], [])
        self.assertFalse(aprovacao['criterios']['todas_origens_aprovadas'])

    def test_nao_modifica_o_mecanismo_de_fallback_do_poc(self):
        """Regressão estrutural — este ajuste nunca deve tocar em
        nmme_download.ordem_tentativa_member_level nem em
        nmme_poc.avaliar_aprovacao_poc; a verificação de rota vive
        inteiramente em nmme_piloto_historico, só na camada de
        agregação."""
        import inspect
        import nmme_download as ndl
        src_ordem = inspect.getsource(ndl.ordem_tentativa_member_level)
        src_avaliar_poc = inspect.getsource(npoc.avaliar_aprovacao_poc)
        self.assertNotIn('rota_validada', src_ordem)
        self.assertNotIn('rota_validada', src_avaliar_poc)


class IntegridadeDasOrigensTestCase(unittest.TestCase):
    """Ajuste pontual — Seção 2 da tarefa: o agregado precisa conter
    exatamente as 16 origens previstas, sem duplicata nem ausência."""

    def test_16_origens_sem_duplicata_nem_ausencia_aprova_o_criterio(self):
        resultados = pilo.executar_piloto_historico(resolver_fns=_resolver_todas_ok)
        aprovacao = pilo.avaliar_aprovacao_piloto(resultados)
        self.assertTrue(aprovacao['criterios']['integridade_das_origens_ok'])
        integridade = aprovacao['integridade_origens']
        self.assertEqual(integridade['n_esperadas'], 16)
        self.assertEqual(integridade['n_observadas'], 16)
        self.assertEqual(integridade['origens_duplicadas'], [])
        self.assertEqual(integridade['origens_ausentes'], [])

    def test_origem_ausente_reprova_o_agregado(self):
        """Cenário obrigatório 4a — uma origem prevista nunca aparece
        no resultado agregado."""
        origens_incompletas = tuple(o for o in pilo.PILOTO_ORIGENS if o != (2005, 1))
        resultados = pilo.executar_piloto_historico(
            origens=origens_incompletas, resolver_fns=_resolver_todas_ok)
        aprovacao = pilo.avaliar_aprovacao_piloto(resultados)   # origens_esperadas=PILOTO_ORIGENS (16)
        self.assertEqual(aprovacao['piloto_status'], 'REPROVADO')
        self.assertFalse(aprovacao['criterios']['integridade_das_origens_ok'])
        self.assertEqual(aprovacao['integridade_origens']['origens_ausentes'], [(2005, 1)])

    def test_origem_duplicada_reprova_o_agregado(self):
        """Cenário obrigatório 4b — a mesma origem processada 2 vezes
        no resultado agregado."""
        origens_com_duplicata = pilo.PILOTO_ORIGENS + ((2005, 1),)
        resultados = pilo.executar_piloto_historico(
            origens=origens_com_duplicata, resolver_fns=_resolver_todas_ok)
        aprovacao = pilo.avaliar_aprovacao_piloto(resultados)
        self.assertEqual(aprovacao['piloto_status'], 'REPROVADO')
        self.assertFalse(aprovacao['criterios']['integridade_das_origens_ok'])
        self.assertEqual(aprovacao['integridade_origens']['origens_duplicadas'], [(2005, 1)])

    def test_origem_inesperada_fora_do_plano_reprova_o_agregado(self):
        """Uma origem fora da lista esperada (nunca deveria acontecer
        em produção, mas defendido mesmo assim) também compromete a
        integridade."""
        resultados = pilo.executar_piloto_historico(
            origens=((1991, 1), (1991, 4)), resolver_fns=_resolver_todas_ok)
        aprovacao = pilo.avaliar_aprovacao_piloto(resultados, origens_esperadas=((1991, 1),))
        self.assertFalse(aprovacao['criterios']['integridade_das_origens_ok'])
        self.assertEqual(aprovacao['integridade_origens']['origens_inesperadas'], [(1991, 4)])


class AptidaoReferenciaObservacionalTestCase(unittest.TestCase):
    """G2 — Seção 3 da tarefa: verdito SEPARADO sobre se a referência
    observacional está apta para uma avaliação científica futura.
    NUNCA aprova enquanto a correspondência espacial (Seção 2) não for
    resolvida — bloqueio estrutural, sempre presente nesta revisão."""

    def _cobertura_perfeita(self):
        linhas = []
        for a, m in pilo.PILOTO_ORIGENS:
            for lead in range(1, 7):
                linhas.append({'origem_piloto': f'{a}-{m:02d}', 'H_lead': lead,
                                 'target_month': f'{a}-{m:02d}', 'disponibilidade': 'PRESENTE',
                                 'procedencia_documental': pilo.PROCEDENCIA_ESTACAO_SINOBRAS,
                                 'fonte_e_substituta_nao_usar': False,
                                 'qualidade_verificada_status': pilo.QUALIDADE_STATUS_OK})
        return pd.DataFrame(linhas)

    def test_g2_nunca_apta_mesmo_com_cobertura_perfeita(self):
        """O bloqueio de correspondência espacial (198 km, Seção 2) é
        estrutural nesta revisão — mesmo cobertura/qualidade 100%
        limpas não tornam a referência apta."""
        aptidao = pilo.avaliar_aptidao_referencia_observacional(self._cobertura_perfeita())
        self.assertFalse(aptidao['apto_para_avaliacao_cientifica'])
        self.assertTrue(any('correspondência espacial' in m for m in aptidao['motivos_bloqueio']))

    def test_g2_cobertura_none_e_um_bloqueio_explicito(self):
        aptidao = pilo.avaliar_aptidao_referencia_observacional(None)
        self.assertFalse(aptidao['apto_para_avaliacao_cientifica'])
        self.assertTrue(any('não avaliada' in m for m in aptidao['motivos_bloqueio']))

    def test_g2_mes_ausente_vira_bloqueio_nomeado(self):
        cobertura = self._cobertura_perfeita()
        cobertura.loc[0, 'disponibilidade'] = 'AUSENTE'
        aptidao = pilo.avaliar_aptidao_referencia_observacional(cobertura)
        self.assertTrue(any('sem registro histórico disponível' in m for m in aptidao['motivos_bloqueio']))
        self.assertEqual(aptidao['n_combinacoes_disponiveis'], len(cobertura) - 1)

    def test_g2_fonte_substituta_vira_bloqueio_nomeado(self):
        cobertura = self._cobertura_perfeita()
        cobertura.loc[0, 'fonte_e_substituta_nao_usar'] = True
        aptidao = pilo.avaliar_aptidao_referencia_observacional(cobertura)
        self.assertTrue(any('preliminar/estimada' in m for m in aptidao['motivos_bloqueio']))

    def test_g2_flag_de_qualidade_vira_bloqueio_nomeado(self):
        cobertura = self._cobertura_perfeita()
        cobertura.loc[0, 'qualidade_verificada_status'] = pilo.QUALIDADE_FLAG_VALOR_AUSENTE
        aptidao = pilo.avaliar_aptidao_referencia_observacional(cobertura)
        self.assertTrue(any('flag de qualidade' in m for m in aptidao['motivos_bloqueio']))

    def test_g2_nunca_confundido_com_reprovacao_de_infraestrutura(self):
        """A insuficiência da referência observacional nunca é reportada
        como falha de acesso ao CFSv2 — os dois vocabulários de status
        são completamente distintos."""
        aptidao = pilo.avaliar_aptidao_referencia_observacional(self._cobertura_perfeita())
        self.assertNotIn('poc_status', aptidao)
        self.assertNotIn('REPROVADO_ACESSO', str(aptidao))


class RepresentacaoDiferenteTestCase(unittest.TestCase):
    """Seção 4 da tarefa — qualquer origem que usar uma representação
    diferente de NMME_HARMONIZED_MONTHLY é registrada explicitamente,
    nunca tratada como equivalente à rota EMPIRICALLY_CONFIRMED."""

    def test_representacao_diferente_e_marcada_true(self):
        resultados = pilo.executar_piloto_historico(
            origens=((2005, 1),), resolver_fns=_resolver_todas_ok)
        # Simula uma origem cujo resultado usou a Representação A —
        # nunca acontece organicamente nesta fixture (B sempre
        # disponível), então testamos a função de resumo diretamente
        # com um resultado sintético.
        resultados[0]['resultado']['dataset_representation_used'] = ncat.REPR_RAW_NATIVE_ENSEMBLE
        resumo = pilo.montar_resumo_por_origem(resultados)
        self.assertTrue(resumo.iloc[0]['representacao_diferente_da_validada'])

    def test_representacao_validada_e_marcada_false(self):
        resultados = pilo.executar_piloto_historico(
            origens=((2005, 1),), resolver_fns=_resolver_todas_ok)
        resumo = pilo.montar_resumo_por_origem(resultados)
        self.assertFalse(resumo.iloc[0]['representacao_diferente_da_validada'])

    def test_representacao_ausente_nao_e_marcada_como_diferente(self):
        """Uma origem sem representação usada (ex.: REPROVADO_ACESSO,
        nenhuma rota respondeu) não deve ser contada como "diferente" —
        ela simplesmente não usou nenhuma."""
        resultados = pilo.executar_piloto_historico(
            origens=((2005, 1),), resolver_fns=_resolver_com_uma_falha((2005, 1)))
        resumo = pilo.montar_resumo_por_origem(resultados)
        self.assertIsNone(resumo.iloc[0]['dataset_representation_used'])
        self.assertFalse(resumo.iloc[0]['representacao_diferente_da_validada'])

    def test_backend_diferente_e_marcada_true(self):
        resultados = pilo.executar_piloto_historico(
            origens=((2005, 1),), resolver_fns=_resolver_todas_ok)
        resultados[0]['resultado']['backend_used'] = ncat.SOURCE_BACKEND_CCSR_BETA
        resumo = pilo.montar_resumo_por_origem(resultados)
        self.assertTrue(resumo.iloc[0]['backend_diferente_da_validada'])

    def test_backend_validado_e_marcada_false(self):
        resultados = pilo.executar_piloto_historico(
            origens=((2005, 1),), resolver_fns=_resolver_todas_ok)
        resumo = pilo.montar_resumo_por_origem(resultados)
        self.assertFalse(resumo.iloc[0]['backend_diferente_da_validada'])


class DistanciaEspacialTestCase(unittest.TestCase):
    """H — Seção 3: correspondência espacial entre a referência
    observacional (centroide das fazendas) e o ponto usado pelo CFSv2
    (São Bento do Tocantins) — achado desta tarefa: os dois pontos NÃO
    coincidem."""

    def test_h_distancia_e_positiva_e_da_ordem_de_centenas_de_km(self):
        dist = pilo.distancia_fazendas_ate_municipio_km()
        self.assertGreater(dist, 100.0)
        self.assertLess(dist, 300.0)

    def test_h_reaproveita_a_mesma_funcao_de_distancia_do_poc(self):
        """Nunca uma fórmula de distância nova — mesma
        nmme_processar.distancia_km_aprox já usada para grid_distance_km
        no RAW do POC."""
        import inspect
        src = inspect.getsource(pilo.distancia_fazendas_ate_municipio_km)
        self.assertIn('distancia_km_aprox', src)


class MetadataEArtifactsTestCase(unittest.TestCase):
    """I — escrever_saidas_piloto gera os artifacts esperados sem
    tocar em dashboard/produção; metadata nunca omite o status do
    catálogo (Seção 1: CFSv2 continua POC_READY_DOCUMENTED), e separa
    claramente as coordenadas de cada lado (Seção 2)."""

    def _tudo(self):
        resultados = pilo.executar_piloto_historico(resolver_fns=_resolver_todas_ok)
        cobertura = pilo.verificar_cobertura_observacional(resultados)
        aprovacao = pilo.avaliar_aprovacao_piloto(resultados)
        aptidao = pilo.avaliar_aptidao_referencia_observacional(cobertura)
        return resultados, cobertura, aprovacao, aptidao

    def test_i_metadata_reflete_status_cfsv2_inalterado(self):
        resultados, cobertura, aprovacao, aptidao = self._tudo()
        meta = pilo.montar_metadata_piloto(resultados, cobertura, aprovacao, aptidao)
        self.assertIn('POC_READY_DOCUMENTED', meta['status_cfsv2_data_access'])
        self.assertTrue(meta['nenhuma_skill_calculada'])
        self.assertTrue(meta['nenhum_dashboard_alterado'])
        self.assertEqual(meta['representacao'], ncat.REPR_NMME_HARMONIZED_MONTHLY)
        self.assertEqual(meta['n_origens'], 16)

    def test_i_metadata_nunca_chama_a_referencia_de_chirps(self):
        """Regressão — a versão anterior tinha um campo
        'chirps_referencia'; a série não é CHIRPS para o período do
        piloto (achado desta tarefa), então nenhum campo do metadata
        pode usar esse nome."""
        resultados, cobertura, aprovacao, aptidao = self._tudo()
        meta = pilo.montar_metadata_piloto(resultados, cobertura, aprovacao, aptidao)
        self.assertNotIn('chirps_referencia', meta)

    def test_i_metadata_registra_coordenadas_dos_dois_lados_e_distancia(self):
        resultados, cobertura, aprovacao, aptidao = self._tudo()
        meta = pilo.montar_metadata_piloto(resultados, cobertura, aprovacao, aptidao)
        self.assertAlmostEqual(meta['previsao_cfsv2_lat'], -6.0203, places=3)
        self.assertAlmostEqual(meta['serie_observacional_lat'], pilo.FAZENDAS_LAT, places=3)
        self.assertGreater(meta['distancia_previsao_observacao_km'], 100.0)
        self.assertIn('consequencias_avaliacao_cientifica_futura', meta)
        self.assertIn('MERRA-2', meta['serie_observacional_procedencia_documental'])

    def test_i_metadata_traz_os_dois_status_separados(self):
        resultados, cobertura, aprovacao, aptidao = self._tudo()
        meta = pilo.montar_metadata_piloto(resultados, cobertura, aprovacao, aptidao)
        self.assertEqual(meta['piloto_status'], 'APROVADO')
        self.assertIn('referencia_observacional_apta_para_avaliacao_cientifica', meta)
        self.assertFalse(meta['referencia_observacional_apta_para_avaliacao_cientifica'])

    def test_i_escrever_saidas_gera_os_7_arquivos(self):
        import tempfile
        resultados = pilo.executar_piloto_historico(
            origens=((2005, 1),), resolver_fns=_resolver_todas_ok)
        cobertura = pilo.verificar_cobertura_observacional(resultados)
        aprovacao = pilo.avaliar_aprovacao_piloto(resultados)
        aptidao = pilo.avaliar_aptidao_referencia_observacional(cobertura)
        antigo = pilo.ARTIFACTS_DIR
        try:
            pilo.ARTIFACTS_DIR = Path(tempfile.mkdtemp())
            pilo.escrever_saidas_piloto(resultados, cobertura, aprovacao, aptidao)
            nomes = {p.name for p in pilo.ARTIFACTS_DIR.iterdir()}
            self.assertEqual(nomes, {'piloto_raw.csv', 'piloto_temporal_audit.csv',
                                       'piloto_access_audit.csv', 'piloto_resumo_por_origem.csv',
                                       'piloto_cobertura_observacional.csv', 'metadata.json',
                                       'RELATORIO.md'})
        finally:
            pilo.ARTIFACTS_DIR = antigo


class ZeroSkillESemDashboardTestCase(unittest.TestCase):
    """J — mesmo princípio estrutural do POC: nenhum termo de CÁLCULO
    de skill no módulo, nenhuma importação de scripts de produção do
    dashboard."""

    def test_j_nenhum_termo_de_skill_no_modulo(self):
        import inspect
        src = inspect.getsource(pilo)
        for termo in ('rpss', 'brier', 'crps', 'msess', 'skill_score'):
            self.assertNotIn(termo, src.lower())

    def test_j_nao_importa_update_dashboard(self):
        import inspect
        src = inspect.getsource(pilo)
        self.assertNotIn('update_dashboard', src)
        self.assertNotIn('verificar_dashboard', src)


if __name__ == '__main__':
    unittest.main()
