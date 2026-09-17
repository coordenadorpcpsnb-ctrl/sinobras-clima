#!/usr/bin/env python3
"""
_c3s_utils.py — utilidades puras compartilhadas por c3s_download.py,
c3s_processar.py e c3s_hindcast.py (Fase 2A).

Reúne aqui só o que é genuinamente comum aos três módulos — alinhamento
temporal init/lead/target (a armadilha central desta fase, ver
LEADTIME_MONTH_1_E_O_MES_DE_INICIALIZACAO) e conversão de unidade de
precipitação. Nada de lógica de download, de parsing de GRIB nem de
métricas aqui — isso fica nos módulos específicos.

MUNICÍPIOS (Seção 2 da tarefa): coordenadas públicas da SEDE municipal,
não das fazendas Sinobras. Fontes documentadas por município — algumas
com pequena divergência entre a infobox do Wikipédia e a coordenada
publicada pela própria prefeitura; nesses casos usei a fonte mais
específica/oficial (prefeitura > Wikipédia) e registrei a alternativa.
Nenhuma geometria privada de fazenda é usada nesta fase.
"""

from calendar import monthrange

import pandas as pd

# ══════════════════════════════════════════════════════════════════════════
# Municípios (Seção 2) — ponto único na sede, delta da caixa documentado
# junto (mesma lógica de _chirps.py::_geometria_ponto: caixa pequena ao
# redor do ponto, bem menor que a resolução das fontes envolvidas).
# ══════════════════════════════════════════════════════════════════════════
MUNICIPIOS = {
    'Sao_Bento_do_Tocantins': {
        'nome_exibicao': 'São Bento do Tocantins', 'uf': 'TO',
        'lat': -6.0203, 'lon': -47.9022,
        'fonte': "Prefeitura de São Bento do Tocantins (saobentodotocantins.to.gov.br) — "
                 "06°01'13\"S 47°54'08\"W, altitude 230m. "
                 "Wikipédia (infobox) traz um valor mais arredondado e um pouco distinto — "
                 "5°52'S 47°50'W (-5.867,-47.833) — mantido aqui só como referência alternativa, "
                 "não usado.",
    },
    'Araguatins': {
        'nome_exibicao': 'Araguatins', 'uf': 'TO',
        'lat': -5.6508, 'lon': -48.1239,
        'fonte': "Wikipédia (infobox do município) — 5°39'03\"S 48°07'26\"W.",
    },
    'Ananas': {
        'nome_exibicao': 'Ananás', 'uf': 'TO',
        'lat': -6.3628, 'lon': -48.0797,
        'fonte': "Wikipédia (infobox do município, pt.wikipedia.org/wiki/Ananás_(Tocantins)) — "
                 "6°21'46\"S 48°04'47\"W.",
    },
}

# Caixa ao redor do ponto para extração de grade C3S (1°x1°, bem mais
# grosseira que CHIRPS 0.05°) — um delta pequeno (~0.05°) já garante que
# pegamos só a célula de grade que contém o ponto; não faz média espacial
# nesta fase (Seção 2 permite isso só "posteriormente").
DELTA_CAIXA_GRAU = 0.05


# ══════════════════════════════════════════════════════════════════════════
# ALINHAMENTO TEMPORAL (Seção 6) — a armadilha central desta fase.
#
# Confirmado via documentação pública (ECMWF forum "Definition of lead
# time and monthly averaged" + NOAA PSL, setembro/2026 — ver resposta
# final para os links): para o dataset "seasonal-monthly-single-levels",
# leadtime_month usa a MESMA convenção do "forecastMonth" do GRIB:
#
#   "Hindcasts initialized on the 1st of the month 'M' with
#    leadtime_month=1 is month 'M'."
#
# Ou seja: leadtime_month=1 é o PRÓPRIO mês de inicialização, não o mês
# seguinte — contra-intuitivo (muita gente assume lead=1 => 1 mês à
# frente). leadtime_month não existe com valor 0.
#
# target_month(init, lead) = init + (lead - 1)
# ══════════════════════════════════════════════════════════════════════════
LEADTIME_MONTH_1_E_O_MES_DE_INICIALIZACAO = True   # documenta a convenção; ver testes


