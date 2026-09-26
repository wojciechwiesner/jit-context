"""Verify the shipped wheel and CLI entrypoints outside the source checkout."""

import os
import re
import select
import shutil
import subprocess
import sys
import tarfile
import time
import tomllib
import urllib.request
import venv
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_wheel_entrypoints_and_assets(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name in ("pyproject.toml", "README.md"):
        shutil.copy2(ROOT / name, source / name)
    shutil.copytree(ROOT / "src", source / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    version = tomllib.loads((source / "pyproject.toml").read_text())["project"]["version"]
    assert f"version: {version}" in (source / "src/plugin.yaml").read_text().splitlines()

    wheels = tmp_path / "wheels"
    wheels.mkdir()
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "-w", str(wheels), str(source)],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    wheel = next(wheels.glob("jit_context-*.whl"))
    subprocess.run(
        [sys.executable, "-c", "import setuptools.build_meta as build; build.build_sdist('dist')"],
        cwd=source, check=True, capture_output=True, text=True, timeout=120,
    )
    with tarfile.open(next((source / "dist").glob("jit_context-*.tar.gz"))) as archive:
        files = archive.getnames()
        assert any(name.endswith("/src/plugin.yaml") for name in files)
        assert any(name.endswith("/src/health/dashboard.html") for name in files)

    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert "health/dashboard.html" in names
        assert "health/live_context.html" in names
        assert any(name.endswith("/share/jit-context/plugin.yaml") for name in names)
        entrypoints = archive.read(next(name for name in names if name.endswith("entry_points.txt"))).decode()
        assert "init:main" in entrypoints
        assert "health.doctor:main" in entrypoints
        assert "health.server:main" in entrypoints
        assert not any(name.startswith("tests/") for name in names)

    environment = tmp_path / "venv"
    venv.create(environment, with_pip=True, system_site_packages=True)
    bin_dir = environment / ("Scripts" if os.name == "nt" else "bin")
    subprocess.run(
        [str(bin_dir / "python"), "-m", "pip", "install", "--no-deps", "--no-index", str(wheel)],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.update({"HOME": str(home), "HERMES_HOME": str(home / ".hermes"), "JIT_HEALTH_HOST": "127.0.0.1", "JIT_HEALTH_PORT": "0"})
    module = subprocess.run(
        [str(bin_dir / "python"), "-c", "import health.server; print(health.server.__file__)"],
        cwd=home,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert str(environment) in module.stdout
    assert str(source) not in module.stdout
    cli = subprocess.run(
        [str(bin_dir / "jit"), "--help"], cwd=home, env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert cli.returncode == 0, cli.stderr
    assert "init" in cli.stdout

    process = subprocess.Popen(
        [str(bin_dir / "jit-observatory")], cwd=home, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        assert process.stdout is not None
        ready, _, _ = select.select([process.stdout], [], [], 20)
        assert ready, "Observatory did not announce its bound address"
        line = process.stdout.readline()
        match = re.search(r"127\.0\.0\.1:(\d+)", line)
        assert match, f"Observatory failed to start: {line}"
        port = int(match.group(1))
        assert port > 0
        for attempt in range(20):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                    assert response.status == 200
                    assert b'"invariants"' in response.read()
                break
            except OSError:
                if attempt == 19:
                    raise
                time.sleep(0.05)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/live", timeout=2) as response:
            assert response.status == 200
            assert response.read() == (ROOT / "src/health/live_context.html").read_bytes()

        # The package alone is not a Hermes plugin installation; doctor must fail honestly.
        doctor = subprocess.run(
            [str(bin_dir / "jit-doctor")], cwd=home,
            env={**env, "JIT_HEALTH_PORT": str(port)},
            capture_output=True, text=True, timeout=30,
        )
        assert doctor.returncode == 1, doctor.stdout + doctor.stderr
        assert re.search(r"Plugin Config\s+FAIL", doctor.stdout)
        assert "READY FOR ACTIVE" not in doctor.stdout
        assert "BLOCKED" in doctor.stdout
    finally:
        process.terminate()
        process.wait(timeout=10)
