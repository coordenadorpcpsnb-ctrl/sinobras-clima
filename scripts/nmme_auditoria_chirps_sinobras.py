#!/usr/bin/env python3
"""
nmme_auditoria_chirps_sinobras.py — Fase 2C.2, investigação dedicada
da reinterpretação CHIRPS (4ª rodada, 2026) e do refinamento zonal
(5ª rodada, 2026).

Contexto (4ª rodada): o responsável pelos dados informou que
SINOBRAS.csv (registros por fazenda, 1996-2025, já auditado por
scripts/nmme_auditoria_sinobras_por_fazenda.py) contém ESTIMATIVAS
extraídas do CHIRPS por fazenda — não leituras diretas de pluviômetro.
A empresa não tem pluviômetro em todas as fazendas.

Contexto (5ª rodada, refinamento): o responsável pelos dados confirmou
que a extração é ZONAL — média dos pixels CHIRPS contidos dentro do
polígono de CADA fazenda, não um ponto único. A versão do CHIRPS, o
critério de inclusão de pixel na borda do polígono, o tratamento de
pixel parcialmente interceptado e o processamento temporal ainda NÃO
foram verificados documentalmente.

Este módulo:
1. Compara `data/serie_subst.csv` (que reproduz SINOBRAS.csv para
   1996-2025, achado já verificado em rodada anterior) com
   `data/chirps_1981_2025.csv` — um CHIRPS de METODOLOGIA CONHECIDA
   (ClimateSERV, dataset 0, ponto único no centroide das fazendas,
   ~0,05° de resolução; ver scripts/backfill_chirps_historico.py),
   já extraído neste repositório para o MESMO ponto. Nunca presume
   que os dois vêm da mesma metodologia — só compara.
2. Lista as informações necessárias para reproduzir a extração de
   SINOBRAS.csv (versão do CHIRPS, polígono por fazenda, critério de
   inclusão/tratamento de pixel na borda, processamento temporal,
   unidades).
3. Compara METODOLOGICAMENTE (5ª rodada) três alternativas de
   referência regional apontadas pelo responsável pelos dados — média
   simples das 34 fazendas (atual), média ponderada por área do
   polígono, e média zonal sobre a união dos polígonos — e a
   possibilidade (inverificável sem os polígonos) de sobreposição
   espacial entre eles. Nenhuma das três é calculada ou implementada.
   Ajuste final (2026): a ausência de sobreposição entre os polígonos
   é NECESSÁRIA mas NÃO SUFICIENTE para a média ponderada por área e a
   média zonal sobre a união coincidirem — a equivalência também
   depende do critério de inclusão/ponderação de pixel ser o mesmo nos
   dois cálculos. Nenhuma das três alternativas é classificada como
   universalmente mais correta — a escolha depende de qual variável
   espacial se pretende representar.
4. Avalia a viabilidade técnica de uma referência CHIRPS espacial e
   temporalmente consistente para 1991-2011, informada pelas
   capacidades JÁ EXISTENTES de scripts/_chirps.py (nunca executa uma
   nova extração — isso seria substituir a referência observacional
   atual, fora do escopo desta tarefa).
5. Audita o CÓDIGO (não os dados, nenhuma extração nova) de
   scripts/_chirps.py — tratamento de valor ausente do ClimateSERV,
   agregação diária→mensal sem cobertura mínima, e a geometria da
   caixa usada na extração central — distinguindo o que está
   CONFIRMADO por leitura de código do que continua PENDENTE de
   verificação. Nenhuma alteração de comportamento do pipeline de
   produção é feita aqui — só diagnóstico e proposta de correção.

Nunca calcula skill, nunca recalcula previsões/indicadores de
desempenho, nunca substitui a referência observacional de produção,
nunca modifica dados históricos, nunca altera o dashboard ou os
modelos climáticos, nunca implementa nenhuma das três alternativas
metodológicas — só lê data/chirps_1981_2025.csv e data/serie_subst.csv
(ambos já no repositório) e escreve um relatório técnico + tabelas de
auditoria em artifacts/.

Roda com:
    python scripts/nmme_auditoria_chirps_sinobras.py --dry-run-plan
    python scripts/nmme_auditoria_chirps_sinobras.py --gerar-relatorio
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

import nmme_piloto_historico as pilo  # noqa: E402

ARTIFACTS_DIR = ROOT / 'artifacts' / 'nmme_auditoria_chirps_sinobras'
RELATORIO_DOC_PATH = ROOT / 'docs' / 'nmme-fase2c2-auditoria-chirps-sinobras.md'

CHIRPS_PONTO_PATH = ROOT / 'data' / 'chirps_1981_2025.csv'
SERIE_PRODUCAO_PATH = pilo.SERIE_OBSERVACIONAL_PATH   # data/serie_subst.csv

ANO_FIM_MERRA2 = pilo.ANO_FIM_MERRA2   # 1995

# Metodologia do CHIRPS já extraído neste repositório (verificada por
# leitura de código em scripts/_chirps.py/backfill_chirps_historico.py
# — nunca assumida). Citada aqui como fato JÁ CONHECIDO, para contraste
# explícito com a metodologia de SINOBRAS.csv, que é DESCONHECIDA.
METODOLOGIA_CHIRPS_PONTO_CONHECIDA = {
    'fonte': 'CHIRPS (UCSB), via ClimateSERV, dataset 0',
    'geometria': 'ponto único no centroide das fazendas (lat=-7.80, lon=-47.95)',
    'resolucao_graus': 0.05,
    'script': 'scripts/_chirps.py::buscar_prec_chirps',
    'backfill_historico': 'scripts/backfill_chirps_historico.py (execução única, já rodada)',
    'versao_chirps_pinada': False,   # ClimateSERV serve a versão corrente — não travada/documentada
    'data_extracao_documentada': False,   # backfill_chirps_historico.py não grava a data de execução
}


# ══════════════════════════════════════════════════════════════════════════
# Item 5 — comparar data/chirps_1981_2025.csv com a série consolidada
# ══════════════════════════════════════════════════════════════════════════

def carregar_chirps_ponto(caminho=CHIRPS_PONTO_PATH):
    """Só leitura — nunca modifica data/chirps_1981_2025.csv."""
    return pd.read_csv(caminho)


def carregar_serie_producao(caminho=SERIE_PRODUCAO_PATH):
    """Só leitura — nunca modifica data/serie_subst.csv."""
    return pd.read_csv(caminho)


def comparar_chirps_ponto_com_serie_producao(chirps_df, serie_df):
    """Item 5 — compara os dois SEM presumir que vêm da mesma
    metodologia. `data/chirps_1981_2025.csv` é CHIRPS de metodologia
    CONHECIDA (ponto único, ClimateSERV); `data/serie_subst.csv`
    reproduz SINOBRAS.csv para 1996-2025 (achado já verificado por
    scripts/nmme_auditoria_sinobras_por_fazenda.py) e o backfill
    MERRA-2/3-municípios para <=1995. Separa a comparação por período
    — nunca um número agregado único que esconderia divergência de
    comportamento entre os dois trechos."""
    merged = serie_df.merge(chirps_df, on=['ano', 'mes'], suffixes=('_serie', '_chirps_ponto'),
                             how='inner')
    merged['diff_abs_mm'] = (merged['prec_serie'] - merged['prec_chirps_ponto']).abs()
    merged['razao_serie_sobre_chirps'] = (
        merged['prec_serie'] / merged['prec_chirps_ponto'].replace(0, pd.NA))

    def _resumo(sub):
        n = len(sub)
        if not n:
            return {'n_meses': 0, 'diff_abs_media_mm': None, 'diff_abs_maxima_mm': None,
                     'correlacao': None, 'razao_mediana': None,
                     'n_meses_identicos_diff_menor_0_01mm': 0}
        return {
            'n_meses': int(n),
            'diff_abs_media_mm': round(float(sub['diff_abs_mm'].mean()), 2),
            'diff_abs_maxima_mm': round(float(sub['diff_abs_mm'].max()), 2),
            'correlacao': round(float(sub['prec_serie'].corr(sub['prec_chirps_ponto'])), 4),
            'razao_mediana': round(float(sub['razao_serie_sobre_chirps'].median()), 3),
            'n_meses_identicos_diff_menor_0_01mm': int((sub['diff_abs_mm'] < 0.01).sum()),
        }

    pos_1996 = merged[merged['ano'] > ANO_FIM_MERRA2]
    pre_1996 = merged[merged['ano'] <= ANO_FIM_MERRA2]
    resumo_pos = _resumo(pos_1996)
    resumo_pre = _resumo(pre_1996)

    return {
        'n_meses_comparados_total': int(len(merged)),
        'periodo_pos_1996': resumo_pos,
        'periodo_pre_1996': resumo_pre,
        'interpretacao': (
            f"{len(merged)} meses comparáveis entre data/serie_subst.csv (que reproduz "
            "SINOBRAS.csv para 1996-2025) e data/chirps_1981_2025.csv (CHIRPS de metodologia "
            "CONHECIDA, ponto único no centroide das fazendas). Pós-1996: correlação "
            f"{resumo_pos['correlacao']}, razão mediana {resumo_pos['razao_mediana']}, mas só "
            f"{resumo_pos['n_meses_identicos_diff_menor_0_01mm']}/{len(pos_1996)} meses "
            "IDÊNTICOS — a correlação alta e a razão mediana próxima de 1 são CONSISTENTES com "
            "ambas as séries terem origem CHIRPS, mas a ausência de identidade numérica mês a "
            "mês mostra que NÃO são a mesma extração. Revisão pontual (5ª rodada, 2026): uma "
            "das causas dessa não-identidade deixou de ser hipótese — o responsável pelos dados "
            "confirmou que SINOBRAS.csv é extração ZONAL (média dos pixels dentro do polígono de "
            "cada fazenda), enquanto data/chirps_1981_2025.csv é PONTUAL (1 valor no centroide "
            "agregado); ponto vs. zonal é agora um FATO conhecido, não uma das possibilidades em "
            "aberto. As demais causas seguem em aberto, nenhuma confirmada: versão diferente do "
            "CHIRPS servida pelo ClimateSERV, critério de inclusão de pixel na borda do polígono, "
            "e processamento temporal diferente (ver item 3 abaixo). Pré-1996: correlação "
            f"{resumo_pre['correlacao']} — mais alta ainda que pós-1996, um achado "
            "curioso que NÃO deve ser lido como prova de que o trecho MERRA-2/3-municípios "
            "também é CHIRPS (isso permanece não comprovado, item 7 da tarefa) — só registrado "
            "aqui como observação para investigação futura."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Item 4 — informações necessárias para reproduzir a extração de SINOBRAS.csv
# ══════════════════════════════════════════════════════════════════════════

def montar_lista_informacoes_necessarias_reproducao():
    """Item 4 — lista OBJETIVA (não computada) do que falta para
    reproduzir a extração que gerou SINOBRAS.csv. Cada item contrasta
    explicitamente com o que JÁ é conhecido para
    data/chirps_1981_2025.csv (METODOLOGIA_CHIRPS_PONTO_CONHECIDA),
    para deixar claro que ter UM CHIRPS no repositório não supre a
    necessidade de conhecer o OUTRO.

    Revisão pontual (5ª rodada, 2026) — o responsável pelos dados
    confirmou que a extração é ZONAL (média dos pixels dentro do
    polígono de cada fazenda). Isso RESOLVE parcialmente o antigo item
    de "resolução/regra de agregação espacial" (já sabemos que é
    zonal, não pontual) mas ABRE dois itens mais específicos: o
    critério de inclusão de pixel na borda do polígono, e o
    tratamento de pixels parcialmente interceptados — nenhum dos dois
    confirmado."""
    return [
        "Versão do produto CHIRPS usada para gerar SINOBRAS.csv (ex.: CHIRPS v2.0 Final vs. "
        "Preliminary) e a data de extração. Contraste: nem mesmo data/chirps_1981_2025.csv "
        "(extraído NESTE repositório) tem isso documentado — ClimateSERV serve a versão "
        "corrente, sem versionamento explícito registrado em "
        "scripts/backfill_chirps_historico.py. PENDENTE.",
        "Polígono usado para extrair a estimativa ZONAL de CADA uma das 34 fazendas (não uma "
        "coordenada única — a extração é confirmadamente zonal) — SINOBRAS.csv não traz "
        "polígonos nem coordenadas (achado de scripts/nmme_auditoria_sinobras_por_fazenda.py). "
        "Sem isso, não é possível saber se os grupos de séries idênticas (FAZ02/03/04/05/08/"
        "09/19 e FAZ07/FAZ15) correspondem a fazendas cujos polígonos cobrem o MESMO conjunto "
        "de pixels CHIRPS. PENDENTE.",
        "RESOLVIDO (5ª rodada): a agregação espacial é ZONAL — média dos pixels CHIRPS dentro "
        "do polígono de cada fazenda (CHIRPS nativo 0,05°, ~5,5km no equador), confirmado pelo "
        "responsável pelos dados. Contraste: data/chirps_1981_2025.csv (já extraído neste "
        "repositório) é PONTUAL — 1 valor no centroide agregado, uma metodologia diferente por "
        "desenho, não uma dúvida a resolver.",
        "Critério de inclusão de pixel na borda do polígono — centro do pixel dentro do "
        "polígono? qualquer sobreposição, por menor que seja? fração de área ponderada? — "
        "determina quantos pixels entram na média de cada fazenda. PENDENTE.",
        "Tratamento de pixels parcialmente interceptados pela borda do polígono — incluídos "
        "por inteiro, excluídos, ou ponderados pela fração de área dentro do polígono? "
        "PENDENTE.",
        "Processamento temporal — CHIRPS nativo é diário; confirmar a regra de agregação "
        "diária→mensal (soma simples do mês? exigência de cobertura mínima de dias válidos?). "
        "PENDENTE.",
        "Unidades e arredondamento — SINOBRAS.csv está em mm/mês, valores inteiros; CHIRPS "
        "nativo é mm/dia. Confirmar se o arredondamento para inteiro foi feito na extração ou "
        "em uma etapa posterior (perda de precisão relevante para meses de chuva baixa, ex.: "
        "jul/ago, onde CLAUDE.md armadilha 7 já documenta viés conhecido de fontes de satélite). "
        "PENDENTE.",
        "Ferramenta/serviço de extração usado (ClimateSERV, como este repositório usa? Google "
        "Earth Engine? download direto dos GeoTIFFs do CHIRPS?) — determina quais dos vieses "
        "conhecidos de ClimateSERV (CLAUDE.md armadilha 7, tabela ERA5/CHIRPS por mês) se "
        "aplicam ou não a SINOBRAS.csv. PENDENTE.",
        "Confirmação de quais das 34 fazendas — se alguma — têm, além da estimativa CHIRPS, um "
        "pluviômetro físico real instalado; a empresa não tem pluviômetro em todas. PENDENTE.",
    ]


# ══════════════════════════════════════════════════════════════════════════
# Itens 4/5/6 da 5ª rodada — comparação metodológica de três alternativas
# de referência regional (SEM calcular ou implementar nenhuma delas)
# ══════════════════════════════════════════════════════════════════════════

def comparar_tres_alternativas_metodologicas():
    """5ª rodada (2026), atividades 5 e 6 — compara METODOLOGICAMENTE
    (nunca computa, nunca implementa) as três possibilidades de
    referência regional apontadas pelo responsável pelos dados:

        (a) média simples das estimativas das 34 fazendas — a
            metodologia HISTÓRICA, já em produção
            (`df_new.groupby(['ano','mes'])['prec_mm'].mean()` em
            scripts/update_dashboard.py), peso IGUAL por fazenda,
            independente da área do seu polígono;
        (b) média das estimativas das 34 fazendas ponderada pela
            respectiva área do polígono;
        (c) média zonal diretamente sobre a UNIÃO dos polígonos das 34
            fazendas, contando cada parcela espacial (pixel) uma única
            vez, não uma soma/média de 34 médias por fazenda.

    Atividade 6 é explícita: "Não implementar automaticamente nenhuma
    das alternativas. Primeiro, avaliar suas diferenças metodológicas
    e a possibilidade de sobreposição espacial." Esta função só avalia
    — nenhuma das três alternativas é calculada ou escrita em nenhum
    arquivo de dados por este módulo.

    Ponto central, matemático: (a) e (b) só coincidem entre si se as 34
    fazendas tiverem área IGUAL (o que não se pode presumir sem os
    polígonos).

    Revisão pontual (ajuste final, 2026) — a condição para (b)/(c)
    coincidirem é mais exigente do que "sem sobreposição": a ausência
    de sobreposição espacial entre os polígonos é NECESSÁRIA, mas
    SOZINHA NÃO É SUFICIENTE. (b) e (c) só coincidem se DUAS condições
    valerem ao mesmo tempo: (i) os 34 polígonos NÃO se sobrepõem
    espacialmente (sobreposição faria (b) contar a área compartilhada
    mais de uma vez, proporcionalmente a quantas fazendas a
    compartilham — (c) conta cada parcela uma única vez por desenho);
    E (ii) o critério de inclusão/ponderação de pixel usado para
    calcular a estimativa zonal de CADA fazenda (o insumo de (b)) é o
    MESMO critério usado no cálculo direto sobre a união (c) — mesma
    regra para pixel na borda, mesmo tratamento de pixel parcialmente
    interceptado. Sem (ii), (b) e (c) podem divergir mesmo com
    polígonos que não se sobrepõem — ex.: um pixel poderia ser incluído
    por inteiro na fazenda cujo centro do pixel cai dentro do polígono
    (critério "centro dentro"), mas ter sua contribuição fracionada de
    outra forma no cálculo direto sobre a união (critério "fração de
    área"). Nenhuma das duas condições é verificável hoje: (i) exige os
    polígonos, que este repositório decidiu deliberadamente não manter
    (CLAUDE.md armadilha 8); (ii) exige o critério de inclusão de
    pixel, item ainda PENDENTE (ver
    montar_lista_informacoes_necessarias_reproducao()). Consequência:
    NENHUMA das três alternativas deve ser classificada como
    universalmente "mais correta" — cada uma responde a uma pergunta
    espacial diferente (ver 'qual_alternativa_e_mais_correta' no
    retorno desta função); a escolha depende de qual variável se
    pretende representar, não de uma hierarquia de precisão."""
    alternativa_a = {
        'nome': 'Média simples das 34 estimativas por fazenda (metodologia histórica, atual)',
        'formula': 'média aritmética simples de prec_mm entre as 34 fazendas, por ano/mês',
        'onde_ja_esta_implementada': "scripts/update_dashboard.py — "
                                      "df_new.groupby(['ano','mes'])['prec_mm'].mean()",
        'peso_por_fazenda': 'IGUAL para todas as 34 fazendas, independente da área do polígono',
        'requisito_de_dados_adicional': 'nenhum — já é a série de produção (data/serie_subst.csv)',
        'representa_area_real_quando': 'as 34 fazendas têm área igual entre si (não verificável '
                                        'sem os polígonos) E os polígonos não se sobrepõem',
    }
    alternativa_b = {
        'nome': 'Média das 34 estimativas por fazenda, ponderada pela área do polígono',
        'formula': 'média ponderada de prec_mm entre as 34 fazendas, peso = área do polígono de '
                    'cada fazenda, por ano/mês',
        'onde_ja_esta_implementada': 'em nenhum lugar — não existe neste repositório',
        'peso_por_fazenda': 'proporcional à área do polígono de cada fazenda',
        'requisito_de_dados_adicional': 'a área do polígono de cada uma das 34 fazendas — não '
                                         'disponível neste repositório (CLAUDE.md armadilha 8)',
        'representa_area_real_quando': 'os polígonos das 34 fazendas não se sobrepõem entre si E '
                                        '(condição adicional, não só a ausência de sobreposição) '
                                        'o critério de inclusão/ponderação de pixel usado na '
                                        'estimativa zonal de cada fazenda é o mesmo que seria '
                                        'usado num cálculo direto sobre a união dos polígonos — '
                                        'nenhuma das duas condições verificável sem os polígonos '
                                        'e sem o critério de inclusão de pixel (ambos ausentes)',
    }
    alternativa_c = {
        'nome': 'Média zonal direta sobre a união dos 34 polígonos',
        'formula': 'média dos pixels CHIRPS contidos na união geométrica dos 34 polígonos, cada '
                    'pixel contado uma única vez, independente de quantas fazendas ele toque',
        'onde_ja_esta_implementada': 'em nenhum lugar — scripts/_chirps.py::'
                                      'buscar_prec_chirps_zonal existe, mas opera sobre o '
                                      'envelope ÚNICO e ANONIMIZADO das 34 fazendas (CLAUDE.md '
                                      'armadilha 8), não sobre a união exata dos 34 polígonos '
                                      'individuais — o envelope é MAIOR que essa união (85.020,5 '
                                      'ha vs. 48.737,3 ha da união dos 37 perímetros reais '
                                      'antigos, por preencher reentrâncias entre fazendas)',
        'peso_por_fazenda': 'não se aplica — não é uma média DE fazendas, é uma média direta '
                             'sobre o espaço; equivale a ponderar por área só no caso sem '
                             'sobreposição',
        'requisito_de_dados_adicional': 'os 34 polígonos individuais (para a união exata) OU o '
                                         'envelope único já existente (para uma aproximação '
                                         'MAIOR que a união real, com área desconhecida de quanto '
                                         'excede) + uma extração zonal nova sobre essa geometria',
        'representa_area_real_quando': 'sempre — é a definição de área real, por construção; não '
                                        'depende de as fazendas terem área igual nem de ausência '
                                        'de sobreposição',
    }
    possibilidade_sobreposicao = {
        'verificavel_com_os_dados_atuais': False,
        'motivo': 'sobreposição espacial entre polígonos de fazenda só é verificável com os '
                  'polígonos em mãos — este repositório não os mantém (CLAUDE.md armadilha 8, '
                  'decisão deliberada de anonimização)',
        'sinal_indireto_disponivel': 'os 2 grupos de séries mensais idênticas identificados em '
                                      'scripts/nmme_auditoria_sinobras_por_fazenda.py '
                                      '(FAZ02/03/04/05/08/09/19 e FAZ07/FAZ15) são um sinal de '
                                      'que ALGUMAS fazendas compartilham o mesmo CONJUNTO DE '
                                      'PIXELS CHIRPS cobertos — mas isso NÃO é a mesma coisa que '
                                      'sobreposição de POLÍGONO: polígonos vizinhos, sem nenhuma '
                                      'sobreposição de área, podem ainda assim cair sobre os '
                                      'mesmos pixels grosseiros do CHIRPS (0,05°, ~5,5km) se '
                                      'forem pequenos e próximos. Compartilhar pixel NÃO implica '
                                      'sobrepor polígono, e sobrepor polígono não é a única causa '
                                      'possível de série idêntica — nenhuma das duas é presumida '
                                      'aqui.',
        'interpretacao': 'a possibilidade de sobreposição espacial entre os polígonos das 34 '
                          'fazendas permanece EM ABERTO, nem confirmada nem descartada — este '
                          'módulo não afirma que existe, nem que não existe.',
        'ausencia_de_sobreposicao_e_suficiente_para_b_igual_c': False,
        'motivo_nao_suficiente': (
            'mesmo SEM nenhuma sobreposição entre os polígonos, (b) e (c) só coincidem se o '
            'critério de inclusão/ponderação de pixel usado para calcular a estimativa zonal '
            'de CADA fazenda (o insumo de (b)) for IDÊNTICO ao critério usado no cálculo '
            'direto sobre a união dos polígonos (c) — mesma regra para pixel na borda, mesmo '
            'tratamento de pixel parcialmente interceptado. Esse critério é hoje DESCONHECIDO '
            'para SINOBRAS.csv (ver montar_lista_informacoes_necessarias_reproducao()), então '
            'a equivalência entre (b) e (c) não pode ser presumida nem mesmo se a ausência de '
            'sobreposição um dia for confirmada.'
        ),
    }
    qual_alternativa_e_mais_correta = (
        'NENHUMA é universalmente mais correta — cada uma responde a uma pergunta espacial '
        'diferente, não são três aproximações da mesma resposta com precisão crescente: (a) '
        'responde "qual a chuva média entre unidades de manejo (fazendas), tratando cada uma '
        'com peso igual, independente do tamanho"; (b) responde "qual a chuva média entre as '
        'estimativas por fazenda, ponderada pela área de cada unidade de manejo"; (c) responde '
        '"qual a chuva média sobre o espaço físico total coberto pelas fazendas, cada parcela '
        'contando uma única vez, independente de quantas fazendas a reivindicam". A escolha '
        'certa depende de qual dessas três variáveis o uso pretendido (ex.: balanço hídrico '
        'por fazenda vs. balanço hídrico regional agregado vs. comparação com a célula de '
        'grade do CFSv2) precisa representar — não de uma hierarquia de exatidão onde uma '
        'alternativa sempre vence as outras duas.'
    )
    return {
        'alternativa_a_media_simples_atual': alternativa_a,
        'alternativa_b_media_ponderada_por_area': alternativa_b,
        'alternativa_c_zonal_sobre_uniao': alternativa_c,
        'possibilidade_de_sobreposicao_espacial': possibilidade_sobreposicao,
        'nenhuma_alternativa_calculada_ou_implementada': True,
        'qual_alternativa_e_mais_correta': qual_alternativa_e_mais_correta,
        'interpretacao': (
            "As três alternativas NÃO são intercambiáveis por desenho, e nenhuma foi calculada "
            "ou implementada aqui (atividade 6). (a), a metodologia histórica em produção, dá "
            "peso IGUAL às 34 fazendas independente de área — diverge de (b) sempre que as áreas "
            "das fazendas forem desiguais (o que não se pode presumir sem os polígonos, mas é "
            "improvável que 34 fazendas tenham área exatamente igual). (b) e (c) só coincidem "
            "entre si se DUAS condições valerem ao mesmo tempo — não uma só: os 34 polígonos NÃO "
            "se sobrepõem espacialmente E o critério de inclusão/ponderação de pixel é o MESMO "
            "nos dois cálculos. A ausência de sobreposição, sozinha, NÃO garante a equivalência: "
            "com sobreposição, (b) conta a área compartilhada mais de uma vez (proporcionalmente "
            "a quantas fazendas a reivindicam), enquanto (c) conta cada parcela espacial uma "
            "única vez, por construção — mas mesmo SEM sobreposição, um critério de inclusão de "
            "pixel diferente entre o cálculo por fazenda (que alimenta (b)) e o cálculo direto "
            "sobre a união (c) já basta para as duas divergirem. NENHUMA das três alternativas "
            "deve ser classificada como universalmente mais correta (ver "
            "'qual_alternativa_e_mais_correta' acima) — a escolha depende de qual variável "
            "espacial se pretende representar. Construir (b) ou (c) exige infraestrutura que não "
            "existe hoje: os 34 polígonos individuais (ou, como aproximação com área desconhecida "
            "de erro, o envelope único e anonimizado), o critério de inclusão de pixel (ainda "
            "PENDENTE) e, para (c), uma extração zonal nova sobre essa geometria. A possibilidade "
            "de sobreposição espacial entre os polígonos é HOJE INVERIFICÁVEL sem os próprios "
            "polígonos — o sinal indireto disponível (grupos de séries mensais idênticas) indica "
            "compartilhamento de PIXEL, não necessariamente sobreposição de POLÍGONO, e as duas "
            "coisas não devem ser confundidas. Nenhuma decisão sobre qual alternativa adotar é "
            "tomada aqui — essa é uma decisão explícita e futura, condicionada a primeiro obter "
            "os polígonos e o critério de inclusão de pixel (o que por sua vez exige revisitar "
            "CLAUDE.md armadilha 8) e/ou aceitar a aproximação do envelope único já existente."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Item 6 — viabilidade de uma referência CHIRPS consistente para 1991-2011
# ══════════════════════════════════════════════════════════════════════════

def avaliar_viabilidade_referencia_chirps_1991_2011():
    """Item 6 — avaliação de VIABILIDADE TÉCNICA, nunca uma execução.
    Este módulo NUNCA chama o ClimateSERV nem qualquer rede — isso
    seria uma nova extração, fora do escopo desta tarefa (a referência
    observacional de produção não pode ser substituída
    automaticamente). Informada pelas capacidades JÁ EXISTENTES e já
    exercitadas de scripts/_chirps.py e
    scripts/backfill_chirps_historico.py.

    Revisão pontual (5ª rodada, 2026) — com a extração ZONAL de
    SINOBRAS.csv confirmada (não mais hipotética), a ressalva (2)
    abaixo deixou de ser "ponto vs. zonal, possibilidade em aberto" e
    passou a ser um FATO: data/chirps_1981_2025.csv é ponto único,
    SINOBRAS.csv é zonal por polígono — são metodologias DIFERENTES
    por desenho, não uma dúvida a resolver. Reproduzir a metodologia
    de SINOBRAS.csv exigiria extração zonal POR FAZENDA INDIVIDUAL —
    que colide com a decisão deliberada de CLAUDE.md armadilha 8 de
    não manter polígonos por fazenda neste repositório (anonimização)."""
    ja_disponivel = CHIRPS_PONTO_PATH.exists()
    n_meses_1991_2011 = None
    if ja_disponivel:
        chirps_df = carregar_chirps_ponto()
        cobertos = chirps_df[(chirps_df['ano'] >= 1991) & (chirps_df['ano'] <= 2011)]
        n_meses_1991_2011 = int(len(cobertos))
    return {
        'data_chirps_1981_2025_ja_cobre_1991_2011': ja_disponivel,
        'n_meses_1991_2011_ja_extraidos': n_meses_1991_2011,
        'n_meses_1991_2011_esperados': 252,   # 21 anos completos x 12
        'metodologia_ja_extraida_e_pontual_nao_zonal': True,
        'poligonos_por_fazenda_conflitam_com_claude_md_armadilha_8': True,
        'ferramentas_ja_existentes': {
            'ponto_unico': 'scripts/_chirps.py::buscar_prec_chirps — já usado para gerar '
                            'data/chirps_1981_2025.csv',
            'zonal_envelope': 'scripts/_chirps.py::buscar_prec_chirps_zonal — existe, cobre o '
                               'envelope ÚNICO e ANONIMIZADO das 34 fazendas (CLAUDE.md '
                               'armadilha 8), não os 34 polígonos individuais; NUNCA passou '
                               'pela suíte de falha de tests/test_fetch_fallback.py — promoção '
                               'a primário é decisão separada, não tomada aqui nem antes.',
            'zonal_por_fazenda_individual': 'NÃO EXISTE neste repositório — reproduzir a '
                                             'metodologia de SINOBRAS.csv (zonal por polígono '
                                             'de CADA fazenda) exigiria 34 extrações zonais '
                                             'individuais, uma função ainda não escrita, e 34 '
                                             'polígonos que o projeto decidiu deliberadamente '
                                             'não manter no repositório.',
            'quebra_em_blocos': 'scripts/backfill_chirps_historico.py já resolve a limitação de '
                                 'período (ClimateSERV rejeita ~45 anos numa chamada só) — o '
                                 'padrão de blocos de ~10 anos já está implementado e testado '
                                 'contra o servidor real.',
        },
        'interpretacao': (
            "TECNICAMENTE VIÁVEL só para uma referência PONTUAL — nunca executado aqui. "
            f"data/chirps_1981_2025.csv JÁ COBRE 1991-2011 ({n_meses_1991_2011}/252 meses "
            "esperados) com metodologia conhecida (ponto único, centroide das fazendas, "
            "ClimateSERV). Mas essa metodologia NÃO é a mesma de SINOBRAS.csv (zonal por "
            "polígono de fazenda, confirmado pelo responsável pelos dados) — não é mais uma "
            "ressalva em aberto, é um fato: comparar as duas sem marcar essa diferença seria "
            "comparar metodologias distintas como se fossem a mesma. Ressalvas: (1) a VERSÃO "
            "do CHIRPS servida pelo ClimateSERV pode ter mudado desde a extração original (não "
            "versionada, não documentada — mesma lacuna que impede reproduzir SINOBRAS.csv, "
            "item 4 acima); reextrair hoje pode não bater byte a byte com o arquivo já salvo; "
            "(2) reproduzir a metodologia ZONAL POR FAZENDA de SINOBRAS.csv exigiria: (a) os "
            "34 polígonos individuais, que o projeto decidiu deliberadamente NÃO manter neste "
            "repositório (CLAUDE.md armadilha 8 — anonimização, decisão que precisaria ser "
            "revisitada explicitamente, não contornada); e (b) uma função de extração zonal "
            "POR FAZENDA que ainda não existe (buscar_prec_chirps_zonal hoje opera só sobre o "
            "envelope único anonimizado, não 34 polígonos individuais); (3) mesmo uma "
            "referência zonal sobre a UNIÃO do envelope (sem precisar dos 34 polígonos "
            "individuais) teria o problema de buscar_prec_chirps_zonal nunca ter passado pela "
            "suíte de falha de tests/test_fetch_fallback.py; (4) qualquer uma dessas "
            "referências, se construída, SUBSTITUIRIA a referência observacional atual — "
            "decisão explícita que este módulo NÃO toma (restrição desta tarefa). Próximo "
            "passo recomendado, se aprovado no futuro: (a) reextrair 1991-2011 com "
            "buscar_prec_chirps (ponto) e comparar contra o data/chirps_1981_2025.csv já "
            "salvo para confirmar estabilidade de versão; (b) decidir explicitamente se manter "
            "polígonos por fazenda é aceitável (revisão da armadilha 8) antes de cogitar "
            "reproduzir a metodologia zonal por fazenda; (c) rodar buscar_prec_chirps_zonal "
            "pela suíte de falha de tests/test_fetch_fallback.py antes de considerar promover "
            "qualquer variante zonal a primário."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Ajuste final (2026) — auditoria do CÓDIGO da extração central existente
# (scripts/_chirps.py), distinguindo o CONFIRMADO do PENDENTE
# ══════════════════════════════════════════════════════════════════════════

def auditar_extracao_chirps_central_existente():
    """Ajuste final (2026) — inspeciona scripts/_chirps.py por LEITURA
    DE CÓDIGO (nenhuma chamada de rede, nenhuma nova extração) e
    reporta, separadamente, o que está CONFIRMADO (fato verificável no
    código-fonte ou por aritmética exata) do que continua PENDENTE
    (depende de documentação externa não disponível aqui — ex.: a
    convenção de alinhamento do grid CHIRPS).

    Os três achados CONFIRMADOS têm reprodução sintética em
    tests/test_chirps_extracao_sintetica.py (mockando
    climateserv.api.request_data — nenhuma rede real):

    1. `(r.get('value') or {}).get('avg') or 0.0` em
       _buscar_prec_chirps_geom trata um dia SEM DADO (avg ausente ou
       None) exatamente como um dia de chuva real ZERO — mesmo valor
       de saída, nenhum sinal de qual dos dois ocorreu. Viola o
       princípio já aplicado a TSA/PDO (CLAUDE.md armadilha 6: "0.0 é
       uma afirmação, não um vazio").
    2. A agregação diária→mensal (`.groupby(['ano','mes'])['prec'].sum()`)
       não exige nenhuma cobertura mínima de dias, e o DataFrame
       retornado não carrega nenhuma coluna de contagem/cobertura —
       um mês com 1 dia de dado e um mês com 31 são indistinguíveis na
       saída. Dias OMITIDOS inteiramente da resposta (nem como None)
       são um segundo modo de incompletude, igualmente sem sinal.
    3. FAZENDAS_LAT (-7.80) e FAZENDAS_LON (-47.95) são múltiplos
       EXATOS da resolução do CHIRPS (0.05°) nos dois eixos (aritmética
       exata, Decimal) — condição geométrica que, dependendo da
       convenção de alinhamento do grid CHIRPS (não verificada aqui),
       pode pôr o ponto central sobre uma borda ou quina de pixel, ao
       contrário do que o comentário de `_geometria_ponto` presume
       ("a média do polígono equivale ao valor do pixel que contém o
       ponto").

    NENHUMA alteração de comportamento é feita em scripts/_chirps.py
    por esta função — só um comentário explicativo foi adicionado no
    código-fonte, apontando para este achado (documentação, não
    correção). A correção proposta abaixo NÃO é aplicada — corrigir o
    pipeline de produção exige apresentar antes o impacto e a proposta,
    que é exatamente o que este achado faz; aplicar a correção em si é
    uma decisão separada, fora do escopo desta tarefa."""
    return {
        'metodo_de_auditoria': 'leitura de código-fonte + testes sintéticos mockados — '
                                'nenhuma chamada de rede, nenhuma nova extração',
        'testes_sinteticos': 'tests/test_chirps_extracao_sintetica.py (9 testes)',
        'confirmado_valor_ausente_pode_virar_zero': True,
        'confirmado_zero_real_e_ausencia_sao_indistinguiveis_na_saida': True,
        'confirmado_sem_cobertura_minima_de_dias_exigida': True,
        'confirmado_resultado_sem_coluna_de_contagem_de_dias': True,
        'confirmado_dias_omitidos_tambem_nao_contam_nem_sinalizam': True,
        'confirmado_ponto_central_e_multiplo_exato_da_resolucao_chirps': True,
        'pendente_convencao_de_alinhamento_do_grid_chirps': (
            'se os pixels do CHIRPS têm CENTRO em múltiplos de 0,05° (caso em que o ponto '
            'central cairia exatamente numa quina compartilhada por até 4 pixels) ou BORDA em '
            'múltiplos de 0,05° (caso em que o ponto cairia exatamente sobre uma borda) — as '
            'duas convenções são comuns em produtos gridded, e a diferença muda a conclusão '
            'sobre se a caixa de _geometria_ponto (delta=0,01°) cruza para um pixel vizinho. '
            'Não verificado aqui — exigiria documentação técnica do grid CHIRPS, não uma nova '
            'extração de precipitação, então poderia em princípio ser resolvido sem violar a '
            'restrição desta tarefa, mas não foi verificado nesta rodada.'
        ),
        'impacto': (
            'RISCO, não comprovado que já tenha se manifestado nos dados hoje salvos em '
            'data/chirps_1981_2025.csv — não há evidência de que o ClimateSERV alguma vez '
            'tenha retornado avg=None para um dia dentro do período já extraído; o achado é '
            'sobre o CÓDIGO (o que aconteceria SE isso ocorrer), não uma afirmação de que os '
            'dados já extraídos estão errados. Se o ClimateSERV retornar dias com avg ausente '
            '(rede instável, processamento parcial do lado do serviço, dia realmente sem '
            'cobertura de satélite), o mês correspondente seria subestimado silenciosamente, '
            'sem nenhum aviso no log nem qualquer coluna que permita a um usuário futuro '
            'auditar a cobertura de dias por mês.'
        ),
        'proposta_de_correcao_nao_aplicada': (
            'NÃO aplicada aqui — apresentada para avaliação futura, conforme exigido antes de '
            'qualquer mudança de comportamento do pipeline de produção. Proposta: (1) trocar '
            '`.get(\'avg\') or 0.0` por uma checagem explícita — se \'avg\' ausente ou None, '
            'marcar o dia como NaN (não 0.0) e excluí-lo do numerador da soma mensal; (2) '
            'propagar no DataFrame retornado por buscar_prec_chirps/buscar_prec_chirps_zonal '
            'uma coluna adicional (ex. \'n_dias_validos\') com a contagem de dias reais '
            'usados naquele mês, para que o chamador (fetch_monthly_data.py, '
            'backfill_chirps_historico.py) possa decidir explicitamente um limiar mínimo de '
            'cobertura — mesmo padrão já usado para TSA/PDO (persistência com sinalização de '
            'origem, nunca 0.0 silencioso, CLAUDE.md armadilha 6); (3) para a geometria, '
            'confirmar documentalmente a convenção de alinhamento do grid CHIRPS antes de '
            'decidir se _geometria_ponto precisa de um delta maior ou de uma escolha '
            'explícita de qual pixel usar quando o ponto cai sobre uma borda/quina.'
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Proposta de continuidade (exigida pelas restrições desta tarefa)
# ══════════════════════════════════════════════════════════════════════════

def montar_proposta_continuidade():
    """Restrição desta tarefa — "produzir... uma proposta de
    continuidade". Lista objetiva de próximos passos, em ordem de
    esforço crescente, nenhum executado aqui.

    5ª rodada (2026) — acrescentados dois passos explícitos pedidos
    pelas atividades 5/6 do responsável pelos dados: avaliar as três
    alternativas metodológicas (e a possibilidade de sobreposição
    espacial) ANTES de implementar qualquer uma delas, e revisitar
    explicitamente CLAUDE.md armadilha 8 antes de cogitar manter
    polígonos por fazenda no repositório."""
    return [
        "Obter do responsável pelos dados um documento técnico (não apenas comunicação verbal) "
        "descrevendo a extração de SINOBRAS.csv: versão do CHIRPS, ferramenta, polígono por "
        "fazenda, critério de inclusão de pixel na borda, tratamento de pixel parcialmente "
        "interceptado, processamento temporal, unidades — ver "
        "montar_lista_informacoes_necessarias_reproducao() para a lista completa.",
        "Obter confirmação explícita de quais das 34 fazendas — se alguma — têm pluviômetro "
        "físico real, para não tratar nenhuma fazenda como instrumentada sem confirmação.",
        "Com os polígonos em mãos, verificar computacionalmente se os 2 grupos de séries "
        "idênticas (FAZ02/03/04/05/08/09/19 e FAZ07/FAZ15) correspondem a fazendas cujos "
        "polígonos cobrem o mesmo conjunto de pixels CHIRPS (0,05°) — isso confirmaria ou "
        "refutaria a hipótese de compartilhamento de pixel como explicação, sem presumir que "
        "compartilhar pixel implica sobrepor polígono (ver "
        "comparar_tres_alternativas_metodologicas()).",
        "Avaliar EXPLICITAMENTE, antes de implementar qualquer uma, as diferenças metodológicas "
        "entre as três alternativas de referência regional (média simples atual, média ponderada "
        "por área, média zonal sobre a união dos polígonos) e a possibilidade de sobreposição "
        "espacial entre os 34 polígonos — ver comparar_tres_alternativas_metodologicas() para a "
        "comparação já feita aqui, sem cálculo ou implementação de nenhuma delas. Atividade 6 "
        "desta rodada é explícita: não implementar automaticamente nenhuma alternativa.",
        "Revisitar EXPLICITAMENTE a decisão de CLAUDE.md armadilha 8 (não manter polígonos por "
        "fazenda no repositório, por anonimização) antes de cogitar qualquer alternativa que "
        "exija esses polígonos (b e c) — essa é uma decisão de privacidade/governança de dados, "
        "não uma decisão técnica, e não deve ser contornada implicitamente ao buscar os "
        "polígonos por outra via.",
        "Reextrair 1991-2011 com scripts/_chirps.py::buscar_prec_chirps (ponto único, já "
        "testado) e comparar contra data/chirps_1981_2025.csv já salvo — se os valores "
        "baterem, confirma estabilidade de versão do CHIRPS ao longo do tempo; se não baterem, "
        "documenta a divergência antes de qualquer uso científico.",
        "Rodar scripts/_chirps.py::buscar_prec_chirps_zonal pela suíte de falha de "
        "tests/test_fetch_fallback.py (hoje só cobre buscar_prec_chirps) antes de considerar "
        "promovê-lo a fonte primária para qualquer finalidade.",
        "Avaliar e, se aprovada, aplicar a proposta de correção (ajuste final, 2026) para o "
        "tratamento de valor ausente em scripts/_chirps.py — ver "
        "auditar_extracao_chirps_central_existente() — ANTES disso, apresentar o impacto real "
        "medido (não só o risco teórico já documentado) e confirmar com o responsável pelos "
        "dados se o ClimateSERV já retornou dias sem avg para o período já extraído; a correção "
        "NÃO foi aplicada nesta rodada, só diagnosticada.",
        "Só depois de tudo acima: decisão EXPLÍCITA e documentada (não automática, fora do "
        "escopo desta tarefa) sobre se/como uma referência CHIRPS construída internamente "
        "(pontual, ponderada por área, ou zonal sobre a união dos polígonos) substituiria, "
        "complementaria, ou seria reportada lado a lado com a referência observacional atual "
        "(MERRA-2/3-municípios pré-1996 + SINOBRAS.csv pós-1996) para fins de validação do "
        "CFSv2, considerando a diferença entre a célula de grade do modelo e a área representada "
        "pelos polígonos (ver descasamento_de_suporte_espacial em "
        "scripts/nmme_auditoria_observacional_historica.py).",
    ]


# ══════════════════════════════════════════════════════════════════════════
# Consolidação + relatório
# ══════════════════════════════════════════════════════════════════════════

def executar_investigacao_completa():
    chirps_df = carregar_chirps_ponto()
    serie_df = carregar_serie_producao()
    comparacao = comparar_chirps_ponto_com_serie_producao(chirps_df, serie_df)
    informacoes_necessarias = montar_lista_informacoes_necessarias_reproducao()
    tres_alternativas = comparar_tres_alternativas_metodologicas()
    viabilidade = avaliar_viabilidade_referencia_chirps_1991_2011()
    auditoria_codigo_extracao = auditar_extracao_chirps_central_existente()
    proposta_continuidade = montar_proposta_continuidade()

    metadata = {
        'fase': '2C.2 — investigação dedicada da reinterpretação CHIRPS (4ª/5ª rodadas + ajuste '
                'final, 2026)',
        'metodologia_chirps_ponto_conhecida': METODOLOGIA_CHIRPS_PONTO_CONHECIDA,
        'comparacao_chirps_ponto_vs_serie_producao': comparacao,
        'informacoes_necessarias_para_reproducao': informacoes_necessarias,
        'comparacao_tres_alternativas_metodologicas': tres_alternativas,
        'viabilidade_referencia_chirps_1991_2011': viabilidade,
        'auditoria_codigo_extracao_central_existente': auditoria_codigo_extracao,
        'proposta_de_continuidade': proposta_continuidade,
        'nenhuma_skill_calculada': True,
        'nenhuma_previsao_ou_indicador_recalculado': True,
        'nenhuma_referencia_observacional_substituida': True,
        'nenhum_dado_historico_modificado': True,
        'nenhum_dashboard_alterado': True,
        'nenhum_modelo_climatico_alterado': True,
        'nenhuma_extracao_nova_executada': True,
    }
    return metadata


def gerar_relatorio_markdown(metadata):
    meto = metadata['metodologia_chirps_ponto_conhecida']
    comp = metadata['comparacao_chirps_ponto_vs_serie_producao']
    tres = metadata['comparacao_tres_alternativas_metodologicas']
    viab = metadata['viabilidade_referencia_chirps_1991_2011']
    audcod = metadata['auditoria_codigo_extracao_central_existente']

    linhas = [
        "# Investigação CHIRPS — reinterpretação da referência observacional Sinobras",
        "",
        "**Relatório técnico — não calcula skill, não recalcula previsões/indicadores, não "
        "substitui a referência observacional atual, não altera dados históricos, dashboard "
        "nem modelos climáticos.**",
        "",
        "## Contexto",
        "",
        "O responsável pelos dados informou que SINOBRAS.csv (registros por fazenda, "
        "1996-2025, já auditado em docs/nmme-fase2c2-auditoria-sinobras-por-fazenda.md) contém "
        "ESTIMATIVAS extraídas do CHIRPS por fazenda — não leituras diretas de pluviômetro. A "
        "empresa não tem pluviômetro em todas as fazendas. Em rodada posterior, confirmou que a "
        "extração é ZONAL — média dos pixels CHIRPS dentro do polígono de CADA fazenda, não um "
        "ponto único. A classificação em docs/nmme-fase2c2-auditoria-observacional-historica.md "
        "e em scripts/nmme_piloto_historico.py foi corrigida para refletir isso (achado "
        "'reinterpretacao_chirps') — este documento é a investigação dedicada.",
        "",
        "## 1. Metodologia do CHIRPS já extraído neste repositório (referência de contraste)",
        "",
        f"- Fonte: {meto['fonte']}.",
        f"- Geometria: {meto['geometria']}.",
        f"- Resolução: {meto['resolucao_graus']}° (~5,5km no equador).",
        f"- Script: `{meto['script']}`.",
        f"- Backfill histórico: `{meto['backfill_historico']}`.",
        f"- Versão do CHIRPS pinada/documentada: {meto['versao_chirps_pinada']}. Data de "
        f"extração documentada: {meto['data_extracao_documentada']}.",
        "- Esta metodologia é CONHECIDA (verificada por leitura de código) — serve de contraste "
        "explícito: mesmo este CHIRPS, extraído dentro deste repositório, tem lacunas de "
        "versionamento. A metodologia de SINOBRAS.csv é inteiramente DESCONHECIDA.",
        "",
        "## 2. Comparação: data/chirps_1981_2025.csv × data/serie_subst.csv",
        "",
        f"- Meses comparados no total: {comp['n_meses_comparados_total']}.",
        "",
        "### Período pós-1996 (SINOBRAS.csv, agora reinterpretado como CHIRPS)",
        "",
    ]
    pos = comp['periodo_pos_1996']
    linhas += [
        f"- Meses comparados: {pos['n_meses']}.",
        f"- Diferença absoluta média: {pos['diff_abs_media_mm']} mm. Máxima: "
        f"{pos['diff_abs_maxima_mm']} mm.",
        f"- Correlação: {pos['correlacao']}. Razão mediana (série/CHIRPS-ponto): "
        f"{pos['razao_mediana']}.",
        f"- Meses numericamente idênticos (diff < 0,01mm): "
        f"{pos['n_meses_identicos_diff_menor_0_01mm']}/{pos['n_meses']}.",
        "",
        "### Período pré-1996 (MERRA-2/3-municípios — procedência não comprovada, item 7)",
        "",
    ]
    pre = comp['periodo_pre_1996']
    linhas += [
        f"- Meses comparados: {pre['n_meses']}.",
        f"- Diferença absoluta média: {pre['diff_abs_media_mm']} mm. Máxima: "
        f"{pre['diff_abs_maxima_mm']} mm.",
        f"- Correlação: {pre['correlacao']}. Razão mediana (série/CHIRPS-ponto): "
        f"{pre['razao_mediana']}.",
        f"- Meses numericamente idênticos (diff < 0,01mm): "
        f"{pre['n_meses_identicos_diff_menor_0_01mm']}/{pre['n_meses']}.",
        "",
        f"- {comp['interpretacao']}",
        "",
        "## 3. Informações necessárias para reproduzir a extração de SINOBRAS.csv",
        "",
    ]
    for item in metadata['informacoes_necessarias_para_reproducao']:
        linhas.append(f"- {item}")

    alt_a, alt_b, alt_c = (tres['alternativa_a_media_simples_atual'],
                            tres['alternativa_b_media_ponderada_por_area'],
                            tres['alternativa_c_zonal_sobre_uniao'])
    sobrep = tres['possibilidade_de_sobreposicao_espacial']
    linhas += [
        "",
        "## 4. Comparação de três alternativas metodológicas para a referência regional "
        "(5ª rodada)",
        "",
        "**Nenhuma das três foi calculada ou implementada — só comparação metodológica "
        "(atividade 6).**",
        "",
        "### (a) Média simples das 34 estimativas por fazenda — metodologia histórica, atual",
        "",
        f"- Já implementada em: `{alt_a['onde_ja_esta_implementada']}`.",
        f"- Peso por fazenda: {alt_a['peso_por_fazenda']}.",
        f"- Requisito de dados adicional: {alt_a['requisito_de_dados_adicional']}.",
        "",
        "### (b) Média das 34 estimativas por fazenda, ponderada pela área do polígono",
        "",
        f"- Onde já está implementada: {alt_b['onde_ja_esta_implementada']}.",
        f"- Peso por fazenda: {alt_b['peso_por_fazenda']}.",
        f"- Requisito de dados adicional: {alt_b['requisito_de_dados_adicional']}.",
        "",
        "### (c) Média zonal direta sobre a união dos 34 polígonos",
        "",
        f"- Onde já está implementada: {alt_c['onde_ja_esta_implementada']}.",
        f"- Requisito de dados adicional: {alt_c['requisito_de_dados_adicional']}.",
        "",
        "### Possibilidade de sobreposição espacial entre os polígonos",
        "",
        f"- Verificável com os dados atuais: {sobrep['verificavel_com_os_dados_atuais']}.",
        f"- {sobrep['sinal_indireto_disponivel']}",
        f"- {sobrep['interpretacao']}",
        f"- Ausência de sobreposição é suficiente, sozinha, para (b) = (c): "
        f"{sobrep['ausencia_de_sobreposicao_e_suficiente_para_b_igual_c']}. "
        f"{sobrep['motivo_nao_suficiente']}",
        "",
        "### Qual alternativa é mais correta",
        "",
        f"- {tres['qual_alternativa_e_mais_correta']}",
        "",
        f"- {tres['interpretacao']}",
        "",
        "## 5. Viabilidade de uma referência CHIRPS consistente para 1991-2011",
        "",
        f"- data/chirps_1981_2025.csv já cobre 1991-2011: "
        f"{viab['data_chirps_1981_2025_ja_cobre_1991_2011']} "
        f"({viab['n_meses_1991_2011_ja_extraidos']}/{viab['n_meses_1991_2011_esperados']} meses).",
        f"- {viab['interpretacao']}",
        "",
        "## 6. Auditoria do código da extração central existente (scripts/_chirps.py, ajuste "
        "final)",
        "",
        "**Auditoria de CÓDIGO — nenhuma chamada de rede, nenhuma nova extração. Achados "
        "reproduzidos por testes sintéticos em `tests/test_chirps_extracao_sintetica.py` (9 "
        "testes). Nenhuma alteração de comportamento do pipeline de produção foi feita — só um "
        "comentário explicativo em scripts/_chirps.py.**",
        "",
        "### Confirmado (por leitura de código / aritmética exata)",
        "",
        f"- Um dia sem dado (avg ausente ou None) pode virar precipitação 0.0: "
        f"{audcod['confirmado_valor_ausente_pode_virar_zero']}.",
        f"- Chuva real zero e dia sem dado são indistinguíveis na saída: "
        f"{audcod['confirmado_zero_real_e_ausencia_sao_indistinguiveis_na_saida']}.",
        f"- Confirmado que NÃO há exigência de cobertura mínima de dias na agregação mensal: "
        f"{audcod['confirmado_sem_cobertura_minima_de_dias_exigida']}.",
        f"- Confirmado que o resultado NÃO carrega nenhuma coluna de contagem/cobertura de "
        f"dias: {audcod['confirmado_resultado_sem_coluna_de_contagem_de_dias']}.",
        f"- Dias omitidos inteiramente da resposta também não contam nem são sinalizados: "
        f"{audcod['confirmado_dias_omitidos_tambem_nao_contam_nem_sinalizam']}.",
        f"- Ponto central (FAZENDAS_LAT/FAZENDAS_LON) é múltiplo exato da resolução do CHIRPS "
        f"(0,05°) nos dois eixos: "
        f"{audcod['confirmado_ponto_central_e_multiplo_exato_da_resolucao_chirps']}.",
        "",
        "### Pendente",
        "",
        f"- {audcod['pendente_convencao_de_alinhamento_do_grid_chirps']}",
        "",
        "### Impacto",
        "",
        f"- {audcod['impacto']}",
        "",
        "### Proposta de correção (não aplicada)",
        "",
        f"- {audcod['proposta_de_correcao_nao_aplicada']}",
        "",
        "## 7. Proposta de continuidade",
        "",
    ]
    for i, item in enumerate(metadata['proposta_de_continuidade'], 1):
        linhas.append(f"{i}. {item}")
    linhas += [
        "",
        "## Restrições respeitadas nesta tarefa",
        "",
        "- Nenhuma métrica de skill foi calculada.",
        "- Nenhuma previsão ou indicador de desempenho foi recalculado.",
        "- A referência observacional de produção (data/serie_subst.csv) NÃO foi substituída — "
        "só lida para comparação.",
        "- Nenhum dado histórico foi modificado.",
        "- O dashboard (docs/index.html) não foi tocado. Nenhum modelo climático foi alterado.",
        "- Nenhuma nova extração do CHIRPS foi executada (nenhum acesso à rede/ClimateSERV "
        "nesta tarefa) — a comparação usa exclusivamente data/chirps_1981_2025.csv, já "
        "existente no repositório.",
    ]
    return '\n'.join(linhas) + '\n'


def escrever_saidas(metadata):
    """Tabelas/metadata reproduzíveis (reexecutando este script, que só "
    lê arquivos já commitados) ficam em artifacts/ — gitignored. O
    relatório técnico vai para docs/, commitado."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS_DIR / 'metadata.json').write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=str))
    relatorio = gerar_relatorio_markdown(metadata)
    RELATORIO_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    RELATORIO_DOC_PATH.write_text(relatorio)
    print("  ✅ artifacts/nmme_auditoria_chirps_sinobras/metadata.json")
    print(f"  ✅ {RELATORIO_DOC_PATH.relative_to(ROOT)}")
    return relatorio


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════

def imprimir_plano():
    print("=== Investigação CHIRPS — reinterpretação da referência observacional Sinobras — "
          "Fase 2C.2 — DRY RUN PLAN (só leitura de arquivos locais já commitados, nenhum "
          "acesso à rede) ===")
    print(f"  entrada: {CHIRPS_PONTO_PATH.relative_to(ROOT)} (já existente) + "
          f"{SERIE_PRODUCAO_PATH.relative_to(ROOT)} (já existente)")
    print("  verificações: comparação CHIRPS-ponto × série de produção, informações necessárias "
          "para reprodução, viabilidade de referência CHIRPS 1991-2011")
    print("  saidas: artifacts/nmme_auditoria_chirps_sinobras/ (gitignored) + "
          "docs/nmme-fase2c2-auditoria-chirps-sinobras.md")
    print("\n✅ Plano gerado (nenhuma extração nova, nenhum cálculo de skill, nenhuma escrita "
          "ainda).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run-plan', action='store_true',
                     help='Só mostra o plano — nenhuma leitura pesada, nenhuma escrita.')
    ap.add_argument('--gerar-relatorio', action='store_true',
                     help='Roda a investigação completa (só leitura de dados locais já '
                          'existentes) e escreve o relatório técnico + metadata em artifacts/.')
    args = ap.parse_args()

    if args.gerar_relatorio:
        imprimir_plano()
        metadata = executar_investigacao_completa()
        escrever_saidas(metadata)
        comp = metadata['comparacao_chirps_ponto_vs_serie_producao']
        print(f"\ncorrelacao_pos_1996={comp['periodo_pos_1996']['correlacao']}")
        print(f"correlacao_pre_1996={comp['periodo_pre_1996']['correlacao']}")
        return

    imprimir_plano()


if __name__ == '__main__':
    main()
