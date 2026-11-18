#!/usr/bin/env bash
# scripts/decidir_continuidade_serie_subst.sh — Fase ENSO-INTEGRIDADE 3B.0.2
#
# Decide se a sub-checagem de continuidade temporal de serie_subst.csv
# (item 9 de verificar_dashboard.py, chamada pelo Job B de ci.yml) pode
# ser pulada. Extraído do passo "Decidir se a checagem de continuidade
# pode ser pulada" de .github/workflows/ci.yml para ser testável de
# verdade (ver tests/test_enso_integridade_fase3b0.py, classe
# AcionamentoRealDoWorkflowTestCase, que roda este MESMO script contra
# um repositório git temporário) — em vez de o teste reimplementar
# esta decisão separadamente, o que provaria só a reimplementação, não
# o ramo real da CI.
#
# Uso:
#   decidir_continuidade_serie_subst.sh <event_name> <base_ref> [head_ref]
#
# Opera sobre o repositório no diretório de trabalho ATUAL (cwd) — em
# ci.yml isso é o checkout real; em teste, um repositório git
# temporário. scripts/validar_correcao_historica_tsa.py é sempre
# resolvido pelo caminho do PRÓPRIO script (independente do cwd), via
# `--repo "$(pwd)"` para que ELE também opere sobre o repositório do
# cwd, não sobre o repositório real do projeto.
#
# Saída (stdout, ÚNICA linha, só quando o exit code é 0): "true" ou
# "false" — o valor a gravar em steps.continuidade.outputs.pular.
# Todo diagnóstico/motivo vai para stderr, nunca para o stdout que o
# chamador captura via $(...).
#
# Exit code:
#   0 — decisão normal; stdout contém exatamente "true" ou "false".
#   1 — tentativa de correção histórica de TSA detectada, mas
#       REPROVADA pelo validador (proveniência ausente/incompleta/
#       inconsistente, OU misturada com alteração não autorizada).
#       NUNCA interpretar como "pode seguir com a checagem ordinária" —
#       o chamador deve reprovar o passo explicitamente (é exatamente
#       o que a ausência de `|| true` neste script, sob `set -e` no
#       chamador, já provoca).
set -u

EVENT_NAME="${1:?uso: decidir_continuidade_serie_subst.sh <event_name> <base_ref> [head_ref]}"
BASE_REF="${2:?uso: decidir_continuidade_serie_subst.sh <event_name> <base_ref> [head_ref]}"
HEAD_REF="${3:-HEAD}"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$EVENT_NAME" != "pull_request" ]; then
  # workflow_dispatch manual, sem PR/base de comparação: mesma situação
  # estrutural do indices_semanal.yml (nunca roda fetch_monthly_data.py)
  # — pular evita o mesmo falso-positivo de calendário já corrigido
  # naquele workflow. Comportamento preservado desta fase.
  echo "workflow_dispatch manual, sem PR — tratado como indices_semanal.yml (pula por padrão)." >&2
  echo "true"
  exit 0
fi

if git diff --quiet "$BASE_REF" "$HEAD_REF" -- \
    data/master_monthly.csv data/serie_subst.csv data/indices_proveniencia.csv; then
  echo "nenhum dos 3 arquivos relevantes (master_monthly.csv/serie_subst.csv/indices_proveniencia.csv) foi tocado — lacuna do mês corrente (se houver) é defasagem de calendário pré-existente, não desta mudança." >&2
  echo "true"
  exit 0
fi

saida_validador=$(python "$DIR/validar_correcao_historica_tsa.py" "$BASE_REF" "$HEAD_REF" --repo "$(pwd)" 2>&1)
codigo_validador=$?
echo "$saida_validador" >&2

if [ "$codigo_validador" -eq 0 ]; then
  echo "diff bate exatamente com o plano fechado de correção histórica de TSA, com proveniência completa — exceção estrita da Fase ENSO-INTEGRIDADE 3B.0/3B.0.2, não uma liberação genérica." >&2
  echo "true"
  exit 0
fi

if [ "$codigo_validador" -eq 10 ]; then
  # Não é uma tentativa de correção de TSA (nenhuma célula do plano foi
  # tocada) — alteração de outra natureza. Comportamento ORDINÁRIO
  # preservado: decide só pela presença/ausência de mudança em
  # serie_subst.csv (igual a antes desta fase) — nunca força a
  # checagem cheia só porque master_monthly.csv/indices_proveniencia.csv
  # mudaram por um motivo não relacionado à TSA.
  echo "alteração em master_monthly.csv/serie_subst.csv/indices_proveniencia.csv não corresponde a nenhuma célula do plano fechado de TSA — alteração de outra natureza; comportamento ordinário preservado (decide só pela própria serie_subst.csv)." >&2
  if git diff --quiet "$BASE_REF" "$HEAD_REF" -- data/serie_subst.csv; then
    echo "true"
  else
    echo "false"
  fi
  exit 0
fi

# Qualquer outro código (hoje, só 1): tentativa de correção de TSA
# detectada e REPROVADA pelo validador — falha explícita. Nunca
# interpretado como "continuidade completa, pode seguir mesmo assim".
echo "tentativa de correção histórica de TSA detectada, mas REPROVADA pelo validador (ver detalhes acima) — esta PR não pode receber a exceção de continuidade nem ser tratada como alteração ordinária." >&2
exit 1
