#!/usr/bin/env python3
"""
update_dashboard.py
Sinobras Florestal — Dashboard Clima Operacional
Executado automaticamente pelo GitHub Actions toda 3ª quinta-feira às 12:00 BRT.

Fluxo:
  1. Lê serie_subst.csv (base histórica atual)
  2. Se existir SINOBRAS_new.csv em data/, incorpora novos dados Sinobras
  3. Treina SARIMAX(N34+TSA+PDO) na série completa
  4. Gera cenários para o próximo ano hidrológico
  5. Recalcula BH Thornthwaite-Mather convergido
  6. Atualiza docs/index.html com todos os dados novos
  7. Grava bundle.json com snapshot dos dados para rastreabilidade
"""

import os, sys, re, json, warnings
from datetime import date, datetime
from pathlib import Path

import numpy  as np
import pandas as pd
warnings.filterwarnings('ignore')

from statsmodels.tsa.statespace.sarimax import SARIMAX

# ── Caminhos ──────────────────────────────────────────────────────────────
ROOT      = Path(__file__).parent.parent
DATA      = ROOT / 'data'
DOCS      = ROOT / 'docs'
DASHBOARD = DOCS / 'index.html'

SERIE_PATH   = DATA / 'serie_subst.csv'
MERRA_PATH   = DATA / 'master_monthly.csv'
NEW_SINOBRAS = DATA / 'SINOBRAS_new.csv'   # opcional: novos dados campo

CAD = 100
ETP_JAN_DEZ = [116,110,115,118,125,112,107,120,138,145,138,122]  # mm/mês
ETP_JUL_JUN = ETP_JAN_DEZ[6:] + ETP_JAN_DEZ[:6]
ETP_JUN_MAI = ETP_JAN_DEZ[5:] + ETP_JAN_DEZ[:5]

TODAY = date.today()
print(f"\n{'='*60}")
print(f"  ATUALIZAÇÃO DASHBOARD — {TODAY.strftime('%d/%m/%Y %H:%M')}")
print(f"{'='*60}")


# ══════════════════════════════════════════════════════════════════════════
# 1. INCORPORAR NOVOS DADOS SINOBRAS (se SINOBRAS_new.csv existir)
# ══════════════════════════════════════════════════════════════════════════
serie = pd.read_csv(SERIE_PATH)

if NEW_SINOBRAS.exists():
    print(f"\n[1/6] Incorporando {NEW_SINOBRAS.name}…")
    df_new = pd.read_csv(NEW_SINOBRAS, sep=';')
    reg_new = df_new.groupby(['ano','mes'])['prec_mm'].mean().reset_index()
    reg_new.columns = ['ano','mes','prec_sinobras']

    merra = pd.read_csv(MERRA_PATH, parse_dates=['date'])
    mer   = merra[['year','month','nino34','tsa','pdo']].copy()
    mer.columns = ['ano','mes','nino34','tsa','pdo']
    mer_idx = mer.set_index(['ano','mes'])

    # Meses novos não presentes na série atual
    existing = set(zip(serie['ano'].astype(int), serie['mes'].astype(int)))
    novos = []
    for _, r in reg_new.iterrows():
        ano, mes = int(r.ano), int(r.mes)
        if (ano, mes) not in existing:
            try:
                mi = mer_idx.loc[(ano,mes)]
                n34,tsa,pdo = float(mi['nino34']),float(mi['tsa']),float(mi['pdo'])
            except:
                n34,tsa,pdo = np.nan,np.nan,np.nan
            novos.append({'ano':ano,'mes':mes,'prec':round(float(r.prec_sinobras),2),
                          'fonte':'Sinobras','nino34':n34,'tsa':tsa,'pdo':pdo})

    if novos:
        df_novos = pd.DataFrame(novos)
        serie = pd.concat([serie, df_novos], ignore_index=True)\
                  .sort_values(['ano','mes']).reset_index(drop=True)
        serie.to_csv(SERIE_PATH, index=False)
        print(f"  ✅ {len(novos)} novos meses adicionados "
              f"({novos[0]['ano']}/{novos[0]['mes']:02d} → "
              f"{novos[-1]['ano']}/{novos[-1]['mes']:02d})")
        # Mover o arquivo processado para evitar reprocessamento
        NEW_SINOBRAS.rename(DATA / f"SINOBRAS_{TODAY.strftime('%Y%m')}.csv")
    else:
        print("  ℹ Nenhum mês novo encontrado no arquivo")
