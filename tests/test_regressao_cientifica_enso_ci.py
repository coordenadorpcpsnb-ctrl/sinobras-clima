#!/usr/bin/env python3
"""
tests/test_regressao_cientifica_enso_ci.py — Fase ENSO-CI (19/10/2026).

Mapa dos 10 cenários de regressão real pedidos para o novo CI
(cada um já causou um bug real documentado no projeto, não é
hipotético). A maioria já tinha teste dedicado em fases anteriores —
este arquivo só acrescenta os que faltavam e documenta onde estão os
outros, para o Job C do CI apontar para um lugar único.

 1. Deslocamento indevido dos meses de precipitação/ETP
    (CLAUDE.md armadilha 1) — SEM teste fixture-based até esta fase
    (só proteção em runtime via verificar_dashboard.py, nunca testada
    contra um HTML deliberadamente quebrado). NOVO nesta fase:
    DeslocamentoDeMesesNuncaPassaSemDetectarTestCase.
 2. Série Niño 3.4 semanal incluída indevidamente como mensal
    — tests/test_update_indices.py (bug real do parser wksst
    corrigido na Fase ENSO-AUTO, ver CLAUDE.md armadilha 9).
 3. Comparação CPC×IRI entre trimestres diferentes
    — tests/test_gerar_relatorio.py::ResumoDivergenciaCpcIriTestCase
    (bug real do zip() corrigido na Fase ENSO-AUTO).
 4. Conversão indevida de null em zero
    — tests/test_enso_iri_set2026.py::NullComoAusenciaNuncaZeroTestCase
    e test_gerar_relatorio.py (CLAUDE.md armadilha 4).
 5. Substituição de emissão oficial recente por emissão antiga
    — tests/test_update_indices_enso_auto.py::RegressaoEmissaoCpcProbabilidadesTestCase
    e ValidacaoObrigatoriaEmissaoCpcTestCase (Correção 1, Fase ENSO-AUTO).
 6. Datas e metadados inconsistentes
    — tests/test_update_indices_enso_auto.py (consistência emissão×
    trimestres, _emissao_e_trimestres_consistentes) e
    tests/test_verificar_dashboard_enso_auto.py (5 categorias de
    defasagem).
 7. Modificação acidental de resultados científicos durante
    atualização de índices
    — tests/test_enso_iri_set2026.py::PreservacaoDeModelosCientificosTestCase
    (blocos SARIMAX_DATA/BH byte-a-byte idênticos; roda tanto no
    Job B quanto explicitamente de novo no Job C deste CI).
 8. Falha de fonte externa apagando dados válidos
    — tests/test_fetch_fallback.py (fallback CHIRPS→Open-Meteo) e
    CLAUDE.md armadilha 6 (persistência de TSA/PDO, nunca grava 0.0).
 9. Mudanças em HTML destruindo objetos/arrays não relacionados
    (CLAUDE.md armadilha 2, re.sub global) — SEM teste até esta fase
    (só a disciplina documentada em CLAUDE.md, nunca verificada
    automaticamente que os padrões usados por update_dashboard.py
    continuam únicos no HTML real). NOVO nesta fase:
    PadroesDeSubstituicaoPermanecemUnicosTestCase.
10. Alteração da trajetória IRI antiga sem atualização dos metadados
    — tests/test_enso_iri_set2026.py::TrajetoriaPreservadaTestCase e
    MetaIriEmissaoTestCase::test_d_separacao_emissao_trajetoria.

Tudo offline, fixtures locais e/ou o próprio docs/index.html real
já commitado — nenhuma rede, nenhuma recalibração de SARIMAX/XGBoost
(scripts/update_dashboard.py nunca é executado, só seu OUTPUT já
commitado é lido).

Roda com:
    python -m unittest tests.test_regressao_cientifica_enso_ci -v
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import verificar_dashboard as vd  # noqa: E402

DASHBOARD_REAL = ROOT / 'docs' / 'index.html'
HTML_REAL = DASHBOARD_REAL.read_text(encoding='utf-8')


class DeslocamentoDeMesesNuncaPassaSemDetectarTestCase(unittest.TestCase):
    """Cenário 1 — réplica fiel da armadilha 1 real (CLAUDE.md): a
    precipitação do horizonte é rotacionada "para alinhar" enquanto a
    ETP e os rótulos do eixo não — o ARM desliza sem erro visível no
    JS. Usa o docs/index.html REAL como base (replicar à mão toda a
    estrutura que verificar_dashboard.py exige arriscaria um fixture
    incompleto falhando por motivo errado) e rotaciona só `fc_clim`
    em 1 posição, mantendo fc_labels intacto — exatamente o padrão do
    bug histórico."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp_html = Path(self._tmpdir.name) / 'index.html'
        self._dashboard_original = vd.DASHBOARD

    def tearDown(self):
        vd.DASHBOARD = self._dashboard_original
        vd.falhas.clear()
        self._tmpdir.cleanup()

    def _rodar_com(self, html):
        self._tmp_html.write_text(html, encoding='utf-8')
        vd.DASHBOARD = self._tmp_html
        vd.falhas.clear()
        cod = vd.main(pular_continuidade_serie_subst=True)
        return cod, list(vd.falhas)

    def test_a_fc_clim_rotacionado_e_detectado(self):
        m = re.search(r'fc_clim:\[([^\]]+)\]', HTML_REAL)
        self.assertIsNotNone(m, 'fc_clim não encontrado no docs/index.html real')
        valores = [v.strip() for v in m.group(1).split(',')]
        self.assertEqual(len(valores), 12)
        rotacionado = valores[1:] + valores[:1]
        self.assertNotEqual(valores, rotacionado,
                             'rotação precisa mudar a sequência para ser um teste válido')
        html_quebrado = HTML_REAL.replace(
            m.group(0), f'fc_clim:[{",".join(rotacionado)}]', 1)

        cod, falhas = self._rodar_com(html_quebrado)

        self.assertEqual(cod, 1, f'HTML com fc_clim rotacionado deveria reprovar; falhas: {falhas}')
        self.assertTrue(
            any('fc_clim' in f and 'desalinhado' in f for f in falhas),
            f'rotação de fc_clim não foi detectada como desalinhamento; falhas registradas: {falhas}')

    def test_b_html_real_nao_aciona_esse_alarme(self):
        # sanity: o HTML real, sem mutação, não deve disparar ESSE
        # alarme específico de desalinhamento.
        _cod, falhas = self._rodar_com(HTML_REAL)
        self.assertFalse(
            any('desalinhado' in f for f in falhas),
            f'o próprio HTML real do repositório não deveria disparar alarme de desalinhamento: {falhas}')


