#!/usr/bin/env python3
"""
tests/test_enso_integridade_fase3a.py — Fase ENSO-INTEGRIDADE 3A:
proteções contra índices oceânicos ausentes/inválidos
(fetch_monthly_data.py::enso_indices,
update_dashboard.py::incorporar_fallback_openmeteo), proveniência
mínima de TSA/PDO (proveniencia_indices.py) e a ferramenta de
correção controlada (corrigir_indices_historicos.py).

Nenhum teste aqui toca os arquivos reais do repositório (data/) —
todos usam cópias/fixtures sintéticos em diretório temporário, mesmo
padrão de tests/test_fetch_fallback.py. Nenhuma requisição de rede
real: urllib é sempre mockado onde aparece.

Roda com:
    python -m unittest tests.test_enso_integridade_fase3a -v
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import proveniencia_indices as prov       # noqa: E402
import fetch_monthly_data as fmd          # noqa: E402
import corrigir_indices_historicos as cih  # noqa: E402
import verificar_dashboard as vd          # noqa: E402


# ══════════════════════════════════════════════════════════════════
# proveniencia_indices.py
# ══════════════════════════════════════════════════════════════════
class ProveniciaIndicesTestCase(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.caminho = Path(self.tmpdir.name) / 'proveniencia.csv'

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_registrar_e_consultar(self):
        prov.registrar('master_monthly.csv', 2026, 9, 'tsa', 0.57, 'observado',
                        ['2026-09'], 'PSL tsa.data', 'observacao_direta',
                        caminho=self.caminho)
        r = prov.consultar('master_monthly.csv', 2026, 9, 'tsa', caminho=self.caminho)
        self.assertEqual(r['classificacao'], 'observado')
        self.assertEqual(r['valor'], 0.57)
        self.assertEqual(r['meses_base'], ['2026-09'])

    def test_consultar_chave_inexistente_devolve_none_nunca_infere(self):
        r = prov.consultar('master_monthly.csv', 1999, 1, 'pdo', caminho=self.caminho)
        self.assertIsNone(r, "ausência de registro não pode virar 'observado' por default")

    def test_idempotente_segunda_chamada_identica_nao_reescreve_arquivo(self):
        prov.registrar('master_monthly.csv', 2026, 9, 'tsa', 0.57, 'observado',
                        ['2026-09'], 'PSL tsa.data', 'observacao_direta',
                        caminho=self.caminho, verificado_em='2026-11-12T00:00:00Z')
        antes = self.caminho.read_bytes()
        prov.registrar('master_monthly.csv', 2026, 9, 'tsa', 0.57, 'observado',
                        ['2026-09'], 'PSL tsa.data', 'observacao_direta',
                        caminho=self.caminho, verificado_em='2026-11-12T00:00:00Z')
        depois = self.caminho.read_bytes()
        self.assertEqual(antes, depois, "fatos idênticos não devem gerar nenhuma escrita nova")

    def test_upsert_sobrescreve_sem_duplicar_chave_quando_fatos_mudam(self):
        prov.registrar('master_monthly.csv', 2026, 10, 'tsa', 0.12, 'persistido',
                        ['2026-07'], 'f', 'persistencia_ultimo_real', caminho=self.caminho)
        prov.registrar('master_monthly.csv', 2026, 10, 'tsa', 0.57, 'persistido',
                        ['2026-09'], 'f', 'persistencia_ultimo_real', caminho=self.caminho)
        linhas = prov._ler(self.caminho)
        self.assertEqual(len(linhas), 1, "a mesma chave nunca pode gerar 2 linhas")
        r = prov.consultar('master_monthly.csv', 2026, 10, 'tsa', caminho=self.caminho)
        self.assertEqual(r['valor'], 0.57)
        self.assertEqual(r['meses_base'], ['2026-09'])

    def test_pdo_registra_tres_meses_base_nao_um_so(self):
        prov.registrar('master_monthly.csv', 2026, 1, 'pdo', -2.85, 'estimado',
                        ['2025-06', '2025-07', '2025-08'], 'PSL pdo.data',
                        'media_3_meses', caminho=self.caminho)
        r = prov.consultar('master_monthly.csv', 2026, 1, 'pdo', caminho=self.caminho)
        self.assertEqual(r['meses_base'], ['2025-06', '2025-07', '2025-08'])

    def test_classificacao_invalida_rejeitada(self):
        with self.assertRaises(ValueError):
            prov.registrar('master_monthly.csv', 2026, 1, 'pdo', -2.85, 'atualizado',
                            [], 'f', 'm', caminho=self.caminho)

    def test_chaves_distintas_por_arquivo_nao_colidem(self):
        prov.registrar('master_monthly.csv', 2026, 7, 'tsa', 0.12, 'observado',
                        ['2026-07'], 'f', 'm', caminho=self.caminho)
        prov.registrar('serie_subst.csv', 2026, 7, 'tsa', 0.20, 'persistido',
                        ['2026-06'], 'f', 'm', caminho=self.caminho)
        a = prov.consultar('master_monthly.csv', 2026, 7, 'tsa', caminho=self.caminho)
        b = prov.consultar('serie_subst.csv', 2026, 7, 'tsa', caminho=self.caminho)
        self.assertEqual(a['valor'], 0.12)
        self.assertEqual(b['valor'], 0.20)
        self.assertEqual(len(prov._ler(self.caminho)), 2)

    def test_verificar_consistencia_detecta_divergencia(self):
        prov.registrar('master_monthly.csv', 2026, 9, 'tsa', 0.57, 'observado',
                        ['2026-09'], 'f', 'observacao_direta', caminho=self.caminho)
        divergencias = prov.verificar_consistencia(
            'master_monthly.csv',
            [{'ano': 2026, 'mes': 9, 'indice': 'tsa', 'valor': 0.12}],
            caminho=self.caminho)
        self.assertEqual(len(divergencias), 1)
        self.assertEqual(divergencias[0]['valor_csv'], 0.12)
        self.assertEqual(divergencias[0]['valor_proveniencia'], 0.57)

    def test_sem_divergencia_quando_valores_coincidem(self):
        prov.registrar('master_monthly.csv', 2026, 9, 'tsa', 0.57, 'observado',
                        ['2026-09'], 'f', 'observacao_direta', caminho=self.caminho)
        divergencias = prov.verificar_consistencia(
            'master_monthly.csv',
            [{'ano': 2026, 'mes': 9, 'indice': 'tsa', 'valor': 0.57}],
            caminho=self.caminho)
        self.assertEqual(divergencias, [])

    def test_verificar_consistencia_tipo_valor_divergente(self):
        """Fase 3A.3: a divergência agora vem com 'tipo' explícito,
        para o chamador decidir severidade por tipo."""
        prov.registrar('master_monthly.csv', 2026, 9, 'tsa', 0.57, 'observado',
                        ['2026-09'], 'f', 'observacao_direta', caminho=self.caminho)
        divergencias = prov.verificar_consistencia(
            'master_monthly.csv',
            [{'ano': 2026, 'mes': 9, 'indice': 'tsa', 'valor': 0.12}],
            caminho=self.caminho)
        self.assertEqual(len(divergencias), 1)
        self.assertEqual(divergencias[0]['tipo'], 'valor_divergente')

    def test_verificar_consistencia_registro_orfao_detectado(self):
        """Registro de proveniência para uma chave que não aparece em
        `linhas_dado` (ex.: a linha foi removida do CSV, ou nunca
        existiu) é um erro de integridade — a proveniência aponta
        para um dado que não existe."""
        prov.registrar('master_monthly.csv', 2026, 9, 'tsa', 0.57, 'observado',
                        ['2026-09'], 'f', 'observacao_direta', caminho=self.caminho)
        divergencias = prov.verificar_consistencia(
            'master_monthly.csv',
            [{'ano': 2026, 'mes': 10, 'indice': 'tsa', 'valor': 0.12}],  # mês diferente
            caminho=self.caminho)
        tipos = [d['tipo'] for d in divergencias]
        self.assertIn('registro_orfao', tipos)
        orfao = next(d for d in divergencias if d['tipo'] == 'registro_orfao')
        self.assertEqual((orfao['ano'], orfao['mes']), (2026, 9))

    def test_verificar_consistencia_valor_invalido_no_registro(self):
        """Um registro com classificação válida (não 'desconhecido')
        mas valor None/NaN/infinito é um erro — deveria ter um valor
        válido e não tem."""
        prov.registrar('master_monthly.csv', 2026, 9, 'tsa', None, 'observado',
                        ['2026-09'], 'f', 'observacao_direta', caminho=self.caminho)
        divergencias = prov.verificar_consistencia(
            'master_monthly.csv',
            [{'ano': 2026, 'mes': 9, 'indice': 'tsa', 'valor': 0.57}],
            caminho=self.caminho)
        tipos = [d['tipo'] for d in divergencias]
        self.assertIn('valor_invalido_no_registro', tipos)

    def test_verificar_consistencia_chave_duplicada_detectada(self):
        """Duplicação de chave no PRÓPRIO arquivo de proveniência
        (corrupção externa — registrar()/preparar_lote() nunca fazem
        isso por conta própria) é um erro de integridade."""
        linhas = [
            {'arquivo': 'master_monthly.csv', 'ano': 2026, 'mes': 9, 'indice': 'tsa',
             'valor': '0.57', 'classificacao': 'observado', 'meses_base': '2026-09',
             'fonte': 'f', 'metodo': 'observacao_direta', 'verificado_em': 'x'},
            {'arquivo': 'master_monthly.csv', 'ano': 2026, 'mes': 9, 'indice': 'tsa',
             'valor': '0.12', 'classificacao': 'observado', 'meses_base': '2026-09',
             'fonte': 'f', 'metodo': 'observacao_direta', 'verificado_em': 'y'},
        ]
        prov._escrever(linhas, self.caminho)   # grava direto, contornando o upsert por chave
        divergencias = prov.verificar_consistencia(
            'master_monthly.csv',
            [{'ano': 2026, 'mes': 9, 'indice': 'tsa', 'valor': 0.57}],
            caminho=self.caminho)
        tipos = [d['tipo'] for d in divergencias]
        self.assertIn('chave_duplicada', tipos)

    def test_verificar_consistencia_registro_obrigatorio_ausente_so_quando_marcado(self):
        """Ausência pura de registro NUNCA gera divergência por si só
        (histórico legado legítimo) — só quando a chave está
        explicitamente em `indices_obrigatorios` (uma escrita que o
        PRÓPRIO chamador sabe que acabou de fazer)."""
        linha_dado = [{'ano': 2026, 'mes': 9, 'indice': 'tsa', 'valor': 0.57}]

        sem_marcar = prov.verificar_consistencia('master_monthly.csv', linha_dado,
                                                  caminho=self.caminho)
        self.assertEqual(sem_marcar, [], "ausência pura não marcada nunca é divergência")

        marcado = prov.verificar_consistencia(
            'master_monthly.csv', linha_dado, caminho=self.caminho,
            indices_obrigatorios={('master_monthly.csv', 2026, 9, 'tsa')})
        tipos = [d['tipo'] for d in marcado]
        self.assertIn('registro_obrigatorio_ausente', tipos)

    def test_verificar_consistencia_zero_legitimo_nao_e_invalido(self):
        """Um valor 0.0 real e registrado como 'observado' nunca deve
        ser confundido com valor inválido/ausente pelo novo check de
        NaN/infinito — 0.0 é finito e válido."""
        prov.registrar('master_monthly.csv', 2026, 9, 'tsa', 0.0, 'observado',
                        ['2026-09'], 'f', 'observacao_direta', caminho=self.caminho)
        divergencias = prov.verificar_consistencia(
            'master_monthly.csv',
            [{'ano': 2026, 'mes': 9, 'indice': 'tsa', 'valor': 0.0}],
            caminho=self.caminho)
        self.assertEqual(divergencias, [], "zero legítimo não deve gerar nenhuma divergência")

    def test_preparar_lote_mescla_sem_escrever_em_disco(self):
        """preparar_lote() é puro — não deve criar nem alterar o
        arquivo em disco; renderizar_texto() devolve o texto exato que
        seria escrito."""
        entradas = [
            {'arquivo': 'master_monthly.csv', 'ano': 2026, 'mes': 9, 'indice': 'tsa',
             'valor': 0.57, 'classificacao': 'observado', 'meses_base': ['2026-09'],
             'fonte': 'f', 'metodo': 'observacao_direta'},
        ]
        linhas, anteriores = prov.preparar_lote(entradas, caminho=self.caminho)
        self.assertFalse(self.caminho.exists(), "preparar_lote nunca deve escrever em disco")
        self.assertEqual(len(linhas), 1)
        self.assertIsNone(anteriores[('master_monthly.csv', 2026, 9, 'tsa')])
        texto = prov.renderizar_texto(linhas)
        self.assertIn('0.57', texto)

    def test_caminho_padrao_nao_e_capturado_na_definicao_da_funcao(self):
        """Regressão: um default `caminho=CAMINHO_PADRAO` na ASSINATURA
        seria avaliado uma única vez, na definição da função — um
        patch.object(prov, 'CAMINHO_PADRAO', tmp) feito por outro teste
        NUNCA afetaria quem chama registrar()/consultar() sem passar
        caminho= explicitamente. Confirma que a resolução é feita
        DENTRO da função, lendo o atributo do módulo em tempo de
        chamada."""
        tmp = Path(self.tmpdir.name) / 'outro_caminho.csv'
        with patch.object(prov, 'CAMINHO_PADRAO', tmp):
            prov.registrar('master_monthly.csv', 2026, 1, 'nino34', 1.0, 'observado',
                            ['2026-01'], 'f', 'm')  # sem caminho= explícito
        self.assertTrue(tmp.exists(), "deveria ter escrito no CAMINHO_PADRAO patcheado")
        self.assertFalse(self.caminho.exists())


# ══════════════════════════════════════════════════════════════════
# fetch_monthly_data.py::enso_indices — fail-closed
# ══════════════════════════════════════════════════════════════════
class EnsoIndicesFailClosedTestCase(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.merra_path = Path(self.tmpdir.name) / 'master_monthly.csv'
        self._patches = [
            patch.object(fmd, 'MERRA_PATH', self.merra_path),
            patch.object(prov, 'CAMINHO_PADRAO', Path(self.tmpdir.name) / 'prov.csv'),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmpdir.cleanup()

    def test_arquivo_inexistente_levanta_indice_indisponivel(self):
        with self.assertRaises(fmd.IndiceIndisponivel):
            fmd.enso_indices(2026, 9)

    def test_csv_sem_colunas_obrigatorias_levanta_sem_crash(self):
        self.merra_path.write_text("foo,bar\n1,2\n")
        with self.assertRaises(fmd.IndiceIndisponivel):
            fmd.enso_indices(2026, 9)

    def test_valor_nan_na_linha_do_mes_levanta_indice_indisponivel(self):
        pd.DataFrame([{'year': 2026, 'month': 9, 'nino34': 2.84,
                       'tsa': float('nan'), 'pdo': -2.85}]).to_csv(self.merra_path, index=False)
        with self.assertRaises(fmd.IndiceIndisponivel):
            fmd.enso_indices(2026, 9)

    def test_valor_infinito_levanta_indice_indisponivel(self):
        pd.DataFrame([{'year': 2026, 'month': 9, 'nino34': 2.84,
                       'tsa': float('inf'), 'pdo': -2.85}]).to_csv(self.merra_path, index=False)
        with self.assertRaises(fmd.IndiceIndisponivel):
            fmd.enso_indices(2026, 9)

    def test_zero_legitimo_observado_e_preservado_sem_ser_rejeitado(self):
        pd.DataFrame([{'year': 2026, 'month': 9, 'nino34': 0.0,
                       'tsa': 0.0, 'pdo': 0.0}]).to_csv(self.merra_path, index=False)
        r = fmd.enso_indices(2026, 9)
        self.assertEqual(r['nino34'], 0.0)
        self.assertEqual(r['tsa'], 0.0)
        self.assertEqual(r['pdo'], 0.0)
        self.assertEqual(r['origem'], 'master')

    def test_mes_ausente_cai_em_persistencia_sem_levantar(self):
        pd.DataFrame([{'year': 2026, 'month': 8, 'nino34': 2.52,
                       'tsa': 0.42, 'pdo': -2.85}]).to_csv(self.merra_path, index=False)
        r = fmd.enso_indices(2026, 9)
        self.assertEqual(r['origem'], 'persistencia de 08/2026')
        self.assertEqual(r['tsa'], 0.42)

    def test_sem_historico_anterior_levanta_indice_indisponivel(self):
        pd.DataFrame([{'year': 2027, 'month': 1, 'nino34': 1.0,
                       'tsa': 0.1, 'pdo': -1.0}]).to_csv(self.merra_path, index=False)
        with self.assertRaises(fmd.IndiceIndisponivel):
            fmd.enso_indices(2026, 9)

    def test_observacao_real_registra_proveniencia_copiada_para_serie_subst(self):
        pd.DataFrame([{'year': 2026, 'month': 9, 'nino34': 2.84,
                       'tsa': 0.57, 'pdo': -2.85}]).to_csv(self.merra_path, index=False)
        # proveniência do master é lida/escrita no mesmo caminho que
        # _registrar_proveniencia_serie_subst deriva de MERRA_PATH —
        # não no CAMINHO_PADRAO patcheado, que esta função não usa mais.
        caminho_prov = self.merra_path.parent / 'indices_proveniencia.csv'
        prov.registrar('master_monthly.csv', 2026, 9, 'tsa', 0.57, 'observado',
                        ['2026-09'], 'PSL tsa.data', 'observacao_direta',
                        caminho=caminho_prov)
        enso = fmd.enso_indices(2026, 9)
        fmd._registrar_proveniencia_serie_subst(2026, 9, enso)
        r = prov.consultar('serie_subst.csv', 2026, 9, 'tsa', caminho=caminho_prov)
        self.assertEqual(r['classificacao'], 'observado')

    def test_master_sem_proveniencia_propria_vira_desconhecida_na_copia(self):
        """Linha legada do master (sem registro de proveniência) nunca
        é promovida a 'observado' só por estar lá — a cópia para
        serie_subst.csv fica 'desconhecido'."""
        pd.DataFrame([{'year': 2026, 'month': 9, 'nino34': 2.84,
                       'tsa': 0.57, 'pdo': -2.85}]).to_csv(self.merra_path, index=False)
        enso = fmd.enso_indices(2026, 9)
        fmd._registrar_proveniencia_serie_subst(2026, 9, enso)
        caminho_prov = self.merra_path.parent / 'indices_proveniencia.csv'
        r = prov.consultar('serie_subst.csv', 2026, 9, 'tsa', caminho=caminho_prov)
        self.assertEqual(r['classificacao'], 'desconhecido')

    def test_persistencia_de_observacao_real_registra_persistido_com_mes_fonte(self):
        """Fase ENSO-INTEGRIDADE 3A.3: a persistência só é classificada
        'persistido' quando o MÊS-FONTE tem proveniência própria
        'observado' (ou 'persistido', numa cadeia) — testado
        separadamente para nino34, tsa e pdo."""
        pd.DataFrame([{'year': 2026, 'month': 8, 'nino34': 2.52,
                       'tsa': 0.42, 'pdo': -2.85}]).to_csv(self.merra_path, index=False)
        caminho_prov = self.merra_path.parent / 'indices_proveniencia.csv'
        for indice, valor in (('nino34', 2.52), ('tsa', 0.42), ('pdo', -2.85)):
            prov.registrar('master_monthly.csv', 2026, 8, indice, valor, 'observado',
                            ['2026-08'], 'PSL (verificado ao vivo)', 'observacao_direta',
                            caminho=caminho_prov)

        enso = fmd.enso_indices(2026, 9)
        fmd._registrar_proveniencia_serie_subst(2026, 9, enso)

        for indice in ('nino34', 'tsa', 'pdo'):
            r = prov.consultar('serie_subst.csv', 2026, 9, indice, caminho=caminho_prov)
            self.assertEqual(r['classificacao'], 'persistido', f'índice {indice}')
            self.assertEqual(r['meses_base'], ['2026-08'], f'índice {indice}')

    def test_persistencia_sem_proveniencia_propria_do_mes_fonte_vira_desconhecida(self):
        """Regressão do bug corrigido na Fase 3A.3: antes, QUALQUER
        persistência era gravada como 'persistido' incondicionalmente,
        mesmo quando o mês-fonte (aqui, 08/2026) não tem nenhum
        registro de proveniência próprio (dado legado, anterior a
        esta fase) — 'persistido' nesse caso seria uma afirmação
        inventada ('não inventar proveniência de meses históricos sem
        metadados'). Corrigido: fica 'desconhecido'."""
        pd.DataFrame([{'year': 2026, 'month': 8, 'nino34': 2.52,
                       'tsa': 0.42, 'pdo': -2.85}]).to_csv(self.merra_path, index=False)
        enso = fmd.enso_indices(2026, 9)
        fmd._registrar_proveniencia_serie_subst(2026, 9, enso)
        caminho_prov = self.merra_path.parent / 'indices_proveniencia.csv'
        for indice in ('nino34', 'tsa', 'pdo'):
            r = prov.consultar('serie_subst.csv', 2026, 9, indice, caminho=caminho_prov)
            self.assertEqual(r['classificacao'], 'desconhecido', f'índice {indice}')
            self.assertEqual(r['meses_base'], [], f'índice {indice}')

    def test_persistencia_de_estimativa_pdo_preserva_classificacao_estimado(self):
        """O caso central pedido pela revisão: uma estimativa de PDO
        (média de 3 meses) propagada por persistência NUNCA pode virar
        'persistido' (o que implicaria derivar de uma observação
        direta) — tem que continuar 'estimado', com os meses_base
        ORIGINAIS da estimativa, não o mês-fonte isolado."""
        pd.DataFrame([{'year': 2026, 'month': 8, 'nino34': 2.52,
                       'tsa': 0.42, 'pdo': -2.85}]).to_csv(self.merra_path, index=False)
        caminho_prov = self.merra_path.parent / 'indices_proveniencia.csv'
        prov.registrar('master_monthly.csv', 2026, 8, 'pdo', -2.85, 'estimado',
                        ['2026-05', '2026-06', '2026-07'], 'media_3_meses (PSL)',
                        'media_3_meses', caminho=caminho_prov)

        enso = fmd.enso_indices(2026, 9)
        fmd._registrar_proveniencia_serie_subst(2026, 9, enso)

        r = prov.consultar('serie_subst.csv', 2026, 9, 'pdo', caminho=caminho_prov)
        self.assertEqual(r['classificacao'], 'estimado')
        self.assertEqual(r['meses_base'], ['2026-05', '2026-06', '2026-07'])

    def test_persistencia_de_origem_desconhecida_explicita_mantem_desconhecida(self):
        """Mês-fonte com proveniência própria EXPLICITAMENTE
        'desconhecido' (não ausente — já consultado e marcado como tal
        antes) continua 'desconhecido' na persistência, nunca promovido."""
        pd.DataFrame([{'year': 2026, 'month': 8, 'nino34': 2.52,
                       'tsa': 0.42, 'pdo': -2.85}]).to_csv(self.merra_path, index=False)
        caminho_prov = self.merra_path.parent / 'indices_proveniencia.csv'
        prov.registrar('master_monthly.csv', 2026, 8, 'tsa', 0.42, 'desconhecido', [],
                        'origem não comprovada', 'origem_nao_comprovada', caminho=caminho_prov)

        enso = fmd.enso_indices(2026, 9)
        fmd._registrar_proveniencia_serie_subst(2026, 9, enso)

        r = prov.consultar('serie_subst.csv', 2026, 9, 'tsa', caminho=caminho_prov)
        self.assertEqual(r['classificacao'], 'desconhecido')

    def test_persistencia_encadeada_preserva_mes_observado_original(self):
        """08/2026 é, ele mesmo, uma PERSISTÊNCIA de 07/2026 (não uma
        observação direta) — a cadeia não pode inventar uma nova
        'observação' a cada elo: 09/2026 persistindo de 08/2026 deve
        apontar para 07/2026 (a observação real mais distante da
        cadeia), não para 08/2026."""
        pd.DataFrame([{'year': 2026, 'month': 8, 'nino34': 2.52,
                       'tsa': 0.42, 'pdo': -2.85}]).to_csv(self.merra_path, index=False)
        caminho_prov = self.merra_path.parent / 'indices_proveniencia.csv'
        prov.registrar('master_monthly.csv', 2026, 8, 'tsa', 0.42, 'persistido',
                        ['2026-07'], 'master_monthly.csv (persistência)',
                        'persistencia_ultimo_real', caminho=caminho_prov)

        enso = fmd.enso_indices(2026, 9)
        fmd._registrar_proveniencia_serie_subst(2026, 9, enso)

        r = prov.consultar('serie_subst.csv', 2026, 9, 'tsa', caminho=caminho_prov)
        self.assertEqual(r['classificacao'], 'persistido')
        self.assertEqual(r['meses_base'], ['2026-07'])


# ══════════════════════════════════════════════════════════════════
# update_dashboard.py::incorporar_fallback_openmeteo — fail-closed
# ══════════════════════════════════════════════════════════════════
def _import_update_dashboard_fallback():
    """incorporar_fallback_openmeteo vive em update_dashboard.py, que
    executa código de nível de módulo (treina SARIMAX etc.) ao ser
    importado inteiro — por isso extraímos só a função, via exec de
    um sub-trecho isolado, igual ao padrão usado pelos testes mais
    antigos deste projeto para este mesmo arquivo (ver histórico de
    tests/test_update_dashboard_*). Aqui, mais simples: reimplementar
    a assinatura chamando o módulo via import parcial não é viável
    (módulo de script, não de biblioteca) — os testes abaixo chamam a
    função através de um módulo carregado por importlib com
    SKIP_TREINO, se existir, ou testam a lógica via chamada direta
    quando possível."""
    import importlib.util
    caminho = ROOT / 'scripts' / 'update_dashboard.py'
    texto = caminho.read_text(encoding='utf-8')
    # Isola só a função-alvo e seus imports, sem executar o resto do
    # script (treino de modelo, geração de dashboard) — nunca toca
    # docs/index.html nem data/ reais.
    inicio = texto.index('def incorporar_fallback_openmeteo')
    fim = texto.index('\n\n\n# ── Caminhos')
    trecho = texto[inicio:fim]
    namespace = {
        'pd': pd, 'np': np, 'prov': prov, 'Path': Path,
        'buscar_prec_openmeteo': None,  # sobrescrito via patch nos testes
    }
    exec(compile(trecho, str(caminho), 'exec'), namespace)
    return namespace['incorporar_fallback_openmeteo']


class IncorporarFallbackOpenmeteoTestCase(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.data_path = Path(self.tmpdir.name)
        self._patch_prov = patch.object(prov, 'CAMINHO_PADRAO', self.data_path / 'prov.csv')
        self._patch_prov.start()
        self.fn = _import_update_dashboard_fallback()

    def tearDown(self):
        self._patch_prov.stop()
        self.tmpdir.cleanup()

    def _serie_base(self, ultimo_ano=2026, ultimo_mes=6):
        return pd.DataFrame([{'ano': ultimo_ano, 'mes': ultimo_mes, 'prec': 10.0,
                               'nino34': 1.0, 'tsa': 0.1, 'pdo': -1.0,
                               'date': f'{ultimo_ano}-{ultimo_mes:02d}-01', 'fonte': 'CHIRPS'}])

    def _om_payload(self, linhas):
        return pd.DataFrame(linhas, columns=['ano', 'mes', 'prec', 'fonte'])

    def test_mes_sem_correspondencia_no_master_e_descartado_nao_vira_zero(self):
        serie = self._serie_base()
        (self.data_path / 'master_monthly.csv').write_text('year,month,nino34,tsa,pdo\n')
        # a função usa o nome 'buscar_prec_openmeteo' do próprio
        # namespace isolado criado por exec() — basta sobrescrevê-lo
        # nos globals da função extraída, sem tocar em sys.modules.
        self.fn.__globals__['buscar_prec_openmeteo'] = lambda *a, **k: self._om_payload(
            [{'ano': 2026, 'mes': 7, 'prec': 5.0, 'fonte': 'OpenMeteo-ERA5'}])
        resultado = self.fn(serie, self.data_path)
        self.assertEqual(len(resultado), 1, "mês sem índice no master não deve ser adicionado")
        self.assertNotIn(7, resultado['mes'].values)

    def test_mes_com_correspondencia_real_e_adicionado_com_proveniencia(self):
        serie = self._serie_base()
        pd.DataFrame([{'year': 2026, 'month': 7, 'date': '2026-07-01',
                       'nino34': 2.0, 'tsa': 0.12, 'pdo': -2.85}]).to_csv(
            self.data_path / 'master_monthly.csv', index=False)
        # mesmo caminho que incorporar_fallback_openmeteo deriva do seu
        # próprio parâmetro data_path — não o CAMINHO_PADRAO patcheado,
        # que esta função não usa mais (resolução passa a ser explícita).
        caminho_prov = self.data_path / 'indices_proveniencia.csv'
        prov.registrar('master_monthly.csv', 2026, 7, 'tsa', 0.12, 'observado',
                        ['2026-07'], 'f', 'observacao_direta', caminho=caminho_prov)
        self.fn.__globals__['buscar_prec_openmeteo'] = lambda *a, **k: self._om_payload(
            [{'ano': 2026, 'mes': 7, 'prec': 5.0, 'fonte': 'OpenMeteo-ERA5'}])
        resultado = self.fn(serie, self.data_path)
        self.assertEqual(len(resultado), 2)
        linha = resultado[resultado['mes'] == 7].iloc[0]
        self.assertEqual(linha['tsa'], 0.12)
        r = prov.consultar('serie_subst.csv', 2026, 7, 'tsa', caminho=caminho_prov)
        self.assertEqual(r['classificacao'], 'observado')

    def test_valor_nan_no_master_tambem_descarta_o_mes(self):
        serie = self._serie_base()
        pd.DataFrame([{'year': 2026, 'month': 7, 'date': '2026-07-01',
                       'nino34': 2.0, 'tsa': float('nan'), 'pdo': -2.85}]).to_csv(
            self.data_path / 'master_monthly.csv', index=False)
        self.fn.__globals__['buscar_prec_openmeteo'] = lambda *a, **k: self._om_payload(
            [{'ano': 2026, 'mes': 7, 'prec': 5.0, 'fonte': 'OpenMeteo-ERA5'}])
        resultado = self.fn(serie, self.data_path)
        self.assertEqual(len(resultado), 1, "NaN no índice deve descartar o mês, nunca virar 0")

    def test_master_ilegivel_nao_derruba_o_fallback_so_pula_a_rodada(self):
        serie = self._serie_base()
        (self.data_path / 'master_monthly.csv').write_text('isto nao e csv valido\n;;garbage')
        self.fn.__globals__['buscar_prec_openmeteo'] = lambda *a, **k: self._om_payload(
            [{'ano': 2026, 'mes': 7, 'prec': 5.0, 'fonte': 'OpenMeteo-ERA5'}])
        resultado = self.fn(serie, self.data_path)
        self.assertEqual(len(resultado), 1, "master corrompido não deve crashar nem fabricar linha")


# ══════════════════════════════════════════════════════════════════
# corrigir_indices_historicos.py
# ══════════════════════════════════════════════════════════════════
class CorrigirIndicesHistoricosTestCase(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmpdir.name)
        self.master = self.dir / 'master_monthly.csv'
        self.subst = self.dir / 'serie_subst.csv'
        self.provp = self.dir / 'prov.csv'
        pd.DataFrame([
            {'year': 2026, 'month': 7, 'date': '2026-07-01', 'nino34': 2.03, 'oni': None, 'tsa': 0.20, 'pdo': -2.85},
            {'year': 2026, 'month': 8, 'date': '2026-08-01', 'nino34': 2.52, 'oni': None, 'tsa': 0.20, 'pdo': -2.85},
            {'year': 2026, 'month': 9, 'date': '2026-09-01', 'nino34': 2.84, 'oni': None, 'tsa': 0.12, 'pdo': -2.85},
        ]).to_csv(self.master, index=False)
        pd.DataFrame([
            {'ano': 2026, 'mes': 7, 'prec': 12.7, 'nino34': 2.03, 'tsa': 0.20, 'pdo': -2.85, 'date': '2026-07-01', 'fonte': 'CHIRPS'},
            {'ano': 2026, 'mes': 8, 'prec': 7.5, 'nino34': 2.52, 'tsa': 0.20, 'pdo': -2.85, 'date': '2026-08-01', 'fonte': 'CHC-Preliminar'},
        ]).to_csv(self.subst, index=False)
        self.caminhos = {'master_monthly.csv': self.master, 'serie_subst.csv': self.subst,
                          '_proveniencia': self.provp}

    def tearDown(self):
        self.tmpdir.cleanup()

    def _plano_sem_outubro(self):
        return list(cih.PLANO_BASE)

    def test_dry_run_nunca_escreve_nada(self):
        hash_antes_m = cih.sha256_arquivo(self.master)
        hash_antes_s = cih.sha256_arquivo(self.subst)
        relatorio = cih.relatorio_dry_run(self._plano_sem_outubro(), self.caminhos)
        self.assertEqual(cih.sha256_arquivo(self.master), hash_antes_m)
        self.assertEqual(cih.sha256_arquivo(self.subst), hash_antes_s)
        self.assertTrue(all(a['status'] == 'pendente' for a in relatorio))

    def test_aplicar_muda_so_as_celulas_do_plano(self):
        texto_antes_m = self.master.read_text()
        texto_antes_s = self.subst.read_text()
        resultado = cih.aplicar(self._plano_sem_outubro(), self.caminhos)
        self.assertTrue(resultado['aplicado'])

        texto_depois_m = self.master.read_text()
        texto_depois_s = self.subst.read_text()
        dif_m = [i for i, (a, b) in enumerate(zip(texto_antes_m.splitlines(),
                                                    texto_depois_m.splitlines())) if a != b]
        dif_s = [i for i, (a, b) in enumerate(zip(texto_antes_s.splitlines(),
                                                    texto_depois_s.splitlines())) if a != b]
        self.assertEqual(len(dif_m), 3, "3 células no master deveriam mudar — nenhuma outra linha")
        self.assertEqual(len(dif_s), 2, "2 células no serie_subst deveriam mudar — nenhuma outra linha")

        df_m = pd.read_csv(self.master)
        self.assertEqual(float(df_m[df_m.month == 9]['tsa'].iloc[0]), 0.57)
        self.assertEqual(float(df_m[df_m.month == 7]['nino34'].iloc[0]), 2.03, "nino34 nunca deveria mudar")

    def test_idempotente_segunda_aplicacao_e_no_op(self):
        cih.aplicar(self._plano_sem_outubro(), self.caminhos)
        hash_m_1 = cih.sha256_arquivo(self.master)
        resultado2 = cih.aplicar(self._plano_sem_outubro(), self.caminhos)
        self.assertEqual(resultado2['motivo'], 'nada_a_fazer_idempotente')
        self.assertEqual(cih.sha256_arquivo(self.master), hash_m_1, "segunda aplicação não deve escrever nada")

    def test_valor_atual_inesperado_aborta_sem_escrever(self):
        df = pd.read_csv(self.master)
        df.loc[df.month == 9, 'tsa'] = 0.99   # nem o antigo esperado (0.12) nem o novo (0.57)
        df.to_csv(self.master, index=False)
        hash_antes = cih.sha256_arquivo(self.master)
        resultado = cih.aplicar(self._plano_sem_outubro(), self.caminhos)
        self.assertFalse(resultado['aplicado'])
        self.assertEqual(resultado['motivo'], 'celulas_inesperadas')
        self.assertEqual(cih.sha256_arquivo(self.master), hash_antes, "nada deve ser escrito se 1 célula abortar")

    def test_registra_proveniencia_apos_aplicar(self):
        cih.aplicar(self._plano_sem_outubro(), self.caminhos)
        r = prov.consultar('master_monthly.csv', 2026, 9, 'tsa', caminho=self.provp)
        self.assertEqual(r['classificacao'], 'observado')
        self.assertEqual(r['valor'], 0.57)

    def test_rollback_restaura_hash_original(self):
        hash_original = cih.sha256_arquivo(self.master)
        cih.aplicar(self._plano_sem_outubro(), self.caminhos)
        self.assertNotEqual(cih.sha256_arquivo(self.master), hash_original)
        resultado = cih.rollback(self.caminhos)
        self.assertTrue(resultado['master_monthly.csv']['restaurado'])
        self.assertEqual(cih.sha256_arquivo(self.master), hash_original)

    def test_rollback_tambem_restaura_proveniencia_quando_nao_existia_antes(self):
        """Regressão do bug corrigido na 3A.3: rollback() não
        restaurava a proveniência. Aqui ela não existia antes da
        aplicação — depois do rollback, tem que ser REMOVIDA (nunca
        sobrar um arquivo criado pela correção que foi revertida)."""
        self.assertFalse(self.provp.exists())
        cih.aplicar(self._plano_sem_outubro(), self.caminhos)
        self.assertTrue(self.provp.exists())
        resultado = cih.rollback(self.caminhos)
        self.assertTrue(resultado['_proveniencia']['restaurado'])
        self.assertFalse(self.provp.exists(),
                          "proveniência não existia antes — rollback deve removê-la, não deixá-la")

    def test_rollback_restaura_proveniencia_preexistente_ao_conteudo_anterior(self):
        """Quando a proveniência JÁ existia (com outro conteúdo) antes
        da correção, rollback() restaura esse conteúdo anterior —
        nunca remove um arquivo que já existia antes."""
        prov.registrar('master_monthly.csv', 2020, 1, 'tsa', 0.01, 'observado',
                        ['2020-01'], 'f', 'm', caminho=self.provp)
        hash_prov_antes = cih.sha256_arquivo(self.provp)

        cih.aplicar(self._plano_sem_outubro(), self.caminhos)
        self.assertNotEqual(cih.sha256_arquivo(self.provp), hash_prov_antes)

        resultado = cih.rollback(self.caminhos)
        self.assertTrue(resultado['_proveniencia']['restaurado'])
        self.assertEqual(cih.sha256_arquivo(self.provp), hash_prov_antes)
        r = prov.consultar('master_monthly.csv', 2020, 1, 'tsa', caminho=self.provp)
        self.assertEqual(r['classificacao'], 'observado', "registro pré-existente preservado")

    def test_falha_apos_primeiro_csv_deixa_manifesto_e_estado_parcial_verificavel(self):
        """Injeção de falha ENTRE as duas substituições de CSV: master_
        monthly.csv já foi trocado no disco quando serie_subst.csv
        falha. aplicar() não finge sucesso nem silencia — devolve
        estado parcial, com o manifesto registrando exatamente o que
        foi substituído."""
        chamadas = {'n': 0}
        def side_effect(tmp, destino):
            chamadas['n'] += 1
            if chamadas['n'] == 2:   # 1=master_monthly.csv, 2=serie_subst.csv
                raise OSError('falha simulada entre as duas substituições de CSV')
            tmp.replace(destino)

        hash_master_antes = cih.sha256_arquivo(self.master)
        hash_subst_antes = cih.sha256_arquivo(self.subst)
        with patch.object(cih, '_substituir', side_effect=side_effect):
            resultado = cih.aplicar(self._plano_sem_outubro(), self.caminhos)

        self.assertFalse(resultado['aplicado'])
        self.assertIn('escrita_falhou_estado_parcial', resultado['motivo'])
        self.assertNotEqual(cih.sha256_arquivo(self.master), hash_master_antes,
                             "master_monthly.csv JÁ foi substituído quando a falha ocorreu")
        self.assertEqual(cih.sha256_arquivo(self.subst), hash_subst_antes,
                          "serie_subst.csv não deveria ter sido tocado")
        manifesto = cih._ler_manifesto(self.caminhos)
        self.assertIsNotNone(manifesto, "manifesto deve continuar em disco após falha parcial")
        self.assertTrue(manifesto['arquivos']['master_monthly.csv']['substituido'])
        self.assertFalse(manifesto['arquivos']['serie_subst.csv']['substituido'])

    def test_falha_durante_proveniencia_deixa_os_dois_csvs_substituidos_no_manifesto(self):
        """Injeção de falha na substituição da PROVENIÊNCIA — os dois
        CSVs já foram trocados quando ela falha."""
        chamadas = {'n': 0}
        def side_effect(tmp, destino):
            chamadas['n'] += 1
            if chamadas['n'] == 3:   # 1=master, 2=subst, 3=proveniência
                raise OSError('falha simulada na substituição da proveniência')
            tmp.replace(destino)

        with patch.object(cih, '_substituir', side_effect=side_effect):
            resultado = cih.aplicar(self._plano_sem_outubro(), self.caminhos)

        self.assertFalse(resultado['aplicado'])
        manifesto = cih._ler_manifesto(self.caminhos)
        self.assertIsNotNone(manifesto)
        self.assertTrue(manifesto['arquivos']['master_monthly.csv']['substituido'])
        self.assertTrue(manifesto['arquivos']['serie_subst.csv']['substituido'])
        self.assertFalse(manifesto['arquivos']['_proveniencia']['substituido'])
        self.assertFalse(self.provp.exists(),
                          "proveniência não existia antes e a escrita falhou — não deve existir")

    def test_recuperar_falha_restaura_estado_parcial_apos_falha_entre_csvs(self):
        """Demonstração completa de recuperação: depois da falha entre
        os dois CSVs, recuperar_falha() restaura TUDO (os dois CSVs e
        a proveniência, incluindo removê-la se não existia antes) ao
        estado anterior, com hash verificado, e remove o manifesto."""
        hash_master_antes = cih.sha256_arquivo(self.master)
        hash_subst_antes = cih.sha256_arquivo(self.subst)
        chamadas = {'n': 0}
        def side_effect(tmp, destino):
            chamadas['n'] += 1
            if chamadas['n'] == 2:
                raise OSError('falha simulada')
            tmp.replace(destino)
        with patch.object(cih, '_substituir', side_effect=side_effect):
            cih.aplicar(self._plano_sem_outubro(), self.caminhos)

        resultado = cih.recuperar_falha(self.caminhos)
        self.assertTrue(resultado['recuperado'])
        self.assertTrue(resultado['detalhe']['master_monthly.csv']['restaurado'])
        self.assertTrue(resultado['detalhe']['serie_subst.csv']['restaurado'])
        self.assertTrue(resultado['detalhe']['_proveniencia']['restaurado'])
        self.assertEqual(cih.sha256_arquivo(self.master), hash_master_antes)
        self.assertEqual(cih.sha256_arquivo(self.subst), hash_subst_antes)
        self.assertFalse(self.provp.exists(), "proveniência não existia antes da transação")
        self.assertIsNone(cih._ler_manifesto(self.caminhos), "manifesto removido após recuperação completa")

    def test_recuperar_falha_e_idempotente_sem_transacao_pendente(self):
        """Chamar recuperar_falha() sem nenhuma transação incompleta
        pendente é um no-op explícito, nunca um erro nem uma tentativa
        de adivinhar o que restaurar."""
        resultado = cih.recuperar_falha(self.caminhos)
        self.assertFalse(resultado['recuperado'])
        self.assertEqual(resultado['motivo'], 'nenhuma_transacao_incompleta_pendente')

    def test_aplicar_apos_recuperacao_funciona_normalmente(self):
        """Depois de recuperar_falha(), aplicar() não deve mais ver
        nenhum manifesto pendente — a próxima chamada aplica
        normalmente, não fica bloqueada para sempre."""
        chamadas = {'n': 0}
        def side_effect(tmp, destino):
            chamadas['n'] += 1
            if chamadas['n'] == 2:
                raise OSError('falha simulada')
            tmp.replace(destino)
        with patch.object(cih, '_substituir', side_effect=side_effect):
            cih.aplicar(self._plano_sem_outubro(), self.caminhos)
        cih.recuperar_falha(self.caminhos)

        resultado = cih.aplicar(self._plano_sem_outubro(), self.caminhos)
        self.assertTrue(resultado['aplicado'])
        self.assertEqual(resultado['motivo'], 'ok')
        df_m = pd.read_csv(self.master)
        self.assertEqual(float(df_m[df_m.month == 9]['tsa'].iloc[0]), 0.57)

    def test_aplicar_recusa_rodar_sobre_transacao_incompleta_sem_recuperar_antes(self):
        """aplicar() nunca tenta aplicar por cima de um estado não
        resolvido — exige recuperar_falha() primeiro."""
        chamadas = {'n': 0}
        def side_effect(tmp, destino):
            chamadas['n'] += 1
            if chamadas['n'] == 2:
                raise OSError('falha simulada')
            tmp.replace(destino)
        with patch.object(cih, '_substituir', side_effect=side_effect):
            cih.aplicar(self._plano_sem_outubro(), self.caminhos)

        resultado = cih.aplicar(self._plano_sem_outubro(), self.caminhos)
        self.assertFalse(resultado['aplicado'])
        self.assertEqual(resultado['motivo'], 'transacao_anterior_incompleta_detectada')

    # ── Fase ENSO-INTEGRIDADE 3A.5 — escrita atômica do manifesto,
    #    validação explícita e condição de sucesso pós-escrita ────────

    def _escrever_manifesto_bruto(self, texto):
        """Grava texto arbitrário direto no caminho do manifesto ATIVO
        — simula um JSON truncado/corrompido por interrupção real,
        sem passar por _escrever_manifesto() (que é exatamente o que
        estamos testando que NUNCA produz esse estado)."""
        p = cih._manifesto_path(self.caminhos)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(texto, encoding='utf-8')

    def test_manifesto_truncado_e_detectado_e_nao_tratado_como_ausente(self):
        self._escrever_manifesto_bruto('{"status": "aplicando", "arquivos": {"master')  # truncado
        with self.assertRaises(cih.ManifestoInvalido):
            cih._ler_manifesto(self.caminhos)

    def test_manifesto_estruturalmente_invalido_e_detectado(self):
        """JSON válido, mas sem os campos obrigatórios — malformado
        estruturalmente, não só sintaticamente."""
        self._escrever_manifesto_bruto('{"alguma_coisa": 1}')
        with self.assertRaises(cih.ManifestoInvalido):
            cih._ler_manifesto(self.caminhos)

    def test_aplicar_recusa_iniciar_com_manifesto_corrompido(self):
        self._escrever_manifesto_bruto('{"status": "aplicando", "arquivos": {"master')
        hash_master_antes = cih.sha256_arquivo(self.master)
        resultado = cih.aplicar(self._plano_sem_outubro(), self.caminhos)
        self.assertFalse(resultado['aplicado'])
        self.assertEqual(resultado['motivo'], 'manifesto_corrompido')
        self.assertEqual(cih.sha256_arquivo(self.master), hash_master_antes,
                          "nenhuma escrita real deve ocorrer com manifesto corrompido pendente")

    def test_recuperar_falha_recusa_manifesto_corrompido_sem_recuperacao_destrutiva(self):
        self._escrever_manifesto_bruto('not even json')
        resultado = cih.recuperar_falha(self.caminhos)
        self.assertFalse(resultado['recuperado'])
        self.assertEqual(resultado['motivo'], 'manifesto_corrompido')
        # o próprio manifesto corrompido continua lá — nada foi
        # "recuperado às cegas" por cima dele.
        self.assertTrue(cih._manifesto_path(self.caminhos).exists())

    def test_rollback_recusa_manifesto_ativo_corrompido(self):
        self._escrever_manifesto_bruto('{"status":')
        resultado = cih.rollback(self.caminhos)
        self.assertEqual(resultado['_origem'], 'manifesto_corrompido')

    def test_escrever_manifesto_interrompido_nao_deixa_manifesto_truncado(self):
        """Simula interrupção entre a gravação do .tmp e a substituição
        atômica — o manifesto ATIVO (nome canônico) nunca chega a
        existir com conteúdo truncado; _ler_manifesto() continua
        devolvendo None (nenhum manifesto válido anterior), nunca
        ManifestoInvalido."""
        dados = {'status': 'backup_concluido', 'iniciado_em': 'x',
                  'arquivos': {'master_monthly.csv': {'caminho': str(self.master), 'substituido': False}}}
        with patch.object(Path, 'replace', side_effect=OSError('interrompido')):
            with self.assertRaises(OSError):
                cih._escrever_manifesto(self.caminhos, dados)
        self.assertIsNone(cih._ler_manifesto(self.caminhos),
                           "interrupção não deve deixar o manifesto ativo com conteúdo truncado")

    def test_hash_divergente_pos_escrita_reprova_e_mantem_manifesto_ativo(self):
        """Injeção de divergência de HASH depois da substituição real
        (simula corrupção silenciosa de disco/fs) — aplicar() tem que
        reprovar (aplicado=False), nunca arquivar a transação como
        concluída, e manter o manifesto ativo para recuperar_falha()."""
        hash_real = cih.sha256_arquivo
        def hash_fake(caminho):
            h = hash_real(caminho)
            if str(caminho) == str(self.master):
                return 'hash-adulterado-nao-corresponde-ao-arquivo-real'
            return h
        with patch.object(cih, 'sha256_arquivo', side_effect=hash_fake):
            resultado = cih.aplicar(self._plano_sem_outubro(), self.caminhos)

        self.assertFalse(resultado['aplicado'])
        self.assertEqual(resultado['motivo'], 'verificacao_pos_escrita_falhou')
        self.assertIn('master_monthly.csv', resultado['hash_mismatch_pos_escrita'])
        self.assertIsNotNone(cih._ler_manifesto(self.caminhos),
                              "manifesto deve continuar ATIVO (não arquivado) após reprovação")
        # recuperação continua funcionando a partir daqui
        rec = cih.recuperar_falha(self.caminhos)
        self.assertTrue(rec['recuperado'])

    def test_divergencia_de_proveniencia_pos_escrita_reprova_e_mantem_manifesto_ativo(self):
        """Mesma garantia, mas para inconsistência de PROVENIÊNCIA
        (não de hash de arquivo) detectada depois da escrita real."""
        divergencia_falsa = [{'tipo': 'valor_divergente', 'arquivo': 'master_monthly.csv',
                               'ano': 2026, 'mes': 9, 'indice': 'tsa',
                               'valor_csv': 0.57, 'valor_proveniencia': 0.12}]
        with patch.object(prov, 'verificar_consistencia', return_value=divergencia_falsa):
            resultado = cih.aplicar(self._plano_sem_outubro(), self.caminhos)

        self.assertFalse(resultado['aplicado'])
        self.assertEqual(resultado['motivo'], 'verificacao_pos_escrita_falhou')
        self.assertIn(divergencia_falsa[0], resultado['divergencias_pos_escrita'])
        self.assertIsNotNone(cih._ler_manifesto(self.caminhos))
        rec = cih.recuperar_falha(self.caminhos)
        self.assertTrue(rec['recuperado'])

    def test_celula_fora_do_plano_nunca_pode_ser_tocada(self):
        """Não existe parâmetro/flag que aceite uma célula arbitrária —
        só o que está em PLANO_BASE (ou na condicional de outubro) pode
        ser escrito. Confirma por inspeção: aplicar() só aceita um
        `plano`, nunca (arquivo, ano, mes, valor) livres."""
        import inspect
        assinatura = inspect.signature(cih.aplicar)
        self.assertIn('plano', assinatura.parameters)
        self.assertNotIn('coluna', assinatura.parameters)
        self.assertNotIn('valor', assinatura.parameters)

    @patch('urllib.request.urlopen')
    def test_outubro_entra_no_plano_quando_fonte_confirma_ausencia(self, mock_urlopen):
        corpo = (b" 2026   0.30 0.45 0.27 0.38 0.17 0.20 0.12 0.42 0.57 -99.99 -99.99 -99.99\n")
        mock_urlopen.return_value.__enter__.return_value.read.return_value = corpo
        plano, motivo = cih.montar_plano(incluir_outubro=True)
        self.assertEqual(len(plano), len(cih.PLANO_BASE) + 1)
        self.assertIn('confirmado sem observação real', motivo)

    @patch('urllib.request.urlopen')
    def test_outubro_removido_do_plano_quando_fonte_ja_tem_real(self, mock_urlopen):
        corpo = (b" 2026   0.30 0.45 0.27 0.38 0.17 0.20 0.12 0.42 0.57 0.61 -99.99 -99.99\n")
        mock_urlopen.return_value.__enter__.return_value.read.return_value = corpo
        plano, motivo = cih.montar_plano(incluir_outubro=True)
        self.assertEqual(len(plano), len(cih.PLANO_BASE), "outubro não deve entrar — já tem real")
        self.assertIn('revisão manual', motivo)

    @patch('urllib.request.urlopen', side_effect=OSError('rede indisponível'))
    def test_outubro_removido_do_plano_quando_rede_falha(self, mock_urlopen):
        plano, motivo = cih.montar_plano(incluir_outubro=True)
        self.assertEqual(len(plano), len(cih.PLANO_BASE))
        self.assertIn('precaução', motivo)


# ══════════════════════════════════════════════════════════════════
# verificar_dashboard.py::divergencias_proveniencia_serie_subst
# (item 13 — Fase ENSO-INTEGRIDADE 3A.3)
# ══════════════════════════════════════════════════════════════════
class VerificarDashboardProveniciaTestCase(unittest.TestCase):
    """Função pura extraída de main() (sem print/sem `falhas` global) —
    testável diretamente contra fixtures sintéticas de serie_subst.csv
    e proveniência, sem precisar montar um docs/index.html completo."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmpdir.name)
        self.subst = self.dir / 'serie_subst.csv'
        self.provp = self.dir / 'indices_proveniencia.csv'   # nome fixo que a função deriva

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_historico_legado_sem_proveniencia_nao_gera_divergencia(self):
        """Demonstra o requisito central: ausência histórica PURA de
        proveniência (nenhum registro nenhum, situação real hoje no
        repositório) nunca é tratada como inconsistência — nunca
        bloqueio global da atualização."""
        pd.DataFrame([
            {'ano': 2026, 'mes': 7, 'tsa': 0.20, 'pdo': -2.85},
            {'ano': 2026, 'mes': 8, 'tsa': 0.20, 'pdo': -2.85},
        ]).to_csv(self.subst, index=False)
        divergencias = vd.divergencias_proveniencia_serie_subst(self.subst)
        self.assertEqual(divergencias, [])

    def test_detecta_divergencia_de_valor_contra_proveniencia(self):
        """Demonstração direta pedida pela revisão: o verificador
        efetivamente detecta quando o CSV e a proveniência divergem."""
        pd.DataFrame([{'ano': 2026, 'mes': 9, 'tsa': 0.12, 'pdo': -2.85}]).to_csv(
            self.subst, index=False)
        prov.registrar('serie_subst.csv', 2026, 9, 'tsa', 0.57, 'observado',
                        ['2026-09'], 'f', 'm', caminho=self.provp)
        divergencias = vd.divergencias_proveniencia_serie_subst(self.subst)
        tipos = [d['tipo'] for d in divergencias]
        self.assertIn('valor_divergente', tipos)

    def test_detecta_registro_orfao_quando_linha_removida_do_csv(self):
        """Proveniência registrada para um mês que não existe (mais)
        em serie_subst.csv — erro de integridade."""
        pd.DataFrame([{'ano': 2026, 'mes': 9, 'tsa': 0.57, 'pdo': -2.85}]).to_csv(
            self.subst, index=False)
        prov.registrar('serie_subst.csv', 2020, 1, 'tsa', 0.01, 'observado',
                        ['2020-01'], 'f', 'm', caminho=self.provp)
        divergencias = vd.divergencias_proveniencia_serie_subst(self.subst)
        tipos = [d['tipo'] for d in divergencias]
        self.assertIn('registro_orfao', tipos)

    def test_proveniencia_consistente_nao_gera_nenhuma_divergencia(self):
        pd.DataFrame([{'ano': 2026, 'mes': 9, 'tsa': 0.57, 'pdo': -2.85}]).to_csv(
            self.subst, index=False)
        prov.registrar('serie_subst.csv', 2026, 9, 'tsa', 0.57, 'observado',
                        ['2026-09'], 'f', 'm', caminho=self.provp)
        prov.registrar('serie_subst.csv', 2026, 9, 'pdo', -2.85, 'estimado',
                        ['2026-06', '2026-07', '2026-08'], 'f', 'm', caminho=self.provp)
        divergencias = vd.divergencias_proveniencia_serie_subst(self.subst)
        self.assertEqual(divergencias, [])

    def test_item_12_aviso_e_item_13_erro_nao_se_confundem(self):
        """O item 12 (aviso sobre a CLASSIFICAÇÃO do mês mais recente)
        e o item 13 (erro de integridade) não podem convergir no mesmo
        sinal: histórico legado (sem registro algum) é só aviso no
        item 12 e nenhuma divergência no item 13 — os dois tratam a
        MESMA ausência sem contradição."""
        pd.DataFrame([{'ano': 2026, 'mes': 8, 'tsa': 0.20, 'pdo': -2.85}]).to_csv(
            self.subst, index=False)
        reg = prov.consultar('serie_subst.csv', 2026, 8, 'tsa', caminho=self.provp)
        self.assertIsNone(reg, "item 12 trataria isso como aviso 'DESCONHECIDA'")
        divergencias = vd.divergencias_proveniencia_serie_subst(self.subst)
        self.assertEqual(divergencias, [], "item 13 não reprova por essa mesma ausência")


# ══════════════════════════════════════════════════════════════════
# .gitignore — manifestos de corrigir_indices_historicos.py nunca
# commitados; indices_proveniencia.csv (registro definitivo)
# permanece versionável (Fase ENSO-INTEGRIDADE 3A.5)
# ══════════════════════════════════════════════════════════════════
class GitignoreManifestoTestCase(unittest.TestCase):
    """Usa `git check-ignore` de verdade contra o .gitignore real do
    repositório — não uma reimplementação do padrão glob em Python,
    que poderia divergir silenciosamente da regra que o git realmente
    aplica."""

    def test_manifesto_ativo_e_ignorado(self):
        r = subprocess.run(['git', 'check-ignore', 'data/.corrigir_indices_historicos.ativo.json'],
                            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, 'manifesto ativo deveria ser ignorado pelo git')

    def test_manifesto_arquivado_e_ignorado(self):
        r = subprocess.run(
            ['git', 'check-ignore',
             'data/.corrigir_indices_historicos.2026-11-13T12-00-00.concluido.json'],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, 'manifesto arquivado deveria ser ignorado pelo git')

    def test_backup_bak_de_qualquer_arquivo_tocado_e_ignorado(self):
        for nome in ('data/master_monthly.2026-11-13T12-00-00.bak',
                     'data/serie_subst.2026-11-13T12-00-00.bak',
                     'data/indices_proveniencia.2026-11-13T12-00-00.bak'):
            r = subprocess.run(['git', 'check-ignore', nome], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, f'{nome} deveria ser ignorado pelo git')

    def test_indices_proveniencia_csv_definitivo_permanece_versionavel(self):
        """O registro definitivo NUNCA deve bater no padrão de
        manifesto/backup — precisa continuar commitável normalmente."""
        r = subprocess.run(['git', 'check-ignore', 'data/indices_proveniencia.csv'],
                            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1,
                          'data/indices_proveniencia.csv NÃO deveria ser ignorado pelo git')


if __name__ == '__main__':
    unittest.main()
