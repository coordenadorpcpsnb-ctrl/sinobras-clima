#!/usr/bin/env python3
"""
c3s_multimodel_catalogo.py — Fase 2B.1: catálogo auditável dos sistemas
sazonais C3S candidatos à comparação multi-modelo, e cálculo do período
comum de hindcast entre eles.

PRINCÍPIO CIENTÍFICO (Seção 1 da tarefa): nesta fase os sistemas
candidatos são definidos por disponibilidade oficial/hindcast/leads/
cobertura — NUNCA por skill local observado. Nenhum tuning aqui.

COMO ESTA TABELA FOI MONTADA — mesma limitação de rede já documentada
em c3s_catalogo.py (Fase 2A): cds.climate.copernicus.eu e ecmwf.int
continuam bloqueados para WebFetch direto nesta sessão (confirmado de
novo nesta tarefa). Diferente da Fase 2A, desta vez WebSearch e WebFetch
para domínios NÃO bloqueados (psl.noaa.gov, confluence.ecmwf.int via
busca, iridl.ldeo.columbia.edu, cmcc.it, dwd.de, umr-cnrm.fr/zenodo)
trouxeram specs cross-confirmadas por 2+ fontes independentes para os 4
sistemas abaixo — por isso todos os 4 candidatos da Seção 2 entram como
`verificado_cruzado=True`, ao contrário da Fase 2A (onde só SEAS5 tinha
essa confirmação). Fontes registradas em cada entrada.

DECISÃO DE VERSÃO — para METFR/DWD/CMCC o sistema "atual" no catálogo
CDS (System9/GCFS2.2/SPS4, respectivamente) é recente demais para ter
specs cross-confirmadas nesta sessão (CMCC confirma isso explicitamente:
"SPS4 was added in August 2026... decisions... still pending"). Optamos
pela versão ANTERIOR de cada um (System8/GCFS2.1/SPS3.5), que tem
hindcast fixo, membros e leads documentados por fonte oficial do próprio
centro — critério da Seção 1 (disponibilidade/documentação), nunca
skill. As versões "atuais" ficam registradas em NAO_INCLUIDOS_VERSAO
para reavaliação futura, quando a infraestrutura multi-modelo permitir
confirmar suas specs (ex.: request mínimo real ao CDS, Seção 13).

PERÍODO DE HINDCAST — os quatro candidatos usam aqui o período de
REFERÊNCIA COMUM do produto multi-sistema C3S, 1993-2016 (confirmado por
2 fontes independentes: a descrição geral do C3S — "for products issued
from November 2018, the reference (hindcast) period for all providers
is 1993-2016" — e a tabela de sistemas do NOAA PSL, que lista esse
mesmo intervalo para todos os provedores). Isso é DISTINTO do hindcast
NATIVO de cada sistema, que pode ser mais longo (e no caso do SEAS5, o
hindcast nativo 1981-2016 é o mesmo já usado e validado na Fase 2A/2A.3
— ver `notas` de cada entrada). `periodo_comum_hindcast()` calcula a
interseção A PARTIR desses campos, nunca hardcoded — para esta
configuração ela deve bater com 1993-2016, mas a função sempre recalcula.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class SistemaMultiModelo:
    centro: str                        # rótulo legível (ex.: 'METEO_FRANCE')
    originating_centre_cds: str        # valor EXATO esperado pelo campo 'originating_centre' da API CDS
    system_name: str
    system_code: str                   # valor do campo 'system' da API CDS
    model_id: Optional[str]
    hindcast_start: Optional[int]
    hindcast_end: Optional[int]
    hindcast_members: Optional[int]
    forecast_members: Optional[int]
    leads_disponiveis: tuple
    resolucao: Optional[str]
    hindcast_production: str           # 'fixed' ou 'on_the_fly'
    verificado_cruzado: bool           # True só se >=2 fontes independentes concordam
    fontes: tuple = field(default_factory=tuple)
    notas: str = ''


CATALOGO = [
    SistemaMultiModelo(
        centro='ECMWF', originating_centre_cds='ecmwf', system_name='SEAS5', system_code='51',
        model_id=None,
        hindcast_start=1993, hindcast_end=2016,
        hindcast_members=25, forecast_members=51,
        leads_disponiveis=(1, 2, 3, 4, 5, 6),
        resolucao='1°x1° (grade CDS; nativo TCo319 ~36km)',
        hindcast_production='fixed',
        verificado_cruzado=True,
        fontes=(
            'c3s_catalogo.py (Fase 2A) — já cross-confirmado por NOAA PSL + MDPI Climate 10(9):128 + '
            'ECMWF forum',
            'psl.noaa.gov/forecasts/s2s_C3S_monthly_to_seasonal/description/ (WebFetch nesta sessão: '
            'hindcast period 1993-2016 "for products issued from November 2018... for all providers")',
        ),
        notas='Mesmo sistema já validado ponta a ponta na Fase 2A.3 (432 origens oficiais, run '
              '35353196015). O hindcast NATIVO usado lá foi 1981-2016 (25 membros) — mais longo que o '
              'período comum 1993-2016 usado aqui para a comparação multi-modelo. Para a Fase 2B.1, '
              'restringir ECMWF ao período comum é uma escolha de protocolo (comparabilidade entre '
              'sistemas), não uma limitação do sistema em si.',
    ),
    SistemaMultiModelo(
        centro='METEO_FRANCE', originating_centre_cds='meteo_france', system_name='System8', system_code='8',
        model_id='CNRM-CM6',
        hindcast_start=1993, hindcast_end=2016,
        hindcast_members=25, forecast_members=51,
        leads_disponiveis=(1, 2, 3, 4, 5, 6),
        resolucao='1°x1° (grade CDS; 360x180 pontos)',
        hindcast_production='fixed',
        verificado_cruzado=True,
        fontes=(
            'umr-cnrm.fr/old/IMG/pdf/c3s2_d370.1.4.1_documentation_of_the_meteo-france_seasonal_'
            'forecasting_system_9_v1.pdf (via WebSearch: "System 8... reforecasts feature 25 members... '
            'real-time forecasts 51 members", "System 8 covers 1993-2018")',
            'iridl.ldeo.columbia.edu/SOURCES/.EU/.Copernicus/.CDS/.C3S/.Meteo_France/.System8 (via '
            'WebFetch: lead 0.5-5.5 meses por 1.0 mês = 6 leads, grade 1° 360x180, forecast 51 '
            'membros, hindcast 25 membros)',
        ),
        notas='`system_code` = "8" inferido pela convenção de versionamento inteiro da Météo-France '
              '(System 7/8/9, sem subversão decimal como ECMWF/CMCC/DWD) — não confirmado como valor '
              'literal do parâmetro `system` da API por uma request real (Seção 13, fora do escopo '
              'desta tarefa). `originating_centre_cds`="meteo_france" (snake_case) inferido do caminho '
              'do mirror IRI/LDEO (".Meteo_France."). Hindcast nativo documentado 1993-2018 (mais longo '
              'que o período comum 1993-2016 usado aqui). System9 (atual) tem reforecast 1993-2024 mas '
              'não foi incluído nesta fase — ver NAO_INCLUIDOS_VERSAO.',
    ),
    SistemaMultiModelo(
        centro='DWD', originating_centre_cds='dwd', system_name='GCFS2.1', system_code='21',
        model_id='MPI-ESM-HR',
        hindcast_start=1993, hindcast_end=2016,
        hindcast_members=30, forecast_members=50,
        leads_disponiveis=(1, 2, 3, 4, 5, 6),
        resolucao=None,
        hindcast_production='fixed',
        verificado_cruzado=True,
        fontes=(
            'confluence.ecmwf.int "Description of GCFS2.1-v20200320 C3S contribution" (via WebSearch: '
            '"DWD contribution to the new operational forecasting system GCFS2.1 has system=21")',
            'dwd.de/EN/ourservices/seasonals_forecasts/download/gcfs_2_1.pdf (via WebSearch: hindcast '
            'de 30 membros, "1982-2019 para fev/mai/ago/nov, 1990-2019 para os demais meses de '
            'inicialização", forecast 50 membros, "6-month lead time")',
            'psl.noaa.gov/forecasts/s2s_C3S_monthly_to_seasonal/description/ (hindcast period '
            '1993-2016 "for all providers")',
        ),
        notas='RISCO EXPLÍCITO (relevante para a Seção 16/27-D): o hindcast NATIVO documentado pela '
              'própria DWD tem cobertura DIFERENTE por mês de inicialização (1982-2019 para fev/mai/'
              'ago/nov; 1990-2019 para os demais) — não confirmado se essa assimetria também se aplica '
              'ao subconjunto 1993-2016 servido via CDS (o período comum usado aqui, 1993-2016, está '
              'contido nos dois casos, então a interseção continua segura). Resolução não confirmada '
              'nesta sessão — campo None em vez de inventado. GCFS2.2 (system=22, atual) não foi '
              'incluído nesta fase — ver NAO_INCLUIDOS_VERSAO.',
    ),
    SistemaMultiModelo(
        centro='CMCC', originating_centre_cds='cmcc', system_name='SPS3.5', system_code='35',
        model_id=None,
        hindcast_start=1993, hindcast_end=2016,
        hindcast_members=40, forecast_members=50,
        leads_disponiveis=(1, 2, 3, 4, 5, 6),
        resolucao=None,
        hindcast_production='fixed',
        verificado_cruzado=True,
        fontes=(
            'cmcc.it TN0288 "The new CMCC Operational Seasonal Prediction System" (via WebSearch: '
            '"hindcast ensemble size of 40 members... 1/1993-12/2016", forecast 50 membros)',
            'psl.noaa.gov/forecasts/s2s_C3S_monthly_to_seasonal/description/ (via WebSearch: "CMCC '
            'SPSv3.5 is referenced as System 35... lead time months 1 to 6")',
        ),
        notas='SPS4 (atual no catálogo CDS, adicionado ago/2026 segundo a busca) está explicitamente '
              'documentado como "decisions... still pending, details to be communicated" — não incluído '
              'nesta fase por falta de specs confirmáveis, não por rejeição científica. Ver '
              'NAO_INCLUIDOS_VERSAO. model_id e resolução não confirmados nesta sessão — None em vez '
              'de inventados.',
    ),
]

SISTEMAS_CANDIDATOS_FASE2B1 = [(s.centro, s.system_name) for s in CATALOGO]

# Seção 3 — versões "atuais" do catálogo CDS que existem mas não têm
# specs cross-confirmadas nesta sessão; substituídas pela versão
# anterior documentada (ver `notas` de cada entrada acima). Não é
# rejeição científica, é controle de escopo (mesmo espírito da Seção 3
# para UKMO/NCEP/ECCC/BOM/JMA).
NAO_INCLUIDOS_VERSAO = {
    ('METEO_FRANCE', 'System9'): 'system_code=9 — specs de hindcast (1993-2024) encontradas, mas não '
                                  'cross-confirmadas para membros/leads/resolução nesta sessão; System8 '
                                  '(incluído) já tem tudo documentado e cobre o período comum.',
    ('DWD', 'GCFS2.2'): 'system_code=22 — introduzido em 2025/2026 segundo a busca, specs de membros/'
                         'leads/resolução não cross-confirmadas nesta sessão; GCFS2.1 (incluído) cobre '
                         'o período comum com specs documentadas pela própria DWD.',
    ('CMCC', 'SPS4'): 'system_code não determinado — fonte oficial (CMCC) diz explicitamente que as '
                       'decisões sobre o SPS4 ainda estão pendentes; SPS3.5 (incluído) tem hindcast, '
                       'membros e leads documentados pela própria CMCC (TN0288).',
}

# Seção 3 — fora de escopo NESTA fase (controle de escopo, não rejeição
# científica). UKMO tem motivo técnico específico (hindcast on-the-fly/
# lagged); os demais são apenas adiados.
SISTEMAS_EXCLUIDOS_FASE2B1 = {
    'UKMO': 'Hindcasts com esquema operacional/on-the-fly e inicializações particulares (lagged '
            'ensemble) — incompatível com o protocolo "hindcast fixo" reutilizado da Fase 2A.3 sem '
            'adaptação adicional. Será avaliado depois que a infraestrutura multi-modelo fixa estiver '
            'validada (Seção 3).',
    'NCEP': 'Fora de escopo da Fase 2B.1 por controle de escopo — não avaliado nesta tarefa.',
    'ECCC': 'Fora de escopo da Fase 2B.1 por controle de escopo — não avaliado nesta tarefa.',
    'BOM': 'Fora de escopo da Fase 2B.1 por controle de escopo — não avaliado nesta tarefa.',
    'JMA': 'Fora de escopo da Fase 2B.1 por controle de escopo — não avaliado nesta tarefa (nem sequer '
           'listado como candidato inicial pela Seção 2).',
}


def sistema_por_nome(centro, system_name):
    for s in CATALOGO:
        if s.centro == centro and s.system_name == system_name:
            return s
    raise KeyError(f"sistema não encontrado no catálogo multi-modelo: {centro}/{system_name}")


def periodo_comum_hindcast(sistemas):
    """Deriva o período comum de hindcast entre os sistemas dados —
    NUNCA hardcoded (Seção 4). Devolve dict com common_start/common_end
    (None se não houver interseção viável) e anos_disponiveis_por_modelo
    (para auditoria). Qualquer sistema com hindcast_start/end ausente
    (None) é reportado em `incompatibilidade`, nunca silenciosamente
    ignorado no cálculo."""
    anos_por_modelo = {}
    incompatibilidade = {}
    inicios, fins = [], []
    for s in sistemas:
        chave = f'{s.centro}/{s.system_name}'
        if s.hindcast_start is None or s.hindcast_end is None:
            incompatibilidade[chave] = 'hindcast_start/hindcast_end ausente no catálogo'
            continue
        if s.hindcast_start > s.hindcast_end:
            incompatibilidade[chave] = f'hindcast_start ({s.hindcast_start}) > hindcast_end ({s.hindcast_end})'
            continue
        anos_por_modelo[chave] = [s.hindcast_start, s.hindcast_end]
        inicios.append(s.hindcast_start)
        fins.append(s.hindcast_end)

    if not inicios:
        return {'common_start': None, 'common_end': None, 'anos_disponiveis_por_modelo': anos_por_modelo,
                'incompatibilidade': incompatibilidade}

    common_start, common_end = max(inicios), min(fins)
    if common_start > common_end:
        incompatibilidade['interseccao'] = (
            f'sem sobreposição real: common_start ({common_start}) > common_end ({common_end})')
        return {'common_start': None, 'common_end': None, 'anos_disponiveis_por_modelo': anos_por_modelo,
                'incompatibilidade': incompatibilidade}

    return {'common_start': common_start, 'common_end': common_end,
            'anos_disponiveis_por_modelo': anos_por_modelo, 'incompatibilidade': incompatibilidade}


def tabela_catalogo(sistemas=None, incluidos=None):
    """DataFrame com as colunas mínimas pedidas (Seção 12) para
    `c3s_multimodel_catalog.csv`. `incluidos`: coleção de (centro,
    system_name) considerados incluídos no POC — default: todo
    CATALOGO."""
    import pandas as pd
    sistemas = sistemas if sistemas is not None else CATALOGO
    incluidos = set(incluidos) if incluidos is not None else set(SISTEMAS_CANDIDATOS_FASE2B1)
    linhas = []
    for s in sistemas:
        compatible_leads_1_6 = tuple(s.leads_disponiveis) == (1, 2, 3, 4, 5, 6)
        linhas.append({
            'centre': s.centro, 'system_name': s.system_name, 'system_code': s.system_code,
            'model_id': s.model_id, 'hindcast_start': s.hindcast_start, 'hindcast_end': s.hindcast_end,
            'hindcast_members': s.hindcast_members, 'max_lead': max(s.leads_disponiveis) if s.leads_disponiveis
            else None,
            'forecast_type': 'ensemble', 'hindcast_production': s.hindcast_production,
            'compatible_precip_monthly': True,   # os 4 candidatos servem o dataset monthly-single-levels
            'compatible_leads_1_6': compatible_leads_1_6,
            'included_phase2b1': (s.centro, s.system_name) in incluidos,
            'notes': s.notas,
        })
    return pd.DataFrame(linhas)


def common_period_json(sistemas=None):
    """dict pronto para `c3s_multimodel_common_period.json` (Seção 12)."""
    sistemas = sistemas if sistemas is not None else CATALOGO
    resultado = periodo_comum_hindcast(sistemas)
    return {
        'candidate_models': [f'{c}/{n}' for c, n in SISTEMAS_CANDIDATOS_FASE2B1],
        'included_models': [f'{s.centro}/{s.system_name}' for s in sistemas],
        'excluded_models': {**{k: v for k, v in SISTEMAS_EXCLUIDOS_FASE2B1.items()},
                             **{f'{c}/{n}': v for (c, n), v in NAO_INCLUIDOS_VERSAO.items()}},
        'common_start': resultado['common_start'], 'common_end': resultado['common_end'],
        'anos_disponiveis_por_modelo': resultado['anos_disponiveis_por_modelo'],
        'reasoning': (
            'Sistemas candidatos definidos por disponibilidade/documentação/cobertura de leads '
            '1-6 (Seção 1), nunca por skill local. Período comum é a interseção de hindcast_start/'
            'hindcast_end de cada sistema incluído — calculada, não fixada manualmente. UKMO excluído '
            'por esquema de hindcast on-the-fly/lagged; NCEP/ECCC/BOM/JMA fora de escopo desta fase; '
            'versões "atuais" de METFR/DWD/CMCC (System9/GCFS2.2/SPS4) substituídas por versões '
            'anteriores com specs cross-confirmadas (ver NAO_INCLUIDOS_VERSAO).'
        ),
    }


if __name__ == '__main__':
    import pandas as pd
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 200)
    print(tabela_catalogo().to_string(index=False))
    print()
    resultado = periodo_comum_hindcast(CATALOGO)
    print(f"Período comum de hindcast: {resultado['common_start']}-{resultado['common_end']}")
    if resultado['incompatibilidade']:
        print(f"Incompatibilidades: {resultado['incompatibilidade']}")
