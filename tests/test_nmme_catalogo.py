#!/usr/bin/env python3
"""
tests/test_nmme_catalogo.py — regressão do catálogo auditável NMME
(scripts/nmme_catalogo.py), Fase 2C.1. Tudo offline — nenhum teste
acessa rede.

Roda com:
    python -m unittest tests.test_nmme_catalogo -v
"""

import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import nmme_catalogo as ncat  # noqa: E402


def _sistema_minimo(**overrides):
    base = dict(
        centre='TEST', model_name='TESTMODEL', model_version=None, official_model_id=None,
        data_source='teste', data_url_template=None, data_access_status=ncat.DATA_ACCESS_UNCONFIRMED,
        current_operational_name=None, hindcast_start=None, hindcast_end=None,
        hindcast_members=10, realtime_members=None, leads_available=(1, 2, 3, 4, 5, 6),
        grid_resolution=None, precip_variable=None, precip_units=None, hindcast_frequency=None,
        initialization_scheme=None, availability_status=ncat.STATUS_CANDIDATO,
        source_reference=(), notes='', evidence={'hindcast_members': ncat.DOCUMENTED},
    )
    base.update(overrides)
    return ncat.SistemaNMME(**base)


# ══════════════════════════════════════════════════════════════════════════
# A — catálogo não aceita período inventado.
# ══════════════════════════════════════════════════════════════════════════

class PeriodoNaoInventadoTestCase(unittest.TestCase):

    def test_a_hindcast_start_sem_fonte_falha(self):
        s = _sistema_minimo(hindcast_start=1991, hindcast_end=2020, source_reference=(),
                             evidence={'hindcast_start': ncat.DOCUMENTED, 'hindcast_end': ncat.DOCUMENTED,
                                       'hindcast_members': ncat.DOCUMENTED})
        with self.assertRaises(ValueError) as e:
            ncat._validar_catalogo([s])
        self.assertIn('source_reference', str(e.exception))

    def test_a_hindcast_start_com_fonte_passa(self):
        s = _sistema_minimo(hindcast_start=1991, hindcast_end=2020, source_reference=('fonte X',),
                             evidence={'hindcast_start': ncat.DOCUMENTED, 'hindcast_end': ncat.DOCUMENTED,
                                       'hindcast_members': ncat.DOCUMENTED})
        self.assertTrue(ncat._validar_catalogo([s]))

    def test_a_catalogo_real_passa_na_validacao(self):
        self.assertTrue(ncat._validar_catalogo(ncat.CATALOGO))


# ══════════════════════════════════════════════════════════════════════════
# B — modelo sem fonte oficial fica UNCONFIRMED.
# ══════════════════════════════════════════════════════════════════════════

class ModeloSemFonteUnconfirmedTestCase(unittest.TestCase):

    def test_b_campo_sem_entrada_na_matriz_e_unconfirmed(self):
        s = _sistema_minimo(evidence={})
        self.assertEqual(ncat.status_evidencia(s, 'grid_resolution'), ncat.UNCONFIRMED)
        self.assertEqual(ncat.status_evidencia(s, 'hindcast_members'), ncat.UNCONFIRMED)

    def test_b_valor_numerico_sem_status_na_matriz_falha(self):
        s = _sistema_minimo(hindcast_members=10, evidence={})
        with self.assertRaises(ValueError) as e:
            ncat._validar_catalogo([s])
        self.assertIn('hindcast_members', str(e.exception))

    def test_b_status_invalido_falha(self):
        s = _sistema_minimo(evidence={'hindcast_members': 'TALVEZ'})
        with self.assertRaises(ValueError):
            ncat._validar_catalogo([s])


# ══════════════════════════════════════════════════════════════════════════
# C/D/E/F — versões sucessoras NUNCA concatenadas com o predecessor.
# ══════════════════════════════════════════════════════════════════════════