else:
    print(f"\n[1/6] Nenhum SINOBRAS_new.csv encontrado — usando série existente "
          f"({len(serie)} meses)")


# ══════════════════════════════════════════════════════════════════════════
# 2. FEATURE ENGINEERING
# ══════════════════════════════════════════════════════════════════════════
print("\n[2/6] Feature engineering…")
d = serie.copy()
d['pdo'] = d['pdo'].ffill().fillna(0)
for L in [2, 3]:
    d[f'n34_l{L}'] = d['nino34'].shift(L)
    d[f'tsa_l{L}'] = d['tsa'].shift(L)
    d[f'pdo_l{L}'] = d['pdo'].shift(L)
d['n34_l23'] = (d['n34_l2'] + d['n34_l3']) / 2
d['tsa_l23'] = (d['tsa_l2'] + d['tsa_l3']) / 2
d['pdo_l23'] = (d['pdo_l2'] + d['pdo_l3']) / 2
d = d.dropna(subset=['n34_l23','tsa_l23','pdo_l23']).reset_index(drop=True)
d['date2'] = pd.to_datetime(dict(year=d['ano'], month=d['mes'], day=1))
print(f"  Série: {len(d)} meses ({int(d.ano.min())}–{int(d.ano.max())})")


# ══════════════════════════════════════════════════════════════════════════
# 3. TREINAR SARIMAX NA SÉRIE COMPLETA
# ══════════════════════════════════════════════════════════════════════════
print("\n[3/6] Treinando SARIMAX(N34+TSA+PDO)…")
endog = pd.Series(d['prec'].values, index=pd.PeriodIndex(d['date2'], freq='M'))
exog  = pd.DataFrame({'n34_l23': d['n34_l23'].values,
                       'tsa_l23': d['tsa_l23'].values,
                       'pdo_l23': d['pdo_l23'].values}, index=endog.index)

res = SARIMAX(endog, exog=exog, order=(1,0,2), seasonal_order=(1,1,1,12),
              enforce_stationarity=False).fit(disp=False)

b1 = float(res.params.get('n34_l23', 0))
b2 = float(res.params.get('tsa_l23', 0))
b3 = float(res.params.get('pdo_l23', 0))
print(f"  β₁(N34)={b1:.4f}  β₂(TSA)={b2:.4f}  β₃(PDO)={b3:.4f}  AIC={res.aic:.1f}")


# ══════════════════════════════════════════════════════════════════════════
# 4. GERAR CENÁRIOS — horizonte: próximo ano hidrológico (jun → mai)
# ══════════════════════════════════════════════════════════════════════════
print("\n[4/6] Gerando cenários…")

n34_hist = pd.Series(d['nino34'].values, index=endog.index)
tsa_hist  = pd.Series(d['tsa'].values,   index=endog.index)
pdo_hist  = pd.Series(d['pdo'].values,   index=endog.index)
pdo_pers  = float(d['pdo'].iloc[-12:].mean())

