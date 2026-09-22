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
RODADA 1 DE INVESTIGAÇÃO (sessão original da Fase 2C.1)
═══════════════════════════════════════════════════════════════════════

Restrição de rede: `www.cpc.ncep.noaa.gov` respondeu (páginas HTML
gerais), mas NENHUMA das páginas alcançadas continha a tabela atual de
modelos/membros/período. Bloqueados para WebFetch direto:
`ftp.cpc.ncep.noaa.gov`, `iridl.ldeo.columbia.edu`, `www.gfdl.noaa.gov`,
`www.weather.gov`, `wpo.noaa.gov`, `eccc-msc.github.io`,
`climate-scenarios.canada.ca`, `agupubs.onlinelibrary.wiley.com`,
`doi.org`, `climatetoolbox.org`.

Achados citáveis, por fonte (todos via WebSearch, exceto o item 1, que
foi um PDF baixado e lido de primeira mão):

1. **Emerson LaJoie (CPC), CDPW nº47, out/2022** — slide 4: "CFSv2 24
   members / GEM_NEMO 10 members / CanCM4i 10 members / GFDL_FLOR 24
   members / NASA_GEOS5v2 4 members / NCAR_CCSM4 10 members" — geração
   ANTERIOR (pré-troca CanCM4i→CanESM5 etc.), mas CFSv2 e NASA_GEOS5v2
   não foram trocados de versão, e os valores de membros coincidem com
   os confirmados na Rodada 2 (ver abaixo).
2. climatetoolbox.org (snippet): troca de geração CanCM4i→CanESM5,
   GEM5-NEMO→GEM5.2-NEMO, adição de SPEAR/CESM1.
3. climate-scenarios.canada.ca/CanSIPS (snippet, ECCC): "CanSIPSv3 uses
   a 30-year seasonal hindcast with 20 ensemble members for each model
   ... from 1991 to 2020" — CanESM5/GEM5.2-NEMO.
4. IRIDL (título indexado): "GFDL-SPEAR HINDCAST 1991-2020 Monthly", 15
   membros, entrou no NMME em 06/fev/2021.
5. "Initialized Seasonal Prediction with the NCAR Models in NMME",
   Weather and Forecasting v.40 n.6 (2025): período comum do TRIO
   CCSM3/CCSM4/CESM1 = 1991-2018 (não CCSM4/CESM1 isoladamente).
6. IRIDL — paths de catálogo indexados: `.Models/.NMME/.GFDL-SPEAR/
   .HINDCAST/.MONTHLY/`, `.Models/.NMME/.NCAR-CESM1/.HINDCAST/.MONTHLY/`,
   `.Models/.NMME/.CanSIPS-IC3/.GEM5-NEMO/.HINDCAST/.MONTHLY/.sst` (nota
   grafia "GEM5-NEMO" sem ".2", distinta da documentação textual).

═══════════════════════════════════════════════════════════════════════
RODADA 2 DE INVESTIGAÇÃO (revisão de auditabilidade pré-PR) — nova
evidência trazida por revisão externa + verificação desta sessão
═══════════════════════════════════════════════════════════════════════

A revisão externa apontou o **NOAA CPC NMME3 Operational User Manual**
(`ftp.cpc.ncep.noaa.gov/CPC/ID/figs/USER_MANUAL.html`) como fonte
oficial documentando, para os 7 candidatos, hindcast 1991-2020 e os
mesmos números de membros já reunidos na Rodada 1 (CFSv2=24,
CanESM5=20, GEM5.2_NEMO=20, GFDL_SPEAR=15, NCAR_CCSM4=10, NCAR_CESM1=10,
NASA_GEOS5v2=4), além de documentar `prate` como a variável conceitual
de precipitação do produto NMME3 (unidades `mm/day` ou `kg m-2 s-1`).

**Tentativa de verificação nesta sessão**: `ftp.cpc.ncep.noaa.gov`
permanece BLOQUEADO para WebFetch direto (mesmo bloqueio da Rodada 1,
confirmado de novo por tentativa direta) — não foi possível abrir a URL
e ler o manual de primeira mão. Uma busca independente (WebSearch) por
"NMME3 Operational User Manual" não encontrou esse documento específico
nem confirmação textual adicional dele; encontrou, em vez disso, um uso
DIFERENTE e mais antigo do termo "NMME3" num documento CPC distinto
("NMME Review for 2020"): "NMME3, operating from 2014–2019, has seven
models including CFSv2, GEOS5, CM2.1, CanCM3, CanCM4, CM2.5-FLOR, and
CCSM4" — uma configuração de modelos completamente diferente da que a
revisão externa descreve. Essa ambiguidade de nomenclatura ("NMME3"
usado para duas gerações de modelos diferentes em documentos CPC
distintos) fica registrada aqui, não resolvida.

