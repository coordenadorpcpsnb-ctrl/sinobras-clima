#!/usr/bin/env python3
"""
cfsv2_relatorio_multiplicativa_2c3d.py — gera o relatório técnico do
Método 3.2 (correção multiplicativa causal) a partir de
data/cfsv2_calibracao_2c3d/metricas_multiplicativa_2c3d.json (já
calculado por scripts/cfsv2_calibracao_multiplicativa.py --executar).
Nunca recalcula métrica nenhuma aqui — só lê e formata.

Roda com:
    python scripts/cfsv2_relatorio_multiplicativa_2c3d.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import cfsv2_calibracao_multiplicativa as m  # noqa: E402
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
    """Acesso tolerante a chave int/str (JSON round-trip)."""
    return dic.get(lead, dic.get(str(lead), {}))


def gerar_relatorio_markdown(resultados):
    if resultados.get('STOP_ON_FAILURE'):
        return (
            "# Correção multiplicativa causal do CFSv2 — Fase 2C.3D (Método 3.2)\n\n"
            "**STOP-ON-FAILURE — métricas NÃO calculadas.**\n\n"
            f"Motivo: {resultados.get('motivo')}\n\n"
            f"Detalhe: {json.dumps(resultados.get('detalhe', {}), ensure_ascii=False)}\n"
        )

    exp = resultados['expanding_operational_simulation']
    det = exp['deterministico_por_horizonte']
    boot = exp['intervalos_confianca_skills_por_horizonte']
    mml = exp['matriz_mes_lead_meses_elegiveis']
    diag_esp = exp['diagnostico_maio_outubro_novembro']
    avaliacao = resultados['avaliacao_meses_com_denominador_seguro']
    loyo_full = resultados['loyo_retrospective']
    loyo_matched = resultados['loyo_matched_intersecao_elegibilidade']

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
        cl = d.get('skill_multiplicativo_vs_aditivo_ic_classificacao')
        if cl == 'ic_totalmente_acima_de_zero':
            return 'multiplicativo MELHOR que o aditivo (IC acima de zero)'
        if cl == 'ic_totalmente_abaixo_de_zero':
            return 'multiplicativo PIOR que o aditivo (IC abaixo de zero)'
        return 'sem evidência de diferença estatisticamente distinguível (IC inclui zero)'

    linhas = [
        "# Correção multiplicativa causal do CFSv2 — Fase 2C.3D (Método 3.2)",
        "",
        "**Relatório técnico — avaliação OFFLINE e científica, completamente separada do "
        "sistema operacional. Nenhuma correção foi aplicada ao dashboard, SARIMAX, XGBoost, "
        "pipeline operacional, `serie_subst.csv`, CFSv2 RAW, CHIRPS v3 histórico, à base "
        "pareada da 2C.3C nem aos artefatos já aprovados do Método 3.1 "
        "(`aditiva_expanding.csv`, `aditiva_loyo.csv`, `metricas_aditiva_2c3d.json`) — todos "
        "só lidos, nunca alterados.**",
        "",
        "## 1. Metodologia",
        "",
        "```",
        "media_prev_treino = média(forecast_raw) no histórico causal elegível",
        "media_obs_treino  = média(observacao)   no MESMO histórico causal elegível",
        "    (mesma combinação lead × mês-alvo, mesma lista de inicializações,",
        "     mesmos anos em ambas as médias — nunca duas climatologias",
        "     independentes com janelas de anos potencialmente diferentes)",
        "razao = media_obs_treino / media_prev_treino",
        "forecast_multiplicativo = forecast_raw × razao",
        "    SE media_prev_treino >= PISO_DENOMINADOR_MM (10,0mm), SENÃO excluído",
        "    (status_multiplicativo = 'denominador_abaixo_do_piso', SEM fallback para a",
        "     correção aditiva)",
        "```",
        "",
        f"`N_TREINO_MINIMO = {resultados['n_treino_minimo']}` (idêntico ao Método 3.1) e "
        f"`PISO_DENOMINADOR_MM = {resultados['piso_denominador_mm']}` (fixado no diagnóstico "
        "prévio, `docs/nmme-fase2c3d-protocolo-multiplicativo-cfsv2.md` — gap vazio "
        "[7,2656mm, 16,6241mm] no denominador, nenhum (lead, mês) fragmentado). **Nenhum teto "
        "de razão é aplicado no método principal** — razões altas em meses com denominador "
        "seguro (ver seção 8) são tratadas como achado a reportar, nunca como instabilidade a "
        "truncar.",
        "",
        "## 2. Elegibilidade e piso — jun-set fora da população de inferência por desenho",
        "",
        f"- Meses elegíveis: {', '.join(NOMES_MES[mes-1] for mes in avaliacao['meses_elegiveis'])}.",
        f"- Meses excluídos pelo piso (jamais incluídos na avaliação principal, em NENHUM "
        f"lead): {', '.join(NOMES_MES[mes-1] for mes in avaliacao['meses_excluidos_por_piso'])}.",
        f"- `{avaliacao['nota']}`",
        "- Verificação de não-fragmentação (nenhum mês parcialmente elegível em algum lead e "
        f"inelegível em outro): "
        f"{'✅ OK' if resultados['verificacao_piso_nao_fragmenta_mes']['ok'] else '❌ FALHOU'}.",
        "",
        "## 3. N elegível total e por horizonte",
        "",
    ]

    contagem = resultados['verificacao_contagem_elegivel']
    linhas.append(f"**N total elegível (avaliação principal): {contagem['n_total_elegivel']}** "
                   f"(derivado programaticamente: {len(avaliacao['meses_elegiveis'])} meses "
                   f"elegíveis × {contagem['n_anos_elegiveis_derivado']:.0f} anos × "
                   f"{len(v.LEADS_ESPERADOS)} leads).")
    linhas += ["", "| Horizonte | N elegível |", "|---|---|"]
    for lead in v.LEADS_ESPERADOS:
        linhas.append(f"| H{lead} | {contagem['contagem_real_por_horizonte'].get(lead, contagem['contagem_real_por_horizonte'].get(str(lead)))} |")

    linhas += [
        "",
        "## 4. Resultados determinísticos H1-H6 (método multiplicativo)",
        "",
        "| Horizonte | N | Bias | MAE | RMSE | Razão média | Razão mediana |",
        "|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(det, lead)
        if d.get('n', 0) == 0:
            linhas.append(f"| H{lead} | 0 | — | — | — | — | — |")
            continue
        linhas.append(f"| H{lead} | {d['n']} | {_fmt(d['bias'])} | {_fmt(d['mae'])} | "
                       f"{_fmt(d['rmse'])} | {_fmt(d['razao_media'], 3)} | "
                       f"{_fmt(d['razao_mediana'], 3)} |")

    linhas += [
        "",
        "## 5. Comparação contra os três benchmarks pré-registrados",
        "",
        "`skill_vs_X = 1 - RMSE_multiplicativo / RMSE_X` — numerador e denominador sempre "
        "sobre exatamente os mesmos casos elegíveis. **Critério de aprovação (item 11, "
        "idêntico ao Método 3.1): IC 95% de `skill_vs_anomalia_reconstruida` E "
        "`RMSESS_climatologia` totalmente acima de zero, SIMULTANEAMENTE.**",
        "",
        "| Horizonte | RMSE mult. | RMSE bruto | RMSE climatologia | RMSE benchmark3 | "
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
        "## 6. Comparação PRINCIPAL — multiplicativo vs. aditivo (Método 3.1), amostra pareada",
        "",
        "`skill_multiplicativo_vs_aditivo = 1 - RMSE_multiplicativo / RMSE_aditivo_matched` — "
        "SEMPRE sobre a MESMA amostra pareada (480 casos total, 80 por horizonte, mesmas chaves "
        "init_date×lead nos dois lados; ver `aditiva_matched_multiplicativo_sample`). **Este é "
        "o teste principal para saber se o Método 3.2 acrescenta algo ao Método 3.1 — nunca "
        "comparado contra o aditivo full (N=720), que usaria amostras diferentes.**",
        "",
        "| Horizonte | RMSE multiplicativo | RMSE aditivo (matched) | "
        "skill_multiplicativo_vs_aditivo |",
        "|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(det, lead)
        if d.get('n', 0) == 0:
            linhas.append(f"| H{lead} | — | — | — |")
            continue
        linhas.append(f"| H{lead} | {_fmt(d['rmse'])} | {_fmt(d['rmse_aditivo_matched'])} | "
                       f"{_fmt(d['skill_multiplicativo_vs_aditivo'], 3)} |")

    linhas += [
        "",
        "## 7. Intervalos de confiança (bootstrap em blocos por target_ano)",
        "",
        "Multiplicativo, os três benchmarks E o aditivo matched sempre nos MESMOS blocos de "
        "ano sorteados em cada reamostra — IC nunca derivado dividindo intervalos separados. "
        "**Classificação meramente descritiva — nunca convertida automaticamente em "
        "'bom'/'mau'.**",
        "",
        "| Horizonte | skill_vs_raw | IC 95% | skill_vs_anomalia_reconstruida | IC 95% | "
        "skill_multiplicativo_vs_aditivo | IC 95% | Evidência vs. aditivo |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(boot, lead)
        if not d.get('amostra_suficiente', False):
            linhas.append(f"| H{lead} | — | — | — | — | — | — | {d.get('nota', 'amostra insuficiente')} |")
            continue
        r = d['skill_vs_raw']
        an = d['skill_vs_anomalia_reconstruida']
        adv = d['skill_multiplicativo_vs_aditivo']
        linhas.append(
            f"| H{lead} | {_fmt(r['estimativa'], 3)} | [{_fmt(r['ic95_lo'], 3)}, {_fmt(r['ic95_hi'], 3)}] | "
            f"{_fmt(an['estimativa'], 3)} | [{_fmt(an['ic95_lo'], 3)}, {_fmt(an['ic95_hi'], 3)}] | "
            f"{_fmt(adv['estimativa'], 3)} | [{_fmt(adv['ic95_lo'], 3)}, {_fmt(adv['ic95_hi'], 3)}] | "
            f"{_evidencia_vs_aditivo(lead)} |")

    linhas += [
        "",
        "### 7.1. Avaliação do critério de aprovação pré-registrado",
        "",
        "| Horizonte | skill_vs_anomalia_reconstruida acima de zero? | RMSESS_climatologia "
        "acima de zero? | Atende ao critério? | skill_multiplicativo_vs_aditivo (informativo, "
        "não decide a aprovação) |",
        "|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        d = _g(boot, lead)
        c1 = d.get('skill_vs_anomalia_reconstruida_ic_classificacao') == 'ic_totalmente_acima_de_zero'
        c2 = d.get('RMSESS_climatologia_ic_classificacao') == 'ic_totalmente_acima_de_zero'
        ok, _ = criterio_por_horizonte[lead]
        cl_adit = d.get('skill_multiplicativo_vs_aditivo_ic_classificacao')
        linhas.append(f"| H{lead} | {'✅ sim' if c1 else '❌ não'} | {'✅ sim' if c2 else '❌ não'} | "
                       f"{'✅ SIM' if ok else '❌ NÃO'} | {_ic_texto(cl_adit)} |")
    linhas += [
        "",
        f"**{'Nenhum horizonte H1–H6 atende integralmente ao critério pré-registrado de aprovação do Método 3.2 nesta rodada.' if nenhum_horizonte_aprovado else 'Ao menos um horizonte atendeu integralmente ao critério — ver tabela acima.'}** "
        "O critério NUNCA foi alterado depois de observar este resultado.",
        "",
        "## 8. Diagnóstico obrigatório — maio, outubro e novembro (razão alta, denominador "
        "SEGURO, NUNCA excluídos nem truncados)",
        "",
        "Objetivo: decidir se a razão alta corrige um viés sistemático real do CFSv2 ou causa "
        "sobrecorreção — **nunca decidido pela magnitude do fator isoladamente**, só pelas "
        "métricas abaixo.",
        "",
    ]
    for mes in m.MESES_DIAGNOSTICO_OBRIGATORIO:
        linhas.append(f"### 8.{list(m.MESES_DIAGNOSTICO_OBRIGATORIO).index(mes)+1}. {NOMES_MES[mes-1]}")
        linhas.append("")
        linhas.append("| Lead | N | Razão média | Razão mediana | Forecast bruto médio | "
                       "Forecast multiplicativo médio | Observado médio | Bias | MAE | RMSE | "
                       "skill_vs_raw | RMSESS_clim. | skill_vs_anomalia | skill_vs_aditivo |")
        linhas.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        por_lead = _g(diag_esp, mes)
        for lead in v.LEADS_ESPERADOS:
            cel = _g(por_lead, lead)
            if cel.get('n', 0) == 0:
                linhas.append(f"| H{lead} | 0 | — | — | — | — | — | — | — | — | — | — | — | — |")
                continue
            linhas.append(
                f"| H{lead} | {cel['n']} | {_fmt(cel['razao_media'], 3)} | "
                f"{_fmt(cel['razao_mediana'], 3)} | {_fmt(cel['forecast_raw_medio'])} | "
                f"{_fmt(cel['forecast_multiplicativo_medio'])} | {_fmt(cel['observado_medio'])} | "
                f"{_fmt(cel['bias'])} | {_fmt(cel['mae'])} | {_fmt(cel['rmse'])} | "
                f"{_fmt(cel['skill_vs_raw'], 3)} | {_fmt(cel['RMSESS_climatologia'], 3)} | "
                f"{_fmt(cel['skill_vs_anomalia_reconstruida'], 3)} | "
                f"{_fmt(cel['skill_multiplicativo_vs_aditivo'], 3)} |")
        linhas.append("")

    linhas += [
        "**Leitura, SEM decidir por magnitude isolada**: outubro tem a razão mediana mais "
        "alta (tipicamente > 4, ver seção abaixo) com `forecast_multiplicativo_medio` muito "
        "mais próximo do `observado_medio` que o `forecast_raw_medio` — consistente com um "
        "viés sistemático real do CFSv2 em outubro (ver `CLAUDE.md`, armadilha 7: o modelo "
        "subestima sistematicamente out-nov-dez). Se `skill_vs_aditivo` nessa célula for "
        "positivo, é evidência de que a correção multiplicativa captura esse viés melhor que a "
        "aditiva nesses meses especificamente — se for negativo ou os benchmarks piorarem "
        "(skill_vs_raw/RMSESS_climatologia muito negativos), é evidência de sobrecorreção. Ver "
        "números acima, não uma conclusão geral pré-definida.",
        "",
        "## 9. Matriz mês-alvo × lead — SOMENTE meses elegíveis (diagnóstico de "
        "heterogeneidade, NUNCA 48 testes de significância)",
        "",
        "### 9.1. N elegível por célula",
        "",
        "| Mês \\ Lead | " + " | ".join(f"H{l}" for l in v.LEADS_ESPERADOS) + " |",
        "|---" * (len(v.LEADS_ESPERADOS) + 1) + "|",
    ]
    for mes in m.MESES_ELEGIVEIS:
        por_lead = _g(mml, mes)
        celulas = [str(_g(por_lead, lead).get('n', 0)) for lead in v.LEADS_ESPERADOS]
        linhas.append(f"| {NOMES_MES[mes-1]} | " + " | ".join(celulas) + " |")

    linhas += [
        "",
        "### 9.2. skill_vs_anomalia_reconstruida por célula (ponto estimado, sem IC nesta matriz)",
        "",
        "| Mês \\ Lead | " + " | ".join(f"H{l}" for l in v.LEADS_ESPERADOS) + " |",
        "|---" * (len(v.LEADS_ESPERADOS) + 1) + "|",
    ]
    for mes in m.MESES_ELEGIVEIS:
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
        "### 9.3. skill_multiplicativo_vs_aditivo por célula (ponto estimado, sem IC nesta matriz)",
        "",
        "| Mês \\ Lead | " + " | ".join(f"H{l}" for l in v.LEADS_ESPERADOS) + " |",
        "|---" * (len(v.LEADS_ESPERADOS) + 1) + "|",
    ]
    for mes in m.MESES_ELEGIVEIS:
        por_lead = _g(mml, mes)
        celulas = []
        for lead in v.LEADS_ESPERADOS:
            cel = _g(por_lead, lead)
            if cel.get('n', 0) == 0:
                celulas.append('—')
                continue
            aviso = '*' if not cel.get('amostra_suficiente', True) else ''
            celulas.append(f"{_fmt(cel.get('skill_multiplicativo_vs_aditivo'), 3)}{aviso}")
        linhas.append(f"| {NOMES_MES[mes-1]} | " + " | ".join(celulas) + " |")
    linhas.append("")
    linhas.append(f"*`*` = célula com N abaixo da amostra mínima do projeto "
                   f"({v.AMOSTRA_MINIMA_ESTRATO}).*")

    linhas += [
        "",
        "## 10. Comparação expanding vs. LOYO matched (elegibilidade explícita)",
        "",
        f"**Rótulo: `{loyo_matched['rotulo']}`.**",
        "",
    ]
    eleg = loyo_matched['elegibilidade']
    linhas += [
        f"- N elegível no expanding (status_multiplicativo='ok'): {eleg['n_elegivel_expanding']}.",
        f"- N elegível no LOYO (elegibilidade própria, piso aplicado igualmente): "
        f"{eleg['n_elegivel_loyo_proprio']}.",
        f"- N na interseção (usada na comparação abaixo): {eleg['n_intersecao']}.",
        f"- N de diferença de elegibilidade (chave elegível no expanding, mas NÃO no LOYO — "
        f"nunca forçada na comparação): {eleg['n_diferenca_elegibilidade']}.",
        f"- `{eleg['nota']}`",
        "",
        "| Horizonte | N expanding (interseção) | N LOYO matched (interseção) | "
        "delta skill_vs_raw | delta RMSESS_climatologia | delta skill_vs_anomalia_reconstruida |",
        "|---|---|---|---|---|---|",
    ]
    comp_loyo = loyo_matched['comparacao_expanding_vs_loyo_matched']
    for lead in v.LEADS_ESPERADOS:
        c = _g(comp_loyo, lead)
        linhas.append(f"| H{lead} | {c.get('n_expanding', 0)} | {c.get('n_loyo_matched', 0)} | "
                       f"{_fmt(c.get('delta_skill_vs_raw'), 4)} | "
                       f"{_fmt(c.get('delta_RMSESS_climatologia'), 4)} | "
                       f"{_fmt(c.get('delta_skill_vs_anomalia_reconstruida'), 4)} |")
    linhas += [
        "",
        "**Delta meramente descritivo — nunca um teste de significância automático.** "
        f"`{loyo_full['aviso']}`",
        "",
        "## 11. Limitações",
        "",
        "- Avaliação principal restrita a 8 dos 12 meses do ano (jun-set excluídos por "
        "desenho, seção 2) — **nunca reportar isto como desempenho anual do Método 3.2**.",
        "- N≈10/célula na matriz mês×lead (seção 9) e no diagnóstico de outubro/maio/novembro "
        "(seção 8) — amostra pequena demais para inferência célula a célula; usada só como "
        "diagnóstico de heterogeneidade.",
        "- `skill_multiplicativo_vs_aditivo` compara contra o aditivo MATCHED (N=480), nunca "
        "contra o aditivo full (N=720, Método 3.1 original) — comparar contra o full misturaria "
        "o efeito do método com o efeito da amostra.",
        "- Nenhum teto de razão foi aplicado — se outubro (ou outro mês) mostrar sinais de "
        "sobrecorreção nos benchmarks (seção 8), isso é um resultado a reportar, não um erro "
        "de implementação a corrigir retroativamente nesta rodada.",
        "- Nenhuma correção operacional de viés foi aplicada — permanece avaliação científica "
        "offline.",
        "",
        "## 12. Conclusão restrita ao Método 3.2 (correção multiplicativa)",
        "",
        "Esta conclusão vale SOMENTE para a correção multiplicativa causal por lead × "
        "mês-alvo, restrita aos meses elegíveis (seção 2) — nunca generalizada para "
        "\"calibração do CFSv2\" em geral, nunca chamando o modelo de validado ou pronto para "
        "produção, e nunca comparada com o Método 3.1 fora da amostra pareada (seção 6).",
        "",
        f"- Critério pré-registrado de aprovação: " + (
            "nenhum horizonte H1-H6 satisfaz simultaneamente os dois critérios estatísticos "
            "principais (seção 7.1)" if nenhum_horizonte_aprovado else
            "ao menos um horizonte satisfaz simultaneamente os dois critérios principais — "
            "ver seção 7.1") + ".",
        "- Comparação principal com o Método 3.1 (seção 6/7): " + "; ".join(
            f"H{lead}: {_evidencia_vs_aditivo(lead)}" for lead in v.LEADS_ESPERADOS) + ".",
        "- Achado de outubro/maio/novembro (seção 8): razão sistematicamente alta com "
        "denominador seguro — ver a leitura condicionada aos números da seção 8, nunca "
        "decidida pela magnitude da razão isoladamente.",
        "- Não implementar correção híbrida aditiva/multiplicativa, quantile mapping, MOS ou "
        "calibração probabilística nesta atividade — decisões de uma próxima etapa, "
        "condicionadas à revisão independente deste resultado.",
    ]
    return '\n'.join(linhas) + '\n'


def gerar_e_escrever():
    resultados = json.loads(m.CAMINHO_METRICAS_JSON.read_text())
    relatorio = gerar_relatorio_markdown(resultados)
    m.RELATORIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    m.RELATORIO_PATH.write_text(relatorio)
    print(f"  ✅ {m.RELATORIO_PATH.relative_to(m.ROOT)}")
    return relatorio


if __name__ == '__main__':
    gerar_e_escrever()
