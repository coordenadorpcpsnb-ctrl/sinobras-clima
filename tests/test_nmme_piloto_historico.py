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
    """E — Seção 3 da tarefa: classificar procedência da série
    observacional usada como referência, nunca tratar valor substituído/
    estimado como observação real. Usa uma série FABRICADA (nunca o
    arquivo real) para determinismo — a cobertura contra o arquivo real
    é testada à parte (RealSerieObservacionalTestCase)."""

    @staticmethod
    def _serie_fabricada():
        linhas = []
        # mês com fonte vazia (baseline MERRA-2/Sinobras) -> confirmada
        linhas.append({'ano': 1991, 'mes': 1, 'prec': 100.0, 'fonte': None})
        # mês com fonte='CHIRPS' (CHIRPS Final) -> confirmada
        linhas.append({'ano': 1991, 'mes': 2, 'prec': 50.0, 'fonte': 'CHIRPS'})
        # mês com fonte preliminar -> NUNCA usar como observação real
        linhas.append({'ano': 1991, 'mes': 3, 'prec': 30.0, 'fonte': 'CHC-Preliminar'})
        # mês com fonte ERA5 (fallback final) -> idem, nunca usar
        linhas.append({'ano': 1991, 'mes': 4, 'prec': 10.0, 'fonte': 'OpenMeteo-ERA5'})
        # (1991-05 deliberadamente ausente -> MES_AUSENTE)
        return pd.DataFrame(linhas)

    def test_e_fonte_vazia_e_confirmada(self):
        resultados = [{'ano': 1990, 'mes': 12, 'resultado': {}}]   # H1 de 1990-12 -> 1990-12... ajustado abaixo
        # Usamos origem 1990-12 com lead 1 (H1) => target 1990-12? Não —
        # a origem precisa mapear para os meses fabricados (1991-01..04).
        # Origem 1990-12: H1->1990-12, H2->1991-01 (fonte vazia, confirmada).
        cobertura = pilo.verificar_cobertura_observacional(resultados, serie_df=self._serie_fabricada())
        linha_h2 = cobertura[(cobertura['origem_piloto'] == '1990-12') & (cobertura['H_lead'] == 2)].iloc[0]
        self.assertEqual(linha_h2['target_month'], '1991-01')
        self.assertEqual(linha_h2['classificacao'], 'OBSERVACAO_CONFIRMADA')

    def test_e_fonte_chirps_e_confirmada(self):
        resultados = [{'ano': 1990, 'mes': 12, 'resultado': {}}]
        cobertura = pilo.verificar_cobertura_observacional(resultados, serie_df=self._serie_fabricada())
        linha_h3 = cobertura[(cobertura['origem_piloto'] == '1990-12') & (cobertura['H_lead'] == 3)].iloc[0]
        self.assertEqual(linha_h3['target_month'], '1991-02')
        self.assertEqual(linha_h3['classificacao'], 'OBSERVACAO_CONFIRMADA')
        self.assertEqual(linha_h3['fonte_observada'], 'CHIRPS')

    def test_e_fonte_preliminar_nunca_e_confirmada(self):
        resultados = [{'ano': 1990, 'mes': 12, 'resultado': {}}]
        cobertura = pilo.verificar_cobertura_observacional(resultados, serie_df=self._serie_fabricada())
        linha_h4 = cobertura[(cobertura['origem_piloto'] == '1990-12') & (cobertura['H_lead'] == 4)].iloc[0]
        self.assertEqual(linha_h4['target_month'], '1991-03')
        self.assertEqual(linha_h4['classificacao'], 'VALOR_SUBSTITUIDO_NAO_USAR')

    def test_e_fonte_era5_fallback_nunca_e_confirmada(self):
        resultados = [{'ano': 1990, 'mes': 12, 'resultado': {}}]
        cobertura = pilo.verificar_cobertura_observacional(resultados, serie_df=self._serie_fabricada())
        linha_h5 = cobertura[(cobertura['origem_piloto'] == '1990-12') & (cobertura['H_lead'] == 5)].iloc[0]
        self.assertEqual(linha_h5['target_month'], '1991-04')
        self.assertEqual(linha_h5['classificacao'], 'VALOR_SUBSTITUIDO_NAO_USAR')

    def test_e_mes_ausente_e_classificado_corretamente(self):
        resultados = [{'ano': 1990, 'mes': 12, 'resultado': {}}]
        cobertura = pilo.verificar_cobertura_observacional(resultados, serie_df=self._serie_fabricada())
        linha_h6 = cobertura[(cobertura['origem_piloto'] == '1990-12') & (cobertura['H_lead'] == 6)].iloc[0]
        self.assertEqual(linha_h6['target_month'], '1991-05')
        self.assertEqual(linha_h6['classificacao'], 'MES_AUSENTE')


