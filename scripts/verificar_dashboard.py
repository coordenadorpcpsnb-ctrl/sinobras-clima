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
  6. Plausibilidade física: nino34/oni/tsa (D.now e série completa) não
     excedem ~5°C em módulo — acima disso é SST absoluta, não anomalia
  7. Continuidade: data/serie_subst.csv não pode ter mês faltando entre
     o primeiro registro e o mês anterior ao atual — um buraco vira erro
     silencioso de alinhamento assim que algum código usar .shift()
     posicional sobre a série (o regressor de um mês passa a vir de
     outro mês). Checa até o mês anterior ao atual, não só até o último
     registro existente — uma lacuna que fica "pendurada" no fim da
     série (a série simplesmente parou de crescer) é tão perigosa
     quanto um buraco no meio, e ficaria invisível se só olhássemos
     entre primeiro e último registro.
  8. RONI vs ONI-aprox: se o card RONI existir no dashboard, os rótulos
     precisam deixar claro que é uma métrica diferente do ONI-aprox
     (média 3m do Niño 3.4 bruto) — reprova se o card ONI ficar com
     rótulo ambíguo ("ONI" puro) ao lado do RONI (ver CLAUDE.md
     armadilha 9).
"""

import re, sys, json
from datetime import date
from pathlib import Path
import numpy as np
import pandas as pd

ROOT      = Path(__file__).parent.parent
DASHBOARD = ROOT / 'docs' / 'index.html'
SERIE_SUBST = ROOT / 'data' / 'serie_subst.csv'

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


def checar_continuidade(serie, ate=None):
    """
    Retorna a lista de meses 'MM/AAAA' faltando entre o primeiro
    registro de `serie` (DataFrame com colunas 'ano'/'mes') e `ate`
    (tupla ano, mes) — por padrão, o mês anterior ao atual. Lista
    vazia = série contínua.

    Checar só até o ÚLTIMO REGISTRO EXISTENTE (em vez de até o mês
    anterior ao atual) deixaria passar batido uma lacuna "pendurada"
    no fim da série — ex.: CHIRPS cobre só parte de um pedido e o
    fallback falha para o resto, então a série simplesmente para de
    crescer sem nenhum registro "depois" para delimitar o buraco.
    Não tem como reproduzir esse caso testando só "entre primeiro e
    último" (ver tests/test_fetch_fallback.py, CoberturaParcialTestCase).

    Extraída para função própria para poder ser testada direto, sem
    precisar rodar main() inteiro contra um docs/index.html real.
    """
    if ate is None:
        hoje = date.today()
        ate = (hoje.year, hoje.month - 1) if hoje.month > 1 else (hoje.year - 1, 12)

    existentes = set(zip(serie['ano'].astype(int), serie['mes'].astype(int)))
    y, m = int(serie['ano'].iloc[0]), int(serie['mes'].iloc[0])
    y_fim, m_fim = ate
    lacunas = []
    while (y, m) <= (y_fim, m_fim):
        if (y, m) not in existentes:
            lacunas.append(f'{m:02d}/{y}')
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return lacunas


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

    # ── 8. plausibilidade física dos índices ENSO ───────────────────────
    # nino34/oni/tsa são anomalias (°C) — nunca ultrapassam ~3°C em módulo.
    # Um valor > 5°C indica bug de parsing (ex.: SST absoluta ~26-29°C
    # usada no lugar da anomalia).
    mnow = re.search(r'now:\s*\{([^}]+)\}', h)
    if mnow:
        bloco_now = mnow.group(1)
        implausiveis = []
        for nome in ['nino34', 'oni', 'tsa']:
            mv = re.search(rf'{nome}:\s*\[[^,]+,\s*(-?[\d.]+)\]', bloco_now)
            if mv:
                v = float(mv.group(1))
                if abs(v) > 5:
                    implausiveis.append(f'{nome}={v}')
        if implausiveis:
            erro('D.now com valor fisicamente implausível (anomalia > 5°C): '
                 + ', '.join(implausiveis))
        else:
            ok('D.now com índices ENSO fisicamente plausíveis')
    else:
        erro('D.now não encontrado para checagem de plausibilidade')

    mv = re.search(r'nino34:\s*\[([^\]]+)\]', blk_idx)
    if mv:
        fora = []
        for tok in mv.group(1).split(','):
            tok = tok.strip()
            if tok == 'null':
                continue
            try:
                v = float(tok)
            except ValueError:
                continue
            if abs(v) > 5:
                fora.append(v)
        if fora:
            erro(f'série nino34 com {len(fora)} valor(es) > 5°C em módulo (implausível): '
                 + ', '.join(f'{v:+.2f}' for v in fora[:5]))
        else:
            ok('série nino34 dentro da faixa física plausível (≤5°C)')

    # ── 9. continuidade de data/serie_subst.csv ──────────────────────────
    # .shift() em pandas opera por POSIÇÃO da linha, não por data — um mês
    # faltando desloca os lags de todo mundo depois dele sem erro visível.
    if not SERIE_SUBST.exists():
        erro('data/serie_subst.csv não encontrado')
    else:
        serie = pd.read_csv(SERIE_SUBST)
        lacunas = checar_continuidade(serie)
        m_ini, y_ini = int(serie['mes'].iloc[0]), int(serie['ano'].iloc[0])
        m_fim, y_fim = int(serie['mes'].iloc[-1]), int(serie['ano'].iloc[-1])
        if lacunas:
            erro(f'serie_subst.csv com mês(es) faltando entre {m_ini:02d}/{y_ini} '
                 f'e o mês anterior ao atual (último registro real: '
                 f'{m_fim:02d}/{y_fim}): ' + ', '.join(lacunas))
        else:
            ok(f'serie_subst.csv contínua até o mês anterior ao atual '
               f'({len(serie)} meses, {m_ini:02d}/{y_ini} → {m_fim:02d}/{y_fim})')

    # ── 10. RONI vs ONI-aprox — rótulos precisam distinguir as métricas ──
    # RONI (CPC, oficial, trimestral, subtrai a tendência de aquecimento
    # tropical) e ONI-aprox (calc_oni: média 3m do Niño 3.4 bruto) são
    # números diferentes para o mesmo trimestre — se aparecerem juntos
    # sem rótulo que os diferencie, dá pra ler um pelo outro (ver
    # CLAUDE.md armadilha 9).
    tem_roni = re.search(r'const RONI\s*=', h) is not None
    if tem_roni:
        card_oni_ambiguo  = re.search(r'card-title">\s*ONI\s*<span', h) is not None
        card_roni_label   = re.search(r'card-title">\s*RONI\b', h) is not None
        card_oni_qualific = re.search(r'card-title">\s*ONI\s+aprox', h) is not None
        if card_oni_ambiguo or not (card_roni_label and card_oni_qualific):
            erro('RONI presente no dashboard mas os rótulos não distinguem '
                 'claramente RONI de ONI-aprox — risco de confundir as duas métricas')
        else:
            ok('RONI e ONI-aprox com rótulos distintos')

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
