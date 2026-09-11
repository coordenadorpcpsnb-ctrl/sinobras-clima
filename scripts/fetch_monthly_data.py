#!/usr/bin/env python3
"""
fetch_monthly_data.py — Busca dados climáticos dos meses ausentes
Sinobras Florestal · executado pelo GitHub Actions toda dia 21

Fluxo:
  1. Lista TODAS as lacunas entre o início da série e o mês anterior ao
     atual (não só o último mês — se o pipeline não rodar num mês, o
     buraco fica para sempre se só olharmos "o mês anterior")
  2. Busca a precipitação em cascata, três camadas:
       a. CHIRPS Final (ClimateSERV, ponto único) — primária
       b. CHC Preliminary (zonal, polígono real das 37 fazendas) — só
          para os meses que o Final ainda não publicou
       c. Open-Meteo ERA5-Land — só para o que sobrar das duas acima
     Cada mês novo registra qual das três foi usada.
  3. Busca os índices ENSO de cada mês no master_monthly.csv, com
     persistência (nunca zero) quando o mês ainda não está consolidado
  4. Grava os meses novos em serie_subst.csv

CHIRPS Final (UCSB, via ClimateSERV) — fonte primária:
  - Combina satélite (0,05°) com estações in situ, desenhado para
    monitoramento de seca
  - Serviço acadêmico (SERVIR/NASA) — pode ficar fora do ar; timeout
    generoso e fallback automático se falhar
  - Tem defasagem de publicação de alguns meses (ver _chirps.py)
  - Aqui usa ponto único (buscar_prec_chirps), não o polígono real —
    a versão zonal (buscar_prec_chirps_zonal) existe mas não está
    plugada no pipeline automático, ver CLAUDE.md armadilha 8: sem
    tratamento de falha parcial de grupo, arriscada para automação.

CHC Preliminary — fallback intermediário, fonte='CHC-Preliminar':
  - MESMO produto CHIRPS, versão preliminar (antes da consolidação
    final) — publica antes do Final, mas pode ser revisado depois
  - Download direto do CHC + zonal stats (rasterio/rasterstats) sobre
    o polígono REAL das 37 fazendas — sem a limitação de anel único do
    ClimateSERV, é processamento local (ver _chirps.py)
  - Gravado com fonte própria, não 'CHIRPS' — quando o Final publicar
    esse mês depois, o valor Preliminary já gravado NÃO é substituído
    automaticamente (mesma limitação da persistência do PDO — ver
    CLAUDE.md armadilha 6)

Open-Meteo ERA5-Land — fallback final:
  - Gratuito, sem autenticação, acessível globalmente
  - Viés sazonal forte em jun-ago (registra só 24-37% da chuva das
    estações nesses meses — ver CLAUDE.md armadilha 7); usado só
    quando nem o CHIRPS Final nem o CHC Preliminary têm o mês
  - Centroide Sinobras: lat=-7.80, lon=-47.95 (Norte do Tocantins)
"""

import sys, shutil
from pathlib import Path
from datetime import date
import pandas as pd

from _chirps import buscar_prec_chirps, buscar_prec_chc_preliminar_zonal
from _openmeteo import buscar_prec_openmeteo

ROOT       = Path(__file__).parent.parent
SERIE_PATH = ROOT / 'data' / 'serie_subst.csv'
MERRA_PATH = ROOT / 'data' / 'master_monthly.csv'

MESES_PT = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez']


def mes_anterior():
    """Retorna (ano, mes) do mês anterior ao dia de hoje."""
    hoje = date.today()
    if hoje.month == 1:
        return hoje.year - 1, 12
    return hoje.year, hoje.month - 1


