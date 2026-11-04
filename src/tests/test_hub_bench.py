"""`jit bench ab` orchestration with a fake `claude` on PATH: no model call, tmp HOME and hub dir."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hub import bench, bench_cli, bench_store, bench_tasks, registry

SRC_DIR = Path(__file__).resolve().parent.parent
OPEN_TASKS = ["Add export endpoint", "Fix login timeout", "Write migration guide"]
TOKENS_ON = {"input_tokens": 600, "output_tokens": 50, "cache_read_input_tokens": 1000,
             "cache_creation_input_tokens": 100}
TOKENS_OFF = {"input_tokens": 1000, "output_tokens": 70, "cache_read_input_tokens": 1500,
              "cache_creation_input_tokens": 200}
FAKE_CLAUDE = r'''#!{python}
import json, os, sys
log = os.environ["FAKE_CLAUDE_LOG"]
off = os.environ.get("JIT_CLAUDE_HOOK") == "0"
with open(log, "a") as fh:
    fh.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd(), "git_file": os.path.isfile(".git"),
        "env": {{k: os.environ.get(k) for k in ("JIT_CLAUDE_HOOK", "JIT_SPILL_HOOK", "JIT_COMPACT_HOOK")}}}}) + "\n")
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
if mode == "crash":
    sys.stderr.write("fake failure\n")
    sys.exit(3)
if mode == "error_json":
    print(json.dumps({{"type": "result", "subtype": "error_max_turns", "is_error": True, "num_turns": 9}}))
    sys.exit(0)
usage = {off_usage} if off else {on_usage}
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "num_turns": 4 if off else 3,
    "result": "answer text", "session_id": "s-1", "total_cost_usd": 0.02 if off else 0.01,
    "duration_api_ms": 1200, "usage": usage}}))
'''


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   check=True, capture_output=True)


def make_repo(root: Path, tasks=OPEN_TASKS, readme="# Alpha Service\n\nQuickstart.\n") -> Path:
    repo = root / "alpha"
    (repo / ".planning").mkdir(parents=True)
    lines = ["# STATE", "- [x] Done already"] + [f"- [ ] {task}" for task in tasks]
    (repo / ".planning" / "STATE.md").write_text("\n".join(lines) + "\n")
    if readme is not None:
        (repo / "README.md").write_text(readme)
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    return repo


@pytest.fixture
def env(tmp_path, monkeypatch):
    home, hub, bin_dir = tmp_path / "home", tmp_path / "hub", tmp_path / "bin"
    for path in (home, hub, bin_dir):
        path.mkdir()
    fake = bin_dir / "claude"
    fake.write_text(FAKE_CLAUDE.format(python=sys.executable, on_usage=TOKENS_ON, off_usage=TOKENS_OFF))
    fake.chmod(0o755)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("JIT_HUB_DIR", str(hub))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("JIT_CLAUDE_HOOK", "1")  # an inherited switch must not leak into the "on" arm
    return {"root": tmp_path / "projects", "log": log, "hub": hub}


def calls(log: Path):
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def run_cli(*argv) -> int:
    parser = argparse.ArgumentParser()
    bench_cli.add_arguments(parser)
    return bench_cli.main(parser.parse_args(list(argv)))


def test_default_tasks_from_state_and_readme(tmp_path):
    repo = make_repo(tmp_path)
    tasks = bench_tasks.default_tasks(repo)
    assert [t.task_id for t in tasks] == ["state-1", "state-2", "readme"]
    assert "Add export endpoint" in tasks[0].prompt and "Fix login timeout" in tasks[1].prompt
    assert "Alpha Service" in tasks[2].prompt
    assert all(bench_tasks.READ_ONLY_RULE in t.prompt for t in tasks)


def test_default_tasks_without_readme_and_without_sources(tmp_path):
    repo = make_repo(tmp_path / "a", readme=None)
    assert [t.task_id for t in bench_tasks.default_tasks(repo)] == ["state-1", "state-2", "state-3"]
    empty = make_repo(tmp_path / "b", tasks=[], readme=None)
    assert bench_tasks.default_tasks(empty) == []


def test_task_file_formats(tmp_path):
    as_json = tmp_path / "t.json"
    as_json.write_text(json.dumps(["first", {"id": "q2", "prompt": "second"}]))
    assert [(t.task_id, t.prompt) for t in bench_tasks.load_task_file(as_json)] == [
        ("task-1", "first"), ("q2", "second")]
    as_text = tmp_path / "t.txt"
    as_text.write_text("# comment\nalpha\n\nbeta\n")
    assert [t.prompt for t in bench_tasks.load_task_file(as_text)] == ["alpha", "beta"]
    bad = tmp_path / "bad.json"
    bad.write_text('{"prompt": "x"}')
    with pytest.raises(bench_tasks.TaskFileError):
        bench_tasks.load_task_file(bad)


def test_arm_env_switches():
    base = {"PATH": "/bin", "JIT_CLAUDE_HOOK": "0", "JIT_SPILL_HOOK": "1"}
    on = bench.arm_env("on", base)
    assert on == {"PATH": "/bin"}
    off = bench.arm_env("off", base)
    assert all(off[key] == "0" for key in bench.JIT_OFF_ENV) and off["PATH"] == "/bin"


def test_refuses_without_yes_and_prints_estimate(env, capsys):
    repo = make_repo(env["root"])
    assert run_cli("ab", str(repo)) == bench_cli.EXIT_USAGE
    out = capsys.readouterr().out
    assert "Szacowana liczba wywołań modelu: 18" in out and "--yes" in out
    assert calls(env["log"]) == []
    assert not (env["hub"] / bench_store.usage_store.USAGE_DB_NAME).exists()


def test_full_batch_with_fake_claude(env, capsys):
    repo = make_repo(env["root"])
    registry.register_project(repo)
    tasks_file = env["root"] / "tasks.txt"
    tasks_file.write_text("What does module X do?\nWhere is the config loaded?\n")
    assert run_cli("ab", "alpha", "--tasks", str(tasks_file), "--runs", "2", "--model", "haiku", "--yes") == 0
    logged = calls(env["log"])
    assert len(logged) == 8
    for call in logged:
        argv = call["argv"]
        assert argv[argv.index("--output-format") + 1] == "json"
        assert argv[argv.index("--model") + 1] == "haiku"
        assert argv[argv.index("--tools") + 1] == bench.READ_ONLY_TOOLS
        assert call["git_file"] and Path(call["cwd"]).resolve() != repo.resolve()
        assert bench.WORK_DIR_INFIX in call["cwd"]
    arms = ["off" if c["env"]["JIT_CLAUDE_HOOK"] == "0" else "on" for c in logged]
    assert arms == ["on", "off", "on", "off", "off", "on", "off", "on"]
    assert all(all(value is None for value in c["env"].values()) for c, arm in zip(logged, arms) if arm == "on")
    worktrees = subprocess.run(["git", "-C", str(repo), "worktree", "list"], capture_output=True, text=True).stdout
    assert len(worktrees.strip().splitlines()) == 1
    assert not [p for p in env["root"].iterdir() if bench.WORK_DIR_INFIX in p.name]

    conn = bench_store.connect()
    rows = [dict(r) for r in conn.execute("SELECT * FROM ab_runs ORDER BY id")]
    conn.close()
    assert len(rows) == 8 and {r["project"] for r in rows} == {"alpha"}
    on_row = next(r for r in rows if r["arm"] == "on")
    assert (on_row["input_tokens"], on_row["cache_read_tokens"], on_row["cache_write_tokens"]) == (600, 1000, 100)
    assert on_row["num_turns"] == 3 and on_row["is_error"] == 0 and on_row["wall_s"] >= 0
    summary = bench_store.summarize(rows)
    assert summary["arms"]["on"]["total_tokens"] == {"median": 1750, "n": 4}
    assert summary["paired_on_minus_off"]["total_tokens"] == {"median": 1750 - 2770, "n": 4}
    out = capsys.readouterr().out
    assert "ab_runs" in out and "różnica w parach" in out


def test_failed_calls_are_errors_with_missing_usage(env, monkeypatch, capsys):
    repo = make_repo(env["root"])
    tasks_file = env["root"] / "tasks.txt"
    tasks_file.write_text("one question\n")
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "crash")
    assert run_cli("ab", str(repo), "--tasks", str(tasks_file), "--runs", "1", "--yes") == bench_cli.EXIT_FAILED
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "error_json")
    assert run_cli("ab", str(repo), "--tasks", str(tasks_file), "--runs", "1", "--yes") == bench_cli.EXIT_FAILED
    conn = bench_store.connect()
    rows = [dict(r) for r in conn.execute("SELECT * FROM ab_runs ORDER BY id")]
    conn.close()
    assert len(rows) == 4 and all(r["is_error"] == 1 for r in rows)
    assert all(r["input_tokens"] is None and bench_store.total_tokens(r) is None for r in rows)
    assert rows[0]["exit_code"] == 3 and "fake failure" in rows[0]["error"]
    assert rows[2]["error"] == "error_max_turns" and rows[2]["num_turns"] == 9
    summary = bench_store.summarize(rows)
    assert summary["arms"]["on"]["total_tokens"] == {"median": None, "n": 0}
    assert "brak (n=0)" in capsys.readouterr().out


def test_unknown_project_and_empty_default_tasks(env, capsys):
    assert run_cli("ab", "no-such-project", "--yes") == bench_cli.EXIT_USAGE
    empty = make_repo(env["root"], tasks=[], readme=None)
    assert run_cli("ab", str(empty), "--yes") == bench_cli.EXIT_USAGE
    assert "podaj --tasks" in capsys.readouterr().out
    assert calls(env["log"]) == []


def test_jit_cli_entrypoint_refuses_without_yes(env):
    repo = make_repo(env["root"])
    proc = subprocess.run([sys.executable, str(SRC_DIR / "init.py"), "bench", "ab", str(repo), "--runs", "1"],
                          capture_output=True, text=True, env=dict(os.environ), timeout=60)
    assert proc.returncode == bench_cli.EXIT_USAGE, proc.stderr
    assert "Szacowana liczba wywołań modelu: 6" in proc.stdout
    assert calls(env["log"]) == []
