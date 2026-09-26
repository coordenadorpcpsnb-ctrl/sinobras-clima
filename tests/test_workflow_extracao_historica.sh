#!/usr/bin/env bash
# tests/test_workflow_extracao_historica.sh — revisão pontual (Fase
# 2C.2, 2ª e 4ª rodadas): testa a LÓGICA OPERACIONAL do workflow
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
#   1. Diretório da localização ainda não existe -> mkdir -p não
#      falha, commit+push funcionam (São Bento).
#   2. Rodar de novo sem nenhuma mudança -> "alterado=false", sem erro,
#      sem commit vazio.
#   3. Push concorrente (outro clone commita entre o checkout e o
#      nosso push) -> `git pull --rebase` resolve, push funciona sem
#      intervenção manual.
#   4. (4ª rodada) As DUAS localidades — São Bento e fazendas — cada
#      uma com o script recebendo SEU PRÓPRIO diretório: nunca
#      commitam/tocam no diretório uma da outra, mesmo rodando na
#      mesma árvore de trabalho, na mesma sequência.
#   5. (4ª rodada) Regressão explícita: chamar o script com o
#      diretório das fazendas NUNCA cria/altera nada dentro de
#      data/nmme_historico/ (e vice-versa) — mesmo que os dois
#      diretórios existam simultaneamente na árvore de trabalho.
#   6. (4ª rodada) O workflow YAML de fato repassa `--localizacao` para
#      --executar-lote E --consolidar, resolve o diretório a partir do
#      input (nunca hardcoded) e identifica a localização no nome do
#      artifact — checado por grep sobre o próprio arquivo YAML,
#      guarda-chuva contra alguém reverter/esquecer a flag.
#
# Roda com:
#   bash tests/test_workflow_extracao_historica.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$ROOT_DIR/scripts/ci/persistir_e_commitar_historico.sh"
WORKFLOW_YAML="$ROOT_DIR/.github/workflows/nmme_extracao_historica.yml"

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

