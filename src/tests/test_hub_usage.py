"""Usage collectors: fixture transcripts, a fixture Hermes state.db and a fixture overlay DB; reruns add nothing."""

import hashlib
import json
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from hub import usage
from hub.usage_claude import encode_path

DAY = "2026-11-02"
TS = f"{DAY}T12:00:00.000Z"
LOCAL_DAY = datetime.fromisoformat(TS.replace("Z", "+00:00")).astimezone().date().isoformat()
SESSION = "11111111-2222-3333-4444-555555555555"


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
                   cwd=cwd, check=True, capture_output=True, text=True)


def assistant(msg_id: str, req: str, inp: int, out: int, cread: int, cwrite: int, cwd: str) -> dict:
    usage_block = {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": cread,
                   "cache_creation_input_tokens": cwrite}
    return {"type": "assistant", "requestId": req, "timestamp": TS, "sessionId": SESSION, "cwd": cwd,
            "message": {"id": msg_id, "role": "assistant", "usage": usage_block, "content": []}}


def user(content: object, cwd: str, **extra: object) -> dict:
    return {"type": "user", "timestamp": TS, "sessionId": SESSION, "cwd": cwd,
            "message": {"role": "user", "content": content}, **extra}


def write_lines(path: Path, entries: list, mode: str = "w", tail: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, mode, encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, separators=(",", ":")) + "\n")
        handle.write(tail)


def make_hermes_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, started_at REAL, cwd TEXT, "
                 "input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, estimated_cost_usd REAL)")
    started = datetime.fromisoformat(f"{DAY}T12:00:00").timestamp()
    conn.executemany("INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
        ("h1", "cli", started, None, 100, 10, 1000, 0.5),
        ("h2", "telegram", started, None, 7, 3, 0, None),
    ])
    conn.commit()
    conn.close()


def make_overlay(root: Path, scope: str, session: str, rows: list) -> Path:
    path = root / scope / session / f"overlay_{session}.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS turn_telemetry (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 "session_id TEXT, turn_id TEXT, created_at TEXT, active_scope TEXT, "
                 "capsule_tokens_est INTEGER DEFAULT 0, hook_total_ms REAL DEFAULT 0)")
    conn.executemany("INSERT INTO turn_telemetry (session_id, turn_id, created_at, active_scope, "
                     "capsule_tokens_est, hook_total_ms) VALUES (?, ?, ?, ?, ?, ?)",
                     [(session, f"t{i}", TS.replace(".000", ""), scope, tok, ms) for i, (tok, ms) in enumerate(rows)])
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("JIT_HUB_DIR", str(tmp_path / "hub"))
    repo = tmp_path / "work" / "alpha"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    worktree = tmp_path / "work" / "alpha-wt"
    git(repo, "worktree", "add", "-q", "-b", "feat", str(worktree))
    sources = usage.UsageSources(tmp_path / "claude", tmp_path / "hermes" / "state.db", tmp_path / "sessions")
    (tmp_path / "hermes").mkdir()
    projects = [{"slug": "alpha", "path": str(repo.resolve())}]
    return {"tmp": tmp_path, "repo": repo.resolve(), "wt": worktree.resolve(), "sources": sources,
            "projects": projects, "db": tmp_path / "hub" / "usage.sqlite"}


def collect(env: dict) -> usage.CollectResult:
    return usage.collect_usage(env["sources"], db_path=env["db"], projects=env["projects"])


def rows_by(env: dict, source: str) -> dict:
    return {r["project"]: r for r in usage.daily_usage(db_path=env["db"]) if r["source"] == source}


def transcript(env: dict) -> Path:
    cwd = str(env["wt"])
    path = env["sources"].claude_projects / encode_path(cwd) / f"{SESSION}.jsonl"
    entries = [
        user("Add a usage collector", cwd),
        assistant("msg_1", "req_1", 3, 50, 1000, 200, cwd),
        assistant("msg_1", "req_1", 3, 50, 1000, 200, cwd),  # same response, second content block
        user([{"type": "tool_result", "content": "ok"}], cwd),
        user("<command-name>/clear</command-name>", cwd, isMeta=True),
        assistant("msg_2", "req_2", 5, 70, 1200, 0, cwd),
        {"type": "attachment", "timestamp": TS},
    ]
    write_lines(path, entries, tail='{"type":"assistant","partial')
    return path


def test_claude_transcript_dedup_turns_and_worktree_mapping(env):
    transcript(env)
    result = collect(env)
    assert result.errors == {}
    row = rows_by(env, "claude")["alpha"]
    assert row["day"] == LOCAL_DAY and row["registered"] == 1
    assert (row["input_tokens"], row["output_tokens"]) == (8, 120)
    assert (row["cache_read_tokens"], row["cache_write_tokens"]) == (2200, 200)
    assert (row["turns"], row["api_calls"], row["sessions"]) == (1, 2, 1)
    assert row["cost_usd"] is None and row["cost_sessions"] == 0


