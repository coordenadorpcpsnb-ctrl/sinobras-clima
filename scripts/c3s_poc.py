#!/usr/bin/env python3
"""
c3s_poc.py — Fase 2A: prova de conceito REAL do C3S/SEAS5, orquestrada
pelo workflow manual `.github/workflows/c3s_poc.yml` (roda no GitHub
Actions, onde o CDS não é bloqueado — diferente desta sessão Claude Code
Web, ver c3s_catalogo.py). NÃO é o hindcast completo — 1 sistema, 1
município, 1 init_date, poucos leads (Seção 6 da tarefa).

Este módulo nunca lê nem imprime o conteúdo de credenciais — só chama
scripts/c3s_download.py::verificar_acesso(), que já tem essa garantia.
`$HOME/.cdsapirc` é escrito pelo PRÓPRIO WORKFLOW (step de shell), não
por este script.

Falha explícita, nunca silenciosa (Seção 14): qualquer dimensão/unidade/
variável fora do esperado no arquivo real levanta exceção — não
converte, não adapta, não preenche com zero.
"""

import argparse
import json
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import c3s_catalogo as cat  # noqa: E402
import c3s_download as dl  # noqa: E402
import c3s_processar as proc  # noqa: E402
import c3s_hindcast as hc  # noqa: E402
from _c3s_utils import MUNICIPIOS, leadtime_para_mes_alvo, tprate_para_mm  # noqa: E402
from _chirps import _geometria_ponto, _buscar_prec_chirps_geom  # noqa: E402

ROOT = Path(__file__).parent.parent
ARTIFACTS_DIR = ROOT / 'artifacts'

# Unidade esperada da variável tprate no C3S (Seção 8: nunca assumir sem
# ler o metadata real — este é o valor que o metadata PRECISA ter para
# prosseguirmos; qualquer outro valor é falha explícita, não adaptação
# silenciosa). Formas equivalentes conhecidas do GRIB/cfgrib.
UNIDADES_TPRATE_ACEITAS = {'m s**-1', 'm s-1', 'm/s'}

# Plausibilidade física (Seção 8): CHIRPS real da região (2015-2024,
# scripts/c3s_observado_chirps.py, já rodado nesta sessão) tem máximo de
# ~546mm/mês num ponto. SEAS5 é média de grade 1° (mais suave que um
# ponto) — 1500mm/mês é quase 3x esse máximo observado: generoso o
# bastante para não descartar um outlier legítimo, baixo o bastante para
# pegar um erro grosseiro de unidade (esquecer de multiplicar pelos
# segundos-no-mês dá valores ~1e5x menores; multiplicar 2x dá valores
# absurdamente maiores).
PREC_MM_MIN_PLAUSIVEL = 0.0
PREC_MM_MAX_PLAUSIVEL = 1500.0

# Área ao redor do ponto do município (Seção 6/9): grade C3S é 1°x1° —
# ±1° garante pegar a célula que contém o ponto mais uma margem de
# vizinhas, sem baixar nada perto de global.
AREA_BUFFER_GRAUS = 1.0

CACHE_CHIRPS_POC = ROOT / 'data' / 'c3s_observado_chirps_poc.csv'


def normalizar_municipio(valor):
    """Aceita tanto a chave interna (Sao_Bento_do_Tocantins) quanto o
    nome de exibição com acentos/espaços (São Bento do Tocantins)."""
    if valor in MUNICIPIOS:
        return valor
    sem_acento = unicodedata.normalize('NFKD', valor).encode('ascii', 'ignore').decode('ascii')
    chave = sem_acento.strip().replace(' ', '_')
    if chave in MUNICIPIOS:
        return chave
    for k, info in MUNICIPIOS.items():
        alvo = unicodedata.normalize('NFKD', info['nome_exibicao']).encode('ascii', 'ignore').decode('ascii')
        if alvo.replace(' ', '_').lower() == chave.lower():
            return k
    raise ValueError(f"município desconhecido: {valor!r} — válidos: {list(MUNICIPIOS)} "
                      f"ou os nomes de exibição correspondentes")


def parsear_leads(valor):
    """'1,2,3' -> [1,2,3]. Falha explícita em formato inválido, sem
    tentar adivinhar (Seção 13, item 3)."""
    leads = []
    for parte in str(valor).split(','):
        parte = parte.strip()
        if not parte:
            continue
        n = int(parte)   # ValueError explícito se não for inteiro
        if n < 1:
            raise ValueError(f"leadtime_month deve ser >= 1, recebido {n}")
        leads.append(n)
    if not leads:
        raise ValueError(f"nenhum lead válido em {valor!r}")
    return leads


