#!/usr/bin/env python3
"""
nmme_cpc_cpt.py — Fase 2C.1 (revisão pós-catálogo): parser do formato
CPT v10 (tab-delimited ASCII) usado pela rota oficial NOAA/CPC de
hindcast mensal NMME em `monthly_nmme_hindcast_in_cpt_format/`, e
utilitários de inspeção leve do nome de arquivo/cabeçalho sem baixar
séries completas.

Este módulo NÃO acessa rede (mesma separação de responsabilidade de
nmme_download.py) — só parseia texto já em mãos (um arquivo pequeno
lido localmente, ou um trecho já obtido por outra via) e interpreta
nomes de arquivo.

═══════════════════════════════════════════════════════════════════════
INVESTIGAÇÃO — o que foi e não foi aberto de primeira mão nesta sessão
═══════════════════════════════════════════════════════════════════════

`ftp.cpc.ncep.noaa.gov` permanece BLOQUEADO para WebFetch/curl nesta
sessão (EGRESS_BLOCKED, mesmo bloqueio de domínio inteiro já registrado
em nmme_catalogo.py — confirmado de novo por tentativa direta ao
diretório, ao `readme` e a um arquivo específico
`nmme_precip_hcst_Janic_6_1991.txt`; não é uma questão de tamanho de
request, então nem Range nem streaming resolveriam isso aqui). Também
bloqueados: `iri.columbia.edu`, `iridl.ldeo.columbia.edu`. Inacessível
(falha de DNS, não bloqueio): `cpthelp.iri.columbia.edu`.

Nenhum byte de um arquivo REAL da rota `cfsv2_..._hcst_..._MENSAL` foi
lido nesta sessão. Isso NÃO significa investigação vazia — dois achados
reais, obtidos de fontes verificáveis fora do domínio bloqueado, mudam
a base de evidência:

1. **Padrão de nome de arquivo (DOCUMENTED, corroborado por múltiplas
   buscas independentes)**: WebSearch devolveu, como resultados de
   busca genuínos (URLs indexadas, não paráfrase), vários nomes reais
   do diretório `monthly_nmme_hindcast_in_cpt_format/`:
   `cfsv2_tmp2m_hcst_Novic_4_1992.txt`, `cfsv2_tmp2m_hcst_Decic_3_1992.txt`,
   `nmme_precip_hcst_Janic_6_1991.txt`, `nmme_precip_hcst_Julic_1_1992.txt`
   — confirmando o padrão `{modelo}_{variavel}_hcst_{MesAbrev}ic_{n}_{ano}.txt`
   com `n` e `ano` SINGULARES (não faixa), diferente do diretório irmão
   `seasonal_nmme_hindcast_in_cpt_format/` (ex.:
   `cfsv2_precip_hcst_Decic_6-8_1992-2021.txt` — lead em FAIXA, ano em
   FAIXA). As duas famílias nunca devem ser confundidas (mesma cautela
   da Seção 21 do catálogo para predecessores).
2. **Formato CPT v10 em si (EMPIRICALLY_CONFIRMED, de fato aberto e
   lido nesta sessão)**: o parser oficial da IRI para este formato —
   pacote `cpt-io`, hoje dentro de `github.com/iri-pycpt/pycpt`
   (`cpt-io/src/cptio/fileio/cpt.py`) — foi lido diretamente via
   `raw.githubusercontent.com` (github não está bloqueado). Isso dá
   certeza sobre a estrutura genérica: linha `xmlns:cpt=
   http://iri.columbia.edu/CPT/v10/`; blocos `cpt:field=...` com
   atributos `nrow`/`ncol`/`row`/`col`/`units`/`missing`/`T`/`S`
   (opcional)/`L` (opcional, lead explícito, ex. "3.0 months")/`M`
   (opcional — dimensão de MEMBRO, confirmada como suportada pelo
   formato em geral); linha de rótulos de coluna logo após o cabeçalho
   do bloco; `nrow` linhas de dado, cada uma com rótulo de linha +
   `ncol` valores tab-delimited.
   Além disso, um exemplo REAL de arquivo de hindcast NMME em CPT v10
   foi lido (`cpt-io/tests/data/SEASONAL_CANCM4I_PRCP_HCST_JUN-SEP_
   None_2021-05.tsv`, fixture de teste do próprio pycpt — modelo
   CanCM4i, produto SAZONAL, não CFSv2/MENSAL): `cpt:field=prec`
   (nome interno da variável — note que difere do token "precip" do
   NOME do arquivo!), `cpt:units=mm/day`, `cpt:nrow=33, cpt:ncol=30`
   (grade 1°×1°, espaçamento confirmado nos rótulos), `cpt:missing=-999`,
   `cpt:S=1980-05-01T00:00` (inicialização explícita no cabeçalho),
   `cpt:L=3.0 months` (lead explícito no cabeçalho) — e **nenhum bloco
   deste arquivo real tem `cpt:M=`**: é ensemble mean por T (ano), não
   membro-a-membro.

**O que isso NÃO confirma**: o achado 2 é para CanCM4i/SAZONAL, não
CFSv2/MENSAL — modelo e produto diferentes, mesma família de formato.
É evidência de FAMÍLIA (mesmo raciocínio já aplicado ao CanSIPS-IC3
FORECAST vs HINDCAST em nmme_catalogo.py), não confirmação do arquivo
específico que o POC real abriria. Ainda assim, é um sinal real e
concreto — não hipotético — de que arquivos CPT v10 de hindcast NMME,
como o CPC/IRI de fato os distribui, costumam ser ensemble-mean-only
mesmo quando o formato-padrão SUPORTA a dimensão M. Por isso
`nmme_catalogo.CATALOGO['NOAA_NCEP/CFSv2'].data_access_status`
permanece `PARTIAL` (não `CONFIRMED`) — ver a nota específica na
entrada do catálogo.

Nenhum arquivo de dado (NetCDF/GRIB/CPT) foi baixado nesta sessão além
da leitura pontual, via GitHub, do código-fonte do parser oficial e de
uma fixture de teste pequena já publicada publicamente pelo próprio
projeto IRI-PyCPT — não é um hindcast baixado por este projeto, é
código/documentação lidos para ENTENDER o formato (mesmo espírito da
Seção 38/50: só infraestrutura/documentação, nenhum download de série).
"""

