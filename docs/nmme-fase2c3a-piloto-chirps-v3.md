# Piloto CHIRPS v3.0 Final — referência histórica independente (Fase 2C.3A)

**Relatório técnico — não calcula skill, não recalcula indicadores de habilidade preditiva, não substitui a referência observacional de produção, não altera SARIMAX/XGBoost/dashboard, não modifica scripts/_chirps.py.**

## 1. Produto e fonte

- Fonte: Climate Hazards Center (UCSB), CHIRPS v3.0 Final.
- Data de lançamento da versão: 2025-01-01 (README oficial: "Version 3.0 released 2025.01.01" — v2.0 foi "2015.02.12").
- README oficial consultado ao vivo: https://data.chc.ucsb.edu/products/CHIRPS/v3.0/README-CHIRPSv3.0.txt
- Diretório base: `https://data.chc.ucsb.edu/products/CHIRPS/v3.0/monthly/global/`
- Produto: mensal já consolidado (`monthly/global/`), formato preferencial COG (Cloud-Optimized GeoTIFF, leitura remota por range-request HTTP via GDAL /vsicurl/ — nunca baixa o raster global inteiro), fallback TIFF comum. NUNCA reconstrução por soma de registros diários (item 2 da tarefa).
- Resolução espacial: 0.05° — confirmada ao vivo abrindo um arquivo real (não presumida a partir da documentação).
- CRS: EPSG:4326.
- Unidade: mm/mês (campo mensal Final já consolidado — não soma de registros diários).
- Valores NoData: sentinela -9999.0 — valor empírico, lendo pixel oceânico conhecido (-30,0) — NÃO documentado na tag GDAL NODATA nem no README oficial.
- Mudanças-chave da v3.0 vs. v2.0 (README oficial): mais de 90 fontes de estação (quase 4x a v2.0), correção de sub-captação de pluviômetro por vento (gauge-undercatch), domínio espacial ampliado (60°N-60°S, antes 50°N-50°S), preenchimento de lacunas com ERA5 0,25° (antes CFS 0,5°) — resultado (texto do próprio README): "CHIRPS v3.0 is overall wetter compared to CHIRPS v2.0".
- Identificação/integridade dos arquivos usados: capturada por requisição HEAD (ETag, Last-Modified, Content-Length) antes de cada leitura — ver `data/chirps_v3_piloto_metadata.json` para os valores por mês. A leitura via GDAL detecta arquivo corrompido/incompleto (status 'arquivo_corrompido_ou_incompleto') sem baixar o arquivo inteiro para checksum.
- **Não se presume que os arquivos CHIRPS já existentes neste repositório (`data/chirps_1981_2025.csv`) pertençam a esta mesma versão** — aquele arquivo foi extraído via ClimateSERV (`scripts/_chirps.py`), que serve a versão CORRENTE do CHIRPS sem versionamento explícito documentado (achado já registrado em docs/nmme-fase2c2-auditoria-chirps-sinobras.md, item METODOLOGIA_CHIRPS_PONTO_CONHECIDA); a versão efetivamente usada naquela extração permanece DESCONHECIDA — pode ou não ser v3.0.

## 2. Referência espacial inicial — `CHIRPS_v3_ponto_centroide`

- Coordenadas consultadas: lat=-7.8, lon=-47.95 (centroide das fazendas, já estabelecido no projeto).
- O pixel é localizado DIRETAMENTE pela transformação espacial do raster (`rasterio.DatasetReader.index`), nunca reutilizando a caixa pequena da extração ClimateSERV atual (`scripts/_chirps.py::_geometria_ponto`).
- **Achado empírico CORRIGIDO nesta revisão** (auditoria independente encontrou o erro): lat/lon são múltiplos EXATOS da resolução NOMINAL do CHIRPS (0,05°), mas os coeficientes REAIS da transformação do raster não são exatamente 0,05 (0,05000000074505806 — resíduo de precisão float32→float64, ver `scripts/_chirps_v3.py::RESOLUCAO_GRAUS_REAL_CONFIRMADA`). Usando os coeficientes reais (correção aplicada em `localizar_pixel()`), o ponto fica classificado como **`proximo_de_borda`** nos dois eixos — a cerca de 1-2 milionésimos de grau (~0,1-0,2m) de duas bordas do pixel selecionado — e não `sobre_borda_exata`. A versão anterior deste relatório usava a resolução NOMINAL (não os coeficientes reais) para essa checagem, o que produzia um falso positivo de "exatamente sobre uma quina compartilhada por 4 pixels". O pixel efetivamente selecionado usa a convenção padrão do GDAL/rasterio (`numpy.floor` na fração de pixel, calculada com os coeficientes reais do transform) — ver `data/chirps_v3_piloto.csv`, colunas `pixel__*`, para as coordenadas centrais e a extensão espacial exata do pixel selecionado, e a tabela abaixo (recalculada desses mesmos limites) para a classificação de proximidade de borda. Um teste de sensibilidade comparando o pixel selecionado com seus 8 vizinhos está disponível em `scripts/_chirps_v3.py::comparar_pixel_com_vizinhos()` — informativo, nunca troca automaticamente a referência do projeto.
- Esta referência (`CHIRPS_v3_ponto_centroide`) é um PONTO ÚNICO — não é apresentada como equivalente à média zonal das 34 fazendas (SINOBRAS.csv/data/serie_subst.csv pós-1996) nem à média zonal do envelope único (`scripts/_chirps.py::buscar_prec_chirps_zonal`).

