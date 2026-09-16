#!/usr/bin/env python3
"""
c3s_processar.py — Fase 2A: GRIB/NetCDF (C3S) -> tabela.

Abre o arquivo baixado (ou já em cache) com xarray/cfgrib e extrai, para
um ponto (município), a série [local, init_date, target_month, lead,
centre, system, member, forecast_prec_mm].

Estrutura esperada do xarray.Dataset (confirmada via documentação
pública, não via arquivo real — ver c3s_catalogo.py sobre o bloqueio de
rede desta sessão): coordenadas `latitude`/`longitude` (grade regular),
`time` (data de inicialização, sempre dia 1 do mês), `forecastMonth`
(ou `leadtime_month` dependendo de como o cfgrib decodifica — os dois
nomes são tratados aqui, ver `_NOME_COORD_LEAD`), `number` (membro do
ensemble, ausente ou com um só valor no controle determinístico) e a
variável `tprate` (m/s). Testado nesta sessão só com Dataset SINTÉTICO
construído com essa mesma forma (ver tests/test_c3s_processar.py) — não
há arquivo GRIB real disponível para validar contra o formato exato do
CDS (rede bloqueada, ver c3s_download.py).
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from _c3s_utils import MUNICIPIOS, leadtime_para_mes_alvo, tprate_para_mm  # noqa: E402

_NOME_COORD_LEAD = ('forecastMonth', 'leadtime_month')


def _nome_coord_lead(ds):
    for nome in _NOME_COORD_LEAD:
        if nome in ds.coords or nome in ds.dims:
            return nome
    raise KeyError(f"nenhuma coordenada de lead encontrada entre {_NOME_COORD_LEAD} — "
                    f"coordenadas disponíveis: {list(ds.coords)}")


def extrair_ponto(ds, lat, lon):
    """Vizinho mais próximo na grade — a grade C3S (1°x1°) é bem mais
    grosseira que a distância entre os 3 municípios desta fase, então
    'vizinho mais próximo' é adequado (não precisa de interpolação)."""
    return ds.sel(latitude=lat, longitude=lon, method='nearest')


def dataset_para_tabela(ds, local, centre, system, lat=None, lon=None):
    """Converte um xarray.Dataset (já recortado ou não no ponto) para o
    DataFrame tabular da Seção 6. Se lat/lon forem dados, extrai o ponto
    primeiro (via extrair_ponto); senão assume que ds já é 1 ponto."""
    if lat is not None and lon is not None:
        ds = extrair_ponto(ds, lat, lon)

    nome_lead = _nome_coord_lead(ds)
    tprate = ds['tprate']

    tem_membro = 'number' in tprate.dims
    linhas = []
    for it in range(ds.sizes.get('time', 1)):
        init_val = ds['time'].values[it] if 'time' in ds.dims else ds['time'].values
        init_date = pd.Period(pd.Timestamp(init_val), freq='M')
        fatia_tempo = tprate.isel(time=it) if 'time' in tprate.dims else tprate

        for il in range(ds.sizes[nome_lead]):
            lead = int(np.atleast_1d(ds[nome_lead].values)[il])
            target_month = leadtime_para_mes_alvo(init_date, lead)
            fatia_lead = fatia_tempo.isel({nome_lead: il}) if nome_lead in fatia_tempo.dims else fatia_tempo

            if tem_membro:
                for im in range(ds.sizes['number']):
                    membro = int(np.atleast_1d(ds['number'].values)[im])
                    valor = float(fatia_lead.isel(number=im).values)
                    linhas.append(_linha(local, init_date, target_month, lead, centre, system,
                                          membro, valor))
            else:
                valor = float(np.asarray(fatia_lead.values))
                linhas.append(_linha(local, init_date, target_month, lead, centre, system, 0, valor))

    return pd.DataFrame(linhas)


def _linha(local, init_date, target_month, lead, centre, system, membro, tprate_m_s):
    prec_mm = tprate_para_mm(tprate_m_s, target_month.year, target_month.month)
    return {
        'local': local, 'init_date': str(init_date), 'target_month': str(target_month),
        'lead': lead, 'centre': centre, 'system': system, 'member': membro,
        'forecast_prec_mm': round(prec_mm, 3),
    }


def processar_municipios(ds, centre, system, municipios=None):
    """Roda dataset_para_tabela para os municípios pedidos (default: os 3
    da Fase 2A) e concatena."""
    municipios = municipios or list(MUNICIPIOS.keys())
    partes = []
    for chave in municipios:
        info = MUNICIPIOS[chave]
        partes.append(dataset_para_tabela(ds, chave, centre, system, lat=info['lat'], lon=info['lon']))
    return pd.concat(partes, ignore_index=True)
