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

    def test_a10_duplicata_identica_colapsada(self):
        texto = _serie_sintetica([('DJF', 2025, 0.10)])
        texto += 'DJF  2025   0.10\n'
        lista, avisos = rh.parse_roni_serie_completa(texto)
        self.assertIsNotNone(lista)
        self.assertEqual(len(lista), 1)
        self.assertTrue(any('duplicada' in a for a in avisos))

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

    def test_d3_interrupcao_entre_operacoes_detectada_e_recuperavel(self):
        conteudo = _serie_sintetica(SERIE_BASE).encode('utf-8')
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 15))
        # Simula perda do registro de proveniência (ex.: processo
        # interrompido entre a gravação da série e a do manifesto).
        rh.PROVENIENCIA_PATH.unlink()
        ok, avisos = rh.serie_ativa_corresponde_ao_snapshot()
        self.assertFalse(ok)  # inconsistência DETECTADA
        # Recuperação determinística: reprocessar a mesma aquisição
        # (mesmo conteúdo) restaura a consistência, sem reescrever a
        # série (já idêntica) e sem duplicar snapshot.
        rh.processar_aquisicao(conteudo_bytes=conteudo, hoje=date(2026, 1, 16))
        ok2, avisos2 = rh.serie_ativa_corresponde_ao_snapshot()
        self.assertTrue(ok2, avisos2)

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
        self.assertIn('nenhuma aquisição promovida', ' '.join(msgs))

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


if __name__ == '__main__':
    unittest.main()
