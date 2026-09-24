"""The Agent Zero adapter is installable without the monorepo's Python core."""
from pathlib import Path
import subprocess
import sys


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def test_self_contained_plugin_layout():
    manifest = (PLUGIN_ROOT / "plugin.yaml").read_text(encoding="utf-8")
    assert "name: jit_context" in manifest
    assert "version: 0.4.0" in manifest
    for path in (
        "LICENSE", "execute.py", "default_config.yaml", "helpers/runtime.py",
        "jev_bridge/_runtime.py", "extensions/python/agent_init/_10_jev_init.py",
        "api/jit_status.py", "webui/config.html",
    ):
        assert (PLUGIN_ROOT / path).is_file(), path


def test_nested_runtime_resolves_without_core_on_pythonpath():
    script = (
        "from jev_bridge._runtime import load_runtime_getter; "
        "getter = load_runtime_getter(); "
        "assert getter is not None; "
        "assert hasattr(getter(), 'compile_capsule')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=PLUGIN_ROOT,
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
