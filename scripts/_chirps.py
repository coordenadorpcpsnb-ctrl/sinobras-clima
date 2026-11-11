#!/usr/bin/env python3
"""
_chirps.py — busca de precipitação via CHIRPS (UCSB), pelo ClimateSERV
Compartilhado por fetch_monthly_data.py e scripts/backfill_chirps_historico.py.

CHIRPS é a fonte primária de fallback (ver CLAUDE.md, armadilha 7): tem
viés desprezível contra as estações Sinobras (razão mediana 0,998 no
período 1981-2025), contra 0,88 do Open-Meteo ERA5-Land. Julho é
exceção conhecida em ambas as fontes — não tratado à parte (ver
armadilha 7 para a justificativa).

ENSO-COBERTURA (verificação real controlada, 06/2024, dataset 0/
Average, mesma geometria de produção): o ClimateSERV devolve, em
`result['data']` (caminho `memory_object`, sem nenhuma transformação
da biblioteca — confirmado lendo climateserv==1.0.8 até o retorno),
um registro por dia do mês pedido com `year`/`month`/`day` (inteiros
separados — a identificação mais simples e segura possível),
`date` (string confirmada no formato MM/DD/YYYY — ambíguo na
documentação oficial, mas desambiguado aqui por triangulação direta
com `day`) e `epochTime` (inteiro, confirmado sempre à meia-noite
UTC na amostra real). `_validar_e_agregar_dias()` usa year/month/day
como fonte primária de identificação do dia e usa date/epochTime
só como confirmação cruzada — nunca como fonte primária, porque o
formato/fuso desses dois campos não é garantido pela documentação
oficial para todo dataset/geometria, só para a amostra verificada.
"""

import math
import time
import tempfile
import urllib.request
from datetime import date as _date, datetime as _datetime, timezone as _timezone
from pathlib import Path
from calendar import monthrange
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import pandas as pd
import climateserv.api as api

# CHC (UCSB) direto — Preliminary, reservado para o mês mais recente
# quando o Final (ClimateSERV) ainda não publicou (ver
# buscar_prec_chc_preliminar_zonal). Importados só quando essa função
# é chamada, não no topo do módulo — rasterio/rasterstats não são
# necessários no caminho comum (ClimateSERV), só nesse fallback.
CHC_PRELIM_URL = ('https://data.chc.ucsb.edu/products/CHIRPS-2.0/prelim/'
                   'global_monthly/tifs/chirps-v2.0.{ano}.{mes:02d}.tif')

FAZENDAS_LAT = -7.80
FAZENDAS_LON = -47.95

# ClimateSERV é um serviço acadêmico (SERVIR/NASA) e pode ficar fora do
# ar ou demorar — generoso, mas limitado, para não travar o workflow
# indefinidamente se o serviço nunca responder.
TIMEOUT_SEGUNDOS = 600


def _geometria_ponto(lat, lon, delta=0.01):
    """Caixa pequena ao redor do ponto — a API exige um polígono, não
    aceita ponto puro. delta=0.01° (~1km) é bem menor que a resolução
    do CHIRPS (0.05°), então a média do polígono equivale ao valor do
    pixel que contém o ponto."""
    return [[lon-delta, lat+delta], [lon+delta, lat+delta],
            [lon+delta, lat-delta], [lon-delta, lat-delta],
            [lon-delta, lat+delta]]


def _dia_valido_no_calendario(ano, mes, dia):
    """True se `dia` é um dia real de `mes`/`ano` (cobre fev. bissexto
    e não bissexto, e meses de 28-31 dias) — nunca lança exceção."""
    try:
        return 1 <= dia <= monthrange(ano, mes)[1]
    except Exception:
        return False


def _parse_date_mdy(date_str):
    """Interpreta `date` no formato MM/DD/YYYY — confirmado por
    verificação real controlada contra o ClimateSERV (06/2024, mesma
    geometria de produção; ver cabeçalho do módulo). Retorna None se
    não for parseável nesse formato exato ou se os componentes não
    formarem uma data real — nunca lança exceção, nunca tenta outros
    formatos (a amostra real não deixou ambiguidade para este
    dataset/geometria; se outro produto do serviço um dia usar outro
    formato, isso precisa ser verificado de novo, não assumido)."""
    try:
        m, d, y = (int(x) for x in str(date_str).split('/'))
        return _date(y, m, d)
    except (ValueError, TypeError, AttributeError):
        return None


