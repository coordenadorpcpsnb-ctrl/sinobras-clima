#!/usr/bin/env python3
"""
update_indices.py — Atualização automática de índices oceânicos
Sinobras Florestal · executado todo dia 21 às 13h BRT pelo GitHub Actions

Fontes PSL/NOAA (públicas, sem autenticação):
  CPC sstoi.indices  : https://www.cpc.ncep.noaa.gov/data/indices/sstoi.indices
  PSL nina34.data    : https://psl.noaa.gov/data/correlation/nina34.data
  PSL tsa.data       : https://psl.noaa.gov/data/correlation/tsa.data
  CPC wksst9120.for  : https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for
"""

import re, sys, shutil
from pathlib import Path
from datetime import date, datetime
import urllib.request
import pandas as pd

ROOT      = Path(__file__).parent.parent
DASHBOARD = ROOT / 'docs' / 'index.html'
MISSING   = -999.9

HEADERS = {
    'User-Agent': 'sinobras-clima/1.0 (github-actions)',
    'Accept'    : 'text/plain, */*',
}

# ══════════════════════════════════════════════════════
# DOWNLOAD
# ══════════════════════════════════════════════════════
def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='replace')


# ══════════════════════════════════════════════════════
# PARSERS
# ══════════════════════════════════════════════════════
def parse_sstoi(text):
    """
    CPC sstoi.indices — colunas fixas:
    YR MON NINO1+2 ANOM NINO3 ANOM NINO4 ANOM NINO3.4 ANOM34
    Retorna {(ano, mes): nino34_anomalia}
    """
    data = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 10:
            continue
        try:
            y, m = int(parts[0]), int(parts[1])
            v = float(parts[9])          # ANOM34
            # anomalia do Niño 3.4 nunca passa de ~3°C — abs(v) > 5 indica
            # coluna errada (ex.: SST absoluta em vez de anomalia)
            if 1950 <= y <= 2030 and abs(v - MISSING) > 1 and abs(v) <= 5:
                data[(y, m)] = round(v, 2)
        except (ValueError, IndexError):
            pass
    return data


# Sentinelas de dado ausente conhecidas nos arquivos de correlação do
# PSL — cada arquivo usa a sua própria convenção (ex.: tsa.data usa
# -99.99, pdo.data usa -9.90). Descartadas explicitamente por valor E
# pelo limite físico abaixo: a lista fixa sozinha é frágil — um
# sentinela novo dentro da faixa física passaria batido.
PSL_SENTINELS = (-99.99, -9.99, -9.90, -999.9)


def parse_psl_anual(text):
    """
    PSL nina34.data / tsa.data / pdo.data — formato real:
        anoIni anoFim         ← linha de cabeçalho (2 tokens, ignorada)
        YYYY v1 v2 ... v12    ← ano e os 12 valores mensais NA MESMA linha
    Descarta sentinelas de ausência conhecidas (PSL_SENTINELS) e, como
    segunda barreira, qualquer valor com abs(v) > 5 (anomalia física
    nunca chega nessa magnitude — pega sentinelas ainda não catalogadas).
    Retorna {(ano, mes): valor}
    """
    data = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 13:
            continue
        try:
            y = int(parts[0])
        except ValueError:
            continue
        if not (1900 <= y <= 2100):
            continue
        for m, vs in enumerate(parts[1:13], start=1):
            try:
                v = float(vs)
            except ValueError:
                continue
            if any(abs(v - s) < 0.01 for s in PSL_SENTINELS):
                continue
            if abs(v) > 5:
                continue
            data[(y, m)] = round(v, 2)
    return data


