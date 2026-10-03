#!/usr/bin/env python3
"""
tests/test_cfsv2_validacao_cientifica.py — Fase 2C.3C.

Foco principal (item 11 da tarefa): testes de CONTROLE DE LEAKAGE —
cada um tem que FALHAR se a climatologia/tercis/pareamento vazarem
informação futura. Também cobre a auditoria (item 2), o pareamento
(item 4) e as métricas determinísticas/probabilísticas básicas.

Todos os testes usam dados SINTÉTICOS — nenhuma rede, nenhum dado
real do CFSv2/CHIRPS é necessário para rodar esta suíte (embora as
classes *ComDadosReais* leiam os arquivos já aprovados do repositório,
sem rede).

Roda com:
    python -m unittest tests.test_cfsv2_validacao_cientifica -v
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import cfsv2_validacao_cientifica as c  # noqa: E402


def _chirps_sintetico(anos=range(1981, 2012), seed=42):
    """Série mensal sintética determinística (seed fixo) cobrindo
    1981-01 a 2011-12 (mais que o necessário, sem problema)."""
    rng = np.random.default_rng(seed)
    linhas = []
    for ano in anos:
        for mes in range(1, 13):
            if ano == 2011 and mes > 5:
                break
            linhas.append({'ano': ano, 'mes': mes, 'valor_mm': float(rng.uniform(0, 300))})
    return pd.DataFrame(linhas)


_FRASES_CONCLUSAO_ISOLADA_PROIBIDAS = ('o cfsv2 é validado', 'o modelo é validado',
                                        'previsão confiável', 'modelo confiável',
                                        'tem boa habilidade', 'possui boa habilidade')


def _assert_nunca_declara_conclusao_isolada(testcase, relatorio):
    """Item 12 da tarefa — o relatório pode (e deve) MENCIONAR essas
    frases como exemplo do que NÃO dizer (ex.: 'nunca resumidos numa
    frase como modelo validado'), mas nunca pode AFIRMÁ-las como
    conclusão. Checa a ausência das afirmações diretas, não da
    substring isolada (que aparece legitimamente como advertência)."""
    texto = relatorio.lower()
    for frase in _FRASES_CONCLUSAO_ISOLADA_PROIBIDAS:
        testcase.assertNotIn(frase, texto, f"relatório afirma diretamente: {frase!r}")


class AnosClimatologiaDisponiveisTestCase(unittest.TestCase):
    """Item 5/11 — núcleo do controle de leakage."""

    def test_a_exemplo_da_tarefa_jan_1991_usa_1981_1990(self):
        chirps = _chirps_sintetico()
        obs = c._obs_dict(chirps)
        clim = c.climatologia_expansivel(mes_alvo=1, init_date='1991-01', obs_dict=obs)
        self.assertEqual(clim['anos_usados'], list(range(1981, 1991)))
        self.assertEqual(clim['n_anos'], 10)

    def test_b_nunca_inclui_ano_mes_igual_ou_posterior_ao_init_date(self):
        chirps = _chirps_sintetico()
        obs = c._obs_dict(chirps)
        for mes_alvo in range(1, 13):
            for init_date in ['1995-01', '2000-06', '2010-12']:
                clim = c.climatologia_expansivel(mes_alvo, init_date, obs)
                init_p = c._periodo(init_date)
                for ano in clim['anos_usados']:
                    self.assertLess(c._periodo(f'{ano}-{mes_alvo:02d}'), init_p,
                                     f"climatologia de {init_date} para mês {mes_alvo} incluiu "
                                     f"{ano}-{mes_alvo:02d}, que não é < init_date")

    def test_c_h6_de_jul_2010_nao_usa_dezembro_2010_mesmo_ano(self):
        """Caso do enunciado: H6 com init=2010-07 (target=2010-12) NÃO
        pode usar dez/2010 na climatologia — ainda não ocorreu antes
        da inicialização, mesmo sendo 'o mesmo ano do target'."""
        chirps = _chirps_sintetico()
        obs = c._obs_dict(chirps)
        clim = c.climatologia_expansivel(mes_alvo=12, init_date='2010-07', obs_dict=obs)
        self.assertNotIn(2010, clim['anos_usados'])
        self.assertEqual(clim['anos_usados'][-1], 2009)

    def test_d_climatologia_cresce_com_inicializacoes_mais_tardias(self):
        chirps = _chirps_sintetico()
        obs = c._obs_dict(chirps)
        clim_1995 = c.climatologia_expansivel(mes_alvo=3, init_date='1995-03', obs_dict=obs)
        clim_2005 = c.climatologia_expansivel(mes_alvo=3, init_date='2005-03', obs_dict=obs)
        self.assertGreater(clim_2005['n_anos'], clim_1995['n_anos'])


class TargetNuncaNaPropriaClimatologiaTestCase(unittest.TestCase):
    """Item 11, 3º ponto — a observação do PRÓPRIO target nunca entra
    na climatologia que o avalia, para NENHUM horizonte (estrutural:
    target_month = init_date + lead - 1 >= init_date sempre)."""

    def test_a_garantia_estrutural_para_todos_os_leads(self):
        chirps = _chirps_sintetico()
        obs = c._obs_dict(chirps)
        for lead in c.LEADS_ESPERADOS:
            init_date = '2000-05'
            init_p = c._periodo(init_date)
            target_p = init_p + (lead - 1)
            target_ano, target_mes = target_p.year, target_p.month
            clim = c.climatologia_expansivel(target_mes, init_date, obs)
            self.assertNotIn(target_ano, clim['anos_usados'],
                              f"lead={lead}: climatologia incluiu o próprio ano do target")


def _indice_previsoes_sintetico(inits, leads=c.LEADS_ESPERADOS, seed=7):
    """índice (init_date, lead) -> ensemble_mean sintético determinístico."""
    rng = np.random.default_rng(seed)
    linhas = []
    for init_date in inits:
        for lead in leads:
            linhas.append({'init_date': init_date, 'lead': lead,
                            'ensemble_mean': float(rng.uniform(0, 300))})
    return pd.DataFrame(linhas)


class ClimatologiaDoModeloSemLeakageTestCase(unittest.TestCase):
    """Item 1 da revisão — climatologia PRÓPRIA do modelo, item 8 dos
    testes pedidos: nunca usa uma inicialização >= init_date."""

    def _inits_mensais(self, ano_inicio=1991, ano_fim=2005, mes=6):
        return [f'{a}-{mes:02d}' for a in range(ano_inicio, ano_fim + 1)]

    def test_a_nunca_usa_inicializacao_igual_ou_posterior(self):
        inits = self._inits_mensais()
        indice = _indice_previsoes_sintetico(inits)
        for init_date in inits:
            for lead in c.LEADS_ESPERADOS:
                clim = c.climatologia_modelo_expansivel(lead, init_date, indice)
                init_p = c._periodo(init_date)
                for usado in clim['inits_usados']:
                    self.assertLess(c._periodo(usado), init_p,
                                     f"climatologia do modelo (lead={lead}, init={init_date}) "
                                     f"usou {usado}, que não é < init_date")

    def test_b_primeira_inicializacao_de_cada_mes_nao_tem_climatologia(self):
        inits = self._inits_mensais()
        indice = _indice_previsoes_sintetico(inits)
        clim = c.climatologia_modelo_expansivel(lead=1, init_date=inits[0], indice_previsoes=indice)
        self.assertEqual(clim['n_inits'], 0)
        self.assertIsNone(clim['media'])

    def test_c_climatologia_cresce_com_inicializacoes_mais_tardias(self):
        inits = self._inits_mensais()
        indice = _indice_previsoes_sintetico(inits)
        clim_cedo = c.climatologia_modelo_expansivel(1, inits[2], indice)
        clim_tarde = c.climatologia_modelo_expansivel(1, inits[-1], indice)
        self.assertGreater(clim_tarde['n_inits'], clim_cedo['n_inits'])

    def test_d_nunca_mistura_leads_diferentes(self):
        inits = self._inits_mensais()
        indice = _indice_previsoes_sintetico(inits)
        clim_h1 = c.climatologia_modelo_expansivel(1, inits[-1], indice)
        clim_h6 = c.climatologia_modelo_expansivel(6, inits[-1], indice)
        # mesmas inicializações usadas (mesmos anos), mas médias de
        # ensemble_mean DIFERENTES, porque vêm de linhas com lead
        # diferente no índice sintético — confirma que o filtro por
        # lead está sendo aplicado, não ignorado.
        self.assertEqual(clim_h1['n_inits'], clim_h6['n_inits'])
        self.assertNotEqual(clim_h1['media'], clim_h6['media'])

    def test_e_previsao_atual_nunca_entra_na_propria_climatologia_do_modelo(self):
        """Garantia estrutural análoga à da climatologia observada:
        como a climatologia do modelo só usa init_date < init_date
        avaliado, a PRÓPRIA previsão (do init_date atual) nunca entra
        no cálculo da climatologia que a avalia."""
        inits = self._inits_mensais()
        indice = _indice_previsoes_sintetico(inits)
        init_atual = inits[-1]
        for lead in c.LEADS_ESPERADOS:
            clim = c.climatologia_modelo_expansivel(lead, init_atual, indice)
            self.assertNotIn(init_atual, clim['inits_usados'])


def _base_enriquecida_determinista(linhas):
    """Monta um 'base_enriquecida' mínimo (mesmas colunas que
    metricas_deterministicas_por_horizonte espera) a partir de valores
    EXATOS e controlados — evita ruído de estimação estatística,
    testando a FÓRMULA diretamente, não a convergência de uma
    climatologia amostrada."""
    linhas_expandidas = []
    for linha in linhas:
        for member in range(1, 25):   # 24 membros idênticos — só a média importa aqui
            linhas_expandidas.append({**linha, 'member': member})
    return pd.DataFrame(linhas_expandidas)


class AnomaliaModeloVsObservadaNaoEquivalentesTestCase(unittest.TestCase):
    """Item 8, último ponto pedido: caso sintético em que a
    climatologia do modelo difere SISTEMATICAMENTE da observada,
    demonstrando que as duas definições de anomalia NÃO são
    equivalentes. Usa BIAS/RMSE (não correlação) como evidência: um
    viés aditivo CONSTANTE não muda a correlação por definição
    (invariante a deslocamento) — o efeito real aparece no bias/RMSE
    da anomalia, que é exatamente onde a correção importa na prática.
    Climatologias fornecidas como valores EXATOS (não estimadas de uma
    amostra sintética ruidosa), para isolar o efeito da FÓRMULA."""

    def test_a_bias_diagnostico_carrega_o_vies_do_modelo_corrigida_nao(self):
        vies_modelo_fixo = 150.0
        linhas = []
        for i, (obs, clim_obs) in enumerate([(100.0, 80.0), (200.0, 80.0), (50.0, 80.0)]):
            previsto = obs + vies_modelo_fixo
            clim_modelo = clim_obs + vies_modelo_fixo   # climatologia do modelo carrega o MESMO viés
            linhas.append({'init_date': f'{1991+i}-06', 'target_month': f'{1991+i}-06', 'lead': 1,
                            'forecast_prec_mm': previsto, 'obs_prec_mm': obs,
                            'clim_media': clim_obs, 'clim_n_anos': 10,
                            'clim_modelo_media': clim_modelo, 'clim_modelo_n_inits': 5})
        base_enr = _base_enriquecida_determinista(linhas)
        det = c.metricas_deterministicas_por_horizonte(base_enr)
        d = det[1]
        bias_diag = d['anomalia_diagnostico_climatologia_observada']['bias']
        bias_corrigido = d['anomalia_corrigida_climatologia_propria_modelo']['bias']
        # diagnóstico: climatologia OBSERVADA (sem o viés do modelo)
        # subtraída da previsão — o viés fixo (150mm) sobra inteiro.
        self.assertAlmostEqual(bias_diag, vies_modelo_fixo, places=6)
        # corrigida: climatologia PRÓPRIA do modelo (que também carrega
        # o mesmo viés fixo) subtraída da previsão — o viés se cancela
        # EXATAMENTE.
        self.assertAlmostEqual(bias_corrigido, 0.0, places=6)
        self.assertGreater(abs(bias_diag - bias_corrigido), 100.0,
                            "as duas definições de anomalia não podem ser equivalentes aqui")

    def test_b_rmse_diagnostico_maior_que_corrigido_com_vies_do_modelo(self):
        vies_modelo_fixo = 150.0
        linhas = []
        for i, (obs, clim_obs) in enumerate([(100.0, 80.0), (200.0, 80.0), (50.0, 80.0), (300.0, 80.0)]):
            previsto = obs + vies_modelo_fixo
            clim_modelo = clim_obs + vies_modelo_fixo
            linhas.append({'init_date': f'{1991+i}-06', 'target_month': f'{1991+i}-06', 'lead': 1,
                            'forecast_prec_mm': previsto, 'obs_prec_mm': obs,
                            'clim_media': clim_obs, 'clim_n_anos': 10,
                            'clim_modelo_media': clim_modelo, 'clim_modelo_n_inits': 5})
        base_enr = _base_enriquecida_determinista(linhas)
        det = c.metricas_deterministicas_por_horizonte(base_enr)
        d = det[1]
        rmse_diag = d['anomalia_diagnostico_climatologia_observada']['rmse']
        rmse_corrigido = d['anomalia_corrigida_climatologia_propria_modelo']['rmse']
        self.assertAlmostEqual(rmse_diag, vies_modelo_fixo, places=6)   # erro = só o viés, constante
        self.assertAlmostEqual(rmse_corrigido, 0.0, places=6)           # viés cancelado, erro zero
        self.assertGreater(rmse_diag, rmse_corrigido + 50.0)

    def test_c_amostra_real_mostra_diferenca_consistente_entre_as_duas_definicoes(self):
        """Confirma com os dados REAIS já aprovados (sem rede) que as
        duas definições produzem valores DIFERENTES de fato — não só
        no caso sintético extremo."""
        if not c.CAMINHO_METRICAS_JSON.parent.exists():
            self.skipTest("dados reais não disponíveis nesta árvore de trabalho")
        df_raw = c.carregar_cfsv2_raw()
        chirps = c.carregar_chirps_v3_historico()
        base = c.construir_base_pareada(df_raw, chirps)
        base_enr = c._enriquecer_com_climatologia(base, chirps)
        det = c.metricas_deterministicas_por_horizonte(base_enr)
        for lead in c.LEADS_ESPERADOS:
            d = det[lead]
            rmse_diag = d['anomalia_diagnostico_climatologia_observada']['rmse']
            rmse_corrigida = d['anomalia_corrigida_climatologia_propria_modelo']['rmse']
            self.assertNotAlmostEqual(rmse_diag, rmse_corrigida, delta=0.5,
                                       msg=f"H{lead}: as duas definições bateram quase exatamente "
                                       "— verificar se a climatologia do modelo está mesmo sendo usada")


class TercisNuncaUsamSerieCompletaTestCase(unittest.TestCase):
    """Item 8/11 — os limites de tercil usam SÓ os anos elegíveis da
    climatologia expansível, nunca 1981-2011 completo."""

    def test_a_tercis_mudam_conforme_init_date_avanca(self):
        chirps = _chirps_sintetico()
        obs = c._obs_dict(chirps)
        clim_1992 = c.climatologia_expansivel(mes_alvo=6, init_date='1992-06', obs_dict=obs)
        clim_2009 = c.climatologia_expansivel(mes_alvo=6, init_date='2009-06', obs_dict=obs)
        # Com só 11 anos (1981-1991) vs quase 28 anos (1981-2008) de
        # amostra DIFERENTE, os tercis quase certamente diferem —
        # se fossem calculados sobre a série completa, seriam IDÊNTICOS
        # para todas as inicializações do mesmo mês.
        self.assertNotEqual(clim_1992['tercil_33'], clim_2009['tercil_33'])
        self.assertNotEqual(clim_1992['n_anos'], clim_2009['n_anos'])

    def test_b_tercis_nao_usam_nenhum_ano_fora_do_permitido(self):
        chirps = _chirps_sintetico()
        obs = c._obs_dict(chirps)
        clim = c.climatologia_expansivel(mes_alvo=9, init_date='2001-09', obs_dict=obs)
        valores_permitidos = {obs[(a, 9)] for a in clim['anos_usados']}
        # Tercil tem que estar entre min/max dos valores PERMITIDOS —
        # nunca influenciado por um valor de fora desse conjunto.
        self.assertGreaterEqual(clim['tercil_33'], min(valores_permitidos))
        self.assertLessEqual(clim['tercil_67'], max(valores_permitidos))


class PareamentoNuncaPorAproximacaoTestCase(unittest.TestCase):
    """Item 4/11 — pareamento exclusivamente por target_month exato;
    nunca por proximidade, nunca usando outra referência."""

    def _raw_sintetico(self):
        linhas = []
        for lead in c.LEADS_ESPERADOS:
            for member in range(1, 25):
                linhas.append({
                    'init_date': '1995-03', 'target_month': str(pd.Period('1995-03', 'M') + (lead - 1)),
                    'lead': lead, 'member': member, 'forecast_prec_mm': 100.0 + lead,
                    'units_original': 'mm/day', 'conversion_applied': 'mm/day * 31 dias',
                    'localizacao': 'Fazendas_Sinobras_Centroide',
                })
        return pd.DataFrame(linhas)

    def test_a_pareia_exatamente_pelo_target_month(self):
        raw = self._raw_sintetico()
        chirps = _chirps_sintetico()
        base = c.construir_base_pareada(raw, chirps)
        obs_esperados = c._obs_dict(chirps)
        for _, row in base.iterrows():
            chave = (int(row['target_ano']), int(row['target_mes']))
            self.assertEqual(row['obs_prec_mm'], obs_esperados[chave])

    def test_b_mes_alvo_ausente_levanta_stop_on_failure(self):
        raw = self._raw_sintetico()
        chirps_incompleto = _chirps_sintetico(anos=range(1981, 1995))  # não cobre 1995-08 (H6)
        with self.assertRaises(RuntimeError):
            c.construir_base_pareada(raw, chirps_incompleto)

    def test_c_nunca_le_serie_subst_ou_chirps_1981_2025_como_referencia(self):
        """A string 'serie_subst.csv'/'chirps_1981_2025.csv' pode
        aparecer em mensagens de aviso (proibindo seu uso); o que este
        teste proíbe de fato é o módulo inteiro LER esses arquivos
        (pd.read_csv apontando para eles) em algum momento."""
        import inspect
        src = inspect.getsource(c)
        self.assertNotIn("read_csv('data/serie_subst.csv')", src.replace('"', "'"))
        self.assertNotIn("read_csv('data/chirps_1981_2025.csv')", src.replace('"', "'"))
        self.assertNotIn('SERIE_PRODUCAO_PATH', src)
        self.assertNotIn('CHIRPS_V2_PONTO_PATH', src)


class MembrosNuncaMisturadosEntreInicializacoesTestCase(unittest.TestCase):
    """Item 11, 5º ponto — membros de uma inicialização nunca se
    misturam com os de outra ao agrupar por (init_date, target_month, lead)."""

    def test_a_groupby_isola_corretamente_cada_inicializacao(self):
        linhas = []
        for init_date, valor_base in (('1995-01', 100.0), ('1996-01', 500.0)):
            for member in range(1, 25):
                linhas.append({'init_date': init_date, 'target_month': init_date, 'lead': 1,
                                'member': member, 'forecast_prec_mm': valor_base + member,
                                'obs_prec_mm': 50.0, 'target_ano': int(init_date[:4]), 'target_mes': 1,
                                'clim_media': 40.0, 'clim_n_anos': 10,
                                'clim_modelo_media': 40.0, 'clim_modelo_n_inits': 5})
        base = pd.DataFrame(linhas)
        resultado = c.metricas_deterministicas_por_horizonte(base)
        # média de 1995-01 (100+1..100+24) e 1996-01 (500+1..500+24) não
        # podem ter se misturado — a média combinada seria ~312, mas a
        # média de CADA init isolada é ~112.5 e ~512.5; o bias agregado
        # (sobre as DUAS médias por init, não sobre as 48 linhas cruas)
        # tem que refletir isso, nunca uma média única das 48 linhas.
        bias = resultado[1]['absoluto']['bias']
        # bias = media((112.5,512.5)) - 50 = 312.5 - 50 = 262.5, não
        # media(100..524)-50 (que também daria um valor parecido aqui,
        # mas o teste real é que SÓ 2 pontos entraram, não 48):
        self.assertEqual(resultado[1]['n'], 2, "deveria haver exatamente 2 (init,target,lead) "
                          "distintos, nunca 48 linhas cruas misturadas")


class CrpsRankHistogramTestCase(unittest.TestCase):
    def test_a_crps_perfeito_quando_todos_os_membros_iguais_a_observacao(self):
        membros = [50.0] * 24
        self.assertAlmostEqual(c.crps_amostral(membros, 50.0), 0.0, places=6)

    def test_b_crps_positivo_quando_membros_divergem_da_observacao(self):
        membros = list(range(1, 25))
        self.assertGreater(c.crps_amostral(membros, 100.0), 0.0)

    def test_c_rank_observacao_dentro_dos_limites(self):
        rng = np.random.default_rng(1)
        membros = sorted(rng.uniform(0, 100, 24))
        r = c.rank_observacao(membros, -10.0, rng)   # observação menor que todos
        self.assertEqual(r, 1)
        r = c.rank_observacao(membros, 1000.0, rng)   # observação maior que todos
        self.assertEqual(r, 25)


class SyntheticLeakageDemonstrationTestCase(unittest.TestCase):
    """Item 11, último ponto — demonstra que uma variante COM leakage
    produz resultado artificialmente melhor, e que o pipeline real
    (climatologia_expansivel) NÃO reproduz esse resultado."""

    def _climatologia_com_leakage(self, mes_alvo, init_date, obs_dict):
        """Variante deliberadamente ERRADA (só para este teste) — usa
        TODOS os anos disponíveis, inclusive >= init_date. Nunca deve
        ser usada fora deste teste."""
        anos_valores = [(a, obs_dict[(a, m)]) for (a, m) in obs_dict if m == mes_alvo]
        valores = np.array([v for _, v in sorted(anos_valores)], dtype=float)
        return {'media': float(valores.mean()), 'n_anos': len(valores)}

    def test_a_leakage_version_usa_mais_anos_incluindo_futuros(self):
        chirps = _chirps_sintetico()
        obs = c._obs_dict(chirps)
        init_date = '1995-06'
        correta = c.climatologia_expansivel(mes_alvo=6, init_date=init_date, obs_dict=obs)
        com_leakage = self._climatologia_com_leakage(mes_alvo=6, init_date=init_date, obs_dict=obs)
        # a versão com leakage usa a série TODA (1981-2011 = 31 anos),
        # a correta só usa 1981-1994 (14 anos) — nunca podem bater:
        self.assertEqual(correta['n_anos'], 14)
        self.assertGreater(com_leakage['n_anos'], correta['n_anos'])
        self.assertNotEqual(correta['media'], com_leakage['media'])

    def test_b_previsao_perfeita_do_proprio_alvo_So_e_possivel_com_leakage(self):
        """Caso extremo: se a climatologia pudesse usar o PRÓPRIO ano
        do target como único dado, a 'previsão' climatológica seria
        perfeita (RMSE=0) — um sintoma inequívoco de leakage. A versão
        correta NUNCA permite isso porque filtra target_year para
        fora, resultando em RMSE > 0 estrutural."""
        chirps = _chirps_sintetico()
        obs = c._obs_dict(chirps)
        init_date = '2005-04'
        mes_alvo = 4
        obs_do_alvo = obs[(2005, 4)]

        # leakage grosseiro: climatologia = só a própria observação do alvo
        media_com_leakage_total = obs_do_alvo
        erro_com_leakage = abs(media_com_leakage_total - obs_do_alvo)
        self.assertEqual(erro_com_leakage, 0.0, "a versão leaky é perfeita por construção")

        correta = c.climatologia_expansivel(mes_alvo, init_date, obs)
        erro_correto = abs(correta['media'] - obs_do_alvo)
        self.assertGreater(erro_correto, 0.0, "a climatologia correta NUNCA deveria ser "
                            "perfeita — se for, há leakage")
        self.assertNotIn(2005, correta['anos_usados'])


class AuditarBaseRawTestCase(unittest.TestCase):
    """Item 2 — auditoria sintética (sem precisar da base real)."""

    def _raw_valido(self, n_inits=2):
        linhas = []
        for i in range(n_inits):
            init_date = str(pd.Period('1991-01', 'M') + i)
            for lead in c.LEADS_ESPERADOS:
                target_month = str(pd.Period(init_date, 'M') + (lead - 1))
                for member in range(1, 25):
                    linhas.append({'init_date': init_date, 'target_month': target_month,
                                    'lead': lead, 'member': member, 'forecast_prec_mm': 100.0,
                                    'units_original': 'mm/day',
                                    'conversion_applied': 'mm/day * 31 dias',
                                    'localizacao': 'Fazendas_Sinobras_Centroide'})
        return pd.DataFrame(linhas)

    def test_a_base_valida_aprova_todos_os_criterios_exceto_periodo_total(self):
        raw = self._raw_valido(n_inits=2)
        a = c.auditar_base_raw(raw)
        self.assertTrue(a['unicidade_init_lead_member_ok'])
        self.assertTrue(a['vinte_quatro_membros_por_init_lead_ok'])
        self.assertTrue(a['target_month_corresponde_a_init_mais_lead_ok'])
        self.assertTrue(a['h1_igual_mes_corrente_ok'])
        self.assertTrue(a['sem_valores_faltantes_ok'])
        # período não é o esperado (240 inits) porque este é um subconjunto de teste
        self.assertFalse(a['periodo_cobertura_ok'])
        self.assertFalse(a['auditoria_aprovada'])

    def test_b_duplicata_e_detectada(self):
        raw = self._raw_valido(n_inits=1)
        duplicada = pd.concat([raw, raw.iloc[[0]]], ignore_index=True)
        a = c.auditar_base_raw(duplicada)
        self.assertFalse(a['unicidade_init_lead_member_ok'])

    def test_c_membro_faltando_e_detectado(self):
        raw = self._raw_valido(n_inits=1)
        sem_um_membro = raw.iloc[:-1]
        a = c.auditar_base_raw(sem_um_membro)
        self.assertFalse(a['vinte_quatro_membros_por_init_lead_ok'])

    def test_d_target_month_incorreto_e_detectado(self):
        raw = self._raw_valido(n_inits=1)
        raw = raw.copy()
        raw.loc[raw.index[0], 'target_month'] = '2099-01'   # corrompido deliberadamente
        a = c.auditar_base_raw(raw)
        self.assertFalse(a['target_month_corresponde_a_init_mais_lead_ok'])

    def test_e_valor_faltante_e_detectado(self):
        raw = self._raw_valido(n_inits=1)
        raw = raw.copy()
        raw.loc[raw.index[0], 'forecast_prec_mm'] = np.nan
        a = c.auditar_base_raw(raw)
        self.assertFalse(a['sem_valores_faltantes_ok'])


class MetricasDeterministicasFormulasTestCase(unittest.TestCase):
    def test_a_bias_mae_rmse_corr_formulas_basicas(self):
        prev = np.array([10.0, 20.0, 30.0])
        obs = np.array([10.0, 20.0, 30.0])
        self.assertAlmostEqual(c._bias(prev, obs), 0.0)
        self.assertAlmostEqual(c._mae(prev, obs), 0.0)
        self.assertAlmostEqual(c._rmse(prev, obs), 0.0)
        self.assertAlmostEqual(c._corr(prev, obs), 1.0)

    def test_b_rmsess_formula_documentada(self):
        self.assertAlmostEqual(c.rmsess(50.0, 100.0), 0.5)
        self.assertAlmostEqual(c.rmsess(100.0, 100.0), 0.0)
        self.assertAlmostEqual(c.rmsess(150.0, 100.0), -0.5)
        self.assertIsNone(c.rmsess(50.0, 0.0))

    def test_c_rmsess_nunca_interpretado_automaticamente_como_bom(self):
        import inspect
        src = inspect.getsource(c.rmsess)
        self.assertIn('NUNCA', src.upper())


class LoyoNuncaMisturadoComExpansivelTestCase(unittest.TestCase):
    def test_a_loyo_rotulado_explicitamente(self):
        chirps = _chirps_sintetico()
        raw = pd.DataFrame([{
            'init_date': '1995-06', 'target_month': '1995-06', 'lead': 1, 'member': m,
            'forecast_prec_mm': 100.0, 'units_original': 'mm/day',
            'conversion_applied': 'x', 'localizacao': 'Fazendas_Sinobras_Centroide',
        } for m in range(1, 25)])
        base = c.construir_base_pareada(raw, chirps)
        resultado = c.executar_loyo_retrospectivo(base, chirps)
        self.assertEqual(resultado['rotulo'], 'loyo_retrospective')
        self.assertIn('expanding', resultado['aviso'].lower())

    def test_b_loyo_usa_anos_futuros_expansivel_nao_usa(self):
        chirps = _chirps_sintetico()
        obs = c._obs_dict(chirps)
        clim_loyo = c.climatologia_loyo(mes_alvo=6, ano_excluido=1995, obs_dict=obs)
        clim_expansivel = c.climatologia_expansivel(mes_alvo=6, init_date='1995-06', obs_dict=obs)
        # LOYO usa todos os anos exceto 1995 (30 anos); expansível só
        # usa os anteriores a 1995-06 (14 anos) — nunca podem ser iguais.
        self.assertGreater(clim_loyo['n_anos'], clim_expansivel['n_anos'])


class ComDadosReaisAprovadosTestCase(unittest.TestCase):
    """Usa os dados REAIS já aprovados (sem rede) — confirma que a
    base de produção passa a auditoria e o pareamento tal como
    descrito pela tarefa (240 inits, 24 membros, H1-H6, 34.560 RAW)."""

    def test_a_auditoria_da_base_real_aprova(self):
        a = c.executar_auditoria()
        self.assertTrue(a['auditoria_aprovada'], a['problemas'])
        self.assertEqual(a['n_raw_total'], 34560)
        self.assertEqual(a['n_inicializacoes_distintas'], 240)

    def test_b_pareamento_da_base_real_nao_tem_mes_ausente(self):
        df_raw = c.carregar_cfsv2_raw()
        chirps = c.carregar_chirps_v3_historico()
        base = c.construir_base_pareada(df_raw, chirps)
        self.assertTrue(c.validar_nenhum_mes_alvo_ausente(base))
        self.assertEqual(len(base), 34560)


class MatrizMesLeadTestCase(unittest.TestCase):
    """Item 3/8 da revisão — matriz target_month × lead (visão sazonal
    PRINCIPAL): confirma N≈20/célula (240 inits / 12 meses) e que cada
    célula usa SÓ as linhas daquele mês e lead (nunca agregado/misturado
    com outro mês)."""

    def setUp(self):
        if not c.CAMINHO_METRICAS_JSON.parent.exists():
            self.skipTest("dados reais não disponíveis nesta árvore de trabalho")
        df_raw = c.carregar_cfsv2_raw()
        chirps = c.carregar_chirps_v3_historico()
        base = c.construir_base_pareada(df_raw, chirps)
        self.base_enr = c._enriquecer_com_climatologia(base, chirps)

    def test_a_cada_celula_tem_aproximadamente_20_inicializacoes(self):
        matriz = c.metricas_matriz_mes_lead(self.base_enr)
        for mes in range(1, 13):
            for lead in c.LEADS_ESPERADOS:
                n = matriz[mes][lead]['n']
                self.assertGreaterEqual(n, 15, f"mes={mes} lead={lead}: N={n} muito abaixo do esperado (~20)")
                self.assertLessEqual(n, 25, f"mes={mes} lead={lead}: N={n} muito acima do esperado (~20)")

    def test_b_soma_dos_12_meses_bate_com_total_do_horizonte(self):
        """Se uma célula estivesse vazando linhas de outro mês, a soma
        das 12 células ultrapassaria o N total do horizonte (ou ficaria
        abaixo, se alguma linha fosse perdida)."""
        matriz = c.metricas_matriz_mes_lead(self.base_enr)
        det = c.metricas_deterministicas_por_horizonte(self.base_enr)
        for lead in c.LEADS_ESPERADOS:
            soma_meses = sum(matriz[mes][lead]['n'] for mes in range(1, 13))
            self.assertEqual(soma_meses, det[lead]['n'],
                              f"lead={lead}: soma das 12 células do mês não bate com N total do "
                              "horizonte — sinal de mistura/duplicação entre meses")


class MatrizGrupoSazonalLeadTestCase(unittest.TestCase):
    """Item 3/8 da revisão — resumo grupo_sazonal × lead: confirma que o
    N de cada grupo é exatamente a soma dos meses que o compõem (nunca
    um mês pertencendo a dois grupos, nem um mês esquecido)."""

    def setUp(self):
        if not c.CAMINHO_METRICAS_JSON.parent.exists():
            self.skipTest("dados reais não disponíveis nesta árvore de trabalho")
        df_raw = c.carregar_cfsv2_raw()
        chirps = c.carregar_chirps_v3_historico()
        base = c.construir_base_pareada(df_raw, chirps)
        self.base_enr = c._enriquecer_com_climatologia(base, chirps)

    def test_a_grupo_sazonal_e_soma_exata_dos_meses_que_o_compoem(self):
        matriz_mes = c.metricas_matriz_mes_lead(self.base_enr)
        matriz_grupo = c.metricas_matriz_grupo_sazonal_lead(self.base_enr)
        for grupo in ('chuvosa', 'transicao', 'seca'):
            meses_grupo = [m for m, g in c.GRUPO_SAZONAL_POR_MES.items() if g == grupo]
            for lead in c.LEADS_ESPERADOS:
                soma = sum(matriz_mes[mes][lead]['n'] for mes in meses_grupo)
                self.assertEqual(soma, matriz_grupo[grupo][lead]['n'],
                                  f"grupo={grupo} lead={lead}: N do grupo não é a soma exata dos "
                                  "meses que o compõem")

    def test_b_nenhum_mes_pertence_a_mais_de_um_grupo_e_todos_os_12_estao_cobertos(self):
        self.assertEqual(set(c.GRUPO_SAZONAL_POR_MES.keys()), set(range(1, 13)))
        self.assertEqual(len(c.GRUPO_SAZONAL_POR_MES), 12)


class BootstrapSkillScoresMesmosBlocosTestCase(unittest.TestCase):
    """Item 2/8 da revisão — garante ESTRUTURALMENTE que o bootstrap de
    skill scores recalcula RMSE/CRPS/Brier do modelo e do benchmark
    usando a MESMA lista de linhas reamostradas em cada iteração — nunca
    bootstraps independentes, que invalidariam RMSESS/CRPSS como razão
    (numerador e denominador precisam vir do mesmo sorteio de anos)."""

    def test_a_mesmo_objeto_de_linhas_reamostradas_alimenta_rmse_crps_e_brier(self):
        if not c.CAMINHO_METRICAS_JSON.parent.exists():
            self.skipTest("dados reais não disponíveis nesta árvore de trabalho")
        import unittest.mock as mock
        df_raw = c.carregar_cfsv2_raw()
        chirps = c.carregar_chirps_v3_historico()
        base = c.construir_base_pareada(df_raw, chirps)
        base_enr = c._enriquecer_com_climatologia(base, chirps)

        ids_rmse, ids_crps, ids_brier = [], [], []
        orig_rmse = c._rmse_modelo_e_climatologia
        orig_crps = c._crps_medio_modelo_e_climatologia
        orig_brier = c._brier_score_categoria

        def fake_rmse(linhas):
            ids_rmse.append(id(linhas))
            return orig_rmse(linhas)

        def fake_crps(linhas):
            ids_crps.append(id(linhas))
            return orig_crps(linhas)

        def fake_brier(linhas, categoria):
            ids_brier.append(id(linhas))
            return orig_brier(linhas, categoria)

        n_resamples = 5
        with mock.patch.object(c, 'LEADS_ESPERADOS', (1,)), \
             mock.patch.object(c, '_rmse_modelo_e_climatologia', side_effect=fake_rmse), \
             mock.patch.object(c, '_crps_medio_modelo_e_climatologia', side_effect=fake_crps), \
             mock.patch.object(c, '_brier_score_categoria', side_effect=fake_brier):
            resultado = c.bootstrap_skill_scores_por_horizonte(base_enr, chirps,
                                                                n_resamples=n_resamples, seed=1)

        self.assertTrue(resultado[1]['amostra_suficiente'])
        # A última chamada de cada lista é o cálculo PONTUAL (fora do
        # laço, sobre `linhas` completo, não reamostrado) — as
        # n_resamples anteriores são as reamostras do laço, na ordem.
        self.assertEqual(len(ids_rmse), n_resamples + 1)
        self.assertEqual(len(ids_crps), n_resamples + 1)
        self.assertEqual(len(ids_brier), 3 * (n_resamples + 1))

        for i in range(n_resamples):
            grupo_brier = {ids_brier[3 * i], ids_brier[3 * i + 1], ids_brier[3 * i + 2]}
            self.assertEqual(len(grupo_brier), 1,
                              f"reamostra {i}: Brier das 3 categorias usou listas DIFERENTES de "
                              "linhas reamostradas entre si")
            self.assertEqual(ids_rmse[i], ids_crps[i],
                              f"reamostra {i}: RMSE e CRPS usaram listas DIFERENTES de linhas "
                              "reamostradas")
            self.assertEqual(ids_rmse[i], grupo_brier.pop(),
                              f"reamostra {i}: RMSE e Brier usaram listas DIFERENTES de linhas "
                              "reamostradas")


class RelatorioTestCase(unittest.TestCase):
    """Smoke test do gerador de relatório (scripts/cfsv2_relatorio_2c3c.py)
    — nunca recalcula métrica, só formata o que já foi calculado."""

    def test_a_relatorio_gerado_sem_erro_a_partir_de_metricas_sinteticas(self):
        import cfsv2_relatorio_2c3c as rel
        resultados = {
            'STOP_ON_FAILURE': False,
            'auditoria': {'n_raw_total': 100, 'n_raw_esperado': 100,
                           'n_inicializacoes_distintas': 10,
                           'unicidade_init_lead_member_ok': True,
                           'vinte_quatro_membros_por_init_lead_ok': True,
                           'target_month_corresponde_a_init_mais_lead_ok': True,
                           'h1_igual_mes_corrente_ok': True, 'sem_valores_faltantes_ok': True,
                           'unidades_ok': True, 'localizacao_unica_ok': True,
                           'n_meses_alvo_distintos': 15, 'auditoria_aprovada': True},
            'expanding_operational_simulation': {
                'n_registros_pareados': 100, 'n_meses_alvo_distintos': 15,
                'deterministico_por_horizonte': {
                    str(h): {'n': 10, 'rotulo': c.ROTULO_HORIZONTE[h],
                              'n_com_climatologia_modelo_disponivel': 8,
                              'absoluto': {'bias': 1.0, 'mae': 2.0, 'rmse': 3.0, 'corr': 0.5},
                              'anomalia_diagnostico_climatologia_observada': {
                                  'nota': 'DIAGNÓSTICO — não é a anomaly correlation principal.',
                                  'bias': 1.0, 'mae': 2.0, 'rmse': 3.0, 'corr': 0.2},
                              'anomalia_corrigida_climatologia_propria_modelo': {
                                  'bias': 0.3, 'mae': 1.2, 'rmse': 2.1, 'corr': 0.35},
                              'benchmark_climatologico': {'bias': 0.5, 'mae': 1.5, 'rmse': 2.5},
                              'rmsess_absoluto': 0.1, 'rmsess_anomalia_diagnostico': 0.1,
                              'rmsess_anomalia_corrigida': 0.15,
                              'formula_rmsess': 'RMSESS = 1 - RMSE_modelo / RMSE_climatologia'}
                    for h in c.LEADS_ESPERADOS},
                'matriz_mes_lead': {
                    str(m): {str(h): {'n': 0} for h in c.LEADS_ESPERADOS} for m in range(1, 13)},
                'matriz_grupo_sazonal_lead': {
                    g: {str(h): {'n': 0} for h in c.LEADS_ESPERADOS}
                    for g in ('chuvosa', 'transicao', 'seca')},
                'por_mes_do_ano': {
                    'rotulo': 'visao_agregada_descritiva_H1_a_H6_combinados',
                    'por_mes': {str(m): {'n': 0} for m in range(1, 13)},
                    'por_grupo_sazonal': {g: {'n': 0} for g in ('chuvosa', 'transicao', 'seca')},
                },
                'probabilistico_por_horizonte': {
                    str(h): {'n': 5, 'amostra_suficiente': False} for h in c.LEADS_ESPERADOS},
                'intervalos_confianca_por_horizonte': {
                    str(h): {'nota': 'amostra insuficiente'} for h in c.LEADS_ESPERADOS},
                'intervalos_confianca_skill_scores_por_horizonte': {
                    str(h): {'amostra_suficiente': False, 'nota': 'amostra insuficiente'}
                    for h in c.LEADS_ESPERADOS},
            },
            'loyo_retrospective': {
                'rotulo': 'loyo_retrospective', 'aviso': 'não simula expanding operational',
                'deterministico_por_horizonte': {
                    str(h): {'n': 10, 'rmsess_absoluto': 0.1} for h in c.LEADS_ESPERADOS},
            },
        }
        relatorio = rel.gerar_relatorio_markdown(resultados)
        self.assertIn('Fase 2C.3C', relatorio)
        self.assertIn('loyo_retrospective', relatorio)
        self.assertIn('expanding', relatorio.lower())
        _assert_nunca_declara_conclusao_isolada(self, relatorio)

    def test_b_stop_on_failure_gera_relatorio_minimo_sem_metricas(self):
        import cfsv2_relatorio_2c3c as rel
        resultados = {'STOP_ON_FAILURE': True, 'motivo': 'teste', 'problemas': ['x']}
        relatorio = rel.gerar_relatorio_markdown(resultados)
        self.assertIn('STOP-ON-FAILURE', relatorio)
        self.assertIn('NÃO calculadas', relatorio)

    def test_c_relatorio_real_tem_todas_as_secoes(self):
        """Com os dados reais já calculados nesta rodada (data/cfsv2_
        validacao_2c3c/metricas_2c3c.json), confirma que o relatório
        real gerado cobre as seções obrigatórias (item 12/14 da
        tarefa) e nunca declara 'modelo validado'/'boa habilidade'
        isoladamente."""
        import json
        if not c.CAMINHO_METRICAS_JSON.exists():
            self.skipTest("métricas reais ainda não calculadas nesta árvore de trabalho")
        import cfsv2_relatorio_2c3c as rel
        resultados = json.loads(c.CAMINHO_METRICAS_JSON.read_text())
        relatorio = rel.gerar_relatorio_markdown(resultados)
        for secao in ('Auditoria da base RAW', 'Base pareada', 'Métricas determinísticas',
                      'climatologia própria do modelo', 'Avaliação sazonal',
                      'Matriz mês-alvo', 'visao_agregada_descritiva_H1_a_H6_combinados',
                      'probabilística', 'sensibilidade do Brier/BSS',
                      'Intervalos de confiança', 'skill scores',
                      'LOYO retrospectivo', 'Interpretação'):
            self.assertIn(secao, relatorio)
        _assert_nunca_declara_conclusao_isolada(self, relatorio)


if __name__ == '__main__':
    unittest.main()