def test_second_run_adds_nothing_and_appends_are_incremental(env):
    path = transcript(env)
    make_hermes_db(env["sources"].hermes_db)
    make_overlay(env["sources"].jit_sessions, "alpha", SESSION, [(400, 12.5), (0, 3.0)])
    first = collect(env)
    snapshot = usage.daily_usage(db_path=env["db"])
    second = collect(env)
    assert sum(first.added.values()) > 0
    assert second.added == {"claude": 0, "hermes": 0, "jit": 0} and second.rollup_rows is None
    assert usage.daily_usage(db_path=env["db"]) == snapshot
    with open(path, "r+", encoding="utf-8") as handle:  # finish the partial line, then one more response
        content = handle.read().rsplit("\n", 1)[0] + "\n"
        handle.seek(0)
        handle.truncate()
        handle.write(content)
    cwd = str(env["wt"])
    write_lines(path, [assistant("msg_3", "req_3", 1, 1, 0, 0, cwd), user("next", cwd)], mode="a")
    third = collect(env)
    assert third.added["claude"] == 2
    row = rows_by(env, "claude")["alpha"]
    assert (row["input_tokens"], row["turns"], row["api_calls"]) == (9, 2, 3)


def test_rewritten_transcript_is_reread_without_double_counting(env):
    path = transcript(env)
    collect(env)
    cwd = str(env["wt"])
    write_lines(path, [assistant("msg_9", "req_9", 4, 4, 0, 0, cwd)])
    collect(env)
    row = rows_by(env, "claude")["alpha"]
    assert (row["input_tokens"], row["api_calls"], row["turns"]) == (4, 1, 0)


def test_dir_name_maps_back_to_registered_path_when_cwd_missing(env):
    path = env["sources"].claude_projects / encode_path(str(env["repo"])) / f"{SESSION}.jsonl"
    entry = assistant("m", "r", 2, 2, 0, 0, "")
    entry.pop("cwd")
    write_lines(path, [entry])
    collect(env)
    assert rows_by(env, "claude")["alpha"]["input_tokens"] == 2


def test_hermes_sessions_read_only_and_updates_replace(env):
    db = env["sources"].hermes_db
    make_hermes_db(db)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE sessions SET cwd=? WHERE id='h1'", (str(env["repo"] / "src"),))
    conn.commit()
    conn.close()
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    assert collect(env).added["hermes"] == 2
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    rows = rows_by(env, "hermes")
    assert (rows["alpha"]["input_tokens"], rows["alpha"]["cache_read_tokens"]) == (100, 1000)
    assert rows["alpha"]["cost_usd"] == 0.5 and rows["alpha"]["cache_write_tokens"] == 0
    assert rows[None]["registered"] == 0 and rows[None]["cost_usd"] is None
    conn = sqlite3.connect(db)
    conn.execute("UPDATE sessions SET input_tokens=150 WHERE id='h1'")
    conn.commit()
    conn.close()
    assert collect(env).added["hermes"] == 1
    assert rows_by(env, "hermes")["alpha"]["input_tokens"] == 150


def test_jit_overlay_rows_and_scope_mapping(env):
    root = env["sources"].jit_sessions
    path = make_overlay(root, "alpha", SESSION, [(400, 12.5), (0, 3.0)])
    make_overlay(root, "other-scope", "s2", [(100, 1.0)])
    assert collect(env).added["jit"] == 3
    rows = rows_by(env, "jit")
    assert (rows["alpha"]["turns"], rows["alpha"]["capsules"], rows["alpha"]["capsule_tokens"]) == (2, 1, 400)
    assert rows["alpha"]["hook_ms"] == pytest.approx(15.5) and rows["alpha"]["sessions"] == 1
    assert rows["other-scope"]["registered"] == 0
    make_overlay(root, "alpha", SESSION, [(50, 1.0)])
    assert collect(env).added["jit"] == 1
    assert rows_by(env, "jit")["alpha"]["capsule_tokens"] == 450
    assert path.exists()


def test_sources_fail_open(env):
    transcript(env)
    env["sources"].hermes_db.write_bytes(b"not a sqlite database at all" * 100)
    bad = env["sources"].jit_sessions / "alpha" / "s" / "overlay_s.db"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"garbage" * 100)
    result = collect(env)
    assert result.added["claude"] > 0
    assert "hermes" in result.errors and "jit" in result.errors
    assert rows_by(env, "claude")["alpha"]["api_calls"] == 2


def test_missing_sources_are_empty_not_errors(env):
    result = collect(env)
    assert result.errors == {} and result.added == {"claude": 0, "hermes": 0, "jit": 0}
    assert usage.daily_usage(db_path=env["db"]) == []


def test_registry_change_rebuilds_rollups(env):
    path = env["sources"].claude_projects / encode_path("/nowhere/beta") / f"{SESSION}.jsonl"
    write_lines(path, [assistant("m", "r", 1, 1, 0, 0, "/nowhere/beta")])
    collect(env)
    assert rows_by(env, "claude")["/nowhere/beta"]["registered"] == 0
    env["projects"].append({"slug": "beta", "path": "/nowhere/beta"})
    result = collect(env)
    assert result.rollup_rows == 1 and rows_by(env, "claude")["beta"]["registered"] == 1


def test_cli_usage_reports_totals(env, capsys, monkeypatch):
    import argparse

    from hub import cli

    monkeypatch.setattr(usage, "default_sources", lambda: env["sources"])
    monkeypatch.setattr(usage.registry, "load_projects", lambda: env["projects"])
    transcript(env)
    assert cli.main(argparse.Namespace(hub_action="usage", days=3650, json=False)) == 0
    out = capsys.readouterr().out
    assert "alpha" in out and "claude" in out and "brak" in out
