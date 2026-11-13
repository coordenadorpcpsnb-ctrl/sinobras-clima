#!/usr/bin/env python3
"""
tests/test_enso_integridade_fase3b0.py — Fase ENSO-INTEGRIDADE 3B.0.

Cobre scripts/validar_correcao_historica_tsa.py (Controle A: exceção
estrita de continuidade temporal da CI para a correção histórica de
TSA) com fixtures sintéticas — nunca toca git nem os dados reais.
Os 12 cenários pedidos pela Fase 3B.0 (seção "Testes obrigatórios")
são cobertos aqui (itens 1-10) e em tests/test_enso_iri_set2026.py
(item 11, canário) / GitignoreTmpTestCase abaixo (item 12).

Roda com:
    python -m unittest tests.test_enso_integridade_fase3b0 -v
"""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import corrigir_indices_historicos as cih  # noqa: E402
import proveniencia_indices as prov        # noqa: E402
import validar_correcao_historica_tsa as v  # noqa: E402


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


class ValidarCorrecaoHistoricaTsaTestCase(unittest.TestCase):
    """Os itens 1-9 e 10 da seção 'Testes obrigatórios' da Fase 3B.0."""

    def test_1_duas_celulas_tsa_autorizadas_aprovado(self):
        master_head = _master_texto({7: {'tsa': 0.12}, 8: {'tsa': 0.42}, 9: {'tsa': 0.57}})
        subst_head = _subst_texto({7: {'tsa': 0.12}, 8: {'tsa': 0.42}})
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, master_head,
                                            _SUBST_BASE_TXT, subst_head, None, None)
        self.assertTrue(autorizado, rel['violacoes'])

    def test_2_tsa_em_outro_mes_e_reprovada(self):
        subst_head = _subst_texto({6: {'tsa': 0.99}})
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _MASTER_BASE_TXT,
                                            _SUBST_BASE_TXT, subst_head, None, None)
        self.assertFalse(autorizado)
        self.assertTrue(rel['violacoes'])

    def test_3_alteracao_de_precipitacao_e_reprovada(self):
        subst_head = _subst_texto({7: {'tsa': 0.12, 'prec': 999.0}})
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _MASTER_BASE_TXT,
                                            _SUBST_BASE_TXT, subst_head, None, None)
        self.assertFalse(autorizado)

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
        serie_subst.csv não tenha sido tocado."""
        master_head = _master_texto({5: {'tsa': 0.99}})
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, master_head,
                                            _SUBST_BASE_TXT, _SUBST_BASE_TXT, None, None)
        self.assertFalse(autorizado)

    def test_9_provenencia_inconsistente_e_reprovada(self):
        """Linha de proveniência para a célula autorizada de julho,
        mas com classificação diferente da exigida pelo plano
        ('observado') — reprova, mesmo com os CSVs de dado corretos."""
        master_head = _master_texto({7: {'tsa': 0.12}, 8: {'tsa': 0.42}, 9: {'tsa': 0.57}})
        subst_head = _subst_texto({7: {'tsa': 0.12}, 8: {'tsa': 0.42}})
        prov_head = prov.renderizar_texto([
            {'arquivo': 'master_monthly.csv', 'ano': 2026, 'mes': 7, 'indice': 'tsa',
             'valor': 0.12, 'classificacao': 'persistido',  # deveria ser 'observado'
             'meses_base': '2026-07', 'fonte': 'PSL tsa.data (verificado ao vivo)',
             'metodo': 'observacao_direta', 'verificado_em': '2026-11-13'},
        ])
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, master_head,
                                            _SUBST_BASE_TXT, subst_head, None, prov_head)
        self.assertFalse(autorizado, rel)

    def test_9b_provenencia_linha_fora_do_plano_e_reprovada(self):
        prov_head = prov.renderizar_texto([
            {'arquivo': 'master_monthly.csv', 'ano': 2026, 'mes': 6, 'indice': 'tsa',
             'valor': 0.99, 'classificacao': 'observado', 'meses_base': '2026-06',
             'fonte': 'x', 'metodo': 'observacao_direta', 'verificado_em': '2026-11-13'},
        ])
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _MASTER_BASE_TXT,
                                            _SUBST_BASE_TXT, _SUBST_BASE_TXT, None, prov_head)
        self.assertFalse(autorizado)

    def test_10_historico_sem_alteracao_preserva_comportamento_original(self):
        """Nada mudou nos 3 arquivos: a exceção NÃO se aplica (não é
        'autorizado' — é 'não se aplica'), preservando o comportamento
        original de ci.yml (que já trata esse caso separadamente via
        `git diff --quiet`, sem nunca chegar a chamar este validador)."""
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, _MASTER_BASE_TXT,
                                            _SUBST_BASE_TXT, _SUBST_BASE_TXT, None, None)
        self.assertFalse(autorizado)
        self.assertTrue(any('não se aplica' in viol for viol in rel['violacoes']))

    def test_outubro_condicional_tambem_e_reconhecida(self):
        """A célula condicional de outubro (CELULA_OUTUBRO_CONDICIONAL)
        é reconhecida como autorizada quando aparece com o valor
        antigo/novo exatos do plano — 'condicional' decide se a
        FERRAMENTA aplica, não se a CI reconhece a célula."""
        master_head = _master_texto({10: {'tsa': 0.57}})
        autorizado, rel = v.validar_textos(_MASTER_BASE_TXT, master_head,
                                            _SUBST_BASE_TXT, _SUBST_BASE_TXT, None, None)
        self.assertTrue(autorizado, rel['violacoes'])

    def test_celulas_autorizadas_usa_o_plano_do_modulo_cih_sem_duplicar(self):
        """Garante que a lista usada aqui é derivada de PLANO_BASE/
        CELULA_OUTUBRO_CONDICIONAL — nunca uma cópia divergente."""
        autorizadas = v.celulas_autorizadas()
        self.assertEqual(len(autorizadas), len(cih.PLANO_BASE) + 1)
        self.assertIn(cih.CELULA_OUTUBRO_CONDICIONAL, autorizadas)
        for c in cih.PLANO_BASE:
            self.assertIn(c, autorizadas)


class ValidarViaGitTestCase(unittest.TestCase):
    """Camada fina com git (validar()/_git_show) — confirma que a
    integração real com `git show` funciona, usando o próprio
    histórico deste repositório (HEAD contra HEAD — sem mudança real,
    nunca toca dados)."""

    def test_validar_contra_head_sem_mudanca_relata_nao_aplicavel(self):
        autorizado, rel = v.validar('HEAD', 'HEAD')
        self.assertFalse(autorizado)
        self.assertTrue(any('não se aplica' in viol for viol in rel['violacoes']))

    def test_cli_exit_code_para_ref_invalida_e_nao_autorizado(self):
        resultado = subprocess.run(
            [sys.executable, str(ROOT / 'scripts' / 'validar_correcao_historica_tsa.py'),
             'HEAD', 'HEAD'],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(resultado.returncode, 1)
        self.assertIn('NÃO AUTORIZADO', resultado.stdout)


class GitignoreTmpTestCase(unittest.TestCase):
    """Item 12 da seção 'Testes obrigatórios': arquivos temporários
    da ferramenta de correção são ignorados pelo Git, mas o registro
    definitivo de proveniência não é — via `git check-ignore` real,
    nunca uma reimplementação própria de glob."""

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