def _parse_epoch_utc_date(epoch_val):
    """Interpreta `epochTime` como segundos UTC desde a época Unix e
    devolve a data (dia calendário) correspondente. Confirmado pela
    mesma verificação real: os 30 registros de 06/2024 caem todos
    exatamente em 00:00:00 UTC. Retorna None se não for interpretável
    — nunca lança exceção."""
    try:
        return _datetime.fromtimestamp(int(epoch_val), tz=_timezone.utc).date()
    except (ValueError, TypeError, OSError, OverflowError):
        return None


def _validar_registro_diario(r):
    """
    Valida UM registro diário bruto do ClimateSERV. Retorna
    (ano, mes, dia, prec) se o registro for aceito, ou
    (None, None, None, motivo) se for rejeitado.

    Identificação do dia: `year`/`month`/`day` (inteiros separados,
    confirmados presentes na amostra real) são a fonte PRIMÁRIA —
    nunca `date` (string, formato só confirmado para esta amostra) nem
    `epochTime` (fuso só confirmado para esta amostra) isoladamente.
    Quando `date`/`epochTime` estão presentes, são usados só como
    CONFIRMAÇÃO cruzada contra year/month/day: uma divergência entre
    eles invalida o registro (nunca escolhe arbitrariamente qual
    campo "está certo").

    Nunca converte ausência em zero: `value.avg` None/ausente é
    rejeitado, nunca torna-se 0.0. Nunca aceita NaN/infinito/negativo
    (precipitação negativa é fisicamente impossível). Zero real
    (`avg == 0.0`, campo presente e válido) é sempre aceito.
    """
    if not isinstance(r, dict):
        return None, None, None, 'registro não é um dict'

    ano, mes, dia = r.get('year'), r.get('month'), r.get('day')
    if not (isinstance(ano, int) and isinstance(mes, int) and isinstance(dia, int)):
        return None, None, None, 'year/month/day ausente(s) ou não inteiro(s)'
    if not (1 <= mes <= 12):
        return None, None, None, f'mês fora do calendário: {mes}'
    if not _dia_valido_no_calendario(ano, mes, dia):
        return None, None, None, f'dia fora do calendário de {mes:02d}/{ano}: {dia}'

    dia_calendario = _date(ano, mes, dia)

    if 'date' in r and r['date'] is not None:
        data_lida = _parse_date_mdy(r['date'])
        if data_lida is None or data_lida != dia_calendario:
            return None, None, None, (
                f"'date' ({r['date']!r}) inconsistente com year/month/day "
                f"({dia_calendario.isoformat()})")

    if 'epochTime' in r and r['epochTime'] is not None:
        data_epoch = _parse_epoch_utc_date(r['epochTime'])
        if data_epoch is None or data_epoch != dia_calendario:
            return None, None, None, (
                f"'epochTime' ({r['epochTime']!r}) inconsistente com year/month/day "
                f"({dia_calendario.isoformat()})")

    valor = r.get('value')
    avg = valor.get('avg') if isinstance(valor, dict) else None
    if avg is None:
        return None, None, None, 'avg ausente/None — sem observação real nesse dia'
    try:
        avg_f = float(avg)
    except (TypeError, ValueError):
        return None, None, None, f'avg não numérico: {avg!r}'
    if not math.isfinite(avg_f):
        return None, None, None, f'avg não finito (NaN/±inf): {avg!r}'
    if avg_f < 0:
        return None, None, None, f'avg negativo (fisicamente inválido): {avg_f}'

    return ano, mes, dia, avg_f


