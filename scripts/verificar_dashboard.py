#!/usr/bin/env python3
"""
verificar_dashboard.py — Verificação de integridade antes de publicar
Sinobras Florestal · executado pelo GitHub Actions após os scripts de atualização

Falha (exit 1) se encontrar inconsistência, impedindo que um dashboard
quebrado chegue ao ar. Checa:

  1. Sintaxe: balanço de chaves do objeto D
  2. Comprimento: todas as séries do horizonte têm 12 elementos
  3. Alinhamento: climatologia e ETP batem com o mês de cada rótulo do eixo X
  4. Coerência física: o balanço hídrico é reprodutível a partir da
     precipitação projetada no mesmo eixo
  5. Monitor ENSO: labels e séries de índices com o mesmo comprimento
"""

import re, sys, json
from pathlib import Path
import numpy as np

ROOT      = Path(__file__).parent.parent
DASHBOARD = ROOT / 'docs' / 'index.html'

CLIM = {1:267.3, 2:282.3, 3:308.4, 4:220.4, 5:83.1,  6:15.6,
        7:6.4,   8:10.4,  9:41.7, 10:119.7, 11:159.2, 12:199.9}
ETP  = {1:116, 2:110, 3:115, 4:118, 5:125, 6:112,
        7:107, 8:120, 9:138, 10:145, 11:138, 12:122}
MESES_CAP = {'Jan':1,'Fev':2,'Mar':3,'Abr':4,'Mai':5,'Jun':6,
             'Jul':7,'Ago':8,'Set':9,'Out':10,'Nov':11,'Dez':12}
CAD = 100

falhas = []


def erro(msg):
    falhas.append(msg)
    print(f'  ❌ {msg}')


def ok(msg):
    print(f'  ✅ {msg}')


def solve_bh(prec, etp, cad=CAD, tol=1e-3, it=200):
    arm = cad
    for _ in range(it):
        prev, res = arm, []
        for P, E in zip(prec, etp):
            a = min(cad, prev + P - E) if P >= E else max(0, prev * np.exp(-(E - P) / cad))
            res.append(round(a, 2)); prev = a
        if abs(res[-1] - arm) < tol:
            break
        arm = res[-1]
    return res