def distancia_km_aprox(lat1, lon1, lat2, lon2):
    """Haversine — suficiente para reportar 'quão longe o grid point
    ficou do ponto pedido', não usado para nenhuma decisão de leakage."""
    R = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlmb = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return float(2 * R * np.arcsin(np.sqrt(a)))


def abrir_e_validar_grib(caminho, leads_esperados):
    """Abre com xarray/cfgrib e valida a estrutura ANTES de extrair
    qualquer valor. Falha explícita (Seção 7/14) se algo não bater —
    nunca adapta silenciosamente."""
    import xarray as xr
    # engine por extensão: cfgrib para GRIB real (download do CDS),
    # padrão do xarray para .nc — usado só nos testes offline, que
    # escrevem NetCDF sintético em vez de GRIB (cfgrib é leitura-only,
    # não tem caminho simples de escrita a partir de um Dataset em
    # memória para construir um arquivo de teste).
    engine = 'cfgrib' if Path(caminho).suffix.lower().startswith('.grib') else None
    ds = xr.open_dataset(caminho, engine=engine)

    if 'tprate' not in ds.data_vars:
        raise RuntimeError(f"variável 'tprate' ausente no arquivo real — variáveis presentes: "
                            f"{list(ds.data_vars)}. FALHANDO (Seção 14) em vez de adivinhar qual é a variável.")

    unidade = ds['tprate'].attrs.get('units')
    if unidade not in UNIDADES_TPRATE_ACEITAS:
        raise RuntimeError(f"unidade inesperada para tprate: {unidade!r} (esperado uma de "
                            f"{UNIDADES_TPRATE_ACEITAS}) — FALHANDO em vez de assumir a conversão.")

    nome_lead = proc._nome_coord_lead(ds)   # já lança KeyError claro se ausente
    leads_no_arquivo = sorted(int(v) for v in np.atleast_1d(ds[nome_lead].values))
    if leads_no_arquivo != sorted(leads_esperados):
        raise RuntimeError(f"leads no arquivo real ({leads_no_arquivo}) != leads pedidos "
                            f"({sorted(leads_esperados)}) — FALHANDO em vez de usar o que veio.")

    if 'number' not in ds['tprate'].dims:
        raise RuntimeError("dimensão de membro do ensemble ('number') ausente no arquivo real de "
                            "hindcast — FALHANDO (Seção 14: 'ensemble dimension ausente').")

    for dim in ('latitude', 'longitude'):
        if dim not in ds.coords:
            raise RuntimeError(f"coordenada '{dim}' ausente no arquivo real — FALHANDO.")

    print(f"  validado: variável=tprate unidade={unidade!r} leads={leads_no_arquivo} "
          f"membros={ds.sizes['number']} lat={ds.sizes['latitude']} lon={ds.sizes['longitude']}")
    return ds, unidade


def buscar_chirps_target_months(municipio_chave, target_months):
    """Reaproveita o CSV já gerado (Seção 10: 'se CHIRPS real já estiver
    disponível pelo código atual, reutilizar'); se não cobrir os meses
    pedidos, busca ao vivo pelo mesmo núcleo de _chirps.py."""
    if CACHE_CHIRPS_POC.exists():
        cache = pd.read_csv(CACHE_CHIRPS_POC)
        cache['ym'] = pd.PeriodIndex(pd.to_datetime(dict(year=cache.ano, month=cache.mes, day=1)), freq='M')
        sub = cache[cache['local'] == municipio_chave]
        faltando = [m for m in target_months if m not in set(sub['ym'])]
        if not faltando:
            r = sub[sub['ym'].isin(target_months)][['ym', 'prec']].set_index('ym')['prec']
            return {m: float(r[m]) for m in target_months}

    info = MUNICIPIOS[municipio_chave]
    geom = _geometria_ponto(info['lat'], info['lon'])
    ano_ini, mes_ini = min(target_months).year, min(target_months).month
    ano_fim, mes_fim = max(target_months).year, max(target_months).month
    ini, fim = f'{mes_ini:02d}/01/{ano_ini}', f'{mes_fim:02d}/01/{ano_fim}'
    df = _buscar_prec_chirps_geom(ini, fim, geom, rotulo=municipio_chave)
    if df.empty:
        raise RuntimeError("CHIRPS indisponível para os target months desta POC — FALHANDO "
                            "(Seção 14: nunca converter indisponibilidade em zero).")
    df['ym'] = pd.PeriodIndex(pd.to_datetime(dict(year=df.ano, month=df.mes, day=1)), freq='M')
    r = df.set_index('ym')['prec']
    faltando = [m for m in target_months if m not in r.index]
    if faltando:
        raise RuntimeError(f"CHIRPS não cobre os target months {faltando} — FALHANDO.")
    return {m: float(r[m]) for m in target_months}


