#!/usr/bin/env python3
"""
tests/test_enso_iri_set2026.py — Fase ENSO-IRI (15/10/2026): cobre a
atualização das probabilidades de fase IRI (Quick Look de set/2026,
publicado 21/09/2026) no bloco `CPC_IRI` de docs/index.html, a
preservação da trajetória mensal do Niño 3.4 (não atualizada nesta
fase) e as correções de renderização encontradas na aba Comparativo
(deslocamento fixo desatualizado em rebuildCmpNino, literal "null%" e
código morto em buildCmpTable).

Esta suíte só lê/parseia docs/index.html por regex (mesmo estilo de
scripts/gerar_relatorio.py e scripts/update_indices.py) — não há parser
JS neste projeto, e `CPC_IRI` continua sendo 100% curado à mão (CLAUDE.md
armadilha 3/4), nunca gerado por scripts/update_dashboard.py.

Roda com:
    python -m unittest tests.test_enso_iri_set2026 -v
"""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
DASHBOARD = ROOT / 'docs' / 'index.html'


def _html():
    return DASHBOARD.read_text(encoding='utf-8')


def _bloco_cpc_iri(html):
    m = re.search(r'const CPC_IRI = \{.*?\n\};', html, re.DOTALL)
    assert m, 'const CPC_IRI não encontrado em docs/index.html'
    return m.group(0)


def _bloco_meta(html):
    bloco = _bloco_cpc_iri(html)
    m = re.search(r'_meta:\s*\{(.*?)\n  \},', bloco, re.DOTALL)
    assert m, '_meta não encontrado dentro de CPC_IRI'
    meta = {}
    for k, v in re.findall(r"(\w+):\s*'((?:[^'\\]|\\.)*)'", m.group(1)):
        meta[k] = v
    return meta


def _array_js(nome, bloco):
    """Extrai um array JS simples (números ou 'null') pelo nome do campo,
    ex. 'en', 'neu', 'ln' dentro de iri:{...}. Converte 'null' -> None."""
    m = re.search(nome + r':\s*\[([^\]]*)\]', bloco)
    assert m, f'campo {nome!r} não encontrado'
    out = []
    for v in m.group(1).split(','):
        v = v.strip()
        if v == 'null':
            out.append(None)
        else:
            out.append(float(v) if '.' in v else int(v))
    return out


def _seasons(bloco):
    m = re.search(r'seasons:\s*\[([^\]]*)\]', bloco)
    assert m
    return [s.strip().strip("'") for s in m.group(1).split(',')]


def _iri_subcampo(nome, bloco):
    m = re.search(r'iri:\{([^}]*)\}', bloco)
    assert m, 'iri:{...} não encontrado'
    return _array_js(nome, m.group(1))


def _cpc_subcampo(nome, bloco):
    m = re.search(r'\n  cpc:\{([^}]*)\}', bloco)
    assert m, 'cpc:{...} não encontrado'
    return _array_js(nome, m.group(1))


def _sarimax_data(html):
    m = re.search(r'const SARIMAX_DATA\s*=\s*(\{.*?\});', html, re.DOTALL)
    assert m, 'const SARIMAX_DATA não encontrado'
    return json.loads(m.group(1))


class MetaIriEmissaoTestCase(unittest.TestCase):

    def setUp(self):
        self.meta = _bloco_meta(_html())

    def test_a_iri_emissao_atualizada_para_21_09_2026(self):
        self.assertEqual(self.meta.get('iri_emissao'), '21/09/2026')

    def test_b_iri_fonte_url_presente_e_correta(self):
        self.assertEqual(
            self.meta.get('iri_fonte_url'),
            'https://iri.columbia.edu/our-expertise/climate/forecasts/enso/current/',
        )

    def test_c_iri_pagina_identificada(self):
        self.assertIn('September 2026 Quick Look', self.meta.get('iri_pagina', ''))

    def test_d_extracao_externa_registrada_sem_alegar_verificacao_pelo_claude(self):
        extracao = self.meta.get('iri_extracao', '')
        self.assertIn('EXTERNA', extracao)
        self.assertNotIn('verificado por Claude', extracao.replace('NÃO reverificado de fonte primária por Claude', ''))
        status = self.meta.get('iri_status', '')
        self.assertIn('NÃO reverificado de fonte primária por Claude', status)

    def test_e_limitacao_de_acesso_registrada_com_causa_correta(self):
        """A causa real (confirmada nesta fase via curl/WebFetch) é bloqueio
        de proxy (403 no CONNECT), não falha de DNS como fases anteriores
        haviam caracterizado — não repetir a caracterização antiga sem
        verificar de novo."""
        extracao = self.meta.get('iri_extracao', '')
        self.assertIn('403', extracao)
        self.assertIn('CONNECT', extracao)

    def test_f_separacao_cpc_outubro_iri_setembro(self):
        self.assertNotEqual(self.meta.get('cpc_emissao'), self.meta.get('iri_emissao'))
        self.assertIn('out/2026', self.meta.get('cpc_emissao', '') + self.meta.get('cpc_probabilidades_emissao', ''))
        self.assertTrue(self.meta.get('iri_emissao', '').startswith('21/09/2026'))

    def test_g_iri_dados_download_registrado(self):
        self.assertIn('não fornece mais arquivos', self.meta.get('iri_dados_download', ''))


