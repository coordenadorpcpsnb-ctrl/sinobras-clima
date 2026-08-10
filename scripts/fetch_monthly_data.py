#!/usr/bin/env python3
"""
fetch_monthly_data.py — Busca dados climáticos do mês anterior
Sinobras Florestal · executado pelo GitHub Actions toda dia 21

Fluxo:
  1. Calcula qual é o mês anterior (ex: rodando em 21/ago → busca jul/2026)
  2. Consulta Open-Meteo ERA5-Land (centroide fazendas Sinobras, Norte TO)
  3. Soma a precipitação diária → total mensal
  4. Verifica se o mês já existe na série (série Sinobras tem prioridade)
  5. Se não existe, adiciona à serie_subst.csv com fonte='OpenMeteo-ERA5'

Open-Meteo ERA5-Land:
  - Gratuito, sem autenticação, acessível globalmente
  - Resolução: 0.1° (~9km) — adequado para estimativa mensal da região
  - Delay: dados consolidados disponíveis ~5 dias após o mês encerrar
  - Centroide Sinobras: lat=-7.80, lon=-47.95 (Norte do Tocantins)
"""

import sys, json, calendar
from pathlib import Path
from datetime import date
import urllib.request
import pandas as pd

ROOT       = Path(__file__).parent.parent
SERIE_PATH = ROOT / 'data' / 'serie_subst.csv'
MERRA_PATH = ROOT / 'data' / 'master_monthly.csv'

# Centroide das 34 fazendas Sinobras — Norte do Tocantins
LAT =  -7.80
LON = -47.95

HEADERS = {'User-Agent': 'sinobras-clima/1.0 (github-actions)'}


def mes_anterior():
    """Retorna (ano, mes) do mês anterior ao dia de hoje."""
    hoje = date.today()
    if hoje.month == 1:
        return hoje.year - 1, 12
    return hoje.year, hoje.month - 1


def buscar_openmeteo(ano: int, mes: int) -> float | None:
    """
    Busca precipitação total do mês via Open-Meteo ERA5-Land.
    Retorna total em mm ou None se falhar.
    """
    ultimo_dia = calendar.monthrange(ano, mes)[1]
    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={LAT}&longitude={LON}"
        f"&start_date={ano}-{mes:02d}-01"
        f"&end_date={ano}-{mes:02d}-{ultimo_dia:02d}"
        f"&daily=precipitation_sum"
        f"&timezone=America%2FSao_Paulo"
    )
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        vals = [float(v) for v in data['daily']['precipitation_sum'] if v is not None]
        total = round(sum(vals), 1)
        return total
    except Exception as e:
        print(f"  ⚠ Open-Meteo falhou: {e}")
        return None


def enso_indices(ano: int, mes: int) -> dict:
    """
    Busca índices ENSO do master_monthly.csv para o mês dado.
    Retorna dict com nino34, tsa, pdo (ou 0.0 se não disponível).
    """
    try:
        merra = pd.read_csv(MERRA_PATH)
        row = merra[(merra['year'] == ano) & (merra['month'] == mes)]
        if not row.empty:
            return {
                'nino34': float(row['nino34'].iloc[0]),
                'tsa':    float(row['tsa'].iloc[0]),
                'pdo':    float(row['pdo'].iloc[0]),
            }
    except Exception:
        pass
    return {'nino34': 0.0, 'tsa': 0.0, 'pdo': 0.0}


def main():
    TODAY = date.today()
    ano, mes = mes_anterior()
    meses_pt = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez']

    print(f"\n{'='*55}")
    print(f"  BUSCA DE DADOS MENSAIS — {TODAY.strftime('%d/%m/%Y')}")
    print(f"  Mês alvo: {meses_pt[mes-1]}/{ano}")
    print(f"{'='*55}")

    # Carregar série atual
    serie = pd.read_csv(SERIE_PATH)
    existentes = set(zip(serie['ano'].astype(int), serie['mes'].astype(int)))

    if (ano, mes) in existentes:
        fonte = serie[(serie['ano']==ano) & (serie['mes']==mes)]['fonte'].iloc[0] \
                if 'fonte' in serie.columns else 'Sinobras'
        print(f"\n  ℹ {meses_pt[mes-1]}/{ano} já existe na série (fonte: {fonte})")
        print(f"  Nenhuma ação necessária.")
        print(f"\n{'='*55}\n")
        return 0

    # Buscar dados
    print(f"\n[1/2] Buscando Open-Meteo ERA5-Land ({LAT}, {LON})…")
    prec = buscar_openmeteo(ano, mes)

    if prec is None:
        print(f"  ❌ Não foi possível obter dados para {meses_pt[mes-1]}/{ano}")
        print(f"  O mês será incorporado na próxima execução quando disponível.")
        return 0

    print(f"  ✅ Precipitação {meses_pt[mes-1]}/{ano}: {prec} mm (ERA5-Land)")

    # Buscar índices ENSO
    print(f"\n[2/2] Buscando índices ENSO…")
    enso = enso_indices(ano, mes)
    print(f"  Niño 3.4: {enso['nino34']} | TSA: {enso['tsa']} | PDO: {enso['pdo']}")

    # Adicionar à série
    novo = pd.DataFrame([{
        'ano':    ano,
        'mes':    mes,
        'prec':   prec,
        'nino34': enso['nino34'],
        'tsa':    enso['tsa'],
        'pdo':    enso['pdo'],
        'date':   f"{ano}-{mes:02d}-01",
        'fonte':  'OpenMeteo-ERA5',
    }])

    serie = pd.concat([serie, novo], ignore_index=True)\
              .sort_values(['ano','mes']).reset_index(drop=True)
    serie.to_csv(SERIE_PATH, index=False)

    print(f"\n  ✅ {meses_pt[mes-1]}/{ano} adicionado à série ({len(serie)} meses total)")
    print(f"  Fonte: Open-Meteo ERA5-Land · centroide fazendas Sinobras")
    print(f"\n{'='*55}\n")
    return 0


if __name__ == '__main__':
    sys.exit(main())
