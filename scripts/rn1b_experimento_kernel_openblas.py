#!/usr/bin/env python3
"""
Fase RN-1B — driver dos experimentos controlados de reprodutibilidade
numérica do EMOS H2 (ver docs/enso-rn1b-experimento-kernel-openblas.md
para o desenho completo). NÃO importa numpy/scipy neste processo — cada
combinação roda em `scripts/rn1b_worker_captura_emos_h2.py`, um processo
Python filho totalmente novo, com as variáveis de ambiente já definidas
ANTES do `subprocess.run` (garantindo que numpy/scipy, quando importados
pelo filho, já veem OPENBLAS_CORETYPE/OPENBLAS_NUM_THREADS corretos —
não há como mudar isso depois do import no mesmo processo).

Não modifica nenhum arquivo, fórmula, bound, tolerância ou critério do
EMOS H2 — só invoca scripts/rn1b_worker_captura_emos_h2.py repetidamente.

Uso:
    python scripts/rn1b_experimento_kernel_openblas.py --saida resultados.jsonl
"""
import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path

WORKER = Path(__file__).parent / 'rn1b_worker_captura_emos_h2.py'

# Grupos confirmados LOCALMENTE nesta fase (ver relatório RN-1B) antes de
# qualquer execução real no GitHub Actions:
#   - "ZEN" não é um kernel distinto nesta wheel scipy-openblas64
#     0.3.31.188.0/0.3.30 — mapeia para o MESMO código do Haswell
#     (confirmado via threadpoolctl, não suposto). G3/G4 do pedido
#     original usam por isso "SANDYBRIDGE" (confirmado compilado,
#     confirmado AVX1-only — compatível com qualquer CPU AVX2, nunca
#     testado neste projeto, kernel genuinamente DIFERENTE do Haswell).
#   - SkylakeX NUNCA é usado como kernel forçado aqui — exige AVX-512,
#     ausente na CPU observada nos runs reais (AMD EPYC 7763).
GRUPOS = [
    {'id': 'G0', 'descricao': 'automático, 4 threads (igual ao CI hoje)',
     'coretype': None, 'num_threads': '4'},
    {'id': 'G1', 'descricao': 'automático, 1 thread',
     'coretype': None, 'num_threads': '1'},
    {'id': 'G2', 'descricao': 'Haswell explícito, 4 threads (controle: reproduz o automático)',
     'coretype': 'HASWELL', 'num_threads': '4'},
    {'id': 'G3', 'descricao': 'Sandybridge explícito (kernel alternativo confirmado disponível), 4 threads',
     'coretype': 'SANDYBRIDGE', 'num_threads': '4'},
    {'id': 'G4', 'descricao': 'Sandybridge explícito, 1 thread',
     'coretype': 'SANDYBRIDGE', 'num_threads': '1'},
]

REPETICOES_PADRAO = 5


def rodar_uma_repeticao(grupo, repeticao):
    import os
    env = os.environ.copy()
    if grupo['coretype'] is not None:
        env['OPENBLAS_CORETYPE'] = grupo['coretype']
    else:
        env.pop('OPENBLAS_CORETYPE', None)
    env['OPENBLAS_NUM_THREADS'] = grupo['num_threads']
    # Controla explicitamente a variável de paralelismo concorrente mais
    # provável de confundir o resultado (OpenMP, usado por scikit-learn/
    # xgboost — não pelo EMOS H2 em si, mas presente no mesmo processo
    # via import) — sem isso, um OMP_NUM_THREADS diferente do
    # OPENBLAS_NUM_THREADS pedido seria uma variável não controlada.
    env['OMP_NUM_THREADS'] = grupo['num_threads']

    proc = subprocess.run(
        [sys.executable, str(WORKER)],
        env=env, capture_output=True, text=True, timeout=120,
    )
    registro = {
        'grupo': grupo['id'], 'descricao_grupo': grupo['descricao'],
        'repeticao': repeticao,
        'coretype_pedido': grupo['coretype'], 'num_threads_pedido': grupo['num_threads'],
        'returncode': proc.returncode,
    }
    if proc.returncode != 0:
        registro['erro'] = True
        registro['stderr'] = proc.stderr[-4000:]
        return registro
    try:
        saida = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        registro['erro'] = True
        registro['stderr'] = f'falha ao decodificar stdout do worker: {exc}\nstdout={proc.stdout[-2000:]}'
        return registro
    registro['erro'] = False
    registro.update(saida)
    return registro


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--saida', required=True, help='Arquivo .jsonl de saída (um registro por linha)')
    ap.add_argument('--repeticoes', type=int, default=REPETICOES_PADRAO)
    ap.add_argument('--grupos', nargs='*', default=None,
                     help='Subconjunto de IDs de grupo a rodar (default: todos)')
    args = ap.parse_args()

    grupos = [g for g in GRUPOS if args.grupos is None or g['id'] in args.grupos]

    print(f'host platform.processor(): {platform.processor()}', file=sys.stderr)
    print(f'grupos: {[g["id"] for g in grupos]}  repeticoes: {args.repeticoes}', file=sys.stderr)

    total = len(grupos) * args.repeticoes
    feito = 0
    with open(args.saida, 'w', encoding='utf-8') as fh:
        for grupo in grupos:
            for rep in range(1, args.repeticoes + 1):
                registro = rodar_uma_repeticao(grupo, rep)
                fh.write(json.dumps(registro, ensure_ascii=False) + '\n')
                fh.flush()
                feito += 1
                status_resumo = (
                    'ERRO' if registro.get('erro') else
                    ','.join(
                        ('PASS' if r['passou'] else 'FAIL') for r in registro.get('resultados', [])
                    )
                )
                print(f'[{feito}/{total}] {grupo["id"]} rep={rep} -> {status_resumo}', file=sys.stderr)

    print(f'Concluído. Resultados em {args.saida}', file=sys.stderr)


if __name__ == '__main__':
    main()
