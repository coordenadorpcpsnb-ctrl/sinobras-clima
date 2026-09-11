#!/usr/bin/env python3
"""
_farm_geometry.py — geometria das fazendas Sinobras (data/fazendas.geojson)
Compartilhado por _chirps.py (zonal via ClimateSERV) e o caminho de
download direto do CHC + rasterstats.

data/fazendas.geojson é um único polígono (Fazendas_v2.kmz, fornecido
pela Sinobras) — envelope das 37 fazendas, SEM identificação individual
(sem nome, id ou cluster de fazenda). Não é um convex hull matemático
(tem concavidades) nem a união exata dos 37 perímetros reais — é o
contorno que a empresa forneceu para uso externo/relatório, área
85.020,5 ha (maior que a união dissolvida dos 37 perímetros reais,
48.737,3 ha, porque preenche as reentrâncias entre fazendas).

Antes deste arquivo usava os 37 polígonos nomeados em 7 grupos
geográficos desconectados, uma chamada ao ClimateSERV por grupo. Com
uma única geometria não há mais o que agrupar: uma chamada cobre tudo.
"""

from pathlib import Path
import json

import pyproj
from shapely.geometry import shape, Polygon
from shapely.ops import transform

ROOT = Path(__file__).parent.parent
FAZENDAS_PATH = ROOT / 'data' / 'fazendas.geojson'

# UTM 23S — zona correta para a longitude das fazendas (~47-48°W).
# Só para calcular área em hectares; a geometria usada nas chamadas
# de API continua em WGS84.
_TO_UTM = pyproj.Transformer.from_crs('EPSG:4326', 'EPSG:32723', always_xy=True).transform

MAX_PONTOS_ANEL = 100


def carregar_fazendas():
    """Retorna o FeatureCollection cru de data/fazendas.geojson."""
    with open(FAZENDAS_PATH, encoding='utf-8') as f:
        return json.load(f)


def poligono():
    """
    Geometria (shapely Polygon) do envelope das fazendas, em WGS84 —
    única feature de data/fazendas.geojson.
    """
    gj = carregar_fazendas()
    return shape(gj['features'][0]['geometry'])


def area_ha():
    """Área do polígono em hectares (reprojetado para UTM 23S)."""
    return round(transform(_TO_UTM, poligono()).area / 10000, 1)


def anel_simplificado(max_pontos=MAX_PONTOS_ANEL, tolerancia_inicial=0.001):
    """
    Anel externo do polígono (list[[lon,lat],...]), pronto para a API
    do ClimateSERV — que só aceita um anel de polígono simples por
    chamada, sem holes.

    O polígono atual (26 vértices) já cabe folgadamente sob
    `max_pontos` sem precisar simplificar. A simplificação adaptativa
    (Douglas-Peucker, tolerância crescente) fica como salvaguarda caso
    data/fazendas.geojson seja substituído por uma geometria mais
    detalhada no futuro — ver _simplificar_ate_caber para o motivo do
    limite (testado ao vivo contra o ClimateSERV: anéis acima de ~150
    vértices falham por complexidade, não por tamanho de URL).

    Retorna (anel, erro_area_pct).
    """
    poly = poligono()
    exterior = list(poly.exterior.coords)
    if len(exterior) <= max_pontos:
        anel = [[round(lon, 6), round(lat, 6)] for lon, lat, *_ in exterior]
        return anel, 0.0
    return _simplificar_ate_caber(poly, tolerancia_inicial, max_pontos)


def _simplificar_ate_caber(poly, tolerancia_inicial, max_pontos):
    """
    Simplifica `poly` (Polygon) até o anel externo ter no máximo
    `max_pontos` vértices, aumentando a tolerância progressivamente.

    Retorna (anel, erro_area_pct) — anel já validado (buffer(0) se a
    simplificação + arredondamento de coordenadas reintroduzir
    auto-interseção: simplify() garante anel válido ANTES de
    arredondar, mas arredondar pra 6 casas pode colapsar vértices
    quase-coincidentes e reintroduzir auto-interseção DEPOIS — validar
    só depois de arredondar, não antes).
    """
    area_original = poly.area
    tol = tolerancia_inicial
    anel = None
    for _ in range(8):
        simplificado = poly.simplify(tol, preserve_topology=True)
        exterior = list(simplificado.exterior.coords)
        anel = [[round(lon, 6), round(lat, 6)] for lon, lat, *_ in exterior]

        poly_final = Polygon(anel)
        if not poly_final.is_valid:
            poly_final = poly_final.buffer(0)
            if poly_final.geom_type == 'MultiPolygon':
                poly_final = max(poly_final.geoms, key=lambda p: p.area)
            anel = [[round(lon, 6), round(lat, 6)] for lon, lat, *_ in poly_final.exterior.coords]

        if len(anel) <= max_pontos:
            erro_pct = abs(Polygon(anel).area - area_original) / area_original * 100
            return anel, erro_pct
        tol *= 1.6

    erro_pct = abs(Polygon(anel).area - area_original) / area_original * 100
    return anel, erro_pct