# Horizonte: junho do ano corrente → maio do ano seguinte
# Se hoje já passou de junho, usar próximo junho
ano_base = TODAY.year if TODAY.month >= 6 else TODAY.year - 1
H_start  = pd.Period(f'{ano_base}-06', 'M')
# Último mês da série de treino como Period explícito
last_end  = pd.Period(str(endog.index[-1]), 'M')
first_fc  = last_end + 1                             # primeiro passo do forecast
# Calcular skip via ordinal — evita ambiguidade com MonthEnd offsets do pandas
skip      = H_start.ordinal - first_fc.ordinal       # passos a pular até jun
if skip < 0:
    # H_start já passou — avançar um ano
    ano_base += 1
    H_start   = pd.Period(f'{ano_base}-06', 'M')
    skip      = H_start.ordinal - first_fc.ordinal
total_fc  = skip + 12                                # total de passos gerados

print(f"  Horizonte: {H_start} → {H_start + 11}")
print(f"  Último mês treinado: {last_end}  →  skip={skip}, total={total_fc}")

# Niño 3.4 observado nos últimos meses (atualizado manualmente no bundle)
obs_n34 = {}  # preenchido pelos dados recentes do bundle/CPC
try:
    meta_old = json.loads((DATA / 'meta_best.json').read_text())
    # Extrair observações mais recentes se disponíveis
except:
    pass

def build_n34_path(A, obs=None):
    obs = obs or {}
    peak = pd.Period(f'{ano_base+1}-01', 'M').ordinal  # pico esperado em jan
    path = {}
    ext  = pd.period_range(f'{ano_base}-04', f'{ano_base+2}-06', freq='M')
    for p in ext:
        k = (p.year, p.month)
        if k in obs: path[k] = obs[k]; continue
        try:
            v = float(n34_hist[p])
            if not np.isnan(v): path[k] = v; continue
        except: pass
        dt = p.ordinal - peak
        v  = A * np.exp(-(dt**2)/(2*3.5**2)) if -8<=dt<=9 else 0.0
        path[k] = round(v, 3)
    return path

def gn34(p, path): return path.get((p.year,p.month), 0.0)
def gtsa(p):
    try: v=float(tsa_hist[p]); return v if not np.isnan(v) else 0.44
    except: return 0.44
def gpdo(p):
    try: v=float(pdo_hist[p]); return v if not np.isnan(v) else pdo_pers
    except: return pdo_pers

SCEN = {'El Nino forte':+2.0,'El Nino moderado':+1.25,'El Nino fraco':+0.75,
        'Neutro':0.0,'La Nina fraca':-0.75,'La Nina moderada':-1.25,
        'La Nina forte':-2.0,'IRI_mean':+1.35}

# Gerar exog para total_fc passos a partir de last_end+1
H_full = pd.period_range(last_end+1, periods=total_fc, freq='M')
H_want = H_full[skip:skip+12]   # os 12 meses do horizonte

results = {}
np.random.seed(42)
for name, A in SCEN.items():
    path     = build_n34_path(A, obs_n34)
    n34_fc   = np.array([(gn34(p-2,path)+gn34(p-3,path))/2 for p in H_full])
    tsa_fc   = np.array([(gtsa(p-2)+gtsa(p-3))/2             for p in H_full])
    pdo_fc   = np.array([(gpdo(p-2)+gpdo(p-3))/2             for p in H_full])
    n34_fc   = np.where(np.isnan(n34_fc), 0.0,      n34_fc)
    tsa_fc   = np.where(np.isnan(tsa_fc), 0.44,     tsa_fc)
    pdo_fc   = np.where(np.isnan(pdo_fc), pdo_pers, pdo_fc)

    ex_full = pd.DataFrame({'n34_l23':n34_fc,'tsa_l23':tsa_fc,'pdo_l23':pdo_fc},
                            index=H_full)
    fc   = res.get_forecast(steps=total_fc, exog=ex_full)
    mean = np.clip(fc.predicted_mean.values, 0, None)
    ci   = fc.conf_int(alpha=0.05).clip(lower=0)
    sims = np.clip(np.asarray(res.simulate(
        nsimulations=total_fc, repetitions=500,
        anchor='end', exog=ex_full)).reshape(total_fc,-1), 0, None)

    results[name] = {
        'labels': [f"{p.month:02d}/{str(p.year)[2:]}" for p in H_want],
        'prec':   mean[skip:skip+12].round(1).tolist(),
        'lo95':   ci.iloc[skip:skip+12,0].round(1).tolist(),
        'hi95':   ci.iloc[skip:skip+12,1].round(1).tolist(),
        'p5':     np.percentile(sims[skip:skip+12,:], 5,  axis=1).round(1).tolist(),
        'p95':    np.percentile(sims[skip:skip+12,:], 95, axis=1).round(1).tolist(),
        'n34':    [path.get((p.year,p.month), 0.0) for p in H_want],
    }

