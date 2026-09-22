#!/usr/bin/env python3
"""
tests/test_nmme_cpc_cpt.py — regressão de scripts/nmme_cpc_cpt.py, o
parser do formato CPT v10 (rota oficial NOAA/CPC de hindcast mensal
NMME) e utilitários de nome de arquivo/inspeção leve (Fase 2C.1,
correção "CFSv2 executável"). Tudo offline — nenhum teste acessa rede
real; os textos CPT usados são sintéticos, exceto um excerto literal de
uma fixture REAL do pacote oficial `iri-pycpt/pycpt` (lida de primeira
mão via raw.githubusercontent.com nesta sessão — ver o docstring de
scripts/nmme_cpc_cpt.py para a proveniência completa).

Roda com:
    python -m unittest tests.test_nmme_cpc_cpt -v
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import nmme_cpc_cpt as cpt  # noqa: E402
from _c3s_utils import MUNICIPIOS  # noqa: E402

SAO_BENTO_LAT = MUNICIPIOS['Sao_Bento_do_Tocantins']['lat']
SAO_BENTO_LON = MUNICIPIOS['Sao_Bento_do_Tocantins']['lon']


def _texto_cpt_minimo(nrow=3, ncol=3, lons=(-48.5, -47.9, -47.2), lats=(-5.5, -6.0, -6.5),
                       valores=((100.0, 120.0, 110.0), (95.0, 130.0, 105.0), (90.0, 115.0, 99.0)),
                       units='mm/day', missing='-999', extra_attrs='', S='1991-01-01T00:00'):
    header = f'cpt:field=prec, cpt:S={S}, cpt:nrow={nrow}, cpt:ncol={ncol}, cpt:row=Y, cpt:col=X'
    if units is not None:
        header += f', cpt:units={units}'
    if missing is not None:
        header += f', cpt:missing={missing}'
    header += extra_attrs
    linhas = [
        'xmlns:cpt=http://iri.columbia.edu/CPT/v10/',
        'cpt:nfields=1',
        header,
        '\t' + '\t'.join(str(x) for x in lons),
    ]
    for lat, vals in zip(lats, valores):
        linhas.append(f'{lat}\t' + '\t'.join(str(v) for v in vals))
    return '\n'.join(linhas) + '\n'


# Excerto LITERAL de cpt-io/tests/data/SEASONAL_CANCM4I_PRCP_HCST_JUN-SEP_
# None_2021-05.tsv (github.com/iri-pycpt/pycpt) — fixture pública do
# projeto IRI-PyCPT, lida de primeira mão via raw.githubusercontent.com
# nesta sessão (não é um hindcast baixado por este projeto). Modelo
# CanCM4i, produto SAZONAL (não CFSv2/MENSAL) — usado aqui só para provar
# que o parser lê um arquivo CPT v10 REAL, não só sintético.
_EXCERTO_REAL_CANCM4I = (
    "xmlns:cpt=http://iri.columbia.edu/CPT/v10/\n"
    "xmlns:cf=http://cf-pcmdi.llnl.gov/documents/cf-conventions/1.4/\n"
    "cpt:nfields=1\n"
    "cpt:field=prec, cpt:L=3.0 months, cpt:S=1980-05-01T00:00, cpt:nrow=3, cpt:ncol=3, cpt:row=Y, "
    "cpt:col=X, cpt:units=mm/day, cf:standard_name=lwe_pecipitation_rate, cpt:missing=-999, "
    "cpt:T=1980-06/09\n"
    "\t68.0\t69.0\t70.0\n"
    "37.0\t  19.4015    \t  27.8848    \t  36.3680    \n"
    "36.0\t  41.4865    \t  55.3207    \t  69.1451    \n"
    "35.0\t  63.5670    \t  82.7447    \t  101.960    \n"
)


class ParseCabecalhoValidoTestCase(unittest.TestCase):
    """A — o parser lê corretamente um cabeçalho CPT v10 bem-formado."""

    def test_a_bloco_minimo_sintetico(self):
        blocos = cpt.parse_cpt_text(_texto_cpt_minimo())
        self.assertEqual(len(blocos), 1)
        self.assertEqual(blocos[0].attrs['field'], 'prec')
        self.assertEqual(blocos[0].attrs['units'], 'mm/day')
        self.assertEqual(blocos[0].col_labels, [-48.5, -47.9, -47.2])
        self.assertEqual(len(blocos[0].linhas), 3)

    def test_a_excerto_real_cancm4i_do_pycpt(self):
        """Prova que o parser lê um arquivo CPT v10 REAL (não só
        sintético) — fixture pública do iri-pycpt/pycpt."""
        blocos = cpt.parse_cpt_text(_EXCERTO_REAL_CANCM4I)
        self.assertEqual(len(blocos), 1)
        b = blocos[0]
        self.assertEqual(b.attrs['field'], 'prec')
        self.assertEqual(b.attrs['units'], 'mm/day')
        self.assertEqual(b.attrs['S'], '1980-05-01T00:00')
        self.assertEqual(b.attrs['L'], '3.0 months')
        self.assertNotIn('M', b.attrs)   # sem dimensão de membro — ver classe L abaixo
        self.assertAlmostEqual(b.linhas[0][1][0], 19.4015)


class ArquivoMalformadoTestCase(unittest.TestCase):
    """B — cabeçalho/arquivo malformado reprova explicitamente."""

    def test_b_sem_xmlns_reprova(self):
        texto = _texto_cpt_minimo().replace('xmlns:cpt=http://iri.columbia.edu/CPT/v10/\n', '')
        with self.assertRaises(ValueError):
            cpt.parse_cpt_text(texto)

    def test_b_sem_nrow_reprova(self):
        texto = _texto_cpt_minimo().replace(', cpt:nrow=3', '')
        with self.assertRaises(ValueError):
            cpt.parse_cpt_text(texto)

    def test_b_nrow_maior_que_linhas_disponiveis_reprova(self):
        texto = _texto_cpt_minimo(nrow=10)
        with self.assertRaises(ValueError):
            cpt.parse_cpt_text(texto)

    def test_b_ncol_diferente_dos_rotulos_reprova(self):
        texto = _texto_cpt_minimo().replace(', cpt:ncol=3', ', cpt:ncol=5')
        with self.assertRaises(ValueError):
            cpt.parse_cpt_text(texto)

    def test_b_arquivo_vazio_reprova(self):
        with self.assertRaises(ValueError):
            cpt.parse_cpt_text('xmlns:cpt=http://iri.columbia.edu/CPT/v10/\n')

    def test_b_nome_arquivo_fora_do_padrao_reprova(self):
        with self.assertRaises(ValueError):
            cpt.parse_nome_arquivo_mensal('arquivo_qualquer.txt')

    def test_b_nome_sazonal_nunca_tratado_como_mensal(self):
        with self.assertRaisesRegex(ValueError, 'SAZONAL'):
            cpt.parse_nome_arquivo_mensal('cfsv2_precip_hcst_Decic_6-8_1992-2021.txt')


class CoordenadasSaoBentoTestCase(unittest.TestCase):
    """C — coordenadas de São Bento do Tocantins selecionadas
    corretamente (mesmo ponto das Fases C3S, nunca outro)."""

    def test_c_seleciona_celula_mais_proxima_de_sao_bento(self):
        texto = _texto_cpt_minimo(
            lons=(-48.5, -47.9, -47.2), lats=(-5.5, -6.0, -6.5),
            valores=((100.0, 120.0, 110.0), (95.0, 130.0, 105.0), (90.0, 115.0, 99.0)))
        blocos = cpt.parse_cpt_text(texto)
        ponto = cpt.selecionar_ponto_mais_proximo(blocos[0], SAO_BENTO_LAT, SAO_BENTO_LON)
        self.assertEqual(ponto['selected_lat'], -6.0)
        self.assertEqual(ponto['selected_lon'], -47.9)
        self.assertEqual(ponto['valor'], 130.0)
        self.assertLess(ponto['grid_distance_km'], 50)


class LongitudeConvencaoTestCase(unittest.TestCase):
    """D — convenção de longitude (0-360 vs. -180/180) tratada
    explicitamente, nunca assumida."""

    def test_d_detecta_convencao_180(self):
        self.assertEqual(cpt.detectar_convencao_longitude([-48.5, -47.9, -47.2]), '-180-180')

    def test_d_detecta_convencao_0_360(self):
        self.assertEqual(cpt.detectar_convencao_longitude([310.0, 312.0, 314.0]), '0-360')

    def test_d_seleciona_corretamente_em_grade_0_360(self):
        # São Bento (-47.90°) em convenção 0-360 é 312.10°.
        texto = _texto_cpt_minimo(lons=(311.0, 312.0, 313.0), lats=(-5.5, -6.0, -6.5),
                                    valores=((10.0, 20.0, 30.0), (11.0, 21.0, 31.0), (12.0, 22.0, 32.0)))
        blocos = cpt.parse_cpt_text(texto)
        ponto = cpt.selecionar_ponto_mais_proximo(blocos[0], SAO_BENTO_LAT, SAO_BENTO_LON)
        self.assertEqual(ponto['longitude_convention_detected'], '0-360')
        self.assertEqual(ponto['selected_lon'], 312.0)
        self.assertEqual(ponto['valor'], 21.0)

    def test_d_normalizar_longitude_ida_e_volta(self):
        self.assertAlmostEqual(cpt.normalizar_longitude_para(-47.9, '0-360'), 312.1)
        self.assertAlmostEqual(cpt.normalizar_longitude_para(312.1, '-180-180'), -47.9)


class UnidadeObrigatoriaTestCase(unittest.TestCase):
    """E — cpt:units é obrigatório; nunca assumido."""

    def test_e_bloco_sem_units_reprova(self):
        texto = _texto_cpt_minimo(units=None)
        with self.assertRaisesRegex(ValueError, 'units'):
            cpt.parse_cpt_text(texto)


class MembroObrigatorioTestCase(unittest.TestCase):
    """F — membro obrigatório quando o objetivo é POC por-membro; nunca
    trata ensemble mean como se fosse por-membro."""

    def test_f_exigir_membro_falha_sem_dimensao_m(self):
        blocos = cpt.parse_cpt_text(_texto_cpt_minimo())
        with self.assertRaises(RuntimeError):
            cpt.exigir_dados_por_membro(blocos, contexto='teste')

    def test_f_exigir_membro_passa_com_dimensao_m(self):
        texto1 = _texto_cpt_minimo(extra_attrs=', cpt:M=1')
        texto2 = _texto_cpt_minimo(extra_attrs=', cpt:M=2')
        blocos = cpt.parse_cpt_text(texto1) + cpt.parse_cpt_text(texto2)
        self.assertTrue(cpt.exigir_dados_por_membro(blocos))


class ContagemMembrosTestCase(unittest.TestCase):
    """G — contagem de membros validada contra o documentado no
    catálogo (ex.: 24 para CFSv2); nunca aceita silenciosamente uma
    contagem diferente."""

    def test_g_contagem_bate_com_documentado(self):
        blocos = []
        for m in range(1, 25):
            blocos += cpt.parse_cpt_text(_texto_cpt_minimo(extra_attrs=f', cpt:M={m}'))
        self.assertEqual(cpt.validar_contagem_membros(blocos, 24), 24)

    def test_g_contagem_diferente_do_documentado_reprova(self):
        blocos = []
        for m in range(1, 11):
            blocos += cpt.parse_cpt_text(_texto_cpt_minimo(extra_attrs=f', cpt:M={m}'))
        with self.assertRaises(RuntimeError):
            cpt.validar_contagem_membros(blocos, 24)

    def test_g_sem_dimensao_m_reprova_contagem(self):
        blocos = cpt.parse_cpt_text(_texto_cpt_minimo())
        with self.assertRaises(RuntimeError):
            cpt.validar_contagem_membros(blocos, 24)


class LeadsSemDuplicataTestCase(unittest.TestCase):
    """H — H1-H6 mapeados para meses-alvo distintos, sem duplicata."""

    def test_h_seis_leads_mapeiam_para_seis_meses_distintos(self):
        import pandas as pd
        sys.path.insert(0, str(ROOT / 'scripts'))
        import nmme_processar as nproc
        init = pd.Period('1991-01', 'M')
        alvos = [str(nproc.leadtime_para_mes_alvo_nmme(init, lead)) for lead in range(1, 7)]
        self.assertEqual(len(alvos), len(set(alvos)))
        self.assertEqual(alvos[0], '1991-01')
        self.assertEqual(alvos[-1], '1991-06')

    def test_h_nomes_de_arquivo_mensais_leads_2_a_7_distintos(self):
        nomes = [f'cfsv2_precip_hcst_Janic_{n}_1991.txt' for n in range(2, 8)]
        numeros = [cpt.parse_nome_arquivo_mensal(n)['numero_apos_ic'] for n in nomes]
        self.assertEqual(len(numeros), len(set(numeros)))


class TargetMonthContraHeaderTestCase(unittest.TestCase):
    """I — target month nunca inferido só pelo nome do arquivo se o
    cabeçalho (cpt:S) contradisser."""

    def test_i_header_consistente_com_nome_do_arquivo(self):
        blocos = cpt.parse_cpt_text(_texto_cpt_minimo(S='1991-01-01T00:00'))
        r = cpt.validar_target_month_contra_header(blocos[0], 1991, 1, numero_apos_ic=1)
        self.assertTrue(r['cruzado_com_header'])
        self.assertEqual(r['target_month_hipotese'], '1991-01')

    def test_i_header_contradiz_nome_do_arquivo_reprova(self):
        blocos = cpt.parse_cpt_text(_texto_cpt_minimo(S='1991-03-01T00:00'))
        with self.assertRaises(ValueError):
            cpt.validar_target_month_contra_header(blocos[0], 1991, 1, numero_apos_ic=1)

    def test_i_sem_cpt_s_fica_nao_cruzado_nao_confirmado(self):
        texto = _texto_cpt_minimo().replace(', cpt:S=1991-01-01T00:00', '')
        blocos = cpt.parse_cpt_text(texto)
        r = cpt.validar_target_month_contra_header(blocos[0], 1991, 1, numero_apos_ic=1)
        self.assertFalse(r['cruzado_com_header'])

    def test_i_hipotese_numero_apos_ic_marcada_unconfirmed(self):
        h = cpt.hipotese_interpretacao_numero_apos_ic()
        self.assertEqual(h['status_evidencia'], 'UNCONFIRMED')


class NanInfReprovaTestCase(unittest.TestCase):
    """J — NaN/inf reprova."""

    def test_j_nan_reprova(self):
        with self.assertRaises(RuntimeError):
            cpt.validar_valor_extraido(float('nan'))

    def test_j_inf_reprova(self):
        with self.assertRaises(RuntimeError):
            cpt.validar_valor_extraido(float('inf'))

    def test_j_valor_valido_passa(self):
        self.assertTrue(cpt.validar_valor_extraido(150.0))


class PrecipitacaoNegativaTestCase(unittest.TestCase):
    """K — precipitação negativa reprova."""

    def test_k_negativo_reprova(self):
        with self.assertRaises(RuntimeError):
            cpt.validar_valor_extraido(-5.0)

    def test_k_fora_da_faixa_plausivel_reprova(self):
        with self.assertRaises(RuntimeError):
            cpt.validar_valor_extraido(5000.0)


class EnsembleMeanVsMembroTestCase(unittest.TestCase):
    """L — arquivo de ensemble mean nunca confundido com ensemble por
    membros."""

    def test_l_sem_m_e_ensemble_mean_only(self):
        blocos = cpt.parse_cpt_text(_texto_cpt_minimo())
        self.assertEqual(cpt.avaliar_adequacao_membro(blocos), cpt.ENSEMBLE_MEAN_ONLY)

    def test_l_com_m_em_todos_os_blocos_e_member_level(self):
        blocos = cpt.parse_cpt_text(_texto_cpt_minimo(extra_attrs=', cpt:M=1')) + \
            cpt.parse_cpt_text(_texto_cpt_minimo(extra_attrs=', cpt:M=2'))
        self.assertEqual(cpt.avaliar_adequacao_membro(blocos), cpt.MEMBER_LEVEL_DATA_PRESENT)

    def test_l_mistura_inconsistente_e_indeterminado(self):
        blocos = cpt.parse_cpt_text(_texto_cpt_minimo(extra_attrs=', cpt:M=1')) + \
            cpt.parse_cpt_text(_texto_cpt_minimo())
        self.assertEqual(cpt.avaliar_adequacao_membro(blocos), cpt.MEMBER_STATUS_INDETERMINADO)

    def test_l_fixture_real_cancm4i_e_ensemble_mean_only(self):
        """A única fixture REAL de hindcast NMME em CPT v10 lida nesta
        sessão não tem dimensão de membro — evidência real, não
        hipotética, do risco discutido em nmme_catalogo.py (Rodada 3)."""
        blocos = cpt.parse_cpt_text(_EXCERTO_REAL_CANCM4I)
        self.assertEqual(cpt.avaliar_adequacao_membro(blocos), cpt.ENSEMBLE_MEAN_ONLY)
        with self.assertRaises(RuntimeError):
            cpt.exigir_dados_por_membro(blocos, contexto='fixture real CanCM4i')


class NomeArquivoMensalTestCase(unittest.TestCase):

    def test_parse_nome_mensal_cfsv2(self):
        r = cpt.parse_nome_arquivo_mensal('cfsv2_precip_hcst_Janic_2_1991.txt')
        self.assertEqual(r['model'], 'cfsv2')
        self.assertEqual(r['variavel_token'], 'precip')
        self.assertEqual(r['init_month_abbr'], 'Jan')
        self.assertEqual(r['init_month'], 1)
        self.assertEqual(r['numero_apos_ic'], 2)
        self.assertEqual(r['ano_arquivo'], 1991)

    def test_parse_nome_mensal_nmme_ensemble(self):
        r = cpt.parse_nome_arquivo_mensal('nmme_precip_hcst_Julic_1_1992.txt')
        self.assertEqual(r['model'], 'nmme')
        self.assertEqual(r['init_month_abbr'], 'Jul')
        self.assertEqual(r['numero_apos_ic'], 1)
        self.assertEqual(r['ano_arquivo'], 1992)

    def test_mes_abreviado_invalido_reprova(self):
        with self.assertRaises(ValueError):
            cpt.parse_nome_arquivo_mensal('cfsv2_precip_hcst_Xyzic_2_1991.txt')


class EstrategiaInspecaoLeveTestCase(unittest.TestCase):
    """Seção 4 — estratégia de inspeção leve documentada, nunca executa
    rede (nenhum import de requests/urllib neste módulo)."""

    def test_estrategia_nao_faz_rede(self):
        import inspect
        src = inspect.getsource(cpt)
        self.assertNotIn('import requests', src)
        self.assertNotIn('urllib', src)

    def test_estrategia_documenta_range_e_fallback(self):
        r = cpt.estrategia_inspecao_leve('https://ftp.cpc.ncep.noaa.gov/International/nmme/'
                                          'monthly_nmme_hindcast_in_cpt_format/'
                                          'cfsv2_precip_hcst_Janic_2_1991.txt')
        self.assertIn('Range', r['metodo_preferido'])
        self.assertIn('EGRESS_BLOCKED', r['tentativa_real_nesta_sessao'])


if __name__ == '__main__':
    unittest.main()