def parse_wksst(text):
    """
    CPC wksst9120.for — linhas com data + duas colunas por região
    (SST absoluta, depois anomalia):
    DDMMMYYYY  SST1+2 ANOM1+2  SST3 ANOM3  SST34 ANOM34  SST4 ANOM4
       idx 0     1      2       3    4       5     6      7    8
    Retorna (label_str, nino34_anom) do registro mais recente.
    """
    ultimo_lbl, ultimo_val = None, None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 9:
            continue
        try:
            datetime.strptime(parts[0], '%d%b%Y')  # valida data
            v = float(parts[6])                     # ANOM34 (0-indexed col 6)
            # anomalia do Niño 3.4 nunca passa de ~3°C — abs(v) > 5 indica
            # coluna errada (ex.: SST absoluta em vez de anomalia)
            if abs(v) > 5:
                continue
            ultimo_lbl = parts[0]
            ultimo_val = round(v, 2)
        except (ValueError, IndexError):
            pass
    return ultimo_lbl, ultimo_val


# ══════════════════════════════════════════════════════
# ONI
# ══════════════════════════════════════════════════════
def calc_oni(nino34):
    """Média móvel de 3 meses centrada no mês do meio."""
    oni = {}
    for (y, m), v in nino34.items():
        ym1 = (y - 1, 12) if m == 1  else (y, m - 1)
        yp1 = (y + 1,  1) if m == 12 else (y, m + 1)
        if ym1 in nino34 and yp1 in nino34:
            oni[(y, m)] = round((nino34[ym1] + v + nino34[yp1]) / 3, 2)
    return oni


# ══════════════════════════════════════════════════════
# MONTAR ARRAYS PARA O DASHBOARD
# ══════════════════════════════════════════════════════
def build_series(nino34, tsa, wk_lbl, wk_val):
    TODAY = date.today()
    oni   = calc_oni(nino34)

    # Jan/2023 até mês atual inclusive
    labels_o, n34_o, oni_o, tsa_o = [], [], [], []
    y, m = 2023, 1
    while (y, m) <= (TODAY.year, TODAY.month):
        lbl = f'"{m:02d}/{str(y)[2:]}"'
        n34 = nino34.get((y, m))
        # mês atual sem dado mensal: usar semanal se disponível
        if n34 is None and wk_val is not None:
            if y == TODAY.year and m == TODAY.month:
                n34 = wk_val
        o   = oni.get((y, m))
        t   = tsa.get((y, m))

        labels_o.append(lbl)
        n34_o.append(str(n34) if n34 is not None else 'null')
        oni_o.append(str(o)   if o   is not None else 'null')
        tsa_o.append(str(t)   if t   is not None else 'null')

        m += 1
        if m > 12:
            y, m = y + 1, 1

    return {'labels': labels_o, 'nino34': n34_o, 'oni': oni_o, 'tsa': tsa_o}


def latest_non_null(series, key):
    for lbl, v in zip(reversed(series['labels']), reversed(series[key])):
        if v != 'null':
            return lbl.strip('"'), float(v)
    return None, None


def label_fmt(lbl):
    """'06/26' → 'jun/2026'"""
    meses = ['jan','fev','mar','abr','mai','jun',
             'jul','ago','set','out','nov','dez']
    try:
        mm, yy = lbl.split('/')
        return f"{meses[int(mm)-1]}/20{yy}"
    except Exception:
        return lbl


