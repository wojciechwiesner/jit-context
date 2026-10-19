"""CLI guards: unknown words are not paths, and the init tier is recorded per project."""

import json
import subprocess
import sys
from pathlib import Path

import init as init_mod

INIT_PY = Path(init_mod.__file__).resolve()


def run_cli(*argv, cwd):
    return subprocess.run([sys.executable, str(INIT_PY), *argv], cwd=cwd, capture_output=True, text=True, timeout=60)


def test_unknown_command_is_rejected_without_traceback(tmp_path):
    res = run_cli("sync", cwd=tmp_path)
    assert res.returncode == 2
    assert "Traceback" not in res.stderr
    assert "sync" in res.stderr
    assert "jit init" in res.stderr
    assert not (tmp_path / ".planning").exists()


def test_missing_init_path_is_rejected_without_traceback(tmp_path):
    res = run_cli("init", str(tmp_path / "nope"), cwd=tmp_path)
    assert res.returncode == 2
    assert "Traceback" not in res.stderr
    assert "nope" in res.stderr


def test_record_tier_merges_into_project_profile(tmp_path):
    planning = tmp_path / ".planning"
    planning.mkdir()
    (planning / "jit.json").write_text(json.dumps({"skills": {"must": ["a"]}}), encoding="utf-8")
    init_mod.record_project_tier(tmp_path, "deep")
    data = json.loads((planning / "jit.json").read_text(encoding="utf-8"))
    assert data["tier"] == "deep"
    assert data["skills"] == {"must": ["a"]}
    assert init_mod.project_tier(tmp_path) == "deep"
    assert init_mod.project_tier(tmp_path / "sub") is None or init_mod.project_tier(tmp_path / "sub") == "deep"


def test_project_tier_found_from_subdirectory(tmp_path):
    init_mod.record_project_tier(tmp_path, "xhigh")
    sub = tmp_path / "src" / "deep"
    sub.mkdir(parents=True)
    assert init_mod.project_tier(sub) == "xhigh"


def test_project_tier_tolerates_broken_profile(tmp_path):
    planning = tmp_path / ".planning"
    planning.mkdir()
    (planning / "jit.json").write_text("{not json", encoding="utf-8")
    assert init_mod.project_tier(tmp_path) is None
    init_mod.record_project_tier(tmp_path, "deep")
    assert init_mod.project_tier(tmp_path) == "deep"