### Classificação de proximidade de borda, recalculada dos limites persistidos

Recalculada diretamente de `data/chirps_v3_piloto.csv` (pixel_bounds_*/ponto_consultado_*, já gravados na extração original) — nenhum raster reaberto, nenhuma rede usada, os 17 registros originais preservados.

| Ano-mês | Classe (lon) | Classe (lat) | Dist. borda mais próxima (lon, °) | Dist. borda mais próxima (lat, °) |
|---|---|---|---|---|
| 1991-01 | proximo_de_borda | proximo_de_borda | 1.97e-06 | 1.01e-06 |
| 1991-04 | proximo_de_borda | proximo_de_borda | 1.97e-06 | 1.01e-06 |
| 1991-07 | proximo_de_borda | proximo_de_borda | 1.97e-06 | 1.01e-06 |
| 1991-10 | proximo_de_borda | proximo_de_borda | 1.97e-06 | 1.01e-06 |
| 1998-01 | proximo_de_borda | proximo_de_borda | 1.97e-06 | 1.01e-06 |
| 1998-04 | proximo_de_borda | proximo_de_borda | 1.97e-06 | 1.01e-06 |
| 1998-07 | proximo_de_borda | proximo_de_borda | 1.97e-06 | 1.01e-06 |
| 1998-10 | proximo_de_borda | proximo_de_borda | 1.97e-06 | 1.01e-06 |
| 2005-01 | proximo_de_borda | proximo_de_borda | 1.97e-06 | 1.01e-06 |
| 2005-04 | proximo_de_borda | proximo_de_borda | 1.97e-06 | 1.01e-06 |
| 2005-07 | proximo_de_borda | proximo_de_borda | 1.97e-06 | 1.01e-06 |
| 2005-10 | proximo_de_borda | proximo_de_borda | 1.97e-06 | 1.01e-06 |
| 2010-01 | proximo_de_borda | proximo_de_borda | 1.97e-06 | 1.01e-06 |
| 2010-04 | proximo_de_borda | proximo_de_borda | 1.97e-06 | 1.01e-06 |
| 2010-07 | proximo_de_borda | proximo_de_borda | 1.97e-06 | 1.01e-06 |
| 2010-10 | proximo_de_borda | proximo_de_borda | 1.97e-06 | 1.01e-06 |
| 2011-05 | proximo_de_borda | proximo_de_borda | 1.97e-06 | 1.01e-06 |

## 3. Extração-piloto

- Meses do piloto: 17 — 1991-01, 1991-04, 1991-07, 1991-10, 1998-01, 1998-04, 1998-07, 1998-10, 2005-01, 2005-04, 2005-07, 2005-10, 2010-01, 2010-04, 2010-07, 2010-10, 2011-05.
- Mecanismo de retomada: meses com resultado já resolvido (ok/zero_real/nodata_sentinela/mes_ausente) NUNCA são reprocessados; falhas de rede são retentadas na próxima execução.
- Limite de requisições por execução: 30 (o piloto tem 17 meses — a série histórica completa NUNCA é baixada automaticamente por este script).
- Intervalo mínimo entre requisições: 1.0s.

## 4. Controle de qualidade

- Veredito: **APROVADO**.
- APROVADO — cobertura temporal completa: de 17 meses obrigatórios, 17 estavam disponíveis no servidor, 17 tiveram extração bem-sucedida (raster aberto, grade validada, pixel lido e classificado), mas só 17 têm um VALOR VÁLIDO utilizável (ok/zero_real) — 0 ausentes no servidor e 0 com NoData NÃO contam como valor válido, mesmo sendo respostas 'esperadas' do servidor/produto. Um período obrigatório e fixo (como este — todos os meses já deveriam estar publicados) só é considerado com cobertura temporal completa quando TODOS os meses têm valor válido — mes_ausente/NoData/falha de extração em QUALQUER mês impede a aprovação plena, mesmo que sejam respostas 'legítimas' do servidor. Reprovação bloqueia o uso científico deste período até a causa raiz ser corrigida — nunca prosseguir com dado incompleto/corrompido/ausente tratado como se fosse íntegro.

### Quatro dimensões distintas (nunca um único booleano)

1. Disponibilidade no servidor: 17/17.
2. Sucesso da extração (raster aberto, grade validada, pixel lido/classificado): 17/17.
3. Valor de precipitação VÁLIDO disponível (ok/zero_real — NoData e ausência NÃO contam): 17/17.
4. Cobertura temporal completa do período (TODOS os meses com valor válido): SIM.

### Resultado por mês