Apesar disso, os valores numéricos citados pela revisão externa
(membros por modelo) são EXATAMENTE os já reunidos independentemente na
Rodada 1 via LaJoie (CPC, fonte primária lida diretamente) — não há
contradição de valores, só a impossibilidade de abrir a URL específica
citada e uma ambiguidade de nomenclatura documental. Por isso os campos
`hindcast_start`/`hindcast_end`/`hindcast_members`/`precip_variable`
(conceitual) sobem para `DOCUMENTED` nesta rodada — nunca
`EMPIRICALLY_CONFIRMED` (nenhum arquivo de hindcast foi aberto).

Outros achados da Rodada 2 (todos via WebSearch, nenhum WebFetch direto
bem-sucedido a domínios novos):

- **Conjunto operacional "core" desde 08/jun/2025** (página "About
  NMME", citada pela revisão externa; corroborada por um WebSearch
  independente desta sessão que devolveu a mesma lista de 6 modelos):
  CFSv2, CanESM5, GEM5.2-NEMO, NCAR-CESM1, NCAR-CCSM4, NASA-GEOS-S2S-2
  — sem GFDL_SPEAR, e com "NASA-GEOS-S2S-2" no lugar de "NASA_GEOS5v2".
  O MESMO WebSearch também encontrou outra página CPC (produtos de
  monitoramento) listando 7 modelos INCLUINDO GFDL_SPEAR e
  NASA_GEOS5v2 (nomenclatura antiga) — confirmando que páginas CPC
  diferentes, nesta mesma época, descrevem conjuntos operacionais
  distintos. Isso é tratado aqui como fato registrado, NUNCA resolvido
  por inferência (Seção 3): `current_operational_name` fica com o nome
  citado pela página "About NMME" quando existe, e uma nota explícita
  quando páginas conflitam.
- **Diretório CPC FTP para hindcast em formato CPT**
  (`ftp.cpc.ncep.noaa.gov/International/nmme/monthly_nmme_hindcast_in_cpt_format/`,
  citado pela revisão externa com o padrão de nome de arquivo
  `cfsv2_precip_hcst_...`) — BLOQUEADO para WebFetch direto nesta
  sessão (mesmo domínio). O padrão de nome de arquivo citado (com
  "precip" explícito) é uma pista útil para uma rota CPC oficial
  prioritária (Seção 6), mas nenhuma listagem de diretório foi aberta
  de primeira mão — registrado como candidato de rota, não como
  endpoint confirmado.
- **IRI CanSIPS-IC3 FORECAST MONTHLY** (estrutura, não hindcast): um
  WebSearch desta sessão encontrou evidência estrutural de que o
  produto FORECAST do CanSIPS-IC3 usa variável `prec`, dimensões
  X/Y/L/M/S (convenção "ingrid" padrão), 20 membros, leads mensais,
  grade 1°. Isso é evidência da FAMÍLIA de modelo (CanESM5/GEM5.2-NEMO
  seguem a mesma convenção estrutural), mas — seguindo a instrução
  explícita da revisão — NUNCA assumido como o mesmo endpoint do
  HINDCAST: o path HINDCAST específico continua sem confirmação, e o
  único path HINDCAST realmente indexado para esta família
  (`.CanSIPS-IC3/.GEM5-NEMO/.HINDCAST/.MONTHLY/.sst`) mostra a variável
  `sst`, não `prec` — reforçando que a variável de um produto não pode
  ser assumida para outro sem confirmação própria.

