#!/usr/bin/env python3
"""
c3s_processar.py — Fase 2A: GRIB/NetCDF (C3S) -> tabela.

Abre o arquivo baixado (ou já em cache) com xarray/cfgrib e extrai, para
um ponto (município), a série [local, init_date, target_month, lead,
centre, system, member, forecast_prec_mm].

ESQUEMA TEMPORAL — dois observados, os dois suportados (ver
`detectar_esquema_temporal`):

  A. `forecastMonth`/`leadtime_month` como coordenada — o lead mensal já
     vem pronto, inteiro, direto do arquivo (era a única forma testada
     antes desta correção, só contra Dataset sintético).

  B. `step` + `valid_time` — o que o arquivo REAL do CDS mostrou (3ª
     execução do workflow C3S POC, request_id cd5eba24-a49a-4ee7-ae56-
     9240aab18516, init 2015-01, leadtime_month=[1,2,3]): cfgrib expõe
     `number`, `time`, `step`, `surface`, `latitude`, `longitude`,
     `valid_time` — SEM `forecastMonth` nem `leadtime_month`.

     Para o esquema B, o lead mensal NUNCA é lido do valor numérico bruto
     de `step` (pode ser timedelta64 em horas/dias, não necessariamente
     alinhado a mês-calendário) — é sempre RECONSTRUÍDO a partir de
     `valid_time` (o timestamp real de validade do mês previsto):

         target_month = Period mensal de valid_time
         lead = mes_alvo_para_leadtime(init_date, target_month)

     (`mes_alvo_para_leadtime` já existe em _c3s_utils.py desde a
     confirmação documental da convenção leadtime_month=1 == mês de
     inicialização — a mesma relação matemática vale aqui, só que agora
     alimentada por um timestamp real em vez de um índice já pronto.)

Se nenhum dos dois esquemas for reconhecível, ou se `step` existir sem
`valid_time` correspondente, FALHA explicitamente (nunca assume step
numérico = lead — ver `detectar_esquema_temporal`).
"""

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from _c3s_utils import MUNICIPIOS, leadtime_para_mes_alvo, mes_alvo_para_leadtime, tprate_para_mm  # noqa: E402

_NOME_COORD_LEAD_PRONTO = ('forecastMonth', 'leadtime_month')

ESQUEMA_LEAD_PRONTO = 'leadtime_month'
ESQUEMA_STEP_VALID_TIME = 'step_valid_time'


def detectar_esquema_temporal(ds):
    """Devolve (esquema, nome_da_dimensao_que_varia_por_lead).

    Nunca adivinha: se só houver `step` sem `valid_time`, FALHA — não dá
    pra reconstruir target_month sem valid_time, e usar o valor bruto de
    step seria exatamente a suposição perigosa que a Seção 2 proíbe."""
    for nome in _NOME_COORD_LEAD_PRONTO:
        if nome in ds.coords or nome in ds.dims:
            return ESQUEMA_LEAD_PRONTO, nome

    tem_step = 'step' in ds.coords or 'step' in ds.dims
    tem_valid_time = 'valid_time' in ds.coords or 'valid_time' in ds.dims
    if tem_step and tem_valid_time:
        return ESQUEMA_STEP_VALID_TIME, 'step'
    if tem_step and not tem_valid_time:
        raise KeyError("dataset tem 'step' mas não tem 'valid_time' — não é possível reconstruir "
                        "target_month sem vazamento de suposição sobre a unidade de 'step' "
                        "(pode ser timedelta em horas, não necessariamente 1 mês-calendário). "
                        "FALHANDO em vez de adivinhar (Seção 2 da correção).")

    raise KeyError(f"nenhum esquema temporal reconhecido — nem {_NOME_COORD_LEAD_PRONTO} nem "
                    f"'step'+'valid_time'. Coordenadas disponíveis: {list(ds.coords)}")


def extrair_ponto(ds, lat, lon):
    """Vizinho mais próximo na grade — a grade C3S (1°x1°) é bem mais
    grosseira que a distância entre os 3 municípios desta fase, então
    'vizinho mais próximo' é adequado (não precisa de interpolação)."""
    return ds.sel(latitude=lat, longitude=lon, method='nearest')


def _valid_time_para_mes_alvo(valor):
    """np.datetime64/pd.Timestamp -> pandas.Period('M'). Funciona
    independente de qual dia do mês o valid_time representa (dia 1,
    meio do mês, o que for) — Period('M') só extrai ano+mês."""
    return pd.Period(pd.Timestamp(valor), freq='M')


def dataset_para_tabela(ds, local, centre, system, lat=None, lon=None):
    """Converte um xarray.Dataset (já recortado ou não no ponto) para o
    DataFrame tabular. Se lat/lon forem dados, extrai o ponto primeiro
    (via extrair_ponto); senão assume que ds já é 1 ponto."""
    if lat is not None and lon is not None:
        ds = extrair_ponto(ds, lat, lon)

    esquema, nome_dim = detectar_esquema_temporal(ds)
    tprate = ds['tprate']
    tem_membro = 'number' in tprate.dims

    linhas = []
    for it in range(ds.sizes.get('time', 1)):
        init_val = ds['time'].values[it] if 'time' in ds.dims else ds['time'].values
        init_date = pd.Period(pd.Timestamp(init_val), freq='M')
        fatia_tempo = tprate.isel(time=it) if 'time' in tprate.dims else tprate
        vt_da_origem = ds['valid_time'].isel(time=it) if (esquema == ESQUEMA_STEP_VALID_TIME
                                                            and 'time' in ds['valid_time'].dims) else ds.get('valid_time')

        for il in range(ds.sizes[nome_dim]):
            if esquema == ESQUEMA_LEAD_PRONTO:
                lead = int(np.atleast_1d(ds[nome_dim].values)[il])
                target_month = leadtime_para_mes_alvo(init_date, lead)
            else:   # ESQUEMA_STEP_VALID_TIME — nunca lê o valor bruto de step
                vt_val = (vt_da_origem.isel(step=il).values if (hasattr(vt_da_origem, 'dims') and 'step' in vt_da_origem.dims)
                          else np.atleast_1d(ds['valid_time'].values)[il])
                target_month = _valid_time_para_mes_alvo(vt_val)
                lead = mes_alvo_para_leadtime(init_date, target_month)

            fatia_lead = fatia_tempo.isel({nome_dim: il}) if nome_dim in fatia_tempo.dims else fatia_tempo

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


