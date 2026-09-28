#!/usr/bin/env python3
"""
tests/test_nmme_auditoria_chirps_sinobras.py — Fase 2C.2, investigação
dedicada da reinterpretação CHIRPS (4ª rodada, 2026).

Este módulo opera SÓ sobre arquivos já commitados no repositório
(data/chirps_1981_2025.csv, data/serie_subst.csv) — nunca depende do
arquivo original SINOBRAS.csv (que não está no repositório). Os testes
usam fixtures sintéticas para as funções isoladas e o dado REAL para
os testes fim a fim (mesmo padrão de RealSerieObservacionalTestCase em
outros módulos deste projeto).

Roda com:
    python -m unittest tests.test_nmme_auditoria_chirps_sinobras -v
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import nmme_auditoria_chirps_sinobras as aud  # noqa: E402


class CompararChirpsPontoComSerieProducaoTestCase(unittest.TestCase):
    """Item 5 — compara SEM presumir mesma metodologia, separado por
    período (pré/pós 1996)."""

    def test_a_meses_identicos_produzem_correlacao_1_e_diff_zero(self):
        serie_df = pd.DataFrame([
            {'ano': 2000, 'mes': 1, 'prec': 100.0},
            {'ano': 2000, 'mes': 2, 'prec': 200.0},
            {'ano': 2000, 'mes': 3, 'prec': 150.0},
        ])
        chirps_df = serie_df.rename(columns={'prec': 'prec'})[['ano', 'mes', 'prec']].copy()
        resultado = aud.comparar_chirps_ponto_com_serie_producao(chirps_df, serie_df)
        pos = resultado['periodo_pos_1996']
        self.assertEqual(pos['n_meses'], 3)
        self.assertEqual(pos['diff_abs_media_mm'], 0.0)
        self.assertEqual(pos['correlacao'], 1.0)
        self.assertEqual(pos['n_meses_identicos_diff_menor_0_01mm'], 3)

    def test_b_separa_pre_e_pos_1996_corretamente(self):
        serie_df = pd.DataFrame([
            {'ano': 1990, 'mes': 1, 'prec': 100.0},
            {'ano': 2000, 'mes': 1, 'prec': 200.0},
        ])
        chirps_df = pd.DataFrame([
            {'ano': 1990, 'mes': 1, 'prec': 90.0},
            {'ano': 2000, 'mes': 1, 'prec': 210.0},
        ])
        resultado = aud.comparar_chirps_ponto_com_serie_producao(chirps_df, serie_df)
        self.assertEqual(resultado['periodo_pre_1996']['n_meses'], 1)
        self.assertEqual(resultado['periodo_pos_1996']['n_meses'], 1)
        self.assertAlmostEqual(resultado['periodo_pre_1996']['diff_abs_media_mm'], 10.0)
        self.assertAlmostEqual(resultado['periodo_pos_1996']['diff_abs_media_mm'], 10.0)

    def test_c_meses_sem_correspondencia_nao_entram_na_comparacao(self):
        serie_df = pd.DataFrame([{'ano': 2000, 'mes': 1, 'prec': 100.0},
                                  {'ano': 2000, 'mes': 2, 'prec': 100.0}])
        chirps_df = pd.DataFrame([{'ano': 2000, 'mes': 1, 'prec': 90.0}])
        resultado = aud.comparar_chirps_ponto_com_serie_producao(chirps_df, serie_df)
        self.assertEqual(resultado['n_meses_comparados_total'], 1)

    def test_d_vazio_nao_quebra(self):
        vazio = pd.DataFrame(columns=['ano', 'mes', 'prec'])
        resultado = aud.comparar_chirps_ponto_com_serie_producao(vazio, vazio)
        self.assertEqual(resultado['n_meses_comparados_total'], 0)
        self.assertEqual(resultado['periodo_pos_1996']['n_meses'], 0)
        self.assertIsNone(resultado['periodo_pos_1996']['correlacao'])

    def test_e_nunca_presume_mesma_metodologia_no_texto(self):
        serie_df = pd.DataFrame([{'ano': 2000, 'mes': 1, 'prec': 100.0}])
        chirps_df = pd.DataFrame([{'ano': 2000, 'mes': 1, 'prec': 100.0}])
        resultado = aud.comparar_chirps_ponto_com_serie_producao(chirps_df, serie_df)
        self.assertIn('NÃO são a mesma extração', resultado['interpretacao'])

    def test_f_dados_reais_reproduzem_correlacao_conhecida(self):
        """Sanidade contra os dados REAIS já commitados — confirma que "
        os números citados no relatório continuam batendo."""
        chirps_df = aud.carregar_chirps_ponto()
        serie_df = aud.carregar_serie_producao()
        resultado = aud.comparar_chirps_ponto_com_serie_producao(chirps_df, serie_df)
        self.assertEqual(resultado['periodo_pos_1996']['n_meses'], 360)
        self.assertEqual(resultado['periodo_pre_1996']['n_meses'], 180)
        self.assertAlmostEqual(resultado['periodo_pos_1996']['correlacao'], 0.9168, places=3)
        self.assertAlmostEqual(resultado['periodo_pre_1996']['correlacao'], 0.9673, places=3)
        self.assertLess(resultado['periodo_pos_1996']['n_meses_identicos_diff_menor_0_01mm'], 20)


class CarregarArquivosTestCase(unittest.TestCase):
    """Item 5 — leitura pura, nunca modifica os arquivos de entrada
    (ambos já commitados no repositório)."""

    def test_a_carregar_chirps_ponto_nunca_escreve(self):
        import inspect
        src = inspect.getsource(aud.carregar_chirps_ponto)
        self.assertNotIn('to_csv', src)
        self.assertNotIn('.write', src)

    def test_b_carregar_serie_producao_nunca_escreve(self):
        import inspect
        src = inspect.getsource(aud.carregar_serie_producao)
        self.assertNotIn('to_csv', src)
        self.assertNotIn('.write', src)

    def test_c_arquivos_reais_existem_e_sao_carregaveis(self):
        chirps_df = aud.carregar_chirps_ponto()
        serie_df = aud.carregar_serie_producao()
        self.assertGreater(len(chirps_df), 0)
        self.assertGreater(len(serie_df), 0)
        self.assertIn('prec', chirps_df.columns)
        self.assertIn('prec', serie_df.columns)


class MontarListaInformacoesNecessariasTestCase(unittest.TestCase):
    """Item 4 — lista objetiva do que falta para reproduzir a extração
    de SINOBRAS.csv."""

    def test_a_lista_cobre_topicos_chave(self):
        """5ª rodada (2026) — a agregação espacial deixou de ser
        incógnita (confirmada como zonal) e virou dois itens mais
        específicos: critério de inclusão de pixel e tratamento de
        pixel parcialmente interceptado."""
        lista = aud.montar_lista_informacoes_necessarias_reproducao()
        self.assertIsInstance(lista, list)
        self.assertGreater(len(lista), 0)
        texto = ' '.join(lista).lower()
        for topico in ('versão', 'polígono', 'zonal', 'pixel', 'processamento',
                       'temporal', 'unidades'):
            self.assertIn(topico, texto)

    def test_c_registra_agregacao_espacial_como_resolvida_e_zonal(self):
        lista = aud.montar_lista_informacoes_necessarias_reproducao()
        texto = ' '.join(lista)
        self.assertIn('RESOLVIDO', texto)
        self.assertIn('ZONAL', texto)
        self.assertIn('borda do polígono', texto)

    def test_b_todos_os_itens_sao_strings_nao_vazias(self):
        for item in aud.montar_lista_informacoes_necessarias_reproducao():
            self.assertIsInstance(item, str)
            self.assertGreater(len(item), 0)


class AvaliarViabilidadeReferenciaChirpsTestCase(unittest.TestCase):
    """Item 6 — avaliação de viabilidade, NUNCA uma execução real de
    extração (nenhum acesso à rede)."""

    def test_a_nunca_acessa_rede(self):
        """Verifica ausência de CHAMADAS de rede (requests/urlopen ou
        uma invocação real de buscar_prec_chirps) — mencionar
        'ClimateSERV' em prosa explicativa é esperado e não conta."""
        import inspect
        src = inspect.getsource(aud.avaliar_viabilidade_referencia_chirps_1991_2011)
        for termo_proibido in ('requests.', 'urlopen', 'buscar_prec_chirps(', 'import requests'):
            self.assertNotIn(termo_proibido, src)

    def test_b_confirma_cobertura_real_1991_2011(self):
        resultado = aud.avaliar_viabilidade_referencia_chirps_1991_2011()
        self.assertTrue(resultado['data_chirps_1981_2025_ja_cobre_1991_2011'])
        self.assertEqual(resultado['n_meses_1991_2011_ja_extraidos'], 252)
        self.assertEqual(resultado['n_meses_1991_2011_esperados'], 252)

    def test_c_interpretacao_nunca_declara_pronto_sem_ressalvas(self):
        resultado = aud.avaliar_viabilidade_referencia_chirps_1991_2011()
        self.assertIn('ressalvas', resultado['interpretacao'].lower())
        self.assertIn('NÃO toma', resultado['interpretacao'])

    def test_d_cita_ferramentas_ja_existentes_sem_reimplementar(self):
        resultado = aud.avaliar_viabilidade_referencia_chirps_1991_2011()
        ferramentas = resultado['ferramentas_ja_existentes']
        self.assertIn('_chirps.py', ferramentas['ponto_unico'])
        self.assertIn('_chirps.py', ferramentas['zonal_envelope'])
        self.assertIn('backfill_chirps_historico.py', ferramentas['quebra_em_blocos'])
        self.assertIn('NÃO EXISTE', ferramentas['zonal_por_fazenda_individual'])

    def test_e_registra_conflito_com_armadilha_8(self):
        """5ª rodada (2026) — reproduzir a metodologia zonal por
        fazenda exigiria polígonos que o projeto decidiu
        deliberadamente não manter (CLAUDE.md armadilha 8)."""
        resultado = aud.avaliar_viabilidade_referencia_chirps_1991_2011()
        self.assertTrue(resultado['poligonos_por_fazenda_conflitam_com_claude_md_armadilha_8'])
        self.assertTrue(resultado['metodologia_ja_extraida_e_pontual_nao_zonal'])
        self.assertIn('armadilha 8', resultado['interpretacao'])
        self.assertIn('zonal', resultado['interpretacao'].lower())


class CompararTresAlternativasMetodologicasTestCase(unittest.TestCase):
    """5ª rodada (2026), atividades 5 e 6 — comparação puramente
    descritiva das três alternativas de referência regional, nunca
    uma implementação/cálculo de nenhuma delas."""

    def test_a_retorna_as_tres_alternativas_e_sobreposicao(self):
        resultado = aud.comparar_tres_alternativas_metodologicas()
        for chave in ('alternativa_a_media_simples_atual', 'alternativa_b_media_ponderada_por_area',
                      'alternativa_c_zonal_sobre_uniao', 'possibilidade_de_sobreposicao_espacial',
                      'interpretacao'):
            self.assertIn(chave, resultado)

    def test_b_nenhuma_alternativa_e_calculada(self):
        """Menções a `.mean()`/`.groupby()` no docstring/strings, citando
        onde a metodologia (a) JÁ está implementada em
        scripts/update_dashboard.py, são esperadas e não contam — o que
        importa é que esta função nunca LÊ um DataFrame nem invoca
        pandas."""
        resultado = aud.comparar_tres_alternativas_metodologicas()
        self.assertTrue(resultado['nenhuma_alternativa_calculada_ou_implementada'])
        import inspect
        src = inspect.getsource(aud.comparar_tres_alternativas_metodologicas)
        for termo_proibido in ('pd.read_csv', 'requests.', 'urlopen', 'carregar_chirps_ponto(',
                                'carregar_serie_producao('):
            self.assertNotIn(termo_proibido, src)

    def test_b2_funcao_nao_recebe_nenhum_dataframe(self):
        import inspect
        assinatura = inspect.signature(aud.comparar_tres_alternativas_metodologicas)
        self.assertEqual(len(assinatura.parameters), 0)

    def test_c_alternativa_a_e_a_metodologia_atual_em_producao(self):
        resultado = aud.comparar_tres_alternativas_metodologicas()
        alt_a = resultado['alternativa_a_media_simples_atual']
        self.assertIn('update_dashboard.py', alt_a['onde_ja_esta_implementada'])
        self.assertIn('IGUAL', alt_a['peso_por_fazenda'])
        self.assertIn('nenhum', alt_a['requisito_de_dados_adicional'])

    def test_d_alternativas_b_e_c_exigem_dados_nao_disponiveis(self):
        resultado = aud.comparar_tres_alternativas_metodologicas()
        alt_b = resultado['alternativa_b_media_ponderada_por_area']
        alt_c = resultado['alternativa_c_zonal_sobre_uniao']
        self.assertIn('não disponível', alt_b['requisito_de_dados_adicional'])
        self.assertIn('armadilha 8', alt_b['requisito_de_dados_adicional'])
        self.assertIn('polígonos individuais', alt_c['requisito_de_dados_adicional'])

    def test_e_sobreposicao_nunca_afirmada_nem_descartada(self):
        resultado = aud.comparar_tres_alternativas_metodologicas()
        sobrep = resultado['possibilidade_de_sobreposicao_espacial']
        self.assertFalse(sobrep['verificavel_com_os_dados_atuais'])
        texto = sobrep['interpretacao'].lower()
        self.assertIn('em aberto', texto)
        self.assertIn('nem confirmada', texto)
        self.assertIn('nem descartada', texto)

    def test_f_distingue_compartilhar_pixel_de_sobrepor_poligono(self):
        """Não presumir que os grupos de séries idênticas implicam
        sobreposição de polígono — só compartilhamento de pixel."""
        resultado = aud.comparar_tres_alternativas_metodologicas()
        sinal = resultado['possibilidade_de_sobreposicao_espacial']['sinal_indireto_disponivel']
        self.assertIn('NÃO', sinal)
        self.assertIn('sobreposição de', sinal)
        self.assertIn('pixels', sinal)

    def test_g_interpretacao_explica_quando_alternativas_convergem(self):
        resultado = aud.comparar_tres_alternativas_metodologicas()
        texto = resultado['interpretacao']
        self.assertIn('área', texto)
        self.assertIn('sobrep', texto.lower())
        self.assertNotIn('recomendamos', texto.lower())

    def test_h_wired_em_executar_investigacao_completa(self):
        metadata = aud.executar_investigacao_completa()
        self.assertIn('comparacao_tres_alternativas_metodologicas', metadata)

    def test_i_wired_no_relatorio_markdown(self):
        metadata = aud.executar_investigacao_completa()
        relatorio = aud.gerar_relatorio_markdown(metadata)
        self.assertIn('três alternativas metodológicas', relatorio)
        self.assertIn('média simples', relatorio.lower())
        self.assertIn('ponderada pela área', relatorio.lower())
        self.assertIn('união dos 34 polígonos', relatorio)

    def test_j_ausencia_de_sobreposicao_nao_e_declarada_suficiente_para_b_igual_c(self):
        """Ajuste final (2026) — a correção pedida: ausência de
        sobreposição é NECESSÁRIA mas NÃO SUFICIENTE para (b) e (c)
        coincidirem; também depende do critério de inclusão/ponderação
        de pixel ser o mesmo nos dois cálculos."""
        resultado = aud.comparar_tres_alternativas_metodologicas()
        sobrep = resultado['possibilidade_de_sobreposicao_espacial']
        self.assertIn('ausencia_de_sobreposicao_e_suficiente_para_b_igual_c', sobrep)
        self.assertFalse(sobrep['ausencia_de_sobreposicao_e_suficiente_para_b_igual_c'])
        self.assertIn('motivo_nao_suficiente', sobrep)
        self.assertIn('critério de inclusão', sobrep['motivo_nao_suficiente'])

    def test_k_interpretacao_nao_afirma_que_sem_sobreposicao_basta(self):
        resultado = aud.comparar_tres_alternativas_metodologicas()
        texto = resultado['interpretacao']
        self.assertIn('DUAS condições', texto)
        self.assertIn('NÃO garante a equivalência', texto)
        self.assertIn('critério de inclusão', texto)

    def test_l_nenhuma_alternativa_classificada_como_universalmente_mais_correta(self):
        """Ajuste final (2026) — não classificar nenhuma alternativa
        como universalmente mais correta; explicitar que a escolha
        depende da variável espacial que se pretende representar."""
        resultado = aud.comparar_tres_alternativas_metodologicas()
        self.assertIn('qual_alternativa_e_mais_correta', resultado)
        texto = resultado['qual_alternativa_e_mais_correta']
        self.assertIn('NENHUMA', texto)
        self.assertIn('universalmente mais correta', texto.lower())
        self.assertNotIn('é a mais correta espacialmente', resultado['interpretacao'])
        self.assertIn('universalmente mais correta', resultado['interpretacao'].lower())

    def test_m_wired_no_relatorio_markdown_secao_qual_e_mais_correta(self):
        metadata = aud.executar_investigacao_completa()
        relatorio = aud.gerar_relatorio_markdown(metadata)
        self.assertIn('Qual alternativa é mais correta', relatorio)
        self.assertIn('NENHUMA', relatorio)
        self.assertNotIn('(c) é a mais correta espacialmente', relatorio)


class AuditarExtracaoChirpsCentralExistenteTestCase(unittest.TestCase):
    """Ajuste final (2026) — auditoria de CÓDIGO de scripts/_chirps.py,
    nenhuma chamada de rede. Achados reproduzidos, com mais detalhe,
    em tests/test_chirps_extracao_sintetica.py; aqui só confirmamos que
    a função de auditoria os relata corretamente e distingue
    CONFIRMADO de PENDENTE."""

    def test_a_confirma_riscos_conhecidos(self):
        resultado = aud.auditar_extracao_chirps_central_existente()
        self.assertTrue(resultado['confirmado_valor_ausente_pode_virar_zero'])
        self.assertTrue(resultado['confirmado_zero_real_e_ausencia_sao_indistinguiveis_na_saida'])
        self.assertTrue(resultado['confirmado_sem_cobertura_minima_de_dias_exigida'])
        self.assertTrue(resultado['confirmado_resultado_sem_coluna_de_contagem_de_dias'])
        self.assertTrue(resultado['confirmado_dias_omitidos_tambem_nao_contam_nem_sinalizam'])
        self.assertTrue(resultado['confirmado_ponto_central_e_multiplo_exato_da_resolucao_chirps'])

    def test_b_distingue_confirmado_de_pendente(self):
        resultado = aud.auditar_extracao_chirps_central_existente()
        self.assertIn('pendente_convencao_de_alinhamento_do_grid_chirps', resultado)
        self.assertIn('não verificado', resultado['pendente_convencao_de_alinhamento_do_grid_chirps'].lower())

    def test_c_impacto_nao_afirma_que_ja_ocorreu(self):
        """O achado é sobre o CÓDIGO — não uma afirmação de que os
        dados já extraídos estão errados (não comprovado)."""
        resultado = aud.auditar_extracao_chirps_central_existente()
        self.assertIn('RISCO', resultado['impacto'])
        self.assertIn('não comprovado', resultado['impacto'])

    def test_d_propoe_correcao_mas_nao_aplica(self):
        resultado = aud.auditar_extracao_chirps_central_existente()
        self.assertIn('proposta_de_correcao_nao_aplicada', resultado)
        self.assertIn('NÃO aplicada', resultado['proposta_de_correcao_nao_aplicada'])

    def test_e_nunca_acessa_rede(self):
        """Menção a 'climateserv.api.request_data' no docstring,
        explicando ONDE os achados são reproduzidos sinteticamente
        (tests/test_chirps_extracao_sintetica.py), é esperada e não
        conta — o que importa é que esta função nunca CHAMA a API."""
        import inspect
        src = inspect.getsource(aud.auditar_extracao_chirps_central_existente)
        for termo_proibido in ('requests.', 'urlopen', 'import requests',
                                'api.request_data(', '_chirps.buscar_prec'):
            self.assertNotIn(termo_proibido, src)

    def test_f_nao_modifica_chirps_py(self):
        """A função só LÊ/relata — não escreve em scripts/_chirps.py."""
        import inspect
        src = inspect.getsource(aud.auditar_extracao_chirps_central_existente)
        self.assertNotIn('.write', src)
        self.assertNotIn('open(', src)

    def test_g_cita_a_suite_de_testes_sinteticos(self):
        resultado = aud.auditar_extracao_chirps_central_existente()
        self.assertIn('test_chirps_extracao_sintetica.py', resultado['testes_sinteticos'])

    def test_h_wired_em_executar_investigacao_completa(self):
        metadata = aud.executar_investigacao_completa()
        self.assertIn('auditoria_codigo_extracao_central_existente', metadata)

    def test_i_wired_no_relatorio_markdown(self):
        metadata = aud.executar_investigacao_completa()
        relatorio = aud.gerar_relatorio_markdown(metadata)
        self.assertIn('Auditoria do código da extração central existente', relatorio)
        self.assertIn('Confirmado', relatorio)
        self.assertIn('Proposta de correção (não aplicada)', relatorio)


class MontarPropostaContinuidadeTestCase(unittest.TestCase):
    def test_a_lista_nao_vazia_de_proximos_passos(self):
        proposta = aud.montar_proposta_continuidade()
        self.assertIsInstance(proposta, list)
        self.assertGreater(len(proposta), 3)

    def test_b_inclui_avaliar_alternativas_antes_de_implementar(self):
        proposta = ' '.join(aud.montar_proposta_continuidade())
        self.assertIn('não implementar automaticamente', proposta.lower())
        self.assertIn('comparar_tres_alternativas_metodologicas', proposta)

    def test_c_inclui_revisitar_armadilha_8(self):
        proposta = ' '.join(aud.montar_proposta_continuidade())
        self.assertIn('armadilha 8', proposta)
        self.assertIn('anonimização', proposta.lower())

    def test_d_inclui_avaliar_correcao_da_extracao_central_antes_de_aplicar(self):
        proposta = ' '.join(aud.montar_proposta_continuidade())
        self.assertIn('auditar_extracao_chirps_central_existente', proposta)
        self.assertIn('NÃO foi aplicada nesta rodada', proposta)


class ExecutarInvestigacaoCompletaEndToEndTestCase(unittest.TestCase):
    """Fim a fim contra os dados REAIS já commitados — nunca depende
    de SINOBRAS.csv (fora do repositório)."""

    def test_a_executa_sem_erro(self):
        metadata = aud.executar_investigacao_completa()
        self.assertTrue(metadata['nenhuma_skill_calculada'])
        self.assertTrue(metadata['nenhuma_previsao_ou_indicador_recalculado'])
        self.assertTrue(metadata['nenhuma_referencia_observacional_substituida'])
        self.assertTrue(metadata['nenhum_dado_historico_modificado'])
        self.assertTrue(metadata['nenhum_dashboard_alterado'])
        self.assertTrue(metadata['nenhum_modelo_climatico_alterado'])
        self.assertTrue(metadata['nenhuma_extracao_nova_executada'])

    def test_b_relatorio_markdown_gerado_sem_erro(self):
        metadata = aud.executar_investigacao_completa()
        relatorio = aud.gerar_relatorio_markdown(metadata)
        self.assertIn('CHIRPS', relatorio)
        self.assertIn('Proposta de continuidade', relatorio)
        self.assertIn('Informações necessárias', relatorio)
        self.assertIn('Viabilidade', relatorio)
        self.assertIn('Restrições respeitadas', relatorio)


class ZeroSkillNuncaSubstituiReferenciaTestCase(unittest.TestCase):
    """Restrições explícitas desta tarefa: nunca calcula skill, nunca
    recalcula previsões/indicadores, nunca substitui a referência
    observacional, nunca modifica dashboard/modelos/dados históricos."""

    def test_a_modulo_nunca_calcula_skill_nem_toca_dashboard(self):
        codigo = Path(aud.__file__).read_text()
        self.assertNotIn('import update_dashboard', codigo)
        self.assertNotIn('calcular_skill', codigo)
        self.assertNotIn('c3s_calibracao', codigo)

    def test_b_modulo_nunca_escreve_em_data(self):
        codigo = Path(aud.__file__).read_text()
        self.assertNotIn(".to_csv(CHIRPS_PONTO_PATH", codigo)
        self.assertNotIn(".to_csv(SERIE_PRODUCAO_PATH", codigo)

    def test_c_dry_run_nao_escreve_nada(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            original = aud.ARTIFACTS_DIR
            aud.ARTIFACTS_DIR = Path(tmp) / 'nunca_criado'
            try:
                aud.imprimir_plano()
                self.assertFalse(aud.ARTIFACTS_DIR.exists())
            finally:
                aud.ARTIFACTS_DIR = original


if __name__ == '__main__':
    unittest.main()
