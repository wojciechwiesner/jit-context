"""Stack detection and verify command must follow manifests, not stray helper scripts."""

import json
from pathlib import Path

import init as init_mod
from context.stack_signals import detect_package_manager, infer_verify_command


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _synthapse_like(root: Path) -> Path:
    pkg = {
        "scripts": {"test": "vitest run", "build": "vite build"},
        "dependencies": {"@google/genai": "^1.0.0"},
        "devDependencies": {"typescript": "~5.8", "vite": "^6", "vitest": "^4"},
    }
    _write(root / "package.json", json.dumps(pkg))
    _write(root / "pnpm-lock.yaml")
    _write(root / "package-lock.json", "{}")
    _write(root / "audio.ts", "export const a = 1")
    _write(root / "src" / "main.ts", "export const b = 2")
    _write(root / "tests" / "audio.test.ts", "test('x', () => {})")
    _write(root / "scripts" / "gen.py", "print('helper')")
    _write(root / "scripts" / "probe.py", "print('helper')")
    return root


def _scan(root: Path):
    scanner = init_mod.ProjectScanner(root)
    stack = scanner.detect_stack()
    return stack, scanner.infer_required_external_knowledge(stack)


def test_node_repo_with_helper_python(tmp_path):
    root = _synthapse_like(tmp_path)
    stack, resources = _scan(root)
    assert stack["languages"] == ["TypeScript"]
    assert stack["helper_languages"] == ["Python"]
    assert {"Vite", "Vitest"} <= set(stack["frameworks"] + stack["test_runners"])
    assert stack["package_manager"] == "pnpm"
    assert stack["test_command"] == "pnpm run test"
    assert len(resources) >= 2
    assert infer_verify_command(root) == "pnpm run test"


def test_lockfile_priority(tmp_path):
    assert detect_package_manager(tmp_path) is None
    _write(tmp_path / "package-lock.json")
    assert detect_package_manager(tmp_path) == "npm"
    _write(tmp_path / "bun.lock")
    assert detect_package_manager(tmp_path) == "bun"
    _write(tmp_path / "yarn.lock")
    assert detect_package_manager(tmp_path) == "yarn"
    _write(tmp_path / "pnpm-lock.yaml")
    assert detect_package_manager(tmp_path) == "pnpm"


def test_plain_python_repo_keeps_python_and_pytest(tmp_path):
    _write(tmp_path / "pyproject.toml", "[tool.pytest.ini_options]\n")
    _write(tmp_path / "app" / "main.py", "from fastapi import FastAPI\n")
    _write(tmp_path / "tests" / "test_x.py", "def test_x(): pass")
    stack, resources = _scan(tmp_path)
    assert stack["languages"] == ["Python"]
    assert stack["helper_languages"] == []
    assert "pytest" in stack["test_runners"] and "FastAPI" in stack["frameworks"]
    assert {"fastapi", "pytest"} <= {r["target"] for r in resources}
    assert infer_verify_command(tmp_path) == "pytest"


def test_python_without_manifest_but_real_sources(tmp_path):
    for name in ("a", "b", "c"):
        _write(tmp_path / "pkg" / f"{name}.py", "x = 1")
    stack, _ = _scan(tmp_path)
    assert stack["languages"] == ["Python"]


def test_mixed_repo_reports_both_languages(tmp_path):
    _write(tmp_path / "pyproject.toml", "[project]\nname='x'\n")
    _write(tmp_path / "api" / "main.py", "x = 1")
    _write(tmp_path / "package.json", json.dumps({"devDependencies": {"typescript": "5"}}))
    stack, _ = _scan(tmp_path)
    assert stack["languages"] == ["Python", "TypeScript"]


def test_verify_command_ordering(tmp_path):
    _write(tmp_path / "tests" / "a.test.js")
    _write(tmp_path / "package.json", json.dumps({"scripts": {"test": "jest"}}))
    assert infer_verify_command(tmp_path) == "npm run test"
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    assert infer_verify_command(tmp_path) is None  # bare tests/ must not imply pytest
    (tmp_path / "package.json").unlink()
    assert infer_verify_command(tmp_path) == "pytest"
    _write(tmp_path / "Cargo.toml")
    assert infer_verify_command(tmp_path) == "cargo test"


def test_capsule_verify_command_for_node_repo(tmp_path):
    from l0.db import init_db, get_db
    from l0.overlay import ensure_session
    from context.compiler import compile_context

    root = _synthapse_like(tmp_path / "repo")
    db_file = tmp_path / "overlay.db"
    init_db(db_file)
    conn = get_db(db_file)
    try:
        ensure_session(conn, "node-session")
        text = str(compile_context(conn, "node-session", "Fix the audio bug", session_cwd=str(root)))
    finally:
        conn.close()
    assert "Verify Command: pnpm run test" in text
    assert "Verify Command: pytest" not in text