import re
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from c3s_poc import distancia_km_aprox, PREC_MM_MIN_PLAUSIVEL, PREC_MM_MAX_PLAUSIVEL  # noqa: E402

CPT_XMLNS_MARCADOR = 'xmlns:cpt=http://iri.columbia.edu/CPT/v10/'

# Seção "membros" — avaliação de adequação para POC probabilístico por
# membro (nunca confundir ensemble mean com dado por membro).
MEMBER_LEVEL_DATA_PRESENT = 'MEMBER_LEVEL_DATA_PRESENT'
ENSEMBLE_MEAN_ONLY = 'ENSEMBLE_MEAN_ONLY'
MEMBER_STATUS_INDETERMINADO = 'INDETERMINADO'

MESES_ABREV_CPC = {'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                    'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12}

_TAG_VALOR_RE = re.compile(r'(?P<tag>cpt:[A-Za-z_]+|cf:[A-Za-z_]+)=(?P<valor>[^,]*)(?:,|$)')

_RE_NOME_MENSAL = re.compile(
    r'^(?P<model>[a-z0-9]+)_(?P<variavel_token>[a-z0-9]+)_hcst_'
    r'(?P<mes_abrev>[A-Za-z]{3})ic_(?P<numero_apos_ic>\d+)_(?P<ano>\d{4})\.txt$'
)
_RE_NOME_SAZONAL = re.compile(
    r'^(?P<model>[a-z0-9]+)_(?P<variavel_token>[a-z0-9]+)_hcst_'
    r'(?P<mes_abrev>[A-Za-z]{3})ic_(?P<lead_range>\d+-\d+)_(?P<ano_range>\d{4}-\d{4})\.txt$'
)


