#!/usr/bin/env python3
"""
nmme_catalogo.py — Fase 2C.1: catálogo auditável dos sistemas
candidatos ao North American Multi-Model Ensemble (NMME), fonte
dinâmica sazonal INDEPENDENTE do C3S (Fase 2B).

PERGUNTA CIENTÍFICA DA FASE 2C (Seção 1 do objetivo): a baixa
previsibilidade observada na Fase 2B.2 — set-fev, H2-H6, probabilidades
— é limitação específica do C3S ou característica mais geral da
previsibilidade sazonal de precipitação em São Bento do Tocantins?
Responder isso exige uma fonte GENUINAMENTE independente — daí a
exclusão deliberada do ECMWF (Seção 5) mesmo que apareça em alguma
configuração NMME3: ECMWF já é a espinha dorsal do C3S validado nas
Fases 2A-2B, incluí-lo aqui invalidaria a independência que a Fase 2C
busca.

PRINCÍPIO FUNDAMENTAL (Seção 1): nenhum SARIMAX/XGBoost/regressora
ONI-N34/otimização retrospectiva/peso local/seleção de modelo por skill
local. Esta fase é validação independente de previsão DINÂMICA, não
mais um ajuste estatístico.

═══════════════════════════════════════════════════════════════════════
INVESTIGAÇÃO REALIZADA NESTA SESSÃO (Seção 3/9) — o que foi possível
confirmar e o que ficou bloqueado
═══════════════════════════════════════════════════════════════════════

Restrição de rede desta sessão (WebFetch): `www.cpc.ncep.noaa.gov`
respondeu (páginas HTML gerais), mas NENHUMA das páginas alcançadas
(`/products/NMME/`, `/products/NMME/data.html`,
`/products/NMME/users_guide.html`, `/products/NMME/NMME_description.html`,
`/products/NMME/current/CanESM5tminSeas.html`) contém a tabela atual de
modelos/membros/período — são páginas de navegação, descrição textual
genérica ou galerias de mapas (nunca usadas como dado, Seção 10). Os
seguintes domínios ficaram BLOQUEADOS pelo proxy de rede desta sessão
(EGRESS_BLOCKED, confirmado por tentativa direta de WebFetch, não
suposição): `ftp.cpc.ncep.noaa.gov`, `iridl.ldeo.columbia.edu`,
`www.gfdl.noaa.gov`, `www.weather.gov`, `wpo.noaa.gov`,
`eccc-msc.github.io`, `climate-scenarios.canada.ca`,
`agupubs.onlinelibrary.wiley.com`, `doi.org`, `climatetoolbox.org`.
Mesma limitação estrutural já documentada em c3s_catalogo.py/
c3s_multimodel_catalogo.py para outros domínios em sessões anteriores —
a disponibilidade de rede varia por sessão, não é garantida.

O WebSearch (que indexa/cita conteúdo independente do bloqueio de
WebFetch) permitiu recuperar trechos citáveis de páginas que o WebFetch
não conseguiu abrir diretamente — tratados aqui como DOCUMENTED (fonte
oficial identificada e trecho citado), nunca EMPIRICALLY_CONFIRMED
(que exigiria abrir/baixar o dado real, não feito nesta tarefa por
proibição explícita da Seção 38/50).

Achados citáveis, por fonte:

1. **Emerson LaJoie (meteorologista CPC), CDPW nº47, 25-27/out/2022**
   (`cpc.ncep.noaa.gov/products/outreach/CDPW/47/sessions/presentations/
   session8-oral1.pdf` — PDF baixado com sucesso e lido via extração de
   texto local, portanto EMPIRICALLY_CONFIRMED para o texto em si, mas
   descreve a geração ANTERIOR de modelos, antes da troca CanCM4i→
   CanESM5/GEM_NEMO→GEM5.2_NEMO/GFDL_FLOR→SPEAR). Slide 4, citação
   exata: "NMME: CFSv2 24 members / GEM_NEMO 10 members / CanCM4i 10
   members / GFDL_FLOR 24 members / NASA_GEOS5v2 4 members / NCAR_CCSM4
   10 members". Slide 6: "common hindcast period: 1982-2020". Slide 4:
   "Raw" NMME: OND 1982-DJF 2020 / Calibrated NMME: OND 1991-DJF 2020.
   Esta é a ÚNICA fonte desta investigação aberta e lida de primeira
   mão (não só snippet de busca) — por isso CFSv2=24 e NASA_GEOS5v2=4
   têm o status mais forte possível dentre os candidatos (mas ainda
   `DOCUMENTED`, não `EMPIRICALLY_CONFIRMED`, porque o texto confirmado
   descreve a config de 2022, não necessariamente a atual — CFSv2 não
   foi trocado de versão, então o valor tem boa chance de continuar
   válido, mas isso não foi verificado no arquivo real).

2. **WebSearch sobre climatetoolbox.org (ago/2024, bloqueado para
   WebFetch direto)**: "Seasonal forecast models have been updated to
   the current operational NMME models, with CanCM4i replaced by
   CanESM5, GEM5-NEMO replaced by GEM5.2-NEMO, and GFDL_SPEAR and
   NCAR_CESM1 added." — confirma a troca de geração e a entrada de
   SPEAR/CESM1 como adição (não substituição).

3. **WebSearch sobre climate-scenarios.canada.ca (ECCC, bloqueado para
   WebFetch direto)**: "CanSIPSv3 uses a 30-year seasonal hindcast with
   20 ensemble members for each model initialized near the start of
   each month from 1991 to 2020" — período/membros de CanESM5 e
   GEM5.2-NEMO. Nota de versão: outro trecho da mesma busca cita
   "CanESM5.1" (não "CanESM5") como componente do CanSIPSv3 — divergência
   de sufixo de versão registrada em `notes`, não resolvida.

4. **WebSearch sobre IRIDL (catálogo `.Models/.NMME/.GFDL-SPEAR/
   .HINDCAST/.MONTHLY/`, título indexado "GFDL-SPEAR HINDCAST
   1991-2020 Monthly", bloqueado para WebFetch direto)**: hindcast
   1991-2020, 15 membros, entrou no NMME em 06/fev/2021.

5. **WebSearch sobre artigo revisado por pares "Initialized Seasonal
   Prediction with the NCAR Models in the North American Multimodel
   Ensemble (NMME)", Weather and Forecasting v.40 n.6 (2025),
   doi.org/10.1175/WAF-D-24-0123.1 (bloqueado para WebFetch direto)**:
   "the common period currently available for the three models [CCSM3,
   CCSM4, CESM1] ... 1991-2018" — sem confirmação de nº de membros para
   CESM1/CCSM4 nesta investigação.

6. **IRIDL — paths de catálogo confirmados via título indexado (não
   via conteúdo do arquivo)**: `.Models/.NMME/.GFDL-SPEAR/.HINDCAST/
   .MONTHLY/`, `.Models/.NMME/.NCAR-CESM1/.HINDCAST/.MONTHLY/`,
   `.Models/.NMME/.CanSIPS-IC3/.GEM5-NEMO/.HINDCAST/.MONTHLY/.sst` —
   note a grafia `GEM5-NEMO` (sem o `.2`) dentro do path IRIDL, distinta
   da grafia `GEM5.2-NEMO` usada em documentação textual — registrado
   como possível inconsistência de nomenclatura entre catálogo/
   documentação, não resolvida nesta sessão.

Nenhum arquivo de dado (NetCDF/GRIB) foi baixado nesta investigação —
só páginas HTML/texto de documentação, dentro do que a Seção 38/50
permite.
"""