| Ano-mês | Status | Valor (mm) |
|---|---|---|
| 1991-01 | ok | 342.9 |
| 1991-04 | ok | 214.6 |
| 1991-07 | ok | 2.0 |
| 1991-10 | ok | 58.3 |
| 1998-01 | ok | 347.5 |
| 1998-04 | ok | 54.1 |
| 1998-07 | ok | 3.4 |
| 1998-10 | ok | 89.3 |
| 2005-01 | ok | 258.8 |
| 2005-04 | ok | 143.8 |
| 2005-07 | ok | 1.9 |
| 2005-10 | ok | 43.4 |
| 2010-01 | ok | 206.4 |
| 2010-04 | ok | 179.4 |
| 2010-07 | ok | 1.9 |
| 2010-10 | ok | 136.2 |
| 2011-05 | ok | 102.8 |

## 5. Comparação com os dados existentes

- 17 meses comparados a três referências: (1) CHIRPS v3.0 Final, novo, ponto único no centroide, versão e metodologia CONTROLADAS (esta extração); (2) CHIRPS histórico existente (data/chirps_1981_2025.csv), extraído pelo ClimateSERV — a versão do CHIRPS usada NUNCA foi registrada por aquele pipeline, então NÃO é identificada aqui como 'CHIRPS v2 confirmado'; (3) série consolidada de produção (data/serie_subst.csv), que combina procedência pré-1996 não comprovada com estimativas CHIRPS ZONAIS por fazenda pós-1996 (metodologia diferente por desenho — zonal vs. ponto). NESTA amostra de 17 meses: 8 meses com CHIRPS v3 superior ao existente, 9 inferior, 0 iguais — diferença média assinada de -2.66 mm (diferença absoluta média 11.02 mm). Isto NÃO confirma nem contradiz, isoladamente, a afirmação geral do README oficial de que "CHIRPS v3.0 is overall wetter compared to CHIRPS v2.0" — aquela é uma caracterização do produto AGREGADO/GLOBAL; esta amostra é REGIONAL (1 ponto, 17 meses, região historicamente com viés conhecido em jun-ago e out-dez, CLAUDE.md armadilha 7) e pequena demais para generalizar. As duas coisas são distintas e não devem ser confundidas: comportamento documentado do produto vs. comportamento observado nesta amostra específica. Nenhum indicador de habilidade preditiva do CFSv2 foi calculado — só estatística descritiva de comparação entre referências (item 6 da tarefa).

- Meses com CHIRPS v3 superior ao existente: 8. Inferior: 9. Iguais: 0.
- Diferença média ASSINADA (v3 menos existente): -2.66 mm. Diferença absoluta média: 11.02 mm.

| Ano-mês | CHIRPS v3 (novo) | CHIRPS existente (versão não confirmada) | Série produção (consolidada) |
|---|---|---|---|
| 1991-01 | 342.94 | 321.8 (diff 21.14) | 308.35 (diff 34.59) |
| 1991-04 | 214.63 | 214.2 (diff 0.43) | 208.3 (diff 6.33) |
| 1991-07 | 1.95 | 0.0 (diff 1.95) | 12.81 (diff -10.86) |
| 1991-10 | 58.28 | 71.5 (diff -13.22) | 106.64 (diff -48.36) |
| 1998-01 | 347.46 | 338.7 (diff 8.76) | 332.71 (diff 14.75) |
| 1998-04 | 54.1 | 59.5 (diff -5.4) | 82.32 (diff -28.22) |
| 1998-07 | 3.36 | 8.2 (diff -4.84) | 3.88 (diff -0.52) |
| 1998-10 | 89.3 | 111.4 (diff -22.1) | 72.32 (diff 16.98) |
| 2005-01 | 258.83 | 249.7 (diff 9.13) | 237.76 (diff 21.07) |
| 2005-04 | 143.77 | 149.5 (diff -5.73) | 165.18 (diff -21.41) |
| 2005-07 | 1.87 | 0.0 (diff 1.87) | 0.0 (diff 1.87) |
| 2005-10 | 43.4 | 57.0 (diff -13.6) | 86.79 (diff -43.39) |
| 2010-01 | 206.42 | 218.3 (diff -11.88) | 275.24 (diff -68.82) |
| 2010-04 | 179.41 | 203.5 (diff -24.09) | 247.18 (diff -67.77) |
| 2010-07 | 1.85 | 0.0 (diff 1.85) | 2.97 (diff -1.12) |
| 2010-10 | 136.15 | 151.6 (diff -15.45) | 137.74 (diff -1.59) |
| 2011-05 | 102.81 | 76.9 (diff 25.91) | 123.53 (diff -20.72) |

## Restrições respeitadas nesta tarefa

- `scripts/_chirps.py` (pipeline operacional) NÃO foi modificado.
- Nenhum indicador de habilidade preditiva do CFSv2 foi calculado.
- Nenhuma referência observacional de produção foi substituída.
- SARIMAX, XGBoost, dashboard e demais modelos climáticos não foram alterados.
- A série histórica completa do CHIRPS v3.0 NÃO foi baixada automaticamente — só os 17 meses do piloto.
- Nenhum raster global foi armazenado no repositório — só o valor do pixel e sua proveniência (`data/chirps_v3_piloto.csv`, `data/chirps_v3_piloto_metadata.json`).