@dataclass
class BlocoCpt:
    """1 bloco `cpt:field=...` + sua grade — sem xarray, tabular puro
    (Seção 3 da tarefa: não tratar CPT como NetCDF)."""
    attrs: dict
    col_labels: list
    linhas: list = field(default_factory=list)   # [(rotulo_linha, [valores...]), ...]

    def tem_membro(self):
        return 'M' in self.attrs


# ══════════════════════════════════════════════════════════════════════════
# Parser — barreira B: cabeçalho malformado reprova explicitamente, nunca
# tenta "adivinhar" a estrutura.
# ══════════════════════════════════════════════════════════════════════════

def parse_header_line(linha):
    pares = _TAG_VALOR_RE.findall(linha)
    if not pares:
        return {}
    return {tag.split(':', 1)[1]: valor.strip() for tag, valor in pares}


def parse_cpt_text(texto):
    """Parseia um texto CPT v10 completo (já em mãos — nunca baixa nada
    aqui) em uma lista de BlocoCpt. Levanta ValueError explícito para
    qualquer inconsistência estrutural (barreira B) — nunca segue
    adiante com suposição."""
    linhas_arquivo = texto.splitlines()
    if not any(CPT_XMLNS_MARCADOR in linha for linha in linhas_arquivo):
        raise ValueError(f"arquivo não contém a linha {CPT_XMLNS_MARCADOR!r} — não é um CPT v10 válido "
                          f"(barreira B).")
    blocos = []
    i, n = 0, len(linhas_arquivo)
    while i < n:
        linha = linhas_arquivo[i].strip()
        if linha.startswith('cpt:field='):
            attrs = parse_header_line(linha)
            if 'nrow' not in attrs or 'ncol' not in attrs:
                raise ValueError(f"bloco cpt:field (linha {i}) sem cpt:nrow/cpt:ncol — cabeçalho "
                                  f"malformado (barreira B).")
            if 'units' not in attrs:
                raise ValueError(f"bloco cpt:field={attrs.get('field')!r} (linha {i}) sem cpt:units — "
                                  f"unidade é obrigatória, nunca assumida (barreira E).")
            nrow, ncol = int(attrs['nrow']), int(attrs['ncol'])
            i += 1
            if i >= n:
                raise ValueError("cabeçalho de bloco sem linha de rótulos de coluna — arquivo truncado "
                                  "(barreira B).")
            col_tokens = linhas_arquivo[i].split('\t')[1:]
            if len(col_tokens) != ncol:
                raise ValueError(f"nº de rótulos de coluna ({len(col_tokens)}) != cpt:ncol ({ncol}) — "
                                  f"cabeçalho inconsistente (barreira B).")
            try:
                col_labels = [float(x) for x in col_tokens]
            except ValueError as e:
                raise ValueError(f"rótulo de coluna não numérico — {e} (barreira B).")
            i += 1
            linhas_dado = []
            for _ in range(nrow):
                if i >= n or not linhas_arquivo[i].strip():
                    raise ValueError("bloco terminou antes de completar cpt:nrow linhas — arquivo "
                                      "truncado (barreira B).")
                partes = linhas_arquivo[i].split('\t')
                if len(partes) != ncol + 1:
                    raise ValueError(f"linha de dado com {len(partes) - 1} valores, esperado {ncol} "
                                      f"(barreira B).")
                try:
                    rotulo = float(partes[0])
                    valores = [float(v) for v in partes[1:]]
                except ValueError as e:
                    raise ValueError(f"valor não numérico em linha de dado — {e} (barreira B).")
                linhas_dado.append((rotulo, valores))
                i += 1
            blocos.append(BlocoCpt(attrs=attrs, col_labels=col_labels, linhas=linhas_dado))
        else:
            i += 1
    if not blocos:
        raise ValueError("nenhum bloco cpt:field encontrado — arquivo malformado ou vazio (barreira B).")
    return blocos


# ══════════════════════════════════════════════════════════════════════════
# Inspeção leve (Seção 4 da tarefa) — estratégia documentada, nunca
# baixa a série completa. Este módulo não faz rede (mesma separação de
# nmme_download.py); a chamada real, se algum dia a rede estiver
# disponível, é responsabilidade de nmme_download.py.
# ══════════════════════════════════════════════════════════════════════════

