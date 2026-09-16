#!/usr/bin/env python3
"""
c3s_processar.py — Fase 2A: GRIB/NetCDF (C3S) -> tabela.

Abre o arquivo baixado (ou já em cache) com xarray/cfgrib e extrai, para
um ponto (município), a série [local, init_date, target_month, lead,
centre, system, member, forecast_prec_mm].

ESQUEMA TEMPORAL — dois observados (ver `detectar_esquema_temporal`):

  A. `forecastMonth`/`leadtime_month` como coordenada — o lead mensal já
     vem pronto, inteiro, direto do arquivo. `forecastMonth` é
     literalmente a mesma chave GRIB `fcmonth` só renomeada pelo
     cfgrib/CDS — não tem a armadilha do item B abaixo.

  B. `step` + `valid_time` — o que o arquivo REAL do CDS mostrou (3ª
     execução do workflow C3S POC, request_id cd5eba24-a49a-4ee7-ae56-
     9240aab18516, init 2015-01, leadtime_month=[1,2,3]): cfgrib expõe
     `number`, `time`, `step`, `surface`, `latitude`, `longitude`,
     `valid_time` — SEM `forecastMonth` nem `leadtime_month`.

     ARMADILHA REAL, CORRIGIDA NESTA VERSÃO: uma correção anterior desta
     mesma fase assumia `target_month = Period(valid_time, 'M')`. A 4ª
     execução real provou isso ERRADO — para este produto (médias
     mensais), `valid_time` é o LIMITE FINAL do período de acumulação/
     média, não o mês em si. Exemplo real: init=2015-01, primeiro campo
     pedido com leadtime_month=1 tem `valid_time=2015-02-01`, mas o
     eccodes lendo o MESMO campo mostra `fcmonth=1` e
     `verifyingMonth=201501` (janeiro/2015) — ou seja, `valid_time` de
     fevereiro é o fim de janeiro, não o mês de fevereiro. Usar
     `Period(valid_time,'M')` direto introduzia +1 mês de deslocamento.

     Por isso, para o esquema B, `target_month`/`lead` NUNCA vêm mais de
     `valid_time` nem do valor bruto de `step` — vêm de
     `extrair_mapeamento_temporal_grib()`, que lê `fcmonth`/
     `verifyingMonth` diretamente do GRIB via eccodes (fonte
     autoritativa, Seção 3 da correção) e cruza contra
     `leadtime_para_mes_alvo(init_date, fcmonth)` — se o GRIB disser
     outro verifyingMonth, FALHA (Seção 9). `valid_time` continua sendo
     lido e reportado (diagnóstico/auditoria), mas SEMPRE rotulado como
     "limite temporal", nunca como target_month.

Se nenhum esquema for reconhecível, ou se `step` existir sem
`valid_time` correspondente, FALHA explicitamente (nunca assume step
numérico = lead — ver `detectar_esquema_temporal`).
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from _c3s_utils import MUNICIPIOS, leadtime_para_mes_alvo, tprate_para_mm  # noqa: E402

_NOME_COORD_LEAD_PRONTO = ('forecastMonth', 'leadtime_month')

ESQUEMA_LEAD_PRONTO = 'leadtime_month'
ESQUEMA_STEP_VALID_TIME = 'step_valid_time'

# Chaves GRIB lidas via eccodes para o esquema B — fcmonth/verifyingMonth
# são a fonte autoritativa (Seção 3); dataDate serve só de conferência
# extra (tem que bater com init_date).
_CHAVES_GRIB_TEMPORAIS = ('step', 'fcmonth', 'verifyingMonth', 'dataDate', 'number')


def detectar_esquema_temporal(ds):
    """Devolve (esquema, nome_da_dimensao_que_varia_por_lead).

    Nunca adivinha: se só houver `step` sem `valid_time`, FALHA — não dá
    pra nem tentar reconstruir nada sem pelo menos localizar o arquivo
    original para ler fcmonth/verifyingMonth via eccodes."""
    for nome in _NOME_COORD_LEAD_PRONTO:
        if nome in ds.coords or nome in ds.dims:
            return ESQUEMA_LEAD_PRONTO, nome

    tem_step = 'step' in ds.coords or 'step' in ds.dims
    tem_valid_time = 'valid_time' in ds.coords or 'valid_time' in ds.dims
    if tem_step and tem_valid_time:
        return ESQUEMA_STEP_VALID_TIME, 'step'
    if tem_step and not tem_valid_time:
        raise KeyError("dataset tem 'step' mas não tem 'valid_time' — não há nem como localizar "
                        "as mensagens correspondentes para ler fcmonth/verifyingMonth via eccodes. "
                        "FALHANDO em vez de adivinhar (Seção 2 da correção).")

    raise KeyError(f"nenhum esquema temporal reconhecido — nem {_NOME_COORD_LEAD_PRONTO} nem "
                    f"'step'+'valid_time'. Coordenadas disponíveis: {list(ds.coords)}")


def extrair_ponto(ds, lat, lon):
    """Vizinho mais próximo na grade — a grade C3S (1°x1°) é bem mais
    grosseira que a distância entre os 3 municípios desta fase, então
    'vizinho mais próximo' é adequado (não precisa de interpolação)."""
    return ds.sel(latitude=lat, longitude=lon, method='nearest')


def _step_em_horas(valor):
    """Converte um valor de step (timedelta64, int já em horas, ou
    numpy timedelta escalar) para um inteiro de horas — usado só como
    CHAVE DE JUNÇÃO entre o valor de step decodificado pelo xarray e o
    valor de step (já em horas) lido via eccodes do MESMO campo GRIB.
    Não é heurística de duração mensal (Seção 5): é conversão de unidade
    de uma grandeza que os dois lados representam identicamente."""
    if isinstance(valor, np.timedelta64):
        return int(valor / np.timedelta64(1, 'h'))
    if hasattr(valor, 'total_seconds'):
        return int(valor.total_seconds() // 3600)
    return int(valor)


def extrair_mapeamento_temporal_grib(caminho, init_date, leads_esperados=None):
    """FONTE AUTORITATIVA de lead/target_month para o esquema B (Seção 3).

    Percorre TODO o arquivo GRIB via eccodes (Seção 7 — não só as
    primeiras mensagens: com N membros de ensemble há N mensagens por
    lead, e as primeiras `limite_mensagens` de uma leitura truncada
    podiam ser todas do mesmo fcmonth, escondendo os outros leads).
    Deduplica por (step, fcmonth, verifyingMonth) — várias mensagens
    (uma por membro) compartilham a mesma combinação.

    Cross-check obrigatório (Seção 9): verifyingMonth do GRIB tem que
    bater com `leadtime_para_mes_alvo(init_date, fcmonth)` — nossa
    convenção (lead 1 = mês de inicialização). Se o GRIB disser outro
    mês, FALHA (nunca aceita metadado inconsistente).

    Devolve {step_em_horas: {'fcmonth':int, 'lead':int, 'target_month':Period}}.
    """
    import eccodes

    init_date = pd.Period(init_date, 'M')
    combinacoes = {}   # step_horas -> (fcmonth, target_month)
    n_mensagens = 0

    with open(caminho, 'rb') as f:
        while True:
            gid = eccodes.codes_grib_new_from_file(f)
            if gid is None:
                break
            n_mensagens += 1
            try:
                step_bruto = eccodes.codes_get(gid, 'step')
                fcmonth = int(eccodes.codes_get(gid, 'fcmonth'))
                verifying_month_raw = int(eccodes.codes_get(gid, 'verifyingMonth'))
            finally:
                eccodes.codes_release(gid)

            ano_vm, mes_vm = divmod(verifying_month_raw, 100)
            target_month = pd.Period(f'{ano_vm:04d}-{mes_vm:02d}', 'M')
            lead = fcmonth

            esperado = leadtime_para_mes_alvo(init_date, lead)
            if target_month != esperado:
                raise RuntimeError(
                    f"Conflito de metadado GRIB (Seção 9): fcmonth={lead} implica target_month="
                    f"{esperado} pela convenção (lead 1 = mês de inicialização {init_date}), mas "
                    f"verifyingMonth do GRIB diz {target_month} — FALHANDO em vez de aceitar "
                    f"metadado inconsistente.")

            step_h = _step_em_horas(step_bruto)
            if step_h in combinacoes and combinacoes[step_h] != (lead, target_month):
                raise RuntimeError(
                    f"step={step_h}h aparece com combinações fcmonth/verifyingMonth diferentes "
                    f"entre mensagens do mesmo arquivo — FALHANDO: {combinacoes[step_h]} vs "
                    f"{(lead, target_month)}")
            combinacoes[step_h] = (lead, target_month)

    if n_mensagens == 0:
        raise RuntimeError(f"nenhuma mensagem GRIB encontrada em {caminho} — FALHANDO.")

    leads_encontrados = sorted(lead for lead, _ in combinacoes.values())
    if leads_esperados is not None and leads_encontrados != sorted(leads_esperados):
        raise RuntimeError(f"leads encontrados via fcmonth ({leads_encontrados}) != leads pedidos "
                            f"({sorted(leads_esperados)}) — FALHANDO. Combinações únicas: {combinacoes}")

    return {step_h: {'fcmonth': lead, 'lead': lead, 'target_month': tm}
            for step_h, (lead, tm) in combinacoes.items()}


def dataset_para_tabela(ds, local, centre, system, lat=None, lon=None, mapeamento_step_fcmonth=None):
    """Converte um xarray.Dataset (já recortado ou não no ponto) para o
    DataFrame tabular. Se lat/lon forem dados, extrai o ponto primeiro
    (via extrair_ponto); senão assume que ds já é 1 ponto.

    `mapeamento_step_fcmonth`: OBRIGATÓRIO para o esquema B (step+
    valid_time) — o dict devolvido por extrair_mapeamento_temporal_grib.
    Sem ele, não há como determinar target_month/lead com segurança
    nesse esquema (ver docstring do módulo) — levanta erro explícito em
    vez de arriscar usar valid_time diretamente de novo."""
    if lat is not None and lon is not None:
        ds = extrair_ponto(ds, lat, lon)

    esquema, nome_dim = detectar_esquema_temporal(ds)
    if esquema == ESQUEMA_STEP_VALID_TIME and mapeamento_step_fcmonth is None:
        raise ValueError("esquema 'step_valid_time' exige mapeamento_step_fcmonth (ver "
                          "extrair_mapeamento_temporal_grib) — não é seguro derivar target_month "
                          "de valid_time diretamente (ver docstring do módulo).")

    tprate = ds['tprate']
    tem_membro = 'number' in tprate.dims

    linhas = []
    for it in range(ds.sizes.get('time', 1)):
        init_val = ds['time'].values[it] if 'time' in ds.dims else ds['time'].values
        init_date = pd.Period(pd.Timestamp(init_val), freq='M')
        fatia_tempo = tprate.isel(time=it) if 'time' in tprate.dims else tprate

        for il in range(ds.sizes[nome_dim]):
            if esquema == ESQUEMA_LEAD_PRONTO:
                lead = int(np.atleast_1d(ds[nome_dim].values)[il])
                target_month = leadtime_para_mes_alvo(init_date, lead)
            else:   # ESQUEMA_STEP_VALID_TIME — step só como chave de junção, nunca como valor
                step_val = ds['step'].values[il] if 'step' in ds['step'].dims else ds['step'].values
                step_h = _step_em_horas(step_val)
                if step_h not in mapeamento_step_fcmonth:
                    raise KeyError(f"step={step_h}h (índice {il}) não está no mapeamento eccodes "
                                    f"{sorted(mapeamento_step_fcmonth)} — FALHANDO em vez de adivinhar.")
                entrada = mapeamento_step_fcmonth[step_h]
                lead, target_month = entrada['lead'], entrada['target_month']

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


def processar_municipios(ds, centre, system, municipios=None, mapeamento_step_fcmonth=None):
    """Roda dataset_para_tabela para os municípios pedidos (default: os 3
    da Fase 2A) e concatena."""
    municipios = municipios or list(MUNICIPIOS.keys())
    partes = []
    for chave in municipios:
        info = MUNICIPIOS[chave]
        partes.append(dataset_para_tabela(ds, chave, centre, system, lat=info['lat'], lon=info['lon'],
                                           mapeamento_step_fcmonth=mapeamento_step_fcmonth))
    return pd.concat(partes, ignore_index=True)


# ══════════════════════════════════════════════════════════════════════════
# DIAGNÓSTICO (Seção 1) — inspeção segura do arquivo real, sem despejar
# arrays grandes. Chamado por c3s_poc.py ANTES de qualquer validação
# estrita. `valid_time` aqui é só o valor bruto decodificado pelo
# cfgrib — NUNCA interpretado como target_month (ver docstring do
# módulo); rotulado explicitamente como limite temporal na saída.
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
                        # rótulo explícito (Seção 10): valid_time É o limite temporal
                        # decodificado pelo cfgrib, NUNCA o target_month.
                        linha = {'time': str(pd.Timestamp(tv)), 'step': str(sv),
                                 'valid_time_limite_temporal': str(pd.Timestamp(vv))}
                        correspondencia.append(linha)
                        print(f"  time={linha['time']}  step={linha['step']}  "
                              f"valid_time(limite temporal, NÃO é o mês)={linha['valid_time_limite_temporal']}")
            else:
                print(f"  (correspondência time/step/valid_time omitida — {n_time*n_step} combinações, "
                      f"acima do limite de {limite_valores} para log seguro)")
        except Exception as e:
            print(f"  (não foi possível montar a correspondência time/step/valid_time: {e})")
    info['correspondencia_time_step_valid_time'] = correspondencia
    print("  --- fim do diagnóstico ---")
    return info
