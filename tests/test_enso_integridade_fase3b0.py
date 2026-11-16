#!/usr/bin/env python3
"""
tests/test_enso_integridade_fase3b0.py — Fase ENSO-INTEGRIDADE 3B.0/3B.0.2.

Cobre scripts/validar_correcao_historica_tsa.py (Controle A: exceção
estrita de continuidade temporal da CI para a correção histórica de
TSA) e scripts/decidir_continuidade_serie_subst.sh (o ramo real de
ci.yml que o chama) com fixtures sintéticas — nunca toca git real nem
os dados reais do repositório (os testes que precisam de git usam um
repositório TEMPORÁRIO, descartado ao final).

Fase 3B.0 (itens 1-10 originais) + Fase 3B.0.2 (fecha 3 lacunas:
proveniência agora é EXIGIDA, não só validada quando existe; os 3
arquivos — não só serie_subst.csv — decidem a classificação; e um
resultado inválido é distinguido de uma mudança não relacionada à
TSA, nunca confundidos).

Roda com:
    python -m unittest tests.test_enso_integridade_fase3b0 -v
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import corrigir_indices_historicos as cih  # noqa: E402
import proveniencia_indices as prov        # noqa: E402
import validar_correcao_historica_tsa as v  # noqa: E402

DECISOR_SH = ROOT / 'scripts' / 'decidir_continuidade_serie_subst.sh'


# ══════════════════════════════════════════════════════════════════
# Fixtures sintéticas — colunas reais dos 2 CSVs (ver cabeçalho real
# de data/master_monthly.csv e data/serie_subst.csv), nunca os dados
# reais do repositório.
# ══════════════════════════════════════════════════════════════════
_MASTER_COLS = ['year', 'month', 'Araguaina', 'Colinas', 'Tocantinopolis', 'prec_reg',
                'date', 'nino34', 'soi', 'oni', 'clim', 'clim_sd', 'anom', 'sanom', 'tsa', 'pdo']
_SUBST_COLS = ['ano', 'mes', 'prec', 'nino34', 'tsa', 'pdo', 'date', 'fonte']

_MASTER_BASE_LINHAS = [
    {'year': 2026, 'month': 5, 'Araguaina': 50.0, 'Colinas': 48.0, 'Tocantinopolis': 52.0,
     'prec_reg': 50.0, 'date': '2026-05-01', 'nino34': 0.9, 'soi': 0.0, 'oni': 0.8, 'clim': 83.1,
     'clim_sd': 10.0, 'anom': -33.1, 'sanom': -3.31, 'tsa': 0.05, 'pdo': 0.40},
    {'year': 2026, 'month': 6, 'Araguaina': 15.0, 'Colinas': 16.0, 'Tocantinopolis': 14.0,
     'prec_reg': 15.0, 'date': '2026-06-01', 'nino34': 1.0, 'soi': 0.0, 'oni': 0.9, 'clim': 15.6,
     'clim_sd': 5.0, 'anom': -0.6, 'sanom': -0.12, 'tsa': 0.10, 'pdo': 0.50},
    {'year': 2026, 'month': 7, 'Araguaina': 6.0, 'Colinas': 7.0, 'Tocantinopolis': 6.0,
     'prec_reg': 6.4, 'date': '2026-07-01', 'nino34': 1.1, 'soi': 0.0, 'oni': 1.0, 'clim': 6.4,
     'clim_sd': 3.0, 'anom': 0.0, 'sanom': 0.0, 'tsa': 0.20, 'pdo': 0.55},
    {'year': 2026, 'month': 8, 'Araguaina': 10.0, 'Colinas': 11.0, 'Tocantinopolis': 10.0,
     'prec_reg': 10.4, 'date': '2026-08-01', 'nino34': 1.2, 'soi': 0.0, 'oni': 1.1, 'clim': 10.4,
     'clim_sd': 4.0, 'anom': 0.0, 'sanom': 0.0, 'tsa': 0.20, 'pdo': 0.60},
    {'year': 2026, 'month': 9, 'Araguaina': 41.0, 'Colinas': 42.0, 'Tocantinopolis': 42.0,
     'prec_reg': 41.7, 'date': '2026-09-01', 'nino34': 1.3, 'soi': 0.0, 'oni': 1.2, 'clim': 41.7,
     'clim_sd': 8.0, 'anom': 0.0, 'sanom': 0.0, 'tsa': 0.12, 'pdo': 0.65},
    {'year': 2026, 'month': 10, 'Araguaina': 119.0, 'Colinas': 120.0, 'Tocantinopolis': 120.0,
     'prec_reg': 119.7, 'date': '2026-10-01', 'nino34': 1.4, 'soi': 0.0, 'oni': 1.3, 'clim': 119.7,
     'clim_sd': 9.0, 'anom': 0.0, 'sanom': 0.0, 'tsa': 0.12, 'pdo': 0.65},
]

_SUBST_BASE_LINHAS = [
    {'ano': 2026, 'mes': 6, 'prec': 15.0, 'nino34': 1.0, 'tsa': 0.10, 'pdo': 0.50,
     'date': '2026-06-01', 'fonte': 'CHIRPS'},
    {'ano': 2026, 'mes': 7, 'prec': 6.4, 'nino34': 1.1, 'tsa': 0.20, 'pdo': 0.55,
     'date': '2026-07-01', 'fonte': 'CHIRPS'},
    {'ano': 2026, 'mes': 8, 'prec': 10.4, 'nino34': 1.2, 'tsa': 0.20, 'pdo': 0.60,
     'date': '2026-08-01', 'fonte': 'CHIRPS'},
    {'ano': 2026, 'mes': 9, 'prec': 41.7, 'nino34': 1.3, 'tsa': 0.12, 'pdo': 0.65,
     'date': '2026-09-01', 'fonte': 'CHIRPS'},
]


def _csv(cols, linhas):
    linhas_txt = [','.join(cols)]
    for linha in linhas:
        linhas_txt.append(','.join(str(linha[c]) for c in cols))
    return '\n'.join(linhas_txt) + '\n'


def _master_texto(mudancas=None):
    """mudancas: {mes: {coluna: valor}}"""
    linhas = [dict(l) for l in _MASTER_BASE_LINHAS]
    for linha in linhas:
        m = (mudancas or {}).get(linha['month'])
        if m:
            linha.update(m)
    return _csv(_MASTER_COLS, linhas)


def _subst_texto(mudancas=None, linhas_extra=None, remover_mes=None, duplicar_mes=None):
    linhas = [dict(l) for l in _SUBST_BASE_LINHAS if l['mes'] != remover_mes]
    for linha in linhas:
        m = (mudancas or {}).get(linha['mes'])
        if m:
            linha.update(m)
    if linhas_extra:
        linhas += linhas_extra
    if duplicar_mes is not None:
        alvo = next(dict(l) for l in linhas if l['mes'] == duplicar_mes)
        linhas.append(alvo)
    return _csv(_SUBST_COLS, linhas)


_MASTER_BASE_TXT = _master_texto()
_SUBST_BASE_TXT = _subst_texto()

# Células reais do plano fechado — nunca uma cópia divergente de seus
# campos, sempre lidas de cih.PLANO_BASE/CELULA_OUTUBRO_CONDICIONAL.
_CEL_MASTER_JUL = next(c for c in cih.PLANO_BASE if c['arquivo'] == 'master_monthly.csv' and c['mes'] == 7)
_CEL_MASTER_AGO = next(c for c in cih.PLANO_BASE if c['arquivo'] == 'master_monthly.csv' and c['mes'] == 8)
_CEL_MASTER_SET = next(c for c in cih.PLANO_BASE if c['arquivo'] == 'master_monthly.csv' and c['mes'] == 9)
_CEL_SUBST_JUL = next(c for c in cih.PLANO_BASE if c['arquivo'] == 'serie_subst.csv' and c['mes'] == 7)
_CEL_SUBST_AGO = next(c for c in cih.PLANO_BASE if c['arquivo'] == 'serie_subst.csv' and c['mes'] == 8)
_CEL_OUTUBRO = cih.CELULA_OUTUBRO_CONDICIONAL


def _provenencia_correta_para(celulas, overrides=None):
    """Monta o texto de proveniência com um registro EXATO (valor/
    classificacao/meses_base/fonte/metodo/verificado_em) para cada
    célula do plano informada, usando os PRÓPRIOS campos do plano como
    fonte única. `overrides`: {(arquivo,ano,mes): {campo: valor}} —
    para os testes negativos que precisam corromper um campo só."""
    overrides = overrides or {}
    linhas = []
    for cel in celulas:
        linha = {
            'arquivo': cel['arquivo'], 'ano': cel['ano'], 'mes': cel['mes'], 'indice': 'tsa',
            'valor': cel['valor_novo'], 'classificacao': cel['classificacao'],
            'meses_base': v._meses_base_str(cel['meses_base']), 'fonte': cel['fonte'],
            'metodo': cel['metodo'], 'verificado_em': '2026-11-16T12:00:00+00:00',
        }
        linha.update(overrides.get((cel['arquivo'], cel['ano'], cel['mes']), {}))
        linhas.append(linha)
    return prov.renderizar_texto(linhas)


_CORRECAO_COMPLETA_MASTER = _master_texto({7: {'tsa': 0.12}, 8: {'tsa': 0.42}, 9: {'tsa': 0.57}})
_CORRECAO_COMPLETA_SUBST = _subst_texto({7: {'tsa': 0.12}, 8: {'tsa': 0.42}})
_CELULAS_CORRECAO_COMPLETA = [_CEL_MASTER_JUL, _CEL_MASTER_AGO, _CEL_MASTER_SET,
                               _CEL_SUBST_JUL, _CEL_SUBST_AGO]
_PROV_CORRECAO_COMPLETA = _provenencia_correta_para(_CELULAS_CORRECAO_COMPLETA)


class ValidarCorrecaoHistoricaTsaTestCase(unittest.TestCase):
    """Itens 1-10 da Fase 3B.0 original (comportamento preservado)."""

    def test_1_duas_celulas_tsa_autorizadas_aprovado(self):
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _CORRECAO_COMPLETA_MASTER,
                                            _SUBST_BASE_TXT, _CORRECAO_COMPLETA_SUBST,
                                            None, _PROV_CORRECAO_COMPLETA)
        self.assertTrue(autorizado, rel['violacoes'])
        self.assertEqual(rel['classificacao'], v.AUTORIZADO)

    def test_2_tsa_em_outro_mes_e_reprovada(self):
        subst_head = _subst_texto({6: {'tsa': 0.99}})
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _MASTER_BASE_TXT,
                                            _SUBST_BASE_TXT, subst_head, None, None)
        self.assertFalse(autorizado)

    def test_3_alteracao_de_precipitacao_e_reprovada(self):
        subst_head = _subst_texto({7: {'tsa': 0.12, 'prec': 999.0}})
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _MASTER_BASE_TXT,
                                            _SUBST_BASE_TXT, subst_head, None, None)
        self.assertFalse(autorizado)
        self.assertEqual(rel['classificacao'], v.TENTATIVA_INVALIDA)

    def test_4_alteracao_de_nino34_ou_pdo_e_reprovada(self):
        subst_head = _subst_texto({8: {'tsa': 0.42, 'pdo': 9.99}})
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _MASTER_BASE_TXT,
                                            _SUBST_BASE_TXT, subst_head, None, None)
        self.assertFalse(autorizado)

        master_head = _master_texto({7: {'nino34': 9.99}})
        autorizado2, rel2 = v.validar_textos(_MASTER_BASE_TXT, master_head,
                                              _SUBST_BASE_TXT, _SUBST_BASE_TXT, None, None)
        self.assertFalse(autorizado2)

    def test_5_inclusao_de_mes_e_reprovada(self):
        extra = [{'ano': 2026, 'mes': 11, 'prec': 0.0, 'nino34': 1.5, 'tsa': 0.6,
                  'pdo': 0.7, 'date': '2026-11-01', 'fonte': 'CHIRPS'}]
        subst_head = _subst_texto({7: {'tsa': 0.12}, 8: {'tsa': 0.42}}, linhas_extra=extra)
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _MASTER_BASE_TXT,
                                            _SUBST_BASE_TXT, subst_head, None, None)
        self.assertFalse(autorizado)

    def test_5_exclusao_de_mes_e_reprovada(self):
        subst_head = _subst_texto({7: {'tsa': 0.12}, 8: {'tsa': 0.42}}, remover_mes=6)
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _MASTER_BASE_TXT,
                                            _SUBST_BASE_TXT, subst_head, None, None)
        self.assertFalse(autorizado)

    def test_6_duplicacao_de_mes_e_reprovada(self):
        subst_head = _subst_texto({7: {'tsa': 0.12}, 8: {'tsa': 0.42}}, duplicar_mes=7)
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _MASTER_BASE_TXT,
                                            _SUBST_BASE_TXT, subst_head, None, None)
        self.assertFalse(autorizado)

    def test_7_mudanca_de_fonte_ou_data_e_reprovada(self):
        subst_head = _subst_texto({7: {'tsa': 0.12, 'fonte': 'CHC-Preliminar'}})
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _MASTER_BASE_TXT,
                                            _SUBST_BASE_TXT, subst_head, None, None)
        self.assertFalse(autorizado)

        subst_head2 = _subst_texto({8: {'tsa': 0.42, 'date': '2026-08-15'}})
        autorizado2, _ = v.validar_textos(_MASTER_BASE_TXT, _MASTER_BASE_TXT,
                                           _SUBST_BASE_TXT, subst_head2, None, None)
        self.assertFalse(autorizado2)

    def test_8_modificacao_indevida_de_master_monthly_e_reprovada(self):
        """Célula de TSA fora do plano fechado (maio/2026, não previsto
        em PLANO_BASE/CELULA_OUTUBRO_CONDICIONAL) reprova, mesmo que
        serie_subst.csv não tenha sido tocado. Fase 3B.0.2: esta é
        também o item 10 da nova seção de testes — "alteração somente
        no master, fora do plano TSA" NUNCA concede a exceção, mas
        também não é tratada como "tentativa de TSA reprovada" (o
        plano nem foi tocado por chave) — classificação NAO_SE_APLICA."""
        master_head = _master_texto({5: {'tsa': 0.99}})
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, master_head,
                                            _SUBST_BASE_TXT, _SUBST_BASE_TXT, None, None)
        self.assertFalse(autorizado)
        self.assertEqual(rel['classificacao'], v.NAO_SE_APLICA)

    def test_9_provenencia_inconsistente_e_reprovada(self):
        """Linha de proveniência para a célula autorizada de julho,
        mas com classificação diferente da exigida pelo plano
        ('observado') — reprova, mesmo com os CSVs de dado corretos."""
        prov_head = prov.renderizar_texto([
            {'arquivo': 'master_monthly.csv', 'ano': 2026, 'mes': 7, 'indice': 'tsa',
             'valor': 0.12, 'classificacao': 'persistido',  # deveria ser 'observado'
             'meses_base': '2026-07', 'fonte': 'PSL tsa.data (verificado ao vivo)',
             'metodo': 'observacao_direta', 'verificado_em': '2026-11-13T00:00:00+00:00'},
        ])
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _CORRECAO_COMPLETA_MASTER,
                                            _SUBST_BASE_TXT, _CORRECAO_COMPLETA_SUBST,
                                            None, prov_head)
        self.assertFalse(autorizado, rel)

    def test_9b_provenencia_linha_fora_do_plano_e_reprovada(self):
        """Linha órfã (mês fora do plano) numa proveniência que também
        contém o resto da correção completa e correta — a correção em
        si está certa, mas a linha extra reprova tudo."""
        linhas = [
            {'arquivo': 'master_monthly.csv', 'ano': 2026, 'mes': c['mes'], 'indice': 'tsa',
             'valor': c['valor_novo'], 'classificacao': c['classificacao'],
             'meses_base': v._meses_base_str(c['meses_base']), 'fonte': c['fonte'],
             'metodo': c['metodo'], 'verificado_em': '2026-11-16T12:00:00+00:00'}
            for c in (_CEL_MASTER_JUL, _CEL_MASTER_AGO, _CEL_MASTER_SET)
        ] + [
            {'arquivo': 'serie_subst.csv', 'ano': 2026, 'mes': c['mes'], 'indice': 'tsa',
             'valor': c['valor_novo'], 'classificacao': c['classificacao'],
             'meses_base': v._meses_base_str(c['meses_base']), 'fonte': c['fonte'],
             'metodo': c['metodo'], 'verificado_em': '2026-11-16T12:00:00+00:00'}
            for c in (_CEL_SUBST_JUL, _CEL_SUBST_AGO)
        ] + [
            {'arquivo': 'master_monthly.csv', 'ano': 2026, 'mes': 6, 'indice': 'tsa',
             'valor': 0.99, 'classificacao': 'observado', 'meses_base': '2026-06',
             'fonte': 'x', 'metodo': 'observacao_direta', 'verificado_em': '2026-11-13T00:00:00+00:00'},
        ]
        prov_head = prov.renderizar_texto(linhas)
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _CORRECAO_COMPLETA_MASTER,
                                            _SUBST_BASE_TXT, _CORRECAO_COMPLETA_SUBST,
                                            None, prov_head)
        self.assertFalse(autorizado)
        self.assertTrue(any('fora do plano foi tocada' in viol for viol in rel['violacoes']))

    def test_10_historico_sem_alteracao_preserva_comportamento_original(self):
        """Nada mudou nos 3 arquivos: a exceção NÃO se aplica (não é
        'autorizado' — é 'não se aplica'), preservando o comportamento
        original de ci.yml (que já trata esse caso separadamente via
        `git diff --quiet`, sem nunca chegar a chamar este validador)."""
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _MASTER_BASE_TXT,
                                            _SUBST_BASE_TXT, _SUBST_BASE_TXT, None, None)
        self.assertFalse(autorizado)
        self.assertEqual(rel['classificacao'], v.NAO_SE_APLICA)
        self.assertTrue(any('não se aplica' in viol for viol in rel['violacoes']))

    def test_outubro_condicional_tambem_e_reconhecida(self):
        """A célula condicional de outubro (CELULA_OUTUBRO_CONDICIONAL)
        é reconhecida como autorizada quando aparece com o valor
        antigo/novo exatos do plano E proveniência completa —
        'condicional' decide se a FERRAMENTA aplica, não se a CI
        reconhece a célula."""
        master_head = _master_texto({10: {'tsa': 0.57}})
        prov_head = _provenencia_correta_para([_CEL_OUTUBRO])
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, master_head,
                                            _SUBST_BASE_TXT, _SUBST_BASE_TXT, None, prov_head)
        self.assertTrue(autorizado, rel['violacoes'])

    def test_celulas_autorizadas_usa_o_plano_do_modulo_cih_sem_duplicar(self):
        """Garante que a lista usada aqui é derivada de PLANO_BASE/
        CELULA_OUTUBRO_CONDICIONAL — nunca uma cópia divergente."""
        autorizadas = v.celulas_autorizadas()
        self.assertEqual(len(autorizadas), len(cih.PLANO_BASE) + 1)
        self.assertIn(cih.CELULA_OUTUBRO_CONDICIONAL, autorizadas)
        for c in cih.PLANO_BASE:
            self.assertIn(c, autorizadas)


class ProvenienciaCompletaObrigatoriaTestCase(unittest.TestCase):
    """Fase ENSO-INTEGRIDADE 3B.0.2 — seção 'Testes obrigatórios',
    itens 1-13 (o item 14, acionamento real da CI, está em
    AcionamentoRealDoWorkflowTestCase)."""

    def test_01_jul_ago_corrigidos_com_provenencia_completa_aprovado(self):
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _CORRECAO_COMPLETA_MASTER,
                                            _SUBST_BASE_TXT, _CORRECAO_COMPLETA_SUBST,
                                            None, _PROV_CORRECAO_COMPLETA)
        self.assertTrue(autorizado, rel['violacoes'])

    def test_02_sem_arquivo_de_provenencia_e_reprovado(self):
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _CORRECAO_COMPLETA_MASTER,
                                            _SUBST_BASE_TXT, _CORRECAO_COMPLETA_SUBST,
                                            None, None)
        self.assertFalse(autorizado)
        self.assertEqual(rel['classificacao'], v.TENTATIVA_INVALIDA)
        self.assertTrue(any('não existe no HEAD' in viol for viol in rel['violacoes']))

    def test_03_sem_registro_para_uma_das_celulas_e_reprovado(self):
        # Proveniência completa para 4 das 5 células — falta serie_subst.csv/ago.
        prov_head = _provenencia_correta_para(
            [_CEL_MASTER_JUL, _CEL_MASTER_AGO, _CEL_MASTER_SET, _CEL_SUBST_JUL])
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _CORRECAO_COMPLETA_MASTER,
                                            _SUBST_BASE_TXT, _CORRECAO_COMPLETA_SUBST,
                                            None, prov_head)
        self.assertFalse(autorizado)
        self.assertTrue(any("serie_subst.csv', 2026, 8, 'tsa'" in viol and 'ausente' in viol
                             for viol in rel['violacoes']), rel['violacoes'])

    def test_04_valor_da_provenencia_diferente_do_csv_e_reprovado(self):
        prov_head = _provenencia_correta_para(
            _CELULAS_CORRECAO_COMPLETA,
            overrides={('master_monthly.csv', 2026, 7): {'valor': 0.99}})
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _CORRECAO_COMPLETA_MASTER,
                                            _SUBST_BASE_TXT, _CORRECAO_COMPLETA_SUBST,
                                            None, prov_head)
        self.assertFalse(autorizado)
        self.assertTrue(any('diverge do valor novo' in viol for viol in rel['violacoes']))

    def test_05_meses_base_incorreto_e_reprovado(self):
        prov_head = _provenencia_correta_para(
            _CELULAS_CORRECAO_COMPLETA,
            overrides={('master_monthly.csv', 2026, 7): {'meses_base': '2026-01'}})
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _CORRECAO_COMPLETA_MASTER,
                                            _SUBST_BASE_TXT, _CORRECAO_COMPLETA_SUBST,
                                            None, prov_head)
        self.assertFalse(autorizado)
        self.assertTrue(any('meses_base' in viol and 'diverge' in viol for viol in rel['violacoes']))

    def test_06_classificacao_incorreta_e_reprovada(self):
        prov_head = _provenencia_correta_para(
            _CELULAS_CORRECAO_COMPLETA,
            overrides={('serie_subst.csv', 2026, 8): {'classificacao': 'persistido'}})
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _CORRECAO_COMPLETA_MASTER,
                                            _SUBST_BASE_TXT, _CORRECAO_COMPLETA_SUBST,
                                            None, prov_head)
        self.assertFalse(autorizado)
        self.assertTrue(any('classificacao' in viol and 'diverge' in viol for viol in rel['violacoes']))

    def test_07_metodo_ou_fonte_incompativel_e_reprovado(self):
        prov_metodo_errado = _provenencia_correta_para(
            _CELULAS_CORRECAO_COMPLETA,
            overrides={('master_monthly.csv', 2026, 8): {'metodo': 'metodo_inventado'}})
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _CORRECAO_COMPLETA_MASTER,
                                            _SUBST_BASE_TXT, _CORRECAO_COMPLETA_SUBST,
                                            None, prov_metodo_errado)
        self.assertFalse(autorizado)
        self.assertTrue(any('metodo' in viol and 'diverge' in viol for viol in rel['violacoes']))

        prov_fonte_errada = _provenencia_correta_para(
            _CELULAS_CORRECAO_COMPLETA,
            overrides={('master_monthly.csv', 2026, 9): {'fonte': 'fonte_inventada'}})
        autorizado2, rel2 = v.validar_textos(_MASTER_BASE_TXT, _CORRECAO_COMPLETA_MASTER,
                                              _SUBST_BASE_TXT, _CORRECAO_COMPLETA_SUBST,
                                              None, prov_fonte_errada)
        self.assertFalse(autorizado2)
        self.assertTrue(any('fonte' in viol and 'diverge' in viol for viol in rel2['violacoes']))

    def test_08_registro_de_provenencia_extra_ou_orfao_e_reprovado(self):
        # Mesmo cenário do test_9b da classe anterior, com outro nome
        # para alinhar explicitamente com o item 8 desta seção.
        linhas = []
        for c in _CELULAS_CORRECAO_COMPLETA:
            linhas.append({
                'arquivo': c['arquivo'], 'ano': c['ano'], 'mes': c['mes'], 'indice': 'tsa',
                'valor': c['valor_novo'], 'classificacao': c['classificacao'],
                'meses_base': v._meses_base_str(c['meses_base']), 'fonte': c['fonte'],
                'metodo': c['metodo'], 'verificado_em': '2026-11-16T12:00:00+00:00',
            })
        linhas.append({  # linha extra/órfã — mês fora do plano
            'arquivo': 'serie_subst.csv', 'ano': 2026, 'mes': 6, 'indice': 'tsa',
            'valor': 0.99, 'classificacao': 'observado', 'meses_base': '2026-06',
            'fonte': 'x', 'metodo': 'observacao_direta', 'verificado_em': '2026-11-13T00:00:00+00:00',
        })
        prov_head = prov.renderizar_texto(linhas)
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _CORRECAO_COMPLETA_MASTER,
                                            _SUBST_BASE_TXT, _CORRECAO_COMPLETA_SUBST,
                                            None, prov_head)
        self.assertFalse(autorizado)
        self.assertTrue(any('fora do plano foi tocada' in viol for viol in rel['violacoes']))

    def test_09_alteracao_somente_no_master_com_provenencia_valida_avaliada_pelo_plano(self):
        """serie_subst.csv não é tocado; master_monthly.csv bate
        exatamente com o plano E tem proveniência completa — avaliado
        pelos próprios méritos, aprovado mesmo sem tocar serie_subst.csv."""
        prov_head = _provenencia_correta_para([_CEL_MASTER_JUL, _CEL_MASTER_AGO, _CEL_MASTER_SET])
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _CORRECAO_COMPLETA_MASTER,
                                            _SUBST_BASE_TXT, _SUBST_BASE_TXT,
                                            None, prov_head)
        self.assertTrue(autorizado, rel['violacoes'])

    def test_10_alteracao_somente_no_master_fora_do_plano_tsa_sem_concessao(self):
        """Já coberto por
        ValidarCorrecaoHistoricaTsaTestCase.test_8_modificacao_indevida_de_master_monthly_e_reprovada
        — repetido aqui com o nome alinhado ao item 10 desta seção,
        confirmando a classificação NAO_SE_APLICA (nunca concede a
        exceção, mas também nunca é tratado como tentativa de TSA)."""
        master_head = _master_texto({5: {'tsa': 0.99}})
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, master_head,
                                            _SUBST_BASE_TXT, _SUBST_BASE_TXT, None, None)
        self.assertFalse(autorizado)
        self.assertEqual(rel['classificacao'], v.NAO_SE_APLICA)

    def test_11_correcao_autorizada_misturada_com_alteracao_indevida_e_reprovada(self):
        master_head = _master_texto({7: {'tsa': 0.12}, 8: {'tsa': 0.42}, 9: {'tsa': 0.57},
                                      6: {'tsa': 0.11}})  # mês 6 fora do plano, misturado
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, master_head,
                                            _SUBST_BASE_TXT, _CORRECAO_COMPLETA_SUBST,
                                            None, _PROV_CORRECAO_COMPLETA)
        self.assertFalse(autorizado)
        self.assertEqual(rel['classificacao'], v.TENTATIVA_INVALIDA)
        self.assertTrue(any('fora do plano' in viol for viol in rel['violacoes']))

    def test_12_ausencia_de_alteracao_preserva_comportamento_original(self):
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _MASTER_BASE_TXT,
                                            _SUBST_BASE_TXT, _SUBST_BASE_TXT, None, None)
        self.assertFalse(autorizado)
        self.assertEqual(rel['classificacao'], v.NAO_SE_APLICA)

    def test_13_outubro_persistido_de_setembro_com_metadados_corretos_exigidos(self):
        master_head = _master_texto({10: {'tsa': 0.57}})

        # Positivo: meses_base correto ('2026-09', persistência de set).
        prov_ok = _provenencia_correta_para([_CEL_OUTUBRO])
        autorizado_ok, rel_ok = v.validar_textos(_MASTER_BASE_TXT, master_head,
                                                  _SUBST_BASE_TXT, _SUBST_BASE_TXT, None, prov_ok)
        self.assertTrue(autorizado_ok, rel_ok['violacoes'])

        # Negativo: meses_base errado (outubro não pode se autodeclarar
        # observação direta de outubro — tem que apontar para set/2026).
        prov_errado = _provenencia_correta_para(
            [_CEL_OUTUBRO], overrides={('master_monthly.csv', 2026, 10): {'meses_base': '2026-10'}})
        autorizado_errado, rel_errado = v.validar_textos(
            _MASTER_BASE_TXT, master_head, _SUBST_BASE_TXT, _SUBST_BASE_TXT, None, prov_errado)
        self.assertFalse(autorizado_errado)
        self.assertTrue(any('meses_base' in viol and 'diverge' in viol for viol in rel_errado['violacoes']))


class ValidarViaGitTestCase(unittest.TestCase):
    """Camada fina com git (validar()/_git_show) — confirma que a
    integração real com `git show` funciona, usando o próprio
    histórico deste repositório (HEAD contra HEAD — sem mudança real,
    nunca toca dados)."""

    def test_validar_contra_head_sem_mudanca_relata_nao_aplicavel(self):
        autorizado, rel = v.validar('HEAD', 'HEAD')
        self.assertFalse(autorizado)
        self.assertEqual(rel['classificacao'], v.NAO_SE_APLICA)
        self.assertTrue(any('não se aplica' in viol for viol in rel['violacoes']))

    def test_cli_exit_10_quando_nao_se_aplica(self):
        resultado = subprocess.run(
            [sys.executable, str(ROOT / 'scripts' / 'validar_correcao_historica_tsa.py'),
             'HEAD', 'HEAD'],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(resultado.returncode, 10)
        self.assertIn('NÃO SE APLICA', resultado.stdout)


# ══════════════════════════════════════════════════════════════════
# Item 14 da Fase 3B.0.2: prova de que o RAMO REAL da CI (o mesmo
# script que ci.yml chama) de fato invoca o validador e respeita seu
# código de saída — com um repositório git TEMPORÁRIO (nunca o real).
# ══════════════════════════════════════════════════════════════════
class _RepoTemporario:
    """Repositório git descartável com dois commits (base/head), cada
    um a partir de um dict {caminho_relativo: conteudo_str|None}
    (None = arquivo ausente nesse commit). Usado só para exercitar de
    verdade scripts/decidir_continuidade_serie_subst.sh e
    scripts/validar_correcao_historica_tsa.py --repo, nunca o
    repositório real."""

    def __init__(self, arquivos_base, arquivos_head):
        self.dir = tempfile.mkdtemp(prefix='enso_fase3b0_2_')
        self._run('git', 'init', '-q')
        self._run('git', 'config', 'user.email', 'teste@example.com')
        self._run('git', 'config', 'user.name', 'Teste 3B.0.2')
        self.base_sha = self._commit(arquivos_base, 'base')
        self.head_sha = self._commit(arquivos_head, 'head')

    def _run(self, *args):
        subprocess.run(args, cwd=self.dir, check=True, capture_output=True, text=True)

    def _commit(self, arquivos, mensagem):
        for caminho, conteudo in arquivos.items():
            p = Path(self.dir) / caminho
            if conteudo is None:
                if p.exists():
                    p.unlink()
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(conteudo, encoding='utf-8')
        self._run('git', 'add', '-A')
        self._run('git', 'commit', '-q', '-m', mensagem, '--allow-empty')
        return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=self.dir,
                               capture_output=True, text=True, check=True).stdout.strip()

    def decidir(self, event_name='pull_request'):
        """Roda o MESMO script que ci.yml chama, contra este repositório
        temporário (cwd=self.dir) — prova real do acionamento do ramo
        da CI, não uma reimplementação da decisão em Python."""
        return subprocess.run(
            ['bash', str(DECISOR_SH), event_name, self.base_sha, self.head_sha],
            cwd=self.dir, capture_output=True, text=True)

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class AcionamentoRealDoWorkflowTestCase(unittest.TestCase):
    """Item 14: 'incluir uma simulação isolada da decisão real do
    workflow, com Git temporário ..., para demonstrar o acionamento do
    ramo da CI' — roda scripts/decidir_continuidade_serie_subst.sh de
    verdade (o mesmo arquivo que .github/workflows/ci.yml invoca)."""

    def setUp(self):
        self._repos = []

    def tearDown(self):
        for r in self._repos:
            r.cleanup()

    def _repo(self, arquivos_base, arquivos_head):
        r = _RepoTemporario(arquivos_base, arquivos_head)
        self._repos.append(r)
        return r

    def test_pull_request_correcao_autorizada_concede_exceção_pula_true(self):
        repo = self._repo(
            {'data/master_monthly.csv': _MASTER_BASE_TXT, 'data/serie_subst.csv': _SUBST_BASE_TXT},
            {'data/master_monthly.csv': _CORRECAO_COMPLETA_MASTER,
             'data/serie_subst.csv': _CORRECAO_COMPLETA_SUBST,
             'data/indices_proveniencia.csv': _PROV_CORRECAO_COMPLETA})
        r = repo.decidir()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'true')
        self.assertIn('exceção estrita', r.stderr)

    def test_pull_request_tentativa_invalida_falha_explicita_exit_nao_zero(self):
        """Proveniência ausente para a correção tentada — o ramo real
        da CI tem que FALHAR explicitamente (código != 0), nunca cair
        de volta em 'pular=false, talvez passe de qualquer forma'."""
        repo = self._repo(
            {'data/master_monthly.csv': _MASTER_BASE_TXT, 'data/serie_subst.csv': _SUBST_BASE_TXT},
            {'data/master_monthly.csv': _CORRECAO_COMPLETA_MASTER,
             'data/serie_subst.csv': _CORRECAO_COMPLETA_SUBST})
        r = repo.decidir()
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('true', r.stdout)
        self.assertNotIn('false', r.stdout)
        self.assertIn('REPROVADA', r.stderr)

    def test_pull_request_alteracao_de_outra_natureza_preserva_comportamento_ordinario(self):
        """master_monthly.csv muda por um motivo não relacionado à TSA
        (nenhuma célula do plano tocada); serie_subst.csv não muda —
        comportamento ORDINÁRIO (pular=true), nunca classificado como
        tentativa de TSA."""
        master_head = _master_texto({5: {'tsa': 0.99}})
        repo = self._repo(
            {'data/master_monthly.csv': _MASTER_BASE_TXT, 'data/serie_subst.csv': _SUBST_BASE_TXT},
            {'data/master_monthly.csv': master_head, 'data/serie_subst.csv': _SUBST_BASE_TXT})
        r = repo.decidir()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'true')
        self.assertIn('outra natureza', r.stderr)

    def test_pull_request_alteracao_de_outra_natureza_em_serie_subst_mantem_checagem_cheia(self):
        """Mesmo caso acima, mas a alteração de outra natureza É em
        serie_subst.csv — comportamento ordinário preservado significa
        pular=false aqui (igual a antes da Fase 3B.0 existir)."""
        subst_head = _subst_texto({6: {'prec': 999.0}})  # nada a ver com TSA
        repo = self._repo(
            {'data/master_monthly.csv': _MASTER_BASE_TXT, 'data/serie_subst.csv': _SUBST_BASE_TXT},
            {'data/master_monthly.csv': _MASTER_BASE_TXT, 'data/serie_subst.csv': subst_head})
        r = repo.decidir()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'false')

    def test_pull_request_correcao_somente_no_master_passa_pela_mesma_validacao(self):
        """Item 4 da seção de testes: modificação exclusiva do master,
        dentro do escopo do plano de TSA, exige a MESMA validação —
        aqui, com proveniência completa, a exceção É concedida mesmo
        sem tocar serie_subst.csv."""
        prov_head = _provenencia_correta_para([_CEL_MASTER_JUL, _CEL_MASTER_AGO, _CEL_MASTER_SET])
        repo = self._repo(
            {'data/master_monthly.csv': _MASTER_BASE_TXT, 'data/serie_subst.csv': _SUBST_BASE_TXT},
            {'data/master_monthly.csv': _CORRECAO_COMPLETA_MASTER,
             'data/serie_subst.csv': _SUBST_BASE_TXT,
             'data/indices_proveniencia.csv': prov_head})
        r = repo.decidir()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'true')

    def test_pull_request_correcao_somente_no_master_sem_provenencia_falha(self):
        """Mesmo caso acima, mas sem proveniência — tem que falhar
        explicitamente, nunca ser tratado como 'nada a ver com TSA'
        só porque serie_subst.csv não foi tocado."""
        repo = self._repo(
            {'data/master_monthly.csv': _MASTER_BASE_TXT, 'data/serie_subst.csv': _SUBST_BASE_TXT},
            {'data/master_monthly.csv': _CORRECAO_COMPLETA_MASTER,
             'data/serie_subst.csv': _SUBST_BASE_TXT})
        r = repo.decidir()
        self.assertNotEqual(r.returncode, 0)

    def test_nenhum_dos_3_arquivos_tocado_preserva_comportamento_original(self):
        repo = self._repo(
            {'data/master_monthly.csv': _MASTER_BASE_TXT, 'data/serie_subst.csv': _SUBST_BASE_TXT},
            {'data/master_monthly.csv': _MASTER_BASE_TXT, 'data/serie_subst.csv': _SUBST_BASE_TXT})
        r = repo.decidir()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'true')

    def test_workflow_dispatch_preserva_comportamento_existente(self):
        repo = self._repo(
            {'data/master_monthly.csv': _MASTER_BASE_TXT, 'data/serie_subst.csv': _SUBST_BASE_TXT},
            {'data/master_monthly.csv': _CORRECAO_COMPLETA_MASTER,
             'data/serie_subst.csv': _CORRECAO_COMPLETA_SUBST})
        r = repo.decidir(event_name='workflow_dispatch')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), 'true')


class GitignoreTmpTestCase(unittest.TestCase):
    """Item 12 da seção 'Testes obrigatórios' da Fase 3B.0: arquivos
    temporários da ferramenta de correção são ignorados pelo Git, mas
    o registro definitivo de proveniência não é — via
    `git check-ignore` real, nunca uma reimplementação própria de glob."""

    def _ignorado(self, caminho_relativo):
        r = subprocess.run(['git', 'check-ignore', '-q', caminho_relativo],
                            cwd=ROOT)
        return r.returncode == 0

    def test_tmp_dos_3_csvs_e_do_manifesto_sao_ignorados(self):
        for caminho in ('data/master_monthly.csv.tmp', 'data/serie_subst.csv.tmp',
                         'data/indices_proveniencia.csv.tmp',
                         'data/.corrigir_indices_historicos.ativo.json.tmp',
                         'data/.corrigir_indices_historicos.2026-11-13T00-00-00.concluido.json.tmp'):
            with self.subTest(caminho=caminho):
                self.assertTrue(self._ignorado(caminho), f'{caminho} deveria ser ignorado')

    def test_registro_definitivo_de_proveniencia_nao_e_ignorado(self):
        self.assertFalse(self._ignorado('data/indices_proveniencia.csv'))

    def test_csvs_reais_nao_sao_ignorados(self):
        for caminho in ('data/master_monthly.csv', 'data/serie_subst.csv'):
            with self.subTest(caminho=caminho):
                self.assertFalse(self._ignorado(caminho))


if __name__ == '__main__':
    unittest.main()
