#!/usr/bin/env python3
"""
cfsv2_diagnostico_multiplicativo.py — Fase 2C.3D, diagnóstico PRÉVIO ao
Método 3.2 (correção multiplicativa). NUNCA calcula forecast_calibrado
multiplicativo, razão aplicada a uma previsão real, nem nenhum
skill/RMSE do método multiplicativo — só analisa a distribuição dos
dois ingredientes já aprovados do benchmark_anomalia_reconstruida
(`climatologia_observada`, `climatologia_modelo_raw`, ambas causais,
já presentes em `data/cfsv2_calibracao_2c3d/aditiva_expanding.csv`,
APROVADO na Fase 2C.3D/Método 3.1 — lido aqui, nunca reescrito).

O objetivo é definir um piso de segurança para o denominador da razão
multiplicativa ANTES de qualquer implementação, usando só estabilidade
numérica/física — nunca escolhido observando qual piso produz melhor
skill (nenhum skill existe ainda nesta atividade).

Roda com:
    python scripts/cfsv2_diagnostico_multiplicativo.py --executar
    python scripts/cfsv2_diagnostico_multiplicativo.py --gerar-relatorio
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import cfsv2_validacao_cientifica as v  # noqa: E402
import cfsv2_calibracao_aditiva as a  # noqa: E402

CAMINHO_TABELA_ADITIVA_APROVADA = a.CAMINHO_TABELA_EXPANDING
CAMINHO_DIAGNOSTICO_JSON = a.DIRETORIO_SAIDA / 'diagnostico_multiplicativo.json'
RELATORIO_PATH = ROOT / 'docs' / 'nmme-fase2c3d-protocolo-multiplicativo-cfsv2.md'

# Piso PROPOSTO — ver justificativa no relatório (Seção 2). Faixa
# segura confirmada empiricamente (Seção 2): qualquer valor entre
# 7,27mm e 16,62mm separa os mesmos meses, sem fragmentar nenhum mês em
# nenhum lead. 10mm escolhido como número redondo dentro dessa faixa —
# NUNCA escolhido observando skill, porque nenhum skill foi calculado
# nesta atividade.
PISO_PROPOSTO_MM = 10.0

NOMES_MES = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']


def _stats(serie):
    """As 9 estatísticas pedidas — nunca um resumo diferente."""
    s = np.asarray(serie, dtype=float)
    return {
        'n': int(len(s)),
        'minimo': float(s.min()), 'p05': float(np.percentile(s, 5)),
        'p10': float(np.percentile(s, 10)), 'p25': float(np.percentile(s, 25)),
        'mediana': float(np.median(s)), 'media': float(s.mean()),
        'p75': float(np.percentile(s, 75)), 'p90': float(np.percentile(s, 90)),
        'maximo': float(s.max()),
    }


def carregar_base_elegivel():
    """Lê a tabela JÁ APROVADA do Método 3.1 (read-only) e restringe à
    população ELEGÍVEL (status_calibracao='ok', N=720=120×6 leads) —
    a MESMA população que o Método 3.2 usará (regra fixa do protocolo:
    'avaliação principal nos mesmos casos elegíveis do método
    aditivo'). climatologia_observada e climatologia_modelo_raw já são
    causais (herdadas da 2C.3C/climatologia_expansivel e
    climatologia_modelo_expansivel) — nunca recalculadas aqui."""
    df = pd.read_csv(CAMINHO_TABELA_ADITIVA_APROVADA)
    ok = df[df['status_calibracao'] == a.STATUS_OK].copy()
    ok['grupo_sazonal'] = ok['target_mes'].map(v.GRUPO_SAZONAL_POR_MES)
    ok['razao'] = ok['climatologia_observada'] / ok['climatologia_modelo_raw']
    return ok


def diagnosticar_denominador(ok):
    """Seção 1 do pedido — distribuição de média(forecast_raw_treino)
    (coluna `climatologia_modelo_raw`, o denominador da razão) por
    lead, mês e grupo sazonal.

    Chaves de mês/lead são sempre `str` aqui, não só depois de passar
    por `json.loads` — assim o dict em memória (devolvido por
    `executar_diagnostico()`, usado direto por quem testa ou chama a
    função sem gravar/reler o JSON) tem exatamente o mesmo formato do
    JSON gravado em disco. Sem isso, `gerar_relatorio_markdown` (que
    indexa por `str(mes)`/`str(lead)`) funciona só depois do
    round-trip por arquivo e quebra com `KeyError` em uso direto —
    achado ao testar a função isoladamente."""
    por_mes = {str(mes): _stats(ok[ok['target_mes'] == mes]['climatologia_modelo_raw'])
               for mes in range(1, 13)}
    por_lead = {str(int(lead)): _stats(ok[ok['lead'] == lead]['climatologia_modelo_raw'])
                for lead in v.LEADS_ESPERADOS}
    por_grupo = {grupo: _stats(ok[ok['grupo_sazonal'] == grupo]['climatologia_modelo_raw'])
                 for grupo in ('chuvosa', 'transicao', 'seca')}
    por_mes_lead = {}
    for mes in range(1, 13):
        por_mes_lead[str(mes)] = {}
        for lead in v.LEADS_ESPERADOS:
            sub = ok[(ok['target_mes'] == mes) & (ok['lead'] == lead)]['climatologia_modelo_raw']
            if len(sub) > 0:
                por_mes_lead[str(mes)][str(int(lead))] = {'min': float(sub.min()), 'max': float(sub.max())}
    return {'por_mes': por_mes, 'por_lead': por_lead, 'por_grupo_sazonal': por_grupo,
            'por_mes_e_lead_min_max': por_mes_lead}


def diagnosticar_razao(ok):
    """Seção 4 do pedido — distribuição das razões (climatologia_
    observada / climatologia_modelo_raw) por mês e lead — PURAMENTE
    DESCRITIVO, nunca um skill (razão não é uma previsão calibrada)."""
    por_mes = {str(mes): _stats(ok[ok['target_mes'] == mes]['razao']) for mes in range(1, 13)}
    por_grupo = {grupo: _stats(ok[ok['grupo_sazonal'] == grupo]['razao'])
                 for grupo in ('chuvosa', 'transicao', 'seca')}
    # células (mês, lead) com razão mediana alta mesmo SEM denominador
    # pequeno — achado específico (Seção 5), distinto do risco de
    # denominador instável.
    celulas_risco_sistematico = []
    for mes in range(1, 13):
        for lead in v.LEADS_ESPERADOS:
            sub = ok[(ok['target_mes'] == mes) & (ok['lead'] == lead)]
            if len(sub) == 0:
                continue
            denom_min = sub['climatologia_modelo_raw'].min()
            razao_mediana = sub['razao'].median()
            if denom_min >= PISO_PROPOSTO_MM and razao_mediana > 1.5:
                celulas_risco_sistematico.append({
                    'mes': mes, 'lead': int(lead), 'denom_min': float(denom_min),
                    'razao_mediana': float(razao_mediana), 'razao_min': float(sub['razao'].min()),
                    'razao_max': float(sub['razao'].max()), 'n': int(len(sub)),
                })
    celulas_risco_sistematico.sort(key=lambda d: -d['razao_mediana'])
    return {'por_mes': por_mes, 'por_grupo_sazonal': por_grupo,
            'celulas_risco_sistematico_acima_do_piso': celulas_risco_sistematico}


def avaliar_candidatos_piso(ok):
    """Seção 3 do pedido — quantos casos seriam excluídos em cada piso
    candidato, e confirmação de que o piso proposto (10mm) separa meses
    inteiros sem fragmentar nenhum (lead, mês) — nunca escolhido
    observando skill."""
    candidatos = [0.5, 1, 2, 3, 5, 10, 15, 20, 30]
    resultado = {}
    for piso in candidatos:
        n_exc = int((ok['climatologia_modelo_raw'] < piso).sum())
        resultado[str(piso)] = {'n_excluido': n_exc, 'pct_excluido': round(100 * n_exc / len(ok), 1)}

    # confirmação da separação limpa por mês (nenhuma sobreposição
    # entre o grupo abaixo e acima do piso proposto, em NENHUM lead)
    piv = ok.groupby(['target_mes', 'lead'])['climatologia_modelo_raw'].agg(['min', 'max']).reset_index()
    meses_abaixo = sorted(piv[piv['max'] < PISO_PROPOSTO_MM]['target_mes'].unique().tolist())
    meses_acima = sorted(piv[piv['min'] >= PISO_PROPOSTO_MM]['target_mes'].unique().tolist())
    meses_mistos = sorted(set(range(1, 13)) - set(meses_abaixo) - set(meses_acima))
    maior_abaixo = float(piv[piv['target_mes'].isin(meses_abaixo)]['max'].max()) if meses_abaixo else None
    menor_acima = float(piv[piv['target_mes'].isin(meses_acima)]['min'].min()) if meses_acima else None

    return {
        'candidatos': resultado,
        'piso_proposto_mm': PISO_PROPOSTO_MM,
        'n_excluido_no_piso_proposto': int((ok['climatologia_modelo_raw'] < PISO_PROPOSTO_MM).sum()),
        'meses_inteiramente_abaixo_do_piso': meses_abaixo,
        'meses_inteiramente_acima_do_piso': meses_acima,
        'meses_fragmentados_pelo_piso': meses_mistos,
        'maior_denominador_entre_os_meses_abaixo': maior_abaixo,
        'menor_denominador_entre_os_meses_acima': menor_acima,
        'gap_seguro_mm': ([maior_abaixo, menor_acima] if maior_abaixo is not None
                           and menor_acima is not None else None),
        'nota': 'O piso proposto cai dentro de um GAP vazio — nenhum (lead,mês) tem '
                'denominador nesse intervalo — confirmando que a escolha não corta nenhum '
                'mês pela metade em nenhum lead.',
    }


def verificar_risco_negativo_ou_explosivo(ok):
    """Seção 6 do pedido — a razão só pode ser negativa se uma das
    climatologias causais fosse negativa; precipitação nunca é
    negativa, então isso é verificado programaticamente, nunca
    assumido."""
    n_obs_nao_positiva = int((ok['climatologia_observada'] <= 0).sum())
    n_modelo_nao_positiva = int((ok['climatologia_modelo_raw'] <= 0).sum())
    n_forecast_raw_negativo = int((ok['forecast_raw'] < 0).sum())
    restante = ok[ok['climatologia_modelo_raw'] >= PISO_PROPOSTO_MM]
    return {
        'climatologia_observada_nao_positiva_n': n_obs_nao_positiva,
        'climatologia_modelo_raw_nao_positiva_n': n_modelo_nao_positiva,
        'forecast_raw_negativo_n': n_forecast_raw_negativo,
        'razao_pode_ser_negativa': bool(n_obs_nao_positiva > 0 or n_modelo_nao_positiva > 0),
        'razao_minima_apos_piso': float(restante['razao'].min()),
        'razao_maxima_apos_piso': float(restante['razao'].max()),
        'nota': 'Nenhuma climatologia causal observada na amostra é <= 0 e nenhum '
                'forecast_raw é negativo — a razão nunca pode ser negativa nesta amostra. '
                'O risco real, mesmo após o piso, é EXPLOSIVO/sistemático (ver células de '
                'risco sistemático), não negativo.',
    }


def executar_diagnostico():
    ok = carregar_base_elegivel()
    resultado = {
        'metodo': 'diagnostico_previo_metodo_3_2_correcao_multiplicativa',
        'nenhum_skill_multiplicativo_calculado': True,
        'nenhum_forecast_calibrado_multiplicativo_calculado': True,
        'n_total_elegivel_metodo_aditivo': int(len(ok)),
        'piso_proposto_mm': PISO_PROPOSTO_MM,
        'diagnostico_denominador': diagnosticar_denominador(ok),
        'diagnostico_razao': diagnosticar_razao(ok),
        'avaliacao_candidatos_piso': avaliar_candidatos_piso(ok),
        'risco_negativo_ou_explosivo': verificar_risco_negativo_ou_explosivo(ok),
        'data_geracao_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    return resultado


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--executar', action='store_true')
    ap.add_argument('--gerar-relatorio', action='store_true')
    args = ap.parse_args()

    if args.executar:
        resultado = executar_diagnostico()
        a.DIRETORIO_SAIDA.mkdir(parents=True, exist_ok=True)
        CAMINHO_DIAGNOSTICO_JSON.write_text(
            json.dumps(resultado, indent=2, ensure_ascii=False, default=str))
        print(f"  ✅ {CAMINHO_DIAGNOSTICO_JSON.relative_to(ROOT)}")
        return

    if args.gerar_relatorio:
        import cfsv2_relatorio_diagnostico_multiplicativo as rel
        rel.gerar_e_escrever()
        return

    ap.print_help()


if __name__ == '__main__':
    main()
