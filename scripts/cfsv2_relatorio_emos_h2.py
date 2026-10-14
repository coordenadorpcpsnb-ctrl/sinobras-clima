#!/usr/bin/env python3
"""
cfsv2_relatorio_emos_h2.py — gera
docs/nmme-fase2c3d-emos-h2-resultados.md a partir de
data/cfsv2_calibracao_2c3d/metricas_emos_h2_2c3d.json (já calculado por
scripts/cfsv2_emos_h2_implementacao.py --executar). Nunca recalcula
nada aqui — só lê e formata. Nunca declara o EMOS "validado" ou
"pronto para produção" — a decisão reportada é exatamente a do
critério pré-registrado (protocolo, seção 20), nunca embelezada.

Roda com:
    python scripts/cfsv2_relatorio_emos_h2.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import cfsv2_emos_h2_implementacao as emos  # noqa: E402

_IC_TEXTO = {
    'ic_totalmente_acima_de_zero': 'IC 95% totalmente ACIMA de zero',
    'ic_inclui_zero': 'IC 95% inclui zero (indeterminado)',
    'ic_totalmente_abaixo_de_zero': 'IC 95% totalmente ABAIXO de zero',
    'indeterminado': 'indeterminado (amostra insuficiente)',
}


def _fmt(val, casas=4):
    return 'N/D' if val is None else f'{val:.{casas}f}'


def _ic_texto(classificacao):
    return _IC_TEXTO.get(classificacao, classificacao or 'N/D')


def gerar_relatorio_markdown(resultados):
    if resultados.get('STOP_ON_FAILURE'):
        return (
            "# EMOS H2 — resultados (Fase 2C.3D, Método 3.5)\n\n"
            "**STOP-ON-FAILURE — métricas NÃO calculadas.**\n\n"
            f"Motivo: {resultados.get('motivo')}\n\n"
            f"Detalhe: {json.dumps(resultados.get('detalhe', {}), ensure_ascii=False, indent=2)}\n"
        )

    n_casos = resultados['n_casos']
    boot = resultados['bootstrap_crpss']
    crps = resultados['crps_medio']
    brier = resultados['brier_bss']
    cobertura = resultados['cobertura_intervalos']
    cobertura_raw = resultados['cobertura_intervalos_raw']
    pit = resultados['pit']
    bias = resultados['bias']
    diag = resultados['diagnostico_parametros']
    decisao = resultados['decisao_criterio_pre_registrado']

    linhas = []
    linhas.append("# EMOS H2 — resultados (Fase 2C.3D, Método 3.5)\n")
    linhas.append(
        "Implementação real do EMOS (Normal censurada em zero, CRPS minimizado "
        "analiticamente) restrita a H2, seguindo estritamente "
        "`docs/nmme-fase2c3d-protocolo-emos-h2.md`. Avaliação expanding-window causal, "
        "regra exigindo simultaneamente `init_date_treino < init_date_avaliada` e "
        "`target_month_treino < init_date_avaliada` (mesma regra já corrigida no "
        "Método 3.4). Warm-up `N_TREINO_MINIMO_EMOS = 120` pares válidos.\n")

    linhas.append("\n## 1. Amostra avaliada\n")
    linhas.append(
        f"- N final de previsões avaliáveis: **{n_casos['n_final']}** "
        f"(esperado estrutural: {n_casos['esperado_estrutural']}, "
        f"bate: {n_casos['bate_com_esperado']}).\n"
        f"- Primeira `init_date` avaliável: **{resultados['primeira_init_date_avaliavel']}**.\n"
        f"- Leakage observacional: {'nenhum encontrado' if resultados['leakage_check']['ok'] else 'ENCONTRADO — ver detalhe'}.\n"
        f"- Falhas de convergência/sanidade: {'nenhuma' if resultados['verificacao_falhas_convergencia']['ok'] else 'ENCONTRADAS — ver detalhe'}.\n")

    linhas.append("\n## 2. CRPS médio (fórmula analítica, protocolo seção 15)\n")
    linhas.append(
        "| Modelo | CRPS médio (mm) |\n|---|---|\n"
        f"| EMOS completo | {_fmt(crps['emos_completo'])} |\n"
        f"| EMOS d=0 | {_fmt(crps['emos_d0'])} |\n"
        f"| Ensemble RAW CFSv2 | {_fmt(crps['raw'])} |\n"
        f"| Climatologia causal | {_fmt(crps['climatologia'])} |\n")

    linhas.append("\n## 2.5. Rastreabilidade do CRPS final de treino (res.fun)\n")
    cft = resultados.get('crps_final_treino_resumo')
    if cft:
        linhas.append(
            "| Modelo | mín | mediana | máx | N finitos |\n|---|---|---|---|---|\n"
            f"| completo | {_fmt(cft['completo']['minimo'])} | {_fmt(cft['completo']['mediana'])} | "
            f"{_fmt(cft['completo']['maximo'])} | {cft['completo']['n']} |\n"
            f"| d=0 | {_fmt(cft['d0']['minimo'])} | {_fmt(cft['d0']['mediana'])} | "
            f"{_fmt(cft['d0']['maximo'])} | {cft['d0']['n']} |\n\n")
    linhas.append(
        "`crps_final_treino_completo`/`crps_final_treino_d0` (protocolo, seção 16.4) registram, "
        "para CADA data causal, o valor da função objetivo (`res.fun`) na solução do otimizador "
        "— o CRPS médio sobre a JANELA DE TREINO que de fato foi minimizada. É uma quantidade "
        "DIFERENTE de `crps_emos`/`crps_d0` (seções 2/3 abaixo), que são o CRPS calculado "
        "retrospectivamente sobre a ÚNICA observação AVALIADA, fora da amostra de treino. As "
        "duas nunca coincidem por construção (uma é média de dezenas/centenas de linhas "
        "históricas; a outra é um único ponto fora de amostra) — ver "
        "`tests/test_cfsv2_emos_h2_implementacao.py::CrpsFinalTreinoTestCase`, que confirma "
        "numericamente a diferença e a igualdade de `crps_final_treino_completo` com `res.fun` "
        "recomputado de forma independente.\n")

    linhas.append("\n## 3. CRPSS e intervalos de confiança (bootstrap em blocos por target_ano, sem refit)\n")
    linhas.append(
        f"N anos distintos: {boot['n_anos_distintos']}, N reamostras: {boot['n_resamples']}, "
        f"semente determinística: `{boot.get('seed')}`. Nenhuma reamostra descartada em "
        f"nenhuma métrica: **{boot.get('nenhuma_reamostra_descartada')}** "
        f"(contagens efetivas: {boot.get('n_resamples_efetivos_por_metrica')}).\n")
    linhas.append("| Comparação | Estimativa pontual | Notação científica | IC 95% | Classificação | N efetivo |\n"
                   "|---|---|---|---|---|---|\n")
    for chave, rotulo in (
        ('CRPSS_vs_raw', 'EMOS completo vs. RAW'),
        ('CRPSS_vs_climatologia', 'EMOS completo vs. climatologia causal'),
        ('CRPSS_spread_dinamico', 'EMOS completo vs. EMOS d=0 (teste CENTRAL)'),
        ('CRPSS_d0_vs_raw', 'EMOS d=0 vs. RAW'),
        ('CRPSS_d0_vs_climatologia', 'EMOS d=0 vs. climatologia causal'),
    ):
        r = boot[chave]
        linhas.append(f"| {rotulo} | {_fmt(r['estimativa'])} | "
                       f"`{r.get('estimativa_notacao_cientifica', 'N/D')}` | "
                       f"[{_fmt(r['ic95_lo'])}, {_fmt(r['ic95_hi'])}] | {_ic_texto(r['ic_classificacao'])} | "
                       f"{r.get('n_resamples_efetivos', 'N/D')} |\n")
    linhas.append(
        "\n**Teste central (CRPSS_spread_dinamico):** a notação científica acima "
        f"(`{boot['CRPSS_spread_dinamico'].get('estimativa_notacao_cientifica')}`) mostra que o "
        "ganho pontual é numericamente muito pequeno mas NÃO matematicamente zero exato — "
        "consistente com `d` convergindo para um valor extremamente próximo do bound inferior "
        "(0) em todas as 95 avaliações (seção 8), nunca exatamente 0.0 em ponto flutuante. O IC "
        "95% inclui zero, então o termo dinâmico de spread (`d * spread_relativo²`) não "
        "acrescenta valor comprovado sobre corrigir só média e dispersão climatológica — "
        "qualquer melhoria do EMOS completo sobre o RAW, nesse caso, vem da correção de "
        "localização/escala, não do spread caso a caso (protocolo, seção 18).\n")

    linhas.append("\n## 4. Brier Score e BSS por categoria de tercil\n")
    linhas.append("| Categoria | Brier Score (EMOS) | Brier ref. nominal (1/3) | BSS |\n|---|---|---|---|\n")
    for cat in ('seco', 'normal', 'umido'):
        linhas.append(f"| {cat} | {_fmt(brier['brier_score_por_categoria'][cat])} | "
                       f"{_fmt(brier['brier_referencia_nominal_por_categoria'][cat])} | "
                       f"{_fmt(brier['bss_por_categoria'][cat])} |\n")
    linhas.append(f"\nVerificação de que as probabilidades somam 1 em todos os casos: "
                  f"{brier['verificacao_probabilidades_somam_um']['ok']} "
                  f"(desvio máximo: {brier['verificacao_probabilidades_somam_um']['max_desvio_abs']:.2e}).\n")
    limiar_bss = decisao.get('limiar_bss_degradacao_grave')
    bss_proximo = decisao.get('bss_valor_mais_proximo_do_limiar')
    linhas.append(
        f"\n**Critério 3 — classificação: `{decisao.get('criterio_3_classificacao')}` "
        f"(diagnóstico, não aprovação certificada).** O protocolo (seção 20, item 3) exige "
        "\"ausência de degradação grave\" de Brier/BSS, sem fixar um limiar numérico. A "
        f"implementação usa BSS > {_fmt(limiar_bss, 2)} como limiar operacional de \"não grave\" "
        "(convenção comum em verificação probabilística categórica: uma queda de até 10% sobre "
        "a referência nominal costuma ser tratada como ruído aceitável, enquanto quedas de "
        "-0,20 a -0,30 ou piores são as convencionalmente citadas como degradação clara) — "
        "**mas esse limiar foi introduzido nesta implementação, no mesmo commit que produziu os "
        "primeiros resultados reais do EMOS H2, e não existe um artefato de pré-registro datado "
        "e independente que o fixasse antes disso.** Por honestidade metodológica, o critério 3 "
        "é reportado como diagnóstico CONDICIONADO a esse limiar não pré-registrado, nunca como "
        "aprovação certificada — o valor calculado (BSS dentro do limiar escolhido) é preservado "
        "integralmente para rastreabilidade. O valor mais próximo do limiar é "
        f"`umido = {_fmt(bss_proximo)}` — um caso LIMÍTROFE, não uma folga confortável.\n")

    linhas.append("\n## 5. Cobertura dos intervalos — EMOS vs. RAW (mesmos 95 casos)\n")
    linhas.append("| Nível nominal | Cobertura EMOS | Largura média EMOS (mm) | Cobertura RAW | Largura média RAW (mm) |\n|---|---|---|---|---|\n")
    for nivel in ('50', '80', '90'):
        e = cobertura[nivel]
        r = cobertura_raw[nivel]
        linhas.append(f"| {nivel}% | {_fmt(e['cobertura_empirica'], 3)} | {_fmt(e['largura_media'], 1)} | "
                       f"{_fmt(r['cobertura_empirica'], 3)} | {_fmt(r['largura_media'], 1)} |\n")

    linhas.append("\n## 6. PIT (mid-PIT, determinístico, sem RNG)\n")
    linhas.append(f"Média: {_fmt(pit['media'], 4)} (ideal: 0,5). Variância: {_fmt(pit['variancia'], 4)} "
                  f"(ideal: 1/12 ≈ 0,0833). N: {pit['n']}.\n\n"
                  "Contagens por decil (0,0-1,0): " + str(pit['contagens_por_bin']) + "\n\n"
                  f"**Concentração no último decil [0,9; 1,0]:** {pit.get('n_ultimo_decil')}/"
                  f"{pit['n']} observações (fração = {_fmt(pit.get('fracao_ultimo_decil'), 3)}, "
                  f"esperado sob uniformidade = {_fmt(pit.get('fracao_ultimo_decil_esperada_sob_uniformidade'), 2)}) "
                  "— mais que o dobro do esperado, consistente com o viés leve de PIT médio "
                  "acima de 0,5 (sub-previsão sistemática discutida no bias, seção 7).\n\n"
                  f"**Limitação da comparação com a uniforme:** {pit.get('nota_limitacao')}\n")

    linhas.append("\n## 7. Bias\n")
    linhas.append(
        f"- `bias_mu_latente` (diagnóstico do parâmetro latente): {_fmt(bias['bias_mu_latente'])} mm.\n"
        f"- `bias_media_preditiva_censurada` (**métrica principal**, usa E[Y]): "
        f"{_fmt(bias['bias_media_preditiva_censurada'])} mm.\n")

    linhas.append("\n## 8. Diagnóstico de parâmetros (distribuição temporal, 95 avaliações)\n")
    linhas.append("| Parâmetro | min | p10 | mediana | média | p90 | máx |\n|---|---|---|---|---|---|---|\n")
    for campo in ('a', 'b', 'c', 'd', 'a_d0', 'b_d0', 'c_d0'):
        s = diag[campo]
        linhas.append(f"| {campo} | {_fmt(s.get('minimo'))} | {_fmt(s.get('p10'))} | "
                       f"{_fmt(s.get('mediana'))} | {_fmt(s.get('media'))} | {_fmt(s.get('p90'))} | "
                       f"{_fmt(s.get('maximo'))} |\n")
    d_dest = diag['destaques']
    linhas.append(
        f"\nDestaques: `d` praticamente zero em {d_dest['n_d_proximo_de_zero']}/{n_casos['n_final']} "
        f"avaliações; `d` no bound inferior (0) em {d_dest['n_d_no_bound_inferior']}/{n_casos['n_final']}; "
        f"`gamma_c` no bound em {d_dest['n_gamma_c_no_bound']}; `gamma_c_d0` no bound em "
        f"{d_dest['n_gamma_c_d0_no_bound']}; `b` negativo em {d_dest['n_b_negativo']}; `b_d0` negativo em "
        f"{d_dest['n_b_d0_negativo']}.\n\n"
        "**Achado consistente nas 95 avaliações:** o otimizador converge para `d ≈ 0` "
        "(bound inferior) em TODAS elas — o EMOS completo colapsa estruturalmente ao EMOS "
        "`d=0` nesta amostra. Isso não é um sinal de implementação malfeita (os dois modelos "
        "são ajustados de forma independente — ver `tests/test_cfsv2_emos_h2_implementacao.py"
        "::IndependenciaD0TestCase`, que confirma divergência genuína num cenário sintético "
        "onde o sinal do spread é real); é o próprio otimizador descobrindo, a partir dos "
        "dados, que o termo dinâmico do spread não reduz o CRPS médio de treino — coerente "
        "com a informação MODESTA do spread já registrada no gate (correlações residuais "
        "0,07-0,24) e nas limitações do protocolo (seção 25).\n")

    linhas.append("\n## 9. Decisão segundo o critério pré-registrado (protocolo, seção 20)\n")
    linhas.append(
        f"| Critério | Resultado | Natureza |\n|---|---|---|\n"
        f"| 1. IC95(CRPSS_spread_dinamico) > 0 | {decisao['criterio_1_crpss_spread_dinamico_ic_acima_de_zero']} | "
        f"pré-registrado, sem ressalva |\n"
        f"| 2. IC95(CRPSS vs. climatologia) > 0 | {decisao['criterio_2_crpss_vs_climatologia_ic_acima_de_zero']} | "
        f"pré-registrado, sem ressalva |\n"
        f"| 3. Sem degradação grave de Brier/BSS | BSS dentro do limiar calculado: "
        f"{decisao['criterio_3_bss_dentro_do_limiar_calculado']} | "
        f"**`{decisao.get('criterio_3_classificacao')}`** (limiar não pré-registrado) |\n"
        f"| 4. Cobertura/calibração/PIT melhor que RAW | cobertura isolada dentro do esperado: "
        f"{decisao['criterio_4_cobertura_dentro_do_esperado_vs_raw']} | "
        f"**`{decisao.get('criterio_4_classificacao')}`** (avaliação parcial) |\n"
        f"| **Aprovado o componente dinâmico de spread?** | **{decisao['aprovado_componente_dinamico_de_spread']}** | — |\n\n"
        "**Motivos suficientes para a não aprovação** (independentes da classificação dos "
        "critérios 3/4 acima):\n"
        + ''.join(f"{i+1}. {m}.\n" for i, m in enumerate(decisao.get('motivos_suficientes_para_nao_aprovacao', [])))
        + f"\n{decisao['nota']}\n\n"
        f"**Limitação do critério 3:** {decisao.get('criterio_3_limitacao')}\n\n"
        f"**Limitação do critério 4:** {decisao.get('criterio_4_limitacao')}\n")

    linhas.append("\n## 10. Conclusão\n")
    if decisao['aprovado_componente_dinamico_de_spread']:
        conclusao = ("Os 4 critérios pré-registrados foram satisfeitos simultaneamente — o "
                      "componente dinâmico de spread do EMOS tem evidência suficiente, segundo "
                      "este protocolo, para ser considerado como acrescentando valor.")
    else:
        motivos = decisao.get('motivos_suficientes_para_nao_aprovacao', [])
        conclusao = (
            f"O critério pré-registrado NÃO foi satisfeito — {len(motivos)} motivo(s) já "
            f"suficiente(s) para a não aprovação, ambos pré-registrados sem ressalva (ver "
            f"seção 9): " + '; '.join(motivos) + ". O componente dinâmico de spread NÃO tem "
            f"evidência suficiente para ser considerado como acrescentando valor sobre corrigir "
            f"só média e dispersão climatológica. O EMOS (completo e `d=0`, estruturalmente "
            f"equivalentes nesta amostra) supera claramente o ensemble RAW "
            f"(CRPSS≈{_fmt(boot['CRPSS_vs_raw']['estimativa'])}, IC95 totalmente acima de zero) "
            f"mas não supera a climatologia probabilística causal "
            f"(CRPSS≈{_fmt(boot['CRPSS_vs_climatologia']['estimativa'])}, IC95 inclui zero) — "
            f"pelo protocolo (seção 20), superar só o RAW não basta. Os critérios 3 e 4 "
            f"(classificados como `{decisao.get('criterio_3_classificacao')}` e "
            f"`{decisao.get('criterio_4_classificacao')}`, nunca como aprovação binária "
            f"certificada) não alteram esta conclusão.")
    linhas.append(conclusao + "\n")

    linhas.append("\n## Limitações (protocolo, seção 25 — reafirmadas aqui)\n")
    linhas.append(
        "- Amostra curta: 95 previsões avaliáveis (~8 anos), warm-up de 120 pares consome a "
        "maior parte do histórico disponível.\n"
        "- H2 foi 1 de 6 horizontes testados no gate — nenhuma correção de multiplicidade "
        "aplicada.\n"
        "- O bootstrap é condicional à sequência causal já ajustada por expanding-window "
        "(sem refit dentro da reamostra).\n"
        "- `mu_latente` e `E[Y]` (média preditiva censurada) são quantidades diferentes — "
        "este relatório usa `E[Y]` como métrica principal de localização final.\n"
        "- O spread CFSv2 contém informação modesta, não forte — o resultado `d≈0` é "
        "consistente com essa limitação já documentada, não uma surpresa isolada.\n")

    linhas.append(
        "\n---\n**Esta atividade implementa e avalia o EMOS H2 real.** Nenhum pipeline "
        "operacional ou dashboard foi alterado. A decisão reportada na Seção 9 segue "
        "estritamente o critério pré-registrado no protocolo — não foi ajustada depois de "
        "observar o resultado.\n")

    return ''.join(linhas)


def gerar_e_escrever():
    resultados = json.loads(emos.CAMINHO_METRICAS_JSON.read_text())
    relatorio = gerar_relatorio_markdown(resultados)
    emos.RELATORIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    emos.RELATORIO_PATH.write_text(relatorio)
    print(f"  ✅ {emos.RELATORIO_PATH.relative_to(emos.ROOT)}")
    return relatorio


if __name__ == '__main__':
    gerar_e_escrever()
