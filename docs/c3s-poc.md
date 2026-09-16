# C3S POC — como rodar

Prova de conceito manual do C3S/SEAS5 (Fase 2A). Roda no GitHub Actions
porque o ambiente Claude Code Web bloqueia o domínio
`cds.climate.copernicus.eu` por política de rede.

## Passo a passo

1. **Criar conta no CDS** — [cds.climate.copernicus.eu](https://cds.climate.copernicus.eu),
   cadastro gratuito.

2. **Aceitar os termos do dataset** — abra a página do dataset
   *"Seasonal forecast monthly statistics on single levels"* no CDS,
   role até "Terms of use" e aceite. Sem isso, o download falha com
   erro de permissão mesmo com token válido.

3. **Obter o Personal Access Token** — na sua página de perfil do CDS
   (ícone da conta → "Your profile" / "API keys"), copie o token
   pessoal.

4. **Criar o GitHub Secret** — neste repositório, vá em
   **Settings → Secrets and variables → Actions → New repository
   secret**. Nome exato: `CDS_API_KEY`. Cole só o token (sem a linha
   `url:`, sem `key:`, só o valor).

5. **Abrir a aba Actions** do repositório no GitHub.

6. **Selecionar o workflow "C3S POC"** na lista à esquerda.

7. **Clicar em "Run workflow"** — ajuste os campos se quiser (município,
   ano/mês de inicialização, leads) ou deixe os padrões (São Bento do
   Tocantins, jan/2015, leads 1,2,3 — todos dentro do período de
   hindcast do SEAS5, 1993-2016).

8. **Baixar o artifact** — ao terminar, a execução do workflow mostra um
   link de artifact chamado `c3s-poc-resultado`, contendo
   `c3s_poc_raw.csv`, `c3s_poc_summary.csv` e `c3s_poc_metadata.json`.
   O resumo (Actions Summary) já mostra a tabela principal sem precisar
   baixar nada.

## O que NÃO fazer

- Não cole o token em nenhum lugar além do campo do GitHub Secret.
- Não rode este workflow por cron — é manual por desenho.
- Não espere o histórico completo de hindcast — isso é só 1 sistema, 1
  município, 1 data de inicialização, poucos leads.