# ══════════════════════════════════════════════════════════════════════════
# DIAGNÓSTICO (Seção 1) — inspeção segura do arquivo real, sem despejar
# arrays grandes. Chamado por c3s_poc.py ANTES de qualquer validação
# estrita, para que uma 4ª execução com um formato ainda diferente deixe
# rastro suficiente no log/Summary para investigar sem precisar de outra
# rodada só para diagnóstico.
# ══════════════════════════════════════════════════════════════════════════

def diagnostico_dataset(ds, limite_valores=40):
    """Imprime estrutura (dims/coords/data_vars/attrs) e, quando possível,
    a correspondência time/step/valid_time — nunca os arrays de dado em
    si (latitude/longitude/tprate). Devolve um dict pequeno (serializável
    em JSON) com o mesmo conteúdo, para uso no Actions Summary."""
    info = {
        'dims': {k: int(v) for k, v in ds.sizes.items()},
        'coords': sorted(ds.coords),
        'data_vars': sorted(ds.data_vars),
        'attrs_globais': {k: str(v) for k, v in ds.attrs.items()},
    }
    if 'tprate' in ds.data_vars:
        info['attrs_tprate'] = {k: str(v) for k, v in ds['tprate'].attrs.items()}

    print("  --- diagnóstico do dataset ---")
    print(f"  dims: {info['dims']}")
    print(f"  coords: {info['coords']}")
    print(f"  data_vars: {info['data_vars']}")
    print(f"  attrs globais relevantes: { {k: v for k, v in info['attrs_globais'].items() if k in ('GRIB_edition', 'Conventions', 'institution')} }")
    if 'attrs_tprate' in info:
        print(f"  attrs de tprate: {info['attrs_tprate']}")

    correspondencia = []
    if 'valid_time' in ds.coords and 'step' in ds.coords:
        try:
            n_time = ds.sizes.get('time', 1)
            n_step = ds.sizes['step']
            if n_time * n_step <= limite_valores:
                for it in range(n_time):
                    tv = ds['time'].values[it] if 'time' in ds.dims else ds['time'].values
                    vt_fatia = ds['valid_time'].isel(time=it) if 'time' in ds['valid_time'].dims else ds['valid_time']
                    st_fatia = ds['step']
                    for il in range(n_step):
                        sv = st_fatia.values[il] if 'step' in st_fatia.dims else st_fatia.values
                        vv = vt_fatia.isel(step=il).values if 'step' in vt_fatia.dims else vt_fatia.values
                        linha = {'time': str(pd.Timestamp(tv)), 'step': str(sv), 'valid_time': str(pd.Timestamp(vv))}
                        correspondencia.append(linha)
                        print(f"  time={linha['time']}  step={linha['step']}  valid_time={linha['valid_time']}")
            else:
                print(f"  (correspondência time/step/valid_time omitida — {n_time*n_step} combinações, "
                      f"acima do limite de {limite_valores} para log seguro)")
        except Exception as e:
            print(f"  (não foi possível montar a correspondência time/step/valid_time: {e})")
    info['correspondencia_time_step_valid_time'] = correspondencia
    print("  --- fim do diagnóstico ---")
    return info


def cross_check_eccodes(caminho, limite_mensagens=20):
    """Validação cruzada OPCIONAL (Seção 6) via chaves GRIB de baixo nível
    (fcmonth/verifyingMonth/step/dataDate), lidas direto com eccodes —
    não é o caminho principal (esse é valid_time, via cfgrib/xarray), só
    um diagnóstico extra para conferência manual no log. Nunca lança
    exceção: qualquer falha aqui vira aviso, não erro — o parser
    principal (dataset_para_tabela) nunca depende deste resultado."""
    resultado = []
    try:
        import eccodes
    except ImportError:
        print("  (cross-check eccodes pulado — pacote eccodes não disponível)")
        return resultado

    try:
        with open(caminho, 'rb') as f:
            for _ in range(limite_mensagens):
                gid = eccodes.codes_grib_new_from_file(f)
                if gid is None:
                    break
                try:
                    chaves = {}
                    for chave in ('fcmonth', 'verifyingMonth', 'step', 'dataDate', 'indexingDate'):
                        try:
                            chaves[chave] = eccodes.codes_get(gid, chave)
                        except Exception:
                            chaves[chave] = None
                    resultado.append(chaves)
                    print(f"  [eccodes cross-check] {chaves}")
                finally:
                    eccodes.codes_release(gid)
    except Exception as e:
        print(f"  (cross-check eccodes falhou, ignorado — diagnóstico opcional: {e})")
    return resultado