class VersoesNaoConcatenadasTestCase(unittest.TestCase):

    def test_c_versoes_sucessoras_nao_sao_concatenadas_no_catalogo(self):
        """Nenhuma entrada do CATALOGO usa o nome do predecessor —
        garante que a lista atual nunca mistura geração antiga/nova sob
        o mesmo model_name."""
        nomes_catalogo = {s.model_name for s in ncat.CATALOGO}
        nomes_predecessores = set(ncat.PREDECESSORES_NAO_CONFUNDIR)
        self.assertEqual(nomes_catalogo & nomes_predecessores, set())

    def test_d_cancm4i_nao_e_canesm5(self):
        self.assertIn('CanCM4i', ncat.PREDECESSORES_NAO_CONFUNDIR)
        self.assertEqual(ncat.PREDECESSORES_NAO_CONFUNDIR['CanCM4i']['substituido_por'], 'CanESM5')
        with self.assertRaises(KeyError):
            ncat.sistema_por_nome('ECCC', 'CanCM4i')
        canesm5 = ncat.sistema_por_nome('ECCC', 'CanESM5')
        self.assertNotEqual(canesm5.model_name, 'CanCM4i')

    def test_e_gem_nemo_nao_e_gem52_nemo(self):
        self.assertIn('GEM_NEMO', ncat.PREDECESSORES_NAO_CONFUNDIR)
        self.assertEqual(ncat.PREDECESSORES_NAO_CONFUNDIR['GEM_NEMO']['substituido_por'], 'GEM5.2_NEMO')
        with self.assertRaises(KeyError):
            ncat.sistema_por_nome('ECCC', 'GEM_NEMO')
        gem = ncat.sistema_por_nome('ECCC', 'GEM5.2_NEMO')
        self.assertNotEqual(gem.model_name, 'GEM_NEMO')
        # membros do predecessor (10) nunca herdados pelo sucessor (20).
        self.assertNotEqual(gem.hindcast_members,
                             ncat.PREDECESSORES_NAO_CONFUNDIR['GEM_NEMO']['membros_documentados_geracao_anterior'])

    def test_f_flor_nao_e_spear(self):
        self.assertIn('GFDL_FLOR', ncat.PREDECESSORES_NAO_CONFUNDIR)
        self.assertEqual(ncat.PREDECESSORES_NAO_CONFUNDIR['GFDL_FLOR']['substituido_por'], 'GFDL_SPEAR')
        with self.assertRaises(KeyError):
            ncat.sistema_por_nome('NOAA_GFDL', 'GFDL_FLOR')
        spear = ncat.sistema_por_nome('NOAA_GFDL', 'GFDL_SPEAR')
        self.assertNotEqual(spear.hindcast_members,
                             ncat.PREDECESSORES_NAO_CONFUNDIR['GFDL_FLOR']['membros_documentados_geracao_anterior'])


# ══════════════════════════════════════════════════════════════════════════
# G — membros são específicos por modelo (nunca um valor genérico).
# ══════════════════════════════════════════════════════════════════════════

class MembrosPorModeloTestCase(unittest.TestCase):

    def test_g_membros_variam_entre_modelos(self):
        membros = {s.model_name: s.hindcast_members for s in ncat.CATALOGO}
        self.assertGreater(len(set(membros.values())), 1, "membros não podem ser um valor único genérico")
        self.assertEqual(membros['GFDL_SPEAR'], 15)
        self.assertEqual(membros['GEOS5v2'], 4)
        self.assertEqual(membros['CanESM5'], 20)


# ══════════════════════════════════════════════════════════════════════════
# Seção 5 — ECMWF nunca incluído.
# ══════════════════════════════════════════════════════════════════════════

class ECMWFExcluidoTestCase(unittest.TestCase):

    def test_ecmwf_nao_esta_no_catalogo(self):
        for s in ncat.CATALOGO:
            self.assertNotIn('ECMWF', s.centre.upper())
            self.assertNotIn('ECMWF', s.model_name.upper())

    def test_ecmwf_esta_registrado_como_excluido_com_motivo(self):
        self.assertIn('ECMWF', ncat.NAO_INCLUIDOS)
        self.assertTrue(ncat.NAO_INCLUIDOS['ECMWF']['motivo'])


# ══════════════════════════════════════════════════════════════════════════
# Seção 4 — exatamente os 7 candidatos documentados, nenhum a mais/menos.
# ══════════════════════════════════════════════════════════════════════════

class SeteCandidatosTestCase(unittest.TestCase):

    def test_sete_candidatos_esperados(self):
        nomes = {(s.centre, s.model_name) for s in ncat.CATALOGO}
        self.assertEqual(len(nomes), 7)
        esperados = {
            ('NOAA_NCEP', 'CFSv2'), ('ECCC', 'CanESM5'), ('ECCC', 'GEM5.2_NEMO'),
            ('NOAA_GFDL', 'GFDL_SPEAR'), ('NCAR', 'NCAR_CCSM4'), ('NCAR', 'NCAR_CESM1'),
            ('NASA', 'GEOS5v2'),
        }
        self.assertEqual(nomes, esperados)


# ══════════════════════════════════════════════════════════════════════════
# Seção 20 — período comum só depois do catálogo, nunca antecipado.
# ══════════════════════════════════════════════════════════════════════════

