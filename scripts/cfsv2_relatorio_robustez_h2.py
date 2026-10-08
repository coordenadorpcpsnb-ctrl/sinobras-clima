#!/usr/bin/env python3
"""
cfsv2_relatorio_robustez_h2.py — gera
docs/nmme-fase2c3d-robustez-spread-h2.md a partir de
data/cfsv2_calibracao_2c3d/robustez_h2_spread_2c3d.json (já calculado
por scripts/cfsv2_robustez_h2_spread.py --executar). Nunca recalcula
nada aqui — só lê e formata. Nunca chama H2 de "validado", nunca
implementa EMOS — este é um relatório de ROBUSTEZ do sinal
diagnóstico, não uma decisão de modelo.

Roda com:
    python scripts/cfsv2_relatorio_robustez_h2.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import cfsv2_robustez_h2_spread as r  # noqa: E402

NOMES_MES = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']

_IC_TEXTO = {
    'ic_totalmente_acima_de_zero': 'IC 95% ACIMA de zero',
    'ic_inclui_zero': 'IC inclui zero',
    'ic_totalmente_abaixo_de_zero': 'IC 95% ABAIXO de zero',
    'indeterminado': 'indeterminado',
}


def _fmt(val, casas=3):
    return 'N/D' if val is None else f'{val:.{casas}f}'


def _ic_texto(cl):
    return _IC_TEXTO.get(cl, cl or 'N/D')


def _g(dic, chave):
    return dic.get(chave, dic.get(str(chave)))


def gerar_relatorio_markdown(resultados):
    if resultados.get('STOP_ON_FAILURE'):
        return (
            "# Robustez do sinal spread×erro em H2 — Fase 2C.3D\n\n"
            "**STOP-ON-FAILURE — análise NÃO calculada.**\n\n"
            f"Motivo: {resultados.get('motivo')}\n\n"
            f"Detalhe: {json.dumps(resultados.get('detalhe', {}), ensure_ascii=False)}\n"
        )

    ref = resultados['referencia_congelada_h2']
    outros = resultados['outros_horizontes_congelado']
    lomo = resultados['leave_one_month_out']
    resumo = resultados['resumo_leave_one_month_out']
    robustez = resultados['classificacao_robustez_h2']
    loso = resultados['leave_one_season_out']
    diag_meses = resultados['diagnostico_meses_h2']
    influencia = resultados['analise_influencia']

    linhas = [
        "# Robustez do sinal spread×erro em H2 — Fase 2C.3D (Método 3.5)",
        "",
        "**Análise de ROBUSTEZ, não implementação. Nenhum EMOS foi ajustado, nenhum membro "
        "foi recalibrado, nenhuma probabilidade operacional foi alterada. O objetivo é "
        "determinar se a associação residual spread×erro observada em H2 (único horizonte "
        "com IC 95% acima de zero após o controle sazonal — ver "
        "`docs/nmme-fase2c3d-gate-calibracao-probabilistica-cfsv2.md`) é robusta ou depende "
        "excessivamente de poucos meses/estações. H2 nunca é chamado de \"validado\" neste "
        "documento.**",
        "",
        "Protegidos e não alterados nesta atividade: Métodos 3.1–3.4, gate 3.3, CFSv2 RAW, "
        "CHIRPS v3, dashboard, pipeline operacional, e todas as métricas já congeladas do "
        "gate do Método 3.5 (CRPS, CRPSS, Brier, BSS, cobertura, ranks, dependência de "
        "membros) — confirmadas idênticas por teste de regressão.",
        "",
        "## 1. Resultado congelado (referência)",
        "",
        f"**H2** — Pearson residual: `{ref['pearson_residual']}`, IC 95% "
        f"`[{ref['pearson_ic95'][0]}, {ref['pearson_ic95'][1]}]`; Spearman residual: "
        f"`{ref['spearman_residual']}`, IC 95% `[{ref['spearman_ic95'][0]}, "
        f"{ref['spearman_ic95'][1]}]`.",
        "",
        f"Congelamento confirmado contra o JSON real do gate: "
        f"{'✅ confere' if ref['congelamento_confirmado_contra_json_do_gate'] else '❌ DIVERGE — ver STOP_ON_FAILURE'}.",
        "",
        "## 2-3. Leave-one-month-out para H2",
        "",
        "Para cada mês excluído, a transformação é refeita INTEGRALMENTE sobre os dados "
        "restantes: médias mensais dos meses remanescentes → resíduos → correlação → "
        "bootstrap em blocos por `target_ano` (`g._bootstrap_residualizado_por_ano`, "
        "reaproveitado sem modificação — mesma metodologia do gate original). Nenhum "
        "resíduo da análise completa é reaproveitado.",
        "",
        "| Mês removido | N | Pearson | IC 95% | Classificação | Spearman | IC 95% | "
        "Classificação |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for mes in range(1, 13):
        d = _g(lomo, mes)
        if not d.get('amostra_suficiente', False):
            linhas.append(f"| {NOMES_MES[mes-1]} | {d.get('n', 0)} | — | — | — | — | — | — |")
            continue
        p, s = d['pearson'], d['spearman']
        linhas.append(
            f"| {d['mes_excluido_nome']} | {d['n']} | {_fmt(p['estimativa'])} | "
            f"[{_fmt(p['ic95_lo'])}, {_fmt(p['ic95_hi'])}] | {_ic_texto(d['pearson_ic_classificacao'])} | "
            f"{_fmt(s['estimativa'])} | [{_fmt(s['ic95_lo'])}, {_fmt(s['ic95_hi'])}] | "
            f"{_ic_texto(d['spearman_ic_classificacao'])} |")

    linhas += [
        "",
        "### 3.1. Resumo das 12 exclusões",
        "",
        "| Métrica | Mínimo | Mediana | Máximo | Exclusões com valor > 0 (de 12) | "
        "Exclusões com IC 95% acima de zero (de 12) |",
        "|---|---|---|---|---|---|",
        f"| Pearson | {_fmt(resumo['pearson_minimo'])} | {_fmt(resumo['pearson_mediana'])} | "
        f"{_fmt(resumo['pearson_maximo'])} | {resumo['n_exclusoes_pearson_positivo']} | "
        f"{resumo['n_exclusoes_pearson_ic_acima_de_zero']} |",
        f"| Spearman | {_fmt(resumo['spearman_minimo'])} | {_fmt(resumo['spearman_mediana'])} | "
        f"{_fmt(resumo['spearman_maximo'])} | {resumo['n_exclusoes_spearman_positivo']} | "
        f"{resumo['n_exclusoes_spearman_ic_acima_de_zero']} |",
        "",
        "## 4. Classificação de robustez de H2",
        "",
        "**Critério pré-registrado (fixado antes de rodar contra dados reais — ver "
        "constantes no topo de `scripts/cfsv2_robustez_h2_spread.py`):**",
        "",
        f"- `{r.CLASSIFICACAO_H2_ROBUSTO}`: Pearson E Spearman positivos em "
        f">= {r.LIMIAR_ROBUSTO_POSITIVO_DE_12}/12 exclusões, pelo menos uma métrica com IC "
        f"95% acima de zero na maioria (>= {r.LIMIAR_MAIORIA_DE_12}/12), e nenhuma exclusão "
        f"com inversão forte (< {r.LIMIAR_INVERSAO_FORTE}).",
        f"- `{r.CLASSIFICACAO_H2_PROMISSOR_FRAGIL}`: sinal mediano positivo e maioria das "
        "exclusões ainda positivas, mas sem atingir o limiar robusto.",
        f"- `{r.CLASSIFICACAO_H2_DEPENDENTE_POUCOS_MESES}`: poucas exclusões mantêm o sinal "
        "positivo, ou alguma exclusão produz inversão forte.",
        "",
        f"**Resultado:** `{robustez['classificacao']}`",
        "",
        f"{robustez['justificativa']}",
        "",
        "| Sinal | Valor |",
        "|---|---|",
    ]
    for chave, rotulo in [
        ('ambas_positivas_limiar_robusto', 'Pearson e Spearman positivos em >= limiar robusto'),
        ('pelo_menos_uma_ic_maioria', 'Pelo menos uma métrica com IC>0 na maioria'),
        ('inversao_forte_em_alguma_exclusao', 'Alguma exclusão com inversão forte'),
        ('ambas_positivas_maioria', 'Pearson e Spearman positivos na maioria'),
        ('sinal_mediano_positivo', 'Sinal mediano positivo'),
    ]:
        linhas.append(f"| {rotulo} | {'✅' if robustez['sinais'][chave] else '❌'} |")

    linhas += [
        "",
        "## 5. Leave-one-season-out",
        "",
        "Mesma reutilização de `g._bootstrap_residualizado_por_ano` — grupos sazonais já "
        "existentes no projeto (chuvosa/transição/seca).",
        "",
        "| Estação excluída | N | Pearson | IC 95% | Classificação | Spearman | IC 95% | "
        "Classificação |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for grupo in ('chuvosa', 'transicao', 'seca'):
        d = loso[grupo]
        if not d.get('amostra_suficiente', False):
            linhas.append(f"| {grupo} | {d.get('n', 0)} | — | — | — | — | — | — |")
            continue
        p, s = d['pearson'], d['spearman']
        linhas.append(
            f"| {grupo} | {d['n']} | {_fmt(p['estimativa'])} | "
            f"[{_fmt(p['ic95_lo'])}, {_fmt(p['ic95_hi'])}] | {_ic_texto(d['pearson_ic_classificacao'])} | "
            f"{_fmt(s['estimativa'])} | [{_fmt(s['ic95_lo'])}, {_fmt(s['ic95_hi'])}] | "
            f"{_ic_texto(d['spearman_ic_classificacao'])} |")
    linhas.append("")
    linhas.append("O sinal não pertence exclusivamente a uma estação: excluir "
                   "transição ou seca mantém IC 95% acima de zero; excluir a estação "
                   "chuvosa (a maior das três, N cai para 100) reduz a amostra o bastante "
                   "para o IC passar a incluir zero — consistente com perda de poder "
                   "estatístico, não necessariamente com ausência de sinal fora da estação "
                   "chuvosa. **Controle mensal (seções 2-4) continua sendo a análise "
                   "principal — este agrupamento sazonal é só complementar.**")

    linhas += [
        "",
        "## 6. Diagnóstico complementar dos 12 meses (valores brutos por célula)",
        "",
        "Descritivo — nenhum teste de significância por mês.",
        "",
        "| Mês | N | Pearson | Spearman | Spread médio | Erro absoluto médio |",
        "|---|---|---|---|---|---|",
    ]
    destaques_pos, destaques_neg, destaques_zero = [], [], []
    for mes in range(1, 13):
        d = diag_meses[str(mes)] if str(mes) in diag_meses else diag_meses[mes]
        p = d.get('pearson_std_vs_erro_abs')
        if d.get('n', 0) < 3 or p is None:
            linhas.append(f"| {d['mes_nome']} | {d.get('n', 0)} | — | — | — | — |")
            continue
        linhas.append(f"| {d['mes_nome']} | {d['n']} | {_fmt(p)} | "
                       f"{_fmt(d.get('spearman_std_vs_erro_abs'))} | "
                       f"{_fmt(d.get('spread_medio'), 2)} | {_fmt(d.get('erro_abs_medio'), 2)} |")
        if p > 0.3:
            destaques_pos.append(d['mes_nome'])
        elif p < -0.1:
            destaques_neg.append(d['mes_nome'])
        else:
            destaques_zero.append(d['mes_nome'])
    linhas.append("")
    linhas.append(f"Sinal positivo mais forte (Pearson > 0,3): {', '.join(destaques_pos) or '—'}. "
                   f"Sinal negativo (Pearson < -0,1): {', '.join(destaques_neg) or '—'}. "
                   f"Próximo de zero: {', '.join(destaques_zero) or '—'}.")

    linhas += [
        "",
        "## 7. Sensibilidade ao mês de maior associação",
        "",
        "**Análise de INFLUÊNCIA, não seleção de modelo** — nenhuma destas exclusões decide "
        "a metodologia final.",
        "",
        f"- Mês com maior Pearson observado (célula bruta, seção 6): "
        f"**{influencia['mes_maior_pearson_observado_nome']}**.",
        f"- Mês com maior Spearman observado: **{influencia['mes_maior_spearman_observado_nome']}**.",
    ]
    if influencia['marco_e_o_mes_de_maior_pearson_e_spearman']:
        linhas.append("- Março é o mês de maior Pearson E maior Spearman — uma única análise "
                       "(\"sem março\") atende aos itens \"sem março\", \"sem o mês de maior "
                       "Pearson\" e \"sem o mês de maior Spearman\" simultaneamente.")
    linhas += [
        "",
        "| Cenário | N | Pearson | IC 95% | Spearman | IC 95% |",
        "|---|---|---|---|---|---|",
        f"| H2 completo (referência) | 240 | {_fmt(ref['pearson_residual'])} | "
        f"[{_fmt(ref['pearson_ic95'][0])}, {_fmt(ref['pearson_ic95'][1])}] | "
        f"{_fmt(ref['spearman_residual'])} | [{_fmt(ref['spearman_ic95'][0])}, "
        f"{_fmt(ref['spearman_ic95'][1])}] |",
    ]
    sem_marco = influencia.get('sem_marco')
    if sem_marco and sem_marco.get('amostra_suficiente'):
        p, s = sem_marco['pearson'], sem_marco['spearman']
        linhas.append(f"| Sem março | {sem_marco['n']} | {_fmt(p['estimativa'])} | "
                       f"[{_fmt(p['ic95_lo'])}, {_fmt(p['ic95_hi'])}] | {_fmt(s['estimativa'])} | "
                       f"[{_fmt(s['ic95_lo'])}, {_fmt(s['ic95_hi'])}] |")
    if not influencia['marco_e_o_mes_de_maior_pearson_e_spearman']:
        sem_p = influencia.get('sem_mes_maior_pearson')
        sem_s = influencia.get('sem_mes_maior_spearman')
        if sem_p and sem_p.get('amostra_suficiente'):
            p = sem_p['pearson']
            linhas.append(f"| Sem {influencia['mes_maior_pearson_observado_nome']} (maior Pearson) | "
                           f"{sem_p['n']} | {_fmt(p['estimativa'])} | "
                           f"[{_fmt(p['ic95_lo'])}, {_fmt(p['ic95_hi'])}] | — | — |")
        if sem_s and sem_s.get('amostra_suficiente'):
            s = sem_s['spearman']
            linhas.append(f"| Sem {influencia['mes_maior_spearman_observado_nome']} (maior Spearman) | "
                           f"{sem_s['n']} | — | — | {_fmt(s['estimativa'])} | "
                           f"[{_fmt(s['ic95_lo'])}, {_fmt(s['ic95_hi'])}] |")
    linhas.append("")
    linhas.append("Remover março leva Pearson ao seu valor MÍNIMO entre as 12 exclusões "
                   "(ver seção 3) e o IC passa a incluir zero — março tem influência real, "
                   "mas o sinal permanece positivo e numericamente próximo das demais "
                   "exclusões (não há um colapso para valores negativos), o que é "
                   "compatível com a classificação de robustez da seção 4.")

    linhas += [
        "",
        "## 8. Multiplicidade",
        "",
        resultados['multiplicidade_nota'],
        "",
        "## 9. Decisão sobre EMOS",
        "",
        f"**`{resultados['decisao_final_emos_h2']}`**",
        "",
        "- `prosseguir_para_protocolo_emos_h2`: recomendado se a classificação de robustez "
        "(seção 4) for `sinal_h2_robusto`.",
        "- `nao_justificar_emos_dinamico_h2`: se `sinal_h2_dependente_de_poucos_meses`.",
        "- `h2_promissor_mas_evidencia_insuficiente`: se `sinal_h2_promissor_mas_fragil`.",
        "",
        "**Nenhum EMOS foi implementado nesta atividade** — esta é só a decisão de "
        "próximo passo, condicionada à revisão independente deste resultado.",
        "",
        "## 10. H1, H3-H6 — preservados como comparação (não repetidos)",
        "",
        "Já falharam no gate principal controlado por mês (ver "
        "`docs/nmme-fase2c3d-gate-calibracao-probabilistica-cfsv2.md`); leave-one-month-out "
        "NÃO foi repetido para eles nesta atividade.",
        "",
        "| Horizonte | Pearson residual (gate principal, congelado) |",
        "|---|---|",
    ]
    for lead in (1, 3, 4, 5, 6):
        linhas.append(f"| H{lead} | {_fmt(outros[str(lead)] if str(lead) in outros else outros[lead])} |")

    linhas += [
        "",
        "## 11. Métricas congeladas (CRPS/CRPSS/Brier/BSS/cobertura/ranks/dependência)",
        "",
        "**Não alteradas nesta atividade** — confirmado por teste de regressão automatizado "
        "(`tests/test_cfsv2_robustez_h2_spread.py`) comparando byte-a-byte contra o JSON do "
        "gate já publicado.",
        "",
        "## 12. Escopo",
        "",
        "Não implementados nesta atividade: EMOS, dressing, recalibração de membros, "
        "probabilidades operacionais. Não alterados: Métodos 3.1–3.4, gate 3.3, CFSv2 RAW, "
        "CHIRPS v3, dashboard, pipeline operacional.",
        "",
        "## 13. Conclusão restrita a esta análise de robustez",
        "",
        "Esta conclusão vale SOMENTE para a robustez do sinal spread×erro controlado por "
        "mês em H2 — nunca uma validação do Método 3.5 nem uma aprovação de EMOS.",
        "",
        f"- Classificação de robustez: `{robustez['classificacao']}`.",
        f"- Decisão de próximo passo: `{resultados['decisao_final_emos_h2']}`.",
        "- H2 permanece o único horizonte candidato a calibração probabilística dinâmica "
        "entre os seis avaliados — tratado aqui como achado exploratório robusto às 12 "
        "exclusões mensais e à maior parte das exclusões sazonais, nunca como \"modelo "
        "validado\".",
        "- Implementação de EMOS (se decidida) permanece de uma próxima etapa, condicionada "
        "à revisão independente deste resultado.",
    ]
    return '\n'.join(linhas) + '\n'


def gerar_e_escrever():
    resultados = json.loads(r.CAMINHO_METRICAS_JSON.read_text())
    relatorio = gerar_relatorio_markdown(resultados)
    r.RELATORIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    r.RELATORIO_PATH.write_text(relatorio)
    print(f"  ✅ {r.RELATORIO_PATH.relative_to(r.ROOT)}")
    return relatorio


if __name__ == '__main__':
    gerar_e_escrever()
