#!/usr/bin/env bash
# tests/test_workflow_extracao_historica.sh — revisão pontual (Fase
# 2C.2, problema 1): testa a LÓGICA OPERACIONAL do workflow
# .github/workflows/nmme_extracao_historica.yml, não só as funções
# Python. scripts/ci/persistir_e_commitar_historico.sh é rodado DE
# VERDADE (git real, sem mock) contra um repositório git local
# descartável com um "origin" também local (bare repo) — a única forma
# de confirmar que a sequência mkdir/add/diff/commit/pull --rebase/push
# funciona sem depender de uma execução real do GitHub Actions (que
# exigiria as credenciais/permissões reais do repositório, fora do
# escopo desta tarefa — GITHUB_TOKEN/contents:write só são
# verificáveis de verdade num workflow_dispatch real).
#
# Cobre:
#   1. data/nmme_historico/ ainda não existe -> mkdir -p não falha,
#      commit+push funcionam.
#   2. Rodar de novo sem nenhuma mudança -> "alterado=false", sem erro,
#      sem commit vazio.
#   3. Push concorrente (outro clone commita entre o checkout e o
#      nosso push) -> `git pull --rebase` resolve, push funciona sem
#      intervenção manual.
#
# Roda com:
#   bash tests/test_workflow_extracao_historica.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT_DIR/scripts/ci/persistir_e_commitar_historico.sh"

if [ ! -x "$SCRIPT" ]; then
  echo "FALHA: $SCRIPT não existe ou não é executável"
  exit 1
fi

FALHAS=0
assert_eq() {
  local esperado="$1" observado="$2" descricao="$3"
  if [ "$esperado" != "$observado" ]; then
    echo "FALHA: $descricao — esperado='$esperado' observado='$observado'"
    FALHAS=$((FALHAS + 1))
  else
    echo "  ok: $descricao"
  fi
}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

git init --bare -q "$TMP/origin.git"
git --git-dir="$TMP/origin.git" symbolic-ref HEAD refs/heads/main

git clone -q "$TMP/origin.git" "$TMP/seed"
(
  cd "$TMP/seed"
  git config user.name "tester"
  git config user.email "tester@example.com"
  echo "seed" > README.md
  git add README.md
  git commit -q -m "seed"
  git push -q origin HEAD:main
)

git clone -q "$TMP/origin.git" "$TMP/runner"
cd "$TMP/runner"
git checkout -q main
export GITHUB_REF_NAME=main
git config user.name "tester"
git config user.email "tester@example.com"

echo "=== Teste 1: diretório data/nmme_historico ainda não existe ==="
if [ -d data/nmme_historico ]; then
  echo "FALHA: data/nmme_historico já existia antes do teste (checkout inesperado)"
  FALHAS=$((FALHAS + 1))
fi
mkdir -p data/nmme_historico
echo "ano,mes,poc_status" > data/nmme_historico/lote_1991-1994_resumo_por_origem.csv
echo "1991,1,APROVADO" >> data/nmme_historico/lote_1991-1994_resumo_por_origem.csv
SAIDA1=$(bash "$SCRIPT" "1991-1994" "25/09/2026 12:00 BRT" 2>&1)
echo "$SAIDA1" | grep -q "alterado=true" && OK1=alterado=true || OK1=alterado=false
assert_eq "alterado=true" "$OK1" "commit+push funcionam com o diretório recém-criado"
REMOTO_TEM_ARQUIVO=$(git --git-dir="$TMP/origin.git" ls-tree -r --name-only main \
  | grep -c "lote_1991-1994_resumo_por_origem.csv" || true)
assert_eq "1" "$REMOTO_TEM_ARQUIVO" "arquivo do lote chegou no remoto (origin)"

echo
echo "=== Teste 2: rodar de novo sem nenhuma mudança ==="
SAIDA2=$(bash "$SCRIPT" "1991-1994" "25/09/2026 12:05 BRT" 2>&1)
echo "$SAIDA2" | grep -q "alterado=false" && OK2=alterado=false || OK2=alterado=true
assert_eq "alterado=false" "$OK2" "segunda execução sem mudança não commita de novo"
N_COMMITS_REMOTO=$(git --git-dir="$TMP/origin.git" log --oneline main | wc -l | tr -d ' ')
assert_eq "2" "$N_COMMITS_REMOTO" "nenhum commit vazio foi criado (ainda só seed + lote 1991-1994)"

echo
echo "=== Teste 3: push concorrente entre o checkout e o nosso commit ==="
git clone -q "$TMP/origin.git" "$TMP/outro"
(
  cd "$TMP/outro"
  git config user.name "outro"
  git config user.email "outro@example.com"
  echo "concorrente" > arquivo_concorrente.txt
  git add arquivo_concorrente.txt
  git commit -q -m "commit concorrente de outra execução"
  git push -q origin HEAD:main
)
echo "ano,mes,poc_status" > data/nmme_historico/lote_1995-1998_resumo_por_origem.csv
echo "1995,1,REPROVADO" >> data/nmme_historico/lote_1995-1998_resumo_por_origem.csv
SAIDA3=$(bash "$SCRIPT" "1995-1998" "25/09/2026 12:10 BRT" 2>&1)
echo "$SAIDA3" | grep -q "alterado=true" && OK3=alterado=true || OK3=alterado=false
assert_eq "alterado=true" "$OK3" "push funciona mesmo com commit concorrente (pull --rebase resolve)"
REMOTO_TEM_AMBOS=$(git --git-dir="$TMP/origin.git" ls-tree -r --name-only main \
  | grep -c "lote_199[15]-19" || true)
assert_eq "2" "$REMOTO_TEM_AMBOS" "os dois lotes (1991-1994 e 1995-1998) e o commit concorrente coexistem no remoto"
REMOTO_TEM_CONCORRENTE=$(git --git-dir="$TMP/origin.git" ls-tree -r --name-only main \
  | grep -c "arquivo_concorrente.txt" || true)
assert_eq "1" "$REMOTO_TEM_CONCORRENTE" "o commit concorrente não foi perdido pelo rebase"

echo
if [ "$FALHAS" -eq 0 ]; then
  echo "✅ TODOS OS TESTES DA LÓGICA OPERACIONAL DO WORKFLOW PASSARAM"
  exit 0
else
  echo "❌ $FALHAS TESTE(S) FALHARAM"
  exit 1
fi