def rodar(municipio_arg, init_year, init_month, leads, forcar_download=False):
    municipio_chave = normalizar_municipio(municipio_arg)
    info = MUNICIPIOS[municipio_chave]
    lat, lon = info['lat'], info['lon']
    init_date = pd.Period(f'{init_year}-{init_month:02d}', 'M')
    centro, sistema = cat.SISTEMA_ESCOLHIDO_FASE_2A

    print(f"=== C3S POC — {sistema}/{centro} — {info['nome_exibicao']} — init={init_date} — leads={leads} ===")

    status = dl.verificar_acesso(verbose=True)
    if not status['credenciais_configuradas']:
        raise SystemExit("CDS_API_KEY não configurado (ver docs/c3s-poc.md) — FALHANDO. "
                          "Nunca simulando um resultado no lugar do download real.")
    if not status['pacote_cdsapi_instalado']:
        raise SystemExit("pacote cdsapi não instalado — rode `pip install -r requirements-c3s.txt`.")

    area = [lat + AREA_BUFFER_GRAUS, lon - AREA_BUFFER_GRAUS,
            lat - AREA_BUFFER_GRAUS, lon + AREA_BUFFER_GRAUS]   # N, W, S, E
    # ('ecmwf', '51') = originating_centre/system exigidos pela API do CDS —
    # código '51' = SEAS5, ver c3s_catalogo.py::SISTEMA_ESCOLHIDO_FASE_2A
    request = dl.montar_request_hindcast(('ecmwf', '51'), init_year, init_month, area, leads)

    caminho = dl.baixar('seasonal-monthly-single-levels', request, extensao='grib', forcar=forcar_download)
    print(f"  arquivo: {caminho}")

    ds, unidade = abrir_e_validar_grib(caminho, leads)

    ponto = proc.extrair_ponto(ds, lat, lon)
    lat_grade = float(ponto['latitude'])
    lon_grade = float(ponto['longitude'])
    dist_km = distancia_km_aprox(lat, lon, lat_grade, lon_grade)
    print(f"  ponto pedido=({lat},{lon})  ponto de grade=({lat_grade},{lon_grade})  dist~{dist_km:.1f}km")

    tabela = proc.dataset_para_tabela(ponto, local=municipio_chave, centre=centro, system=sistema)
    tabela['init_date'] = str(init_date)

    for v in tabela['forecast_prec_mm']:
        if not (PREC_MM_MIN_PLAUSIVEL <= v <= PREC_MM_MAX_PLAUSIVEL):
            raise RuntimeError(f"precipitação implausível: {v}mm (limites [{PREC_MM_MIN_PLAUSIVEL}, "
                               f"{PREC_MM_MAX_PLAUSIVEL}]) — FALHANDO em vez de aceitar silenciosamente "
                               f"(Seção 8: barreira de plausibilidade).")

    target_months = sorted(set(pd.Period(t, 'M') for t in tabela['target_month']))
    chirps = buscar_chirps_target_months(municipio_chave, target_months)
    tabela['target_month_p'] = tabela['target_month'].apply(lambda s: pd.Period(s, 'M'))
    tabela['chirps_prec_mm'] = tabela['target_month_p'].map(chirps)
    tabela = tabela.drop(columns=['target_month_p'])
    tabela = tabela.rename(columns={'forecast_prec_mm': 'c3s_prec_mm'})

    resumo_linhas = []
    for lead, g in tabela.groupby('lead'):
        est = hc.estatisticas_ensemble(g['c3s_prec_mm'].values)
        resumo_linhas.append({
            'lead': int(lead), 'target_month': g['target_month'].iloc[0],
            'ens_mean': round(est['mean'], 2), 'ens_median': round(est['median'], 2),
            'p10': round(est['p10'], 2), 'p25': round(est['p25'], 2),
            'p75': round(est['p75'], 2), 'p90': round(est['p90'], 2),
            'chirps_prec_mm': round(float(g['chirps_prec_mm'].iloc[0]), 2),
        })
    resumo = pd.DataFrame(resumo_linhas).sort_values('lead')

    metadata = {
        'data_execucao': pd.Timestamp.now().isoformat(),
        'sistema': {'centro': centro, 'sistema': sistema, 'cds_system_code': '51'},
        'init_date': str(init_date), 'leads': leads,
        'municipio': {'chave': municipio_chave, 'nome_exibicao': info['nome_exibicao'],
                      'lat_pedida': lat, 'lon_pedida': lon,
                      'lat_grade': lat_grade, 'lon_grade': lon_grade, 'distancia_km': round(dist_km, 2)},
        'unidade_tprate_detectada': unidade,
        'n_membros': int(ds.sizes['number']),
        'limites_plausibilidade_mm': [PREC_MM_MIN_PLAUSIVEL, PREC_MM_MAX_PLAUSIVEL],
        'request_cds': request,
    }

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    tabela.to_csv(ARTIFACTS_DIR / 'c3s_poc_raw.csv', index=False)
    resumo.to_csv(ARTIFACTS_DIR / 'c3s_poc_summary.csv', index=False)
    (ARTIFACTS_DIR / 'c3s_poc_metadata.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False))
    print(f"  ✅ artifacts/c3s_poc_raw.csv ({len(tabela)} linhas)")
    print(f"  ✅ artifacts/c3s_poc_summary.csv ({len(resumo)} linhas)")
    print(f"  ✅ artifacts/c3s_poc_metadata.json")

    escrever_resumo_actions(metadata, resumo)
    return metadata, tabela, resumo


def escrever_resumo_actions(metadata, resumo_df):
    """Seção 12 — GitHub Actions Summary. Escreve em $GITHUB_STEP_SUMMARY
    se a env var existir (dentro do Actions); senão, imprime no stdout
    (rodando localmente/testando)."""
    import os
    linhas = [
        "## C3S POC — resultado", "",
        f"- **Status CDS**: credenciais OK, download concluído",
        f"- **Sistema**: {metadata['sistema']['centro']}/{metadata['sistema']['sistema']} "
        f"(código `{metadata['sistema']['cds_system_code']}`)",
        f"- **Init date**: {metadata['init_date']}",
        f"- **Município**: {metadata['municipio']['nome_exibicao']} "
        f"(pedido: {metadata['municipio']['lat_pedida']},{metadata['municipio']['lon_pedida']})",
        f"- **Ponto de grade selecionado**: {metadata['municipio']['lat_grade']},"
        f"{metadata['municipio']['lon_grade']} (~{metadata['municipio']['distancia_km']}km do ponto pedido)",
        f"- **Nº de membros**: {metadata['n_membros']}",
        f"- **Leads**: {metadata['leads']}",
        f"- **Unidade tprate detectada**: `{metadata['unidade_tprate_detectada']}`",
        "", "### Previsão C3S (ensemble mean) vs CHIRPS observado, por lead", "",
        "| lead | target_month | ens_mean (mm) | chirps (mm) | diferença (mm) |",
        "|---|---|---|---|---|",
    ]
    for _, r in resumo_df.iterrows():
        diff = round(r['ens_mean'] - r['chirps_prec_mm'], 2)
        linhas.append(f"| {r['lead']} | {r['target_month']} | {r['ens_mean']} | "
                       f"{r['chirps_prec_mm']} | {diff:+.2f} |")

    texto = '\n'.join(linhas) + '\n'
    caminho_summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if caminho_summary:
        with open(caminho_summary, 'a') as f:
            f.write(texto)
    else:
        print('\n' + texto)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--municipio', default='Sao_Bento_do_Tocantins')
    ap.add_argument('--init-year', type=int, default=2015)
    ap.add_argument('--init-month', type=int, default=1)
    ap.add_argument('--leads', default='1,2,3')
    ap.add_argument('--forcar-download', action='store_true')
    args = ap.parse_args()

    leads = parsear_leads(args.leads)
    rodar(args.municipio, args.init_year, args.init_month, leads, forcar_download=args.forcar_download)


if __name__ == '__main__':
    main()
