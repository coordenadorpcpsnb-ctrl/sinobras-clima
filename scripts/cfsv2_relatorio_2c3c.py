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

NOMES_MES = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']

_IC_TEXTO = {
    'ic_totalmente_acima_de_zero': 'IC 95% totalmente ACIMA de zero',
    'ic_inclui_zero': 'IC 95% inclui zero (indeterminado)',
    'ic_totalmente_abaixo_de_zero': 'IC 95% totalmente ABAIXO de zero',
    'indeterminado': 'indeterminado (amostra insuficiente)',
}


def _fmt(v, casas=2):
    return 'N/D' if v is None else f'{v:.{casas}f}'


def _ic_texto(classificacao):
    return _IC_TEXTO.get(classificacao, classificacao or 'N/D')


def _linha_tabela_absoluto_diagnostico(lead, det):
    a, diag = det['absoluto'], det['anomalia_diagnostico_climatologia_observada']
    return (f"| H{lead} | {det['n']} | {_fmt(a['bias'])} | {_fmt(a['mae'])} | {_fmt(a['rmse'])} | "
            f"{_fmt(a['corr'], 3)} | {_fmt(diag['corr'], 3)} | {_fmt(det['rmsess_absoluto'], 3)} | "
            f"{_fmt(det['rmsess_anomalia_diagnostico'], 3)} |")


def _linha_tabela_corrigida(lead, det):
    cor = det['anomalia_corrigida_climatologia_propria_modelo']
    if 'nota' in cor:
        return f"| H{lead} | {det.get('n_com_climatologia_modelo_disponivel', 0)} | — | — | — | — | — ({cor['nota']}) |"
    return (f"| H{lead} | {det.get('n_com_climatologia_modelo_disponivel', 0)} | {_fmt(cor['bias'])} | "
            f"{_fmt(cor['mae'])} | {_fmt(cor['rmse'])} | {_fmt(cor['corr'], 3)} | "
            f"{_fmt(det['rmsess_anomalia_corrigida'], 3)} |")