def estrategia_inspecao_leve(url):
    """Documenta o plano de inspeção leve de um arquivo CPT remoto sem
    baixar a série completa. Não executa nenhuma chamada de rede — só
    descreve a estratégia e registra a tentativa real já feita nesta
    sessão contra o mesmo domínio (Seção 4)."""
    return {
        'url': url,
        'metodo_preferido': 'HTTP GET com header Range: bytes=0-8191 — 8 KiB cobre cabeçalho + rótulos '
                             'de coluna + várias dezenas de linhas de dado nos arquivos MENSAIS (1 ano x '
                             '1 número-após-ic por arquivo, bem menores que os arquivos SAZONAIS/'
                             'multi-década do diretório irmão).',
        'fallback_se_range_nao_suportado': 'GET com stream=True, leitura via iter_lines interrompida '
                                            'após as primeiras ~200 linhas, sem materializar o corpo '
                                            'inteiro em memória.',
        'tentativa_real_nesta_sessao': 'EGRESS_BLOCKED em ftp.cpc.ncep.noaa.gov — bloqueio de domínio '
                                        'inteiro (confirmado via WebFetch na listagem do diretório, no '
                                        'readme e em um arquivo específico), não uma limitação de '
                                        'tamanho de request; nem Range nem streaming teriam contornado '
                                        'isso nesta sessão. Documentado aqui para quando a rede estiver '
                                        'disponível (POC real, revisão humana) — nmme_download.py é o '
                                        'módulo responsável por executar, nunca este.',
    }


# ══════════════════════════════════════════════════════════════════════════
# Nome de arquivo — barreira B: nunca adivinha; distingue explicitamente
# MENSAL de SAZONAL (famílias diferentes, nunca confundidas).
# ══════════════════════════════════════════════════════════════════════════

def parse_nome_arquivo_mensal(nome):
    m = _RE_NOME_MENSAL.match(nome)
    if not m:
        if _RE_NOME_SAZONAL.match(nome):
            raise ValueError(f"{nome!r} é um nome de arquivo SAZONAL (lead/ano em faixa, diretório "
                              f"seasonal_nmme_hindcast_in_cpt_format/), não MENSAL — as duas famílias "
                              f"nunca devem ser tratadas como equivalentes.")
        raise ValueError(f"{nome!r} não corresponde ao padrão mensal documentado "
                          f"'{{model}}_{{variavel}}_hcst_{{MesAbrev}}ic_{{n}}_{{ano}}.txt' — FALHANDO "
                          f"em vez de adivinhar (barreira B).")
    g = m.groupdict()
    mes_abrev = g['mes_abrev'].capitalize()
    if mes_abrev not in MESES_ABREV_CPC:
        raise ValueError(f"abreviação de mês {g['mes_abrev']!r} não reconhecida em {nome!r} — esperado "
                          f"uma de {sorted(MESES_ABREV_CPC)}.")
    return {
        'model': g['model'], 'variavel_token': g['variavel_token'],
        'init_month_abbr': mes_abrev, 'init_month': MESES_ABREV_CPC[mes_abrev],
        'numero_apos_ic': int(g['numero_apos_ic']), 'ano_arquivo': int(g['ano']),
    }


def hipotese_interpretacao_numero_apos_ic():
    """Nunca apresenta a interpretação do nº após 'ic' no nome do
    arquivo como fato — é hipótese, com status de evidência explícito
    (Seção 2 da tarefa: 'NÃO assumir. Confirmar pela estrutura do
    arquivo ou documentação associada')."""
    return {
        'hipotese': "numero_apos_ic é o LEAD em meses, seguindo a mesma convenção "
                    "'lead1_igual_mes_inicializacao' já usada para outras fontes NMME nesta base de "
                    "código (nmme_processar.py, _c3s_utils.py).",
        'status_evidencia': 'UNCONFIRMED',
        'motivo': "Nenhum arquivo real da rota monthly_nmme_hindcast_in_cpt_format foi aberto nesta "
                  "sessão (ftp.cpc.ncep.noaa.gov bloqueado). Evidência indireta: um arquivo real do "
                  "MESMO FORMATO (produto SAZONAL, CanCM4i, lido via github.com/iri-pycpt/pycpt) "
                  "carrega cpt:S (inicialização) e cpt:L (lead explícito) no próprio cabeçalho — se os "
                  "arquivos MENSAIS seguirem a mesma convenção autodescritiva, o cabeçalho pode "
                  "confirmar ou contradizer essa hipótese sem depender só do nome do arquivo — ver "
                  "validar_target_month_contra_header().",
    }


