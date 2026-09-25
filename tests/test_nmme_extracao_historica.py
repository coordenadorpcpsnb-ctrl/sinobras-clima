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


def _ds_para_origem_em(ano, mes, lat_centro, lon_centro, n_membros=24, valor_base=5.0, escala=3.0):
    """Generalização de `_ds_para_origem` para um ponto QUALQUER — usada
    nos testes de localização (revisão pontual, 3ª rodada) para simular
    o centroide das fazendas (lat=-7.80, lon=-47.95) sem duplicar
    `_ds_para_origem` (mantida intocada, ainda usada por todos os
    testes que já existiam antes desta rodada)."""
    lon_360 = lon_centro % 360.0
    lons = np.array([lon_360 - 1.0, lon_360, lon_360 + 1.0])
    lats = np.array([lat_centro - 1.0, lat_centro, lat_centro + 1.0])
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


def _resolver_fazendas(ano, mes):
    return _baixar_ok, (lambda c, ano=ano, mes=mes: _ds_para_origem_em(
        ano, mes, ext.FAZENDAS_LAT, ext.FAZENDAS_LON))


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


# ══════════════════════════════════════════════════════════════════════════
# Revisão pontual — problemas 1/2/3
# ══════════════════════════════════════════════════════════════════════════

def _linha_resumo_valida(ano=2000, mes=1):
    """Linha de resumo mínima, íntegra por construção — usada como
    ponto de partida nos testes de `_verificar_integridade_origem`,
    quebrada campo a campo em cada teste."""
    return pd.Series({
        'ano': ano, 'mes': mes, 'init_date': f'{ano}-{mes:02d}', 'poc_status': 'APROVADO',
        'backend_diferente_da_validada': False, 'representacao_diferente_da_validada': False,
    })


def _raw_valido(origem_str='2000-01', n_membros=24):
    linhas = [{'origem_piloto': origem_str, 'lead': lead, 'member': m}
              for lead in range(1, 7) for m in range(1, n_membros + 1)]
    return pd.DataFrame(linhas)


def _temporal_valido(origem_str='2000-01'):
    return pd.DataFrame([{'origem_piloto': origem_str, 'H_lead': lead} for lead in range(1, 7)])


