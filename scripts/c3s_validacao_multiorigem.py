#!/usr/bin/env python3
"""
c3s_validacao_multiorigem.py — Fase 2A.2: valida o pipeline C3S/SEAS5
(já confirmado tecnicamente na POC de origem única — PRs #14/#15) em 12
origens históricas controladas, 1 município (São Bento do Tocantins),
leads 1-6.

Pergunta única desta fase: o pipeline real C3S/SEAS5 produz previsões
mensais tecnicamente consistentes e comparáveis ao CHIRPS em diferentes
origens (anos, estações do ano, transições de ano)? NÃO é o hindcast
completo, NÃO seleciona sistema/modelo, NÃO faz bias correction — só
inspeciona o dado bruto real em mais de uma origem (a POC de 2015-01
sozinha não é evidência suficiente disso).

REGIME DE MEMBROS DO SEAS5 (achado real da 1ª execução, run 35225848837)
— a documentação ECMWF/Copernicus confirma dois regimes distintos, não
intercambiáveis:

  - reforecast/hindcast 1981-2016: 25 membros (o que esta fase pede).
  - real-time forecast a partir de 2017: 51 membros.

A 1ª execução real pediu origens de 2015/2018/2021 e viu exatamente
isso: 2015 (dentro do hindcast) voltou com 25 membros e passou; 2018 e
2021 (fora do hindcast) voltaram com 51 membros e foram corretamente
rejeitados pela barreira `N_MEMBROS_ESPERADO = 25` (Seção 9.A) — não é
bug do CDS nem do parser, é a mistura de dois regimes heterogêneos.
Por isso `ORIGENS` só usa anos <= 2016 (`validar_periodo_hindcast`
falha ANTES de qualquer download se isso mudar) e `N_MEMBROS_ESPERADO`
continua 25, nunca 51 nem "25 ou 51".

Os dados de 2018/2021 (51 membros) não são descartados conceitualmente
— são potencialmente úteis como um "archived real-time forecast
confirmation set" prospectivo, mas isso é trabalho de uma FASE FUTURA
SEPARADA, não implementado aqui (ver `NOTA_REAL_TIME_FORECAST_POS_2016`,
sempre incluída no RELATORIO.md gerado).

Este módulo ORQUESTRA várias execuções da lógica já validada em
c3s_poc.py/c3s_download.py/c3s_processar.py/c3s_hindcast.py/
_c3s_utils.py — não reimplementa nada dela (abertura/validação de GRIB,
extração de ponto, tabela, estatísticas de ensemble, busca CHIRPS com a
barreira observacional e o intervalo mensal corrigido continuam vindo de
lá). O que é específico daqui: iterar sobre origens, cache/retry/
checkpoint por origem, as barreiras de fail-fast adicionais da Seção 9
(contagem exata de membros/leads/linhas) e a consolidação dos resultados
em artifacts/c3s_multi/.

CHECKPOINT/RESUME — O QUE É E O QUE NÃO É (achado real da 1ª execução):
`artifacts/c3s_multi/checkpoint.json` protege/reaproveita processamento
já feito DENTRO DO MESMO FILESYSTEM/PROCESSO — por exemplo, se o script
for reexecutado localmente ou numa mesma sessão sem apagar
`artifacts/c3s_multi/`. Um runner NOVO do GitHub Actions sempre começa
com filesystem limpo (o checkout é sempre do zero); publicar o
checkpoint como artifact NÃO faz o próximo `workflow_dispatch` baixá-lo
de volta automaticamente. Ou seja: **não há resume automático entre
execuções independentes do workflow hoje** — isso exigiria um passo
explícito de download do artifact anterior, que esta correção
deliberadamente NÃO implementa (fora de escopo). O checkpoint publicado
serve para auditoria/diagnóstico de qual origem falhou e por quê, não
como mecanismo de retomada entre runs.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import c3s_catalogo as cat  # noqa: E402
import c3s_download as dl  # noqa: E402
import c3s_processar as proc  # noqa: E402
import c3s_hindcast as hc  # noqa: E402
import c3s_poc as poc  # noqa: E402
from _c3s_utils import MUNICIPIOS, leadtime_para_mes_alvo  # noqa: E402

ROOT = Path(__file__).parent.parent
ARTIFACTS_DIR = ROOT / 'artifacts' / 'c3s_multi'
DADOS_ORIGEM_DIR = ARTIFACTS_DIR / '_dados_origem'
CHECKPOINT_PATH = ARTIFACTS_DIR / 'checkpoint.json'

# Seção 2 — só São Bento do Tocantins nesta fase, para separar
# variabilidade temporal (o que testamos aqui) de variabilidade espacial
# (Araguatins/Ananás ficam para uma fase seguinte).
MUNICIPIO = 'Sao_Bento_do_Tocantins'

# Seção 3
LEADS = [1, 2, 3, 4, 5, 6]
N_MEMBROS_ESPERADO = 25
N_LEADS_ESPERADO = len(LEADS)
LINHAS_RAW_ESPERADAS_POR_ORIGEM = N_MEMBROS_ESPERADO * N_LEADS_ESPERADO   # 150
LINHAS_SUMMARY_ESPERADAS_POR_ORIGEM = N_LEADS_ESPERADO                    # 6
UNIDADE_TPRATE_ESPERADA = 'm s**-1'

# Seção 4 — 12 origens controladas: 4 meses por ano (jan=chuvosa,
# abr=fim/transição da chuvosa, jul=seca, out=início/transição para a
# chuvosa) x 3 anos espaçados no tempo, TODOS dentro do período
# homogêneo de hindcast do SEAS5 (1981-2016, 25 membros — ver docstring
# do módulo). 2005/2010/2015 substituem 2018/2021 depois que a 1ª
# execução real (run 35225848837) mostrou 2018/2021 retornando
# number=51 (real-time forecast, regime diferente). 2015-01 continua no
# conjunto só como mais um caso — Seção 5: a fase só é válida se TODAS
# as 12 passarem, não só essa.
ORIGENS = [
    (2005, 1), (2005, 4), (2005, 7), (2005, 10),
    (2010, 1), (2010, 4), (2010, 7), (2010, 10),
    (2015, 1), (2015, 4), (2015, 7), (2015, 10),
]

# Seção 4 da correção — guardrail contra misturar hindcast (25 membros)
# com real-time forecast (51 membros): nenhuma origem desta fase pode
# ser posterior a este ano. Falha ANTES de qualquer download (ver
# validar_periodo_hindcast) — nunca depende só da contagem de membros
# descoberta depois do download para pegar isso.
PERIODO_HINDCAST_SEAS5_ANO_MAX = 2016

# Seção 7 — retry controlado, nunca loop infinito (MAX_TENTATIVAS_CDS
# limita). Esperas progressivas; com 3 tentativas só as 2 primeiras
# esperas (15s, 30s) chegam a ser usadas — a 3ª (60s) fica disponível
# caso MAX_TENTATIVAS_CDS suba no futuro.
MAX_TENTATIVAS_CDS = 3
ESPERAS_RETRY_SEGUNDOS = [15, 30, 60]

# Seção 12 — erro percentual só quando CHIRPS está bem acima de zero,
# para não inflar a métrica em meses secos (denominador pequeno).
CHIRPS_LIMIAR_MM_PARA_ERRO_PCT = 10.0


def _origem_str(ano, mes):
    return f'{ano:04d}-{mes:02d}'


# Seção 7 — nota metodológica fixa, sempre incluída no RELATORIO.md.
# Achado real desta fase (não implementado aqui, só documentado): 2018 e
# 2021 (51 membros, real-time forecast) não são descartados
# conceitualmente, só adiados para uma fase separada futura.
NOTA_REAL_TIME_FORECAST_POS_2016 = (
    "Forecasts pós-2016 do SEAS5 usam 51 membros (regime operacional de real-time forecast, "
    "diferente do hindcast 1981-2016 com 25 membros) e serão avaliados separadamente como "
    "conjunto de confirmação prospectiva/real-time archive. Não implementado nesta fase."
)


def validar_periodo_hindcast(origens):
    """Guardrail (Seção 4 da correção): a Fase 2A.2 exige exclusivamente
    origens do período homogêneo de hindcast do SEAS5 (1981-2016, 25
    membros) — ver docstring do módulo. Chamado ANTES de qualquer
    download (dentro de `rodar()`), para nunca depender só da contagem
    de membros descoberta depois do download."""
    fora = [(a, m) for a, m in origens if a > PERIODO_HINDCAST_SEAS5_ANO_MAX]
    if fora:
        raise ValueError(
            f"Fase 2A.2 exige origens do período homogêneo de hindcast SEAS5 "
            f"(1981–{PERIODO_HINDCAST_SEAS5_ANO_MAX}). Origens fora do período: "
            f"{[_origem_str(a, m) for a, m in fora]} — FALHANDO antes de qualquer download. "
            f"Real-time forecasts pós-{PERIODO_HINDCAST_SEAS5_ANO_MAX} usam 51 membros, um "
            f"regime diferente (não misturar — ver docstring do módulo).")


# ══════════════════════════════════════════════════════════════════════════
# Download com cache determinístico (reaproveita c3s_download.py) + retry
# controlado (Seção 7 — específico desta orquestração multi-origem; a POC
# de origem única não precisava, só baixava 1 vez).
# ══════════════════════════════════════════════════════════════════════════

def _baixar_com_retry_e_cache(request, sleep_fn=time.sleep):
    """Cache hit (arquivo já em data/c3s_cache/, mesmo request -> mesmo
    hash) nunca soma tentativa nem espera — dl.baixar já retorna cedo
    nesse caso. Retry só cobre falha real de rede/CDS."""
    destino = dl.caminho_cache('seasonal-monthly-single-levels', request, extensao='grib')
    cache_hit = destino.exists()
    ultimo_erro = None
    for tentativa in range(1, MAX_TENTATIVAS_CDS + 1):
        try:
            caminho = dl.baixar('seasonal-monthly-single-levels', request, extensao='grib')
            return caminho, cache_hit, tentativa - 1   # retries = tentativas além da primeira
        except Exception as e:
            ultimo_erro = e
            if tentativa < MAX_TENTATIVAS_CDS:
                espera = ESPERAS_RETRY_SEGUNDOS[min(tentativa - 1, len(ESPERAS_RETRY_SEGUNDOS) - 1)]
                print(f"    ⚠ tentativa {tentativa}/{MAX_TENTATIVAS_CDS} falhou ({e}); aguardando {espera}s…")
                sleep_fn(espera)
    raise RuntimeError(f"download CDS falhou após {MAX_TENTATIVAS_CDS} tentativas — último erro: {ultimo_erro}")


# ══════════════════════════════════════════════════════════════════════════
# Processamento de UMA origem — reaproveita poc.abrir_e_validar_grib,
# proc.extrair_ponto, proc.dataset_para_tabela, poc.buscar_chirps_target_
# months (que já tem a barreira observacional e o intervalo mensal
# corrigido) e hc.estatisticas_ensemble. Adiciona só as barreiras de
# fail-fast extras da Seção 9 (contagens exatas) que a POC de origem
# única não precisava (lá as contagens eram sempre as pedidas via CLI).
# ══════════════════════════════════════════════════════════════════════════

def processar_origem(ano, mes, sleep_fn=time.sleep):
    """Processa 1 origem ponta a ponta. Levanta exceção com mensagem
    clara (prefixada com a origem e a letra da barreira da Seção 9) em
    qualquer inconsistência — nunca preenche com zero, nunca troca CHIRPS
    por ERA5, nunca ignora um membro/lead faltando."""
    origem = _origem_str(ano, mes)
    init_date = pd.Period(f'{ano}-{mes:02d}', 'M')
    info = MUNICIPIOS[MUNICIPIO]
    lat, lon = info['lat'], info['lon']
    centro, sistema = cat.SISTEMA_ESCOLHIDO_FASE_2A

    area = [lat + poc.AREA_BUFFER_GRAUS, lon - poc.AREA_BUFFER_GRAUS,
            lat - poc.AREA_BUFFER_GRAUS, lon + poc.AREA_BUFFER_GRAUS]
    # ('ecmwf', '51') = mesmo system code SEAS5 da POC de origem única —
    # nada de request/dataset/variável muda aqui.
    request = dl.montar_request_hindcast(('ecmwf', '51'), ano, mes, area, LEADS)

    caminho, cache_hit, retries = _baixar_com_retry_e_cache(request, sleep_fn=sleep_fn)

    ds, unidade, esquema, mapa_lead_alvo, diag_info, mapeamento_step_fcmonth = \
        poc.abrir_e_validar_grib(caminho, LEADS)

    # A — 25 membros exatos
    n_membros = int(ds.sizes['number'])
    if n_membros != N_MEMBROS_ESPERADO:
        raise RuntimeError(f"[{origem}] número de membros = {n_membros}, esperado "
                            f"{N_MEMBROS_ESPERADO} (Seção 9.A)")

    # B — leads 1..6 exatos (abrir_e_validar_grib já falha se leads no
    # arquivo != LEADS pedidos; redundante aqui de propósito — Seção 9
    # pede a checagem explícita nesta camada também)
    leads_encontrados = sorted(mapa_lead_alvo)
    if leads_encontrados != LEADS:
        raise RuntimeError(f"[{origem}] leads encontrados {leads_encontrados} != esperados "
                            f"{LEADS} (Seção 9.B)")

    # C — 6 verifyingMonth distintos
    alvos = [pd.Period(v, 'M') for v in mapa_lead_alvo.values()]
    if len(set(alvos)) != N_LEADS_ESPERADO:
        raise RuntimeError(f"[{origem}] target months não são {N_LEADS_ESPERADO} distintos: "
                            f"{sorted(alvos)} (Seção 9.C)")

    # D — verifyingMonth coerente com leadtime_para_mes_alvo(init_date, fcmonth)
    # (já validado internamente para o esquema step_valid_time; confirmado
    # aqui de novo, cobrindo também o esquema leadtime_month pronto)
    for lead, alvo_str in mapa_lead_alvo.items():
        esperado = leadtime_para_mes_alvo(init_date, lead)
        if pd.Period(alvo_str, 'M') != esperado:
            raise RuntimeError(f"[{origem}] lead {lead}: target_month {alvo_str} != esperado "
                                f"{esperado} pela convenção lead1=mês de inicialização (Seção 9.D)")

    # E — unidade exatamente a esperada (a POC aceita 3 formas
    # equivalentes; aqui exigimos a forma real observada, para pegar
    # qualquer drift entre origens/execuções)
    if unidade != UNIDADE_TPRATE_ESPERADA:
        raise RuntimeError(f"[{origem}] unidade tprate = {unidade!r}, esperado "
                            f"{UNIDADE_TPRATE_ESPERADA!r} (Seção 9.E)")

    ponto = proc.extrair_ponto(ds, lat, lon)
    lat_grade, lon_grade = float(ponto['latitude']), float(ponto['longitude'])
    dist_km = poc.distancia_km_aprox(lat, lon, lat_grade, lon_grade)

    tabela = proc.dataset_para_tabela(ponto, local=MUNICIPIO, centre=centro, system=sistema,
                                       mapeamento_step_fcmonth=mapeamento_step_fcmonth)
    tabela = tabela.rename(columns={'forecast_prec_mm': 'c3s_prec_mm'})

    # F — nenhuma precipitação negativa/NaN/infinita
    valores = tabela['c3s_prec_mm'].to_numpy(dtype=float)
    if not np.all(np.isfinite(valores)):
        raise RuntimeError(f"[{origem}] c3s_prec_mm contém NaN/infinito (Seção 9.F)")
    if (valores < 0).any():
        raise RuntimeError(f"[{origem}] c3s_prec_mm contém precipitação negativa (Seção 9.F)")

    # G — barreira física ampla já existente na POC (0-1500mm/mês)
    fora = valores[(valores < poc.PREC_MM_MIN_PLAUSIVEL) | (valores > poc.PREC_MM_MAX_PLAUSIVEL)]
    if len(fora):
        raise RuntimeError(f"[{origem}] {len(fora)} valor(es) fora de "
                            f"[{poc.PREC_MM_MIN_PLAUSIVEL},{poc.PREC_MM_MAX_PLAUSIVEL}]mm: "
                            f"{sorted(fora)[:5]} (Seção 9.G)")

    # H — exatamente 150 linhas raw (25 membros x 6 leads)
    if len(tabela) != LINHAS_RAW_ESPERADAS_POR_ORIGEM:
        raise RuntimeError(f"[{origem}] {len(tabela)} linhas raw, esperado "
                            f"{LINHAS_RAW_ESPERADAS_POR_ORIGEM} (Seção 9.H)")

    # CHIRPS — reaproveita poc.buscar_chirps_target_months (já tem a
    # barreira observacional: 1 valor por mês, sem NaN/negativo, e o
    # intervalo mensal corrigido até o último dia real do mês final).
    # Nunca troca por ERA5-Land aqui — se CHIRPS falhar, a exceção sobe
    # e a origem é marcada FALHADA, ponto.
    target_months = sorted(set(pd.Period(t, 'M') for t in tabela['target_month']))
    chirps = poc.buscar_chirps_target_months(MUNICIPIO, target_months)

    # J — exatamente 6 valores CHIRPS válidos
    if len(chirps) != N_LEADS_ESPERADO:
        raise RuntimeError(f"[{origem}] {len(chirps)} valores CHIRPS válidos, esperado "
                            f"{N_LEADS_ESPERADO} (Seção 9.J)")

    tabela['target_month_p'] = tabela['target_month'].apply(lambda s: pd.Period(s, 'M'))
    tabela['chirps_prec_mm'] = tabela['target_month_p'].map(chirps)
    tabela = tabela.drop(columns=['target_month_p'])
    tabela['lat_pedida'] = lat
    tabela['lon_pedida'] = lon
    tabela['lat_grade'] = lat_grade
    tabela['lon_grade'] = lon_grade
    tabela['distancia_grade_km'] = round(dist_km, 2)

    resumo_linhas = []
    for lead, g in tabela.groupby('lead'):
        v = g['c3s_prec_mm'].to_numpy(dtype=float)
        est = hc.estatisticas_ensemble(v)
        chirps_mm = float(g['chirps_prec_mm'].iloc[0])
        erro_media = round(est['mean'] - chirps_mm, 2)
        resumo_linhas.append({
            'init_date': origem, 'target_month': g['target_month'].iloc[0], 'lead': int(lead),
            'ens_mean': round(est['mean'], 2), 'ens_median': round(est['median'], 2),
            'p10': round(est['p10'], 2), 'p25': round(est['p25'], 2),
            'p75': round(est['p75'], 2), 'p90': round(est['p90'], 2),
            'ensemble_min': round(float(v.min()), 2), 'ensemble_max': round(float(v.max()), 2),
            'ensemble_sd': round(float(v.std()), 2),
            'chirps_prec_mm': round(chirps_mm, 2),
            'erro_media_mm': erro_media, 'erro_abs_mm': abs(erro_media),
            'erro_pct': (round(100 * erro_media / chirps_mm, 1)
                         if chirps_mm > CHIRPS_LIMIAR_MM_PARA_ERRO_PCT else None),
        })
    resumo = pd.DataFrame(resumo_linhas).sort_values('lead').reset_index(drop=True)

    # I — exatamente 6 linhas summary
    if len(resumo) != LINHAS_SUMMARY_ESPERADAS_POR_ORIGEM:
        raise RuntimeError(f"[{origem}] {len(resumo)} linhas summary, esperado "
                            f"{LINHAS_SUMMARY_ESPERADAS_POR_ORIGEM} (Seção 9.I)")

    temporal_linhas = []
    for lead in LEADS:
        alvo = pd.Period(mapa_lead_alvo[lead], 'M')
        limite = str((alvo + 1).start_time.date())
        temporal_linhas.append({'init_date': origem, 'lead': lead, 'fcmonth': lead,
                                 'verifying_month': str(alvo), 'valid_time_limite': limite,
                                 'status': 'OK'})
    temporal_df = pd.DataFrame(temporal_linhas)

    metadata_origem = {
        'cache_hit': bool(cache_hit), 'retries': int(retries), 'n_membros': n_membros,
        'lat_grade': lat_grade, 'lon_grade': lon_grade, 'distancia_grade_km': round(dist_km, 2),
        'unidade': unidade, 'esquema_temporal': esquema,
    }
    return tabela, resumo, temporal_df, metadata_origem


# ══════════════════════════════════════════════════════════════════════════
# Checkpoint (Seção 8) — artifact de execução, nunca commitado
# (artifacts/ já está no .gitignore). Registra concluídas/falhadas/
# pendentes; se `rodar()` for chamado de novo NO MESMO FILESYSTEM
# (mesma sessão local, mesmo processo/job) sem apagar
# artifacts/c3s_multi/, origens já concluídas não são reprocessadas.
#
# NÃO é resume automático entre execuções independentes do workflow do
# GitHub Actions — um runner novo sempre começa com filesystem limpo
# (checkout do zero); publicar checkpoint.json como artifact não o
# baixa de volta no próximo workflow_dispatch. Ver docstring do módulo.
# ══════════════════════════════════════════════════════════════════════════

def _checkpoint_vazio():
    return {'concluidas': {}, 'falhadas': {}, 'pendentes': [_origem_str(a, m) for a, m in ORIGENS]}


def carregar_checkpoint():
    if CHECKPOINT_PATH.exists():
        return json.loads(CHECKPOINT_PATH.read_text())
    return _checkpoint_vazio()


def salvar_checkpoint(estado):
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_PATH.write_text(json.dumps(estado, indent=2, ensure_ascii=False))


def _salvar_dados_origem(origem, tabela, resumo, temporal_df):
    DADOS_ORIGEM_DIR.mkdir(parents=True, exist_ok=True)
    tabela.to_json(DADOS_ORIGEM_DIR / f'{origem}_raw.json', orient='records')
    resumo.to_json(DADOS_ORIGEM_DIR / f'{origem}_summary.json', orient='records')
    temporal_df.to_json(DADOS_ORIGEM_DIR / f'{origem}_temporal.json', orient='records')


def _dados_origem_completos(origem):
    return all((DADOS_ORIGEM_DIR / f'{origem}_{sufixo}.json').exists()
               for sufixo in ('raw', 'summary', 'temporal'))


def _carregar_dados_origem(origem):
    raw = pd.read_json(DADOS_ORIGEM_DIR / f'{origem}_raw.json', orient='records')
    summary = pd.read_json(DADOS_ORIGEM_DIR / f'{origem}_summary.json', orient='records')
    temporal = pd.read_json(DADOS_ORIGEM_DIR / f'{origem}_temporal.json', orient='records')
    return raw, summary, temporal


# ══════════════════════════════════════════════════════════════════════════
# Orquestração das 12 origens
# ══════════════════════════════════════════════════════════════════════════

def rodar(origens=None, sleep_fn=time.sleep):
    origens = origens if origens is not None else ORIGENS
    validar_periodo_hindcast(origens)   # Seção 4 — falha antes de qualquer download
    estado = carregar_checkpoint()
    contadores = {'requests_cds': 0, 'cache_hits': 0, 'downloads': 0, 'retries': 0}
    raws, summaries, temporais = [], [], []

    for ano, mes in origens:
        origem = _origem_str(ano, mes)

        if origem in estado['concluidas'] and _dados_origem_completos(origem):
            print(f"[{origem}] já concluída (checkpoint) — reaproveitando, sem novo download")
            raw, summary, temporal = _carregar_dados_origem(origem)
            raws.append(raw); summaries.append(summary); temporais.append(temporal)
            continue

        print(f"\n=== origem {origem} ===")
        try:
            tabela, resumo, temporal_df, meta_origem = processar_origem(ano, mes, sleep_fn=sleep_fn)
        except Exception as e:
            print(f"  ❌ FALHOU: {e}")
            estado['falhadas'][origem] = {'motivo': str(e),
                                           'quando': datetime.now(timezone.utc).isoformat()}
            estado['concluidas'].pop(origem, None)
            if origem in estado['pendentes']:
                estado['pendentes'].remove(origem)
            salvar_checkpoint(estado)
            continue

        contadores['requests_cds'] += 1
        contadores['cache_hits'] += int(meta_origem['cache_hit'])
        contadores['downloads'] += int(not meta_origem['cache_hit'])
        contadores['retries'] += meta_origem['retries']

        _salvar_dados_origem(origem, tabela, resumo, temporal_df)
        estado['concluidas'][origem] = {**meta_origem, 'quando': datetime.now(timezone.utc).isoformat()}
        estado['falhadas'].pop(origem, None)
        if origem in estado['pendentes']:
            estado['pendentes'].remove(origem)
        salvar_checkpoint(estado)

        raws.append(tabela); summaries.append(resumo); temporais.append(temporal_df)
        print(f"  ✅ {origem}: {len(tabela)} linhas raw, {len(resumo)} linhas summary")

    raw_final = pd.concat(raws, ignore_index=True) if raws else pd.DataFrame()
    summary_final = pd.concat(summaries, ignore_index=True) if summaries else pd.DataFrame()
    temporal_final = pd.concat(temporais, ignore_index=True) if temporais else pd.DataFrame()
    return raw_final, summary_final, temporal_final, estado, contadores


def verificar_grid_point_constante(estado):
    """Seção 13 — mesmo município em todas as origens, então o ponto de
    grade deveria ser constante. Se mudar, é ALERTA (não reprova a
    fase — pode indicar mudança de grid/system/request entre requests,
    mas não é um critério de aprovação da Seção 23)."""
    pontos = {(round(v['lat_grade'], 4), round(v['lon_grade'], 4)) for v in estado['concluidas'].values()}
    if len(pontos) > 1:
        msg = f"ALERTA: ponto de grade C3S mudou entre origens concluídas: {sorted(pontos)}"
        print(f"  ⚠ {msg}")
        return [msg]
    return []


# ══════════════════════════════════════════════════════════════════════════
# Metadata (Seção 22) — nunca inclui token/credencial.
# ══════════════════════════════════════════════════════════════════════════

def _versoes_pacotes():
    import importlib.metadata as im
    versoes = {'python': sys.version.split()[0]}
    for pkg in ('cdsapi', 'cfgrib', 'eccodes', 'xarray'):
        try:
            versoes[pkg] = im.version(pkg)
        except im.PackageNotFoundError:
            versoes[pkg] = None
    return versoes


def montar_metadata(estado, contadores, grid_alertas):
    centro, sistema = cat.SISTEMA_ESCOLHIDO_FASE_2A
    origens_str = [_origem_str(a, m) for a, m in ORIGENS]
    status_por_origem = {}
    for o in origens_str:
        if o in estado['concluidas']:
            status_por_origem[o] = {'status': 'CONCLUIDA',
                                     **{k: v for k, v in estado['concluidas'][o].items()}}
        elif o in estado['falhadas']:
            status_por_origem[o] = {'status': 'FALHADA', **estado['falhadas'][o]}
        else:
            status_por_origem[o] = {'status': 'PENDENTE'}

    return {
        'data_execucao': datetime.now(timezone.utc).isoformat(),
        'sistema': {'centro': centro, 'sistema': sistema, 'cds_system_code': '51'},
        'municipio': MUNICIPIO,
        'origens': origens_str,
        'leads': LEADS,
        'n_membros_esperado': N_MEMBROS_ESPERADO,
        'unidade_esperada': UNIDADE_TPRATE_ESPERADA,
        'status_por_origem': status_por_origem,
        'n_origens_concluidas': len(estado['concluidas']),
        'n_origens_falhadas': len(estado['falhadas']),
        'requests_cds': contadores['requests_cds'],
        'cache_hits': contadores['cache_hits'],
        'downloads': contadores['downloads'],
        'retries_totais': contadores['retries'],
        'alertas_grid_point': grid_alertas,
        'versoes_pacotes': _versoes_pacotes(),
    }


# ══════════════════════════════════════════════════════════════════════════
# Relatório markdown (Seção 23)
# ══════════════════════════════════════════════════════════════════════════

def veredito_aprovado(estado, origens=None):
    """Critério mínimo da Seção 23: todas as origens concluídas, zero
    falhadas — nunca reprova por erro meteorológico alto (Section 16).
    Usado tanto no relatório quanto para decidir o exit code de main()
    (Seção 5 da correção)."""
    origens = origens if origens is not None else ORIGENS
    return len(estado['concluidas']) == len(origens) and len(estado['falhadas']) == 0


def gerar_relatorio_markdown(estado, contadores, raw_final, summary_final, grid_alertas, origens=None):
    origens = origens if origens is not None else ORIGENS
    n_ok, n_falhas = len(estado['concluidas']), len(estado['falhadas'])
    aprovado = veredito_aprovado(estado, origens)

    linhas = [
        "# Validação Multi-origem C3S/SEAS5 — Fase 2A.2", "",
        f"- Origens concluídas: {n_ok}/{len(origens)}",
        f"- Origens falhadas: {n_falhas}",
    ]
    if estado['falhadas']:
        linhas += ["", "## Falhas", ""]
        for o, info in estado['falhadas'].items():
            linhas.append(f"- **{o}**: {info['motivo']}")

    linhas += [
        "", f"- Linhas raw totais: {len(raw_final)} "
            f"(esperado {len(origens) * LINHAS_RAW_ESPERADAS_POR_ORIGEM} se {len(origens)}/{len(origens)})",
        f"- Linhas summary totais: {len(summary_final)} "
        f"(esperado {len(origens) * LINHAS_SUMMARY_ESPERADAS_POR_ORIGEM} se {len(origens)}/{len(origens)})",
        f"- Membros esperados por origem: {N_MEMBROS_ESPERADO}",
        f"- Unidade tprate: `{UNIDADE_TPRATE_ESPERADA}`",
        "", "## Nota metodológica", "", NOTA_REAL_TIME_FORECAST_POS_2016,
    ]

    if grid_alertas:
        linhas += ["", "## Alertas de grade", ""] + [f"- ⚠ {a}" for a in grid_alertas]
    elif estado['concluidas']:
        v0 = next(iter(estado['concluidas'].values()))
        linhas += ["", f"- Ponto de grade (constante em todas as origens concluídas): "
                        f"({v0['lat_grade']}, {v0['lon_grade']}), ~{v0['distancia_grade_km']}km do ponto pedido"]

    if not raw_final.empty:
        linhas += ["", "## Faixa de valores", "",
                   f"- C3S (c3s_prec_mm): min={raw_final['c3s_prec_mm'].min():.1f}mm, "
                   f"max={raw_final['c3s_prec_mm'].max():.1f}mm",
                   f"- CHIRPS (chirps_prec_mm): min={raw_final['chirps_prec_mm'].min():.1f}mm, "
                   f"max={raw_final['chirps_prec_mm'].max():.1f}mm"]

    if not summary_final.empty:
        linhas += ["", "## Consistência temporal", "",
                   "- Nenhum erro de metadado temporal (fcmonth/verifyingMonth) nas origens "
                   "concluídas — qualquer origem com erro temporal foi marcada FALHADA, nunca ignorada "
                   "nem corrigida silenciosamente (ver c3s_multi_temporal_check.csv)."]

        linhas += ["", "## DIAGNÓSTICO POC — NÃO É ESTIMATIVA FINAL DE SKILL", "",
                   "Métricas exploratórias descritivas deste conjunto pequeno (12 origens) — "
                   "não uma avaliação de capacidade preditiva definitiva. Não usadas para "
                   "selecionar sistema, calibrar ou otimizar nada.", ""]
        obs_prev = pd.DataFrame({'observado': summary_final['chirps_prec_mm'],
                                  'previsto': summary_final['ens_mean']})
        m_geral = hc.metricas_deterministicas(obs_prev)
        linhas += [f"- Geral: RMSE={m_geral['rmse']}mm, MAE={m_geral['mae']}mm, "
                   f"bias={m_geral['bias']}mm, corr={m_geral['corr']}, n={m_geral['n']}",
                   "", "### Por lead", "",
                   "| lead | RMSE (mm) | MAE (mm) | bias (mm) | corr | n |", "|---|---|---|---|---|---|"]
        for lead, g in summary_final.groupby('lead'):
            gm = hc.metricas_deterministicas(pd.DataFrame({'observado': g['chirps_prec_mm'],
                                                             'previsto': g['ens_mean']}))
            linhas.append(f"| {lead} | {gm['rmse']} | {gm['mae']} | {gm['bias']} | {gm['corr']} | {gm['n']} |")

    linhas += ["", f"- Requests CDS: {contadores['requests_cds']}, cache hits: {contadores['cache_hits']}, "
                   f"downloads: {contadores['downloads']}, retries totais: {contadores['retries']}"]

    linhas += ["", "---", "",
               "**VALIDAÇÃO MULTI-ORIGEM APROVADA**" if aprovado else "**VALIDAÇÃO MULTI-ORIGEM REPROVADA**"]
    return '\n'.join(linhas) + '\n'


def escrever_saidas(raw_final, summary_final, temporal_final, estado, contadores, grid_alertas, origens=None):
    origens = origens if origens is not None else ORIGENS
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    raw_final.to_csv(ARTIFACTS_DIR / 'c3s_multi_raw.csv', index=False)
    summary_final.to_csv(ARTIFACTS_DIR / 'c3s_multi_summary.csv', index=False)
    temporal_final.to_csv(ARTIFACTS_DIR / 'c3s_multi_temporal_check.csv', index=False)

    metadata = montar_metadata(estado, contadores, grid_alertas)
    (ARTIFACTS_DIR / 'c3s_multi_metadata.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False))

    relatorio = gerar_relatorio_markdown(estado, contadores, raw_final, summary_final, grid_alertas, origens=origens)
    (ARTIFACTS_DIR / 'RELATORIO.md').write_text(relatorio)

    print(f"\n✅ artifacts/c3s_multi/c3s_multi_raw.csv ({len(raw_final)} linhas)")
    print(f"✅ artifacts/c3s_multi/c3s_multi_summary.csv ({len(summary_final)} linhas)")
    print(f"✅ artifacts/c3s_multi/c3s_multi_temporal_check.csv ({len(temporal_final)} linhas)")
    print(f"✅ artifacts/c3s_multi/c3s_multi_metadata.json")
    print(f"✅ artifacts/c3s_multi/RELATORIO.md")

    caminho_summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if caminho_summary:
        with open(caminho_summary, 'a') as f:
            f.write(relatorio)
    return metadata, relatorio


def main():
    status = dl.verificar_acesso(verbose=True)
    if not status['credenciais_configuradas']:
        raise SystemExit("CDS_API_KEY não configurado (ver docs/c3s-poc.md) — FALHANDO. "
                          "Nunca simulando resultado real (Seção 27 — sem rede/credencial, só "
                          "preparar e testar offline).")
    if not status['pacote_cdsapi_instalado']:
        raise SystemExit("pacote cdsapi não instalado — rode `pip install -r requirements-c3s.txt`.")

    print(f"=== C3S Validação Multi-origem — {MUNICIPIO} — {len(ORIGENS)} origens — leads {LEADS} ===")
    raw_final, summary_final, temporal_final, estado, contadores = rodar()
    grid_alertas = verificar_grid_point_constante(estado)
    # Seção 5 da correção: artifacts SEMPRE gravados antes de decidir o
    # exit code — um veredito REPROVADO não pode impedir o diagnóstico
    # de chegar aos artifacts do Actions.
    escrever_saidas(raw_final, summary_final, temporal_final, estado, contadores, grid_alertas)

    if not veredito_aprovado(estado, ORIGENS):
        print("\n❌ VALIDAÇÃO MULTI-ORIGEM REPROVADA — artifacts gravados; encerrando com código de "
              "erro (Seção 5 da correção: o workflow não pode terminar 'success' com a fase reprovada).")
        sys.exit(1)
    print("\n✅ VALIDAÇÃO MULTI-ORIGEM APROVADA")


if __name__ == '__main__':
    main()