def validar_target_month_contra_header(bloco, init_ano, init_mes, numero_apos_ic,
                                        esquema='lead1_igual_mes_inicializacao'):
    """Barreira I: nunca aceita o target month só pelo nome do arquivo
    se o cabeçalho do bloco tiver cpt:S contradizendo. Levanta
    ValueError explícito em conflito; quando o bloco não tem cpt:S,
    devolve a hipótese como NÃO cruzada (não confirmada, não negada)."""
    import pandas as pd
    import nmme_processar as nproc
    target_hipotese = nproc.leadtime_para_mes_alvo_nmme(
        pd.Period(f'{init_ano}-{init_mes:02d}', 'M'), numero_apos_ic, esquema)
    s_raw = bloco.attrs.get('S')
    if not s_raw:
        return {'target_month_hipotese': str(target_hipotese), 'cruzado_com_header': False,
                'nota': "bloco sem cpt:S — não foi possível cruzar com o nome do arquivo; hipótese "
                        "permanece UNCONFIRMED."}
    try:
        ano_s, mes_s = int(s_raw[:4]), int(s_raw[5:7])
    except (ValueError, IndexError):
        raise ValueError(f"cpt:S={s_raw!r} não pôde ser interpretado como data (esperado "
                          f"'YYYY-MM-...') — FALHANDO em vez de ignorar (barreira I).")
    if (ano_s, mes_s) != (init_ano, init_mes):
        raise ValueError(f"cpt:S do cabeçalho ({ano_s}-{mes_s:02d}) diverge do mês de inicialização "
                          f"assumido pelo nome do arquivo ({init_ano}-{init_mes:02d}) — FALHANDO em vez "
                          f"de confiar só no nome (barreira I).")
    return {'target_month_hipotese': str(target_hipotese), 'cruzado_com_header': True, 'cpt_S': s_raw}


# ══════════════════════════════════════════════════════════════════════════
# Grade/coordenadas — barreira D: convenção de longitude tratada
# explicitamente, nunca assumida.
# ══════════════════════════════════════════════════════════════════════════

def detectar_convencao_longitude(col_labels):
    return '0-360' if all(x >= 0 for x in col_labels) else '-180-180'


def normalizar_longitude_para(lon, convencao):
    if convencao == '0-360':
        return lon % 360.0
    if convencao == '-180-180':
        return ((lon + 180.0) % 360.0) - 180.0
    raise ValueError(f"convenção de longitude desconhecida: {convencao!r}.")


def selecionar_ponto_mais_proximo(bloco, lat_alvo, lon_alvo):
    """Localiza a célula de grade mais próxima de (lat_alvo, lon_alvo) —
    São Bento do Tocantins, no uso real (Seção 15/CLAUDE.md: nunca nova
    localização). Trata a convenção de longitude explicitamente
    (barreira D) e devolve requested/selected/distância — mesmo padrão
    de nmme_processar.montar_linha_raw."""
    convencao = detectar_convencao_longitude(bloco.col_labels)
    lon_norm = normalizar_longitude_para(lon_alvo, convencao)
    idx_col = min(range(len(bloco.col_labels)), key=lambda j: abs(bloco.col_labels[j] - lon_norm))
    idx_row = min(range(len(bloco.linhas)), key=lambda i: abs(bloco.linhas[i][0] - lat_alvo))
    lat_sel = bloco.linhas[idx_row][0]
    lon_sel = bloco.col_labels[idx_col]
    valor = bloco.linhas[idx_row][1][idx_col]
    missing = bloco.attrs.get('missing')
    if missing is not None and valor == float(missing):
        valor = float('nan')
    dist_km = distancia_km_aprox(lat_alvo, lon_alvo, lat_sel, lon_sel)
    return {'requested_lat': lat_alvo, 'requested_lon': lon_alvo, 'selected_lat': lat_sel,
            'selected_lon': lon_sel, 'valor': valor, 'grid_distance_km': dist_km,
            'longitude_convention_detected': convencao, 'units': bloco.attrs.get('units')}


