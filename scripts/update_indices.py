#!/usr/bin/env python3
"""
update_indices.py — Atualização automática de índices oceânicos
Sinobras Florestal · executado todo dia 21 às 12h BRT pelo GitHub Actions

Fontes (PSL/NOAA — públicas, sem autenticação, sem geobloqueio):
  Niño 3.4 mensal : https://psl.noaa.gov/data/correlation/nina34.data
  TSA mensal      : https://psl.noaa.gov/data/correlation/tsa.data
  PDO mensal      : https://psl.noaa.gov/data/correlation/pdo.data
  CPC weekly Niño : https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for

Calcula ONI (média móvel 3 meses do Niño 3.4) e atualiza docs/index.html.
"""

import re, json, sys
from pathlib import Path
from datetime import date, datetime
import urllib.request

ROOT      = Path(__file__).parent.parent
DASHBOARD = ROOT / 'docs' / 'index.html'

MISSING = -999.9   # valor usado pelo PSL para dado ausente

# ══════════════════════════════════════════════════════════════════════════
# 1. DOWNLOAD DAS SÉRIES PSL/NOAA
# ══════════════════════════════════════════════════════════════════════════

HEADERS = {
    'User-Agent': 'sinobras-clima/1.0 (github-actions; contato: github.com)',
    'Accept': 'text/plain, */*',
}

def fetch_psl(url: str, timeout: int = 20) -> str:
    """Baixa um arquivo texto do PSL/NOAA."""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='replace')


def parse_psl_annual(text: str) -> dict:
    """
    Parseia o formato PSL anual:
      YEAR  JAN  FEB  MAR  APR  MAY  JUN  JUL  AUG  SEP  OCT  NOV  DEC
      1950  0.1  0.2  ...
    Retorna {(ano, mes): valor} ignorando -999.9.
    """
    data = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 13:
            continue
        try:
            year = int(parts[0])
        except ValueError:
            continue
        if year < 1950 or year > date.today().year + 1:
            continue
        for m, val_s in enumerate(parts[1:13], start=1):
            try:
                val = float(val_s)
                if abs(val - MISSING) > 1:
                    data[(year, m)] = round(val, 2)
            except ValueError:
                pass
    return data


def fetch_cpc_weekly_nino34() -> tuple[str, float] | tuple[None, None]:
    """
    Lê o arquivo semanal do CPC (wksst9120.for) e extrai o valor
    mais recente do Niño 3.4.
    Retorna (label_semana, valor) ou (None, None) se falhar.
    """
    url = 'https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for'
    try:
        text = fetch_psl(url)
    except Exception as e:
        print(f"  ⚠ CPC semanal indisponível: {e}")
        return None, None

    # Formato: "04JAN1990   26.0  0.1  25.6  0.0  25.7  0.0  21.3  0.5"
    # Colunas: data, SST Niño1+2, anom, SST Niño3, anom, SST Niño34, anom, SST Niño4, anom
    lines = [l for l in text.splitlines() if len(l) > 30 and l[0].isdigit()]
    if not lines:
        return None, None
    last = lines[-1].split()
    try:
        label = last[0]          # ex: "15JUL2026"
        nino34_weekly = float(last[6])   # anomalia Niño 3.4 (coluna 7)
        return label, round(nino34_weekly, 2)
    except (IndexError, ValueError):
        return None, None


# ══════════════════════════════════════════════════════════════════════════
# 2. CALCULAR ONI (média móvel 3 meses)
# ══════════════════════════════════════════════════════════════════════════

def calc_oni(nino34: dict) -> dict:
    """
    ONI = média de 3 meses consecutivos do Niño 3.4.
    Retorna {(ano, mes_central): oni_value}.
    Nota: mes_central é o mês do meio do trimestre.
    """
    oni = {}
    for (y, m), v in nino34.items():
        # mês anterior e posterior
        ym1 = (y-1, 12) if m == 1  else (y, m-1)
        yp1 = (y+1,  1) if m == 12 else (y, m+1)
        if ym1 in nino34 and yp1 in nino34:
            oni[(y, m)] = round((nino34[ym1] + v + nino34[yp1]) / 3, 2)
    return oni


# ══════════════════════════════════════════════════════════════════════════
# 3. MONTAR ARRAYS PARA O DASHBOARD
# ══════════════════════════════════════════════════════════════════════════