from dataclasses import dataclass, field
from typing import Optional

# ══════════════════════════════════════════════════════════════════════════
# Seção 7 — matriz de evidência: todo campo crítico carrega um status.
# ══════════════════════════════════════════════════════════════════════════
DOCUMENTED = 'DOCUMENTED'
EMPIRICALLY_CONFIRMED = 'EMPIRICALLY_CONFIRMED'
DOCUMENTED_AND_CONFIRMED = 'DOCUMENTED_AND_CONFIRMED'
UNCONFIRMED = 'UNCONFIRMED'
STATUS_VALIDOS = {DOCUMENTED, EMPIRICALLY_CONFIRMED, DOCUMENTED_AND_CONFIRMED, UNCONFIRMED}

# Seção 19 — disponibilidade por critério de protocolo, nunca por
# performance local (Seção 19/22).
STATUS_CANDIDATO = 'CANDIDATE'
STATUS_NAO_HOMOGENEO = 'NOT_HOMOGENEOUSLY_AVAILABLE'


@dataclass(frozen=True)
class SistemaNMME:
    centre: str                            # organização/centro contribuinte
    model_name: str                        # nome do modelo na geração NMME ATUAL (Seção 4)
    model_version: Optional[str]
    official_model_id: Optional[str]       # identificador em catálogos oficiais (ex.: path IRIDL)
    data_source: str                       # rota de dados PRINCIPAL investigada (Seção 9)
    data_url_template: Optional[str]       # padrão de URL só quando documentado; None se não (Seção 6)
    hindcast_start: Optional[int]
    hindcast_end: Optional[int]
    hindcast_members: Optional[int]
    realtime_members: Optional[int]
    leads_available: tuple
    grid_resolution: Optional[str]
    precip_variable: Optional[str]
    precip_units: Optional[str]
    hindcast_frequency: Optional[str]
    initialization_scheme: Optional[str]
    availability_status: str               # CANDIDATE | NOT_HOMOGENEOUSLY_AVAILABLE
    source_reference: tuple = field(default_factory=tuple)
    notes: str = ''
    # Seção 7/8 — status por campo crítico; chaves ausentes tratadas como
    # UNCONFIRMED por _validar_catalogo() (Seção 35-B), nunca por omissão
    # silenciosa.
    evidence: dict = field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════════════
