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
    loyo = resultados['loyo_retrospective']
    det = exp['deterministico_por_horizonte']
    boot = exp['intervalos_confianca_skills_por_horizonte']
    mml = exp['matriz_mes_lead']
    mgsl = exp['matriz_grupo_sazonal_lead']
    det_loyo = loyo['deterministico_por_horizonte']
    comparacao = resultados['comparacao_expanding_vs_loyo']

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
        f"**Rótulo LOYO: `{loyo['rotulo']}`.** {loyo['aviso']}",
        "",
        "| Horizonte | N expanding | N LOYO | RMSESS_climatologia expanding | "
        "RMSESS_climatologia LOYO | Divergência (LOYO − expanding) |",
        "|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        c = comparacao.get(lead, comparacao.get(str(lead), {}))
        linhas.append(f"| H{lead} | {c.get('n_expanding', 0)} | {c.get('n_loyo', 0)} | "
                       f"{_fmt(c.get('RMSESS_climatologia_expanding'), 3)} | "
                       f"{_fmt(c.get('RMSESS_climatologia_loyo'), 3)} | "
                       f"{_fmt(c.get('divergencia_loyo_menos_expanding'), 3)} |")
    linhas += [
        "",
        "LOYO usa anos passados E futuros (amostra maior, mais estável) — **nunca uma "
        "simulação operacional**. Divergências de sinal ou magnitude entre expanding e LOYO "
        "são registradas aqui como achado, nunca escondidas atrás do resultado mais favorável.",
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
        "- `skill_vs_raw` (vs. CFSv2 bruto): ver seção 6 — se o IC 95% estiver totalmente "
        "acima de zero em todos os horizontes, isso mostra que remover o viés aditivo causal "
        "melhora sobre o ensemble bruto não corrigido, mas este NÃO é o critério principal "
        "de aprovação.",
        "- `RMSESS_climatologia` (vs. climatologia causal): ver seção 6.",
        "- **`skill_vs_anomalia_reconstruida` (vs. benchmark_anomalia_reconstruida) é o ponto "
        "PRINCIPAL pré-registrado (protocolo, Seção 6.2) — a aprovação do método depende de "
        "seu IC 95% estar totalmente acima de zero, consistentemente entre expanding e LOYO, "
        "e sem degradação relevante escondida na matriz mês×lead. Ver seção 6 para a "
        "classificação real, por horizonte.**",
        "- Qualquer horizonte em que esse IC inclua ou fique abaixo de zero significa que a "
        "correção aditiva NÃO demonstrou ganho estatisticamente distinguível sobre o "
        "benchmark mais exigente naquele horizonte — um resultado válido e esperado, não uma "
        "falha de implementação.",
        "- Não implementar o método multiplicativo, quantile mapping, MOS ou calibração "
        "probabilística nesta atividade — são decisões de uma próxima etapa, condicionadas à "
        "revisão independente deste resultado.",
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