Nenhum arquivo de dado (NetCDF/GRIB) foi baixado em nenhuma das duas
rodadas — só páginas/documentos de texto, dentro do que a tarefa
permite.
"""

from dataclasses import dataclass, field
from typing import Optional

# ══════════════════════════════════════════════════════════════════════════
# Seção 7/11 — matriz de evidência: todo campo crítico carrega um status.
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

# Seção 7/8 (correção pós-revisão) — acesso a dado, separado de
# disponibilidade científica: um modelo pode ser um CANDIDATO válido
# (retrospectiva documentada) e ainda assim não ter endpoint/variável/
# dimensões confirmados o bastante para um POC real executar sem
# adivinhar (Seção 7/8). CONFIRMED exige as 3 coisas ao mesmo tempo
# (endpoint do HINDCAST específico, variável de precipitação
# identificada NESSE endpoint, dimensões documentadas); PARTIAL quando
# só parte disso existe (ex.: endpoint do modelo conhecido mas variável
# de precipitação não confirmada nesse path); UNCONFIRMED quando nada
# disso existe.
DATA_ACCESS_CONFIRMED = 'CONFIRMED'
DATA_ACCESS_PARTIAL = 'PARTIAL'
DATA_ACCESS_UNCONFIRMED = 'UNCONFIRMED'
DATA_ACCESS_STATUS_VALIDOS = {DATA_ACCESS_CONFIRMED, DATA_ACCESS_PARTIAL, DATA_ACCESS_UNCONFIRMED}


@dataclass(frozen=True)
class SistemaNMME:
    centre: str                            # organização/centro contribuinte
    model_name: str                        # nome do sistema retrospectivo/hindcast documentado (Seção 3
                                            # — equivalente ao "hindcast_system_name" pedido na revisão)
    model_version: Optional[str]
    official_model_id: Optional[str]       # identificador em catálogos oficiais (ex.: path IRIDL)
    data_source: str                       # rota de dados PRINCIPAL investigada (Seção 9)
    data_url_template: Optional[str]       # padrão de URL só quando documentado; None se não (Seção 6)
    data_access_status: str                # CONFIRMED | PARTIAL | UNCONFIRMED (Seção 7/8, correção)
    current_operational_name: Optional[str]  # nome no conjunto operacional ATUAL (pode divergir do
                                              # nome do sistema retrospectivo — Seção 3, correção); None
                                              # quando o modelo não aparece claramente no rol operacional
                                              # corrente ou quando isso é ambíguo entre páginas CPC.
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

# Fonte comum da Rodada 2 (citada em vários source_reference abaixo) —
# extraída aqui para não repetir o texto inteiro em cada entrada.
_FONTE_NMME3_MANUAL = (
    'NOAA CPC "NMME3 Operational User Manual" (ftp.cpc.ncep.noaa.gov/CPC/ID/figs/USER_MANUAL.html), '
    'citado pela revisão externa com hindcast 1991-2020 e nº de membros por modelo. NÃO aberto de '
    'primeira mão nesta sessão (ftp.cpc.ncep.noaa.gov bloqueado para WebFetch direto, mesma restrição '
    'da Rodada 1) — DOCUMENTED via citação da revisão + coerência com os valores já reunidos '
    'independentemente na Rodada 1 (LaJoie/CPC), nunca EMPIRICALLY_CONFIRMED. Nota de nomenclatura: '
    'um WebSearch independente desta sessão encontrou o termo "NMME3" usado em outro documento CPC '
    '("NMME Review for 2020") para uma configuração de 2014-2019 com modelos diferentes (CFSv2/GEOS5/'
    'CM2.1/CanCM3/CanCM4/CM2.5-FLOR/CCSM4) — ambiguidade de nomenclatura registrada, não resolvida.'
)
_FONTE_ABOUT_NMME_JUN2025 = (
    'Página CPC "About NMME", citada pela revisão externa como descrevendo o conjunto operacional '
    '"core" desde 08/jun/2025 (CFSv2, CanESM5, GEM5.2-NEMO, NCAR-CESM1, NCAR-CCSM4, NASA-GEOS-S2S-2). '
    'Corroborada por WebSearch independente desta sessão, que devolveu a mesma lista de 6 modelos — '
    'mas o MESMO WebSearch também encontrou outra página CPC de monitoramento listando 7 modelos '
    'incluindo GFDL_SPEAR e NASA_GEOS5v2 (nomenclatura antiga) para aproximadamente a mesma época — '
    'páginas CPC distintas descrevendo conjuntos operacionais diferentes, não resolvido por inferência '
    '(Seção 3).'
)

# ══════════════════════════════════════════════════════════════════════════
# Seção 4/6/8 — os 7 candidatos investigados. NENHUM valor numérico
# aparece sem `source_reference` não-vazio (barreira em
# _validar_catalogo). Onde a investigação não permitiu confirmação
# (rede bloqueada), o campo fica `None`/status `UNCONFIRMED` — nunca
# inventado (Seção 6: "Quando uma informação não puder ser comprovada:
# usar None. Nunca inventar.").
# ══════════════════════════════════════════════════════════════════════════
CATALOGO = [
    SistemaNMME(
        centre='NOAA_NCEP', model_name='CFSv2', model_version=None, official_model_id=None,
        data_source='IRI Data Library (CFSv2 hindcast "legado" 1982+, PRATE) e/ou CPC FTP (arquivos '
                     'CPT-format, padrão "cfsv2_precip_hcst_..." — Seção 6/10) — nenhuma das duas rotas '
                     'tem endpoint específico confirmado nesta sessão para o hindcast 1991-2020 do '
                     'NMME3.',
        data_url_template=None,   # nenhum endpoint específico confirmado (nem IRI nem CPC FTP)
        data_access_status=DATA_ACCESS_UNCONFIRMED,
        current_operational_name='CFSv2',   # citado como core operacional em ambas as páginas CPC (Seção 3)
        hindcast_start=1991, hindcast_end=2020,
        hindcast_members=24, realtime_members=None,
        leads_available=(1, 2, 3, 4, 5, 6),
        grid_resolution=None, precip_variable='prate', precip_units=None,
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
            _FONTE_NMME3_MANUAL, _FONTE_ABOUT_NMME_JUN2025,
        ),
        notes='Seção 10 (correção pós-revisão): existe documentação IRI para um dataset CFSv2 hindcast '
              '"legado" (desde 1982, variável PRATE, 24-28 membros DEPENDENDO da organização histórica '
              'usada) que é POTENCIALMENTE DIFERENTE do hindcast 1991-2020/24-membros definido pelo '
              'NMME3 manual — os dois nunca devem ser misturados sem verificar como o CPC realmente '
              'constrói os 24 membros do produto NMME3 atual; o POC real precisa confirmar isso '
              'empiricamente na rota escolhida, não assumir que são o mesmo dataset. precip_variable='
              '"prate" é o nome CONCEITUAL documentado no manual NMME3 para o produto como um todo — '
              'o nome real da variável no arquivo específico que o POC abrir continua UNCONFIRMED '
              '(Seção 11).',
        evidence={'hindcast_members': DOCUMENTED, 'hindcast_start': DOCUMENTED, 'hindcast_end': DOCUMENTED,
                   'precip_variable': DOCUMENTED, 'realtime_members': UNCONFIRMED,
                   'grid_resolution': UNCONFIRMED, 'precip_units': UNCONFIRMED,
                   'initialization_scheme': UNCONFIRMED, 'data_url_template': UNCONFIRMED},
    ),
    SistemaNMME(
        centre='ECCC', model_name='CanESM5', model_version='CanESM5 (uma fonte cita "CanESM5.1" — '
                                                              'divergência de sufixo não resolvida)',
        official_model_id=None,
        data_source='IRI Data Library (NMME collection), catálogo CanSIPS-IC3',
        data_url_template=None,   # path exato do HINDCAST não confirmado — ver notes
        data_access_status=DATA_ACCESS_UNCONFIRMED,
        current_operational_name='CanESM5',   # citado na página "About NMME" 08/jun/2025 (Seção 3)
        hindcast_start=1991, hindcast_end=2020,
        hindcast_members=20, realtime_members=None,   # ver notes — esquema de 4 dias pode dobrar p/ 40
        leads_available=(1, 2, 3, 4, 5, 6),
        grid_resolution='1° (documentado para o produto FORECAST do CanSIPS-IC3, mesma família — Seção '
                          '9; NÃO confirmado para o HINDCAST especificamente)',
        precip_variable='prec (documentado para o produto FORECAST do CanSIPS-IC3, mesma família — '
                          'Seção 9; o único path HINDCAST desta família realmente indexado mostra a '
                          'variável "sst", não "prec" — NUNCA assumir que o HINDCAST usa o mesmo nome '
                          'sem confirmação própria)',
        precip_units=None,
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
            'WebSearch sobre estrutura do IRI CanSIPS-IC3 FORECAST MONTHLY: variável prec, dimensões '
            'X/Y/L/M/S, 20 membros, grade 1°, leads mensais (Seção 9 — evidência estrutural da '
            'FAMÍLIA de modelo, não do endpoint HINDCAST específico).',
            _FONTE_NMME3_MANUAL, _FONTE_ABOUT_NMME_JUN2025,
        ),
        notes='Substitui CanCM4i (Seção 21 — nunca concatenar as duas séries). Path IRIDL exato do '
              'HINDCAST não confirmado — só foi visto o path de GEM5-NEMO (mesma família CanSIPS-IC3), '
              'com variável "sst" (não precipitação). Nunca assumir a URL/variável do produto FORECAST '
              'como válida para o HINDCAST (Seção 9) — marcado data_access_status=UNCONFIRMED até o '
              'POC real confirmar o endpoint específico do hindcast.',
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
                           'variável indexada nesse path é "sst", não precipitação)',
        data_access_status=DATA_ACCESS_PARTIAL,   # endpoint do MODELO/HINDCAST conhecido, variável de
                                                    # precipitação NÃO confirmada nesse path específico
        current_operational_name='GEM5.2-NEMO',   # citado na página "About NMME" 08/jun/2025 (Seção 3)
        hindcast_start=1991, hindcast_end=2020,
        hindcast_members=20, realtime_members=None,
        leads_available=(1, 2, 3, 4, 5, 6),
        grid_resolution='1° (documentado para o produto FORECAST do CanSIPS-IC3, mesma família — Seção '
                          '9; NÃO confirmado para o HINDCAST especificamente)',
        precip_variable=None,   # path do HINDCAST mostrou "sst"; "prec" só confirmado no FORECAST (Seção 9)
        precip_units=None,
        hindcast_frequency='monthly',
        initialization_scheme='Mesma ressalva de CanESM5 sobre possível ensemble lagged de 4 dias no '
                               'forecast operacional (20→40) — não confirmada de primeira mão.',
        availability_status=STATUS_CANDIDATO,
        source_reference=(
            'WebSearch sobre climate-scenarios.canada.ca (ECCC) — mesma citação de CanESM5: hindcast '
            '20 membros/modelo, 1991-2020.',
            'WebSearch sobre catálogo IRIDL — título indexado ".Models/.NMME/.CanSIPS-IC3/.GEM5-NEMO/'
            '.HINDCAST/.MONTHLY/.sst" (variável mostrada foi sst, não precipitação — path real '
            'confirma o MODELO/HINDCAST, não a variável de precipitação).',
            'WebSearch sobre estrutura do IRI CanSIPS-IC3 FORECAST MONTHLY (Seção 9) — mesma nota de '
            'CanESM5: variável prec só confirmada no produto FORECAST, nunca assumida igual no HINDCAST.',
            _FONTE_NMME3_MANUAL, _FONTE_ABOUT_NMME_JUN2025,
        ),
        notes='Substitui GEM_NEMO (Seção 21 — nunca concatenar). Path IRIDL usa a grafia "GEM5-NEMO" '
              '(sem ".2"), enquanto a documentação textual da ECCC/CPC usa "GEM5.2-NEMO" — '
              'inconsistência de nomenclatura entre catálogo e documentação registrada, não resolvida; '
              'o POC real deve confirmar qual grafia o path realmente aceita. data_access_status='
              'PARTIAL (não CONFIRMED) porque falta a variável de precipitação confirmada NESSE path '
              'específico do hindcast (Seção 7/8) — o path em si aponta pro modelo certo, mas abrir '
              'esse path hoje mostraria sst, não precipitação, sem mais investigação.',
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
        data_access_status=DATA_ACCESS_PARTIAL,   # endpoint do modelo/hindcast conhecido; variável de
                                                    # precipitação não confirmada nesse path
        current_operational_name=None,   # NÃO listado no conjunto "core" da página "About NMME" desde
                                          # 08/jun/2025 (Seção 3) — ver notes; isso não exclui o
                                          # candidato histórico/retrospectivo (Seção 5).
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
            _FONTE_NMME3_MANUAL, _FONTE_ABOUT_NMME_JUN2025,
        ),
        notes='Substitui GFDL_FLOR (Seção 21 — sistema novo, não uma revisão do FLOR, nunca '
              'concatenar as duas séries). Entrou no NMME em 06/fev/2021 (data documentada). Seção 5 '
              '(correção pós-revisão): a página "About NMME" (08/jun/2025) não lista SPEAR no conjunto '
              '"core" operacional atual, mas o NMME3 manual documenta 15 membros/1991-2020 e outra '
              'página CPC de monitoramento ainda o inclui — status operacional atual E retrospectiva '
              'documentada são questões DISTINTAS; SPEAR permanece candidato histórico válido para o '
              'POC retrospectivo desta fase, o status operacional incerto não é motivo de exclusão.',
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
        data_access_status=DATA_ACCESS_UNCONFIRMED,
        current_operational_name='NCAR-CCSM4',   # citado na página "About NMME" 08/jun/2025 (Seção 3)
        hindcast_start=1991, hindcast_end=2020,
        hindcast_members=10, realtime_members=None,
        leads_available=(1, 2, 3, 4, 5, 6),
        grid_resolution=None, precip_variable='prate', precip_units=None,
        hindcast_frequency='monthly', initialization_scheme=None,
        availability_status=STATUS_CANDIDATO,
        source_reference=(
            'WebSearch sobre "Initialized Seasonal Prediction with the NCAR Models in NMME", Weather '
            'and Forecasting v.40 n.6 (2025), doi:10.1175/WAF-D-24-0123.1 (bloqueado para WebFetch '
            'direto): "the common period currently available for the three models [CCSM3, CCSM4, '
            'CESM1] ... 1991-2018" — cobre os 3 modelos NCAR juntos, período DIFERENTE do NMME3 manual '
            '(ver notes).',
            _FONTE_NMME3_MANUAL, _FONTE_ABOUT_NMME_JUN2025,
        ),
        notes='Seção 2 (correção pós-revisão): o NMME3 manual (citado pela revisão externa) documenta '
              '1991-2020 para os 7 candidatos, incluindo CCSM4 — usado aqui como a fonte principal do '
              'período (mais recente e mais específica ao produto NMME3 operacional). O artigo de 2025 '
              '(fonte independente desta sessão) cita 1991-2018 para o TRIO NCAR — um período '
              'ligeiramente mais curto e referente aos 3 modelos NCAR juntos, não necessariamente ao '
              'produto NMME3 hindcast isolado; essa divergência de 2 anos (2018 vs 2020) fica '
              'registrada, não resolvida — o POC real deve confirmar empiricamente qual janela o '
              'arquivo realmente cobre. precip_variable="prate" é conceitual (documentado no manual '
              'NMME3), nome real no arquivo específico continua UNCONFIRMED.',
        evidence={'hindcast_members': DOCUMENTED, 'hindcast_start': DOCUMENTED, 'hindcast_end': DOCUMENTED,
                   'precip_variable': DOCUMENTED, 'realtime_members': UNCONFIRMED,
                   'grid_resolution': UNCONFIRMED, 'precip_units': UNCONFIRMED,
                   'initialization_scheme': UNCONFIRMED, 'data_url_template': UNCONFIRMED},
    ),
    SistemaNMME(
        centre='NCAR', model_name='NCAR_CESM1', model_version='CESM1', official_model_id=None,
        data_source='IRI Data Library (NMME collection)',
        data_url_template='https://iridl.ldeo.columbia.edu/SOURCES/.Models/.NMME/.NCAR-CESM1/'
                           '.HINDCAST/.MONTHLY/ (sufixo de variável de precipitação ainda não '
                           'identificado — path visto na busca só mostrou a variável tsmx)',
        data_access_status=DATA_ACCESS_PARTIAL,   # endpoint do modelo/hindcast conhecido; variável de
                                                    # precipitação não confirmada nesse path (tsmx, não prec)
        current_operational_name='NCAR-CESM1',   # citado na página "About NMME" 08/jun/2025 (Seção 3)
        hindcast_start=1991, hindcast_end=2020,
        hindcast_members=10, realtime_members=None,
        leads_available=(1, 2, 3, 4, 5, 6),
        grid_resolution=None, precip_variable='prate', precip_units=None,
        hindcast_frequency='monthly',
        initialization_scheme='CESM1 usa CAM5 (atmosfera) — documentado (WebSearch sobre página NCAR) '
                               'que é uma evolução de CCSM4; nunca tratar CCSM4 e CESM1 como o mesmo '
                               'sistema (são dois candidatos distintos nesta lista, não uma sucessão '
                               'a concatenar).',
        availability_status=STATUS_CANDIDATO,
        source_reference=(
            'WebSearch sobre catálogo IRIDL — título indexado ".Models/.NMME/.NCAR-CESM1/.HINDCAST/'
            '.MONTHLY/tsmx" confirma que o path do MODELO/HINDCAST existe no catálogo (variável '
            'mostrada foi tsmx, não precipitação).',
            'WebSearch sobre "Initialized Seasonal Prediction with the NCAR Models in NMME" (2025) — '
            'mesma citação de período comum 1991-2018 usada em NCAR_CCSM4 (ver notes de NCAR_CCSM4 '
            'sobre a divergência com o NMME3 manual).',
            _FONTE_NMME3_MANUAL, _FONTE_ABOUT_NMME_JUN2025,
        ),
        notes='hindcast_members=10 e hindcast_start/end=1991/2020 agora DOCUMENTED via NMME3 manual '
              '(Seção 2 da correção) — antes desta rodada eram UNCONFIRMED, vindos só da especificação '
              'da tarefa. data_access_status=PARTIAL (não CONFIRMED): o path do hindcast é conhecido, '
              'mas a variável indexada nesse path é "tsmx" (temperatura), não precipitação — falta '
              'confirmar onde a variável de precipitação está dentro desse mesmo catálogo.',
        evidence={'hindcast_members': DOCUMENTED, 'hindcast_start': DOCUMENTED, 'hindcast_end': DOCUMENTED,
                   'data_url_template': DOCUMENTED, 'precip_variable': DOCUMENTED,
                   'realtime_members': UNCONFIRMED, 'grid_resolution': UNCONFIRMED,
                   'precip_units': UNCONFIRMED},
    ),
    SistemaNMME(
        centre='NASA', model_name='GEOS5v2', model_version='GEOS5v2', official_model_id=None,
        data_source='IRI Data Library (NMME collection) — padrão esperado, path exato não confirmado',
        data_url_template=None,
        data_access_status=DATA_ACCESS_UNCONFIRMED,
        # Seção 4 (correção pós-revisão): NUNCA afirmar GEOS5v2 == GEOS-S2S-2 automaticamente. A página
        # "About NMME" (08/jun/2025) cita "NASA-GEOS-S2S-2" no conjunto operacional core — registrado
        # aqui como o nome operacional ATUAL, mas como possível sucessão/nomenclatura diferente do
        # sistema retrospectivo documentado GEOS5v2, nunca como confirmação de equivalência. Se o
        # arquivo acessível no POC real vier identificado como "NASA_GEOS5v2", usar esse nome; se vier
        # como "GEOS-S2S-2", NÃO assumir equivalência sem metadata/documentação que prove que é a
        # mesma configuração (mesma lógica de versão da Seção 21, aplicada aqui como pergunta aberta,
        # não como fato resolvido).
        current_operational_name='NASA-GEOS-S2S-2 (possível sucessor de GEOS5v2 — NÃO confirmado como '
                                   'o mesmo sistema, ver notes/Seção 4)',
        hindcast_start=1991, hindcast_end=2020,
        hindcast_members=4, realtime_members=None,
        leads_available=(1, 2, 3, 4, 5, 6),
        grid_resolution=None, precip_variable='prate', precip_units=None,
        hindcast_frequency='monthly', initialization_scheme=None,
        availability_status=STATUS_CANDIDATO,
        source_reference=(
            'LaJoie (CPC), CDPW47, out/2022, slide 4: "NASA_GEOS5v2 4 members" (PDF lido de primeira '
            'mão nesta sessão).',
            _FONTE_NMME3_MANUAL, _FONTE_ABOUT_NMME_JUN2025,
        ),
        notes='hindcast_members=4 e hindcast_start/end=1991/2020 agora DOCUMENTED via NMME3 manual '
              '(coerente com LaJoie 2022, PDF lido de primeira mão). Seção 4/9 (correção pós-revisão): '
              'NUNCA tratar GEOS5v2 e GEOS-S2S-2 como o mesmo sistema sem confirmação — a página "About '
              'NMME" 08/jun/2025 cita "NASA-GEOS-S2S-2" no rol operacional atual, uma fonte secundária '
              'não-oficial encontrada na Rodada 1 já apontava essa mesma divergência de nome com outro '
              'nº de membros (10, não 4) — se forem sistemas DIFERENTES (sucessão real), misturar os '
              'dois seria o mesmo erro da Seção 21 para os outros modelos. Para a análise histórica '
              'usar SOMENTE a retrospectiva identificável no dataset como "NASA_GEOS5v2" — se o arquivo '
              'acessível vier como "GEOS-S2S-2", tratar como candidato NOVO a investigar, não como '
              'confirmação retroativa desta entrada.',
        evidence={'hindcast_members': DOCUMENTED, 'hindcast_start': DOCUMENTED, 'hindcast_end': DOCUMENTED,
                   'precip_variable': DOCUMENTED, 'model_version': UNCONFIRMED,
                   'realtime_members': UNCONFIRMED, 'grid_resolution': UNCONFIRMED,
                   'precip_units': UNCONFIRMED, 'initialization_scheme': UNCONFIRMED,
                   'data_url_template': UNCONFIRMED},
    ),
]


def sistema_por_nome(centre, model_name):
    for s in CATALOGO:
        if s.centre == centre and s.model_name == model_name:
            return s
    raise KeyError(f"sistema não encontrado no catálogo NMME: {centre}/{model_name}")


# ══════════════════════════════════════════════════════════════════════════
# Seção 8 (correção pós-revisão) — separa o catálogo CIENTÍFICO (todos os
# candidatos documentados, usado para o período comum/relatório) da
# lista EXECUTÁVEL do POC (só sistemas com endpoint+variável+dimensões
# confirmados o bastante para montar um request real sem adivinhar).
# Um modelo NUNCA sai do catálogo científico por faltar acesso — as duas
# listas são conceitos ortogonais (Seção 8: "nunca falhar em série
# apenas porque quatro modelos ainda têm endpoint não confirmado. Mas
# também nunca excluir um modelo por skill.").
# ══════════════════════════════════════════════════════════════════════════

def sistemas_poc_executaveis(catalogo=None):
    """Só entra na lista executável quem tem data_access_status=CONFIRMED
    (endpoint do HINDCAST + variável de precipitação NESSE endpoint +
    dimensões documentadas, todos ao mesmo tempo — Seção 7/8). Nesta
    rodada, NENHUM dos 7 candidatos atinge essa barra (o mais próximo,
    GEM5.2_NEMO/GFDL_SPEAR/NCAR_CESM1, tem o endpoint do modelo
    conhecido mas a variável de precipitação NÃO confirmada nesse path
    — PARTIAL, não CONFIRMED) — resultado esperado e honesto desta
    etapa, não um bug."""
    catalogo = catalogo if catalogo is not None else CATALOGO
    return [s for s in catalogo if s.data_access_status == DATA_ACCESS_CONFIRMED]


def sistemas_poc_nao_executaveis(catalogo=None):
    """Complemento de sistemas_poc_executaveis — cada entrada com o
    motivo (data_access_status) para auditoria (Seção 8/13)."""
    catalogo = catalogo if catalogo is not None else CATALOGO
    return [s for s in catalogo if s.data_access_status != DATA_ACCESS_CONFIRMED]


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
        if s.data_access_status not in DATA_ACCESS_STATUS_VALIDOS:
            raise ValueError(f"{chave}: data_access_status inválido: {s.data_access_status!r} "
                              f"(precisa ser um de {sorted(DATA_ACCESS_STATUS_VALIDOS)}).")
        if s.data_access_status == DATA_ACCESS_CONFIRMED and \
                (s.data_url_template is None or s.precip_variable is None):
            raise ValueError(f"{chave}: data_access_status=CONFIRMED exige data_url_template E "
                              f"precip_variable preenchidos (nunca confirmado por omissão, Seção 7/8).")
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
    defensável), `elegiveis`/`incompatibilidade` para auditoria, e
    `n_documented_models`/`n_empirically_confirmed_models` (Seção 2,
    correção pós-revisão — distinção explícita entre "documentado" e
    "confirmado empiricamente", nunca confundidos)."""
    elegiveis = {}
    incompatibilidade = {}
    inicios, fins = [], []
    n_empiricamente_confirmados = 0
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
        if status_ini in (EMPIRICALLY_CONFIRMED, DOCUMENTED_AND_CONFIRMED) and \
                status_fim in (EMPIRICALLY_CONFIRMED, DOCUMENTED_AND_CONFIRMED):
            n_empiricamente_confirmados += 1

    if not inicios:
        return {'common_start': None, 'common_end': None, 'elegiveis': elegiveis,
                'incompatibilidade': incompatibilidade, 'status': UNCONFIRMED,
                'n_documented_models': 0, 'n_empirically_confirmed_models': 0,
                'n_elegiveis': 0, 'n_total': len(sistemas)}

    common_start, common_end = max(inicios), min(fins)
    if common_start > common_end:
        incompatibilidade['interseccao'] = (f'sem sobreposição real: common_start ({common_start}) > '
                                             f'common_end ({common_end})')
        return {'common_start': None, 'common_end': None, 'elegiveis': elegiveis,
                'incompatibilidade': incompatibilidade, 'status': UNCONFIRMED,
                'n_documented_models': len(elegiveis), 'n_empirically_confirmed_models': 0,
                'n_elegiveis': len(elegiveis), 'n_total': len(sistemas)}

    return {'common_start': common_start, 'common_end': common_end, 'elegiveis': elegiveis,
            'incompatibilidade': incompatibilidade, 'status': DOCUMENTED,
            'n_documented_models': len(elegiveis),
            'n_empirically_confirmed_models': n_empiricamente_confirmados,
            'n_elegiveis': len(elegiveis), 'n_total': len(sistemas)}


def tabela_catalogo(sistemas=None):
    import pandas as pd
    sistemas = sistemas if sistemas is not None else CATALOGO
    linhas = []
    for s in sistemas:
        linhas.append({
            'centre': s.centre, 'model_name': s.model_name, 'model_version': s.model_version,
            'current_operational_name': s.current_operational_name,
            'official_model_id': s.official_model_id, 'data_source': s.data_source,
            'data_url_template': s.data_url_template, 'data_access_status': s.data_access_status,
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
