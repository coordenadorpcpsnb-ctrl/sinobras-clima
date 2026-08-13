# Dashboard Clima Operacional — Sinobras Florestal

Dashboard de previsão climática para as 34 fazendas de eucalipto no Norte do Tocantins.  
Atualizado automaticamente toda **3ª quinta-feira do mês às 12:00 BRT** via GitHub Actions.

## Acesso

**URL pública:** `https://<usuario>.github.io/<repositorio>/`  
*(após configurar GitHub Pages — veja Configuração abaixo)*

## Estrutura do repositório

```
├── .github/
│   └── workflows/
│       └── update.yml          # Agendamento automático (3ª quinta, 12h BRT)
├── data/
│   ├── serie_subst.csv         # Série histórica (MERRA-2 1981-1995 + Sinobras 1996-hoje)
│   ├── master_monthly.csv      # Índices oceânicos MERRA-2 (Niño 3.4, TSA, PDO)
│   ├── meta_best.json          # Parâmetros do modelo SARIMAX selecionado
│   ├── fc_results_best.json    # Cenários de precipitação (7 + IRI_mean)
│   ├── scen12_best.csv         # Sumário dos cenários (DEF, EXC, probabilidades)
│   ├── sarimax_data_best.json  # SARIMAX_DATA (trimestres + monthly para o dashboard)
│   ├── bh_final.json           # Balanço hídrico convergido por cenário
│   └── SINOBRAS_new.csv        # ← COLOCAR AQUI os dados novos do campo (opcional)
├── docs/
│   └── index.html              # Dashboard HTML (publicado como GitHub Pages)
├── scripts/
│   └── update_dashboard.py     # Script principal de atualização
├── requirements.txt
└── README.md
```

## Configuração inicial

### 1. Criar o repositório no GitHub

```bash
# No GitHub: criar repositório privado chamado "sinobras-clima"
# Depois, no terminal local:
git clone https://github.com/<usuario>/sinobras-clima.git
cd sinobras-clima

# Copiar os arquivos deste pacote para dentro da pasta clonada
# e fazer o primeiro push
git add .
git commit -m "feat: setup inicial dashboard clima"
git push origin main
```

### 2. Ativar GitHub Pages

No repositório GitHub:  
`Settings → Pages → Source: Deploy from branch → Branch: main → Folder: /docs`

A URL do dashboard será: `https://<usuario>.github.io/sinobras-clima/`

### 3. Verificar o workflow

`Actions → Atualização Dashboard Clima → Run workflow`  
(para testar manualmente antes da primeira execução automática)

## Atualização mensal com dados novos do campo

Para incorporar novos dados das fazendas Sinobras:

1. **Exportar** o CSV das 34 fazendas com colunas `ano`, `mes`, `estacao`, `prec_mm`
2. **Renomear** para `SINOBRAS_new.csv`
3. **Commitar** na pasta `data/`:
   ```bash
   cp /caminho/para/SINOBRAS_new.csv data/SINOBRAS_new.csv
   git add data/SINOBRAS_new.csv
   git commit -m "data: novos dados Sinobras julho/2026"
   git push
   ```
4. O workflow detecta o arquivo automaticamente na próxima execução  
   (ou rodar manualmente: `Actions → Run workflow`)

O arquivo `SINOBRAS_new.csv` é renomeado após o processamento  
para `SINOBRAS_AAAAMM.csv` — nunca é reprocessado duas vezes.

## Atualização manual dos índices oceânicos (CPC/IRI)

Os índices ONI, Niño 3.4, TSA e probabilidades CPC/IRI são embutidos  
diretamente no HTML. Para atualizar:

1. Abrir uma conversa com Claude
2. Dizer: *"Atualize o dashboard com os dados mais recentes do CPC e IRI"*
3. Claude busca os dados, atualiza o HTML e você substitui `docs/index.html`

## Agendamento

| Item | Valor |
|------|-------|
| Frequência | Toda 3ª quinta-feira do mês |
| Horário | 12:00 BRT (15:00 UTC) |
| Duração estimada | ~4 minutos |
| Minutos Actions consumidos | ~4/mês (~48/ano, bem dentro dos 2.000 gratuitos) |
| Trigger manual | `Actions → Run workflow` |

## Modelo

**SARIMAX(N34+TSA+PDO)** — Selecionado entre 10 candidatos  
- Série: MERRA-2 (1981–1995) + Sinobras 34 FAZs (1996–hoje)  
- Preditores: Niño 3.4, TSA, PDO (lags 2–3 meses)  
- R² holdout 2018–2025: 0,78  
- RMSE: 62 mm/mês