# ══════════════════════════════════════════════════════
# ATUALIZAR HTML
# ══════════════════════════════════════════════════════
def update_html(series, wk_lbl, wk_val):
    html = DASHBOARD.read_text(encoding='utf-8')
    original = html

    # ── Séries do Monitor ENSO ──────────────────────────────────────────
    # ATENÇÃO: operar SOMENTE dentro do bloco `indices:{...}`.
    # Um re.sub global em 'labels:[...]' também casaria dentro de
    # 'fc_labels:[...]' e de 'clim: { labels: [...] }', destruindo o eixo X
    # dos gráficos de previsão e de balanço hídrico.
    ini = html.find('indices:')
    if ini < 0:
        print('  ⚠ bloco indices: não encontrado — séries não atualizadas')
        return False
    fim = html.find('fc_labels:', ini)          # o bloco termina antes disto
    if fim < 0:
        fim = ini + 20000
    bloco = html[ini:fim]

    bloco = re.sub(r'labels:\[[^\]]+\]',
                   f'labels:[{",".join(series["labels"])}]', bloco, count=1)
    bloco = re.sub(r'nino34:\[[^\]]+\]',
                   f'nino34:[{",".join(series["nino34"])}]', bloco, count=1)
    bloco = re.sub(r'oni:\s*\[[^\]]+\]',
                   f'oni:   [{",".join(series["oni"])}]', bloco, count=1)
    bloco = re.sub(r'tsa:\s*\[[^\]]+\]',
                   f'tsa:   [{",".join(series["tsa"])}]', bloco, count=1)

    html = html[:ini] + bloco + html[fim:]

    # D.now — cards do Monitor ENSO
    lbl_n, val_n = latest_non_null(series, 'nino34')
    lbl_o, val_o = latest_non_null(series, 'oni')
    lbl_t, val_t = latest_non_null(series, 'tsa')

    # Preferir semanal para Niño 3.4 se mais recente que o mensal
    if wk_val is not None and wk_lbl is not None:
        try:
            dt = datetime.strptime(wk_lbl, '%d%b%Y')
            val_n = wk_val
            lbl_n = dt.strftime('%m/%y')
        except Exception:
            pass

    TODAY = date.today()
    if val_n is not None and val_o is not None:
        new_now = (
            'now: {\n'
            f'    nino34: ["{label_fmt(lbl_n)}", {val_n}],  '
            f'// Atualizado {TODAY.strftime("%d/%m/%Y")} — PSL/NOAA\n'
            f'    oni:    ["{label_fmt(lbl_o)}", {val_o}],  '
            f'// ONI (média 3m)\n'
            f'    tsa:    ["{label_fmt(lbl_t) if lbl_t else "—"}", '
            f'{val_t if val_t is not None else 0}]  '
            f'// TSA mensal\n'
            '  }'
        )
        old_now = re.search(r'now:\s*\{[^}]+\}', html)
        if old_now:
            html = html[:old_now.start()] + new_now + html[old_now.end():]

    # Data de atualização
    dt_str = TODAY.strftime('%d/%m/%Y')
    html = re.sub(r"data:\s*'[\d/]+'",       f"data:       '{dt_str}'", html)
    html = re.sub(r"atualizado_em:\s*'[\d/]+'",
                  f"atualizado_em: '{dt_str}'", html)

    changed = html != original
    if changed:
        DASHBOARD.write_text(html, encoding='utf-8')
    return changed


# ══════════════════════════════════════════════════════
# HISTÓRICO — master_monthly.csv e serie_subst.csv
# ══════════════════════════════════════════════════════
MASTER_PATH = ROOT / 'data' / 'master_monthly.csv'
SUBST_PATH  = ROOT / 'data' / 'serie_subst.csv'


def backup_csv(path):
    """Cópia .bak antes de qualquer escrita — sobrescreve o backup anterior."""
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + '.bak'))


def _tsa_persistido(tsa):
    """Último valor real de TSA disponível no dict, ou (None, None)."""
    chaves = sorted(tsa.keys())
    if not chaves:
        return None, None
    ult = chaves[-1]
    return tsa[ult], ult


def _pdo_estimado(pdo):
    """Média dos últimos 3 meses reais de PDO disponíveis no dict, ou None.
    Nunca o último valor isolado — um mês atípico não deve ser propagado
    como se fosse a característica do ano inteiro."""
    chaves = sorted(pdo.keys())
    if len(chaves) < 3:
        return None
    return round(sum(pdo[k] for k in chaves[-3:]) / 3, 2)