class SeasonsEAlinhamentoTestCase(unittest.TestCase):

    def setUp(self):
        self.bloco = _bloco_cpc_iri(_html())
        self.seasons = _seasons(self.bloco)

    def test_a_nove_trimestres_inalterados(self):
        self.assertEqual(
            self.seasons,
            ['ASO/26', 'SON/26', 'OND/26', 'NDJ/26', 'DJF/27', 'JFM/27', 'FMA/27', 'MAM/27', 'AMJ/27'],
        )

    def test_b_iri_en_neu_ln_mesmo_tamanho_dos_seasons(self):
        n = len(self.seasons)
        self.assertEqual(len(_iri_subcampo('en', self.bloco)), n)
        self.assertEqual(len(_iri_subcampo('neu', self.bloco)), n)
        self.assertEqual(len(_iri_subcampo('ln', self.bloco)), n)

    def test_c_cpc_nao_foi_alterado_nesta_fase(self):
        self.assertEqual(
            _cpc_subcampo('en', self.bloco),
            [None, 100.0, 100.0, 100.0, 100.0, 100.0, 98.0, 85.0, 45.0],
        )


class ValoresExplicitosSetembro2026TestCase(unittest.TestCase):

    def setUp(self):
        self.bloco = _bloco_cpc_iri(_html())
        self.en = _iri_subcampo('en', self.bloco)
        self.neu = _iri_subcampo('neu', self.bloco)
        self.ln = _iri_subcampo('ln', self.bloco)

    def test_a_aso26_nao_confirmado_e_null(self):
        self.assertIsNone(self.en[0])

    def test_b_son26_a_fma27_100_por_cento_el_nino(self):
        # índices 1..6 = SON/26, OND/26, NDJ/26, DJF/27, JFM/27, FMA/27
        self.assertEqual(self.en[1:7], [100, 100, 100, 100, 100, 100])

    def test_c_mam27_99_amj27_90(self):
        self.assertEqual(self.en[7], 99)
        self.assertEqual(self.en[8], 90)

    def test_d_neu_ln_zero_apenas_onde_fonte_declara_ausencia(self):
        self.assertEqual(self.neu[1:7], [0] * 6)
        self.assertEqual(self.ln[1:7], [0] * 6)

    def test_e_neu_ln_null_quando_divisao_nao_documentada(self):
        for idx in (7, 8):  # MAM/27, AMJ/27
            self.assertIsNone(self.neu[idx], f'neu[{idx}] deveria ser null (divisão não documentada)')
            self.assertIsNone(self.ln[idx], f'ln[{idx}] deveria ser null (divisão não documentada)')


class NullComoAusenciaNuncaZeroTestCase(unittest.TestCase):
    """CLAUDE.md armadilha 6 (persistência != 0,0) aplicada aqui ao IRI:
    null é ausência de dado, nunca deve ser gravado como 0 por
    conveniência, e um valor antigo nunca deve ser reaproveitado sem
    identificação individual da emissão (Fase ENSO-IRI, Seção 4)."""

    def setUp(self):
        self.bloco = _bloco_cpc_iri(_html())
        self.en = _iri_subcampo('en', self.bloco)
        self.neu = _iri_subcampo('neu', self.bloco)
        self.ln = _iri_subcampo('ln', self.bloco)

    def test_a_aso26_nao_reaproveita_valor_antigo(self):
        # valor antigo (Quick Look 19/ago/2026) era en=100,neu=0,ln=0 — se
        # continuasse igual, seria sinal de reaproveitamento sem
        # identificação individual da nova emissão.
        self.assertIsNone(self.en[0])
        self.assertIsNone(self.neu[0])
        self.assertIsNone(self.ln[0])

    def test_b_nenhum_null_de_mam_amj_foi_gravado_como_zero(self):
        for idx in (7, 8):
            self.assertIsNone(self.neu[idx])
            self.assertIsNone(self.ln[idx])


