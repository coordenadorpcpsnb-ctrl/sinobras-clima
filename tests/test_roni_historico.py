#!/usr/bin/env python3
"""Testes de scripts/roni_historico.py — série histórica oficial do
RONI, snapshots imutáveis e proveniência (Fase ENSO-RONI-MIGRAÇÃO 2).

Isolamento: todo teste que grava em disco usa `tempfile.TemporaryDirectory()`
e `patch.object` nos caminhos do módulo (HISTORICO_PATH/PROVENIENCIA_PATH/
SNAPSHOTS_DIR) — nunca toca `data/roni_historico.csv` nem
`data/roni_proveniencia.csv` reais. A fixture `_roni_ascii_fixture.txt`
é um snapshot congelado de uma aquisição real (ver cabeçalho do
arquivo) — os testes nunca dependem de rede.
"""
import math
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
import roni_historico as rh  # noqa: E402

FIXTURE_PATH = Path(__file__).parent / '_roni_ascii_fixture.txt'
FIXTURE_TEXTO = FIXTURE_PATH.read_text(encoding='utf-8')
FIXTURE_BYTES = FIXTURE_PATH.read_bytes()


def _serie_sintetica(pares):
    """pares: lista de (temporada, ano, valor), já em ordem cronológica
    válida — gera o texto bruto 'SEAS YR ANOM' correspondente."""
    linhas = ['SEAS   YR  ANOM']
    for seas, ano, val in pares:
        linhas.append(f'{seas}  {ano} {val:>6.2f}')
    return '\n'.join(linhas) + '\n'


SERIE_BASE = [
    ('DJF', 2025, 0.10), ('JFM', 2025, 0.20), ('FMA', 2025, 0.30),
    ('MAM', 2025, 0.40), ('AMJ', 2025, 0.50), ('MJJ', 2025, 0.60),
    ('JJA', 2025, 0.70), ('JAS', 2025, 0.80), ('ASO', 2025, 0.90),
    ('SON', 2025, 1.00), ('OND', 2025, 1.10), ('NDJ', 2025, 1.20),
    ('DJF', 2026, 1.30),
]


