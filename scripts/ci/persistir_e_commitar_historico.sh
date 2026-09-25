#!/usr/bin/env bash
# scripts/ci/persistir_e_commitar_historico.sh — revisão pontual
# (Fase 2C.2, problema 1 da revisão): extraído do workflow
# .github/workflows/nmme_extracao_historica.yml para ser testável fora
# do GitHub Actions (tests/test_workflow_extracao_historica.sh cria um
# repositório git local com um remoto de mentira e roda este script de
# verdade contra ele — a única forma de confirmar a mecânica de
# commit/push sem depender de uma execução real do Actions).
#
# Roda DEPOIS de `python scripts/nmme_extracao_historica.py
# --executar-lote <LOTE_ID>` — mesmo quando esse comando falhou (lote
# REPROVADO), porque `executar_lote()` já escreve os CSVs em
# data/nmme_historico/ ANTES de reportar reprovação (nmme_
# extracao_historica.py::executar_lote — os resultados parciais
# aprovados dentro de um lote nunca ficam perdidos só porque outra
# origem do mesmo lote falhou). Este script só cuida de PERSISTIR o que
# já está no disco do runner — nunca decide se o lote foi aprovado
# (isso continua sendo sinalizado pelo exit code do passo Python
# anterior, checado separadamente no workflow).
#
# Uso: persistir_e_commitar_historico.sh <lote_id> <data_legivel>
# Variáveis de ambiente esperadas (já presentes em qualquer runner do
# GitHub Actions, ou passáveis manualmente em teste local):
#   GITHUB_REF_NAME — branch atual (default: HEAD atual via git)
set -euo pipefail

LOTE_ID="${1:?uso: persistir_e_commitar_historico.sh <lote_id> <data_legivel>}"
DATA="${2:?uso: persistir_e_commitar_historico.sh <lote_id> <data_legivel>}"
REF_NAME="${GITHUB_REF_NAME:-$(git rev-parse --abbrev-ref HEAD)}"

# Nunca falha por o diretório ainda não existir (revisão pontual,
# problema 1: "garantir que o workflow não falhe ao tentar adicionar
# data/nmme_historico/ quando esse diretório ainda não existir") — o
# primeiro lote já rodado num checkout limpo cria o diretório aqui.
mkdir -p data/nmme_historico

git add data/nmme_historico

if git diff --cached --quiet; then
  echo "alterado=false"
  echo "Nada para commitar em data/nmme_historico/ (sem alteração)."
  exit 0
fi

git config user.name  "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
git commit -m "auto: NMME extração histórica — lote ${LOTE_ID} — ${DATA}

Fase 2C.2 — data/nmme_historico/ (armazenamento permanente,
commitado no repositório). Resultados parciais são persistidos mesmo
quando uma ou mais inicializações do lote são reprovadas — a
sinalização de reprovação do lote (se houver) é reportada pelo passo
seguinte do workflow, separadamente deste commit. Nenhuma skill
calculada, nenhum dashboard alterado, nenhuma rota/representação
promovida."

# Outro workflow (ou outra execução deste) pode ter commitado entre o
# checkout e aqui — rebase antes de empurrar (mesma convenção de
# indices_semanal.yml).
git pull --rebase origin "${REF_NAME}"
git push origin "HEAD:${REF_NAME}"
echo "alterado=true"
