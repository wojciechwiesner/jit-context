"""Record the optional Project Hub walkthrough in an isolated state directory."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request

REPO = Path(__file__).resolve().parents[2]
ROOT = Path(__file__).parent


def emit(text, pause=0.0):
    print(text, flush=True)
    if pause:
        time.sleep(pause)


def run_step(label, argv, env, home):
    emit(f'$ {label}', .35)
    process = subprocess.run(argv, cwd=REPO, env=env, text=True,
                             capture_output=True, timeout=60, check=True)
    # The isolated HOME is a temp dir; show it as "~" so the frame stays readable.
    shown = process.stdout
    for prefix in (str(home.resolve()), str(home)):
        shown = shown.replace(prefix, '~')
    lines = [line for line in shown.splitlines() if line.strip()][:8]
    emit('\n'.join('  ' + line[:88] for line in lines), 2.3)


def story():
    scratch = Path(tempfile.mkdtemp(prefix='jit-hub-', dir=os.environ.get('TMPDIR')))
    projects = scratch / 'Projects' / 'active'
    for name, files in (('receipt-import', ('receipt_import/service.py', 'tests/test_import_batch.py')),
                        ('invoice-router', ('router/dispatch.py', 'tests/test_dispatch.py')),
                        ('observatory-lite', ('observatory/server.py', 'README.md'))):
        project = projects / name
        for rel in files:
            target = project / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('# sample project\n')
        (project / '.planning').mkdir(exist_ok=True)
        (project / '.planning/STATE.md').write_text(f'# {name}\n\n## Active Goal\nKeep tests passing.\n')
        subprocess.run(['git', 'init', '-q', str(project)], check=True)
    env = {**os.environ, 'PYTHONPATH': str(REPO / 'src'), 'JIT_STATE_DIR': str(scratch / 'state'),
           'JIT_HUB_DIR': str(scratch / 'hub'), 'HOME': str(scratch),
           'JIT_LLM_BASE_URL': 'http://127.0.0.1:1/v1', 'BORG_TOOLS_LLM_TOKEN': ''}
    emit('\033[2J\033[H\033[1;36mJIT CONTEXT  /  PROJECT HUB\033[0m', .8)
    for label, tail in (('jit hub scan ~/Projects/active', ('scan', str(projects))),
                        ('jit hub list', ('list',)),
                        ('jit hub refresh --once', ('refresh', '--once'))):
        run_step(label, ['python3', '-m', 'init', 'hub', *tail], env, scratch)
    server = subprocess.Popen(['python3', '-m', 'health.livestream', '--port', '8769'],
                              cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        emit('$ python3 -m health.livestream --port 8767  # isolated probe on :8769', .5)
        for _ in range(25):
            try:
                page = urllib.request.urlopen('http://127.0.0.1:8769/hub', timeout=1).read().decode()
                break
            except OSError:
                time.sleep(.2)
        else:
            raise RuntimeError('Hub server did not respond')
        emit(f'  GET /hub -> HTTP 200 ({len(page)} bytes) | Mission Control ready', 4)
    finally:
        server.terminate()
        server.wait(timeout=5)
        shutil.rmtree(scratch, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--story', action='store_true')
    args = parser.parse_args()
    if args.story:
        story()
        return
    # Relative command from docs/demo keeps local paths out of the committed .cast header.
    subprocess.run(['asciinema', 'rec', '--overwrite', '--headless', '--return', '--window-size', '82x20',
                    '-c', 'python3 -B hub_demo.py --story', 'jit-hub.cast'], check=True, cwd=ROOT)
    subprocess.run(['agg', '--theme', 'github-dark', '--font-size', '18', '--idle-time-limit', '5',
                    'jit-hub.cast', 'jit-hub.gif'], check=True, cwd=ROOT)


if __name__ == '__main__':
    main()