class PadroesDeSubstituicaoPermanecemUnicosTestCase(unittest.TestCase):
    """Cenário 9 — réplica da armadilha 2 real (CLAUDE.md): um
    `re.sub` sem `count=1` sobre o HTML inteiro só é seguro enquanto o
    padrão casar exatamente uma vez. scripts/update_dashboard.py usa
    vários `re.sub(..., html)` (sem count=1, operando sobre o HTML
    completo, não sobre um bloco já delimitado por `html.find(...)`)
    confiando nessa unicidade — nunca verificada automaticamente até
    esta fase. Este teste NÃO executa update_dashboard.py (isso
    recalcularia SARIMAX/XGBoost, fora do permitido nesta fase): só
    confirma, de forma estática, que cada padrão crítico ainda casa
    exatamente 1 vez no docs/index.html real e commitado — se um
    editor futuro (humano ou script) introduzir uma segunda
    ocorrência da mesma chave em outro lugar do arquivo, o próximo
    `update_dashboard.py` corromperia silenciosamente um array não
    relacionado, e este teste reprova ANTES disso virar produção."""

    # (nome, padrão, origem em update_dashboard.py)
    PADROES_DEVEM_SER_UNICOS = [
        ('annual',        r'annual:\{years:.*?maximo:\[\d+,[\d.]+\]\}',            'sub() helper, count=1 — mas depende de padrão único mesmo assim'),
        ('clim mean/std', r'clim:\s*\{\s*mean:\[[^\]]+\],\s*std:\[[^\]]+\]\s*\}',  'sub() helper, count=1'),
        ('fc_labels',     r'fc_labels:\[[^\]]+\]',                                 're.sub sem count=1, HTML inteiro'),
        ('fc_clim',       r'fc_clim:\[[^\]]+\]',                                   're.sub sem count=1, HTML inteiro'),
        ('CLIM_WIN',      r'const CLIM_WIN\s*=\s*\[[^\]]+\]',                      're.sub sem count=1, HTML inteiro'),
        ('CLIM_MON',      r'const CLIM_MON\s*=\s*\[[^\]]+\]',                      're.sub sem count=1, HTML inteiro'),
        ('nino_seasons',  r'nino_seasons:\[[^\]]+\]',                              're.sub sem count=1, HTML inteiro'),
        ('BH_LABELS_HYD', r'BH_LABELS_HYD\s*=\s*[^;\n]+',                          're.sub sem count=1, HTML inteiro'),
        ('BH_CLIM_HYD bloco', r'/\* BH_CLIM_HYD.*?BH_CLIM_HYD = \{.*?\};',          're.sub sem count=1, DOTALL, HTML inteiro'),
        ('ETP pré-rotada (buildBhEtrComp)', r'// ETP pré-rotada.*?\n  const etp = \[[^\]]+\];', 're.sub sem count=1, HTML inteiro'),
        ('SARIMAX_DATA',  r'const SARIMAX_DATA = \{.*?\};',                        're.sub sem count=1, DOTALL, HTML inteiro'),
        ('etp_jan_dez',   r'etp_jan_dez:\s*\[[^\]]+\]',                            're.sub sem count=1, HTML inteiro'),
        ('etp_jul_jun',   r'etp_jul_jun:\s*\[[^\]]+\]',                            're.sub sem count=1, HTML inteiro'),
    ]

    def test_a_cada_padrao_critico_casa_exatamente_uma_vez(self):
        falhas = []
        for nome, padrao, _origem in self.PADROES_DEVEM_SER_UNICOS:
            n = len(re.findall(padrao, HTML_REAL, flags=re.DOTALL))
            if n != 1:
                falhas.append(f'{nome}: {n} ocorrência(s) (esperado 1)')
        self.assertEqual(
            falhas, [],
            'padrão(ões) de substituição de update_dashboard.py deixaram de ser '
            'únicos no HTML real — risco de corromper um array não relacionado '
            'na próxima atualização (CLAUDE.md armadilha 2): ' + '; '.join(falhas))

    def test_b_regiao_bh_block_e_delimitada_antes_de_qualquer_substituicao_interna(self):
        # As substituições de def_total/exc_total por cenário (ver
        # update_dashboard.py) operam sobre bh_block, uma substring já
        # isolada por html.find('const BH = {')..find(delimitador) —
        # o padrão recomendado pelo CLAUDE.md armadilha 2 ("delimite a
        # região primeiro"). Confirma que esse delimitador ainda
        # existe e ainda isola uma região não-vazia (e não
        # absurdamente grande — sinal de delimitador quebrado
        # casando com -1, ver correção do mesmo bug em
        # verificar_dashboard.py nesta fase) no HTML real. O
        # cabeçalho real usa traço DUPLO (══, padrão de seção
        # principal — MONITOR/PREVISÃO/CLIMA/PLANO usam o mesmo),
        # nunca traço simples (──, reservado a headers de bloco
        # local como "── CONSTANTES ──").
        bh_s = HTML_REAL.find('const BH = {')
        bh_e = HTML_REAL.find('\n\n/* ══ BALANÇO HÍDRICO COMPARATIVO', bh_s)
        self.assertGreater(bh_s, 0, 'const BH = { não encontrado')
        self.assertGreater(bh_e, bh_s, 'delimitador de fim de BH não encontrado após o início')
        self.assertGreater(bh_e - bh_s, 100, 'região de BH delimitada parece vazia ou truncada')
        self.assertLess(bh_e - bh_s, 50000,
                         'região de BH delimitada parece absurdamente grande — sinal de que '
                         'o delimitador não casou (find retornando -1) e a fatia está '
                         'incluindo quase o arquivo inteiro por acidente')