def _meses_da_janela(ano_ini, mes_ini, ano_fim, mes_fim):
    """Lista (ano,mes) de ano_ini/mes_ini até ano_fim/mes_fim, inclusive."""
    meses, y, m = [], ano_ini, mes_ini
    while (y, m) <= (ano_fim, mes_fim):
        meses.append((y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return meses


def _validar_e_agregar_dias(registros, ano_ini, mes_ini, ano_fim, mes_fim, rotulo='CHIRPS'):
    """
    Valida cada registro diário bruto e só aceita um mês (ano,mes) na
    agregação final quando TODOS os dias do calendário desse mês têm
    exatamente um registro válido — nenhum faltando, nenhum
    duplicado, nenhuma inconsistência temporal, nenhum valor
    ausente/inválido. Um mês que falhe qualquer critério fica
    simplesmente FORA do resultado (mesma semântica já documentada
    para "mês ainda não publicado") — nunca entra com um total
    calculado sobre dias insuficientes, nem com registros
    problemáticos descartados em silêncio para depois declarar
    cobertura completa.

    Registro com mês identificável (year/month presentes e válidos,
    mesmo que day/date/epochTime/value tenham o problema) invalida
    SÓ aquele mês.

    Registro SEM identificação temporal confiável (year/month
    ausentes ou não inteiros — não dá para saber a qual mês
    pertenceria) recebe tratamento CONSERVADOR: nunca presumimos que
    ele seja irrelevante só porque não conseguimos lê-lo. Como pode
    pertencer a QUALQUER mês da janela efetivamente solicitada nesta
    chamada (`ano_ini`/`mes_ini` a `ano_fim`/`mes_fim`), todos os
    meses dessa janela são invalidados — não só os que já têm
    registros válidos acumulados. Isso é deliberadamente mais
    cauteloso que invalidar só os meses "vistos": um mês da janela
    que ainda nem tivesse nenhum registro processado também fica de
    fora, porque o registro não identificável poderia ser dele.
    Efeito prático em janelas de vários meses (ex.: os blocos de
    ~10 anos de backfill_chirps_historico.py): um único registro
    corrompido/sem identificação em qualquer ponto da resposta
    invalida a janela PEDIDA inteira nesta chamada — aceito como
    o preço da cautela (nunca aceitar dado que pode estar mal
    atribuído), nunca de volta ao histórico já persistido (esta
    função só decide o que ENTRA no resultado desta chamada).

    Retorna DataFrame [ano, mes, prec] (sem a coluna 'fonte' — quem
    chama decide/sobrescreve, como já fazia antes desta correção).
    """
    por_mes = {}            # (ano,mes) -> {dia: prec_valido}
    meses_invalidados = set()
    descartados_sem_identificacao = 0

    for r in registros:
        ano, mes, dia, avg_ou_motivo = _validar_registro_diario(r)

        if ano is None:
            motivo = avg_ou_motivo
            ano_r = r.get('year') if isinstance(r, dict) else None
            mes_r = r.get('month') if isinstance(r, dict) else None
            if isinstance(ano_r, int) and isinstance(mes_r, int) and 1 <= mes_r <= 12:
                meses_invalidados.add((ano_r, mes_r))
                print(f"  ⚠ CHIRPS ({rotulo}): registro de {mes_r:02d}/{ano_r} "
                      f"rejeitado ({motivo}) — mês invalidado, fallback será tentado")
            else:
                descartados_sem_identificacao += 1
            continue

        chave = (ano, mes)
        dias_do_mes = por_mes.setdefault(chave, {})
        if dia in dias_do_mes:
            meses_invalidados.add(chave)
            print(f"  ⚠ CHIRPS ({rotulo}): dia {dia:02d}/{mes:02d}/{ano} duplicado "
                  f"— mês invalidado, fallback será tentado")
            continue
        dias_do_mes[dia] = avg_ou_motivo

    if descartados_sem_identificacao:
        janela = _meses_da_janela(ano_ini, mes_ini, ano_fim, mes_fim)
        meses_invalidados.update(janela)
        print(f"  ⚠ CHIRPS ({rotulo}): {descartados_sem_identificacao} registro(s) sem "
              f"year/month identificável — não é possível descartá-lo(s) com segurança; "
              f"TODOS os meses da janela solicitada ({mes_ini:02d}/{ano_ini} a "
              f"{mes_fim:02d}/{ano_fim}) ficam indisponíveis nesta fonte, fallback será tentado")

    linhas = []
    for (ano, mes), dias_validos in por_mes.items():
        if (ano, mes) in meses_invalidados:
            continue
        n_dias_mes = monthrange(ano, mes)[1]
        if len(dias_validos) != n_dias_mes:
            print(f"  ⚠ CHIRPS ({rotulo}): {mes:02d}/{ano} com cobertura incompleta "
                  f"({len(dias_validos)}/{n_dias_mes} dias válidos) — mês não aceito, "
                  f"fallback será tentado")
            continue
        linhas.append({'ano': ano, 'mes': mes, 'prec': round(sum(dias_validos.values()), 1)})

    return pd.DataFrame(linhas, columns=['ano', 'mes', 'prec'])


def _buscar_prec_chirps_geom(ini, fim, geom, ano_ini, mes_ini, ano_fim, mes_fim, rotulo='CHIRPS'):
    """
    Núcleo comum: uma chamada ao ClimateSERV para um anel de polígono
    já pronto (`geom`, lista de [lon,lat]), com timeout limitado e
    validação de cobertura temporal diária antes de aceitar qualquer
    mês (ver `_validar_e_agregar_dias`). Usada tanto pelo ponto único
    (buscar_prec_chirps) quanto pela busca por grupo geográfico
    (buscar_prec_chirps_zonal) — não duplicar essa lógica.

    `ano_ini, mes_ini, ano_fim, mes_fim` são os limites da janela
    solicitada nesta chamada (não necessariamente os mesmos de `ini`/
    `fim`, que já vêm formatados como string) — repassados a
    `_validar_e_agregar_dias` para a invalidação conservadora de janela
    inteira quando um registro não tiver year/month identificável.

    Retorna DataFrame [ano, mes, prec, fonte]. Meses sem publicação
    ainda, ou com cobertura diária incompleta/duplicada/inconsistente,
    simplesmente não aparecem no resultado — nunca vêm como zero nem
    como um total calculado sobre dias insuficientes.
    """
    def _chamar():
        return api.request_data(0, 'Average', ini, fim, geom, '', '', 'memory_object')

    vazio = pd.DataFrame(columns=['ano', 'mes', 'prec', 'fonte'])

    # Sem "with": o gerenciador de contexto do ThreadPoolExecutor chama
    # shutdown(wait=True) na saída, que BLOQUEIA até a thread em segundo
    # plano terminar sozinha — mesmo depois de future.result(timeout=…)
    # já ter estourado o timeout. Isso anularia o propósito do timeout
    # (a chamada só "voltaria" quando o serviço travado finalmente
    # respondesse, não em TIMEOUT_SEGUNDOS). shutdown(wait=False) evita
    # isso: a thread órfã termina sozinha em segundo plano, descartada.
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        future = ex.submit(_chamar)
        result = future.result(timeout=TIMEOUT_SEGUNDOS)
    except FutureTimeoutError:
        print(f"  ⚠ CHIRPS ({rotulo}) indisponível: sem resposta em {TIMEOUT_SEGUNDOS}s")
        return vazio
    except Exception as e:
        print(f"  ⚠ CHIRPS ({rotulo}) indisponível: {e}")
        return vazio
    finally:
        ex.shutdown(wait=False, cancel_futures=True)

    if not result or not isinstance(result, dict) or not result.get('data'):
        print(f"  ⚠ CHIRPS ({rotulo}) indisponível: resposta vazia ou sem dados")
        return vazio

    # Resposta malformada de um jeito que a validação não previu (ex.:
    # result['data'] não é uma lista) não pode derrubar o pipeline
    # inteiro — vira fallback, como qualquer outra falha do CHIRPS.
    try:
        mensal = _validar_e_agregar_dias(result['data'], ano_ini, mes_ini, ano_fim, mes_fim, rotulo=rotulo)
        mensal['fonte'] = 'CHIRPS'
        return mensal
    except Exception as e:
        print(f"  ⚠ CHIRPS ({rotulo}) indisponível: resposta malformada ({e})")
        return vazio


def buscar_prec_chirps(ano_ini, mes_ini, ano_fim, mes_fim):
    """
    Precipitação mensal via CHIRPS (dataset 0 do ClimateSERV) para o
    intervalo inteiro, numa única chamada, usando uma caixa pequena ao
    redor do ponto centroide das fazendas (não o envelope das fazendas —
    para isso, ver buscar_prec_chirps_zonal). Pedidos muito longos (~45
    anos) falham no lado do servidor — para históricos grandes, quebre
    em blocos de poucos anos (ver backfill_chirps_historico.py).

    Retorna DataFrame [ano, mes, prec, fonte].
    """
    ultimo_dia = monthrange(ano_fim, mes_fim)[1]
    ini = f'{mes_ini:02d}/01/{ano_ini}'
    fim = f'{mes_fim:02d}/{ultimo_dia:02d}/{ano_fim}'
    geom = _geometria_ponto(FAZENDAS_LAT, FAZENDAS_LON)
    return _buscar_prec_chirps_geom(ini, fim, geom, ano_ini, mes_ini, ano_fim, mes_fim, rotulo='ponto único')


def buscar_prec_chirps_zonal(ano_ini, mes_ini, ano_fim, mes_fim):
    """
    Precipitação mensal via CHIRPS, com o polígono do envelope das
    fazendas (data/fazendas.geojson, Fazendas_v2.kmz — sem identificação
    individual) em vez do ponto único — ver CLAUDE.md, armadilha 8, e
    _farm_geometry.py.

    Uma geometria única, uma chamada ao ClimateSERV (antes eram 7,
    quando o geojson tinha as 37 fazendas em 7 grupos desconectados —
    a fragilidade de "sucesso parcial por grupo" não existe mais).

    Retorna DataFrame [ano, mes, prec, fonte='CHIRPS-zonal'] — vazio se
    a chamada falhar (rede, timeout, resposta malformada); nunca grava
    zero.
    """
    from _farm_geometry import anel_simplificado

    ultimo_dia = monthrange(ano_fim, mes_fim)[1]
    ini = f'{mes_ini:02d}/01/{ano_ini}'
    fim = f'{mes_fim:02d}/{ultimo_dia:02d}/{ano_fim}'

    anel, erro_pct = anel_simplificado()
    if erro_pct:
        print(f"  ℹ CHIRPS zonal: anel simplificado, erro de área {erro_pct:.2f}%")

    resultado = _buscar_prec_chirps_geom(ini, fim, anel, ano_ini, mes_ini, ano_fim, mes_fim, rotulo='envelope fazendas')
    if not resultado.empty:
        resultado['fonte'] = 'CHIRPS-zonal'
    return resultado


def buscar_prec_chc_preliminar_zonal(ano, mes, timeout_segundos=120):
    """
    Precipitação de UM mês via CHIRPS Preliminary — download direto do
    CHC (data.chc.ucsb.edu), zonal stats via rasterio/rasterstats sobre
    o polígono do envelope das fazendas (data/fazendas.geojson, sem
    simplificar — sem a limitação de anel único do ClimateSERV, aqui é
    processamento local, não uma URL).

    Reservado para o mês mais recente quando o CHIRPS Final (via
    buscar_prec_chirps/buscar_prec_chirps_zonal) ainda não publicou —
    o Preliminary sai antes, mas sem a consolidação/correção final.
    NÃO é substituto do Final para meses já consolidados: só usar aqui
    quando o Final genuinamente não tiver o mês ainda.

    Retorna dict {'ano', 'mes', 'prec', 'fonte': 'CHIRPS-prelim-zonal'}
    ou None se o arquivo não existir ainda (mês não publicado, mesmo no
    Preliminary) ou o download/processamento falhar — nunca inventa
    zero.
    """
    from _farm_geometry import poligono
    from shapely.geometry import mapping

    url = CHC_PRELIM_URL.format(ano=ano, mes=mes)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as tmp:
            tmp_path = Path(tmp.name)
            req = urllib.request.Request(url, headers={'User-Agent': 'sinobras-clima/1.0'})
            with urllib.request.urlopen(req, timeout=timeout_segundos) as r:
                tmp.write(r.read())

        import rasterio  # noqa: F401 (só pra falhar cedo e claro se faltar a dependência)
        from rasterstats import zonal_stats

        stats = zonal_stats(mapping(poligono()), str(tmp_path), stats=['mean', 'count'], nodata=-9999)

        if not stats or stats[0]['mean'] is None or stats[0]['count'] == 0:
            print(f"  ⚠ CHC Preliminary {mes:02d}/{ano}: zonal stats sem pixels válidos")
            return None

        return {
            'ano': ano, 'mes': mes,
            'prec': round(stats[0]['mean'], 1),
            'fonte': 'CHIRPS-prelim-zonal',
        }
    except Exception as e:
        print(f"  ⚠ CHC Preliminary {mes:02d}/{ano} indisponível: {e}")
        return None
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
