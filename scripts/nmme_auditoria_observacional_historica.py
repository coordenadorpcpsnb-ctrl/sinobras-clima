#!/usr/bin/env python3
"""
nmme_auditoria_observacional_historica.py — Fase 2C.2, validação
científica da referência observacional para a extração histórica CFSv2
do centroide das fazendas.

Contexto: a extração histórica (scripts/nmme_extracao_historica.py,
localização Fazendas_Sinobras_Centroide) rodou de verdade e foi
consolidada como aprovada — GitHub Actions run 36238169299,
240/240 inicializações aprovadas, 34.560 registros RAW, nenhuma
pendência (`extracao_completa_e_aprovada=true`). Este módulo NÃO
executa nenhuma consulta nova ao CFSv2 — só AUDITA a referência
observacional (data/serie_subst.csv) contra o que já foi extraído, e
propõe (em prosa, no relatório) um protocolo estatístico para uma
FUTURA avaliação de skill — que este módulo, deliberadamente, NUNCA
calcula.

Reaproveita, sem modificar o comportamento existente:
- `nmme_piloto_historico.verificar_cobertura_observacional` — mesma
  classificação de 3 eixos (disponibilidade/procedência documental/
  qualidade efetivamente verificada) já usada no piloto de 16 origens,
  agora sobre as 240 origens × 6 leads da extração completa.
- `nmme_piloto_historico.avaliar_aptidao_referencia_observacional` —
  ganhou parâmetros aditivos `distancia_km`/`ponto_descricao` (default
  preserva o comportamento original para São Bento) para poder receber
  a distância REAL do centroide das fazendas até a grade do CFSv2
  (lida diretamente do RAW persistido e aprovado, nunca resuposta).
- `nmme_extracao_historica.ORIGENS_HISTORICAS`/`ANO_FIM_MERRA2` — os
  mesmos 240 pares (ano, mês) e o mesmo limiar MERRA-2/Sinobras já
  usados em todo o resto do projeto.

Nunca calcula skill (nenhuma métrica de erro entre previsão e
observação), nunca modifica o dashboard, nunca altera os modelos
climáticos (SARIMAX/XGBoost) — só lê dados já existentes e escreve um
relatório técnico + tabelas de auditoria em
artifacts/nmme_auditoria_observacional_historica/.

Roda com:
    python scripts/nmme_auditoria_observacional_historica.py --dry-run-plan
    python scripts/nmme_auditoria_observacional_historica.py --gerar-relatorio
"""

import argparse
import glob
import io
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import nmme_extracao_historica as ext  # noqa: E402
import nmme_piloto_historico as pilo  # noqa: E402
import nmme_processar as nproc  # noqa: E402

ARTIFACTS_DIR = ROOT / 'artifacts' / 'nmme_auditoria_observacional_historica'

SERIE_OBSERVACIONAL_PATH = pilo.SERIE_OBSERVACIONAL_PATH
MASTER_MONTHLY_PATH = ROOT / 'data' / 'master_monthly.csv'
UPDATE_DASHBOARD_PATH = ROOT / 'scripts' / 'update_dashboard.py'

# Evidência formal da extração histórica aprovada (item citado nesta
# auditoria, nunca recalculado aqui) — run real, verificado via GitHub
# Actions antes de iniciar esta tarefa.
EVIDENCIA_EXTRACAO_HISTORICA_FAZENDAS = {
    'run_id': 36238169299,
    'workflow': 'nmme_extracao_historica.yml (--consolidar --localizacao fazendas)',
    'n_origens_aprovadas_total': 240, 'n_raw_total': 34560,
    'extracao_completa_e_aprovada': True,
}

# Nova evidência recebida (3ª rodada) — SINOBRAS.csv, registros
# mensais individualizados por fazenda, 1996-2025. Auditada de forma
# INDEPENDENTE por scripts/nmme_auditoria_sinobras_por_fazenda.py
# (rotina separada, nunca reimplementada aqui) — estes são os achados
# JÁ VERIFICADOS por aquele módulo nesta sessão (mesmo padrão de
# EVIDENCIA_EXTRACAO_HISTORICA_FAZENDAS acima: um fato formal citado,
# não recalculado dentro deste módulo). O arquivo original NÃO foi
# incorporado a este repositório — o relatório completo e reprodutível
# (com a tabela de reconciliação mês a mês) fica em
# docs/nmme-fase2c2-auditoria-sinobras-por-fazenda.md.
EVIDENCIA_SINOBRAS_POR_FAZENDA = {
    'arquivo': 'SINOBRAS.csv',
    'sha256': 'ad44fa16d9bdba16fb6550ab1ff3eabaefdbc6dfffee0a6afc19e6c5a931ca1a',
    'periodo_coberto_inicio': '1996-01', 'periodo_coberto_fim': '2025-12',
    'n_registros': 12240, 'n_identificadores': 34,
    'n_series_mensais_distintas': 27,
    'grupos_de_series_identicas': [
        ['FAZ02', 'FAZ03', 'FAZ04', 'FAZ05', 'FAZ08', 'FAZ09', 'FAZ19'],
        ['FAZ07', 'FAZ15'],
    ],
    'integridade_estrutural_completa': True,
    'reconciliacao_com_serie_producao_completa': True,
    'relatorio_completo': 'docs/nmme-fase2c2-auditoria-sinobras-por-fazenda.md',
    'script_auditoria': 'scripts/nmme_auditoria_sinobras_por_fazenda.py',
}

ANO_FIM_MERRA2 = pilo.ANO_FIM_MERRA2   # 1995 — README.md
ORIGENS_HISTORICAS = ext.ORIGENS_HISTORICAS   # 240 pares (ano, mês), 1991-2010

# Padrão de agregação das leituras de campo Sinobras, tal como escrito
# em scripts/update_dashboard.py — verificado por leitura de código
# (nunca assumido do README): média aritmética simples por (ano, mês)
# sobre as linhas presentes no arquivo enviado naquele mês, SEM exigir
# um número mínimo de estações/fazendas reportando e SEM reter a
# leitura por estação individual em data/serie_subst.csv (só a média
# sobrevive).
PADRAO_AGREGACAO_SINOBRAS = "df_new.groupby(['ano','mes'])['prec_mm'].mean()"


# ══════════════════════════════════════════════════════════════════════════
# Item 1 — cobertura da série observacional para o período 1991-2010 + H1-H6
# ══════════════════════════════════════════════════════════════════════════

def periodo_alvo_completo(origens=ORIGENS_HISTORICAS, leads=pilo.npoc.LEADS):
    """O período que a série observacional PRECISA cobrir não é só
    1991-2010 (as inicializações), mas até o H6 da última inicialização
    (2010-12) — item 1 da tarefa: "incluindo os meses previstos que
    ultrapassem dezembro de 2010". Reaproveita `nproc.
    leadtime_para_mes_alvo_nmme` (mesma função usada por
    `verificar_cobertura_observacional`) para nunca ter uma segunda
    fórmula de mapeamento H-lead → mês-alvo."""
    ultimo_ano, ultimo_mes = max(origens)
    init_date = pd.Period(f'{ultimo_ano}-{ultimo_mes:02d}', 'M')
    ultimo_alvo = max(nproc.leadtime_para_mes_alvo_nmme(init_date, lead, 'lead1_igual_mes_inicializacao')
                        for lead in leads)
    primeiro_ano, primeiro_mes = min(origens)
    primeiro_alvo = pd.Period(f'{primeiro_ano}-{primeiro_mes:02d}', 'M')
    return primeiro_alvo, ultimo_alvo


def verificar_cobertura_calendario_bruta(serie_df=None):
    """Item 1 — audita a série DIRETAMENTE pelo calendário (não pela
    lente de origem×lead de `verificar_cobertura_observacional`): todo
    mês do período alvo completo deve aparecer EXATAMENTE 1 vez, sem
    lacuna e sem duplicata. Complementar, não substitui, a verificação
    por origem×lead abaixo — uma lacuna pode existir mesmo quando
    nenhuma combinação origem×lead específica a expôs (ex.: lacuna fora
    do conjunto de meses-alvo do piloto de 240 origens, mas dentro do
    período nominal)."""
    if serie_df is None:
        serie_df = pd.read_csv(SERIE_OBSERVACIONAL_PATH)
    primeiro_alvo, ultimo_alvo = periodo_alvo_completo()
    esperados = pd.period_range(primeiro_alvo, ultimo_alvo, freq='M')

    periodos = pd.PeriodIndex(pd.to_datetime(
        serie_df[['ano', 'mes']].assign(dia=1).rename(columns={'dia': 'day', 'mes': 'month', 'ano': 'year'})),
        freq='M')
    contagem = periodos.value_counts()

    ausentes = [str(p) for p in esperados if contagem.get(p, 0) == 0]
    duplicados = [str(p) for p in esperados if contagem.get(p, 0) > 1]
    return {
        'periodo_alvo_inicio': str(primeiro_alvo), 'periodo_alvo_fim': str(ultimo_alvo),
        'n_meses_esperados': len(esperados),
        'meses_ausentes': ausentes, 'n_meses_ausentes': len(ausentes),
        'meses_duplicados': duplicados, 'n_meses_duplicados': len(duplicados),
        'cobertura_calendario_completa': not ausentes and not duplicados,
    }