class SemProbabilidadesInventadasTestCase(unittest.TestCase):

    def setUp(self):
        self.bloco = _bloco_cpc_iri(_html())
        self.en = _iri_subcampo('en', self.bloco)
        self.neu = _iri_subcampo('neu', self.bloco)
        self.ln = _iri_subcampo('ln', self.bloco)

    def test_a_soma_100_apenas_nos_trimestres_totalmente_documentados(self):
        for idx in range(1, 7):  # SON/26..FMA/27
            soma = self.en[idx] + self.neu[idx] + self.ln[idx]
            self.assertEqual(soma, 100, f'trimestre índice {idx} deveria somar 100')

    def test_b_mam27_amj27_nao_tem_divisao_fabricada(self):
        # garantir que NINGUÉM preencheu neu/ln com "100-en" ou qualquer
        # outro cálculo para forçar soma 100 nesses dois trimestres.
        for idx in (7, 8):
            self.assertIsNone(self.neu[idx])
            self.assertIsNone(self.ln[idx])

    def test_c_mjj27_nao_foi_acrescentado_ao_horizonte(self):
        seasons = _seasons(self.bloco)
        self.assertNotIn('MJJ/27', seasons)
        self.assertEqual(len(seasons), 9)


class Mjj27ForaDoHorizonteDocumentadoTestCase(unittest.TestCase):

    def test_a_probabilidade_61_registrada_em_meta(self):
        meta = _bloco_meta(_html())
        campo = meta.get('iri_mjj27_fora_horizonte', '')
        self.assertIn('61', campo)
        self.assertIn('MJJ', campo)
        self.assertIn('fora', campo.lower())


class TrajetoriaPreservadaTestCase(unittest.TestCase):
    """Seção 6 da Fase ENSO-IRI: a trajetória mensal do Niño 3.4
    (nino_seasons/iri_nino_mean/p15/p85) não tem decomposição numérica
    exata verificável na emissão de set/2026 — deve permanecer
    BYTE-A-BYTE igual à de 19/ago/2026, nunca estimada."""

    def setUp(self):
        self.bloco = _bloco_cpc_iri(_html())

    def _array_simples(self, nome):
        m = re.search(nome + r':\s*\[([^\]]*)\]', self.bloco)
        self.assertIsNotNone(m, f'{nome} não encontrado')
        return [v.strip() for v in m.group(1).split(',')]

    def test_a_nino_seasons_inalterado(self):
        self.assertEqual(
            [s.strip("'") for s in self._array_simples('nino_seasons')],
            ['set/26', 'out/26', 'nov/26', 'dez/26', 'jan/27', 'fev/27',
             'mar/27', 'abr/27', 'mai/27', 'jun/27', 'jul/27', 'ago/27'],
        )

    def test_b_iri_nino_mean_inalterado(self):
        self.assertEqual(
            [float(v) for v in self._array_simples('iri_nino_mean')],
            [2.70, 2.20, 2.35, 2.50, 2.55, 2.50, 2.35, 2.10, 1.80, 1.45, 1.05, 0.70],
        )

    def test_c_iri_nino_p15_p85_inalterados(self):
        self.assertEqual(
            [float(v) for v in self._array_simples('iri_nino_p15')],
            [2.15, 1.60, 1.70, 1.80, 1.85, 1.80, 1.65, 1.45, 1.15, 0.80, 0.45, 0.15],
        )
        self.assertEqual(
            [float(v) for v in self._array_simples('iri_nino_p85')],
            [3.25, 2.80, 3.00, 3.20, 3.25, 3.20, 3.05, 2.75, 2.45, 2.10, 1.65, 1.25],
        )

    def test_d_meta_distingue_emissao_da_trajetoria_da_emissao_das_probabilidades(self):
        meta = _bloco_meta(_html())
        self.assertNotEqual(meta.get('iri_trajetoria_emissao'), meta.get('iri_emissao'))
        self.assertEqual(meta.get('iri_trajetoria_emissao'), 'ago/2026 (19/ago)')


class CompatibilidadeComSarimaxDataTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not DASHBOARD.exists():
            raise unittest.SkipTest('docs/index.html não disponível nesta árvore')
        cls.html = _html()
        cls.sd = _sarimax_data(cls.html)

    def test_a_todas_as_9_seasons_existem_em_iri_mean_trimestres(self):
        seasons = _seasons(_bloco_cpc_iri(self.html))
        tri_iri = self.sd['trimestres']['IRI_mean']
        faltando = [s for s in seasons if s not in tri_iri]
        self.assertEqual(faltando, [], f'trimestre(s) ausente(s) em SARIMAX_DATA.trimestres.IRI_mean: {faltando}')

    def test_b_todas_as_9_seasons_existem_em_todo_cenario_de_trimestres(self):
        seasons = _seasons(_bloco_cpc_iri(self.html))
        for cenario, tri in self.sd['trimestres'].items():
            faltando = [s for s in seasons if s not in tri]
            self.assertEqual(faltando, [], f'cenário {cenario!r} sem os trimestres: {faltando}')


class ComparativoRenderizacaoTestCase(unittest.TestCase):
    """Cobre as duas correções de renderização encontradas durante a
    investigação da Seção 7: o deslocamento fixo desatualizado em
    rebuildCmpNino() e o tratamento de null em buildCmpTable()."""

    def setUp(self):
        self.html = _html()

    def test_a_deslocamento_fixo_antigo_nao_existe_mais(self):
        self.assertNotIn('Math.min(i+3', self.html)

    def test_b_alinhamento_agora_e_por_rotulo_de_mes(self):
        self.assertIn('nsAsMmYy', self.html)
        self.assertIn('indexOf(lbl)', self.html)

    def test_c_mes_sem_correspondencia_produz_null_nao_ultimo_valor_repetido(self):
        trecho = re.search(r'function rebuildCmpNino\(\).*?\n\}', self.html, re.DOTALL)
        self.assertIsNotNone(trecho)
        corpo = trecho.group(0)
        self.assertIn('i===-1 ? null : i', corpo)

    def test_d_label_iri_media_inclui_emissao_da_trajetoria(self):
        self.assertIn("'IRI média ('+(CPC_IRI._meta.iri_trajetoria_emissao||'?')+')'", self.html)

    def test_e_tabela_comparativo_nao_renderiza_literal_null_pct(self):
        trecho = re.search(r'function buildCmpTable\(\).*?\n\}', self.html, re.DOTALL)
        self.assertIsNotNone(trecho)
        corpo = trecho.group(0)
        self.assertNotIn('${cp.en[i]}%', corpo)
        self.assertNotIn('${ir.en[i]}%', corpo)
        self.assertIn('fmtPct', corpo)

    def test_f_codigo_morto_dom_foi_removido(self):
        trecho = re.search(r'function buildCmpTable\(\).*?\n\}', self.html, re.DOTALL)
        self.assertIsNotNone(trecho)
        self.assertNotIn('const dom', trecho.group(0))

    def test_g_semaforo_sinaliza_trajetoria_separada_da_probabilidade(self):
        trecho = re.search(r'const ruleNote = document\.getElementById.*?\n  \}', self.html, re.DOTALL)
        self.assertIsNotNone(trecho)
        self.assertIn('iri_trajetoria_emissao', trecho.group(0))


