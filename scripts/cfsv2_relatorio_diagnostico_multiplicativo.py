#!/usr/bin/env python3
"""
cfsv2_relatorio_diagnostico_multiplicativo.py — gera
docs/nmme-fase2c3d-protocolo-multiplicativo-cfsv2.md a partir de
data/cfsv2_calibracao_2c3d/diagnostico_multiplicativo.json. Nunca
recalcula nada aqui — só lê e formata.

Roda com:
    python scripts/cfsv2_relatorio_diagnostico_multiplicativo.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import cfsv2_diagnostico_multiplicativo as d  # noqa: E402
import cfsv2_validacao_cientifica as v  # noqa: E402

NOMES_MES = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']


def _fmt(val, casas=2):
    return 'N/D' if val is None else f'{val:.{casas}f}'


def gerar_relatorio_markdown(resultados):
    den = resultados['diagnostico_denominador']
    razao = resultados['diagnostico_razao']
    piso = resultados['avaliacao_candidatos_piso']
    risco = resultados['risco_negativo_ou_explosivo']

    linhas = [
        "# Protocolo da correção multiplicativa do CFSv2 — Fase 2C.3D (Método 3.2)",
        "",
        "**Documento de diagnóstico PRÉVIO — não é relatório de resultados.** Nenhum "
        "`forecast_calibrado` multiplicativo foi calculado. Nenhum skill, RMSE ou razão "
        "aplicada a uma previsão real foi calculado nesta atividade — só a distribuição dos "
        "dois ingredientes já aprovados (`climatologia_observada`, `climatologia_modelo_raw`) "
        "da tabela do Método 3.1, já aprovada "
        f"(`{d.CAMINHO_TABELA_ADITIVA_APROVADA.relative_to(ROOT)}`), lida aqui, nunca "
        "reescrita. O piso de segurança proposto é definido exclusivamente por "
        "estabilidade numérica/física — nunca escolhido observando qual valor produziria "
        "melhor skill, porque nenhum skill existe ainda.",
        "",
        "## 0. Desenho que será reaproveitado integralmente (regras fixas)",
        "",
        "- `N_TREINO_MINIMO = 10` (protocolo, Seção 5.1) — mesmo warm-up do Método 3.1.",
        "- Expanding-window causal como avaliação principal; avaliação principal restrita "
        "aos MESMOS casos elegíveis do método aditivo (N=720=120×6 leads, `status_"
        "calibracao='ok'` da tabela aprovada).",
        "- LOYO full apenas descritivo; LOYO matched para a comparação direta "
        "(protocolo, Seção 5.1 da 2C.3D revisão 2).",
        "- Três benchmarks: CFSv2 bruto, climatologia causal, "
        "`benchmark_anomalia_reconstruida`.",
        "- Bootstrap em blocos por `target_ano`; mesmo critério de aprovação (IC 95% de "
        "`skill_vs_anomalia_reconstruida` E `RMSESS_climatologia` totalmente acima de zero, "
        "simultaneamente).",
        "- H1 sempre separado de H2-H6.",
        "- Matriz mês × lead só como diagnóstico de heterogeneidade, nunca 72 testes de "
        "significância.",
        "",
        "## 1. Distribuição histórica de média(forecast_raw_treino) — o denominador",
        "",
        f"População analisada: N={resultados['n_total_elegivel_metodo_aditivo']} (status_"
        "calibracao='ok' da tabela aprovada do Método 3.1 — a MESMA população que o Método "
        "3.2 usará).",
        "",
        "### 1.1. Por mês-alvo (todos os leads agregados)",
        "",
        "| Mês | N | Mínimo | p05 | p10 | p25 | Mediana | Média | p75 | p90 | Máximo |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for mes in range(1, 13):
        s = den['por_mes'][str(mes)]
        linhas.append(f"| {NOMES_MES[mes-1]} | {s['n']} | {_fmt(s['minimo'])} | {_fmt(s['p05'])} | "
                       f"{_fmt(s['p10'])} | {_fmt(s['p25'])} | {_fmt(s['mediana'])} | "
                       f"{_fmt(s['media'])} | {_fmt(s['p75'])} | {_fmt(s['p90'])} | "
                       f"{_fmt(s['maximo'])} |")

    linhas += [
        "",
        "### 1.2. Por lead (todos os meses agregados)",
        "",
        "| Lead | N | Mínimo | p05 | p10 | p25 | Mediana | Média | p75 | p90 | Máximo |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for lead in v.LEADS_ESPERADOS:
        s = den['por_lead'][str(lead)]
        linhas.append(f"| H{lead} | {s['n']} | {_fmt(s['minimo'])} | {_fmt(s['p05'])} | "
                       f"{_fmt(s['p10'])} | {_fmt(s['p25'])} | {_fmt(s['mediana'])} | "
                       f"{_fmt(s['media'])} | {_fmt(s['p75'])} | {_fmt(s['p90'])} | "
                       f"{_fmt(s['maximo'])} |")

    linhas += [
        "",
        "### 1.3. Por grupo sazonal (chuvosa/transição/seca)",
        "",
        "| Grupo | N | Mínimo | p05 | p10 | p25 | Mediana | Média | p75 | p90 | Máximo |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for grupo in ('chuvosa', 'transicao', 'seca'):
        s = den['por_grupo_sazonal'][grupo]
        linhas.append(f"| {grupo} | {s['n']} | {_fmt(s['minimo'])} | {_fmt(s['p05'])} | "
                       f"{_fmt(s['p10'])} | {_fmt(s['p25'])} | {_fmt(s['mediana'])} | "
                       f"{_fmt(s['media'])} | {_fmt(s['p75'])} | {_fmt(s['p90'])} | "
                       f"{_fmt(s['maximo'])} |")

    linhas += [
        "",
        "## 2. Proposta objetiva do piso",
        "",
        f"**Piso proposto: {_fmt(piso['piso_proposto_mm'], 1)}mm.** Critério: existe um GAP "
        "VAZIO no denominador entre o maior valor dos meses mais secos e o menor valor dos "
        "demais meses — **nenhum (lead, mês) tem denominador dentro desse intervalo**, "
        "confirmado para todos os 6 leads individualmente, não só no agregado:",
        "",
        f"- Maior denominador entre os meses inteiramente abaixo do piso: "
        f"{_fmt(piso['maior_denominador_entre_os_meses_abaixo'])}mm.",
        f"- Menor denominador entre os meses inteiramente acima do piso: "
        f"{_fmt(piso['menor_denominador_entre_os_meses_acima'])}mm.",
        f"- Gap seguro confirmado: [{_fmt(piso['gap_seguro_mm'][0])}, "
        f"{_fmt(piso['gap_seguro_mm'][1])}]mm — o piso proposto ({_fmt(piso['piso_proposto_mm'], 1)}mm) "
        "cai dentro desse gap, portanto **nenhum mês é fragmentado em nenhum lead**.",
        f"- Meses inteiramente abaixo do piso: "
        f"{', '.join(NOMES_MES[m-1] for m in piso['meses_inteiramente_abaixo_do_piso'])}.",
        f"- Meses inteiramente acima do piso: "
        f"{', '.join(NOMES_MES[m-1] for m in piso['meses_inteiramente_acima_do_piso'])}.",
        f"- Meses fragmentados pelo piso (deveria ser vazio): "
        f"{piso['meses_fragmentados_pelo_piso'] or 'nenhum'}.",
        "",
        "**O piso NUNCA foi escolhido observando qual valor produz melhor RMSE/skill — "
        "nenhum skill multiplicativo foi calculado nesta atividade.** A escolha é "
        "puramente baseada em onde a distribuição do denominador tem uma separação natural "
        "entre meses fisicamente secos e os demais.",
        "",
        "## 3. Quantidade de casos que seriam excluídos",
        "",
        "| Piso candidato (mm) | N excluído | % excluído |",
        "|---|---|---|",
    ]
    for piso_cand, info in sorted(piso['candidatos'].items(), key=lambda kv: float(kv[0])):
        marca = ' **(proposto)**' if abs(float(piso_cand) - piso['piso_proposto_mm']) < 1e-9 else ''
        linhas.append(f"| {_fmt(float(piso_cand), 1)}{marca} | {info['n_excluido']} | "
                       f"{info['pct_excluido']}% |")

    linhas += [
        "",
        f"**No piso proposto ({_fmt(piso['piso_proposto_mm'], 1)}mm): "
        f"{piso['n_excluido_no_piso_proposto']} de {resultados['n_total_elegivel_metodo_aditivo']} "
        f"casos elegíveis seriam excluídos "
        f"({100*piso['n_excluido_no_piso_proposto']/resultados['n_total_elegivel_metodo_aditivo']:.1f}%)** "
        "— corresponde exatamente aos meses jun-set em todos os 6 leads (4 meses × 6 leads × "
        "10 anos = 240), o núcleo da estação seca regional (CLAUDE.md: seca bem marcada "
        "jun-ago, com setembro de transição tardia).",
        "",
        "## 4. Distribuição das razões resultantes (puramente descritivo — nunca um skill)",
        "",
        "`razão = climatologia_observada / climatologia_modelo_raw` — ambas já causais, "
        "herdadas do Método 3.1. Esta NÃO é uma previsão calibrada nem uma métrica de "
        "skill — é só a razão entre duas climatologias, para entender a MAGNITUDE que o "
        "fator multiplicativo teria.",
        "",
        "### 4.1. Por mês-alvo",
        "",
        "| Mês | N | Mínimo | p05 | p10 | p25 | Mediana | Média | p75 | p90 | Máximo |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for mes in range(1, 13):
        s = razao['por_mes'][str(mes)]
        linhas.append(f"| {NOMES_MES[mes-1]} | {s['n']} | {_fmt(s['minimo'])} | {_fmt(s['p05'])} | "
                       f"{_fmt(s['p10'])} | {_fmt(s['p25'])} | {_fmt(s['mediana'])} | "
                       f"{_fmt(s['media'])} | {_fmt(s['p75'])} | {_fmt(s['p90'])} | "
                       f"{_fmt(s['maximo'])} |")

    linhas += [
        "",
        "## 5. Risco específico na estação seca — E um achado adicional fora da estação seca",
        "",
        "### 5.1. Estação seca (esperado)",
        "",
        "Jun-set têm os menores denominadores de toda a série (máximo "
        f"{_fmt(piso['maior_denominador_entre_os_meses_abaixo'])}mm) — risco de razão "
        "INSTÁVEL/EXPLOSIVA por denominador pequeno, exatamente o modo de falha já "
        "documentado em produção (`CLAUDE.md`, armadilha 7: corrigir julho por um fator "
        "fixo multiplicou a chuva por quase 46× e piorou o RMSE do SARIMAX). O piso "
        "proposto (Seção 2) remove inteiramente esse risco, excluindo esses meses da "
        "avaliação multiplicativa principal.",
        "",
        "### 5.2. Achado adicional — risco SISTEMÁTICO mesmo acima do piso (não esperado)",
        "",
        "**Mesmo com denominador ACIMA do piso proposto, algumas células (mês, lead) têm "
        "razão mediana consistentemente alta em TODOS os ~10 anos — não é instabilidade "
        "de amostra pequena, é um viés sistemático real do CFSv2.** Destaque: outubro, em "
        "TODOS os 6 leads, com denominador seguro (16,6-25,7mm) mas razão mediana entre "
        "4,9× e 7,4× — o modelo climatologicamente prevê ~17-26mm para outubro quando a "
        "climatologia observada causal é ~125-133mm (consistente com a climatologia de "
        "referência do projeto, `CLIM_JAN_DEZ[9]=119,7mm` no `CLAUDE.md`). Maio e novembro "
        "mostram o mesmo padrão em menor intensidade (maio: 2,3-3,7×; novembro: 1,6-2,5×).",
        "",
        "| Mês | Lead | Denom. mínimo (mm) | Razão mediana | Razão min-max | N |",
        "|---|---|---|---|---|---|",
    ]
    for c in razao['celulas_risco_sistematico_acima_do_piso']:
        linhas.append(f"| {NOMES_MES[c['mes']-1]} | H{c['lead']} | {_fmt(c['denom_min'])} | "
                       f"{_fmt(c['razao_mediana'], 2)} | {_fmt(c['razao_min'], 2)}-"
                       f"{_fmt(c['razao_max'], 2)} | {c['n']} |")

    linhas += [
        "",
        "**Implicação para a implementação futura do Método 3.2**: um piso baseado só na "
        "magnitude do denominador NÃO protege contra esse risco — outubro passa pelo piso "
        "de 10mm sem ser excluído, mas pediria um fator multiplicativo de ~5-7× baseado em "
        "só ~10 pontos históricos por lead, risco real de overfitting (protocolo, Seção 4, "
        "item 1: seleção/ajuste de parâmetro com amostra pequena). Isso deve ser avaliado "
        "explicitamente quando o Método 3.2 for implementado — por exemplo, reportando "
        "outubro separadamente na matriz mês×lead (diagnóstico de heterogeneidade, nunca "
        "removido silenciosamente) e considerando se um teto na razão (Seção 6) é também "
        "necessário, não só um piso no denominador.",
        "",
        "## 6. Regra para impedir previsão negativa ou explosiva",
        "",
        f"- Climatologia observada causal <= 0 em {risco['climatologia_observada_nao_positiva_n']} "
        f"casos; climatologia do modelo bruto causal <= 0 em "
        f"{risco['climatologia_modelo_raw_nao_positiva_n']} casos; forecast_raw negativo em "
        f"{risco['forecast_raw_negativo_n']} casos.",
        f"- **{'A razão PODE ser negativa nesta amostra — regra adicional necessária.' if risco['razao_pode_ser_negativa'] else 'A razão NUNCA pode ser negativa nesta amostra — precipitação é sempre >= 0 em ambas as climatologias causais e no forecast_raw, confirmado programaticamente.'}**",
        f"- Após aplicar o piso proposto, a razão varia entre {_fmt(risco['razao_minima_apos_piso'], 3)}× "
        f"e {_fmt(risco['razao_maxima_apos_piso'], 3)}× — **o risco real remanescente é "
        "EXPLOSIVO/sistemático (Seção 5.2), não negativo**.",
        "- Regra proposta para a implementação futura: `status_multiplicativo = "
        "'denominador_abaixo_do_piso'` quando `climatologia_modelo_raw < 10mm` — exclusão "
        "da avaliação multiplicativa principal, SEM fallback automático para a correção "
        "aditiva (isso criaria um método híbrido aditivo/multiplicativo, dificultando saber "
        "qual método produziu o resultado — uma versão híbrida pode ser avaliada "
        "posteriormente como método SEPARADO, se houver justificativa, nunca implícita).",
        "",
        "## 7. Confirmação de que nenhum skill multiplicativo foi calculado",
        "",
        f"- `nenhum_skill_multiplicativo_calculado`: {resultados['nenhum_skill_multiplicativo_calculado']}.",
        f"- `nenhum_forecast_calibrado_multiplicativo_calculado`: "
        f"{resultados['nenhum_forecast_calibrado_multiplicativo_calculado']}.",
        "- Esta atividade analisou só a distribuição de duas climatologias causais já "
        "aprovadas (`climatologia_observada`, `climatologia_modelo_raw`) e sua razão — "
        "nenhum `forecast_calibrado = forecast_raw × razão` foi computado, nenhum RMSE, "
        "MAE, correlação de anomalia, skill ou IC do método multiplicativo foi calculado.",
        "- `data/cfsv2_calibracao_2c3d/aditiva_expanding.csv` (Método 3.1, aprovado) foi só "
        "lido, nunca alterado.",
        "",
        "## Próximos passos (fora do escopo desta atividade)",
        "",
        "1. Revisão deste diagnóstico e do piso proposto (10mm).",
        "2. Implementação do Método 3.2 em si: `forecast_calibrado = forecast_raw × razão`, "
        "com `status_multiplicativo='denominador_abaixo_do_piso'` para `climatologia_"
        "modelo_raw < 10mm`, reaproveitando integralmente o desenho da Seção 0.",
        "3. Avaliação explícita do achado da Seção 5.2 (outubro e, em menor grau, maio e "
        "novembro) na matriz mês×lead da implementação — nunca escondida.",
        "4. Só depois disso, calcular os três skills e os ICs do Método 3.2 — nunca antes "
        "de fixar o piso.",
    ]
    return '\n'.join(linhas) + '\n'


def gerar_e_escrever():
    resultados = json.loads(d.CAMINHO_DIAGNOSTICO_JSON.read_text())
    relatorio = gerar_relatorio_markdown(resultados)
    d.RELATORIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    d.RELATORIO_PATH.write_text(relatorio)
    print(f"  ✅ {d.RELATORIO_PATH.relative_to(ROOT)}")
    return relatorio


if __name__ == '__main__':
    gerar_e_escrever()
