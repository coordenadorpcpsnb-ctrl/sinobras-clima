#!/usr/bin/env python3
"""
backfill_chirps_historico.py — EXECUÇÃO ÚNICA, não faz parte do pipeline.

Gerou data/chirps_1981_2025.csv: precipitação mensal do CHIRPS (UCSB,
via ClimateSERV) para o ponto das fazendas Sinobras (lat=-7.80,
lon=-47.95), 1981-2025, usada para medir o viés ERA5/CHIRPS vs. estações
Sinobras (ver CLAUDE.md, armadilha 7) e para decidir a migração de fonte
do fallback em fetch_monthly_data.py.

NÃO rodar de novo por rotina — é um backfill histórico, o cache já
gerado (data/chirps_1981_2025.csv) é o artefato que importa. Só rode
de novo se precisar reconstruir o cache do zero (ex.: CHIRPS reprocessou
uma versão mais recente do produto).

O ClimateSERV (climateserv.servirglobal.net) rejeita pedidos muito
longos numa única chamada síncrona (testado: 45 anos de uma vez falha
com "Error occurred while processing data request") — por isso o fetch
é quebrado em blocos de ~10 anos, com progresso salvo incrementalmente
a cada bloco.
"""

import time
from pathlib import Path

import pandas as pd

from _chirps import buscar_prec_chirps

ROOT = Path(__file__).parent.parent
OUT  = ROOT / 'data' / 'chirps_1981_2025.csv'

PERIODOS = [
    (1981, 1, 1990, 12),
    (1991, 1, 2000, 12),
    (2001, 1, 2010, 12),
    (2011, 1, 2020, 12),
    (2021, 1, 2025, 12),
]


def main():
    blocos = []

    for y_ini, m_ini, y_fim, m_fim in PERIODOS:
        print(f"\n=== Buscando {m_ini:02d}/{y_ini} a {m_fim:02d}/{y_fim} ===")
        mensal = None
        for tentativa in range(3):
            mensal = buscar_prec_chirps(y_ini, m_ini, y_fim, m_fim)
            if not mensal.empty:
                break
            print(f"  falhou, tentativa {tentativa+1}/3, aguardando 20s…")
            time.sleep(20)
        if mensal is None or mensal.empty:
            print(f"  DESISTINDO deste período: {m_ini:02d}/{y_ini} a {m_fim:02d}/{y_fim}")
            continue

        blocos.append(mensal[['ano', 'mes', 'prec']])
        print(f"  OK: {len(mensal)} meses")

        pd.concat(blocos, ignore_index=True).sort_values(['ano', 'mes']).to_csv(OUT, index=False)
        time.sleep(5)

    print(f"\nCONCLUÍDO — {OUT}")


if __name__ == '__main__':
    main()