# Seção 5 — ECMWF explicitamente fora de escopo, mesmo que alguma config
# NMME3 o liste: queremos independência da validação C3S (Fases 2A-2B).
# Seção 21 — predecessores JAMAIS tratados como o mesmo sistema que o
# substituiu; registrados aqui só para auditoria/anti-confusão, nunca
# usados para preencher hindcast do sistema atual (Seção 22).
# ══════════════════════════════════════════════════════════════════════════
NAO_INCLUIDOS = {
    'ECMWF': {
        'motivo': 'Exclusão deliberada (Seção 5) — ECMWF já é a base do C3S validado nas Fases 2A-2B. '
                   'Incluí-lo aqui invalidaria a independência que a Fase 2C busca, mesmo que alguma '
                   'configuração NMME3 documentada recentemente o liste em algum papel.',
    },
}

PREDECESSORES_NAO_CONFUNDIR = {
    'CanCM4i': {
        'substituido_por': 'CanESM5', 'centre': 'ECCC',
        'motivo': 'Troca de sistema documentada (Seção 21) — CanCM4i e CanESM5 NÃO são o mesmo modelo; '
                   'uma série concatenando os dois não é um hindcast homogêneo (Seção 21/22).',
        'membros_documentados_geracao_anterior': 10,
        'fonte': 'LaJoie (CPC), CDPW47, out/2022 — slide 4: "CanCM4i 10 members".',
    },
    'GEM_NEMO': {
        'substituido_por': 'GEM5.2_NEMO', 'centre': 'ECCC',
        'motivo': 'Troca de sistema documentada (Seção 21) — GEM_NEMO (sem o ".2") é o predecessor, '
                   'nunca o mesmo sistema que GEM5.2_NEMO.',
        'membros_documentados_geracao_anterior': 10,
        'fonte': 'LaJoie (CPC), CDPW47, out/2022 — slide 4: "GEM_NEMO 10 members".',
    },
    'GFDL_FLOR': {
        'substituido_por': 'GFDL_SPEAR', 'centre': 'NOAA/GFDL',
        'motivo': 'Troca de sistema documentada (Seção 21) — GFDL_FLOR (CM2.5-FLOR) é o predecessor; '
                   'SPEAR entrou no NMME em 06/fev/2021 como sistema NOVO, não uma revisão do FLOR.',
        'membros_documentados_geracao_anterior': 24,
        'fonte': 'LaJoie (CPC), CDPW47, out/2022 — slide 4: "GFDL_FLOR 24 members".',
    },
}