def leadtime_para_mes_alvo(init_date, leadtime_month):
    """init_date: pandas.Period (freq='M'), sempre dia 1 do mês por
    convenção C3S. leadtime_month: inteiro >= 1.
    Devolve o pandas.Period do mês-alvo."""
    if leadtime_month < 1:
        raise ValueError(f"leadtime_month deve ser >= 1 (não existe leadtime 0); recebido {leadtime_month}")
    init_date = pd.Period(init_date, freq='M')
    return init_date + (leadtime_month - 1)


def mes_alvo_para_leadtime(init_date, mes_alvo):
    """Inverso de leadtime_para_mes_alvo — útil para validar/testar."""
    init_date = pd.Period(init_date, freq='M')
    mes_alvo = pd.Period(mes_alvo, freq='M')
    return int((mes_alvo - init_date).n) + 1


# ══════════════════════════════════════════════════════════════════════════
# CONVERSÃO DE UNIDADE (Seção 19, teste 1) — tprate vem em m/s (taxa
# média do período, não total acumulado). Documentado publicamente:
# "Mean total precipitation rate" (tprate), units m s**-1.
# mm_no_mes = tprate_m_s * segundos_no_mes * 1000
# segundos_no_mes MUDA por mês (28-31 dias) — nunca usar uma constante
# fixa (a armadilha específica que o teste 1 cobre).
# ══════════════════════════════════════════════════════════════════════════

def segundos_no_mes(ano, mes):
    dias = monthrange(int(ano), int(mes))[1]
    return dias * 86400


def tprate_para_mm(tprate_m_s, ano, mes):
    """tprate_m_s pode ser escalar ou array numpy — funciona nos dois casos."""
    return tprate_m_s * segundos_no_mes(ano, mes) * 1000.0


# ══════════════════════════════════════════════════════════════════════════
# INTERVALO MENSAL PARA O CLIMATESERV (bug real desta sessão) — os dois
# consumidores C3S (c3s_poc.py, c3s_observado_chirps.py) construíam o fim
# do intervalo como o DIA 1 do último mês (`{mes_fim}/01/{ano_fim}`), não
# o último dia real. _buscar_prec_chirps_geom soma por ano/mês o que a
# API devolve dentro do intervalo pedido — com fim=dia 1, o último mês do
# intervalo fica cortado (só o dia 1), então o agregado mensal desse mês
# vem drasticamente subestimado (ex.: 8,6mm em vez de ~200mm em março).
#
# _chirps.py::buscar_prec_chirps (produção) já faz isso certo via
# monthrange — replicado aqui como função pura para os dois consumidores
# C3S, sem tocar em _chirps.py (Seção 4 da correção: função de produção
# intocada) nem duplicar a regra em dois lugares (armadilha 2 do
# CLAUDE.md: duas implementações divergentes do "mesmo" corte de data já
# causaram bug real antes).
# ══════════════════════════════════════════════════════════════════════════

def intervalo_mensal_chirps(ano_ini, mes_ini, ano_fim, mes_fim):
    """Devolve (ini, fim) no formato MM/DD/AAAA que _buscar_prec_chirps_geom
    espera — do dia 1 do mês inicial até o ÚLTIMO DIA REAL do mês final
    (via monthrange, nunca hardcoded — cobre fevereiro comum/bissexto e
    meses de 30/31 dias corretamente)."""
    ano_ini, mes_ini, ano_fim, mes_fim = int(ano_ini), int(mes_ini), int(ano_fim), int(mes_fim)
    ultimo_dia = monthrange(ano_fim, mes_fim)[1]
    ini = f'{mes_ini:02d}/01/{ano_ini}'
    fim = f'{mes_fim:02d}/{ultimo_dia:02d}/{ano_fim}'
    return ini, fim