class RealSerieObservacionalTestCase(unittest.TestCase):
    """F — checagem contra o arquivo real data/serie_subst.csv (só
    leitura local, nunca rede) para as 16 origens efetivamente adotadas
    — confirma o achado desta tarefa: os 16x6=96 meses-alvo do piloto
    têm todos `fonte` vazia (baseline MERRA-2 1981-1995 / estação
    Sinobras 1996-presente, README.md), nenhum com tag de fallback
    preliminar/estimado."""

    def test_f_96_combinacoes_todas_confirmadas_no_arquivo_real(self):
        resultados = [{'ano': ano, 'mes': mes, 'resultado': {}} for ano, mes in pilo.PILOTO_ORIGENS]
        cobertura = pilo.verificar_cobertura_observacional(resultados)
        self.assertEqual(len(cobertura), 16 * 6)
        self.assertTrue((cobertura['classificacao'] == 'OBSERVACAO_CONFIRMADA').all(),
                          msg='pelo menos um mês-alvo do piloto não está confirmado no arquivo real '
                              '(mudança em data/serie_subst.csv desde que este teste foi escrito?)')


class AprovacaoPilotoTestCase(unittest.TestCase):
    """G — critérios de aprovação do piloto (distintos da aprovação por
    origem): todas aprovadas + sem erro inesperado + cobertura >= 90%."""

    def test_g_aprova_quando_tudo_ok(self):
        resultados = pilo.executar_piloto_historico(resolver_fns=_resolver_todas_ok)
        cobertura = pilo.verificar_cobertura_observacional(resultados)
        aprovacao = pilo.avaliar_aprovacao_piloto(resultados, cobertura)
        self.assertEqual(aprovacao['piloto_status'], 'APROVADO')
        self.assertEqual(aprovacao['n_origens_aprovadas'], 16)
        self.assertTrue(all(aprovacao['criterios'].values()))

    def test_g_reprova_com_uma_origem_falhando(self):
        resultados = pilo.executar_piloto_historico(
            resolver_fns=_resolver_com_uma_falha((2005, 1)))
        cobertura = pilo.verificar_cobertura_observacional(resultados)
        aprovacao = pilo.avaliar_aprovacao_piloto(resultados, cobertura)
        self.assertEqual(aprovacao['piloto_status'], 'REPROVADO')
        self.assertEqual(aprovacao['n_origens_aprovadas'], 15)
        self.assertFalse(aprovacao['criterios']['todas_origens_aprovadas'])

    def test_g_sem_cobertura_informada_nunca_aprova_silenciosamente(self):
        """Regressão — cobertura_df=None não pode virar um APROVADO
        implícito; o critério fica None (NAO_AVALIADO), nunca True por
        omissão."""
        resultados = pilo.executar_piloto_historico(resolver_fns=_resolver_todas_ok)
        aprovacao = pilo.avaliar_aprovacao_piloto(resultados, cobertura_df=None)
        self.assertIsNone(aprovacao['criterios']['cobertura_observacional_ok'])
        self.assertEqual(aprovacao['piloto_status'], 'REPROVADO')

    def test_g_reprova_por_cobertura_insuficiente(self):
        resultados = pilo.executar_piloto_historico(resolver_fns=_resolver_todas_ok)
        cobertura_ruim = pd.DataFrame({
            'classificacao': ['OBSERVACAO_CONFIRMADA'] * 10 + ['MES_AUSENTE'] * 86})
        aprovacao = pilo.avaliar_aprovacao_piloto(resultados, cobertura_ruim)
        self.assertEqual(aprovacao['piloto_status'], 'REPROVADO')
        self.assertFalse(aprovacao['criterios']['cobertura_observacional_ok'])


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
    catálogo (Seção 1: CFSv2 continua POC_READY_DOCUMENTED)."""

    def test_i_metadata_reflete_status_cfsv2_inalterado(self):
        resultados = pilo.executar_piloto_historico(resolver_fns=_resolver_todas_ok)
        cobertura = pilo.verificar_cobertura_observacional(resultados)
        aprovacao = pilo.avaliar_aprovacao_piloto(resultados, cobertura)
        meta = pilo.montar_metadata_piloto(resultados, cobertura, aprovacao)
        self.assertIn('POC_READY_DOCUMENTED', meta['status_cfsv2_data_access'])
        self.assertTrue(meta['nenhuma_skill_calculada'])
        self.assertTrue(meta['nenhum_dashboard_alterado'])
        self.assertEqual(meta['representacao'], ncat.REPR_NMME_HARMONIZED_MONTHLY)
        self.assertEqual(meta['n_origens'], 16)

    def test_i_escrever_saidas_gera_os_7_arquivos(self):
        import tempfile
        resultados = pilo.executar_piloto_historico(
            origens=((2005, 1),), resolver_fns=_resolver_todas_ok)
        cobertura = pilo.verificar_cobertura_observacional(resultados)
        aprovacao = pilo.avaliar_aprovacao_piloto(resultados, cobertura)
        antigo = pilo.ARTIFACTS_DIR
        try:
            pilo.ARTIFACTS_DIR = Path(tempfile.mkdtemp())
            pilo.escrever_saidas_piloto(resultados, cobertura, aprovacao)
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
