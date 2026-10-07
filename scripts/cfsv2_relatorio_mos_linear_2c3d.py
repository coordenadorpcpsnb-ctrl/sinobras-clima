#!/usr/bin/env python3
"""
cfsv2_relatorio_mos_linear_2c3d.py — gera
docs/nmme-fase2c3d-mos-linear-cfsv2.md a partir de
data/cfsv2_calibracao_2c3d/metricas_mos_linear_2c3d.json (já calculado
por scripts/cfsv2_calibracao_mos_linear.py --executar). Nunca recalcula
nada aqui — só lê e formata. Nunca chama o método de validado ou
pronto para produção, e nunca usa o termo "nowcast"/"nowcasting" para
H1.

Roda com:
    python scripts/cfsv2_relatorio_mos_linear_2c3d.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import cfsv2_calibracao_mos_linear as mos  # noqa: E402
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


def _g(dic, lead):
    return dic.get(lead, dic.get(str(lead), {}))


def gerar_relatorio_markdown(resultados):
    if resultados.get('STOP_ON_FAILURE'):
        return (
            "# MOS linear causal no espaço de anomalias — Fase 2C.3D (Método 3.4)\n\n"
            "**STOP-ON-FAILURE — métricas NÃO calculadas.**\n\n"
            f"Motivo: {resultados.get('motivo')}\n\n"
            f"Detalhe: {json.dumps(resultados.get('detalhe', {}), ensure_ascii=False)}\n"
        )

    exp = resultados['expanding_operational_simulation']
    det = exp['deterministico_por_horizonte']
    boot = exp['intervalos_confianca_skills_por_horizonte']
    mml = exp['matriz_mes_lead']
    mgsl = exp['matriz_grupo_sazonal_lead']
    het = exp['diagnostico_heterogeneidade_variancia']
    primeira = resultados['primeira_inicializacao_elegivel_por_lead']
    loyo_full = resultados['loyo_retrospective']
    loyo_matched = resultados['loyo_matched_evaluation_period']

    def _criterio_aprovacao(lead):
        d = _g(boot, lead)
        if not d.get('amostra_suficiente', False):
            return False, 'amostra insuficiente'
        c1 = d.get('skill_vs_anomalia_reconstruida_ic_classificacao') == 'ic_totalmente_acima_de_zero'
        c2 = d.get('RMSESS_climatologia_ic_classificacao') == 'ic_totalmente_acima_de_zero'
        return (c1 and c2), ('ambas condições atendidas' if (c1 and c2) else
                              'skill_vs_anomalia_reconstruida OK, RMSESS_climatologia não' if c1 else
                              'RMSESS_climatologia OK, skill_vs_anomalia_reconstruida não' if c2 else
                              'nenhuma das duas condições atendida')

    criterio_por_horizonte = {lead: _criterio_aprovacao(lead) for lead in v.LEADS_ESPERADOS}
    nenhum_horizonte_aprovado = not any(ok for ok, _ in criterio_por_horizonte.values())

    def _evidencia_vs_aditivo(lead):
        d = _g(boot, lead)
        cl = d.get('skill_mos_vs_aditivo_ic_classificacao')
        if cl == 'ic_totalmente_acima_de_zero':
            return 'MOS MELHOR que o aditivo (IC acima de zero)'
        if cl == 'ic_totalmente_abaixo_de_zero':
            return 'MOS PIOR que o aditivo (IC abaixo de zero)'
        return 'sem evidência de diferença estatisticamente distinguível (IC inclui zero)'

    linhas = [
        "# MOS linear causal no espaço de anomalias — Fase 2C.3D (Método 3.4)",
        "",
        "**Relatório técnico — avaliação OFFLINE e científica, completamente separada do "
        "sistema operacional. Nenhuma correção foi aplicada ao dashboard, SARIMAX, XGBoost, "
        "pipeline operacional, `serie_subst.csv`, CFSv2 RAW, CHIRPS v3 histórico, à base "
        "pareada da 2C.3C, nem aos artefatos já aprovados dos Métodos 3.1/3.2 e do gate do "
        "Método 3.3 — todos só lidos, nunca alterados.**",
        "",
        "## 1. Metodologia",
        "",
        "```",
        "anom_modelo_raw = forecast_raw - climatologia_modelo_raw",
        "anom_observada  = observacao   - climatologia_observada",
        "anom_observada  = alpha_lead + beta_lead * anom_modelo_raw + erro   (OLS, por lead)",
        "forecast_mos    = climatologia_observada + alpha_lead + beta_lead * anom_modelo_raw",
        "```",
        "",
        "Apenas 2 parâmetros por horizonte (`alpha_lead`, `beta_lead`) — sem mês-dummy, "
        "interação, ENSO, tendência, termo quadrático, regularização ou seleção automática "
        "nesta primeira versão. Treino por `lead`, agregando TODOS os meses (pooling entre "
        "meses deliberado — nunca entre leads).",
        "",
        "## 2. Pares válidos e warm-up",
        "",
        f"`N_TREINO_MINIMO_MOS = {resultados['n_treino_minimo_mos']}` **pares de anomalias "
        "válidas** (nunca inicializações simplesmente contadas) — uma linha só conta se "
        "`forecast_raw`, `observacao`, `climatologia_modelo_raw`, `climatologia_observada`, "
        "`anom_modelo_raw` e `anom_observada` forem TODOS finitos.",
        "",
        "| Status | Significado |",
        "|---|---|",
        f"| `{mos.STATUS_OK}` | par válido, `n_treino_mos >= {resultados['n_treino_minimo_mos']}`, OLS ajustado com sucesso |",
        f"| `{mos.STATUS_WARMUP}` | par válido na própria linha, mas histórico de pares válidos ainda insuficiente |",
        f"| `{mos.STATUS_ANOMALIA_INDISPONIVEL}` | a própria linha avaliada não tem par de anomalia válido (tipicamente por falta de climatologia própria do modelo ainda causalmente disponível) |",
        f"| `{mos.STATUS_DEGENERADA}` | variância de `anom_modelo_raw` no treino abaixo do critério numérico fixo ({resultados['variancia_minima_anom_modelo']}) ou matriz de posto deficiente |",
        f"| `{mos.STATUS_COEF_INVALIDO}` | `alpha`/`beta` resultantes não finitos |",
        "",
        "## 3. Auditoria anti-leakage",
        "",
        f"- Identidade algébrica do `benchmark_anomalia_reconstruida`: "
        f"{'✅ OK' if resultados['identidade_benchmark3']['identidade_ok'] else '❌ FALHOU'} "
        f"(diferença máxima absoluta = {resultados['identidade_benchmark3']['max_diff_absoluto']:.2e}, "
        f"{resultados['identidade_benchmark3']['n_verificado']} linhas verificadas).",
        f"- Verificação de leakage (periodo_treino_fim sempre < init_date avaliada): "
        f"{'✅ OK' if resultados['leakage_check']['ok'] else '❌ FALHOU'} "
        f"({resultados['leakage_check']['n_problemas']} problemas encontrados).",
        f"- Verificação de que nenhum outro lead contaminou o treino: "
        f"{'✅ OK' if resultados['verificacao_outro_lead_nunca_contaminou_treino']['ok'] else '❌ FALHOU'}.",
        "- Testes automatizados (nenhuma linha de treino com `init_date >= avaliada`; própria "
        "linha nunca entra no OLS; outro lead nunca entra no treino; observação/forecast/"
        "climatologia futuros nunca alteram alpha/beta/anomalias históricas passadas; linhas "
        "sem par válido nunca contam para `n_treino_mos`; nenhuma linha NaN/Inf entra no OLS; "
        "demonstração sintética de leakage bloqueado) — ver "
        "`tests/test_cfsv2_calibracao_mos_linear.py`.",
        "",
        "## 4. Primeira elegibilidade por H1-H6 (derivada programaticamente)",
        "",
        "| Horizonte | Primeira `init_date` elegível | `n_treino_mos` nessa data | Linhas "
        "anteriores descartadas por anomalia indisponível |",
        "|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        p = _g(primeira, lead)
        linhas.append(f"| {v.ROTULO_HORIZONTE[lead]} | {p.get('primeira_init_date_elegivel', 'N/D')} | "
                       f"{p.get('n_treino_mos_nessa_data', 'N/D')} | "
                       f"{p.get('n_linhas_descartadas_por_anomalia_indisponivel_antes_dessa_data', 'N/D')} |")
    linhas += [
        "",
        "**Nenhuma data foi assumida a priori** (a versão anterior deste protocolo sugeria "
        "~2001; a implementação real confirma a data verdadeira, tipicamente adiada por causa "
        "das primeiras inicializações de cada lead, que ainda não têm climatologia própria do "
        "modelo disponível — ver tabela acima).",
        "",
        "## 5. Coeficientes alpha/beta por horizonte",
        "",
        "| Horizonte | N | alpha mín | alpha p10 | alpha mediana | alpha média | alpha p90 | "
        "alpha máx |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(det, lead)
        al = d.get('alpha', {})
        if al.get('n', 0) == 0:
            linhas.append(f"| H{lead} | 0 | — | — | — | — | — | — |")
            continue
        linhas.append(f"| H{lead} | {al['n']} | {_fmt(al['minimo'])} | {_fmt(al['p10'])} | "
                       f"{_fmt(al['mediana'])} | {_fmt(al['media'])} | {_fmt(al['p90'])} | "
                       f"{_fmt(al['maximo'])} |")
    linhas += [
        "",
        "| Horizonte | N | beta mín | beta p10 | beta mediana | beta média | beta p90 | "
        "beta máx |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(det, lead)
        be = d.get('beta', {})
        if be.get('n', 0) == 0:
            linhas.append(f"| H{lead} | 0 | — | — | — | — | — | — |")
            continue
        linhas.append(f"| H{lead} | {be['n']} | {_fmt(be['minimo'], 3)} | {_fmt(be['p10'], 3)} | "
                       f"{_fmt(be['mediana'], 3)} | {_fmt(be['media'], 3)} | {_fmt(be['p90'], 3)} | "
                       f"{_fmt(be['maximo'], 3)} |")

    linhas += [
        "",
        "**Leitura pré-registrada (protocolo, Seção 8) — nunca uma classificação automática "
        "do método**:",
        "",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(det, lead)
        be = d.get('beta', {})
        if be.get('n', 0) == 0:
            continue
        destaques = []
        if be['mediana'] <= 0:
            destaques.append('beta mediano <= 0 — indicador inverso, destaque científico '
                              'obrigatório, investigar antes de qualquer conclusão')
        elif be['mediana'] < 0.9:
            destaques.append(f"beta mediano {be['mediana']:.3f} < 0,9 — sugere amortecimento "
                              "das anomalias do CFSv2")
        elif be['mediana'] > 1.1:
            destaques.append(f"beta mediano {be['mediana']:.3f} > 1,1 — sugere amplificação")
        else:
            destaques.append(f"beta mediano {be['mediana']:.3f} próximo de 1 — comportamento "
                              "semelhante ao benchmark_anomalia_reconstruida")
        linhas.append(f"- H{lead}: {'; '.join(destaques)}.")

    linhas += [
        "",
        "## 6. Diagnóstico de estabilidade",
        "",
        "| Horizonte | N | R² treino mín | R² treino p10 | R² treino mediana | R² treino "
        "média | R² treino p90 | R² treino máx |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(det, lead)
        r2 = d.get('r2_treino', {})
        if r2.get('n', 0) == 0:
            linhas.append(f"| H{lead} | 0 | — | — | — | — | — | — |")
            continue
        linhas.append(f"| H{lead} | {r2['n']} | {_fmt(r2['minimo'], 3)} | {_fmt(r2['p10'], 3)} | "
                       f"{_fmt(r2['mediana'], 3)} | {_fmt(r2['media'], 3)} | {_fmt(r2['p90'], 3)} | "
                       f"{_fmt(r2['maximo'], 3)} |")
    linhas += [
        "",
        "**`R² treino` nunca é usado como evidência de skill** — é o ajuste DENTRO da amostra "
        "de treino de cada linha, não uma medida de desempenho fora da amostra (essa vem da "
        "seção 9, sobre casos nunca vistos no próprio treino daquela linha).",
        "",
        "## 7. Heterogeneidade de variância mensal — só diagnóstico",
        "",
        f"Verificação de que as participações no `sum(x²)` somam ~1 dentro de cada lead: "
        f"{'✅ OK' if het['verificacao_soma_participacoes_ok'] else '❌ FALHOU'} "
        f"({json.dumps(het['verificacao_soma_participacoes_por_lead'])}).",
        "",
        "`" + het['nota'] + "`",
        "",
    ]
    for lead in v.LEADS_ESPERADOS:
        linhas.append(f"### 7.{lead}. H{lead}")
        linhas.append("")
        linhas.append("| Mês | N | Desvio padrão anom. modelo | Desvio padrão anom. observada | "
                       "RMSE benchmark3 | Participação no sum(x²) |")
        linhas.append("|---|---|---|---|---|---|")
        matriz_lead = _g(het['matriz'], lead)
        for mes in range(1, 13):
            cel = _g(matriz_lead, mes)
            if cel.get('n', 0) == 0:
                linhas.append(f"| {NOMES_MES[mes-1]} | 0 | — | — | — | — |")
                continue
            linhas.append(f"| {NOMES_MES[mes-1]} | {cel['n']} | "
                           f"{_fmt(cel['desvio_padrao_anom_modelo_raw'])} | "
                           f"{_fmt(cel['desvio_padrao_anom_observada'])} | "
                           f"{_fmt(cel['rmse_benchmark3'])} | "
                           f"{_fmt(cel['participacao_no_sum_x2_do_lead'], 3)} |")
        linhas.append("")
    linhas.append("**Nenhuma reponderação do OLS, nenhuma padronização e nenhum mês dominante "
                   "removido nesta versão do Método 3.4** — esta seção serve só para verificar "
                   "se `beta_lead` está sendo dominado por poucos meses de alta variância, "
                   "antes de interpretar o coeficiente como representativo do horizonte.")

    linhas += [
        "",
        "## 8. Resultados determinísticos H1-H6",
        "",
        "| Horizonte | N | Bias | MAE | RMSE | Corr. absoluta | Corr. anomalia |",
        "|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(det, lead)
        if d.get('n', 0) == 0:
            linhas.append(f"| H{lead} | 0 | — | — | — | — | — |")
            continue
        linhas.append(f"| H{lead} | {d['n']} | {_fmt(d['bias'])} | {_fmt(d['mae'])} | "
                       f"{_fmt(d['rmse'])} | {_fmt(d['corr_absoluta'], 3)} | "
                       f"{_fmt(d['corr_anomalia'], 3)} |")

    linhas += [
        "",
        "## 9. Comparação contra os três benchmarks pré-registrados",
        "",
        "`skill_vs_X = 1 - RMSE_mos / RMSE_X` — numerador e denominador sempre sobre "
        "exatamente os mesmos casos elegíveis.",
        "",
        "| Horizonte | RMSE MOS | RMSE bruto | RMSE climatologia | RMSE benchmark3 | "
        "skill_vs_raw | RMSESS_climatologia | skill_vs_anomalia_reconstruida |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(det, lead)
        if d.get('n', 0) == 0:
            linhas.append(f"| H{lead} | — | — | — | — | — | — | — |")
            continue
        linhas.append(f"| H{lead} | {_fmt(d['rmse'])} | {_fmt(d['rmse_raw'])} | "
                       f"{_fmt(d['rmse_climatologia'])} | "
                       f"{_fmt(d['rmse_benchmark_anomalia_reconstruida'])} | "
                       f"{_fmt(d['skill_vs_raw'], 3)} | {_fmt(d['RMSESS_climatologia'], 3)} | "
                       f"{_fmt(d['skill_vs_anomalia_reconstruida'], 3)} |")

    linhas += [
        "",
        "## 10. Comparação PRINCIPAL — MOS vs. aditivo (Método 3.1), amostra pareada",
        "",
        "`skill_mos_vs_aditivo = 1 - RMSE_mos / RMSE_aditivo_matched` — SEMPRE sobre a MESMA "
        "amostra pareada (`aditiva_matched_mos_sample`, mesmas chaves `init_date×lead` nos "
        "dois lados). **Nunca comparado contra o aditivo full** (que usaria amostras "
        "diferentes).",
        "",
        "| Horizonte | RMSE MOS | RMSE aditivo (matched) | skill_mos_vs_aditivo |",
        "|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(det, lead)
        if d.get('n', 0) == 0:
            linhas.append(f"| H{lead} | — | — | — |")
            continue
        linhas.append(f"| H{lead} | {_fmt(d['rmse'])} | {_fmt(d['rmse_aditivo_matched'])} | "
                       f"{_fmt(d['skill_mos_vs_aditivo'], 3)} |")

    linhas += [
        "",
        "## 11. Intervalos de confiança (bootstrap em blocos por target_ano)",
        "",
        "MOS, os três benchmarks E o aditivo matched sempre nos MESMOS blocos de ano "
        "sorteados em cada reamostra. **Classificação meramente descritiva.**",
        "",
        "| Horizonte | skill_vs_raw | IC 95% | skill_vs_anomalia_reconstruida | IC 95% | "
        "skill_mos_vs_aditivo | IC 95% | Evidência vs. aditivo |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(boot, lead)
        if not d.get('amostra_suficiente', False):
            linhas.append(f"| H{lead} | — | — | — | — | — | — | {d.get('nota', 'amostra insuficiente')} |")
            continue
        r = d['skill_vs_raw']
        an = d['skill_vs_anomalia_reconstruida']
        adv = d['skill_mos_vs_aditivo']
        linhas.append(
            f"| H{lead} | {_fmt(r['estimativa'], 3)} | [{_fmt(r['ic95_lo'], 3)}, {_fmt(r['ic95_hi'], 3)}] | "
            f"{_fmt(an['estimativa'], 3)} | [{_fmt(an['ic95_lo'], 3)}, {_fmt(an['ic95_hi'], 3)}] | "
            f"{_fmt(adv['estimativa'], 3)} | [{_fmt(adv['ic95_lo'], 3)}, {_fmt(adv['ic95_hi'], 3)}] | "
            f"{_evidencia_vs_aditivo(lead)} |")

    linhas += [
        "",
        "### 11.1. Avaliação do critério de aprovação pré-registrado",
        "",
        "| Horizonte | skill_vs_anomalia_reconstruida acima de zero? | RMSESS_climatologia "
        "acima de zero? | Atende ao critério? | skill_mos_vs_aditivo (informativo) |",
        "|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(boot, lead)
        c1 = d.get('skill_vs_anomalia_reconstruida_ic_classificacao') == 'ic_totalmente_acima_de_zero'
        c2 = d.get('RMSESS_climatologia_ic_classificacao') == 'ic_totalmente_acima_de_zero'
        ok, _ = criterio_por_horizonte[lead]
        cl_adit = d.get('skill_mos_vs_aditivo_ic_classificacao')
        linhas.append(f"| H{lead} | {'✅ sim' if c1 else '❌ não'} | {'✅ sim' if c2 else '❌ não'} | "
                       f"{'✅ SIM' if ok else '❌ NÃO'} | {_ic_texto(cl_adit)} |")
    linhas += [
        "",
        f"**{'Nenhum horizonte H1–H6 atende integralmente ao critério pré-registrado de aprovação do Método 3.4 nesta rodada.' if nenhum_horizonte_aprovado else 'Ao menos um horizonte atendeu integralmente ao critério — ver tabela acima.'}** "
        "O critério nunca foi alterado depois de observar este resultado.",
        "",
        "## 12. Matriz mês-alvo × lead (diagnóstico de heterogeneidade — NUNCA 72 testes de "
        "significância)",
        "",
        "### 12.1. N elegível por célula",
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
        "### 12.2. skill_vs_anomalia_reconstruida por célula",
        "",
        "| Mês \\ Lead | " + " | ".join(f"H{l}" for l in v.LEADS_ESPERADOS) + " |",
        "|---" * (len(v.LEADS_ESPERADOS) + 1) + "|",
    ]
    for mes in range(1, 13):
        por_lead = _g(mml, mes)
        celulas = []
        for lead in v.LEADS_ESPERADOS:
            cel = _g(por_lead, lead)
            if cel.get('n', 0) == 0:
                celulas.append('—')
                continue
            aviso = '*' if not cel.get('amostra_suficiente', True) else ''
            celulas.append(f"{_fmt(cel.get('skill_vs_anomalia_reconstruida'), 3)}{aviso}")
        linhas.append(f"| {NOMES_MES[mes-1]} | " + " | ".join(celulas) + " |")

    linhas += [
        "",
        "### 12.3. skill_mos_vs_aditivo por célula",
        "",
        "| Mês \\ Lead | " + " | ".join(f"H{l}" for l in v.LEADS_ESPERADOS) + " |",
        "|---" * (len(v.LEADS_ESPERADOS) + 1) + "|",
    ]
    for mes in range(1, 13):
        por_lead = _g(mml, mes)
        celulas = []
        for lead in v.LEADS_ESPERADOS:
            cel = _g(por_lead, lead)
            if cel.get('n', 0) == 0:
                celulas.append('—')
                continue
            aviso = '*' if not cel.get('amostra_suficiente', True) else ''
            celulas.append(f"{_fmt(cel.get('skill_mos_vs_aditivo'), 3)}{aviso}")
        linhas.append(f"| {NOMES_MES[mes-1]} | " + " | ".join(celulas) + " |")
    linhas.append("")
    linhas.append(f"*`*` = célula com N abaixo da amostra mínima do projeto "
                   f"({v.AMOSTRA_MINIMA_ESTRATO}).*")

    linhas += [
        "",
        "## 13. Grupos sazonais (chuvosa/transição/seca) × lead — diagnóstico complementar",
        "",
        "| Grupo | Métrica | " + " | ".join(f"H{l}" for l in v.LEADS_ESPERADOS) + " |",
        "|---" * (len(v.LEADS_ESPERADOS) + 2) + "|",
    ]
    for grupo in ('chuvosa', 'transicao', 'seca'):
        por_lead = _g(mgsl, grupo)
        linha_n = [str(_g(por_lead, lead).get('n', 0)) for lead in v.LEADS_ESPERADOS]
        linhas.append(f"| {grupo} | N | " + " | ".join(linha_n) + " |")
        linha_skill = [_fmt(_g(por_lead, lead).get('skill_vs_anomalia_reconstruida'), 3)
                       for lead in v.LEADS_ESPERADOS]
        linhas.append(f"| {grupo} | skill_vs_anomalia_reconstruida | " + " | ".join(linha_skill) + " |")
        linha_adit = [_fmt(_g(por_lead, lead).get('skill_mos_vs_aditivo'), 3)
                      for lead in v.LEADS_ESPERADOS]
        linhas.append(f"| {grupo} | skill_mos_vs_aditivo | " + " | ".join(linha_adit) + " |")

    linhas += [
        "",
        "## 14. Comparação expanding vs. LOYO matched",
        "",
        f"**LOYO full** (`{loyo_full['rotulo']}`): {loyo_full['aviso']}",
        "",
        f"**LOYO matched** (`{loyo_matched['rotulo']}`) — comparação PRINCIPAL, mesmas chaves "
        "do expanding:",
        "",
        "| Horizonte | N expanding | N LOYO matched | RMSE expanding | RMSE LOYO matched | "
        "delta skill_vs_raw | delta RMSESS_climatologia | delta skill_vs_anomalia_reconstruida |",
        "|---|---|---|---|---|---|---|---|",
    ]
    comp_loyo = loyo_matched['comparacao_expanding_vs_loyo_matched']
    for lead in v.LEADS_ESPERADOS:
        c = _g(comp_loyo, lead)
        linhas.append(f"| H{lead} | {c.get('n_expanding', 0)} | {c.get('n_loyo_matched', 0)} | "
                       f"{_fmt(c.get('rmse_expanding'))} | {_fmt(c.get('rmse_loyo_matched'))} | "
                       f"{_fmt(c.get('delta_skill_vs_raw'), 4)} | "
                       f"{_fmt(c.get('delta_RMSESS_climatologia'), 4)} | "
                       f"{_fmt(c.get('delta_skill_vs_anomalia_reconstruida'), 4)} |")
    linhas.append("")
    linhas.append("**Delta meramente descritivo — nunca um teste de significância automático. "
                   "LOYO full (amostra diferente) nunca comparado diretamente com o expanding "
                   "— só a comparação matched acima é interpretável.**")

    linhas += [
        "",
        "## 15. Limitações",
        "",
        "- Warm-up de 120 pares válidos reduz substancialmente a amostra de avaliação "
        "principal em relação ao total de 240 inicializações — perda deliberada de poder "
        "estatístico em troca de defensabilidade metodológica (protocolo, Seção 6).",
        "- O pooling entre meses (Seção 3 do protocolo) assume implicitamente que a relação "
        "`alpha`/`beta` é homogênea entre meses — a seção 7 (heterogeneidade de variância) "
        "mostra até que ponto isso é razoável, mas não corrige por isso nesta versão.",
        "- `R² treino` (seção 6) não é uma medida de skill fora da amostra — nunca interpretado "
        "como tal.",
        "- A matriz mês × lead (seção 12) e os grupos sazonais (seção 13) têm amostra pequena "
        "por célula — usados só como diagnóstico de heterogeneidade, nunca como critério de "
        "aprovação célula a célula.",
        "- Nenhuma correção operacional de viés foi aplicada — permanece avaliação científica "
        "offline.",
        "",
        "## 16. Conclusão restrita ao Método 3.4 (MOS linear)",
        "",
        "Esta conclusão vale SOMENTE para o MOS linear causal no espaço de anomalias, treinado "
        "por lead com pooling entre meses — nunca generalizada para \"calibração do CFSv2\" em "
        "geral, nunca chamando o modelo de validado ou pronto para produção.",
        "",
        f"- Critério pré-registrado de aprovação: " + (
            "nenhum horizonte H1-H6 satisfaz simultaneamente os dois critérios estatísticos "
            "principais (seção 11.1)" if nenhum_horizonte_aprovado else
            "ao menos um horizonte satisfaz simultaneamente os dois critérios principais — "
            "ver seção 11.1") + ".",
        "- Comparação principal com o Método 3.1 (seção 10/11): " + "; ".join(
            f"H{lead}: {_evidencia_vs_aditivo(lead)}" for lead in v.LEADS_ESPERADOS) + ".",
        "- Não implementar extensão do modelo (dummy mensal, interação, ENSO, tendência, "
        "termo quadrático, regularização, seleção automática), quantile mapping, nem "
        "correção híbrida nesta atividade — decisões de uma próxima etapa, condicionadas à "
        "revisão independente deste resultado.",
    ]
    return '\n'.join(linhas) + '\n'


def gerar_e_escrever():
    resultados = json.loads(mos.CAMINHO_METRICAS_JSON.read_text())
    relatorio = gerar_relatorio_markdown(resultados)
    mos.RELATORIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    mos.RELATORIO_PATH.write_text(relatorio)
    print(f"  ✅ {mos.RELATORIO_PATH.relative_to(mos.ROOT)}")
    return relatorio


if __name__ == '__main__':
    gerar_e_escrever()