# ══════════════════════════════════════════════════════════════════════════
# Barreiras J/K — plausibilidade física, mesma faixa reaproveitada de
# c3s_poc.py/nmme_processar.py (limite físico, não específico de fonte).
# ══════════════════════════════════════════════════════════════════════════

def validar_valor_extraido(valor):
    v = float(valor)
    if not np.isfinite(v):
        raise RuntimeError("valor extraído do CPT não é finito (NaN/inf) — FALHANDO (barreira J).")
    if v < 0:
        raise RuntimeError("valor extraído do CPT é precipitação negativa — FALHANDO (barreira K).")
    if not (PREC_MM_MIN_PLAUSIVEL <= v <= PREC_MM_MAX_PLAUSIVEL):
        raise RuntimeError(f"valor {v} fora da faixa física plausível "
                            f"[{PREC_MM_MIN_PLAUSIVEL},{PREC_MM_MAX_PLAUSIVEL}]mm — FALHANDO.")
    return True


# ══════════════════════════════════════════════════════════════════════════
# Membro vs. ensemble mean (Seção 8/9 do catálogo) — barreira F/G/L.
# ══════════════════════════════════════════════════════════════════════════

def avaliar_adequacao_membro(blocos):
    """ENSEMBLE_MEAN_ONLY quando NENHUM bloco tem cpt:M;
    MEMBER_LEVEL_DATA_PRESENT quando TODOS têm; INDETERMINADO numa
    mistura inconsistente (nunca decidido silenciosamente — barreira L,
    nunca confundir ensemble mean com dado por membro)."""
    if not blocos:
        return MEMBER_STATUS_INDETERMINADO
    tem_m = [b.tem_membro() for b in blocos]
    if all(tem_m):
        return MEMBER_LEVEL_DATA_PRESENT
    if not any(tem_m):
        return ENSEMBLE_MEAN_ONLY
    return MEMBER_STATUS_INDETERMINADO


def exigir_dados_por_membro(blocos, contexto=''):
    """Barreira F: usada quando o objetivo exige valores individuais
    por membro (POC probabilístico). Levanta RuntimeError explícito se
    os blocos não carregarem a dimensão M — nunca trata ensemble mean
    como se fosse por-membro."""
    status = avaliar_adequacao_membro(blocos)
    if status != MEMBER_LEVEL_DATA_PRESENT:
        sufixo = f' ({contexto})' if contexto else ''
        raise RuntimeError(f"dados por membro exigidos{sufixo}, mas os blocos CPT não têm a dimensão "
                            f"M — status={status}. Esta rota/arquivo não serve para POC probabilístico "
                            f"por membro sem outra fonte (Seção 8/9).")
    return True


def validar_contagem_membros(blocos, membros_esperados):
    """Barreira G: nº de membros nos blocos precisa bater exatamente com
    o documentado no catálogo — nunca aceito silenciosamente se
    diferente."""
    membros = sorted({b.attrs.get('M') for b in blocos if 'M' in b.attrs}, key=lambda x: float(x))
    if not membros:
        raise RuntimeError("nenhum bloco tem dimensão M — use avaliar_adequacao_membro/"
                            "exigir_dados_por_membro antes de validar contagem.")
    if len(membros) != membros_esperados:
        raise RuntimeError(f"nº de membros nos blocos = {len(membros)}, esperado {membros_esperados} "
                            f"(documentado no catálogo) — FALHANDO (barreira G, nunca aceitar "
                            f"silenciosamente uma contagem diferente da documentada).")
    return len(membros)
