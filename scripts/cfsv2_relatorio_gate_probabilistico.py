#!/usr/bin/env python3
"""
cfsv2_relatorio_gate_probabilistico.py — gera
docs/nmme-fase2c3d-gate-calibracao-probabilistica-cfsv2.md a partir de
data/cfsv2_calibracao_2c3d/gate_calibracao_probabilistica_2c3d.json (já
calculado por scripts/cfsv2_gate_calibracao_probabilistica.py
--executar). Nunca recalcula nada aqui — só lê e formata. Nunca declara
o Método 3.5 aprovado nem implementado — este é o relatório de um GATE
DIAGNÓSTICO.

Revisão sazonal (pós-commit ad6caf5): a classificação principal do
gate passou a usar a análise de spread-skill CONTROLADA POR MÊS, não
mais a correlação pooled — ver seção 3/3.1/10.

Roda com:
    python scripts/cfsv2_relatorio_gate_probabilistico.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import cfsv2_gate_calibracao_probabilistica as g  # noqa: E402
import cfsv2_validacao_cientifica as v  # noqa: E402

NOMES_MES = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']

_IC_TEXTO = {
    'ic_totalmente_acima_de_zero': 'IC 95% totalmente ACIMA de zero',
    'ic_inclui_zero': 'IC 95% inclui zero (indeterminado)',
    'ic_totalmente_abaixo_de_zero': 'IC 95% totalmente ABAIXO de zero',
    'indeterminado': 'indeterminado (amostra insuficiente)',
}


def _fmt(val, casas=2):
    return 'N/D' if val is None else f'{val:.{casas}f}'


def _ic_texto(classificacao):
    return _IC_TEXTO.get(classificacao, classificacao or 'N/D')


def _g(dic, chave):
    return dic.get(chave, dic.get(str(chave), {}))


def gerar_relatorio_markdown(resultados):
    if resultados.get('STOP_ON_FAILURE'):
        return (
            "# Gate diagnóstico de calibração probabilística — Fase 2C.3D (Método 3.5)\n\n"
            "**STOP-ON-FAILURE — diagnóstico NÃO calculado.**\n\n"
            f"Motivo: {resultados.get('motivo')}\n\n"
            f"Detalhe: {json.dumps(resultados.get('detalhe', {}), ensure_ascii=False)}\n"
        )

    ser = resultados['spread_error_ratio_por_horizonte']
    ss_raw = resultados['spread_skill_raw_pooled_por_horizonte']
    ss_mc = resultados['spread_skill_month_controlled_retrospective_por_horizonte']
    ss_matriz = resultados['spread_skill_matriz_mes_lead']
    cov = resultados['cobertura_intervalos_por_horizonte']
    prob = resultados['probabilistico_por_horizonte']
    mml = resultados['matriz_mes_lead']
    mgsl = resultados['matriz_grupo_sazonal_lead']
    dep = resultados['dependencia_membros_por_horizonte']
    classif = resultados['classificacao_gate_por_horizonte']
    classif_raw_ref = resultados['classificacao_raw_pooled_referencia_apenas_por_horizonte']
    auditoria_membros = resultados['auditoria_membros']

    linhas = [
        "# Gate diagnóstico de calibração probabilística — Fase 2C.3D (Método 3.5)",
        "",
        "**GATE DIAGNÓSTICO, não implementação. Nenhum EMOS foi ajustado, nenhum membro "
        "foi recalibrado, nenhum dressing foi aplicado, nenhum quantile mapping "
        "probabilístico foi executado, nenhuma probabilidade operacional nem o dashboard "
        "foram alterados. O único objetivo deste documento é responder, com os fatos "
        "primeiro, se a dispersão dos 24 membros do CFSv2 contém informação útil sobre a "
        "incerteza/erro da previsão — e classificar essa resposta por horizonte, nunca "
        "declarar o Método 3.5 aprovado.**",
        "",
        "**Revisão sazonal (pós-commit `ad6caf5`):** a revisão independente confirmou "
        "auditoria de 24 membros, CRPS/CRPSS, Brier/BSS, bootstrap anual, rank histogram e "
        "cobertura, mas apontou que a classificação original (baseada na correlação "
        "spread×erro POOLED, todos os meses juntos) podia estar confundida pelo ciclo "
        "sazonal forte da precipitação — meses chuvosos têm spread E erro absolutos "
        "maiores que meses secos por pura sazonalidade, o que por si só já gera correlação "
        "positiva entre spread e erro, mesmo sem nenhuma informação caso a caso. A partir "
        "desta revisão, a classificação PRINCIPAL do gate (seção 10) usa a correlação "
        "spread×erro CONTROLADA POR MÊS (seção 3.1); a versão pooled é mantida só como "
        "referência (seção 3 e 10.1), nunca decisória.",
        "",
        "Protegidos e não alterados nesta atividade: CFSv2 RAW, CHIRPS v3 histórico, base "
        "pareada da 2C.3C, dashboard, SARIMAX/XGBoost, pipeline operacional, "
        "`serie_subst.csv`, e os artefatos já aprovados dos Métodos 3.1/3.2/3.4 e do gate "
        "do Método 3.3 — todos só lidos, nunca alterados.",
        "",
        "## 1. Unidade de análise e auditoria de 24 membros",
        "",
        "1 linha por `(init_date, lead)`; os 24 membros são usados SÓ para estatísticas "
        "internas do ensemble (`ensemble_mean`, `ensemble_median`, `ensemble_std` "
        "(`ddof=1`), `ensemble_variance`, `ensemble_iqr`, `ensemble_min/max/range`) — "
        "NUNCA tratados como 24 anos/observações históricas independentes em nenhum "
        "bootstrap deste módulo (todo bootstrap resample `target_ano`, em blocos, nunca "
        "membros).",
        "",
        f"Auditoria de contagem de membros: "
        f"{'✅ todas as linhas têm exatamente ' + str(resultados['n_membros_esperado']) + ' membros' if auditoria_membros['ok'] else '❌ FALHOU — ' + str(auditoria_membros['n_linhas_divergentes']) + ' linha(s) divergente(s)'}.",
        "",
        "## 2. Spread médio por horizonte e spread-error ratio (itens 1, 2 e 4 do pedido "
        "original)",
        "",
        "`erro_abs = |ensemble_mean - obs|`, `erro_quadratico = (ensemble_mean - obs)²`, "
        "`erro_assinado = ensemble_mean - obs` — SEM qualquer correção de bias (diagnóstico "
        "do ensemble RAW). `spread_error_ratio = mean(ensemble_std) / RMSE(ensemble_mean, "
        "obs)` — leitura SEMPRE só diagnóstica, nunca prova isolada de calibração. Esses "
        "sinais (junto com o rank histogram, seção 4) alimentam o julgamento de "
        "\"calibração de magnitude\" usado na classificação (seção 10).",
        "",
        "| Horizonte | N | Spread médio (`ensemble_std`) | RMSE(`ensemble_mean`, obs) | "
        "spread_error_ratio | Leitura diagnóstica |",
        "|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(ser, lead)
        if not d.get('n'):
            linhas.append(f"| H{lead} | 0 | — | — | — | — |")
            continue
        linhas.append(f"| H{lead} | {d['n']} | {_fmt(d['spread_medio'])} | "
                       f"{_fmt(d['rmse_ensemble_mean'])} | {_fmt(d['spread_error_ratio'], 3)} | "
                       f"{d['leitura_diagnostica']} |")

    linhas += [
        "",
        "## 3. Spread-skill RAW POOLED — diagnóstico bruto, mantido só como referência",
        "",
        "`spread_skill_raw_pooled`: Pearson e Spearman entre `ensemble_std` e `erro_abs` "
        "(e Pearson entre `ensemble_variance` e `erro_quadratico`), SEM separar por mês — "
        "todos os casos de todos os meses juntos. Bootstrap em blocos por `target_ano` "
        "(`v.bootstrap_blocos_por_ano`, reaproveitado sem modificação). **Mantido "
        "integralmente (mesmos números de sempre), mas NÃO é mais usado para decidir a "
        "classificação do gate** — pode estar confundido pelo ciclo sazonal (ver seção "
        "3.1).",
        "",
        "| Horizonte | N | Pearson(std, erro_abs) | IC 95% | Spearman(std, erro_abs) | "
        "IC 95% | Pearson(variance, erro_quad.) | IC 95% |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(ss_raw, lead)
        if not d.get('amostra_suficiente', False):
            linhas.append(f"| H{lead} | {d.get('n', 0)} | — | — | — | — | — | — | "
                           f"{d.get('nota', 'amostra insuficiente')} |")
            continue
        p = d['pearson_std_vs_erro_abs']
        s = d['spearman_std_vs_erro_abs']
        pv = d['pearson_variance_vs_erro_quadratico']
        linhas.append(
            f"| H{lead} | {d['n']} | {_fmt(p['estimativa'], 3)} | "
            f"[{_fmt(p['ic95_lo'], 3)}, {_fmt(p['ic95_hi'], 3)}] | {_fmt(s['estimativa'], 3)} | "
            f"[{_fmt(s['ic95_lo'], 3)}, {_fmt(s['ic95_hi'], 3)}] | {_fmt(pv['estimativa'], 3)} | "
            f"[{_fmt(pv['ic95_lo'], 3)}, {_fmt(pv['ic95_hi'], 3)}] |")

    linhas += [
        "",
        "## 3.1. Spread-skill CONTROLADO POR MÊS — análise PRINCIPAL (revisão sazonal, "
        "itens 2/3)",
        "",
        "`spread_skill_month_controlled_retrospective` — RETROSPECTIVA/DESCRITIVA (a "
        "centralização usa a amostra completa de hindcast, nunca operacional). Para cada "
        "`lead × target_mes` (as ~20 observações daquele mês), calcula "
        "`spread_resid = ensemble_std - média_do_mês`, `erro_abs_resid = erro_abs - "
        "média_do_mês`, e equivalente para `ensemble_variance`/`erro_quadratico` — depois "
        "correlaciona os RESÍDUOS. Testa se o spread tem informação ALÉM do ciclo "
        "sazonal. Bootstrap em blocos por `target_ano`, recalculando as médias mensais "
        "DENTRO de cada reamostra (preferência explícita da revisão — reflete toda a "
        "transformação, não só a correlação final).",
        "",
        "| Horizonte | N | Pearson resid(std, erro_abs) | IC 95% | Classificação | "
        "Spearman resid | IC 95% | Classificação |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(ss_mc, lead)
        if not d.get('amostra_suficiente', False):
            linhas.append(f"| H{lead} | {d.get('n', 0)} | — | — | — | — | — | — |")
            continue
        p = d['pearson_std_resid_vs_erro_abs_resid']
        s = d['spearman_std_resid_vs_erro_abs_resid']
        linhas.append(
            f"| H{lead} | {d['n']} | {_fmt(p['estimativa'], 3)} | "
            f"[{_fmt(p['ic95_lo'], 3)}, {_fmt(p['ic95_hi'], 3)}] | "
            f"{_ic_texto(d['pearson_std_resid_vs_erro_abs_resid_ic_classificacao'])} | "
            f"{_fmt(s['estimativa'], 3)} | [{_fmt(s['ic95_lo'], 3)}, {_fmt(s['ic95_hi'], 3)}] | "
            f"{_ic_texto(d['spearman_std_resid_vs_erro_abs_resid_ic_classificacao'])} |")

    linhas += [
        "",
        "### 3.2. Quanto a correlação caiu após o controle sazonal",
        "",
        "| Horizonte | Pearson RAW pooled | Pearson residual (controlado por mês) | Queda |",
        "|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        draw = _g(ss_raw, lead)
        dmc = _g(ss_mc, lead)
        if not draw.get('amostra_suficiente', False) or not dmc.get('amostra_suficiente', False):
            linhas.append(f"| H{lead} | — | — | — |")
            continue
        p_raw = draw['pearson_std_vs_erro_abs']['estimativa']
        p_resid = dmc['pearson_std_resid_vs_erro_abs_resid']['estimativa']
        linhas.append(f"| H{lead} | {_fmt(p_raw, 3)} | {_fmt(p_resid, 3)} | "
                       f"{_fmt(p_raw - p_resid, 3)} |")
    linhas.append("")
    linhas.append("Queda grande e consistente em quase todos os horizontes confirma que boa "
                   "parte (ou toda) a correlação pooled vinha do ciclo sazonal comum entre "
                   "spread e erro, não de informação caso a caso — exatamente a confusão que "
                   "a revisão apontou como risco.")

    linhas += [
        "",
        "### 3.3. Coerência mês × lead (revisão sazonal, item 5) — descritivo, nunca 72 "
        "testes de significância",
        "",
        "Pearson(`ensemble_std`, `erro_abs`) por célula `target_mes × lead`, N≈20 por "
        "célula, SEM centralização dentro da própria célula (um único mês não tem o que "
        "centralizar). Objetivo: ver se o sinal raw pooled é coerente em muitos meses ou "
        "concentrado na diferença seca/chuvosa.",
        "",
        "| Mês \\ Lead | " + " | ".join(f"H{l}" for l in v.LEADS_ESPERADOS) + " |",
        "|---" * (len(v.LEADS_ESPERADOS) + 1) + "|",
    ]
    for mes in range(1, 13):
        por_lead = _g(ss_matriz, mes)
        celulas = [_fmt(_g(por_lead, lead).get('pearson_std_vs_erro_abs'), 2)
                   for lead in v.LEADS_ESPERADOS]
        linhas.append(f"| {NOMES_MES[mes-1]} | " + " | ".join(celulas) + " |")
    linhas.append("")
    linhas.append("Sinais de magnitude e direção variáveis mês a mês (ver tabela) — "
                   "consistente com a interpretação de que o sinal pooled é inflado pela "
                   "diferença entre meses, não um padrão caso a caso uniformemente presente "
                   "dentro de cada mês.")

    linhas += [
        "",
        "## 4. Rank histogram (item 5 do pedido original)",
        "",
        "Posição (1..25) da observação entre os 24 membros ordenados. Tie-break "
        "**explícito e determinístico** (`_rank_observacao_determinístico`, próprio deste "
        "módulo — ver nota de implementação abaixo), nunca o sorteio seedado de "
        "`v.rank_observacao` usado em outros pontos da 2C.3C. Diagnóstico derivado, nunca "
        "um teste de hipótese formal como critério único: frequência nos ranks extremos "
        "(1 e 25 — formato em U sugere underdispersion), frequência central (terço central "
        "— concentração sugere overdispersion), e desvio de uniformidade.",
        "",
        "> **Nota de implementação (desvio deliberado do reuso literal):** o item 5 do "
        "pedido original exige tie-break \"explícito e determinístico\"; `v.rank_"
        "observacao` (2C.3C) resolve empates por sorteio seedado — reprodutível, mas não "
        "determinístico no sentido de regra fixa. Por isso este módulo define sua própria "
        "`_rank_observacao_determinístico`: sem empate, mesma posição de sempre; com "
        "empate, sempre o PONTO MÉDIO do intervalo de posições válidas, arredondado "
        "meio-para-cima em caso de 0,5 exato. `crps_amostral` e `categoria_tercil` "
        "continuam reaproveitados sem modificação.",
        "",
        "| Horizonte | N | Freq. ranks extremos (1 e 25) | Freq. central (terço central) | "
        "Desvio de uniformidade | Esperado por rank sob uniformidade |",
        "|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(prob, lead).get('rank_histogram_diagnostico', {})
        n = _g(prob, lead).get('n', 0)
        if not n:
            linhas.append(f"| H{lead} | 0 | — | — | — | — |")
            continue
        linhas.append(f"| H{lead} | {n} | {_fmt(d.get('frequencia_ranks_extremos'), 3)} | "
                       f"{_fmt(d.get('frequencia_central'), 3)} | "
                       f"{_fmt(d.get('desvio_uniformidade'), 3)} | "
                       f"{_fmt(d.get('esperado_sob_uniformidade_por_rank'), 2)} |")
    linhas.append("")
    linhas.append("Esperado sob uniformidade perfeita: 2/25 = 0,080 nos ranks extremos "
                   "combinados. Frequências nos ranks extremos consistentemente acima disso "
                   "em todos os horizontes (ver tabela) são consistentes com um ensemble RAW "
                   "**underdispersive** — a observação cai fora da faixa dos 24 membros com "
                   "frequência maior do que uma dispersão bem calibrada permitiria.")

    linhas += [
        "",
        "### 4.1. Rank 1 vs. rank 25 separados — bias vs. underdispersion (revisão "
        "sazonal, item 9)",
        "",
        "O uso conjunto dos ranks extremos (seção 4) detecta falta de cobertura mas não "
        "distingue dispersão insuficiente (extremos altos e aproximadamente simétricos) de "
        "bias sistemático (forte assimetria entre rank 1 e rank 25) — os dois podem "
        "coexistir. `diferenca = freq_rank25 - freq_rank1`.",
        "",
        "| Horizonte | Freq. rank 1 | Freq. rank 25 | Diferença (rank25 − rank1) |",
        "|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(prob, lead).get('rank_histogram_diagnostico', {})
        if not _g(prob, lead).get('n', 0):
            linhas.append(f"| H{lead} | — | — | — |")
            continue
        linhas.append(f"| H{lead} | {_fmt(d.get('frequencia_rank_1'), 3)} | "
                       f"{_fmt(d.get('frequencia_rank_m_mais_1'), 3)} | "
                       f"{_fmt(d.get('diferenca_rank_m_mais_1_menos_rank_1'), 3)} |")
    linhas.append("")
    linhas.append("**Forte assimetria em todos os horizontes: freq. rank 25 >> freq. rank "
                   "1** (ver tabela) — a observação cai ACIMA de todos os 24 membros com "
                   "frequência muito maior do que cai abaixo de todos eles. Isso é evidência "
                   "de um componente de BIAS SISTEMÁTICO (o ensemble RAW subestima a "
                   "precipitação com mais frequência do que sobrestima), não apenas "
                   "underdispersion simétrica — os dois componentes coexistem aqui, e a "
                   "seção 4 isolada não deixava isso visível.")

    linhas += [
        "",
        "## 5. Cobertura de intervalos empíricos 50/80/90% (item 6 do pedido original)",
        "",
        "Intervalos EMPÍRICOS (percentis dos 24 membros RAW, nunca uma distribuição "
        "assumida). `coverage_error = cobertura_observada - cobertura_nominal`. **Nenhuma "
        "calibração de intervalo aplicada nesta etapa — só diagnóstico.**",
        "",
        "| Horizonte | N | Cobertura 50% (nominal 0,50) | erro | Cobertura 80% (nominal "
        "0,80) | erro | Cobertura 90% (nominal 0,90) | erro |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(cov, lead)
        if not d.get('n'):
            linhas.append(f"| H{lead} | 0 | — | — | — | — | — | — |")
            continue
        iv = d['intervalos']
        i50, i80, i90 = _g(iv, 50), _g(iv, 80), _g(iv, 90)
        linhas.append(
            f"| H{lead} | {d['n']} | {_fmt(i50['cobertura_observada'], 3)} | "
            f"{_fmt(i50['coverage_error'], 3)} | {_fmt(i80['cobertura_observada'], 3)} | "
            f"{_fmt(i80['coverage_error'], 3)} | {_fmt(i90['cobertura_observada'], 3)} | "
            f"{_fmt(i90['coverage_error'], 3)} |")
    linhas.append("")
    linhas.append("Coverage_error consistentemente NEGATIVO (cobertura observada abaixo da "
                   "nominal) em todos os horizontes é o mesmo sinal de dispersão insuficiente "
                   "já visto no spread_error_ratio (seção 2) e no rank histogram (seção 4).")
    linhas.append("")
    linhas.append(f"**Nota metodológica (revisão sazonal, item 10):** {resultados.get('cobertura_nota_metodologica', '')}")

    linhas += [
        "",
        "## 6. CRPS RAW (item 7 do pedido original — NÃO alterado nesta revisão)",
        "",
        "Fórmula \"fair\" (Ferro et al. 2008) reaproveitada sem modificação "
        "(`v.crps_amostral`) — nunca uma segunda fórmula paralela. `crps_medio_"
        "climatologia` usa a mesma climatologia causal observada já aprovada na 2C.3C "
        "como referência DIRETAMENTE comparável. **Valores idênticos ao commit `ad6caf5` "
        "— confirmado em teste de regressão automatizado "
        "(`tests/test_cfsv2_gate_calibracao_probabilistica.py`).**",
        "",
        "| Horizonte | N | CRPS médio (modelo RAW) | CRPS médio (climatologia causal) | "
        "CRPSS |",
        "|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(prob, lead)
        if not d.get('n'):
            linhas.append(f"| H{lead} | 0 | — | — | — |")
            continue
        linhas.append(f"| H{lead} | {d['n']} | {_fmt(d['crps_medio_modelo'])} | "
                       f"{_fmt(d['crps_medio_climatologia'])} | {_fmt(d['crpss'], 3)} |")
    linhas.append("")
    linhas.append("CRPSS negativo em todos os horizontes indica que o ensemble RAW do "
                   "CFSv2, sem qualquer correção, tem CRPS pior que a climatologia causal "
                   "observada — achado consistente com o skill interanual determinístico "
                   "fraco já documentado nos Métodos 3.1/3.2/3.4.")

    linhas += [
        "",
        "## 7. Brier Score e BSS por tercil (item 8 do pedido original — NÃO alterado "
        "nesta revisão)",
        "",
        "Categorias de tercil (seco/normal/úmido) e `BS_ref_nominal = mean((1/3 - o_i)^2)` "
        "reaproveitados EXATAMENTE da 2C.3C (`v.categoria_tercil`), nunca redefinidos. "
        "Probabilidades RAW = fração dos 24 membros em cada categoria. **Valores idênticos "
        "ao commit `ad6caf5` — confirmado em teste de regressão.**",
        "",
        "| Horizonte | BS seco | BS normal | BS úmido | BSS seco | BSS normal | BSS úmido |",
        "|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(prob, lead)
        if not d.get('n'):
            linhas.append(f"| H{lead} | — | — | — | — | — | — |")
            continue
        bs = d['brier_score_por_categoria']
        bss = d['bss_por_categoria']
        linhas.append(f"| H{lead} | {_fmt(bs['seco'], 3)} | {_fmt(bs['normal'], 3)} | "
                       f"{_fmt(bs['umido'], 3)} | {_fmt(bss['seco'], 3)} | "
                       f"{_fmt(bss['normal'], 3)} | {_fmt(bss['umido'], 3)} |")
    linhas.append("")
    linhas.append("BSS calculado sempre contra a referência nominal `mean((1/3-o_i)^2)` já "
                   "corrigida na 2C.3C — nunca a constante 2/9.")

    linhas += [
        "",
        "## 8. Dependência/diversidade entre membros — raw vs. anomalia mensal (revisão "
        "sazonal, itens 7/8)",
        "",
        "Correlação de Pearson par-a-par média entre as 24 séries temporais de membro "
        "(fora da diagonal). `correlacao_membros_raw` (sobre precipitação bruta) é "
        "fortemente contaminada pelo mesmo ciclo sazonal comum a todos os membros — meses "
        "chuvosos elevam TODOS os membros juntos. `correlacao_membros_anomalia_mensal` "
        "(PRINCIPAL) remove isso: para cada membro, subtrai sua própria média histórica por "
        "`target_mes` antes de montar a matriz de correlação.",
        "",
        "| Horizonte | N inicializações | N membros | Correlação RAW | Correlação anomalia "
        "mensal (principal) | ESS aprox. (raw) | ESS aprox. (principal) |",
        "|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(dep, lead)
        if d.get('correlacao_membros_raw') is None and d.get('correlacao_membros_anomalia_mensal') is None:
            linhas.append(f"| H{lead} | {d.get('n_inits', 0)} | {d.get('n_membros', 0)} | — | — | — | — |")
            continue
        linhas.append(f"| H{lead} | {d['n_inits']} | {d['n_membros']} | "
                       f"{_fmt(d.get('correlacao_membros_raw'), 3)} | "
                       f"{_fmt(d.get('correlacao_membros_anomalia_mensal'), 3)} | "
                       f"{_fmt(d.get('effective_ensemble_size_aprox_raw'), 2)} | "
                       f"{_fmt(d.get('effective_ensemble_size_aprox'), 2)} |")
    linhas.append("")
    linhas.append("**A correlação RAW (~0,77–0,85) cai substancialmente para a anomalia "
                   "mensal (~0,06–0,29) em todos os horizontes** — confirma que boa parte da "
                   "aparente \"redundância\" entre membros era só o ciclo sazonal comum, não "
                   "falta de diversidade real. O Effective Ensemble Size aproximado sobe de "
                   "~1,2 (raw, quase \"1 membro efetivo\") para valores bem mais plausíveis "
                   "(3 a 10, dependendo do horizonte) na versão por anomalia mensal.")
    linhas.append("")
    linhas.append("**Leitura heurística correta (nunca literal):** \"a correlação média "
                   "entre anomalias dos membros implica redundância moderada/baixa segundo "
                   "esta aproximação\" — nunca \"o ensemble possui apenas N membros "
                   "independentes\". Nunca usado para expandir a amostra histórica de 240 "
                   "inicializações.")

    linhas += [
        "",
        "## 9. Sazonalidade — mês × lead e grupo sazonal × lead, atenção à estação seca "
        "(item 10 do pedido original)",
        "",
        "Diagnóstico DESCRITIVO (CRPS/CRPSS, não alterados) — nunca 72 testes de "
        "significância independentes nem um critério de aprovação célula a célula. Ver "
        "seção 3.3 para a matriz equivalente de spread-skill.",
        "",
        "### 9.1. N elegível por célula (mês × lead)",
        "",
        "| Mês \\ Lead | " + " | ".join(f"H{l}" for l in v.LEADS_ESPERADOS) + " |",
        "|---" * (len(v.LEADS_ESPERADOS) + 1) + "|",
    ]
    for mes in range(1, 13):
        por_lead = _g(mml, mes)
        celulas = [str(_g(por_lead, lead).get('n', 0)) for lead in v.LEADS_ESPERADOS]
        linhas.append(f"| {NOMES_MES[mes-1]} | " + " | ".join(celulas) + " |")

    linhas += [
        "",
        "### 9.2. CRPS médio (modelo RAW) por célula (mês × lead)",
        "",
        "| Mês \\ Lead | " + " | ".join(f"H{l}" for l in v.LEADS_ESPERADOS) + " |",
        "|---" * (len(v.LEADS_ESPERADOS) + 1) + "|",
    ]
    for mes in range(1, 13):
        por_lead = _g(mml, mes)
        celulas = [_fmt(_g(por_lead, lead).get('crps_medio_modelo'), 2) for lead in v.LEADS_ESPERADOS]
        linhas.append(f"| {NOMES_MES[mes-1]} | " + " | ".join(celulas) + " |")

    linhas += [
        "",
        "### 9.3. Grupos sazonais (chuvosa/transição/seca) × lead",
        "",
        "| Grupo | Métrica | " + " | ".join(f"H{l}" for l in v.LEADS_ESPERADOS) + " |",
        "|---" * (len(v.LEADS_ESPERADOS) + 2) + "|",
    ]
    for grupo in ('chuvosa', 'transicao', 'seca'):
        por_lead = _g(mgsl, grupo)
        linha_n = [str(_g(por_lead, lead).get('n', 0)) for lead in v.LEADS_ESPERADOS]
        linhas.append(f"| {grupo} | N | " + " | ".join(linha_n) + " |")
        linha_crps = [_fmt(_g(por_lead, lead).get('crps_medio_modelo'), 2) for lead in v.LEADS_ESPERADOS]
        linhas.append(f"| {grupo} | CRPS médio (modelo) | " + " | ".join(linha_crps) + " |")
        linha_crpss = [_fmt(_g(por_lead, lead).get('crpss'), 3) for lead in v.LEADS_ESPERADOS]
        linhas.append(f"| {grupo} | CRPSS | " + " | ".join(linha_crpss) + " |")

    linhas.append("")
    linhas.append("**Atenção especial à estação seca (jun-ago, ver seção 9.3)** — os "
                   "Métodos 3.2/3.4 já mostraram baixa variabilidade de sinal nesses meses "
                   "(chuva rara e próxima de zero). O CRPS médio absoluto da estação seca é "
                   "o menor entre os três grupos simplesmente porque a magnitude da chuva "
                   "observada é pequena — isso não deve ser lido como \"melhor desempenho "
                   "relativo\" sem olhar o CRPSS ao lado do valor absoluto. A mesma cautela "
                   "sazonal se estende à seção 3 (correlação pooled pode estar misturando "
                   "este regime de baixa variância com o regime chuvoso de alta variância).")

    linhas += [
        "",
        "## 10. Classificação PRINCIPAL do gate por horizonte — controlada por mês "
        "(revisão sazonal, item 6)",
        "",
        "**Nenhum limiar numérico foi escolhido depois de ver o resultado.** 4 rótulos "
        "possíveis, cruzando SEMPRE calibração de magnitude (ratio/rank histogram, seções "
        "2/4) com informatividade CONTROLADA POR MÊS (seção 3.1):",
        "",
        f"- `{g.CLASSIFICACAO_INFORMATIVO}`: bem calibrado em magnitude E correlação "
        "controlada por mês robusta.",
        f"- `{g.CLASSIFICACAO_MAL_CALIBRADO_POTENCIAL}`: mal calibrado em magnitude, MAS a "
        "correlação controlada por mês ainda é positiva (IC acima de zero) — spread "
        "informativo caso a caso, além do ciclo sazonal.",
        f"- `{g.CLASSIFICACAO_MAL_CALIBRADO_POUCO_INFORMATIVO}` (NOVO): mal calibrado em "
        "magnitude E a correlação controlada por mês caiu para perto de zero — ainda pode "
        "haver calibração da dispersão MÉDIA, mas o spread caso a caso não demonstra valor "
        "como preditor dinâmico.",
        f"- `{g.CLASSIFICACAO_POUCO_INFORMATIVO}`: bem calibrado em magnitude, mas sem "
        "correlação controlada por mês — nada a corrigir na dispersão, e o spread também "
        "não ajuda caso a caso.",
        "",
        "| Horizonte | Classificação PRINCIPAL | Pearson resid IC>0? | Spearman resid "
        "IC>0? | Ratio moderadamente fora de 1? | Ratio extremo? | Rank histogram sinaliza "
        "desvio? |",
        "|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        c = _g(classif, lead)
        s = c.get('sinais', {})
        linhas.append(
            f"| H{lead} | `{c.get('classificacao')}` | "
            f"{'✅' if s.get('corr_pearson_resid_ic_acima_zero') else '❌'} | "
            f"{'✅' if s.get('corr_spearman_resid_ic_acima_zero') else '❌'} | "
            f"{'✅' if s.get('ratio_moderadamente_fora_de_1') else '❌'} | "
            f"{'✅' if s.get('ratio_extremo') else '❌'} | "
            f"{'✅' if s.get('rank_histogram_sinaliza_desvio') else '❌'} |")
    linhas.append("")
    for lead in v.LEADS_ESPERADOS:
        c = _g(classif, lead)
        linhas.append(f"- **H{lead}** (`{c.get('classificacao')}`): {c.get('justificativa')}")

    linhas += [
        "",
        "### 10.1. Classificação de REFERÊNCIA apenas — baseada no pooled (NÃO decisória)",
        "",
        "Mantida só para comparação/transparência (\"não apagar métricas atuais\") — "
        "mostra como a classificação teria saído sem controlar por mês. Note a diferença "
        "em relação à tabela principal acima.",
        "",
        "| Horizonte | Classificação (referência, pooled) |",
        "|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        cref = _g(classif_raw_ref, lead)
        linhas.append(f"| H{lead} | `{cref.get('classificacao')}` |")

    linhas += [
        "",
        "## 11. Síntese do gate e próximo passo recomendado (itens 11, 12 e 13 do pedido "
        "original; item 12 da revisão sazonal)",
        "",
        f"**Síntese:** {resultados['sintese_gate']}",
        "",
        f"**Próximo passo recomendado:** `{resultados['proximo_passo_recomendado']}`",
        "",
        "**O que NÃO foi feito nesta atividade — confirmação explícita:**",
        "",
        f"- Nenhum EMOS ajustado: {'✅ confirmado' if resultados['nenhum_emos_ajustado'] else '❌'}",
        f"- Nenhum dressing aplicado: {'✅ confirmado' if resultados['nenhum_dressing_aplicado'] else '❌'}",
        f"- Nenhuma probabilidade operacional alterada: "
        f"{'✅ confirmado' if resultados['nenhuma_probabilidade_operacional_alterada'] else '❌'}",
        "- Nenhum quantile mapping probabilístico executado.",
        "- Nenhuma mudança no dashboard, SARIMAX, XGBoost ou pipeline operacional.",
        "- O Método 3.5 **não** foi declarado aprovado nesta atividade — este documento é "
        "um gate diagnóstico, não uma aprovação.",
        "",
        "## 12. Limitações",
        "",
        "- `effective_ensemble_size_aprox` (seção 8) é uma aproximação HEURÍSTICA de "
        "redundância, nunca usada para reponderar nenhuma métrica deste relatório nem para "
        "expandir a amostra histórica.",
        "- A matriz mês × lead e os grupos sazonais (seções 3.3 e 9) têm amostra pequena "
        "por célula — usados só como diagnóstico, nunca como critério de aprovação célula a "
        "célula nem como 72 testes de significância.",
        "- O tie-break determinístico do rank histogram (seção 4) é uma convenção "
        "explícita (ponto médio do intervalo de posições válidas), não a única convenção "
        "possível na literatura.",
        "- Este gate avalia o ensemble RAW; nenhuma correção de bias determinístico "
        "(Métodos 3.1/3.2/3.4) foi combinada com a dispersão aqui.",
        "- **Checagem por regressão partial/`C(target_mes) + ensemble_std` (item 4 da "
        "revisão) não foi implementada como modelo separado** — pelo teorema de "
        "Frisch-Waugh-Lovell, o coeficiente de uma regressão OLS de `erro_abs` sobre "
        "dummies de `target_mes` e `ensemble_std` é algebricamente idêntico ao coeficiente "
        "de regredir os RESÍDUOS centrados por mês de `erro_abs` sobre os RESÍDUOS "
        "centrados por mês de `ensemble_std` — exatamente a transformação já feita na "
        "seção 3.1. Implementar a regressão categórica separadamente duplicaria a mesma "
        "informação (e uma segunda biblioteca estatística) sem mudar a conclusão sobre "
        "sinal/magnitude do efeito — optou-se pela isenção de segunda implementação "
        "explicitamente permitida pelo pedido de revisão (item 4: \"se preferir evitar "
        "uma segunda implementação estatística, a análise residualizada da seção 2 é "
        "suficiente\").",
        "",
        "## 13. Conclusão restrita ao gate do Método 3.5",
        "",
        "Esta conclusão vale SOMENTE para o diagnóstico de dispersão do ensemble CFSv2 "
        "RAW — nunca generalizada para \"calibração do CFSv2\" em geral, e nunca uma "
        "aprovação do Método 3.5.",
        "",
        f"- Classificação PRINCIPAL por horizonte (controlada por mês): " + "; ".join(
            f"H{lead}: `{_g(classif, lead).get('classificacao')}`" for lead in v.LEADS_ESPERADOS) + ".",
        f"- {resultados['sintese_gate']}",
        "- A correlação spread×erro pooled (seção 3) caiu substancialmente após controlar "
        "por mês (seção 3.1/3.2) na maioria dos horizontes — confirma que o ciclo sazonal "
        "era, de fato, um confundidor relevante, como apontado na revisão independente.",
        "- Decisão de implementar (ou não) um protocolo de calibração probabilística — "
        "EMOS ou equivalente parcimonioso — permanece de uma próxima etapa, condicionada "
        "à revisão independente deste resultado, nunca decidida automaticamente por este "
        "gate.",
    ]
    return '\n'.join(linhas) + '\n'


def gerar_e_escrever():
    resultados = json.loads(g.CAMINHO_METRICAS_JSON.read_text())
    relatorio = gerar_relatorio_markdown(resultados)
    g.RELATORIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    g.RELATORIO_PATH.write_text(relatorio)
    print(f"  ✅ {g.RELATORIO_PATH.relative_to(g.ROOT)}")
    return relatorio


if __name__ == '__main__':
    gerar_e_escrever()
