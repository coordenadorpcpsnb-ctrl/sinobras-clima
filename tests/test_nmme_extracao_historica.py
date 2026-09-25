#!/usr/bin/env python3
"""
tests/test_nmme_extracao_historica.py — regressão da extração histórica
em lotes com retomada (Fase 2C.2): scripts/nmme_extracao_historica.py.
Tudo offline — baixar_fn/abrir_fn são sempre injetados (nunca requests/
xarray reais); os datasets usados são SINTÉTICOS, nunca um subset NMME
real (a rede real nunca é acessada nesta tarefa). Todo teste que grava
em disco usa um `diretorio` temporário (tempfile) — nunca escreve em
data/nmme_historico/ (armazenamento permanente real).

Este módulo reaproveita nmme_piloto_historico.executar_piloto_historico/
avaliar_aprovacao_piloto/montar_resumo_por_origem/
concatenar_dataframes_piloto SEM modificação — os guardrails de
integridade/rota já têm cobertura própria em
tests/test_nmme_piloto_historico.py e não são reexercitados em detalhe
aqui. O que este arquivo testa é o que a extração ADICIONA por cima do
piloto: particionamento em lotes, retomada (nunca reconsultar uma
origem já `APROVADO` persistida), retentativa seletiva (só a origem que
falhou), armazenamento permanente e consolidação honesta (nunca finge
completude parcial como total).

Roda com:
    python -m unittest tests.test_nmme_extracao_historica -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import nmme_extracao_historica as ext  # noqa: E402
from _c3s_utils import MUNICIPIOS  # noqa: E402

SAO_BENTO = MUNICIPIOS['Sao_Bento_do_Tocantins']


def _ds_para_origem(ano, mes, n_membros=24, valor_base=5.0, escala=3.0):
    """Dataset sintético válido (Representação B) para 1 origem —
    mesmo padrão de tests/test_nmme_piloto_historico.py."""
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
    return ('/tmp/fake-extracao-nmme.nc', False)


def _baixar_falha(url, destino):
    raise RuntimeError('rede indisponível simulada')


def _resolver_todas_ok(ano, mes):
    return _baixar_ok, (lambda c, ano=ano, mes=mes: _ds_para_origem(ano, mes))


def _resolver_com_falha_em(origens_com_falha):
    origens_com_falha = set(origens_com_falha)

    def resolver(ano, mes):
        if (ano, mes) in origens_com_falha:
            return _baixar_falha, (lambda c: _ds_para_origem(ano, mes))
        return _baixar_ok, (lambda c, ano=ano, mes=mes: _ds_para_origem(ano, mes))
    return resolver


def _resolver_contado(resolver_base):
    """Envolve um resolver_fns contando as origens realmente
    consultadas — usado para provar retomada/retentativa seletiva de
    forma direta (nunca só inferido pelo resultado final)."""
    chamadas = []

    def resolver(ano, mes):
        chamadas.append((ano, mes))
        return resolver_base(ano, mes)
    resolver.chamadas = chamadas
    return resolver


class DefinirLotesTestCase(unittest.TestCase):
    """Particionamento em lotes de até 48 origens (Seção 1 da tarefa)."""

    def test_a_240_origens_240_meses_1991_2010(self):
        self.assertEqual(len(ext.ORIGENS_HISTORICAS), 240)
        self.assertEqual(ext.ORIGENS_HISTORICAS[0], (1991, 1))
        self.assertEqual(ext.ORIGENS_HISTORICAS[-1], (2010, 12))

    def test_b_5_lotes_de_48_cobrindo_tudo_sem_lacuna_nem_sobreposicao(self):
        lotes = ext.definir_lotes()
        self.assertEqual(len(lotes), 5)
        for lote in lotes:
            self.assertEqual(len(lote.origens), 48)
        todas = [o for lote in lotes for o in lote.origens]
        self.assertEqual(len(todas), 240)
        self.assertEqual(len(set(todas)), 240)   # sem duplicata
        self.assertEqual(set(todas), set(ext.ORIGENS_HISTORICAS))   # sem lacuna

    def test_c_ordem_cronologica_nunca_embaralhada(self):
        lotes = ext.definir_lotes()
        for lote in lotes:
            self.assertEqual(list(lote.origens), sorted(lote.origens))

    def test_d_lote_ids_sao_faixas_de_ano_legiveis(self):
        ids = [lote.lote_id for lote in ext.LOTES_HISTORICOS]
        self.assertEqual(ids, ['1991-1994', '1995-1998', '1999-2002', '2003-2006', '2007-2010'])

    def test_e_n_raw_esperado_total_34560(self):
        self.assertEqual(ext.N_RAW_ESPERADO_TOTAL, 34560)
        self.assertEqual(ext.N_RAW_ESPERADO_TOTAL, 240 * 6 * 24)

    def test_f_particionamento_generico_com_tamanho_diferente(self):
        """A mesma função particiona qualquer conjunto/tamanho de
        lote — não é hardcoded para 240/48."""
        origens = tuple((2000, m) for m in range(1, 11))
        lotes = ext.definir_lotes(origens=origens, tamanho_lote=4)
        self.assertEqual([len(lote.origens) for lote in lotes], [4, 4, 2])


class ArmazenamentoPermanenteTestCase(unittest.TestCase):
    """Não depende só do artifact do GitHub Actions (retenção 30 dias) —
    diretório permanente commitado em data/."""

    def test_diretorio_historico_fica_em_data_nao_em_artifacts(self):
        self.assertEqual(ext.DIRETORIO_HISTORICO, ext.ROOT / 'data' / 'nmme_historico')
        self.assertNotIn('artifacts', str(ext.DIRETORIO_HISTORICO))


class OrigensPendentesTestCase(unittest.TestCase):
    """Retomada — Seção 1: uma origem já persistida com poc_status=
    APROVADO nunca é reconsultada; qualquer outro estado é retentado."""

    def test_a_lote_nunca_rodado_todas_pendentes(self):
        with tempfile.TemporaryDirectory() as tmp:
            lote = ext.LoteHistorico('teste', ((2000, 1), (2000, 2)))
            self.assertEqual(ext.origens_pendentes(lote, Path(tmp)), lote.origens)

    def test_b_tudo_aprovado_persistido_nenhuma_pendente(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1), (2000, 2)))
            ext.executar_lote(lote, resolver_fns=_resolver_todas_ok, diretorio=diretorio)
            self.assertEqual(ext.origens_pendentes(lote, diretorio), ())

    def test_c_uma_origem_reprovada_so_ela_fica_pendente(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1), (2000, 2)))
            ext.executar_lote(lote, resolver_fns=_resolver_com_falha_em({(2000, 1)}),
                               diretorio=diretorio)
            self.assertEqual(ext.origens_pendentes(lote, diretorio), ((2000, 1),))


class ExecutarLoteTestCase(unittest.TestCase):
    """Orquestração central: reaproveita
    nmme_piloto_historico.executar_piloto_historico/
    avaliar_aprovacao_piloto sem reimplementar guardrails, escreve
    armazenamento permanente, retentativa seletiva."""

    def test_a_lote_totalmente_aprovado(self):
        with tempfile.TemporaryDirectory() as tmp:
            lote = ext.LoteHistorico('teste', ((2000, 1), (2000, 2), (2000, 3)))
            metadata = ext.executar_lote(lote, resolver_fns=_resolver_todas_ok, diretorio=Path(tmp))
            self.assertEqual(metadata['lote_status'], 'APROVADO')
            self.assertEqual(metadata['n_origens_aprovadas'], 3)
            self.assertEqual(metadata['n_origens_pendentes_nesta_execucao'], 3)
            self.assertEqual(metadata['n_origens_reaproveitadas_do_disco'], 0)
            self.assertEqual(metadata['n_raw'], 3 * 6 * 24)

    def test_b_arquivos_persistidos_no_diretorio(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1),))
            ext.executar_lote(lote, resolver_fns=_resolver_todas_ok, diretorio=diretorio)
            for sufixo in ('raw.csv', 'temporal_audit.csv', 'access_audit.csv',
                            'resumo_por_origem.csv', 'metadata.json'):
                self.assertTrue((diretorio / f'lote_teste_{sufixo}').exists(), sufixo)

    def test_c_resumo_por_origem_tem_1_linha_por_origem_do_lote(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1), (2000, 2)))
            ext.executar_lote(lote, resolver_fns=_resolver_todas_ok, diretorio=diretorio)
            resumo = pd.read_csv(diretorio / 'lote_teste_resumo_por_origem.csv')
            self.assertEqual(len(resumo), 2)

    def test_d_resumo_por_origem_tem_n_raw_correto_na_primeira_execucao(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1), (2000, 2)))
            ext.executar_lote(lote, resolver_fns=_resolver_todas_ok, diretorio=diretorio)
            resumo = pd.read_csv(diretorio / 'lote_teste_resumo_por_origem.csv')
            self.assertTrue((resumo['n_raw'] == 144).all())   # 6 leads x 24 membros

    def test_e_segunda_execucao_com_tudo_aprovado_nao_consulta_a_rede(self):
        """Regressão de retomada: zero chamadas de rede quando todas as
        origens do lote já estão APROVADO persistidas."""
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1), (2000, 2)))
            ext.executar_lote(lote, resolver_fns=_resolver_todas_ok, diretorio=diretorio)

            resolver_contado = _resolver_contado(_resolver_todas_ok)
            metadata2 = ext.executar_lote(lote, resolver_fns=resolver_contado, diretorio=diretorio)
            self.assertEqual(resolver_contado.chamadas, [])
            self.assertEqual(metadata2['n_origens_pendentes_nesta_execucao'], 0)
            self.assertEqual(metadata2['n_origens_reaproveitadas_do_disco'], 2)
            self.assertEqual(metadata2['lote_status'], 'APROVADO')

    def test_f_retentativa_seletiva_so_a_origem_que_falhou_e_reconsultada(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1), (2000, 2)))
            metadata1 = ext.executar_lote(
                lote, resolver_fns=_resolver_com_falha_em({(2000, 1)}), diretorio=diretorio)
            self.assertEqual(metadata1['lote_status'], 'REPROVADO')
            self.assertEqual(metadata1['n_origens_aprovadas'], 1)

            resolver_contado = _resolver_contado(_resolver_todas_ok)
            metadata2 = ext.executar_lote(lote, resolver_fns=resolver_contado, diretorio=diretorio)
            self.assertEqual(resolver_contado.chamadas, [(2000, 1)])   # só a que falhou
            self.assertEqual(metadata2['n_origens_pendentes_nesta_execucao'], 1)
            self.assertEqual(metadata2['n_origens_reaproveitadas_do_disco'], 1)
            self.assertEqual(metadata2['lote_status'], 'APROVADO')
            self.assertEqual(metadata2['n_origens_aprovadas'], 2)

    def test_g_n_raw_da_origem_reaproveitada_nao_zera_apos_retomada(self):
        """Regressão do bug encontrado em verificação manual: origens
        reaproveitadas do disco tinham raw_df vazio de propósito
        (_resultado_minimo_da_linha_resumo), e montar_resumo_por_origem
        calcula n_raw por len(raw_df) — sem a correção, toda origem
        reaproveitada gravava n_raw=0 mesmo já tendo 144 linhas RAW
        persistidas de verdade."""
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1), (2000, 2)))
            ext.executar_lote(lote, resolver_fns=_resolver_todas_ok, diretorio=diretorio)
            # Segunda execução: ambas origens reaproveitadas (nenhuma pendente).
            ext.executar_lote(lote, resolver_fns=_resolver_todas_ok, diretorio=diretorio)
            resumo = pd.read_csv(diretorio / 'lote_teste_resumo_por_origem.csv')
            self.assertTrue((resumo['n_raw'] == 144).all(), resumo[['init_date', 'n_raw']])

    def test_h_raw_final_nao_duplica_origem_reprocessada(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1),))
            ext.executar_lote(lote, resolver_fns=_resolver_com_falha_em({(2000, 1)}), diretorio=diretorio)
            ext.executar_lote(lote, resolver_fns=_resolver_todas_ok, diretorio=diretorio)
            raw = pd.read_csv(diretorio / 'lote_teste_raw.csv')
            self.assertEqual(len(raw), 144)   # nunca 288 (a falha antiga não fica duplicada)

    def test_i_nao_reimplementa_validacao_de_rota_ou_integridade(self):
        """Estrutural — a extração reaproveita
        avaliar_aprovacao_piloto/executar_piloto_historico do piloto
        sem duplicar a lógica de validação de rota/integridade."""
        import inspect
        src = inspect.getsource(ext.executar_lote)
        self.assertIn('pilo.executar_piloto_historico', src)
        self.assertIn('pilo.avaliar_aprovacao_piloto', src)
        self.assertNotIn('def _origens_aprovadas_com_rota_diferente', src)
        self.assertNotIn('def _verificar_integridade_das_origens', src)


class ConsolidacaoTestCase(unittest.TestCase):
    """Seção 1 da tarefa — consolidação honesta: nunca finge
    completude parcial como total."""

    def test_a_nenhum_lote_rodado_reporta_incompleto(self):
        with tempfile.TemporaryDirectory() as tmp:
            lotes = (ext.LoteHistorico('teste', ((2000, 1), (2000, 2))),)
            consolidado = ext.consolidar_extracao_completa(lotes=lotes, diretorio=Path(tmp))
            self.assertFalse(consolidado['extracao_completa_e_aprovada'])
            self.assertEqual(consolidado['n_origens_aprovadas_total'], 0)
            self.assertEqual(consolidado['n_raw_total'], 0)
            self.assertIsNone(consolidado['n_raw_bate_com_esperado'])

    def test_b_parcialmente_concluido_reporta_incompleto_por_lote(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote1 = ext.LoteHistorico('l1', ((2000, 1),))
            lote2 = ext.LoteHistorico('l2', ((2000, 2),))
            ext.executar_lote(lote1, resolver_fns=_resolver_todas_ok, diretorio=diretorio)
            consolidado = ext.consolidar_extracao_completa(lotes=(lote1, lote2), diretorio=diretorio)
            self.assertFalse(consolidado['extracao_completa_e_aprovada'])
            self.assertEqual(consolidado['n_origens_aprovadas_total'], 1)
            self.assertTrue(consolidado['lotes_status']['l1']['iniciado'])
            self.assertFalse(consolidado['lotes_status']['l2']['iniciado'])

    def test_c_tudo_aprovado_reporta_completo_e_n_raw_bate(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote1 = ext.LoteHistorico('l1', ((2000, 1), (2000, 2)))
            lote2 = ext.LoteHistorico('l2', ((2000, 3),))
            ext.executar_lote(lote1, resolver_fns=_resolver_todas_ok, diretorio=diretorio)
            ext.executar_lote(lote2, resolver_fns=_resolver_todas_ok, diretorio=diretorio)
            consolidado = ext.consolidar_extracao_completa(lotes=(lote1, lote2), diretorio=diretorio)
            self.assertTrue(consolidado['extracao_completa_e_aprovada'])
            self.assertEqual(consolidado['n_origens_aprovadas_total'], 3)
            self.assertEqual(consolidado['n_raw_total'], 3 * 6 * 24)
            self.assertEqual(consolidado['n_raw_esperado_se_completo'], 3 * 6 * 24)
            self.assertTrue(consolidado['n_raw_bate_com_esperado'])

    def test_d_n_raw_esperado_e_dinamico_nao_hardcoded_para_240(self):
        """Regressão: comparar contra o total fixo de 34.560 (só válido
        para as 240 origens reais) faria um subconjunto pequeno e
        completo reportar `n_raw_bate_com_esperado=False` por engano —
        o esperado deve ser calculado a partir de `lotes`, não do
        constante de produção."""
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('l1', ((2000, 1),))
            ext.executar_lote(lote, resolver_fns=_resolver_todas_ok, diretorio=diretorio)
            consolidado = ext.consolidar_extracao_completa(lotes=(lote,), diretorio=diretorio)
            self.assertTrue(consolidado['extracao_completa_e_aprovada'])
            self.assertNotEqual(consolidado['n_raw_esperado_se_completo'], ext.N_RAW_ESPERADO_TOTAL)
            self.assertTrue(consolidado['n_raw_bate_com_esperado'])

    def test_e_lotes_historicos_reais_default_bate_com_34560(self):
        """Com o default real (LOTES_HISTORICOS, 240 origens), o
        esperado dinâmico coincide com N_RAW_ESPERADO_TOTAL."""
        with tempfile.TemporaryDirectory() as tmp:
            consolidado = ext.consolidar_extracao_completa(diretorio=Path(tmp))
            self.assertEqual(consolidado['n_raw_esperado_se_completo'], ext.N_RAW_ESPERADO_TOTAL)


class NuncaCalculaSkillNuncaModificaDashboardTestCase(unittest.TestCase):
    def test_consolidado_declara_restricoes(self):
        with tempfile.TemporaryDirectory() as tmp:
            consolidado = ext.consolidar_extracao_completa(diretorio=Path(tmp))
            self.assertTrue(consolidado['nenhuma_skill_calculada'])
            self.assertTrue(consolidado['nenhum_dashboard_alterado'])

    def test_modulo_nunca_importa_dashboard_ou_skill(self):
        codigo = Path(ext.__file__).read_text()
        self.assertNotIn('update_dashboard', codigo)
        self.assertNotIn('calcular_skill', codigo)

    def test_modulo_nunca_importa_catalogo_para_escrita(self):
        """nmme_catalogo não é sequer importado aqui — nenhuma rota/
        representação/sistema pode ser promovida por este módulo."""
        codigo = Path(ext.__file__).read_text()
        self.assertNotIn('import nmme_catalogo', codigo)


if __name__ == '__main__':
    unittest.main()