class IntegridadeOrigemPersistidaTestCase(unittest.TestCase):
    """Revisão pontual, Seção 2 — `_verificar_integridade_origem`
    isolada: cada verificação exigida (status, backend, representação,
    identificação, 144 RAW, sem duplicata, 6 auditorias temporais)
    quebrada uma de cada vez, todas as outras íntegras."""

    def test_a_origem_nunca_persistida(self):
        integra, motivos = ext._verificar_integridade_origem('2000-01', None, pd.DataFrame(), pd.DataFrame())
        self.assertFalse(integra)
        self.assertEqual(motivos, ['origem_nao_persistida'])

    def test_b_tudo_integro(self):
        integra, motivos = ext._verificar_integridade_origem(
            '2000-01', _linha_resumo_valida(), _raw_valido(), _temporal_valido())
        self.assertTrue(integra)
        self.assertEqual(motivos, [])

    def test_c_poc_status_nao_aprovado(self):
        linha = _linha_resumo_valida()
        linha['poc_status'] = 'REPROVADO_ACESSO'
        integra, motivos = ext._verificar_integridade_origem('2000-01', linha, _raw_valido(), _temporal_valido())
        self.assertFalse(integra)
        self.assertIn('poc_status_nao_aprovado', motivos)

    def test_d_backend_diferente_da_validada(self):
        linha = _linha_resumo_valida()
        linha['backend_diferente_da_validada'] = True
        integra, motivos = ext._verificar_integridade_origem('2000-01', linha, _raw_valido(), _temporal_valido())
        self.assertFalse(integra)
        self.assertIn('backend_diferente_da_validada', motivos)

    def test_e_representacao_diferente_da_validada(self):
        linha = _linha_resumo_valida()
        linha['representacao_diferente_da_validada'] = True
        integra, motivos = ext._verificar_integridade_origem('2000-01', linha, _raw_valido(), _temporal_valido())
        self.assertFalse(integra)
        self.assertIn('representacao_diferente_da_validada', motivos)

    def test_f_init_date_divergente(self):
        linha = _linha_resumo_valida()
        linha['init_date'] = '1999-12'
        integra, motivos = ext._verificar_integridade_origem('2000-01', linha, _raw_valido(), _temporal_valido())
        self.assertFalse(integra)
        self.assertIn('init_date_divergente', motivos)

    def test_g_n_raw_menor_que_144(self):
        raw_incompleto = _raw_valido().iloc[:100]
        integra, motivos = ext._verificar_integridade_origem(
            '2000-01', _linha_resumo_valida(), raw_incompleto, _temporal_valido())
        self.assertFalse(integra)
        self.assertIn('n_raw_diferente_de_144', motivos)

    def test_h_n_raw_maior_que_144(self):
        raw_excedente = pd.concat([_raw_valido(), _raw_valido().iloc[:5]], ignore_index=True)
        integra, motivos = ext._verificar_integridade_origem(
            '2000-01', _linha_resumo_valida(), raw_excedente, _temporal_valido())
        self.assertFalse(integra)
        self.assertIn('n_raw_diferente_de_144', motivos)

    def test_i_duplicata_lead_member(self):
        raw = _raw_valido()
        raw_com_duplicata = pd.concat([raw.iloc[:-1], raw.iloc[[0]]], ignore_index=True)   # ainda 144 linhas
        self.assertEqual(len(raw_com_duplicata), 144)
        integra, motivos = ext._verificar_integridade_origem(
            '2000-01', _linha_resumo_valida(), raw_com_duplicata, _temporal_valido())
        self.assertFalse(integra)
        self.assertIn('duplicata_lead_member', motivos)

    def test_j_auditoria_temporal_faltando_um_lead(self):
        temporal_incompleto = _temporal_valido().iloc[:5]   # só H1-H5
        integra, motivos = ext._verificar_integridade_origem(
            '2000-01', _linha_resumo_valida(), _raw_valido(), temporal_incompleto)
        self.assertFalse(integra)
        self.assertIn('auditorias_temporais_incompletas', motivos)

    def test_k_auditoria_temporal_com_lead_duplicado(self):
        temporal = _temporal_valido()
        temporal_com_duplicata = pd.concat([temporal.iloc[:-1], temporal.iloc[[0]]], ignore_index=True)
        self.assertEqual(len(temporal_com_duplicata), 6)   # ainda 6 linhas, mas H1 duas vezes e H6 ausente
        integra, motivos = ext._verificar_integridade_origem(
            '2000-01', _linha_resumo_valida(), _raw_valido(), temporal_com_duplicata)
        self.assertFalse(integra)
        self.assertIn('auditorias_temporais_incompletas', motivos)

    def test_l_raw_de_outra_origem_nao_conta(self):
        """raw_df/temporal_df podem conter várias origens (é assim que
        são persistidos por lote) — só as linhas com o `origem_piloto`
        pedido contam para esta verificação."""
        raw_outra_origem = _raw_valido(origem_str='1999-06')
        integra, motivos = ext._verificar_integridade_origem(
            '2000-01', _linha_resumo_valida(), raw_outra_origem, _temporal_valido())
        self.assertFalse(integra)
        self.assertIn('n_raw_diferente_de_144', motivos)


class RetomadaComArquivosIncompletosTestCase(unittest.TestCase):
    """Revisão pontual, Seção 2 — 'se os arquivos estiverem incompletos
    ou inconsistentes, registrar o problema e não considerar a
    inicialização validamente preservada', e 'não perder os registros
    anteriores sem antes identificar a inconsistência'."""

    def test_a_resumo_diz_aprovado_mas_raw_csv_truncado_fica_pendente(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1),))
            ext.executar_lote(lote, resolver_fns=_resolver_todas_ok, diretorio=diretorio)

            # Corrompe o raw.csv persistido (simula truncamento/edição
            # depois do fato) SEM tocar no resumo, que continua
            # dizendo APROVADO — exatamente o cenário que o bug real
            # de n_raw=0 já provou ser possível nesta extração.
            caminho_raw = ext._caminho_lote('teste', 'raw.csv', diretorio)
            raw = pd.read_csv(caminho_raw)
            self.assertEqual(len(raw), 144)
            raw.iloc[:100].to_csv(caminho_raw, index=False)

            pendentes = ext.origens_pendentes(lote, diretorio)
            self.assertEqual(pendentes, ((2000, 1),))

    def test_b_inconsistencia_e_registrada_na_metadata_do_lote(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1),))
            ext.executar_lote(lote, resolver_fns=_resolver_todas_ok, diretorio=diretorio)
            caminho_raw = ext._caminho_lote('teste', 'raw.csv', diretorio)
            pd.read_csv(caminho_raw).iloc[:100].to_csv(caminho_raw, index=False)

            metadata = ext.executar_lote(lote, resolver_fns=_resolver_todas_ok, diretorio=diretorio)
            self.assertEqual(len(metadata['origens_com_inconsistencia_detectada']), 1)
            registro = metadata['origens_com_inconsistencia_detectada'][0]
            self.assertEqual(registro['origem'], '2000-01')
            self.assertIn('n_raw_diferente_de_144', registro['motivos'])

    def test_c_nunca_tentada_nao_conta_como_inconsistencia(self):
        """Uma origem que simplesmente nunca rodou ainda (motivo único
        'origem_nao_persistida') não é uma INCONSISTÊNCIA — é o estado
        normal de um lote ainda não concluído."""
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1),))
            metadata = ext.executar_lote(lote, resolver_fns=_resolver_todas_ok, diretorio=diretorio)
            self.assertEqual(metadata['origens_com_inconsistencia_detectada'], [])

    def test_d_retomada_corrige_a_inconsistencia_sem_perder_dado_bom_de_outra_origem(self):
        """'Não perder os registros anteriores sem antes identificar a
        inconsistência' — a origem boa (2000-02) nunca é tocada; só a
        corrompida (2000-01) é reprocessada e corrigida."""
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1), (2000, 2)))
            ext.executar_lote(lote, resolver_fns=_resolver_todas_ok, diretorio=diretorio)
            caminho_raw = ext._caminho_lote('teste', 'raw.csv', diretorio)
            raw = pd.read_csv(caminho_raw)
            raw_corrompido = raw[~((raw['origem_piloto'] == '2000-01') & (raw.index >= raw.index[raw['origem_piloto'] == '2000-01'][40]))]
            raw_corrompido.to_csv(caminho_raw, index=False)

            resolver_contado = _resolver_contado(_resolver_todas_ok)
            metadata = ext.executar_lote(lote, resolver_fns=resolver_contado, diretorio=diretorio)
            self.assertEqual(resolver_contado.chamadas, [(2000, 1)])   # só a corrompida foi reconsultada
            self.assertEqual(metadata['lote_status'], 'APROVADO')
            raw_final = pd.read_csv(caminho_raw)
            self.assertEqual(len(raw_final[raw_final['origem_piloto'] == '2000-01']), 144)
            self.assertEqual(len(raw_final[raw_final['origem_piloto'] == '2000-02']), 144)


