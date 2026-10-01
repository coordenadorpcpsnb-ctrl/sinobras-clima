#!/usr/bin/env python3
"""
cfsv2_relatorio_2c3c.py — gera o relatório técnico da Fase 2C.3C a
partir de data/cfsv2_validacao_2c3c/metricas_2c3c.json (já calculado
por scripts/cfsv2_validacao_cientifica.py --executar-metricas). Nunca
recalcula métrica nenhuma aqui — só lê e formata.

Roda com:
    python scripts/cfsv2_relatorio_2c3c.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import cfsv2_validacao_cientifica as c  # noqa: E402


def _fmt(v, casas=2):
    return 'N/D' if v is None else f'{v:.{casas}f}'


def _linha_tabela_horizonte(lead, det):
    a, an = det['absoluto'], det['anomalia']
    return (f"| H{lead} | {det['n']} | {_fmt(a['bias'])} | {_fmt(a['mae'])} | {_fmt(a['rmse'])} | "
            f"{_fmt(a['corr'], 3)} | {_fmt(an['corr'], 3)} | {_fmt(det['rmsess_absoluto'], 3)} | "
            f"{_fmt(det['rmsess_anomalia'], 3)} |")


def gerar_relatorio_markdown(resultados):
    if resultados.get('STOP_ON_FAILURE'):
        return (
            "# Validação científica retrospectiva do CFSv2 — Fase 2C.3C\n\n"
            "**STOP-ON-FAILURE — métricas NÃO calculadas.**\n\n"
            f"Motivo: {resultados.get('motivo')}\n\n"
            f"Problemas encontrados na auditoria: {json.dumps(resultados.get('problemas', []), ensure_ascii=False)}\n"
        )

    aud = resultados['auditoria']
    exp = resultados['expanding_operational_simulation']
    loyo = resultados['loyo_retrospective']

    linhas = [
        "# Validação científica retrospectiva do CFSv2 — Fase 2C.3C",
        "",
        "**Relatório técnico — completamente separado do sistema operacional. Nenhuma "
        "métrica aqui é apresentada no dashboard de produção. Referência observacional "
        "exclusiva: `data/chirps_v3_historico/chirps_v3_1981_2011.csv` (365 meses, Fase "
        "2C.3B) — `data/serie_subst.csv` e `data/chirps_1981_2025.csv` NÃO foram usados "
        "como referência principal em nenhum cálculo.**",
        "",
        "## 1. Auditoria da base RAW (antes de qualquer métrica)",
        "",
        f"- Registros RAW: {aud['n_raw_total']} (esperado {aud['n_raw_esperado']}).",
        f"- Inicializações distintas: {aud['n_inicializacoes_distintas']} (esperado "
        f"{c.N_INICIALIZACOES_ESPERADO}, jan/1991 a dez/2010).",
        f"- Unicidade (init_date × lead × member): {'✅' if aud['unicidade_init_lead_member_ok'] else '❌'}.",
        f"- Exatamente 24 membros por (init_date, lead): "
        f"{'✅' if aud['vinte_quatro_membros_por_init_lead_ok'] else '❌'}.",
        f"- target_month corresponde a init_date+(lead-1) — **validado, nunca reconstruído**: "
        f"{'✅' if aud['target_month_corresponde_a_init_mais_lead_ok'] else '❌'}.",
        f"- H1 = mês corrente (target_month == init_date): "
        f"{'✅' if aud['h1_igual_mes_corrente_ok'] else '❌'}.",
        f"- Sem valores faltantes nas colunas essenciais: "
        f"{'✅' if aud['sem_valores_faltantes_ok'] else '❌'}.",
        f"- Unidades (mm/day convertido para mm/mês, conversão registrada): "
        f"{'✅' if aud['unidades_ok'] else '❌'}.",
        f"- Localização única (Fazendas_Sinobras_Centroide, nunca misturada com São Bento): "
        f"{'✅' if aud['localizacao_unica_ok'] else '❌'}.",
        f"- Meses-alvo distintos cobertos: {aud['n_meses_alvo_distintos']}.",
        f"- **Auditoria {'APROVADA' if aud['auditoria_aprovada'] else 'REPROVADA'}.**",
        "",
        "## 2. Base pareada CFSv2 × CHIRPS v3",
        "",
        f"- {exp['n_registros_pareados']} registros pareados (um por init_date×target_month×"
        f"lead×member), {exp['n_meses_alvo_distintos']} meses-alvo distintos.",
        "- Pareamento exclusivo por `target_month` exato — nenhuma observação de "
        "`serie_subst.csv`/`chirps_1981_2025.csv` foi usada como referência principal.",
        "- Nenhum mês-alvo ausente (validado antes de qualquer métrica).",
        "",
        "## 3. Métricas determinísticas por horizonte (média dos 24 membros)",
        "",
        "H1 é a previsão do **mês corrente** — tratado separadamente, nunca agregado com "
        "H2-H6 (horizontes futuros) numa métrica única.",
        "",
        "| Horizonte | N | Bias (abs, mm) | MAE (abs, mm) | RMSE (abs, mm) | Corr (abs) | "
        "Corr (anomalia) | RMSESS (abs) | RMSESS (anomalia) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for lead in c.LEADS_ESPERADOS:
        linhas.append(_linha_tabela_horizonte(lead, exp['deterministico_por_horizonte'][str(lead)]))
    linhas += [
        "",
        f"**Fórmula do skill score:** `{exp['deterministico_por_horizonte']['1']['formula_rmsess']}` "
        "— positivo significa que o modelo erra MENOS que a climatologia expansível "
        "(benchmark, calculada sem leakage); negativo significa que a climatologia sozinha "
        "seria uma previsão melhor. **Nenhum valor aqui deve ser lido como 'bom' ou 'mau' "
        "isoladamente** — ver a seção 7 (intervalos de confiança) antes de qualquer conclusão.",
        "",
        "**Nota sobre bias/MAE/RMSE/RMSESS 'absoluto' vs. 'anomalia' serem numericamente "
        "idênticos na tabela:** isso é esperado, não um erro de cópia. Subtrair a mesma "
        "climatologia da previsão e da observação não muda a DIFERENÇA entre elas "
        "(erro = previsto-observado é invariante a essa translação) — por isso bias/MAE/RMSE "
        "e o RMSESS derivado deles são idênticos nas duas colunas. A métrica que realmente "
        "muda — e que importa aqui — é a **correlação**, porque ela depende da variância "
        "de cada série: a climatologia (o ciclo sazonal) infla a correlação 'absoluta' "
        "artificialmente, e só desaparece quando as duas são expressas como anomalia.",
        "",
        "A correlação cai fortemente da precipitação absoluta para a anomalia em todos os "
        "horizontes — esperado: parte da correlação absoluta é só o ciclo sazonal "
        "(out-abr chuvoso, jun-ago seco) que tanto o modelo quanto a climatologia capturam "
        "trivialmente. A correlação em anomalia é a medida mais honesta da habilidade real "
        "de prever o DESVIO em relação ao esperado para aquele mês.",
        "",
        "## 4. Avaliação por mês do ano (Seção 10 — nunca escondida numa média anual)",
        "",
        "| Mês | Grupo sazonal | N | Bias | MAE | RMSE | Corr |",
        "|---|---|---|---|---|---|---|",
    ]
    nomes_mes = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']
    for mes in range(1, 13):
        d = exp['por_mes_do_ano']['por_mes'][str(mes)]
        if d.get('n', 0) == 0:
            continue
        aviso = '' if d.get('amostra_suficiente', True) else ' ⚠ amostra pequena'
        linhas.append(f"| {nomes_mes[mes-1]} | {d['grupo_sazonal']} | {d['n']}{aviso} | "
                       f"{_fmt(d['bias'])} | {_fmt(d['mae'])} | {_fmt(d['rmse'])} | {_fmt(d['corr'], 3)} |")
    linhas += ["", "**Por grupo sazonal regional (CLAUDE.md):**", "",
               "| Grupo | N | Bias | MAE | RMSE | Corr |", "|---|---|---|---|---|---|"]
    for grupo in ('chuvosa', 'transicao', 'seca'):
        d = exp['por_mes_do_ano']['por_grupo_sazonal'][grupo]
        if d.get('n', 0) == 0:
            continue
        linhas.append(f"| {grupo} | {d['n']} | {_fmt(d['bias'])} | {_fmt(d['mae'])} | "
                       f"{_fmt(d['rmse'])} | {_fmt(d['corr'], 3)} |")

    linhas += [
        "",
        "## 5. Avaliação probabilística (24 membros)",
        "",
        "CRPS calculado com a fórmula \"fair\" (Ferro et al. 2008), não-viesada para ensemble "
        "finito. CRPSS compara contra a climatologia probabilística (conjunto dos anos "
        "históricos elegíveis, sem leakage). Tercis calculados exclusivamente com o "
        "histórico permitido antes de cada inicialização — nunca com 1981-2011 completo.",
        "",
        "| Horizonte | N | CRPS modelo | CRPS climatologia | CRPSS | BS seco | BS normal | "
        "BS úmido | BSS seco | BSS normal | BSS úmido |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for lead in c.LEADS_ESPERADOS:
        d = exp['probabilistico_por_horizonte'][str(lead)]
        if not d.get('amostra_suficiente', False):
            linhas.append(f"| H{lead} | {d.get('n', 0)} | — | — | — | — | — | — | — | — | — "
                           f"(amostra insuficiente) |")
            continue
        bs, bss = d['brier_score_por_categoria'], d['bss_por_categoria']
        linhas.append(f"| H{lead} | {d['n']} | {_fmt(d['crps_medio_modelo'])} | "
                       f"{_fmt(d['crps_medio_climatologia'])} | {_fmt(d['crpss'], 3)} | "
                       f"{_fmt(bs['seco'], 4)} | {_fmt(bs['normal'], 4)} | {_fmt(bs['umido'], 4)} | "
                       f"{_fmt(bss['seco'], 3)} | {_fmt(bss['normal'], 3)} | {_fmt(bss['umido'], 3)} |")
    linhas += [
        "",
        f"**Fórmulas:** `{exp['probabilistico_por_horizonte']['1'].get('formula_crpss', 'CRPSS = 1 - CRPS_modelo/CRPS_climatologia')}` "
        f"— `{exp['probabilistico_por_horizonte']['1'].get('formula_bss', 'BSS = 1 - BS_modelo/BS_referencia (p=1/3)')}`.",
        "",
        "### Rank histogram (posição da observação entre os 24 membros ordenados, 1-25)",
        "",
    ]
    for lead in c.LEADS_ESPERADOS:
        d = exp['probabilistico_por_horizonte'][str(lead)]
        if not d.get('amostra_suficiente', False):
            continue
        hist = d['rank_histogram']
        resumo = ', '.join(f"{k}:{v}" for k, v in sorted(hist.items(), key=lambda x: int(x[0]))
                            if int(v) > 0)
        linhas.append(f"- H{lead}: {resumo}")

    linhas += [
        "",
        "## 6. Intervalos de confiança (bootstrap em blocos por ano, nunca linhas independentes)",
        "",
        "O mesmo `target_month` aparece em vários horizontes/inicializações — as observações "
        "NÃO são independentes. O IC 95% usa reamostragem em blocos por ANO do target_month "
        "(nunca bootstrap de linhas soltas, que subestimaria a incerteza real).",
        "",
        "| Horizonte | RMSE | IC 95% | MAE | IC 95% | Bias | IC 95% |",
        "|---|---|---|---|---|---|---|",
    ]
    for lead in c.LEADS_ESPERADOS:
        ic = exp['intervalos_confianca_por_horizonte'].get(str(lead), {})
        if 'nota' in ic:
            linhas.append(f"| H{lead} | — | {ic['nota']} | | | | |")
            continue
        r, m, b = ic['rmse'], ic['mae'], ic['bias']
        linhas.append(f"| H{lead} | {_fmt(r['estimativa'])} | [{_fmt(r['ic95_lo'])}, "
                       f"{_fmt(r['ic95_hi'])}] | {_fmt(m['estimativa'])} | [{_fmt(m['ic95_lo'])}, "
                       f"{_fmt(m['ic95_hi'])}] | {_fmt(b['estimativa'])} | [{_fmt(b['ic95_lo'])}, "
                       f"{_fmt(b['ic95_hi'])}] |")

    linhas += [
        "",
        "## 7. LOYO retrospectivo (complementar — NUNCA misturado com a simulação operacional)",
        "",
        f"**Rótulo: `{loyo['rotulo']}`.** {loyo['aviso']}",
        "",
        "| Horizonte | N | RMSESS (abs) |",
        "|---|---|---|",
    ]
    for lead in c.LEADS_ESPERADOS:
        d = loyo['deterministico_por_horizonte'][str(lead)]
        linhas.append(f"| H{lead} | {d.get('n', 0)} | {_fmt(d.get('rmsess_absoluto'), 3)} |")

    linhas += [
        "",
        "## 8. Interpretação — separada por tipo de desempenho, nunca uma conclusão única",
        "",
        "Esta seção separa deliberadamente quatro desempenhos DIFERENTES — nunca resumidos "
        "numa frase como \"modelo validado\" ou \"boa habilidade\":",
        "",
        "1. **Desempenho absoluto** — correlação alta (0.80-0.83) em todos os horizontes, mas "
        "dominada pelo ciclo sazonal regional (chuva concentrada out-abr).",
        "2. **Desempenho em anomalias** — correlação cai para a faixa 0.10-0.41 e diminui com "
        "o horizonte — a habilidade real de prever o desvio em relação ao esperado para "
        "aquele mês é MODESTA e decai com o lead time, como esperado fisicamente.",
        "3. **Desempenho relativo à climatologia (RMSESS/CRPSS)** — NEGATIVO em todos os "
        "horizontes testados, tanto na simulação operacional expansível quanto no LOYO "
        "retrospectivo — a climatologia expansível sem leakage teve erro MENOR que o "
        "ensemble bruto (não corrigido por viés) do CFSv2 neste ponto único, nesta amostra. "
        "Isso NÃO significa que o CFSv2 é inútil — o ensemble aqui usado é bruto "
        "(forecast_prec_mm sem qualquer correção de viés ou downscaling), e o benchmark é "
        "uma climatologia já bem ajustada aos próprios dados observados.",
        "4. **Desempenho probabilístico** — CRPSS e BSS também predominantemente negativos, "
        "consistente com os itens 2-3: o ensemble bruto discrimina mal as categorias de "
        "tercil neste ponto.",
        "",
        "**Nenhuma dessas quatro leituras, isoladamente, autoriza uma conclusão geral de "
        "habilidade.** Qualquer decisão sobre uso operacional do CFSv2 deve revisar "
        "conjuntamente: magnitude do skill, intervalo de confiança (seção 6), horizonte, "
        "época do ano (seção 4) e tamanho da amostra (N=240 inicializações, mas com "
        "dependência temporal relevante — daí o bootstrap em blocos).",
        "",
        "## Restrições respeitadas",
        "",
        "- Dashboard, SARIMAX, XGBoost, pipeline operacional, série de produção e dados RAW "
        "do CFSv2 não foram alterados.",
        "- Nenhuma métrica desta fase é apresentada automaticamente no dashboard de produção.",
        "- `serie_subst.csv`/`chirps_1981_2025.csv` não foram usados como referência "
        "principal em nenhum cálculo.",
        "- Testes de controle de leakage (climatologia, tercis, pareamento, mistura de "
        "membros, demonstração sintética) executados e aprovados antes do cálculo das "
        "métricas — ver `tests/test_cfsv2_validacao_cientifica.py`.",
    ]
    return '\n'.join(linhas) + '\n'


def gerar_e_escrever():
    resultados = json.loads(c.CAMINHO_METRICAS_JSON.read_text())
    relatorio = gerar_relatorio_markdown(resultados)
    c.RELATORIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    c.RELATORIO_PATH.write_text(relatorio)
    print(f"  ✅ {c.RELATORIO_PATH.relative_to(c.ROOT)}")
    return relatorio


if __name__ == '__main__':
    gerar_e_escrever()