def main():
    print(f"\n{'='*58}")
    print('  VERIFICAÇÃO DE INTEGRIDADE DO DASHBOARD')
    print(f"{'='*58}\n")

    if not DASHBOARD.exists():
        print('  ❌ docs/index.html não encontrado')
        return 1
    h = DASHBOARD.read_text(encoding='utf-8')

    # ── 1. estrutura do objeto D ────────────────────────────────────────
    i = h.find('\nconst D = {')
    e = h.find('\n};', i) + 3
    if i < 0 or e < 3:
        erro('objeto D não encontrado')
        return 1
    D = h[i:e]
    if D.count('{') != D.count('}'):
        erro(f'chaves desequilibradas em D ({D.count("{")} abre, {D.count("}")} fecha)')
    else:
        ok('estrutura do objeto D íntegra')

    # ── 2. eixo X do horizonte ──────────────────────────────────────────
    m = re.search(r'fc_labels:\[([^\]]+)\]', h)
    if not m:
        erro('fc_labels ausente')
        return 1
    lbl = [v.strip().strip('"\'') for v in m.group(1).split(',')]
    if len(lbl) != 12:
        erro(f'fc_labels tem {len(lbl)} rótulos — deveria ter 12. '
             'Provável substituição indevida por outro script.')
        return 1
    ok(f'fc_labels com 12 rótulos ({lbl[0]} → {lbl[-1]})')

    try:
        mh = [int(x[:2]) for x in lbl]
    except ValueError:
        erro(f'fc_labels em formato inesperado: {lbl[:3]}')
        return 1
    esp_clim = [CLIM[x] for x in mh]
    esp_etp  = [ETP[x]  for x in mh]

    # ── 3. séries alinhadas ao eixo ─────────────────────────────────────
    def serie(pat, txt=h):
        mm = re.search(pat, txt, re.DOTALL)
        return [float(v.strip().strip('"\'')) for v in mm.group(1).split(',')] if mm else None

    i_ch = h.find('BH_CLIM_HYD = {')
    blk  = h[i_ch:i_ch + 900] if i_ch > 0 else ''

    for nome, vals, esperado in [
        ('fc_clim',         serie(r'fc_clim:\[([^\]]+)\]'),               esp_clim),
        ('CLIM_WIN',        serie(r'const CLIM_WIN\s*=\s*\[([^\]]+)\]'),  esp_clim),
        ('ETP do gráfico',  serie(r'const etp = \[([^\]]+)\];'),          esp_etp),
        ('BH_CLIM_HYD.p',   serie(r'p:\s*\[([^\]]+)\]', blk),             esp_clim),
        ('BH_CLIM_HYD.etp', serie(r'etp:\s*\[([^\]]+)\]', blk),           esp_etp),
    ]:
        if vals is None:
            erro(f'{nome}: não encontrado')
        elif len(vals) != 12:
            erro(f'{nome}: {len(vals)} elementos (esperado 12)')
        elif not all(abs(a - b) <= 0.6 for a, b in zip(vals, esperado)):
            erro(f'{nome}: desalinhado do eixo X')
        else:
            ok(f'{nome} alinhado ao eixo')

    # ── 4. coerência do balanço hídrico ─────────────────────────────────
    bh_s = h.find('const BH = {')
    bh_e = h.find('\n\n/* ── BALANÇO HÍDRICO COMP', bh_s)
    bh   = h[bh_s:bh_e] if bh_s > 0 else ''
    etp_h = esp_etp

    cenarios = ['El Nino forte','El Nino moderado','El Nino fraco','Neutro',
                'La Nina fraca','La Nina moderada','La Nina forte']
    incoerentes = []
    for sc in cenarios:
        mp = re.search(rf'"{re.escape(sc)}":\{{prec:\[([^\]]+)\]', h)
        ma = re.search(rf"'{re.escape(sc)}':\s*\{{.*?arm:\s*(\[[^\]]+\])", bh, re.DOTALL)
        if not mp or not ma:
            erro(f'{sc}: prec ou arm ausente')
            continue
        prec = [float(v) for v in mp.group(1).split(',')]
        arm  = json.loads(ma.group(1))
        if len(prec) != 12 or len(arm) != 12:
            erro(f'{sc}: prec={len(prec)} arm={len(arm)} (esperado 12)')
            continue
        dif = max(abs(a - b) for a, b in zip(arm, solve_bh(prec, etp_h)))
        if dif > 1.0:
            incoerentes.append(f'{sc} ({dif:.0f} mm)')
    if incoerentes:
        erro('balanço hídrico não reproduz a precipitação: ' + ', '.join(incoerentes))
    else:
        ok(f'balanço hídrico coerente nos {len(cenarios)} cenários')

    # ── 5. climatologia da aba Clima ────────────────────────────────────
    ml = re.search(r"clim:.*?labels:\s*\[([^\]]+)\]", bh, re.DOTALL)
    mp = re.search(r'clim:.*?p:\s*(\[[^\]]+\])', bh, re.DOTALL)
    if ml and mp:
        lb = [v.strip().strip("'\"") for v in ml.group(1).split(',')]
        pv = json.loads(mp.group(1))
        if len(lb) != 12 or len(pv) != 12:
            erro(f'BH.clim: labels={len(lb)} p={len(pv)} (esperado 12)')
        elif not all(abs(a - CLIM[MESES_CAP[l]]) <= 0.6 for l, a in zip(lb, pv)):
            erro('BH.clim: precipitação desalinhada dos rótulos')
        else:
            ok('BH.clim alinhado (aba Clima)')

    # ── 6. Monitor ENSO ─────────────────────────────────────────────────
    ini = h.find('indices:')
    fim = h.find('fc_labels:', ini)
    blk_idx = h[ini:fim] if ini > 0 and fim > ini else ''
    mi = re.search(r'labels:\[([^\]]+)\]', blk_idx)
    if mi:
        n_lbl = len(mi.group(1).split(','))
        comp = {'labels': n_lbl}
        for nome in ['nino34', 'oni', 'tsa']:
            mm = re.search(rf'{nome}:\s*\[([^\]]+)\]', blk_idx)
            comp[nome] = len(mm.group(1).split(',')) if mm else 0
        if len(set(comp.values())) != 1:
            erro(f'Monitor ENSO com séries de tamanhos diferentes: {comp}')
        else:
            ok(f'Monitor ENSO consistente ({n_lbl} meses)')

    # ── 7. trimestres do Comparativo (CPC/IRI x SARIMAX) ────────────────
    # CPC_IRI.seasons é curado manualmente; se pedir um trimestre que o
    # SARIMAX_DATA não tem, o JS lança erro e a aba Comparativo não renderiza.
    msd = re.search(r'const SARIMAX_DATA\s*=\s*(\{.*?\});\n', h, re.DOTALL)
    mse = re.search(r'seasons:\s*\[([^\]]+)\]', h)
    if msd and mse:
        try:
            sd = json.loads(msd.group(1))
            disp = set(next(iter(sd['trimestres'].values())).keys())
            pedidos = [v.strip().strip("'\"") for v in mse.group(1).split(',')]
            faltando = [x for x in pedidos if x not in disp]
            if faltando:
                erro('CPC_IRI.seasons pede trimestres ausentes no SARIMAX_DATA: '
                     + ', '.join(faltando) + ' — a aba Comparativo vai quebrar')
            else:
                ok(f'trimestres do Comparativo completos ({len(pedidos)} seasons)')
        except Exception as ex:
            erro(f'não foi possível validar SARIMAX_DATA: {ex}')

    # ── resultado ───────────────────────────────────────────────────────
    print(f"\n{'='*58}")
    if falhas:
        print(f'  REPROVADO — {len(falhas)} problema(s)')
        print('  A publicação deve ser interrompida.')
        print(f"{'='*58}\n")
        return 1
    print('  APROVADO — dashboard íntegro e consistente')
    print(f"{'='*58}\n")
    return 0


if __name__ == '__main__':
    sys.exit(main())
