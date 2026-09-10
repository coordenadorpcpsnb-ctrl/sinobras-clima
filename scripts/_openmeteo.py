#!/usr/bin/env python3
"""
_openmeteo.py — busca de precipitação via Open-Meteo ERA5-Land
Compartilhado por fetch_monthly_data.py e update_dashboard.py — não
duplicar esta função nos dois scripts.
"""

import urllib.request, json, calendar
import pandas as pd

# Centroide das 34 fazendas Sinobras — Norte do Tocantins
FAZENDAS_LAT = -7.80
FAZENDAS_LON = -47.95


def buscar_prec_openmeteo(ano_ini, mes_ini, ano_fim, mes_fim):
    """
    Precipitação diária via Open-Meteo ERA5-Land → total mensal.
    Pede o intervalo inteiro numa única requisição e agrupa por mês —
    várias chamadas em sequência para meses individuais esbarram no
    rate limit (HTTP 429) da API.
    """
    ultimo_dia = calendar.monthrange(ano_fim, mes_fim)[1]
    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={FAZENDAS_LAT}&longitude={FAZENDAS_LON}"
        f"&start_date={ano_ini}-{mes_ini:02d}-01"
        f"&end_date={ano_fim}-{mes_fim:02d}-{ultimo_dia:02d}"
        f"&daily=precipitation_sum&timezone=America%2FSao_Paulo"
    )
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "sinobras-clima/1.0 (github-actions)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        df = pd.DataFrame({
            "data": pd.to_datetime(data["daily"]["time"]),
            "prec": pd.to_numeric(pd.Series(data["daily"]["precipitation_sum"]),
                                  errors="coerce").fillna(0),
        })
        df["ano"] = df["data"].dt.year
        df["mes"] = df["data"].dt.month
        mensal = df.groupby(["ano", "mes"])["prec"].sum().reset_index()
        mensal["prec"]  = mensal["prec"].round(1)
        mensal["fonte"] = "OpenMeteo-ERA5"
        return mensal
    except Exception as e:
        print(f"  ⚠ Open-Meteo indisponível: {e}")
        return pd.DataFrame(columns=["ano", "mes", "prec", "fonte"])