print(f"  ✅ {len(results)} cenários gerados")


# ══════════════════════════════════════════════════════════════════════════
# 5. BALANÇO HÍDRICO CONVERGIDO
# ══════════════════════════════════════════════════════════════════════════
print("\n[5/6] Calculando balanço hídrico…")

def solve_bh(prec_jul, etp_jul, cad=100, tol=0.001, max_iter=200):
    arm = cad
    for _ in range(max_iter):
        arm_prev = arm; res_bh = []
        for P, E in zip(prec_jul, etp_jul):
            if P >= E:
                arm_new = min(cad, arm_prev + P - E)
                etr=E; exc=max(0, arm_prev+P-E-cad); def_=0
            else:
                arm_new = max(0, arm_prev * np.exp(-(E-P)/cad))
                etr=P+arm_prev-arm_new; def_=E-etr; exc=0
            res_bh.append({'arm':round(arm_new,2),'etr':round(etr,2),
                            'def':round(def_,2),'exc':round(exc,2)})
            arm_prev = arm_new
        if abs(res_bh[-1]['arm']-arm)<tol: break
        arm = res_bh[-1]['arm']
    return res_bh

cenarios_bh = [s for s in SCEN if s != 'IRI_mean']
bh_results  = {}

for sc in cenarios_bh:
    prec_jm  = results[sc]['prec']           # jun→mai
    prec_jul = prec_jm[1:] + [prec_jm[0]]   # → jul→jun
    res_bh   = solve_bh(prec_jul, ETP_JUL_JUN)
    rjm      = [res_bh[-1]] + res_bh[:-1]   # → jun→mai
    def_t    = int(round(sum(r['def'] for r in rjm)))
    exc_t    = int(round(sum(r['exc'] for r in rjm)))
    bh_results[sc] = {
        'arm':[r['arm'] for r in rjm], 'etr':[r['etr'] for r in rjm],
        'def':[r['def'] for r in rjm], 'exc':[r['exc'] for r in rjm],
        'def_total':def_t, 'exc_total':exc_t,
    }

# Climatologia
anual_s   = serie.groupby('ano')['prec'].sum()
monthly_s = serie[serie['ano'].between(1981,2025)].groupby('mes')['prec']\
              .agg(['mean','std']).round(1)
cm  = monthly_s['mean'].tolist()
cs  = monthly_s['std'].tolist()
clim_jul = cm[6:] + cm[:6]
rc  = solve_bh(clim_jul, ETP_JUL_JUN)
rjm = [rc[-1]] + rc[:-1]

bh_final = {
    'cenarios':    bh_results,
    'clim':        {'p':[round(v,1) for v in cm[5:]+cm[:5]],'etp':ETP_JUN_MAI,
                    'etr':[r['etr'] for r in rjm],'def':[r['def'] for r in rjm],
                    'exc':[r['exc'] for r in rjm],'arm':[r['arm'] for r in rjm],
                    'def_total':int(round(sum(r['def'] for r in rjm))),
                    'exc_total':int(round(sum(r['exc'] for r in rjm)))},
    'etp_jd':ETP_JAN_DEZ, 'etp_jul':ETP_JUL_JUN, 'etp_jm':ETP_JUN_MAI,
}

