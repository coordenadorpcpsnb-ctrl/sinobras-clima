#!/usr/bin/env python3
"""
cfsv2_relatorio_viabilidade_qm.py — gera
docs/nmme-fase2c3d-viabilidade-quantile-mapping.md a partir de
data/cfsv2_calibracao_2c3d/viabilidade_quantile_mapping.json (já
calculado por scripts/cfsv2_viabilidade_quantile_mapping.py
--executar). Nunca recalcula nada aqui — só lê e formata. Nenhum
skill/RMSE/MAE/IC do Método 3.3 aparece neste relatório porque nenhum
foi calculado.

Roda com:
    python scripts/cfsv2_relatorio_viabilidade_qm.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import cfsv2_viabilidade_quantile_mapping as q  # noqa: E402
import cfsv2_validacao_cientifica as v  # noqa: E402

NOMES_MES = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']


def gerar_relatorio_markdown(resultados):
    if resultados.get('STOP_ON_FAILURE'):
        return (
            "# Gate de viabilidade — Método 3.3 (Quantile Mapping), Fase 2C.3D\n\n"
            "**STOP-ON-FAILURE — avaliação de viabilidade NÃO concluída.**\n\n"
            f"Motivo: {resultados.get('motivo')}\n\n"
            f"Detalhe: {json.dumps(resultados.get('detalhe', {}), ensure_ascii=False)}\n"
        )

    av = resultados['avaliacao']
    matriz = resultados['matriz_maximo_n_causal_por_celula']
    testavel = av['metodo_3_3_testavel']

    linhas = [
        "# Gate de viabilidade — Método 3.3 (Quantile Mapping), Fase 2C.3D",
        "",
        "**Documento de GATE — não é uma avaliação de desempenho.** Nenhum `forecast_"
        "calibrado` por quantile mapping foi calculado. Nenhum RMSE, MAE, skill ou IC do "
        "Método 3.3 existe nesta atividade — só a contagem, programática, de quantas "
        "observações históricas causais cada célula (lead × mês-alvo) teria disponível para "
        "treinar um mapeamento de quantis, comparada ao limiar pré-registrado "
        f"`AMOSTRA_MINIMA_ESTRATO = {av['limiar_minimo_quantile_mapping']}`.",
        "",
        "## 0. Restrição estrutural da amostra",
        "",
        "O CFSv2 histórico aprovado (`data/nmme_historico_fazendas/`) é um hindcast **FIXO**: "
        "240 inicializações, jan/1991-dez/2010 (20 anos) — não cresce com o calendário atual, "
        "é a extração já aprovada na Fase 2C.3C. A calibração é causal "
        "(`init_date_treino < init_date_avaliada`) e específica por `lead × mês-alvo`; como "
        "mês-alvo = mês de inicialização + lead - 1 (função determinística do mês de "
        "inicialização para um lead fixo), **cada célula tem exatamente 1 inicialização por "
        "ano** — no máximo 20 observações totais por célula, no máximo 19 estritamente "
        "anteriores à última (causal nunca inclui a própria avaliada).",
        "",
        f"- N total de previsões avaliadas (todas as células, todos os leads): "
        f"{av['n_previsoes_total_avaliadas']}.",
        f"- N total de células (lead × mês-alvo): {av['n_celulas_total']} "
        f"({len(v.LEADS_ESPERADOS)} leads × 12 meses).",
        f"- Verificação de que os 24 membros do ensemble NÃO inflaram a contagem (item 3 do "
        f"pedido): {resultados['dedup_ensemble_check']['n_linhas_base_pareada_original']} "
        f"linhas na base pareada (membro a membro) → {resultados['dedup_ensemble_check']['n_indice']} "
        "linhas após deduplicar para 1 por (init_date, lead) — exatamente "
        f"{resultados['dedup_ensemble_check']['n_esperado']} esperado "
        f"({'✅ OK' if resultados['dedup_ensemble_check']['ok'] else '❌ FALHOU'}).",
        "",
        "## 1. Máximo N causal disponível por célula",
        "",
        f"**Máximo observado em TODA a base: {av['maximo_n_causal_observado_geral']}** "
        f"(confirmado no fim da série — a última inicialização cronológica de cada célula, "
        f"ano 2010). Mínimo do máximo entre as 72 células: "
        f"{av['minimo_do_maximo_n_causal_por_celula']}. "
        f"Valores distintos de máximo observados entre as células: "
        f"{av['valores_distintos_do_maximo_por_celula']} — {av['nota_maximo_uniforme']}",
        "",
        "### 1.1. Matriz do máximo de N causal por célula (lead × mês-alvo)",
        "",
        "| Mês \\ Lead | " + " | ".join(f"H{l}" for l in v.LEADS_ESPERADOS) + " |",
        "|---" * (len(v.LEADS_ESPERADOS) + 1) + "|",
    ]
    for mes in range(1, 13):
        celulas = []
        for lead in v.LEADS_ESPERADOS:
            mapa_lead = matriz.get(lead, matriz.get(str(lead), {}))
            celulas.append(str(mapa_lead.get(mes, mapa_lead.get(str(mes), '—'))))
        linhas.append(f"| {NOMES_MES[mes-1]} | " + " | ".join(celulas) + " |")

    linhas += [
        "",
        "### 1.2. Distribuição de N ao longo do tempo (agregada, todas as 72 células)",
        "",
        "Cada célula percorre exatamente a mesma sequência cronológica de N "
        "(0, 1, 2, ..., 19) — por isso a contagem por valor é idêntica em toda a tabela "
        "(72 células, 1 ocorrência de cada valor por célula):",
        "",
        "| N causal | N° de previsões com esse N (em todas as células) |",
        "|---|---|",
    ]
    for n_valor, contagem in sorted(av['distribuicao_n_treino_causal_geral'].items(),
                                     key=lambda kv: int(kv[0])):
        linhas.append(f"| {n_valor} | {contagem} |")

    linhas += [
        "",
        "## 2. Avaliação formal contra o limiar pré-registrado",
        "",
        f"`AMOSTRA_MINIMA_ESTRATO = {av['limiar_minimo_quantile_mapping']}` — mesmo limiar já "
        "usado em toda a Fase 2C.3C/2C.3D, **nunca reduzido** depois de conhecer os "
        "resultados dos Métodos 3.1/3.2.",
        "",
        f"- **Número de previsões com N >= {av['limiar_minimo_quantile_mapping']}: "
        f"{av['n_previsoes_com_n_maior_igual_limiar']}** (de {av['n_previsoes_total_avaliadas']} "
        "avaliadas).",
        f"- **Número de células com N >= {av['limiar_minimo_quantile_mapping']}: "
        f"{av['n_celulas_com_n_maior_igual_limiar']}** (de {av['n_celulas_total']}).",
        f"- Primeiro ano elegível: {av['nota_primeiro_ano_elegivel']}",
        f"- Período avaliável restante: {av['periodo_avaliavel_restante']}",
        "",
        "## 3. LOYO — SOMENTE como contexto (nunca como substituto da avaliação causal)",
        "",
        f"`{av['loyo_contexto']['nota']}`",
        "",
        f"- Máximo de N em desenho LOYO (exclui só o próprio ano, usa passado E futuro): "
        f"{av['loyo_contexto']['maximo_n_loyo_geral']}.",
        f"- Número de células que atingiriam o limiar em LOYO: "
        f"{av['loyo_contexto']['n_celulas_loyo_com_n_maior_igual_limiar']} de "
        f"{av['n_celulas_total']}.",
        "- **O mesmo teto estrutural (20 anos totais na base) limita o LOYO tanto quanto o "
        "causal** — LOYO ganha só 1 ano extra por célula (o próprio ano, no caso causal "
        "sempre excluído; aqui também excluído, mas sem a exigência de ser só passado), "
        "nunca o suficiente para cruzar o limiar de 20. Isto confirma que a limitação é "
        "estrutural do período histórico disponível, não um artefato do desenho causal "
        "especificamente.",
        "",
        "## 4. Decisão final",
        "",
        f"**`metodo_3_3_status = {av['metodo_3_3_status']}`**",
        "",
    ]
    if testavel:
        linhas.append(
            "O Método 3.3 (quantile mapping) é **TESTÁVEL** sob as regras pré-registradas — "
            "ver a matriz acima para quais células especificamente atingem o limiar. A "
            "implementação do método em si (cálculo de quantis, forecast calibrado, skills) "
            "é uma atividade SEPARADA, condicionada à revisão deste gate.")
    else:
        linhas += [
            "O Método 3.3 (quantile mapping) é **NÃO TESTÁVEL por insuficiência de amostra** — "
            "**isto não é uma falha do pipeline**, é uma limitação estrutural do período "
            "histórico disponível (20 anos de hindcast CFSv2, máximo de 19 observações causais "
            "por célula, sempre abaixo do limiar de 20 exigido para quantile mapping).",
            "",
            "Conforme o próprio protocolo pré-registrado, o Método 3.3 é **pulado** por "
            "insuficiência de amostra. O próximo método elegível é:",
            "",
            f"**`{resultados['proximo_metodo_elegivel_se_inviavel']}`** — Método 3.4, regressão "
            "linear / MOS simples. **Não implementado nesta atividade.**",
        ]

    linhas += [
        "",
        "## 5. O que NÃO foi feito nesta atividade (item 3 do pedido)",
        "",
        "- Nenhum pooling entre meses ou entre leads.",
        "- Nenhuma redução do limiar de 20 observado nos resultados.",
        "- Nenhuma interpolação de quantis com N < 20.",
        "- LOYO usado SOMENTE como contexto (seção 3), nunca como substituto da avaliação "
        "causal para declarar o método testável.",
        "- Nenhum uso de 1981-1990 como se fossem previsões CFSv2 (o CFSv2 não existe nesse "
        "período; só CHIRPS/estações têm dado observacional ali).",
        "- Nenhum random split.",
        "- Nenhuma expansão artificial de N usando os 24 membros do ensemble como anos "
        "independentes — confirmado pela verificação de deduplicação (seção 0).",
        "- Nenhum `forecast_calibrado` por quantile mapping, nenhum RMSE/MAE/skill/IC do "
        "Método 3.3 foi calculado.",
    ]
    return '\n'.join(linhas) + '\n'


def gerar_e_escrever():
    resultados = json.loads(q.CAMINHO_METRICAS_JSON.read_text())
    relatorio = gerar_relatorio_markdown(resultados)
    q.RELATORIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    q.RELATORIO_PATH.write_text(relatorio)
    print(f"  ✅ {q.RELATORIO_PATH.relative_to(q.ROOT)}")
    return relatorio


if __name__ == '__main__':
    gerar_e_escrever()