class PreservacaoDeModelosCientificosTestCase(unittest.TestCase):
    """Guarda de regressão — REVISADA na Correção 3 (revisão externa,
    3ª rodada, Fase ENSO-AUTO).

    A versão original desta guarda (Fase ENSO-IRI) listava, junto dos
    artefatos científicos de verdade, 4 SCRIPTS OPERACIONAIS de
    ingestão/apresentação (`gerar_relatorio.py`, `fetch_monthly_data.py`,
    `update_indices.py`, `verificar_dashboard.py`). Isso era correto
    NAQUELA fase (nenhum deveria mudar ali), mas errado como guarda
    PERMANENTE: cada um desses 4 scripts já foi alterado, com
    autorização externa explícita, em fases posteriores (ENSO-DADOS,
    ENSO-AUTO) — a guarda antiga comparava sempre contra
    `merge-base(origin/main, HEAD)`, então qualquer branch futura que
    tocasse esses scripts (mesmo autorizada) reprovava este teste para
    sempre, até alguém apagar o teste ou a entrada da lista. Isso é
    "congelamento permanente de scripts operacionais", exatamente o
    que a revisão pediu para evitar — não "proteção de modelo".

    Esta versão protege só o que é de fato científico: o script do
    modelo (`update_dashboard.py` — SARIMAX/XGBoost/EMOS H2) e os
    artefatos de dados que são SAÍDA ou REFERÊNCIA do modelo, nunca
    produzidos por um script de ingestão/automação. Complementado por
    testes de INVARIANTE DE CONTEÚDO (não só de arquivo): o bloco
    `SARIMAX_DATA` e o bloco `BH` embutidos em `docs/index.html` têm
    que continuar byte-a-byte idênticos entre o merge-base e HEAD,
    mesmo quando `docs/index.html` como um todo muda legitimamente
    (ex.: bloco `CPC_IRI`, JS do Comparativo/semáforo) — prova direta
    de que "nenhum resultado de precipitação ou balanço hídrico foi
    recalculado", em vez de inferir isso indiretamente do nome dos
    arquivos tocados.
    """

    ARQUIVOS_CIENTIFICOS = [
        'scripts/update_dashboard.py',    # SARIMAX/XGBoost/EMOS H2 — núcleo do modelo
        'data/scen12_best.csv',           # saída do modelo: cenários/probabilidades
        'data/bh_final.json',             # saída do modelo: balanço hídrico calculado
        'data/fc_results_best.json',      # saída do modelo: projeção de precipitação
        'data/serie_subst.csv',           # série de referência que treina o modelo
    ]

    # ── Fase ENSO-INTEGRIDADE 3A/3A.1 ───────────────────────────────
    # `scripts/update_dashboard.py` ganhou proteção fail-closed contra
    # índices ENSO ausentes/inválidos (`incorporar_fallback_openmeteo`)
    # e passou a registrar proveniência (`import proveniencia_indices`).
    # Isso NÃO é mudança de modelo científico — a função tratada aqui
    # só decide SE um mês novo entra na série via Open-Meteo, nunca
    # como SARIMAX/XGBoost/EMOS H2/solve_bh calculam o que quer que
    # seja. Em vez de tirar o arquivo da lista de intocáveis (o que
    # cegaria esta guarda para qualquer mudança futura nele, científica
    # ou não) ou usar skip/xfail/tolerância, a guarda abaixo compara
    # byte-a-byte SÓ a superfície explicitamente autorizada; qualquer
    # outra diferença no arquivo ainda reprova test_a, exatamente como
    # antes.
    _UD_IMPORT_PERMITIDO = 'import proveniencia_indices as prov\n'
    _UD_FUNC_INICIO = 'def incorporar_fallback_openmeteo'
    _UD_FUNC_FIM_MARCADOR = '\n\n\n# ── Caminhos'

    # Segunda superfície autorizada: a linha que inicializava o PDO
    # ausente com `.fillna(0)` (um 0.0 fabricado, exatamente o que
    # CLAUDE.md "armadilha 6" proíbe) foi trocada por `.ffill()` puro —
    # o NaN residual (só na abertura da série) é removido depois pelo
    # `dropna(subset=[...,'pdo_l23'])` já existente antes desta fase.
    # Aceita as duas formas (antiga/nova) em qualquer ordem, porque a
    # mesma função compara texto de base OU de HEAD indistintamente.
    _UD_PDO_ANTIGO = "d['pdo'] = d['pdo'].ffill().fillna(0)\n"
    _UD_PDO_NOVO = (
        "d['pdo'] = d['pdo'].ffill()   # Fase ENSO-INTEGRIDADE: nunca fillna(0) — um 0.0\n"
        "                               # fabricado seria ENSO-neutro falso; qualquer NaN\n"
        "                               # residual (só a abertura da série, antes de\n"
        "                               # existir qualquer PDO real) é removido abaixo\n"
        "                               # pelo dropna(subset=[...,'pdo_l23']), nunca\n"
        "                               # sobrevive como 0.0 disfarçado de observação.\n"
    )

    @classmethod
    def _nucleo_cientifico_update_dashboard(cls, texto):
        """Devolve o conteúdo de update_dashboard.py com a superfície
        autorizada (o import novo, o corpo de
        incorporar_fallback_openmeteo e a linha do PDO fail-closed)
        removida — o que resta é só o que tem que continuar
        byte-a-byte idêntico. Nunca falha em silêncio: se os
        marcadores não forem encontrados (ex.: alguém renomeou/moveu a
        função, ou a linha do PDO foi alterada de uma terceira forma
        não autorizada), levanta em vez de devolver um resultado que
        pareceria "sem diferença" por engano."""
        sem_import = texto.replace(cls._UD_IMPORT_PERMITIDO, '', 1)

        inicio = sem_import.find(cls._UD_FUNC_INICIO)
        if inicio < 0:
            raise AssertionError(
                f'{cls._UD_FUNC_INICIO!r} não encontrado — marcador da área '
                'autorizada mudou; revisar esta guarda antes de confiar nela')
        fim = sem_import.find(cls._UD_FUNC_FIM_MARCADOR, inicio)
        if fim < 0:
            raise AssertionError(
                f'{cls._UD_FUNC_FIM_MARCADOR!r} não encontrado após o início da função — '
                'marcador da área autorizada mudou; revisar esta guarda antes de confiar nela')
        sem_funcao = sem_import[:inicio] + sem_import[fim:]

        if cls._UD_PDO_ANTIGO in sem_funcao:
            sem_pdo = sem_funcao.replace(cls._UD_PDO_ANTIGO, '', 1)
        elif cls._UD_PDO_NOVO in sem_funcao:
            sem_pdo = sem_funcao.replace(cls._UD_PDO_NOVO, '', 1)
        else:
            raise AssertionError(
                'nem a forma antiga (.fillna(0)) nem a nova (.ffill() fail-closed) da '
                "linha do PDO foram encontradas — marcador da área autorizada mudou; "
                'revisar esta guarda antes de confiar nela')

        return sem_pdo

    @classmethod
    def setUpClass(cls):
        try:
            cls.base = subprocess.run(
                ['git', 'merge-base', 'origin/main', 'HEAD'],
                cwd=ROOT, capture_output=True, text=True, check=True,
            ).stdout.strip()
        except Exception:
            raise unittest.SkipTest('não foi possível determinar o merge-base com origin/main')

    def test_a_nenhum_arquivo_cientifico_ou_de_dados_de_referencia_foi_alterado(self):
        resultado = subprocess.run(
            ['git', 'diff', '--name-only', self.base, '--'] + self.ARQUIVOS_CIENTIFICOS,
            cwd=ROOT, capture_output=True, text=True,
        )
        alterados = [l for l in resultado.stdout.splitlines() if l.strip()]

        # scripts/update_dashboard.py pode aparecer como "alterado" por
        # causa só da superfície autorizada (ENSO-INTEGRIDADE 3A/3A.1) —
        # nesse caso, confirmar que o NÚCLEO científico do arquivo segue
        # byte-a-byte idêntico antes de tirá-lo da lista de reprovados.
        # Qualquer outro arquivo nesta lista, ou qualquer diferença fora
        # dessa superfície em update_dashboard.py, continua reprovando.
        if alterados == ['scripts/update_dashboard.py']:
            base_txt = self._ler_arquivo_na_revisao(self.base, 'scripts/update_dashboard.py')
            head_txt = self._ler_arquivo_na_revisao('HEAD', 'scripts/update_dashboard.py')
            self.assertIsNotNone(base_txt, 'não foi possível ler update_dashboard.py no merge-base')
            self.assertIsNotNone(head_txt, 'não foi possível ler update_dashboard.py em HEAD')
            nucleo_base = self._nucleo_cientifico_update_dashboard(base_txt)
            nucleo_head = self._nucleo_cientifico_update_dashboard(head_txt)
            self.assertEqual(
                nucleo_base, nucleo_head,
                'scripts/update_dashboard.py mudou FORA da superfície autorizada '
                '(import proveniencia_indices + incorporar_fallback_openmeteo + '
                'linha fail-closed do PDO) — isso é alteração de modelo científico, '
                'não de validação/fallback')
            return

        self.assertEqual(alterados, [], f'arquivo(s) científico(s)/de referência foram alterados: {alterados}')

    def _ler_arquivo_na_revisao(self, ref, caminho):
        resultado = subprocess.run(
            ['git', 'show', f'{ref}:{caminho}'],
            cwd=ROOT, capture_output=True, text=True,
        )
        return resultado.stdout if resultado.returncode == 0 else None

    def test_b_bloco_sarimax_data_embutido_no_html_e_byte_identico(self):
        """Invariante de CONTEÚDO, não só de arquivo inteiro:
        `docs/index.html` muda legitimamente nesta fase (bloco
        `CPC_IRI`, JS do Comparativo) — o que nunca pode mudar é o
        bloco `SARIMAX_DATA` dentro dele, gerado só por
        `update_dashboard.py` (nunca por scripts desta fase)."""
        def bloco(ref):
            conteudo = self._ler_arquivo_na_revisao(ref, 'docs/index.html')
            if conteudo is None:
                return None
            m = re.search(r'const SARIMAX_DATA\s*=\s*\{.*?\};\n', conteudo, re.DOTALL)
            return m.group(0) if m else None

        bloco_base, bloco_head = bloco(self.base), bloco('HEAD')
        if bloco_base is None or bloco_head is None:
            self.skipTest('SARIMAX_DATA não encontrado em uma das revisões')
        self.assertEqual(bloco_base, bloco_head,
                          'SARIMAX_DATA mudou — nenhuma fase de ingestão/automação deveria '
                          'alterar a saída do modelo SARIMAX/XGBoost')

    def test_c_bloco_balanco_hidrico_bh_e_byte_identico(self):
        """Mesmo princípio para `const BH = {...}` (balanço hídrico
        calculado) — verificação direta pedida: 'nenhum resultado de
        precipitação ou balanço hídrico foi recalculado'."""
        def bloco(ref):
            conteudo = self._ler_arquivo_na_revisao(ref, 'docs/index.html')
            if conteudo is None:
                return None
            ini = conteudo.find('const BH = {')
            fim = conteudo.find('\nconst SC_COL = {', ini)
            if ini < 0 or fim < 0:
                return None
            return conteudo[ini:fim]

        bloco_base, bloco_head = bloco(self.base), bloco('HEAD')
        if bloco_base is None or bloco_head is None:
            self.skipTest('bloco BH não encontrado em uma das revisões')
        self.assertEqual(bloco_base, bloco_head,
                          'bloco BH (balanço hídrico) mudou — nenhuma fase de ingestão '
                          'deveria recalculá-lo')

    def test_d_scripts_operacionais_podem_mudar_quando_autorizado(self):
        """Contraste explícito com a guarda antiga: scripts de
        ingestão/apresentação NÃO estão na lista de intocáveis — esta
        fase (ENSO-AUTO) os altera com autorização explícita, e isso
        é esperado, não uma regressão. Este teste documenta a decisão,
        não afirma que eles mudaram (podem ou não, dependendo da
        fase) — só confirma que a guarda não os bloqueia."""
        scripts_operacionais = [
            'scripts/gerar_relatorio.py',
            'scripts/fetch_monthly_data.py',
            'scripts/update_indices.py',
            'scripts/verificar_dashboard.py',
        ]
        self.assertTrue(
            set(scripts_operacionais).isdisjoint(self.ARQUIVOS_CIENTIFICOS),
            'scripts operacionais nunca devem entrar na lista de arquivos científicos')

    # ── Regressão da superfície autorizada (ENSO-INTEGRIDADE 3A.1) ──
    # Os testes abaixo não tocam git nem o arquivo real — são testes
    # unitários puros de `_nucleo_cientifico_update_dashboard`, com
    # texto sintético, para provar que a exceção introduzida em test_a
    # é estreita: cobre exatamente o que foi autorizado (import +
    # incorporar_fallback_openmeteo + a linha fail-closed do PDO) e
    # nada além disso.

    _TEXTO_SINTETICO_BASE = (
        "import os\n"
        "from pathlib import Path\n"
        "\n"
        "def incorporar_fallback_openmeteo(serie, data_path):\n"
        "    return serie\n"
        "\n"
        "\n"
        "# ── Caminhos ──\n"
        "def solve_bh(prec_jul, etp_jul):\n"
        "    return prec_jul - etp_jul\n"
        "\n"
        "d['pdo'] = d['pdo'].ffill().fillna(0)\n"
        "def gtsa(p):\n"
        "    return p\n"
    )

    def test_e_mudanca_so_na_area_permitida_nao_e_sinalizada(self):
        """Positivo: alterar só o import autorizado, o corpo de
        incorporar_fallback_openmeteo e a linha do PDO (o que
        ENSO-INTEGRIDADE 3A/3A.1 de fato fez) não deve sobrar
        diferença no núcleo científico — é exatamente o caso que
        permite test_a destravar sem mascarar nada."""
        texto_modificado = self._TEXTO_SINTETICO_BASE.replace(
            "import os\nfrom pathlib import Path\n",
            "import os\nfrom pathlib import Path\nimport proveniencia_indices as prov\n",
        ).replace(
            "def incorporar_fallback_openmeteo(serie, data_path):\n    return serie\n",
            "def incorporar_fallback_openmeteo(serie, data_path):\n"
            "    if serie is None:\n"
            "        raise ValueError('fail-closed')\n"
            "    return serie\n",
        ).replace(self._UD_PDO_ANTIGO, self._UD_PDO_NOVO)
        nucleo_base = self._nucleo_cientifico_update_dashboard(self._TEXTO_SINTETICO_BASE)
        nucleo_mod = self._nucleo_cientifico_update_dashboard(texto_modificado)
        self.assertEqual(nucleo_base, nucleo_mod)

    def test_f_mudanca_fora_da_area_permitida_e_detectada(self):
        """Negativo: uma alteração em código científico de verdade
        (aqui, solve_bh — fora da área autorizada) tem que continuar
        sendo detectada pela comparação de núcleo, mesmo que o import
        de proveniência e a mudança autorizada do PDO também estejam
        presentes. Prova que a exceção de test_a não abre brecha para
        mudanças científicas indevidas passarem disfarçadas de 'só
        validação/fallback'."""
        texto_com_mudancas_permitidas = self._TEXTO_SINTETICO_BASE.replace(
            "import os\nfrom pathlib import Path\n",
            "import os\nfrom pathlib import Path\nimport proveniencia_indices as prov\n",
        ).replace(self._UD_PDO_ANTIGO, self._UD_PDO_NOVO)
        texto_com_bh_tambem_alterado = texto_com_mudancas_permitidas.replace(
            "def solve_bh(prec_jul, etp_jul):\n    return prec_jul - etp_jul\n",
            "def solve_bh(prec_jul, etp_jul):\n    return (prec_jul - etp_jul) * 0.9\n",
        )
        nucleo_base = self._nucleo_cientifico_update_dashboard(self._TEXTO_SINTETICO_BASE)
        nucleo_alterado = self._nucleo_cientifico_update_dashboard(texto_com_bh_tambem_alterado)
        self.assertNotEqual(
            nucleo_base, nucleo_alterado,
            'uma mudança em solve_bh (núcleo científico) deveria ter sido detectada')

    def test_g_terceira_forma_nao_autorizada_da_linha_pdo_e_detectada(self):
        """Negativo específico para a segunda superfície autorizada:
        uma TERCEIRA forma da linha do PDO (nem `.fillna(0)` nem
        `.ffill()` fail-closed — ex.: alguém trocasse por uma
        constante arbitrária) não é reconhecida por nenhum dos dois
        marcadores, então tem que levantar em vez de ser tratada como
        'sem diferença'."""
        texto_terceira_forma = self._TEXTO_SINTETICO_BASE.replace(
            self._UD_PDO_ANTIGO, "d['pdo'] = d['pdo'].fillna(-99)\n")
        with self.assertRaises(AssertionError):
            self._nucleo_cientifico_update_dashboard(texto_terceira_forma)

    def test_h_marcadores_ausentes_levantam_em_vez_de_mascarar(self):
        """Se os marcadores da área autorizada não forem encontrados
        (ex.: a função foi renomeada/movida), a comparação tem que
        levantar — nunca devolver silenciosamente 'sem diferença'."""
        texto_sem_funcao = "import os\nfrom pathlib import Path\n# nada aqui\n"
        with self.assertRaises(AssertionError):
            self._nucleo_cientifico_update_dashboard(texto_sem_funcao)


if __name__ == '__main__':
    unittest.main()
