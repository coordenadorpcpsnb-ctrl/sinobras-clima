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

PERÍODO DE HINDCAST — dois conceitos DISTINTOS, nunca confundidos
(correção de auditabilidade pós-revisão externa):

  - `native_hindcast_start`/`native_hindcast_end` — o período de
    reforecast documentado pela FONTE OFICIAL do próprio centro (pode
    ser mais longo que o período usado na comparação — ex.: SEAS5 tem
    hindcast nativo 1981-2016, o mesmo já usado e validado na Fase
    2A/2A.3). `None` quando a fonte disponível não permite atribuir um
    período nativo único com confiança (nunca inventado — ver `notas`
    de cada entrada, ex.: DWD GCFS2.1 tem cobertura nativa ASSIMÉTRICA
    por mês de inicialização, então um único par de anos seria enganoso).
  - `evaluation_hindcast_start`/`evaluation_hindcast_end` — o período
    RETROSPECTIVO COMUM servido/usado pelo produto C3S multi-sistema
    para comparação homogênea entre os 4 candidatos desta fase. Para
    os 4, esse período é 1993-2016 (confirmado por 2 fontes
    independentes: a descrição geral do C3S — "for products issued
    from November 2018, the reference (hindcast) period for all
    providers is 1993-2016" — e a tabela de sistemas do NOAA PSL, que
    lista esse mesmo intervalo para todos os provedores).