class PeriodoComumTestCase(unittest.TestCase):

    def test_periodo_comum_usa_so_sistemas_confirmados(self):
        """Rodada 2 (manual NMME3 Operational User Manual, DOCUMENTED
        para os 7): agora os 7/7 candidatos têm hindcast_start/end
        DOCUMENTED e nenhum fica em incompatibilidade — diferente da
        Rodada 1, onde só 3/7 tinham evidência suficiente."""
        cp = ncat.periodo_comum_hindcast(ncat.CATALOGO)
        self.assertEqual(cp['common_start'], 1991)
        self.assertEqual(cp['common_end'], 2020)
        self.assertEqual(cp['n_elegiveis'], 7)
        self.assertEqual(cp['n_total'], 7)
        self.assertEqual(cp['incompatibilidade'], {})

    def test_periodo_comum_vazio_quando_nenhum_sistema_confirmado(self):
        sistemas = [_sistema_minimo(centre='X', model_name='Y')]
        cp = ncat.periodo_comum_hindcast(sistemas)
        self.assertIsNone(cp['common_start'])
        self.assertIsNone(cp['common_end'])

    def test_periodo_comum_ignora_sistema_com_unconfirmed_mesmo_com_valor_numerico(self):
        s = replace(_sistema_minimo(hindcast_start=1980, hindcast_end=2020, source_reference=('x',)),
                     evidence={'hindcast_start': ncat.UNCONFIRMED, 'hindcast_end': ncat.DOCUMENTED,
                               'hindcast_members': ncat.DOCUMENTED})
        cp = ncat.periodo_comum_hindcast([s])
        self.assertIsNone(cp['common_start'])
        self.assertIn('TEST/TESTMODEL', cp['incompatibilidade'])

    def test_sem_sobreposicao_real_devolve_none(self):
        s1 = _sistema_minimo(centre='A', hindcast_start=1980, hindcast_end=1990, source_reference=('x',),
                              evidence={'hindcast_start': ncat.DOCUMENTED, 'hindcast_end': ncat.DOCUMENTED,
                                        'hindcast_members': ncat.DOCUMENTED})
        s2 = _sistema_minimo(centre='B', hindcast_start=2000, hindcast_end=2010, source_reference=('y',),
                              evidence={'hindcast_start': ncat.DOCUMENTED, 'hindcast_end': ncat.DOCUMENTED,
                                        'hindcast_members': ncat.DOCUMENTED})
        cp = ncat.periodo_comum_hindcast([s1, s2])
        self.assertIsNone(cp['common_start'])
        self.assertIn('interseccao', cp['incompatibilidade'])


# ══════════════════════════════════════════════════════════════════════════
# tabela_catalogo / common_period_json — nunca acessam rede.
# ══════════════════════════════════════════════════════════════════════════

class TabelaCatalogoTestCase(unittest.TestCase):

    def test_tabela_catalogo_tem_uma_linha_por_sistema(self):
        tab = ncat.tabela_catalogo()
        self.assertEqual(len(tab), len(ncat.CATALOGO))
        for campo in ('centre', 'model_name', 'hindcast_members', 'evidence_hindcast_members',
                      'availability_status'):
            self.assertIn(campo, tab.columns)

    def test_common_period_json_serializavel(self):
        import json
        cp = ncat.common_period_json()
        json.dumps(cp, default=str)   # não deve levantar


# ══════════════════════════════════════════════════════════════════════════
# Correção de auditabilidade pré-PR — nova evidência oficial (NMME3
# manual + "About NMME" 08/jun/2025). Itens 1-7/9 do pedido de revisão.
# ══════════════════════════════════════════════════════════════════════════

