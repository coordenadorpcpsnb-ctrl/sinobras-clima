#!/usr/bin/env python3
"""
_farm_geometry.py — geometria das fazendas Sinobras (data/fazendas.geojson)
Compartilhado por _chirps.py (zonal via ClimateSERV) e o caminho de
download direto do CHC + rasterstats.

data/fazendas.geojson vem de FAZENDAS.kml (upload do usuário),
convertido e validado: 37 fazendas, área da união dissolvida ~48.737 ha
(bate com os ~48.000 ha esperados). Duas ressalvas do KML fonte,
documentadas em gj['properties'] e não corrigidas aqui:
  - Bacuri tinha auto-interseção — corrigida via buffer(0) na conversão.
  - 3R e NOSSA SENHORA APARECIDA se sobrepõem em ~1.649 ha — provável
    erro de digitalização no KML fonte; a área da união já não conta
    essa faixa em dobro, mas a sobreposição em si não foi corrigida.

As 37 fazendas formam 7 grupos geograficamente desconectados
(cluster_id 0-6, atribuído por área de interseção exata com a união
dissolvida — nunca por tolerância de distância, que gruda fazendas
próximas mas não tocantes num grupo errado e deixa outro órfão).
ClimateSERV só aceita um anel de polígono simples por chamada, então
cada grupo vira uma chamada própria; os 37 polígonos originais (com
suas sobreposições reais) são usados como estão no caminho de
rasterstats, que lida com geometria complexa nativamente.
"""

from pathlib import Path
import json

import pyproj
from shapely.geometry import shape, mapping, Polygon
from shapely.ops import unary_union, transform

ROOT = Path(__file__).parent.parent
FAZENDAS_PATH = ROOT / 'data' / 'fazendas.geojson'

# UTM 23S — zona correta para a longitude das fazendas (~47-48°W).
# Só para calcular área em hectares; a geometria usada nas chamadas
# de API continua em WGS84.
_TO_UTM = pyproj.Transformer.from_crs('EPSG:4326', 'EPSG:32723', always_xy=True).transform


def carregar_fazendas():
    """Retorna o FeatureCollection cru de data/fazendas.geojson."""
    with open(FAZENDAS_PATH, encoding='utf-8') as f:
        return json.load(f)


def poligono_completo():
    """
    Geometria (shapely) de todas as 37 fazendas, em WGS84, como estão
    no KML fonte — inclui a sobreposição 3R/NOSSA SENHORA APARECIDA.
    Uso: zonal stats via rasterstats, que soma peso de pixel por
    geometria de entrada e lida com múltiplos polígonos nativamente.
    """
    gj = carregar_fazendas()
    return [shape(f['geometry']) for f in gj['features']]


MAX_PONTOS_ANEL = 100


def _simplificar_ate_caber(dissolvido, tolerancia_inicial, max_pontos):
    """
    Simplifica `dissolvido` (Polygon) até o anel externo ter no máximo
    `max_pontos` vértices, aumentando a tolerância progressivamente.

    Por que: testado ao vivo contra o ClimateSERV — um anel de 161
    vértices falha (resposta vazia, sem status HTTP claro — não é
    limite de tamanho de URL, a query string fica em ~5KB, bem abaixo
    de qualquer limite comum), 72 vértices funciona. O motor de zonal
    stats deles parece ter um teto de complexidade de polígono, não só
    de bytes da URL. max_pontos=100 dá margem folgada abaixo de onde
    ele começa a falhar.

    Retorna (anel, erro_area_pct) — anel já validado (buffer(0) se a
    simplificação + arredondamento de coordenadas reintroduzir
    auto-interseção; ver nota abaixo).
    """
    area_original = dissolvido.area
    tol = tolerancia_inicial
    for _ in range(8):
        simplificado = dissolvido.simplify(tol, preserve_topology=True)
        exterior = list(simplificado.exterior.coords)
        anel = [[round(lon, 6), round(lat, 6)] for lon, lat, *_ in exterior]

        # simplify() garante anel válido ANTES de arredondar — mas
        # arredondar pra 6 casas (~11cm) pode colapsar dois vértices
        # quase-coincidentes ou empurrar um vértice pra cima de uma
        # aresta vizinha, reintroduzindo auto-interseção. Isso não dá
        # erro aqui, mas faz o ClimateSERV falhar silenciosamente —
        # mesmo tratamento do self-intersection da Bacuri no KML fonte:
        # buffer(0) no anel JÁ ARREDONDADO (validar antes de arredondar
        # não adianta, o problema só aparece depois).
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


def grupos_geograficos(tolerancia_simplificacao=0.001, max_pontos_anel=MAX_PONTOS_ANEL):
    """
    Lista de grupos geográficos dissolvidos: cada um é a união das
    fazendas com o mesmo cluster_id, em WGS84 — um anel simples por
    grupo (sem holes, sem multipolygon), pronto para a API do
    ClimateSERV, que só aceita isso.

    O anel é simplificado (Douglas-Peucker, preserve_topology=True),
    com a tolerância aumentada adaptativamente até caber em
    `max_pontos_anel` vértices — ver _simplificar_ate_caber().

    Retorna list[dict] com: cluster_id, area_ha, n_fazendas, fazendas
    (nomes), geometry (shapely Polygon, NÃO simplificado — área e uso
    geral), anel (list[[lon,lat],...], simplificado, pronto para passar
    como geometry_coords ao ClimateSERV), erro_simplificacao_pct
    (diferença de área entre o anel simplificado e o original).
    """
    gj = carregar_fazendas()
    por_cluster = {}
    for feat in gj['features']:
        cid = feat['properties']['cluster_id']
        por_cluster.setdefault(cid, []).append(feat)

    grupos = []
    for cid in sorted(por_cluster):
        feats = por_cluster[cid]
        geoms = [shape(f['geometry']) for f in feats]
        dissolvido = unary_union(geoms)
        if dissolvido.geom_type != 'Polygon':
            raise ValueError(
                f'cluster_id {cid} não dissolveu num único Polygon '
                f'({dissolvido.geom_type}) — atribuição de cluster '
                f'inconsistente com a união real, precisa reconferir '
                f'data/fazendas.geojson')

        anel, erro_pct = _simplificar_ate_caber(
            dissolvido, tolerancia_simplificacao, max_pontos_anel)

        # área do POLÍGONO DISSOLVIDO, não a soma das fazendas do grupo:
        # o cluster 3R/NOSSA SENHORA APARECIDA tem ~1.649 ha de
        # sobreposição real entre as duas (ver nota no properties do
        # geojson) — somar as áreas individuais contaria essa faixa em
        # dobro. A área dissolvida é a área real do anel que vai pro
        # ClimateSERV, e é isso que importa pra ponderar entre grupos.
        area_ha = round(transform(_TO_UTM, dissolvido).area / 10000, 1)

        grupos.append({
            'cluster_id': cid,
            'area_ha': area_ha,
            'n_fazendas': len(feats),
            'fazendas': [f['properties']['fazenda'] for f in feats],
            'geometry': dissolvido,
            'anel': anel,
            'erro_simplificacao_pct': round(erro_pct, 2),
        })

    return grupos
