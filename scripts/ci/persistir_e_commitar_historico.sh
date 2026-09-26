#!/usr/bin/env bash
# scripts/ci/persistir_e_commitar_historico.sh — revisão pontual
# (Fase 2C.2, problema 1 da 2ª rodada + item 2 da 4ª rodada):
# extraído do workflow .github/workflows/nmme_extracao_historica.yml
# para ser testável fora do GitHub Actions
# (tests/test_workflow_extracao_historica.sh cria um repositório git
# local com um remoto de mentira e roda este script de verdade contra
# ele — a única forma de confirmar a mecânica de commit/push sem
# depender de uma execução real do Actions).
#
# Roda DEPOIS de `python scripts/nmme_extracao_historica.py
# --executar-lote <LOTE_ID> --localizacao <sao_bento|fazendas>` —
# mesmo quando esse comando falhou (lote REPROVADO), porque
# `executar_lote()` já escreve os CSVs em disco ANTES de reportar
# reprovação (nmme_extracao_historica.py::executar_lote — os
# resultados parciais aprovados dentro de um lote nunca ficam perdidos
# só porque outra origem do mesmo lote falhou). Este script só cuida de
# PERSISTIR o que já está no disco do runner — nunca decide se o lote
# foi aprovado (isso continua sendo sinalizado pelo exit code do passo
# Python anterior, checado separadamente no workflow).
#
# 4ª rodada — recebe o DIRETÓRIO explicitamente como 1º argumento (nunca
# mais hardcoded para data/nmme_historico/): o workflow resolve
# data/nmme_historico/ (São Bento) ou data/nmme_historico_fazendas/
# (fazendas) a partir do input `localizacao` e passa aqui. `git add`/
# `git diff --cached`/`git commit` ficam TODOS explicitamente
# restritos a esse diretório (pathspec) — nunca tocam, adicionam ou
# commitam nada da outra localização, mesmo que por algum motivo haja
# alterações não relacionadas soltas na árvore de trabalho.
#
# Uso: persistir_e_commitar_historico.sh <diretorio> <lote_id> <data_legivel>
# Variáveis de ambiente esperadas (já presentes em qualquer runner do
# GitHub Actions, ou passáveis manualmente em teste local):
#   GITHUB_REF_NAME — branch atual (default: HEAD atual via git)
set -euo pipefail

DIRETORIO="${1:?uso: persistir_e_commitar_historico.sh <diretorio> <lote_id> <data_legivel>}"
LOTE_ID="${2:?uso: persistir_e_commitar_historico.sh <diretorio> <lote_id> <data_legivel>}"
DATA="${3:?uso: persistir_e_commitar_historico.sh <diretorio> <lote_id> <data_legivel>}"
REF_NAME="${GITHUB_REF_NAME:-$(git rev-parse --abbrev-ref HEAD)}"

# Nunca falha por o diretório ainda não existir (revisão pontual,
# problema 1 da 2ª rodada: "garantir que o workflow não falhe ao
# tentar adicionar data/nmme_historico/ quando esse diretório ainda
# não existir") — o primeiro lote já rodado num checkout limpo cria o
# diretório aqui. Vale para as DUAS localizações, cada uma com seu
# próprio diretório.
mkdir -p "$DIRETORIO"

# `--` limita explicitamente ao diretório desta localização — nunca
# adiciona nem commita nada de fora dele (item 2 da 4ª rodada:
# "identificar e armazenar exclusivamente o diretório correspondente à
# localização selecionada").
git add -- "$DIRETORIO"

if git diff --cached --quiet -- "$DIRETORIO"; then
  echo "alterado=false"
  echo "Nada para commitar em ${DIRETORIO}/ (sem alteração)."
  exit 0
fi

git config user.name  "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
git commit -m "auto: NMME extração histórica — ${DIRETORIO} — lote ${LOTE_ID} — ${DATA}

Fase 2C.2 — ${DIRETORIO}/ (armazenamento permanente, commitado no
repositório, exclusivo desta localização — nunca compartilhado com o
diretório da outra). Resultados parciais são persistidos mesmo quando
uma ou mais inicializações do lote são reprovadas — a sinalização de
reprovação do lote (se houver) é reportada pelo passo seguinte do
workflow, separadamente deste commit. Nenhuma skill calculada, nenhum
dashboard alterado, nenhuma rota/representação promovida." \
  -- "$DIRETORIO"

# Outro workflow (ou outra execução deste, inclusive da OUTRA
# localização) pode ter commitado entre o checkout e aqui — rebase
# antes de empurrar (mesma convenção de indices_semanal.yml).
git pull --rebase origin "${REF_NAME}"
git push origin "HEAD:${REF_NAME}"
echo "alterado=true"