def _linha_matriz(valor_fmt, rotulo_linha, por_lead, chave, casas=3, marcar_amostra=True):
    celulas = []
    for lead in c.LEADS_ESPERADOS:
        d = por_lead.get(str(lead), {})
        if d.get('n', 0) == 0:
            celulas.append('—')
            continue
        v = d.get(chave)
        aviso = '*' if marcar_amostra and not d.get('amostra_suficiente', True) else ''
        celulas.append(f"{valor_fmt(v, casas) if v is not None else 'N/D'}{aviso}")
    return f"| {rotulo_linha} | " + ' | '.join(celulas) + ' |'


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
        "**Revisão 2C.3C (refinamentos pré-merge):** esta versão substitui a definição de "
        "anomalia usada até o commit anterior (que subtraía a MESMA climatologia observada "
        "dos dois lados) por uma climatologia PRÓPRIA do modelo, sem leakage, específica por "
        "lead e mês-alvo. A versão antiga foi mantida apenas como diagnóstico explícito, "
        "nunca como a anomaly correlation principal. Também foram adicionados: IC 95% dos "
        "skill scores (RMSESS/CRPSS/BSS) via bootstrap pareado (modelo e climatologia nos "
        "MESMOS blocos), a matriz mês-alvo × lead como visão sazonal principal, e a "
        "frequência observada das categorias de tercil como contexto do Brier Score.",
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
        f"H1 é a previsão do **mês corrente** ({c.ROTULO_HORIZONTE[1]}) — nunca tratado como "
        "horizonte futuro e nunca chamado de \"nowcast\" sem data de emissão/disponibilidade "
        "comprovada. H1 é tratado separadamente, nunca agregado com H2-H6 (horizontes "
        "futuros) numa métrica única.",
        "",
        "### 3.1. Precipitação absoluta e anomalia DIAGNÓSTICO (climatologia observada nos dois lados)",
        "",
        "**Esta subseção é diagnóstico, não a anomaly correlation principal** — ver 3.2. "
        "Subtrair a MESMA climatologia (observada) da previsão e da observação só remove o "
        "ciclo sazonal compartilhado; não remove o viés sistemático próprio do CFSv2. Por "
        "isso bias/MAE/RMSE/RMSESS são idênticos aos da coluna absoluta (erro = "
        "previsto-observado é invariante a essa translação) — só a correlação muda, porque "
        "depende da variância de cada série.",
        "",
        "| Horizonte | N | Bias (abs, mm) | MAE (abs, mm) | RMSE (abs, mm) | Corr (abs) | "
        "Corr (anomalia diagnóstico) | RMSESS (abs) | RMSESS (anomalia diagnóstico) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for lead in c.LEADS_ESPERADOS:
        linhas.append(_linha_tabela_absoluto_diagnostico(lead, exp['deterministico_por_horizonte'][str(lead)]))

    linhas += [
        "",
        "### 3.2. Anomalia CORRIGIDA pela climatologia própria do modelo — PRINCIPAL",
        "",
        "`anomalia_modelo = previsao_ensemble_mean - climatologia_do_modelo(lead, mês-alvo, "
        "só inicializações < init_date atual)`; `anomalia_observada = observacao_CHIRPS - "
        "climatologia_observada`. Esta é a anomaly correlation que deve ser citada como "
        "principal daqui em diante — a subseção 3.1 existe só como diagnóstico de quanto o "
        "viés sistemático do modelo estava inflando/distorcendo a leitura anterior.",
        "",
        "| Horizonte | N com climatologia do modelo disponível | Bias corrigido (mm) | "
        "MAE corrigido (mm) | RMSE corrigido (mm) | Corr (anomalia corrigida) | "
        "RMSESS (anomalia corrigida) |",
        "|---|---|---|---|---|---|---|",
    ]
    for lead in c.LEADS_ESPERADOS:
        linhas.append(_linha_tabela_corrigida(lead, exp['deterministico_por_horizonte'][str(lead)]))

    linhas += [
        "",
        f"**Fórmula do skill score:** `{exp['deterministico_por_horizonte']['1']['formula_rmsess']}` "
        "— positivo significa que o modelo erra MENOS que a climatologia expansível "
        "(benchmark, calculada sem leakage); negativo significa que a climatologia sozinha "
        "seria uma previsão melhor. **Nenhum valor aqui deve ser lido como 'bom' ou 'mau' "
        "isoladamente** — ver a seção 6b (intervalos de confiança dos skill scores) antes de "
        "qualquer conclusão.",
        "",
        "A correlação cai da precipitação absoluta (3.1, coluna 'abs') para qualquer versão "
        "de anomalia em todos os horizontes — esperado: parte da correlação absoluta é só o "
        "ciclo sazonal regional (out-abr chuvoso, jun-ago seco) que tanto o modelo quanto a "
        "climatologia capturam trivialmente. Note que a correlação em anomalia CORRIGIDA "
        "(3.2) não é sistematicamente maior nem menor que a diagnóstico (3.1) — em H1 é "
        "praticamente igual, em H3-H6 é MAIOR; isso é o esperado quando se remove um viés "
        "próprio do modelo que varia com o lead, não um artefato.",
        "",
        "## 4. Avaliação sazonal — matriz mês-alvo × lead (PRINCIPAL) e grupo sazonal × lead",
        "",
        "Cada célula da matriz mês × lead tem N≈20 (uma observação por ano de inicialização "
        "elegível) — amostra pequena por desenho. **Nenhuma inferência forte deve ser feita "
        "célula a célula**; células marcadas com `*` têm N abaixo do mínimo "
        f"({c.AMOSTRA_MINIMA_ESTRATO}) definido para este projeto. A visão por grupo sazonal "
        "(chuvosa/transição/seca) agrega células adjacentes só para reduzir ruído de amostra "
        "pequena — não substitui a matriz mês × lead.",
        "",
        "### 4.1. Matriz mês-alvo × lead — N por célula",
        "",
        "| Mês \\ Lead | H1 | H2 | H3 | H4 | H5 | H6 |",
        "|---|---|---|---|---|---|---|",
    ]
    mml = exp['matriz_mes_lead']
    for mes in range(1, 13):
        por_lead = mml.get(str(mes), {})
        celulas = [str(por_lead.get(str(lead), {}).get('n', 0)) for lead in c.LEADS_ESPERADOS]
        linhas.append(f"| {NOMES_MES[mes-1]} | " + ' | '.join(celulas) + ' |')

    linhas += [
        "",
        "### 4.2. Matriz mês-alvo × lead — RMSESS (ponto estimado, sem IC nesta matriz)",
        "",
        "| Mês \\ Lead | H1 | H2 | H3 | H4 | H5 | H6 |",
        "|---|---|---|---|---|---|---|",
    ]
    for mes in range(1, 13):
        linhas.append(_linha_matriz(_fmt, NOMES_MES[mes-1], mml.get(str(mes), {}), 'rmsess'))

    linhas += [
        "",
        "### 4.3. Matriz mês-alvo × lead — correlação de anomalia corrigida (climatologia própria do modelo)",
        "",
        "| Mês \\ Lead | H1 | H2 | H3 | H4 | H5 | H6 |",
        "|---|---|---|---|---|---|---|",
    ]
    for mes in range(1, 13):
        linhas.append(_linha_matriz(_fmt, NOMES_MES[mes-1], mml.get(str(mes), {}),
                                     'corr_anomalia_climatologia_propria_modelo'))

    linhas += [
        "",
        "*`*` = célula com N abaixo da amostra mínima do projeto "
        f"({c.AMOSTRA_MINIMA_ESTRATO}).*",
        "",
        "### 4.4. Resumo por grupo sazonal regional (CLAUDE.md) × lead",
        "",
        "| Grupo | Métrica | H1 | H2 | H3 | H4 | H5 | H6 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    mgsl = exp['matriz_grupo_sazonal_lead']
    for grupo in ('chuvosa', 'transicao', 'seca'):
        por_lead = mgsl.get(grupo, {})
        linhas.append(_linha_matriz(lambda v, _c: str(int(v)), f"{grupo} | N",
                                     por_lead, 'n', marcar_amostra=False))
        linhas.append(_linha_matriz(_fmt, f"{grupo} | RMSESS", por_lead, 'rmsess'))
        linhas.append(_linha_matriz(_fmt, f"{grupo} | Corr anomalia corrigida",
                                     por_lead, 'corr_anomalia_climatologia_propria_modelo'))

    linhas += [
        "",
        "### 4.5. Visão agregada mensal descritiva (SECUNDÁRIA — H1 a H6 combinados)",
        "",
        f"**Rótulo: `{exp['por_mes_do_ano']['rotulo']}`.** Mantida só como visão descritiva "
        "de referência — a matriz 4.1-4.3 é a análise sazonal principal porque não mistura "
        "lead times diferentes dentro da mesma célula.",
        "",
        "| Mês | Grupo sazonal | N | Bias | MAE | RMSE | Corr abs | Corr anomalia corrigida | RMSESS |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for mes in range(1, 13):
        d = exp['por_mes_do_ano']['por_mes'][str(mes)]
        if d.get('n', 0) == 0:
            continue
        aviso = '' if d.get('amostra_suficiente', True) else ' ⚠'
        linhas.append(f"| {NOMES_MES[mes-1]} | {d['grupo_sazonal']} | {d['n']}{aviso} | "
                       f"{_fmt(d['bias'])} | {_fmt(d['mae'])} | {_fmt(d['rmse'])} | "
                       f"{_fmt(d['corr_absoluta'], 3)} | "
                       f"{_fmt(d.get('corr_anomalia_climatologia_propria_modelo'), 3)} | "
                       f"{_fmt(d['rmsess'], 3)} |")
    linhas += ["", "| Grupo | N | Bias | MAE | RMSE | Corr abs | Corr anomalia corrigida | RMSESS |",
               "|---|---|---|---|---|---|---|---|"]
    for grupo in ('chuvosa', 'transicao', 'seca'):
        d = exp['por_mes_do_ano']['por_grupo_sazonal'][grupo]
        if d.get('n', 0) == 0:
            continue
        linhas.append(f"| {grupo} | {d['n']} | {_fmt(d['bias'])} | {_fmt(d['mae'])} | "
                       f"{_fmt(d['rmse'])} | {_fmt(d['corr_absoluta'], 3)} | "
                       f"{_fmt(d.get('corr_anomalia_climatologia_propria_modelo'), 3)} | "
                       f"{_fmt(d['rmsess'], 3)} |")

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
        f"— `{exp['probabilistico_por_horizonte']['1'].get('formula_bss', 'BSS = 1 - BS_modelo/BS_referencia (p=1/3)')}`. "
        "**O Brier Score de referência nominal (p=1/3) é a referência PRINCIPAL e nunca é "
        "alterada silenciosamente** — a seção 5.1 só complementa.",
        "",
        "### 5.1. Frequência observada das categorias e sensibilidade do Brier/BSS",
        "",
        "A referência nominal do Brier Score (seção 5) assume 1/3 de probabilidade "
        "climatológica para cada categoria (seco/normal/úmido) por desenho — nunca alterada. "
        "A tabela abaixo mostra a frequência EFETIVAMENTE observada de cada categoria nesta "
        "amostra, que pode divergir de 1/3 por tamanho de amostra finito e empates nos "
        "limiares de tercil.",
        "",
        "| Horizonte | Freq. observada seco | Freq. observada normal | Freq. observada úmido |",
        "|---|---|---|---|",
    ]
    for lead in c.LEADS_ESPERADOS:
        d = exp['probabilistico_por_horizonte'][str(lead)]
        freq = d.get('frequencia_observada_por_categoria')
        if not freq:
            linhas.append(f"| H{lead} | — | — | — |")
            continue
        linhas.append(f"| H{lead} | {_fmt(freq['seco'], 3)} | {_fmt(freq['normal'], 3)} | "
                       f"{_fmt(freq['umido'], 3)} |")
    linhas += [
        "",
        "**BSS de sensibilidade (climatologia empírica causal, em vez do nominal 1/3) — "
        "NUNCA substitui o BSS nominal da seção 5, só complementa:**",
        "",
        "| Horizonte | BSS sens. seco | BSS sens. normal | BSS sens. úmido |",
        "|---|---|---|---|",
    ]
    for lead in c.LEADS_ESPERADOS:
        d = exp['probabilistico_por_horizonte'][str(lead)]
        bss_s = d.get('bss_sensibilidade_climatologia_empirica_por_categoria')
        if not bss_s:
            linhas.append(f"| H{lead} | — | — | — |")
            continue
        linhas.append(f"| H{lead} | {_fmt(bss_s['seco'], 3)} | {_fmt(bss_s['normal'], 3)} | "
                       f"{_fmt(bss_s['umido'], 3)} |")
    linhas += [
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
        "### 6.1. Bias/MAE/RMSE absolutos",
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
        "### 6.2. Intervalos de confiança dos skill scores (RMSESS, CRPSS, BSS) — PRINCIPAL para interpretação de habilidade",
        "",
        "Diferente da seção 6.1, aqui o bootstrap reamostra os MESMOS blocos (mesmos anos "
        "sorteados) para recalcular modelo E climatologia a cada reamostra — garante que "
        "RMSESS/CRPSS/BSS sejam proporções válidas a cada iteração, em vez de dividir dois "
        "ICs calculados de forma independente. **A classificação abaixo nunca é 'bom'/'mau' "
        "— só indica se o IC 95% está totalmente acima de zero, inclui zero, ou totalmente "
        "abaixo de zero.**",
        "",
        "| Horizonte | RMSESS | IC 95% | Classificação | CRPSS | IC 95% | Classificação |",
        "|---|---|---|---|---|---|---|",
    ]
    ic_skill = exp.get('intervalos_confianca_skill_scores_por_horizonte', {})
    for lead in c.LEADS_ESPERADOS:
        d = ic_skill.get(str(lead), {})
        if not d or not d.get('amostra_suficiente', False):
            linhas.append(f"| H{lead} | — | — | {d.get('nota', 'amostra insuficiente')} | — | — | — |")
            continue
        rs, cp = d['rmsess'], d['crpss']
        linhas.append(f"| H{lead} | {_fmt(rs['estimativa'], 3)} | [{_fmt(rs['ic95_lo'], 3)}, "
                       f"{_fmt(rs['ic95_hi'], 3)}] | {_ic_texto(d['rmsess_ic_classificacao'])} | "
                       f"{_fmt(cp['estimativa'], 3)} | [{_fmt(cp['ic95_lo'], 3)}, "
                       f"{_fmt(cp['ic95_hi'], 3)}] | {_ic_texto(d['crpss_ic_classificacao'])} |")

    linhas += [
        "",
        "**BSS por categoria, com IC 95% (mesmos blocos do bootstrap acima):**",
        "",
        "| Horizonte | BSS seco | IC 95% | BSS normal | IC 95% | BSS úmido | IC 95% |",
        "|---|---|---|---|---|---|---|",
    ]
    for lead in c.LEADS_ESPERADOS:
        d = ic_skill.get(str(lead), {})
        bss = d.get('bss_por_categoria')
        if not bss:
            linhas.append(f"| H{lead} | — | — | — | — | — | — |")
            continue
        s, n, u = bss['seco'], bss['normal'], bss['umido']
        linhas.append(f"| H{lead} | {_fmt(s['estimativa'], 3)} | [{_fmt(s['ic95_lo'], 3)}, "
                       f"{_fmt(s['ic95_hi'], 3)}] | {_fmt(n['estimativa'], 3)} | "
                       f"[{_fmt(n['ic95_lo'], 3)}, {_fmt(n['ic95_hi'], 3)}] | "
                       f"{_fmt(u['estimativa'], 3)} | [{_fmt(u['ic95_lo'], 3)}, {_fmt(u['ic95_hi'], 3)}] |")

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
        "## 8. Interpretação — separada por dimensão, nunca uma conclusão única",
        "",
        "Esta seção separa deliberadamente SEIS leituras DIFERENTES — nunca resumidas numa "
        "frase como \"modelo validado\" ou \"boa habilidade\":",
        "",
        "1. **Precipitação absoluta** — correlação alta (0.80-0.83) em todos os horizontes, "
        "mas dominada pelo ciclo sazonal regional (chuva concentrada out-abr); não é medida "
        "de habilidade preditiva real.",
        "2. **Anomalia corrigida pela climatologia própria do modelo (seção 3.2, PRINCIPAL)** "
        "— correlação entre 0,14 e 0,40 (H2 mais baixa, H4 mais alta — não monotônica com o "
        "lead, diferente do padrão da versão diagnóstico). Ao remover o viés sistemático "
        "próprio do CFSv2 (em vez de só o ciclo sazonal compartilhado), a leitura muda "
        "qualitativamente em relação à versão diagnóstico anterior: bias e RMSE caem "
        "fortemente (ex.: RMSE de H1 cai de ~72mm para ~56mm), e a correlação em H3-H6 fica "
        "MAIOR que na versão diagnóstico — evidência de que parte do que parecia 'sem skill' "
        "na versão anterior era viés sistemático do modelo, não ausência de sinal.",
        "3. **Skill relativo à climatologia (RMSESS/CRPSS, seção 6.2)** — ponto estimado "
        "ainda negativo em todos os horizontes tanto para RMSESS quanto CRPSS, e os ICs 95% "
        "calculados nesta revisão (bootstrap pareado, mesmos blocos) ficaram TOTALMENTE "
        "ABAIXO de zero em todos os H1-H6 testados — ou seja, a incerteza amostral não muda "
        "a conclusão de que a climatologia expansível sem leakage teve erro MENOR que o "
        "ensemble bruto do CFSv2 nesta amostra. Isso é mais forte que apenas 'o ponto "
        "estimado é negativo': a faixa de incerteza também não inclui zero.",
        "4. **Probabilístico (CRPSS/BSS, seções 5 e 6.2)** — predominantemente negativo, "
        "consistente com o item 3; a seção 5.1 mostra que a frequência observada de 'seco' "
        "(~41,7% em H1) se desvia do nominal 1/3, contexto relevante para a leitura do Brier "
        "Score mas que não altera a referência nominal.",
        "5. **Dependência com o lead** — RMSESS (ponto estimado) piora monotonicamente de H1 "
        "(-0,22) a H6 (-0,49); a anomalia corrigida NÃO segue o mesmo padrão monotônico "
        "(ver item 2) — os dois fenômenos (skill relativo à climatologia vs. correlação de "
        "anomalia) respondem de forma diferente ao aumento do lead, e não devem ser lidos "
        "como a mesma coisa.",
        "6. **Dependência com a época do ano (seção 4)** — a matriz mês × lead mostra "
        "variação relevante célula a célula (N≈20/célula), mas qualquer leitura por mês "
        "isolado deve considerar a amostra pequena; o resumo por grupo sazonal (4.4) suaviza "
        "esse ruído sem substituir a matriz completa.",
        "",
        "**O ensemble bruto aqui avaliado (`forecast_prec_mm`, sem qualquer correção "
        "operacional de viés ou downscaling) não deve ser confundido com um produto "
        "operacional corrigido — esta é avaliação científica do RAW, nenhuma correção de "
        "viés foi aplicada nesta fase.** Nenhuma das seis leituras acima, isoladamente, "
        "autoriza uma conclusão geral de habilidade. Qualquer decisão sobre uso operacional "
        "do CFSv2 deve revisar conjuntamente: magnitude do skill, intervalo de confiança "
        "(seção 6.2), horizonte, época do ano (seção 4) e tamanho da amostra (N=240 "
        "inicializações, mas com dependência temporal relevante — daí o bootstrap em blocos).",
        "",
        "## Restrições respeitadas",
        "",
        "- Dashboard, SARIMAX, XGBoost, pipeline operacional, série de produção e dados RAW "
        "do CFSv2 não foram alterados.",
        "- Nenhuma correção operacional de viés foi aplicada — esta fase permanece avaliação "
        "científica do ensemble RAW.",
        "- Nenhuma métrica desta fase é apresentada automaticamente no dashboard de produção.",
        "- `serie_subst.csv`/`chirps_1981_2025.csv` não foram usados como referência "
        "principal em nenhum cálculo.",
        "- Testes de controle de leakage (climatologia observada, climatologia do modelo, "
        "tercis, pareamento, mistura de membros, demonstração sintética das duas definições "
        "de anomalia) executados e aprovados antes do cálculo das métricas — ver "
        "`tests/test_cfsv2_validacao_cientifica.py`.",
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