def executar_auditoria_cobertura_por_origem_lead():
    """Reaproveita `nmme_piloto_historico.verificar_cobertura_
    observacional` SEM modificação — a função já aceita qualquer lista
    de origens com `ano`/`mes` (usada antes só com as 16 do piloto,
    aqui com as 240 da extração completa). Produz 1 linha por
    combinação origem×lead (240 × 6 = 1.440), com disponibilidade/
    procedência documental/qualidade verificada — nunca colapsados num
    único rótulo."""
    origens_minimas = [{'ano': ano, 'mes': mes} for ano, mes in ORIGENS_HISTORICAS]
    return pilo.verificar_cobertura_observacional(origens_minimas)


# ══════════════════════════════════════════════════════════════════════════
# Item 2 (2ª rodada) — combinações previsão×horizonte vs. observações
# mensais INDEPENDENTES — nunca a mesma coisa
# ══════════════════════════════════════════════════════════════════════════

def analisar_dependencia_temporal_observacoes(cobertura_df):
    """Item 2 (2ª rodada) — 1.440 combinações origem×lead NÃO são 1.440
    observações independentes: o mesmo mês observado é o alvo de várias
    combinações diferentes (uma origem de janeiro mirando lead 1 e uma
    origem de dezembro do ano anterior mirando lead 2 podem mirar o
    MESMO mês). Conta quantos meses DISTINTOS são realmente usados como
    alvo, e quantas vezes cada um é reaproveitado — nunca deixa isso
    implícito para uma futura estimativa de incerteza estatística, que
    precisa tratar essas combinações como dependentes, não como uma
    amostra i.i.d. de 1.440 pontos."""
    reuso = cobertura_df['target_month'].value_counts()
    return {
        'n_combinacoes_origem_lead': int(len(cobertura_df)),
        'n_meses_observados_distintos': int(len(reuso)),
        'razao_combinacoes_por_mes_distinto': round(len(cobertura_df) / len(reuso), 2) if len(reuso) else None,
        'reuso_por_mes_min': int(reuso.min()) if len(reuso) else None,
        'reuso_por_mes_max': int(reuso.max()) if len(reuso) else None,
        'reuso_por_mes_medio': round(float(reuso.mean()), 2) if len(reuso) else None,
        'reuso_por_mes_mediano': int(reuso.median()) if len(reuso) else None,
        'distribuicao_de_reuso': {int(k): int(v) for k, v in reuso.value_counts().sort_index().items()},
        'interpretacao': (
            f"{len(cobertura_df)} combinações origem×lead compartilham apenas "
            f"{len(reuso)} meses observados distintos — cada mês é reaproveitado como alvo, em "
            f"média, {round(len(cobertura_df) / len(reuso), 1) if len(reuso) else 0} vezes (a "
            "maioria dos meses centrais da janela é usada pelas 6 combinações possíveis: origem "
            "no próprio mês com H1, origem no mês anterior com H2, ..., origem 5 meses antes com "
            "H6). Uma futura estimativa de incerteza (intervalo de confiança, erro padrão) que "
            "tratasse as 1.440 combinações como observações independentes SUPERESTIMARIA o "
            "tamanho efetivo da amostra em até 6x — precisa considerar a dependência temporal "
            "(mesmo mês observado citado por várias previsões, além da autocorrelação natural "
            "da precipitação mês a mês) antes de qualquer cálculo de significância."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Item 2 (numeração original da tarefa 1) — separar MERRA-2 de Estação Sinobras
# ══════════════════════════════════════════════════════════════════════════

def resumir_por_procedencia(cobertura_df):
    """Item 2/6 — contagem de combinações origem×lead por procedência
    documental (a mesma coluna já calculada por
    `verificar_cobertura_observacional`, nunca uma nova classificação)."""
    resumo = (cobertura_df.groupby('procedencia_documental', dropna=False)
                .size().rename('n_combinacoes').reset_index()
                .sort_values('n_combinacoes', ascending=False))
    return resumo


def analisar_distribuicao_pre_1996(cobertura_df):
    """Item 4 (2ª rodada) — a 1ª versão deste relatório descrevia as
    345 combinações pré-1996 como "concentradas nos leads mais longos
    das origens de 1991", o que NUNCA foi checado contra os dados —
    corrigido aqui com a distribuição REAL, computada, não suposta:
    por ano-alvo, por ano de origem e por H_lead."""
    pre = cobertura_df[cobertura_df['procedencia_documental'].astype(str).str.contains(
        'MERRA-2', na=False)].copy()
    if not len(pre):
        return {'n_total': 0, 'por_ano_alvo': {}, 'por_ano_origem': {}, 'por_h_lead': {}}
    pre['ano_alvo'] = pre['target_month'].str.slice(0, 4)
    pre['ano_origem'] = pre['origem_piloto'].str.slice(0, 4)
    return {
        'n_total': int(len(pre)),
        'por_ano_alvo': pre['ano_alvo'].value_counts().sort_index().to_dict(),
        'por_ano_origem': pre['ano_origem'].value_counts().sort_index().to_dict(),
        'por_h_lead': {int(k): int(v) for k, v in pre['H_lead'].value_counts().sort_index().items()},
        'interpretacao': (
            "Distribuição real (não suposta): as 345 combinações pré-1996 estão razoavelmente "
            "distribuídas entre os 5 anos-alvo 1991-1995 (57 a 72 cada) e entre os 6 leads "
            "(55 a 60 cada) — NÃO concentradas nos leads mais longos das origens de 1991, como "
            "uma versão anterior deste relatório afirmava sem checar. A contagem menor em "
            "1991 (57) e 1995 (57) é só efeito de borda: origens de 1991 com lead alto ainda "
            "miram 1991-1992 (dentro da janela), e origens de 1995 com lead alto já miram 1996 "
            "(fora do trecho MERRA-2, contadas em 'Estação Sinobras')."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Item 3 — documentação efetivamente disponível (nunca só o README)
# ══════════════════════════════════════════════════════════════════════════

def verificar_identidade_merra2_com_master_monthly():
    """Item 3 — o README descreve o trecho pré-1996 como "MERRA-2", mas
    isso nunca foi verificado numericamente neste projeto. Aqui: compara
    `prec` de data/serie_subst.csv, ano a ano, com `prec_reg` de
    data/master_monthly.csv (média de 3 colunas nomeadas Araguaina/
    Colinas/Tocantinopolis — cuja origem/coordenadas NÃO têm nenhum
    script neste repositório que as gere ou documente: o arquivo já
    existia por completo no primeiro commit que o introduziu, "Create
    index.html", sem metodologia registrada).

    Revisão pontual (2ª rodada, item 1) — o que este cálculo PROVA e o
    que ele NÃO prova, sem misturar os dois: (a) prova que os NÚMEROS de
    serie_subst.csv (ano<=1995) e prec_reg de master_monthly.csv são
    idênticos — os dois arquivos guardam o mesmo valor; (b) NÃO prova
    que esse valor de fato veio do MERRA-2 — a única evidência de que é
    "MERRA-2" é o rótulo do README, e a igualdade numérica confirma
    apenas que as 3 colunas nomeadas (Araguaína/Colinas do Tocantins/
    Tocantinópolis) foram usadas para compor `prec`, nunca QUAL foi a
    fonte de dado que preencheu essas 3 colunas em primeiro lugar
    (poderia ser MERRA-2, poderia ser outra reanálise, poderia ser
    estação de superfície de cada cidade — nenhuma dessas hipóteses é
    verificável a partir deste repositório). `fonte_original_
    comprovada` fica sempre `False` por este motivo — nunca promovida a
    `True` só porque os números batem."""
    serie = pd.read_csv(SERIE_OBSERVACIONAL_PATH)
    if not MASTER_MONTHLY_PATH.exists():
        return {'comparavel': False, 'motivo': f'{MASTER_MONTHLY_PATH} não encontrado',
                'fonte_original_comprovada': False}
    master = pd.read_csv(MASTER_MONTHLY_PATH)
    if 'prec_reg' not in master.columns:
        return {'comparavel': False, 'motivo': "coluna 'prec_reg' não existe em master_monthly.csv",
                'fonte_original_comprovada': False}

    merged = serie.merge(master[['year', 'month', 'prec_reg']],
                          left_on=['ano', 'mes'], right_on=['year', 'month'], how='inner')
    pre = merged[merged['ano'] <= ANO_FIM_MERRA2].dropna(subset=['prec_reg'])
    pos = merged[merged['ano'] > ANO_FIM_MERRA2].dropna(subset=['prec_reg'])
    diff_pre = (pre['prec'] - pre['prec_reg']).abs()
    diff_pos = (pos['prec'] - pos['prec_reg']).abs()

    return {
        'comparavel': True,
        'n_meses_comparados_pre_1996': int(len(pre)),
        'diff_abs_maxima_pre_1996_mm': round(float(diff_pre.max()), 4) if len(diff_pre) else None,
        'identico_numericamente_pre_1996': bool(len(diff_pre) and diff_pre.max() < 0.01),
        'n_meses_comparados_pos_1996': int(len(pos)),
        'diff_abs_media_pos_1996_mm': round(float(diff_pos.mean()), 2) if len(diff_pos) else None,
        'diff_abs_maxima_pos_1996_mm': round(float(diff_pos.max()), 2) if len(diff_pos) else None,
        'diverge_pos_1996': bool(len(diff_pos) and diff_pos.mean() > 1.0),
        # Item 1 (2ª rodada) — SEMPRE False: igualdade numérica com uma
        # coluna rotulada "MERRA-2" não comprova que a fonte ORIGINAL
        # dessas 3 séries municipais seja de fato o MERRA-2.
        'fonte_original_comprovada': False,
        'interpretacao': (
            "O trecho 'MERRA-2' (ano<=1995) de serie_subst.csv é numericamente idêntico a "
            "prec_reg=média(Araguaína, Colinas do Tocantins, Tocantinópolis) de "
            "master_monthly.csv — isso é um FATO verificado. O que continua NÃO COMPROVADO é a "
            "fonte ORIGINAL dessas 3 séries municipais: a igualdade numérica só mostra que "
            "'prec' é a média dessas 3 colunas, nunca de onde elas vieram. O rótulo 'MERRA-2' "
            "do README é a única evidência disponível para essa origem, e não é verificável a "
            "partir deste repositório (nenhum script, coordenada ou registro de commit anterior "
            "documenta se são MERRA-2, outra reanálise, ou estações de superfície das 3 "
            "cidades). Tratar como 'MERRA-2 confirmado' seria uma afirmação não sustentada pelos "
            "dados disponíveis."
        ),
    }


def verificar_padrao_agregacao_sinobras_no_codigo():
    """Item 3 — confirma por LEITURA DE CÓDIGO (nunca por execução —
    scripts/update_dashboard.py roda uma pipeline de produção inteira
    se importado, então este módulo só lê o texto do arquivo) que a
    incorporação de NOVAS leituras de campo (SINOBRAS_new.csv) usa
    média aritmética simples, sem mínimo de estações e sem retenção da
    leitura por estação individual em serie_subst.csv.

    Revisão pontual (2ª rodada, item 1) — isto descreve o PROCEDIMENTO
    ATUAL do código, que só se aplica a dados incorporados A PARTIR de
    quando esse código passou a existir. NUNCA presumir que o backfill
    histórico 1996-2010 foi produzido por este mesmo procedimento — ver
    `verificar_dados_1996_2010_precedem_pipeline_atual` (o backfill já
    estava completo no primeiro commit do repositório, antes deste
    código)."""
    if not UPDATE_DASHBOARD_PATH.exists():
        return {'encontrado': False, 'motivo': f'{UPDATE_DASHBOARD_PATH} não encontrado'}
    codigo = UPDATE_DASHBOARD_PATH.read_text()
    encontrado = PADRAO_AGREGACAO_SINOBRAS in codigo
    return {
        'arquivo': str(UPDATE_DASHBOARD_PATH.relative_to(ROOT)),
        'padrao_verificado': PADRAO_AGREGACAO_SINOBRAS,
        'encontrado': encontrado,
        'aplica_se_a': 'incorporação de dados NOVOS (SINOBRAS_new.csv) a partir de quando este '
                        'código passou a existir — nunca confirmado como o método usado para '
                        'produzir o backfill histórico 1996-2010 (ver achado separado abaixo).',
        'interpretacao': (
            "Confirmado: a incorporação de SINOBRAS_new.csv usa "
            "df_new.groupby(['ano','mes'])['prec_mm'].mean() — média aritmética simples sobre "
            "QUANTAS estações/fazendas estiverem presentes naquele envio, sem exigência de "
            "número mínimo (1 fazenda reportando produz o mesmo tipo de valor que 34 "
            "reportando) e sem reter a leitura por estação individual — só a média sobrevive "
            "em serie_subst.csv (coluna 'prec'), a granularidade por fazenda é descartada. Isso "
            "descreve o procedimento ATUAL para dados NOVOS — não o backfill histórico."
        ) if encontrado else (
            "Padrão de agregação esperado não encontrado no arquivo atual — o método pode ter "
            "mudado desde esta auditoria; revisar scripts/update_dashboard.py manualmente antes "
            "de confiar nesta interpretação."
        ),
    }


def verificar_dados_1996_2010_precedem_pipeline_atual():
    """Item 3 (2ª rodada, item 1 da revisão) — NÃO presumir que os
    dados de 1996-2011 foram produzidos pelo procedimento atual de
    incorporação (`verificar_padrao_agregacao_sinobras_no_codigo`).
    Verifica via `git log`/`git show` (nunca por suposição) se o
    período 1996-2010 já estava completo no PRIMEIRO commit do
    repositório que introduziu data/serie_subst.csv — se sim, esse
    backfill preexiste a qualquer execução do código atual, e o método
    que de fato o produziu é DESCONHECIDO (fora deste repositório, ou
    nunca registrado)."""
    try:
        log = subprocess.run(
            ['git', 'log', '--follow', '--diff-filter=A', '--format=%H', '--', 'data/serie_subst.csv'],
            cwd=ROOT, capture_output=True, text=True, timeout=15, check=True)
        commits = log.stdout.strip().splitlines()
        if not commits:
            return {'verificavel': False, 'motivo': 'nenhum commit de criação encontrado para serie_subst.csv'}
        primeiro_commit = commits[-1]
        show = subprocess.run(['git', 'show', f'{primeiro_commit}:data/serie_subst.csv'],
                               cwd=ROOT, capture_output=True, text=True, timeout=15, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        return {'verificavel': False, 'motivo': f'git indisponível ou falhou: {e}'}

    df_primeiro_commit = pd.read_csv(io.StringIO(show.stdout))
    sub = df_primeiro_commit[(df_primeiro_commit['ano'] >= 1996) & (df_primeiro_commit['ano'] <= 2010)]
    n_esperado = 15 * 12   # 1996-2010, 15 anos completos

    return {
        'verificavel': True,
        'primeiro_commit': primeiro_commit,
        'n_meses_1996_2010_no_primeiro_commit': int(len(sub)),
        'n_meses_esperado': n_esperado,
        'ja_completo_no_primeiro_commit': bool(len(sub) == n_esperado),
        'interpretacao': (
            f"O período 1996-2010 já estava {'COMPLETO' if len(sub) == n_esperado else 'PARCIAL'} "
            f"({len(sub)}/{n_esperado} meses) no primeiro commit deste repositório "
            f"({primeiro_commit[:8]}) — ou seja, antes de qualquer execução do procedimento de "
            "incorporação hoje presente em scripts/update_dashboard.py. O método que de fato "
            "produziu esses valores históricos é DESCONHECIDO a partir deste repositório; não "
            "deve ser presumido igual ao procedimento atual só porque ambos dizem respeito a "
            "'dados Sinobras'."
        ),
    }


def montar_achados_documentacao():
    """Item 3 — reúne os achados de documentação/procedência em 1
    estrutura, cada um com evidência computada (nunca uma alegação sem
    número ou trecho de código por trás)."""
    return {
        'readme_descricao_unica': (
            'README.md linha 18/104: "Série histórica (MERRA-2 1981-1995 + Sinobras 1996-hoje)" '
            '— uma única linha, sem coordenadas, sem procedimento de agregação, sem menção a '
            'lacunas conhecidas, sem indicação de incerteza/qualidade por período.'
        ),
        'identidade_merra2_master_monthly': verificar_identidade_merra2_com_master_monthly(),
        'agregacao_sinobras_no_codigo': verificar_padrao_agregacao_sinobras_no_codigo(),
        'dados_1996_2010_precedem_pipeline_atual': verificar_dados_1996_2010_precedem_pipeline_atual(),
        'coordenadas_dos_3_municipios_pre_1996': (
            'Araguaína/Colinas do Tocantins/Tocantinópolis — nenhuma coordenada, nenhum script '
            'de geração e nenhum registro de commit anterior ao primeiro commit do repositório '
            '("Create index.html") documentam a origem dessas 3 colunas em '
            'data/master_monthly.csv. Não verificável a partir deste repositório — não estimado '
            'aqui para não inventar dado que a tarefa pede para nunca supor.'
        ),
        'gaps_e_qualidade_documentados_previamente': (
            'Nenhuma lacuna conhecida do período 1991-2010 está documentada em README.md/'
            'CLAUDE.md — as armadilhas documentadas em CLAUDE.md (6/7) cobrem viés de fonte '
            'satelital (CHIRPS/ERA5, período recente) e persistência de índices oceânicos, '
            'nunca a série de precipitação pré-2011 usada nesta auditoria.'
        ),
        'documentos_necessarios_para_comprovar_procedencia': montar_lista_documentos_necessarios(),
        'nova_evidencia_sinobras_por_fazenda': montar_achado_nova_evidencia_sinobras_por_fazenda(),
    }


def montar_achado_nova_evidencia_sinobras_por_fazenda():
    """Item 6/7 (3ª rodada) — a nova evidência SINOBRAS.csv (registros
    por fazenda, 1996-2025) foi auditada de forma INDEPENDENTE por
    scripts/nmme_auditoria_sinobras_por_fazenda.py — nunca
    reimplementada aqui. Resume os achados JÁ VERIFICADOS por aquele
    módulo (EVIDENCIA_SINOBRAS_POR_FAZENDA) e deixa explícito o que
    muda no achado desta auditoria principal e o que CONTINUA sem
    comprovação."""
    ev = EVIDENCIA_SINOBRAS_POR_FAZENDA
    return {
        **ev,
        'interpretacao': (
            f"A agregação numérica histórica de {ev['periodo_coberto_inicio']} a "
            f"{ev['periodo_coberto_fim']} foi REPRODUZIDA de forma independente a partir de "
            f"{ev['n_registros']} registros por fazenda ({ev['n_identificadores']} "
            f"identificadores, SHA-256 `{ev['sha256']}`) — reconciliação 100% completa com "
            f"data/serie_subst.csv (detalhamento completo em {ev['relatorio_completo']}). Isso "
            "muda o item 1 da lista de documentos necessários abaixo: dados originais por "
            "estação/fazenda individual foram PARCIALMENTE obtidos para 1996-2025 — o trecho "
            "pré-1996 (MERRA-2/3-municípios) continua integralmente sem essa evidência. A mesma "
            f"auditoria independente também encontrou só {ev['n_series_mensais_distintas']} "
            f"séries mensais numericamente distintas entre os {ev['n_identificadores']} "
            f"identificadores — 2 grupos compartilham a mesma série completa "
            f"({ev['grupos_de_series_identicas']}). O que CONTINUA sem comprovação, mesmo com "
            "esta nova evidência: a metodologia de medição em campo, eventuais preenchimentos "
            "retrospectivos, e se os identificadores agrupados representam pluviômetro "
            "compartilhado ou replicação administrativa de fazendas distintas — nenhuma das "
            f"duas hipóteses deve ser presumida (ver {ev['relatorio_completo']})."
        ),
    }


def montar_lista_documentos_necessarios():
    """Item 4 (2ª rodada) — lista OBJETIVA (não computada — não há como
    verificar programaticamente a ausência de documentos fora deste
    repositório) do que seria necessário para comprovar de verdade a
    procedência histórica, tanto do trecho pré-1996 quanto do pós-1996.
    Item 1 foi PARCIALMENTE endereçado na 3ª rodada por SINOBRAS.csv
    (ver montar_achado_nova_evidencia_sinobras_por_fazenda) — os
    demais itens continuam integralmente ausentes deste repositório."""
    return [
        "Dados originais por estação/fazenda individual para 1996-2025 — PARCIALMENTE obtido "
        "via SINOBRAS.csv (arquivo recebido, não incorporado a este repositório; ver achado "
        "'nova_evidencia_sinobras_por_fazenda' e docs/nmme-fase2c2-auditoria-sinobras-por-"
        "fazenda.md). Ainda faltam: a metodologia de medição em campo, eventuais preenchimentos "
        "retrospectivos, e a independência efetiva dos instrumentos — nenhum dos três é "
        "verificável a partir desse arquivo isoladamente. Para o trecho pré-1996 (MERRA-2/"
        "3-municípios), este item continua integralmente ausente.",
        "Coordenadas de cada uma das 34 fazendas/estações pluviométricas Sinobras — hoje só o "
        "centroide agregado (lat=-7,80/lon=-47,95) é conhecido, nunca a posição individual "
        "(SINOBRAS.csv também não traz coordenadas).",
        "Períodos de operação de cada estação/fazenda (quando cada uma começou/parou de medir, "
        "e quaisquer interrupções de manutenção) — necessário para saber se a amostra por mês é "
        "estável ao longo do tempo ou varia por entrada/saída de estações.",
        "Identificação da fonte ORIGINAL das 3 séries municipais (Araguaína/Colinas do "
        "Tocantins/Tocantinópolis) usadas no período 1981-1995: se são de fato extração MERRA-2 "
        "(e, se sim, em qual ponto de grade/data de extração), ou outra reanálise, ou estações "
        "de superfície de cada cidade.",
        "Coordenadas exatas (ou o ponto/célula de grade) usadas para extrair essas 3 séries "
        "municipais, sejam elas de reanálise ou de estação.",
        "O script, planilha ou processo — mesmo que externo a este repositório — que gerou o "
        "backfill 1996-2010 de serie_subst.csv antes do primeiro commit ('Create index.html'), "
        "já que o procedimento hoje em scripts/update_dashboard.py não pode ser presumido como "
        "o mesmo (ver achado 'dados_1996_2010_precedem_pipeline_atual').",
        "Documentação do número mínimo de estações/fazendas (se algum) considerado necessário "
        "para publicar um valor mensal válido — hoje o código aceita qualquer contagem >=1 sem "
        "distinção.",
        "Explicação para os 2 grupos de identificadores com série mensal completa idêntica "
        "encontrados em SINOBRAS.csv (FAZ02/FAZ03/FAZ04/FAZ05/FAZ08/FAZ09/FAZ19 e FAZ07/FAZ15) "
        "— se representam pluviômetro compartilhado, replicação administrativa de um registro "
        "entre fazendas realmente distintas, ou preenchimento de uma fazenda a partir de outra "
        "(ver docs/nmme-fase2c2-auditoria-sinobras-por-fazenda.md, Seção 3/4).",
    ]


# ══════════════════════════════════════════════════════════════════════════
# Item 4 — correspondência espacial: fazendas, centroide e grade do CFSv2
# ══════════════════════════════════════════════════════════════════════════

def distancia_grade_cfsv2_fazendas_km(diretorio=None):
    """Item 4 — lê `grid_distance_km` DIRETAMENTE dos CSVs RAW
    persistidos e aprovados na consolidação (run 36238169299) — nunca
    resuposta/recalculada com uma fórmula nova. Levanta erro explícito
    se os 5 lotes não concordarem entre si (nunca reporta um número
    médio que esconderia uma divergência real de grade)."""
    diretorio = diretorio or ext.DIRETORIO_HISTORICO_FAZENDAS
    arquivos = sorted(glob.glob(str(diretorio / 'lote_*_raw.csv')))
    if not arquivos:
        raise FileNotFoundError(f'nenhum lote_*_raw.csv encontrado em {diretorio}')
    valores = set()
    for caminho in arquivos:
        d = pd.read_csv(caminho, usecols=['grid_distance_km'])
        valores.update(round(v, 4) for v in d['grid_distance_km'].unique())
    if len(valores) != 1:
        raise RuntimeError(f'grid_distance_km não é constante entre os lotes de {diretorio}: {valores} '
                            '— divergência real de grade, auditoria não pode assumir um único ponto')
    return valores.pop()


def avaliar_correspondencia_espacial():
    """Item 4 — reúne as 3 camadas do problema espacial, nunca
    reduzidas a 1 número só:
    1. distância REAL entre o centroide pedido (-7.80, -47.95) e o
       ponto de grade do CFSv2 efetivamente selecionado — MUITO menor
       que os 198 km de São Bento, mas não zero (grade ~1°, célula
       mais próxima ainda fica a ~23 km);
    2. a série observacional pré-1996 representa uma média de 3
       municípios cujas coordenadas nem são verificáveis (não é 1
       ponto, é uma área difusa e não documentada);
    3. a série observacional 1996+ representa uma média de até 34
       fazendas (o "centroide" é o de um ENVELOPE de ~85.020 ha —
       CLAUDE.md armadilha 8 — não de um ponto), enquanto o CFSv2
       fornece 1 valor por célula de grade (~1°, ordem de 100 km de
       lado) — descasamento de SUPORTE ESPACIAL (área difusa vs.
       célula única), não só de distância entre pontos."""
    dist_grade_km = distancia_grade_cfsv2_fazendas_km()
    return {
        'distancia_grade_cfsv2_ate_centroide_km': dist_grade_km,
        'distancia_sao_bento_ate_centroide_km_referencia_anterior': round(
            pilo.distancia_fazendas_ate_municipio_km(), 1),
        'melhoria_vs_sao_bento_km': round(pilo.distancia_fazendas_ate_municipio_km() - dist_grade_km, 1),
        'observacao_pre_1996_e_area_ou_ponto': (
            'ÁREA difusa e não documentada — média de 3 municípios (Araguaína/Colinas do '
            'Tocantins/Tocantinópolis), coordenadas não verificáveis a partir do repositório.'
        ),
        'observacao_pos_1996_e_area_ou_ponto': (
            'ÁREA — média de até 34 fazendas dentro do envelope de ~85.020,5 ha '
            '(CLAUDE.md armadilha 8), não um ponto único; número de fazendas reportando '
            'varia mês a mês sem mínimo exigido (ver achados de documentação).'
        ),
        'descasamento_de_suporte_espacial': (
            'A previsão do CFSv2 é 1 valor por célula de grade (~1° ~ 100km de lado); a '
            'observação é uma média sobre uma área (município triplo ou envelope de '
            'fazendas), nunca um ponto equivalente à célula de grade — mesmo com a distância '
            'melhorada (~23km em vez de 198km), comparar os dois exige decidir explicitamente '
            'se a média de área é um proxy aceitável do valor pontual de grade, o que este '
            'módulo NÃO decide.'
        ),
        'necessidade_de_coordenadas_individuais': (
            f"Item 7 (3ª rodada) — a nova evidência SINOBRAS.csv (achado da Seção 4, "
            f"EVIDENCIA_SINOBRAS_POR_FAZENDA) identifica "
            f"{EVIDENCIA_SINOBRAS_POR_FAZENDA['n_series_mensais_distintas']} séries mensais "
            f"distintas entre os {EVIDENCIA_SINOBRAS_POR_FAZENDA['n_identificadores']} "
            "identificadores de fazenda, mas nenhuma coordenada individual — nem no arquivo "
            "recebido, nem em qualquer outro arquivo deste repositório (CLAUDE.md armadilha 8: "
            "data/fazendas.geojson foi deliberadamente substituído por um envelope único sem "
            "identificação por fazenda). É NECESSÁRIO obter as coordenadas individuais de cada "
            "ponto de medição (no mínimo, de cada série mensal numericamente distinta) para "
            "decidir se o suporte espacial da observação — potencialmente múltiplos pontos, não "
            "um único centroide — é comparável à célula de grade do CFSv2. Sem essas "
            "coordenadas, a distância de 22,91km acima continua sendo a distância de UM ponto "
            f"agregado, nunca das medições individuais (detalhamento completo em "
            f"{EVIDENCIA_SINOBRAS_POR_FAZENDA['relatorio_completo']})."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Item 5 — alinhamento temporal H1-H6
# ══════════════════════════════════════════════════════════════════════════

def verificar_alinhamento_temporal(diretorio=None):
    """Item 5 — confirma, a partir dos temporal_audit.csv REALMENTE
    persistidos (não recalculado), que as 240×6=1.440 combinações têm
    `mapping_status=OK` e que H1 é o mesmo mês da inicialização (H6 =
    +5 meses) — nunca assume, sempre lê o que foi de fato gravado na
    extração aprovada."""
    diretorio = diretorio or ext.DIRETORIO_HISTORICO_FAZENDAS
    arquivos = sorted(glob.glob(str(diretorio / 'lote_*_temporal_audit.csv')))
    if not arquivos:
        raise FileNotFoundError(f'nenhum lote_*_temporal_audit.csv encontrado em {diretorio}')
    t = pd.concat([pd.read_csv(f) for f in arquivos], ignore_index=True)
    n_total = len(t)
    n_ok = int((t['mapping_status'] == 'OK').sum())

    # H1 == mês da própria inicialização, H6 == +5 meses — checado
    # diretamente nos dados persistidos, não recalculado por fórmula.
    t_h1 = t[t['H_lead'] == 1]
    h1_igual_init = bool((t_h1['origem_piloto'] == t_h1['target_month']).all()) if len(t_h1) else False

    return {
        'n_combinacoes_origem_lead': n_total,
        'n_esperado': len(ORIGENS_HISTORICAS) * 6,
        'n_mapping_status_ok': n_ok,
        'todas_ok': n_ok == n_total,
        'h1_igual_mes_inicializacao_confirmado': h1_igual_init,
        'origem_alvo_mais_distante': str(t['target_month'].max()),
    }


# ══════════════════════════════════════════════════════════════════════════
# Item 6 — períodos utilizáveis (reanálise x medição de campo)
# ══════════════════════════════════════════════════════════════════════════

def identificar_periodos_utilizaveis(cobertura_df):
    """Item 6 — a partir da cobertura por origem×lead já classificada
    (item 1/2), separa quais combinações têm o MÊS-ALVO em cada
    procedência — nunca pela origem (mês de inicialização), porque o
    que importa para uma futura avaliação é de que fonte vem o valor
    OBSERVADO a comparar, não de quando a previsão foi emitida (uma
    origem de 1995 com lead 6 mira um alvo já em 1996, já Sinobras)."""
    disponivel = cobertura_df[cobertura_df['disponibilidade'] == 'PRESENTE'].copy()
    nao_substituta = disponivel[~disponivel['fonte_e_substituta_nao_usar']]
    qualidade_ok = nao_substituta[nao_substituta['qualidade_verificada_status'] == pilo.QUALIDADE_STATUS_OK]

    por_procedencia = qualidade_ok['procedencia_documental'].value_counts().to_dict()
    return {
        'n_total_combinacoes': len(cobertura_df),
        'n_disponivel_e_qualidade_ok': len(qualidade_ok),
        'combinacoes_utilizaveis_por_procedencia': por_procedencia,
        'reanalise_merra2_tem_uso_limitado': (
            'A procedência rotulada MERRA-2 (achado da Seção 4: fonte original não comprovada — '
            'é, numericamente, a média de 3 municípios) só se aplica a alvos com ano<=1995: '
            '345/1.440 combinações, razoavelmente distribuídas entre 1991-1995 e entre os 6 '
            'leads (ver Seção 4, distribuição real pré-1996) — nunca concentradas num único trecho.'
        ),
        'recomendacao': (
            'Reportar qualquer avaliação futura SEPARADAMENTE para alvos MERRA-2/3-municípios '
            '(ano<=1995) e alvos Estação Sinobras (ano>=1996) — nunca uma métrica agregada '
            'única que misture as duas procedências, dado que já divergem em magnitude '
            '(achado da Seção 4, diff média >1mm/mês pós-1996) e em suporte espacial (Seção 5).'
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Item 3 (2ª rodada) — protocolo de validação: amostra de uma climatologia
# restrita a registros Sinobras (>=1996) sob janela expansível
# ══════════════════════════════════════════════════════════════════════════

def analisar_amostra_climatologia_sinobras_apenas(origens=ORIGENS_HISTORICAS,
                                                    ano_inicio_sinobras=ANO_FIM_MERRA2 + 1):
    """Item 3 (2ª rodada) — a abordagem (b) do protocolo de validação
    (janela expansível, só informação anterior à emissão da previsão —
    ver Seção 8.3 do relatório) exige uma climatologia de referência
    construída SÓ com anos anteriores ao ano avaliado. Se essa
    climatologia for restrita a registros Sinobras (>=1996 — a única
    procedência com série de campo real neste repositório; a
    procedência MERRA-2/3-municípios não teve sua fonte original
    comprovada, achado do item 1), o número de anos prévios disponíveis
    é PEQUENO ou ZERO para os primeiros anos da janela 1991-2010 —
    calculado aqui, nunca suposto: `max(0, ano_origem - 1996)` anos
    completos anteriores a cada ano de origem avaliado."""
    anos_origem = sorted({ano for ano, mes in origens})
    disponibilidade = {ano: max(0, ano - ano_inicio_sinobras) for ano in anos_origem}
    n_zero = sum(1 for v in disponibilidade.values() if v == 0)
    n_menor_5 = sum(1 for v in disponibilidade.values() if v < 5)
    return {
        'ano_inicio_sinobras': ano_inicio_sinobras,
        'anos_origem_avaliados': anos_origem,
        'anos_climatologia_sinobras_disponiveis_por_ano_origem': disponibilidade,
        'n_anos_origem_com_zero_anos_previos': n_zero,
        'n_anos_origem_com_menos_de_5_anos_previos': n_menor_5,
        'interpretacao': (
            "Na abordagem (b) — janela expansível, só informação anterior à emissão —, uma "
            f"climatologia restrita a registros Sinobras (>={ano_inicio_sinobras}) teria ZERO anos "
            f"prévios disponíveis para {n_zero} dos {len(anos_origem)} anos de origem avaliados "
            f"(1991 a {ano_inicio_sinobras}, inclusive) e menos de 5 anos de amostra para "
            f"{n_menor_5} deles — amostra pequena demais para uma climatologia estável nos "
            "primeiros anos da janela. Exemplos concretos (calculados, não estimados): ano de "
            f"origem 1997 → {disponibilidade.get(1997)} ano(s) prévio(s) disponível(is); 2000 → "
            f"{disponibilidade.get(2000)}; 2005 → {disponibilidade.get(2005)}; 2010 → "
            f"{disponibilidade.get(2010)}. Isso não invalida a abordagem (b) — é uma limitação "
            "amostral real que precisa ser decidida explicitamente antes de qualquer cálculo de "
            "skill: usar uma climatologia mais longa que misture a procedência MERRA-2/"
            "3-municípios (cuja fonte original não é comprovada — achado da Seção 4) para os "
            "primeiros anos, ou aceitar a amostra pequena/zero documentando a incerteza adicional "
            "que isso implica."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Consolidação + relatório
# ══════════════════════════════════════════════════════════════════════════

def executar_auditoria_completa():
    cobertura_df = executar_auditoria_cobertura_por_origem_lead()
    cobertura_calendario = verificar_cobertura_calendario_bruta()
    resumo_procedencia = resumir_por_procedencia(cobertura_df)
    dependencia_temporal = analisar_dependencia_temporal_observacoes(cobertura_df)
    distribuicao_pre_1996 = analisar_distribuicao_pre_1996(cobertura_df)
    achados_documentacao = montar_achados_documentacao()
    correspondencia_espacial = avaliar_correspondencia_espacial()
    alinhamento_temporal = verificar_alinhamento_temporal()
    periodos_utilizaveis = identificar_periodos_utilizaveis(cobertura_df)
    amostra_climatologia_sinobras_apenas = analisar_amostra_climatologia_sinobras_apenas()

    aptidao = pilo.avaliar_aptidao_referencia_observacional(
        cobertura_df,
        distancia_km=correspondencia_espacial['distancia_grade_cfsv2_ate_centroide_km'],
        ponto_descricao='centroide das fazendas (grade CFSv2, extração histórica aprovada, run 36238169299)')

    metadata = {
        'fase': '2C.2 — validação científica da referência observacional (centroide das fazendas)',
        'evidencia_extracao_historica': EVIDENCIA_EXTRACAO_HISTORICA_FAZENDAS,
        'cobertura_calendario_bruta': cobertura_calendario,
        'resumo_procedencia': resumo_procedencia.to_dict(orient='records'),
        'dependencia_temporal_observacoes': dependencia_temporal,
        'distribuicao_pre_1996': distribuicao_pre_1996,
        'achados_documentacao': achados_documentacao,
        'correspondencia_espacial': correspondencia_espacial,
        'alinhamento_temporal': alinhamento_temporal,
        'periodos_utilizaveis': periodos_utilizaveis,
        'amostra_climatologia_sinobras_apenas': amostra_climatologia_sinobras_apenas,
        'aptidao_referencia_observacional': aptidao,
        'nenhuma_skill_calculada': True, 'nenhum_dashboard_alterado': True,
        'nenhum_modelo_climatico_alterado': True,
    }
    return cobertura_df, metadata


def gerar_relatorio_markdown(cobertura_df, metadata):
    ap = metadata['aptidao_referencia_observacional']
    cal = metadata['cobertura_calendario_bruta']
    dep = metadata['dependencia_temporal_observacoes']
    doc = metadata['achados_documentacao']
    dist_pre96 = metadata['distribuicao_pre_1996']
    esp = metadata['correspondencia_espacial']
    tmp = metadata['alinhamento_temporal']
    per = metadata['periodos_utilizaveis']
    amostra = metadata['amostra_climatologia_sinobras_apenas']

    linhas = [
        "# Auditoria da referência observacional — extração histórica CFSv2 (fazendas)",
        "",
        "**Relatório técnico — não calcula skill, não declara aptidão científica final, "
        "só reúne evidência e decisões pendentes.**",
        "",
        "## Evidência de partida",
        "",
        f"- Extração histórica consolidada e aprovada: run "
        f"{metadata['evidencia_extracao_historica']['run_id']} — "
        f"{metadata['evidencia_extracao_historica']['n_origens_aprovadas_total']}/240 origens, "
        f"{metadata['evidencia_extracao_historica']['n_raw_total']} registros RAW.",
        "",
        "## 1. Cobertura da série observacional",
        "",
        f"- Período exigido (1ª inicialização a H6 da última): "
        f"{cal['periodo_alvo_inicio']} → {cal['periodo_alvo_fim']} "
        f"({cal['n_meses_esperados']} meses).",
        f"- Meses ausentes no calendário: {cal['n_meses_ausentes']} "
        f"({cal['meses_ausentes'] if cal['meses_ausentes'] else 'nenhum'}).",
        f"- Meses duplicados: {cal['n_meses_duplicados']} "
        f"({cal['meses_duplicados'] if cal['meses_duplicados'] else 'nenhum'}).",
        f"- **Cobertura de calendário completa: {cal['cobertura_calendario_completa']}**",
        "",
        "## 2. MERRA-2 vs. Estação Sinobras (combinações origem×lead)",
        "",
    ]
    for row in metadata['resumo_procedencia']:
        linhas.append(f"- `{row['procedencia_documental']}`: {row['n_combinacoes']} combinações")
    linhas += [
        "",
        "## 3. Combinações previsão×horizonte vs. observações mensais independentes",
        "",
        "**Nunca confundir as duas contagens — são coisas diferentes.**",
        "",
        f"- Combinações origem×lead: {dep['n_combinacoes_origem_lead']}.",
        f"- Meses observados DISTINTOS usados como alvo: {dep['n_meses_observados_distintos']}.",
        f"- Razão combinações/mês distinto: {dep['razao_combinacoes_por_mes_distinto']} "
        f"(reuso por mês: mínimo {dep['reuso_por_mes_min']}, máximo {dep['reuso_por_mes_max']}, "
        f"médio {dep['reuso_por_mes_medio']}, mediano {dep['reuso_por_mes_mediano']}).",
        f"- {dep['interpretacao']}",
        "",
        "## 4. Documentação efetivamente disponível",
        "",
        f"- {doc['readme_descricao_unica']}",
        "",
        "### Identidade MERRA-2 vs. master_monthly.csv (achado numérico)",
        "",
    ]
    idm = doc['identidade_merra2_master_monthly']
    if idm.get('comparavel'):
        linhas += [
            f"- Meses comparados (ano<=1995): {idm['n_meses_comparados_pre_1996']}, diferença "
            f"absoluta máxima: {idm['diff_abs_maxima_pre_1996_mm']} mm — "
            f"**idêntico numericamente: {idm['identico_numericamente_pre_1996']}** "
            f"(fonte original comprovada: {idm['fonte_original_comprovada']}).",
            f"- Meses comparados (ano>=1996): {idm['n_meses_comparados_pos_1996']}, diferença "
            f"absoluta média: {idm['diff_abs_media_pos_1996_mm']} mm, máxima: "
            f"{idm['diff_abs_maxima_pos_1996_mm']} mm — **diverge: {idm['diverge_pos_1996']}**.",
            f"- {idm['interpretacao']}",
        ]
    else:
        linhas.append(f"- Não comparável: {idm.get('motivo')}")
    linhas += [
        "",
        "### Método de agregação das leituras de campo Sinobras (achado por leitura de código)",
        "",
        f"- Arquivo: `{doc['agregacao_sinobras_no_codigo'].get('arquivo', UPDATE_DASHBOARD_PATH.name)}`",
        f"- Padrão verificado: `{doc['agregacao_sinobras_no_codigo'].get('padrao_verificado', '')}` — "
        f"encontrado: {doc['agregacao_sinobras_no_codigo'].get('encontrado')}",
        f"- Aplica-se a: {doc['agregacao_sinobras_no_codigo'].get('aplica_se_a')}",
        f"- {doc['agregacao_sinobras_no_codigo'].get('interpretacao')}",
        "",
        "### Backfill histórico 1996-2010 precede o pipeline atual (achado via git)",
        "",
    ]
    bkf = doc['dados_1996_2010_precedem_pipeline_atual']
    if bkf.get('verificavel'):
        linhas += [
            f"- Primeiro commit do repositório com `data/serie_subst.csv`: "
            f"`{bkf['primeiro_commit'][:8]}`.",
            f"- Meses 1996-2010 já presentes nesse primeiro commit: "
            f"{bkf['n_meses_1996_2010_no_primeiro_commit']}/{bkf['n_meses_esperado']} — "
            f"**já completo: {bkf['ja_completo_no_primeiro_commit']}**.",
            f"- {bkf['interpretacao']}",
        ]
    else:
        linhas.append(f"- Não verificável: {bkf.get('motivo')}")
    linhas += [
        "",
        "### Distribuição real das 345 combinações pré-1996 (corrigido)",
        "",
        f"- Total de combinações com procedência MERRA-2/3-municípios: {dist_pre96['n_total']}.",
        f"- Por ano-alvo: {dist_pre96['por_ano_alvo']}.",
        f"- Por ano de origem: {dist_pre96['por_ano_origem']}.",
        f"- Por horizonte (H_lead): {dist_pre96['por_h_lead']}.",
        f"- {dist_pre96.get('interpretacao', '')}",
        "",
        "### Documentos necessários para comprovar a procedência histórica",
        "",
        "Nenhum destes está disponível neste repositório hoje (ver achados acima):",
        "",
    ]
    for item in doc['documentos_necessarios_para_comprovar_procedencia']:
        linhas.append(f"- {item}")
    linhas += [
        "",
        "### Nova evidência: SINOBRAS.csv (registros por fazenda, 1996-2025)",
        "",
    ]
    nova_ev = doc['nova_evidencia_sinobras_por_fazenda']
    linhas += [
        f"- Arquivo: `{nova_ev['arquivo']}` — SHA-256 `{nova_ev['sha256']}` — não incorporado a "
        "este repositório.",
        f"- Período coberto: {nova_ev['periodo_coberto_inicio']} → "
        f"{nova_ev['periodo_coberto_fim']} ({nova_ev['n_registros']} registros, "
        f"{nova_ev['n_identificadores']} identificadores).",
        f"- Integridade estrutural completa: {nova_ev['integridade_estrutural_completa']}. "
        f"Reconciliação com data/serie_subst.csv completa: "
        f"{nova_ev['reconciliacao_com_serie_producao_completa']}.",
        f"- Séries mensais numericamente distintas: {nova_ev['n_series_mensais_distintas']} "
        f"(de {nova_ev['n_identificadores']} identificadores) — grupos idênticos: "
        f"{nova_ev['grupos_de_series_identicas']}.",
        f"- Relatório completo e reprodutível: `{nova_ev['relatorio_completo']}` (gerado por "
        f"`{nova_ev['script_auditoria']}`).",
        f"- {nova_ev['interpretacao']}",
        "",
        f"### Coordenadas dos 3 municípios do período MERRA-2 (1981-1995)",
        "",
        f"- {doc['coordenadas_dos_3_municipios_pre_1996']}",
        "",
        f"### Lacunas e qualidade documentadas previamente",
        "",
        f"- {doc['gaps_e_qualidade_documentados_previamente']}",
        "",
        "## 5. Correspondência espacial",
        "",
        f"- Distância REAL grade CFSv2 ↔ centroide das fazendas (lida do RAW aprovado): "
        f"**{esp['distancia_grade_cfsv2_ate_centroide_km']} km**.",
        f"- Referência anterior (São Bento do Tocantins, piloto): "
        f"{esp['distancia_sao_bento_ate_centroide_km_referencia_anterior']} km — "
        f"melhoria de {esp['melhoria_vs_sao_bento_km']} km com o centroide das fazendas.",
        f"- Observação pré-1996: {esp['observacao_pre_1996_e_area_ou_ponto']}",
        f"- Observação pós-1996: {esp['observacao_pos_1996_e_area_ou_ponto']}",
        f"- **Descasamento de suporte espacial**: {esp['descasamento_de_suporte_espacial']}",
        f"- **Necessidade de coordenadas individuais**: {esp['necessidade_de_coordenadas_individuais']}",
        "",
        "## 6. Alinhamento temporal H1-H6",
        "",
        f"- Combinações origem×lead auditadas: {tmp['n_combinacoes_origem_lead']}/{tmp['n_esperado']}.",
        f"- `mapping_status=OK` em todas: {tmp['todas_ok']} ({tmp['n_mapping_status_ok']} confirmadas).",
        f"- H1 = mês da própria inicialização (confirmado nos dados persistidos): "
        f"{tmp['h1_igual_mes_inicializacao_confirmado']}.",
        f"- Mês-alvo mais distante (H6 da origem 2010-12): {tmp['origem_alvo_mais_distante']}.",
        "",
        "## 7. Períodos utilizáveis",
        "",
        f"- Combinações disponíveis, não substitutas (nunca CHC-Preliminar/ERA5) e com qualidade "
        f"OK: {per['n_disponivel_e_qualidade_ok']}/{per['n_total_combinacoes']}.",
    ]
    for proc, n in per['combinacoes_utilizaveis_por_procedencia'].items():
        linhas.append(f"  - `{proc}`: {n}")
    linhas += [
        f"- {per['reanalise_merra2_tem_uso_limitado']}",
        f"- **Recomendação**: {per['recomendacao']}",
        "",
        "## 8. Protocolo estatístico proposto (NÃO calculado nesta tarefa)",
        "",
        "Proposta para uma etapa FUTURA e SEPARADA — nenhum destes cálculos foi executado aqui.",
        "",
        "### 8.1 Determinístico",
        "- Viés médio (bias) e MAE do ensemble mean por lead (H1-H6), separadamente para alvos "
        "MERRA-2/3-municípios (ano<=1995) e Estação Sinobras (ano>=1996) — nunca agregados "
        "entre si (achado da Seção 4: já divergem em magnitude).",
        "- Correlação de Pearson/Spearman entre ensemble mean e observação, por lead.",
        "",
        "### 8.2 Probabilístico",
        "- CRPS (Continuous Ranked Probability Score) do ensemble de 24 membros por lead.",
        "- Brier Skill Score (BSS) para terços de probabilidade (abaixo/normal/acima), com a "
        "climatologia de referência definida na Seção 8.3 como benchmark.",
        "- Diagrama de confiabilidade (reliability diagram) por lead, para checar calibração do "
        "ensemble.",
        "- Qualquer estimativa de incerteza estatística (intervalo de confiança, erro padrão, "
        "significância) deve tratar as combinações como dependentes, não como amostra i.i.d. "
        "— ver Seção 3 (1.440 combinações compartilham só 245 meses observados distintos).",
        "",
        "### 8.3 Protocolo de validação e climatologia de referência — duas abordagens, "
        "não escolhidas aqui",
        "",
        "Apresentadas separadamente, com as diferenças entre elas — este módulo NÃO escolhe "
        "um protocolo definitivo; a escolha fica para a etapa futura de cálculo de skill.",
        "",
        "**(a) Validação retrospectiva com exclusão do ano avaliado (leave-one-year-out, LOYO).** "
        "Usa o período completo disponível (ex.: 1981-2010) menos o próprio ano-alvo Y para "
        "montar a climatologia de referência de cada avaliação. Mais simples e auditável (o "
        "conjunto de anos de cada climatologia é sempre \"todos menos Y\"), mas PODE incluir "
        "anos POSTERIORES a Y na climatologia — informação que, na data real de emissão da "
        "previsão de Y, ainda não existia. Isso não é vazamento literal treino/teste (a "
        "climatologia não usa o próprio valor de Y), mas é uso de informação futura em relação "
        "ao momento da previsão, e precisa ser declarado explicitamente se esta abordagem for "
        "escolhida.",
        "",
        "**(b) Validação com janela temporal expansível, só informação anterior à emissão.** "
        "Para avaliar o alvo do ano Y, usa só a climatologia calculada com anos < Y — nunca "
        "anos posteriores. Operacionalmente mais realista (reproduz o que estaria disponível "
        "no momento real da previsão), mas sofre de amostra pequena ou ZERO nos primeiros anos "
        "da janela 1991-2010 quando restrita a registros Sinobras (>=1996) — ver análise "
        "abaixo.",
        "",
        f"- Combinações origem×lead auditadas: {tmp['n_combinacoes_origem_lead']}.",
        f"- Anos de origem avaliados: {amostra['anos_origem_avaliados'][0]}-"
        f"{amostra['anos_origem_avaliados'][-1]}.",
        f"- Anos de climatologia Sinobras-apenas (>={amostra['ano_inicio_sinobras']}) disponíveis "
        f"por ano de origem, sob a abordagem (b): {amostra['anos_climatologia_sinobras_disponiveis_por_ano_origem']}.",
        f"- Anos de origem com ZERO anos prévios disponíveis: "
        f"{amostra['n_anos_origem_com_zero_anos_previos']}. Anos de origem com menos de 5 anos "
        f"prévios: {amostra['n_anos_origem_com_menos_de_5_anos_previos']}.",
        f"- {amostra['interpretacao']}",
        "",
        "- **Nunca** usar a climatologia de referência do dashboard (1981-2025 completa) para "
        "avaliar previsões cujo período de emissão (1991-2010) está DENTRO dela sem declarar "
        "isso explicitamente — em qualquer uma das duas abordagens acima, o conjunto de anos "
        "que define a climatologia de CADA avaliação deve ser documentado no mesmo "
        "arquivo/tabela do resultado, nunca implícito.",
        "",
        "### 8.4 Decisões que precisam de aprovação explícita antes do cálculo de skill",
        "1. Usar ou não os alvos MERRA-2/3-municípios (ano<=1995) na avaliação, dado que sua "
        "fonte original não foi comprovada (Seção 4) e as coordenadas dos 3 "
        "municípios não são verificáveis.",
        "2. Aceitar ou não a média de área (3 municípios ou até 34 fazendas) como proxy do "
        "valor pontual de grade do CFSv2 (Seção 5) — e se aceitar, registrar isso como "
        "premissa explícita do estudo, não como equivalência.",
        "3. Escolher entre as abordagens (a) LOYO e (b) janela expansível da Seção 8.3 — ou "
        "outra — e documentar explicitamente qual conjunto de anos define a climatologia de "
        "cada avaliação, antes de qualquer BSS/anomalia ser calculado.",
        "4. Definir o tratamento de meses com `qualidade_verificada_status` diferente de OK "
        "— excluir da avaliação (recomendado) ou uma estratégia de imputação, nunca "
        "silenciosamente incluídos como se fossem OK.",
        "5. Definir como tratar a dependência temporal entre combinações (Seção 3: 1.440 "
        "combinações, 245 meses distintos) em qualquer estimativa de incerteza estatística.",
        "",
        "## Verdito de aptidão para avaliação científica (infraestrutura + observação)",
        "",
        f"- `apto_para_avaliacao_cientifica`: **{ap['apto_para_avaliacao_cientifica']}**",
        "- Motivos de bloqueio:",
    ]
    for motivo in ap['motivos_bloqueio']:
        linhas.append(f"  - {motivo}")
    linhas += [
        "",
        "### Ressalvas adicionais (não incluídas no verdito de infraestrutura acima, mas igualmente "
        "bloqueantes para uma avaliação científica)",
        "",
        "`avaliar_aptidao_referencia_observacional` (reaproveitada sem modificação) só verifica "
        "cobertura/procedência-substituta/qualidade numérica e a distância espacial — ela NÃO "
        "avalia se a documentação de procedência é suficiente. As seções 4 e 5 acima levantam "
        "problemas que continuam pendentes mesmo se a distância espacial fosse aceita:",
        "- A fonte original do trecho \"MERRA-2\" (1981-1995) — numericamente idêntico a uma "
        "média de 3 municípios sem coordenadas/metodologia verificáveis (Seção 4) — não "
        "comprovada; tratar como reanálise de grade confirmada seria uma afirmação não "
        "sustentada pelo repositório.",
        "- O descasamento de suporte espacial (célula de grade vs. média de área difusa e "
        "variável, Seção 5) — não resolvido só por a distância ter melhorado.",
        "- A agregação Sinobras sem mínimo de estações (Seção 4) — um mês com 1 fazenda "
        "reportando é tratado, na série, exatamente como um mês com 34 — e isso descreve só o "
        "procedimento ATUAL do código, não o backfill histórico 1996-2010 (Seção 4), cujo "
        "método real é desconhecido.",
        "- A dependência temporal entre combinações origem×lead (Seção 3) — 1.440 combinações "
        "não são 1.440 observações independentes.",
        "",
        "## Restrições respeitadas nesta tarefa",
        "",
        "- Nenhuma métrica de skill foi calculada.",
        "- O dashboard (docs/index.html) não foi tocado.",
        "- Nenhum modelo climático (SARIMAX/XGBoost) foi alterado.",
        "- Nenhum dado histórico foi modificado.",
        "- Os 34.560 registros RAW já extraídos (data/nmme_historico_fazendas/) foram preservados "
        "integralmente — este módulo só LÊ esses arquivos.",
    ]
    return '\n'.join(linhas) + '\n'


RELATORIO_DOC_PATH = ROOT / 'docs' / 'nmme-fase2c2-auditoria-observacional-historica.md'


def escrever_saidas(cobertura_df, metadata):
    """Tabelas/metadata (reproduzíveis a qualquer momento reexecutando
    este script, nunca editadas à mão) ficam em artifacts/ — gitignored,
    mesma convenção de nmme_poc/nmme_poc_espacial_fazendas. O relatório
    técnico em si é o DELIVERABLE desta tarefa — vai para docs/,
    commitado, mesma convenção de
    docs/nmme-fase2c2-piloto-cobertura-observacional.md (o relatório
    análogo da fase anterior)."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    cobertura_df.to_csv(ARTIFACTS_DIR / 'cobertura_por_origem_lead.csv', index=False)
    (ARTIFACTS_DIR / 'metadata.json').write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=str))
    relatorio = gerar_relatorio_markdown(cobertura_df, metadata)
    RELATORIO_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    RELATORIO_DOC_PATH.write_text(relatorio)
    for nome in ('cobertura_por_origem_lead.csv', 'metadata.json'):
        print(f"  ✅ artifacts/nmme_auditoria_observacional_historica/{nome}")
    print(f"  ✅ {RELATORIO_DOC_PATH.relative_to(ROOT)}")
    return relatorio


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def imprimir_plano():
    primeiro_alvo, ultimo_alvo = periodo_alvo_completo()
    print("=== Auditoria da Referência Observacional — Fase 2C.2 (fazendas) — "
          "DRY RUN PLAN (só leitura de arquivos locais, nenhum acesso à rede) ===")
    print(f"  periodo_alvo_necessario: {primeiro_alvo} -> {ultimo_alvo}")
    print(f"  n_origens: {len(ORIGENS_HISTORICAS)}, n_combinacoes_origem_lead: "
          f"{len(ORIGENS_HISTORICAS) * 6}")
    print(f"  ano_fim_merra2: {ANO_FIM_MERRA2}")
    print("  saidas: artifacts/nmme_auditoria_observacional_historica/")
    print("\n✅ Plano da auditoria gerado (nenhum cálculo de skill, nenhuma escrita ainda).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run-plan', action='store_true',
                     help='Só mostra o plano — nenhuma leitura pesada, nenhuma escrita.')
    ap.add_argument('--gerar-relatorio', action='store_true',
                     help='Roda a auditoria completa (só leitura de dados locais já existentes) e '
                          'escreve o relatório técnico + tabelas em artifacts/.')
    args = ap.parse_args()

    if args.gerar_relatorio:
        imprimir_plano()
        cobertura_df, metadata = executar_auditoria_completa()
        escrever_saidas(cobertura_df, metadata)
        ap_result = metadata['aptidao_referencia_observacional']
        print(f"\napto_para_avaliacao_cientifica={ap_result['apto_para_avaliacao_cientifica']}")
        for motivo in ap_result['motivos_bloqueio']:
            print(f"  - {motivo}")
        return

    imprimir_plano()


if __name__ == '__main__':
    main()