`periodo_comum_hindcast()` calcula a interseção a partir dos campos
`evaluation_hindcast_start/end` (nunca dos nativos, e nunca hardcoded)
— para esta configuração ela deve bater com 1993-2016, mas a função
sempre recalcula.
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
    native_hindcast_start: Optional[int]      # período de reforecast NATIVO documentado pela fonte oficial
    native_hindcast_end: Optional[int]
    evaluation_hindcast_start: Optional[int]  # período retrospectivo COMUM usado na comparação multi-sistema
    evaluation_hindcast_end: Optional[int]
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
        native_hindcast_start=1981, native_hindcast_end=2016,
        evaluation_hindcast_start=1993, evaluation_hindcast_end=2016,
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
              '35353196015), que usou o hindcast NATIVO completo, 1981-2016 (25 membros). Para a '
              'comparação multi-modelo desta fase, ECMWF é restrito ao período de avaliação comum '
              '1993-2016 — escolha de protocolo (comparabilidade entre sistemas), não uma limitação '
              'do sistema em si.',
    ),
    SistemaMultiModelo(
        centro='METEO_FRANCE', originating_centre_cds='meteo_france', system_name='System8', system_code='8',
        model_id='CNRM-CM6',
        native_hindcast_start=1993, native_hindcast_end=2018,
        evaluation_hindcast_start=1993, evaluation_hindcast_end=2016,
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
            'ECMWF Confluence Knowledge Base — "Description of the C3S seasonal multi-system" '
            '(confluence.ecmwf.int/spaces/CKB/pages/77213502/Description+of+the+C3S+seasonal+multi-'
            'system, ou a página atual equivalente) — fonte oficial apontada pela revisão externa '
            'desta tarefa como confirmando `system=8` para o Météo-France System 8 no CDS. '
            'WebFetch direto a essa URL nesta sessão continua bloqueado ("EGRESS_BLOCKED", testado de '
            'novo agora); WebSearch confirma que a página existe com esse título exato e que '
            '"Description of System8-v20210101 C3S contribution" é uma página irmã dedicada — mas não '
            'reproduziu o texto literal da tabela de códigos. Registrada como fonte oficial informada, '
            'com essa ressalva de verificação explícita — não tratada como confirmação de primeira mão '
            'desta sessão.',
        ),
        notas='`system_code`="8" — a revisão externa desta tarefa confirmou, na documentação oficial '
              'C3S "Description of the C3S seasonal multi-system" (ver terceira fonte acima), que esse '
              'é o código oficial do Météo-France System 8 no CDS; deixou de ser tratado como inferência '
              'pela convenção de versionamento da Météo-France (ver ressalva de verificação na fonte '
              'acima — WebFetch direto à página segue bloqueado nesta sessão). '
              '`originating_centre_cds`="meteo_france" (snake_case) segue o caminho do mirror IRI/LDEO '
              '(".Meteo_France."). Hindcast NATIVO documentado 1993-2018 — mais longo que o período de '
              'avaliação comum 1993-2016 usado na comparação multi-modelo desta fase. Nº de membros do '
              'hindcast (25) mantido sem alteração: segue suportado pelas duas fontes já coletadas '
              '(CNRM/umr-cnrm.fr e IRI/LDEO), não por uma tabela genérica de outro sistema/versionamento. '
              'System9 (atual) tem reforecast 1993-2024 mas não foi incluído nesta fase — ver '
              'NAO_INCLUIDOS_VERSAO.',
    ),
    SistemaMultiModelo(
        centro='DWD', originating_centre_cds='dwd', system_name='GCFS2.1', system_code='21',
        model_id='MPI-ESM-HR',
        native_hindcast_start=None, native_hindcast_end=None,
        evaluation_hindcast_start=1993, evaluation_hindcast_end=2016,
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
        notas='`native_hindcast_start/end` deixados EXPLICITAMENTE None (nunca inventado, Seção 2 da '
              'correção de auditabilidade): a própria DWD documenta cobertura nativa DIFERENTE por mês '
              'de inicialização (1982-2019 para fev/mai/ago/nov; 1990-2019 para os demais) — um único '
              'par de anos resumiria mal essa assimetria. Os dois intervalos nativos contêm o período '
              'de avaliação comum 1993-2016 usado aqui, então a interseção da comparação multi-modelo '
              'continua segura independente da assimetria. Não confirmado se essa assimetria também se '
              'aplica ao subconjunto 1993-2016 servido via CDS para o produto multi-sistema (relevante '
              'para a Seção 16/27-D de validações futuras). Resolução não confirmada nesta sessão — '
              'campo None em vez de inventado. GCFS2.2 (system=22, atual) não foi incluído nesta fase '
              '— ver NAO_INCLUIDOS_VERSAO.',
    ),
    SistemaMultiModelo(
        centro='CMCC', originating_centre_cds='cmcc', system_name='SPS3.5', system_code='35',
        model_id=None,
        # Fonte oficial CMCC (TN0288) documenta o hindcast NATIVO como o próprio intervalo
        # 1/1993-12/2016 — aqui, ao contrário do SEAS5/System8, native == evaluation porque
        # a CMCC nunca publicou um reforecast mais longo que esse para o SPS3.5.
        native_hindcast_start=1993, native_hindcast_end=2016,
        evaluation_hindcast_start=1993, evaluation_hindcast_end=2016,
        hindcast_members=40, forecast_members=50,
        leads_disponiveis=(1, 2, 3, 4, 5, 6),
        resolucao=None,
        hindcast_production='fixed',
        verificado_cruzado=True,
        fontes=(
            'cmcc.it TN0288 "The new CMCC Operational Seasonal Prediction System" (via WebSearch: '
            '"hindcast ensemble size of 40 members... 1/1993-12/2016", forecast 50 membros) — fonte '
            'oficial CMCC, registra explicitamente hindcast 1993-2016, 40 membros de hindcast, 50 '
            'membros de forecast, leads 1-6 meses (Seção 3 da correção de auditabilidade).',
            'psl.noaa.gov/forecasts/s2s_C3S_monthly_to_seasonal/description/ (via WebSearch: "CMCC '
            'SPSv3.5 is referenced as System 35... lead time months 1 to 6")',
        ),
        notas='Fonte oficial CMCC (TN0288) confirma explicitamente: hindcast 1993-2016, 40 membros de '
              'hindcast, 50 membros de forecast, 6 meses de lead — todos os quatro registrados aqui sem '
              'alteração. SPS4 (atual no catálogo CDS, adicionado ago/2026 segundo a busca) está '
              'explicitamente documentado como "decisions... still pending, details to be communicated" '
              '— não incluído nesta fase por falta de specs confirmáveis, não por rejeição científica. '
              'Ver NAO_INCLUIDOS_VERSAO. model_id e resolução não confirmados nesta sessão — None em '
              'vez de inventados.',
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
    """Deriva o período comum de AVALIAÇÃO entre os sistemas dados —
    NUNCA hardcoded (Seção 4), e sempre a partir dos campos
    `evaluation_hindcast_start/end` (nunca dos `native_hindcast_*` —
    Seção 5 da correção de auditabilidade: o período nativo, quando mais
    longo, não entra nesse cálculo). Devolve dict com common_start/
    common_end (None se não houver interseção viável) e
    anos_disponiveis_por_modelo (para auditoria). Qualquer sistema com
    evaluation_hindcast_start/end ausente (None) é reportado em
    `incompatibilidade`, nunca silenciosamente ignorado no cálculo."""
    anos_por_modelo = {}
    incompatibilidade = {}
    inicios, fins = [], []
    for s in sistemas:
        chave = f'{s.centro}/{s.system_name}'
        if s.evaluation_hindcast_start is None or s.evaluation_hindcast_end is None:
            incompatibilidade[chave] = 'evaluation_hindcast_start/evaluation_hindcast_end ausente no catálogo'
            continue
        if s.evaluation_hindcast_start > s.evaluation_hindcast_end:
            incompatibilidade[chave] = (f'evaluation_hindcast_start ({s.evaluation_hindcast_start}) > '
                                         f'evaluation_hindcast_end ({s.evaluation_hindcast_end})')
            continue
        anos_por_modelo[chave] = [s.evaluation_hindcast_start, s.evaluation_hindcast_end]
        inicios.append(s.evaluation_hindcast_start)
        fins.append(s.evaluation_hindcast_end)

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
    `c3s_multimodel_catalog.csv`. Inclui os campos `native_hindcast_*`
    (período de reforecast documentado pela fonte oficial do centro,
    pode ser mais longo — `None` quando não atribuível com confiança) e
    `evaluation_hindcast_*` (período retrospectivo comum usado na
    comparação multi-modelo desta fase) separadamente — nunca misturados
    numa única coluna ambígua (Seção 2 da correção de auditabilidade).
    `incluidos`: coleção de (centro, system_name) considerados incluídos
    no POC — default: todo CATALOGO."""
    import pandas as pd
    sistemas = sistemas if sistemas is not None else CATALOGO
    incluidos = set(incluidos) if incluidos is not None else set(SISTEMAS_CANDIDATOS_FASE2B1)
    linhas = []
    for s in sistemas:
        compatible_leads_1_6 = tuple(s.leads_disponiveis) == (1, 2, 3, 4, 5, 6)
        linhas.append({
            'centre': s.centro, 'system_name': s.system_name, 'system_code': s.system_code,
            'model_id': s.model_id,
            'native_hindcast_start': s.native_hindcast_start, 'native_hindcast_end': s.native_hindcast_end,
            'evaluation_hindcast_start': s.evaluation_hindcast_start,
            'evaluation_hindcast_end': s.evaluation_hindcast_end,
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
            '1-6 (Seção 1), nunca por skill local. Período comum é a interseção de '
            'evaluation_hindcast_start/evaluation_hindcast_end (o período retrospectivo COMUM usado na '
            'comparação multi-modelo) de cada sistema incluído — calculada, não fixada manualmente, e '
            'nunca a partir de native_hindcast_start/end (o período de reforecast nativo documentado '
            'pela fonte oficial de cada centro, que pode ser mais longo — ex.: ECMWF SEAS5 nativo é '
            '1981-2016). UKMO excluído por esquema de hindcast on-the-fly/lagged; NCEP/ECCC/BOM/JMA '
            'fora de escopo desta fase; versões "atuais" de METFR/DWD/CMCC (System9/GCFS2.2/SPS4) '
            'substituídas por versões anteriores com specs cross-confirmadas (ver NAO_INCLUIDOS_VERSAO).'
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