class CenariosJaCobertosPorOutrosArquivosSmokeTestCase(unittest.TestCase):
    """Sentinela leve (não redundante com a cobertura profunda já
    existente): confirma que os módulos/classes citados no mapa do
    docstring deste arquivo ainda existem e são importáveis — se um
    deles for removido ou renomeado sem querer, o mapa de cobertura
    acima fica desatualizado silenciosamente. Não reexecuta a lógica
    detalhada (isso é papel dos próprios arquivos, já rodados pelo
    Job A/B/C)."""

    def test_a_classes_de_protecao_citadas_existem(self):
        import importlib
        checagens = [
            ('tests.test_update_indices_enso_auto', 'RegressaoEmissaoCpcProbabilidadesTestCase', None),
            ('tests.test_gerar_relatorio', 'ResumoDivergenciaCpcIriTestCase', None),
            ('tests.test_enso_iri_set2026', 'NullComoAusenciaNuncaZeroTestCase', None),
            ('tests.test_enso_iri_set2026', 'PreservacaoDeModelosCientificosTestCase', None),
            ('tests.test_enso_iri_set2026', 'TrajetoriaPreservadaTestCase', None),
            ('tests.test_verificar_dashboard_enso_auto', 'DefasagemCincoCategoriasTestCase', None),
            ('tests.test_fetch_fallback', None, None),
        ]
        ausentes = []
        for modulo, classe, _ in checagens:
            try:
                mod = importlib.import_module(modulo)
            except ImportError as e:
                ausentes.append(f'{modulo}: módulo não importável ({e})')
                continue
            if classe is not None and not hasattr(mod, classe):
                ausentes.append(f'{modulo}.{classe}: classe não encontrada')
        self.assertEqual(
            ausentes, [],
            'mapa de cobertura dos 10 cenários científicos ficou desatualizado: '
            + '; '.join(ausentes))


if __name__ == '__main__':
    unittest.main()