def build_series(nino34: dict, tsa: dict,
                 weekly_label: str | None, weekly_val: float | None
                 ) -> dict:
    """
    Constrói os arrays labels/nino34/oni/tsa para o dashboard.
    Cobre jan/2023 → mês mais recente disponível.
    """
    TODAY = date.today()
    oni   = calc_oni(nino34)

    # Intervalo: jan/2023 até o mês atual (inclusive estimativa semanal)
    start_y, start_m = 2023, 1
    end_y,   end_m   = TODAY.year, TODAY.month

    labels_out  = []
    nino34_out  = []
    oni_out     = []
    tsa_out     = []

    y, m = start_y, start_m
    while (y, m) <= (end_y, end_m):
        # Label
        if m >= 6:   # jun em diante: "mm/yy" sem zero
            lbl = f"{m:02d}/{str(y)[2:]}"
        else:
            lbl = f"{m:02d}/{str(y)[2:]}"

        # Niño 3.4 mensal
        n34 = nino34.get((y, m))

        # Se é o mês atual e temos valor semanal recente, usar
        if n34 is None and weekly_val is not None:
            if y == TODAY.year and m == TODAY.month:
                n34 = weekly_val

        # ONI
        o = oni.get((y, m))

        # TSA
        t = tsa.get((y, m))

        labels_out.append(f'"{lbl}"')
        nino34_out.append(str(n34) if n34 is not None else 'null')
        oni_out.append(str(o)   if o   is not None else 'null')
        tsa_out.append(str(t)   if t   is not None else 'null')

        # Avançar mês
        if m == 12: y, m = y+1, 1
        else:        m += 1

    return {
        'labels': labels_out,
        'nino34': nino34_out,
        'oni':    oni_out,
        'tsa':    tsa_out,
    }


def latest_value(series: dict, key: str) -> tuple[str, float] | tuple[None, None]:
    """Retorna (label, valor) do último não-null da série."""
    labels = series['labels']
    vals   = series[key]
    for lbl, v in zip(reversed(labels), reversed(vals)):
        if v != 'null':
            return lbl.strip('"'), float(v)
    return None, None


# ══════════════════════════════════════════════════════════════════════════
# 4. ATUALIZAR O HTML
# ══════════════════════════════════════════════════════════════════════════

def update_html(series: dict, weekly_label: str | None,
                weekly_val: float | None) -> bool:
    """Aplica os novos índices ao docs/index.html. Retorna True se alterou."""
    html = DASHBOARD.read_text(encoding='utf-8')
    original = html

    # ── labels / nino34 / oni / tsa ──────────────────────────────────────
    html = re.sub(
        r'labels:\[[^\]]+\]',
        f'labels:[{",".join(series["labels"])}]',
        html
    )
    html = re.sub(
        r'nino34:\[([-\d.,\s]+)\]',
        f'nino34:[{",".join(series["nino34"])}]',
        html
    )
    html = re.sub(
        r'oni:\s*\[([-\d.,\s\wnull]+)\]',
        f'oni:   [{",".join(series["oni"])}]',
        html
    )
    html = re.sub(
        r'tsa:\s*\[([-\d.,\s\wnull]+)\]',
        f'tsa:   [{",".join(series["tsa"])}]',
        html
    )

    # ── D.now — cards do Monitor ENSO ────────────────────────────────────
    lbl_n34, val_n34 = latest_value(series, 'nino34')
    lbl_oni, val_oni = latest_value(series, 'oni')
    lbl_tsa, val_tsa = latest_value(series, 'tsa')

    # Preferir valor semanal para Niño 3.4 se mais recente
    if weekly_val is not None and weekly_label is not None:
        # Converter label "15JUL2026" para "jul/2026"
        try:
            dt = datetime.strptime(weekly_label, '%d%b%Y')
            lbl_n34 = dt.strftime(f'%m/%Y').lstrip('0') or '0'
            lbl_n34_display = dt.strftime('%-m/%Y') if sys.platform != 'win32' \
                              else dt.strftime('%m/%Y').lstrip('0')
            val_n34 = weekly_val
            lbl_n34 = dt.strftime('%b/%Y').lower()[:3] + '/' + str(dt.year)
        except Exception:
            pass

    def fmt_lbl(lbl):
        """Formata label para exibição: '06/2026' → 'jun/2026'."""
        meses = ['jan','fev','mar','abr','mai','jun',
                 'jul','ago','set','out','nov','dez']
        try:
            parts = lbl.replace('"','').split('/')
            m_num = int(parts[0])
            return f"{meses[m_num-1]}/{parts[1]}"
        except Exception:
            return lbl

    if val_n34 is not None:
        lbl_n34_fmt = fmt_lbl(lbl_n34) if lbl_n34 else ''
    if val_oni is not None:
        lbl_oni_fmt = fmt_lbl(lbl_oni) if lbl_oni else ''
    if val_tsa is not None:
        lbl_tsa_fmt = fmt_lbl(lbl_tsa) if lbl_tsa else ''

    old_now = re.search(r'now:\s*\{[^}]+\}', html)
    if old_now and val_n34 is not None:
        TODAY = date.today()
        new_now = (
            'now: {\n'
            f'    nino34: ["{lbl_n34_fmt}", {val_n34}],'
            f'   // Atualizado automaticamente {TODAY.strftime("%d/%m/%Y")}\n'
            f'    oni:    ["{lbl_oni_fmt}", {val_oni}],'
            f'   // ONI (média 3m Niño 3.4)\n'
            f'    tsa:    ["{lbl_tsa_fmt}", {val_tsa}]'
            f'    // TSA (último mensal disponível)\n'
            '  }'
        )
        html = html[:old_now.start()] + new_now + html[old_now.end():]

    # ── Data de atualização ───────────────────────────────────────────────
    TODAY = date.today()
    dt_str = TODAY.strftime('%d/%m/%Y')
    html = re.sub(r"data:\s*'[\d/]+'", f"data:       '{dt_str}'", html)
    html = re.sub(r"atualizado_em:\s*'[\d/]+'",
                  f"atualizado_em: '{dt_str}'", html)

    changed = html != original
    if changed:
        DASHBOARD.write_text(html, encoding='utf-8')
        print(f"  ✅ docs/index.html atualizado")
    else:
        print(f"  ℹ Nenhuma alteração detectada nos índices")
    return changed