assert_grep() {
  local arquivo="$1" padrao="$2" descricao="$3"
  if grep -Fq -- "$padrao" "$arquivo"; then
    echo "  ok: $descricao"
  else
    echo "FALHA: $descricao — padrão não encontrado em $arquivo: $padrao"
    FALHAS=$((FALHAS + 1))
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

DIR_SB="data/nmme_historico"
DIR_FAZ="data/nmme_historico_fazendas"

echo "=== Teste 1: diretório de São Bento ainda não existe ==="
if [ -d "$DIR_SB" ]; then
  echo "FALHA: $DIR_SB já existia antes do teste (checkout inesperado)"
  FALHAS=$((FALHAS + 1))
fi
mkdir -p "$DIR_SB"
echo "ano,mes,poc_status" > "$DIR_SB/lote_1991-1994_resumo_por_origem.csv"
echo "1991,1,APROVADO" >> "$DIR_SB/lote_1991-1994_resumo_por_origem.csv"
SAIDA1=$(bash "$SCRIPT" "$DIR_SB" "1991-1994" "25/09/2026 12:00 BRT" 2>&1)
echo "$SAIDA1" | grep -q "alterado=true" && OK1=alterado=true || OK1=alterado=false
assert_eq "alterado=true" "$OK1" "commit+push funcionam com o diretório recém-criado (São Bento)"
REMOTO_TEM_ARQUIVO=$(git --git-dir="$TMP/origin.git" ls-tree -r --name-only main \
  | grep -c "lote_1991-1994_resumo_por_origem.csv" || true)
assert_eq "1" "$REMOTO_TEM_ARQUIVO" "arquivo do lote chegou no remoto (origin)"

echo
echo "=== Teste 2: rodar de novo sem nenhuma mudança ==="
SAIDA2=$(bash "$SCRIPT" "$DIR_SB" "1991-1994" "25/09/2026 12:05 BRT" 2>&1)
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
echo "ano,mes,poc_status" > "$DIR_SB/lote_1995-1998_resumo_por_origem.csv"
echo "1995,1,REPROVADO" >> "$DIR_SB/lote_1995-1998_resumo_por_origem.csv"
SAIDA3=$(bash "$SCRIPT" "$DIR_SB" "1995-1998" "25/09/2026 12:10 BRT" 2>&1)
echo "$SAIDA3" | grep -q "alterado=true" && OK3=alterado=true || OK3=alterado=false
assert_eq "alterado=true" "$OK3" "push funciona mesmo com commit concorrente (pull --rebase resolve)"
REMOTO_TEM_AMBOS=$(git --git-dir="$TMP/origin.git" ls-tree -r --name-only main \
  | grep -c "lote_199[15]-19" || true)
assert_eq "2" "$REMOTO_TEM_AMBOS" "os dois lotes (1991-1994 e 1995-1998) e o commit concorrente coexistem no remoto"
REMOTO_TEM_CONCORRENTE=$(git --git-dir="$TMP/origin.git" ls-tree -r --name-only main \
  | grep -c "arquivo_concorrente.txt" || true)
assert_eq "1" "$REMOTO_TEM_CONCORRENTE" "o commit concorrente não foi perdido pelo rebase"

echo
echo "=== Teste 4: fazendas — diretório próprio, também ainda não existe ==="
if [ -d "$DIR_FAZ" ]; then
  echo "FALHA: $DIR_FAZ já existia antes do teste"
  FALHAS=$((FALHAS + 1))
fi
mkdir -p "$DIR_FAZ"
echo "ano,mes,poc_status" > "$DIR_FAZ/lote_1991-1994_resumo_por_origem.csv"
echo "1991,1,APROVADO" >> "$DIR_FAZ/lote_1991-1994_resumo_por_origem.csv"
SAIDA4=$(bash "$SCRIPT" "$DIR_FAZ" "1991-1994" "25/09/2026 12:15 BRT" 2>&1)
echo "$SAIDA4" | grep -q "alterado=true" && OK4=alterado=true || OK4=alterado=false
assert_eq "alterado=true" "$OK4" "commit+push funcionam com o diretório das fazendas recém-criado"

echo
echo "=== Teste 5 (regressão central, item 4 da 4ª rodada): fazendas nunca toca em São Bento e vice-versa ==="
# No estado atual do commit de fazendas, confirma que NENHUM arquivo
# de data/nmme_historico/ (São Bento) foi incluído.
ARQUIVOS_COMMIT_FAZ=$(git show --stat --format="" HEAD)
if echo "$ARQUIVOS_COMMIT_FAZ" | grep -q "^ data/nmme_historico/"; then
  echo "FALHA: commit das fazendas tocou em data/nmme_historico/ (São Bento) — MISTURA DE LOCALIDADES"
  FALHAS=$((FALHAS + 1))
else
  echo "  ok: commit das fazendas não tocou em data/nmme_historico/ (São Bento)"
fi

# Roda mais uma vez para São Bento (mudança nova) e confirma que o
# commit resultante não inclui nada de data/nmme_historico_fazendas/.
echo "ano,mes,poc_status" > "$DIR_SB/lote_1999-2002_resumo_por_origem.csv"
echo "1999,1,APROVADO" >> "$DIR_SB/lote_1999-2002_resumo_por_origem.csv"
bash "$SCRIPT" "$DIR_SB" "1999-2002" "25/09/2026 12:20 BRT" >/dev/null 2>&1
ARQUIVOS_COMMIT_SB=$(git show --stat --format="" HEAD)
if echo "$ARQUIVOS_COMMIT_SB" | grep -q "^ data/nmme_historico_fazendas/"; then
  echo "FALHA: commit de São Bento tocou em data/nmme_historico_fazendas/ — MISTURA DE LOCALIDADES"
  FALHAS=$((FALHAS + 1))
else
  echo "  ok: commit de São Bento não tocou em data/nmme_historico_fazendas/"
fi

# Confirma que as duas árvores persistidas no remoto continuam
# separadas e cada uma só tem os arquivos da sua própria localização.
REMOTO_SB_TEM_FAZENDAS=$(git --git-dir="$TMP/origin.git" ls-tree -r --name-only main -- "$DIR_SB" \
  | grep -c "fazendas" || true)
assert_eq "0" "$REMOTO_SB_TEM_FAZENDAS" "diretório de São Bento no remoto não contém nenhum arquivo de fazendas"
REMOTO_FAZ_TEM_SO_FAZENDAS=$(git --git-dir="$TMP/origin.git" ls-tree -r --name-only main -- "$DIR_FAZ" | wc -l | tr -d ' ')
assert_eq "1" "$REMOTO_FAZ_TEM_SO_FAZENDAS" "diretório das fazendas no remoto contém só o arquivo dele mesmo"

echo
echo "=== Teste 6: wiring do workflow YAML — localização repassada, nunca hardcoded ==="
if [ ! -f "$WORKFLOW_YAML" ]; then
  echo "FALHA: $WORKFLOW_YAML não existe"
  FALHAS=$((FALHAS + 1))
else
  assert_grep "$WORKFLOW_YAML" '--executar-lote "${{ inputs.lote_id }}"' \
    "workflow chama --executar-lote com o lote_id"
  assert_grep "$WORKFLOW_YAML" '--localizacao "${{ inputs.localizacao }}"' \
    "workflow repassa --localizacao (usado tanto no lote real quanto na consolidação)"
  assert_grep "$WORKFLOW_YAML" '--consolidar --localizacao "${{ inputs.localizacao }}"' \
    "consolidação recebe --localizacao explicitamente"
  assert_grep "$WORKFLOW_YAML" 'steps.resolver_diretorio.outputs.diretorio' \
    "persistência/publicação usam o diretório resolvido a partir do input, nunca hardcoded"
  assert_grep "$WORKFLOW_YAML" 'name: nmme-extracao-historica-${{ inputs.localizacao }}-lote-${{ inputs.lote_id }}' \
    "nome do artifact identifica a localização sem ambiguidade"
  # Nunca mais um caminho hardcoded 'data/nmme_historico/lote_' solto
  # fora do bloco de resolução de diretório (regressão: o bug antigo
  # era exatamente isso — caminho fixo, ignorando a localização
  # selecionada).
  if grep -F 'data/nmme_historico/lote_${{ inputs.lote_id }}' "$WORKFLOW_YAML" > /dev/null; then
    echo "FALHA: workflow ainda tem caminho hardcoded para data/nmme_historico/ (ignora --localizacao)"
    FALHAS=$((FALHAS + 1))
  else
    echo "  ok: nenhum caminho hardcoded para data/nmme_historico/ restante no workflow"
  fi
fi

echo
if [ "$FALHAS" -eq 0 ]; then
  echo "✅ TODOS OS TESTES DA LÓGICA OPERACIONAL DO WORKFLOW PASSARAM"
  exit 0
else
  echo "❌ $FALHAS TESTE(S) FALHARAM"
  exit 1
fi