def atualizar_master_monthly(nino34, tsa, pdo):
    """
    Acrescenta a data/master_monthly.csv os meses com Niño 3.4 real
    disponível que ainda não constam na série. TSA/PDO ausentes usam
    persistência/estimativa (nunca zero), sinalizadas no log. Colunas
    que não vêm dessa fonte (estações, clim, anom, soi) ficam vazias —
    não inventadas.
    """
    df = pd.read_csv(MASTER_PATH)
    existentes = set(zip(df['year'].astype(int), df['month'].astype(int)))
    oni = calc_oni(nino34)

    tsa_val, tsa_key   = _tsa_persistido(tsa)
    pdo_media3         = _pdo_estimado(pdo)

    novas = []
    for (y, m) in sorted(nino34.keys()):
        if (y, m) in existentes:
            continue

        if (y, m) in tsa:
            t = tsa[(y, m)]
        elif tsa_val is not None:
            t = tsa_val
            print(f"  ⚠ master_monthly {m:02d}/{y}: TSA sem dado real — "
                  f"persistência de {tsa_key[1]:02d}/{tsa_key[0]} ({t})")
        else:
            t = None

        if (y, m) in pdo:
            p = pdo[(y, m)]
        elif pdo_media3 is not None:
            p = pdo_media3
            print(f"  ⚠ master_monthly {m:02d}/{y}: PDO sem dado real — "
                  f"estimativa (média 3m) = {p}")
        else:
            p = None

        novas.append({
            'year': y, 'month': m, 'date': f'{y}-{m:02d}-01',
            'nino34': nino34[(y, m)], 'oni': oni.get((y, m)),
            'tsa': t, 'pdo': p,
        })

    if not novas:
        return 0

    backup_csv(MASTER_PATH)
    df = pd.concat([df, pd.DataFrame(novas)], ignore_index=True, sort=False)
    df = df.sort_values(['year', 'month']).reset_index(drop=True)
    df.to_csv(MASTER_PATH, index=False)
    return len(novas)


def corrigir_serie_subst(nino34, tsa, pdo):
    """
    Corrige em data/serie_subst.csv as linhas já existentes com
    nino34=tsa=pdo=0 — resíduo do bug em que um mês ausente no master
    era gravado como ENSO neutro. Atualiza os índices no lugar,
    preservando prec, date e fonte. É esta série que treina o SARIMAX.
    """
    df = pd.read_csv(SUBST_PATH)
    tsa_val, tsa_key = _tsa_persistido(tsa)
    pdo_media3       = _pdo_estimado(pdo)

    zeradas = df[(df['nino34'] == 0) & (df['tsa'] == 0) & (df['pdo'] == 0)]
    corrigidas = 0
    linhas_tocadas = []
    for idx, row in zeradas.iterrows():
        y, m = int(row['ano']), int(row['mes'])
        if (y, m) not in nino34:
            continue  # sem Niño 3.4 real tampouco — não mexe

        if (y, m) in tsa:
            t = tsa[(y, m)]
        elif tsa_val is not None:
            t = tsa_val
            print(f"  ⚠ serie_subst {m:02d}/{y}: TSA sem dado real — "
                  f"persistência de {tsa_key[1]:02d}/{tsa_key[0]} ({t})")
        else:
            t = row['tsa']

        if (y, m) in pdo:
            p = pdo[(y, m)]
        elif pdo_media3 is not None:
            p = pdo_media3
            print(f"  ⚠ serie_subst {m:02d}/{y}: PDO sem dado real — "
                  f"estimativa (média 3m) = {p}")
        else:
            p = row['pdo']

        df.at[idx, 'nino34'] = nino34[(y, m)]
        df.at[idx, 'tsa']    = t
        df.at[idx, 'pdo']    = p
        corrigidas += 1
        linhas_tocadas.append(f'{m:02d}/{y}')

    if corrigidas:
        backup_csv(SUBST_PATH)
        df.to_csv(SUBST_PATH, index=False)
        print(f"  ✅ serie_subst.csv: corrigidas {', '.join(linhas_tocadas)}")
    return corrigidas