class PersistenciaAposFalhaParcialTestCase(unittest.TestCase):
    """Revisão pontual, Seção 1 — 'os resultados obtidos sejam
    persistidos mesmo quando uma ou mais inicializações do lote forem
    reprovadas' e 'não transformar uma execução parcialmente reprovada
    em sucesso'. Nível Python (a orquestração do workflow em si — que
    dependia disso continuar disponível em disco mesmo com o passo
    anterior tendo saído com erro — é testada separadamente em
    tests/test_workflow_extracao_historica.sh)."""

    def test_a_origem_aprovada_persiste_mesmo_com_outra_reprovada_no_mesmo_lote(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1), (2000, 2)))
            metadata = ext.executar_lote(
                lote, resolver_fns=_resolver_com_falha_em({(2000, 1)}), diretorio=diretorio)
            self.assertEqual(metadata['lote_status'], 'REPROVADO')   # sinalização preservada

            raw = pd.read_csv(ext._caminho_lote('teste', 'raw.csv', diretorio))
            self.assertEqual(len(raw[raw['origem_piloto'] == '2000-02']), 144)   # persistida mesmo assim
            self.assertEqual(len(raw[raw['origem_piloto'] == '2000-01']), 0)   # a que falhou não tem RAW

    def test_b_resumo_tem_linha_para_a_origem_que_falhou_tambem(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1), (2000, 2)))
            ext.executar_lote(lote, resolver_fns=_resolver_com_falha_em({(2000, 1)}), diretorio=diretorio)
            resumo = pd.read_csv(ext._caminho_lote('teste', 'resumo_por_origem.csv', diretorio))
            self.assertEqual(len(resumo), 2)
            self.assertNotEqual(
                resumo.loc[resumo['init_date'] == '2000-01', 'poc_status'].iloc[0], 'APROVADO')
            self.assertEqual(
                resumo.loc[resumo['init_date'] == '2000-02', 'poc_status'].iloc[0], 'APROVADO')

    def test_c_reprovacao_nunca_vira_sucesso_silencioso(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1), (2000, 2)))
            metadata = ext.executar_lote(
                lote, resolver_fns=_resolver_com_falha_em({(2000, 1)}), diretorio=diretorio)
            self.assertNotEqual(metadata['lote_status'], 'APROVADO')
            self.assertFalse(metadata['criterios']['todas_origens_aprovadas'])