# ══════════════════════════════════════════════════════════════════════════
# Seção 4/6/8 — os 7 candidatos investigados. NENHUM valor numérico
# aparece sem `source_reference` não-vazio (barreira em
# _validar_catalogo). Onde a investigação desta sessão não permitiu
# confirmação (rede bloqueada), o campo fica `None`/status
# `UNCONFIRMED` — nunca inventado (Seção 6: "Quando uma informação não
# puder ser comprovada: usar None. Nunca inventar.").
# ══════════════════════════════════════════════════════════════════════════
CATALOGO = [
    SistemaNMME(
        centre='NOAA_NCEP', model_name='CFSv2', model_version=None, official_model_id=None,
        data_source='IRI Data Library (NMME collection) — padrão esperado, não confirmado nesta sessão',
        data_url_template=None,
        hindcast_start=None, hindcast_end=None,   # ver notes — LaJoie cita 1982-2020/1991-2020, mas
                                                    # para a config PRÉ-troca de geração; não reafirmado
                                                    # para a config atual nesta sessão.
        hindcast_members=24, realtime_members=None,
        leads_available=(1, 2, 3, 4, 5, 6),
        grid_resolution=None, precip_variable=None, precip_units=None,
        hindcast_frequency='monthly (múltiplas inicializações diárias agregadas ao mês, a confirmar '
                            '— Seção 14)',
        initialization_scheme='CFSv2 roda com múltiplas inicializações DIÁRIAS dentro do mês (padrão '
                               'documentado do sistema desde a Fase NMME original) — como o ensemble '
                               'mensal é formado a partir dessas rodadas NÃO foi confirmado nesta '
                               'sessão (Seção 14); nunca misturar rodada diária com ensemble mensal '
                               'sem essa confirmação.',
        availability_status=STATUS_CANDIDATO,
        source_reference=(
            'LaJoie (CPC), Climate Diagnostics and Prediction Workshop nº47, 25-27/out/2022, slide 4: '
            '"CFSv2 24 members" (cpc.ncep.noaa.gov/products/outreach/CDPW/47/sessions/presentations/'
            'session8-oral1.pdf — PDF lido de primeira mão nesta sessão).',
        ),
        notes='hindcast_members=24 é o único campo numérico desta entrada com fonte lida de primeira '
              'mão (PDF baixado com sucesso) — mas descreve a config de out/2022, sem reconfirmação '
              'para a config atual (CFSv2 não foi trocado de versão nas trocas documentadas de '
              '2023-2024, então é razoável esperar que continue válido, mas isso é inferência, não '
              'confirmação). hindcast_start/end ficam None porque as duas janelas citadas por LaJoie '
              '(1982-2020 "raw"/1991-2020 "calibrated") descrevem o CONJUNTO de 6 modelos da geração '
              'anterior, não CFSv2 isoladamente — não é seguro atribuir esse período só a CFSv2 sem '
              'reconfirmação no arquivo real.',
        evidence={'hindcast_members': DOCUMENTED, 'hindcast_start': UNCONFIRMED,
                   'hindcast_end': UNCONFIRMED, 'realtime_members': UNCONFIRMED,
                   'grid_resolution': UNCONFIRMED, 'precip_variable': UNCONFIRMED,
                   'precip_units': UNCONFIRMED, 'initialization_scheme': UNCONFIRMED},
    ),
    SistemaNMME(
        centre='ECCC', model_name='CanESM5', model_version='CanESM5 (uma fonte cita "CanESM5.1" — '
                                                              'divergência de sufixo não resolvida)',
        official_model_id=None,
        data_source='IRI Data Library (NMME collection), catálogo CanSIPS-IC3',
        data_url_template=None,   # path exato não confirmado — só o de GEM5-NEMO foi visto (ver notes)
        hindcast_start=1991, hindcast_end=2020,
        hindcast_members=20, realtime_members=None,   # ver notes — esquema de 4 dias pode dobrar p/ 40
        leads_available=(1, 2, 3, 4, 5, 6),
        grid_resolution=None, precip_variable=None, precip_units=None,
        hindcast_frequency='monthly',
        initialization_scheme='Real-time: relato (via busca, não confirmado de primeira mão) de que em '
                               '11/jun/2024 o tamanho do ensemble operacional passou de 20 para 40 '
                               'combinando o dia mais recente com inicializações de até 4 dias antes '
                               '— se verdadeiro, isso é um ensemble LAGGED no forecast, distinto do '
                               'hindcast de 20 membros/mês; precisa validação explícita antes do POC '
                               'real (Seção 14).',
        availability_status=STATUS_CANDIDATO,
        source_reference=(
            'WebSearch sobre climate-scenarios.canada.ca (ECCC, técnico CanSIPS) — bloqueado para '
            'WebFetch direto nesta sessão: "CanSIPSv3 uses a 30-year seasonal hindcast with 20 '
            'ensemble members for each model initialized near the start of each month from 1991 to '
            '2020."',
            'WebSearch sobre mudança de ensemble 20→40 (fonte não plenamente identificada nesta '
            'sessão — citada com reserva, ver notes).',
        ),
        notes='Substitui CanCM4i (Seção 21 — nunca concatenar as duas séries). Path IRIDL exato não '
              'confirmado — só foi visto o path de GEM5-NEMO sob o mesmo catálogo CanSIPS-IC3 '
              '(.Models/.NMME/.CanSIPS-IC3/.GEM5-NEMO/...), por analogia esperamos '
              '.Models/.NMME/.CanSIPS-IC3/.CanESM5/... mas isso é EXTRAPOLAÇÃO, não confirmação — '
              'marcado None até o POC real verificar. hindcast_start/end=1991/2020 vem de uma fonte '
              'oficial (ECCC) mas só via snippet de busca, nunca aberta diretamente nesta sessão — '
              'DOCUMENTED, não EMPIRICALLY_CONFIRMED.',
        evidence={'hindcast_start': DOCUMENTED, 'hindcast_end': DOCUMENTED,
                   'hindcast_members': DOCUMENTED, 'realtime_members': UNCONFIRMED,
                   'model_version': UNCONFIRMED, 'data_url_template': UNCONFIRMED,
                   'grid_resolution': UNCONFIRMED, 'precip_variable': UNCONFIRMED,
                   'precip_units': UNCONFIRMED, 'initialization_scheme': UNCONFIRMED},
    ),
    SistemaNMME(
        centre='ECCC', model_name='GEM5.2_NEMO', model_version='GEM5.2-NEMO', official_model_id=None,
        data_source='IRI Data Library (NMME collection), catálogo CanSIPS-IC3',
        data_url_template='https://iridl.ldeo.columbia.edu/SOURCES/.Models/.NMME/.CanSIPS-IC3/'
                           '.GEM5-NEMO/.HINDCAST/.MONTHLY/ (grafia do path SEM o ".2" — ver notes; '
                           'sufixo de variável de precipitação ainda não identificado)',
        hindcast_start=1991, hindcast_end=2020,
        hindcast_members=20, realtime_members=None,
        leads_available=(1, 2, 3, 4, 5, 6),
        grid_resolution=None, precip_variable=None, precip_units=None,
        hindcast_frequency='monthly',
        initialization_scheme='Mesma ressalva de CanESM5 sobre possível ensemble lagged de 4 dias no '
                               'forecast operacional (20→40) — não confirmada de primeira mão.',
        availability_status=STATUS_CANDIDATO,
        source_reference=(
            'WebSearch sobre climate-scenarios.canada.ca (ECCC) — mesma citação de CanESM5: hindcast '
            '20 membros/modelo, 1991-2020.',
            'WebSearch sobre catálogo IRIDL — título indexado ".Models/.NMME/.CanSIPS-IC3/.GEM5-NEMO/'
            '.HINDCAST/.MONTHLY/.sst" (variável mostrada foi sst, não precipitação — path real '
            'confirma o MODELO, não a variável de precipitação).',
        ),
        notes='Substitui GEM_NEMO (Seção 21 — nunca concatenar). Path IRIDL usa a grafia "GEM5-NEMO" '
              '(sem ".2"), enquanto a documentação textual da ECCC usa "GEM5.2-NEMO" — inconsistência '
              'de nomenclatura entre catálogo e documentação registrada, não resolvida; o POC real '
              'deve confirmar qual grafia o path realmente aceita.',
        evidence={'hindcast_start': DOCUMENTED, 'hindcast_end': DOCUMENTED,
                   'hindcast_members': DOCUMENTED, 'data_url_template': DOCUMENTED,
                   'realtime_members': UNCONFIRMED, 'grid_resolution': UNCONFIRMED,
                   'precip_variable': UNCONFIRMED, 'precip_units': UNCONFIRMED,
                   'initialization_scheme': UNCONFIRMED},
    ),
    SistemaNMME(
        centre='NOAA_GFDL', model_name='GFDL_SPEAR', model_version='SPEAR', official_model_id=None,
        data_source='IRI Data Library (NMME collection)',
        data_url_template='https://iridl.ldeo.columbia.edu/SOURCES/.Models/.NMME/.GFDL-SPEAR/'
                           '.HINDCAST/.MONTHLY/ (sufixo de variável de precipitação ainda não '
                           'identificado)',
        hindcast_start=1991, hindcast_end=2020,
        hindcast_members=15, realtime_members=None,
        leads_available=(1, 2, 3, 4, 5, 6),
        grid_resolution=None, precip_variable=None, precip_units=None,
        hindcast_frequency='monthly', initialization_scheme=None,
        availability_status=STATUS_CANDIDATO,
        source_reference=(
            'WebSearch sobre título indexado do catálogo IRIDL: "Models NMME GFDL-SPEAR HINDCAST '
            '1991-2020 Monthly".',
            'WebSearch: "Ensemble Size: The SPEAR seasonal prediction ensemble has 15 members" e '
            '"As of February 6, 2021, SPEAR became part of the North American Multi-Model Ensemble '
            '(NMME)".',
        ),
        notes='Substitui GFDL_FLOR (Seção 21 — sistema novo, não uma revisão do FLOR, nunca '
              'concatenar as duas séries). Entrou no NMME em 06/fev/2021 (data documentada).',
        evidence={'hindcast_start': DOCUMENTED, 'hindcast_end': DOCUMENTED,
                   'hindcast_members': DOCUMENTED, 'data_url_template': DOCUMENTED,
                   'realtime_members': UNCONFIRMED, 'grid_resolution': UNCONFIRMED,
                   'precip_variable': UNCONFIRMED, 'precip_units': UNCONFIRMED,
                   'initialization_scheme': UNCONFIRMED},
    ),
    SistemaNMME(
        centre='NCAR', model_name='NCAR_CCSM4', model_version='CCSM4', official_model_id=None,
        data_source='IRI Data Library (NMME collection) — padrão esperado, path exato não confirmado',
        data_url_template=None,
        hindcast_start=None, hindcast_end=None,   # ver notes — 1991-2018 é do TRIO (CCSM3/CCSM4/CESM1)
        hindcast_members=10, realtime_members=None,
        leads_available=(1, 2, 3, 4, 5, 6),
        grid_resolution=None, precip_variable=None, precip_units=None,
        hindcast_frequency='monthly', initialization_scheme=None,
        availability_status=STATUS_CANDIDATO,
        source_reference=(
            'WebSearch sobre "Initialized Seasonal Prediction with the NCAR Models in NMME", Weather '
            'and Forecasting v.40 n.6 (2025), doi:10.1175/WAF-D-24-0123.1 (bloqueado para WebFetch '
            'direto): "the common period currently available for the three models [CCSM3, CCSM4, '
            'CESM1] ... 1991-2018" — cobre os 3 modelos NCAR juntos, não CCSM4 isoladamente.',
        ),
        notes='hindcast_members=10 vem da especificação original desta tarefa (Seção 8), não de uma '
              'fonte independente verificada nesta sessão — mantido como valor a confirmar '
              '(`documented_expected`, Seção 8), nunca tratado como fato estabelecido. '
              'hindcast_start/end ficam None porque a única janela encontrada (1991-2018) descreve o '
              'período COMUM aos 3 modelos NCAR, não necessariamente o hindcast nativo de CCSM4 '
              'isolado — e o próprio snippet de busca menciona possível extensão até 2020 sem '
              'confirmar, então não é seguro atribuir 1991-2018 como definitivo.',
        evidence={'hindcast_members': UNCONFIRMED, 'hindcast_start': UNCONFIRMED,
                   'hindcast_end': UNCONFIRMED, 'realtime_members': UNCONFIRMED,
                   'grid_resolution': UNCONFIRMED, 'precip_variable': UNCONFIRMED,
                   'precip_units': UNCONFIRMED, 'initialization_scheme': UNCONFIRMED},
    ),
    SistemaNMME(
        centre='NCAR', model_name='NCAR_CESM1', model_version='CESM1', official_model_id=None,
        data_source='IRI Data Library (NMME collection)',
        data_url_template='https://iridl.ldeo.columbia.edu/SOURCES/.Models/.NMME/.NCAR-CESM1/'
                           '.HINDCAST/.MONTHLY/ (sufixo de variável de precipitação ainda não '
                           'identificado — path visto na busca só mostrou a variável tsmx)',
        hindcast_start=None, hindcast_end=None,   # ver notes — mesma ressalva de CCSM4
        hindcast_members=10, realtime_members=None,
        leads_available=(1, 2, 3, 4, 5, 6),
        grid_resolution=None, precip_variable=None, precip_units=None,
        hindcast_frequency='monthly',
        initialization_scheme='CESM1 usa CAM5 (atmosfera) — documentado (WebSearch sobre página NCAR) '
                               'que é uma evolução de CCSM4; nunca tratar CCSM4 e CESM1 como o mesmo '
                               'sistema (são dois candidatos distintos nesta lista, não uma sucessão '
                               'a concatenar).',
        availability_status=STATUS_CANDIDATO,
        source_reference=(
            'WebSearch sobre catálogo IRIDL — título indexado ".Models/.NMME/.NCAR-CESM1/.HINDCAST/'
            '.MONTHLY/tsmx" confirma que o path do MODELO existe no catálogo (variável mostrada foi '
            'tsmx, não precipitação).',
            'WebSearch sobre "Initialized Seasonal Prediction with the NCAR Models in NMME" (2025) — '
            'mesma citação de período comum 1991-2018 usada em NCAR_CCSM4.',
        ),
        notes='hindcast_members=10 é `documented_expected` (Seção 8, vindo da especificação da '
              'tarefa), não confirmado de primeira mão nesta sessão.',
        evidence={'hindcast_members': UNCONFIRMED, 'hindcast_start': UNCONFIRMED,
                   'hindcast_end': UNCONFIRMED, 'data_url_template': DOCUMENTED,
                   'realtime_members': UNCONFIRMED, 'grid_resolution': UNCONFIRMED,
                   'precip_variable': UNCONFIRMED, 'precip_units': UNCONFIRMED},
    ),
    SistemaNMME(
        centre='NASA', model_name='GEOS5v2', model_version='GEOS5v2 (uma listagem não-oficial '
                                                              'encontrada cita "GEOS-S2S-2" com outro '
                                                              'nº de membros — ver notes, NÃO tratado '
                                                              'como o mesmo sistema sem confirmação)',
        official_model_id=None,
        data_source='IRI Data Library (NMME collection) — padrão esperado, path exato não confirmado',
        data_url_template=None,
        hindcast_start=None, hindcast_end=None,
        hindcast_members=4, realtime_members=None,
        leads_available=(1, 2, 3, 4, 5, 6),
        grid_resolution=None, precip_variable=None, precip_units=None,
        hindcast_frequency='monthly', initialization_scheme=None,
        availability_status=STATUS_CANDIDATO,
        source_reference=(
            'LaJoie (CPC), CDPW47, out/2022, slide 4: "NASA_GEOS5v2 4 members" (PDF lido de primeira '
            'mão nesta sessão).',
        ),
        notes='hindcast_members=4 tem a mesma força de evidência que CFSv2 (PDF oficial CPC lido '
              'diretamente), mas também descreve a config de out/2022. Uma fonte secundária '
              '(repositório GitHub não-oficial, citado só como sinal de possível divergência, nunca '
              'como autoridade — Seção 2) lista "NASA-GEOS-S2S-2" com 10 membros — se for uma versão '
              'DIFERENTE (S2S-2 sucedendo GEOS5v2, mesma lógica da Seção 21 para os outros modelos), '
              'nunca tratar como o mesmo sistema sem confirmação; registrado aqui como pergunta em '
              'aberto para o POC real, não resolvida nesta sessão. hindcast_start/end: nenhuma fonte '
              'encontrada nesta sessão.',
        evidence={'hindcast_members': DOCUMENTED, 'hindcast_start': UNCONFIRMED,
                   'hindcast_end': UNCONFIRMED, 'model_version': UNCONFIRMED,
                   'realtime_members': UNCONFIRMED, 'grid_resolution': UNCONFIRMED,
                   'precip_variable': UNCONFIRMED, 'precip_units': UNCONFIRMED,
                   'initialization_scheme': UNCONFIRMED},
    ),
]