class RevisaoAuditabilidadeTestCase(unittest.TestCase):

    _MEMBROS_ESPERADOS = {
        'CFSv2': 24, 'CanESM5': 20, 'GEM5.2_NEMO': 20, 'GFDL_SPEAR': 15,
        'NCAR_CCSM4': 10, 'NCAR_CESM1': 10, 'GEOS5v2': 4,
    }

    # 1 — sete candidatos com hindcast documental 1991-2020.
    def test_1_sete_candidatos_hindcast_1991_2020_documented(self):
        self.assertEqual(len(ncat.CATALOGO), 7)
        for s in ncat.CATALOGO:
            self.assertEqual(s.hindcast_start, 1991, f'{s.model_name}: hindcast_start')
            self.assertEqual(s.hindcast_end, 2020, f'{s.model_name}: hindcast_end')
            self.assertEqual(ncat.status_evidencia(s, 'hindcast_start'), ncat.DOCUMENTED)
            self.assertEqual(ncat.status_evidencia(s, 'hindcast_end'), ncat.DOCUMENTED)
            # nunca EMPIRICALLY_CONFIRMED nesta etapa — nenhum arquivo foi aberto.
            self.assertNotEqual(ncat.status_evidencia(s, 'hindcast_start'), ncat.EMPIRICALLY_CONFIRMED)

    # 2 — membros documentados por modelo.
    def test_2_membros_documentados_por_modelo(self):
        for s in ncat.CATALOGO:
            self.assertEqual(s.hindcast_members, self._MEMBROS_ESPERADOS[s.model_name],
                              f'{s.model_name}: hindcast_members')
            self.assertEqual(ncat.status_evidencia(s, 'hindcast_members'), ncat.DOCUMENTED)

    # 3 — período comum documental = 1991-2020 para 7/7.
    def test_3_periodo_comum_documental_7_de_7(self):
        cp = ncat.periodo_comum_hindcast(ncat.CATALOGO)
        self.assertEqual(cp['common_start'], 1991)
        self.assertEqual(cp['common_end'], 2020)
        self.assertEqual(cp['n_documented_models'], 7)
        self.assertEqual(cp['n_elegiveis'], 7)
        self.assertEqual(cp['n_total'], 7)
        self.assertEqual(cp['incompatibilidade'], {})

    # 4 — período empiricamente confirmado ainda UNCONFIRMED antes do POC.
    def test_4_periodo_empiricamente_confirmado_ainda_unconfirmed(self):
        cp = ncat.periodo_comum_hindcast(ncat.CATALOGO)
        self.assertEqual(cp['n_empirically_confirmed_models'], 0)
        for s in ncat.CATALOGO:
            self.assertNotEqual(ncat.status_evidencia(s, 'hindcast_start'), ncat.EMPIRICALLY_CONFIRMED)
            self.assertNotEqual(ncat.status_evidencia(s, 'hindcast_start'), ncat.DOCUMENTED_AND_CONFIRMED)

    # 5/6 — modelo sem endpoint confirmado não entra em
    # SISTEMAS_POC_EXECUTAVEIS, mas continua no catálogo científico.
    def test_5_modelo_sem_endpoint_confirmado_fora_da_lista_executavel(self):
        executaveis = {f'{s.centre}/{s.model_name}' for s in ncat.sistemas_poc_executaveis()}
        self.assertEqual(executaveis, set())   # nenhum CONFIRMED nesta rodada — resultado honesto

    def test_6_catalogo_cientifico_nao_perde_modelo_por_falta_de_acesso(self):
        nomes_catalogo = {(s.centre, s.model_name) for s in ncat.CATALOGO}
        nomes_nao_executaveis = {(s.centre, s.model_name) for s in ncat.sistemas_poc_nao_executaveis()}
        self.assertEqual(nomes_nao_executaveis, nomes_catalogo)   # os 7 continuam no catálogo
        self.assertEqual(len(ncat.CATALOGO), 7)   # nada foi removido

    # 7 — nenhum URL é inventado por analogia (CONFIRMED exige url+variável).
    def test_7_confirmed_exige_url_e_variavel_ao_mesmo_tempo(self):
        s = _sistema_minimo(data_access_status=ncat.DATA_ACCESS_CONFIRMED, data_url_template=None,
                             precip_variable=None)
        with self.assertRaises(ValueError) as e:
            ncat._validar_catalogo([s])
        self.assertIn('CONFIRMED', str(e.exception))

    def test_7_nenhum_data_url_template_no_catalogo_real_e_extrapolado_sem_marca(self):
        """Todo data_url_template presente no catálogo real vem
        acompanhado de data_access_status != CONFIRMED quando a
        variável de precipitação não foi confirmada nesse path — nunca
        promovido a executável por analogia."""
        for s in ncat.CATALOGO:
            if s.data_url_template is not None and s.precip_variable is None:
                self.assertNotEqual(s.data_access_status, ncat.DATA_ACCESS_CONFIRMED)

    # 9 — NASA GEOS5v2 não é automaticamente igual a GEOS-S2S-2.
    def test_9_geos5v2_nao_e_automaticamente_geos_s2s_2(self):
        geos = ncat.sistema_por_nome('NASA', 'GEOS5v2')
        self.assertEqual(geos.model_name, 'GEOS5v2')
        self.assertNotEqual(geos.model_name, 'GEOS-S2S-2')
        # o nome operacional atual pode CITAR GEOS-S2S-2, mas isso não é
        # tratado como confirmação de equivalência (fica registrado em notes).
        self.assertIn('GEOS-S2S-2', geos.current_operational_name or '')
        self.assertIn('NÃO confirmado', geos.current_operational_name or '')
        self.assertEqual(ncat.status_evidencia(geos, 'model_version'), ncat.UNCONFIRMED)

    def test_current_operational_name_registrado_separado_do_hindcast_system_name(self):
        """Seção 3 — hindcast_system_name (model_name) e
        current_operational_name são conceitos distintos; GFDL_SPEAR é
        um caso onde eles divergem (SPEAR não aparece no rol "core"
        operacional atual, mas continua candidato histórico válido)."""
        spear = ncat.sistema_por_nome('NOAA_GFDL', 'GFDL_SPEAR')
        self.assertEqual(spear.model_name, 'GFDL_SPEAR')
        self.assertIsNone(spear.current_operational_name)
        self.assertEqual(spear.availability_status, ncat.STATUS_CANDIDATO)   # continua candidato


if __name__ == '__main__':
    unittest.main()
