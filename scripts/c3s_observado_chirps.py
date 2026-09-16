#!/usr/bin/env python3
"""
c3s_observado_chirps.py — Fase 2A, Seção 7: observação CHIRPS para os 3
municípios (São Bento do Tocantins, Araguatins, Ananás), independente da
série regional Sinobras (que só entra depois, como validação operacional
adicional — não usada aqui).

Reaproveita _chirps.py::_geometria_ponto/_buscar_prec_chirps_geom (mesmo
núcleo usado pela produção) com as coordenadas de _c3s_utils.py::MUNICIPIOS
em vez do ponto único das fazendas Sinobras — nada em _chirps.py precisou
mudar.

PROVA DE CONCEITO (Seção 18): busca só um período recente (não o
histórico completo de hindcast de ~30 anos) — o objetivo aqui é validar
a extração ponto-a-ponto para os 3 municípios, não popular o hindcast
inteiro. Expandir para o período completo é trabalho de uma fase
seguinte, uma vez que o pipeline C3S em si tenha acesso real ao CDS
(ver c3s_download.py) para ter algo com que comparar.
"""

import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from _c3s_utils import MUNICIPIOS  # noqa: E402
from _chirps import _geometria_ponto, _buscar_prec_chirps_geom  # noqa: E402

ROOT = Path(__file__).parent.parent
OUT = ROOT / 'data' / 'c3s_observado_chirps_poc.csv'

# Prova de conceito: últimos ~10 anos, suficiente para validar a extração
# e já dar uma amostra observacional real por município.
PERIODO_POC = (2015, 1, 2024, 12)


def buscar_municipio(chave, ano_ini, mes_ini, ano_fim, mes_fim):
    info = MUNICIPIOS[chave]
    geom = _geometria_ponto(info['lat'], info['lon'])
    ini = f'{mes_ini:02d}/01/{ano_ini}'
    fim = f'{mes_fim:02d}/01/{ano_fim}'   # dia exato não importa para o agregado mensal
    df = _buscar_prec_chirps_geom(ini, fim, geom, rotulo=chave)
    if not df.empty:
        df['local'] = chave
    return df


def main():
    ano_ini, mes_ini, ano_fim, mes_fim = PERIODO_POC
    partes = []
    for chave in MUNICIPIOS:
        print(f"\n=== {MUNICIPIOS[chave]['nome_exibicao']} ({chave}) ===")
        df = None
        for tentativa in range(3):
            df = buscar_municipio(chave, ano_ini, mes_ini, ano_fim, mes_fim)
            if not df.empty:
                break
            print(f"  falhou, tentativa {tentativa+1}/3, aguardando 15s…")
            time.sleep(15)
        if df is None or df.empty:
            print(f"  DESISTINDO de {chave} nesta rodada")
            continue
        partes.append(df)
        print(f"  OK: {len(df)} meses")

    if not partes:
        print("\nNenhum município retornou dado — nada gravado.")
        return

    final = pd.concat(partes, ignore_index=True).sort_values(['local', 'ano', 'mes'])
    final.to_csv(OUT, index=False)
    print(f"\n✅ {OUT.relative_to(ROOT)} — {len(final)} linhas, "
          f"{final['local'].nunique()} município(s)")


if __name__ == '__main__':
    main()
