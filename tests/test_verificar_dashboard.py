#!/usr/bin/env python3
"""
tests/test_verificar_dashboard.py — Fase ENSO-DADOS (auditoria
15/10/2026): cobre a flag `--pular-continuidade-serie-subst` (nova) e
o parser de datas pt-BR usado no aviso de defasagem do CPC_IRI
(`_dias_desde_data_pt`), sem tocar nenhuma das outras checagens já
existentes do verificador.

Contexto do bug corrigido: `indices_semanal.yml` nunca chama
`fetch_monthly_data.py` (só `update.yml`, dia 21) — então, do dia 1 ao
dia 20 de todo mês, a checagem de continuidade de `serie_subst.csv`
reprova por um motivo que aquele workflow não pode corrigir,
bloqueando o commit e o heartbeat seguintes. A flag existe só pra esse
workflow; `update.yml`/`publicar.yml` continuam com o comportamento
padrão (bloqueante), nunca passam a flag.

Roda com:
    python -m unittest tests.test_verificar_dashboard -v
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import verificar_dashboard as vd  # noqa: E402


class DiasDesdeDataPtTestCase(unittest.TestCase):

    def test_a_formato_dd_mmm_aaaa(self):
        d = vd._dias_desde_data_pt('13/ago/2026')
        esperado = (date.today() - date(2026, 8, 13)).days
        self.assertEqual(d, esperado)

    def test_b_formato_mmm_aaaa_parenteses_dd_mmm(self):
        # formato real de CPC_IRI._meta.iri_emissao: 'ago/2026 (19/ago)'
        d = vd._dias_desde_data_pt('ago/2026 (19/ago)')
        esperado = (date.today() - date(2026, 8, 19)).days
        self.assertEqual(d, esperado)

    def test_c_texto_sem_data_retorna_none_nunca_lanca(self):
        self.assertIsNone(vd._dias_desde_data_pt('série CPC da emissão de jul/26'))
        self.assertIsNone(vd._dias_desde_data_pt(''))
        self.assertIsNone(vd._dias_desde_data_pt('qualquer coisa sem data'))

    def test_d_mes_invalido_retorna_none(self):
        self.assertIsNone(vd._dias_desde_data_pt('13/xxx/2026'))

    def test_e_dia_invalido_para_o_mes_retorna_none_nunca_lanca(self):
        self.assertIsNone(vd._dias_desde_data_pt('31/fev/2026'))


class PularContinuidadeSerieSubstTestCase(unittest.TestCase):
    """Usa os dados reais do repositório (mesma árvore de trabalho) —
    só pula se não existirem, igual às outras suítes `ComDadosReais*`
    do projeto."""

    @classmethod
    def setUpClass(cls):
        if not vd.SERIE_SUBST.exists() or not vd.DASHBOARD.exists():
            raise unittest.SkipTest("dados reais não disponíveis nesta árvore de trabalho")

    def test_a_flag_desligada_mantem_comportamento_padrao(self):
        """Default (sem flag) precisa continuar idêntico ao
        comportamento de sempre — update.yml/publicar.yml nunca passam
        a flag, então `main()` sem argumento tem que se comportar
        exatamente como antes desta correção."""
        vd.falhas.clear()
        resultado = vd.main()
        # ambos os comportamentos são válidos dependendo do estado real
        # da árvore de trabalho — o que esta prova é que a flag NUNCA
        # muda o resultado quando desligada (comparado a seu próprio
        # default), não que o resultado precisa ser 0 ou 1 especificamente.
        vd.falhas.clear()
        resultado_de_novo = vd.main(pular_continuidade_serie_subst=False)
        self.assertEqual(resultado, resultado_de_novo)

    def test_b_flag_ligada_nunca_adiciona_a_falhas_por_causa_do_serie_subst(self):
        vd.falhas.clear()
        vd.main(pular_continuidade_serie_subst=True)
        for f in vd.falhas:
            self.assertNotIn('serie_subst.csv com mês(es) faltando', f)

    def test_c_flag_ligada_nunca_e_mais_permissiva_que_desligada_em_outras_checagens(self):
        """A flag só pode SUPRIMIR a falha específica do item 9 — nunca
        fazer uma falha de qualquer OUTRA checagem desaparecer. Prova:
        toda falha com a flag ligada (exceto a do serie_subst) também
        aparece com a flag desligada."""
        vd.falhas.clear()
        vd.main(pular_continuidade_serie_subst=False)
        falhas_sem_flag = set(vd.falhas)

        vd.falhas.clear()
        vd.main(pular_continuidade_serie_subst=True)
        falhas_com_flag = set(vd.falhas)

        extras = falhas_com_flag - falhas_sem_flag
        self.assertEqual(extras, set(), f'flag introduziu falha nova: {extras}')

    def tearDown(self):
        vd.falhas.clear()


def _serie_subst_fixture_csv(com_lacuna):
    """Série sintética de `serie_subst.csv` (NUNCA o CSV real) cobrindo
    de jan/2020 até o mês anterior ao atual — mesmo horizonte que
    `checar_continuidade()` cobre por padrão (CLAUDE.md: 'checa até o
    mês anterior ao atual'). Construída relativa a `date.today()`,
    nunca a um mês/ano hardcoded — continua válida em qualquer ciclo
    futuro, ao contrário dos testes antigos que dependiam do estado
    real da série ter uma lacuna (deixou de ser verdade quando a série
    real alcançou continuidade).

    Com `com_lacuna=True`, omite deliberadamente 03/2020 — bem longe da
    ponta mais recente, para que nenhuma lógica de 'mês mais recente'
    (itens 11/12) seja afetada, só a checagem de continuidade (item 9).
    tsa/pdo ficam vazios de propósito: sem valor, a checagem de
    proveniência (itens 12/13) não tem nada para avaliar e nunca
    reprova por um motivo que não é o que este teste quer exercitar."""
    hoje = date.today()
    y_fim, m_fim = (hoje.year, hoje.month - 1) if hoje.month > 1 else (hoje.year - 1, 12)
    linhas = ['ano,mes,prec,nino34,tsa,pdo,date,fonte']
    y, m = 2020, 1
    while (y, m) <= (y_fim, m_fim):
        pular = com_lacuna and (y, m) == (2020, 3)
        if not pular:
            linhas.append(f'{y},{m},100.0,0.0,,,{y}-{m:02d}-01,fixture')
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return '\n'.join(linhas) + '\n'


def _montar_arvore_isolada_verificador(raiz, serie_subst_csv_texto):
    """Copia só o que `scripts/verificar_dashboard.py` precisa para
    rodar como subprocesso real (igual a indices_semanal.yml/
    update.yml o chamam) — `verificar_dashboard.py` e suas dependências
    locais `proveniencia_indices.py`/`roni_historico.py` (Fase
    ENSO-RONI-MIGRAÇÃO 2.1), e o `docs/index.html` REAL (não é isso que
    está sob teste aqui) — com um `data/serie_subst.csv` FIXTURE no
    lugar do real. Deliberadamente SEM `data/roni_historico.csv`/
    `roni_proveniencia.csv`/`roni_snapshots/` — a verificação RONI
    (leitura) trata a ausência total desses artefatos como "nada a
    verificar ainda", nunca como falha, então a árvore isolada permanece
    válida sem eles. Como `verificar_dashboard.py` resolve
    `ROOT = Path(__file__).parent.parent`, rodar o binário copiado faz
    `SERIE_SUBST`/`DASHBOARD` apontarem para esta árvore isolada, nunca
    para o repositório real."""
    (raiz / 'scripts').mkdir(parents=True)
    (raiz / 'docs').mkdir()
    (raiz / 'data').mkdir()
    for nome in ('verificar_dashboard.py', 'proveniencia_indices.py', 'roni_historico.py'):
        shutil.copy(ROOT / 'scripts' / nome, raiz / 'scripts' / nome)
    shutil.copy(ROOT / 'docs' / 'index.html', raiz / 'docs' / 'index.html')
    (raiz / 'data' / 'serie_subst.csv').write_text(serie_subst_csv_texto, encoding='utf-8')
    return raiz


class ComandoExatoDoWorkflowSemanalTestCase(unittest.TestCase):
    """Revisão externa (2ª rodada, 'Correção 4'; revisada na Fase
    ENSO-INTEGRIDADE 3B.8A.3): testa o comando exatamente como
    `.github/workflows/indices_semanal.yml` o executa (subprocesso
    real, não chamada direta de `main()`), e confirma que `update.yml`
    continua chamando o verificador sem a flag (bloqueante,
    comportamento 100% preservado).

    Correção 3B.8A.3: os testes originais (`test_a`/`test_d`) rodavam
    contra `data/serie_subst.csv` REAL, presumindo que a série real
    tinha uma lacuna — verdade quando foram escritos, mas não mais
    (a série real alcançou continuidade; confirmado reproduzindo a
    falha idêntica na baseline antes desta correção). Substituídos por
    uma árvore isolada com fixture temporal (`_serie_subst_fixture_csv`),
    nunca o CSV real, para que o resultado não dependa do mês em que o
    teste roda nem precise ser fixado a um mês/ano específico."""

    @classmethod
    def setUpClass(cls):
        if not vd.SERIE_SUBST.exists() or not vd.DASHBOARD.exists():
            raise unittest.SkipTest("dados reais não disponíveis nesta árvore de trabalho")
        cls._tmpdir = tempfile.TemporaryDirectory()
        raiz = Path(cls._tmpdir.name)
        cls.arvore_completa = _montar_arvore_isolada_verificador(
            raiz / 'completa', _serie_subst_fixture_csv(com_lacuna=False))
        cls.arvore_com_lacuna = _montar_arvore_isolada_verificador(
            raiz / 'com_lacuna', _serie_subst_fixture_csv(com_lacuna=True))

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    @staticmethod
    def _rodar(arvore, com_flag):
        args = [sys.executable, str(arvore / 'scripts' / 'verificar_dashboard.py')]
        if com_flag:
            args.append('--pular-continuidade-serie-subst')
        return subprocess.run(args, cwd=arvore, capture_output=True, text=True)

    # ── item 1: série completa — aprovado com e sem flag ──
    def test_a_serie_completa_aprovada_com_e_sem_flag(self):
        for com_flag in (False, True):
            with self.subTest(com_flag=com_flag):
                resultado = self._rodar(self.arvore_completa, com_flag)
                self.assertEqual(resultado.returncode, 0,
                                  f'série completa deveria aprovar (com_flag={com_flag}):\n{resultado.stdout}')
                self.assertIn('APROVADO', resultado.stdout)
                self.assertNotIn('IGNORADO nesta execução', resultado.stdout,
                                  'nada deveria precisar ser ignorado numa série sem lacuna')

    # ── item 2: série com lacuna — sem flag, reprovado ──
    def test_b_serie_com_lacuna_sem_flag_e_reprovada(self):
        resultado = self._rodar(self.arvore_com_lacuna, com_flag=False)
        self.assertEqual(resultado.returncode, 1)
        self.assertIn('serie_subst.csv com mês(es) faltando', resultado.stdout)
        self.assertNotIn('IGNORADO nesta execução', resultado.stdout)

    # ── item 3: série com lacuna — a flag dispensa SÓ a continuidade ──
    def test_c_serie_com_lacuna_com_flag_dispensa_so_a_continuidade(self):
        resultado = self._rodar(self.arvore_com_lacuna, com_flag=True)
        self.assertEqual(resultado.returncode, 0,
                          f'a única falha conhecida desta árvore é a lacuna; a flag deveria aprovar:\n{resultado.stdout}')
        self.assertIn('IGNORADO nesta execução', resultado.stdout)
        self.assertIn('--pular-continuidade-serie-subst', resultado.stdout)
        linhas_falha = [linha for linha in resultado.stdout.splitlines() if '❌' in linha]
        self.assertEqual(linhas_falha, [], f'flag deveria suprimir só o item 9: {linhas_falha}')

    # ── item 4: erro em OUTRO controle — a flag não aprova indevidamente ──
    def test_d_falha_em_outro_controle_nao_e_mascarada_pela_flag(self):
        """Corrompe o docs/index.html da árvore com lacuna (quebra o
        objeto D, item 1 — nada a ver com serie_subst.csv) e confirma
        que a flag, que só existe para o item 9, não aprova a execução
        mesmo assim."""
        raiz_corrompida = Path(self._tmpdir.name) / 'com_lacuna_e_html_quebrado'
        _montar_arvore_isolada_verificador(raiz_corrompida, _serie_subst_fixture_csv(com_lacuna=True))
        html = (raiz_corrompida / 'docs' / 'index.html').read_text(encoding='utf-8')
        html_quebrado = html.replace('const D = {', 'const D = { {{{{quebrado', 1)
        self.assertNotEqual(html, html_quebrado, 'substituição não encontrou o marcador esperado')
        (raiz_corrompida / 'docs' / 'index.html').write_text(html_quebrado, encoding='utf-8')
        resultado = self._rodar(raiz_corrompida, com_flag=True)
        self.assertEqual(resultado.returncode, 1,
                          f'flag nunca deveria aprovar uma falha fora do item 9:\n{resultado.stdout}')
        self.assertIn('IGNORADO nesta execução', resultado.stdout)  # item 9 foi suprimido...
        self.assertIn('❌', resultado.stdout)  # ...mas o item 1 continua reprovando

    # ── item 5: comando de indices_semanal.yml mantém a flag ──
    def test_e_workflow_semanal_usa_a_flag_exatamente_como_testada_aqui(self):
        with open(ROOT / '.github' / 'workflows' / 'indices_semanal.yml', encoding='utf-8') as f:
            conteudo = f.read()
        self.assertIn(
            'run: python scripts/verificar_dashboard.py --pular-continuidade-serie-subst',
            conteudo,
        )

    # ── item 6: comando de update.yml continua sem flag ──
    def test_f_comando_do_workflow_mensal_update_yml_nao_leva_a_flag(self):
        with open(ROOT / '.github' / 'workflows' / 'update.yml', encoding='utf-8') as f:
            conteudo = f.read()
        self.assertIn('run: python scripts/verificar_dashboard.py\n', conteudo)
        self.assertNotIn('--pular-continuidade-serie-subst', conteudo)


if __name__ == '__main__':
    unittest.main()
