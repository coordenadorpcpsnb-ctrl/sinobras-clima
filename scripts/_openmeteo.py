#!/usr/bin/env python3
"""
_openmeteo.py — busca de precipitação via Open-Meteo ERA5-Land
Compartilhado por fetch_monthly_data.py e update_dashboard.py — não
duplicar esta função nos dois scripts.
"""

import math
import urllib.request, json, calendar
from datetime import datetime

import pandas as pd

# Centroide das 34 fazendas Sinobras — Norte do Tocantins
FAZENDAS_LAT = -7.80
FAZENDAS_LON = -47.95


def _validar_e_agregar_dias_openmeteo(tempos, valores):
    """
    Mesma disciplina de `_chirps.py::_validar_e_agregar_dias` — um mês
    só entra no resultado quando TODOS os dias do calendário têm
    exatamente uma data válida com valor numérico finito e não
    negativo. `daily.time` já vem como string ISO 'YYYY-MM-DD' (sem
    ambiguidade de formato, ao contrário de `date` no ClimateSERV) no
    fuso pedido na própria URL (America/Sao_Paulo) — não há conversão
    de fuso a fazer aqui, o dia calendário já é o dia correto.

    Nunca converte `None`/valor ausente em zero: só uma observação
    numérica real (incluindo 0.0 legítimo) conta como dia coberto.

    Retorna DataFrame [ano, mes, prec] (sem a coluna 'fonte').
    """
    por_mes = {}            # (ano,mes) -> {dia: prec_valido}
    meses_invalidados = set()
    descartados_sem_identificacao = 0

    for t_str, v in zip(tempos, valores):
        try:
            dt = datetime.strptime(str(t_str), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            descartados_sem_identificacao += 1
            continue

        chave = (dt.year, dt.month)

        if v is None:
            meses_invalidados.add(chave)
            print(f"  ⚠ Open-Meteo: {dt.isoformat()} sem observação "
                  f"(precipitation_sum ausente/None) — mês invalidado, "
                  f"fallback será tentado")
            continue
        try:
            v_f = float(v)
        except (TypeError, ValueError):
            meses_invalidados.add(chave)
            print(f"  ⚠ Open-Meteo: {dt.isoformat()} valor não numérico "
                  f"({v!r}) — mês invalidado, fallback será tentado")
            continue
        if not math.isfinite(v_f):
            meses_invalidados.add(chave)
            print(f"  ⚠ Open-Meteo: {dt.isoformat()} valor não finito "
                  f"(NaN/±inf: {v_f}) — mês invalidado, fallback será tentado")
            continue
        if v_f < 0:
            meses_invalidados.add(chave)
            print(f"  ⚠ Open-Meteo: {dt.isoformat()} valor negativo "
                  f"(fisicamente inválido: {v_f}) — mês invalidado, "
                  f"fallback será tentado")
            continue

        dias_do_mes = por_mes.setdefault(chave, {})
        if dt.day in dias_do_mes:
            meses_invalidados.add(chave)
            print(f"  ⚠ Open-Meteo: {dt.isoformat()} duplicado — mês "
                  f"invalidado, fallback será tentado")
            continue
        dias_do_mes[dt.day] = v_f

    if descartados_sem_identificacao:
        print(f"  ⚠ Open-Meteo: {descartados_sem_identificacao} data(s) inválida(s) "
              f"descartada(s), sem afetar nenhum mês específico")

    linhas = []
    for (ano, mes), dias_validos in por_mes.items():
        if (ano, mes) in meses_invalidados:
            continue
        n_dias_mes = calendar.monthrange(ano, mes)[1]
        if len(dias_validos) != n_dias_mes:
            print(f"  ⚠ Open-Meteo: {mes:02d}/{ano} com cobertura incompleta "
                  f"({len(dias_validos)}/{n_dias_mes} dias) — mês não aceito, "
                  f"fallback será tentado")
            continue
        linhas.append({'ano': ano, 'mes': mes, 'prec': round(sum(dias_validos.values()), 1)})

    return pd.DataFrame(linhas, columns=['ano', 'mes', 'prec'])


def buscar_prec_openmeteo(ano_ini, mes_ini, ano_fim, mes_fim):
    """
    Precipitação diária via Open-Meteo ERA5-Land → total mensal.
    Pede o intervalo inteiro numa única requisição e agrupa por mês —
    várias chamadas em sequência para meses individuais esbarram no
    rate limit (HTTP 429) da API.

    Valida cobertura diária completa (ver
    `_validar_e_agregar_dias_openmeteo`) antes de aceitar qualquer
    mês — um mês com dia ausente, duplicado ou valor
    ausente/inválido/negativo simplesmente não aparece no resultado,
    nunca é aceito com um total parcial ou com ausência convertida
    em zero.
    """
    ultimo_dia = calendar.monthrange(ano_fim, mes_fim)[1]
    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={FAZENDAS_LAT}&longitude={FAZENDAS_LON}"
        f"&start_date={ano_ini}-{mes_ini:02d}-01"
        f"&end_date={ano_fim}-{mes_fim:02d}-{ultimo_dia:02d}"
        f"&daily=precipitation_sum&timezone=America%2FSao_Paulo"
    )
    vazio = pd.DataFrame(columns=["ano", "mes", "prec", "fonte"])
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "sinobras-clima/1.0 (github-actions)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())

        tempos = data["daily"]["time"]
        valores = data["daily"]["precipitation_sum"]
        if len(tempos) != len(valores):
            print(f"  ⚠ Open-Meteo: quantidade de datas ({len(tempos)}) difere da "
                  f"quantidade de valores ({len(valores)}) — resposta rejeitada")
            return vazio

        mensal = _validar_e_agregar_dias_openmeteo(tempos, valores)
        mensal["fonte"] = "OpenMeteo-ERA5"
        return mensal
    except Exception as e:
        print(f"  ⚠ Open-Meteo indisponível: {e}")
        return vazio