print(f"  ✅ BH convergido — EN forte DEF={bh_results['El Nino forte']['def_total']}mm "
      f"EXC={bh_results['El Nino forte']['exc_total']}mm")


# ══════════════════════════════════════════════════════════════════════════
# 6. ATUALIZAR O DASHBOARD HTML
# ══════════════════════════════════════════════════════════════════════════
print("\n[6/6] Atualizando dashboard HTML…")

html = DASHBOARD.read_text(encoding='utf-8')
H_want_labels = results['Neutro']['labels']
clim_jun_mai  = [round(v,1) for v in cm[5:]+cm[:5]]

# Sumário de cenários
scen_data = pd.read_csv(DATA / 'scen12_best.csv') if (DATA/'scen12_best.csv').exists() else None
anual_c   = anual_s[anual_s.index.isin(range(1981,2026))]
P20 = float(np.percentile(anual_c, 20))
P80 = float(np.percentile(anual_c, 80))
rows = []
for sc in cenarios_bh:
    r     = results[sc]
    total = round(sum(r['prec']), 0)
    anom  = round((total/float(anual_c.mean())-1)*100, 1)
    np.random.seed(42)
    n_sim = 800
    tots  = []
    for _ in range(n_sim):
        tot = sum(max(np.random.normal(r['prec'][i],
                       max((r['p95'][i]-r['p5'][i])/3.28,1)),0)
                  for i in range(12))
        tots.append(tot)
    tots  = np.array(tots)
    rows.append({'cenario':sc,'total12m':total,'anom_pct':anom,
                 'lo95':round(float(np.percentile(tots,2.5)),0),
                 'hi95':round(float(np.percentile(tots,97.5)),0),
                 'p_seca':round(float((tots<P20).mean()*100),1),
                 'p_excesso':round(float((tots>P80).mean()*100),1)})
scen_df = pd.DataFrame(rows)
scen_df.to_csv(DATA / 'scen12_best.csv', index=False)

def sub(html, pattern, new_val, flags=0):
    return re.sub(pattern, new_val, html, count=1, flags=flags)

# D.annual
years = [int(y) for y in anual_c.index]
vals  = [round(float(anual_c[y]),1) for y in years]
ann   = (f'annual:{{years:{json.dumps(years)},vals:{json.dumps(vals)},'
         f'media:{round(float(np.mean(vals)),1)},dp:{round(float(np.std(vals)),1)},'
         f'cv:{round(float(np.std(vals)/np.mean(vals)*100),1)},'
         f'minimo:[{years[int(np.argmin(vals))]},{min(vals)}],'
         f'maximo:[{years[int(np.argmax(vals))]},{max(vals)}]}}')
html = sub(html, r'annual:\{years:.*?maximo:\[\d+,[\d.]+\]\}', ann, re.DOTALL)

# D.clim
html = sub(html, r'clim:\s*\{\s*mean:\[[^\]]+\],\s*std:\[[^\]]+\]\s*\}',
           f'clim:{{mean:{json.dumps(cm)},std:{json.dumps(cs)}}}')

# fc_labels / fc_clim / CLIM_WIN / CLIM_MON
html = re.sub(r'fc_labels:\[[^\]]+\]',     f'fc_labels:{json.dumps(H_want_labels)}', html)
html = re.sub(r'fc_clim:\[[^\]]+\]',       f'fc_clim:{json.dumps(clim_jun_mai)}',    html)
html = re.sub(r'const CLIM_WIN\s*=\s*\[[^\]]+\]',
              f'const CLIM_WIN = {json.dumps(clim_jun_mai)}', html)
html = re.sub(r'const CLIM_MON\s*=\s*\[[^\]]+\]',
              f'const CLIM_MON = {json.dumps(cm)}', html)

