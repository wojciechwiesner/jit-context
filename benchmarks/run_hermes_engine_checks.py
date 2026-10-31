"""Run the Hermes engine integration tests inside Hermes' own runtime (no pytest needed).

Usage (uses the exact interpreter and packages production Hermes runs on):
  hermes --run-module benchmarks.run_hermes_engine_checks      # from the repo root
Exit code 0 only when every check passes.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "src" / "tests" / "test_hermes_engine_integration.py"


class _MonkeyPatch:
    """Minimal stand-in for pytest's monkeypatch fixture."""

    def __init__(self) -> None:
        self._env: list[tuple[str, str | None]] = []
        self._paths: list[str] = []

    def setenv(self, name: str, value: str) -> None:
        self._env.append((name, os.environ.get(name)))
        os.environ[name] = value

    def syspath_prepend(self, path: str) -> None:
        sys.path.insert(0, path)
        self._paths.append(path)

    def undo(self) -> None:
        for name, old in reversed(self._env):
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old
        for path in self._paths:
            if path in sys.path:
                sys.path.remove(path)


def _load_tests():
    sys.modules.setdefault("pytest", _fake_pytest())
    spec = importlib.util.spec_from_file_location("hermes_engine_integration", TESTS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_pytest():
    import types

    fake = types.ModuleType("pytest")
    fake.fixture = lambda *a, **k: (lambda fn: fn) if not a or not callable(a[0]) else a[0]
    fake.mark = types.SimpleNamespace(skipif=lambda *a, **k: None)
    return fake


def main() -> int:
    module = _load_tests()
    fixture = getattr(module, "engine_module")
    names = sorted(n for n in dir(module) if n.startswith("test_"))
    failures = 0
    for name in names:
        patcher = _MonkeyPatch()
        generator = fixture(patcher)
        engine_module = next(generator)
        test = getattr(module, name)
        try:
            kwargs = {"engine_module": engine_module}
            if "monkeypatch" in test.__code__.co_varnames[: test.__code__.co_argcount]:
                kwargs["monkeypatch"] = patcher
            test(**kwargs)
            print(f"PASS {name}")
        except Exception:
            failures += 1
            print(f"FAIL {name}")
            traceback.print_exc()
        finally:
            next(generator, None)
            patcher.undo()
    print(f"{len(names) - failures} passed, {failures} failed (python {sys.version.split()[0]})")
    return 1 if failures else 0


if __name__ == "__main__":
    os.environ.setdefault("TMPDIR", tempfile.gettempdir())
    sys.exit(main())