class DiretorioInicialmenteInexistenteTestCase(unittest.TestCase):
    """Revisão pontual, Seção 1 — o workflow (e as funções Python por
    trás dele) não podem falhar por data/nmme_historico/ ainda não
    existir na primeira execução."""

    def test_a_origens_pendentes_com_diretorio_nunca_criado(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio_inexistente = Path(tmp) / 'nunca_criado' / 'nmme_historico'
            self.assertFalse(diretorio_inexistente.exists())
            lote = ext.LoteHistorico('teste', ((2000, 1),))
            pendentes = ext.origens_pendentes(lote, diretorio_inexistente)
            self.assertEqual(pendentes, ((2000, 1),))

    def test_b_diagnosticar_integridade_lote_com_diretorio_nunca_criado(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio_inexistente = Path(tmp) / 'nunca_criado' / 'nmme_historico'
            lote = ext.LoteHistorico('teste', ((2000, 1),))
            diagnostico = ext.diagnosticar_integridade_lote(lote, diretorio_inexistente)
            self.assertFalse(diagnostico[(2000, 1)]['concluida_e_integra'])
            self.assertEqual(diagnostico[(2000, 1)]['motivos'], ['origem_nao_persistida'])

    def test_c_executar_lote_cria_o_diretorio_sozinho(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio_inexistente = Path(tmp) / 'nunca_criado' / 'nmme_historico'
            lote = ext.LoteHistorico('teste', ((2000, 1),))
            ext.executar_lote(lote, resolver_fns=_resolver_todas_ok, diretorio=diretorio_inexistente)
            self.assertTrue(diretorio_inexistente.exists())


class ConsolidacaoComRawInsuficienteTestCase(unittest.TestCase):
    """Revisão pontual, Seção 3 — a aprovação final exige
    SIMULTANEAMENTE as 240 (aqui, um conjunto pequeno de teste)
    inicializações aprovadas, rota validada, exatamente 144 RAW por
    inicialização, o total batendo E as auditorias temporais completas
    — uma divergência em RAW insuficiente bloqueia mesmo que o resumo
    persistido diga APROVADO para todas."""

    def test_a_raw_insuficiente_em_1_origem_bloqueia_consolidacao_mesmo_com_resumo_aprovado(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote1 = ext.LoteHistorico('l1', ((2000, 1), (2000, 2)))
            lote2 = ext.LoteHistorico('l2', ((2000, 3),))
            ext.executar_lote(lote1, resolver_fns=_resolver_todas_ok, diretorio=diretorio)
            ext.executar_lote(lote2, resolver_fns=_resolver_todas_ok, diretorio=diretorio)

            # Corrompe o RAW de 1 origem já aprovada (resumo continua
            # dizendo APROVADO) — simula divergência entre o resumo e
            # o dado real persistido: remove as últimas 50 linhas QUE
            # PERTENCEM a 2000-01, deixando 94 (não 144).
            caminho_raw = ext._caminho_lote('l1', 'raw.csv', diretorio)
            raw = pd.read_csv(caminho_raw)
            idx_2000_01 = raw.index[raw['origem_piloto'] == '2000-01']
            raw.drop(index=idx_2000_01[-50:]).to_csv(caminho_raw, index=False)

            consolidado = ext.consolidar_extracao_completa(lotes=(lote1, lote2), diretorio=diretorio)
            self.assertFalse(consolidado['extracao_completa_e_aprovada'])
            self.assertFalse(consolidado['todas_origens_com_144_raw'])
            self.assertLess(consolidado['n_origens_aprovadas_total'], 3)

    def test_b_auditoria_temporal_incompleta_em_1_origem_bloqueia_consolidacao(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('l1', ((2000, 1), (2000, 2)))
            ext.executar_lote(lote, resolver_fns=_resolver_todas_ok, diretorio=diretorio)

            caminho_temporal = ext._caminho_lote('l1', 'temporal_audit.csv', diretorio)
            temporal = pd.read_csv(caminho_temporal)
            temporal_incompleto = temporal[~((temporal['origem_piloto'] == '2000-01')
                                               & (temporal['H_lead'] == 6))]
            temporal_incompleto.to_csv(caminho_temporal, index=False)

            consolidado = ext.consolidar_extracao_completa(lotes=(lote,), diretorio=diretorio)
            self.assertFalse(consolidado['extracao_completa_e_aprovada'])
            self.assertFalse(consolidado['todas_auditorias_temporais_completas'])

    def test_c_tudo_144_e_completo_aprova_normalmente(self):
        """Contraprova — sem corrupção nenhuma, a consolidação de um
        conjunto pequeno mas completo aprova normalmente (garante que
        as novas verificações não introduziram falso negativo)."""
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('l1', ((2000, 1), (2000, 2)))
            ext.executar_lote(lote, resolver_fns=_resolver_todas_ok, diretorio=diretorio)
            consolidado = ext.consolidar_extracao_completa(lotes=(lote,), diretorio=diretorio)
            self.assertTrue(consolidado['extracao_completa_e_aprovada'])
            self.assertTrue(consolidado['todas_origens_com_144_raw'])
            self.assertTrue(consolidado['todas_auditorias_temporais_completas'])
            self.assertEqual(consolidado['n_raw_total'], 288)

    def test_d_registro_raw_extra_de_origem_inesperada_bloqueia_consolidacao(self):
        """Revisão pontual (2ª rodada) — regressão específica pedida:
        TODAS as origens previstas aprovadas, cada uma com exatamente
        144 RAW (`todas_origens_com_144_raw` continua True, porque essa
        verificação só soma linhas das origens PREVISTAS em
        `lote.origens`) — mas existe 1 registro RAW A MAIS associado a
        uma origem que não está no plano nenhum ('1999-06', fora de
        `lote.origens`). Isso NUNCA deveria acontecer num raw.csv
        gerado por este módulo, mas nada impede um arquivo editado à
        mão de introduzir isso — só a comparação agregada
        `n_raw_total == n_raw_esperado` pega esse caso, e ela precisa
        bloquear `extracao_completa_e_aprovada` explicitamente."""
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('l1', ((2000, 1), (2000, 2)))
            ext.executar_lote(lote, resolver_fns=_resolver_todas_ok, diretorio=diretorio)

            caminho_raw = ext._caminho_lote('l1', 'raw.csv', diretorio)
            raw = pd.read_csv(caminho_raw)
            self.assertEqual(len(raw), 288)
            linha_extra = raw.iloc[[0]].copy()
            linha_extra['origem_piloto'] = '1999-06'   # origem fora do plano do lote
            pd.concat([raw, linha_extra], ignore_index=True).to_csv(caminho_raw, index=False)

            consolidado = ext.consolidar_extracao_completa(lotes=(lote,), diretorio=diretorio)
            self.assertEqual(consolidado['n_raw_total'], 289)
            self.assertEqual(consolidado['n_raw_esperado_se_completo'], 288)
            # As origens PREVISTAS continuam corretas — a única
            # divergência é o total agregado, por causa do registro de
            # uma origem inesperada.
            self.assertTrue(consolidado['todas_origens_com_144_raw'])
            self.assertTrue(consolidado['todas_auditorias_temporais_completas'])
            self.assertEqual(consolidado['n_origens_aprovadas_total'], 2)
            self.assertFalse(consolidado['n_raw_bate_com_esperado'])
            self.assertFalse(consolidado['extracao_completa_e_aprovada'])


class LocalizacaoTestCase(unittest.TestCase):
    """Revisão pontual (3ª rodada) — parametrização da localização
    (item 1: preserva São Bento; item 2: diretório próprio para as
    fazendas; item 3: coordenadas solicitada/selecionada registradas)."""

    def test_a_lat_lon_sao_bento_preserva_resolucao_via_municipios(self):
        self.assertEqual(ext.lat_lon_para_localizacao(ext.LOCALIZACAO_SAO_BENTO), (None, None))

    def test_b_lat_lon_fazendas_e_explicito(self):
        self.assertEqual(ext.lat_lon_para_localizacao(ext.LOCALIZACAO_FAZENDAS),
                          (ext.FAZENDAS_LAT, ext.FAZENDAS_LON))

    def test_c_fazendas_lat_lon_bate_com_chirps_e_poc_espacial(self):
        import _chirps
        import nmme_poc_espacial_fazendas as espacial
        self.assertEqual(ext.FAZENDAS_LAT, _chirps.FAZENDAS_LAT)
        self.assertEqual(ext.FAZENDAS_LON, _chirps.FAZENDAS_LON)
        self.assertEqual(ext.FAZENDAS_LAT, espacial.FAZENDAS_LAT)
        self.assertEqual(ext.FAZENDAS_LON, espacial.FAZENDAS_LON)

    def test_d_diretorios_padrao_sao_distintos(self):
        d_sb = ext.diretorio_padrao_para_localizacao(ext.LOCALIZACAO_SAO_BENTO)
        d_faz = ext.diretorio_padrao_para_localizacao(ext.LOCALIZACAO_FAZENDAS)
        self.assertNotEqual(d_sb, d_faz)
        self.assertEqual(d_sb, ext.DIRETORIO_HISTORICO)
        self.assertEqual(d_faz, ext.DIRETORIO_HISTORICO_FAZENDAS)

    def test_e_localizacao_invalida_lanca_erro(self):
        with self.assertRaises(ValueError):
            ext.diretorio_padrao_para_localizacao('Outra_Localizacao_Qualquer')
        with self.assertRaises(ValueError):
            ext.lat_lon_para_localizacao('Outra_Localizacao_Qualquer')

    def test_f_executar_lote_default_preserva_sao_bento(self):
        """Nenhum `localizacao` passado — comportamento idêntico ao de
        antes desta revisão (item 1: "preservando integralmente")."""
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1),))
            metadata = ext.executar_lote(lote, resolver_fns=_resolver_todas_ok, diretorio=diretorio)
            self.assertEqual(metadata['localizacao'], ext.LOCALIZACAO_SAO_BENTO)
            self.assertIsNone(metadata['localizacao_lat'])
            self.assertIsNone(metadata['localizacao_lon'])
            raw = pd.read_csv(diretorio / 'lote_teste_raw.csv')
            self.assertTrue((raw['requested_lat'] == SAO_BENTO['lat']).all())
            self.assertNotIn('evidencia_poc_localizacao', metadata)

    def test_g_executar_lote_fazendas_usa_coordenadas_das_fazendas(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1),))
            metadata = ext.executar_lote(lote, resolver_fns=_resolver_fazendas, diretorio=diretorio,
                                           localizacao=ext.LOCALIZACAO_FAZENDAS)
            self.assertEqual(metadata['localizacao'], ext.LOCALIZACAO_FAZENDAS)
            self.assertEqual(metadata['localizacao_lat'], ext.FAZENDAS_LAT)
            self.assertEqual(metadata['localizacao_lon'], ext.FAZENDAS_LON)
            raw = pd.read_csv(diretorio / 'lote_teste_raw.csv')
            self.assertTrue((raw['requested_lat'] == ext.FAZENDAS_LAT).all())
            self.assertTrue((raw['requested_lon'] == ext.FAZENDAS_LON).all())

    def test_h_coordenada_solicitada_e_selecionada_registradas_em_todos_os_resultados(self):
        """Item 3 — nunca só a coordenada pedida, também o ponto de
        grade efetivamente selecionado, em toda linha RAW."""
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1), (2000, 2)))
            ext.executar_lote(lote, resolver_fns=_resolver_fazendas, diretorio=diretorio,
                                localizacao=ext.LOCALIZACAO_FAZENDAS)
            raw = pd.read_csv(diretorio / 'lote_teste_raw.csv')
            for col in ('requested_lat', 'requested_lon', 'selected_lat', 'selected_lon'):
                self.assertIn(col, raw.columns)
                self.assertTrue(raw[col].notna().all(), col)

    def test_i_evidencia_poc_fazendas_so_aparece_para_fazendas(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1),))
            metadata_faz = ext.executar_lote(lote, resolver_fns=_resolver_fazendas, diretorio=diretorio,
                                               localizacao=ext.LOCALIZACAO_FAZENDAS)
            self.assertIn('evidencia_poc_localizacao', metadata_faz)
            self.assertEqual(metadata_faz['evidencia_poc_localizacao']['run_id'], 36169942349)
            self.assertFalse(metadata_faz['evidencia_poc_localizacao']['aptidao_cientifica_declarada'])
            self.assertFalse(metadata_faz['evidencia_poc_localizacao']['outras_localizacoes_promovidas'])

        with tempfile.TemporaryDirectory() as tmp2:
            diretorio2 = Path(tmp2)
            lote2 = ext.LoteHistorico('teste', ((2000, 1),))
            metadata_sb = ext.executar_lote(lote2, resolver_fns=_resolver_todas_ok, diretorio=diretorio2)
            self.assertNotIn('evidencia_poc_localizacao', metadata_sb)


