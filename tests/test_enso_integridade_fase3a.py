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
        prov.registrar('master_monthly.csv', 2026, 9, 'tsa', 0.57, 'observado',
                        ['2026-09'], 'PSL tsa.data', 'observacao_direta')
        enso = fmd.enso_indices(2026, 9)
        fmd._registrar_proveniencia_serie_subst(2026, 9, enso)
        r = prov.consultar('serie_subst.csv', 2026, 9, 'tsa')
        self.assertEqual(r['classificacao'], 'observado')

    def test_master_sem_proveniencia_propria_vira_desconhecida_na_copia(self):
        """Linha legada do master (sem registro de proveniência) nunca
        é promovida a 'observado' só por estar lá — a cópia para
        serie_subst.csv fica 'desconhecido'."""
        pd.DataFrame([{'year': 2026, 'month': 9, 'nino34': 2.84,
                       'tsa': 0.57, 'pdo': -2.85}]).to_csv(self.merra_path, index=False)
        enso = fmd.enso_indices(2026, 9)
        fmd._registrar_proveniencia_serie_subst(2026, 9, enso)
        r = prov.consultar('serie_subst.csv', 2026, 9, 'tsa')
        self.assertEqual(r['classificacao'], 'desconhecido')

    def test_persistencia_registra_proveniencia_persistido_com_mes_fonte(self):
        pd.DataFrame([{'year': 2026, 'month': 8, 'nino34': 2.52,
                       'tsa': 0.42, 'pdo': -2.85}]).to_csv(self.merra_path, index=False)
        enso = fmd.enso_indices(2026, 9)
        fmd._registrar_proveniencia_serie_subst(2026, 9, enso)
        r = prov.consultar('serie_subst.csv', 2026, 9, 'tsa')
        self.assertEqual(r['classificacao'], 'persistido')
        self.assertEqual(r['meses_base'], ['2026-08'])


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
        'pd': pd, 'np': np, 'prov': prov,
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
        prov.registrar('master_monthly.csv', 2026, 7, 'tsa', 0.12, 'observado',
                        ['2026-07'], 'f', 'observacao_direta')
        self.fn.__globals__['buscar_prec_openmeteo'] = lambda *a, **k: self._om_payload(
            [{'ano': 2026, 'mes': 7, 'prec': 5.0, 'fonte': 'OpenMeteo-ERA5'}])
        resultado = self.fn(serie, self.data_path)
        self.assertEqual(len(resultado), 2)
        linha = resultado[resultado['mes'] == 7].iloc[0]
        self.assertEqual(linha['tsa'], 0.12)
        r = prov.consultar('serie_subst.csv', 2026, 7, 'tsa')
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


if __name__ == '__main__':
    unittest.main()
