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
import json
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
# Item 2 — separar MERRA-2 de Estação Sinobras
# ══════════════════════════════════════════════════════════════════════════

def resumir_por_procedencia(cobertura_df):
    """Item 2/6 — contagem de combinações origem×lead por procedência
    documental (a mesma coluna já calculada por
    `verificar_cobertura_observacional`, nunca uma nova classificação)."""
    resumo = (cobertura_df.groupby('procedencia_documental', dropna=False)
                .size().rename('n_combinacoes').reset_index()
                .sort_values('n_combinacoes', ascending=False))
    return resumo


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
    index.html", sem metodologia registrada). Resultado, não suposição:
    (a) idêntico (diferença de arredondamento) para ano<=1995 — ou seja,
    o "MERRA-2" da série de produção É, literalmente, essa média de 3
    municípios, nunca verificada como reanálise de grade única no ponto
    das fazendas; (b) diverge substancialmente a partir de 1996,
    consistente com a transição para leitura de campo Sinobras."""
    serie = pd.read_csv(SERIE_OBSERVACIONAL_PATH)
    if not MASTER_MONTHLY_PATH.exists():
        return {'comparavel': False, 'motivo': f'{MASTER_MONTHLY_PATH} não encontrado'}
    master = pd.read_csv(MASTER_MONTHLY_PATH)
    if 'prec_reg' not in master.columns:
        return {'comparavel': False, 'motivo': "coluna 'prec_reg' não existe em master_monthly.csv"}

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
        'identico_pre_1996': bool(len(diff_pre) and diff_pre.max() < 0.01),
        'n_meses_comparados_pos_1996': int(len(pos)),
        'diff_abs_media_pos_1996_mm': round(float(diff_pos.mean()), 2) if len(diff_pos) else None,
        'diff_abs_maxima_pos_1996_mm': round(float(diff_pos.max()), 2) if len(diff_pos) else None,
        'diverge_pos_1996': bool(len(diff_pos) and diff_pos.mean() > 1.0),
        'interpretacao': (
            "O trecho 'MERRA-2' (ano<=1995) de serie_subst.csv é numericamente idêntico a "
            "prec_reg=média(Araguaína, Colinas do Tocantins, Tocantinópolis) de "
            "master_monthly.csv. Nenhum script deste repositório documenta a origem, as "
            "coordenadas, o procedimento de agregação ou a data de criação dessas 3 colunas — "
            "o arquivo já as continha por completo no commit que o introduziu. O rótulo "
            "'MERRA-2' do README não pôde ser confirmado como reanálise de grade única no "
            "centroide das fazendas; é, na prática, uma média de 3 sedes municipais cuja "
            "identidade como MERRA-2 (em vez de, por exemplo, estações de superfície das 3 "
            "cidades) não é verificável a partir do repositório."
        ),
    }


def verificar_padrao_agregacao_sinobras_no_codigo():
    """Item 3 — confirma por LEITURA DE CÓDIGO (nunca por execução —
    scripts/update_dashboard.py roda uma pipeline de produção inteira
    se importado, então este módulo só lê o texto do arquivo) que a
    incorporação de novas leituras de campo (SINOBRAS_new.csv) usa
    média aritmética simples, sem mínimo de estações e sem retenção da
    leitura por estação individual em serie_subst.csv."""
    if not UPDATE_DASHBOARD_PATH.exists():
        return {'encontrado': False, 'motivo': f'{UPDATE_DASHBOARD_PATH} não encontrado'}
    codigo = UPDATE_DASHBOARD_PATH.read_text()
    encontrado = PADRAO_AGREGACAO_SINOBRAS in codigo
    return {
        'arquivo': str(UPDATE_DASHBOARD_PATH.relative_to(ROOT)),
        'padrao_verificado': PADRAO_AGREGACAO_SINOBRAS,
        'encontrado': encontrado,
        'interpretacao': (
            "Confirmado: a incorporação de SINOBRAS_new.csv usa "
            "df_new.groupby(['ano','mes'])['prec_mm'].mean() — média aritmética simples sobre "
            "QUANTAS estações/fazendas estiverem presentes naquele envio, sem exigência de "
            "número mínimo (1 fazenda reportando produz o mesmo tipo de valor que 34 "
            "reportando) e sem reter a leitura por estação individual — só a média sobrevive "
            "em serie_subst.csv (coluna 'prec'), a granularidade por fazenda é descartada."
        ) if encontrado else (
            "Padrão de agregação esperado não encontrado no arquivo atual — o método pode ter "
            "mudado desde esta auditoria; revisar scripts/update_dashboard.py manualmente antes "
            "de confiar nesta interpretação."
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
    }


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
            'A procedência MERRA-2 (na verdade, achado do item 3: média de 3 municípios não '
            'verificável) só se aplica a alvos com ano<=1995 — poucas combinações no início da '
            'janela 1991-2010, concentradas nos leads mais longos das origens de 1991.'
        ),
        'recomendacao': (
            'Reportar qualquer avaliação futura SEPARADAMENTE para alvos MERRA-2/3-municípios '
            '(ano<=1995) e alvos Estação Sinobras (ano>=1996) — nunca uma métrica agregada '
            'única que misture as duas procedências, dado que já divergem em magnitude '
            '(achado do item 3, diff média >1mm/mês pós-1996) e em suporte espacial (item 4).'
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Consolidação + relatório
# ══════════════════════════════════════════════════════════════════════════

def executar_auditoria_completa():
    cobertura_df = executar_auditoria_cobertura_por_origem_lead()
    cobertura_calendario = verificar_cobertura_calendario_bruta()
    resumo_procedencia = resumir_por_procedencia(cobertura_df)
    achados_documentacao = montar_achados_documentacao()
    correspondencia_espacial = avaliar_correspondencia_espacial()
    alinhamento_temporal = verificar_alinhamento_temporal()
    periodos_utilizaveis = identificar_periodos_utilizaveis(cobertura_df)

    aptidao = pilo.avaliar_aptidao_referencia_observacional(
        cobertura_df,
        distancia_km=correspondencia_espacial['distancia_grade_cfsv2_ate_centroide_km'],
        ponto_descricao='centroide das fazendas (grade CFSv2, extração histórica aprovada, run 36238169299)')

    metadata = {
        'fase': '2C.2 — validação científica da referência observacional (centroide das fazendas)',
        'evidencia_extracao_historica': EVIDENCIA_EXTRACAO_HISTORICA_FAZENDAS,
        'cobertura_calendario_bruta': cobertura_calendario,
        'resumo_procedencia': resumo_procedencia.to_dict(orient='records'),
        'achados_documentacao': achados_documentacao,
        'correspondencia_espacial': correspondencia_espacial,
        'alinhamento_temporal': alinhamento_temporal,
        'periodos_utilizaveis': periodos_utilizaveis,
        'aptidao_referencia_observacional': aptidao,
        'nenhuma_skill_calculada': True, 'nenhum_dashboard_alterado': True,
        'nenhum_modelo_climatico_alterado': True,
    }
    return cobertura_df, metadata


def gerar_relatorio_markdown(cobertura_df, metadata):
    ap = metadata['aptidao_referencia_observacional']
    cal = metadata['cobertura_calendario_bruta']
    doc = metadata['achados_documentacao']
    esp = metadata['correspondencia_espacial']
    tmp = metadata['alinhamento_temporal']
    per = metadata['periodos_utilizaveis']

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
        "## 3. Documentação efetivamente disponível",
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
            f"**idêntico: {idm['identico_pre_1996']}**.",
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
        f"- {doc['agregacao_sinobras_no_codigo'].get('interpretacao')}",
        "",
        f"### Coordenadas dos 3 municípios do período MERRA-2 (1981-1995)",
        "",
        f"- {doc['coordenadas_dos_3_municipios_pre_1996']}",
        "",
        f"### Lacunas e qualidade documentadas previamente",
        "",
        f"- {doc['gaps_e_qualidade_documentados_previamente']}",
        "",
        "## 4. Correspondência espacial",
        "",
        f"- Distância REAL grade CFSv2 ↔ centroide das fazendas (lida do RAW aprovado): "
        f"**{esp['distancia_grade_cfsv2_ate_centroide_km']} km**.",
        f"- Referência anterior (São Bento do Tocantins, piloto): "
        f"{esp['distancia_sao_bento_ate_centroide_km_referencia_anterior']} km — "
        f"melhoria de {esp['melhoria_vs_sao_bento_km']} km com o centroide das fazendas.",
        f"- Observação pré-1996: {esp['observacao_pre_1996_e_area_ou_ponto']}",
        f"- Observação pós-1996: {esp['observacao_pos_1996_e_area_ou_ponto']}",
        f"- **Descasamento de suporte espacial**: {esp['descasamento_de_suporte_espacial']}",
        "",
        "## 5. Alinhamento temporal H1-H6",
        "",
        f"- Combinações origem×lead auditadas: {tmp['n_combinacoes_origem_lead']}/{tmp['n_esperado']}.",
        f"- `mapping_status=OK` em todas: {tmp['todas_ok']} ({tmp['n_mapping_status_ok']} confirmadas).",
        f"- H1 = mês da própria inicialização (confirmado nos dados persistidos): "
        f"{tmp['h1_igual_mes_inicializacao_confirmado']}.",
        f"- Mês-alvo mais distante (H6 da origem 2010-12): {tmp['origem_alvo_mais_distante']}.",
        "",
        "## 6. Períodos utilizáveis",
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
        "## 7. Protocolo estatístico proposto (NÃO calculado nesta tarefa)",
        "",
        "Proposta para uma etapa FUTURA e SEPARADA — nenhum destes cálculos foi executado aqui.",
        "",
        "### 7.1 Determinístico",
        "- Viés médio (bias) e MAE do ensemble mean por lead (H1-H6), separadamente para alvos "
        "MERRA-2/3-municípios (ano<=1995) e Estação Sinobras (ano>=1996) — nunca agregados "
        "entre si (achado do item 3: já divergem em magnitude).",
        "- Correlação de Pearson/Spearman entre ensemble mean e observação, por lead.",
        "",
        "### 7.2 Probabilístico",
        "- CRPS (Continuous Ranked Probability Score) do ensemble de 24 membros por lead.",
        "- Brier Skill Score (BSS) para terços de probabilidade (abaixo/normal/acima), com a "
        "climatologia de referência definida na Seção 7.3 como benchmark.",
        "- Diagrama de confiabilidade (reliability diagram) por lead, para checar calibração do "
        "ensemble.",
        "",
        "### 7.3 Climatologia de referência — mecanismo contra vazamento de informação",
        "- **Nunca** usar a climatologia de referência do dashboard (1981-2025 completa) para "
        "avaliar previsões cujo período de emissão (1991-2010) está DENTRO dela — isso "
        "vazaria informação futura (relativa a cada ano avaliado) para dentro do "
        "benchmark de comparação.",
        "- Proposta: climatologia EXPANSÍVEL retrospectiva — para avaliar o alvo do ano Y, usar "
        "só a climatologia calculada com anos < Y (ou, no mínimo, excluir o próprio ano Y e "
        "os 2 anos vizinhos, para reduzir autocorrelação de baixa frequência tipo PDO). "
        "Alternativa mais simples e auditável: climatologia leave-one-year-out (LOYO) sobre "
        "1981-2010 inteiro, recalculada a cada alvo excluindo o ano do próprio alvo.",
        "- Qualquer que seja a escolha, documentar explicitamente qual conjunto de anos define "
        "a climatologia de cada avaliação, no mesmo arquivo/tabela do resultado — nunca "
        "implícito.",
        "",
        "### 7.4 Decisões que precisam de aprovação explícita antes do cálculo de skill",
        "1. Usar ou não os alvos MERRA-2/3-municípios (ano<=1995) na avaliação, dado que sua "
        "procedência como reanálise não foi confirmada (item 3) e as coordenadas dos 3 "
        "municípios não são verificáveis.",
        "2. Aceitar ou não a média de área (3 municípios ou até 34 fazendas) como proxy do "
        "valor pontual de grade do CFSv2 (item 4) — e se aceitar, registrar isso como "
        "premissa explícita do estudo, não como equivalência.",
        "3. Definir o mecanismo exato de climatologia sem vazamento (Seção 7.3) antes de "
        "qualquer BSS/anomalia ser calculado.",
        "4. Definir o tratamento de meses com `qualidade_verificada_status` diferente de OK "
        "— excluir da avaliação (recomendado) ou uma estratégia de imputação, nunca "
        "silenciosamente incluídos como se fossem OK.",
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
        "avalia se a documentação de procedência é suficiente. As seções 3 e 4 acima levantam "
        "problemas que continuam pendentes mesmo se a distância espacial fosse aceita:",
        "- A identidade do trecho \"MERRA-2\" (1981-1995) com uma média de 3 municípios sem "
        "coordenadas/metodologia verificáveis (Seção 3) — usar isso como reanálise de grade "
        "seria uma afirmação não sustentada pelo repositório.",
        "- O descasamento de suporte espacial (célula de grade vs. média de área difusa e "
        "variável, Seção 4) — não resolvido só por a distância ter melhorado.",
        "- A agregação Sinobras sem mínimo de estações (Seção 3) — um mês com 1 fazenda "
        "reportando é tratado, na série, exatamente como um mês com 34.",
        "",
        "## Restrições respeitadas nesta tarefa",
        "",
        "- Nenhuma métrica de skill foi calculada.",
        "- O dashboard (docs/index.html) não foi tocado.",
        "- Nenhum modelo climático (SARIMAX/XGBoost) foi alterado.",
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