class IsolamentoMixin:
    """Redireciona HISTORICO_PATH/PROVENIENCIA_PATH/SNAPSHOTS_DIR para
    um diretório temporário em cada teste."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmpdir.name)
        self._patches = [
            patch.object(rh, 'HISTORICO_PATH', tmp / 'roni_historico.csv'),
            patch.object(rh, 'PROVENIENCIA_PATH', tmp / 'roni_proveniencia.csv'),
            patch.object(rh, 'SNAPSHOTS_DIR', tmp / 'roni_snapshots'),
            patch.object(rh, 'ROOT', tmp),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._tmpdir.cleanup)


# ══════════════════════════════════════════════════════
# GRUPO A — Parsing e calendário
# ══════════════════════════════════════════════════════
class ParseRoniSerieCompletaTestCase(unittest.TestCase):

    def test_a1_serie_oficial_valida_fixture_real(self):
        lista, avisos = rh.parse_roni_serie_completa(FIXTURE_TEXTO)
        self.assertIsNotNone(lista)
        self.assertEqual(avisos, [])
        self.assertEqual(len(lista), 921)
        self.assertEqual(lista[0]['temporada'], 'DJF')
        self.assertEqual(lista[0]['ano'], 1950)
        self.assertEqual(lista[-1]['temporada'], 'ASO')
        self.assertEqual(lista[-1]['ano'], 2026)
        self.assertEqual(lista[-1]['valor'], 1.97)

    def test_a2_cabecalho_invalido(self):
        texto = 'ANO SEAS VALOR\nDJF 2020 1.00\n'
        lista, avisos = rh.parse_roni_serie_completa(texto)
        self.assertIsNone(lista)
        self.assertTrue(avisos)

    def test_a3_resposta_vazia(self):
        lista, avisos = rh.parse_roni_serie_completa('')
        self.assertIsNone(lista)

    def test_a4_resposta_html(self):
        texto = '<html><body>404 Not Found</body></html>'
        lista, avisos = rh.parse_roni_serie_completa(texto)
        self.assertIsNone(lista)

    def test_a5_ano_nao_numerico(self):
        texto = _serie_sintetica([('DJF', 2025, 0.1)]).replace('2025', 'ABCD')
        lista, avisos = rh.parse_roni_serie_completa(texto)
        self.assertIsNone(lista)

    def test_a6_temporada_invalida(self):
        texto = 'SEAS   YR  ANOM\nXYZ  2025   0.10\n'
        lista, avisos = rh.parse_roni_serie_completa(texto)
        self.assertIsNone(lista)

    def test_a7_valor_nao_numerico(self):
        texto = 'SEAS   YR  ANOM\nDJF  2025   N/D\n'
        lista, avisos = rh.parse_roni_serie_completa(texto)
        self.assertIsNone(lista)

    def test_a8_valor_infinito(self):
        texto = 'SEAS   YR  ANOM\nDJF  2025    inf\n'
        lista, avisos = rh.parse_roni_serie_completa(texto)
        self.assertIsNone(lista)

    def test_a8b_valor_nan(self):
        texto = 'SEAS   YR  ANOM\nDJF  2025    nan\n'
        lista, avisos = rh.parse_roni_serie_completa(texto)
        self.assertIsNone(lista)

    def test_a9_valor_implausivel(self):
        texto = _serie_sintetica([('DJF', 2025, 6.00)])
        lista, avisos = rh.parse_roni_serie_completa(texto)
        self.assertIsNone(lista)

    def test_a10_duplicata_identica_e_sempre_rejeitada(self):
        # Fase ENSO-RONI-MIGRAÇÃO 2.2, Correção 4: a regra aprovada
        # exige rejeição de QUALQUER duplicidade na série oficial —
        # mesmo com valor idêntico. Nenhuma linha é escolhida
        # arbitrariamente; o documento inteiro é rejeitado.
        texto = _serie_sintetica([('DJF', 2025, 0.10)])
        texto += 'DJF  2025   0.10\n'
        lista, avisos = rh.parse_roni_serie_completa(texto)
        self.assertIsNone(lista)

    def test_a10b_duplicata_coincidente_so_apos_arredondamento_rejeitada(self):
        texto = _serie_sintetica([('DJF', 2025, 0.101)])
        texto += 'DJF  2025   0.104\n'  # ambos arredondam para 0.10, mas são valores distintos
        lista, avisos = rh.parse_roni_serie_completa(texto)
        self.assertIsNone(lista)

    def test_a10c_duplicata_com_ordem_invertida_tambem_rejeitada(self):
        texto = _serie_sintetica([('DJF', 2025, 0.20)])
        texto += 'DJF  2025   0.10\n'  # segunda ocorrência com valor MENOR, ordem irrelevante
        lista, avisos = rh.parse_roni_serie_completa(texto)
        self.assertIsNone(lista)

    def test_a11_duplicata_divergente_rejeitada(self):
        texto = _serie_sintetica([('DJF', 2025, 0.10)])
        texto += 'DJF  2025   0.20\n'
        lista, avisos = rh.parse_roni_serie_completa(texto)
        self.assertIsNone(lista)

    def test_a12_lacuna_interna_rejeitada(self):
        # DJF, JFM, (falta FMA), MAM — lacuna no meio, não no final.
        pares = [('DJF', 2025, 0.1), ('JFM', 2025, 0.2), ('MAM', 2025, 0.4)]
        texto = _serie_sintetica(pares)
        lista, avisos = rh.parse_roni_serie_completa(texto)
        self.assertIsNone(lista)

    def test_a12b_lacuna_no_final_nao_e_rejeicao(self):
        # Série termina em ASO/2026 (trimestre mais recente ainda não
        # publicado não aparece) — isso não é lacuna interna.
        lista, avisos = rh.parse_roni_serie_completa(FIXTURE_TEXTO)
        self.assertIsNotNone(lista)

    def test_a13_arquivo_truncado(self):
        texto = 'SEAS   YR  ANOM\nDJF  2025   0.10\nJFM  2025\n'
        lista, avisos = rh.parse_roni_serie_completa(texto)
        self.assertIsNone(lista)

    def test_a14_ultimo_trimestre_correto(self):
        lista, _ = rh.parse_roni_serie_completa(_serie_sintetica(SERIE_BASE))
        ultimo = rh.ultimo_da_lista(lista)
        self.assertEqual(ultimo, {'seas': 'DJF', 'ano': 2026, 'valor': 1.30})

    def test_a15_virada_djf_mes_inicial_ano_anterior(self):
        lista, _ = rh.parse_roni_serie_completa(_serie_sintetica(SERIE_BASE))
        djf = next(d for d in lista if d['temporada'] == 'DJF' and d['ano'] == 2026)
        self.assertEqual(djf['mes_inicial'], '2025-12')
        self.assertEqual(djf['mes_central'], '2026-01')
        self.assertEqual(djf['mes_final'], '2026-02')

    def test_a16_virada_ndj_mes_final_ano_seguinte(self):
        lista, _ = rh.parse_roni_serie_completa(_serie_sintetica(SERIE_BASE))
        ndj = next(d for d in lista if d['temporada'] == 'NDJ')
        self.assertEqual(ndj['mes_inicial'], '2025-11')
        self.assertEqual(ndj['mes_central'], '2025-12')
        self.assertEqual(ndj['mes_final'], '2026-01')

    def test_a17_precisao_publicada_preservada(self):
        lista, _ = rh.parse_roni_serie_completa(_serie_sintetica([('JJA', 2025, 1.36)]))
        self.assertEqual(lista[0]['valor'], 1.36)

    def test_a18_continuidade_entre_anos(self):
        # NDJ/2025 -> DJF/2026 é uma sequência válida (dezembro central
        # avança para janeiro central do ano seguinte).
        lista, avisos = rh.parse_roni_serie_completa(_serie_sintetica(SERIE_BASE))
        self.assertIsNotNone(lista)
        self.assertEqual(len(lista), 13)

    def test_a19_validar_cabecalho_tolera_espacamento(self):
        self.assertTrue(rh.validar_cabecalho('SEAS YR ANOM\nDJF 2025 0.10\n'))
        self.assertTrue(rh.validar_cabecalho('SEAS   YR  ANOM\n'))

    def test_a20_validar_cabecalho_rejeita_vazio_e_none(self):
        self.assertFalse(rh.validar_cabecalho(''))
        self.assertFalse(rh.validar_cabecalho(None))


# ══════════════════════════════════════════════════════
# GRUPO B — Snapshots e proveniência
# ══════════════════════════════════════════════════════
class SnapshotsEProveniemciaTestCase(IsolamentoMixin, unittest.TestCase):

    def test_b1_aquisicao_inicial_promovida(self):
        r = rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                    hoje=date(2026, 1, 15))
        self.assertEqual(r['estado_promocao'], 'promovida')
        self.assertEqual(r['ultimo'], {'seas': 'DJF', 'ano': 2026, 'valor': 1.30})
        self.assertTrue(rh.HISTORICO_PATH.exists())
        self.assertTrue(rh.PROVENIENCIA_PATH.exists())
        self.assertEqual(len(list(rh.SNAPSHOTS_DIR.glob('*.txt'))), 1)

    def test_b2_hash_do_snapshot_corresponde_ao_conteudo(self):
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        r = rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15))
        prov, _ = rh.ler_proveniencia_seguro()
        linha = prov[prov['aquisicao_id'] == r['aquisicao_id']].iloc[0]
        hash_esperado = rh.calcular_hash(conteudo)
        self.assertEqual(linha['hash_sha256'], hash_esperado)
        self.assertEqual(rh.caminho_snapshot(hash_esperado).read_bytes(), conteudo)

    def test_b3_revisao_recente_promovida(self):
        base = list(SERIE_BASE)
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(base).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        revisada = base[:-1] + [('DJF', 2026, 1.35)]  # revisão do trimestre mais recente
        r2 = rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(revisada).encode('utf-8'),
                                     hoje=date(2026, 1, 20))
        self.assertEqual(r2['estado_promocao'], 'promovida')
        self.assertEqual(r2['ultimo']['valor'], 1.35)

    def test_b4_trimestre_adicional_promovido(self):
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        estendida = SERIE_BASE + [('JFM', 2026, 1.40)]
        r2 = rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(estendida).encode('utf-8'),
                                     hoje=date(2026, 2, 10))
        self.assertEqual(r2['estado_promocao'], 'promovida')
        self.assertEqual(r2['ultimo'], {'seas': 'JFM', 'ano': 2026, 'valor': 1.40})

    def test_b5_conteudo_identico_nao_duplica_snapshot(self):
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15))
        r2 = rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 16))
        self.assertEqual(r2['estado_promocao'], 'reaproveitada_sem_mudanca')
        self.assertEqual(len(list(rh.SNAPSHOTS_DIR.glob('*.txt'))), 1)
        prov, _ = rh.ler_proveniencia_seguro()
        self.assertEqual(len(prov), 2)  # duas observações, mesmo conteúdo

    def test_b6_reprocessamento_mesma_aquisicao_e_idempotente(self):
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15), aquisicao_id='AQ-1')
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15), aquisicao_id='AQ-1')
        prov, _ = rh.ler_proveniencia_seguro()
        self.assertEqual(len(prov), 1)  # mesmo id, upsert, não duplica

    def test_b7_retorno_a_conteudo_anterior_reaproveita_snapshot(self):
        conteudo_a = _serie_sintetica(SERIE_BASE).encode('utf-8')
        hash_a = rh.calcular_hash(conteudo_a)
        status1 = rh.gravar_snapshot(hash_a, conteudo_a)
        conteudo_b = _serie_sintetica(SERIE_BASE + [('JFM', 2026, 1.4)]).encode('utf-8')
        rh.gravar_snapshot(rh.calcular_hash(conteudo_b), conteudo_b)
        status2 = rh.gravar_snapshot(hash_a, conteudo_a)  # retorno ao conteúdo A
        self.assertEqual(status1, 'criado')
        self.assertEqual(status2, 'reaproveitado')
        self.assertEqual(len(list(rh.SNAPSHOTS_DIR.glob('*.txt'))), 2)

    def test_b8_preservacao_de_snapshots_anteriores_apos_revisao(self):
        conteudo1 = _serie_sintetica(SERIE_BASE).encode('utf-8')
        hash1 = rh.calcular_hash(conteudo1)
        rh.processar_aquisicao(conteudo_bytes=conteudo1, hoje=date(2026, 1, 15))
        revisada = SERIE_BASE[:-1] + [('DJF', 2026, 1.35)]
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(revisada).encode('utf-8'),
                                hoje=date(2026, 1, 20))
        self.assertTrue(rh.caminho_snapshot(hash1).exists())  # snapshot antigo preservado

    def test_b9_snapshot_corrompido_detectado(self):
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        hash_ = rh.calcular_hash(conteudo)
        rh.SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        rh.caminho_snapshot(hash_).write_bytes(b'conteudo adulterado, nao corresponde ao hash')
        with self.assertRaises(rh.SerieRejeitada):
            rh.gravar_snapshot(hash_, conteudo)

    def test_b9b_pipeline_reporta_snapshot_corrompido_sem_lancar(self):
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        hash_ = rh.calcular_hash(conteudo)
        rh.SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        rh.caminho_snapshot(hash_).write_bytes(b'conteudo adulterado')
        r = rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15))
        self.assertEqual(r['estado_promocao'], 'rejeitada_snapshot_corrompido')

    def test_b10_hoje_controlado_por_fixture_afeta_janela_de_revisao(self):
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        revisada = SERIE_BASE[:-1] + [('DJF', 2026, 1.35)]
        r_recente = rh.processar_aquisicao(
            conteudo_bytes=_serie_sintetica(revisada).encode('utf-8'), hoje=date(2026, 2, 1))
        self.assertEqual(r_recente['estado_promocao'], 'promovida')


# ══════════════════════════════════════════════════════
# GRUPO C — Revisões e integridade
# ══════════════════════════════════════════════════════
class RevisoesEIntegridadeTestCase(IsolamentoMixin, unittest.TestCase):

    def test_c1_revisao_recente_legitima_direto(self):
        lista_antiga, _ = rh.parse_roni_serie_completa(_serie_sintetica(SERIE_BASE))
        df_antiga = rh._serie_para_dataframe(
            [{**d, 'versao_metodologica': 'ERSSTv6', 'snapshot_sha256': 'x'} for d in lista_antiga])
        nova = SERIE_BASE[:-1] + [('DJF', 2026, 1.35)]
        lista_nova, _ = rh.parse_roni_serie_completa(_serie_sintetica(nova))
        comp = rh.comparar_series(df_antiga, lista_nova)
        estado, _ = rh.decidir_promocao(comp, date(2026, 2, 1))
        self.assertEqual(estado, 'promovida')

    def test_c2_revisao_historica_inesperada_nao_promovida(self):
        lista_antiga, _ = rh.parse_roni_serie_completa(_serie_sintetica(SERIE_BASE))
        df_antiga = rh._serie_para_dataframe(
            [{**d, 'versao_metodologica': 'ERSSTv6', 'snapshot_sha256': 'x'} for d in lista_antiga])
        # Revisa DJF/2025 (11 meses antes de 2026-01, fora da janela de 2m).
        nova = [('DJF', 2025, 0.99)] + SERIE_BASE[1:]
        lista_nova, _ = rh.parse_roni_serie_completa(_serie_sintetica(nova))
        comp = rh.comparar_series(df_antiga, lista_nova)
        estado, motivo = rh.decidir_promocao(comp, date(2026, 1, 15))
        self.assertEqual(estado, 'rejeitada_revisao_historica_inesperada')
        self.assertIn('DJF/2025', motivo)

    def test_c3_cobertura_reduzida_rejeitada(self):
        lista_antiga, _ = rh.parse_roni_serie_completa(_serie_sintetica(SERIE_BASE))
        df_antiga = rh._serie_para_dataframe(
            [{**d, 'versao_metodologica': 'ERSSTv6', 'snapshot_sha256': 'x'} for d in lista_antiga])
        reduzida = SERIE_BASE[:-1]  # remove o trimestre mais recente
        lista_nova, _ = rh.parse_roni_serie_completa(_serie_sintetica(reduzida))
        comp = rh.comparar_series(df_antiga, lista_nova)
        estado, _ = rh.decidir_promocao(comp, date(2026, 1, 15))
        self.assertEqual(estado, 'rejeitada_cobertura_reduzida')

    def test_c4_versao_metodologica_e_constante_nunca_inferida(self):
        # Limitação documentada: o arquivo não autodeclara a versão
        # ERSST — versao_metodologica é sempre a constante do módulo,
        # nunca algo lido/inferido do conteúdo.
        r = rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                    hoje=date(2026, 1, 15))
        df = rh._ler_serie_persistida()
        self.assertTrue((df['versao_metodologica'] == rh.VERSAO_METODOLOGICA).all())

    def test_c5_falha_de_coleta_preserva_ultima_valida(self):
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        with patch.object(rh, 'buscar_bytes_brutos', side_effect=TimeoutError('rede indisponível')):
            r = rh.processar_aquisicao(hoje=date(2026, 1, 20))
        self.assertEqual(r['estado_promocao'], 'rejeitada_falha_coleta')
        self.assertEqual(r['ultimo'], {'seas': 'DJF', 'ano': 2026, 'valor': 1.30})

    def test_c6_rejeicao_estrutural_preserva_ultima_valida(self):
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        r = rh.processar_aquisicao(conteudo_bytes=b'<html>pagina de erro</html>', hoje=date(2026, 1, 20))
        self.assertEqual(r['estado_promocao'], 'rejeitada_estrutural')
        self.assertEqual(r['ultimo'], {'seas': 'DJF', 'ano': 2026, 'valor': 1.30})

    def test_c7_preservacao_apos_rejeicao_nao_altera_arquivo(self):
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        hash_antes = rh.calcular_hash(rh.HISTORICO_PATH.read_bytes())
        rh.processar_aquisicao(conteudo_bytes=b'invalido', hoje=date(2026, 1, 20))
        hash_depois = rh.calcular_hash(rh.HISTORICO_PATH.read_bytes())
        self.assertEqual(hash_antes, hash_depois)

    def test_c8_reconstrucao_exata_pelo_snapshot(self):
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        ok, avisos = rh.serie_ativa_corresponde_ao_snapshot()
        self.assertTrue(ok, avisos)


# ══════════════════════════════════════════════════════
# GRUPO D — Persistência e recuperação
# ══════════════════════════════════════════════════════
class PersistenciaERecuperacaoTestCase(IsolamentoMixin, unittest.TestCase):

    def test_d1_snapshot_corrompido_nao_promove(self):
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        hash_ = rh.calcular_hash(conteudo)
        rh.SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        rh.caminho_snapshot(hash_).write_bytes(b'lixo')
        r = rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15))
        self.assertEqual(r['estado_promocao'], 'rejeitada_snapshot_corrompido')
        self.assertFalse(rh.HISTORICO_PATH.exists())

    def test_d2_proveniencia_tolera_linha_final_truncada(self):
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        with rh.PROVENIENCIA_PATH.open('a', encoding='utf-8') as f:
            # linha com campos extras (mais vírgulas que o cabeçalho) —
            # o parser C do pandas levanta ParserError ao tokenizar,
            # simulando corrupção real por interrupção durante a escrita.
            f.write('AQ-trunc,2026-01-16T00:00:00+00:00,http://x,NOAA,ERSSTv6,'
                    'hash,repr,caminho,primeiro,ultimo,1,parser,aceita,'
                    'True,True,promovida,,EXTRA,CAMPOS,A,MAIS\n')
        df, avisos = rh.ler_proveniencia_seguro()
        self.assertTrue(avisos)
        self.assertGreaterEqual(len(df), 1)

    def test_d3_manifesto_perdido_com_serie_presente_nunca_e_recuperado_silenciosamente(self):
        # Fase 2.2, Correção 5 (Cenário C): apagar o manifesto INTEIRO
        # enquanto a série normalizada continua presente NÃO é o mesmo
        # que "primeira aquisição" — representa perda de evidência de
        # aquisições anteriores, sem recuperação inequívoca possível
        # (não sabemos quantas aquisições existiram nem seus fatos).
        # `serie_ativa_corresponde_ao_snapshot()` sozinha não basta para
        # detectar este cenário específico (a série continua
        # autoconsistente com seu próprio snapshot) — por isso
        # `verificar_integridade_roni()` cruza com o manifesto
        # (Cenário F) e `processar_aquisicao()` recusa explicitamente
        # processar qualquer coisa nessa condição.
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15))
        hash_antes = rh.calcular_hash(rh.HISTORICO_PATH.read_bytes())

        rh.PROVENIENCIA_PATH.unlink()

        ok, avisos = rh.verificar_integridade_roni()
        self.assertFalse(ok, avisos)  # inconsistência DETECTADA via verificar_integridade_roni

        # NUNCA recuperado silenciosamente por um simples reprocessamento
        # — mesmo com o MESMO conteúdo de antes.
        r = rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 16))
        self.assertEqual(r['estado_promocao'], 'rejeitada_manifesto_perdido')
        # A série ativa permanece exatamente como estava — nada foi
        # reescrito por essa tentativa.
        self.assertEqual(hash_antes, rh.calcular_hash(rh.HISTORICO_PATH.read_bytes()))

        # A recuperação explícita (Cenário B) também falha aqui, porque
        # este NÃO é o Cenário B — é o Cenário C (manifesto ausente),
        # para o qual não há reconstrução segura.
        ok_rec, avisos_rec = rh.reconstruir_serie_a_partir_do_manifesto()
        self.assertFalse(ok_rec, avisos_rec)

    def test_d4_arquivo_historico_nunca_fica_parcial(self):
        # _gravar_serie_historico usa escrita em .tmp + replace atômico
        # — confirmamos que nenhum .tmp sobra após a operação.
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        tmp_residuais = list(rh.HISTORICO_PATH.parent.glob('*.tmp'))
        self.assertEqual(tmp_residuais, [])

    def test_d5_decodificacao_invalida_nunca_promove(self):
        r = rh.processar_aquisicao(conteudo_bytes=b'\xff\xfe\x00\x01', hoje=date(2026, 1, 15))
        self.assertEqual(r['estado_promocao'], 'rejeitada_estrutural')
        self.assertFalse(rh.HISTORICO_PATH.exists())

    _CSV_CORROMPIDO = (
        'temporada,ano,mes_inicial,mes_central,mes_final,valor,versao_metodologica,snapshot_sha256\n'
        'DJF,2025,2024-12,2025-01,2025-02,0.1,ERSSTv6,abc\n'
        'JFM,2025,2025-01,2025-02,2025-03,0.2,ERSSTv6,abc,CAMPO,EXTRA\n'  # linhas com nº de campos divergente
    )

    def test_d7_base_corrompida_nunca_e_confundida_com_ausente(self):
        # Simula roni_historico.csv EXISTENTE mas corrompido (linhas com
        # número de campos divergente — nunca o mesmo caso de "primeira
        # aquisição, arquivo nunca existiu").
        rh.HISTORICO_PATH.parent.mkdir(parents=True, exist_ok=True)
        rh.HISTORICO_PATH.write_text(self._CSV_CORROMPIDO, encoding='utf-8')
        r = rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                    hoje=date(2026, 1, 15))
        self.assertEqual(r['estado_promocao'], 'rejeitada_base_corrompida')
        self.assertIsNone(r['ultimo'])
        # A base corrompida NUNCA é silenciosamente sobrescrita por uma
        # nova inicialização — o conteúdo corrompido original permanece.
        self.assertEqual(rh.HISTORICO_PATH.read_text(encoding='utf-8'), self._CSV_CORROMPIDO)

    def test_d8_serie_ativa_corresponde_ao_snapshot_reporta_base_corrompida(self):
        rh.HISTORICO_PATH.parent.mkdir(parents=True, exist_ok=True)
        rh.HISTORICO_PATH.write_text(self._CSV_CORROMPIDO, encoding='utf-8')
        ok, avisos = rh.serie_ativa_corresponde_ao_snapshot()
        self.assertFalse(ok)
        self.assertTrue(avisos)

    def test_d6_nenhum_arquivo_temporario_apos_fluxo_completo(self):
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        revisada = SERIE_BASE[:-1] + [('DJF', 2026, 1.35)]
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(revisada).encode('utf-8'),
                                hoje=date(2026, 1, 20))
        residuais = list(Path(rh.HISTORICO_PATH.parent).rglob('*.tmp'))
        self.assertEqual(residuais, [])


# ══════════════════════════════════════════════════════
# GRUPO E — Compatibilidade
# ══════════════════════════════════════════════════════
class CompatibilidadeTestCase(IsolamentoMixin, unittest.TestCase):

    def test_e1_parse_roni_legado_intocado(self):
        sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
        import update_indices as ui
        seas, ano, val = ui.parse_roni('SEAS   YR  ANOM\nJJA  2026   1.36\n')
        self.assertEqual((seas, ano, val), ('JJA', 2026, 1.36))

    def test_e2_ultimo_da_serie_ativa_coincide_com_ultimo_da_lista(self):
        lista, _ = rh.parse_roni_serie_completa(_serie_sintetica(SERIE_BASE))
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        self.assertEqual(rh.ultimo_da_serie_ativa(), rh.ultimo_da_lista(lista))

    def test_e3_formato_do_ultimo_compativel_com_const_roni(self):
        r = rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                    hoje=date(2026, 1, 15))
        self.assertEqual(set(r['ultimo'].keys()), {'seas', 'ano', 'valor'})

    def test_e4_ultimo_none_quando_nunca_promovido(self):
        r = rh.processar_aquisicao(conteudo_bytes=b'<html>erro</html>', hoje=date(2026, 1, 15))
        self.assertIsNone(r['ultimo'])

    def test_e5_modulo_nunca_referencia_dashboard_html(self):
        # O módulo pode MENCIONAR docs/index.html ou 'const RONI' em
        # prosa (explicando por que nunca compara contra eles), mas
        # nunca importa/usa a variável DASHBOARD (o Path real do HTML
        # em update_indices.py/verificar_dashboard.py) nem abre esse
        # arquivo para leitura/escrita.
        texto_modulo = Path(rh.__file__).read_text(encoding='utf-8')
        self.assertNotIn('DASHBOARD =', texto_modulo)
        self.assertNotIn('DASHBOARD.read', texto_modulo)
        self.assertNotIn('DASHBOARD.write', texto_modulo)

    def test_e6_modulo_nunca_referencia_modelos_cientificos(self):
        texto_modulo = Path(rh.__file__).read_text(encoding='utf-8')
        for termo in ('SARIMAX', 'XGBoost', 'n34_l23', 'tsa_l23', 'pdo_l23', 'CAD', 'ETP'):
            self.assertNotIn(termo, texto_modulo)


# ══════════════════════════════════════════════════════
# verificar_integridade_roni() — verificação somente leitura
# ══════════════════════════════════════════════════════
class VerificarIntegridadeRoniTestCase(IsolamentoMixin, unittest.TestCase):

    def test_nenhum_artefato_nao_e_falha(self):
        ok, msgs = rh.verificar_integridade_roni()
        self.assertTrue(ok)
        self.assertTrue(msgs)

    def test_estado_valido_apos_promocao(self):
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        ok, msgs = rh.verificar_integridade_roni()
        self.assertTrue(ok, msgs)

    def test_snapshot_ausente_reprovado(self):
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        for f in rh.SNAPSHOTS_DIR.glob('*.txt'):
            f.unlink()
        ok, msgs = rh.verificar_integridade_roni()
        self.assertFalse(ok)
        self.assertTrue(msgs)

    def test_hash_divergente_conteudo_do_snapshot_alterado(self):
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        hash_ = rh.calcular_hash(conteudo)
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15))
        # Adultera o CONTEÚDO do arquivo de snapshot sem renomeá-lo —
        # o nome ainda diz `hash_`, mas o conteúdo não bate mais.
        rh.caminho_snapshot(hash_).write_bytes(_serie_sintetica(SERIE_BASE[:-1]).encode('utf-8'))
        ok, msgs = rh.verificar_integridade_roni()
        self.assertFalse(ok, msgs)

    def test_manifesto_ausente_reprovado(self):
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        rh.PROVENIENCIA_PATH.unlink()
        ok, msgs = rh.verificar_integridade_roni()
        self.assertFalse(ok)
        # Fase 2.2: a série ainda se autovalida contra seu próprio
        # snapshot (Correção 2/3) — o que a reprova aqui é o cruzamento
        # com o manifesto (Cenário F, Seção 8.3): nenhuma promoção
        # registrada para o hash que a série referencia.
        self.assertIn('não registra nenhuma promoção', ' '.join(msgs))

    def test_serie_adulterada_valor_alterado_reprovada(self):
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        df = rh._ler_serie_persistida()
        df.loc[df.index[-1], 'valor'] = 99.0  # adulteração direta, fora do pipeline
        df.to_csv(rh.HISTORICO_PATH, index=False)
        ok, msgs = rh.verificar_integridade_roni()
        self.assertFalse(ok, msgs)

    def test_serie_adulterada_duplicidade_reprovada(self):
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        df = rh._ler_serie_persistida()
        duplicada = pd.concat([df, df.iloc[[-1]]], ignore_index=True)
        duplicada.to_csv(rh.HISTORICO_PATH, index=False)
        ok, msgs = rh.verificar_integridade_roni()
        self.assertFalse(ok, msgs)

    def test_serie_adulterada_lacuna_interna_reprovada(self):
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        df = rh._ler_serie_persistida()
        reduzida = df.drop(df.index[5]).reset_index(drop=True)  # remove um trimestre do meio
        reduzida.to_csv(rh.HISTORICO_PATH, index=False)
        ok, msgs = rh.verificar_integridade_roni()
        self.assertFalse(ok, msgs)

    def test_base_corrompida_reprovada_explicitamente(self):
        rh.HISTORICO_PATH.parent.mkdir(parents=True, exist_ok=True)
        rh.HISTORICO_PATH.write_text(PersistenciaERecuperacaoTestCase._CSV_CORROMPIDO,
                                      encoding='utf-8')
        ok, msgs = rh.verificar_integridade_roni()
        self.assertFalse(ok)
        self.assertTrue(msgs)

    def test_preservacao_dos_arquivos_durante_a_verificacao(self):
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        hash_historico_antes = rh.calcular_hash(rh.HISTORICO_PATH.read_bytes())
        hash_prov_antes = rh.calcular_hash(rh.PROVENIENCIA_PATH.read_bytes())
        n_snapshots_antes = len(list(rh.SNAPSHOTS_DIR.glob('*.txt')))
        for _ in range(3):
            rh.verificar_integridade_roni()
        self.assertEqual(hash_historico_antes, rh.calcular_hash(rh.HISTORICO_PATH.read_bytes()))
        self.assertEqual(hash_prov_antes, rh.calcular_hash(rh.PROVENIENCIA_PATH.read_bytes()))
        self.assertEqual(n_snapshots_antes, len(list(rh.SNAPSHOTS_DIR.glob('*.txt'))))


# ══════════════════════════════════════════════════════
# Fase ENSO-RONI-MIGRAÇÃO 2.2 — Correção 1: janela de revisão oficial
# ══════════════════════════════════════════════════════
class JanelaRevisaoOficialTestCase(IsolamentoMixin, unittest.TestCase):
    """Mês central, mês final, publicação inicial e primeira
    observação pelo sistema são eventos distintos (Seção 4.1). Estes
    testes identificam explicitamente, em cada cenário, se a data usada
    é COMPROVADA (passada via `datas_publicacao_informadas`, uma
    fixture hipotética — nunca uma data real do CPC, que esta fonte não
    publica) ou ESTIMADA (calendário: mês final + 1)."""

    _BASE_ATE_ASO = [
        ('DJF', 2025, 0.10), ('JFM', 2025, 0.20), ('FMA', 2025, 0.30),
        ('MAM', 2025, 0.40), ('AMJ', 2025, 0.50), ('MJJ', 2025, 0.60),
        ('JJA', 2025, 0.70), ('JAS', 2025, 0.80), ('ASO', 2025, 0.90),
        ('SON', 2025, 1.00), ('OND', 2025, 1.10), ('NDJ', 2025, 1.20),
        ('DJF', 2026, 1.30), ('JFM', 2026, 1.35), ('FMA', 2026, 1.40),
        ('MAM', 2026, 1.45), ('AMJ', 2026, 1.50), ('MJJ', 2026, 1.55),
        ('JJA', 2026, 1.60), ('JAS', 2026, 1.65), ('ASO', 2026, 1.97),
    ]

    def test_reproducao_regra_antiga_rejeitava_revisao_legitima_de_dezembro(self):
        """Seção 4.2: ASO/2026 — mês central set/2026, mês final
        out/2026, publicação inicial (fixture hipotética) nov/2026,
        revisão em dez/2026. A fórmula ANTIGA (mês central, sem +1 mês)
        teria contado 3 meses (set→dez) e rejeitado uma revisão que,
        pela janela real do CPC a partir da publicação (nov→dez = 1
        mês), é legítima."""
        hoje = date(2026, 12, 10)
        mes_central = rh._SEAS_PARA_MES_CENTRAL['ASO']  # 9 (setembro)
        meses_pela_regra_antiga = (hoje.year - 2026) * 12 + (hoje.month - mes_central)
        self.assertEqual(meses_pela_regra_antiga, 3)
        self.assertGreater(meses_pela_regra_antiga, rh.JANELA_REVISAO_RECENTE_MESES)  # a regra antiga rejeitaria

        # A correção: usando a publicação informada (fixture
        # hipotética) de nov/2026, só decorreu 1 mês até dez/2026.
        ano_pub, mes_pub, origem = rh._referencia_disponibilidade(
            2026, 'ASO', '2026-10', datas_publicacao_informadas={(2026, 'ASO'): (2026, 11)})
        self.assertEqual((ano_pub, mes_pub, origem), (2026, 11, 'informada'))
        meses_corrigido = (hoje.year - ano_pub) * 12 + (hoje.month - mes_pub)
        self.assertEqual(meses_corrigido, 1)
        self.assertLessEqual(meses_corrigido, rh.JANELA_REVISAO_RECENTE_MESES)

    def test_correcao_aceita_revisao_de_dezembro_com_novo_trimestre_simultaneo(self):
        """Mesmo cenário da reprodução, mas através do pipeline
        completo: revisão de ASO/2026 (dentro da janela, usando a data
        de publicação informada) + inclusão simultânea de SON/2026
        (trimestre novo) — a aquisição inteira deve ser promovida, não
        rejeitada por causa da revisão."""
        base = _serie_sintetica(self._BASE_ATE_ASO).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=base, hoje=date(2026, 11, 20))

        revisada = self._BASE_ATE_ASO[:-1] + [('ASO', 2026, 2.01), ('SON', 2026, 2.10)]
        r = rh.processar_aquisicao(
            conteudo_bytes=_serie_sintetica(revisada).encode('utf-8'),
            hoje=date(2026, 12, 10),
            datas_publicacao_informadas={(2026, 'ASO'): (2026, 11)})
        self.assertEqual(r['estado_promocao'], 'promovida')
        self.assertEqual(r['ultimo'], {'seas': 'SON', 'ano': 2026, 'valor': 2.10})

    def test_revisao_no_mes_da_publicacao_inicial_estimada(self):
        # ASO/2026: mês final out/2026 → publicação ESTIMADA nov/2026.
        # Revisão no PRÓPRIO mês da publicação estimada (0 meses).
        base = _serie_sintetica(self._BASE_ATE_ASO).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=base, hoje=date(2026, 11, 5))
        revisada = self._BASE_ATE_ASO[:-1] + [('ASO', 2026, 2.00)]
        r = rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(revisada).encode('utf-8'),
                                    hoje=date(2026, 11, 20))
        self.assertEqual(r['estado_promocao'], 'promovida')

    def test_revisao_no_mes_seguinte_a_publicacao_estimada(self):
        base = _serie_sintetica(self._BASE_ATE_ASO).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=base, hoje=date(2026, 11, 5))
        revisada = self._BASE_ATE_ASO[:-1] + [('ASO', 2026, 2.02)]
        r = rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(revisada).encode('utf-8'),
                                    hoje=date(2026, 12, 15))
        self.assertEqual(r['estado_promocao'], 'promovida')

    def test_revisao_no_segundo_mes_posterior_a_publicacao_estimada(self):
        base = _serie_sintetica(self._BASE_ATE_ASO).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=base, hoje=date(2026, 11, 5))
        revisada = self._BASE_ATE_ASO[:-1] + [('ASO', 2026, 2.03)]
        r = rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(revisada).encode('utf-8'),
                                    hoje=date(2027, 1, 10))
        self.assertEqual(r['estado_promocao'], 'promovida')

    def test_revisao_fora_da_janela_sinalizada_nao_promovida(self):
        base = _serie_sintetica(self._BASE_ATE_ASO).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=base, hoje=date(2026, 11, 5))
        revisada = self._BASE_ATE_ASO[:-1] + [('ASO', 2026, 2.04)]
        r = rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(revisada).encode('utf-8'),
                                    hoje=date(2027, 2, 1))  # 3 meses após nov/2026
        self.assertEqual(r['estado_promocao'], 'rejeitada_revisao_historica_inesperada')
        # A série ativa preserva o valor original (2026, não 2.04).
        self.assertEqual(r['ultimo']['valor'], 1.97)

    def test_virada_de_ano_djf(self):
        # DJF/2026: mês final fev/2026 → publicação estimada mar/2026.
        base = [('NDJ', 2025, 1.20), ('DJF', 2026, 1.30), ('JFM', 2026, 1.35)]
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(base).encode('utf-8'),
                                hoje=date(2026, 3, 5))
        revisada = [('NDJ', 2025, 1.20), ('DJF', 2026, 1.32), ('JFM', 2026, 1.35)]
        r = rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(revisada).encode('utf-8'),
                                    hoje=date(2026, 4, 15))  # 1 mês após mar/2026
        self.assertEqual(r['estado_promocao'], 'promovida')

    def test_virada_de_ano_ndj(self):
        # NDJ/2025: mês final jan/2026 → publicação estimada fev/2026.
        base = [('OND', 2025, 1.10), ('NDJ', 2025, 1.20), ('DJF', 2026, 1.30)]
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(base).encode('utf-8'),
                                hoje=date(2026, 2, 5))
        revisada = [('OND', 2025, 1.10), ('NDJ', 2025, 1.22), ('DJF', 2026, 1.30)]
        r = rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(revisada).encode('utf-8'),
                                    hoje=date(2026, 3, 20))  # 1 mês após fev/2026
        self.assertEqual(r['estado_promocao'], 'promovida')

    def test_revisao_historica_inesperada_com_novo_trimestre_simultaneo_tambem_nao_promove(self):
        # Mesmo com um trimestre novo legítimo incluído, uma revisão
        # fora da janela ainda bloqueia a aquisição INTEIRA (mesmo
        # comportamento de antes — nunca promove parcialmente).
        base = _serie_sintetica(self._BASE_ATE_ASO).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=base, hoje=date(2026, 11, 5))
        revisada = self._BASE_ATE_ASO[:-1] + [('ASO', 2026, 2.05), ('SON', 2026, 2.10)]
        r = rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(revisada).encode('utf-8'),
                                    hoje=date(2027, 3, 1))
        self.assertEqual(r['estado_promocao'], 'rejeitada_revisao_historica_inesperada')
        self.assertEqual(r['ultimo']['seas'], 'ASO')  # SON/2026 NÃO foi adicionado

    def test_serie_inicial_com_periodos_antigos_nunca_elegivel_a_revisao_recente(self):
        """A aquisição inicial contém dados desde 1950 (fixture real),
        mas isso não significa que esses trimestres estejam "recém-
        publicados" — a primeira aquisição nunca passa pela lógica de
        janela de revisão, porque `comparar_series` não tem base
        anterior para detectar "revisão" nenhuma (todos entram como
        `trimestres_novos`, nunca `valores_revisados`)."""
        lista, _ = rh.parse_roni_serie_completa(FIXTURE_TEXTO)
        comp = rh.comparar_series(None, lista)
        self.assertEqual(comp['valores_revisados'], [])
        self.assertEqual(len(comp['trimestres_novos']), 921)
        estado, _ = rh.decidir_promocao(comp, date(2026, 11, 27))
        self.assertEqual(estado, 'promovida')


# ══════════════════════════════════════════════════════
# Fase ENSO-RONI-MIGRAÇÃO 2.2 — Correção 2: alterações exclusivamente
# textuais nunca trocam a âncora de reconstrução sem reescrever a série
# ══════════════════════════════════════════════════════
class AlteracoesTextuaisTestCase(IsolamentoMixin, unittest.TestCase):

    def _conteudo_com_espacamento_alterado(self, pares):
        linhas = ['SEAS   YR  ANOM']  # cabeçalho idêntico (exigido)
        for seas, ano, val in pares:
            linhas.append(f'{seas}    {ano}  {val:>7.3f}')  # espaçamento diferente
        return ('\n'.join(linhas) + '\n\n').encode('utf-8')  # linha em branco extra ao final

    def test_a_conteudo_e_valores_identicos_reaproveita_sem_mudanca(self):
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15))
        r2 = rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 16))
        self.assertEqual(r2['estado_promocao'], 'reaproveitada_sem_mudanca')

    def test_b_texto_diferente_valores_identicos_nao_troca_ancora(self):
        conteudo1 = _serie_sintetica(SERIE_BASE).encode('utf-8')
        r1 = rh.processar_aquisicao(conteudo_bytes=conteudo1, hoje=date(2026, 1, 15))
        hash1 = rh.calcular_hash(conteudo1)

        conteudo2 = self._conteudo_com_espacamento_alterado(SERIE_BASE)
        self.assertNotEqual(rh.calcular_hash(conteudo2), hash1)  # hash realmente diferente
        r2 = rh.processar_aquisicao(conteudo_bytes=conteudo2, hoje=date(2026, 1, 16))

        self.assertEqual(r2['estado_promocao'], 'observada_texto_diferente_valor_identico')
        # A série ativa NUNCA trocou de âncora — continua referenciando
        # o hash ORIGINAL, nunca o novo.
        df = rh._ler_serie_persistida()
        self.assertEqual(set(df['snapshot_sha256'].unique()), {hash1})
        # Mas os dois snapshots foram preservados (nunca descartados).
        self.assertTrue(rh.caminho_snapshot(hash1).exists())
        self.assertTrue(rh.caminho_snapshot(rh.calcular_hash(conteudo2)).exists())
        # E a série continua íntegra e reconstruível.
        ok, avisos = rh.serie_ativa_corresponde_ao_snapshot()
        self.assertTrue(ok, avisos)
        ok2, avisos2 = rh.verificar_integridade_roni()
        self.assertTrue(ok2, avisos2)

    def test_c_texto_diferente_e_valor_revisado_promove_normalmente(self):
        conteudo1 = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=conteudo1, hoje=date(2026, 1, 15))
        revisada = SERIE_BASE[:-1] + [('DJF', 2026, 1.99)]
        conteudo2 = self._conteudo_com_espacamento_alterado(revisada)
        r2 = rh.processar_aquisicao(conteudo_bytes=conteudo2, hoje=date(2026, 1, 20))
        self.assertEqual(r2['estado_promocao'], 'promovida')
        self.assertEqual(r2['ultimo']['valor'], 1.99)
        df = rh._ler_serie_persistida()
        self.assertEqual(set(df['snapshot_sha256'].unique()), {rh.calcular_hash(conteudo2)})

    def test_d_retorno_a_conteudo_previamente_observado(self):
        conteudo_a = _serie_sintetica(SERIE_BASE).encode('utf-8')
        conteudo_b = self._conteudo_com_espacamento_alterado(SERIE_BASE)
        rh.processar_aquisicao(conteudo_bytes=conteudo_a, hoje=date(2026, 1, 15))
        rh.processar_aquisicao(conteudo_bytes=conteudo_b, hoje=date(2026, 1, 16))
        r3 = rh.processar_aquisicao(conteudo_bytes=conteudo_a, hoje=date(2026, 1, 17))
        # Retorno ao conteúdo A (já observado, e é o hash ATIVO) — nada
        # de novo a fazer.
        self.assertEqual(r3['estado_promocao'], 'reaproveitada_sem_mudanca')
        ok, avisos = rh.verificar_integridade_roni()
        self.assertTrue(ok, avisos)

    def test_e_alteracao_de_quebra_de_linha_tambem_detectada(self):
        conteudo1 = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=conteudo1, hoje=date(2026, 1, 15))
        conteudo_crlf = conteudo1.replace(b'\n', b'\r\n')
        self.assertNotEqual(rh.calcular_hash(conteudo_crlf), rh.calcular_hash(conteudo1))
        r2 = rh.processar_aquisicao(conteudo_bytes=conteudo_crlf, hoje=date(2026, 1, 16))
        self.assertEqual(r2['estado_promocao'], 'observada_texto_diferente_valor_identico')

    def test_f_alterou_texto_reflete_comparacao_com_ativo_nao_criacao_de_arquivo(self):
        conteudo1 = _serie_sintetica(SERIE_BASE).encode('utf-8')
        conteudo2 = self._conteudo_com_espacamento_alterado(SERIE_BASE)
        rh.processar_aquisicao(conteudo_bytes=conteudo1, hoje=date(2026, 1, 15))
        rh.processar_aquisicao(conteudo_bytes=conteudo2, hoje=date(2026, 1, 16))
        # Reobservar o conteúdo2 (já existe como snapshot, não seria
        # "criado" de novo) ainda deve reportar alterou_texto=True,
        # porque DIFERE do hash ativo (que continua sendo o de conteudo1).
        r3 = rh.processar_aquisicao(conteudo_bytes=conteudo2, hoje=date(2026, 1, 17))
        prov, _ = rh.ler_proveniencia_seguro()
        linha = prov[prov['aquisicao_id'] == r3['aquisicao_id']].iloc[0]
        self.assertEqual(bool(linha['alterou_texto']), True)


# ══════════════════════════════════════════════════════
# Fase ENSO-RONI-MIGRAÇÃO 2.2 — Correção 3: verificação efetiva de hash
# ══════════════════════════════════════════════════════
class VerificacaoEfetivaDeHashTestCase(IsolamentoMixin, unittest.TestCase):

    def test_snapshot_ativo_integro_reconstroi(self):
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15))
        lista, avisos = rh.reconstruir_da_snapshot(rh.calcular_hash(conteudo))
        self.assertIsNotNone(lista, avisos)

    def test_snapshot_ativo_alterado_so_nos_espacos_e_detectado(self):
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        hash_ = rh.calcular_hash(conteudo)
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15))
        # Adultera o ARQUIVO do snapshot sob o mesmo nome — só espaços,
        # os valores climáticos resultantes seriam os mesmos, mas o
        # hash do conteúdo não bate mais.
        rh.caminho_snapshot(hash_).write_bytes(conteudo.replace(b' ', b'  '))
        lista, avisos = rh.reconstruir_da_snapshot(hash_)
        self.assertIsNone(lista)
        self.assertTrue(any('CORROMPIDO' in a for a in avisos))

    def test_snapshot_ativo_com_alteracao_climatica_e_detectada(self):
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        hash_ = rh.calcular_hash(conteudo)
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15))
        rh.caminho_snapshot(hash_).write_bytes(
            _serie_sintetica(SERIE_BASE[:-1] + [('DJF', 2026, 4.99)]).encode('utf-8'))
        lista, avisos = rh.reconstruir_da_snapshot(hash_)
        self.assertIsNone(lista)

    def test_snapshot_antigo_aceito_ausente_reprova_verificacao_completa(self):
        c1 = _serie_sintetica(SERIE_BASE).encode('utf-8')
        h1 = rh.calcular_hash(c1)
        rh.processar_aquisicao(conteudo_bytes=c1, hoje=date(2026, 1, 15))
        revisada = SERIE_BASE[:-1] + [('DJF', 2026, 1.77)]
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(revisada).encode('utf-8'),
                                hoje=date(2026, 1, 20))
        rh.caminho_snapshot(h1).unlink()  # remove o snapshot ANTIGO (não o ativo)
        ok, msgs = rh.verificar_integridade_roni()
        self.assertFalse(ok, msgs)
        self.assertTrue(any(h1 in m for m in msgs))

    def test_snapshot_antigo_aceito_adulterado_reprova_verificacao_completa(self):
        c1 = _serie_sintetica(SERIE_BASE).encode('utf-8')
        h1 = rh.calcular_hash(c1)
        rh.processar_aquisicao(conteudo_bytes=c1, hoje=date(2026, 1, 15))
        revisada = SERIE_BASE[:-1] + [('DJF', 2026, 1.78)]
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(revisada).encode('utf-8'),
                                hoje=date(2026, 1, 20))
        rh.caminho_snapshot(h1).write_bytes(b'lixo adulterado')
        ok, msgs = rh.verificar_integridade_roni()
        self.assertFalse(ok, msgs)

    def test_hash_invalido_no_manifesto_reprova(self):
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15))
        df = pd.read_csv(rh.PROVENIENCIA_PATH)
        df.loc[0, 'hash_sha256'] = 'não-é-um-hash-valido'
        df.to_csv(rh.PROVENIENCIA_PATH, index=False)
        ok, msgs = rh.verificar_integridade_roni()
        self.assertFalse(ok, msgs)
        self.assertTrue(any('formato' in m for m in msgs))

    def test_caminho_de_snapshot_incompativel_reprova(self):
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15))
        df = pd.read_csv(rh.PROVENIENCIA_PATH)
        df.loc[0, 'caminho_snapshot'] = 'data/roni_snapshots/outro_arquivo.txt'
        df.to_csv(rh.PROVENIENCIA_PATH, index=False)
        ok, msgs = rh.verificar_integridade_roni()
        self.assertFalse(ok, msgs)
        self.assertTrue(any('estrutura aprovada' in m for m in msgs))

    def test_verificacao_e_somente_leitura_mesmo_detectando_problema(self):
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        h = rh.calcular_hash(conteudo)
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15))
        rh.caminho_snapshot(h).write_bytes(b'lixo')
        hash_historico_antes = rh.calcular_hash(rh.HISTORICO_PATH.read_bytes())
        hash_prov_antes = rh.calcular_hash(rh.PROVENIENCIA_PATH.read_bytes())
        rh.verificar_integridade_roni()
        self.assertEqual(hash_historico_antes, rh.calcular_hash(rh.HISTORICO_PATH.read_bytes()))
        self.assertEqual(hash_prov_antes, rh.calcular_hash(rh.PROVENIENCIA_PATH.read_bytes()))
        self.assertTrue(rh.caminho_snapshot(h).exists())  # nunca sobrescrito/removido


# ══════════════════════════════════════════════════════
# Fase ENSO-RONI-MIGRAÇÃO 2.2 — Correção 4: unicidade e cobertura
# (complementa os testes a10/a10b/a10c/a11 já no Grupo A)
# ══════════════════════════════════════════════════════
class UnicidadeECoberturaTestCase(IsolamentoMixin, unittest.TestCase):

    def test_reducao_de_cobertura_em_relacao_a_serie_ativa_e_rejeitada(self):
        """Demonstra que a política já existente de `comparar_series`/
        `decidir_promocao` (cobertura_reduzida) cobre exatamente o caso
        de 'início truncado em relação ao que já está ativo' — não é
        necessário duplicar essa regra dentro do validador estrutural
        (que opera sobre um documento isolado, sem saber o que está
        ativo). Uma série sintética começando DEPOIS do início já
        ativo, mesmo sendo internamente consecutiva, é rejeitada."""
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        truncada_no_inicio = SERIE_BASE[3:]  # remove os 3 primeiros trimestres
        r = rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(truncada_no_inicio).encode('utf-8'),
                                    hoje=date(2026, 1, 20))
        self.assertEqual(r['estado_promocao'], 'rejeitada_cobertura_reduzida')
        # A série ativa preserva a cobertura completa original.
        df = rh._ler_serie_persistida()
        self.assertEqual(len(df), len(SERIE_BASE))

    def test_crescimento_legitimo_da_cobertura_e_promovido(self):
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        estendida = SERIE_BASE + [('JFM', 2026, 1.40)]
        r = rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(estendida).encode('utf-8'),
                                    hoje=date(2026, 2, 10))
        self.assertEqual(r['estado_promocao'], 'promovida')
        self.assertEqual(len(rh._ler_serie_persistida()), len(estendida))

    def test_validador_estrutural_nao_fixa_contagem_de_observacoes(self):
        """O validador aceita séries sintéticas de qualquer tamanho —
        não há nenhuma verificação de 'exatamente 921' ou de início em
        1950 dentro de `parse_roni_serie_completa`; essa contagem é só
        uma propriedade EMPÍRICA da fonte real hoje, nunca um requisito
        codificado."""
        pequena, _ = rh.parse_roni_serie_completa(_serie_sintetica([('DJF', 2030, 0.5)]))
        self.assertEqual(len(pequena), 1)
        grande, _ = rh.parse_roni_serie_completa(FIXTURE_TEXTO)
        self.assertEqual(len(grande), 921)  # propriedade observada da fixture real, não exigida pelo código


# ══════════════════════════════════════════════════════
# Fase ENSO-RONI-MIGRAÇÃO 2.2 — Correção 5: imutabilidade do manifesto
# ══════════════════════════════════════════════════════
class ImutabilidadeDoManifestoTestCase(IsolamentoMixin, unittest.TestCase):

    def test_reprocessamento_preserva_integralmente_o_registro_original(self):
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15),
                                aquisicao_id='AQ-ORIGINAL')
        prov_antes, _ = rh.ler_proveniencia_seguro()
        linha_antes = prov_antes[prov_antes['aquisicao_id'] == 'AQ-ORIGINAL'].iloc[0].to_dict()

        # Reprocessa a MESMA aquisição (mesmo id, mesmos fatos) —
        # mesmo chamada bem depois, com `coletado_em_utc` interno
        # recalculado por esta 2ª chamada (datetime.now()) — o
        # registro ORIGINAL deve permanecer intocado.
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15),
                                aquisicao_id='AQ-ORIGINAL')
        prov_depois, _ = rh.ler_proveniencia_seguro()
        linha_depois = prov_depois[prov_depois['aquisicao_id'] == 'AQ-ORIGINAL'].iloc[0].to_dict()

        # dict == trata NaN != NaN (semântica de float) — comparar via
        # repr evita um falso negativo só por isso; o que importa é que
        # TODOS os campos, inclusive coletado_em_utc, sejam idênticos.
        self.assertEqual(repr(linha_antes), repr(linha_depois))
        self.assertEqual(len(prov_depois), 1)  # nunca duplica

    def test_conflito_de_identificador_com_hash_diferente_e_rejeitado(self):
        """Fase 2.2A, Seção 4.2: o conflito precisa ser detectado ANTES
        de qualquer gravação — confirmado aqui comparando o estado
        completo (hash da série, hash do manifesto, último valor
        ativo) antes e depois da tentativa conflituosa, não só o
        `estado_promocao` devolvido."""
        c1 = _serie_sintetica(SERIE_BASE).encode('utf-8')
        c2 = _serie_sintetica(SERIE_BASE[:-1] + [('DJF', 2026, 4.90)]).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=c1, hoje=date(2026, 1, 15), aquisicao_id='AQ-X')

        hash_serie_antes = rh.calcular_hash(rh.HISTORICO_PATH.read_bytes())
        hash_manifesto_antes = rh.calcular_hash(rh.PROVENIENCIA_PATH.read_bytes())
        ultimo_antes = rh.ultimo_da_serie_ativa()

        r2 = rh.processar_aquisicao(conteudo_bytes=c2, hoje=date(2026, 1, 15), aquisicao_id='AQ-X')

        self.assertEqual(r2['estado_promocao'], 'rejeitada_conflito_aquisicao')
        # A aquisição rejeitada nunca devolve o valor do conteúdo
        # conflitante (4.90) — devolve a série ativa, intocada.
        self.assertEqual(r2['ultimo'], ultimo_antes)
        self.assertNotEqual(r2['ultimo']['valor'], 4.90)

        # Nem a série nem o manifesto foram tocados — bytes idênticos,
        # não só "mesmo conteúdo lógico".
        self.assertEqual(rh.calcular_hash(rh.HISTORICO_PATH.read_bytes()), hash_serie_antes)
        self.assertEqual(rh.calcular_hash(rh.PROVENIENCIA_PATH.read_bytes()), hash_manifesto_antes)
        self.assertEqual(rh.ultimo_da_serie_ativa(), ultimo_antes)

        # O registro original de AQ-X nunca foi sobrescrito.
        prov, _ = rh.ler_proveniencia_seguro()
        self.assertEqual(len(prov[prov['aquisicao_id'] == 'AQ-X']), 1)
        self.assertEqual(prov[prov['aquisicao_id'] == 'AQ-X'].iloc[0]['hash_sha256'],
                          rh.calcular_hash(c1))

        # A base permanece íntegra sob a verificação completa — o
        # conflito rejeitado não deixou nenhum rastro de inconsistência.
        ok, avisos = rh.verificar_integridade_roni()
        self.assertTrue(ok, avisos)

    def test_conflito_de_identificador_em_aquisicao_antiga_nao_altera_versao_ativa(self):
        """Fase 2.2A, Seção 4: se o identificador repetido pertence a
        uma aquisição ANTIGA (já superada por uma promoção posterior),
        o conflito ainda deve ser rejeitado antes da promoção — e a
        versão ATIVA (a mais recente) nunca pode ser alterada ou
        revertida por essa tentativa."""
        c1 = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=c1, hoje=date(2026, 1, 15), aquisicao_id='AQ-1')
        revisada = SERIE_BASE[:-1] + [('DJF', 2026, 1.88)]
        c2 = _serie_sintetica(revisada).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=c2, hoje=date(2026, 1, 20), aquisicao_id='AQ-2')
        ultimo_ativo_antes = rh.ultimo_da_serie_ativa()
        self.assertEqual(ultimo_ativo_antes['valor'], 1.88)

        # Reaproveita o id ANTIGO (AQ-1), mas com conteúdo incompatível
        # com o que foi de fato registrado para AQ-1 na época.
        c_conflitante = _serie_sintetica(SERIE_BASE[:-1] + [('DJF', 2026, 9.99)]).encode('utf-8')
        r = rh.processar_aquisicao(conteudo_bytes=c_conflitante, hoje=date(2026, 1, 25),
                                    aquisicao_id='AQ-1')
        self.assertEqual(r['estado_promocao'], 'rejeitada_conflito_aquisicao')
        self.assertEqual(r['ultimo'], ultimo_ativo_antes)  # nunca restaura nem altera a ativa
        self.assertEqual(rh.ultimo_da_serie_ativa(), ultimo_ativo_antes)

    def test_nova_coleta_com_conteudo_identico_gera_novo_registro_distinto(self):
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15), aquisicao_id='AQ-1')
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 16), aquisicao_id='AQ-2')
        prov, _ = rh.ler_proveniencia_seguro()
        self.assertEqual(len(prov), 2)  # duas observações reais e distintas, nunca fundidas

    def test_manifesto_inicial_real_tem_dois_registros_distintos_com_mesmo_hash(self):
        """Reproduz isoladamente o padrão observado no manifesto real
        (Fase 2): 2 linhas com o mesmo hash e aquisicao_id DIFERENTES
        (ids derivados de timestamps ~13s apart). Confirma apenas o
        comportamento do CÓDIGO: os 2 registros são tratados como 2
        observações distintas, nunca fundidos nem tratados como
        conflito (ids diferentes, mesmo hash, não é o caso de
        ConflitoDeAquisicao — esse exige o MESMO id com fatos
        diferentes).

        Limitação documentada (Fase 2.2A, Seção 10): isso, isoladamente,
        NÃO demonstra duas consultas reais e independentes à NOAA — os
        dois registros do manifesto real são preservados exatamente
        como estão, sem inventar essa conclusão. Não há, nos 3
        artefatos reais, evidência adicional (ex.: uma data de
        publicação informada por fonte externa) que resolva essa
        ambiguidade; os timestamps históricos reais nunca são alterados
        para investigar isso."""
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15),
                                aquisicao_id='20261126T194759Z')
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15),
                                aquisicao_id='20261126T195819.363274Z')
        prov, _ = rh.ler_proveniencia_seguro()
        self.assertEqual(len(prov), 2)
        self.assertEqual(prov['hash_sha256'].nunique(), 1)
        self.assertEqual(prov['aquisicao_id'].nunique(), 2)

    def test_manifesto_com_linha_malformada_bloqueia_novas_escritas(self):
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        with rh.PROVENIENCIA_PATH.open('a', encoding='utf-8') as f:
            f.write('linha,com,campos,incompativeis,com,o,cabecalho,' + ','.join(['x'] * 15) + '\n')
        conteudo_novo = _serie_sintetica(SERIE_BASE + [('JFM', 2026, 1.40)]).encode('utf-8')
        r = rh.processar_aquisicao(conteudo_bytes=conteudo_novo, hoje=date(2026, 2, 10))
        self.assertEqual(r['estado_promocao'], 'rejeitada_manifesto_problema')
        # A série ativa NÃO foi alterada por essa tentativa.
        df = rh._ler_serie_persistida()
        self.assertEqual(len(df), len(SERIE_BASE))

    def test_manifesto_com_aquisicao_id_duplicado_e_reprovado_estruturalmente(self):
        """Fase 2.2A, Seção 7/9 (cenário 4): duas linhas com o MESMO
        aquisicao_id no arquivo (produzido fora do pipeline normal, que
        nunca permite isso — id repetido é tratado como no-op/conflito
        ANTES de escrever) não quebra a LEITURA do CSV (estruturalmente
        válido), mas agora é reprovado pela validação estrutural
        mínima — mesmo com os registros sendo IDÊNTICOS (nunca escolhe
        arbitrariamente qual das duas linhas é a 'verdadeira')."""
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15), aquisicao_id='AQ-DUP')
        df = pd.read_csv(rh.PROVENIENCIA_PATH)
        linha_idêntica = df.iloc[0].copy()  # duplicata IDÊNTICA, não só com fatos diferentes
        df2 = pd.concat([df, pd.DataFrame([linha_idêntica])], ignore_index=True)
        df2.to_csv(rh.PROVENIENCIA_PATH, index=False)

        prov, avisos = rh.ler_proveniencia_seguro()
        self.assertEqual(len(prov[prov['aquisicao_id'] == 'AQ-DUP']), 2)
        self.assertTrue(avisos)
        self.assertIn('duplicado', ' '.join(avisos))

        # Nenhuma nova escrita é permitida sobre um manifesto nessa
        # condição — nem uma aquisição nova e sem relação com AQ-DUP.
        r = rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE + [('JFM', 2026, 1.1)])
                                    .encode('utf-8'), hoje=date(2026, 2, 10), aquisicao_id='AQ-NOVA')
        self.assertEqual(r['estado_promocao'], 'rejeitada_manifesto_problema')

        ok, avisos_verif = rh.verificar_integridade_roni()
        self.assertFalse(ok, avisos_verif)

    def test_serie_normalizada_ausente_com_manifesto_integro_e_reconstruivel(self):
        """Cenário B (Seção 8.3): recuperação EXPLÍCITA, nunca
        automática dentro de processar_aquisicao."""
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15))
        conteudo_historico = rh.HISTORICO_PATH.read_bytes()
        rh.HISTORICO_PATH.unlink()  # série normalizada AUSENTE

        ok, avisos = rh.verificar_integridade_roni()
        self.assertFalse(ok)  # ausência com manifesto/snapshot presentes é detectada

        ok_rec, avisos_rec = rh.reconstruir_serie_a_partir_do_manifesto()
        self.assertTrue(ok_rec, avisos_rec)
        self.assertEqual(rh.HISTORICO_PATH.read_bytes(), conteudo_historico)
        ok2, avisos2 = rh.verificar_integridade_roni()
        self.assertTrue(ok2, avisos2)

    def test_serie_normalizada_corrompida_com_snapshot_integro_e_reconstruivel(self):
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15))
        conteudo_historico = rh.HISTORICO_PATH.read_bytes()
        rh.HISTORICO_PATH.write_text(
            PersistenciaERecuperacaoTestCase._CSV_CORROMPIDO, encoding='utf-8')

        ok_rec, avisos_rec = rh.reconstruir_serie_a_partir_do_manifesto()
        self.assertTrue(ok_rec, avisos_rec)
        self.assertEqual(rh.HISTORICO_PATH.read_bytes(), conteudo_historico)

    def test_snapshot_ativo_corrompido_impede_reconstrucao_do_manifesto(self):
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        h = rh.calcular_hash(conteudo)
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15))
        rh.HISTORICO_PATH.unlink()
        rh.caminho_snapshot(h).write_bytes(b'lixo')
        ok_rec, avisos_rec = rh.reconstruir_serie_a_partir_do_manifesto()
        self.assertFalse(ok_rec, avisos_rec)
        self.assertFalse(rh.HISTORICO_PATH.exists())  # nunca inventa/recria sem evidência válida

    def test_recuperacao_sem_perder_aquisicoes_anteriores(self):
        c1 = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=c1, hoje=date(2026, 1, 15), aquisicao_id='AQ-1')
        revisada = SERIE_BASE[:-1] + [('DJF', 2026, 1.88)]
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(revisada).encode('utf-8'),
                                hoje=date(2026, 1, 20), aquisicao_id='AQ-2')
        prov_antes, _ = rh.ler_proveniencia_seguro()
        self.assertEqual(len(prov_antes), 2)

        rh.HISTORICO_PATH.unlink()
        ok_rec, _ = rh.reconstruir_serie_a_partir_do_manifesto()
        self.assertTrue(ok_rec)

        prov_depois, _ = rh.ler_proveniencia_seguro()
        self.assertEqual(len(prov_depois), 2)  # as 2 aquisições anteriores continuam no manifesto
        self.assertEqual(set(prov_antes['aquisicao_id']), set(prov_depois['aquisicao_id']))

    def test_falha_de_recuperacao_impede_publicacao_inconsistente(self):
        # Sem manifesto (Cenário C) a reconstrução falha — e
        # verificar_integridade_roni(), a barreira usada pelos
        # workflows operacionais, continua reprovando: nada que
        # dependa dela publicaria esse estado.
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15))
        rh.PROVENIENCIA_PATH.unlink()
        ok_rec, _ = rh.reconstruir_serie_a_partir_do_manifesto()
        self.assertFalse(ok_rec)
        ok_verif, _ = rh.verificar_integridade_roni()
        self.assertFalse(ok_verif)


# ══════════════════════════════════════════════════════
# Fase ENSO-RONI-MIGRAÇÃO 2.2A — Seção 5: fonte única de
# verdade para a versão ativa (_ultima_promocao_valida)
# ══════════════════════════════════════════════════════
class FonteUnicaDaVersaoAtivaTestCase(IsolamentoMixin, unittest.TestCase):

    def test_duas_promocoes_validas_consecutivas_ultima_e_a_segunda(self):
        c1 = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=c1, hoje=date(2026, 1, 15), aquisicao_id='AQ-1')
        revisada = SERIE_BASE[:-1] + [('DJF', 2026, 1.88)]
        c2 = _serie_sintetica(revisada).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=c2, hoje=date(2026, 1, 20), aquisicao_id='AQ-2')
        prov, _ = rh.ler_proveniencia_seguro()
        ultima = rh._ultima_promocao_valida(prov)
        self.assertEqual(ultima['aquisicao_id'], 'AQ-2')
        self.assertEqual(ultima['hash_sha256'], rh.calcular_hash(c2))

    def test_serie_presa_numa_promocao_antiga_ja_superada_e_reprovada(self):
        """Regressão do bug corrigido na Fase 2.2A (Seção 5): o
        cruzamento antigo aceitava o hash ativo se ele correspondesse a
        QUALQUER promoção do histórico (`.any()`), mesmo uma já
        superada por uma promoção mais recente. Simula exatamente essa
        condição (série ativa presa na 1ª promoção, com a 2ª já
        registrada no manifesto — nunca produzido pelo pipeline normal,
        só por edição externa, como uma interrupção entre a gravação da
        série e do manifesto) e confirma que agora é reprovada."""
        c1 = _serie_sintetica(SERIE_BASE).encode('utf-8')
        hash1 = rh.calcular_hash(c1)
        rh.processar_aquisicao(conteudo_bytes=c1, hoje=date(2026, 1, 15), aquisicao_id='AQ-1')
        conteudo_historico_apos_aq1 = rh.HISTORICO_PATH.read_bytes()

        revisada = SERIE_BASE[:-1] + [('DJF', 2026, 1.88)]
        c2 = _serie_sintetica(revisada).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=c2, hoje=date(2026, 1, 20), aquisicao_id='AQ-2')

        rh.HISTORICO_PATH.write_bytes(conteudo_historico_apos_aq1)
        df_preso = rh._ler_serie_persistida()
        self.assertEqual(df_preso['snapshot_sha256'].iloc[-1], hash1)

        ok, avisos = rh.verificar_integridade_roni()
        self.assertFalse(ok, avisos)  # nunca aceita uma versão superada como ativa válida

    def test_aquisicao_rejeitada_apos_ultima_promocao_nao_e_considerada_ativa(self):
        c1 = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=c1, hoje=date(2026, 1, 15), aquisicao_id='AQ-1')
        # Aquisição estruturalmente inválida — registrada no manifesto
        # como rejeitada, mas NUNCA pode se tornar a referência ativa.
        rh.processar_aquisicao(conteudo_bytes=b'<html>erro</html>', hoje=date(2026, 1, 20),
                                aquisicao_id='AQ-2-REJEITADA')
        prov, _ = rh.ler_proveniencia_seguro()
        ultima = rh._ultima_promocao_valida(prov)
        self.assertEqual(ultima['aquisicao_id'], 'AQ-1')
        self.assertEqual(ultima['hash_sha256'], rh.calcular_hash(c1))
        ok, avisos = rh.verificar_integridade_roni()
        self.assertTrue(ok, avisos)

    def test_tres_pontos_de_uso_concordam_sobre_a_ultima_promocao(self):
        """Seção 5: evita três implementações independentes da mesma
        regra — confirma que verificar_integridade_roni(),
        processar_aquisicao() e reconstruir_serie_a_partir_do_manifesto()
        concordam sobre qual é a última promoção válida."""
        c1 = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=c1, hoje=date(2026, 1, 15), aquisicao_id='AQ-1')
        revisada = SERIE_BASE[:-1] + [('DJF', 2026, 1.88)]
        c2 = _serie_sintetica(revisada).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=c2, hoje=date(2026, 1, 20), aquisicao_id='AQ-2')
        esperado = rh.calcular_hash(c2)

        # 1. verificar_integridade_roni() aceita o estado atual (série
        #    ativa == última promoção válida do manifesto).
        ok, avisos = rh.verificar_integridade_roni()
        self.assertTrue(ok, avisos)

        # 2. processar_aquisicao() usa a mesma referência — reobservar
        #    o conteúdo ativo é tratado como "reaproveitada_sem_
        #    mudanca" (hash bate com o ativo segundo o manifesto).
        r = rh.processar_aquisicao(conteudo_bytes=c2, hoje=date(2026, 1, 21), aquisicao_id='AQ-3')
        self.assertEqual(r['estado_promocao'], 'reaproveitada_sem_mudanca')

        # 3. reconstruir_serie_a_partir_do_manifesto() reconstrói
        #    exatamente o conteúdo referente à mesma última promoção.
        conteudo_antes = rh.HISTORICO_PATH.read_bytes()
        rh.HISTORICO_PATH.unlink()
        ok_rec, avisos_rec = rh.reconstruir_serie_a_partir_do_manifesto()
        self.assertTrue(ok_rec, avisos_rec)
        self.assertEqual(rh.HISTORICO_PATH.read_bytes(), conteudo_antes)
        df_reconstruida = rh._ler_serie_persistida()
        self.assertEqual(df_reconstruida['snapshot_sha256'].iloc[-1], esperado)


# ══════════════════════════════════════════════════════
# Fase ENSO-RONI-MIGRAÇÃO 2.2A — Seção 9: cenários de
# aceitação adicionais, não cobertos pelos grupos anteriores
# ══════════════════════════════════════════════════════
class CenariosDeAceitacaoTestCase(IsolamentoMixin, unittest.TestCase):

    def test_reprocessamento_de_aquisicao_antiga_idempotente_nao_altera_ativa(self):
        """Cenário 3 (Seção 9): reprocessar uma aquisição ANTIGA (já
        superada) com o MESMO conteúdo de então é idempotente — devolve
        o resultado ORIGINAL, mas nunca restaura nem altera a versão
        ATIVA (que é a da promoção mais recente)."""
        c1 = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=c1, hoje=date(2026, 1, 15), aquisicao_id='AQ-1')
        revisada = SERIE_BASE[:-1] + [('DJF', 2026, 1.88)]
        c2 = _serie_sintetica(revisada).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=c2, hoje=date(2026, 1, 20), aquisicao_id='AQ-2')
        ultimo_ativo_antes = rh.ultimo_da_serie_ativa()

        r = rh.processar_aquisicao(conteudo_bytes=c1, hoje=date(2026, 1, 15), aquisicao_id='AQ-1')
        self.assertEqual(r['estado_promocao'], 'promovida')  # resultado ORIGINAL de AQ-1
        self.assertEqual(r['ultimo'], ultimo_ativo_antes)  # mas a ativa é a de AQ-2
        self.assertEqual(rh.ultimo_da_serie_ativa(), ultimo_ativo_antes)

    def test_manifesto_com_esquema_invalido_bloqueia_leitura_confiavel(self):
        """Cenário 5 (Seção 9/7): manifesto sem uma coluna obrigatória
        — estruturalmente lido pelo pandas sem lançar, mas nunca tratado
        como íntegro; bloqueia novas escritas."""
        rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                hoje=date(2026, 1, 15))
        df = pd.read_csv(rh.PROVENIENCIA_PATH)
        df.drop(columns=['estado_promocao']).to_csv(rh.PROVENIENCIA_PATH, index=False)

        prov, avisos = rh.ler_proveniencia_seguro()
        self.assertTrue(avisos)
        self.assertIn('coluna', ' '.join(avisos))

        r = rh.processar_aquisicao(
            conteudo_bytes=_serie_sintetica(SERIE_BASE + [('JFM', 2026, 1.1)]).encode('utf-8'),
            hoje=date(2026, 2, 1))
        self.assertEqual(r['estado_promocao'], 'rejeitada_manifesto_problema')

    def test_processar_aquisicao_recusa_quando_serie_diverge_da_ultima_promocao(self):
        """Cenário 6 (Seção 9): série normalizada estruturalmente
        legível, mas presa numa promoção já superada pelo manifesto —
        `processar_aquisicao()` recusa processar qualquer coisa nova
        sobre essa base, nunca promove por cima dela."""
        c1 = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=c1, hoje=date(2026, 1, 15), aquisicao_id='AQ-1')
        conteudo_historico_apos_aq1 = rh.HISTORICO_PATH.read_bytes()
        revisada = SERIE_BASE[:-1] + [('DJF', 2026, 1.88)]
        c2 = _serie_sintetica(revisada).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=c2, hoje=date(2026, 1, 20), aquisicao_id='AQ-2')

        rh.HISTORICO_PATH.write_bytes(conteudo_historico_apos_aq1)  # presa na promoção antiga

        r = rh.processar_aquisicao(
            conteudo_bytes=_serie_sintetica(SERIE_BASE + [('JFM', 2026, 1.1)]).encode('utf-8'),
            hoje=date(2026, 2, 1), aquisicao_id='AQ-3')
        self.assertEqual(r['estado_promocao'], 'rejeitada_estado_existente_inconsistente')
        self.assertIsNone(r['ultimo'])
        self.assertEqual(rh.HISTORICO_PATH.read_bytes(), conteudo_historico_apos_aq1)

    def test_processar_aquisicao_recusa_quando_serie_ausente_com_manifesto_integro(self):
        """Cenário 7 (Seção 9/6 — Cenário B): série ausente mas o
        manifesto já registra promoção(ões) — nunca tratado como
        primeira aquisição dentro de `processar_aquisicao()`; a
        recuperação é sempre explícita."""
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15), aquisicao_id='AQ-1')
        rh.HISTORICO_PATH.unlink()

        r = rh.processar_aquisicao(conteudo_bytes=_serie_sintetica(SERIE_BASE).encode('utf-8'),
                                    hoje=date(2026, 1, 20), aquisicao_id='AQ-2')
        self.assertEqual(r['estado_promocao'], 'rejeitada_serie_ausente_com_manifesto_integro')
        self.assertFalse(rh.HISTORICO_PATH.exists())  # nunca reinicializa silenciosamente

    def test_falha_de_escrita_do_manifesto_preserva_base_anterior_consistente(self):
        """Cenário 9 (Seção 9): uma falha ao persistir o manifesto
        (ex.: disco) nunca deixa uma promoção 'pela metade' — a base
        permanece exatamente como estava antes da tentativa, e isso
        nunca é confundido com uma inconsistência real (Seção 8: 'uma
        falha de integridade não deve ser confundida com uma falha de
        rede/escrita normal')."""
        c1 = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=c1, hoje=date(2026, 1, 15), aquisicao_id='AQ-1')
        hash_serie_antes = rh.calcular_hash(rh.HISTORICO_PATH.read_bytes())
        hash_manifesto_antes = rh.calcular_hash(rh.PROVENIENCIA_PATH.read_bytes())

        revisada = SERIE_BASE[:-1] + [('DJF', 2026, 1.88)]
        c2 = _serie_sintetica(revisada).encode('utf-8')
        with patch.object(rh, '_registrar_proveniencia', side_effect=OSError('disco cheio simulado')):
            with self.assertRaises(OSError):
                rh.processar_aquisicao(conteudo_bytes=c2, hoje=date(2026, 1, 20), aquisicao_id='AQ-2')

        self.assertEqual(rh.calcular_hash(rh.HISTORICO_PATH.read_bytes()), hash_serie_antes)
        self.assertEqual(rh.calcular_hash(rh.PROVENIENCIA_PATH.read_bytes()), hash_manifesto_antes)
        ok, avisos = rh.verificar_integridade_roni()
        self.assertTrue(ok, avisos)

    def test_falha_na_geracao_da_serie_apos_manifesto_registrado_e_detectavel_e_recuperavel(self):
        """Cenário 10 (Seção 9) — a ordem recomendada pela Seção 8:
        se houver interrupção DEPOIS do manifesto já registrar a
        promoção (passo 4) mas ANTES da série normalizada ser reescrita
        (passo 5), a inconsistência precisa ser detectável (nunca
        silenciosa) e a série precisa ser reconstruível a partir da
        última promoção registrada — nunca uma 'atomicidade conjunta'
        inventada entre os dois arquivos."""
        c1 = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=c1, hoje=date(2026, 1, 15), aquisicao_id='AQ-1')
        conteudo_historico_antes = rh.HISTORICO_PATH.read_bytes()

        revisada = SERIE_BASE[:-1] + [('DJF', 2026, 1.88)]
        c2 = _serie_sintetica(revisada).encode('utf-8')
        with patch.object(rh, '_gravar_serie_historico', side_effect=OSError('falha simulada')):
            with self.assertRaises(OSError):
                rh.processar_aquisicao(conteudo_bytes=c2, hoje=date(2026, 1, 20), aquisicao_id='AQ-2')

        # O manifesto JÁ registra a promoção de AQ-2 — mas a série
        # normalizada continua com o conteúdo de AQ-1 (o passo 5 nunca
        # rodou). Exatamente a inconsistência que o Cenário F detecta.
        self.assertEqual(rh.HISTORICO_PATH.read_bytes(), conteudo_historico_antes)
        prov, _ = rh.ler_proveniencia_seguro()
        linha_aq2 = prov[prov['aquisicao_id'] == 'AQ-2'].iloc[0]
        self.assertEqual(linha_aq2['estado_promocao'], 'promovida')

        ok, avisos = rh.verificar_integridade_roni()
        self.assertFalse(ok, avisos)

        ok_rec, avisos_rec = rh.reconstruir_serie_a_partir_do_manifesto()
        self.assertTrue(ok_rec, avisos_rec)
        df_recuperada = rh._ler_serie_persistida()
        self.assertEqual(df_recuperada['snapshot_sha256'].iloc[-1], rh.calcular_hash(c2))

    def test_inconsistencia_pos_escrita_nunca_entrega_valor_nao_validado(self):
        """Cenário 13 (Seção 9) / passo 6 (Seção 8): mesmo que a
        escrita da série pareça ter concluído, uma verificação final de
        consistência roda antes de devolver sucesso — se ela reprovar,
        o valor nunca é entregue ao chamador (e por extensão, ao card)."""
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        with patch.object(rh, 'serie_ativa_corresponde_ao_snapshot',
                           return_value=(False, ['simulado'])):
            r = rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15))
        self.assertEqual(r['estado_promocao'], 'rejeitada_inconsistencia_pos_escrita')
        self.assertIsNone(r['ultimo'])


if __name__ == '__main__':
    unittest.main()