def listar_lacunas(serie, ate_ano, ate_mes):
    """
    Lista todos os (ano, mes) faltando entre o primeiro mês da série e
    ate_ano/ate_mes (inclusive) — cobre lacunas internas, não só o mês
    seguinte ao último registro.
    """
    existentes = set(zip(serie['ano'].astype(int), serie['mes'].astype(int)))
    y, m = int(serie['ano'].iloc[0]), int(serie['mes'].iloc[0])
    faltando = []
    while (y, m) <= (ate_ano, ate_mes):
        if (y, m) not in existentes:
            faltando.append((y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return faltando


def enso_indices(ano: int, mes: int) -> dict:
    """
    Busca índices ENSO do master_monthly.csv para o mês dado.
    Se o mês exato não existir, usa persistência do último valor
    disponível — zero significaria ENSO neutro, uma afirmação falsa
    quando o mês simplesmente ainda não foi consolidado no master.
    Retorna dict com nino34, tsa, pdo e 'origem'
    ('master' ou 'persistencia de MM/AAAA').
    """
    try:
        merra = pd.read_csv(MERRA_PATH)
    except Exception:
        return {'nino34': 0.0, 'tsa': 0.0, 'pdo': 0.0, 'origem': 'indisponivel'}

    row = merra[(merra['year'] == ano) & (merra['month'] == mes)]
    if not row.empty:
        return {
            'nino34': float(row['nino34'].iloc[0]),
            'tsa':    float(row['tsa'].iloc[0]),
            'pdo':    float(row['pdo'].iloc[0]),
            'origem': 'master',
        }

    anteriores = merra[
        (merra['year'] < ano) | ((merra['year'] == ano) & (merra['month'] < mes))
    ].sort_values(['year', 'month'])
    if not anteriores.empty:
        ult = anteriores.iloc[-1]
        return {
            'nino34': float(ult['nino34']),
            'tsa':    float(ult['tsa']),
            'pdo':    float(ult['pdo']),
            'origem': f"persistencia de {int(ult['month']):02d}/{int(ult['year'])}",
        }

    return {'nino34': 0.0, 'tsa': 0.0, 'pdo': 0.0, 'origem': 'indisponivel'}


def main():
    TODAY = date.today()
    ano_lim, mes_lim = mes_anterior()

    print(f"\n{'='*55}")
    print(f"  BUSCA DE DADOS MENSAIS — {TODAY.strftime('%d/%m/%Y')}")
    print(f"  Até: {MESES_PT[mes_lim-1]}/{ano_lim}")
    print(f"{'='*55}")

    serie = pd.read_csv(SERIE_PATH)
    faltando = listar_lacunas(serie, ano_lim, mes_lim)

    if not faltando:
        print(f"\n  ℹ Série completa até {MESES_PT[mes_lim-1]}/{ano_lim}")
        print(f"  Nenhuma ação necessária.")
        print(f"\n{'='*55}\n")
        return 0

    print(f"\n  Meses faltando: "
          + ', '.join(f'{m:02d}/{y}' for y, m in faltando))

    # Buscar precipitação em cascata: CHIRPS Final -> CHC Preliminary -> Open-Meteo
    y_ini, m_ini = faltando[0]
    y_fim, m_fim = faltando[-1]

    print(f"\n[1/4] Buscando CHIRPS Final ({m_ini:02d}/{y_ini} → {m_fim:02d}/{y_fim})…")
    chirps_df = buscar_prec_chirps(y_ini, m_ini, y_fim, m_fim)
    prec_map  = {}
    fonte_map = {}
    for r in chirps_df.itertuples():
        prec_map[(int(r.ano), int(r.mes))]  = r.prec
        fonte_map[(int(r.ano), int(r.mes))] = 'CHIRPS'

    faltando_chirps = [ym for ym in faltando if ym not in prec_map]
    faltando_prelim = []
    if faltando_chirps:
        print(f"\n[2/4] CHIRPS Final sem {len(faltando_chirps)} mês(es) — "
              f"tentando CHC Preliminary (zonal, polígono real)…")
        for (y, m) in faltando_chirps:
            r = buscar_prec_chc_preliminar_zonal(y, m)
            if r is not None:
                prec_map[(y, m)]  = r['prec']
                fonte_map[(y, m)] = 'CHC-Preliminar'
                print(f"  ✅ {MESES_PT[m-1]}/{y}: {r['prec']}mm (CHC-Preliminar)")
            else:
                faltando_prelim.append((y, m))
    else:
        print(f"\n[2/4] CHIRPS Final cobriu todos os meses — CHC Preliminary não necessário")

    if faltando_prelim:
        y_ini2, m_ini2 = faltando_prelim[0]
        y_fim2, m_fim2 = faltando_prelim[-1]
        print(f"\n[3/4] Ainda sem {len(faltando_prelim)} mês(es) — "
              f"buscando Open-Meteo ERA5-Land (fallback final) "
              f"({m_ini2:02d}/{y_ini2} → {m_fim2:02d}/{y_fim2})…")
        era5_df = buscar_prec_openmeteo(y_ini2, m_ini2, y_fim2, m_fim2)
        for r in era5_df.itertuples():
            key = (int(r.ano), int(r.mes))
            if key not in prec_map:
                prec_map[key]  = r.prec
                fonte_map[key] = 'OpenMeteo-ERA5'
    else:
        print(f"\n[3/4] Nenhum mês restante — Open-Meteo não necessário")

    print(f"\n[4/4] Buscando índices ENSO por mês…")
    novas = []
    for (y, m) in faltando:
        if (y, m) not in prec_map:
            print(f"  ⚠ {MESES_PT[m-1]}/{y}: sem precipitação de nenhuma fonte — "
                  f"pulando, tentaremos na próxima execução")
            continue

        prec  = prec_map[(y, m)]
        fonte = fonte_map[(y, m)]
        enso  = enso_indices(y, m)
        if enso['origem'] != 'master':
            print(f"  ⚠ {MESES_PT[m-1]}/{y}: sem registro no master_monthly — "
                  f"usando {enso['origem']}")

        novas.append({
            'ano':    y,
            'mes':    m,
            'prec':   prec,
            'nino34': enso['nino34'],
            'tsa':    enso['tsa'],
            'pdo':    enso['pdo'],
            'date':   f"{y}-{m:02d}-01",
            'fonte':  fonte,
        })

    if not novas:
        print(f"\n  Nenhum mês pôde ser preenchido nesta execução.")
        print(f"\n{'='*55}\n")
        return 0

    if SERIE_PATH.exists():
        shutil.copy2(SERIE_PATH, SERIE_PATH.with_suffix(SERIE_PATH.suffix + '.bak'))

    serie = pd.concat([serie, pd.DataFrame(novas)], ignore_index=True)\
              .sort_values(['ano', 'mes']).reset_index(drop=True)
    serie.to_csv(SERIE_PATH, index=False)

    print(f"\n  ✅ {len(novas)} mês(es) adicionados: "
          + ', '.join(f"{n['mes']:02d}/{n['ano']} ({n['fonte']})" for n in novas)
          + f" — {len(serie)} meses total na série")
    print(f"\n{'='*55}\n")
    return 0


if __name__ == '__main__':
    sys.exit(main())
