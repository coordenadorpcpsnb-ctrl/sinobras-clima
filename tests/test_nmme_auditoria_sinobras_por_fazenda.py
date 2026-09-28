#!/usr/bin/env python3
"""
tests/test_nmme_auditoria_sinobras_por_fazenda.py — Fase 2C.2, auditoria
da nova evidência SINOBRAS.csv (registros por fazenda, 1996-2025).

Tudo com dados SINTÉTICOS — este módulo NUNCA depende do arquivo
original recebido (SINOBRAS.csv não é incorporado ao repositório, por
restrição explícita da tarefa). A suíte automatizada continua
funcionando sem qualquer acesso a esse arquivo.

Roda com:
    python -m unittest tests.test_nmme_auditoria_sinobras_por_fazenda -v
"""

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import nmme_auditoria_sinobras_por_fazenda as aud  # noqa: E402


def _escrever_sinobras_sintetico(caminho, linhas):
    """`linhas`: lista de (ano, mes, prec_mm, estacao)."""
    df = pd.DataFrame(linhas, columns=['ano', 'mes', 'prec_mm', 'estacao'])
    df.to_csv(caminho, sep=';', index=False)
    return df


def _sinobras_completo_4_estacoes_3_meses():
    """4 identificadores × 3 meses = 12 registros. FAZ_A e FAZ_B têm a
    MESMA série completa (grupo idêntico); FAZ_C e FAZ_D são únicas."""
    linhas = []
    valores = {
        'FAZ_A': [100, 110, 120], 'FAZ_B': [100, 110, 120],
        'FAZ_C': [90, 95, 130], 'FAZ_D': [80, 85, 140],
    }
    for mes_idx, mes in enumerate((1, 2, 3)):
        for estacao, vals in valores.items():
            linhas.append((2000, mes, vals[mes_idx], estacao))
    return linhas


