#!/usr/bin/env python3
"""
tests/test_nmme_auditoria_observacional_historica.py — Fase 2C.2,
validação científica da referência observacional (centroide das
fazendas). Tudo offline — nenhuma rede, nenhuma execução de
scripts/update_dashboard.py (só leitura de texto). Fixtures sintéticas
para os achados isolados; alguns testes rodam contra os dados REAIS já
commitados (data/serie_subst.csv, data/master_monthly.csv,
data/nmme_historico_fazendas/) para confirmar que os números
reportados no relatório continuam batendo — mesmo padrão de
RealSerieObservacionalTestCase em test_nmme_piloto_historico.py.

Roda com:
    python -m unittest tests.test_nmme_auditoria_observacional_historica -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import nmme_auditoria_observacional_historica as aud  # noqa: E402
import nmme_piloto_historico as pilo  # noqa: E402


class PeriodoAlvoCompletoTestCase(unittest.TestCase):
    """Item 1 — o período exigido vai além da última origem, até o H6
    dela (não só até a última origem em si)."""

    def test_a_com_origens_reais_vai_ate_maio_2011(self):
        primeiro, ultimo = aud.periodo_alvo_completo()
        self.assertEqual(str(primeiro), '1991-01')
        self.assertEqual(str(ultimo), '2011-05')

    def test_b_generico_com_origens_customizadas(self):
        primeiro, ultimo = aud.periodo_alvo_completo(origens=((2000, 6),), leads=(1, 2, 3, 4, 5, 6))
        self.assertEqual(str(primeiro), '2000-06')
        self.assertEqual(str(ultimo), '2000-11')   # H6 = +5 meses


class CoberturaCalendarioTestCase(unittest.TestCase):
    """Item 1 — auditoria direta pelo calendário, independente da lente
    origem×lead."""

    def _serie_completa(self):
        linhas = []
        for periodo in pd.period_range('1991-01', '2011-05', freq='M'):
            linhas.append({'ano': periodo.year, 'mes': periodo.month, 'prec': 100.0, 'fonte': None})
        return pd.DataFrame(linhas)

    def test_a_serie_completa_sem_lacuna(self):
        resultado = aud.verificar_cobertura_calendario_bruta(self._serie_completa())
        self.assertTrue(resultado['cobertura_calendario_completa'])
        self.assertEqual(resultado['n_meses_ausentes'], 0)
        self.assertEqual(resultado['n_meses_duplicados'], 0)
        self.assertEqual(resultado['n_meses_esperados'], 245)

    def test_b_com_lacuna_detectada(self):
        serie = self._serie_completa()
        serie = serie[~((serie['ano'] == 2000) & (serie['mes'] == 6))]
        resultado = aud.verificar_cobertura_calendario_bruta(serie)
        self.assertFalse(resultado['cobertura_calendario_completa'])
        self.assertIn('2000-06', resultado['meses_ausentes'])
        self.assertEqual(resultado['n_meses_ausentes'], 1)

    def test_c_com_duplicata_detectada(self):
        serie = self._serie_completa()
        linha_dup = serie[(serie['ano'] == 2005) & (serie['mes'] == 3)]
        serie = pd.concat([serie, linha_dup], ignore_index=True)
        resultado = aud.verificar_cobertura_calendario_bruta(serie)
        self.assertFalse(resultado['cobertura_calendario_completa'])
        self.assertIn('2005-03', resultado['meses_duplicados'])

    def test_d_serie_real_sem_lacuna(self):
        """Sanidade contra o dado real commitado — deve bater com o
        que o relatório reporta (245 meses, 0 lacunas)."""
        resultado = aud.verificar_cobertura_calendario_bruta()
        self.assertEqual(resultado['n_meses_esperados'], 245)
        self.assertTrue(resultado['cobertura_calendario_completa'], resultado['meses_ausentes'])


class IdentidadeMerra2TestCase(unittest.TestCase):
    """Item 3 — achado numérico: idêntico pré-1996, divergente pós."""

    def test_a_identico_pre_1996_diverge_pos(self):
        with tempfile.TemporaryDirectory() as tmp:
            serie_path = Path(tmp) / 'serie.csv'
            master_path = Path(tmp) / 'master.csv'
            serie = pd.DataFrame([
                {'ano': 1994, 'mes': 1, 'prec': 100.0},
                {'ano': 1994, 'mes': 2, 'prec': 200.0},
                {'ano': 1996, 'mes': 1, 'prec': 50.0},   # Sinobras real, diverge de prec_reg
            ])
            master = pd.DataFrame([
                {'year': 1994, 'month': 1, 'prec_reg': 100.0},
                {'year': 1994, 'month': 2, 'prec_reg': 200.0},
                {'year': 1996, 'month': 1, 'prec_reg': 300.0},   # bem diferente do real Sinobras
            ])
            serie.to_csv(serie_path, index=False)
            master.to_csv(master_path, index=False)

            original_serie, original_master = aud.SERIE_OBSERVACIONAL_PATH, aud.MASTER_MONTHLY_PATH
            aud.SERIE_OBSERVACIONAL_PATH, aud.MASTER_MONTHLY_PATH = serie_path, master_path
            try:
                resultado = aud.verificar_identidade_merra2_com_master_monthly()
            finally:
                aud.SERIE_OBSERVACIONAL_PATH, aud.MASTER_MONTHLY_PATH = original_serie, original_master

            self.assertTrue(resultado['comparavel'])
            self.assertTrue(resultado['identico_numericamente_pre_1996'])
            self.assertFalse(resultado['fonte_original_comprovada'])
            self.assertTrue(resultado['diverge_pos_1996'])
            self.assertEqual(resultado['n_meses_comparados_pre_1996'], 2)
            self.assertEqual(resultado['n_meses_comparados_pos_1996'], 1)

    def test_b_master_ausente_reporta_nao_comparavel(self):
        original_master = aud.MASTER_MONTHLY_PATH
        aud.MASTER_MONTHLY_PATH = Path('/tmp/nao_existe_de_verdade_12345.csv')
        try:
            resultado = aud.verificar_identidade_merra2_com_master_monthly()
        finally:
            aud.MASTER_MONTHLY_PATH = original_master
        self.assertFalse(resultado['comparavel'])
        self.assertFalse(resultado['fonte_original_comprovada'])

    def test_c_dados_reais_confirmam_identidade_pre_1996(self):
        """Sanidade contra o dado real — o achado central do relatório
        (Seção 3) precisa continuar verdadeiro."""
        resultado = aud.verificar_identidade_merra2_com_master_monthly()
        self.assertTrue(resultado['comparavel'])
        self.assertTrue(resultado['identico_numericamente_pre_1996'])
        self.assertFalse(resultado['fonte_original_comprovada'])
        self.assertGreater(resultado['n_meses_comparados_pre_1996'], 0)


class BackfillPrecedePipelineAtualTestCase(unittest.TestCase):
    """Item 1 (2ª rodada) — verifica via git, nunca por suposição, que o
    backfill 1996-2010 já estava completo no primeiro commit do
    repositório, antes de qualquer execução do procedimento atual de
    scripts/update_dashboard.py."""

    def test_a_dados_reais_primeiro_commit_ja_completo(self):
        resultado = aud.verificar_dados_1996_2010_precedem_pipeline_atual()
        self.assertTrue(resultado['verificavel'])
        self.assertEqual(resultado['primeiro_commit'], '8a76a0fad509e14e00b25b635ba7261dc375996f')
        self.assertEqual(resultado['n_meses_esperado'], 180)
        self.assertEqual(resultado['n_meses_1996_2010_no_primeiro_commit'], 180)
        self.assertTrue(resultado['ja_completo_no_primeiro_commit'])

    def test_b_git_indisponivel_reporta_nao_verificavel(self):
        import subprocess as sp
        original_run = sp.run

        def _run_com_falha(*args, **kwargs):
            raise FileNotFoundError('git não encontrado (simulado)')

        aud.subprocess.run = _run_com_falha
        try:
            resultado = aud.verificar_dados_1996_2010_precedem_pipeline_atual()
        finally:
            aud.subprocess.run = original_run
        self.assertFalse(resultado['verificavel'])
        self.assertIn('motivo', resultado)


class NovaEvidenciaSinobrasPorFazendaTestCase(unittest.TestCase):
    """Item 6/7 (3ª rodada) — a nova evidência SINOBRAS.csv é citada
    aqui como um FATO formal já verificado por
    scripts/nmme_auditoria_sinobras_por_fazenda.py (rotina
    independente), nunca recalculada dentro deste módulo."""

    def test_a_achado_reflete_a_constante_evidencia(self):
        achado = aud.montar_achado_nova_evidencia_sinobras_por_fazenda()
        self.assertEqual(achado['sha256'], aud.EVIDENCIA_SINOBRAS_POR_FAZENDA['sha256'])
        self.assertEqual(achado['n_identificadores'], 34)
        self.assertEqual(achado['n_series_mensais_distintas'], 27)
        self.assertTrue(achado['integridade_estrutural_completa'])
        self.assertTrue(achado['reconciliacao_com_serie_producao_completa'])
        self.assertIn('REPRODUZIDA', achado['interpretacao'])
        self.assertIn('PARCIALMENTE', achado['interpretacao'])

    def test_b_wired_em_montar_achados_documentacao(self):
        doc = aud.montar_achados_documentacao()
        self.assertIn('nova_evidencia_sinobras_por_fazenda', doc)
        self.assertEqual(doc['nova_evidencia_sinobras_por_fazenda']['n_identificadores'], 34)

    def test_c_lista_de_documentos_reflete_evidencia_parcial(self):
        documentos = aud.montar_lista_documentos_necessarios()
        self.assertIn('PARCIALMENTE obtido', documentos[0])
        self.assertIn('SINOBRAS.csv', documentos[0])

    def test_d_correspondencia_espacial_registra_necessidade_de_coordenadas(self):
        """3ª/4ª rodada (ajuste pontual) — pede coordenada/pixel E o
        mapeamento identificador→instrumento; nunca presume que as 27
        séries distintas equivalem a 27 locais físicos independentes."""
        esp = aud.avaliar_correspondencia_espacial()
        self.assertIn('necessidade_de_coordenadas_individuais', esp)
        texto = esp['necessidade_de_coordenadas_individuais']
        self.assertIn('coordenada', texto)
        self.assertIn('mapeamento', texto)
        self.assertIn('pluviômetro', texto)
        self.assertIn('CHIRPS', texto)
        self.assertIn('NUNCA uma contagem de locais físicos OU pixels CHIRPS independentes', texto)

    def test_f_observacao_pos_1996_registra_34_em_todos_os_360_meses(self):
        """Ajuste pontual 1 (3ª rodada) — o arquivo histórico auditado
        tem EXATAMENTE 34 registros em todos os 360 meses; a
        possibilidade de contagem variável é do procedimento ATUAL de
        incorporação, não do histórico já analisado."""
        esp = aud.avaliar_correspondencia_espacial()
        texto = esp['observacao_pos_1996_e_area_ou_ponto']
        self.assertIn('EXATAMENTE 34', texto)
        self.assertIn('360 meses', texto)
        self.assertIn('VARIÁVEL', texto)
        self.assertIn('procedimento ATUAL', texto)

    def test_g_agregacao_sinobras_no_codigo_distingue_atual_de_historico(self):
        """Ajuste pontual 1 (3ª rodada) — mesma distinção no achado de
        leitura de código."""
        achado = aud.verificar_padrao_agregacao_sinobras_no_codigo()
        self.assertIn('NUNCA variou', achado['interpretacao'])
        self.assertIn('34', achado['interpretacao'])
        self.assertIn('360', achado['interpretacao'])

    def test_h_lista_de_documentos_pede_mapeamento_instrumento(self):
        """Ajuste pontual 3 (3ª rodada) — o item de coordenadas também
        pede o mapeamento identificador→instrumento, nunca presumindo
        27 séries distintas como 27 locais físicos independentes."""
        documentos = aud.montar_lista_documentos_necessarios()
        texto_coordenadas = documentos[1]
        self.assertIn('mapeamento', texto_coordenadas)
        self.assertIn('instrumento', texto_coordenadas)
        self.assertIn('não devem ser presumidas', texto_coordenadas)

    def test_e_nunca_le_o_arquivo_original_nesta_funcao(self):
        """A função só cita a constante EVIDENCIA_SINOBRAS_POR_FAZENDA
        (já verificada por scripts/nmme_auditoria_sinobras_por_fazenda.py)
        — nunca abre nem lê o arquivo original."""
        import inspect
        src = inspect.getsource(aud.montar_achado_nova_evidencia_sinobras_por_fazenda)
        self.assertNotIn('read_csv', src)
        self.assertNotIn('open(', src)


class ReinterpretacaoChirpsTestCase(unittest.TestCase):
    """Item 1/2/8 (4ª rodada, 2026) — correção explícita: o responsável
    pelos dados informou que SINOBRAS.csv é estimativa CHIRPS por
    fazenda, não leitura direta de pluviômetro. Testa que a correção
    foi registrada (não apagada), que a classificação anterior é
    citada, e que a aptidão científica reflete a nova informação."""

    def test_a_achado_registra_antes_e_depois(self):
        achado = aud.montar_achado_reinterpretacao_chirps()
        self.assertIn('leitura direta de campo', achado['classificacao_anterior_ate_3a_rodada'])
        self.assertIn('CHIRPS', achado['classificacao_corrigida_4a_rodada'])
        self.assertNotIn('leitura direta', achado['classificacao_corrigida_4a_rodada'])
        self.assertFalse(achado['fonte_verificada_documentalmente'])
        self.assertFalse(achado['empresa_possui_pluviometro_em_todas_as_fazendas'])

    def test_b_wired_em_montar_achados_documentacao(self):
        doc = aud.montar_achados_documentacao()
        self.assertIn('reinterpretacao_chirps', doc)
        self.assertEqual(doc['reinterpretacao_chirps']['classificacao_corrigida_4a_rodada'],
                          pilo.PROCEDENCIA_ESTACAO_SINOBRAS)

    def test_c_constante_procedencia_ja_reflete_chirps(self):
        """A correção de fundo é no reuso — PROCEDENCIA_ESTACAO_SINOBRAS
        em nmme_piloto_historico.py — nunca reimplementada aqui."""
        self.assertIn('CHIRPS', pilo.PROCEDENCIA_ESTACAO_SINOBRAS)
        self.assertIn('NÃO', pilo.PROCEDENCIA_ESTACAO_SINOBRAS)
        self.assertNotIn('leitura direta de campo', pilo.PROCEDENCIA_ESTACAO_SINOBRAS)

    def test_d_evidencia_sinobras_por_fazenda_tem_campos_chirps(self):
        ev = aud.EVIDENCIA_SINOBRAS_POR_FAZENDA
        self.assertFalse(ev['fonte_e_leitura_direta_de_pluviometro'])
        self.assertFalse(ev['fonte_verificada_documentalmente'])
        self.assertFalse(ev['empresa_possui_pluviometro_em_todas_as_fazendas'])
        self.assertEqual(ev['relatorio_chirps'], 'docs/nmme-fase2c2-auditoria-chirps-sinobras.md')

    def test_e_aptidao_recebe_o_parametro_chirps_nao_instrumental(self):
        """Item 8 (4ª rodada) — a chamada de aptidão do módulo principal
        passa procedencia_pos_1996_nao_instrumental=True, adicionando
        um bloqueio explícito sobre a fonte CHIRPS não verificada."""
        cobertura_df, metadata = aud.executar_auditoria_completa()
        aptidao = metadata['aptidao_referencia_observacional']
        self.assertFalse(aptidao['apto_para_avaliacao_cientifica'])
        self.assertTrue(any('estimativa CHIRPS' in m for m in aptidao['motivos_bloqueio']))

    def test_f_relatorio_markdown_inclui_secao_chirps(self):
        cobertura_df, metadata = aud.executar_auditoria_completa()
        relatorio = aud.gerar_relatorio_markdown(cobertura_df, metadata)
        self.assertIn('Reinterpretação CHIRPS', relatorio)
        self.assertIn('Classificação anterior', relatorio)
        self.assertIn('Classificação corrigida', relatorio)


class MontarListaDocumentosNecessariosTestCase(unittest.TestCase):
    """Item 4 (2ª rodada) — lista objetiva, não computada, do que falta
    para comprovar procedência histórica."""

    def test_a_lista_nao_vazia_de_strings_cobrindo_topicos_chave(self):
        documentos = aud.montar_lista_documentos_necessarios()
        self.assertIsInstance(documentos, list)
        self.assertGreater(len(documentos), 0)
        for item in documentos:
            self.assertIsInstance(item, str)
        texto_completo = ' '.join(documentos).lower()
        for topico in ('coordenadas', 'municipais', 'período', 'backfill', 'estações'):
            self.assertIn(topico, texto_completo)


class AnalisarDistribuicaoPre1996TestCase(unittest.TestCase):
    """Item 4 (2ª rodada) — distribuição real das combinações
    pré-1996, nunca suposta."""

    def _cobertura_sintetica(self):
        return pd.DataFrame([
            {'procedencia_documental': pilo.PROCEDENCIA_MERRA2, 'target_month': '1991-01',
             'origem_piloto': '1991-01', 'H_lead': 1},
            {'procedencia_documental': pilo.PROCEDENCIA_MERRA2, 'target_month': '1991-02',
             'origem_piloto': '1991-01', 'H_lead': 2},
            {'procedencia_documental': pilo.PROCEDENCIA_MERRA2, 'target_month': '1995-12',
             'origem_piloto': '1995-11', 'H_lead': 2},
            {'procedencia_documental': pilo.PROCEDENCIA_ESTACAO_SINOBRAS, 'target_month': '1996-06',
             'origem_piloto': '1996-05', 'H_lead': 2},
        ])

    def test_a_conta_so_procedencia_merra2(self):
        resultado = aud.analisar_distribuicao_pre_1996(self._cobertura_sintetica())
        self.assertEqual(resultado['n_total'], 3)
        self.assertEqual(resultado['por_ano_alvo']['1991'], 2)
        self.assertEqual(resultado['por_ano_alvo']['1995'], 1)
        self.assertEqual(resultado['por_h_lead'][1], 1)
        self.assertEqual(resultado['por_h_lead'][2], 2)

    def test_b_vazio_quando_sem_merra2(self):
        vazio = pd.DataFrame([
            {'procedencia_documental': pilo.PROCEDENCIA_ESTACAO_SINOBRAS, 'target_month': '1996-06',
             'origem_piloto': '1996-05', 'H_lead': 2},
        ])
        resultado = aud.analisar_distribuicao_pre_1996(vazio)
        self.assertEqual(resultado['n_total'], 0)

    def test_c_dados_reais_345_combinacoes_distribuidas(self):
        """Sanidade contra o dado real — corrige a alegação anterior
        (nunca checada) de concentração nos leads longos de 1991."""
        cobertura_df = aud.executar_auditoria_cobertura_por_origem_lead()
        resultado = aud.analisar_distribuicao_pre_1996(cobertura_df)
        self.assertEqual(resultado['n_total'], 345)
        self.assertEqual(sum(resultado['por_ano_alvo'].values()), 345)
        self.assertEqual(sum(resultado['por_h_lead'].values()), 345)
        # Nenhum ano-alvo isolado concentra a maioria das 345 combinações.
        for n in resultado['por_ano_alvo'].values():
            self.assertLess(n, 345 * 0.5)


class AnalisarDependenciaTemporalObservacoesTestCase(unittest.TestCase):
    """Item 2 (2ª rodada) — combinações origem×lead não são observações
    mensais independentes; o mesmo mês é reaproveitado como alvo por
    várias combinações."""

    def test_a_reuso_sintetico_calculado_corretamente(self):
        cobertura_df = pd.DataFrame({
            'target_month': ['2000-01', '2000-01', '2000-01', '2000-02'],
        })
        resultado = aud.analisar_dependencia_temporal_observacoes(cobertura_df)
        self.assertEqual(resultado['n_combinacoes_origem_lead'], 4)
        self.assertEqual(resultado['n_meses_observados_distintos'], 2)
        self.assertEqual(resultado['reuso_por_mes_max'], 3)
        self.assertEqual(resultado['reuso_por_mes_min'], 1)

    def test_b_dados_reais_1440_combinacoes_245_meses_distintos(self):
        """Sanidade contra o dado real — a base numérica do achado do
        item 2 desta rodada."""
        cobertura_df = aud.executar_auditoria_cobertura_por_origem_lead()
        resultado = aud.analisar_dependencia_temporal_observacoes(cobertura_df)
        self.assertEqual(resultado['n_combinacoes_origem_lead'], 1440)
        self.assertEqual(resultado['n_meses_observados_distintos'], 245)
        self.assertEqual(resultado['reuso_por_mes_max'], 6)


class AnalisarAmostraClimatologiaSinobrasApenasTestCase(unittest.TestCase):
    """Item 3 (2ª rodada) — sob a abordagem de janela expansível, uma
    climatologia restrita a registros Sinobras (>=1996) tem amostra
    pequena/zero nos primeiros anos avaliados."""

    def test_a_disponibilidade_calculada_por_ano_origem(self):
        resultado = aud.analisar_amostra_climatologia_sinobras_apenas(
            origens=((1991, 1), (1996, 1), (1997, 1), (2000, 1)))
        disp = resultado['anos_climatologia_sinobras_disponiveis_por_ano_origem']
        self.assertEqual(disp[1991], 0)
        self.assertEqual(disp[1996], 0)
        self.assertEqual(disp[1997], 1)
        self.assertEqual(disp[2000], 4)
        self.assertEqual(resultado['n_anos_origem_com_zero_anos_previos'], 2)

    def test_b_dados_reais_1996_e_1997_2000_2005_2010(self):
        resultado = aud.analisar_amostra_climatologia_sinobras_apenas()
        disp = resultado['anos_climatologia_sinobras_disponiveis_por_ano_origem']
        self.assertEqual(disp[1996], 0)
        self.assertEqual(disp[1997], 1)
        self.assertEqual(disp[2000], 4)
        self.assertEqual(disp[2005], 9)
        self.assertEqual(disp[2010], 14)


class AgregacaoSinobrasCodigoTestCase(unittest.TestCase):
    """Item 3 — achado por leitura de código, nunca por execução."""

    def test_a_padrao_encontrado_no_arquivo_real(self):
        resultado = aud.verificar_padrao_agregacao_sinobras_no_codigo()
        self.assertTrue(resultado['encontrado'])

    def test_b_nunca_importa_update_dashboard_como_modulo(self):
        """Estrutural — confirma que o módulo lê o arquivo como TEXTO
        (Path.read_text), nunca via import (que executaria a pipeline
        de produção inteira)."""
        import inspect
        src = inspect.getsource(aud.verificar_padrao_agregacao_sinobras_no_codigo)
        self.assertIn('read_text', src)
        self.assertNotIn('import update_dashboard', src)

    def test_c_arquivo_ausente_reporta_motivo(self):
        original = aud.UPDATE_DASHBOARD_PATH
        aud.UPDATE_DASHBOARD_PATH = Path('/tmp/nao_existe_de_verdade_67890.py')
        try:
            resultado = aud.verificar_padrao_agregacao_sinobras_no_codigo()
        finally:
            aud.UPDATE_DASHBOARD_PATH = original
        self.assertFalse(resultado['encontrado'])
        self.assertIn('motivo', resultado)


class DistanciaGradeCfsv2TestCase(unittest.TestCase):
    """Item 4 — distância lida diretamente do RAW persistido, nunca
    resuposta."""

    def test_a_valor_constante_entre_lotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            for lote_id in ('a', 'b'):
                pd.DataFrame({'grid_distance_km': [22.91, 22.91, 22.91]}).to_csv(
                    diretorio / f'lote_{lote_id}_raw.csv', index=False)
            dist = aud.distancia_grade_cfsv2_fazendas_km(diretorio=diretorio)
            self.assertEqual(dist, 22.91)

    def test_b_divergencia_entre_lotes_lanca_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            pd.DataFrame({'grid_distance_km': [22.91]}).to_csv(diretorio / 'lote_a_raw.csv', index=False)
            pd.DataFrame({'grid_distance_km': [30.0]}).to_csv(diretorio / 'lote_b_raw.csv', index=False)
            with self.assertRaises(RuntimeError):
                aud.distancia_grade_cfsv2_fazendas_km(diretorio=diretorio)

    def test_c_diretorio_vazio_lanca_erro_explicito(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                aud.distancia_grade_cfsv2_fazendas_km(diretorio=Path(tmp))

    def test_d_dados_reais_confirmam_22_91km(self):
        """Sanidade contra o dado real persistido pela extração
        histórica aprovada (run 36238169299)."""
        dist = aud.distancia_grade_cfsv2_fazendas_km()
        self.assertAlmostEqual(dist, 22.91, delta=0.5)


class AlinhamentoTemporalTestCase(unittest.TestCase):
    """Item 5 — H1-H6 confirmado a partir do temporal_audit persistido."""

    def _escrever_temporal(self, diretorio, origem, mapping_ok=True):
        ano, mes = origem
        linhas = []
        for lead in range(1, 7):
            alvo = pd.Period(f'{ano}-{mes:02d}', 'M') + (lead - 1)
            linhas.append({'origem_piloto': f'{ano}-{mes:02d}', 'H_lead': lead,
                             'target_month': str(alvo),
                             'mapping_status': 'OK' if mapping_ok else 'DIVERGENTE'})
        pd.DataFrame(linhas).to_csv(diretorio / 'lote_x_temporal_audit.csv', index=False)

    def test_a_tudo_ok_e_h1_igual_mes_inicializacao(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            self._escrever_temporal(diretorio, (2000, 1))
            resultado = aud.verificar_alinhamento_temporal(diretorio=diretorio)
            self.assertTrue(resultado['todas_ok'])
            self.assertTrue(resultado['h1_igual_mes_inicializacao_confirmado'])
            self.assertEqual(resultado['origem_alvo_mais_distante'], '2000-06')

    def test_b_mapping_divergente_e_detectado(self):
        with tempfile.TemporaryDirectory() as tmp:
            diretorio = Path(tmp)
            self._escrever_temporal(diretorio, (2000, 1), mapping_ok=False)
            resultado = aud.verificar_alinhamento_temporal(diretorio=diretorio)
            self.assertFalse(resultado['todas_ok'])

    def test_c_dados_reais_1440_combinacoes_ok(self):
        resultado = aud.verificar_alinhamento_temporal()
        self.assertEqual(resultado['n_combinacoes_origem_lead'], 1440)
        self.assertEqual(resultado['n_esperado'], 1440)
        self.assertTrue(resultado['todas_ok'])
        self.assertTrue(resultado['h1_igual_mes_inicializacao_confirmado'])


class IdentificarPeriodosUtilizaveisTestCase(unittest.TestCase):
    """Item 6 — separa por procedência, nunca mistura."""

    def _cobertura(self):
        return pd.DataFrame([
            {'disponibilidade': 'PRESENTE', 'fonte_e_substituta_nao_usar': False,
             'qualidade_verificada_status': pilo.QUALIDADE_STATUS_OK,
             'procedencia_documental': pilo.PROCEDENCIA_MERRA2},
            {'disponibilidade': 'PRESENTE', 'fonte_e_substituta_nao_usar': False,
             'qualidade_verificada_status': pilo.QUALIDADE_STATUS_OK,
             'procedencia_documental': pilo.PROCEDENCIA_ESTACAO_SINOBRAS},
            {'disponibilidade': 'PRESENTE', 'fonte_e_substituta_nao_usar': True,
             'qualidade_verificada_status': pilo.QUALIDADE_STATUS_OK,
             'procedencia_documental': pilo.PROCEDENCIA_CHC_PRELIMINAR},
            {'disponibilidade': 'AUSENTE', 'fonte_e_substituta_nao_usar': False,
             'qualidade_verificada_status': pilo.QUALIDADE_STATUS_NAO_APLICAVEL_AUSENTE,
             'procedencia_documental': None},
        ])

    def test_a_exclui_ausentes_e_substitutas(self):
        resultado = aud.identificar_periodos_utilizaveis(self._cobertura())
        self.assertEqual(resultado['n_total_combinacoes'], 4)
        self.assertEqual(resultado['n_disponivel_e_qualidade_ok'], 2)
        self.assertEqual(
            resultado['combinacoes_utilizaveis_por_procedencia'][pilo.PROCEDENCIA_MERRA2], 1)
        self.assertEqual(
            resultado['combinacoes_utilizaveis_por_procedencia'][pilo.PROCEDENCIA_ESTACAO_SINOBRAS], 1)


class AvaliarCorrespondenciaEspacialTestCase(unittest.TestCase):
    def test_a_com_dados_reais_melhoria_positiva(self):
        resultado = aud.avaliar_correspondencia_espacial()
        self.assertLess(resultado['distancia_grade_cfsv2_ate_centroide_km'],
                         resultado['distancia_sao_bento_ate_centroide_km_referencia_anterior'])
        self.assertGreater(resultado['melhoria_vs_sao_bento_km'], 100)


class AuditoriaCompletaEndToEndTestCase(unittest.TestCase):
    """Fim a fim contra os dados reais — confirma que a orquestração
    inteira roda sem erro e produz um veredito nunca silenciosamente
    'apto', dado que a distância espacial (ainda que pequena) e as
    lacunas de documentação continuam presentes."""

    def test_a_executa_sem_erro_e_nunca_declara_apto_as_cegas(self):
        cobertura_df, metadata = aud.executar_auditoria_completa()
        self.assertEqual(len(cobertura_df), 1440)
        self.assertFalse(metadata['aptidao_referencia_observacional']['apto_para_avaliacao_cientifica'])
        self.assertTrue(metadata['nenhuma_skill_calculada'])
        self.assertTrue(metadata['nenhum_dashboard_alterado'])
        self.assertTrue(metadata['nenhum_modelo_climatico_alterado'])

    def test_b_relatorio_markdown_gerado_sem_erro(self):
        cobertura_df, metadata = aud.executar_auditoria_completa()
        relatorio = aud.gerar_relatorio_markdown(cobertura_df, metadata)
        self.assertIn('apto_para_avaliacao_cientifica', relatorio)
        self.assertIn('Protocolo estatístico proposto', relatorio)
        self.assertIn('janela expansível', relatorio)
        self.assertIn('meses observados', relatorio)
        self.assertIn('fonte original comprovada', relatorio)
        self.assertIn('Documentos necessários', relatorio)


class ReusoDeInfraestruturaTestCase(unittest.TestCase):
    """Estrutural — confirma reuso (nunca reimplementação) das funções
    já testadas do piloto."""

    def test_a_usa_verificar_cobertura_observacional_sem_reimplementar(self):
        import inspect
        src = inspect.getsource(aud.executar_auditoria_cobertura_por_origem_lead)
        self.assertIn('pilo.verificar_cobertura_observacional', src)

    def test_b_usa_avaliar_aptidao_sem_reimplementar(self):
        import inspect
        src = inspect.getsource(aud.executar_auditoria_completa)
        self.assertIn('pilo.avaliar_aptidao_referencia_observacional', src)

    def test_c_usa_leadtime_para_mes_alvo_nmme_sem_formula_nova(self):
        import inspect
        src = inspect.getsource(aud.periodo_alvo_completo)
        self.assertIn('nproc.leadtime_para_mes_alvo_nmme', src)


class ZeroSkillNuncaModificaDashboardTestCase(unittest.TestCase):
    def test_a_modulo_nunca_importa_dashboard_ou_calibracao(self):
        codigo = Path(aud.__file__).read_text()
        self.assertNotIn('import update_dashboard', codigo)
        self.assertNotIn('c3s_calibracao', codigo)
        self.assertNotIn('calcular_skill', codigo)

    def test_b_metadata_declara_restricoes(self):
        _, metadata = aud.executar_auditoria_completa()
        self.assertTrue(metadata['nenhuma_skill_calculada'])
        self.assertTrue(metadata['nenhum_dashboard_alterado'])
        self.assertTrue(metadata['nenhum_modelo_climatico_alterado'])

    def test_c_dry_run_nao_escreve_nada(self):
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
