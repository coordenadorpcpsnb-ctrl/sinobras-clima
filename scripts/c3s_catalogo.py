#!/usr/bin/env python3
"""
c3s_catalogo.py — Fase 2A, Seção 4: metadados dos sistemas C3S
("Seasonal forecast monthly statistics on single levels").

IMPORTANTE — como esta tabela foi montada: o ambiente desta sessão tem
acesso à internet geral (WebSearch/WebFetch), mas o proxy de rede
bloqueia explicitamente todos os domínios cds.climate.copernicus.eu,
ecmwf.int (e subdomínios, inclusive páginas de documentação/treinamento
em ecmwf-projects.github.io) e até wikipedia.org/ibge.gov.br para
WebFetch direto — só WebSearch (que roda num backend próprio) trouxe
resultado. Não foi possível abrir a página oficial do catálogo CDS nem
confirmar programaticamente (`cdsapi.Client().catalogue`) — o pacote
`cdsapi` está instalado, mas qualquer chamada real precisa de rede até
cds.climate.copernicus.eu, que está bloqueada nesta sessão (ver
c3s_download.py::verificar_acesso()).

Os dados abaixo vêm de busca textual (WebSearch), não de leitura direta
da página do catálogo — por isso os campos sem confirmação cruzada
independente estão marcados `None`/`'não verificado nesta sessão'` em
vez de inventados. SEAS5 (ECMWF) é o único sistema com specs
cross-confirmadas por 2+ fontes independentes (ver `fontes` de cada
entrada) — por isso é o único ESCOLHIDO nesta fase (Seção 4: critério é
cobertura/disponibilidade/documentação, nunca skill observado).

Para reconstruir/atualizar esta tabela com uma sessão que tenha acesso
real ao CDS:
    import cdsapi
    c = cdsapi.Client()
    # inspecionar o formulário do dataset via CDS Toolbox/API, ou:
    # https://cds.climate.copernicus.eu/datasets/seasonal-monthly-single-levels
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class SistemaC3S:
    centro: str
    sistema: str
    cds_system_code: str    # valor do campo "system" na API do CDS
    hindcast_start: Optional[int]
    hindcast_end: Optional[int]
    n_members_hindcast: Optional[int]
    n_members_forecast: Optional[int]
    max_lead_months: Optional[int]
    resolucao: Optional[str]
    verificado_cruzado: bool   # True só se >=2 fontes independentes concordam
    fontes: tuple = field(default_factory=tuple)
    notas: str = ''


CATALOGO = [
    SistemaC3S(
        centro='ECMWF', sistema='SEAS5', cds_system_code='51',
        hindcast_start=1993, hindcast_end=2016,
        n_members_hindcast=25, n_members_forecast=51,
        max_lead_months=6,
        resolucao='1°x1° (grade CDS; nativo TCo319 ~36km)',
        verificado_cruzado=True,
        fontes=(
            'NOAA PSL — psl.noaa.gov/forecasts/s2s_C3S_monthly_to_seasonal/description/ '
            '(lista de sistemas C3S, período de hindcast comum 1993-2016)',
            'MDPI Climate 10(9):128 — "Evaluation of ECMWF-SEAS5 Seasonal Temperature and '
            'Precipitation Predictions over South America" (25 membros, grade 1°x1°, '
            '"6 lead times: mês de inicialização + 5 meses seguintes")',
            'ECMWF forum — forum.ecmwf.int/t/definition-of-lead-time-and-monthly-averaged/2076 '
            '(confirma leadtime_month=1 == mês de inicialização)',
        ),
        notas='Operacional desde nov/2017. Fonte de notícia da ECMWF cita "até 7 meses à frente" '
              'para o produto operacional completo — o dataset monthly-single-levels do CDS usado '
              'aqui tem 6 leadtime_months documentados de forma cross-confirmada (M mesmo mês + 5). '
              'Único sistema com validação publicada especificamente para a América do Sul '
              'encontrada nesta sessão — motivo adicional para a escolha, além da cobertura/'
              'documentação (a validação em si não foi usada como critério de skill, só como sinal '
              'de que a comunidade científica já usa esse sistema nesta região).',
    ),
    SistemaC3S(
        centro='UKMO', sistema='GloSea6-GC5.1', cds_system_code='610',
        hindcast_start=None, hindcast_end=None,
        n_members_hindcast=None, n_members_forecast=None,
        max_lead_months=None, resolucao=None,
        verificado_cruzado=False,
        fontes=('NOAA PSL — lista o código de sistema, sem detalhar hindcast/membros/resolução',),
        notas='Atualizado para GC5.1 em abr/2026 segundo o mesmo resultado de busca — sistema em '
              'transição recente, specs não confirmadas nesta sessão. Candidato a 2º sistema numa '
              'fase futura com acesso real ao CDS.',
    ),
    SistemaC3S(
        centro='METFR', sistema='System9', cds_system_code='9',
        hindcast_start=None, hindcast_end=None,
        n_members_hindcast=None, n_members_forecast=None,
        max_lead_months=None, resolucao=None,
        verificado_cruzado=False,
        fontes=('NOAA PSL',), notas='System9 adicionado em ago/2026 segundo a busca — muito recente, '
                                     'sem hindcast longo documentado nesta sessão.',
    ),
    SistemaC3S(
        centro='CMCC', sistema='SPS4', cds_system_code='4',
        hindcast_start=None, hindcast_end=None,
        n_members_hindcast=None, n_members_forecast=None,
        max_lead_months=None, resolucao=None,
        verificado_cruzado=False, fontes=('NOAA PSL',),
        notas='SPS4 adicionado em ago/2026 segundo a busca — mesmo caso de System9.',
    ),
    SistemaC3S(
        centro='DWD', sistema='GCFS2.2', cds_system_code='22',
        hindcast_start=None, hindcast_end=None,
        n_members_hindcast=None, n_members_forecast=None,
        max_lead_months=None, resolucao=None,
        verificado_cruzado=False, fontes=('NOAA PSL',), notas='',
    ),
    SistemaC3S(
        centro='BOM', sistema='ACCESS-S2', cds_system_code='2',
        hindcast_start=None, hindcast_end=None,
        n_members_hindcast=None, n_members_forecast=None,
        max_lead_months=None, resolucao=None,
        verificado_cruzado=False, fontes=('NOAA PSL',),
        notas='ACCESS-S2 adicionado em ago/2026 segundo a busca.',
    ),
    SistemaC3S(
        centro='NCEP', sistema='CFSv2', cds_system_code='2',
        hindcast_start=None, hindcast_end=None,
        n_members_hindcast=None, n_members_forecast=None,
        max_lead_months=None, resolucao=None,
        verificado_cruzado=False, fontes=('NOAA PSL',), notas='',
    ),
    SistemaC3S(
        centro='ECCC', sistema='GEM5.2-NEMO', cds_system_code='5',
        hindcast_start=None, hindcast_end=None,
        n_members_hindcast=None, n_members_forecast=None,
        max_lead_months=None, resolucao=None,
        verificado_cruzado=False, fontes=('NOAA PSL',), notas='',
    ),
    SistemaC3S(
        centro='ECCC', sistema='CanESM5.1p1bc', cds_system_code='4',
        hindcast_start=None, hindcast_end=None,
        n_members_hindcast=None, n_members_forecast=None,
        max_lead_months=None, resolucao=None,
        verificado_cruzado=False, fontes=('NOAA PSL',), notas='',
    ),
]

SISTEMA_ESCOLHIDO_FASE_2A = ('ECMWF', 'SEAS5')


def sistema_por_nome(centro, sistema):
    for s in CATALOGO:
        if s.centro == centro and s.sistema == sistema:
            return s
    raise KeyError(f"sistema não encontrado no catálogo: {centro}/{sistema}")


def sistemas_verificados():
    """Só os sistemas com specs cross-confirmadas por >=2 fontes
    independentes — critério objetivo de 'estabilidade/documentação'
    (Seção 4), não de skill."""
    return [s for s in CATALOGO if s.verificado_cruzado]


def tabela_resumo():
    """DataFrame (Seção 4: 'criar uma tabela')."""
    import pandas as pd
    return pd.DataFrame([{
        'centro': s.centro, 'sistema': s.sistema, 'cds_system_code': s.cds_system_code,
        'hindcast_start': s.hindcast_start, 'hindcast_end': s.hindcast_end,
        'n_members_hindcast': s.n_members_hindcast, 'n_members_forecast': s.n_members_forecast,
        'max_lead_months': s.max_lead_months, 'resolucao': s.resolucao,
        'verificado_cruzado': s.verificado_cruzado,
    } for s in CATALOGO])


if __name__ == '__main__':
    import pandas as pd
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 160)
    print(tabela_resumo().to_string(index=False))
    print(f"\nSistema escolhido para a Fase 2A: {SISTEMA_ESCOLHIDO_FASE_2A}")