# D.fc mensal
fc_parts = []
for sc in cenarios_bh:
    dfc = results[sc]
    fc_parts.append(f'    "{sc}":{{prec:{json.dumps(dfc["prec"])},'
                    f'lo95:{json.dumps(dfc["lo95"])},hi95:{json.dumps(dfc["hi95"])},'
                    f'p5:{json.dumps(dfc["p5"])},p95:{json.dumps(dfc["p95"])}}}')
new_fc = '  fc:{\n' + ',\n'.join(fc_parts) + '\n  }'
fc_s = html.find('  fc:{\n    "El Nino forte"')
fc_e = html.find('\n  },\n  summary:', fc_s)
if fc_s>=0 and fc_e>=0:
    html = html[:fc_s] + new_fc + html[fc_e:]

# D.summary
sum_s = html.find('summary:{\n'); sum_e = html.find('\n  }', sum_s) + 4
parts = [f'    "{r.cenario}":{{tot:{r.total12m},anom:{r.anom_pct},'
         f'lo:{r.lo95},hi:{r.hi95},pseca:{r.p_seca},pexc:{r.p_excesso}}}'
         for _, r in scen_df.iterrows()]
html = html[:sum_s] + 'summary:{\n' + ',\n'.join(parts) + '\n  }' + html[sum_e:]

# SARIMAX_DATA
TRI={'AMJ':[(ano_base,4),(ano_base,5),(ano_base,6)],
     'MJJ':[(ano_base,5),(ano_base,6),(ano_base,7)],
     'JJA':[(ano_base,6),(ano_base,7),(ano_base,8)],
     'JAS':[(ano_base,7),(ano_base,8),(ano_base,9)],
     'ASO':[(ano_base,8),(ano_base,9),(ano_base,10)],
     'SON':[(ano_base,9),(ano_base,10),(ano_base,11)],
     'OND':[(ano_base,10),(ano_base,11),(ano_base,12)],
     'NDJ':[(ano_base,11),(ano_base,12),(ano_base+1,1)],
     'DJF':[(ano_base,12),(ano_base+1,1),(ano_base+1,2)]}
ab = str(ano_base)[2:]; ab1 = str(ano_base+1)[2:]
tri_keys = [f'AMJ/{ab}',f'MJJ/{ab}',f'JJA/{ab}',f'JAS/{ab}',f'ASO/{ab}',
            f'SON/{ab}',f'OND/{ab}',f'NDJ/{ab}',f'DJF/{ab1}']

def ym_idx(y, m):
    lbl = f"{m:02d}/{str(y)[2:]}"
    return H_want_labels.index(lbl) if lbl in H_want_labels else None

sd_export = {'trimestres':{},'monthly':{},'labels_win':H_want_labels,'n34':{}}
for sc, dat in results.items():
    pr=dat['prec']; lo=dat['lo95']; hi=dat['hi95']
    tri={}
    for tri_name,(tri_months,tk) in zip(TRI.keys(),zip(TRI.values(),tri_keys)):
        vs,ls,hs=[],[],[]
        for y,m in tri_months:
            idx=ym_idx(y,m)
            if idx is not None: vs.append(pr[idx]); ls.append(lo[idx]); hs.append(hi[idx])
            else: vs.append(cm[m-1]); ls.append(0); hs.append(0)
        tri[tk]={'mean':round(sum(vs),1),'lo':round(sum(ls),1),'hi':round(sum(hs),1)}
    sd_export['trimestres'][sc]=tri
    sd_export['monthly'][sc]={'prec':[round(v,1) for v in pr],
                               'lo95':[round(v,1) for v in lo],'hi95':[round(v,1) for v in hi],
                               'p5':[round(v,1) for v in dat['p5']],'p95':[round(v,1) for v in dat['p95']]}
    sd_export['n34'][sc]=[round(v,3) for v in dat['n34']]

html = re.sub(r'const SARIMAX_DATA = \{.*?\};',
              f'const SARIMAX_DATA = {json.dumps(sd_export, ensure_ascii=False, separators=(",",":"))};',
              html, flags=re.DOTALL)