# ══════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════
def main():
    TODAY = date.today()
    print(f"\n{'='*55}")
    print(f"  ÍNDICES OCEÂNICOS — {TODAY.strftime('%d/%m/%Y')}")
    print(f"{'='*55}")

    nino34, tsa, pdo = {}, {}, {}

    # 1. CPC sstoi.indices (fonte primária — formato simples)
    print("\n[1/5] CPC sstoi.indices (primário)…")
    try:
        text   = fetch('https://www.cpc.ncep.noaa.gov/data/indices/sstoi.indices')
        nino34 = parse_sstoi(text)
        last   = max(nino34)
        print(f"  ✅ Niño 3.4: {len(nino34)} meses | último: {last[1]:02d}/{last[0]}")
    except Exception as e:
        print(f"  ⚠ sstoi.indices falhou: {e} — tentando PSL…")
        try:
            text   = fetch('https://psl.noaa.gov/data/correlation/nina34.data')
            nino34 = parse_psl_anual(text)
            last   = max(nino34)
            print(f"  ✅ PSL nina34: {len(nino34)} meses | último: {last[1]:02d}/{last[0]}")
        except Exception as e2:
            print(f"  ❌ Ambas as fontes falharam: {e2}")

    # 2. PSL tsa.data
    print("\n[2/5] PSL tsa.data…")
    try:
        text = fetch('https://psl.noaa.gov/data/correlation/tsa.data')
        tsa  = parse_psl_anual(text)
        last_t = max(tsa)
        print(f"  ✅ TSA: {len(tsa)} meses | último: {last_t[1]:02d}/{last_t[0]}")
    except Exception as e:
        print(f"  ⚠ TSA indisponível (não crítico): {e}")

    if not nino34:
        print("\n❌ Sem dados de Niño 3.4 — abortando")
        return 1

    # 3. PSL pdo.data
    print("\n[3/5] PSL pdo.data…")
    try:
        text = fetch('https://psl.noaa.gov/data/correlation/pdo.data')
        pdo  = parse_psl_anual(text)
        last_p = max(pdo)
        print(f"  ✅ PDO: {len(pdo)} meses | último: {last_p[1]:02d}/{last_p[0]}")
    except Exception as e:
        print(f"  ⚠ PDO indisponível (não crítico): {e}")

    # 4. CPC semanal
    print("\n[4/5] CPC wksst9120.for (semanal)…")
    wk_lbl, wk_val = None, None
    try:
        text = fetch('https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for')
        wk_lbl, wk_val = parse_wksst(text)
        if wk_val is not None:
            print(f"  ✅ Semanal: {wk_lbl} → {wk_val:+.2f}°C")
    except Exception as e:
        print(f"  ⚠ Semanal indisponível: {e}")

    # 5. Histórico — master_monthly.csv e serie_subst.csv
    print("\n[5/5] Atualizando histórico (master_monthly.csv / serie_subst.csv)…")
    n_master = atualizar_master_monthly(nino34, tsa, pdo)
    n_serie  = corrigir_serie_subst(nino34, tsa, pdo)
    print(f"  master_monthly.csv: {n_master} mês(es) adicionados")
    print(f"  serie_subst.csv: {n_serie} linha(s) corrigidas")

    # Montar e atualizar
    series  = build_series(nino34, tsa, wk_lbl, wk_val)
    changed = update_html(series, wk_lbl, wk_val)

    lbl_n, val_n = latest_non_null(series, 'nino34')
    lbl_o, val_o = latest_non_null(series, 'oni')
    lbl_t, val_t = latest_non_null(series, 'tsa')

    print(f"\n  Niño 3.4 : {val_n:+.2f}°C ({label_fmt(lbl_n)})")
    print(f"  ONI      : {val_o:+.2f}°C ({label_fmt(lbl_o)})")
    if val_t:
        print(f"  TSA      : {val_t:+.2f}°C ({label_fmt(lbl_t)})")
    if wk_val:
        print(f"  Semanal  : {wk_val:+.2f}°C ({wk_lbl})")

    print(f"\n  Alterações: {'sim' if changed else 'nenhuma'}")
    print(f"{'='*55}\n")
    return 0


if __name__ == '__main__':
    sys.exit(main())