def sistema_por_nome(centre, model_name):
    for s in CATALOGO:
        if s.centre == centre and s.model_name == model_name:
            return s
    raise KeyError(f"sistema não encontrado no catálogo NMME: {centre}/{model_name}")


# ══════════════════════════════════════════════════════════════════════════
# Seção 35-A — guardrail: nenhum campo numérico de período pode existir
# sem fonte citada (nunca "período inventado"). Seção 35-B — todo campo
# sem evidência explícita é tratado como UNCONFIRMED, nunca omitido
# silenciosamente.
# ══════════════════════════════════════════════════════════════════════════

def _validar_catalogo(catalogo):
    for s in catalogo:
        chave = f'{s.centre}/{s.model_name}'
        if (s.hindcast_start is not None or s.hindcast_end is not None) and not s.source_reference:
            raise ValueError(f"{chave}: hindcast_start/hindcast_end numérico sem source_reference — "
                              f"período não pode ser inventado (Seção 35-A).")
        for campo in ('hindcast_start', 'hindcast_end', 'hindcast_members'):
            if getattr(s, campo) is not None and campo not in s.evidence:
                raise ValueError(f"{chave}: campo {campo!r} tem valor numérico mas nenhum status na "
                                  f"matriz de evidência — todo valor precisa de status explícito "
                                  f"(Seção 7/35-B).")
        for campo, status in s.evidence.items():
            if status not in STATUS_VALIDOS:
                raise ValueError(f"{chave}: status de evidência inválido para {campo!r}: {status!r} "
                                  f"(precisa ser um de {sorted(STATUS_VALIDOS)}).")
        if s.availability_status not in (STATUS_CANDIDATO, STATUS_NAO_HOMOGENEO):
            raise ValueError(f"{chave}: availability_status inválido: {s.availability_status!r}.")
    return True