class CalcularSha256TestCase(unittest.TestCase):
    """Item 9 — hash de integridade, calculado sobre o arquivo tal como
    recebido, nunca sobre uma cópia parcial."""

    def test_a_hash_bate_com_hashlib_direto(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / 'arquivo.csv'
            caminho.write_text('ano;mes;prec_mm;estacao\n2000;1;100;FAZ_A\n')
            esperado = hashlib.sha256(caminho.read_bytes()).hexdigest()
            self.assertEqual(aud.calcular_sha256(caminho), esperado)

    def test_b_arquivos_diferentes_produzem_hashes_diferentes(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / 'a.csv'
            b = Path(tmp) / 'b.csv'
            a.write_text('ano;mes;prec_mm;estacao\n2000;1;100;FAZ_A\n')
            b.write_text('ano;mes;prec_mm;estacao\n2000;1;101;FAZ_A\n')
            self.assertNotEqual(aud.calcular_sha256(a), aud.calcular_sha256(b))


class CarregarSinobrasTestCase(unittest.TestCase):
    """Item 1 — leitura pura, nunca escreve nem modifica o arquivo de
    entrada."""

    def test_a_leitura_happy_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / 'sinobras.csv'
            mtime_antes = None
            _escrever_sinobras_sintetico(caminho, _sinobras_completo_4_estacoes_3_meses())
            conteudo_antes = caminho.read_bytes()
            df = aud.carregar_sinobras(caminho)
            self.assertEqual(len(df), 12)
            self.assertEqual(caminho.read_bytes(), conteudo_antes)   # nunca modificado

    def test_b_coluna_ausente_lanca_erro_explicito(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / 'sinobras_incompleto.csv'
            pd.DataFrame({'ano': [2000], 'mes': [1], 'prec_mm': [100]}).to_csv(
                caminho, sep=';', index=False)
            with self.assertRaises(ValueError):
                aud.carregar_sinobras(caminho)

    def test_c_nunca_escreve_no_arquivo_original(self):
        import inspect
        src = inspect.getsource(aud.carregar_sinobras)
        self.assertNotIn('to_csv', src)
        self.assertNotIn('.write', src)


class VerificarIntegridadeEstruturalTestCase(unittest.TestCase):
    """Item 2 — cobertura mensal, duplicatas, valores implausíveis,
    nunca assumindo 34 fazendas nem 360 meses fixos."""

    def test_a_dados_completos_sao_integros(self):
        df = pd.DataFrame(_sinobras_completo_4_estacoes_3_meses(),
                           columns=['ano', 'mes', 'prec_mm', 'estacao'])
        resultado = aud.verificar_integridade_estrutural(df)
        self.assertEqual(resultado['n_registros'], 12)
        self.assertEqual(resultado['n_identificadores'], 4)
        self.assertTrue(resultado['cobertura_mensal_sem_lacunas'])
        self.assertEqual(resultado['n_duplicatas_ano_mes_estacao'], 0)
        self.assertEqual(resultado['n_valores_implausiveis'], 0)
        self.assertTrue(resultado['integro'])

    def test_b_mes_ausente_e_detectado(self):
        linhas = [l for l in _sinobras_completo_4_estacoes_3_meses() if l[1] != 2]
        df = pd.DataFrame(linhas, columns=['ano', 'mes', 'prec_mm', 'estacao'])
        resultado = aud.verificar_integridade_estrutural(df)
        self.assertFalse(resultado['cobertura_mensal_sem_lacunas'])
        self.assertIn('2000-02', resultado['meses_ausentes_dentro_do_periodo'])
        self.assertFalse(resultado['integro'])

    def test_c_duplicata_e_detectada(self):
        linhas = _sinobras_completo_4_estacoes_3_meses() + [(2000, 1, 999, 'FAZ_A')]
        df = pd.DataFrame(linhas, columns=['ano', 'mes', 'prec_mm', 'estacao'])
        resultado = aud.verificar_integridade_estrutural(df)
        self.assertEqual(resultado['n_duplicatas_ano_mes_estacao'], 2)
        self.assertFalse(resultado['integro'])

    def test_d_valor_implausivel_e_detectado(self):
        linhas = [l if not (l[3] == 'FAZ_C' and l[1] == 1) else (2000, 1, -5, 'FAZ_C')
                  for l in _sinobras_completo_4_estacoes_3_meses()]
        df = pd.DataFrame(linhas, columns=['ano', 'mes', 'prec_mm', 'estacao'])
        resultado = aud.verificar_integridade_estrutural(df)
        self.assertEqual(resultado['n_valores_implausiveis'], 1)
        self.assertFalse(resultado['integro'])

    def test_e_estacao_com_registro_faltando_e_detectada(self):
        linhas = [l for l in _sinobras_completo_4_estacoes_3_meses()
                  if not (l[3] == 'FAZ_D' and l[1] == 3)]
        df = pd.DataFrame(linhas, columns=['ano', 'mes', 'prec_mm', 'estacao'])
        resultado = aud.verificar_integridade_estrutural(df)
        self.assertIn('FAZ_D', resultado['identificadores_com_contagem_diferente_do_maximo'])
        self.assertIn('2000-03', resultado['meses_com_numero_de_registros_atipico'])
        self.assertFalse(resultado['integro'])


class ReproduzirMediaMensalTestCase(unittest.TestCase):
    """Item 3 — mesma fórmula de agregação já verificada por leitura de
    código no módulo de auditoria histórica (média aritmética simples)."""

    def test_a_media_calculada_corretamente(self):
        df = pd.DataFrame(_sinobras_completo_4_estacoes_3_meses(),
                           columns=['ano', 'mes', 'prec_mm', 'estacao'])
        media = aud.reproduzir_media_mensal(df)
        linha_jan = media[(media['ano'] == 2000) & (media['mes'] == 1)].iloc[0]
        self.assertAlmostEqual(linha_jan['media_mm'], (100 + 100 + 90 + 80) / 4)
        self.assertEqual(linha_jan['n_registros'], 4)


class ConfrontarComSerieProducaoTestCase(unittest.TestCase):
    """Item 3 — só LÊ a série de produção informada via `serie_path`,
    nunca escreve nela."""

    def test_a_reconciliacao_identica(self):
        with tempfile.TemporaryDirectory() as tmp:
            serie_path = Path(tmp) / 'serie.csv'
            pd.DataFrame([
                {'ano': 2000, 'mes': 1, 'prec': 97.5},
                {'ano': 2000, 'mes': 2, 'prec': 200.0},
            ]).to_csv(serie_path, index=False)
            media_df = pd.DataFrame([
                {'ano': 2000, 'mes': 1, 'media_mm': 97.5, 'n_registros': 4},
                {'ano': 2000, 'mes': 2, 'media_mm': 200.0, 'n_registros': 4},
            ])
            resumo, tabela = aud.confrontar_com_serie_producao(media_df, serie_path=serie_path)
            self.assertTrue(resumo['reconciliacao_completa'])
            self.assertEqual(resumo['n_meses_identicos_apos_arredondamento_2_casas'], 2)
            self.assertEqual(resumo['diff_abs_maxima_mm'], 0.0)

    def test_b_mes_sem_correspondencia_e_detectado(self):
        with tempfile.TemporaryDirectory() as tmp:
            serie_path = Path(tmp) / 'serie.csv'
            pd.DataFrame([{'ano': 2000, 'mes': 1, 'prec': 97.5}]).to_csv(serie_path, index=False)
            media_df = pd.DataFrame([
                {'ano': 2000, 'mes': 1, 'media_mm': 97.5, 'n_registros': 4},
                {'ano': 1900, 'mes': 1, 'media_mm': 50.0, 'n_registros': 4},
            ])
            resumo, _ = aud.confrontar_com_serie_producao(media_df, serie_path=serie_path)
            self.assertEqual(resumo['n_meses_sem_correspondencia_na_serie_producao'], 1)
            self.assertFalse(resumo['reconciliacao_completa'])

    def test_c_divergencia_e_detectada(self):
        with tempfile.TemporaryDirectory() as tmp:
            serie_path = Path(tmp) / 'serie.csv'
            pd.DataFrame([{'ano': 2000, 'mes': 1, 'prec': 300.0}]).to_csv(serie_path, index=False)
            media_df = pd.DataFrame([{'ano': 2000, 'mes': 1, 'media_mm': 97.5, 'n_registros': 4}])
            resumo, _ = aud.confrontar_com_serie_producao(media_df, serie_path=serie_path)
            self.assertFalse(resumo['reconciliacao_completa'])
            self.assertAlmostEqual(resumo['diff_abs_maxima_mm'], 202.5)


class IdentificarGruposSeriesIdenticasTestCase(unittest.TestCase):
    """Item 4 — grupos identificados automaticamente por igualdade
    EXATA dos 360 (ou N) valores mensais completos."""

    def test_a_grupo_identico_detectado_e_unicas_separadas(self):
        df = pd.DataFrame(_sinobras_completo_4_estacoes_3_meses(),
                           columns=['ano', 'mes', 'prec_mm', 'estacao'])
        resultado = aud.identificar_grupos_series_identicas(df)
        self.assertEqual(resultado['n_identificadores_comparados'], 4)
        self.assertEqual(resultado['n_series_mensais_distintas'], 3)
        self.assertEqual(resultado['grupos_de_series_identicas'], [['FAZ_A', 'FAZ_B']])
        self.assertEqual(sorted(resultado['identificadores_com_serie_unica']), ['FAZ_C', 'FAZ_D'])

    def test_b_todas_distintas_nao_produz_grupo(self):
        linhas = [
            (2000, 1, 100, 'FAZ_A'), (2000, 1, 200, 'FAZ_B'),
            (2000, 2, 110, 'FAZ_A'), (2000, 2, 210, 'FAZ_B'),
        ]
        df = pd.DataFrame(linhas, columns=['ano', 'mes', 'prec_mm', 'estacao'])
        resultado = aud.identificar_grupos_series_identicas(df)
        self.assertEqual(resultado['n_series_mensais_distintas'], 2)
        self.assertEqual(resultado['grupos_de_series_identicas'], [])


class DistinguirIdentificadoresSeriesInstrumentosTestCase(unittest.TestCase):
    """Item 5 — nunca presume equivalência entre identificadores,
    séries distintas e instrumentos independentes."""

    def test_a_instrumentos_independentes_sempre_none(self):
        integridade = {'n_identificadores': 34}
        grupos = {'n_series_mensais_distintas': 27}
        resultado = aud.distinguir_identificadores_series_e_instrumentos(integridade, grupos)
        self.assertEqual(resultado['n_identificadores_de_fazenda'], 34)
        self.assertEqual(resultado['n_series_mensais_numericamente_distintas'], 27)
        self.assertIsNone(
            resultado['n_instrumentos_pluviometricos_efetivamente_independentes_confirmados'])
        self.assertIn('DESCONHECIDO', resultado['interpretacao'])


class AnalisarSensibilidadeDeduplicacaoTestCase(unittest.TestCase):
    """Teste de sensibilidade informativo — nunca uma correção
    proposta, nunca aplicada à série de produção."""

    def test_a_diferenca_calculada_corretamente(self):
        df = pd.DataFrame(_sinobras_completo_4_estacoes_3_meses(),
                           columns=['ano', 'mes', 'prec_mm', 'estacao'])
        grupos = aud.identificar_grupos_series_identicas(df)
        resultado = aud.analisar_sensibilidade_deduplicacao(df, grupos)
        # jan/2000: média dos 4 = (100+100+90+80)/4 = 92.5;
        # média por série única (1 representante do grupo A/B + C + D) = (100+90+80)/3 = 90.0
        media_jan_todos = (100 + 100 + 90 + 80) / 4
        media_jan_dedup = (100 + 90 + 80) / 3
        self.assertAlmostEqual(resultado['diff_abs_maxima_mm'],
                                max(abs(media_jan_todos - media_jan_dedup),
                                    abs((110 + 110 + 95 + 85) / 4 - (110 + 95 + 85) / 3),
                                    abs((120 + 120 + 130 + 140) / 4 - (120 + 130 + 140) / 3)),
                                places=4)

    def test_b_nunca_menciona_aplicar_a_producao(self):
        import inspect
        src = inspect.getsource(aud.analisar_sensibilidade_deduplicacao)
        self.assertNotIn('serie_subst', src)
        self.assertNotIn('to_csv', src)


class MontarAchadosEspaciaisTestCase(unittest.TestCase):
    """Item 7 — registra a NECESSIDADE de coordenadas individuais,
    nunca as inventa."""

    def test_a_coordenadas_registradas_como_ausentes(self):
        grupos = {'n_series_mensais_distintas': 27}
        resultado = aud.montar_achados_espaciais(grupos)
        self.assertFalse(resultado['coordenadas_individuais_disponiveis_no_arquivo'])
        self.assertFalse(resultado['coordenadas_individuais_disponiveis_no_repositorio'])
        self.assertIn('coordenadas individuais', resultado['interpretacao'])


class ExecutarAuditoriaCompletaEndToEndTestCase(unittest.TestCase):
    """Fim a fim, inteiramente com dados sintéticos — nunca depende do
    arquivo original SINOBRAS.csv."""

    def test_a_reconciliacao_completa_com_serie_sintetica_compativel(self):
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = Path(tmp) / 'sinobras_sintetico.csv'
            _escrever_sinobras_sintetico(arquivo, _sinobras_completo_4_estacoes_3_meses())

            serie_path = Path(tmp) / 'serie.csv'
            pd.DataFrame([
                {'ano': 2000, 'mes': 1, 'prec': (100 + 100 + 90 + 80) / 4},
                {'ano': 2000, 'mes': 2, 'prec': (110 + 110 + 95 + 85) / 4},
                {'ano': 2000, 'mes': 3, 'prec': (120 + 120 + 130 + 140) / 4},
            ]).to_csv(serie_path, index=False)

            tabela, metadata = aud.executar_auditoria_completa(arquivo, serie_path=serie_path)
            self.assertTrue(metadata['integridade_estrutural']['integro'])
            self.assertTrue(metadata['reconciliacao_com_serie_producao']['reconciliacao_completa'])
            self.assertEqual(metadata['grupos_series_identicas']['n_series_mensais_distintas'], 3)
            self.assertTrue(metadata['nenhuma_skill_calculada'])
            self.assertTrue(metadata['nenhuma_aptidao_cientifica_declarada'])
            self.assertTrue(metadata['nenhum_dashboard_alterado'])
            self.assertTrue(metadata['nenhuma_serie_historica_de_producao_alterada'])
            self.assertTrue(metadata['nenhuma_serie_duplicada_eliminada'])
            self.assertTrue(metadata['arquivo_original_nao_incorporado_ao_repositorio'])
            self.assertEqual(metadata['arquivo_analisado']['sha256'], aud.calcular_sha256(arquivo))

    def test_b_reconciliacao_incompleta_quando_serie_diverge(self):
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = Path(tmp) / 'sinobras_sintetico.csv'
            _escrever_sinobras_sintetico(arquivo, _sinobras_completo_4_estacoes_3_meses())

            serie_path = Path(tmp) / 'serie_divergente.csv'
            pd.DataFrame([
                {'ano': 2000, 'mes': 1, 'prec': 999.0},
                {'ano': 2000, 'mes': 2, 'prec': 999.0},
                {'ano': 2000, 'mes': 3, 'prec': 999.0},
            ]).to_csv(serie_path, index=False)

            _, metadata = aud.executar_auditoria_completa(arquivo, serie_path=serie_path)
            self.assertFalse(metadata['reconciliacao_com_serie_producao']['reconciliacao_completa'])

    def test_c_relatorio_markdown_gerado_sem_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = Path(tmp) / 'sinobras_sintetico.csv'
            _escrever_sinobras_sintetico(arquivo, _sinobras_completo_4_estacoes_3_meses())
            serie_path = Path(tmp) / 'serie.csv'
            pd.DataFrame([
                {'ano': 2000, 'mes': 1, 'prec': (100 + 100 + 90 + 80) / 4},
                {'ano': 2000, 'mes': 2, 'prec': (110 + 110 + 95 + 85) / 4},
                {'ano': 2000, 'mes': 3, 'prec': (120 + 120 + 130 + 140) / 4},
            ]).to_csv(serie_path, index=False)
            tabela, metadata = aud.executar_auditoria_completa(arquivo, serie_path=serie_path)
            relatorio = aud.gerar_relatorio_markdown(tabela, metadata)
            self.assertIn('SHA-256', relatorio)
            self.assertIn(aud.calcular_sha256(arquivo), relatorio)
            self.assertIn('DESCONHECIDO', relatorio)
            self.assertIn('coordenadas individuais', relatorio)
            self.assertIn('SEM COMPROVAÇÃO', relatorio)


class ZeroSkillNuncaModificaProducaoTestCase(unittest.TestCase):
    """Restrições explícitas desta tarefa: nunca calcula skill, nunca
    modifica dashboard/série de produção, nunca elimina duplicatas,
    nunca incorpora o arquivo original ao repositório."""

    def test_a_modulo_nunca_calcula_skill_nem_toca_dashboard(self):
        codigo = Path(aud.__file__).read_text()
        self.assertNotIn('import update_dashboard', codigo)
        self.assertNotIn('calcular_skill', codigo)
        self.assertNotIn('c3s_calibracao', codigo)

    def test_b_modulo_nunca_escreve_em_data_serie_subst(self):
        codigo = Path(aud.__file__).read_text()
        # A série de produção só aparece como leitura (pd.read_csv em
        # confrontar_com_serie_producao) — nunca como destino de escrita.
        self.assertNotIn("serie_path, 'w')", codigo)
        self.assertNotIn('.to_csv(serie_path', codigo)
        self.assertNotIn('.to_csv(pilo.SERIE_OBSERVACIONAL_PATH', codigo)

    def test_c_dry_run_nao_escreve_nada(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = aud.ARTIFACTS_DIR
            aud.ARTIFACTS_DIR = Path(tmp) / 'nunca_criado'
            try:
                aud.imprimir_plano()
                self.assertFalse(aud.ARTIFACTS_DIR.exists())
            finally:
                aud.ARTIFACTS_DIR = original

    def test_d_gerar_relatorio_sem_arquivo_falha_com_erro_explicito(self):
        import subprocess
        resultado = subprocess.run(
            [sys.executable, str(ROOT / 'scripts' / 'nmme_auditoria_sinobras_por_fazenda.py'),
             '--gerar-relatorio'],
            capture_output=True, text=True)
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn('--arquivo', resultado.stderr)


if __name__ == '__main__':
    unittest.main()
