# Dashboard Clima Operacional — Sinobras Florestal

Painel de previsão climática para 34 fazendas de eucalipto no Norte do
Tocantins (~48.000 ha). Projeta precipitação e balanço hídrico 12 meses à
frente, condicionado ao ENSO, para orientar a janela de plantio.

## Arquitetura

```
scripts/
  fetch_monthly_data.py    1. busca ERA5-Land do mês anterior (Open-Meteo)
  update_indices.py        2. índices oceânicos (PSL/NOAA + CPC)
  update_dashboard.py      3. SARIMAX x XGBoost, cenários, BH, gera o HTML
  verificar_dashboard.py   4. BARREIRA — falha se algo estiver inconsistente
  gerar_relatorio.py       5. relatório executivo .docx (2 páginas)
data/                      série, índices e resultados intermediários
docs/index.html            o dashboard (arquivo único, publicado no Pages)
docs/relatorio-executivo.docx
.github/workflows/
  update.yml               dia 21, 12h BRT — pipeline completo
  publicar.yml             a cada push em docs/ — só republica o Pages
```

O dashboard é **um único HTML** com dados embutidos em objetos JS
(`const D`, `const BH`, `const CPC_IRI`, `const SARIMAX_DATA`). O
`update_dashboard.py` reescreve esses objetos por regex. Não há build.

## Comandos

```bash
pip install -r requirements.txt

python scripts/update_dashboard.py     # regenera docs/index.html
python scripts/verificar_dashboard.py  # exit 1 se houver inconsistência
python scripts/gerar_relatorio.py      # regenera o .docx
```

**Sempre rode `verificar_dashboard.py` depois de qualquer alteração que
toque no HTML ou nos scripts que o geram.** É o teste de regressão do
projeto e roda em segundos.

## Armadilhas conhecidas

Estas causaram bugs reais em produção. Leia antes de mexer.

### 1. Eixo X — nunca rotacionar arrays já alinhados

O horizonte começa no **mês corrente** e vai 12 meses à frente
(`D.fc_labels`). Os cenários em `results[sc]['prec']` **já saem nesse
eixo**. Rotacioná-los "para alinhar" é o erro clássico: o ARM ficou 2
meses adiantado em relação à chuva que o alimenta, e o solo aparecia
enchendo em novembro com chuva menor que a ETP.

Regra: a ETP é rotacionada para o eixo (`ETP_HORIZ`), a precipitação não.
Nada de rotação depois de `solve_bh`.

Exceção: `BH.clim` na aba Clima usa jul→jun fixo, e `BH_CLIM_HYD` é o
mesmo dado pré-rotado para o mês corrente. São coisas diferentes.

### 2. `re.sub` global destrói campos vizinhos

`re.sub(r'labels:\[[^\]]+\]', ...)` também casa dentro de
`fc_labels:[...]` e de `clim: { labels: [...] }`. Isso apagou o eixo X de
todos os gráficos em produção.

Regra: ao editar o HTML por regex, **delimite a região primeiro**
(`html.find('indices:')` … `html.find('fc_labels:')`) e use `count=1`.

### 3. `CPC_IRI` é curado à mão e avança com o calendário

`CPC_IRI.seasons` é atualizado manualmente a cada emissão do CPC/IRI. Se
pedir um trimestre que `SARIMAX_DATA` não tem, o JS quebra com
`Cannot read properties of undefined` e a aba Comparativo não renderiza.

Por isso os trimestres são gerados dinamicamente a partir do horizonte
(13 deles, desde o mês anterior). O `verificar_dashboard.py` checa isso.

### 4. Não inventar dados de CPC/IRI

As probabilidades por trimestre alimentam o comparativo, o cenário
central e o relatório. Quando um centro não publica a tabela em texto
(o CPC só publica figura), use `null` e rotule a série como da emissão
anterior. Nunca estimar.

CPC usa ERSSTv5, IRI usa OISSTv2 — divergência de até 0,5 °C no Niño 3.4
é esperada e não é discordância.

### 5. Dois workflows publicando

`update.yml` e `publicar.yml` compartilham `concurrency: group: pages`
para não colidirem. Se adicionar outro workflow que publique, use o mesmo
grupo.

## Convenções

- Português brasileiro em tudo: código, comentários, commits, saída.
- Números no padrão pt-BR (1.409 mm, +2,70 °C).
- Ano hidrológico jul→jun na aba Clima; horizonte móvel nas demais.
- Climatologia de referência: 1981–2025, média 1.714 mm/ano.
- CAD = 100 mm; "mês crítico" = ARM < 20 mm.

## Constantes

```python
CLIM_JAN_DEZ = [267.3,282.3,308.4,220.4,83.1,15.6,6.4,10.4,41.7,119.7,159.2,199.9]
ETP_JAN_DEZ  = [116,110,115,118,125,112,107,120,138,145,138,122]  # 1.466 mm/ano
FAZENDAS_LAT, FAZENDAS_LON = -7.80, -47.95
HOLDOUT = 36   # meses de holdout para escolher entre SARIMAX e XGBoost
```

## Ao propor mudanças

1. Rode `verificar_dashboard.py` antes e depois.
2. Se mexer em rotação de arrays, mostre a tabela mês a mês comparando
   rótulo do eixo com o valor, para conferência visual.
3. Mudanças em `update_dashboard.py` afetam o HTML inteiro — regenere e
   verifique, não edite o HTML à mão.
4. O que é gerado (`docs/`, `data/`) o robô sobrescreve todo dia 21.
   Correção de verdade vai sempre nos `scripts/`.