# BH.clim e BH.fc
etp_str = f'etp_jan_dez: {json.dumps(ETP_JAN_DEZ)}'
html    = re.sub(r'etp_jan_dez:\s*\[[^\]]+\]', etp_str, html)
etp_jul_str = f'etp_jul_jun: {json.dumps(ETP_JUL_JUN)}'
html        = re.sub(r'etp_jul_jun:\s*\[[^\]]+\]', etp_jul_str, html)

bh_s = html.find('const BH = {')
bh_e = html.find('\n\n/* ── BALANÇO HÍDRICO COMPARATIVO', bh_s)
bh_block = html[bh_s:bh_e]
for sc in cenarios_bh:
    nb = bh_final['cenarios'][sc]
    for field in ['arm','etr','def','exc']:
        bh_block = re.sub(
            rf"('{re.escape(sc)}':\s*\{{[^{{}}]*?{field}:\s*)(\[[^\]]+\])",
            lambda mo, nv=json.dumps(nb[field]): mo.group(1)+nv,
            bh_block, flags=re.DOTALL)
    bh_block = re.sub(rf"('{re.escape(sc)}':\s*\{{[^{{}}]*?def_total:\s*)\d+",
                      lambda mo,v=nb['def_total']: mo.group(1)+str(v), bh_block, flags=re.DOTALL)
    bh_block = re.sub(rf"('{re.escape(sc)}':\s*\{{[^{{}}]*?exc_total:\s*)\d+",
                      lambda mo,v=nb['exc_total']: mo.group(1)+str(v), bh_block, flags=re.DOTALL)
html = html[:bh_s] + bh_block + html[bh_e:]

# Atualizar ULTIMA_ATUALIZACAO e EMBEDDED_BUNDLE
dt_str = TODAY.strftime('%d/%m/%Y')
html = re.sub(r"data:\s*'[\d/]+'", f"data:       '{dt_str}'", html)

new_bundle = json.dumps({
    'version':     '2.0',
    'updated_at':  dt_str,
    'serie_subst': serie.to_csv(index=False),
    'meta_best':   {'modelo':'SARIMAX(N34+TSA+PDO)',
                    'b1':round(b1,4),'b2':round(b2,4),'b3':round(b3,4),
                    'aic':round(res.aic,1),'n':len(d),
                    'years':years,'vals':vals,'clim_mean':cm,'clim_std':cs,
                    'media':round(float(np.mean(vals)),1),'dp':round(float(np.std(vals)),1),
                    'cv':round(float(np.std(vals)/np.mean(vals)*100),1),
                    'min_y':int(years[int(np.argmin(vals))]),'min_v':min(vals),
                    'max_y':int(years[int(np.argmax(vals))]),'max_v':max(vals)},
    'model_ranking': [],
    'fc_results':  results,
    'scen12':      scen_df.to_csv(index=False),
    'sarimax_data':sd_export,
    'bh_final':    bh_final,
}, ensure_ascii=False, separators=(',',':'))

html = re.sub(r'const EMBEDDED_BUNDLE = \{.*?\};',
              f'const EMBEDDED_BUNDLE = {new_bundle};',
              html, flags=re.DOTALL)

DASHBOARD.write_text(html, encoding='utf-8')
print(f"  ✅ docs/index.html atualizado ({len(html)//1024} KB)")

# Salvar arquivos de dados atualizados
json.dump(results,    open(DATA/'fc_results_best.json','w'), ensure_ascii=False, indent=2)
json.dump(sd_export,  open(DATA/'sarimax_data_best.json','w'), ensure_ascii=False, indent=2)
json.dump(bh_final,   open(DATA/'bh_final.json','w'), ensure_ascii=False, indent=2)
serie.to_csv(DATA/'serie_subst.csv', index=False)

print(f"\n{'='*60}")
print(f"  CONCLUÍDO — {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
print(f"  Dashboard: docs/index.html")
print(f"{'='*60}\n")
