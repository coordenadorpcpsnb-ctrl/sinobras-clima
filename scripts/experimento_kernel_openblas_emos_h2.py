#!/usr/bin/env python3
"""
scripts/experimento_kernel_openblas_emos_h2.py — Fase ENSO-CI,
experimento controlado comparando os kernels OpenBLAS Haswell e
SkylakeX nos 2 testes EMOS H2 que falham intermitentemente no runner
real (run 39605920724: kernel Haswell → FAIL, kernel SkylakeX → PASS,
mas com CPUs diferentes — este experimento tenta isolar o kernel como
variável, mantendo a mesma CPU constante).

TEMPORÁRIO — igual a tests/test_diagnostico_emos_h2_ci.py, considerar
remoção depois da investigação, preservando as conclusões em
documentação.

Desenho (dois modos no mesmo arquivo, para evitar duplicar lógica):

- Modo DRIVER (padrão, `_EXPERIMENTO_WORKER` não definido): para cada
  kernel pretendido, primeiro verifica por via SEGURA (flags de
  /proc/cpuinfo) se a CPU anuncia os recursos mínimos daquele kernel
  — nunca força um kernel sem essa checagem (requisito 2 da revisão
  externa). Se a checagem indicar risco, NÃO tenta — registra
  'nao_tentado', nunca força. Se passar, lança um processo Python
  NOVO (subprocess), com OPENBLAS_CORETYPE definido no ambiente ANTES
  do processo começar (logo antes de qualquer import de numpy/scipy
  acontecer dentro dele — requisito 1), em modo WORKER. Os dois
  kernels rodam sequencialmente, no mesmo job/runner (mesma CPU),
  nunca em paralelo.

- Modo WORKER (`_EXPERIMENTO_WORKER=1`, processo filho): importa
  numpy/scipy (só agora, depois do ambiente já estar definido pelo
  pai), aquece o BLAS e confirma via threadpoolctl.threadpool_info()
  qual arquitetura REALMENTE carregou — nunca presume que
  OPENBLAS_CORETYPE foi respeitado só porque foi definido (requisito
  4). Se a arquitetura confirmada não corresponder à pedida, reporta
  'inconclusivo' e PARA — não roda os testes reais nesse caso. Se
  confirmar, roda os 2 MÉTODOS DE TESTE ORIGINAIS (via
  tests.test_diagnostico_emos_h2_ci._rodar_metodo_original — mesma
  função já usada e validada nos Jobs D/E, nenhuma fixture duplicada)
  e imprime um único JSON na última linha de stdout com tudo: kernel
  pedido/confirmado, backend completo, threads, e o resultado de cada
  teste (passou/mensagem/todas as chamadas minimize com
  success/status/message/nit/nfev/fun/x/jac/dist_bounds).

Um processo WORKER que trava com SIGILL (instrução não suportada pela
CPU real, apesar da checagem de flags) é um crash do PROCESSO FILHO —
o DRIVER nunca crasha com ele, só inspeciona o returncode (negativo em
Unix = morto por sinal) e registra como inconclusivo. Nenhum
continue-on-error de YAML é necessário: a tolerância a esse tipo de
falha é tratada aqui, em Python, de forma explícita e visível — nunca
silenciosa.

Não altera cfsv2_emos_h2_implementacao.py nem
tests/test_cfsv2_emos_h2_implementacao.py. Não altera tolerâncias,
critérios de convergência, parâmetros, bounds ou dados.

Classificação final (revisão externa, item 3 — explícita e nunca
mascarada, sem continue-on-error/`|| true`): cada kernel é
PASS (executou e os 2 testes passaram), FAIL (executou e pelo menos
um reprovou) ou INCONCLUSIVO (não executou de verdade — kernel não
tentado por segurança, não confirmado pelo threadpoolctl, processo
morto por sinal, timeout ou saída não parseável). O Job inteiro é
FAIL se qualquer kernel for FAIL (`sys.exit(1)`, propaga de verdade,
sem mecanismo de mascaramento); PASS só se pelo menos um kernel
executou e nenhum reprovou; INCONCLUSIVO (`sys.exit(0)`, mas rotulado
explicitamente como tal, nunca como aprovação) se nenhum kernel
chegou a executar. O resultado científico completo (PASS/FAIL de cada
teste, em cada kernel, com todos os campos do OptimizeResult) é
sempre impresso, nunca resumido a ponto de esconder uma reprovação.

Roda com:
    python scripts/experimento_kernel_openblas_emos_h2.py
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Requisitos mínimos de flags de CPU (de /proc/cpuinfo) para cada
# kernel do OpenBLAS ser, com razoável segurança, executável sem
# SIGILL. Lista conservadora (recursos centrais de cada microarquitetura
# que o OpenBLAS usa nos kernels de mesmo nome) — não é garantia formal
# (microcódigo/variações de CPU poderiam divergir), por isso o
# experimento AINDA confirma via threadpoolctl depois (requisito 3/4) e
# o driver ainda trata um crash do processo filho sem propagar.
_REQUISITOS_KERNEL = {
    'HASWELL': {'avx2', 'fma', 'bmi2'},
    'SKYLAKEX': {'avx512f', 'avx512bw', 'avx512dq', 'avx512vl', 'avx512cd'},
}

_NUM_THREADS_CONSTANTE = '4'  # mesmo valor observado nos runs reais (D/E) — mantido fixo nas duas configs


def _flags_cpu():
    try:
        with open('/proc/cpuinfo') as f:
            for linha in f:
                if linha.startswith('flags') or linha.startswith('Features'):
                    return set(linha.split(':', 1)[1].strip().split())
    except OSError:
        pass
    return set()


def _cpu_suporta_kernel_com_seguranca(kernel):
    """Checagem heurística, nunca uma garantia formal — só reduz o
    risco de tentar um kernel claramente incompatível. 'Verdadeiro'
    aqui não implica ausência de SIGILL (daí a confirmação posterior
    via threadpoolctl e a tolerância do driver a um crash do filho);
    'Falso' é motivo suficiente para NUNCA tentar (requisito 2/5)."""
    necessarios = _REQUISITOS_KERNEL.get(kernel.upper())
    if necessarios is None:
        return False, f'kernel {kernel!r} sem lista de requisitos conhecida nesta investigação'
    flags = _flags_cpu()
    if not flags:
        return False, '/proc/cpuinfo não informou "flags" — não há base para decidir com segurança'
    faltando = sorted(necessarios - flags)
    if faltando:
        return False, f'CPU não anuncia os recursos mínimos deste kernel: {faltando}'
    return True, f'CPU anuncia todos os recursos mínimos deste kernel ({sorted(necessarios)})'


def _modo_worker():
    kernel_pedido = os.environ.get('OPENBLAS_CORETYPE', '')
    resultado = {'kernel_pedido': kernel_pedido}

    sys.path.insert(0, str(ROOT))
    import numpy as np  # noqa: F401  (import só agora, ambiente já definido pelo pai)
    from tests.test_diagnostico_emos_h2_ci import (  # noqa: E402
        _TESTE_1, _TESTE_2, _backend_blas_efetivo, _info_ambiente, _minimize_instrumentado,
        _restaurar_minimize_original, _rodar_metodo_original, emos,
    )

    # Revisão externa (item 2.2/2.3): registrar CPU/instruções/versões
    # explicitamente, não só o backend BLAS. Reusa _info_ambiente() (já
    # validada em Job D/E) em vez de duplicar a leitura de versões —
    # ela já inclui cpu_model e o backend_blas_efetivo completo.
    resultado['ambiente'] = _info_ambiente()
    resultado['flags_cpu_relevantes'] = sorted(
        _flags_cpu() & set().union(*_REQUISITOS_KERNEL.values()))

    backend = resultado['ambiente']['backend_blas_efetivo']  # mesmo dict, já aquecido por _info_ambiente()
    resultado['backend'] = backend

    confirmado = False
    arquiteturas_vistas = []
    if backend.get('disponivel'):
        arquiteturas_vistas = sorted({
            (b.get('architecture') or '').upper() for b in backend['bibliotecas']
        })
        confirmado = kernel_pedido.upper() in arquiteturas_vistas

    resultado['kernel_confirmado'] = confirmado
    resultado['arquiteturas_vistas'] = arquiteturas_vistas

    if not confirmado:
        # Requisito 4/5: nunca presumir que OPENBLAS_CORETYPE foi
        # respeitado — se threadpoolctl não confirma, para aqui e
        # marca inconclusivo, sem rodar os testes reais sob uma
        # premissa não verificada.
        resultado['status'] = 'inconclusivo'
        resultado['motivo'] = (
            f'OPENBLAS_CORETYPE={kernel_pedido!r} não resultou na arquitetura esperada '
            f'segundo threadpoolctl (visto: {arquiteturas_vistas or "nenhuma biblioteca BLAS detectada"}) '
            '— a variável de ambiente não garante a seleção; OpenBLAS pode ignorá-la '
            'silenciosamente e cair no autodetect.')
        print(json.dumps(resultado, ensure_ascii=False, default=str))
        return

    resultado['num_threads_observado'] = [b.get('num_threads') for b in backend['bibliotecas']]

    # Roda os 2 MÉTODOS DE TESTE ORIGINAIS — nenhuma fixture duplicada,
    # mesmo mecanismo já usado e validado nos Jobs D/E.
    emos.minimize = _minimize_instrumentado
    try:
        passou1, msg1, chamadas1 = _rodar_metodo_original(*_TESTE_1)
        passou2, msg2, chamadas2 = _rodar_metodo_original(*_TESTE_2)
    finally:
        _restaurar_minimize_original()  # restaura sempre, mesmo se algo acima lançar

    resultado['status'] = 'executado'
    resultado['teste_1'] = {'nome': '.'.join(_TESTE_1), 'passou': passou1,
                             'mensagem': msg1, 'chamadas': chamadas1}
    resultado['teste_2'] = {'nome': '.'.join(_TESTE_2), 'passou': passou2,
                             'mensagem': msg2, 'chamadas': chamadas2}
    print(json.dumps(resultado, ensure_ascii=False, default=str))


def _classificar_kernel(r):
    """Revisão externa (item 3): PASS/FAIL/INCONCLUSIVO têm que ser
    explícitos e distintos — nunca 'não deu pra tentar' lido como
    aprovação, nunca uma reprovação real mascarada. FAIL exige que o
    teste tenha REALMENTE EXECUTADO (status 'executado') e reprovado;
    qualquer outro status ('nao_tentado', 'inconclusivo',
    'falhou_no_processo', 'timeout', 'saida_nao_parseavel') é sempre
    INCONCLUSIVO, nunca PASS nem FAIL."""
    if r.get('status') != 'executado':
        return 'INCONCLUSIVO'
    if r['teste_1']['passou'] and r['teste_2']['passou']:
        return 'PASS'
    return 'FAIL'


def _classificar_job(resultados):
    """Agregado do Job F inteiro. FAIL se qualquer kernel reprovou
    (uma falha científica real executada nunca é só 'um dos dois');
    PASS só se pelo menos um kernel executou e todos os executados
    passaram; INCONCLUSIVO se nenhum kernel chegou a executar — nesse
    caso o Job F termina com exit 0, mas rotulado explicitamente como
    'não é aprovação científica', nunca como sucesso silencioso."""
    classificacoes = {k: _classificar_kernel(r) for k, r in resultados.items()}
    if 'FAIL' in classificacoes.values():
        return 'FAIL', classificacoes, 1
    if 'PASS' in classificacoes.values():
        return 'PASS', classificacoes, 0
    return 'INCONCLUSIVO', classificacoes, 0


def _imprimir_comparacao(resultados, classificacoes):
    print('\n' + '=' * 70)
    print('COMPARAÇÃO — kernel OpenBLAS (Haswell vs. SkylakeX), EMOS H2')
    print('=' * 70)
    for kernel, r in resultados.items():
        print(f'\n--- {kernel}: {classificacoes[kernel]} ---')
        print(f'  status do mecanismo: {r.get("status")}')
        if r.get('status') != 'executado':
            print(f'  motivo: {r.get("motivo")}')
            print('  INCONCLUSIVO não é aprovação científica — nenhum teste real rodou sob este kernel.')
            continue
        ambiente = r.get('ambiente', {})
        print(f'  cpu_model: {ambiente.get("cpu_model")}')
        print(f'  python/numpy/scipy: {ambiente.get("python")}/{ambiente.get("numpy")}/{ambiente.get("scipy")}')
        print(f'  flags de CPU relevantes: {r.get("flags_cpu_relevantes")}')
        print(f'  arquitetura confirmada (threadpoolctl): {r.get("arquiteturas_vistas")}')
        print(f'  threads observadas: {r.get("num_threads_observado")}')
        for chave in ('teste_1', 'teste_2'):
            t = r[chave]
            print(f'  {t["nome"]}: {"PASS" if t["passou"] else "FAIL"} '
                  f'({len(t["chamadas"])} chamadas minimize)')
            for c in t['chamadas']:
                if c['status'] == 2:  # só a(s) chamada(s) ABNORMAL, para não poluir
                    print(f'    chamada ABNORMAL: fun_final={c["fun_final"]} '
                          f'jac={c["jac"]} dist_bounds={c["dist_bounds"]}')
    print('=' * 70)


def _modo_driver():
    resultados = {}
    for kernel in ('HASWELL', 'SKYLAKEX'):
        ok_seguranca, motivo_seguranca = _cpu_suporta_kernel_com_seguranca(kernel)
        if not ok_seguranca:
            resultados[kernel] = {'status': 'nao_tentado', 'motivo': motivo_seguranca}
            print(f'{kernel}: NÃO TENTADO — {motivo_seguranca}')
            continue

        env = dict(os.environ)
        env['OPENBLAS_CORETYPE'] = kernel
        env['OPENBLAS_NUM_THREADS'] = _NUM_THREADS_CONSTANTE
        env['OMP_NUM_THREADS'] = _NUM_THREADS_CONSTANTE
        env['_EXPERIMENTO_WORKER'] = '1'

        print(f'{kernel}: checagem de segurança OK ({motivo_seguranca}) — lançando processo novo...')
        try:
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve())],
                env=env, cwd=str(ROOT), capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            resultados[kernel] = {'status': 'timeout', 'motivo': 'processo filho excedeu 120s'}
            print(f'{kernel}: TIMEOUT')
            continue

        if proc.returncode != 0:
            resultados[kernel] = {
                'status': 'falhou_no_processo',
                'returncode': proc.returncode,
                'motivo': (
                    'processo encerrado por sinal (possível SIGILL — kernel forçado não '
                    'suportado de fato por esta CPU, apesar da checagem de flags) — tratado '
                    'como inconclusivo, não como falha do experimento'
                    if proc.returncode < 0 else
                    f'saída não-zero inesperada ({proc.returncode}) — ver stderr'),
                'stderr_tail': proc.stderr[-4000:],
            }
            print(f'{kernel}: PROCESSO FALHOU (returncode={proc.returncode}) — {resultados[kernel]["motivo"]}')
            continue

        ultima_linha = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ''
        try:
            resultados[kernel] = json.loads(ultima_linha)
        except (json.JSONDecodeError, IndexError) as e:
            resultados[kernel] = {
                'status': 'saida_nao_parseavel', 'motivo': str(e),
                'stdout_tail': proc.stdout[-4000:], 'stderr_tail': proc.stderr[-4000:],
            }
            print(f'{kernel}: SAÍDA NÃO PARSEÁVEL — {e}')
            continue

        print(f'{kernel}: concluído, status={resultados[kernel].get("status")}')

    print('\n' + json.dumps(resultados, indent=2, ensure_ascii=False, default=str))
    classificacao_job, classificacoes, codigo_saida = _classificar_job(resultados)
    _imprimir_comparacao(resultados, classificacoes)
    print(f'\nCLASSIFICAÇÃO FINAL DO JOB F: {classificacao_job}')
    if classificacao_job == 'INCONCLUSIVO':
        print('INCONCLUSIVO — nenhum kernel pôde ser executado/confirmado com segurança nesta '
              'run; isto NÃO valida nem aprova o modelo, só significa que este experimento '
              'não produziu dado utilizável nesta execução.')
    elif classificacao_job == 'FAIL':
        print('FAIL — pelo menos um kernel reproduziu a reprovação científica real dos testes '
              'EMOS H2 (ver detalhes acima). Job F sinaliza isso via exit code, sem '
              'continue-on-error nem qualquer mecanismo que mascare o resultado.')
    return codigo_saida


if __name__ == '__main__':
    if os.environ.get('_EXPERIMENTO_WORKER') == '1':
        _modo_worker()
        sys.exit(0)  # o worker nunca decide PASS/FAIL do job — só reporta dados ao driver
    else:
        sys.exit(_modo_driver())
