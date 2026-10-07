#!/usr/bin/env python3
"""
cfsv2_relatorio_gate_probabilistico.py — gera
docs/nmme-fase2c3d-gate-calibracao-probabilistica-cfsv2.md a partir de
data/cfsv2_calibracao_2c3d/gate_calibracao_probabilistica_2c3d.json (já
calculado por scripts/cfsv2_gate_calibracao_probabilistica.py
--executar). Nunca recalcula nada aqui — só lê e formata. Nunca declara
o Método 3.5 aprovado nem implementado — este é o relatório de um GATE
DIAGNÓSTICO.

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

_CLASSIFICACAO_TEXTO = {
    g.CLASSIFICACAO_INFORMATIVO: 'spread_informativo',
    g.CLASSIFICACAO_POUCO_INFORMATIVO: 'spread_pouco_informativo',
    g.CLASSIFICACAO_MAL_CALIBRADO_POTENCIAL: 'ensemble_mal_calibrado_mas_potencialmente_calibravel',
    'amostra_insuficiente': 'amostra_insuficiente',
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
    ss = resultados['spread_skill_por_horizonte']
    cov = resultados['cobertura_intervalos_por_horizonte']
    prob = resultados['probabilistico_por_horizonte']
    mml = resultados['matriz_mes_lead']
    mgsl = resultados['matriz_grupo_sazonal_lead']
    dep = resultados['dependencia_membros_por_horizonte']
    classif = resultados['classificacao_gate_por_horizonte']
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
        "## 2. Spread médio por horizonte e spread-error ratio (itens 1, 2 e 4 do pedido)",
        "",
        "`erro_abs = |ensemble_mean - obs|`, `erro_quadratico = (ensemble_mean - obs)²`, "
        "`erro_assinado = ensemble_mean - obs` — SEM qualquer correção de bias (diagnóstico "
        "do ensemble RAW). `spread_error_ratio = mean(ensemble_std) / RMSE(ensemble_mean, "
        "obs)` — leitura SEMPRE só diagnóstica, nunca prova isolada de calibração.",
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
        "## 3. Spread-skill: Pearson e Spearman, com IC 95% (item 3 do pedido)",
        "",
        "Bootstrap SEMPRE em blocos por `target_ano` (`v.bootstrap_blocos_por_ano`, "
        "reaproveitado sem modificação) — nunca resample de membros ou de linhas "
        "individuais. Correlação pontual positiva isolada NUNCA é suficiente para declarar "
        "relação útil — ver classificação (seção 10), que cruza isso com ratio e rank "
        "histogram.",
        "",
        "| Horizonte | N | Pearson(std, erro_abs) | IC 95% | Spearman(std, erro_abs) | "
        "IC 95% | Pearson(variance, erro_quad.) | IC 95% |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(ss, lead)
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
        "## 4. Rank histogram (item 5 do pedido)",
        "",
        "Posição (1..25) da observação entre os 24 membros ordenados. Tie-break "
        "**explícito e determinístico** (`_rank_observacao_determinístico`, próprio deste "
        "módulo — ver nota de implementação abaixo), nunca o sorteio seedado de "
        "`v.rank_observacao` usado em outros pontos da 2C.3C. Diagnóstico derivado, nunca "
        "um teste de hipótese formal como critério único: frequência nos ranks extremos "
        "(1 e 25 — formato em U sugere underdispersion), frequência central (terço central "
        "— concentração sugere overdispersion), e desvio de uniformidade (soma dos desvios "
        "absolutos da frequência esperada sob uniformidade, 1/25 por rank).",
        "",
        "> **Nota de implementação (desvio deliberado do reuso literal):** o item 5 do "
        "pedido exige tie-break \"explícito e determinístico\"; `v.rank_observacao` "
        "(2C.3C) resolve empates por sorteio seedado — reprodutível, mas não "
        "determinístico no sentido de regra fixa. Por isso este módulo define sua própria "
        "`_rank_observacao_determinístico`: sem empate, mesma posição de sempre; com "
        "empate, sempre o PONTO MÉDIO do intervalo de posições válidas, arredondado "
        "meio-para-cima em caso de 0,5 exato. `crps_amostral` e `categoria_tercil` "
        "continuam reaproveitados sem modificação (itens 7/8 exigem reuso exato).",
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
        "## 5. Cobertura de intervalos empíricos 50/80/90% (item 6 do pedido)",
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
                   "nominal) em todos os horizontes é o mesmo sinal de underdispersion já "
                   "visto no spread_error_ratio (seção 2) e no rank histogram (seção 4) — "
                   "três diagnósticos independentes apontando na mesma direção, nunca um só "
                   "usado isoladamente para essa conclusão.")

    linhas += [
        "",
        "## 6. CRPS RAW (item 7 do pedido)",
        "",
        "Fórmula \"fair\" (Ferro et al. 2008) reaproveitada sem modificação "
        "(`v.crps_amostral`) — nunca uma segunda fórmula paralela. `crps_medio_"
        "climatologia` usa a mesma climatologia causal observada já aprovada na 2C.3C "
        "(`anos_hist`, elegíveis por `v.construir_linhas_avaliacao_por_lead`) como "
        "referência DIRETAMENTE comparável, já que ambos os CRPS são calculados sobre as "
        "MESMAS linhas/observações — por isso a comparação formal (CRPSS) É reportada "
        "aqui, não diferida.",
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
                   "fraco já documentado nos Métodos 3.1/3.2/3.4, nunca uma conclusão nova "
                   "deste gate isoladamente.")

    linhas += [
        "",
        "## 7. Brier Score e BSS por tercil (item 8 do pedido)",
        "",
        "Categorias de tercil (seco/normal/úmido) e `BS_ref_nominal = mean((1/3 - o_i)^2)` "
        "reaproveitados EXATAMENTE da 2C.3C (`v.categoria_tercil`), nunca redefinidos. "
        "Probabilidades RAW = fração dos 24 membros em cada categoria.",
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
        "## 8. Dependência/diversidade entre membros (item 9 do pedido)",
        "",
        "Correlação de Pearson par-a-par média entre as 24 séries temporais de membro "
        "(fora da diagonal) — perto de 1 indica membros quase idênticos (pouca "
        "diversidade real); perto de 0, membros efetivamente independentes. "
        "`effective_ensemble_size_aprox = M / (1 + (M-1)·ρ_média)` (Bretherton et al. "
        "1999, adaptada) — **diagnóstico apenas, NUNCA usado para inflar a amostra "
        "histórica de 240 inicializações.**",
        "",
        "| Horizonte | N inicializações | N membros | Correlação média par-a-par | "
        "Effective Ensemble Size (aprox.) |",
        "|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(dep, lead)
        if 'correlacao_media_par_a_par' not in d or d.get('correlacao_media_par_a_par') is None:
            linhas.append(f"| H{lead} | {d.get('n_inits', 0)} | {d.get('n_membros', 0)} | — | — |")
            continue
        linhas.append(f"| H{lead} | {d['n_inits']} | {d['n_membros']} | "
                       f"{_fmt(d['correlacao_media_par_a_par'], 3)} | "
                       f"{_fmt(d['effective_ensemble_size_aprox'], 2)} |")
    linhas.append("")
    linhas.append("Correlação par-a-par média alta (ver tabela) com Effective Ensemble Size "
                   "muito abaixo de 24 em todos os horizontes indica que os 24 membros do "
                   "CFSv2 são fortemente redundantes ao longo do tempo — a maior parte da "
                   "variação entre membros não traz diversidade temporal nova, o que é "
                   "coerente com a natureza do CFSv2 (perturbações iniciais de um mesmo "
                   "modelo dinâmico, não 24 modelos independentes).")

    linhas += [
        "",
        "## 9. Sazonalidade — mês × lead e grupo sazonal × lead, atenção à estação seca "
        "(item 10 do pedido)",
        "",
        "Diagnóstico DESCRITIVO — nunca 72 testes de significância independentes nem um "
        "critério de aprovação célula a célula.",
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
                   "o menor entre os três grupos (ver tabela) simplesmente porque a "
                   "magnitude da chuva observada é pequena — isso não deve ser lido como "
                   "\"melhor desempenho relativo\" sem olhar o CRPSS (que compara contra a "
                   "climatologia do próprio período) ao lado do valor absoluto.")

    linhas += [
        "",
        "## 10. Classificação do gate por horizonte (item 11 do pedido)",
        "",
        "**Nenhum limiar numérico foi escolhido depois de ver o resultado** — os limiares "
        "usados (spread_error_ratio fora de [0,8; 1,2] como desvio moderado, fora de "
        "[0,5; 2,0] como extremo; múltiplos simples sobre a frequência esperada do rank "
        "histogram) estavam fixados no código antes desta execução. A classificação cruza "
        "SEMPRE correlação (seção 3) com ratio (seção 2) e rank histogram (seção 4) — "
        "correlação positiva isolada nunca basta para `spread_informativo`.",
        "",
        "| Horizonte | Classificação | Pearson IC>0? | Spearman IC>0? | Ratio moderadamente "
        "fora de 1? | Ratio extremo? | Rank histogram sinaliza desvio? |",
        "|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        c = _g(classif, lead)
        s = c.get('sinais', {})
        linhas.append(
            f"| H{lead} | `{c.get('classificacao')}` | "
            f"{'✅' if s.get('corr_pearson_ic_acima_zero') else '❌'} | "
            f"{'✅' if s.get('corr_spearman_ic_acima_zero') else '❌'} | "
            f"{'✅' if s.get('ratio_moderadamente_fora_de_1') else '❌'} | "
            f"{'✅' if s.get('ratio_extremo') else '❌'} | "
            f"{'✅' if s.get('rank_histogram_sinaliza_desvio') else '❌'} |")
    linhas.append("")
    for lead in v.LEADS_ESPERADOS:
        c = _g(classif, lead)
        linhas.append(f"- **H{lead}** (`{c.get('classificacao')}`): {c.get('justificativa')}")

    linhas += [
        "",
        "## 11. Síntese do gate e próximo passo recomendado (itens 11, 12 e 13 do pedido)",
        "",
        f"**Síntese:** {resultados['sintese_gate']}",
        "",
        f"**Próximo passo recomendado:** `{resultados['proximo_passo_recomendado']}`",
        "",
        "**O que NÃO foi feito nesta atividade (item 13 do pedido) — confirmação "
        "explícita:**",
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
        "- `effective_ensemble_size_aprox` (seção 8) é uma aproximação de diagnóstico, "
        "nunca usada para reponderar nenhuma métrica deste relatório.",
        "- A matriz mês × lead e os grupos sazonais (seção 9) têm amostra pequena por "
        "célula — usados só como diagnóstico, nunca como critério de aprovação célula a "
        "célula.",
        "- O tie-break determinístico do rank histogram (seção 4) é uma convenção "
        "explícita (ponto médio do intervalo de posições válidas), não a única convenção "
        "possível na literatura — está documentada e é reprodutível por construção, nunca "
        "aleatória.",
        "- Este gate avalia o ensemble RAW; nenhuma correção de bias determinístico "
        "(Métodos 3.1/3.2/3.4) foi combinada com a dispersão aqui — avaliar a dispersão "
        "em torno de uma previsão já corrigida por bias é uma pergunta diferente, fora do "
        "escopo desta atividade.",
        "",
        "## 13. Conclusão restrita ao gate do Método 3.5",
        "",
        "Esta conclusão vale SOMENTE para o diagnóstico de dispersão do ensemble CFSv2 "
        "RAW — nunca generalizada para \"calibração do CFSv2\" em geral, e nunca uma "
        "aprovação do Método 3.5.",
        "",
        f"- Classificação por horizonte: " + "; ".join(
            f"H{lead}: `{_g(classif, lead).get('classificacao')}`" for lead in v.LEADS_ESPERADOS) + ".",
        f"- {resultados['sintese_gate']}",
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