_validar_catalogo(CATALOGO)


def status_evidencia(sistema, campo):
    """Devolve o status de evidência de `campo` para `sistema` — UNCONFIRMED
    se o campo não tiver entrada explícita na matriz (Seção 35-B: nunca
    tratar ausência de registro como confirmação por omissão)."""
    return sistema.evidence.get(campo, UNCONFIRMED)


# ══════════════════════════════════════════════════════════════════════════
# Seção 20 — período comum só é calculado DEPOIS do catálogo estar
# pronto, nunca antecipado. Usa só sistemas com hindcast_start/end não
# nulos E status de evidência em {DOCUMENTED, EMPIRICALLY_CONFIRMED,
# DOCUMENTED_AND_CONFIRMED} — um valor UNCONFIRMED nunca entra no
# cálculo do período comum, mesmo que o campo não seja None (defensivo:
# nesta versão do catálogo isso não ocorre, já que todo valor não-None
# tem evidence != UNCONFIRMED por construção de _validar_catalogo, mas a
# checagem fica explícita para robustez a edições futuras).
# ══════════════════════════════════════════════════════════════════════════

def periodo_comum_hindcast(sistemas):
    """Deriva o período comum de hindcast entre os sistemas dados — NUNCA
    hardcoded (Seção 20). Devolve dict com common_start/common_end (None
    se não houver interseção viável ou se nenhum sistema tiver período
    defensável) e `elegveis`/`incompatibilidade` para auditoria."""
    elegiveis = {}
    incompatibilidade = {}
    inicios, fins = [], []
    for s in sistemas:
        chave = f'{s.centre}/{s.model_name}'
        if s.hindcast_start is None or s.hindcast_end is None:
            incompatibilidade[chave] = 'hindcast_start/hindcast_end ausente (UNCONFIRMED) no catálogo'
            continue
        status_ini = status_evidencia(s, 'hindcast_start')
        status_fim = status_evidencia(s, 'hindcast_end')
        if UNCONFIRMED in (status_ini, status_fim):
            incompatibilidade[chave] = (f'hindcast_start/end presente mas evidence=UNCONFIRMED '
                                         f'({status_ini}/{status_fim}) — não entra no período comum.')
            continue
        if s.hindcast_start > s.hindcast_end:
            incompatibilidade[chave] = f'hindcast_start ({s.hindcast_start}) > hindcast_end ({s.hindcast_end})'
            continue
        elegiveis[chave] = [s.hindcast_start, s.hindcast_end]
        inicios.append(s.hindcast_start)
        fins.append(s.hindcast_end)

    if not inicios:
        return {'common_start': None, 'common_end': None, 'elegiveis': elegiveis,
                'incompatibilidade': incompatibilidade, 'status': UNCONFIRMED}

    common_start, common_end = max(inicios), min(fins)
    if common_start > common_end:
        incompatibilidade['interseccao'] = (f'sem sobreposição real: common_start ({common_start}) > '
                                             f'common_end ({common_end})')
        return {'common_start': None, 'common_end': None, 'elegiveis': elegiveis,
                'incompatibilidade': incompatibilidade, 'status': UNCONFIRMED}

    return {'common_start': common_start, 'common_end': common_end, 'elegiveis': elegiveis,
            'incompatibilidade': incompatibilidade, 'status': DOCUMENTED,
            'n_elegiveis': len(elegiveis), 'n_total': len(sistemas)}