class NuncaMisturaLocalidadesTestCase(unittest.TestCase):
    """Revisão pontual (3ª rodada), item 7 — regressão explícita:
    impedir que registros de São Bento e das fazendas se misturem, seja
    em disco (diretórios) ou na integridade persistida (coluna
    `localizacao`)."""

    def test_a_localizacao_gravada_em_toda_linha_raw_temporal_resumo(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1),))
            ext.executar_lote(lote, resolver_fns=_resolver_fazendas, diretorio=diretorio,
                                localizacao=ext.LOCALIZACAO_FAZENDAS)
            raw = pd.read_csv(diretorio / 'lote_teste_raw.csv')
            temporal = pd.read_csv(diretorio / 'lote_teste_temporal_audit.csv')
            resumo = pd.read_csv(diretorio / 'lote_teste_resumo_por_origem.csv')
            self.assertTrue((raw['localizacao'] == ext.LOCALIZACAO_FAZENDAS).all())
            self.assertTrue((temporal['localizacao'] == ext.LOCALIZACAO_FAZENDAS).all())
            self.assertTrue((resumo['localizacao'] == ext.LOCALIZACAO_FAZENDAS).all())

    def test_b_duas_localidades_em_diretorios_separados_nunca_se_tocam(self):
        with tempfile.TemporaryDirectory() as tmp_sb, tempfile.TemporaryDirectory() as tmp_faz:
            dir_sb, dir_faz = Path(tmp_sb), Path(tmp_faz)
            lote = ext.LoteHistorico('teste', ((2000, 1), (2000, 2)))
            ext.executar_lote(lote, resolver_fns=_resolver_todas_ok, diretorio=dir_sb,
                                localizacao=ext.LOCALIZACAO_SAO_BENTO)
            ext.executar_lote(lote, resolver_fns=_resolver_fazendas, diretorio=dir_faz,
                                localizacao=ext.LOCALIZACAO_FAZENDAS)

            raw_sb = pd.read_csv(dir_sb / 'lote_teste_raw.csv')
            raw_faz = pd.read_csv(dir_faz / 'lote_teste_raw.csv')
            self.assertTrue((raw_sb['localizacao'] == ext.LOCALIZACAO_SAO_BENTO).all())
            self.assertTrue((raw_faz['localizacao'] == ext.LOCALIZACAO_FAZENDAS).all())
            self.assertTrue((raw_sb['requested_lat'] == SAO_BENTO['lat']).all())
            self.assertTrue((raw_faz['requested_lat'] == ext.FAZENDAS_LAT).all())
            # Nenhum arquivo de uma localidade aparece no diretório da outra.
            self.assertEqual(sorted(p.name for p in dir_sb.iterdir()),
                              sorted(p.name for p in dir_faz.iterdir()))   # mesmos NOMES de arquivo...
            self.assertNotEqual(dir_sb, dir_faz)   # ...mas em diretórios diferentes

    def test_c_linha_contaminada_de_outra_localidade_e_detectada_e_fica_pendente(self):
        """Regressão central do item 7 — uma linha de OUTRA localidade
        "vazada" para dentro do raw.csv de uma origem (mesmo
        `origem_piloto`, `localizacao` diferente) é detectada mesmo que
        a origem já estivesse com poc_status=APROVADO persistido."""
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1), (2000, 2)))
            ext.executar_lote(lote, resolver_fns=_resolver_fazendas, diretorio=diretorio,
                                localizacao=ext.LOCALIZACAO_FAZENDAS)

            caminho_raw = diretorio / 'lote_teste_raw.csv'
            raw = pd.read_csv(caminho_raw)
            linha_contaminada = raw.iloc[[0]].copy()
            linha_contaminada['localizacao'] = ext.LOCALIZACAO_SAO_BENTO
            linha_contaminada['requested_lat'] = SAO_BENTO['lat']
            linha_contaminada['requested_lon'] = SAO_BENTO['lon']
            # A linha contaminada pertence à MESMA origem (2000-01) —
            # nunca uma origem nova/inexistente no plano.
            self.assertEqual(linha_contaminada['origem_piloto'].iloc[0], '2000-01')
            pd.concat([raw, linha_contaminada], ignore_index=True).to_csv(caminho_raw, index=False)

            pendentes = ext.origens_pendentes(lote, diretorio, localizacao_esperada=ext.LOCALIZACAO_FAZENDAS)
            self.assertEqual(pendentes, ((2000, 1),))   # só a contaminada, nunca a 2000-02 (limpa)

    def test_d_retomada_corrige_contaminacao_sem_tocar_na_origem_limpa(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('teste', ((2000, 1), (2000, 2)))
            ext.executar_lote(lote, resolver_fns=_resolver_fazendas, diretorio=diretorio,
                                localizacao=ext.LOCALIZACAO_FAZENDAS)

            caminho_raw = diretorio / 'lote_teste_raw.csv'
            raw = pd.read_csv(caminho_raw)
            linha_contaminada = raw.iloc[[0]].copy()
            linha_contaminada['localizacao'] = ext.LOCALIZACAO_SAO_BENTO
            pd.concat([raw, linha_contaminada], ignore_index=True).to_csv(caminho_raw, index=False)

            resolver_contado = _resolver_contado(_resolver_fazendas)
            metadata = ext.executar_lote(lote, resolver_fns=resolver_contado, diretorio=diretorio,
                                           localizacao=ext.LOCALIZACAO_FAZENDAS)
            self.assertEqual(resolver_contado.chamadas, [(2000, 1)])   # só a contaminada
            self.assertEqual(metadata['lote_status'], 'APROVADO')

            raw_final = pd.read_csv(caminho_raw)
            self.assertTrue((raw_final['localizacao'] == ext.LOCALIZACAO_FAZENDAS).all())
            self.assertEqual(len(raw_final[raw_final['origem_piloto'] == '2000-01']), 144)
            self.assertEqual(len(raw_final[raw_final['origem_piloto'] == '2000-02']), 144)

    def test_e_consolidacao_reprova_quando_ha_contaminacao_de_outra_localidade(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            lote = ext.LoteHistorico('l1', ((2000, 1), (2000, 2)))
            ext.executar_lote(lote, resolver_fns=_resolver_fazendas, diretorio=diretorio,
                                localizacao=ext.LOCALIZACAO_FAZENDAS)

            caminho_raw = diretorio / 'lote_l1_raw.csv'
            raw = pd.read_csv(caminho_raw)
            linha_contaminada = raw.iloc[[0]].copy()
            linha_contaminada['localizacao'] = ext.LOCALIZACAO_SAO_BENTO
            pd.concat([raw, linha_contaminada], ignore_index=True).to_csv(caminho_raw, index=False)

            consolidado = ext.consolidar_extracao_completa(
                lotes=(lote,), diretorio=diretorio, localizacao=ext.LOCALIZACAO_FAZENDAS)
            self.assertFalse(consolidado['extracao_completa_e_aprovada'])
            self.assertLess(consolidado['n_origens_aprovadas_total'], 2)

    def test_f_verificar_integridade_ignora_localizacao_quando_nao_pedido(self):
        """Backward-compat explícito — com `localizacao_esperada=None`
        (default), uma linha com localização "errada" NUNCA é motivo de
        reprovação (comportamento anterior a esta revisão, preservado
        para quem não passa o parâmetro)."""
        linha = pd.Series({'ano': 2000, 'mes': 1, 'init_date': '2000-01', 'poc_status': 'APROVADO',
                             'backend_diferente_da_validada': False,
                             'representacao_diferente_da_validada': False,
                             'localizacao': 'Qualquer_Outra_Coisa'})
        raw = pd.DataFrame([{'origem_piloto': '2000-01', 'lead': lead, 'member': m,
                               'localizacao': 'Qualquer_Outra_Coisa'}
                              for lead in range(1, 7) for m in range(1, 25)])
        temporal = pd.DataFrame([{'origem_piloto': '2000-01', 'H_lead': lead,
                                    'localizacao': 'Qualquer_Outra_Coisa'} for lead in range(1, 7)])
        integra, motivos = ext._verificar_integridade_origem('2000-01', linha, raw, temporal)
        self.assertTrue(integra)
        self.assertEqual(motivos, [])

    def test_g_verificar_integridade_pega_localizacao_errada_quando_pedido(self):
        linha = pd.Series({'ano': 2000, 'mes': 1, 'init_date': '2000-01', 'poc_status': 'APROVADO',
                             'backend_diferente_da_validada': False,
                             'representacao_diferente_da_validada': False,
                             'localizacao': ext.LOCALIZACAO_SAO_BENTO})
        raw = pd.DataFrame([{'origem_piloto': '2000-01', 'lead': lead, 'member': m,
                               'localizacao': ext.LOCALIZACAO_SAO_BENTO}
                              for lead in range(1, 7) for m in range(1, 25)])
        temporal = pd.DataFrame([{'origem_piloto': '2000-01', 'H_lead': lead,
                                    'localizacao': ext.LOCALIZACAO_SAO_BENTO} for lead in range(1, 7)])
        integra, motivos = ext._verificar_integridade_origem(
            '2000-01', linha, raw, temporal, localizacao_esperada=ext.LOCALIZACAO_FAZENDAS)
        self.assertFalse(integra)
        self.assertIn('localizacao_diferente_da_esperada', motivos)

    def test_h_coluna_localizacao_ausente_no_raw_falha_fechado(self):
        """Uma linha RAW sem a coluna `localizacao` de jeito nenhum
        (arquivo de antes desta revisão, hipotético) NÃO é tratada como
        automaticamente válida quando a verificação está ativa — falha
        fechado, nunca assume o melhor caso por ausência de dado."""
        linha = pd.Series({'ano': 2000, 'mes': 1, 'init_date': '2000-01', 'poc_status': 'APROVADO',
                             'backend_diferente_da_validada': False,
                             'representacao_diferente_da_validada': False})   # sem 'localizacao'
        raw = pd.DataFrame([{'origem_piloto': '2000-01', 'lead': lead, 'member': m}
                              for lead in range(1, 7) for m in range(1, 25)])   # sem 'localizacao'
        temporal = pd.DataFrame([{'origem_piloto': '2000-01', 'H_lead': lead} for lead in range(1, 7)])
        integra, motivos = ext._verificar_integridade_origem(
            '2000-01', linha, raw, temporal, localizacao_esperada=ext.LOCALIZACAO_FAZENDAS)
        self.assertFalse(integra)
        self.assertIn('localizacao_diferente_da_esperada', motivos)

    def test_i_lotes_historicos_identicos_para_as_duas_localidades(self):
        """Item 4 — os mesmos 5 lotes/240 origens, nunca uma partição
        paralela duplicada para as fazendas."""
        self.assertEqual(len(ext.LOTES_HISTORICOS), 5)
        origens_todas = tuple(o for lote in ext.LOTES_HISTORICOS for o in lote.origens)
        self.assertEqual(len(origens_todas), 240)
        # Usar o MESMO LOTES_HISTORICOS para as duas localidades —
        # nenhuma constante paralela criada para fazendas.
        for lote in ext.LOTES_HISTORICOS:
            self.assertIsInstance(lote, ext.LoteHistorico)


if __name__ == '__main__':
    unittest.main()
