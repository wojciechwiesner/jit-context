"""Run an isolated Hermes A/B (or local 2x2) and keep real measurements."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from fixture import PROMPT, materialize
from gateway import open_gateway

REPO = Path(__file__).resolve().parents[2]
USER_HOME = Path.home()
MODEL = 'google/gemini-3.5-flash-lite'
LOCAL_MODELS = ('qwen3.8:9b-64k', 'lfm2.5:2.6b-16k')
CLOUD_MODELS = (MODEL, 'google/gemini-2.5-flash', 'qwen/qwen3.8-27b')
PATTERN = re.compile(r'^test_\w+ \([^)]+\) \.\.\. (ok|FAIL|ERROR)$', re.M)


def check(root, env):
    run = subprocess.run(['python3', '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                         cwd=root, env=env, text=True, capture_output=True, timeout=20)
    results = PATTERN.findall(run.stderr + run.stdout)
    return {'total': len(results), 'passed': results.count('ok'), 'exit_code': run.returncode}


def lookup_key(*names):
    for name in names:
        if key := os.environ.get(name):
            return key
    path = USER_HOME / '.hermes' / '.env'
    if path.is_file():
        values = {}
        for line in path.read_text().splitlines():
            var, _, value = line.removeprefix('export ').partition('=')
            values[var.strip()] = value.strip().strip('"\'')
        for name in names:
            if values.get(name):
                return values[name]
    raise RuntimeError(f'Set {names[0]} or configure it in Hermes')


def install_fixture(root, home, env, tools):
    root.mkdir(parents=True)
    (home / 'plugins').mkdir(parents=True)
    (home / 'plugins' / 'ona-context').symlink_to(REPO / 'src', target_is_directory=True)
    (home / 'config.yaml').write_text('plugins:\n  enabled: [ona-context]\n'
                                    'terminal:\n  backend: local\n'
                                    'agent:\n  max_turns: 7\n'
                                    'model:\n  streaming: false\n'
                                    'security:\n  redact_secrets: true\n'
                                    'toolsets: []\n')
    materialize(root)
    subprocess.run(['git', 'init', '-q', str(root)], env=env, check=True)
    print('$ jit init .', flush=True)
    init = subprocess.run(['python3', '-m', 'init', 'init', '.'], cwd=root, env=env,
                          text=True, capture_output=True, timeout=30)
    if init.returncode or not (root / '.planning/STATE.md').is_file():
        raise RuntimeError('jit init failed: ' + init.stdout[-500:] + init.stderr[-400:])
    baseline = check(root, env)
    if baseline != {'total': 4, 'passed': 1, 'exit_code': 1}:
        raise RuntimeError(f'Unexpected baseline: {baseline}')
    # Both tool-enabled arms start with the same files; no-tools arms get a snapshot in the prompt.
    print('  created .planning/STATE.md | baseline tests: 1/4 passed', flush=True)
    return baseline


def apply_diff(text, root, env):
    block = re.search(r'```(?:diff|patch)\s*\n(.*?)```', text, re.S)
    diff = (block[1] if block else text).strip() + '\n'
    return subprocess.run(['git', 'apply', '--recount', '-'], cwd=root, env=env, input=diff,
                          capture_output=True, text=True, timeout=10).returncode == 0


def arm(work, model, active, tools, dry_run, offline, backend):
    tag = f'{"on" if active else "off"}-{"tools" if tools else "no-tools"}'
    home = work / 'home'
    root = work / 'receipt-import'
    settings = home / '.hermes'
    env = {k: v for k, v in os.environ.items()
           if k in {'PATH', 'LANG', 'LC_ALL', 'TERM', 'SYSTEMROOT', 'SSL_CERT_FILE'}}
    env.update(HOME=str(home), HERMES_HOME=str(settings), PYTHONPATH=str(REPO / 'src'),
               ONA_CONTEXT_MODE='active' if active else 'disabled', JIT_L2_ENABLED='0',
               JIT_LLM_BASE_URL='http://127.0.0.1:1/v1', JIT_TURN_AUDIT='0',
               BORG_TOOLS_LLM_TOKEN='', JIT_JEV_ENABLED='0', TERMINAL_CWD=str(root),
               PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(work))
    baseline = install_fixture(root, settings, env, tools)
    if dry_run:
        return {'arm': tag, 'baseline': baseline}
    if model in LOCAL_MODELS:
        provider, key = 'http://127.0.0.1:11434/v1', None
    elif backend == 'google':
        provider = 'https://generativelanguage.googleapis.com/v1beta/openai'
        key = None if offline else lookup_key('GOOGLE_API_KEY')
        model = model.removeprefix('google/')
    else:
        provider = 'https://openrouter.ai/api/v1'
        key = None if offline else lookup_key('JEV_OPENROUTER_KEY', 'OPENROUTER_API_KEY')
    calls = []
    server = open_gateway(provider, key, calls, 7 if tools else 1, tools,
                          root.name if active else None, offline=offline)
    agent_source = Path(os.environ.get('HERMES_AGENT_SRC', USER_HOME / '.hermes/hermes-agent')).resolve()
    host_python = os.environ.get('HERMES_AGENT_PYTHON', str(agent_source / '.venv/bin/python'))
    env.update(PYTHONPATH=str(agent_source), OPENAI_BASE_URL=f'http://127.0.0.1:{server.server_port}/v1',
               OPENAI_API_KEY='demo-proxy', HERMES_DISABLE_LAZY_INSTALLS='1')
    prompt = PROMPT
    if not tools:
        prompt = PROMPT.replace('and run the tests before reporting.', 'and return only a unified diff.')
        for source in sorted((root / 'receipt_import').glob('*.py')):
            if source.stat().st_size:
                prompt += f'\n--- {source.relative_to(root)} ---\n{source.read_text()}'
    bootstrap = ('import sys, runpy; sys._hermes_relaunched = True; '
                 'path = sys.argv.pop(1); runpy.run_path(path, run_name="__main__")')
    cmd = [host_python, '-B', '-c', bootstrap, str(Path(__file__).with_name('host.py')), model,
           'tools' if tools else 'no-tools']
    print(f'$ python3 docs/demo/host.py  # Hermes, JIT {"ON" if active else "OFF"}, '
          f'{"tools" if tools else "no tools"}', flush=True)
    started = time.monotonic()
    timed_out = False
    try:
        process = subprocess.run(cmd, cwd=root, env=env, text=True, input=json.dumps(prompt),
                                 capture_output=True, timeout=400 if model in LOCAL_MODELS else 220)
        stdout, stderr, host_exit = process.stdout, process.stderr, process.returncode
    except subprocess.TimeoutExpired as exc:
        # A timeout is a measured outcome for this arm, not a reason to drop the rest of the matrix.
        timed_out = True
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or '')
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or '')
        host_exit = None
    finally:
        server.shutdown()
        server.server_close()
    wall = round(time.monotonic() - started, 2)
    (work / 'hermes.jsonl').write_text(stdout)
    (work / 'hermes.stderr').write_text(stderr)
    events = []
    for line in stdout.splitlines():
        if line.startswith('{'):
            events.append(json.loads(line))
    final = next((event for event in reversed(events) if event.get('type') == 'result'), {})
    patch_applied = None if tools or offline else apply_diff(final.get('text', ''), root, env)
    # Restore original tests before independent verification; their edits cannot improve the score.
    from fixture import TESTS
    (root / 'tests/test_import_batch.py').write_text(TESTS)
    result = {'arm': tag, 'baseline': baseline, 'tests': check(root, env), 'wall_s': wall,
              'requested_model': model, 'host_exit': host_exit, 'timed_out': timed_out,
              'first_scope': calls[0]['capsule_scope'] if calls else None,
              'tools_seen': calls[0]['tool_count'] if calls else None, 'patch_applied': patch_applied,
              'calls': calls, 'engine': 'Hermes', 'offline': offline}
    print(json.dumps({k: result[k] for k in ('arm', 'wall_s', 'tests', 'first_scope', 'tools_seen')})
          + f' | provider calls={len(calls)}', flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=(*CLOUD_MODELS, *LOCAL_MODELS), default=MODEL)
    parser.add_argument('--backend', choices=('google', 'openrouter'), default='google')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--scratch', type=Path, default=Path(os.environ.get('TMPDIR', tempfile.gettempdir())))
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--offline', action='store_true', help='Check payload, never contact a model; not a result')
    parser.add_argument('--order', choices=('off-first', 'on-first'), default='off-first')
    args = parser.parse_args()
    if shutil.which('hermes') is None:
        parser.error('Hermes CLI is required')
    work = Path(tempfile.mkdtemp(prefix='jit-demo-', dir=args.scratch))
    print(f'Run traces: {work}', flush=True)
    modes = (True, False) if args.order == 'on-first' else (False, True)
    results = []
    for tools in ((True, False) if args.model in LOCAL_MODELS and not args.dry_run else (True,)):
        for active in modes:
            name = f'{"on" if active else "off"}-{int(tools)}'
            results.append(arm(work / name, args.model, active, tools, args.dry_run, args.offline, args.backend))
            args.output.write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    main()