def tabela_catalogo(sistemas=None):
    import pandas as pd
    sistemas = sistemas if sistemas is not None else CATALOGO
    linhas = []
    for s in sistemas:
        linhas.append({
            'centre': s.centre, 'model_name': s.model_name, 'model_version': s.model_version,
            'official_model_id': s.official_model_id, 'data_source': s.data_source,
            'data_url_template': s.data_url_template,
            'hindcast_start': s.hindcast_start, 'hindcast_end': s.hindcast_end,
            'hindcast_members': s.hindcast_members, 'realtime_members': s.realtime_members,
            'leads_available': ','.join(str(x) for x in s.leads_available),
            'grid_resolution': s.grid_resolution, 'precip_variable': s.precip_variable,
            'precip_units': s.precip_units, 'hindcast_frequency': s.hindcast_frequency,
            'initialization_scheme': s.initialization_scheme,
            'availability_status': s.availability_status,
            'evidence_hindcast_start': status_evidencia(s, 'hindcast_start'),
            'evidence_hindcast_end': status_evidencia(s, 'hindcast_end'),
            'evidence_hindcast_members': status_evidencia(s, 'hindcast_members'),
            'source_reference': ' | '.join(s.source_reference), 'notes': s.notes,
        })
    return pd.DataFrame(linhas)


def common_period_json(sistemas=None):
    sistemas = sistemas if sistemas is not None else CATALOGO
    return periodo_comum_hindcast(sistemas)
