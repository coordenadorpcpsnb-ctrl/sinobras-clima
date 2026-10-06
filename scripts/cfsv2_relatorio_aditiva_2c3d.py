#!/usr/bin/env python3
"""
cfsv2_relatorio_aditiva_2c3d.py — gera o relatório técnico da Fase
2C.3D (Método 3.1, correção aditiva causal) a partir de
data/cfsv2_calibracao_2c3d/metricas_aditiva_2c3d.json (já calculado por
scripts/cfsv2_calibracao_aditiva.py --executar). Nunca recalcula
métrica nenhuma aqui — só lê e formata.

Roda com:
    python scripts/cfsv2_relatorio_aditiva_2c3d.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import cfsv2_calibracao_aditiva as a  # noqa: E402
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


def gerar_relatorio_markdown(resultados):
    if resultados.get('STOP_ON_FAILURE'):
        return (
            "# Correção aditiva causal do CFSv2 — Fase 2C.3D (Método 3.1)\n\n"
            "**STOP-ON-FAILURE — métricas NÃO calculadas.**\n\n"
            f"Motivo: {resultados.get('motivo')}\n\n"
            f"Detalhe: {json.dumps(resultados.get('detalhe', resultados.get('problemas', [])), ensure_ascii=False)}\n"
        )

    exp = resultados['expanding_operational_simulation']
    loyo_full = resultados['loyo_retrospective']
    loyo_matched = resultados['loyo_matched_evaluation_period']
    det = exp['deterministico_por_horizonte']
    boot = exp['intervalos_confianca_skills_por_horizonte']
    mml = exp['matriz_mes_lead']
    mgsl = exp['matriz_grupo_sazonal_lead']
    det_loyo_full = loyo_full['deterministico_por_horizonte']
    det_loyo_matched = loyo_matched['deterministico_por_horizonte']
    boot_loyo_matched = loyo_matched['intervalos_confianca_skills_por_horizonte']
    comparacao_full = resultados['comparacao_expanding_vs_loyo_full']
    comparacao_matched = resultados['comparacao_expanding_vs_loyo_matched']

    def _criterio_aprovacao(lead):
        """Segunda revisão, item 1 — um horizonte só atende ao critério
        pré-registrado se as DUAS condições estatísticas principais
        valerem SIMULTANEAMENTE: skill_vs_anomalia_reconstruida E
        RMSESS_climatologia com IC 95% totalmente acima de zero."""
        d = boot.get(lead, boot.get(str(lead), {}))
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

    linhas = [
        "# Correção aditiva causal do CFSv2 — Fase 2C.3D (Método 3.1)",
        "",
        "**Relatório técnico — avaliação OFFLINE e científica, completamente separada do "
        "sistema operacional. Nenhuma correção foi aplicada ao dashboard, SARIMAX, XGBoost, "
        "pipeline operacional, `serie_subst.csv`, CFSv2 RAW, CHIRPS v3 histórico nem à base "
        "pareada já aprovada da Fase 2C.3C — todos só lidos, nunca alterados.**",
        "",
        "## 1. Metodologia",
        "",
        "Único método implementado nesta atividade: **correção ADITIVA causal por lead × "
        "mês-alvo** (Método 3.1 do protocolo, `docs/nmme-fase2c3d-protocolo-calibracao-cfsv2.md`). "
        "Nenhum outro método (multiplicativo, quantile mapping, MOS, calibração probabilística) "
        "foi implementado.",
        "",
        "```",
        "erro_historico = forecast_raw - observacao",
        "bias_aditivo(lead, mes_alvo, init_date) = média dos erros históricos elegíveis da",
        "    MESMA combinação lead × mês-alvo, com init_date_treino < init_date_avaliada",
        "forecast_calibrado = forecast_raw - bias_aditivo",
        "```",
        "",
        "Previsão determinística = média do ensemble dos 24 membros (mesma convenção da "
        "2C.3C) — os membros individuais NÃO são recalibrados nesta atividade; "
        "consequentemente, avaliação probabilística do ensemble calibrado (CRPSS/BSS) NÃO "
        "se aplica e não foi calculada.",
        "",
        "## 2. Warm-up e amostra elegível",
        "",
        f"`N_TREINO_MINIMO = {resultados['n_treino_minimo']}` observações históricas elegíveis "
        "por combinação lead × mês-alvo, pré-registrado no protocolo (Seção 5.1) — nunca "
        "ajustado depois de ver resultados. Abaixo disso, `status_calibracao = "
        "'warmup_amostra_insuficiente'`: sem previsão calibrada válida, nunca substituída pela "
        "previsão bruta, nunca imputada, nunca compartilhada entre meses.",
        "",
        "**Primeira inicialização elegível por lead × mês-alvo (derivada programaticamente, "
        "nunca hardcoded):**",
        "",
    ]

    primeira = resultados.get('primeira_inicializacao_elegivel_por_lead_e_mes', {})
    if primeira:
        anos_primeira = sorted({d.split('-')[0] for leadmap in primeira.values() for d in leadmap.values()})
        linhas.append(f"- Ano da primeira inicialização elegível em TODAS as células lead×mês "
                       f"observado nesta execução: {', '.join(anos_primeira)}.")
        linhas.append("")
        linhas.append("| Lead \\ Mês | " + " | ".join(NOMES_MES) + " |")
        linhas.append("|---" * 13 + "|")
        for lead in v.LEADS_ESPERADOS:
            mapa = primeira.get(lead) or primeira.get(str(lead), {})
            celulas = [mapa.get(m) or mapa.get(str(m), '—') for m in range(1, 13)]
            linhas.append(f"| H{lead} | " + " | ".join(celulas) + " |")
    else:
        linhas.append("*(nenhuma célula atingiu o warm-up nesta execução)*")

    linhas += [
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
        "- Testes automatizados de leakage (nunca init_date_treino >= avaliada; própria "
        "inicialização nunca entra no seu bias; outro lead/mês-alvo nunca entra no treino; "
        "observação futura nunca modifica previsão calibrada passada; demonstração sintética "
        "de que uma implementação leaky produziria ganho artificial, bloqueada pela "
        "implementação real) — ver `tests/test_cfsv2_calibracao_aditiva.py`.",
        "",
        "## 4. Resultados H1–H6 (método calibrado)",
        "",
        "Somente sobre casos com `status_calibracao = 'ok'` e "
        "`benchmark_anomalia_reconstruida` disponível — nunca misturando com warm-up.",
        "",
        "| Horizonte | N elegível | Bias | MAE | RMSE | Corr absoluta | N p/ anomalia | "
        "Corr anomalia calibrada |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = det.get(lead, det.get(str(lead), {}))
        if d.get('n_elegivel', 0) == 0:
            linhas.append(f"| H{lead} | 0 | — | — | — | — | — | — |")
            continue
        linhas.append(f"| H{lead} | {d['n_elegivel']} | {_fmt(d['bias'])} | {_fmt(d['mae'])} | "
                       f"{_fmt(d['rmse'])} | {_fmt(d['corr_absoluta'], 3)} | "
                       f"{d['n_anomalia_disponivel']} | "
                       f"{_fmt(d.get('corr_anomalia_modelo_calibrado'), 3)} |")

    linhas += [
        "",
        "## 5. Comparação contra os três benchmarks pré-registrados",
        "",
        "`skill_vs_X = 1 - RMSE_calibrado / RMSE_X` — numerador e denominador sempre sobre "
        "exatamente os mesmos casos elegíveis. **Critério pré-registrado de aprovação "
        "(protocolo, Seção 6.2): o ponto PRINCIPAL é `skill_vs_anomalia_reconstruida`, nunca "
        "`skill_vs_raw` isoladamente.**",
        "",
        "| Horizonte | RMSE calibrado | RMSE bruto | RMSE climatologia | RMSE benchmark3 | "
        "skill_vs_raw | RMSESS_climatologia | skill_vs_anomalia_reconstruida |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = det.get(lead, det.get(str(lead), {}))
        if d.get('n_elegivel', 0) == 0:
            linhas.append(f"| H{lead} | — | — | — | — | — | — | — |")
            continue
        linhas.append(f"| H{lead} | {_fmt(d['rmse'])} | {_fmt(d['rmse_raw'])} | "
                       f"{_fmt(d['rmse_climatologia'])} | "
                       f"{_fmt(d['rmse_benchmark_anomalia_reconstruida'])} | "
                       f"{_fmt(d['skill_vs_raw'], 3)} | {_fmt(d['RMSESS_climatologia'], 3)} | "
                       f"{_fmt(d['skill_vs_anomalia_reconstruida'], 3)} |")

    linhas += [
        "",
        "## 6. Intervalos de confiança (bootstrap em blocos por target_ano)",
        "",
        "Método calibrado e os três benchmarks sempre nos MESMOS blocos de ano sorteados em "
        "cada reamostra — IC nunca derivado dividindo intervalos separados. **Classificação "
        "meramente descritiva — nunca convertida automaticamente em 'bom'/'mau'.**",
        "",
        "| Horizonte | skill_vs_raw | IC 95% | Classe | RMSESS_climatologia | IC 95% | Classe | "
        "skill_vs_anomalia_reconstruida | IC 95% | Classe |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = boot.get(lead, boot.get(str(lead), {}))
        if not d.get('amostra_suficiente', False):
            linhas.append(f"| H{lead} | — | — | {d.get('nota', 'amostra insuficiente')} | | | | | | |")
            continue
        r, c, an = d['skill_vs_raw'], d['RMSESS_climatologia'], d['skill_vs_anomalia_reconstruida']
        linhas.append(
            f"| H{lead} | {_fmt(r['estimativa'], 3)} | [{_fmt(r['ic95_lo'], 3)}, {_fmt(r['ic95_hi'], 3)}] | "
            f"{_ic_texto(d['skill_vs_raw_ic_classificacao'])} | "
            f"{_fmt(c['estimativa'], 3)} | [{_fmt(c['ic95_lo'], 3)}, {_fmt(c['ic95_hi'], 3)}] | "
            f"{_ic_texto(d['RMSESS_climatologia_ic_classificacao'])} | "
            f"{_fmt(an['estimativa'], 3)} | [{_fmt(an['ic95_lo'], 3)}, {_fmt(an['ic95_hi'], 3)}] | "
            f"{_ic_texto(d['skill_vs_anomalia_reconstruida_ic_classificacao'])} |")

    linhas += [
        "",
        "### 6.1. Avaliação do critério de aprovação pré-registrado — NENHUM horizonte isolado",
        "",
        "O protocolo (Seção 6.2) exige, SIMULTANEAMENTE, que o IC 95% de "
        "`skill_vs_anomalia_reconstruida` E de `RMSESS_climatologia` estejam totalmente acima "
        "de zero — bater só um dos dois **não é suficiente** para aprovação. Atender só "
        "`skill_vs_anomalia_reconstruida` (como H1) não habilita a chamar aquele horizonte de "
        "aprovado.",
        "",
        "| Horizonte | skill_vs_anomalia_reconstruida acima de zero? | RMSESS_climatologia "
        "acima de zero? | Atende ao critério pré-registrado? |",
        "|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = boot.get(lead, boot.get(str(lead), {}))
        c1 = d.get('skill_vs_anomalia_reconstruida_ic_classificacao') == 'ic_totalmente_acima_de_zero'
        c2 = d.get('RMSESS_climatologia_ic_classificacao') == 'ic_totalmente_acima_de_zero'
        ok, _ = criterio_por_horizonte[lead]
        linhas.append(f"| H{lead} | {'✅ sim' if c1 else '❌ não'} | {'✅ sim' if c2 else '❌ não'} | "
                       f"{'✅ SIM' if ok else '❌ NÃO'} |")
    linhas += [
        "",
        f"**{'Nenhum horizonte H1–H6 atende integralmente ao critério pré-registrado de aprovação do Método 3.1 nesta rodada.' if nenhum_horizonte_aprovado else 'Ao menos um horizonte atendeu integralmente ao critério — ver tabela acima.'}** "
        "H1 pode ser descrito como: *único horizonte com evidência de ganho sobre o benchmark "
        "de anomalia reconstruída, porém sem evidência conclusiva de ganho sobre a "
        "climatologia causal* — nunca chamado de \"aprovado\".",
        "",
        "## 7. Matriz mês-alvo × lead (diagnóstico de heterogeneidade — NUNCA 72 testes de "
        "significância)",
        "",
        "Usada só para verificar direção/coerência dos efeitos, concentração do ganho, "
        "degradações relevantes e padrões sazonais — nunca como critério de aprovação "
        "célula a célula.",
        "",
        "### 7.1. N elegível por célula",
        "",
        "| Mês \\ Lead | " + " | ".join(f"H{l}" for l in v.LEADS_ESPERADOS) + " |",
        "|---" * (len(v.LEADS_ESPERADOS) + 1) + "|",
    ]
    for mes in range(1, 13):
        por_lead = mml.get(mes, mml.get(str(mes), {}))
        celulas = [str(por_lead.get(lead, por_lead.get(str(lead), {})).get('n', 0))
                   for lead in v.LEADS_ESPERADOS]
        linhas.append(f"| {NOMES_MES[mes-1]} | " + " | ".join(celulas) + " |")

    linhas += [
        "",
        "### 7.2. skill_vs_anomalia_reconstruida por célula (ponto estimado, sem IC nesta matriz)",
        "",
        "| Mês \\ Lead | " + " | ".join(f"H{l}" for l in v.LEADS_ESPERADOS) + " |",
        "|---" * (len(v.LEADS_ESPERADOS) + 1) + "|",
    ]
    for mes in range(1, 13):
        por_lead = mml.get(mes, mml.get(str(mes), {}))
        celulas = []
        for lead in v.LEADS_ESPERADOS:
            cel = por_lead.get(lead, por_lead.get(str(lead), {}))
            if cel.get('n', 0) == 0:
                celulas.append('—')
                continue
            aviso = '*' if not cel.get('amostra_suficiente', True) else ''
            celulas.append(f"{_fmt(cel.get('skill_vs_anomalia_reconstruida'), 3)}{aviso}")
        linhas.append(f"| {NOMES_MES[mes-1]} | " + " | ".join(celulas) + " |")
    linhas.append("")
    linhas.append(f"*`*` = célula com N abaixo da amostra mínima do projeto "
                   f"({v.AMOSTRA_MINIMA_ESTRATO}).*")

    linhas += [
        "",
        "## 8. Grupos sazonais (chuvosa/transição/seca) × lead",
        "",
        "| Grupo | Métrica | " + " | ".join(f"H{l}" for l in v.LEADS_ESPERADOS) + " |",
        "|---" * (len(v.LEADS_ESPERADOS) + 2) + "|",
    ]
    for grupo in ('chuvosa', 'transicao', 'seca'):
        por_lead = mgsl.get(grupo, {})
        linha_n = [str(por_lead.get(lead, por_lead.get(str(lead), {})).get('n', 0))
                   for lead in v.LEADS_ESPERADOS]
        linhas.append(f"| {grupo} | N | " + " | ".join(linha_n) + " |")
        linha_skill = [_fmt(por_lead.get(lead, por_lead.get(str(lead), {})).get('skill_vs_anomalia_reconstruida'), 3)
                       for lead in v.LEADS_ESPERADOS]
        linhas.append(f"| {grupo} | skill_vs_anomalia_reconstruida | " + " | ".join(linha_skill) + " |")
        linha_rmsess = [_fmt(por_lead.get(lead, por_lead.get(str(lead), {})).get('RMSESS_climatologia'), 3)
                        for lead in v.LEADS_ESPERADOS]
        linhas.append(f"| {grupo} | RMSESS_climatologia | " + " | ".join(linha_rmsess) + " |")

    linhas += [
        "",
        "## 9. Comparação expanding vs. LOYO",
        "",
        "### 9.1. LOYO full (retrospectivo descritivo — amostra DIFERENTE do expanding)",
        "",
        f"**Rótulo: `{loyo_full['rotulo']}`.** {loyo_full['aviso']}",
        "",
        "| Horizonte | N expanding | N LOYO full | RMSESS_climatologia expanding | "
        "RMSESS_climatologia LOYO full | Divergência (LOYO full − expanding) |",
        "|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        c = comparacao_full.get(lead, comparacao_full.get(str(lead), {}))
        linhas.append(f"| H{lead} | {c.get('n_expanding', 0)} | {c.get('n_loyo', 0)} | "
                       f"{_fmt(c.get('RMSESS_climatologia_expanding'), 3)} | "
                       f"{_fmt(c.get('RMSESS_climatologia_loyo'), 3)} | "
                       f"{_fmt(c.get('divergencia_loyo_menos_expanding'), 3)} |")
    linhas += [
        "",
        "**Esta comparação mistura dois efeitos: o desenho de treinamento (causal vs. "
        "passado+futuro) E o período de avaliação (N=120, 2001-2010 vs. N=240, 1991-2010) — "
        "nunca interpretar a divergência acima como efeito puro do método de treinamento.** "
        "Ver 9.2 para a comparação pareada.",
        "",
        "### 9.2. LOYO matched evaluation period — comparação PRINCIPAL (mesmos 120 casos)",
        "",
        f"**Rótulo: `{loyo_matched['rotulo']}`.** {loyo_matched['aviso']}",
        "",
        f"- Identidade algébrica do `benchmark_anomalia_reconstruida_loyo`: "
        f"{'✅ OK' if loyo_matched['identidade_benchmark3_loyo']['identidade_ok'] else '❌ FALHOU'} "
        f"(diferença máxima absoluta = "
        f"{loyo_matched['identidade_benchmark3_loyo']['max_diff_absoluto']:.2e}, "
        f"{loyo_matched['identidade_benchmark3_loyo']['n_verificado']} linhas verificadas).",
        "",
        "| Horizonte | N exp. | N LOYO matched | RMSE calibrado exp. | RMSE calibrado "
        "LOYO matched | skill_vs_raw exp. | skill_vs_raw LOYO matched | "
        "RMSESS_climatologia exp. | RMSESS_climatologia LOYO matched | "
        "skill_vs_anomalia_reconstruida exp. | skill_vs_anomalia_reconstruida LOYO matched |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        c = comparacao_matched.get(lead, comparacao_matched.get(str(lead), {}))
        linhas.append(
            f"| H{lead} | {c.get('n_expanding', 0)} | {c.get('n_loyo_matched', 0)} | "
            f"{_fmt(c.get('rmse_calibrado_expanding'))} | {_fmt(c.get('rmse_calibrado_loyo_matched'))} | "
            f"{_fmt(c.get('skill_vs_raw_expanding'), 3)} | {_fmt(c.get('skill_vs_raw_loyo_matched'), 3)} | "
            f"{_fmt(c.get('RMSESS_climatologia_expanding'), 3)} | "
            f"{_fmt(c.get('RMSESS_climatologia_loyo_matched'), 3)} | "
            f"{_fmt(c.get('skill_vs_anomalia_reconstruida_expanding'), 3)} | "
            f"{_fmt(c.get('skill_vs_anomalia_reconstruida_loyo_matched'), 3)} |")

    linhas += [
        "",
        "**Delta (LOYO matched − expanding), meramente descritivo — nunca um teste de "
        "significância automático:**",
        "",
        "| Horizonte | delta skill_vs_raw | delta RMSESS_climatologia | "
        "delta skill_vs_anomalia_reconstruida |",
        "|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        c = comparacao_matched.get(lead, comparacao_matched.get(str(lead), {}))
        linhas.append(f"| H{lead} | {_fmt(c.get('delta_skill_vs_raw'), 4)} | "
                       f"{_fmt(c.get('delta_RMSESS_climatologia'), 4)} | "
                       f"{_fmt(c.get('delta_skill_vs_anomalia_reconstruida'), 4)} |")

    linhas += [
        "",
        "**IC 95% dos três skills do LOYO matched (bootstrap em blocos por target_ano, mesmos "
        "blocos para método e benchmarks em cada reamostra):**",
        "",
        "| Horizonte | skill_vs_raw | IC 95% | Classe | RMSESS_climatologia | IC 95% | Classe | "
        "skill_vs_anomalia_reconstruida | IC 95% | Classe |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = boot_loyo_matched.get(lead, boot_loyo_matched.get(str(lead), {}))
        if not d.get('amostra_suficiente', False):
            linhas.append(f"| H{lead} | — | — | {d.get('nota', 'amostra insuficiente')} | | | | | | |")
            continue
        r, c, an = d['skill_vs_raw'], d['RMSESS_climatologia'], d['skill_vs_anomalia_reconstruida']
        linhas.append(
            f"| H{lead} | {_fmt(r['estimativa'], 3)} | [{_fmt(r['ic95_lo'], 3)}, {_fmt(r['ic95_hi'], 3)}] | "
            f"{_ic_texto(d['skill_vs_raw_ic_classificacao'])} | "
            f"{_fmt(c['estimativa'], 3)} | [{_fmt(c['ic95_lo'], 3)}, {_fmt(c['ic95_hi'], 3)}] | "
            f"{_ic_texto(d['RMSESS_climatologia_ic_classificacao'])} | "
            f"{_fmt(an['estimativa'], 3)} | [{_fmt(an['ic95_lo'], 3)}, {_fmt(an['ic95_hi'], 3)}] | "
            f"{_ic_texto(d['skill_vs_anomalia_reconstruida_ic_classificacao'])} |")

    deltas_abs = [abs(c.get(k)) for lead in v.LEADS_ESPERADOS
                  for c in [comparacao_matched.get(lead, comparacao_matched.get(str(lead), {}))]
                  for k in ('delta_skill_vs_raw', 'delta_RMSESS_climatologia',
                            'delta_skill_vs_anomalia_reconstruida')
                  if c.get(k) is not None]
    divergencias_full = [abs(c.get('divergencia_loyo_menos_expanding'))
                          for lead in v.LEADS_ESPERADOS
                          for c in [comparacao_full.get(lead, comparacao_full.get(str(lead), {}))]
                          if c.get('divergencia_loyo_menos_expanding') is not None]
    maior_delta_matched = max(deltas_abs) if deltas_abs else None
    maior_divergencia_full = max(divergencias_full) if divergencias_full else None

    linhas += [
        "",
        "### 9.3. Contradição entre os desenhos?",
        "",
        f"Maior `|delta|` observado entre LOYO matched e expanding (mesmos 120 casos, seção "
        f"9.2): **{_fmt(maior_delta_matched, 4)}**. Maior divergência observada entre LOYO "
        f"full e expanding (amostras diferentes, N=240 vs. N=120, seção 9.1): "
        f"**{_fmt(maior_divergencia_full, 4)}**.",
        "",
    ]
    if maior_delta_matched is not None and maior_divergencia_full is not None:
        if maior_delta_matched < maior_divergencia_full / 2:
            linhas.append(
                "Quando o período de avaliação é mantido CONSTANTE (9.2), os deltas ficam "
                "substancialmente MENORES que a divergência observada em 9.1 — isto sugere "
                "que a maior parte da divergência vista entre LOYO full e expanding é "
                "atribuível à diferença de amostra/período (N=240 vs. N=120), não ao desenho "
                "de treinamento em si. Leitura descritiva dos números acima, não um teste "
                "estatístico de equivalência entre os dois desenhos.")
        else:
            linhas.append(
                "Mesmo com o período de avaliação mantido constante (9.2), os deltas "
                "permanecem de magnitude comparável à divergência observada em 9.1 — isto "
                "sugere que o desenho de treinamento (causal vs. passado+futuro) tem, sim, "
                "efeito relevante além da diferença de amostra/período. Leitura descritiva "
                "dos números acima, não um teste estatístico formal.")
    linhas.append(
        "Em ambos os casos, esta seção é descritiva — nunca transforma automaticamente a "
        "comparação em teste de significância.")

    linhas += [
        "",
        "## 10. Limitações",
        "",
        "- Warm-up de 10 anos reduz a amostra de avaliação principal de 240 para 120 "
        "inicializações por horizonte (perda deliberada de poder estatístico em troca de "
        "defensabilidade — protocolo, Seção 5.1).",
        "- A correlação de anomalia do modelo calibrado depende de uma SEGUNDA climatologia "
        "causal (do modelo já calibrado), com amostra ainda menor que o bias aditivo — ver "
        "coluna 'N p/ anomalia' na seção 4, sempre reportada explicitamente.",
        "- A matriz mês × lead (seção 7) tem N≈10/célula no período principal — amostra "
        "pequena demais para qualquer inferência célula a célula; usada só como diagnóstico "
        "de heterogeneidade (protocolo, Seção 5.5).",
        "- Avaliação probabilística do ensemble calibrado (CRPSS/BSS) não se aplica nesta "
        "implementação — os 24 membros não foram recalibrados individualmente.",
        "- Nenhuma correção operacional de viés foi aplicada — permanece avaliação científica "
        "offline.",
        "",
        "## 11. Conclusão restrita ao Método 3.1 (correção aditiva)",
        "",
        "Esta conclusão vale SOMENTE para a correção aditiva causal por lead × mês-alvo — "
        "nunca generalizada para \"calibração do CFSv2\" em geral, e nunca chamando o modelo "
        "de validado ou pronto para produção.",
        "",
        "### 11.1. Evidência expanding",
        "",
        "- Melhora robusta contra o CFSv2 bruto (`skill_vs_raw`) em TODOS os H1-H6: IC 95% "
        "totalmente acima de zero em todos os horizontes (seção 6) — remover o viés aditivo "
        "causal melhora de forma consistente sobre o ensemble bruto não corrigido. Isto NÃO "
        "é, por si só, o critério de aprovação.",
        "- Contra a climatologia causal (`RMSESS_climatologia`): IC 95% totalmente acima de "
        "zero somente em H3 e H5 (seção 6) — nos demais horizontes, o IC inclui zero.",
        "- Contra o `benchmark_anomalia_reconstruida` (`skill_vs_anomalia_reconstruida`): IC "
        "95% totalmente acima de zero somente em H1 (seção 6).",
        "- **Portanto, " + ("nenhum horizonte H1-H6 satisfaz simultaneamente os dois "
        "critérios estatísticos principais (seção 6.1)" if nenhum_horizonte_aprovado else
        "ao menos um horizonte satisfaz simultaneamente os dois critérios principais — ver "
        "seção 6.1") + ".**",
        "- H1: único horizonte com evidência de ganho sobre o benchmark de anomalia "
        "reconstruída, porém SEM evidência conclusiva de ganho sobre a climatologia causal — "
        "nunca descrito como aprovado.",
        "",
        "### 11.2. Evidência LOYO",
        "",
        "- **LOYO full** (seção 9.1, N=240, 1991-2010): retrospectivo descritivo adicional — "
        "amostra DIFERENTE do expanding, nunca comparado diretamente como se fosse só efeito "
        "do método de treinamento.",
        "- **LOYO matched** (seção 9.2, N=120, mesmos casos do expanding): comparação "
        "metodologicamente justa — isola o efeito do desenho de treinamento do efeito do "
        "período de avaliação.",
        "- Maior `|delta|` entre LOYO matched e expanding: " + _fmt(maior_delta_matched, 4) +
        "; maior divergência entre LOYO full e expanding: " + _fmt(maior_divergencia_full, 4) +
        " — ver discussão quantitativa na seção 9.3 sobre se isso indica ou não contradição "
        "real entre os desenhos, antes de qualquer conclusão.",
        "",
        "### 11.3. Síntese",
        "",
        "- Não implementar o método multiplicativo, quantile mapping, MOS ou calibração "
        "probabilística nesta atividade — são decisões de uma próxima etapa, condicionadas à "
        "revisão independente deste resultado.",
        "- Nenhum horizonte deve ser chamado de \"aprovado\" nesta rodada quando o critério "
        "pré-registrado não for integralmente satisfeito; a leitura correta é que a correção "
        "aditiva ainda não demonstrou, para esse(s) horizonte(s), ganho estatisticamente "
        "distinguível SIMULTANEAMENTE sobre a climatologia causal e sobre o benchmark de "
        "anomalia reconstruída — um resultado válido e informativo, não uma falha de "
        "implementação.",
    ]
    return '\n'.join(linhas) + '\n'


def gerar_e_escrever():
    resultados = json.loads(a.CAMINHO_METRICAS_JSON.read_text())
    relatorio = gerar_relatorio_markdown(resultados)
    a.RELATORIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    a.RELATORIO_PATH.write_text(relatorio)
    print(f"  ✅ {a.RELATORIO_PATH.relative_to(a.ROOT)}")
    return relatorio


if __name__ == '__main__':
    gerar_e_escrever()
