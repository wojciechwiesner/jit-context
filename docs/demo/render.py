"""Render an asciinema replay of validated live measurements; never perform inference."""

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import time

ROOT = Path(__file__).parent


def emit(text, pause=0.0):
    print(text, flush=True)
    if pause:
        time.sleep(pause)


def summarize(result):
    calls = result['calls']
    tokens = sum((call.get('usage') or {}).get('total_tokens') or 0 for call in calls)
    return (len(calls), tokens, f"{result['wall_s']:.2f} s",
            f"{result['tests']['passed']}/{result['tests']['total']}")


def compare(results):
    arms = {r['arm']: r for r in results}
    off, on = (arms[f'{mode}-tools'] for mode in ('off', 'on'))
    for arm, scope in ((off, None), (on, 'receipt-import')):
        if (arm.get('offline') or arm['first_scope'] != scope or not arm['tools_seen']
                or not arm['calls'] or any(c.get('status') != 200 for c in arm['calls'])
                or not all((c.get('usage') or {}).get('total_tokens') for c in arm['calls'])):
            raise ValueError(f"Incomplete live measurement: {arm['arm']}")
    if off['requested_model'] != on['requested_model']:
        raise ValueError('A/B model mismatch')
    return off, on


def story(results):
    off, on = compare(results)
    emit('\033[2J\033[H\033[1;36mJIT CONTEXT  /  ONE TASK, TWO RUNS\033[0m')
    emit(f'Live Hermes runs | {on["requested_model"]} | terminal replay', 2)
    emit('\n$ tree receipt-import', .4)
    emit('  receipt_import/\n    normalize.py    money.py\n    service.py      repository.py    report.py\n  tests/test_import_batch.py', 3)
    emit('\n$ jit init .', .8)
    emit('  Created .planning/STATE.md in both fresh workspaces.', .8)
    emit('  Baseline: 1/4 tests passed.', 2)
    emit('\nTask: trim IDs before deduplication; reject invalid records;\n      round decimal amounts half-up and keep totals consistent.', 4)
    emit('\nHermes / files + terminal / exact same prompt', .6)
    emit('  JIT OFF: first request had no capsule.', 1.4)
    emit('  JIT ON : first request carried the receipt-import capsule.', 3)
    emit('\033[2J\033[H\033[1;36mJIT CONTEXT  /  MEASURED RESULT\033[0m')
    emit(f'Hermes | {on["requested_model"]} | same fixture, same checks\n', .5)
    emit(f'{"Measurement":24} {"JIT OFF":>13} {"JIT ON":>13}', .5)
    for label, a, b in zip(('Model API calls', 'Reported tokens', 'Wall clock', 'Tests passed'),
                           summarize(off), summarize(on)):
        emit(f'{label:24} {a:>13} {b:>13}', 1)
    emit('\nN=1, multi-file task. Short single-file tasks get a small overhead.', 6)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=ROOT / 'cloud.json')
    parser.add_argument('--story', action='store_true')
    args = parser.parse_args()
    results = json.loads(args.results.read_text())
    if args.story:
        story(results)
        return
    compare(results)
    # Run from docs/demo with relative paths so the committed .cast header holds no local paths.
    results_arg = os.path.relpath(args.results.resolve(), ROOT.resolve())
    command = shlex.join(['python3', '-B', 'render.py', '--results', results_arg, '--story'])
    subprocess.run(['asciinema', 'rec', '--overwrite', '--headless', '--return', '--window-size', '76x21',
                    '-c', command, 'jit-demo.cast'], check=True, cwd=ROOT)
    subprocess.run(['agg', '--theme', 'github-dark', '--font-size', '18', '--idle-time-limit', '7',
                    'jit-demo.cast', 'jit-demo.gif'], check=True, cwd=ROOT)


if __name__ == '__main__':
    main()