# ══════════════════════════════════════════════════════════════════════════
# 5. MAIN
# ══════════════════════════════════════════════════════════════════════════

def main():
    TODAY = date.today()
    print(f"\n{'='*55}")
    print(f"  ATUALIZAÇÃO DE ÍNDICES — {TODAY.strftime('%d/%m/%Y')}")
    print(f"{'='*55}")

    # Baixar séries mensais
    print("\n[1/3] Baixando séries PSL/NOAA…")
    nino34_data, tsa_data = {}, {}

    try:
        text = fetch_psl('https://psl.noaa.gov/data/correlation/nina34.data')
        nino34_data = parse_psl_annual(text)
        last_n34 = max(nino34_data.keys())
        print(f"  ✅ Niño 3.4: {len(nino34_data)} meses "
              f"(último: {last_n34[1]:02d}/{last_n34[0]})")
    except Exception as e:
        print(f"  ❌ Niño 3.4 falhou: {e}")

    try:
        text = fetch_psl('https://psl.noaa.gov/data/correlation/tsa.data')
        tsa_data = parse_psl_annual(text)
        last_tsa = max(tsa_data.keys())
        print(f"  ✅ TSA: {len(tsa_data)} meses "
              f"(último: {last_tsa[1]:02d}/{last_tsa[0]})")
    except Exception as e:
        print(f"  ⚠ TSA falhou (não crítico): {e}")

    # Valor semanal mais recente
    print("\n[2/3] Buscando Niño 3.4 semanal (CPC)…")
    weekly_label, weekly_val = fetch_cpc_weekly_nino34()
    if weekly_val is not None:
        print(f"  ✅ Semanal: {weekly_label} = {weekly_val:+.2f}°C")
    else:
        print(f"  ⚠ Valor semanal indisponível")

    if not nino34_data:
        print("\n❌ Sem dados de Niño 3.4 — abortando")
        sys.exit(1)

    # Montar séries e atualizar HTML
    print("\n[3/3] Atualizando dashboard…")
    series  = build_series(nino34_data, tsa_data, weekly_label, weekly_val)
    changed = update_html(series, weekly_label, weekly_val)

    # Resumo
    lbl_n34, val_n34 = latest_value(series, 'nino34')
    lbl_oni, val_oni = latest_value(series, 'oni')
    lbl_tsa, val_tsa = latest_value(series, 'tsa')
    print(f"\n  Niño 3.4: {val_n34:+.2f}°C ({lbl_n34})")
    print(f"  ONI:      {val_oni:+.2f}°C ({lbl_oni})")
    if val_tsa:
        print(f"  TSA:      {val_tsa:+.2f}°C ({lbl_tsa})")

    print(f"\n{'='*55}")
    print(f"  CONCLUÍDO — alterações: {'sim' if changed else 'nenhuma'}")
    print(f"{'='*55}\n")
    return 0 if changed else 0


if __name__ == '__main__':
    sys.exit(main())
