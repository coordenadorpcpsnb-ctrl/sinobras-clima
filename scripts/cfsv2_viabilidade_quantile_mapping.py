#!/usr/bin/env python3
"""
cfsv2_viabilidade_quantile_mapping.py — Fase 2C.3D: GATE DE VIABILIDADE
do Método 3.3 (quantile mapping), condicionado aos Métodos 3.1/3.2 já
aprovados e mergeados (`main`, commit 0209cf5). NUNCA implementa
quantile mapping nesta atividade — nenhum forecast calibrado por QM,
nenhum RMSE/MAE/skill/IC do Método 3.3 é calculado aqui. O único
objetivo é responder, programaticamente, se o método é EXECUTÁVEL sob
as regras já pré-registradas (AMOSTRA_MINIMA_ESTRATO=20).

Restrição estrutural (item 1 do pedido): o CFSv2 histórico aprovado
(`data/nmme_historico_fazendas/`) tem 240 inicializações FIXAS,
jan/1991-dez/2010 (20 anos) — não é um dataset que cresce com o
calendário, é o hindcast já extraído e aprovado na Fase 2C.3C. A
calibração é causal e específica por (lead, mês-alvo); como cada mês-
alvo corresponde a um único mês de inicialização por lead (mês-alvo =
mês de inicialização + lead - 1), cada célula tem EXATAMENTE 1
inicialização por ano — logo, no máximo 20 observações totais por
célula, e no máximo 19 estritamente anteriores à última (causal nunca
inclui a própria avaliada).

Item 3 do pedido — NADA disto é tentado aqui para contornar o limite:
nenhum pooling entre meses/leads, nenhuma redução do limiar de 20,
nenhuma interpolação de quantis com N<20, nenhum uso de LOYO como
substituto da avaliação causal, nenhum uso de 1981-1990 (CFSv2 não
existe nesse período), nenhum random split, e os 24 membros do
ensemble NUNCA são tratados como 24 anos independentes —
`construir_indice_inits_unicos` deduplica para 1 linha por
(init_date, lead) antes de qualquer contagem.

Roda com:
    python scripts/cfsv2_viabilidade_quantile_mapping.py --executar
    python scripts/cfsv2_viabilidade_quantile_mapping.py --gerar-relatorio
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import cfsv2_validacao_cientifica as v  # noqa: E402
import cfsv2_calibracao_aditiva as a  # noqa: E402

DIRETORIO_SAIDA = a.DIRETORIO_SAIDA
CAMINHO_METRICAS_JSON = DIRETORIO_SAIDA / 'viabilidade_quantile_mapping.json'
RELATORIO_PATH = ROOT / 'docs' / 'nmme-fase2c3d-viabilidade-quantile-mapping.md'

# Limiar PRÉ-REGISTRADO no protocolo da 2C.3D — o MESMO AMOSTRA_MINIMA_
# ESTRATO já usado em toda a Fase 2C.3C/2C.3D para avisos de amostra
# pequena, reaproveitado aqui como critério de viabilidade do quantile
# mapping (nunca um número novo, nunca reduzido depois de ver os
# resultados dos Métodos 3.1/3.2).
LIMIAR_MINIMO_QUANTILE_MAPPING = v.AMOSTRA_MINIMA_ESTRATO

STATUS_TESTAVEL = 'testavel'
STATUS_NAO_TESTAVEL = 'nao_testavel_amostra_insuficiente'

NOMES_MES = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']


def construir_indice_inits_unicos(base_pareada):
    """Item 3 do pedido — NUNCA usar os 24 membros do ensemble como 24
    observações climatológicas independentes: deduplica para 1 linha
    por (init_date, lead) ANTES de qualquer contagem de N. Se o
    pareamento tiver mais de uma linha por (init_date, lead) com
    target_mes/target_ano divergentes, isso seria um bug no pareamento
    em si (nunca escondido aqui)."""
    idx = base_pareada[['init_date', 'target_month', 'target_ano', 'target_mes', 'lead']
                        ].drop_duplicates().reset_index(drop=True)
    return idx


def calcular_n_causal_por_previsao(indice):
    """Para cada (lead, mês-alvo), ordena as inicializações no tempo e
    atribui n_treino_causal = nº de inicializações ESTRITAMENTE
    anteriores na MESMA célula (posição 0-indexada na ordem
    cronológica) — mesma lógica de warm-up dos Métodos 3.1/3.2, nunca
    pooling entre meses ou leads. A própria inicialização NUNCA conta
    para seu próprio n_treino_causal, por construção (a posição 0 é a
    primeira, com histórico vazio)."""
    linhas = []
    for (lead, mes_alvo), grupo in indice.groupby(['lead', 'target_mes']):
        grupo_ordenado = grupo.assign(
            _p=pd.PeriodIndex(grupo['init_date'], freq='M')).sort_values('_p')
        for posicao, (_, row) in enumerate(grupo_ordenado.iterrows()):
            linhas.append({
                'init_date': row['init_date'], 'lead': int(lead), 'target_mes': int(mes_alvo),
                'target_ano': int(row['target_ano']), 'n_treino_causal': posicao,
            })
    return pd.DataFrame(linhas)


def calcular_n_loyo_por_celula(indice):
    """Item 4 do pedido — SÓ diagnóstico de viabilidade (contexto),
    NUNCA usado para declarar o método testável se o causal não
    atingir o mínimo. LOYO exclui somente o próprio ano (usa passado E
    futuro) — n_treino_loyo = N_total_da_célula - 1, uniforme dentro de
    cada célula (não varia por posição cronológica, diferente do
    causal)."""
    contagens = indice.groupby(['lead', 'target_mes']).size()
    return {(int(lead), int(mes)): int(n - 1) for (lead, mes), n in contagens.items()}


def avaliar_viabilidade(tabela_n_causal, n_loyo_por_celula):
    """Item 2 do pedido — avaliação formal, sem calcular NENHUM
    skill/RMSE/MAE/IC do Método 3.3. Decisão automática: testável
    somente se pelo menos UMA previsão real atingir n_treino_causal >=
    LIMIAR_MINIMO_QUANTILE_MAPPING."""
    maximo_por_celula = tabela_n_causal.groupby(['lead', 'target_mes'])['n_treino_causal'].max()
    n_total_por_celula = tabela_n_causal.groupby(['lead', 'target_mes']).size()

    n_previsoes_total = len(tabela_n_causal)
    n_previsoes_com_minimo = int((tabela_n_causal['n_treino_causal']
                                   >= LIMIAR_MINIMO_QUANTILE_MAPPING).sum())
    n_celulas_com_minimo = int((maximo_por_celula >= LIMIAR_MINIMO_QUANTILE_MAPPING).sum())
    n_celulas_total = len(maximo_por_celula)
    maximo_geral_observado = int(maximo_por_celula.max())
    minimo_geral_do_maximo = int(maximo_por_celula.min())
    valores_distintos_do_maximo_por_celula = sorted(set(int(x) for x in maximo_por_celula.unique()))

    distribuicao_n_treino_causal = {
        int(n): int(c) for n, c in tabela_n_causal['n_treino_causal'].value_counts().sort_index().items()
    }

    testavel = n_previsoes_com_minimo > 0
    status = STATUS_TESTAVEL if testavel else STATUS_NAO_TESTAVEL

    deficit_anos = LIMIAR_MINIMO_QUANTILE_MAPPING + 1 - int(n_total_por_celula.max())
    deficit_texto = ('falta 1 ano' if deficit_anos == 1 else f'faltam {deficit_anos} anos')
    primeiro_ano_elegivel = None
    nota_primeiro_ano_elegivel = (
        "não aplicável — nenhuma previsão real atinge o limiar nesta base histórica fixa "
        f"(1991-2010, {int(n_total_por_celula.max())} anos/célula). Hipoteticamente, SE o "
        f"hindcast tivesse {LIMIAR_MINIMO_QUANTILE_MAPPING + 1} anos numa célula ({deficit_texto} "
        f"além dos {int(n_total_por_celula.max())} disponíveis), a "
        f"{LIMIAR_MINIMO_QUANTILE_MAPPING + 1}ª inicialização cronológica daquela célula seria "
        "a primeira elegível — mas essa inicialização NÃO existe na base aprovada; não é uma "
        "projeção de calendário (a base é um hindcast fixo, não um fluxo que cresce com o "
        "tempo presente).")

    por_celula_loyo = {f'H{lead}_mes{mes:02d}': n for (lead, mes), n in n_loyo_por_celula.items()}
    maximo_loyo_geral = max(n_loyo_por_celula.values()) if n_loyo_por_celula else None
    n_celulas_loyo_com_minimo = sum(1 for n in n_loyo_por_celula.values()
                                     if n >= LIMIAR_MINIMO_QUANTILE_MAPPING)

    return {
        'limiar_minimo_quantile_mapping': LIMIAR_MINIMO_QUANTILE_MAPPING,
        'n_previsoes_total_avaliadas': n_previsoes_total,
        'n_celulas_total': n_celulas_total,
        'maximo_n_causal_observado_geral': maximo_geral_observado,
        'minimo_do_maximo_n_causal_por_celula': minimo_geral_do_maximo,
        'valores_distintos_do_maximo_por_celula': valores_distintos_do_maximo_por_celula,
        'nota_maximo_uniforme': (
            'todas as células têm o MESMO máximo de N causal (a lista acima tem um único '
            'valor) — estrutural, não um achado de uma célula específica: cada célula tem '
            'exatamente 1 inicialização por ano, então a posição cronológica da última '
            'inicialização determina o máximo igualmente em toda célula.'
            if len(valores_distintos_do_maximo_por_celula) == 1 else
            'as células têm máximos DIFERENTES — investigar antes de prosseguir, pois a '
            'estrutura 1-init-por-ano-por-célula previa um valor uniforme.'),
        'distribuicao_n_treino_causal_geral': distribuicao_n_treino_causal,
        'n_previsoes_com_n_maior_igual_limiar': n_previsoes_com_minimo,
        'n_celulas_com_n_maior_igual_limiar': n_celulas_com_minimo,
        'primeiro_ano_elegivel': primeiro_ano_elegivel,
        'nota_primeiro_ano_elegivel': nota_primeiro_ano_elegivel,
        'periodo_avaliavel_restante': (
            'nenhum — toda a amostra causal disponível (240 inicializações × 6 leads) foi '
            'esgotada sem nenhuma previsão atingir o limiar; não há período adicional a '
            'esperar dentro da base de hindcast aprovada.' if not testavel else
            f'{n_previsoes_com_minimo} previsões elegíveis — ver matriz por célula no '
            'relatório.'),
        'loyo_contexto': {
            'nota': 'SÓ diagnóstico de viabilidade — NUNCA usado para declarar o método '
                    'testável se o causal não atingir o mínimo (item 4 do pedido). LOYO '
                    'exclui só o próprio ano, logo n_treino_loyo é uniforme por célula '
                    '(= N_total_da_célula - 1), não cresce com o tempo como o causal.',
            'maximo_n_loyo_geral': maximo_loyo_geral,
            'n_celulas_loyo_com_n_maior_igual_limiar': n_celulas_loyo_com_minimo,
            'por_celula': por_celula_loyo,
        },
        'metodo_3_3_status': status,
        'metodo_3_3_testavel': testavel,
        'nenhum_skill_ou_forecast_calibrado_calculado': True,
    }


def _verificar_dedup_nao_inflou_nem_perdeu(base_pareada, indice):
    """Checagem defensiva — item 3/7 do pedido: o índice deduplicado
    tem que ter EXATAMENTE N_INICIALIZACOES_ESPERADO × len(LEADS_
    ESPERADOS) linhas, nunca mais (ensemble inflando) nem menos
    (pareamento quebrado)."""
    esperado = v.N_INICIALIZACOES_ESPERADO * len(v.LEADS_ESPERADOS)
    return {'ok': len(indice) == esperado, 'n_indice': len(indice), 'n_esperado': esperado,
            'n_linhas_base_pareada_original': len(base_pareada)}


def executar_viabilidade():
    auditoria = v.executar_auditoria()
    if not auditoria['auditoria_aprovada']:
        return {'STOP_ON_FAILURE': True,
                'motivo': 'auditoria da base RAW (2C.3C) reprovada'}

    df_raw = v.carregar_cfsv2_raw()
    chirps_df = v.carregar_chirps_v3_historico()
    base = v.construir_base_pareada(df_raw, chirps_df)
    if not v.validar_nenhum_mes_alvo_ausente(base):
        return {'STOP_ON_FAILURE': True, 'motivo': 'pareamento com mês-alvo ausente'}

    indice = construir_indice_inits_unicos(base)
    dedup_check = _verificar_dedup_nao_inflou_nem_perdeu(base, indice)
    if not dedup_check['ok']:
        return {'STOP_ON_FAILURE': True,
                'motivo': 'deduplicação de membros do ensemble produziu contagem inesperada — '
                          'risco de N inflado ou pareamento quebrado', 'detalhe': dedup_check}

    tabela_n_causal = calcular_n_causal_por_previsao(indice)
    if len(tabela_n_causal) != len(indice):
        return {'STOP_ON_FAILURE': True,
                'motivo': 'contagem causal produziu número de linhas diferente do índice '
                          'deduplicado'}

    n_loyo_por_celula = calcular_n_loyo_por_celula(indice)
    avaliacao = avaliar_viabilidade(tabela_n_causal, n_loyo_por_celula)

    matriz_max_por_celula = {}
    maximo_series = tabela_n_causal.groupby(['lead', 'target_mes'])['n_treino_causal'].max()
    for (lead, mes), maximo in maximo_series.items():
        matriz_max_por_celula.setdefault(int(lead), {})[int(mes)] = int(maximo)

    resultado = {
        'STOP_ON_FAILURE': False,
        'metodo': 'gate_de_viabilidade_quantile_mapping_metodo_3_3',
        'dedup_ensemble_check': dedup_check,
        'avaliacao': avaliacao,
        'matriz_maximo_n_causal_por_celula': matriz_max_por_celula,
        'proximo_metodo_elegivel_se_inviavel': 'metodo_3_4_regressao_linear_mos_simples',
        'data_geracao_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    return resultado


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--executar', action='store_true')
    ap.add_argument('--gerar-relatorio', action='store_true')
    args = ap.parse_args()

    if args.executar:
        resultado = executar_viabilidade()
        DIRETORIO_SAIDA.mkdir(parents=True, exist_ok=True)
        CAMINHO_METRICAS_JSON.write_text(
            json.dumps(resultado, indent=2, ensure_ascii=False, default=str))
        print(f"  ✅ {CAMINHO_METRICAS_JSON.relative_to(ROOT)}")
        if resultado.get('STOP_ON_FAILURE'):
            print(f"\n❌ STOP_ON_FAILURE: {resultado.get('motivo')}")
            return
        print(f"  metodo_3_3_status = {resultado['avaliacao']['metodo_3_3_status']}")
        return

    if args.gerar_relatorio:
        import cfsv2_relatorio_viabilidade_qm as rel
        rel.gerar_e_escrever()
        return

    ap.print_help()


if __name__ == '__main__':
    main()
